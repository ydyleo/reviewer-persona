import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from common.executables import executable_path  # noqa: E402
from common.output_layout import repository_identity  # noqa: E402
from review.get_commit_diff import _git  # noqa: E402


class ExecutablePathTest(unittest.TestCase):
    def tearDown(self):
        executable_path.cache_clear()

    @patch('common.executables.shutil.which', return_value='/usr/bin/git')
    def test_returns_absolute_executable_path(self, _which):
        self.assertEqual(executable_path('git'), '/usr/bin/git')

    @patch('common.executables.shutil.which', return_value=None)
    def test_missing_executable_has_clear_error(self, _which):
        with self.assertRaisesRegex(RuntimeError, '未找到外部命令：git'):
            executable_path('git')

    @patch('common.output_layout.subprocess.run')
    @patch('common.output_layout.executable_path', return_value='/opt/tools/git')
    def test_repository_identity_invokes_absolute_git(self, _path, run):
        run.return_value = SimpleNamespace(returncode=1, stdout='')
        with tempfile.TemporaryDirectory() as temp:
            repository_identity(temp)
        self.assertEqual(run.call_args.args[0][0], '/opt/tools/git')

    @patch('review.get_commit_diff.subprocess.run')
    @patch('review.get_commit_diff.executable_path', return_value='/opt/tools/git')
    def test_review_git_helper_invokes_absolute_git(self, _path, run):
        run.return_value = SimpleNamespace(
            returncode=0, stdout='ok\n', stderr='')
        self.assertEqual(_git('/repo', 'status'), 'ok\n')
        self.assertEqual(run.call_args.args[0][0], '/opt/tools/git')


if __name__ == '__main__':
    unittest.main()
