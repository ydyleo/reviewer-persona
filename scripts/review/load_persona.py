"""加载 / 列出 reviewer 人格分身。

- 扫描 personas/*.skill.md
- 支持按姓名或工号匹配
- list-personas 展示 姓名/工号/规则数量

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/review/load_persona.py --list
    python <SKILL_ROOT>/scripts/review/load_persona.py --w3 z00000001
    python <SKILL_ROOT>/scripts/review/load_persona.py --name 张示例
"""
import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # code-review/scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.paths import PERSONAS_DIR  # noqa: E402
from common.persona import parse_persona  # noqa: E402


def list_personas() -> list:
    if not PERSONAS_DIR.exists():
        return []
    personas = []
    for p in sorted(PERSONAS_DIR.glob('*.skill.md')):
        personas.append(parse_persona(p))
    return personas


def find_persona(name: str = None, w3: str = None) -> str:
    """返回匹配的 persona 文件路径，未匹配返回空串。"""
    for p in list_personas():
        if w3 and p['w3'] == w3:
            return p['file']
        if name and p['name'] == name:
            return p['file']
    return ''


def main():
    parser = argparse.ArgumentParser(description='加载/列出 reviewer 人格')
    parser.add_argument('--list', action='store_true', help='列出所有 persona')
    parser.add_argument('--name', default='', help='按姓名匹配')
    parser.add_argument('--w3', default='', help='按工号匹配')
    args = parser.parse_args()

    if args.list:
        personas = list_personas()
        if not personas:
            print(f'{PERSONAS_DIR} 下无 persona 文件')
            return
        print(f'{"姓名":<10}{"工号":<14}{"蒸馏范围":<24}{"规则数":<8}关注领域')
        print('-' * 95)
        for p in personas:
            meta = p.get('metadata') or {}
            period = f"{meta.get('distill_start') or '?'}~{meta.get('distill_end') or '?'}"
            print(f"{p['name']:<10}{p['w3']:<14}{period:<24}"
                  f"{p['rule_count']:<8}{p['focus']}")
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
