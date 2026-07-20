"""校验 persona 草稿并自动启用，只保留最近一个 previous 备份。

模型始终先写 outputs/generated_personas/ 草稿；本脚本负责确定性校验、备份和原子安装。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.paths import (  # noqa: E402
    PERSONAS_DIR, PERSONA_BACKUP_DIR, ensure_dirs,
)
from common.persona import parse_persona, validate_persona  # noqa: E402


def _safe_name(name: str) -> str:
    value = re.sub(r'[^A-Za-z0-9._\-\u4e00-\u9fff]+', '-', name).strip('-')
    if not value or value in {'.', '..'}:
        raise ValueError(f'无法生成安全的 persona 文件名: {name!r}')
    return value


def _structured_meta(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    meta = data.get('meta') or {}
    required = ('reviewer_name', 'reviewer_w3', 'total_reviews',
                'distill_start', 'distill_end', 'prepared_at')
    missing = [key for key in required if meta.get(key) in ('', None)]
    if missing:
        raise ValueError(f'structured.meta 缺少字段: {", ".join(missing)}')
    return meta


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=destination.parent, prefix=f'.{destination.name}.',
        suffix='.tmp', delete=False,
    ) as tmp:
        temp_path = Path(tmp.name)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _install_draft(draft: Path, active_path: Path) -> None:
    os.replace(draft, active_path)


def activate_persona(draft: Path, structured: Path, draft_only: bool = False,
                     personas_dir: Path = PERSONAS_DIR,
                     backup_dir: Path = PERSONA_BACKUP_DIR) -> dict:
    """校验并启用草稿。测试可注入临时 personas/backup 目录。"""
    ensure_dirs()
    draft, structured = Path(draft), Path(structured)
    personas_dir, backup_dir = Path(personas_dir), Path(backup_dir)
    warnings = []
    meta = _structured_meta(structured)
    info = validate_persona(draft, expected=meta)
    if draft_only:
        return {
            'status': 'validated_draft', 'draft': str(draft),
            'active': '', 'backup': '', 'persona': info,
        }

    personas_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    canonical_name = (
        f'reviewer-{_safe_name(info["name"])}-{info["w3"]}.skill.md')
    active_path = personas_dir / canonical_name

    same_reviewer = []
    for path in sorted(personas_dir.glob('*.skill.md')):
        parsed = parse_persona(path)
        if parsed.get('w3') == info['w3']:
            same_reviewer.append(path)
    if len(same_reviewer) > 1:
        paths = '\n'.join(f'- {path}' for path in same_reviewer)
        raise ValueError(f'正式目录存在多个同工号 persona，请先处理：\n{paths}')
    if active_path.exists() and active_path not in same_reviewer:
        raise ValueError(f'目标文件已被其他 persona 占用: {active_path}')

    previous_path = None
    previous_snapshot = None
    old_active = same_reviewer[0] if same_reviewer else None
    if old_active:
        previous_path = backup_dir / (
            f'reviewer-{_safe_name(info["name"])}-{info["w3"]}.previous.skill.md')
        if previous_path.exists():
            previous_snapshot = backup_dir / f'.{info["w3"]}.previous.rollback'
            _copy_atomic(previous_path, previous_snapshot)
        try:
            _copy_atomic(old_active, previous_path)
            # outputs/ 与 personas/ 同属 skill 根，替换后正式文件不会出现半写状态。
            _install_draft(draft, active_path)
        except OSError:
            if previous_snapshot and previous_snapshot.exists():
                os.replace(previous_snapshot, previous_path)
            elif previous_path.exists():
                previous_path.unlink()
            raise
        finally:
            if previous_snapshot and previous_snapshot.exists():
                previous_snapshot.unlink()
        for stale in backup_dir.glob(
                f'reviewer-*-{info["w3"]}.previous.skill.md'):
            if stale != previous_path:
                try:
                    stale.unlink()
                except OSError as error:
                    warnings.append(f'未能清理旧 previous {stale}: {error}')
    else:
        _install_draft(draft, active_path)

    if old_active and old_active != active_path and old_active.exists():
        try:
            old_active.unlink()
        except OSError as error:
            warnings.append(f'未能清理旧姓名 persona {old_active}: {error}')
    installed = parse_persona(active_path)
    if installed['w3'] != info['w3']:
        raise RuntimeError('persona 安装后校验异常')
    return {
        'status': 'activated', 'draft': '', 'active': str(active_path),
        'backup': str(previous_path) if previous_path else '',
        'persona': installed, 'warnings': warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='校验并启用 persona 草稿')
    parser.add_argument('--draft', required=True, help='模型生成的 persona 草稿')
    parser.add_argument('--structured', required=True, help='本次蒸馏 structured JSON')
    parser.add_argument('--draft-only', action='store_true', help='只校验，不启用')
    args = parser.parse_args()
    try:
        result = activate_persona(
            Path(args.draft), Path(args.structured), draft_only=args.draft_only)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        print(f'正式 persona 未修改；草稿保留：{args.draft}', file=sys.stderr)
        raise SystemExit(1)
    if result['status'] == 'validated_draft':
        print(f'persona 草稿校验通过，未启用：{result["draft"]}')
    else:
        print(f'persona 已生成并启用：{result["active"]}')
        if result['backup']:
            print(f'上一版本备份：{result["backup"]}')
        for warning in result.get('warnings', []):
            print(f'警告：{warning}')
        print(f'现在可执行：/code-review review --commit <commit> '
              f'--persona {result["persona"]["w3"]}')


if __name__ == '__main__':
    main()
