# /code-review distill 模型编排提示词

> 本 prompt 由顶层 `SKILL.md` 在 `/code-review distill` 时读取并组织输入给模型。
> 输出 persona 骨架见 `templates/persona_skill_template.md`，规则分类见 `references/rule-taxonomy.md`，
> persona 内嵌的输出要求段见 `references/review-output-format.md`。

## 任务

对一位 CodeHub 评审人的历史评论进行人格蒸馏，生成一份 Claude Code 专用评审分身 Skill 文档。

## 输入材料

1. **structured JSON**：由 `scripts/distill/prepare_review_data.py` 产出于 `outputs/structured/{reviewer_w3}_{start}_{end}_structured.json`。读取该文件作为本次蒸馏的数据源，含：
   - `meta`：`reviewer_name` / `reviewer_w3` / `distill_start` / `distill_end` /
     `prepared_at` / `total_reviews` / `severity_distribution` / `unique_files` /
     `total_patterns`（persona 标题与元信息只能从这里取）
   - `pattern_clusters`：预聚类模式（带 `count` / `category` / `review_ids`），按 count 降序——**规则提炼的主索引**
   - `file_distribution`：文件分布
   - `reviews`：全量 matched 评论，每条含 `comment` / `severity` / `file` / `line` / `target_code` / `context_lines` / `submitter`。体量可能较大，**按 `pattern_clusters` 的 `review_ids` 抽取每簇 2-3 条代表样本**作为规则样本，不要把全集塞进 persona。
2. **persona 模板**：`templates/persona_skill_template.md`。
3. **规则分类**：`references/rule-taxonomy.md`（S/P/B/A/C/D）。
4. **输出格式契约**：`references/review-output-format.md`（persona 的「输出要求」段须内嵌铁律格式块）。

## 硬性要求

### 1. 语言风格保留
完整保留该评论人的语言习惯：语气、口头禅、句式、吐槽、短句、严肃/随意风格，绝不美化、绝不官方化。
从历史评论中归纳其「书面化负面清单」（公文式表述 → 口语化替换）。

### 2. 规则提炼（核心）
- 从评论 + 代码上下文提炼**可复用的审查规则**，而非仅选取几条评论。
- 每条规则包含：触发条件、检查方法、禁止模式、推荐模式、≥2-3 条真实评论样本（含触发代码）、提炼约束。
- 规则编号用 S/P/B/A/C/D 分类。
- 优先从 `pattern_clusters` 中 count 最高的模式开始提炼。
- 严重程度高的评论重点提炼；"建议"类用于补充样本多样性。
- 宁可规则多也不要遗漏有价值的审查经验。

### 3. 代码上下文利用
- `target_code`（`>>` 标记的目标行）直接用作每条规则的「禁止模式」反例。
- `context_lines` 用于理解问题全貌、辅助构建「推荐模式」。
- 若 target_code 为空或与评论不匹配，以评论文字为准。

### 4. 规则分类
按 S/P/B/A/C/D 六大类归纳，参考预聚类的 category 标注但需交叉验证。
不是每类都必须生成——只为其历史评论确有体现的类别生成规则。

### 5. 输出格式
严格匹配 `templates/persona_skill_template.md` 骨架，不要额外解释，只输出成品 persona 内容。
`Persona 元信息` 中的姓名、工号、蒸馏日期、评论数量和数据准备时间必须逐字取自
structured `meta`，禁止推测或改写。
persona 的「输出要求」段必须内嵌 `references/review-output-format.md` 的铁律格式块
（`【{姓名}意见】` / `【评审来源】` / `【位置】` / 连贯段落 / `【修改示例】` / `---`，
严重程度四档分组，禁止拆 `【问题根因】`/`【修改建议】` 等字段）。

## 输出路径

生成草稿到 `outputs/generated_personas/reviewer-{姓名}-{工号}.skill.md`。生成结束后不要直接
改写 `personas/`；由 `scripts/distill/activate_persona.py` 校验、备份并原子启用。

## 数据读取

执行蒸馏时，直接读取 `outputs/structured/{reviewer_w3}_{start}_{end}_structured.json`
作为数据源（`meta` 取姓名/工号，`pattern_clusters` 作规则主索引，`reviews` 抽代表样本）。
无需人工粘贴数据，模型自行从该文件读取。
