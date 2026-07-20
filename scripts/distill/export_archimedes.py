"""从阿基米德平台导出检视评审意见 Excel。

来源：legacy ajimide_export.py，重构为正式脚本。
- 登录态放 cache/archimedes_session/（勿提交）。
- 输出锚定 outputs/raw_archimedes/（走 common.paths，不传 --output-dir）。
- 首次运行需用户在 Playwright 浏览器里手动完成登录（不要 --headless）。

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/distill/export_archimedes.py \
        --reviewer-w3 z00000001 --start 2024-07-01 --end 2026-01-01
"""
import argparse
import re
import warnings
import time
from pathlib import Path
from urllib.parse import urlencode, unquote
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # code-review/scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.paths import RAW_ARCHIMEDES_DIR, ARCHIMEDES_SESSION_DIR, ensure_dirs  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

from playwright.sync_api import (  # noqa: E402
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

try:
    import pandas as pd
except ImportError:
    pd = None

PAGE_URL = "https://ajimide.huawei.com/dataDrill/codeV2/drill/reviewDetail"
EXCEL_API_MARK = "/code-v2-provider/mr/detail/review/excel"
AUTH_FILENAME = "ajimide_auth.json"


def _auth_path() -> Path:
    return ARCHIMEDES_SESSION_DIR / AUTH_FILENAME


def parse_filename(content_disposition: str, default_name: str) -> str:
    if not content_disposition:
        return default_name
    match = re.search(r'filename="?([^";]+)"?', content_disposition)
    if not match:
        return default_name
    filename = unquote(match.group(1))
    return filename or default_name


LOGIN_TIMEOUT = 300  # 等待用户登录的超时秒数（5 分钟）


def _try_open_target_after_login(page, target_url: str) -> None:
    """登录轮询期间尽力回到目标页；页面跳转瞬时失败时由下一轮重试。"""
    if not target_url or page.url == target_url:
        return
    current_url = page.url.lower()
    if 'login' in current_url or 'passport' in current_url:
        return
    try:
        page.goto(target_url, wait_until='domcontentloaded', timeout=30_000)
        page.wait_for_timeout(2000)
    except PlaywrightError:
        return


def _try_save_login_state(page, auth_path: Path) -> bool:
    """检测导出按钮并保存登录态；瞬时 DOM/页面错误返回 False。"""
    try:
        button = page.get_by_text('导出数据', exact=False)
        if button.count() <= 0 or not button.first.is_visible():
            return False
        page.context.storage_state(path=str(auth_path))
        return True
    except PlaywrightError:
        return False


def wait_for_login(page, auth_path: Path, target_url: str,
                   timeout_seconds: int = LOGIN_TIMEOUT):
    """等待用户完成登录并跳转到目标页面。

    登录成功的判定信号：页面上出现「导出数据」按钮（可见且可点击）。
    这个按钮只有登录成功 + 页面加载完毕才会出现，比检测 URL 更可靠。
    检测到后自动保存 storage_state。
    超时后抛出 RuntimeError，不静默跳过。
    """
    print("请在浏览器中完成登录，脚本将持续检测「导出数据」按钮"
          f"（超时 {timeout_seconds} 秒）...")
    start = time.time()
    while time.time() - start < timeout_seconds:
        _try_open_target_after_login(page, target_url)
        if _try_save_login_state(page, auth_path):
            print(f"检测到登录成功，登录状态已保存到 {auth_path}")
            return
        time.sleep(2)
    raise RuntimeError(
        f"登录超时（{timeout_seconds} 秒）。请在浏览器中完成登录后重新运行本脚本。")


def get_reviewer_name_from_excel(xlsx_path: Path, w3_account: str) -> str:
    if pd is None:
        return ""
    try:
        df = pd.read_excel(str(xlsx_path))
        if '检视人W3' in df.columns and '检视人姓名' in df.columns:
            match = df[df['检视人W3'] == w3_account]['检视人姓名'].dropna()
            if not match.empty:
                return str(match.iloc[0])
    except Exception as e:
        print(f'读取检视人姓名失败: {e}')
    return ""


def rename_export_file(xlsx_path: Path, reviewer_name: str, w3_account: str,
                        start: str, end: str) -> Path:
    """按命名规则：{姓名}_{工号}_{start}_{end}_archimedes.xlsx。"""
    if reviewer_name:
        new_name = f"{reviewer_name}_{w3_account}_{start}_{end}_archimedes.xlsx"
    else:
        new_name = f"{w3_account}_{start}_{end}_archimedes.xlsx"
    new_path = xlsx_path.parent / new_name
    if new_path.exists():
        new_path.unlink()
    xlsx_path.rename(new_path)
    return new_path


def export_review_excel(start: str, end: str, w3_account: str,
                        reviewer_name: str = "", headless: bool = False) -> Path:
    ensure_dirs()
    output_path = RAW_ARCHIMEDES_DIR
    output_path.mkdir(parents=True, exist_ok=True)

    query = {"start": start, "end": end, "repoUuid": "", "w3Account": w3_account}
    page_url = f"{PAGE_URL}?{urlencode(query)}"
    auth_path = _auth_path()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        if auth_path.exists():
            print(f"检测到已保存的登录态 {auth_path}，正在复用...")
            context = browser.new_context(storage_state=str(auth_path))
        else:
            context = browser.new_context()
        page = context.new_page()

        print(f"打开页面：{page_url}")
        page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)  # 等待页面 JS 完成渲染

        current_url = page.url
        if "login" in current_url.lower() or "passport" in current_url.lower():
            print("检测到需要登录。")
            wait_for_login(page, auth_path, page_url)
            # 登录成功后页面已就绪，无需重新 goto

        try:
            with page.expect_response(
                lambda response: EXCEL_API_MARK in response.url
                and response.status in (200, 201),
                timeout=120_000,
            ) as response_info:
                page.get_by_text("导出数据", exact=False).click()

            response = response_info.value
            headers = response.headers
            body = response.body()

            content_type = headers.get("content-type", "")
            if ("spreadsheetml.sheet" not in content_type
                    and "octet-stream" not in content_type):
                if auth_path.exists():
                    print("登录态可能已过期，正在清除旧状态...")
                    auth_path.unlink()
                raise RuntimeError(
                    f"返回内容不像 Excel，content-type={content_type}，"
                    f"可能是登录失效或接口返回异常。请重新运行完成登录。")

            default_filename = f"review_detail_{w3_account}_{start}_{end}.xlsx"
            filename = parse_filename(
                headers.get("content-disposition", ""), default_filename)
            if not filename.endswith(".xlsx"):
                filename = default_filename

            file_path = output_path / filename
            file_path.write_bytes(body)

            excel_name = get_reviewer_name_from_excel(file_path, w3_account)
            if excel_name:
                if reviewer_name and reviewer_name != excel_name:
                    print(f'提示：输入姓名"{reviewer_name}"与实际"{excel_name}"不一致，已自动更正')
                final_name = excel_name
            elif reviewer_name:
                final_name = reviewer_name
            else:
                final_name = ""
            if final_name:
                print(f"检视人：{final_name}（{w3_account}）")
            new_path = rename_export_file(file_path, final_name, w3_account, start, end)
            print(f"导出成功：{new_path}")
            return new_path

        except PlaywrightTimeoutError:
            print("导出超时。可能原因：页面未登录 / 按钮文字非'导出数据' / "
                  "导出接口未触发 / 页面加载慢 / 登录态过期（删除 "
                  f"{auth_path} 后重试）")
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从阿基米德导出检视评审意见 Excel")
    parser.add_argument("--reviewer-w3", required=True, help="检视人 w3 账号（工号），如 z00000001")
    parser.add_argument("--start", required=True, help="开始日期，如 2024-07-01")
    parser.add_argument("--end", required=True, help="结束日期（含当天数据则设为次日）")
    parser.add_argument("--name", default="", help="检视人姓名，不填则从导出数据自动获取")
    parser.add_argument("--headless", action="store_true",
                        help="无头模式（首次登录不建议使用）")
    args = parser.parse_args()
    export_review_excel(
        start=args.start, end=args.end, w3_account=args.reviewer_w3,
        reviewer_name=args.name, headless=args.headless,
    )
