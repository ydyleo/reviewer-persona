"""运行产物的确定性 JSON 写入辅助。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def write_json(path: Path, data: dict) -> None:
    """同目录临时文件 + replace，避免中途失败留下半份 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        'w', encoding='utf-8', dir=path.parent, delete=False,
        prefix=f'.{path.name}.', suffix='.tmp',
    ) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.write('\n')
        temp_name = tmp.name
    os.replace(temp_name, path)
