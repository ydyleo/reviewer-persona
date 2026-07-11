"""获取目标 commit 的 diff，输出结构化 diff JSON + Markdown。

来源逻辑：旧 huawei_code_review/SKILL.md Step 2/3（commit 校验、auto-fetch、测试代码排除）。
- --repo 可选，不传默认当前工作目录；git 命令统一 git -C <repo>。
- 校验 commit 存在，不存在则 git fetch + pull 后复查。
- 排除测试代码（testcode/、*_test.cpp、*_llt.cpp、LLT_*.cpp 等）。
- 中间 diff 输出到 outputs/diffs/（锚定 skill 根，不写入目标仓）。

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/review/get_commit_diff.py --commit abc123
    python <SKILL_ROOT>/scripts/review/get_commit_diff.py --repo /path/to/repo --commit abc123
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # code-review/scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.paths import DIFFS_DIR, ensure_dirs  # noqa: E402

# 测试代码排除（与旧 SKILL.md Step 3 一致）
_TEST_FILE_RE = re.compile(
    r'(testcode/|_test\.cpp$|_llt\.cpp$|LLT_.*\.cpp$|test_.*\.py$|_test\.py$'
    r'|Test\.java$|Tests\.java$|_test\.go$|_test\.rs$)', re.IGNORECASE)

_EXT_LANG = {
    '.cpp': 'C++', '.cc': 'C++', '.cxx': 'C++', '.h': 'C++', '.hpp': 'C++',
    '.c': 'C', '.py': 'Python', '.go': 'Go', '.java': 'Java',
    '.rs': 'Rust', '.sh': 'Shell', '.tf': 'Terraform',
    '.yml': 'YAML', '.yaml': 'YAML',
}


def _git(repo: str, *args, check: bool = True) -> str:
    result = subprocess.run(
        ['git', '-C', repo, *args],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {result.stderr.strip()}")
    return result.stdout


def _is_git_repo(repo: str) -> bool:
    return subprocess.run(
        ['git', '-C', repo, 'rev-parse', '--is-inside-work-tree'],
        capture_output=True, text=True,
    ).returncode == 0


def validate_commit(repo: str, commit: str) -> bool:
    return subprocess.run(
        ['git', '-C', repo, 'cat-file', '-e', f'{commit}^{{commit}}'],
        capture_output=True,
    ).returncode == 0


def ensure_commit(repo: str, commit: str) -> None:
    if validate_commit(repo, commit):
        return
    print(f'commit {commit} 本地不存在，尝试 fetch...')
    try:
        _git(repo, 'fetch', 'origin')
    except RuntimeError as e:
        print(f'fetch 失败: {e}')
    if not validate_commit(repo, commit):
        raise RuntimeError(
            f'commit {commit} 仍不存在。请确认 commit ID 正确，或目标仓已同步。')


def split_diff_by_file(diff_text: str):
    """把整段 git diff 按文件拆成 [(file_path, file_diff_text)]。"""
    if not diff_text:
        return []
    # 以 'diff --git a/... b/...' 为分隔
    parts = re.split(r'(?=^diff --git )', diff_text, flags=re.MULTILINE)
    files = []
    for part in parts:
        m = re.match(r'^diff --git a/(.*?) b/(.*?)\n', part)
        if not m:
            continue
        # 用 +++ 行的路径（rename/copy 时更准），fallback 到 b/ 路径
        new_path_m = re.search(r'^\+\+\+ b/(.+?)$', part, re.MULTILINE)
        file_path = new_path_m.group(1).strip() if new_path_m else m.group(2)
        status = 'D' if re.search(r'^new file mode 0000000', part, re.MULTILINE) \
            else ('A' if re.search(r'^new file mode', part, re.MULTILINE) else 'M')
        files.append((file_path, status, part))
    return files


def get_commit_diff(repo: str, commit: str) -> dict:
    ensure_dirs()
    if not _is_git_repo(repo):
        raise RuntimeError(f'{repo} 不是 Git 仓库。请 cd 到目标仓库或通过 --repo 指定。')
    ensure_commit(repo, commit)

    # 单 commit 相对父节点的 diff
    try:
        raw = _git(repo, 'diff', f'{commit}~1', commit, '--no-color',
                   check=True)
    except RuntimeError:
        # 根 commit（无父节点），退回 git show
        raw = _git(repo, 'show', commit, '--no-color', '--format=', check=True)

    files = split_diff_by_file(raw)
    kept, excluded = [], 0
    for file_path, status, file_diff in files:
        if _TEST_FILE_RE.search(file_path):
            excluded += 1
            continue
        ext = Path(file_path).suffix.lower()
        kept.append({
            'file_path': file_path,
            'status': status,
            'language': _EXT_LANG.get(ext, ''),
            'is_test_file': False,
            'diff_text': file_diff,
        })

    result = {
        'commit': commit,
        'repo': str(Path(repo).resolve()),
        'total_files': len(files),
        'kept_files': len(kept),
        'excluded_test_files': excluded,
        'files': kept,
    }

    json_out = DIFFS_DIR / f'{commit}_diff.json'
    md_out = DIFFS_DIR / f'{commit}_diff.md'
    with open(json_out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    with open(md_out, 'w', encoding='utf-8') as f:
        f.write(f'# Commit {commit} diff\n\n')
        f.write(f'仓库: {result["repo"]}\n')
        f.write(f'文件: {result["kept_files"]} 个'
                f'（排除测试代码 {excluded} 个）\n\n---\n\n')
        for fi in kept:
            f.write(f'## {fi["file_path"]} ({fi["status"]}, {fi["language"]})\n\n')
            f.write('```diff\n')
            f.write(fi['diff_text'])
            f.write('\n```\n\n')

    print(f'diff 输出：\n  {json_out}\n  {md_out}')
    print(f'  保留 {len(kept)} 个文件（排除 {excluded} 个测试文件）')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='获取 commit diff')
    parser.add_argument('--repo', default='.', help='目标 Git 仓库（默认当前目录）')
    parser.add_argument('--commit', required=True, help='commit ID')
    args = parser.parse_args()
    get_commit_diff(repo=args.repo, commit=args.commit)
