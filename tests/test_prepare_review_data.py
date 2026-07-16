import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from distill.prepare_review_data import prepare  # noqa: E402


class PrepareReviewDataTest(unittest.TestCase):
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
