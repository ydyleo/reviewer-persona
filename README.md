# code-review skill

华为 CodeHub 代码评审的 Claude Code Native Skill。从历史评审数据蒸馏 reviewer 人格分身，并用指定人格评审 commit。编排入口与命令说明见 `SKILL.md`。

## 核心命令

```
/code-review distill        # 从历史评审数据生成 reviewer 人格分身
/code-review review         # 用指定人格评审单个 commit
/code-review list-personas  # 列出已有 persona
/code-review refresh-persona  # 基于新时间范围刷新 persona
```

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
scripts/      确定性数据处理（distill/review/common）
prompts/      模型编排提示词
references/   固定规则与评审报告格式契约
templates/    persona 与评审报告模板
personas/     最终 reviewer 人格（被 review 加载）
outputs/      运行产物（raw_archimedes/enriched/structured/diffs/generated_personas/reports）
cache/        缓存与登录态（mr_diffs/archimedes_session）
legacy/       旧测试脚本，仅迁移参考，非运行依赖
```

完整命令流程、参数与编排细节见 `SKILL.md`。
