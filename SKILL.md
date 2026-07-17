---
name: code-review
description: 华为 CodeHub 代码评审 skill。从历史评审数据蒸馏 reviewer 人格分身，用指定人格评审 commit，并用未参与蒸馏的 MR 对比 AI 与真人评论的位置、问题关切和语言风格。用于 /code-review distill、review、list-personas 和 benchmark；兼容旧 refresh-persona 命令并按 distill 执行。
---

# code-review 调度入口

华为 CodeHub 代码评审 skill。从历史评审数据蒸馏 reviewer 人格分身，并用指定人格评审 commit。确定性数据处理由 `scripts/` 下 Python 脚本完成，persona 与评审报告的生成由本 skill 编排当前模型按 prompt + template 完成。

## 核心命令

```
/code-review distill        # 从历史评审数据生成 reviewer 人格分身
/code-review review         # 用指定人格评审单个 commit
/code-review list-personas  # 列出已有 persona
/code-review benchmark      # persona 质量评估：AI 评审 vs 真人评论，位置/关切/风格对比
```

## 关键约定

1. **脚本用绝对路径调用**。本 skill 根目录 `<SKILL_ROOT>` = 当前 `SKILL.md` 所在目录。调用脚本时写 `python <SKILL_ROOT>/scripts/...`，不要写 `python scripts/...`（review 经常在目标代码仓目录执行，相对路径会失效）。
2. **确定性工作由 Python 脚本做；生成类工作（persona、评审报告）由当前模型按 prompt + template 编排完成**，不写独立 LLM 调用脚本。
3. **运行产物锚定 skill 根目录**（outputs/、cache/、personas/），不写入被评审目标仓。review 按仓库/commit 聚合，benchmark 按 domain/project/MR/reviewer 聚合；不要再把新产物写入旧 `outputs/diffs/`、`outputs/reports/`。
4. **评审报告格式是契约**。persona 意见、报告、prompt、template 四处必须使用 `references/review-output-format.md` 的同一套 token（`【{分身姓名}意见】` / `【评审来源】` / `【位置】` / 连贯段落 / `【修改示例】` / `---`，严重程度四档分组）。禁止拆 `【问题根因】`/`【修改建议】` 等字段。
5. **结构化 JSON 是评审数据真源**。模型按 `references/review-json-format.md` 生成 JSON，再用 `scripts/review/render_review.py` 渲染 Markdown；禁止分别生成两份内容。

---

## 命令一：/code-review distill

### 参数

```
/code-review distill \
  --reviewer-w3 <工号> \
  --start <YYYY-MM-DD> \
  --end <YYYY-MM-DD> [--draft-only]
```

默认逐条从阿基米德「检视地址」推导 CodeHub domain；同一批数据包含多个 domain 时自动分组处理。
可选传 `--domain <地域>` 作为严格约束，任一 URL 与其不一致就停止，不静默串地域。
默认在生成并校验后立即启用 persona；仅明确传 `--draft-only` 时保留草稿而不启用。

### 执行流程

按顺序运行三个确定性脚本，再由模型生成 persona：

**Step 1 导出阿基米德 Excel**
```bash
python <SKILL_ROOT>/scripts/distill/export_archimedes.py \
  --reviewer-w3 <工号> --start <起> --end <止>
```
- 首次运行需用户在 Playwright 浏览器手动完成阿基米德登录（不要 headless）。
- 登录态存 `<SKILL_ROOT>/cache/archimedes_session/`，后续复用。
- 产物：`<SKILL_ROOT>/outputs/raw_archimedes/{姓名}_{工号}_{起}_{止}_archimedes.xlsx`

**Step 2 补充 CodeHub 字段和代码上下文**
```bash
# 首次需在 .env 填入 CODEHUB_TOKEN（cp .env.example .env 后编辑）
python <SKILL_ROOT>/scripts/distill/enrich_reviews.py \
  --input <SKILL_ROOT>/outputs/raw_archimedes/<上面>.xlsx \
  --reviewer-w3 <工号> --start <起> --end <止>
```
- comment 取阿基米德 Excel 检视意见；file_path/line/severity 取 CodeHub /reviews；diff/上下文取 CodeHub /changes。
- 严格解析每条 URL 的 domain/project_path/mr_iid/note_hash，只接受四个已配置 CodeHub 地域；
  每个 domain 分别获取 user_id，并用 `(domain, project_path, mr_iid)` 隔离请求与缓存。
- 正式输出只保留 `context_status = matched` 的记录。
- 产物：`outputs/enriched/{工号}_{起}_{止}_enriched.xlsx` 和 `.jsonl`，每条记录保存 `domain`。

**Step 3 生成结构化 JSON**
```bash
python <SKILL_ROOT>/scripts/distill/prepare_review_data.py \
  --input <SKILL_ROOT>/outputs/enriched/<上面>.jsonl
```
- 产物：`outputs/structured/{工号}_{起}_{止}_structured.json`（meta 明确包含姓名、工号、
  蒸馏起止时间、数据准备时间和评论数，另含 reviews / pattern_clusters / file_distribution）

**Step 4 模型编排生成 persona（本步由当前模型完成）**

读取以下文件组织输入：
- `outputs/structured/<上面>.json`
- `prompts/distill_persona_prompt.md`
- `templates/persona_skill_template.md`
- `references/rule-taxonomy.md`
- `references/review-output-format.md`（persona 的"输出要求"段须内嵌铁律格式块）

按 distill prompt 硬性要求生成，写入草稿：
`outputs/generated_personas/reviewer-{姓名}-{工号}.skill.md`

**Step 5 校验并自动启用 persona**（确定性，脚本）

默认运行：
```bash
python <SKILL_ROOT>/scripts/distill/activate_persona.py \
  --draft <SKILL_ROOT>/outputs/generated_personas/reviewer-<姓名>-<工号>.skill.md \
  --structured <SKILL_ROOT>/outputs/structured/<本次 structured.json>
```

- 首次生成时直接安装为 `personas/reviewer-{姓名}-{工号}.skill.md`。
- 同工号正式 persona 已存在时，先覆盖保存最近一个
  `outputs/generated_personas/backup/reviewer-{姓名}-{工号}.previous.skill.md`，再原子安装新版。
- 每个工号最多保留一个 previous，不累计时间戳历史。
- 校验或安装失败时正式 persona 不变，草稿留在 `outputs/generated_personas/` 供排查。
- 成功启用后草稿被移动到 `personas/`，用户无需手工复制。

用户传 `--draft-only` 时，给上面脚本增加 `--draft-only`；只校验和保留草稿，不修改正式 persona。

### 兼容旧命令

收到 `/code-review refresh-persona` 时，提示该命令是兼容别名，建议后续改用
`/code-review distill`；随后原样转交同一组参数并执行上面的 distill Step 1~5，不建立独立流程。
更新已有 persona 时仍由 `activate_persona.py` 原子覆盖，并且每个工号只保留最近一个 previous。

---

## 命令二：/code-review review

### 参数

```
# 默认在当前目标 Git 仓库执行
/code-review review --commit <commit_id> --persona <工号|姓名>

# 不在目标仓库目录时显式指定
/code-review review --repo /path/to/target/repo --commit <commit_id> --persona <工号|姓名>
```

当前仅支持单个 `--commit`。多 commit 批量审查暂不纳入。

### 执行流程

**Step 1 获取 commit diff**

用户未传 `--repo` 时，默认使用当前工作目录作为目标 Git 仓：

```bash
python <SKILL_ROOT>/scripts/review/get_commit_diff.py \
  --commit <commit_id>
```

用户显式传入 `--repo` 时，使用指定目标仓路径：

```bash
python <SKILL_ROOT>/scripts/review/get_commit_diff.py \
  --repo <目标仓路径> \
  --commit <commit_id>
```

- 脚本统一用 `git -C <repo>`；未传 `--repo` 时 `<repo>` 等于当前工作目录 `.`；commit 不存在则 fetch 后复查。
- 排除测试代码（testcode/、*_test.cpp、*_llt.cpp、LLT_*.cpp 等）。
- 从 origin 推导 domain/project_path；无可解析 origin 时使用 `local/{仓库名-路径短哈希}`。
- 产物：`outputs/review/{domain}/{project_path}/commit-{short_sha}/manifest.json`、`diff.json`、`diff.md`。

**Step 2 加载 persona**

```bash
python <SKILL_ROOT>/scripts/review/load_persona.py --w3 <工号>
# 或 --name <姓名>；或 --list 列出全部
```
输出 persona 文件路径，读取其内容（强制固定约束 / 核心评审偏好 / 分身专属规则 / 输出要求）。

**Step 3 模型编排生成评审报告（本步由当前模型完成）**

读取以下文件组织输入：
- 上一步产出的 `diff.json`（结构化 diff，含完整 file_path + 行号）
- persona 文件内容
- `prompts/review_with_persona_prompt.md`
- `templates/review_report_template.md`
- `references/review-output-format.md`
- 可选 `references/cpp-baseline.md`（若加载，先做基线扫描，命中走"通用基线违规区"）

按 `references/review-json-format.md` 生成结构化结果：
- 100% 复刻 persona 语言习惯（语气/口头禅/句式/吐槽/书面化负面清单）。
- 每条意见必须有完整文件路径+行号（取 diff 新文件行号），能对应 persona 规则编号。
- 连贯一段话描述，代码放 `【修改示例】`。
- 按严重程度（高危/中危/低危/优化建议）在 `## 评审意见` 下分组。

先写：
`<review_case_dir>/reviewers/{工号}/review.json`

再确定性渲染并更新 manifest：
```bash
python <SKILL_ROOT>/scripts/review/render_review.py \
  --input <review_case_dir>/reviewers/<工号>/review.json \
  --output <review_case_dir>/reviewers/<工号>/review.md \
  --manifest <review_case_dir>/manifest.json
```

旧 `outputs/diffs/`、`outputs/reports/` 只保留历史产物，新流程不写入。
同一仓库、commit、reviewer 重跑时覆盖 `review.json/.md`，只保留最新报告；其他 reviewer 目录不受影响。

---

## 命令三：/code-review list-personas

```
/code-review list-personas [--verbose]
```

```bash
python <SKILL_ROOT>/scripts/review/load_persona.py --list --format json
```
- JSON 只输出到 stdout，不保存文件；读取 `personas` 数组后向用户展示分块列表，不直接转贴 JSON。
- 默认直接从“已安装 N 个 reviewer persona”开始，每项固定三行：序号+姓名+工号、规则数+蒸馏范围、`focus_summary`；
  不要输出“JSON 已拿到”“编码正常”等内部过程，不要添加 `---`，不要使用定宽表格。
- 用户传 `--verbose` 时保持相同结构，但用完整 `focus` 替换 `focus_summary`。
- persona Markdown 固定按 UTF-8 读取，CLI stdout/stderr 固定为 UTF-8；JSON 使用 ASCII-safe 转义，兼容 Windows CP936 调用环境。
- 用户直接在终端阅读时可运行 `--list --format text [--verbose]`（`text` 是默认格式）。

---

## 命令四：/code-review benchmark

评估 persona 蒸馏质量：拿该评审人**真实评审过的 MR**，让 persona 生成 AI 评审，
与真人评论对照，人工确认五类结果并计算召回/精度/风格。

benchmark MR 必须来自未参与当前 persona 蒸馏的留出集（优先使用蒸馏时间范围之后的 MR）。
当前脚本不掌握 persona 的训练 MR 清单，执行前由用户确认；未确认时在结果中明确标记潜在数据泄漏，
不得把近似复现训练样本当作泛化能力。

### 为什么按 MR 而不是 commit

review 走 `--commit`，但真人评论挂在 MR 上、enriched 没存 commit_id——两者键对不上。
benchmark 的解法是按 **`domain + project_path + mr_iid`** 对齐：AI 评该 MR 的 diff，
真人评论也从 enriched 里按同一项目和 MR 取，并复核真人评论位置是否仍在当前 diff，
避开走 `merge_commit_sha` 的 squash/rebase diff 不一致噪声。

### 参数

```
# ① 列候选 MR（纯本地读 enriched，不需内网/token）
/code-review benchmark --reviewer-w3 <工号>

# ② 选一个 MR，生成 benchmark case + AI 报告；domain 从 enriched 自动取得
#    project_path 不用打；persona 一律取 --reviewer-w3 同人（验证的就是本人复现本人）
/code-review benchmark --reviewer-w3 <工号> --pick <序号>
# 或按 mr_iid
/code-review benchmark --reviewer-w3 <工号> --mr-iid <iid>
# mr_iid 在多个项目重复时必须增加 --project-path <完整项目路径>
# 仅旧 enriched 无 domain 或跨地域消歧时补 --domain <地域>
```

`--reviewer-w3` = 谁的真实评审当 ground truth（候选 MR 池 + 真人评论来自此人 enriched）。
**persona 一律取 `--reviewer-w3` 同人**（`load_persona --w3`）——benchmark 验证的就是"本人 persona 复现本人评论"，
用别人的 persona 评此人的真实评论是在比两个评审人的观点差异，与 persona 蒸馏质量无关，不做。

### 执行流程

**Step 1 列候选 MR**（确定性，脚本）
```bash
python <SKILL_ROOT>/scripts/benchmark/collect_benchmark_case.py \
  --reviewer-w3 <工号> --list
```
从 `outputs/enriched/*.jsonl` 按 `(project_path, mr_iid)` 聚合该评审人的 matched 评论，
输出 序号 | project_path/mr_iid | 真人评论数 | 严重程度（按评论数降序）。
候选集 = 有 ground truth 的 MR。

**Step 2 生成 benchmark case 输入**（确定性，脚本）
```bash
python <SKILL_ROOT>/scripts/benchmark/collect_benchmark_case.py \
  --reviewer-w3 <工号> --pick <序号>
```
- project_path 从 enriched 自动取，**用户全程不打 project_path**。
- 按 mr_iid 从 enriched 取真人评论（file/line/severity/comment/note_hash）。
- 调 `get_mr_diff` 取 MR diff，复用普通 review 的 diff 装配管线。
- domain 优先取 enriched；旧 enriched 会尝试从其 `link` 回填，仍无法取得时才要求显式参数。
- 产物目录：`outputs/benchmark/{domain}/{project_path}/mr-{iid}/reviewer-{工号}/`。
- 本步生成 `manifest.json`、`diff.json`、`diff.md`、`ground_truth.json`。
- 当前 MR diff 中找不到位置的历史评论写入 `excluded_comments`，不参与指标；若
  `benchmark_ready=false`，停止本次 benchmark，不生成 AI 比较结果。
- 同一 case 重跑时覆盖输入并清除旧 `ai_review`/`comparison`，只保留最新结果；不创建 runs 时间目录。

**Step 3 生成 AI 报告**（生成，模型）
persona 取 `--reviewer-w3` 同人（`load_persona --w3 <工号>`）。复用普通 review 的 prompt、
JSON 契约和渲染器。**生成 AI 评论时只读 `diff.json` + persona，禁止读取
`ground_truth.json` 或任何真人评论**，写 `ai_review.json` 后渲染 `ai_review.md`。
MR diff 的 `files[]` 与 commit diff 完全一致，模型评审能力不分来源。

```bash
python <SKILL_ROOT>/scripts/review/render_review.py \
  --input <benchmark_case_dir>/ai_review.json \
  --output <benchmark_case_dir>/ai_review.md \
  --manifest <benchmark_case_dir>/manifest.json
```

**Step 4 独立比较并人工确认**
AI 评论落盘后，读取 `ground_truth.json`、`ai_review.json`、`diff.json` 和
`prompts/compare_benchmark_prompt.md`，按 `references/benchmark-comparison-format.md`
生成 `comparison.json`，再用 `scripts/benchmark/render_comparison.py` 渲染 `comparison.md`。
比较 **位置 / 问题关切 / 风格 / 文本表达**，标注
**命中/部分命中/新发现/噪声/漏检**；问题关切不一致时，即使位置和语气相似也不得算命中。
- 位置：完整 file_path + 新文件行号；同行/范围重叠为 1.0，相差 1~3 行为 0.8。
- 风格：询问/命令语气、强弱、口头禅、句式、标点和建议习惯，人工校准 1~5。
- 召回 = 命中真人问题数 / 真人问题总数（按问题数，不按评论数；批量评论先归并成问题）。
- 精度 = 命中 AI 意见数 / (命中 + 部分命中 + 噪声)；新发现单独成桶不计入分母。
- 模型可以先生成候选匹配和评分，但最终结论必须人判。

```bash
python <SKILL_ROOT>/scripts/benchmark/render_comparison.py \
  --comparison <benchmark_case_dir>/comparison.json \
  --ground-truth <benchmark_case_dir>/ground_truth.json \
  --ai-review <benchmark_case_dir>/ai_review.json \
  --output <benchmark_case_dir>/comparison.md
```

一次一个 MR，从候选集采样跑 5~10 个再汇总总召回/精度/风格——这就是 persona 蒸馏质量的真信号。
批量自动取数（`--sample N`）与模型自动匹配留 Phase 1（需先用本 Phase 0 人工标注标定）。

---

## 数据链路

```
阿基米德 Excel
  → CodeHub API 补 file_path/line/severity/context
  → enriched JSONL（matched-only）
  → structured JSON
  → SKILL.md 编排模型生成草稿 → 自动校验/备份/启用 reviewer persona
  → 指定 persona 评审 commit
  → SKILL.md 编排模型生成 review report
  → benchmark：按 domain/project/MR 取真人评论 + MR diff → 复用 review 生成 AI JSON → 独立比较 → 人工确认
```

## 目录职责

```
scripts/common/   公共能力（paths/config/codehub_client/diff_parser/context_builder/excel_io/jsonl_io/filters）
scripts/distill/  生成人格链路（export/enrich/prepare/activate persona）
scripts/review/   共用评审链路（diff / persona / review Markdown 渲染）
scripts/benchmark/  benchmark 对照链路（case 收集 / comparison 渲染）
prompts/          模型提示词（persona 蒸馏 / 共用评审 / benchmark 比较）
references/       固定规则与契约（评审 JSON/Markdown、benchmark 比较、规则分类、基线）
templates/        输出模板（persona_skill_template/review_report_template/benchmark_worksheet）
personas/         最终 reviewer 人格
outputs/          运行产物（generated_personas 作暂存并保留单 previous；新评审写 review/benchmark）
cache/            缓存与登录态（mr_diffs/archimedes_session）
legacy/           旧测试脚本，仅迁移参考，非运行依赖
```

## 环境约束

- 运行于华为内网；review 依赖与内部 CodeHub 同步的本地 git 仓。
- CodeHub token 写进 skill 根目录的 `.env`（`cp .env.example .env` 后填入 `CODEHUB_TOKEN`），loader 读取时找不到 `.env` 则回退环境变量 `CODEHUB_TOKEN`。不写进代码。
- 阿基米德首次需手动浏览器登录，登录态在 `cache/archimedes_session/`，**勿提交**。
- `outputs/`、`cache/` 均在 `.gitignore`，可能含真实代码/敏感信息。
- 依赖：`pip install -r requirements.txt && playwright install chromium`。
