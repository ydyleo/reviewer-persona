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
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # code-review/scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.paths import PERSONAS_DIR  # noqa: E402

_RULE_HEADING_RE = re.compile(r'^###\s+([SPBACD])\d+', re.MULTILINE)
# 文件名 reviewer-{姓名}-{工号}.skill.md
_FILENAME_RE = re.compile(r'^reviewer-(.+)-([a-zA-Z0-9]+)\.skill\.md$')
# 标题 # 评审人格分身：【{name} {w3}】
_TITLE_RE = re.compile(r'#\s*评审人格分身：【(.+?)\s+([a-zA-Z0-9]+)】')


def _parse_persona(path: Path) -> dict:
    text = path.read_text(encoding='utf-8')
    name, w3 = '', ''
    m = _TITLE_RE.search(text)
    if m:
        name, w3 = m.group(1).strip(), m.group(2).strip()
    if not name or not w3:
        fm = _FILENAME_RE.match(path.name)
        if fm:
            name = name or fm.group(1)
            w3 = w3 or fm.group(2)
    rule_count = len(_RULE_HEADING_RE.findall(text))
    # 关注领域（粗提取 ## 核心评审偏好 下第一行）
    focus = ''
    fm2 = re.search(r'##\s*核心评审偏好\s*\n\s*[^-\n]*?：\s*(.+)', text)
    if fm2:
        focus = fm2.group(1).strip()[:60]
    return {'file': str(path), 'name': name, 'w3': w3,
            'rule_count': rule_count, 'focus': focus}


def list_personas() -> list:
    if not PERSONAS_DIR.exists():
        return []
    personas = []
    for p in sorted(PERSONAS_DIR.glob('*.skill.md')):
        personas.append(_parse_persona(p))
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
        print(f'{"姓名":<10}{"工号":<14}{"规则数":<8}关注领域')
        print('-' * 70)
        for p in personas:
            print(f"{p['name']:<10}{p['w3']:<14}{p['rule_count']:<8}{p['focus']}")
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
