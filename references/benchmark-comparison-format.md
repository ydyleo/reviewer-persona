# Benchmark 比较契约

只在 `ai_review.json` 已生成后读取 `ground_truth.json`，比较位置、问题关切、风格和文本表达。
生成阶段严禁把 ground truth 提供给 AI reviewer。

```json
{
  "schema_version": "1.0",
  "assessment_status": "model_assisted",
  "comparisons": [
    {
      "id": "CMP-001",
      "ground_truth_ids": ["GT-001"],
      "ai_review_ids": ["AI-001"],
      "result": "matched",
      "concern": {"score": 0.95, "reason": "指出同一空指针风险"},
      "style": {"score": 4, "reason": "疑问句和措辞习惯接近"},
      "reason": "位置邻近、问题一致且表达风格接近"
    }
  ],
  "summary": {
    "ground_truth_count": 1,
    "ai_review_count": 1,
    "matched": 1,
    "partial_matched": 0,
    "missed": 0,
    "new_findings": 0,
    "noise": 0,
    "location_hit_rate": 1.0,
    "average_style_score": 4.0
  }
}
```

模型只填写对应关系、`result`、`concern`、`style` 和说明。运行
`scripts/benchmark/render_comparison.py` 时，脚本根据完整路径/行号确定性补充
`location`，用原始评论文本确定性补充 `text_similarity`，并重新计算整个 `summary`；
不要让模型自行计算这些字段。

模型初次生成时设置 `assessment_status=model_assisted`；人工逐项确认或修订后改为
`human_confirmed`。未确认结果只能作为辅助观察，不能作为正式 benchmark 结论。

`result` 只能是：

- `matched`：位置邻近且问题关切一致。
- `partial_matched`：同一区域，但关切不完整或角度有偏差。
- `missed`：真人评论没有对应 AI 意见。
- `new_finding`：AI 指出真人未评论但真实存在的问题。
- `noise`：AI 意见错误、无关或误报。

问题关切是命中的门槛：仅位置和语气相似、实际指出不同问题时，不得判为 `matched`。
位置评分建议：同行或范围重叠 1.0；同文件相差 1～3 行 0.8；相差 4～10 行 0.4；不同文件 0。
风格按 1～5 分人工校准；模型可以先给候选评分，但最终结论需要人工确认。
