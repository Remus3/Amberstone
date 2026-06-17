"""Difference-of-differences scorer: does DS rank empirically-winning items higher?

For each (champion x mode x DS-comp-bucket) we take DS's top-K item ids (cross-eval
comp_grid) and look up each one's rewind WIN-rate (win_anchor). The bucket's outcome
alignment is the LIFT of its DS-favored items over the champion's baseline win-rate:

    lift = mean(item_wr for DS-top-K items with n >= min_item_n) - baseline_wr

Lift is a difference of differences (item-WR vs baseline), never a fragile cross-item
equality, so it is robust to the small per-item samples in rewind_history.db. A second,
softer signal is the rank correlation between DS goodness (-rank) and item WR over the
overlap set (positive = DS orders winners first).

No engine state is touched; this module is pure given a CrossEval + a ChampModeWin.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cross_eval_loader import CrossEval
from .win_anchor import ChampModeWin


@dataclass(frozen=True)
class PermConfig:
    top_k: int = 6
    min_item_n: int = 1


@dataclass(frozen=True)
class BucketScore:
    bucket: str
    overlap_n: int
    mean_wr_topk: float | None
    lift_vs_baseline: float | None
    rank_corr: float | None


@dataclass(frozen=True)
class ChampScore:
    champion: str
    mode: str
    n_games: int
    baseline_wr: float | None
    buckets: dict[str, BucketScore]
    mean_lift: float | None


def _rankdata(vals: list[float]) -> list[float]:
    """Average-rank (1-based) of each value; ties share the mean rank."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = sum((a[i] - ma) ** 2 for i in range(n)) ** 0.5
    db = sum((b[i] - mb) ** 2 for i in range(n)) ** 0.5
    if da == 0 or db == 0:
        return None
    return round(num / (da * db), 4)


def _spearman(pairs: list[tuple[int, float]]) -> float | None:
    """Correlate DS goodness (-rank) with item WR; positive = winners ranked first."""
    if len(pairs) < 2:
        return None
    goodness = [float(-p[0]) for p in pairs]
    wr = [p[1] for p in pairs]
    return _pearson(_rankdata(goodness), _rankdata(wr))


def _score_bucket(bucket: str, ds_items, cmw: ChampModeWin, cfg: PermConfig) -> BucketScore:
    topk = ds_items[: cfg.top_k]
    pairs: list[tuple[int, float]] = []
    wrs: list[float] = []
    for it in topk:
        rec = cmw.items.get(it.id)
        if rec is None or rec.n < cfg.min_item_n:
            continue
        pairs.append((it.rank, rec.wr))
        wrs.append(rec.wr)
    if not wrs:
        return BucketScore(bucket, 0, None, None, None)
    mean_wr = round(sum(wrs) / len(wrs), 4)
    lift = round(mean_wr - cmw.baseline_wr, 4) if cmw.baseline_wr is not None else None
    return BucketScore(bucket, len(wrs), mean_wr, lift, _spearman(pairs))


def score_champ(ce: CrossEval, cmw: ChampModeWin, cfg: PermConfig | None = None) -> ChampScore:
    cfg = cfg or PermConfig()
    buckets: dict[str, BucketScore] = {}
    for bucket, ds_items in ce.comp_grid.items():
        buckets[bucket] = _score_bucket(bucket, ds_items, cmw, cfg)
    lifts = [b.lift_vs_baseline for b in buckets.values() if b.lift_vs_baseline is not None]
    mean_lift = round(sum(lifts) / len(lifts), 4) if lifts else None
    return ChampScore(ce.champion, cmw.mode, cmw.n, cmw.baseline_wr, buckets, mean_lift)


def _bucket_dict(b: BucketScore) -> dict:
    return {
        "bucket": b.bucket,
        "overlap_n": b.overlap_n,
        "mean_wr_topk": b.mean_wr_topk,
        "lift_vs_baseline": b.lift_vs_baseline,
        "rank_corr": b.rank_corr,
    }


def _champ_dict(cs: ChampScore) -> dict:
    return {
        "champion": cs.champion,
        "mode": cs.mode,
        "n_games": cs.n_games,
        "baseline_wr": cs.baseline_wr,
        "mean_lift": cs.mean_lift,
        "buckets": {k: _bucket_dict(v) for k, v in cs.buckets.items()},
    }


def build_report(
    cross_evals: dict[str, CrossEval],
    win_by_champ_mode: dict[tuple[str, str], ChampModeWin],
    cfg: PermConfig | None = None,
    modes: tuple[str, ...] = ("ARAM", "SR"),
    anchor_match_only: bool = True,
) -> dict:
    """Aggregate a per-(champ x mode) report from the DS rankings + WIN anchor.

    cross_evals: file-stem -> CrossEval. win_by_champ_mode: (champion, mode) -> ChampModeWin.

    The comp_grid is computed ONCE at each champion's anchor_mode (with that mode's
    modifiers applied). Scoring an ARAM-anchored ranking against SR win outcomes (or
    vice versa) is apples-to-oranges - DS would recommend a different build for the
    other mode - so anchor_match_only (default True) scores only the anchor-matched
    mode. On the live roster 171/172 anchor ARAM, so this drops the spurious SR column
    that otherwise dominated the divergent tail (e.g. Ezreal SR mean_wr 0.0). A valid
    cross-mode score would need a per-mode re-probe (FUTURE).
    """
    cfg = cfg or PermConfig()
    champ_rows: list[dict] = []
    scored: list[ChampScore] = []
    considered = 0
    for ce in cross_evals.values():
        for mode in modes:
            if anchor_match_only and ce.anchor_mode and mode != ce.anchor_mode:
                continue
            cmw = win_by_champ_mode.get((ce.champion, mode))
            if cmw is None or cmw.n == 0:
                continue
            considered += 1
            cs = score_champ(ce, cmw, cfg)
            champ_rows.append(_champ_dict(cs))
            if cs.mean_lift is not None:
                scored.append(cs)
    n_scored = len(scored)
    n_pos = sum(1 for cs in scored if cs.mean_lift > 0)
    total_games = sum(cs.n_games for cs in scored)
    weighted = (
        round(sum(cs.mean_lift * cs.n_games for cs in scored) / total_games, 4)
        if total_games
        else None
    )
    unweighted = round(sum(cs.mean_lift for cs in scored) / n_scored, 4) if n_scored else None
    champ_rows.sort(key=lambda r: (r["mean_lift"] is None, -(r["mean_lift"] or 0.0)))
    return {
        "config": {
            "top_k": cfg.top_k,
            "min_item_n": cfg.min_item_n,
            "modes": list(modes),
            "anchor_match_only": anchor_match_only,
        },
        "aggregate": {
            "n_champ_mode_considered": considered,
            "n_champs_scored": n_scored,
            "n_positive_lift": n_pos,
            "pct_positive_lift": round(100.0 * n_pos / n_scored, 2) if n_scored else None,
            "mean_lift_weighted": weighted,
            "mean_lift_unweighted": unweighted,
        },
        "champs": champ_rows,
    }
