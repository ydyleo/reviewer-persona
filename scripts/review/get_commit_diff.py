"""获取评审目标的 diff，输出结构化 diff JSON + Markdown。

支持两种 diff 源（互斥）：
- --commit：从本地 Git 仓取 commit 相对父节点的 diff（auto-fetch、测试代码排除）。
- --mr：从 CodeHub 取某 MR 的 diff（benchmark 用：和真人当时评的是同一份 diff，行号天然对齐）。

两种源走同一套 split/status/排除/装配/输出管线，只是 diff 来源不同，
下游 review Step 3（模型）读 files[] 不区分来源。

来源逻辑：旧 huawei_code_review/SKILL.md Step 2/3（commit 校验、auto-fetch、测试代码排除）。
- --repo 可选，不传默认当前工作目录；git 命令统一 git -C <repo>。
- --mr 模式需要 --domain 与 --mr <project_path>/<mr_iid>。
- 排除测试代码（testcode/、*_test.cpp、*_llt.cpp、LLT_*.cpp 等）。
- 中间 diff 输出到 outputs/diffs/（锚定 skill 根，不写入目标仓）。

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/review/get_commit_diff.py --commit abc123
    python <SKILL_ROOT>/scripts/review/get_commit_diff.py --repo /path/to/repo --commit abc123
    python <SKILL_ROOT>/scripts/review/get_commit_diff.py --mr hw-xxx/svc/42 --domain codehub-g
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


def _file_status(file_diff: str) -> str:
    """从单文件 diff 文本判定状态：A 新增 / D 删除 / M 修改。

    commit 模式与 MR 模式共用，保证两边状态判定一致。
    """
    if re.search(r'^new file mode 0000000', file_diff, re.MULTILINE):
        return 'D'
    if re.search(r'^new file mode', file_diff, re.MULTILINE):
        return 'A'
    return 'M'


def split_diff_by_file(diff_text: str):
    """把整段 git diff 按文件拆成 [(file_path, status, file_diff_text)]。"""
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
        files.append((file_path, _file_status(part), part))
    return files


def _assemble_files(files_split):
    """应用测试代码排除 + 语言识别，装配 files[]。commit/MR 共用。"""
    kept, excluded = [], 0
    for file_path, status, file_diff in files_split:
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
    return kept, excluded


def _write_diff_output(out_stem: str, title: str, meta_lines: list,
                       files_split, extra_meta: dict) -> dict:
    """装配 + 写 {out_stem}.json/.md，返回 result。commit/MR 共用。"""
    ensure_dirs()
    kept, excluded = _assemble_files(files_split)
    result = {
        **extra_meta,
        'total_files': len(files_split),
        'kept_files': len(kept),
        'excluded_test_files': excluded,
        'files': kept,
    }
    json_out = DIFFS_DIR / f'{out_stem}.json'
    md_out = DIFFS_DIR / f'{out_stem}.md'
    with open(json_out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(md_out, 'w', encoding='utf-8') as f:
        f.write(f'# {title}\n\n')
        for line in meta_lines:
            f.write(f'{line}\n')
        f.write(f'文件: {len(kept)} 个（排除测试代码 {excluded} 个）\n\n---\n\n')
        for fi in kept:
            f.write(f'## {fi["file_path"]} ({fi["status"]}, {fi["language"]})\n\n')
            f.write('```diff\n')
            f.write(fi['diff_text'])
            f.write('\n```\n\n')

    print(f'diff 输出：\n  {json_out}\n  {md_out}')
    print(f'  保留 {len(kept)} 个文件（排除 {excluded} 个测试文件）')
    return result


def get_commit_diff(repo: str, commit: str) -> dict:
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

    files_split = split_diff_by_file(raw)
    return _write_diff_output(
        out_stem=f'{commit}_diff',
        title=f'Commit {commit} diff',
        meta_lines=[f'仓库: {Path(repo).resolve()}'],
        files_split=files_split,
        extra_meta={'commit': commit, 'repo': str(Path(repo).resolve())},
    )


def get_mr_review_diff(domain: str, project_path: str, mr_iid) -> dict:
    """从 CodeHub 取 MR diff，走同一套装配/输出管线。

    benchmark 主路径：AI 评的 diff = 真人当时评的那份，行号天然对齐，
    避开走 merge_commit_sha 的 squash/rebase diff 不一致噪声。
    产物 outputs/diffs/{mr_iid}_mrdiff.json/.md，files[] 形状与 commit 模式一致。
    """
    from common.codehub_client import CodeHubClient
    client = CodeHubClient(domain=domain)
    diff_map = client.get_mr_diff(project_path, mr_iid)  # {new_path: diff_text}
    if not diff_map:
        raise RuntimeError(
            f'MR {project_path} !{mr_iid} 未取到 diff。可能 MR 不存在/已关闭/接口异常。')
    # 每个文件 diff 自带 diff --git 头；用 split 复用 status 判定。
    # 若 diff 无头（API 裁剪），直接按 new_path 建，状态用 _file_status。
    files_split = split_diff_by_file('\n'.join(diff_map.values()))
    if not files_split:
        files_split = [(p, _file_status(d), d) for p, d in diff_map.items()]
    return _write_diff_output(
        out_stem=f'{mr_iid}_mrdiff',
        title=f'MR {project_path} !{mr_iid} diff',
        meta_lines=[f'MR: {project_path} !{mr_iid}', f'domain: {domain}'],
        files_split=files_split,
        extra_meta={
            'mr_iid': mr_iid, 'project_path': project_path, 'domain': domain,
        },
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='获取评审目标 diff（commit 或 MR）')
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument('--commit', help='commit ID（走本地 Git）')
    src.add_argument('--mr', help='MR，格式 <project_path>/<mr_iid>（走 CodeHub，需 --domain）')
    parser.add_argument('--repo', default='.', help='目标 Git 仓库（仅 --commit 用，默认当前目录）')
    parser.add_argument('--domain', help='CodeHub 地域（仅 --mr 用，如 codehub-g）')
    args = parser.parse_args()

    if args.commit:
        get_commit_diff(repo=args.repo, commit=args.commit)
    else:
        if not args.domain:
            parser.error('--mr 必须配合 --domain（如 codehub-g）')
        project, _, iid = args.mr.rpartition('/')
        if not project or not iid:
            parser.error('--mr 格式应为 <project_path>/<mr_iid>，如 hw-xxx/svc/42')
        get_mr_review_diff(domain=args.domain, project_path=project, mr_iid=iid)
