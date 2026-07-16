"""把结构化 review JSON 渲染成现有铁律格式 Markdown 报告。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.artifacts import now_iso, write_json  # noqa: E402

_SEVERITIES = ('高危', '中危', '低危', '优化建议')


def _position(issue: dict) -> str:
    # Markdown 保持原契约只展示 basename；JSON 始终保留完整 file_path 供 benchmark 对齐。
    file_name = Path(str(issue.get('file_path', ''))).name
    start = issue.get('line_start', '')
    end = issue.get('line_end', '')
    if end not in ('', None) and str(end) != str(start):
        return f'{file_name}:{start}-{end}'
    return f'{file_name}:{start}'


def validate_review(data: dict) -> None:
    if data.get('schema_version') != '1.0':
        raise ValueError('review.json schema_version 必须为 1.0')
    reviewer = data.get('reviewer') or {}
    if not reviewer.get('name') or not reviewer.get('w3'):
        raise ValueError('review.json 缺少 reviewer.name / reviewer.w3')
    issues = data.get('issues')
    if not isinstance(issues, list):
        raise ValueError('review.json issues 必须是数组')
    seen = set()
    for issue in issues:
        issue_id = issue.get('id')
        if not issue_id or issue_id in seen:
            raise ValueError(f'评审意见 id 缺失或重复: {issue_id!r}')
        seen.add(issue_id)
        if issue.get('severity') not in _SEVERITIES:
            raise ValueError(f'{issue_id} severity 必须是 {_SEVERITIES}')
        for field in ('file_path', 'line_start', 'description'):
            if issue.get(field) in ('', None):
                raise ValueError(f'{issue_id} 缺少 {field}')
    for baseline in data.get('baseline_violations', []):
        for field in ('rule_id', 'rule_name', 'level', 'file_path',
                      'line_start', 'description', 'suggestion'):
            if baseline.get(field) in ('', None):
                raise ValueError(f'通用基线违规缺少 {field}')
        if baseline['level'] not in {'要求', '建议'}:
            raise ValueError('通用基线 level 必须为 要求/建议')


def render_review(data: dict) -> str:
    validate_review(data)
    reviewer = data['reviewer']
    target = data.get('target') or {}
    files = data.get('files') or []
    source = target.get('source', 'commit')
    if source == 'mr':
        target_line = f'检视MR: {target.get("project_path", "")} !{target.get("mr_iid", "")}'
    else:
        target_line = f'检视Commit: {target.get("commit", "")}'
    file_summary = ', '.join(files[:8])
    if len(files) > 8:
        file_summary += ', ...'

    divider = '═' * 63
    lines = [
        divider,
        '                    代码检视报告',
        divider,
        target_line,
        f'评审分身: {reviewer["name"]}（{reviewer["w3"]}）',
        f'代码变更文件: {len(files)} 个' + (f'（摘要：{file_summary}）' if files else ''),
        divider,
        '',
    ]

    baseline_violations = data.get('baseline_violations', [])
    if baseline_violations:
        lines.extend(['## 通用基线违规', ''])
        for baseline in baseline_violations:
            lines.extend([
                f'【通用基线违规】{baseline["rule_id"]} - {baseline["rule_name"]}',
                f'【规则来源】通用基线-{baseline.get("source_index", baseline["rule_id"])}',
                f'【级别】{baseline["level"]}',
                f'【位置】{_position(baseline)}',
                f'【问题描述】{baseline["description"]}',
                f'【整改建议】{baseline["suggestion"]}',
                '',
            ])
    lines.extend(['## 评审意见', ''])

    ordered = sorted(
        data['issues'],
        key=lambda issue: (_SEVERITIES.index(issue['severity']), issue['id']),
    )
    for index, issue in enumerate(ordered, 1):
        rule_id = str(issue.get('rule_id') or '通用')
        rule_name = str(issue.get('rule_name') or '').strip()
        rule = f'{rule_id}-{rule_name}' if rule_name else rule_id
        lines.extend([
            f'### {index}. {issue["severity"]}：{issue.get("summary") or issue["id"]}',
            '',
            f'【{reviewer["name"]}意见】',
            f'【评审来源】{reviewer["name"]}|{rule}',
            f'【位置】{_position(issue)}',
            '',
            str(issue['description']).strip(),
        ])
        code_example = str(issue.get('code_example') or '').strip()
        if code_example:
            lines.extend([
                '',
                '【修改示例】',
                f'```{issue.get("language", "")}',
                code_example,
                '```',
            ])
        lines.extend(['---', ''])

    counts = Counter(issue['severity'] for issue in data['issues'])
    merge_risk = (data.get('summary') or {}).get('merge_risk')
    if merge_risk not in {'通过', '需整改后合并'}:
        merge_risk = '需整改后合并' if data['issues'] else '通过'
    lines.extend([
        '## 总结',
        '',
        divider,
        '                          总结',
        divider,
        f'高危问题: {counts["高危"]} 项',
        f'中危问题: {counts["中危"]} 项',
        f'低危问题: {counts["低危"]} 项',
        f'优化建议: {counts["优化建议"]} 项',
        f'合并风险评估: {merge_risk}',
        divider,
        '',
    ])
    return '\n'.join(lines)


def update_manifest(path: Path, data: dict, json_path: Path,
                    markdown_path: Path) -> None:
    manifest = json.loads(path.read_text(encoding='utf-8'))
    reviewer = data['reviewer']
    def relative_artifact(artifact: Path) -> str:
        try:
            return str(artifact.resolve().relative_to(path.parent.resolve()))
        except ValueError:
            return str(artifact)

    entry = {
        'w3': reviewer['w3'],
        'name': reviewer['name'],
        'persona_file': reviewer.get('persona_file', ''),
        'persona_sha256': reviewer.get('persona_sha256', ''),
        'review_json': relative_artifact(json_path),
        'review_markdown': relative_artifact(markdown_path),
        'generated_at': now_iso(),
    }
    if manifest.get('kind') == 'review':
        reviewers = [item for item in manifest.get('reviewers', [])
                     if item.get('w3') != reviewer['w3']]
        reviewers.append(entry)
        manifest['reviewers'] = reviewers
    else:
        manifest['ai_review'] = entry
    write_json(path, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description='将 review JSON 渲染为 Markdown')
    parser.add_argument('--input', required=True, help='review.json / ai_review.json')
    parser.add_argument('--output', help='输出 Markdown；默认同目录同 stem')
    parser.add_argument('--manifest', help='渲染完成后更新对应 manifest.json')
    args = parser.parse_args()
    input_path = Path(args.input)
    data = json.loads(input_path.read_text(encoding='utf-8'))
    output = Path(args.output) if args.output else input_path.with_suffix('.md')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_review(data), encoding='utf-8')
    if args.manifest:
        update_manifest(Path(args.manifest), data, input_path, output)
    print(f'评审 Markdown 输出：{output}')


if __name__ == '__main__':
    main()
