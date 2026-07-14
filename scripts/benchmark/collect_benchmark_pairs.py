"""收集 benchmark 对照包：某评审人真实评审过的 MR 列表 + 单 MR 的(真人评论, MR diff)对。

benchmark 按 mr_iid 对齐：
- 真人评论来自 enriched JSONL（按 mr_iid 过滤，字段已英文 key）
- MR diff 来自 CodeHub get_mr_diff（= 真人当时评的那份），两边同键同 diff，行号天然对齐
产物 outputs/benchmark/{mr_iid}_pair.json，供 benchmark worksheet 人工对照。

ground truth 取 enriched matched 评论（有 file/line/severity）；enrich 未匹配上的
评论不在基准里（如需全量可改读 raw 阿基米德 Excel，后续再说）。

- --list：纯本地读 enriched，列候选 MR（不需内网，不需 token）。
- --pick/--mr-iid：需 --domain（拉 MR diff 走 CodeHub）。

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/benchmark/collect_benchmark_pairs.py \
        --reviewer-w3 z00000001 --list
    python <SKILL_ROOT>/scripts/benchmark/collect_benchmark_pairs.py \
        --reviewer-w3 z00000001 --pick 1 --domain codehub-g
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # code-review/scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.paths import ENRICHED_DIR, BENCHMARK_DIR, ensure_dirs  # noqa: E402
from common.jsonl_io import read_jsonl  # noqa: E402


def _load_reviewer_records(reviewer_w3: str) -> list:
    """读 outputs/enriched/*.jsonl，按 reviewer_w3 过滤。"""
    records = []
    if not ENRICHED_DIR.exists():
        return records
    for p in sorted(ENRICHED_DIR.glob('*_enriched.jsonl')):
        for r in read_jsonl(str(p)):
            if str(r.get('reviewer_w3', '')) == reviewer_w3:
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


def _resolve(reviewer_w3, pick=None, mr_iid=None):
    records = _load_reviewer_records(reviewer_w3)
    if not records:
        raise SystemExit(f'enriched 里没有 reviewer_w3={reviewer_w3} 的记录，先跑 distill。')
    ordered = _aggregate_mrs(records)
    if pick is not None:
        idx = int(pick) - 1
        if not (0 <= idx < len(ordered)):
            raise SystemExit(f'--pick {pick} 超范围（共 {len(ordered)} 个 MR）')
        return ordered[idx]
    for item in ordered:
        (pp, mi), v = item
        if str(mi) == str(mr_iid):
            return item
    raise SystemExit(f'未在 enriched 找到 mr_iid={mr_iid}')


def collect_pair(reviewer_w3: str, project_path: str, mr_iid,
                 records: list, domain: str) -> dict:
    from review.get_commit_diff import get_mr_review_diff  # 复用 MR diff 装配管线
    ensure_dirs()
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

    real_comments = [{
        'note_hash': r.get('note_hash', ''),
        'file_path': r.get('file_path', ''),
        'line': r.get('line', ''),
        'severity': r.get('severity', ''),
        'comment': r.get('comment', ''),
        'created_at': r.get('created_at', ''),
        'resolved_at': r.get('resolved_at', ''),
    } for r in records]

    # 拉 MR diff（走同一管线，落 outputs/diffs/{mr_iid}_mrdiff.json）。
    # pair.json 只存对 mrdiff.json 的引用 + 统计，不重复存整段 diff（一份就够）。
    diff_result = get_mr_review_diff(domain, project_path, mr_iid)

    pair = {
        'reviewer_w3': reviewer_w3,
        'reviewer_name': next((r.get('reviewer_name', '') for r in records
                               if r.get('reviewer_name')), ''),
        'project_path': project_path,
        'mr_iid': mr_iid,
        'real_comment_count': len(real_comments),
        'real_comments': real_comments,
        'diff_ref': {
            'mrdiff_json': f'outputs/diffs/{mr_iid}_mrdiff.json',
            'kept_files': diff_result['kept_files'],
            'excluded_test_files': diff_result['excluded_test_files'],
        },
    }
    out = BENCHMARK_DIR / f'{mr_iid}_pair.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(pair, f, ensure_ascii=False, indent=2)
    print(f'benchmark pair 输出：{out}')
    print(f'  真人评论 {len(real_comments)} 条，MR diff 保留文件 '
          f'{diff_result["kept_files"]} 个（见 outputs/diffs/{mr_iid}_mrdiff.json）')
    print(f'  下一步：模型读 {mr_iid}_mrdiff.json + persona 生成 AI 报告')
    print(f'  （无需再带 project_path/domain，diff 已在上面那份 mrdiff.json 里）')
    return pair


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='收集 benchmark 对照包')
    parser.add_argument('--reviewer-w3', required=True, help='评审人工号')
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--list', action='store_true', help='列出候选 MR')
    g.add_argument('--pick', help='--list 输出的序号')
    g.add_argument('--mr-iid', help='直接按 mr_iid 选')
    parser.add_argument('--domain', help='CodeHub 地域（--pick/--mr-iid 拉 diff 需要）')
    args = parser.parse_args()

    if args.list:
        list_mrs(args.reviewer_w3)
    else:
        if not args.domain:
            parser.error('--pick/--mr-iid 需配合 --domain（拉 MR diff 走 CodeHub）')
        (pp, mi), v = _resolve(args.reviewer_w3, pick=args.pick, mr_iid=args.mr_iid)
        collect_pair(args.reviewer_w3, pp, mi, v['records'], args.domain)
