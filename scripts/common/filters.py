"""轻量噪声评论过滤。

为减少不必要的 CodeHub API 请求，enrich 阶段可在调用 API 前做保守预过滤，
跳过明显没有评审价值的短回复。这不是最终语义判断——
不要把风险追问、验证要求、边界确认类评论误删（例如"降低权限后有验证发放 pod 吗"不是噪声）。
prepare_review_data.py 也复用同一过滤做防御性清理。
来源：legacy test_full_export.py is_noise_comment，并补充常见噪声示例词。
"""
import re

_NOISE_WORDS = {
    '', 'lgtm', 'lg', 'ok', 'okay', '+1', 'done', 'fixed', 'pass',
    '通过', '已处理', '已修改', '已改', '已解决', '修改了', '好的', '好',
    '收到', '同意', '辛苦', '辛苦了', '看了', '没问题', '无问题', '可以',
}

_NOISE_PATTERNS = [
    r'^lgtm[\.。!！]*$',
    r'^ok[\.。!！]*$',
    r'^ok了$',
    r'^已处理[\.。!！]*$',
    r'^已修改[\.。!！]*$',
    r'^已改[\.。!！]*$',
    r'^已解决[\.。!！]*$',
    r'^收到[\.。!！]*$',
    r'^同意[\.。!！]*$',
    r'^辛苦[了!！.。]*$',
]


def is_noise_comment(comment) -> bool:
    """判断是否是无效/低价值评审意见。"""
    if comment is None:
        return True
    text = str(comment).strip().lower()
    normalized = re.sub(r'[\s。.!！?？,，;；~～]+', '', text)
    if normalized in _NOISE_WORDS:
        return True
    for pattern in _NOISE_PATTERNS:
        if re.match(pattern, text):
            return True
    return False
