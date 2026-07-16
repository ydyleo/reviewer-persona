import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from distill.enrich_reviews import _parse_link_info  # noqa: E402


class EnrichDomainTest(unittest.TestCase):
    def test_single_domain_is_inferred(self):
        links = [
            (3, 'https://codehub-g.huawei.com/team/a/'
                'merge_requests/1#note_a'),
            (8, 'https://codehub-g.huawei.com/team/b/'
                'merge_requests/2#note_b'),
        ]
        info, domains, errors = _parse_link_info(links)
        self.assertEqual(domains, ['codehub-g'])
        self.assertEqual(info[3]['project_path'], 'team/a')
        self.assertEqual(errors, [])

    def test_multiple_domains_remain_separate(self):
        links = [
            (1, 'https://codehub-g.huawei.com/team/service/'
                'merge_requests/6#note_g'),
            (2, 'https://codehub-y.huawei.com/team/service/'
                'merge_requests/6#note_y'),
        ]
        info, domains, errors = _parse_link_info(links)
        identities = {
            (item['domain'], item['project_path'], item['mr_iid'])
            for item in info.values()
        }
        self.assertEqual(domains, ['codehub-g', 'codehub-y'])
        self.assertEqual(len(identities), 2)
        self.assertEqual(errors, [])

    def test_explicit_domain_is_a_strict_constraint(self):
        links = [(1, 'https://codehub-y.huawei.com/team/service/'
                     'merge_requests/6#note_y')]
        info, domains, errors = _parse_link_info(
            links, requested_domain='codehub-g')
        self.assertEqual(info, {})
        self.assertEqual(domains, [])
        self.assertIn('不一致', errors[0][1])

    def test_invalid_link_is_reported_with_original_index(self):
        info, domains, errors = _parse_link_info([(17, 'not-a-url')])
        self.assertEqual(info, {})
        self.assertEqual(domains, [])
        self.assertEqual(errors[0][0], 17)


if __name__ == '__main__':
    unittest.main()
