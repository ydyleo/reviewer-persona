import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from common.codehub_url import (  # noqa: E402
    normalize_codehub_domain,
    parse_review_url,
)


class CodeHubDomainTest(unittest.TestCase):
    def test_normalize_all_supported_hosts(self):
        cases = {
            'https://codehub-g.huawei.com/x': 'codehub-g',
            'codehub-y.huawei.com': 'codehub-y',
            'cr-y.codehub.huawei.com': 'cr-y.codehub',
            'open.codehub': 'open.codehub',
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_codehub_domain(value), expected)

    def test_reject_unknown_or_lookalike_host(self):
        for value in ('clouddevops.huawei.com',
                      'codehub-g.huawei.com.example.com'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_codehub_domain(value)

    def test_parse_review_url_complete_identity(self):
        parsed = parse_review_url(
            'https://codehub-g.huawei.com/'
            'MiddleWare-SRE/CloudDB-SRE/LINKDB-API/'
            'merge_requests/6#note_abc123')
        self.assertEqual(parsed, {
            'domain': 'codehub-g',
            'project_path': 'MiddleWare-SRE/CloudDB-SRE/LINKDB-API',
            'mr_iid': '6',
            'note_hash': 'abc123',
        })

    def test_parse_decodes_project_path(self):
        parsed = parse_review_url(
            'https://codehub-y.huawei.com/team%20name/service/'
            'merge_requests/9#note_n1')
        self.assertEqual(parsed['project_path'], 'team name/service')

    def test_explicit_domain_mismatch_fails(self):
        with self.assertRaisesRegex(ValueError, '不一致'):
            parse_review_url(
                'https://codehub-g.huawei.com/team/service/'
                'merge_requests/6#note_x', expected_domain='codehub-y')

    def test_missing_host_mr_or_note_fails(self):
        invalid = (
            'codehub-g.huawei.com/team/service/merge_requests/6#note_x',
            'https://codehub-g.huawei.com/team/service#note_x',
            'https://codehub-g.huawei.com/team/service/merge_requests/6',
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_review_url(value)

    def test_mixed_domains_are_detectable_per_row(self):
        links = [
            'https://codehub-g.huawei.com/team/a/merge_requests/1#note_a',
            'https://codehub-y.huawei.com/team/b/merge_requests/2#note_b',
        ]
        domains = {parse_review_url(link)['domain'] for link in links}
        self.assertEqual(domains, {'codehub-g', 'codehub-y'})


if __name__ == '__main__':
    unittest.main()
