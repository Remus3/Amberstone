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
    * ``core.item_wpa._load_frames`` - per-match frame grouping. The
      participant -> team / win / champion roster is read here, strictly
      (a NULL or out-of-range win is unknown, never a loss).
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
is gitignored so the suite stays clean-checkout safe).

FAIL-SOFT ON DATA, FAIL-LOUD ON EVERYTHING ELSE (s144 true-audit cycle 96)
    The only producer, ``tools/aram_item_interaction_precompute.py``, writes
    the result over the TRACKED snapshot the live coach reads, so a partial or
    garbage result must never come back as ``ok=True``:
      * a malformed purchase row is skipped (that row only); a match whose
        frames or roster are malformed is skipped WHOLE and rolled back;
      * ``sqlite3.Error`` (for example "database is locked") PROPAGATES, and
        so does any exception that is not a data error;
      * an empty champion or item catalog is ``{"ok": False, "error": ...}``
        - an empty catalog would bucket every purchase as one fabricated
        shape, or drop every purchase.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional, Sequence

from core.aram_comp_verdict import compute_factors
from core.failed_load_gate import FailedLoadGate
from core.item_wpa import _load_frames, load_legendary_ids
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

# What a malformed MATCH (bad frame / roster values) can raise inside the
# per-match sweep. Deliberately narrow: sqlite3.Error is not here (a locked DB
# is not a bad row) and neither is any other class (a defect must surface).
_MATCH_DATA_ERRORS = (TypeError, ValueError, ArithmeticError)

# Champion-name memo. Published only after a SUCCESSFUL load, under the lock,
# so a concurrent caller never sees a half-filled catalog, and a failed load
# is never cached (RM-439): it is retried after the gate's backoff.
_CHAMP_NAMES: Optional[dict[int, str]] = None
_CHAMP_NAMES_LOCK = threading.Lock()
_CHAMP_NAMES_GATE = FailedLoadGate()


def _strict_int(value: object) -> Optional[int]:
    """``value`` as an int, or ``None`` when it is not exactly an integer.

    Accepts an int, an integral finite float and a numeric string; refuses
    ``bool`` (``True`` would read as id 1), a fractional float (never
    truncated onto a real id), bytes and anything else.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _resolve_patch() -> Optional[str]:
    try:
        return _DS_DIR.joinpath("current.txt").read_text(encoding="utf-8").strip() or None
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError):
        return None


def _load_champion_names() -> tuple[Optional[dict[int, str]], str]:
    """Read the catalog: ``(names, "")`` or ``(None, why)`` on any failure.

    A catalog with no usable entry is a failure too - no real champion
    catalog is empty.
    """
    patch = _resolve_patch()
    if not patch:
        return None, "no current patch"
    path = _DS_DIR / patch / "champions.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path.name}: {type(exc).__name__}: {exc}"
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return None, f"{path.name}: no champion object"
    names: dict[int, str] = {}
    for champ in data.values():
        if not isinstance(champ, dict):
            continue
        cid = _strict_int(champ.get("key"))
        name = champ.get("name")
        if cid is None or not isinstance(name, str) or not name.strip():
            continue
        names[cid] = name
    if not names:
        return None, f"{path.name}: no usable champion entry"
    return names, ""


def champion_names_by_id() -> dict[int, str]:
    """``{riot_champion_id: display_name}`` from the patch-current catalog.

    Resolves by the numeric ``key`` field, NOT by champion_name string, because
    the stored ``participants.champion_name`` is the DDragon id ("MonkeyKing")
    while the comp-fact extractor keys on the display name ("Wukong").

    Memoised after a SUCCESSFUL load only. A missing, unparseable, wrong-shape
    or empty catalog returns ``{}`` WITHOUT caching it; the load is retried
    after the ``FailedLoadGate`` backoff and warns once per failure streak.
    An entry with a bool / fractional / non-numeric ``key`` or an empty name
    is skipped. The returned dict is shared: callers must not mutate it.
    """
    global _CHAMP_NAMES
    cached = _CHAMP_NAMES
    if cached is not None:
        return cached
    with _CHAMP_NAMES_LOCK:
        if _CHAMP_NAMES is not None:
            return _CHAMP_NAMES
        if not _CHAMP_NAMES_GATE.should_attempt():
            return {}
        names, why = _load_champion_names()
        if names is None:
            if _CHAMP_NAMES_GATE.record_failure():
                log.warning("champion_names_by_id: catalog unavailable (%s)"
                            " - will retry", why)
            return {}
        _CHAMP_NAMES_GATE.record_success()
        _CHAMP_NAMES = names
        return names


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


def _team_names(champion_ids: Sequence[object]) -> list[str]:
    """Display names for the ids the catalog knows (others skipped)."""
    names = champion_names_by_id()
    out: list[str] = []
    for raw in champion_ids or ():
        cid = _strict_int(raw)
        if cid is not None and cid in names:
            out.append(names[cid])
    return out


def comp_shape(champion_ids: Sequence[int]) -> str:
    """Comp shape for a team given Riot champion ids.

    Unknown or unparseable ids (``None``, a bool, a fractional float, a
    non-numeric string) are skipped, never raised on.
    """
    return shape_from_factors(compute_factors(_team_names(champion_ids)))


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
    so a truncated window never masquerades as a full-window reading. ``None``
    too when a gold value is non-finite, so inf / NaN never reach the payload.
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
    swing = own_delta - enemy_delta
    return swing if math.isfinite(swing) else None


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


def _read_roster(conn: sqlite3.Connection, mid: str
                 ) -> tuple[dict[int, set[int]], dict[int, int], dict[int, int]]:
    """``(teams, champ_of, win_of)`` for one match, read strictly.

    A row whose participant id is not an integer, or whose team is not 100 /
    200, is skipped. A NULL / non-integer champion id is absent from
    ``champ_of``; a win other than 0 / 1 is absent from ``win_of`` (unknown,
    never a loss). A participant id listed twice raises ``ValueError``: the
    roster is ambiguous, so the caller skips the whole match.
    """
    teams: dict[int, set[int]] = {}
    champ_of: dict[int, int] = {}
    win_of: dict[int, int] = {}
    seen: set[int] = set()
    rows = conn.execute(
        "SELECT participant_id, team_id, champion_id, win FROM participants "
        "WHERE match_id=?",
        (mid,),
    ).fetchall()
    for pid_raw, team_raw, cid_raw, win_raw in rows:
        pid = _strict_int(pid_raw)
        team = _strict_int(team_raw)
        if pid is None or team not in (100, 200):
            continue
        if pid in seen:
            raise ValueError(f"participant {pid} listed twice")
        seen.add(pid)
        teams.setdefault(team, set()).add(pid)
        cid = _strict_int(cid_raw)
        if cid is not None:
            champ_of[pid] = cid
        win = _strict_int(win_raw)
        if win in (0, 1):
            win_of[pid] = win
    return teams, champ_of, win_of


def _match_observations(
    conn: sqlite3.Connection,
    mid: str,
    *,
    legendary: dict[int, str],
    champion_id: Optional[int],
    model: WpaModel | None,
    timing_buckets,
    pressure_window_s: int,
) -> list[tuple[tuple[str, int, str], float, float, float, Optional[float]]]:
    """Every counted purchase of one match as ``(cell_key, win, expected,
    purchase_time_s, gold_swing)``. Raises a ``_MATCH_DATA_ERRORS`` class on
    malformed frames / roster; the caller then drops the whole match."""
    frames = _load_frames(conn, mid)
    if not frames:
        return []
    teams, champ_of, win_of = _read_roster(conn, mid)
    if len(teams) != 2:
        return []
    # Enemy comp shape is a per-TEAM fact: for a member of team T the enemy
    # comp is the other team's champion list. None when no enemy champion
    # resolves - an invented "mixed/fl_none" bucket is not a shape.
    shape_for_team: dict[int, Optional[str]] = {}
    for t in teams:
        enemy_ids = [champ_of[p] for tt, pids in teams.items() if tt != t
                     for p in sorted(pids) if p in champ_of]
        names = _team_names(enemy_ids)
        shape_for_team[t] = (shape_from_factors(compute_factors(names))
                             if names else None)
    team_of = {p: t for t, pids in teams.items() for p in pids}
    events = conn.execute(
        "SELECT timestamp_ms, participant_id, item_id FROM timeline_events "
        "WHERE match_id=? AND event_type='ITEM_PURCHASED' "
        "ORDER BY timestamp_ms ASC, id ASC",
        (mid,),
    ).fetchall()
    obs: list = []
    for ts_raw, pid_raw, item_raw in events:
        iid = _strict_int(item_raw)
        if iid is None or iid not in legendary:
            continue
        pid = _strict_int(pid_raw)
        team_id = team_of.get(pid) if pid is not None else None
        win = win_of.get(pid) if pid is not None else None
        if team_id is None or win is None:
            continue
        if champion_id is not None and champ_of.get(pid) != champion_id:
            continue
        shape = shape_for_team.get(team_id)
        if shape is None:
            continue
        ts_ms = _strict_int(ts_raw)
        if ts_ms is None:  # unknown time: cannot place the purchase
            continue
        t_s = ts_ms / 1000.0
        bucket = _timing_bucket(t_s, timing_buckets)
        if bucket is None:
            continue
        rows = _interpolate_frame_for_event(frames, ts_ms)
        if rows is None:  # purchase before any frame
            continue
        expected = _expected_win_for_team(rows, t_s, team_id, model)
        if expected is None or not math.isfinite(expected):
            continue
        enemy = set().union(*(p for t, p in teams.items() if t != team_id))
        swing = _gold_swing(frames, ts_ms, teams[team_id], enemy,
                            pressure_window_s)
        obs.append(((shape, iid, bucket), float(win), float(expected), t_s,
                    swing))
    return obs


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

    Arguments are validated before the sweep (``ValueError``): ``min_n`` an
    ``int >= 0``, ``champion_id`` ``None`` or an ``int > 0``,
    ``pressure_window_s`` an ``int > 0`` (``bool`` refused for all three).

    Fail-soft on DATA, fail-loud on everything else:
      * a purchase row with a missing / non-integer time, participant or item
        id, a participant whose win is not 0 / 1, and a purchaser whose enemy
        team has no champion the catalog knows (its shape would be invented)
        are skipped - that row only;
      * a match with malformed frames or roster (a participant listed twice)
        is skipped WHOLE and rolled back - never half-counted;
      * ``sqlite3.Error`` and any non-data exception PROPAGATE;
      * an empty champion or item catalog returns
        ``{"ok": False, "error": ...}`` before the sweep.
    """
    if isinstance(min_n, bool) or not isinstance(min_n, int) or min_n < 0:
        raise ValueError("min_n must be an int >= 0")
    if champion_id is not None and (
            isinstance(champion_id, bool) or not isinstance(champion_id, int)
            or champion_id <= 0):
        raise ValueError("champion_id must be None or an int > 0")
    if (isinstance(pressure_window_s, bool)
            or not isinstance(pressure_window_s, int) or pressure_window_s <= 0):
        raise ValueError("pressure_window_s must be an int > 0")
    t0 = time.perf_counter()
    legendary = load_legendary_ids(items_json, map_id=ARAM_MAP_ID)
    if not legendary:
        return {"ok": False, "error": "item catalog unavailable"}
    if not champion_names_by_id():
        return {"ok": False, "error": "champion catalog unavailable"}

    where = ["has_timeline=1", "map_id=?"]
    params: list = [ARAM_MAP_ID]
    if patch is not None:
        where.append("patch=?")
        params.append(str(patch))
    sql = "SELECT match_id FROM matches WHERE " + " AND ".join(where)
    # sqlite3.Error propagates: an empty corpus from a locked DB must not be
    # written over the snapshot as if it were real.
    match_ids = [r[0] for r in conn.execute(sql, params).fetchall()]

    cells: dict[tuple[str, int, str], _Cell] = {}
    matches_used = 0

    for mid in match_ids:
        try:
            obs = _match_observations(
                conn, mid, legendary=legendary, champion_id=champion_id,
                model=model, timing_buckets=timing_buckets,
                pressure_window_s=pressure_window_s,
            )
        except _MATCH_DATA_ERRORS as exc:
            log.warning("compute_aram_item_interaction: match %s skipped -> %s: %s",
                        mid, type(exc).__name__, exc)
            continue
        # Merged only after the whole match read cleanly (rollback by design).
        for key, win, expected, t_s, swing in obs:
            cell = cells.setdefault(key, _Cell())
            cell.n += 1
            cell.wins += win
            cell.sum_expected += expected
            cell.sum_ts += t_s
            if swing is not None:
                cell.sum_swing += swing
                cell.n_swing += 1
        if obs:
            matches_used += 1

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
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
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

    ``{"ok": False, "error": "rewind_history.db missing"}`` when absent (or
    the path is not a regular file). ``sqlite3.Error`` and a ``ValueError``
    for a bad argument propagate (see ``compute_aram_item_interaction``).

    The read-only URI goes through ``Path.as_uri``, which percent-encodes the
    path: an f-string ``file:{path}?mode=ro`` let a '#' or '%' in the checkout
    path truncate the URI or open a different file.
    """
    src = Path(db_path) if db_path is not None else (
        _PROJECT_ROOT / "data" / "rewind_history.db")
    if not src.is_file():
        return {"ok": False, "error": "rewind_history.db missing"}
    model = load_model(model_path)
    uri = src.absolute().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        return compute_aram_item_interaction(
            conn, min_n=min_n, champion_id=champion_id, patch=patch, model=model
        )
    finally:
        conn.close()
