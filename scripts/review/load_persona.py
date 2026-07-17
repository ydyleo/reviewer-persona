"""加载 / 列出 reviewer 人格分身。

- 扫描 personas/*.skill.md
- 支持按姓名或工号匹配
- list-personas 支持分块文本和只写 stdout 的 JSON
- persona 文件和 CLI 输出统一使用 UTF-8

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/review/load_persona.py --list
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


def _list_record(persona: dict) -> dict:
    metadata = persona.get('metadata') or {}
    return {
        'name': persona.get('name', ''),
        'w3': persona.get('w3', ''),
        'distill_start': metadata.get('distill_start') or '',
        'distill_end': metadata.get('distill_end') or '',
        'rule_count': persona.get('rule_count', 0),
        'focus': persona.get('focus', ''),
        'file': persona.get('file', ''),
    }


def render_personas_json(personas: list) -> str:
    """返回 ASCII-safe JSON；调用方读取 stdout，不创建清单文件。"""
    payload = {
        'schema_version': '1.0',
        'personas': [_list_record(persona) for persona in personas],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2)


def render_personas_text(personas: list) -> str:
    """返回不依赖中日韩字符显示宽度的分块文本。"""
    if not personas:
        return f'{PERSONAS_DIR} 下无 persona 文件'
    lines = [f'共 {len(personas)} 个 persona', '']
    for index, persona in enumerate(personas):
        item = _list_record(persona)
        start = item['distill_start'] or '未知'
        end = item['distill_end'] or '未知'
        focus = item['focus'] or '未填写'
        lines.extend([
            f"- {item['name']}（{item['w3']}）",
            f'  蒸馏范围：{start} ~ {end}',
            f"  规则数：{item['rule_count']}",
            f'  关注领域：{focus}',
        ])
        if index != len(personas) - 1:
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
    parser.add_argument('--name', default='', help='按姓名匹配')
    parser.add_argument('--w3', default='', help='按工号匹配')
    args = parser.parse_args()

    if args.list:
        personas = list_personas()
        renderer = render_personas_json if args.format == 'json' else render_personas_text
        print(renderer(personas))
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
