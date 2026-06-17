"""DSP10 consolidated mismatch report.

For the most outcome-divergent anchor-matched champ-modes (lowest mean_lift from the
DSP1 difference-of-differences scorer), join the items DS favors (comp_grid top-K,
union across the target-preset buckets) against the empirical above-baseline winning
items DS BURIES, so a later per-champion fix targets the real gap instead of guessing.

Pure given a CrossEval map + a ChampModeWin map (the DSP1 substrate). No engine state
is touched; the hermetic tests synthesize their own fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cross_eval_loader import CrossEval
from .perm_score import PermConfig, score_champ
from .win_anchor import ChampModeWin


@dataclass(frozen=True)
class TopItemView:
    """A DS-favored item with its live rewind outcome (None wr = no rewind data)."""

    best_rank: int
    id: str
    name: str
    rewind_n: int
    rewind_wr: float | None


@dataclass(frozen=True)
class BuriedWinner:
    """An above-baseline empirical winner that DS does NOT put in any bucket top-K."""

    id: str
    name: str
    n: int
    wr: float
    lift_over_baseline: float


@dataclass(frozen=True)
class ChampMismatch:
    champion: str
    mode: str
    scorer: str
    archetype: str
    n_games: int
    baseline_wr: float | None
    mean_lift: float | None
    ds_top: tuple[TopItemView, ...]
    buried_winners: tuple[BuriedWinner, ...]


def _ds_favored(ce: CrossEval, top_k: int) -> dict[str, tuple[int, str]]:
    """Union of comp_grid top-K item ids across all buckets -> (best_rank, name)."""
    favored: dict[str, tuple[int, str]] = {}
    for items in ce.comp_grid.values():
        for it in items[:top_k]:
            prev = favored.get(it.id)
            if prev is None or it.rank < prev[0]:
                favored[it.id] = (it.rank, it.name)
    return favored


def champ_mismatch(
    ce: CrossEval,
    cmw: ChampModeWin,
    cfg: PermConfig | None = None,
    max_buried: int = 8,
) -> ChampMismatch:
    """Build the DS-top vs buried-winner view for one anchor-matched champ-mode."""
    cfg = cfg or PermConfig()
    cs = score_champ(ce, cmw, cfg)
    favored = _ds_favored(ce, cfg.top_k)

    ds_top: list[TopItemView] = []
    for iid, (rank, name) in sorted(favored.items(), key=lambda kv: kv[1][0]):
        rec = cmw.items.get(iid)
        ds_top.append(
            TopItemView(
                best_rank=rank,
                id=iid,
                name=name,
                rewind_n=rec.n if rec else 0,
                rewind_wr=rec.wr if rec else None,
            )
        )

    # Buried winners come from the curated cross-eval empirical block (mode-matched),
    # gated to n >= min_item_n and a win-rate above the champion baseline, excluding
    # anything DS already favors. These are the items a per-champion fix should lift.
    buried: list[BuriedWinner] = []
    block = ce.empirical.get(cmw.mode)
    base = cmw.baseline_wr if cmw.baseline_wr is not None else 0.0
    if block is not None:
        for it in block.items:
            if it.n < cfg.min_item_n or it.id in favored or it.wr <= base:
                continue
            buried.append(
                BuriedWinner(
                    id=it.id,
                    name=it.name,
                    n=it.n,
                    wr=it.wr,
                    lift_over_baseline=round(it.wr - base, 4),
                )
            )
    buried.sort(key=lambda b: b.wr, reverse=True)

    return ChampMismatch(
        champion=ce.champion,
        mode=cmw.mode,
        scorer=ce.scorer,
        archetype=ce.archetype_primary,
        n_games=cmw.n,
        baseline_wr=cmw.baseline_wr,
        mean_lift=cs.mean_lift,
        ds_top=tuple(ds_top),
        buried_winners=tuple(buried[:max_buried]),
    )


def _view_dict(v: TopItemView) -> dict:
    return {
        "best_rank": v.best_rank,
        "id": v.id,
        "name": v.name,
        "rewind_n": v.rewind_n,
        "rewind_wr": v.rewind_wr,
    }


def _buried_dict(b: BuriedWinner) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "n": b.n,
        "wr": b.wr,
        "lift_over_baseline": b.lift_over_baseline,
    }


def _mismatch_dict(m: ChampMismatch) -> dict:
    return {
        "champion": m.champion,
        "mode": m.mode,
        "scorer": m.scorer,
        "archetype": m.archetype,
        "n_games": m.n_games,
        "baseline_wr": m.baseline_wr,
        "mean_lift": m.mean_lift,
        "ds_top": [_view_dict(v) for v in m.ds_top],
        "buried_winners": [_buried_dict(b) for b in m.buried_winners],
    }


def consolidate(
    cross_evals: dict[str, CrossEval],
    win_by_champ_mode: dict[tuple[str, str], ChampModeWin],
    cfg: PermConfig | None = None,
    worst_n: int = 30,
) -> dict:
    """Worst-N anchor-matched champ-modes (lowest mean_lift) with DS-top vs buried-winner.

    Only the champion's anchor_mode is consolidated (the comp_grid is mode-specific;
    the DSP1 anchor_match_only rationale). Returns a json-serializable dict.
    """
    cfg = cfg or PermConfig()
    rows: list[ChampMismatch] = []
    for ce in cross_evals.values():
        mode = ce.anchor_mode or "ARAM"
        cmw = win_by_champ_mode.get((ce.champion, mode))
        if cmw is None or cmw.n == 0:
            continue
        m = champ_mismatch(ce, cmw, cfg)
        if m.mean_lift is None:
            continue
        rows.append(m)
    rows.sort(key=lambda m: m.mean_lift)
    worst = rows[:worst_n]
    return {
        "config": {"top_k": cfg.top_k, "min_item_n": cfg.min_item_n, "worst_n": worst_n},
        "n_consolidated": len(rows),
        "worst": [_mismatch_dict(m) for m in worst],
    }
