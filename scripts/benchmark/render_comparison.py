"""把 comparison.json 渲染成人工可读的 comparison.md。"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.artifacts import write_json  # noqa: E402

_RESULT_LABELS = {
    'matched': '命中',
    'partial_matched': '部分命中',
    'missed': '漏检',
    'new_finding': '新发现',
    'noise': '噪声',
}


def _line_range(item: dict) -> tuple[int, int]:
    try:
        start = int(item.get('line_start'))
        end = int(item.get('line_end') or start)
        return min(start, end), max(start, end)
    except (TypeError, ValueError):
        return -1, -1


def _location_pair_score(ground_truth: dict, ai_issue: dict) -> tuple[float, int | None]:
    if ground_truth.get('file_path') != ai_issue.get('file_path'):
        return 0.0, None
    gt_start, gt_end = _line_range(ground_truth)
    ai_start, ai_end = _line_range(ai_issue)
    if gt_start < 0 or ai_start < 0:
        return 0.0, None
    if gt_start <= ai_end and ai_start <= gt_end:
        return 1.0, 0
    distance = min(abs(gt_start - ai_end), abs(ai_start - gt_end))
    if distance <= 3:
        return 0.8, distance
    if distance <= 10:
        return 0.4, distance
    return 0.0, distance


def _text(item: dict) -> str:
    return str(item.get('comment') or item.get('description') or item.get('summary') or '')


def finalize_comparison(comparison: dict, ground_truth: dict,
                        ai_review: dict) -> dict:
    """校验匹配覆盖并确定性计算 summary；不让模型自行计算指标。"""
    if comparison.get('schema_version') != '1.0':
        raise ValueError('comparison.json schema_version 必须为 1.0')
    if comparison.get('assessment_status') not in {'model_assisted', 'human_confirmed'}:
        raise ValueError(
            'comparison.json assessment_status 必须为 model_assisted/human_confirmed')
    gt_ids = {item['id'] for item in ground_truth.get('comments', [])}
    ai_ids = {item['id'] for item in ai_review.get('issues', [])}
    gt_by_id = {item['id']: item for item in ground_truth.get('comments', [])}
    ai_by_id = {item['id']: item for item in ai_review.get('issues', [])}
    seen_gt, seen_ai = set(), set()
    result_gt = {key: set() for key in _RESULT_LABELS}
    result_ai = {key: set() for key in _RESULT_LABELS}
    location_hits = set()
    style_scores = []

    for item in comparison.get('comparisons', []):
        result = item.get('result')
        if result not in _RESULT_LABELS:
            raise ValueError(f'未知 comparison result: {result!r}')
        current_gt = set(item.get('ground_truth_ids', []))
        current_ai = set(item.get('ai_review_ids', []))
        unknown_gt = current_gt - gt_ids
        unknown_ai = current_ai - ai_ids
        if unknown_gt or unknown_ai:
            raise ValueError(f'comparison 引用了未知 id: GT={unknown_gt}, AI={unknown_ai}')
        if seen_gt & current_gt or seen_ai & current_ai:
            raise ValueError('同一个 GT/AI id 不能出现在多个 comparison 条目中')
        if result in {'matched', 'partial_matched'} and not (current_gt and current_ai):
            raise ValueError(f'{result} 条目必须同时引用 GT 和 AI')
        if result == 'missed' and (not current_gt or current_ai):
            raise ValueError('missed 条目必须只引用 ground truth')
        if result in {'new_finding', 'noise'} and (current_gt or not current_ai):
            raise ValueError(f'{result} 条目必须只引用 AI 意见')
        if result in {'matched', 'partial_matched'}:
            concern_score = (item.get('concern') or {}).get('score')
            if concern_score in ('', None) or not 0 <= float(concern_score) <= 1:
                raise ValueError('命中条目的 concern.score 必须在 0~1 之间')
            if (item.get('style') or {}).get('score') in ('', None):
                raise ValueError('命中条目必须填写 style.score')

        location_scores, distances = [], []
        same_file = False
        for gt_id in current_gt:
            candidates = [_location_pair_score(gt_by_id[gt_id], ai_by_id[ai_id])
                          for ai_id in current_ai]
            same_file = same_file or any(distance is not None
                                         for _score, distance in candidates)
            best = max(
                candidates, default=(0.0, None),
                key=lambda value: (
                    value[0], value[1] is not None,
                    -(value[1] if value[1] is not None else 10**9),
                ),
            )
            location_scores.append(best[0])
            if best[1] is not None:
                distances.append(best[1])
        location_score = (
            round(sum(location_scores) / len(location_scores), 4)
            if location_scores else 0.0)
        item['location'] = {
            'same_file': same_file,
            'line_distance': min(distances) if distances else None,
            'score': location_score,
        }
        gt_text = '\n'.join(_text(gt_by_id[item_id]) for item_id in sorted(current_gt))
        ai_text = '\n'.join(_text(ai_by_id[item_id]) for item_id in sorted(current_ai))
        item['text_similarity'] = round(
            difflib.SequenceMatcher(None, gt_text, ai_text).ratio(), 4
        ) if gt_text and ai_text else 0.0
        seen_gt |= current_gt
        seen_ai |= current_ai
        result_gt[result] |= current_gt
        result_ai[result] |= current_ai
        if location_score >= 0.8:
            location_hits |= current_gt
        style_score = (item.get('style') or {}).get('score')
        if style_score not in ('', None) and current_gt and current_ai:
            score = float(style_score)
            if not 1 <= score <= 5:
                raise ValueError('style.score 必须在 1~5 之间')
            style_scores.append(score)

    if seen_gt != gt_ids or seen_ai != ai_ids:
        raise ValueError(
            f'comparison 未完整覆盖输入：缺少 GT={gt_ids-seen_gt}, AI={ai_ids-seen_ai}')
    if result_gt['new_finding'] or result_gt['noise']:
        raise ValueError('new_finding/noise 条目不能引用 ground truth')
    if result_ai['missed']:
        raise ValueError('missed 条目不能引用 AI 意见')

    matched_gt = len(result_gt['matched'])
    precision_denominator = (
        len(result_ai['matched']) + len(result_ai['partial_matched'])
        + len(result_ai['noise']))
    comparison['summary'] = {
        'ground_truth_count': len(gt_ids),
        'ai_review_count': len(ai_ids),
        'matched': matched_gt,
        'partial_matched': len(result_gt['partial_matched']),
        'missed': len(result_gt['missed']),
        'new_findings': len(result_ai['new_finding']),
        'noise': len(result_ai['noise']),
        'location_hit_rate': round(len(location_hits) / len(gt_ids), 4) if gt_ids else 0,
        'average_style_score': (
            round(sum(style_scores) / len(style_scores), 2) if style_scores else None),
        'recall': round(matched_gt / len(gt_ids), 4) if gt_ids else 0,
        'precision': (
            round(len(result_ai['matched']) / precision_denominator, 4)
            if precision_denominator else 0),
    }
    return comparison


def _cell(value) -> str:
    return str(value or '').replace('|', '\\|').replace('\n', '<br>')


def _item_text(item: dict) -> str:
    if not item:
        return '无'
    line = item.get('line_start', '')
    location = f'{item.get("file_path", "")}:{line}'
    text = item.get('summary') or item.get('comment') or item.get('description') or ''
    return f'{item.get("id", "")} {location} {text}'.strip()


def render_comparison(comparison: dict, ground_truth: dict,
                      ai_review: dict) -> str:
    gt_by_id = {item['id']: item for item in ground_truth.get('comments', [])}
    ai_by_id = {item['id']: item for item in ai_review.get('issues', [])}
    lines = [
        '# Benchmark 对比结果', '',
        f'- MR：`{ground_truth.get("project_path", "")} !{ground_truth.get("mr_iid", "")}`',
        f'- reviewer：`{ground_truth.get("reviewer_w3", "")}` / `{ground_truth.get("reviewer_name", "")}`',
        f'- 状态：`{comparison.get("assessment_status", "")}`',
        '',
        '| # | 真人评论 | AI 评论 | 结果 | 位置 | 问题关切 | 风格 | 原因 |',
        '|---|---|---|---|---|---|---|---|',
    ]
    for index, item in enumerate(comparison.get('comparisons', []), 1):
        gt = '<br>'.join(_item_text(gt_by_id.get(i, {}))
                         for i in item.get('ground_truth_ids', [])) or '无'
        ai = '<br>'.join(_item_text(ai_by_id.get(i, {}))
                         for i in item.get('ai_review_ids', [])) or '无'
        location = item.get('location') or {}
        concern = item.get('concern') or {}
        style = item.get('style') or {}
        lines.append('| {} | {} | {} | {} | {} | {} | {} | {} |'.format(
            index, _cell(gt), _cell(ai),
            _RESULT_LABELS.get(item.get('result'), item.get('result', '')),
            _cell(location.get('score')), _cell(concern.get('score')),
            _cell(style.get('score')), _cell(item.get('reason')),
        ))

    summary = comparison.get('summary') or {}
    lines.extend(['', '## 汇总', ''])
    for key, label in (
        ('ground_truth_count', '真人评论数'), ('ai_review_count', 'AI 意见数'),
        ('matched', '命中'), ('partial_matched', '部分命中'),
        ('missed', '漏检'), ('new_findings', '新发现'), ('noise', '噪声'),
        ('location_hit_rate', '位置命中率'),
        ('average_style_score', '平均风格分'),
        ('recall', '召回率'), ('precision', '精度'),
    ):
        if key in summary:
            lines.append(f'- {label}：`{summary[key]}`')
    lines.append('')
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description='将 comparison JSON 渲染为 Markdown')
    parser.add_argument('--comparison', required=True)
    parser.add_argument('--ground-truth', required=True)
    parser.add_argument('--ai-review', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    comparison = json.loads(Path(args.comparison).read_text(encoding='utf-8'))
    ground_truth = json.loads(Path(args.ground_truth).read_text(encoding='utf-8'))
    ai_review = json.loads(Path(args.ai_review).read_text(encoding='utf-8'))
    output = Path(args.output)
    comparison = finalize_comparison(comparison, ground_truth, ai_review)
    write_json(Path(args.comparison), comparison)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_comparison(comparison, ground_truth, ai_review), encoding='utf-8')
    print(f'benchmark 对比 Markdown 输出：{output}')


if __name__ == '__main__':
    main()
