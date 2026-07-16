"""基于阿基米德 Excel，通过 CodeHub API 补充字段和代码上下文，输出 enriched Excel / JSONL。

数据口径：
- 阿基米德 Excel = 评论列表来源（comment 固定取自 Excel 检视意见）
- CodeHub /reviews = 评论详情补充来源（file_path / line / severity）
- CodeHub /changes = diff 和代码上下文来源
- note_hash（#note_xxx）→ 匹配 CodeHub discussion_id
- 正式输出只保留 context_status = matched 的记录

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/distill/enrich_reviews.py \
        --input <SKILL_ROOT>/outputs/raw_archimedes/z00000001_2024-07-01_2026-01-01_archimedes.xlsx \
        --reviewer-w3 z00000001
"""
import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # code-review/scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.paths import ENRICHED_DIR, ensure_dirs  # noqa: E402
from common.codehub_url import (  # noqa: E402
    REGIONS, normalize_codehub_domain, parse_review_url,
)
from common.diff_parser import parse_diff_to_lines  # noqa: E402
from common.context_builder import build_context  # noqa: E402
from common.filters import is_noise_comment  # noqa: E402
from common.jsonl_io import write_jsonl  # noqa: E402

MAX_WORKERS = 5

# 测试代码识别（与旧 SKILL.md Step 3 排除规则一致）
_TEST_FILE_RE = re.compile(
    r'(testcode/|_test\.cpp$|_llt\.cpp$|LLT_.*\.cpp$|test_.*\.py$|_test\.py$'
    r'|Test\.java$|Tests\.java$|_test\.go$|_test\.rs$)', re.IGNORECASE)

_EXT_LANG = {
    '.cpp': 'C++', '.cc': 'C++', '.cxx': 'C++', '.h': 'C++', '.hpp': 'C++',
    '.c': 'C', '.py': 'Python', '.go': 'Go', '.java': 'Java',
    '.rs': 'Rust', '.sh': 'Shell', '.tf': 'Terraform',
    '.yml': 'YAML', '.yaml': 'YAML',
}


def extract_project_and_mr(link):
    try:
        parsed = parse_review_url(link)
        return parsed['project_path'], parsed['mr_iid']
    except ValueError:
        return None, None


def extract_note_hash(link):
    try:
        return parse_review_url(link)['note_hash']
    except ValueError:
        return None


def detect_test_file(file_path: str) -> bool:
    return bool(file_path) and bool(_TEST_FILE_RE.search(file_path))


def detect_language(file_path: str) -> str:
    if not file_path:
        return ''
    ext = Path(file_path).suffix.lower()
    return _EXT_LANG.get(ext, '')


def _derive_start_end(input_path: str, start: str, end: str):
    """若未显式传 start/end，从输入文件名 {..}_{start}_{end}_archimedes.xlsx 解析。"""
    if start and end:
        return start, end
    m = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_archimedes\.xlsx$',
                  str(input_path))
    if m:
        return m.group(1), m.group(2)
    return start or 'unknown', end or 'unknown'


def _parse_link_info(indexed_links, requested_domain: str = ''):
    """纯本地解析检视地址，返回 (按行身份, domain 列表, 错误列表)。"""
    wanted = normalize_codehub_domain(requested_domain) if requested_domain else ''
    link_info, errors = {}, []
    for index, addr in indexed_links:
        try:
            link_info[index] = parse_review_url(addr, expected_domain=wanted)
        except ValueError as error:
            errors.append((index, str(error)))
    domains = sorted({item['domain'] for item in link_info.values()})
    return link_info, domains, errors


def enrich(input_xlsx: str, reviewer_w3: str, domain: str = '',
           start: str = '', end: str = '', token: str = None) -> dict:
    from common.codehub_client import CodeHubClient
    from common.excel_io import read_archimedes_excel, write_enriched_excel

    ensure_dirs()
    start, end = _derive_start_end(input_xlsx, start, end)

    print('\n===== 读取阿基米德 Excel =====')
    df = read_archimedes_excel(input_xlsx)
    total_rows = len(df)
    excel_w3 = df['检视人W3'].dropna().iloc[0] if '检视人W3' in df.columns else ''
    reviewer_name = df['检视人姓名'].dropna().iloc[0] if '检视人姓名' in df.columns else ''
    if not reviewer_w3:
        reviewer_w3 = excel_w3
    print(f'检视人：{reviewer_name}（{reviewer_w3}），原始 {total_rows} 条')

    # 过滤：类型=MR 且 MR状态=merged，且非噪声
    before = len(df)
    if '类型' in df.columns:
        df = df[df['类型'] == 'MR']
    if 'MR状态' in df.columns:
        df = df[df['MR状态'] == 'merged']
    status_filtered = before - len(df)
    before_noise = len(df)
    if '检视意见' in df.columns:
        df = df[~df['检视意见'].apply(is_noise_comment)]
    noise_filtered = before_noise - len(df)
    print(f'过滤：移除非MR/非merged {status_filtered} 条，移除噪声 {noise_filtered} 条，剩余 {len(df)} 条')

    if '检视地址' not in df.columns:
        raise RuntimeError('阿基米德 Excel 缺少「检视地址」列，无法推导 CodeHub domain')
    link_info, domains, link_errors = _parse_link_info(
        df['检视地址'].items(), requested_domain=domain)
    if link_errors:
        preview = '\n'.join(
            f'  - Excel 行 {index + 2}: {error}' for index, error in link_errors[:5])
        more = f'\n  ... 另有 {len(link_errors)-5} 条' if len(link_errors) > 5 else ''
        raise RuntimeError(
            f'{len(link_errors)} 条检视地址无法可靠解析：\n{preview}{more}')
    if not domains:
        raise RuntimeError('过滤后没有可用于 enrich 的 CodeHub MR 检视地址')
    print('检测到 CodeHub domain：' + ', '.join(domains))

    # 每个 CodeHub 实例的数字 user_id 可能不同，必须分别获取。
    print('\n===== 获取检视人数字用户 ID =====')
    clients, user_ids = {}, {}
    for detected_domain in domains:
        client = CodeHubClient(domain=detected_domain, token=token)
        user_id, _ = client.get_user_id(reviewer_w3)
        if not user_id:
            raise RuntimeError(
                f'无法在 {detected_domain} 获取用户ID（{reviewer_w3}），终止')
        clients[detected_domain] = client
        user_ids[detected_domain] = user_id

    # 完整身份必须包含 domain，避免不同地域同项目/MR 冲突。
    project_set = {
        (item['domain'], item['project_path']) for item in link_info.values()
    }
    mr_set = {
        (item['domain'], item['project_path'], item['mr_iid'])
        for item in link_info.values()
    }
    print(f'共 {len(project_set)} 个地域项目，{len(mr_set)} 个唯一 MR')

    # 并发获取 reviews → reviews_map[did] = review；记录失败项目
    print(f'\n===== 逐项目获取评审意见（{len(project_set)} 个）=====')
    reviews_map = {}
    failed_projects = set()
    sorted_projects = sorted(project_set)
    done = 0

    def fetch_reviews(item):
        detected_domain, pp = item
        try:
            reviews = clients[detected_domain].get_reviews_for_project(
                pp, user_ids[detected_domain])
            return detected_domain, pp, reviews, None
        except Exception as e:  # noqa: BLE001
            return detected_domain, pp, [], str(e)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_reviews, item): item for item in sorted_projects}
        for fut in as_completed(futs):
            detected_domain, pp = futs[fut]
            try:
                detected_domain, pp, reviews, err = fut.result()
            except Exception as e:  # noqa: BLE001
                detected_domain, pp = futs[fut]
                reviews, err = [], str(e)
            if err:
                failed_projects.add((detected_domain, pp))
            for r in reviews:
                did = r.get('discussion_id', '')
                if did:
                    reviews_map[(detected_domain, did)] = r
            done += 1
            print(f'  [{done}/{len(sorted_projects)}] [{detected_domain}] '
                  f'{pp} - {len(reviews)} 条'
                  + (f' (失败: {err})' if err else ''))
    print(f'reviews_map 共 {len(reviews_map)} 条（去重 by domain + discussion_id）')

    # 并发获取 MR diff → mr_diff_cache；记录失败 MR
    print('\n===== 构建 MR diff 缓存 =====')
    mr_diff_cache = {}
    failed_mrs = set()
    sorted_mrs = sorted(mr_set)
    done = 0

    def fetch_diff(item):
        detected_domain, pp, mi = item
        try:
            return (detected_domain, pp, mi,
                    clients[detected_domain].get_mr_diff(pp, mi), None)
        except Exception as e:  # noqa: BLE001
            return detected_domain, pp, mi, {}, str(e)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_diff, item): item for item in sorted_mrs}
        for fut in as_completed(futs):
            detected_domain, pp, mi = futs[fut]
            try:
                _, _, _, diff_map, err = fut.result()
            except Exception as e:  # noqa: BLE001
                diff_map, err = {}, str(e)
            cache_key = (detected_domain, pp, mi)
            if err:
                failed_mrs.add(cache_key)
            mr_diff_cache[cache_key] = diff_map
            done += 1
            print(f'  [{done}/{len(sorted_mrs)}] [{detected_domain}] '
                  f'{pp} !{mi} - {len(diff_map)} 文件'
                  + (f' (失败: {err})' if err else ''))
    print(f'mr_diff_cache 共 {len(mr_diff_cache)} 个 MR')

    # 逐行匹配 + 构建上下文
    print('\n===== 构建代码上下文 =====')
    results = []
    for index, row in df.iterrows():
        addr = row.get('检视地址', '')
        parsed = link_info[index]
        row_domain = parsed['domain']
        project_path = parsed['project_path']
        mr_iid = parsed['mr_iid']
        note_hash = parsed['note_hash']

        if not note_hash or not project_path or not mr_iid:
            api_status, ctx_status, error_detail = 'invalid_link', 'no_review', '无法从检视地址提取 project/mr/note_hash'
            review = None
        elif (row_domain, project_path) in failed_projects:
            api_status, ctx_status, error_detail = (
                'api_error', 'no_review',
                f'reviews 接口请求失败: {row_domain}/{project_path}')
            review = None
        else:
            review = reviews_map.get((row_domain, note_hash))
            if review:
                api_status = 'matched_review'
                error_detail = ''
            else:
                api_status, error_detail = 'review_not_found', f'note_hash 未在 CodeHub reviews 中匹配: {note_hash}'

        # 字段来源 fallback
        comment = row.get('检视意见', '')
        if review:
            file_path = review.get('file_path', '') or ''
            line = review.get('line', '')
            severity = review.get('severity_cn', '') or ''
            created_at = review.get('created_at') or row.get('创建时间', '') or ''
        else:
            file_path, line, severity = '', '', ''
            created_at = row.get('创建时间', '') or ''
        resolved_at = row.get('解决时间', '') or ''

        # 上下文状态
        ctx_status = 'no_review'
        ctx_start = ctx_end = ''
        code_context = ''
        if review and api_status == 'matched_review':
            if not file_path or line == '' or line is None:
                ctx_status, error_detail = 'no_file_or_line', 'review 无 file_path 或 line'
            else:
                try:
                    target_line = int(line)
                except (ValueError, TypeError):
                    ctx_status, error_detail = 'invalid_line', f'line 非数字: {line}'
                    target_line = None
                else:
                    cache_key = (row_domain, project_path, mr_iid)
                    if cache_key in failed_mrs:
                        ctx_status, error_detail = 'api_error', f'changes 接口请求失败: {cache_key}'
                    else:
                        diff_map = mr_diff_cache.get(cache_key, {})
                        diff_text = diff_map.get(file_path, '')
                        if not diff_text:
                            ctx_status, error_detail = 'diff_not_found', f'文件未在 MR diff 中: {file_path}'
                        else:
                            line_map = parse_diff_to_lines(diff_text)
                            code_context, ctx_start, ctx_end = build_context(line_map, target_line)
                            if code_context:
                                ctx_status = 'matched'
                                error_detail = ''
                            else:
                                ctx_status, error_detail = 'context_not_found', f'行号未在 diff hunk 中: {target_line}'

        rec = {
            'reviewer_name': reviewer_name,
            'reviewer_w3': reviewer_w3,
            'submitter_name': row.get('提交人姓名', ''),
            'submitter_w3': row.get('提交人W3', ''),
            'domain': row_domain,
            'project_path': project_path or '',
            'mr_iid': mr_iid or '',
            'note_hash': note_hash or '',
            'link': addr,
            'mr_status': row.get('MR状态', ''),
            'comment': str(comment) if comment is not None else '',
            'file_path': file_path,
            'line': line if line != '' and line is not None else '',
            'severity': severity,
            'created_at': str(created_at) if created_at else '',
            'resolved_at': str(resolved_at) if resolved_at else '',
            'api_review_match_status': api_status,
            'context_status': ctx_status,
            'error_detail': error_detail,
            'code_context': code_context,
            'context_start_line': ctx_start if ctx_start else '',
            'context_end_line': ctx_end if ctx_end else '',
            'is_test_file': detect_test_file(file_path),
            'language': detect_language(file_path),
        }
        results.append(rec)

    # 统计
    total = len(results)
    api_matched = sum(1 for r in results if r['api_review_match_status'] == 'matched_review')
    ctx_matched = sum(1 for r in results if r['context_status'] == 'matched')
    print(f'  总计 {total}；API匹配 {api_matched}；上下文匹配 {ctx_matched}')

    # 正式输出：只保留 context_status = matched
    matched = [r for r in results if r['context_status'] == 'matched']
    print(f'\n过滤：保留 matched {len(matched)} 条（移除 {total - len(matched)} 条无上下文）')

    base = f'{reviewer_w3}_{start}_{end}_enriched'
    xlsx_out = ENRICHED_DIR / f'{base}.xlsx'
    jsonl_out = ENRICHED_DIR / f'{base}.jsonl'

    write_enriched_excel(matched, str(xlsx_out))
    write_jsonl(matched, str(jsonl_out))
    print(f'\n输出：\n  {xlsx_out}\n  {jsonl_out}')

    return {
        'reviewer_w3': reviewer_w3, 'reviewer_name': reviewer_name,
        'domains': domains,
        'start': start, 'end': end, 'total': total,
        'api_matched': api_matched, 'ctx_matched': ctx_matched,
        'matched': len(matched), 'xlsx': str(xlsx_out), 'jsonl': str(jsonl_out),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='补充 CodeHub 字段和代码上下文')
    parser.add_argument('--input', required=True, help='阿基米德导出的 Excel 路径')
    parser.add_argument('--reviewer-w3', required=True, help='检视人 w3 账号')
    parser.add_argument('--domain', choices=sorted(REGIONS),
                        help='可选：限制/校验 CodeHub 地域；默认从检视地址自动推导')
    parser.add_argument('--start', default='', help='开始日期（不传则从文件名解析）')
    parser.add_argument('--end', default='', help='结束日期（不传则从文件名解析）')
    args = parser.parse_args()
    enrich(
        input_xlsx=args.input, reviewer_w3=args.reviewer_w3, domain=args.domain,
        start=args.start, end=args.end,
    )
