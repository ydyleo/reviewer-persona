"""enriched JSONL 读写。

enriched JSONL 是后续蒸馏的标准输入（优先于 Excel）。
字段取英文 key。
阿基米德 Excel 的中文列在此映射为英文 key。
"""
import json

# 中文 Excel 列名 → 英文 key
CN_TO_EN = {
    '检视人姓名': 'reviewer_name',
    '检视人W3': 'reviewer_w3',
    '提交人姓名': 'submitter_name',
    '提交人W3': 'submitter_w3',
    '检视意见': 'comment',
    '类型': 'mr_type',
    'MR状态': 'mr_status',
    '创建时间': 'created_at',
    '检视地址': 'link',
    '解决时间': 'resolved_at',
    '检视文件': 'file_path',
    '检视意见行': 'line',
    '严重程度': 'severity',
    'API评论匹配状态': 'api_review_match_status',
    '上下文匹配状态': 'context_status',
    '代码上下文': 'code_context',
    '上下文起始行': 'context_start_line',
    '上下文结束行': 'context_end_line',
}


def normalize_record(row: dict) -> dict:
    """把阿基米德/Excel 的中文 key 记录归一化为英文 key 记录。

    已是英文 key 的字段原样保留；domain / project_path / mr_iid / note_hash /
    is_test_file / language / error_detail 由 enrich 阶段补入。
    """
    out = {}
    for k, v in row.items():
        out[CN_TO_EN.get(k, k)] = v
    return out


def write_jsonl(records: list, output_file: str) -> int:
    """逐行写 JSONL。返回写入条数。"""
    with open(output_file, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
    return len(records)


def read_jsonl(input_file: str) -> list:
    """逐行读 JSONL。"""
    records = []
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
