"""DS permutation-swarm WIN-anchor harness (DSP1).

Scores Daemon Slayer top-N item rankings (the 2026-06-16 per-champion cross-eval
comp_grid) against per-item WIN-rate from data/rewind_history.db, per (champion x
mode), via difference-of-differences. BUILD-only foundation for the DSP2-DSP10 swarm;
no engine state is touched. See docs/DS_PERMUTATION_SWARM_PLAN.md ("DSP1").
"""
from .cross_eval_loader import (
    CrossEval,
    DSItem,
    EmpiricalBlock,
    EmpiricalItem,
    cross_eval_from_dict,
    load_cross_eval,
    load_cross_eval_dir,
)
from .consolidate import (
    BuriedWinner,
    ChampMismatch,
    TopItemView,
    champ_mismatch,
    consolidate,
)
from .perm_score import (
    BucketScore,
    ChampScore,
    PermConfig,
    build_report,
    score_champ,
)
from .win_anchor import (
    MODE_BY_MAP,
    ChampModeWin,
    ItemWinRate,
    compute_champ_win,
    compute_win_rates,
    resolve_mode,
)

__all__ = [
    "CrossEval",
    "DSItem",
    "EmpiricalBlock",
    "EmpiricalItem",
    "cross_eval_from_dict",
    "load_cross_eval",
    "load_cross_eval_dir",
    "BucketScore",
    "ChampScore",
    "PermConfig",
    "build_report",
    "score_champ",
    "BuriedWinner",
    "ChampMismatch",
    "TopItemView",
    "champ_mismatch",
    "consolidate",
    "MODE_BY_MAP",
    "ChampModeWin",
    "ItemWinRate",
    "compute_champ_win",
    "compute_win_rates",
    "resolve_mode",
]
