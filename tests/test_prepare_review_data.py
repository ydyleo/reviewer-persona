import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from distill.prepare_review_data import (  # noqa: E402
    PATTERN_RULES, PatternRule, classify_review, prepare,
)


class PrepareReviewDataTest(unittest.TestCase):
    def test_pattern_rules_are_named_and_keep_all_legacy_fields(self):
        self.assertTrue(PATTERN_RULES)
        self.assertTrue(all(isinstance(rule, PatternRule)
                            for rule in PATTERN_RULES))
        first = PATTERN_RULES[0]
        self.assertEqual(first.label, 'const/auto&缺失')
        self.assertTrue(first.code_keywords)
        self.assertTrue(first.description)

    def test_named_rule_access_keeps_comment_and_code_classification(self):
        comment_matches = classify_review('', '这里的返回值没有检查', '')
        self.assertIn(('错误码/返回值未检查', 'B'), comment_matches)
        code_matches = classify_review('std::unique_ptr<Item> value;', '', '')
        self.assertIn(('智能指针使用', 'P'), code_matches)

    @patch('distill.prepare_review_data.ensure_dirs')
    @patch('distill.prepare_review_data._load_records')
    def test_structured_meta_contains_distill_period(self, load_records, _ensure):
        load_records.return_value = ([{
            'reviewer_name': '张三', 'reviewer_w3': 'z1',
            'comment': '这里需要判空', 'severity': '一般',
            'file_path': 'src/a.cpp', 'line': 10,
            'code_context': ' >> 10: ptr->run();',
        }], None)
        with tempfile.TemporaryDirectory() as temp, patch(
                'distill.prepare_review_data.STRUCTURED_DIR', Path(temp)):
            output = prepare(
                'ignored.jsonl', reviewer_w3='z1',
                start='2026-01-01', end='2026-06-30')
            data = json.loads(Path(output).read_text(encoding='utf-8'))
        self.assertEqual(data['meta']['distill_start'], '2026-01-01')
        self.assertEqual(data['meta']['distill_end'], '2026-06-30')
        self.assertEqual(data['meta']['total_reviews'], 1)
        self.assertTrue(data['meta']['prepared_at'])


if __name__ == '__main__':
    unittest.main()
