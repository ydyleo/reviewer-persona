import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from review.load_persona import (  # noqa: E402
    list_personas,
    render_personas_json,
    render_personas_text,
    summarize_focus,
)


def _persona(path: Path, focus='配置完整性与命名一致性') -> Path:
    path.write_text(f'''# 评审人格分身：【测试用户 t00000001】

## Persona 元信息
- reviewer：测试用户
- reviewer_w3：t00000001
- 蒸馏开始日期：2026-01-01
- 蒸馏结束日期：2026-06-30
- 历史评论数量：12
- 数据准备时间：2026-07-17T10:00:00+08:00

## 核心评审偏好
- 重点关注领域：{focus}

### S01 【规范要求】检查配置
### P01 【潜在问题】检查默认值
''', encoding='utf-8')
    return path


class ListPersonasTest(unittest.TestCase):
    def test_list_reads_utf8_persona_and_returns_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            _persona(Path(temp) / 'reviewer-测试用户-t00000001.skill.md')
            personas = list_personas(Path(temp))
        self.assertEqual(len(personas), 1)
        self.assertEqual(personas[0]['name'], '测试用户')
        self.assertEqual(personas[0]['rule_count'], 2)
        self.assertEqual(personas[0]['metadata']['distill_start'], '2026-01-01')

    def test_text_uses_blocks_instead_of_fixed_width_table(self):
        with tempfile.TemporaryDirectory() as temp:
            _persona(Path(temp) / 'reviewer-测试用户-t00000001.skill.md')
            output = render_personas_text(list_personas(Path(temp)))
        self.assertIn('已安装 1 个 reviewer persona', output)
        self.assertIn('1. 测试用户（t00000001）', output)
        self.assertIn('2 条规则 · 2026-01-01 ~ 2026-06-30', output)
        self.assertNotIn('姓名        工号', output)

    def test_focus_is_not_truncated_for_the_old_fixed_width_table(self):
        long_focus = '配置完整性与命名一致性' * 10
        with tempfile.TemporaryDirectory() as temp:
            _persona(
                Path(temp) / 'reviewer-测试用户-t00000001.skill.md', long_focus)
            personas = list_personas(Path(temp))
        self.assertNotIn(long_focus, render_personas_text(personas))
        self.assertIn('…', render_personas_text(personas))
        self.assertIn(long_focus, render_personas_text(personas, verbose=True))
        payload = json.loads(render_personas_json(personas))
        self.assertEqual(payload['personas'][0]['focus'], long_focus)

    def test_focus_summary_ignores_commas_inside_parentheses(self):
        focus = (
            '错误码检查（BaseError, JsonError）、接口设计与参数映射、并发安全、'
            '代码复用、测试质量、日志职责')
        self.assertEqual(
            summarize_focus(focus),
            '错误码检查、接口设计与参数映射、并发安全、代码复用、测试质量等')

    def test_verbose_keeps_full_focus_while_default_uses_summary(self):
        focus = '错误码检查、接口设计、并发安全、代码复用、测试质量、日志职责'
        persona = {
            'name': '示例用户', 'w3': 't00000002', 'rule_count': 14,
            'focus': focus, 'metadata': {}, 'file': 'persona.md',
        }
        compact = render_personas_text([persona])
        verbose = render_personas_text([persona], verbose=True)
        self.assertIn('关注：错误码检查、接口设计、并发安全、代码复用、测试质量等', compact)
        self.assertNotIn('日志职责', compact)
        self.assertIn(f'关注：{focus}', verbose)

    def test_json_is_ascii_safe_and_round_trips_chinese(self):
        with tempfile.TemporaryDirectory() as temp:
            _persona(Path(temp) / 'reviewer-测试用户-t00000001.skill.md')
            output = render_personas_json(list_personas(Path(temp)))
        output.encode('ascii')
        payload = json.loads(output)
        self.assertEqual(payload['schema_version'], '1.1')
        self.assertEqual(payload['personas'][0]['name'], '测试用户')
        self.assertEqual(payload['personas'][0]['focus_summary'], '配置完整性与命名一致性')
        self.assertEqual(payload['personas'][0]['focus'], '配置完整性与命名一致性')

    def test_cli_overrides_cp936_stdout_with_utf8(self):
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'cp936'
        env['PYTHONPATH'] = str(SCRIPTS)
        code = (
            'from review.load_persona import configure_utf8_stdio; '
            'configure_utf8_stdio(); print("姓名")'
        )
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=str(SCRIPTS.parent), env=env,
            capture_output=True, check=True,
        )
        self.assertEqual(result.stdout.decode('utf-8').strip(), '姓名')


if __name__ == '__main__':
    unittest.main()
