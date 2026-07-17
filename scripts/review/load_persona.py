"""加载 / 列出 reviewer 人格分身。

- 扫描 personas/*.skill.md
- 支持按姓名或工号匹配
- list-personas 支持紧凑文本、verbose 完整文本和只写 stdout 的 JSON
- persona 文件和 CLI 输出统一使用 UTF-8

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/review/load_persona.py --list
    python <SKILL_ROOT>/scripts/review/load_persona.py --list --verbose
    python <SKILL_ROOT>/scripts/review/load_persona.py --list --format json
    python <SKILL_ROOT>/scripts/review/load_persona.py --w3 z00000001
    python <SKILL_ROOT>/scripts/review/load_persona.py --name 张示例
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # code-review/scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.paths import PERSONAS_DIR  # noqa: E402
from common.persona import parse_persona  # noqa: E402

_FOCUS_SEPARATORS = {'、', '，', ',', '；', ';'}
_FOCUS_BRACKETS = {'(': ')', '（': '）', '[': ']', '【': '】'}


def configure_utf8_stdio() -> None:
    """固定 CLI 字节流编码，避免 Windows CP936 与 UTF-8 调用方冲突。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            reconfigure(encoding='utf-8', errors='replace')


def list_personas(personas_dir: Path = None) -> list:
    directory = Path(personas_dir) if personas_dir is not None else PERSONAS_DIR
    if not directory.exists():
        return []
    personas = []
    for p in sorted(directory.glob('*.skill.md')):
        personas.append(parse_persona(p))
    return personas


def summarize_focus(focus: str, limit: int = 5, max_chars: int = 80) -> str:
    """提取顶层关注主题；忽略括号内分隔符，默认最多返回五项。"""
    value = str(focus or '').strip()
    if not value:
        return ''
    parts, buffer, brackets = [], [], []
    for char in value:
        if char in _FOCUS_BRACKETS:
            brackets.append(_FOCUS_BRACKETS[char])
        elif brackets and char == brackets[-1]:
            brackets.pop()
        if char in _FOCUS_SEPARATORS and not brackets:
            part = ''.join(buffer).strip()
            if part:
                parts.append(part)
            buffer = []
        else:
            buffer.append(char)
    tail = ''.join(buffer).strip()
    if tail:
        parts.append(tail)

    topics = []
    for part in parts:
        # 紧凑列表只保留主题名；括号里的例子/细节留给 verbose。
        topic = part
        for opening in _FOCUS_BRACKETS:
            if opening in topic:
                topic = topic.split(opening, 1)[0].strip()
                break
        if topic and topic not in topics:
            topics.append(topic)
    if not topics:
        return value
    summary = '、'.join(topics[:limit])
    summary += '等' if len(topics) > limit else ''
    if len(summary) > max_chars:
        summary = summary[:max_chars - 1].rstrip() + '…'
    return summary


def _list_record(persona: dict) -> dict:
    metadata = persona.get('metadata') or {}
    focus = persona.get('focus', '')
    return {
        'name': persona.get('name', ''),
        'w3': persona.get('w3', ''),
        'distill_start': metadata.get('distill_start') or '',
        'distill_end': metadata.get('distill_end') or '',
        'rule_count': persona.get('rule_count', 0),
        'focus_summary': summarize_focus(focus),
        'focus': focus,
        'file': persona.get('file', ''),
    }


def render_personas_json(personas: list) -> str:
    """返回 ASCII-safe JSON；调用方读取 stdout，不创建清单文件。"""
    payload = {
        'schema_version': '1.1',
        'personas': [_list_record(persona) for persona in personas],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2)


def render_personas_text(personas: list, verbose: bool = False) -> str:
    """返回不依赖中日韩字符显示宽度的分块文本。"""
    if not personas:
        return f'{PERSONAS_DIR} 下无 persona 文件'
    lines = [f'已安装 {len(personas)} 个 reviewer persona', '']
    for index, persona in enumerate(personas, 1):
        item = _list_record(persona)
        if item['distill_start'] and item['distill_end']:
            period = f"{item['distill_start']} ~ {item['distill_end']}"
        else:
            period = '蒸馏范围未记录'
        focus = (item['focus'] if verbose else item['focus_summary']) or '未填写'
        lines.extend([
            f"{index}. {item['name']}（{item['w3']}）",
            f"   {item['rule_count']} 条规则 · {period}",
            f"   关注：{focus}",
        ])
        if index != len(personas):
            lines.append('')
    return '\n'.join(lines)


def find_persona(name: str = None, w3: str = None) -> str:
    """返回匹配的 persona 文件路径，未匹配返回空串。"""
    for p in list_personas():
        if w3 and p['w3'] == w3:
            return p['file']
        if name and p['name'] == name:
            return p['file']
    return ''


def main():
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description='加载/列出 reviewer 人格')
    parser.add_argument('--list', action='store_true', help='列出所有 persona')
    parser.add_argument('--format', choices=('text', 'json'), default='text',
                        help='--list 输出格式；json 只写 stdout，不生成文件')
    parser.add_argument('--verbose', action='store_true',
                        help='--list 文本模式展示完整关注领域')
    parser.add_argument('--name', default='', help='按姓名匹配')
    parser.add_argument('--w3', default='', help='按工号匹配')
    args = parser.parse_args()

    if args.list:
        personas = list_personas()
        if args.format == 'json':
            print(render_personas_json(personas))
        else:
            print(render_personas_text(personas, verbose=args.verbose))
        return

    if args.name or args.w3:
        path = find_persona(name=args.name or None, w3=args.w3 or None)
        if path:
            print(path)
        else:
            print(f'未找到 persona（name={args.name}, w3={args.w3}）')
            sys.exit(1)
        return

    parser.print_help()


if __name__ == '__main__':
    main()
