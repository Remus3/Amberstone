"""
core/augment_recommender.py - data-driven Mayhem/Arena augment ranking.

CLAUDE.md #88 / plan `Desktop/MAYHEM_AUGMENT_RECOMMENDER_PLAN_2026-05-17.md`.
The augment-OCR → coach path is already live (item 86): vision reads *which
augments are offered*; this module decides *which to take* by historical
win-rate, conditioned on the augments already taken this game.

Algorithm - re-implemented from the plan's math spec (§4/§5), NOT vendored
from `ReformedDoge/Mayhem-Doctor` (no LICENSE - algorithm only, §7):

  • Per-augment own win-rate, Laplace/Beta-smoothed toward 0.5:
        own_wr(a) = (wins[a] + α) / (games[a] + 2α)
  • External per-augment marginal prior (Task 2, Overlay App E Mayhem data).
  • §4 blend (Option B external-seed):
        score₀(a) = w·own_wr(a) + (1−w)·ext_wr(a),  w = n_own/(n_own+K)
    Zero own games ⇒ w=0 ⇒ 100 % external prior; shifts to own history
    smoothly as ingest grows (Task-1 reality: n_own ≈ 0-2 today).
  • Pairwise co-occurrence synergy (own-history only - the external source
    has no augment-pair data), shrunk by its own sample count:
        syn(a) = mean_{p∈picked} [ m/(m+K) · (pair_wr(a,p) − own_wr(a)) ]
    Conditioning on the already-picked set === the plan's "greedy synergy".
  • Final: score(a) = score₀(a) + λ·syn(a).

Confidence surfaced for §6 is the blend weight w (how much own-history is
trusted). Never raises into callers; with neither own nor external data the
result is a neutral 0.5 ranking at confidence 0, so the coach keeps its LLM
augment prompt as the primary signal (§5: parallel, not fallback).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Optional, Sequence

from core import augment_external_source as _ext
from core import smoothed_rates as _sr

_log = logging.getLogger("rc.augment_recommender")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _PROJECT_ROOT / "data" / "match_history.db"

# Mode → (gameMode, queueId set) for filtering lcu_match_detail.
_MODE_FILTERS = {
    "mayhem": ("KIWI", {2400}),
    "arena": ("CHERRY", {1700, 1710}),
}

# Smoothed-rate family defaults sourced from the shared primitive so
# the augment recommender, pick/ban synergy, and the PGR score stay
# statistically coherent (CLAUDE.md #90). Re-exported under the
# recommender's long-standing public names for callers/tests.
DEFAULT_ALPHA = _sr.DEFAULT_ALPHA   # Laplace/Beta prior strength (-> 0.5)
DEFAULT_K = _sr.DEFAULT_K           # n/(n+K) shrinkage (the n/(n+5) family)
DEFAULT_SYNERGY_WEIGHT = 1.0        # lambda on the (already-shrunk) synergy term

_lock = threading.Lock()
_own_cache: dict[str, "OwnHistory"] = {}
_own_cache_key: dict[str, tuple] = {}


@dataclass(frozen=True)
class OwnHistory:
    """Tracked-player augment outcomes for one mode, from
    match_history.db `raw_data.lcu_match_detail`."""

    mode: str
    games: dict[int, int] = field(default_factory=dict)       # aug -> games taken
    wins: dict[int, int] = field(default_factory=dict)        # aug -> games won
    pair_games: dict[tuple, int] = field(default_factory=dict)  # (a<b) -> games
    pair_wins: dict[tuple, int] = field(default_factory=dict)
    total_games: int = 0
    total_wins: int = 0
    n_matches: int = 0

    def n_own(self, a: int) -> int:
        return int(self.games.get(a, 0))


@dataclass(frozen=True)
class AugmentScore:
    augment_id: int
    name: str
    rarity: Optional[str]
    score: float            # final blended + synergy score
    base: float             # blended marginal (pre-synergy)
    own_wr: float
    ext_wr: Optional[float]
    blend_w: float          # = confidence
    n_own: int
    synergy: float

    @property
    def confidence(self) -> float:
        return self.blend_w


@dataclass(frozen=True)
class RecommendationResult:
    mode: str
    ranked: list[AugmentScore]
    used_external: bool
    n_matches: int
    stage: Optional[int] = None

    @property
    def top(self) -> Optional[AugmentScore]:
        return self.ranked[0] if self.ranked else None


def _participant_for_puuid(detail: dict, puuid: str) -> Optional[dict]:
    pid_by_puuid = {}
    for pi in detail.get("participantIdentities") or []:
        pl = pi.get("player") or {}
        if pl.get("puuid"):
            pid_by_puuid[pl["puuid"]] = pi.get("participantId")
    target_pid = pid_by_puuid.get(puuid)
    if target_pid is None:
        return None
    for p in detail.get("participants") or []:
        if p.get("participantId") == target_pid:
            return p
    return None


def _scan_own_history(mode: str, db_path: Path) -> OwnHistory:
    gm, qids = _MODE_FILTERS.get(mode, ("", set()))
    games: dict[int, int] = {}
    wins: dict[int, int] = {}
    pair_games: dict[tuple, int] = {}
    pair_wins: dict[tuple, int] = {}
    total_games = total_wins = n_matches = 0

    if not db_path.exists():
        return OwnHistory(mode=mode)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        _log.warning("augment_recommender: cannot open %s: %s", db_path, exc)
        return OwnHistory(mode=mode)
    try:
        rows = conn.execute(
            "SELECT raw_data FROM matches "
            "WHERE raw_data LIKE '%lcu_match_detail%'"
        ).fetchall()
    except sqlite3.Error as exc:
        _log.warning("augment_recommender: query failed: %s", exc)
        conn.close()
        return OwnHistory(mode=mode)
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    for (raw,) in rows:
        try:
            rd = json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(rd, dict):
            continue
        d = rd.get("lcu_match_detail")
        tp = rd.get("tracked_puuid")
        if not isinstance(d, dict) or not tp:
            continue
        if d.get("gameMode") != gm and d.get("queueId") not in qids:
            continue
        me = _participant_for_puuid(d, tp)
        if me is None:
            continue
        st = me.get("stats") or {}
        augs = sorted(
            {
                int(st[f"playerAugment{i}"])
                for i in (1, 2, 3, 4, 5, 6)
                if st.get(f"playerAugment{i}")
            }
        )
        if not augs:
            continue
        won = 1 if st.get("win") else 0
        n_matches += 1
        total_games += 1
        total_wins += won
        for a in augs:
            games[a] = games.get(a, 0) + 1
            wins[a] = wins.get(a, 0) + won
        for a, b in combinations(augs, 2):  # augs already sorted → a<b
            pair_games[(a, b)] = pair_games.get((a, b), 0) + 1
            pair_wins[(a, b)] = pair_wins.get((a, b), 0) + won

    return OwnHistory(
        mode=mode,
        games=games,
        wins=wins,
        pair_games=pair_games,
        pair_wins=pair_wins,
        total_games=total_games,
        total_wins=total_wins,
        n_matches=n_matches,
    )


def _lcu_row_count(path: Path) -> int:
    """Cheap freshness signal: how many rows carry an lcu_match_detail.
    The main db file's (mtime,size) can lag under WAL and a small INSERT
    may not change the page count, so the row count is the reliable cache
    key - a newly-ingested game must invalidate the scan (§4 blend depends
    on own-history growing)."""
    if not path.exists():
        return -1
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return -1
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM matches "
                "WHERE raw_data LIKE '%lcu_match_detail%'"
            ).fetchone()[0]
        )
    except sqlite3.Error:
        return -1
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def load_own_history(mode: str = "mayhem", *, db_path: Optional[Path] = None) -> OwnHistory:
    """Cached own-history scan. Re-scans only when the count of
    augment-bearing rows (or db mtime/size) changes - augment history
    grows post-game, never mid-pick, so this is safe to call per
    augment-select tick."""
    path = db_path or _DB_PATH
    try:
        stt = path.stat()
        key = (stt.st_mtime, stt.st_size, _lcu_row_count(path))
    except OSError:
        key = (-1.0, -1, -1)
    with _lock:
        if _own_cache.get(mode) is not None and _own_cache_key.get(mode) == key:
            return _own_cache[mode]
    hist = _scan_own_history(mode, path)
    with _lock:
        _own_cache[mode] = hist
        _own_cache_key[mode] = key
    return hist


def _own_wr(hist: OwnHistory, a: int, alpha: float) -> float:
    g = hist.games.get(a, 0)
    w = hist.wins.get(a, 0)
    return _sr.laplace_rate(w, g, alpha)


def _pair_wr(hist: OwnHistory, a: int, b: int, alpha: float) -> tuple[float, int]:
    key = (a, b) if a < b else (b, a)
    m = hist.pair_games.get(key, 0)
    w = hist.pair_wins.get(key, 0)
    # Beta-smoothed pairwise == Laplace on the pair counts.
    return _sr.laplace_rate(w, m, alpha), m


def recommend(
    offered_ids: Sequence[int],
    picked_ids: Sequence[int] = (),
    *,
    mode: str = "mayhem",
    stage: Optional[int] = None,
    alpha: float = DEFAULT_ALPHA,
    k: float = DEFAULT_K,
    synergy_weight: float = DEFAULT_SYNERGY_WEIGHT,
    db_path: Optional[Path] = None,
) -> RecommendationResult:
    """Rank `offered_ids` for the operator given `picked_ids` already taken
    this game. Pure function of (cached external prior, cached own history,
    inputs). Never raises."""
    try:
        offered = [int(x) for x in offered_ids if x]
    except (TypeError, ValueError):
        offered = []
    if not offered:
        return RecommendationResult(mode=mode, ranked=[], used_external=False,
                                    n_matches=0, stage=stage)
    try:
        picked = [int(x) for x in picked_ids if x]
    except (TypeError, ValueError):
        picked = []

    if mode not in _MODE_FILTERS:
        mode = "mayhem"

    priors = _ext.get_priors(mode)
    meta = _ext.get_augment_meta()
    hist = load_own_history(mode, db_path=db_path)
    used_external = False

    scored: list[AugmentScore] = []
    for idx, a in enumerate(offered):
        n = hist.n_own(a)
        own = _own_wr(hist, a, alpha)

        ext = None
        if stage is not None:
            ext = priors.stage_win_rate(a, stage)
        if ext is None:
            ext = priors.win_rate(a)

        if ext is not None:
            used_external = True
            w = _sr.shrink(n, k)
            base = _sr.blend(own, ext, w)
            conf = w
        elif n > 0:
            w = _sr.shrink(n, k)
            base = own            # own-only (no external prior for this id)
            conf = w
        else:
            w = 0.0
            base = 0.5            # neutral - coach keeps LLM path primary
            conf = 0.0

        syn = 0.0
        if picked:
            contribs = []
            for p in picked:
                if p == a:
                    continue
                pwr, m = _pair_wr(hist, a, p, alpha)
                shrink = _sr.shrink(m, k)
                contribs.append(shrink * (pwr - own))
            if contribs:
                syn = sum(contribs) / len(contribs)

        score = base + synergy_weight * syn
        scored.append(
            AugmentScore(
                augment_id=a,
                name=meta.name(a) or str(a),
                rarity=meta.rarity(a),
                score=score,
                base=base,
                own_wr=own,
                ext_wr=ext,
                blend_w=conf,
                n_own=n,
                synergy=syn,
                # preserve input order as the stable tiebreak
            )
        )

    # Sort by score desc, stable on original offered order for ties.
    order = {a: i for i, a in enumerate(offered)}
    scored.sort(key=lambda s: (-s.score, order.get(s.augment_id, 0)))

    return RecommendationResult(
        mode=mode,
        ranked=scored,
        used_external=used_external,
        n_matches=hist.n_matches,
        stage=stage,
    )


def reset_cache() -> None:
    """Test hook - clear the own-history process cache."""
    with _lock:
        _own_cache.clear()
        _own_cache_key.clear()
