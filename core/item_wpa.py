"""Per-item Win Probability Added (WPA) over RC's own rewind corpus.

A selection-bias-corrected residual for each completed-legendary item,
computed entirely over the local ``data/rewind_history.db`` timelines.
Lifted from the coachless.gg teardown (docs/COMPETITOR_LIFT_2026-06-02.md,
finding 1): a raw item winrate conflates the item's effect with WHO buys
it and WHEN. A player far ahead buys luxury crit and then wins anyway;
the win was already coming. coachless decomposes each item winrate into
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

# Default catalog used to identify completed legendaries. Verified at
# patch 16.11.1 to yield ~125 SR-legal completed legendaries.
_ITEMS_JSON = Path("data") / "daemon_slayer" / "16.11.1" / "items.json"

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


def load_legendary_ids(items_json: Path | None = None) -> dict[int, str]:
    """Return ``{item_id: name}`` for completed, SR-legal legendaries.

    A completed legendary is: purchasable, builds into NOTHING (empty
    ``into`` - nothing further is built from it), is a built item (has a
    ``from`` component list or a ``depth``), is expensive
    (>= ``_LEGENDARY_MIN_GOLD`` total gold), carries no Boots/Consumable/
    Trinket tag, and is legal on Summoner's Rift (``maps["11"]``). The SR
    gate naturally excludes the Arena 22-prefixed mirror ids and the
    Golden Spatula (ARAM-only joke item).

    Fail-soft: a missing or unparseable catalog returns ``{}``.
    """
    path = Path(items_json) if items_json is not None else _ITEMS_JSON
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("load_legendary_ids: %s -> %s", path, exc)
        return {}
    data = raw.get("data", raw)
    out: dict[int, str] = {}
    for iid_str, item in data.items():
        if not _is_completed_legendary(item):
            continue
        try:
            out[int(iid_str)] = str(item.get("name") or iid_str)
        except (TypeError, ValueError):
            continue
    return out


def _is_completed_legendary(item: dict) -> bool:
    """Heuristic gate for a completed, SR-legal legendary item dict."""
    gold = item.get("gold") or {}
    if not gold.get("purchasable"):
        return False
    if item.get("into"):  # builds into something -> a component
        return False
    if (gold.get("total") or 0) < _LEGENDARY_MIN_GOLD:
        return False
    tags = set(item.get("tags") or ())
    if tags & _EXCLUDE_TAGS:
        return False
    # Must be a built item, not a raw stat-stick / joke anvil.
    if item.get("depth") is None and not item.get("from"):
        return False
    maps = item.get("maps") or {}
    if not maps.get("11"):  # SR-legal only
        return False
    return True


def _load_frames(conn: sqlite3.Connection, match_id: str) -> list[tuple[int, list[tuple]]]:
    """Group ``timeline_frames`` for one match by timestamp ascending.

    Each entry is ``(timestamp_ms, [(participant_id, total_gold, xp), ...])``
    matching the shape ``update_state_from_frame`` consumes. Returns ``[]``
    when the match has no frames.
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
        if current_ts is None or ts != current_ts:
            if current_ts is not None and current_rows:
                frames.append((current_ts, current_rows))
            current_ts = int(ts or 0)
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

    Fail-soft: a match with no frames, or a purchase before any frame, is
    skipped (never crashes); each match is wrapped so one bad row cannot
    abort the whole sweep.
    """
    t0 = time.time()
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
            for ts_ms, pid, item_id in ev_cur:
                if item_id is None or int(item_id) not in legendary:
                    continue
                meta = pt.get(int(pid)) if pid is not None else None
                if meta is None:
                    continue
                team_id, win = meta
                rows = _interpolate_frame_for_event(frames, int(ts_ms or 0))
                if rows is None:  # purchase before any frame
                    continue
                exp = _expected_win_for_team(
                    rows, float(ts_ms or 0) / 1000.0, team_id, model
                )
                if exp is None:
                    continue
                iid = int(item_id)
                n_obs[iid] = n_obs.get(iid, 0) + 1
                sum_obs[iid] = sum_obs.get(iid, 0.0) + float(win)
                sum_exp[iid] = sum_exp.get(iid, 0.0) + exp
                sum_ts[iid] = sum_ts.get(iid, 0.0) + float(ts_ms or 0) / 1000.0
        except Exception as exc:  # noqa: BLE001 - one bad match cannot abort
            log.warning("compute_item_wpa: match %s -> %s", mid, exc)
            continue

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
        "elapsed_ms": int((time.time() - t0) * 1000),
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
    the DB is absent.
    """
    src = Path(db_path) if db_path is not None else (Path("data") / "rewind_history.db")
    if not src.exists():
        return {"ok": False, "error": "rewind_history.db missing"}
    model = load_model(model_path)
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)
    try:
        return compute_item_wpa(
            conn, min_n=min_n, queue_id=queue_id, patch=patch, model=model
        )
    finally:
        conn.close()
