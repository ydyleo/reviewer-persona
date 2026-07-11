"""配置/密钥读取。

从 skill 根目录的 .env 文件读取 KEY=VALUE，找不到再回退环境变量。
.env 已在 .gitignore，勿提交真实 token。零依赖手动解析（不引入 python-dotenv）。

用法：
    from common.config import get_secret
    token = get_secret('CODEHUB_TOKEN')          # .env 优先，环境变量兜底
"""
import os

from common.paths import SKILL_ROOT

_ENV_FILE = SKILL_ROOT / ".env"


def load_env(path=None) -> dict:
    """解析 .env 文件为 dict。文件不存在返回空 dict，不报错。

    支持 KEY=VALUE、# 注释、值两端引号去除、首尾空白去除。
    """
    target = path or _ENV_FILE
    result = {}
    if not target.exists():
        return result
    try:
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if key:
                    result[key] = value
    except Exception:
        return result
    return result


def get_secret(key: str, default=None):
    """先查 .env 文件值，再回退 os.environ（保留老的环境变量用法）。"""
    value = load_env().get(key)
    if value:
        return value
    return os.environ.get(key, default)
