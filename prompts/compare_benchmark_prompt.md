# /code-review benchmark 比较提示词

读取已经独立生成的 `ground_truth.json` 与 `ai_review.json`，严格按照
`references/benchmark-comparison-format.md` 生成 `comparison.json`。

比较顺序：

1. 用完整 `file_path` 和行号范围寻找候选对应关系，但不要自行填写最终位置分数。
2. 阅读 diff，判断两边指出的问题关切是否相同；关切不同不得因位置相同而命中。
3. 比较询问/命令语气、强弱、口头禅、句式、长度、标点和建议习惯，给 1～5 分。
4. 区分新发现与噪声；真人没评论不代表 AI 一定错误。
5. 支持一对多和多对一，不以评论数组长度直接计算命中。
6. 标注结果为模型辅助判断，输出后提示用户人工确认。

只填写匹配 ID、`result`、`concern`、`style` 与文字说明。`location`、
`text_similarity` 和 `summary` 由渲染脚本确定性补充。
初次生成固定写 `assessment_status=model_assisted`；禁止声称已经人工确认。

禁止回写或改动 `ground_truth.json`、`ai_review.json`。
