"""CodeHub API 客户端。

reviews 接口的用途不是全量收集评论，而是根据阿基米德 Excel 中的
project_path / mr_iid / note_hash 反查评论详情，补充 file_path / line / severity。
来源：legacy test_full_export.py 的 get_user_id / get_mr_diff / get_reviews_for_project。

- token 从 .env 配置文件读取（回退环境变量 CODEHUB_TOKEN），不写进代码。
- 内网自签证书：verify=False，抑制 urllib3 InsecureRequestWarning（有意为之）。
- regions 对应地域选择。
"""
import sys

import requests
import urllib3

from common.config import get_secret  # .env 优先，环境变量回退

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REGIONS = {
    'codehub-y': 'codehub-y',
    'codehub-g': 'codehub-g',
    'cr-y.codehub': 'cr-y.codehub',
    'open.codehub': 'open.codehub',
}

# 地域序号映射（保留 legacy 交互输入兼容）
REGION_BY_INDEX = {
    '1': 'codehub-y',
    '2': 'codehub-g',
    '3': 'cr-y.codehub',
    '4': 'open.codehub',
}


def _log(msg: str) -> None:
    print(msg)
    sys.stdout.flush()


def _headers(token: str) -> dict:
    if not token:
        raise RuntimeError('CODEHUB_TOKEN 未设置（请在 .env 填入 CODEHUB_TOKEN，或 export CODEHUB_TOKEN）')
    return {'PRIVATE-TOKEN': token}


def _encoded_path(project_path: str) -> str:
    return project_path.replace('/', '%2F')


class CodeHubClient:
    def __init__(self, domain: str, token: str = None, timeout: int = 30):
        if domain not in REGIONS:
            raise ValueError(f'未知地域 {domain}，可选: {list(REGIONS)}')
        self.domain = domain
        self.token = token or get_secret('CODEHUB_TOKEN')
        self.timeout = timeout
        self.base = f'https://{domain}.huawei.com/api/v4'

    def get_user_id(self, username: str):
        """通过工号获取 CodeHub 数字用户 ID。返回 (user_id, name) 或 (None, None)。"""
        url = f'{self.base}/users?username={username}'
        try:
            resp = requests.get(url, headers=_headers(self.token),
                                verify=False, timeout=self.timeout).json()
            if resp and isinstance(resp, list):
                user_id = resp[0]['id']
                name = resp[0].get('name_cn', resp[0].get('name', ''))
                _log(f'  用户ID: {user_id}，姓名: {name}，工号: {username}')
                return user_id, name
            _log(f'  未找到工号为 {username} 的用户')
            return None, None
        except Exception as e:
            _log(f'  获取用户ID失败: {e}')
            return None, None

    def get_reviews_for_project(self, project_path: str, user_id):
        """获取某项目中指定检视人的评审意见（分页，proposer_id 过滤）。"""
        encoded = _encoded_path(project_path)
        all_reviews = []
        n = 1
        while True:
            url = (f'{self.base}/projects/{encoded}/reviews'
                   f'?page={n}&per_page=100&proposer_id={user_id}&noteable_type=MergeRequest')
            try:
                raw = requests.get(url, headers=_headers(self.token),
                                   verify=False, timeout=self.timeout)
                if raw.status_code != 200:
                    _log(f'  项目 {project_path} reviews 请求失败，状态码: {raw.status_code}')
                    break
                resp = raw.json()
            except Exception as e:
                _log(f'  获取项目 {project_path} 评审意见失败: {e}')
                break
            if not isinstance(resp, list):
                break
            all_reviews.extend(resp)
            if len(resp) == 100:
                n += 1
            else:
                break
        return all_reviews

    def get_mr_diff(self, project_path: str, mr_iid):
        """获取 MR 的 diff。返回 {file_path(new_path): diff_text}。"""
        encoded = _encoded_path(project_path)
        url = (f'{self.base}/projects/{encoded}/merge_requests/{mr_iid}'
               f'/changes?view=simple')
        try:
            resp = requests.get(url, headers=_headers(self.token),
                                verify=False, timeout=self.timeout).json()
            diff_map = {}
            for change in resp.get('changes', []):
                file_path = change.get('new_path', '')
                diff_text = change.get('diff', '')
                if file_path and diff_text:
                    diff_map[file_path] = diff_text
            return diff_map
        except Exception as e:
            _log(f'  获取 MR {mr_iid} diff 失败: {e}')
            return {}
