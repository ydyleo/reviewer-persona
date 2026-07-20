import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from benchmark.collect_benchmark_pairs import (  # noqa: E402
    _legacy_link_domain, _resolve, collect_case,
)


class BenchmarkResolveTest(unittest.TestCase):
    def setUp(self):
        self.records = [
            {'project_path': 'team/service-a', 'mr_iid': 6},
            {'project_path': 'team/service-b', 'mr_iid': 6},
        ]

    @patch('benchmark.collect_benchmark_pairs._load_reviewer_records')
    def test_duplicate_mr_iid_requires_project_path(self, load):
        load.return_value = self.records
        with self.assertRaises(SystemExit) as caught:
            _resolve('z1', mr_iid=6)
        self.assertIn('--project-path', str(caught.exception))

    @patch('benchmark.collect_benchmark_pairs._load_reviewer_records')
    def test_project_path_disambiguates_mr(self, load):
        load.return_value = self.records
        (domain, project, iid), _ = _resolve(
            'z1', mr_iid=6, project_path='team/service-b')
        self.assertEqual(domain, '')
        self.assertEqual((project, iid), ('team/service-b', 6))

    @patch('benchmark.collect_benchmark_pairs._load_reviewer_records')
    def test_domain_disambiguates_same_project_and_mr(self, load):
        load.return_value = [
            {'domain': 'codehub-g', 'project_path': 'team/service', 'mr_iid': 6},
            {'domain': 'codehub-y', 'project_path': 'team/service', 'mr_iid': 6},
        ]
        (domain, _project, _iid), _ = _resolve(
            'z1', mr_iid=6, domain='codehub-y')
        self.assertEqual(domain, 'codehub-y')

    def test_legacy_link_domain_has_explicit_empty_fallback(self):
        self.assertEqual(_legacy_link_domain('not-a-url'), '')
        self.assertEqual(
            _legacy_link_domain(
                'https://codehub-g.huawei.com/team/service/'
                'merge_requests/6#note_example'),
            'codehub-g')

    @patch('benchmark.collect_benchmark_pairs._persona_metadata')
    @patch('benchmark.collect_benchmark_pairs.benchmark_case_dir')
    @patch('review.get_commit_diff.get_mr_review_diff')
    def test_collect_case_excludes_locations_missing_from_current_diff(
            self, get_diff, case_dir, persona):
        diff_text = (
            'diff --git a/src/config.cpp b/src/config.cpp\n'
            '--- a/src/config.cpp\n+++ b/src/config.cpp\n'
            '@@ -27,2 +27,2 @@\n context\n+changed\n')
        get_diff.return_value = {
            'kept_files': 1,
            'excluded_test_files': 0,
            'files': [{
                'file_path': 'src/config.cpp',
                'diff_text': diff_text,
            }],
        }
        persona.return_value = {'w3': 'z1', 'file': 'persona.md', 'sha256': 'x'}
        records = [
            {'reviewer_name': '张三', 'domain': 'codehub-g',
             'file_path': 'src/config.cpp',
             'line': 28, 'comment': '命中'},
            {'reviewer_name': '张三', 'domain': 'codehub-g',
             'file_path': 'src/old.cpp',
             'line': 9, 'comment': '当前 diff 已不存在'},
        ]
        with tempfile.TemporaryDirectory() as temp:
            case_dir.return_value = Path(temp)
            collect_case('z1', 'team/service', 6, records, 'codehub-g')
            ground_truth = json.loads(
                (Path(temp) / 'ground_truth.json').read_text(encoding='utf-8'))
        self.assertTrue(ground_truth['benchmark_ready'])
        self.assertEqual(ground_truth['comment_count'], 1)
        self.assertEqual(ground_truth['domain'], 'codehub-g')
        self.assertEqual(len(ground_truth['excluded_comments']), 1)


if __name__ == '__main__':
    unittest.main()
