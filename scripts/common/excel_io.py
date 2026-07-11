"""Excel 读写。

读阿基米德原始导出 Excel；写 enriched Excel（人工检查用，带列宽）。
enriched Excel 不是蒸馏首选输入——后续蒸馏优先读 enriched JSONL。
来源：legacy test_full_export.py 的 read_excel / 导出 Excel 段。
"""
import warnings

import pandas as pd
from openpyxl.utils import get_column_letter

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# enriched Excel 列宽
_COLUMN_WIDTHS = {
    '代码上下文': 50, '检视意见': 30, '检视地址': 35, '检视文件': 25,
    'code_context': 50, 'comment': 30, 'link': 35, 'file_path': 25,
}


def read_archimedes_excel(xlsx_path: str) -> pd.DataFrame:
    """读取阿基米德导出的原始 Excel。"""
    return pd.read_excel(xlsx_path)


def write_enriched_excel(records: list, output_file: str,
                         sheet_name: str = '评审意见') -> str:
    """写 enriched Excel，自动设列宽；文件被占用时回退到 _new.xlsx。返回实际写入路径。"""
    df = pd.DataFrame(records)
    try:
        return _write(df, output_file, sheet_name)
    except PermissionError:
        fallback = output_file.rsplit('.', 1)[0] + '_new.xlsx'
        return _write(df, fallback, sheet_name)


def _write(df: pd.DataFrame, output_file: str, sheet_name: str) -> str:
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        worksheet = writer.sheets[sheet_name]
        for i, col in enumerate(df.columns):
            col_letter = get_column_letter(i + 1)
            width = _COLUMN_WIDTHS.get(col, 15)
            worksheet.column_dimensions[col_letter].width = width
    return output_file
