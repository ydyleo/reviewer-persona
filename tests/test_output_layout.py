import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from common.output_layout import (  # noqa: E402
    benchmark_case_dir,
    normalize_project_path,
    parse_repository_url,
)


class OutputLayoutTest(unittest.TestCase):
    def test_parse_codehub_merge_requests_url(self):
        value = parse_repository_url(
            'https://codehub-g.huawei.com/'
            'MiddleWare-SRE/CloudDB-SRE/LINKDB-API/merge_requests')
        self.assertEqual(value['domain'], 'codehub-g')
        self.assertEqual(
            value['project_path'], 'MiddleWare-SRE/CloudDB-SRE/LINKDB-API')

    def test_parse_scp_git_url(self):
        value = parse_repository_url(
            'git@codehub-g.huawei.com:'
            'MiddleWare-SRE/CloudDB-SRE/LINKDB-API.git')
        self.assertEqual(value['domain'], 'codehub-g')
        self.assertEqual(value['project_parts'][-1], 'LINKDB-API')

    def test_benchmark_identity_prevents_mr_iid_collision(self):
        first = benchmark_case_dir('codehub-g', 'team/service-a', 6, 'z1')
        second = benchmark_case_dir('codehub-g', 'team/service-b', 6, 'z1')
        self.assertNotEqual(first, second)
        self.assertTrue(str(first).endswith('team/service-a/mr-6/reviewer-z1'))

    def test_reject_parent_path(self):
        with self.assertRaises(ValueError):
            normalize_project_path('../service-a')

    def test_known_project_path_does_not_strip_route_like_name(self):
        self.assertEqual(
            normalize_project_path('team/commits'), ('team', 'commits'))


if __name__ == '__main__':
    unittest.main()
