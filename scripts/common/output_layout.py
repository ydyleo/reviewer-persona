"""review / benchmark 产物目录计算。

目录使用完整对象身份，避免只用 commit 或 mr_iid 导致跨仓库覆盖：
- review: outputs/review/{domain}/{project_path}/commit-{sha}/
- benchmark: outputs/benchmark/{domain}/{project_path}/mr-{iid}/reviewer-{w3}/
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from common.paths import BENCHMARK_DIR, REVIEW_DIR
from common.executables import executable_path

_ROUTE_PARTS = {'merge_requests', 'commits', 'tree', 'blob'}
_SAFE_SEGMENT_RE = re.compile(r'[^A-Za-z0-9._\-\u4e00-\u9fff]+')


def _safe_segment(value: str) -> str:
    value = _SAFE_SEGMENT_RE.sub('-', str(value).strip()).strip('-')
    if not value or value in {'.', '..'}:
        raise ValueError(f'非法路径片段: {value!r}')
    return value


def normalize_domain(domain: str) -> str:
    """把 codehub-g.huawei.com / codehub-g 统一成目录键 codehub-g。"""
    value = str(domain or '').strip().lower()
    if '://' in value:
        value = urlparse(value).hostname or value
    value = value.split('@')[-1].split(':')[0]
    if value.endswith('.huawei.com'):
        value = value[:-len('.huawei.com')]
    return _safe_segment(value or 'local')


def normalize_project_path(project_path: str, strip_page_route: bool = False) -> tuple[str, ...]:
    """规范化 CodeHub project_path；解析网页 URL 时可剥离页面路由。"""
    raw = str(project_path or '').strip().strip('/')
    parts = [part for part in PurePosixPath(raw).parts if part not in {'', '/'}]
    if strip_page_route:
        for i, part in enumerate(parts):
            if part in _ROUTE_PARTS:
                parts = parts[:i]
                break
    if parts and parts[-1].endswith('.git'):
        parts[-1] = parts[-1][:-4]
    if not parts:
        raise ValueError(f'无法识别项目路径: {project_path!r}')
    return tuple(_safe_segment(part) for part in parts)


def parse_repository_url(remote_url: str) -> dict:
    """解析 HTTPS/SSH/scp 风格 Git URL，返回 host/domain/project_path。"""
    value = str(remote_url or '').strip()
    if not value:
        raise ValueError('remote URL 为空')

    if '://' in value:
        parsed = urlparse(value)
        host = parsed.hostname or ''
        path = parsed.path
    else:
        match = re.match(r'^(?:[^@]+@)?([^:]+):(.+)$', value)
        if not match:
            raise ValueError(f'无法解析 remote URL: {remote_url}')
        host, path = match.group(1), match.group(2)

    project_parts = normalize_project_path(path, strip_page_route=True)
    return {
        'host': host,
        'domain': normalize_domain(host),
        'project_path': '/'.join(project_parts),
        'project_parts': project_parts,
        'remote_url': value,
    }


def repository_identity(repo: str) -> dict:
    """优先从 origin 推导仓库身份；无 origin 时使用 local/{目录名-短哈希}。"""
    resolved = Path(repo).resolve()
    result = subprocess.run(
        [executable_path('git'), '-C', str(resolved),
         'remote', 'get-url', 'origin'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            identity = parse_repository_url(result.stdout.strip())
        except ValueError:
            identity = None
        if identity is not None:
            identity['local_path'] = str(resolved)
            return identity

    suffix = hashlib.sha256(str(resolved).encode('utf-8')).hexdigest()[:8]
    repo_name = f'{_safe_segment(resolved.name or "repository")}-{suffix}'
    return {
        'host': '',
        'domain': 'local',
        'project_path': repo_name,
        'project_parts': (repo_name,),
        'remote_url': '',
        'local_path': str(resolved),
    }


def review_case_dir(repo: str, commit: str) -> tuple[Path, dict]:
    identity = repository_identity(repo)
    short_sha = _safe_segment(str(commit))[:12]
    output = REVIEW_DIR / identity['domain']
    output = output.joinpath(*identity['project_parts'], f'commit-{short_sha}')
    return output, identity


def benchmark_case_dir(domain: str, project_path: str, mr_iid,
                       reviewer_w3: str) -> Path:
    output = BENCHMARK_DIR / normalize_domain(domain)
    return output.joinpath(
        *normalize_project_path(project_path),
        f'mr-{_safe_segment(str(mr_iid))}',
        f'reviewer-{_safe_segment(reviewer_w3)}',
    )
