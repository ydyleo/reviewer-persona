# code-review skill

华为 CodeHub 代码评审的 Claude Code Native Skill。从历史评审数据**蒸馏 reviewer 人格分身**，并用指定人格评审新 commit，输出与真人评审风格一致的报告。

完整命令流程、参数与编排细节见 `SKILL.md`（单一真源，README 只给概览与上手）。

## 这是什么 / 为什么

代码评审高度依赖评审人的个人经验与习惯——关注点、措辞、语气、爱挑的毛病类型。但每个 reviewer 的"评审风格"是隐性的，新人学不来，团队也难以沉淀。

这个 skill 把这件事显性化、可复用：

1. **采集**某评审人在 CodeHub / 阿基米德上**真实写过的**历史评审意见（带代码上下文）；
2. **蒸馏**成一份"人格分身"（persona）规则集——**保留该评审人的语言习惯原样**（口头禅、句式、吐槽方式），不 AI 化润色；
3. 用这个 persona 去**评审新的 commit**，产出风格与该真人一致的评审报告。

效果：相当于让这位评审人"分身"去评他没看过的代码，风格与关注点都延续他本人。

> persona 分身 = 一份 `.md` 规则文件，含强制固定约束（保语言风格）+ 核心评审偏好 + 分身专属规则（按 S/P/B/A/C/D 六类编号）+ 输出要求（铁律格式块）。

## 概念三段式

```
① 采集 Collect          ② 蒸馏 Distill            ③ 评审 Review
─────────────           ─────────────             ─────────────
阿基米德 Excel           历史评审 + 代码上下文       persona 规则集
+ CodeHub API 补        → 结构化 JSON             + 新 commit 的 diff
  file/line/上下文        → 模型编排生成            → 模型编排生成
→ enriched JSONL          persona skill 文件         评审报告
```

- **采集**：阿基米德 Excel 是评审意见的单一入口；CodeHub API 补 `file_path/line/severity` 和目标行代码上下文，产出 enriched JSONL。
- **蒸馏**：模型读 enriched + 结构化 JSON，按 prompt + template 生成 persona `.md`，写入 `personas/`。
- **评审**：模型读 persona + commit diff，按格式契约生成报告。

## 核心命令

```
/code-review distill          # 从历史评审数据生成 reviewer 人格分身
/code-review review           # 用指定人格评审单个 commit
/code-review list-personas    # 列出已有 persona
/code-review refresh-persona  # 基于新时间范围刷新 persona（备份旧版后覆盖）
/code-review benchmark        # persona 质量评估：AI 评审 vs 真人评论（人工比对召回/精度/风格）
```

## 快速上手

```bash
# 1. 装依赖
pip install -r requirements.txt
playwright install chromium          # 阿基米德导出需要

# 2. 配 CodeHub token（CodeHub → Settings → Access Tokens 取）
cp .env.example .env
#   编辑 .env 填入 CODEHUB_TOKEN

# 3. 蒸馏某评审人的 persona（首次会在浏览器弹阿基米德登录，不要 headless）
/code-review distill --reviewer-w3 <工号> \
  --start 2024-07-01 --end 2024-08-01 --domain codehub-g

# 4. 用该 persona 评审一个 commit（在目标代码仓目录执行）
/code-review review --commit <commit_id> --persona <工号>
```

第 3 步产出 `personas/reviewer-{姓名}-{工号}.skill.md`；第 4 步产出评审报告（对话输出或落 `outputs/reports/`）。

更细的参数、每步脚本、报告格式契约见 `SKILL.md`。

## 主数据链路

```
阿基米德 Excel → CodeHub API 补 file_path/line/severity/context
  → enriched JSONL → structured JSON
  → SKILL.md 编排模型生成 reviewer persona
  → 指定 persona 评审 commit → SKILL.md 编排模型生成 review report
```

## 安装

```bash
pip install -r requirements.txt
playwright install chromium   # 阿基米德导出需要
cp .env.example .env          # 复制配置模板
# 编辑 .env，填入 CODEHUB_TOKEN（CodeHub → Settings → Access Tokens）
```

`.env` 已在 `.gitignore`，勿提交真实 token。也可改用环境变量 `export CODEHUB_TOKEN=xxxx`，loader 找不到 `.env` 时会回退读环境变量。

## 环境约束

- 运行于华为内网，依赖与内部 CodeHub 同步的本地 git 仓。
- 阿基米德首次运行需手动浏览器登录（不要 headless），登录态存于 `cache/archimedes_session/`，**勿提交**。
- `outputs/`、`cache/` 均锚定 skill 根目录，已在 `.gitignore` 中忽略。
- `/code-review review` 在目标代码仓目录执行时，报告仍写入 skill 根 `outputs/reports/`，不污染目标仓。

## 目录速览

```
scripts/      确定性数据处理（distill/review/common/benchmark）
prompts/      模型编排提示词
references/   固定规则与评审报告格式契约
templates/    persona 与评审报告模板
personas/     最终 reviewer 人格（被 review 加载）
outputs/      运行产物（raw_archimedes/enriched/structured/diffs/generated_personas/reports/benchmark）
cache/        缓存与登录态（mr_diffs/archimedes_session）
legacy/       旧测试脚本，仅迁移参考，非运行依赖
```

完整命令流程、参数与编排细节见 `SKILL.md`。
