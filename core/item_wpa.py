"""Per-item Win Probability Added (WPA) over RC's own rewind corpus.

A selection-bias-corrected residual for each completed-legendary item,
computed entirely over the local ``data/rewind_history.db`` timelines.
Lifted from competitor teardown (docs/_archive/COMPETITOR_LIFT_2026-06-02.md,
finding 1): a raw item winrate conflates the item's effect with WHO buys
it and WHEN. A player far ahead buys luxury crit and then wins anyway;
the win was already coming. The competitor decomposes each item winrate into
an expected baseline (the game state at the moment of purchase) plus the
residual that the item adds on top.

    item_wpa = winrate_observed - winrate_expected

where ``winrate_expected`` is the mean win-probability of the PURCHASING
participant's team at the frame the item was bought, estimated by the
already-shipped ``core.post_game_score`` WPA logistic-regression model,
and ``winrate_observed`` is whether that team actually won. A positive
residual means the item correlates with winning beyond what the purchase
timing/lead would predict (the item is "carrying"); a negative residual
means the item is a vanity buy that the lead, not the item, explains.

HONEST FRAMING - this is a DESCRIPTIVE personal-corpus lens, NOT a global
meta winrate and NOT a redistributable stat. The corpus is ~2902 mostly
one-operator games, so per-item sample sizes are modest; the shrink toward
0 (Laplace/confidence weighting via ``core.smoothed_rates.shrink``) and
the ``min_n`` gate are LOAD-BEARING - a low-N item must NOT surface a
confident wpa. It is a selection-bias-corrected residual over the local
games, useful for spotting which of the operator's habitual buys actually
pull their weight, nothing more.

Reuse, not reinvention:
  * Frame grouping + most-recent-frame interpolation: the same
    ``MatchState`` / ``update_state_from_frame`` /
    ``_interpolate_frame_for_event`` machinery ``compute_match_wpa``
    already uses (post_game_score.py).
  * Win-probability: ``predict_prob`` returns P(team 100 wins). We flip
    to the purchasing participant's TEAM perspective
    (``1 - p`` for team 200) so observed and expected share a frame.
  * Damping: ``core.smoothed_rates.shrink(n)`` = n/(n+k) in [0, 1).

No new dependency (stdlib sqlite3 + post_game_score + smoothed_rates).
Connection-injected so a test can pass an in-memory sqlite fixture.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Sequence

from core.post_game_score import (
    MatchState,
    WpaModel,
    _interpolate_frame_for_event,
    load_model,
    predict_prob,
    update_state_from_frame,
)
from core.smoothed_rates import shrink

log = logging.getLogger("rc.item_wpa")

# Catalog used to identify completed legendaries. The DEFAULT resolves the
# patch-current snapshot via data/daemon_slayer/current.txt (the canonical
# DS patch marker) so the catalog tracks live patch bumps; _ITEMS_JSON is
# the pinned authoring-time fallback (verified at 16.11.1 to yield ~125
# SR-legal completed legendaries) used only when the marker or the
# patch-current file is absent (fresh checkout). Anchored to the repo root,
# never the CWD (RM-1022).
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DS_DIR = _DATA_DIR / "daemon_slayer"
_REWIND_DB = _DATA_DIR / "rewind_history.db"
_ITEMS_JSON = _DS_DIR / "16.11.1" / "items.json"


def _default_items_json() -> Path:
    """Patch-current items catalog path, pinned-snapshot fallback.

    Reads ``current.txt`` and prefers ``<patch>/items.json`` when that file
    exists; otherwise returns the pinned ``_ITEMS_JSON`` (the pre-fix
    behavior). Fail-soft: any IO error degrades to the pin (deep-audit P2
    W1-C - the fixed 16.11.1 pin went stale when the live patch bumped).
    """
    try:
        patch = (_DS_DIR / "current.txt").read_text(encoding="utf-8").strip()
        if patch:
            cand = _DS_DIR / patch / "items.json"
            if cand.is_file():
                return cand
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError):
        pass
    return _ITEMS_JSON

# Tags that disqualify an item from the "completed legendary" set even if
# the gold/depth heuristics otherwise pass.
_EXCLUDE_TAGS = frozenset({"Boots", "Consumable", "Trinket"})

# Minimum total gold for an item to count as a completed legendary.
# B.F. Sword (1300) and most components fall below; Infinity Edge (3500),
# Manamune (2900) etc. clear it. Chosen as a conservative floor in the
# verified 120-160 legendary-count band (probe yielded 125 at 2200).
_LEGENDARY_MIN_GOLD = 2200

# Shrink constant. ``shrink(n)`` = n/(n+k); larger k damps small samples
# harder. The smoothed_rates default (5.0) is appropriate for a personal
# corpus where most items have tens-to-low-hundreds of observations.
_SHRINK_K = 5.0

# What a malformed MATCH (bad frame / participant values) can raise inside
# the per-match sweep. Deliberately narrow: sqlite3.Error is not here (it
# must propagate - a locked DB is not a bad row), and neither is any other
# exception class (a defect must surface, not be logged once per match).
_MATCH_DATA_ERRORS = (TypeError, ValueError, ArithmeticError)


def _opt_int(value: object) -> int | None:
    """``int(value)``, or ``None`` when it is missing or not a number."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def load_legendary_ids(items_json: Path | None = None,
                       map_id: int = 11) -> dict[int, str]:
    """Return ``{item_id: name}`` for completed legendaries legal on ``map_id``.

    A completed legendary is: purchasable, builds into NOTHING (empty
    ``into`` - nothing further is built from it), is a built item (has a
    ``from`` component list or a ``depth``), is expensive
    (>= ``_LEGENDARY_MIN_GOLD`` total gold), carries no Boots/Consumable/
    Trinket tag, and is legal on ``map_id`` (``maps["<map_id>"]``). ``map_id``
    DEFAULTS to 11 (Summoner's Rift) - unchanged for every existing caller;
    the SR gate naturally excludes the Arena 22-prefixed mirror ids and the
    Golden Spatula (ARAM-only joke item). ``core.aram_item_interaction`` passes
    12 for the ARAM-legal set.

    Fail-soft: a missing, unparseable or wrong-shape catalog (a top level or
    ``data`` that is not an object) returns ``{}``; a single malformed item
    entry is skipped and the rest of the catalog is kept.
    """
    path = Path(items_json) if items_json is not None else _default_items_json()
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("load_legendary_ids: %s -> %s", path, exc)
        return {}
    data = raw.get("data", raw) if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        log.warning("load_legendary_ids: %s -> not an item object", path)
        return {}
    out: dict[int, str] = {}
    for iid_str, item in data.items():
        if not _is_completed_legendary(item, map_id):
            continue
        try:
            out[int(iid_str)] = str(item.get("name") or iid_str)
        except (TypeError, ValueError):
            continue
    return out


def _tag_set(tags: object) -> frozenset | None:
    """``tags`` as a set of names, or ``None`` when the field is malformed.

    A bare string is ONE tag, never its characters (``set("Boots")`` would
    dodge the exclusion gate). Absent / null tags are the empty set; any
    other type cannot be proven free of Boots/Consumable/Trinket.
    """
    if tags is None:
        return frozenset()
    if isinstance(tags, str):
        return frozenset((tags,))
    if isinstance(tags, (list, tuple)):
        return frozenset(t for t in tags if isinstance(t, str))
    return None


def _is_completed_legendary(item: object, map_id: int = 11) -> bool:
    """Heuristic gate for a completed legendary item dict legal on ``map_id``.

    Wrong-shape input (a non-dict entry, ``gold`` / ``maps`` not objects, a
    non-numeric ``gold.total``) is NOT a legendary - never an exception.
    """
    if not isinstance(item, dict):
        return False
    gold = item.get("gold")
    if not isinstance(gold, dict) or not gold.get("purchasable"):
        return False
    if item.get("into"):  # builds into something -> a component
        return False
    total = gold.get("total")
    if not isinstance(total, (int, float)):
        return False
    if not total >= _LEGENDARY_MIN_GOLD:  # also rejects NaN
        return False
    tags = _tag_set(item.get("tags"))
    if tags is None or tags & _EXCLUDE_TAGS:
        return False
    # Must be a built item, not a raw stat-stick / joke anvil.
    if item.get("depth") is None and not item.get("from"):
        return False
    maps = item.get("maps")
    # legal on the requested map only
    return isinstance(maps, dict) and bool(maps.get(str(map_id)))


def _load_frames(conn: sqlite3.Connection, match_id: str) -> list[tuple[int, list[tuple]]]:
    """Group ``timeline_frames`` for one match by timestamp ascending.

    Each entry is ``(timestamp_ms, [(participant_id, total_gold, xp), ...])``
    matching the shape ``update_state_from_frame`` consumes. Returns ``[]``
    when the match has no frames. A NULL timestamp reads as 0; rows are
    grouped on the NORMALISED timestamp, so NULL (or a numeric string)
    rows join their frame instead of each becoming a duplicate frame. A
    non-numeric timestamp raises ``ValueError`` (a data error the caller
    skips the match for).
    """
    cur = conn.execute(
        "SELECT timestamp_ms, participant_id, total_gold, xp "
        "FROM timeline_frames WHERE match_id=? "
        "ORDER BY timestamp_ms ASC, participant_id ASC",
        (match_id,),
    )
    frames: list[tuple[int, list[tuple]]] = []
    current_ts: int | None = None
    current_rows: list[tuple] = []
    for ts, pid, gold, xp in cur:
        ts_norm = int(ts or 0)
        if current_ts is None or ts_norm != current_ts:
            if current_ts is not None and current_rows:
                frames.append((current_ts, current_rows))
            current_ts = ts_norm
            current_rows = []
        current_rows.append((pid, gold, xp))
    if current_ts is not None and current_rows:
        frames.append((current_ts, current_rows))
    return frames


def _participant_team_win(
    conn: sqlite3.Connection, match_id: str
) -> dict[int, tuple[int, int]]:
    """Return ``{participant_id: (team_id, win)}`` for one match.

    ``team_id`` is Riot's 100/200; ``win`` is 1 if that participant's team
    won else 0. Authoritative from the ``participants`` table.
    """
    cur = conn.execute(
        "SELECT participant_id, team_id, win FROM participants WHERE match_id=?",
        (match_id,),
    )
    out: dict[int, tuple[int, int]] = {}
    for pid, team_id, win in cur:
        try:
            out[int(pid)] = (int(team_id or 0), int(win or 0))
        except (TypeError, ValueError):
            continue
    return out


def _expected_win_for_team(
    frame_rows: Sequence[tuple], game_time_s: float, team_id: int, model: WpaModel | None
) -> float | None:
    """P(team ``team_id`` wins) at this frame, via the WPA model.

    ``predict_prob`` references team 100, so for team 200 we flip the
    probability (``1 - p``). Returns ``None`` when the team is unknown.
    """
    if team_id not in (100, 200):
        return None
    state = MatchState()
    update_state_from_frame(state, list(frame_rows))
    feats = state.to_feature_vector(float(game_time_s))
    p100 = predict_prob(feats, model)
    return p100 if team_id == 100 else (1.0 - p100)


def compute_item_wpa(
    conn: sqlite3.Connection,
    *,
    min_n: int = 20,
    queue_id: int | None = None,
    patch: str | None = None,
    model: WpaModel | None = None,
    items_json: Path | None = None,
) -> dict:
    """Decompose each completed-legendary winrate into expected vs observed
    over the local rewind corpus.

    For every ITEM_PURCHASED event of any of the 10 participants in a
    qualifying match, locate the frame state at/<= the purchase timestamp,
    estimate the purchasing team's win-probability there (expected), and
    record whether that team actually won (observed). Per item:

        observed_winrate = mean(observed)
        expected_winrate = mean(expected)
        wpa              = observed_winrate - expected_winrate
        wpa_shrunk       = wpa * shrink(n)   # damp low-N toward 0

    Items with ``n < min_n`` are gated out. ``queue_id`` / ``patch``
    optionally restrict the match set.

    Returns::

        {
          "ok": True, "patch": ..., "queue_id": ..., "min_n": ...,
          "items": [ {item_id, name, n, observed_winrate, expected_winrate,
                      wpa, wpa_shrunk, avg_purchase_time_s}, ...
                     sorted by wpa_shrunk desc ],
          "elapsed_ms": ...
        }

    ``min_n`` must be an ``int >= 0`` (``bool`` refused); anything else is
    a ``ValueError`` raised before the sweep.

    Fail-soft on DATA, fail-loud on everything else:
      * a match with no frames, a purchase before any frame, and a purchase
        row with a missing / non-numeric timestamp, participant or item id
        are skipped - that row only, never the rest of its match;
      * a match whose frames are malformed (``TypeError`` / ``ValueError``
        / ``ArithmeticError``) is skipped WHOLE: its contribution is rolled
        back, so a skipped match is never half-counted;
      * ``sqlite3.Error`` (for example "database is locked") PROPAGATES - a
        partial sweep must not be served, or cached, as a complete corpus;
      * any other exception is a defect and propagates too.
    """
    if isinstance(min_n, bool) or not isinstance(min_n, int) or min_n < 0:
        raise ValueError("min_n must be an int >= 0")
    t0 = time.perf_counter()
    legendary = load_legendary_ids(items_json)

    # Select qualifying matches with timeline data.
    where = ["has_timeline=1"]
    params: list = []
    if queue_id is not None:
        where.append("queue_id=?")
        params.append(int(queue_id))
    if patch is not None:
        where.append("patch=?")
        params.append(str(patch))
    sql = "SELECT match_id FROM matches WHERE " + " AND ".join(where)
    match_ids = [r[0] for r in conn.execute(sql, params).fetchall()]

    # Accumulators per item_id.
    n_obs: dict[int, int] = {}
    sum_obs: dict[int, float] = {}
    sum_exp: dict[int, float] = {}
    sum_ts: dict[int, float] = {}

    for mid in match_ids:
        # Per-match observations, merged only when the whole match is read
        # cleanly, so a match skipped half-way contributes nothing.
        obs: list[tuple[int, float, float, float]] = []
        try:
            frames = _load_frames(conn, mid)
            if not frames:
                continue
            pt = _participant_team_win(conn, mid)
            if not pt:
                continue
            ev_cur = conn.execute(
                "SELECT timestamp_ms, participant_id, item_id "
                "FROM timeline_events WHERE match_id=? "
                "AND event_type='ITEM_PURCHASED' "
                "ORDER BY timestamp_ms ASC, id ASC",
                (mid,),
            )
            for ts_raw, pid_raw, item_raw in ev_cur:
                iid = _opt_int(item_raw)
                if iid is None or iid not in legendary:
                    continue
                pid = _opt_int(pid_raw)
                meta = pt.get(pid) if pid is not None else None
                if meta is None:
                    continue
                ts_ms = _opt_int(ts_raw)
                if ts_ms is None:  # unknown time: cannot place the purchase
                    continue
                team_id, win = meta
                rows = _interpolate_frame_for_event(frames, ts_ms)
                if rows is None:  # purchase before any frame
                    continue
                t_s = ts_ms / 1000.0
                exp = _expected_win_for_team(rows, t_s, team_id, model)
                if exp is None:
                    continue
                obs.append((iid, float(win), float(exp), t_s))
        except _MATCH_DATA_ERRORS as exc:
            log.warning("compute_item_wpa: match %s skipped -> %s: %s",
                        mid, type(exc).__name__, exc)
            continue
        for iid, win_f, exp_f, t_s in obs:
            n_obs[iid] = n_obs.get(iid, 0) + 1
            sum_obs[iid] = sum_obs.get(iid, 0.0) + win_f
            sum_exp[iid] = sum_exp.get(iid, 0.0) + exp_f
            sum_ts[iid] = sum_ts.get(iid, 0.0) + t_s

    items_out: list[dict] = []
    for iid, n in n_obs.items():
        if n < min_n:
            continue
        observed = sum_obs[iid] / n
        expected = sum_exp[iid] / n
        wpa = observed - expected
        wpa_shrunk = wpa * shrink(float(n), _SHRINK_K)
        items_out.append({
            "item_id": iid,
            "name": legendary.get(iid, str(iid)),
            "n": n,
            "observed_winrate": round(observed, 4),
            "expected_winrate": round(expected, 4),
            "wpa": round(wpa, 4),
            "wpa_shrunk": round(wpa_shrunk, 4),
            "avg_purchase_time_s": round(sum_ts[iid] / n, 1),
        })

    items_out.sort(key=lambda it: it["wpa_shrunk"], reverse=True)

    return {
        "ok": True,
        "patch": patch,
        "queue_id": queue_id,
        "min_n": min_n,
        "items": items_out,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def compute_item_wpa_from_db(
    db_path: Path | None = None,
    *,
    min_n: int = 20,
    queue_id: int | None = None,
    patch: str | None = None,
    model_path: Path | None = None,
) -> dict:
    """Convenience wrapper: open ``rewind_history.db`` read-only, load the
    persisted WPA model (or fall back), compute, close.

    Returns ``{"ok": False, "error": "rewind_history.db missing"}`` when
    the DB is absent (or the path is not a regular file). ``sqlite3.Error``
    from the sweep propagates (see ``compute_item_wpa``).

    The read-only URI goes through ``Path.as_uri``, which percent-encodes
    the path: an f-string ``file:{path}?mode=ro`` let a '#', '%' or '?' in
    the checkout path truncate the URI or open a different file.
    """
    src = Path(db_path) if db_path is not None else _REWIND_DB
    if not src.is_file():
        return {"ok": False, "error": "rewind_history.db missing"}
    model = load_model(model_path)
    uri = src.absolute().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        return compute_item_wpa(
            conn, min_n=min_n, queue_id=queue_id, patch=patch, model=model
        )
    finally:
        conn.close()
