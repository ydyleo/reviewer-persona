---
name: code-review
description: 华为 CodeHub 代码评审 skill。从历史评审数据蒸馏 reviewer 人格分身（/code-review distill），用指定人格评审 commit（/code-review review）。阿基米德 Excel 驱动单数据入口，模型生成由本 skill 编排。
user-invocable: true
origin: local
---

# code-review 调度入口

华为 CodeHub 代码评审 skill。从历史评审数据蒸馏 reviewer 人格分身，并用指定人格评审 commit。确定性数据处理由 `scripts/` 下 Python 脚本完成，persona 与评审报告的生成由本 skill 编排当前模型按 prompt + template 完成。

## 核心命令

```
/code-review distill        # 从历史评审数据生成 reviewer 人格分身
/code-review review         # 用指定人格评审单个 commit
/code-review list-personas  # 列出已有 persona
/code-review refresh-persona  # 基于新时间范围刷新 persona（备份旧版后覆盖）
/code-review benchmark      # persona 质量评估：AI 评审 vs 真人评论，人工四分类算召回/精度/风格
```

## 关键约定

1. **脚本用绝对路径调用**。本 skill 根目录 `<SKILL_ROOT>` = 当前 `SKILL.md` 所在目录。调用脚本时写 `python <SKILL_ROOT>/scripts/...`，不要写 `python scripts/...`（review 经常在目标代码仓目录执行，相对路径会失效）。
2. **确定性工作由 Python 脚本做；生成类工作（persona、评审报告）由当前模型按 prompt + template 编排完成**，不写独立 LLM 调用脚本。
3. **运行产物锚定 skill 根目录**（outputs/、cache/、personas/），不写入被评审目标仓。脚本内部走 `scripts/common/paths.py`。
4. **评审报告格式是契约**。persona 意见、报告、prompt、template 四处必须使用 `references/review-output-format.md` 的同一套 token（`【{分身姓名}意见】` / `【评审来源】` / `【位置】` / 连贯段落 / `【修改示例】` / `---`，严重程度四档分组）。禁止拆 `【问题根因】`/`【修改建议】` 等字段。

---

## 命令一：/code-review distill

### 参数

```
/code-review distill \
  --reviewer-w3 <工号> \
  --start <YYYY-MM-DD> \
  --end <YYYY-MM-DD> \
  --domain <codehub-y|codehub-g|cr-y.codehub|open.codehub>
```

`--domain` 只用于后续 enrich 调 CodeHub API；export 阿基米德不需要 domain。

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
  --reviewer-w3 <工号> --domain <地域> --start <起> --end <止>
```
- comment 取阿基米德 Excel 检视意见；file_path/line/severity 取 CodeHub /reviews；diff/上下文取 CodeHub /changes。
- 正式输出只保留 `context_status = matched` 的记录。
- 产物：`outputs/enriched/{工号}_{起}_{止}_enriched.xlsx` 和 `.jsonl`

**Step 3 生成结构化 JSON**
```bash
python <SKILL_ROOT>/scripts/distill/prepare_review_data.py \
  --input <SKILL_ROOT>/outputs/enriched/<上面>.jsonl
```
- 产物：`outputs/structured/{工号}_{起}_{止}_structured.json`（含 meta / reviews / pattern_clusters / file_distribution）

**Step 4 模型编排生成 persona（本步由当前模型完成）**

读取以下文件组织输入：
- `outputs/structured/<上面>.json`
- `prompts/distill_persona_prompt.md`
- `templates/persona_skill_template.md`
- `references/rule-taxonomy.md`
- `references/review-output-format.md`（persona 的"输出要求"段须内嵌铁律格式块）

按 distill prompt 硬性要求生成，写入草稿：
`outputs/generated_personas/reviewer-{姓名}-{工号}.skill.md`

人工确认后，复制到正式目录：`personas/reviewer-{姓名}-{工号}.skill.md`。

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
- 产物：`outputs/diffs/{commit}_diff.json` 和 `.md`（锚定 skill 根，不写入目标仓）。

**Step 2 加载 persona**

```bash
python <SKILL_ROOT>/scripts/review/load_persona.py --w3 <工号>
# 或 --name <姓名>；或 --list 列出全部
```
输出 persona 文件路径，读取其内容（强制固定约束 / 核心评审偏好 / 分身专属规则 / 输出要求）。

**Step 3 模型编排生成评审报告（本步由当前模型完成）**

读取以下文件组织输入：
- `outputs/diffs/{commit}_diff.json`（结构化 diff，含 file_path + 行号）
- persona 文件内容
- `prompts/review_with_persona_prompt.md`
- `templates/review_report_template.md`
- `references/review-output-format.md`
- 可选 `references/cpp-baseline.md`（若加载，先做基线扫描，命中走"通用基线违规区"）

按 review prompt 要求生成报告：
- 100% 复刻 persona 语言习惯（语气/口头禅/句式/吐槽/书面化负面清单）。
- 每条意见必须有文件名+行号（取 diff 新文件行号），能对应 persona 规则编号。
- 连贯一段话描述，代码放 `【修改示例】`。
- 按严重程度（高危/中危/低危/优化建议）在 `## 评审意见` 下分组。

报告可直接在对话输出，或落盘：
`<SKILL_ROOT>/outputs/reports/{commit}_{persona}_review.md`

---

## 命令三：/code-review list-personas

```bash
python <SKILL_ROOT>/scripts/review/load_persona.py --list
```
展示 姓名 / 工号 / 规则数 / 关注领域。

---

## 命令四：/code-review refresh-persona

### 参数

```
/code-review refresh-persona \
  --reviewer-w3 <工号> --start <起> --end <止> --domain <地域>
```

### 执行流程

1. 备份旧版正式 persona 到 `outputs/generated_personas/backup/reviewer-{姓名}-{工号}_<时间戳>.skill.md`（带时间戳，可回滚）。
2. 重跑 distill 的 Step 1~4（同 `--reviewer-w3`，新 `--start/--end`）。
3. 新版 persona 草稿经人工确认后覆盖 `personas/reviewer-{姓名}-{工号}.skill.md`。

不要无备份直接覆盖正式 persona。

---

## 命令五：/code-review benchmark

评估 persona 蒸馏质量：拿该评审人**真实评审过的 MR**，让 persona 生成 AI 评审，
与真人评论对照，人工填四分类算召回/精度/风格。

### 为什么按 MR 而不是 commit

review 走 `--commit`，但真人评论挂在 MR 上、enriched 没存 commit_id——两者键对不上。
benchmark 的解法是**按 `mr_iid` 对齐**：AI 评该 MR 自己的 diff（`get_mr_diff` 已能取，
= 真人当时评的那份），真人评论也在 enriched 里按 `mr_iid` 取，两边同键同 diff，行号天然对齐，
避开走 `merge_commit_sha` 的 squash/rebase diff 不一致噪声。

### 参数

```
# ① 列候选 MR（纯本地读 enriched，不需内网/token）
/code-review benchmark --reviewer-w3 <工号>

# ② 选一个 MR，出对照包 + AI 报告
#    project_path 不用打；persona 一律取 --reviewer-w3 同人（验证的就是本人复现本人）
/code-review benchmark --reviewer-w3 <工号> --pick <序号> --domain <地域>
# 或按 mr_iid
/code-review benchmark --reviewer-w3 <工号> --mr-iid <iid> --domain <地域>
```

`--reviewer-w3` = 谁的真实评审当 ground truth（候选 MR 池 + 真人评论来自此人 enriched）。
**persona 一律取 `--reviewer-w3` 同人**（`load_persona --w3`）——benchmark 验证的就是"本人 persona 复现本人评论"，
用别人的 persona 评此人的真实评论是在比两个评审人的观点差异，与 persona 蒸馏质量无关，不做。

### 执行流程

**Step 1 列候选 MR**（确定性，脚本）
```bash
python <SKILL_ROOT>/scripts/benchmark/collect_benchmark_pairs.py \
  --reviewer-w3 <工号> --list
```
从 `outputs/enriched/*.jsonl` 按 `mr_iid` 聚合该评审人的 matched 评论，
输出 序号 | project_path/mr_iid | 真人评论数 | 严重程度（按评论数降序）。
候选集 = 有 ground truth 的 MR。

**Step 2 出对照包**（确定性，脚本）
```bash
python <SKILL_ROOT>/scripts/benchmark/collect_benchmark_pairs.py \
  --reviewer-w3 <工号> --pick <序号> --domain <地域>
```
- project_path 从 enriched 自动取，**用户全程不打 project_path**。
- 按 mr_iid 从 enriched 取真人评论（file/line/severity/comment/note_hash）。
- 调 `get_mr_diff` 取 MR diff，走与 review `--mr` 同一管线，落 `outputs/diffs/{mr_iid}_mrdiff.json`。
- 产物：`outputs/benchmark/{mr_iid}_pair.json`（real_comments + 对 mrdiff.json 的引用，自包含真人侧）。

**Step 3 生成 AI 报告**（生成，模型）
persona 取 `--reviewer-w3` 同人（`load_persona --w3 <工号>`）。
模型读 `outputs/diffs/{mr_iid}_mrdiff.json`（diff 已在 Step 2 拉好，**无需 project_path/domain 再拉一遍**）
+ persona 内容 + `prompts/review_with_persona_prompt.md` + `references/review-output-format.md`，
按 persona 生成 AI 报告，落 `outputs/reports/{mr_iid}_{persona}_review.md`。
（mrdiff.json 的 files[] 形状与 commit 模式的 `{commit}_diff.json` 一致，review 模型步骤不分来源。）

**Step 4 人工对照填四分类**
照 `templates/benchmark_worksheet.md` 把真人问题（pair.json 的 real_comments 归并）与 AI 意见逐对标
**命中/部分命中/新发现/噪声/漏检** + 风格 1-5，底部算召回/精度。
- 召回 = 命中真人问题数 / 真人问题总数（按问题数，不按评论数；批量评论先归并成问题）。
- 精度 = 命中 AI 意见数 / (命中 + 部分命中 + 噪声)；新发现单独成桶不计入分母。
- 风格 = 主观打分，自动不可靠，必须人判。

一次一个 MR，从候选集采样跑 5~10 个再汇总总召回/精度/风格——这就是 persona 蒸馏质量的真信号。
批量自动取数（`--sample N`）与模型自动匹配留 Phase 1（需先用本 Phase 0 人工标注标定）。

---

## 数据链路

```
阿基米德 Excel
  → CodeHub API 补 file_path/line/severity/context
  → enriched JSONL（matched-only）
  → structured JSON
  → SKILL.md 编排模型生成 reviewer persona skill
  → 指定 persona 评审 commit
  → SKILL.md 编排模型生成 review report
  → benchmark：按 mr_iid 取真人评论 + MR diff → AI 报告 vs 真人评论 → 人工四分类 → 召回/精度/风格
```

## 目录职责

```
scripts/common/   公共能力（paths/config/codehub_client/diff_parser/context_builder/excel_io/jsonl_io/filters）
scripts/distill/  生成人格链路（export_archimedes/enrich_reviews/prepare_review_data）
scripts/review/   评审 commit 链路（get_commit_diff/load_persona）
scripts/benchmark/  benchmark 对照链路（collect_benchmark_pairs）
prompts/          模型提示词（distill_persona_prompt/review_with_persona_prompt）
references/       固定规则与契约（review-output-format/rule-taxonomy/cpp-baseline）
templates/        输出模板（persona_skill_template/review_report_template/benchmark_worksheet）
personas/         最终 reviewer 人格
outputs/          运行产物（raw_archimedes/enriched/structured/diffs/generated_personas/reports/benchmark）
cache/            缓存与登录态（mr_diffs/archimedes_session）
legacy/           旧测试脚本，仅迁移参考，非运行依赖
```

## 环境约束

- 运行于华为内网；review 依赖与内部 CodeHub 同步的本地 git 仓。
- CodeHub token 写进 skill 根目录的 `.env`（`cp .env.example .env` 后填入 `CODEHUB_TOKEN`），loader 读取时找不到 `.env` 则回退环境变量 `CODEHUB_TOKEN`。不写进代码。
- 阿基米德首次需手动浏览器登录，登录态在 `cache/archimedes_session/`，**勿提交**。
- `outputs/`、`cache/` 均在 `.gitignore`，可能含真实代码/敏感信息。
- 依赖：`pip install -r requirements.txt && playwright install chromium`。
