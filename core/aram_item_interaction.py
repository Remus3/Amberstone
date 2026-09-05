"""ARAM comp-conditioned item-interaction aggregation (RM-111).

WHAT
    For the local ARAM corpus in ``data/rewind_history.db``, mine
    ``(enemy-comp-shape x item x purchase-timing) -> outcome`` so a live coach
    can answer "when did buying this actually pay off AGAINST THIS SHAPE of
    enemy comp, in my own games" - a timing / pressure cue rather than a static
    build list.

    ARAM is the right first mode: there is no lane phase, the 5v5 comp is known
    at load-in, and item timings map directly onto the constant-teamfight
    pressure curve.

HARD FIREWALL
    DESCRIPTIVE / EMPIRICAL ONLY. This surface must NEVER feed back into
    ``agents/daemon_slayer`` rank - same firewall as the F3 snowball-elasticity
    item. DS answers "what is optimal in simulation"; this answers "what
    happened in my own games". Mixing them would launder a personal-corpus
    correlation into the engine's optimality math.

REUSE, NOT REINVENTION
    * ``core.item_wpa.load_legendary_ids`` - the completed-legendary catalog
      gate (called with ``map_id=12`` for the ARAM-legal set).
    * ``core.item_wpa._load_frames`` / ``_participant_team_win`` - per-match
      frame grouping + participant->team/win resolution.
    * ``core.post_game_score._interpolate_frame_for_event`` / ``predict_prob``
      - the shipped WPA logistic model, used here for the same selection-bias
      correction ``item_wpa`` applies (a player far ahead buys luxury items and
      wins anyway; the win was already coming).
    * ``core.aram_comp_verdict.compute_factors`` - the SHIPPED comp-balance
      fact extractor (ad/ap lean counts + frontline count off champions.json).
    * ``core.smoothed_rates`` - Laplace shrink toward 0.5 + the n/(n+k)
      confidence weight.

CELL GRANULARITY (the load-bearing scope cut)
    A literal 5-champion enemy tuple is NOT a bucket - it is an id. Comp shape
    is therefore a COARSE 9-way bucket: enemy damage axis (ad_heavy / mixed /
    ap_heavy) x enemy frontline count (none / light / heavy). Even so, a
    (champion x shape x item x timing) cell thins out fast over ~2073 ARAM
    matches, so the DEFAULT aggregation drops the champion axis entirely and
    ``champion_id`` is an opt-in filter. ``MIN_BUCKET_N`` is a HARD gate - a
    cell below it is dropped, never surfaced with a shy number.

PRESSURE METRIC
    Team gold swing over ``PRESSURE_WINDOW_S`` after the purchase: the
    purchasing team's summed ``total_gold`` delta minus the enemy team's, from
    ``timeline_frames``. Positive = the team gained tempo in the window after
    the buy. An observation whose window is not FULLY covered by frames (the
    game ended first) records ``None`` pressure rather than a truncated one.
    Per-frame champion HP is not stored, so an HP-swing variant is not
    available on this schema.

Read-only, connection-injected (tests pass an in-memory sqlite fixture; the db
is gitignored so the suite stays clean-checkout safe). Never raises - one bad
match is logged and skipped.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional, Sequence

from core.aram_comp_verdict import compute_factors
from core.item_wpa import _load_frames, _participant_team_win, load_legendary_ids
from core.post_game_score import (
    MatchState,
    WpaModel,
    _interpolate_frame_for_event,
    load_model,
    predict_prob,
    update_state_from_frame,
)
from core.smoothed_rates import DEFAULT_ALPHA, DEFAULT_K, laplace_rate, shrink

log = logging.getLogger("rc.aram_item_interaction")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DS_DIR = _PROJECT_ROOT / "data" / "daemon_slayer"

ARAM_MAP_ID = 12
ARAM_QUEUE_ID = 450

# Hard sample-size gate. A cell below this is DROPPED from the payload - not
# emitted with a low-confidence flag, because a coach cue the operator reads
# mid-fight has no room for a caveat.
MIN_BUCKET_N = 15

# Gold-swing measurement window after the purchase.
PRESSURE_WINDOW_S = 120

# Purchase-timing buckets, seconds from game start. ARAM games are short
# (~15-25m) and gold is continuous, so three coarse bands: the first-item
# window, the two-to-three-item spike window, and everything after.
DEFAULT_TIMING_BUCKETS = (
    ("early", 0, 480),
    ("mid", 480, 900),
    ("late", 900, None),
)

# Enemy damage-axis bucket: this many of the 5 enemies leaning one type reads
# as mono-typed for itemisation purposes (armor vs MR stacking).
_DMG_HEAVY_MIN = 4
# Enemy frontline-count bucket boundaries.
_FRONTLINE_LIGHT_MAX = 2  # 1..2 = light; 0 = none; 3+ = heavy

_champ_names_by_id: dict[int, str] = {}
_champ_names_loaded = False


def _resolve_patch() -> Optional[str]:
    try:
        return _DS_DIR.joinpath("current.txt").read_text(encoding="utf-8").strip() or None
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError):
        return None


def champion_names_by_id() -> dict[int, str]:
    """``{riot_champion_id: display_name}`` from the patch-current catalog.

    Resolves by the numeric ``key`` field, NOT by champion_name string, because
    the stored ``participants.champion_name`` is the DDragon id ("MonkeyKing")
    while the comp-fact extractor keys on the display name ("Wukong"). Memoised;
    ``{}`` fail-soft on a missing / unparseable catalog.
    """
    global _champ_names_loaded
    if _champ_names_loaded:
        return _champ_names_by_id
    _champ_names_loaded = True
    patch = _resolve_patch()
    if not patch:
        return _champ_names_by_id
    try:
        data = json.loads(
            (_DS_DIR / patch / "champions.json").read_text(encoding="utf-8")
        ).get("data") or {}
    except (OSError, ValueError) as exc:
        log.warning("champion_names_by_id: %s", exc)
        return _champ_names_by_id
    for champ in data.values():
        if not isinstance(champ, dict):
            continue
        try:
            _champ_names_by_id[int(champ.get("key"))] = str(champ.get("name") or "")
        except (TypeError, ValueError):
            continue
    return _champ_names_by_id


def shape_from_factors(factors: dict) -> str:
    """Coarse 9-way comp-shape label from a ``compute_factors`` dict.

    ``"<ad_heavy|mixed|ap_heavy>/<fl_none|fl_light|fl_heavy>"``. Pure function
    over the factor counts, so it is testable without any champion catalog.
    """
    ad = int(factors.get("ad_count") or 0)
    ap = int(factors.get("ap_count") or 0)
    fl = int(factors.get("frontline_count") or 0)
    if ad >= _DMG_HEAVY_MIN:
        dmg = "ad_heavy"
    elif ap >= _DMG_HEAVY_MIN:
        dmg = "ap_heavy"
    else:
        dmg = "mixed"
    if fl <= 0:
        front = "fl_none"
    elif fl <= _FRONTLINE_LIGHT_MAX:
        front = "fl_light"
    else:
        front = "fl_heavy"
    return f"{dmg}/{front}"


def comp_shape(champion_ids: Sequence[int]) -> str:
    """Comp shape for a team given Riot champion ids (unknown ids skipped)."""
    names = champion_names_by_id()
    team = [names[int(cid)] for cid in (champion_ids or []) if int(cid) in names]
    return shape_from_factors(compute_factors(team))


def _timing_bucket(ts_s: float, buckets) -> Optional[str]:
    for label, lo, hi in buckets:
        if ts_s >= lo and (hi is None or ts_s < hi):
            return label
    return None


def _team_gold(frame_rows: Sequence[tuple], pids: set[int]) -> float:
    """Summed ``total_gold`` over the given participant ids in one frame.

    ``_load_frames`` rows are ``(participant_id, total_gold, xp)``.
    """
    total = 0.0
    for row in frame_rows:
        try:
            if int(row[0]) in pids:
                total += float(row[1] or 0)
        except (TypeError, ValueError, IndexError):
            continue
    return total


def _last_frame_ts(frames) -> int:
    return int(frames[-1][0]) if frames else 0


def _gold_swing(frames, ts_ms: int, own: set[int], enemy: set[int],
                window_s: int) -> Optional[float]:
    """Own-minus-enemy team gold delta across the window after ``ts_ms``.

    ``None`` when the window is not fully covered by frames (game ended first)
    so a truncated window never masquerades as a full-window reading.
    """
    end_ms = int(ts_ms) + window_s * 1000
    if _last_frame_ts(frames) < end_ms:
        return None
    start_rows = _interpolate_frame_for_event(frames, int(ts_ms))
    end_rows = _interpolate_frame_for_event(frames, end_ms)
    if start_rows is None or end_rows is None:
        return None
    own_delta = _team_gold(end_rows, own) - _team_gold(start_rows, own)
    enemy_delta = _team_gold(end_rows, enemy) - _team_gold(start_rows, enemy)
    return own_delta - enemy_delta


def _expected_win_for_team(frame_rows: Sequence[tuple], game_time_s: float,
                           team_id: int, model: WpaModel | None) -> Optional[float]:
    """P(``team_id`` wins) at this frame - ``predict_prob`` flipped for team 200."""
    if team_id not in (100, 200):
        return None
    state = MatchState()
    update_state_from_frame(state, list(frame_rows))
    p100 = predict_prob(state.to_feature_vector(float(game_time_s)), model)
    return p100 if team_id == 100 else (1.0 - p100)


class _Cell:
    """Accumulator for one (shape, item, timing) cell."""

    __slots__ = ("n", "wins", "sum_expected", "sum_swing", "n_swing", "sum_ts")

    def __init__(self) -> None:
        self.n = 0
        self.wins = 0.0
        self.sum_expected = 0.0
        self.sum_swing = 0.0
        self.n_swing = 0
        self.sum_ts = 0.0


def compute_aram_item_interaction(
    conn: sqlite3.Connection,
    *,
    min_n: int = MIN_BUCKET_N,
    champion_id: Optional[int] = None,
    patch: Optional[str] = None,
    model: WpaModel | None = None,
    items_json: Path | None = None,
    timing_buckets=DEFAULT_TIMING_BUCKETS,
    pressure_window_s: int = PRESSURE_WINDOW_S,
    alpha: float = DEFAULT_ALPHA,
    shrink_k: float = DEFAULT_K,
) -> dict:
    """Aggregate ``(enemy comp shape x item x purchase timing) -> outcome``.

    Every ITEM_PURCHASED of a completed ARAM-legal legendary, by any of the 10
    participants of a map-12 match carrying timelines, contributes one
    observation to the cell keyed by the PURCHASER's enemy-team comp shape, the
    item, and the timing bucket of the purchase. Per cell::

        winrate          = wins / n                       (raw)
        winrate_smoothed = laplace_rate(wins, n, alpha)    (shrunk toward 0.5)
        wpa              = winrate - mean(expected)        (bias-corrected)
        wpa_shrunk       = wpa * shrink(n, k)
        gold_swing       = mean own-minus-enemy gold delta in the window

    ``champion_id`` optionally restricts observations to purchases made by that
    champion (the axis is OFF by default - see the module docstring's cell
    granularity note). Cells with ``n < min_n`` are DROPPED.

    Never raises: one unreadable match is logged and skipped.
    """
    t0 = time.time()
    legendary = load_legendary_ids(items_json, map_id=ARAM_MAP_ID)

    where = ["has_timeline=1", "map_id=?"]
    params: list = [ARAM_MAP_ID]
    if patch is not None:
        where.append("patch=?")
        params.append(str(patch))
    sql = "SELECT match_id FROM matches WHERE " + " AND ".join(where)
    try:
        match_ids = [r[0] for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error as exc:
        log.warning("compute_aram_item_interaction: match select -> %s", exc)
        match_ids = []

    cells: dict[tuple[str, int, str], _Cell] = {}
    matches_used = 0

    for mid in match_ids:
        try:
            frames = _load_frames(conn, mid)
            if not frames:
                continue
            roster = conn.execute(
                "SELECT participant_id, team_id, champion_id FROM participants "
                "WHERE match_id=?",
                (mid,),
            ).fetchall()
            teams: dict[int, set[int]] = {}
            champ_of: dict[int, int] = {}
            for pid, team_id, cid in roster:
                if pid is None or team_id is None:
                    continue
                teams.setdefault(int(team_id), set()).add(int(pid))
                if cid is not None:
                    champ_of[int(pid)] = int(cid)
            if len(teams) != 2:
                continue
            pt = _participant_team_win(conn, mid)
            if not pt:
                continue
            # Enemy comp shape is a per-TEAM fact: for a member of team T the
            # enemy comp is the other team's champion list.
            shape_for_team: dict[int, str] = {}
            for t in teams:
                enemy_pids = [p for tt, pids in teams.items() if tt != t
                              for p in pids]
                shape_for_team[t] = comp_shape(
                    [champ_of[p] for p in sorted(enemy_pids) if p in champ_of]
                )
            events = conn.execute(
                "SELECT timestamp_ms, participant_id, item_id FROM timeline_events "
                "WHERE match_id=? AND event_type='ITEM_PURCHASED' "
                "ORDER BY timestamp_ms ASC, id ASC",
                (mid,),
            ).fetchall()
            used = False
            for ts_ms, pid, item_id in events:
                if item_id is None or pid is None:
                    continue
                iid = int(item_id)
                if iid not in legendary:
                    continue
                pid = int(pid)
                if champion_id is not None and champ_of.get(pid) != int(champion_id):
                    continue
                meta = pt.get(pid)
                if meta is None:
                    continue
                team_id, win = meta
                ts_ms = int(ts_ms or 0)
                bucket = _timing_bucket(ts_ms / 1000.0, timing_buckets)
                if bucket is None:
                    continue
                rows = _interpolate_frame_for_event(frames, ts_ms)
                if rows is None:  # purchase before any frame
                    continue
                expected = _expected_win_for_team(rows, ts_ms / 1000.0, team_id, model)
                if expected is None:
                    continue
                own = teams.get(team_id) or set()
                enemy = set().union(*(p for t, p in teams.items() if t != team_id))
                swing = _gold_swing(frames, ts_ms, own, enemy, pressure_window_s)

                cell = cells.setdefault(
                    (shape_for_team.get(team_id, "mixed/fl_light"), iid, bucket),
                    _Cell(),
                )
                cell.n += 1
                cell.wins += float(win)
                cell.sum_expected += expected
                cell.sum_ts += ts_ms / 1000.0
                if swing is not None:
                    cell.sum_swing += swing
                    cell.n_swing += 1
                used = True
            if used:
                matches_used += 1
        except Exception as exc:  # noqa: BLE001 - one bad match cannot abort
            log.warning("compute_aram_item_interaction: match %s -> %s", mid, exc)
            continue

    out: list[dict] = []
    dropped = 0
    for (shape, iid, bucket), cell in cells.items():
        if cell.n < min_n:
            dropped += 1
            continue
        winrate = cell.wins / cell.n
        expected = cell.sum_expected / cell.n
        wpa = winrate - expected
        out.append({
            "shape": shape,
            "item_id": iid,
            "name": legendary.get(iid, str(iid)),
            "timing": bucket,
            "n": cell.n,
            "winrate": round(winrate, 4),
            "winrate_smoothed": round(laplace_rate(cell.wins, cell.n, alpha), 4),
            "expected_winrate": round(expected, 4),
            "wpa": round(wpa, 4),
            "wpa_shrunk": round(wpa * shrink(float(cell.n), shrink_k), 4),
            "gold_swing": (round(cell.sum_swing / cell.n_swing, 1)
                           if cell.n_swing else None),
            "n_gold_swing": cell.n_swing,
            "avg_purchase_time_s": round(cell.sum_ts / cell.n, 1),
        })

    out.sort(key=lambda c: (-c["wpa_shrunk"], c["shape"], c["item_id"], c["timing"]))

    return {
        "ok": True,
        "map_id": ARAM_MAP_ID,
        "patch": patch,
        "champion_id": champion_id,
        "min_n": min_n,
        "pressure_window_s": pressure_window_s,
        "matches": matches_used,
        "cells": out,
        "cells_dropped_below_min_n": dropped,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def compute_aram_item_interaction_from_db(
    db_path: Path | None = None,
    *,
    min_n: int = MIN_BUCKET_N,
    champion_id: Optional[int] = None,
    patch: Optional[str] = None,
    model_path: Path | None = None,
) -> dict:
    """Open ``rewind_history.db`` read-only, aggregate, close.

    ``{"ok": False, "error": "rewind_history.db missing"}`` when absent.
    """
    src = Path(db_path) if db_path is not None else (
        _PROJECT_ROOT / "data" / "rewind_history.db")
    if not Path(src).exists():
        return {"ok": False, "error": "rewind_history.db missing"}
    model = load_model(model_path)
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)
    try:
        return compute_aram_item_interaction(
            conn, min_n=min_n, champion_id=champion_id, patch=patch, model=model
        )
    finally:
        conn.close()
