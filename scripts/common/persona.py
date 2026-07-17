"""persona 文件的公共解析与新草稿校验。"""
from __future__ import annotations

import re
from pathlib import Path

RULE_HEADING_RE = re.compile(r'^###\s+([SPBACD])\d+', re.MULTILINE)
FILENAME_RE = re.compile(r'^reviewer-(.+)-([a-zA-Z0-9]+)\.skill\.md$')
TITLE_RE = re.compile(r'^#\s*评审人格分身：【(.+?)\s+([a-zA-Z0-9]+)】', re.MULTILINE)

_META_PATTERNS = {
    'reviewer_name': r'^-\s*reviewer[：:]\s*(.+?)\s*$',
    'reviewer_w3': r'^-\s*reviewer_w3[：:]\s*([a-zA-Z0-9]+)\s*$',
    'distill_start': r'^-\s*蒸馏开始日期[：:]\s*(.+?)\s*$',
    'distill_end': r'^-\s*蒸馏结束日期[：:]\s*(.+?)\s*$',
    'total_reviews': r'^-\s*历史评论数量[：:]\s*(\d+)\s*$',
    'prepared_at': r'^-\s*数据准备时间[：:]\s*(.+?)\s*$',
}


def _metadata(text: str) -> dict:
    result = {}
    for key, pattern in _META_PATTERNS.items():
        match = re.search(pattern, text, re.MULTILINE)
        result[key] = match.group(1).strip() if match else ''
    if result.get('total_reviews'):
        result['total_reviews'] = int(result['total_reviews'])
    return result


def parse_persona(path: Path) -> dict:
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    name, w3 = '', ''
    title = TITLE_RE.search(text)
    if title:
        name, w3 = title.group(1).strip(), title.group(2).strip()
    if not name or not w3:
        filename = FILENAME_RE.match(path.name)
        if filename:
            name = name or filename.group(1)
            w3 = w3 or filename.group(2)
    focus = ''
    focus_match = re.search(
        r'##\s*核心评审偏好\s*\n\s*-?\s*重点关注领域[：:]\s*(.+)', text)
    if focus_match:
        focus = focus_match.group(1).strip()
    return {
        'file': str(path), 'name': name, 'w3': w3,
        'rule_count': len(RULE_HEADING_RE.findall(text)),
        'focus': focus, 'metadata': _metadata(text),
    }


def validate_persona(path: Path, expected: dict = None) -> dict:
    """校验新草稿；返回解析信息，失败抛出包含全部原因的 ValueError。"""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'persona 草稿不存在: {path}')
    text = path.read_text(encoding='utf-8')
    info = parse_persona(path)
    errors = []
    if not TITLE_RE.search(text):
        errors.append('缺少合法标题「# 评审人格分身：【姓名 工号】」')
    if '/' in info['name'] or '\\' in info['name'] or info['name'] in {'', '.', '..'}:
        errors.append('reviewer 姓名为空或包含非法路径字符')
    if not info['w3']:
        errors.append('无法解析 reviewer_w3')
    for heading in ('Persona 元信息', '强制固定约束', '核心评审偏好',
                    '分身专属规则', '输出要求'):
        if not re.search(rf'^##\s+[^\n]*{re.escape(heading)}', text, re.MULTILINE):
            errors.append(f'缺少「{heading}」章节')
    if info['rule_count'] < 1:
        errors.append('至少需要一条 S/P/B/A/C/D 编号规则')
    output_match = re.search(r'^##\s+输出要求\s*\n([\s\S]*)$', text, re.MULTILINE)
    output_text = output_match.group(1) if output_match else ''
    if output_text and not re.search(r'【.+?意见】', output_text):
        errors.append('输出要求缺少「【{姓名}意见】」token')
    for token in ('【评审来源】', '【位置】', '【修改示例】', '---'):
        if output_text and token not in output_text:
            errors.append(f'输出要求缺少 token {token}')

    metadata = info['metadata']
    for key, label in (
        ('reviewer_name', 'reviewer'), ('reviewer_w3', 'reviewer_w3'),
        ('distill_start', '蒸馏开始日期'), ('distill_end', '蒸馏结束日期'),
        ('total_reviews', '历史评论数量'), ('prepared_at', '数据准备时间'),
    ):
        if metadata.get(key) in ('', None):
            errors.append(f'Persona 元信息缺少「{label}」')

    expected = expected or {}
    checks = (
        ('reviewer_name', info['name'], '标题姓名'),
        ('reviewer_w3', info['w3'], '标题工号'),
        ('reviewer_name', metadata.get('reviewer_name'), '元信息姓名'),
        ('reviewer_w3', metadata.get('reviewer_w3'), '元信息工号'),
        ('distill_start', metadata.get('distill_start'), '蒸馏开始日期'),
        ('distill_end', metadata.get('distill_end'), '蒸馏结束日期'),
        ('total_reviews', metadata.get('total_reviews'), '历史评论数量'),
        ('prepared_at', metadata.get('prepared_at'), '数据准备时间'),
    )
    for key, actual, label in checks:
        wanted = expected.get(key)
        if wanted not in ('', None) and str(actual) != str(wanted):
            errors.append(f'{label}={actual!r}，与 structured 的 {wanted!r} 不一致')
    if errors:
        raise ValueError('persona 校验失败：\n- ' + '\n- '.join(errors))
    return info
