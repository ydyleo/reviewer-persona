# 结构化评审 JSON 契约

模型先生成结构化 JSON，再由 `scripts/review/render_review.py` 确定性渲染 Markdown。
普通 review 使用 `review.json`，benchmark 使用 `ai_review.json`，两者结构相同。

```json
{
  "schema_version": "1.0",
  "target": {
    "source": "commit",
    "commit": "完整 commit SHA",
    "project_path": "完整项目路径"
  },
  "reviewer": {
    "w3": "z00123456",
    "name": "张三",
    "persona_file": "reviewer-张三-z00123456.skill.md",
    "persona_sha256": "..."
  },
  "files": ["src/common/config.cpp"],
  "baseline_violations": [],
  "issues": [
    {
      "id": "AI-001",
      "severity": "中危",
      "rule_id": "S03",
      "rule_name": "空指针检查",
      "file_path": "src/common/config.cpp",
      "line_start": 28,
      "line_end": 28,
      "summary": "配置对象可能为空",
      "description": "符合 persona 语气的连贯描述",
      "language": "cpp",
      "code_example": "可选的修改代码"
    }
  ],
  "summary": {"merge_risk": "需整改后合并"}
}
```

约束：

- `file_path` 必须取 diff 中的完整相对路径；禁止只写 basename。
- 行号必须取 diff 新文件行号；无有效行号不得输出意见。
- `severity` 只能是高危、中危、低危、优化建议。
- `description` 保留 persona 口吻，并连贯写清问题、原因和修改方向。
- `issues[].id` 在单份报告内唯一，从 `AI-001` 连续编号。
- 无修改示例时省略 `code_example`，不要填空代码块。
- 未加载或未命中公共基线时令 `baseline_violations=[]`；命中时每项保存
  `rule_id/rule_name/source_index/level/file_path/line_start/line_end/description/suggestion`。
- Markdown 中的稳定 token 仍以 `references/review-output-format.md` 为准。
