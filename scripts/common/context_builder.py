"""根据文件路径和行号构建代码上下文。

输入 file_path + line + diff_map（来自 codehub_client.get_mr_diff 或 diff_parser），
输出 code_context（带 `>>` 目标行标记）、context_start_line、context_end_line。
来源：legacy test_full_export.py build_context。
"""

CONTEXT_LINES = 3


def build_context(line_map: dict, target_line: int):
    """构建代码上下文。返回 (context_str, start, end)，无法构建时返回 (None, None, None)。"""
    if not line_map or target_line not in line_map:
        return None, None, None
    min_line = min(line_map.keys())
    max_line = max(line_map.keys())
    start = max(target_line - CONTEXT_LINES, min_line)
    end = min(target_line + CONTEXT_LINES, max_line)
    context_lines = []
    for ln in range(start, end + 1):
        content = line_map.get(ln, '')
        marker = ' >>' if ln == target_line else '   '
        context_lines.append(f'{marker} {ln}: {content}')
    return '\n'.join(context_lines), start, end
