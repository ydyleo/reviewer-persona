import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FakePlaywrightError(Exception):
    """测试用 Playwright 瞬时错误。"""


playwright = types.ModuleType('playwright')
playwright.__path__ = []
sync_api = types.ModuleType('playwright.sync_api')
sync_api.Error = FakePlaywrightError
sync_api.TimeoutError = FakePlaywrightError
sync_api.sync_playwright = lambda: None

with patch.dict(sys.modules, {
        'playwright': playwright,
        'playwright.sync_api': sync_api,
}):
    export_archimedes = importlib.import_module('scripts.distill.export_archimedes')


class ExportLoginRetryTest(unittest.TestCase):
    def test_navigation_retries_only_playwright_errors(self):
        class Page:
            url = 'https://example.com/home'

            @staticmethod
            def goto(*_args, **_kwargs):
                raise FakePlaywrightError('页面正在跳转')

        self.assertIsNone(export_archimedes._try_open_target_after_login(
            Page(), 'https://example.com/target'))

    def test_navigation_does_not_hide_programming_errors(self):
        class Page:
            url = 'https://example.com/home'

            @staticmethod
            def goto(*_args, **_kwargs):
                raise RuntimeError('代码错误')

        with self.assertRaisesRegex(RuntimeError, '代码错误'):
            export_archimedes._try_open_target_after_login(
                Page(), 'https://example.com/target')

    def test_login_state_playwright_error_is_explicit_false(self):
        class Page:
            @staticmethod
            def get_by_text(*_args, **_kwargs):
                raise FakePlaywrightError('DOM 正在刷新')

        with tempfile.TemporaryDirectory() as temp:
            saved = export_archimedes._try_save_login_state(
                Page(), Path(temp) / 'auth.json')
        self.assertFalse(saved)


if __name__ == '__main__':
    unittest.main()
