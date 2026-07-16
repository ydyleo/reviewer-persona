import sys
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from benchmark.render_comparison import (  # noqa: E402
    finalize_comparison,
    render_comparison,
)
from review.render_review import render_review, update_manifest  # noqa: E402


class ReviewRendererTest(unittest.TestCase):
    def setUp(self):
        self.data = {
            'schema_version': '1.0',
            'target': {'source': 'commit', 'commit': 'abc123'},
            'reviewer': {'name': '张三', 'w3': 'z1'},
            'files': ['src/common/config.cpp'],
            'baseline_violations': [{
                'rule_id': 'CPP-01', 'rule_name': '判空', 'source_index': 1,
                'level': '要求', 'file_path': 'src/common/config.cpp',
                'line_start': 27, 'line_end': 27,
                'description': '指针可能为空', 'suggestion': '使用前判空',
            }],
            'issues': [{
                'id': 'AI-001', 'severity': '中危',
                'rule_id': 'S03', 'rule_name': '判空',
                'file_path': 'src/common/config.cpp',
                'line_start': 28, 'line_end': 28,
                'summary': '可能为空', 'description': '这里要先判空。',
            }],
            'summary': {'merge_risk': '需整改后合并'},
        }

    def test_render_keeps_markdown_contract_and_json_full_path(self):
        markdown = render_review(self.data)
        self.assertIn('【张三意见】', markdown)
        self.assertIn('【位置】config.cpp:28', markdown)
        self.assertIn('【通用基线违规】CPP-01 - 判空', markdown)
        self.assertEqual(
            self.data['issues'][0]['file_path'], 'src/common/config.cpp')

    def test_update_manifest_uses_relative_artifact_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / 'manifest.json'
            review_json = root / 'reviewers/z1/review.json'
            review_md = root / 'reviewers/z1/review.md'
            review_json.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({
                'kind': 'review', 'reviewers': [],
            }), encoding='utf-8')
            update_manifest(manifest, self.data, review_json, review_md)
            updated = json.loads(manifest.read_text(encoding='utf-8'))
        self.assertEqual(
            updated['reviewers'][0]['review_json'], 'reviewers/z1/review.json')


class ComparisonRendererTest(unittest.TestCase):
    def setUp(self):
        self.gt = {
            'project_path': 'team/service', 'mr_iid': 6,
            'reviewer_w3': 'z1', 'reviewer_name': '张三',
            'comments': [{
                'id': 'GT-001', 'file_path': 'src/config.cpp',
                'line_start': 28, 'comment': '这里要判空',
            }],
        }
        self.ai = {'issues': [{
            'id': 'AI-001', 'file_path': 'src/config.cpp',
            'line_start': 29, 'summary': '返回值可能为空',
        }]}
        self.comparison = {
            'schema_version': '1.0',
            'assessment_status': 'model_assisted',
            'comparisons': [{
                'id': 'CMP-001',
                'ground_truth_ids': ['GT-001'],
                'ai_review_ids': ['AI-001'],
                'result': 'matched',
                'location': {'score': 0.8},
                'concern': {'score': 0.95},
                'style': {'score': 4},
                'reason': '位置邻近且问题一致',
            }],
        }

    def test_finalize_calculates_summary(self):
        result = finalize_comparison(self.comparison, self.gt, self.ai)
        self.assertEqual(result['summary']['matched'], 1)
        self.assertEqual(result['summary']['location_hit_rate'], 1.0)
        self.assertEqual(result['summary']['average_style_score'], 4.0)
        self.assertEqual(result['comparisons'][0]['location']['line_distance'], 1)
        self.assertGreater(result['comparisons'][0]['text_similarity'], 0)

    def test_render_comparison(self):
        result = finalize_comparison(self.comparison, self.gt, self.ai)
        markdown = render_comparison(result, self.gt, self.ai)
        self.assertIn('GT-001 src/config.cpp:28', markdown)
        self.assertIn('AI-001 src/config.cpp:29', markdown)
        self.assertIn('命中', markdown)


if __name__ == '__main__':
    unittest.main()
