"""Unified diff 解析。

第一版优先支持新文件行号（review 评论行号对应 diff 中的 new_path 行号）。
若评论位于旧行或 diff 外上下文，由 context_builder 标记 context_not_found。
来源：legacy test_full_export.py parse_diff_to_lines。
"""
import re

_HUNK_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')


def parse_diff_to_lines(diff_text: str) -> dict:
    """解析 unified diff，返回 {新文件行号: 行内容}。

    - hunk 头 @@ -x,y +a,b @@ 记录新文件起始行号 a。
    - '+' 开头（非 +++）= 新增行，计入 line_map，行号 +1。
    - ' ' 开头 = 上下文行，计入 line_map，行号 +1。
    - '-' 开头（非 ---）= 删除行，不计入，行号不变。
    """
    line_map = {}
    new_line_num = 0
    for line in diff_text.split('\n'):
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            new_line_num = int(hunk_match.group(1))
            continue
        if new_line_num == 0:
            continue
        if line.startswith('+') and not line.startswith('+++'):
            line_map[new_line_num] = line[1:]
            new_line_num += 1
        elif line.startswith('-') and not line.startswith('---'):
            continue
        elif line.startswith(' '):
            line_map[new_line_num] = line[1:]
            new_line_num += 1
    return line_map
