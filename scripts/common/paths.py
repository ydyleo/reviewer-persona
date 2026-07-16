"""Skill 工程路径锚点。

所有脚本统一从这里引入路径常量，避免在目标代码仓当前目录下
误写 outputs/ 或 cache/。paths.py 只负责定位输出和资源路径；
跨目录 import 仍需要入口脚本把 scripts/ 加入 sys.path。
"""
from pathlib import Path

# code-review/scripts/common/paths.py -> parents[2] = code-review/
SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = SKILL_ROOT / "scripts"

OUTPUTS_DIR = SKILL_ROOT / "outputs"
CACHE_DIR = SKILL_ROOT / "cache"
PERSONAS_DIR = SKILL_ROOT / "personas"
PROMPTS_DIR = SKILL_ROOT / "prompts"
TEMPLATES_DIR = SKILL_ROOT / "templates"
REFERENCES_DIR = SKILL_ROOT / "references"
SCHEMAS_DIR = SKILL_ROOT / "schemas"

# outputs/ 子目录
RAW_ARCHIMEDES_DIR = OUTPUTS_DIR / "raw_archimedes"
ENRICHED_DIR = OUTPUTS_DIR / "enriched"
STRUCTURED_DIR = OUTPUTS_DIR / "structured"
DIFFS_DIR = OUTPUTS_DIR / "diffs"
PROFILES_DIR = OUTPUTS_DIR / "profiles"
GENERATED_PERSONAS_DIR = OUTPUTS_DIR / "generated_personas"
REPORTS_DIR = OUTPUTS_DIR / "reports"
BENCHMARK_DIR = OUTPUTS_DIR / "benchmark"
REVIEW_DIR = OUTPUTS_DIR / "review"

# cache/ 子目录
MR_DIFFS_CACHE_DIR = CACHE_DIR / "mr_diffs"
ARCHIMEDES_SESSION_DIR = CACHE_DIR / "archimedes_session"

PERSONA_BACKUP_DIR = GENERATED_PERSONAS_DIR / "backup"


def ensure_dirs() -> None:
    """首次运行时确保 outputs/cache 关键子目录存在。

    persona/prompt/template/reference 等工程资源目录由仓库管理，
    不在此创建。
    """
    for d in (
        RAW_ARCHIMEDES_DIR,
        ENRICHED_DIR,
        STRUCTURED_DIR,
        DIFFS_DIR,
        PROFILES_DIR,
        GENERATED_PERSONAS_DIR,
        PERSONA_BACKUP_DIR,
        REPORTS_DIR,
        BENCHMARK_DIR,
        REVIEW_DIR,
        MR_DIFFS_CACHE_DIR,
        ARCHIMEDES_SESSION_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
