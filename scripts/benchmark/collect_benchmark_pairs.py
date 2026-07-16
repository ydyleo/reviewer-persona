"""收集 benchmark case：某评审人的真人评论 + 对应 MR diff。

benchmark 按 domain + project_path + mr_iid 对齐：
- 真人评论来自 enriched JSONL（按 mr_iid 过滤，字段已英文 key）
- MR diff 来自 CodeHub get_mr_diff；脚本会复核真人评论位置是否仍存在于当前 diff
产物写入 outputs/benchmark/{domain}/{project_path}/mr-{iid}/reviewer-{w3}/：
manifest.json、diff.json/.md、ground_truth.json。

ground truth 取 enriched matched 评论（有 file/line/severity）；enrich 未匹配上的
评论不在基准里（如需全量可改读 raw 阿基米德 Excel，后续再说）。

- --list：纯本地读 enriched，列候选 MR（不需内网，不需 token）。
- --pick/--mr-iid：需 --domain（拉 MR diff 走 CodeHub）。

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/benchmark/collect_benchmark_case.py \
        --reviewer-w3 z00000001 --list
    python <SKILL_ROOT>/scripts/benchmark/collect_benchmark_case.py \
        --reviewer-w3 z00000001 --pick 1 --domain codehub-g
"""
import argparse
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # code-review/scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.artifacts import now_iso, write_json  # noqa: E402
from common.output_layout import benchmark_case_dir, normalize_domain  # noqa: E402
from common.paths import ENRICHED_DIR, ensure_dirs  # noqa: E402
from common.jsonl_io import read_jsonl  # noqa: E402
from common.diff_parser import parse_diff_to_lines  # noqa: E402
from review.load_persona import find_persona  # noqa: E402


def _load_reviewer_records(reviewer_w3: str) -> list:
    """读 enriched 并按评论身份去重，避免重叠时间范围重复计数。"""
    records, seen = [], set()
    if not ENRICHED_DIR.exists():
        return records
    for p in sorted(ENRICHED_DIR.glob('*_enriched.jsonl')):
        for r in read_jsonl(str(p)):
            if str(r.get('reviewer_w3', '')) == reviewer_w3:
                key = (
                    r.get('project_path', ''), str(r.get('mr_iid', '')),
                    r.get('note_hash', '') or (
                        r.get('file_path', ''), str(r.get('line', '')),
                        r.get('comment', ''), r.get('created_at', ''),
                    ),
                )
                if key in seen:
                    continue
                seen.add(key)
                records.append(r)
    return records


def _aggregate_mrs(records: list):
    """按 (project_path, mr_iid) 聚合评论。返回 [((pp, mi), {'records': [...]})] 按评论数降序。"""
    mrs = defaultdict(lambda: {'records': []})
    for r in records:
        pp = r.get('project_path', '')
        mi = r.get('mr_iid', '')
        if not pp or not mi:
            continue
        mrs[(pp, mi)]['records'].append(r)
    return sorted(mrs.items(), key=lambda kv: -len(kv[1]['records']))


def list_mrs(reviewer_w3: str) -> None:
    records = _load_reviewer_records(reviewer_w3)
    if not records:
        print(f'enriched 里没有 reviewer_w3={reviewer_w3} 的记录。')
        print('请先跑 /code-review distill 到 enrich，产出 outputs/enriched/*.jsonl。')
        return
    ordered = _aggregate_mrs(records)
    print(f'reviewer_w3={reviewer_w3}  共 {len(records)} 条 matched 评论，'
          f'{len(ordered)} 个 MR\n')
    print(f'{"序号":>4}  {"project_path/mr_iid":<48}  {"评论数":>5}  严重程度')
    print('-' * 90)
    for i, ((pp, mi), v) in enumerate(ordered, 1):
        sev = Counter(str(r.get('severity', '')).strip() or '未知'
                      for r in v['records'])
        sev_str = ', '.join(f'{k}:{n}' for k, n in sev.most_common())
        key = f'{pp}/{mi}'
        print(f'{i:>4}  {key[:48]:<48}  {len(v["records"]):>5}  {sev_str}')
    print('\n选用: --pick <序号> 或 --mr-iid <iid>（需 --domain 拉 MR diff）')


def _resolve(reviewer_w3, pick=None, mr_iid=None, project_path=None):
    records = _load_reviewer_records(reviewer_w3)
    if not records:
        raise SystemExit(f'enriched 里没有 reviewer_w3={reviewer_w3} 的记录，先跑 distill。')
    ordered = _aggregate_mrs(records)
    if pick is not None:
        idx = int(pick) - 1
        if not (0 <= idx < len(ordered)):
            raise SystemExit(f'--pick {pick} 超范围（共 {len(ordered)} 个 MR）')
        return ordered[idx]
    matches = []
    for item in ordered:
        (pp, mi), v = item
        if str(mi) == str(mr_iid) and (not project_path or pp == project_path):
            matches.append(item)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        projects = '\n'.join(f'  - {pp}' for (pp, _), _v in matches)
        raise SystemExit(
            f'mr_iid={mr_iid} 在多个项目中存在，请增加 --project-path：\n{projects}')
    raise SystemExit(f'未在 enriched 找到 mr_iid={mr_iid}')


def _persona_metadata(reviewer_w3: str) -> dict:
    path_str = find_persona(w3=reviewer_w3)
    if not path_str:
        return {'w3': reviewer_w3, 'file': '', 'sha256': ''}
    path = Path(path_str)
    return {
        'w3': reviewer_w3,
        'file': path.name,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def collect_case(reviewer_w3: str, project_path: str, mr_iid,
                 records: list, domain: str) -> dict:
    from review.get_commit_diff import get_mr_review_diff  # 复用 MR diff 装配管线
    ensure_dirs()
    output_dir = benchmark_case_dir(domain, project_path, mr_iid, reviewer_w3)
    output_dir.mkdir(parents=True, exist_ok=True)
    # 当前方案只保留最新结果；输入重新收集后，旧 AI/比较结果已失效。
    for stale_name in ('ai_review.json', 'ai_review.md',
                       'comparison.json', 'comparison.md'):
        stale_path = output_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()

    real_comments = [{
        'id': f'GT-{i:03d}',
        'note_hash': r.get('note_hash', ''),
        'file_path': r.get('file_path', ''),
        'line_start': r.get('line', ''),
        'line_end': r.get('line', ''),
        'severity': r.get('severity', ''),
        'comment': r.get('comment', ''),
        'created_at': r.get('created_at', ''),
        'resolved_at': r.get('resolved_at', ''),
    } for i, r in enumerate(records, 1)]

    # 与普通 review 复用同一套 diff 装配管线，只改变输出目录。
    diff_result = get_mr_review_diff(
        domain, project_path, mr_iid, output_dir=output_dir)
    diff_lines = {
        item['file_path']: parse_diff_to_lines(item['diff_text'])
        for item in diff_result['files']
    }
    aligned_count = 0
    for comment in real_comments:
        try:
            line = int(comment['line_start'])
        except (TypeError, ValueError):
            line = -1
        aligned = line in diff_lines.get(comment['file_path'], {})
        comment['diff_location_status'] = 'matched' if aligned else 'not_in_current_diff'
        aligned_count += int(aligned)
    eligible_comments = [item for item in real_comments
                         if item['diff_location_status'] == 'matched']
    excluded_comments = [item for item in real_comments
                         if item['diff_location_status'] != 'matched']

    ground_truth = {
        'schema_version': '1.0',
        'reviewer_w3': reviewer_w3,
        'reviewer_name': next((r.get('reviewer_name', '') for r in records
                               if r.get('reviewer_name')), ''),
        'project_path': project_path,
        'mr_iid': mr_iid,
        'source_comment_count': len(real_comments),
        'comment_count': len(eligible_comments),
        'benchmark_ready': bool(eligible_comments),
        'diff_location_matched_count': aligned_count,
        'diff_location_unmatched_count': len(real_comments) - aligned_count,
        'comments': eligible_comments,
        'excluded_comments': excluded_comments,
        'diff_ref': {
            'json': 'diff.json',
            'markdown': 'diff.md',
            'kept_files': diff_result['kept_files'],
            'excluded_test_files': diff_result['excluded_test_files'],
        },
    }
    ground_truth_out = output_dir / 'ground_truth.json'
    write_json(ground_truth_out, ground_truth)

    reviewer_name = ground_truth['reviewer_name']
    persona = _persona_metadata(reviewer_w3)
    persona['name'] = reviewer_name
    manifest = {
        'schema_version': '1.0',
        'kind': 'benchmark',
        'created_at': now_iso(),
        'domain': normalize_domain(domain),
        'project_path': project_path,
        'mr_iid': mr_iid,
        'reviewer': {'w3': reviewer_w3, 'name': reviewer_name},
        'persona': persona,
        'benchmark_ready': bool(eligible_comments),
        'generation_isolation': {
            'ai_review_inputs': ['diff.json', persona['file']],
            'forbidden_during_ai_generation': ['ground_truth.json'],
        },
        'artifacts': {
            'diff_json': 'diff.json',
            'diff_markdown': 'diff.md',
            'ground_truth': 'ground_truth.json',
            'ai_review_json': 'ai_review.json',
            'ai_review_markdown': 'ai_review.md',
            'comparison_json': 'comparison.json',
            'comparison_markdown': 'comparison.md',
        },
    }
    write_json(output_dir / 'manifest.json', manifest)
    print(f'benchmark case 输出：{output_dir}')
    print(f'  真人评论 {len(real_comments)} 条，MR diff 保留文件 '
          f'{diff_result["kept_files"]} 个')
    if aligned_count != len(real_comments):
        print(f'  警告：{len(real_comments)-aligned_count} 条真人评论位置不在当前 MR diff，'
              '比较时不得计入位置命中')
    if not eligible_comments:
        print('  benchmark 不可继续：没有真人评论位置能与当前 MR diff 对齐')
    print('  下一步：模型只读 diff.json + persona，生成 ai_review.json')
    print('  注意：生成 AI 评论前禁止读取 ground_truth.json')
    return {
        'output_dir': str(output_dir),
        'ground_truth': ground_truth,
        'diff': diff_result,
        'manifest': manifest,
    }


# 兼容旧的 Python 调用名；顶层命令和文档统一使用 collect_case。
collect_pair = collect_case


def main() -> None:
    parser = argparse.ArgumentParser(description='收集 benchmark case')
    parser.add_argument('--reviewer-w3', required=True, help='评审人工号')
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--list', action='store_true', help='列出候选 MR')
    g.add_argument('--pick', help='--list 输出的序号')
    g.add_argument('--mr-iid', help='直接按 mr_iid 选')
    parser.add_argument('--project-path', help='mr_iid 跨项目重复时用于消歧')
    parser.add_argument('--domain', help='CodeHub 地域（--pick/--mr-iid 拉 diff 需要）')
    args = parser.parse_args()

    if args.list:
        list_mrs(args.reviewer_w3)
    else:
        if not args.domain:
            parser.error('--pick/--mr-iid 需配合 --domain（拉 MR diff 走 CodeHub）')
        (pp, mi), v = _resolve(
            args.reviewer_w3, pick=args.pick, mr_iid=args.mr_iid,
            project_path=args.project_path,
        )
        collect_case(args.reviewer_w3, pp, mi, v['records'], args.domain)


if __name__ == '__main__':
    main()
