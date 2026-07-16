import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from distill.activate_persona import activate_persona  # noqa: E402
from common.persona import parse_persona  # noqa: E402


def _structured(path: Path, name='张三', w3='z1', start='2026-01-01',
                end='2026-06-30', total=12):
    data = {'meta': {
        'reviewer_name': name, 'reviewer_w3': w3,
        'distill_start': start, 'distill_end': end,
        'total_reviews': total, 'prepared_at': '2026-07-16T10:00:00+08:00',
    }}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path


def _draft(path: Path, marker='新版', name='张三', w3='z1',
           start='2026-01-01', end='2026-06-30', total=12):
    text = f'''# 评审人格分身：【{name} {w3}】

## Persona 元信息

- reviewer：{name}
- reviewer_w3：{w3}
- 蒸馏开始日期：{start}
- 蒸馏结束日期：{end}
- 历史评论数量：{total}
- 数据准备时间：2026-07-16T10:00:00+08:00

## 🔴 强制固定约束（不可删除）
{marker}

## 核心评审偏好
- 重点关注领域：空指针

## 分身专属规则

### S01 【规范要求】判空
**触发条件**：指针使用

## 输出要求

【{name}意见】
【评审来源】{name}|S01-判空
【位置】{{文件名}}:{{行号}}
【修改示例】
---
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


class PersonaActivationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.personas = self.root / 'personas'
        self.backups = self.root / 'generated/backup'
        self.structured = _structured(self.root / 'structured.json')

    def tearDown(self):
        self.temp.cleanup()

    def activate(self, draft, structured=None, draft_only=False):
        return activate_persona(
            draft, structured or self.structured, draft_only=draft_only,
            personas_dir=self.personas, backup_dir=self.backups,
        )

    def test_first_activation_installs_without_backup(self):
        draft = _draft(self.root / 'drafts/persona.md')
        result = self.activate(draft)
        self.assertEqual(result['status'], 'activated')
        self.assertFalse(draft.exists())
        self.assertTrue(Path(result['active']).exists())
        self.assertEqual(result['backup'], '')

    def test_legacy_persona_without_metadata_still_loads(self):
        legacy = self.root / 'reviewer-旧用户-z9.skill.md'
        legacy.write_text(
            '# 评审人格分身：【旧用户 z9】\n\n### S01 旧规则\n',
            encoding='utf-8')
        info = parse_persona(legacy)
        self.assertEqual(info['w3'], 'z9')
        self.assertEqual(info['metadata']['distill_start'], '')

    def test_refresh_keeps_only_immediately_previous_version(self):
        self.activate(_draft(self.root / 'drafts/first.md', marker='第一版'))
        self.activate(_draft(self.root / 'drafts/second.md', marker='第二版'))
        result = self.activate(_draft(self.root / 'drafts/third.md', marker='第三版'))
        backups = list(self.backups.glob('*.previous.skill.md'))
        self.assertEqual(len(backups), 1)
        self.assertIn('第二版', backups[0].read_text(encoding='utf-8'))
        self.assertIn('第三版', Path(result['active']).read_text(encoding='utf-8'))

    def test_invalid_draft_does_not_modify_active_or_backup(self):
        first = self.activate(_draft(self.root / 'drafts/first.md', marker='正式版'))
        active = Path(first['active'])
        invalid = self.root / 'drafts/invalid.md'
        invalid.write_text('# 不完整', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.activate(invalid)
        self.assertIn('正式版', active.read_text(encoding='utf-8'))
        self.assertTrue(invalid.exists())
        self.assertEqual(list(self.backups.glob('*')), [])

    def test_structured_metadata_mismatch_is_rejected(self):
        draft = _draft(self.root / 'drafts/persona.md', total=13)
        with self.assertRaisesRegex(ValueError, '历史评论数量'):
            self.activate(draft)
        self.assertTrue(draft.exists())
        self.assertFalse(self.personas.exists())

    def test_draft_only_validates_without_activation(self):
        draft = _draft(self.root / 'drafts/persona.md')
        result = self.activate(draft, draft_only=True)
        self.assertEqual(result['status'], 'validated_draft')
        self.assertTrue(draft.exists())
        self.assertFalse(self.personas.exists())

    def test_name_change_replaces_old_file_and_keeps_one_backup(self):
        self.activate(_draft(self.root / 'drafts/old.md', name='张三'))
        structured = _structured(self.root / 'new_structured.json', name='张小三')
        result = self.activate(
            _draft(self.root / 'drafts/new.md', name='张小三'), structured)
        active_files = list(self.personas.glob('*.skill.md'))
        self.assertEqual(len(active_files), 1)
        self.assertIn('张小三', active_files[0].name)
        self.assertTrue(Path(result['backup']).exists())

    def test_install_failure_restores_existing_previous_backup(self):
        self.activate(_draft(self.root / 'drafts/first.md', marker='第一版'))
        self.activate(_draft(self.root / 'drafts/second.md', marker='第二版'))
        previous = next(self.backups.glob('*.previous.skill.md'))
        self.assertIn('第一版', previous.read_text(encoding='utf-8'))
        third = _draft(self.root / 'drafts/third.md', marker='第三版')
        with patch('distill.activate_persona._install_draft',
                   side_effect=OSError('模拟安装失败')):
            with self.assertRaises(OSError):
                self.activate(third)
        active = next(self.personas.glob('*.skill.md'))
        self.assertIn('第二版', active.read_text(encoding='utf-8'))
        self.assertIn('第一版', previous.read_text(encoding='utf-8'))
        self.assertTrue(third.exists())


if __name__ == '__main__':
    unittest.main()
