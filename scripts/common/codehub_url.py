"""零网络依赖的 CodeHub domain 与阿基米德检视地址解析。"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from common.output_layout import normalize_domain

REGIONS = {
    'codehub-y': 'codehub-y',
    'codehub-g': 'codehub-g',
    'cr-y.codehub': 'cr-y.codehub',
    'open.codehub': 'open.codehub',
}


def normalize_codehub_domain(value: str) -> str:
    """统一 domain/host/URL 并严格限制为已支持的 CodeHub 地域。"""
    domain = normalize_domain(value)
    if domain not in REGIONS:
        raise ValueError(f'未知 CodeHub 地域 {domain}，可选: {list(REGIONS)}')
    return domain


def parse_review_url(link: str, expected_domain: str = '') -> dict:
    """解析阿基米德检视地址，返回 domain/project/mr/note 的完整身份。"""
    value = str(link or '').strip()
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('检视地址必须是带 http/https host 的完整 URL')
    domain = normalize_codehub_domain(parsed.hostname)
    if expected_domain:
        wanted = normalize_codehub_domain(expected_domain)
        if domain != wanted:
            raise ValueError(f'URL domain={domain} 与显式 --domain={wanted} 不一致')
    route = re.match(r'^/(.+)/merge_requests/(\d+)(?:/.*)?$', parsed.path)
    if not route:
        raise ValueError('检视地址缺少 /<project>/merge_requests/<iid>')
    project_path = unquote(route.group(1)).strip('/')
    parts = PurePosixPath(project_path).parts
    if not parts or any(part in {'', '.', '..'} for part in parts):
        raise ValueError('检视地址包含非法 project_path')
    note = re.match(r'^note_(.+)$', parsed.fragment or '')
    if not note:
        raise ValueError('检视地址缺少 #note_<id>')
    return {
        'domain': domain,
        'project_path': project_path,
        'mr_iid': route.group(2),
        'note_hash': note.group(1),
    }
