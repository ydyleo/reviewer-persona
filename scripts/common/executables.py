"""外部可执行文件解析。"""
from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def executable_path(name: str) -> str:
    """从 PATH 解析并返回绝对路径，未安装时给出明确错误。"""
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f'未找到外部命令：{name}，请先安装并配置 PATH')
    resolved = Path(found).resolve()
    if not resolved.is_absolute():
        raise RuntimeError(f'无法解析外部命令绝对路径：{name}')
    return str(resolved)
