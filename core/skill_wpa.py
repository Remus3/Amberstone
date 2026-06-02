"""Per-(champion, first-maxed basic) skill-order WPA over RC's rewind corpus.

The skill-order analog of ``core.item_wpa``. The decision-bearing skill
choice is the MAX ORDER - which basic ability (Q / W / E) a player levels
to rank 5 first (max-Q-Ahri vs max-W-Ahri). The unit is therefore
``(champion_id, first_maxed_basic_slot)``, NOT a per-skill-point row
(every champion levels all three basics, so per-point is degenerate).

Lifted from the competitor teardown (docs/COMPETITOR_LIFT_2026-06-02.md):
the competitor applies its WPA decomposition to Skills as well as Items. A
raw "max-Q winrate" conflates the skill choice with WHO maxes Q and the
state when the max locks in. We decompose it into an expected baseline
(the WPA model's win-probability at the frame the basic hit rank 5) plus
the selection-bias-corrected residual:

    skill_wpa = winrate_observed - winrate_expected

where ``winrate_expected`` is the mean ``core.post_game_score`` win-prob of
the maxing participant's TEAM at the frame the chosen basic reached rank 5,
and ``winrate_observed`` is whether that team won. A positive residual
means that max-order correlates with winning beyond the lead it was
chosen under; a negative residual means the lead, not the skill order,
explains the win.

HONEST FRAMING - same as item_wpa: a DESCRIPTIVE personal-corpus lens, NOT
a global meta winrate and NOT redistributable. Skills are also a WEAKER
signal than items (the basic-max order is partly champion-fixed - many
kits have one obvious max-first skill), so the ``min_n`` gate + the
``shrink`` damping are load-bearing; a low-N (champion, slot) must NOT
surface a confident wpa. Only the three basics (slots 1/2/3 = Q/W/E) are
considered; the ultimate (slot 4) is excluded (it is leveled whenever
available, never a "max-first" choice).

Reuse, not reinvention: the frame grouping + interpolation + win-prob
machinery is shared with ``core.item_wpa`` (``_load_frames`` /
``_expected_win_for_team``) and ``core.post_game_score``
(``_interpolate_frame_for_event``). No new dependency (stdlib sqlite3).
Connection-injected so a test can pass an in-memory sqlite fixture.
"""
from __future__ import annotations

import logging
import sqlite3
import time

from core.archetype_picks import champion_name_by_key
from core.item_wpa import _expected_win_for_team, _load_frames
from core.post_game_score import WpaModel, _interpolate_frame_for_event, load_model
from core.smoothed_rates import shrink

log = logging.getLogger("rc.skill_wpa")

# Slot -> ability letter. Only the three basics are ranked for max order.
_BASIC_SLOTS = (1, 2, 3)
_SLOT_LETTER = {1: "Q", 2: "W", 3: "E"}

# Rank at which a basic is "maxed" (5 points).
_MAX_RANK = 5

# Shrink constant; same rationale as item_wpa (personal corpus).
_SHRINK_K = 5.0


def _participant_meta(
    conn: sqlite3.Connection, match_id: str
) -> dict[int, tuple[int, int, int]]:
    """Return ``{participant_id: (team_id, win, champion_id)}`` for a match."""
    cur = conn.execute(
        "SELECT participant_id, team_id, win, champion_id "
        "FROM participants WHERE match_id=?",
        (match_id,),
    )
    out: dict[int, tuple[int, int, int]] = {}
    for pid, team_id, win, champ_id in cur:
        try:
            out[int(pid)] = (int(team_id or 0), int(win or 0), int(champ_id or 0))
        except (TypeError, ValueError):
            continue
    return out


def _first_maxed_basics(
    conn: sqlite3.Connection, match_id: str
) -> dict[int, tuple[int, int]]:
    """For each participant, the ``(skill_slot, timestamp_ms)`` of the first
    BASIC ability (slot 1/2/3) to reach rank ``_MAX_RANK``.

    Walks ``SKILL_LEVEL_UP`` events in time order, counting points per slot;
    the first slot to hit 5 wins (and locks the participant out). Returns
    ``{participant_id: (slot, ts_ms)}``; a participant whose game ended
    before any basic hit 5 is absent.
    """
    cur = conn.execute(
        "SELECT timestamp_ms, participant_id, skill_slot "
        "FROM timeline_events WHERE match_id=? "
        "AND event_type='SKILL_LEVEL_UP' "
        "ORDER BY timestamp_ms ASC, id ASC",
        (match_id,),
    )
    ranks: dict[int, dict[int, int]] = {}
    maxed: dict[int, tuple[int, int]] = {}
    for ts_ms, pid, slot in cur:
        if pid is None or slot is None:
            continue
        try:
            pid_i = int(pid)
            slot_i = int(slot)
        except (TypeError, ValueError):
            continue
        if slot_i not in _BASIC_SLOTS or pid_i in maxed:
            continue
        per = ranks.setdefault(pid_i, {})
        per[slot_i] = per.get(slot_i, 0) + 1
        if per[slot_i] >= _MAX_RANK:
            maxed[pid_i] = (slot_i, int(ts_ms or 0))
    return maxed


def compute_skill_wpa(
    conn: sqlite3.Connection,
    *,
    min_n: int = 20,
    queue_id: int | None = None,
    patch: str | None = None,
    model: WpaModel | None = None,
) -> dict:
    """Decompose each ``(champion, first-maxed basic)`` winrate into expected
    vs observed over the local rewind corpus.

    For every participant of every qualifying match who maxed a basic, locate
    the frame state at the rank-5 timestamp, estimate that team's win-prob
    there (expected), and record whether the team won (observed). Per
    ``(champion_id, skill_slot)``:

        observed_winrate = mean(observed)
        expected_winrate = mean(expected)
        wpa              = observed_winrate - expected_winrate
        wpa_shrunk       = wpa * shrink(n)

    Keys with ``n < min_n`` are gated out. ``queue_id`` / ``patch`` optionally
    restrict the match set.

    Returns ``{ok, patch, queue_id, min_n, items: [...], elapsed_ms}`` where
    each row is ``{champion_id, champion, skill_slot, skill, n,
    observed_winrate, expected_winrate, wpa, wpa_shrunk, avg_max_time_s}``
    sorted by ``wpa_shrunk`` desc.

    Fail-soft: a match with no frames, or a max before any frame, is skipped;
    each match is wrapped so one bad row cannot abort the sweep.
    """
    t0 = time.time()

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

    # Accumulators keyed by (champion_id, slot).
    n_obs: dict[tuple[int, int], int] = {}
    sum_obs: dict[tuple[int, int], float] = {}
    sum_exp: dict[tuple[int, int], float] = {}
    sum_ts: dict[tuple[int, int], float] = {}

    for mid in match_ids:
        try:
            frames = _load_frames(conn, mid)
            if not frames:
                continue
            meta = _participant_meta(conn, mid)
            if not meta:
                continue
            maxed = _first_maxed_basics(conn, mid)
            for pid, (slot, ts_ms) in maxed.items():
                pm = meta.get(pid)
                if pm is None:
                    continue
                team_id, win, champ_id = pm
                if champ_id <= 0:
                    continue
                rows = _interpolate_frame_for_event(frames, int(ts_ms or 0))
                if rows is None:  # max before any frame
                    continue
                exp = _expected_win_for_team(
                    rows, float(ts_ms or 0) / 1000.0, team_id, model
                )
                if exp is None:
                    continue
                key = (champ_id, slot)
                n_obs[key] = n_obs.get(key, 0) + 1
                sum_obs[key] = sum_obs.get(key, 0.0) + float(win)
                sum_exp[key] = sum_exp.get(key, 0.0) + exp
                sum_ts[key] = sum_ts.get(key, 0.0) + float(ts_ms or 0) / 1000.0
        except Exception as exc:  # noqa: BLE001 - one bad match cannot abort
            log.warning("compute_skill_wpa: match %s -> %s", mid, exc)
            continue

    items_out: list[dict] = []
    for (champ_id, slot), n in n_obs.items():
        if n < min_n:
            continue
        observed = sum_obs[(champ_id, slot)] / n
        expected = sum_exp[(champ_id, slot)] / n
        wpa = observed - expected
        wpa_shrunk = wpa * shrink(float(n), _SHRINK_K)
        items_out.append({
            "champion_id": champ_id,
            "champion": champion_name_by_key(champ_id) or str(champ_id),
            "skill_slot": slot,
            "skill": _SLOT_LETTER.get(slot, str(slot)),
            "n": n,
            "observed_winrate": round(observed, 4),
            "expected_winrate": round(expected, 4),
            "wpa": round(wpa, 4),
            "wpa_shrunk": round(wpa_shrunk, 4),
            "avg_max_time_s": round(sum_ts[(champ_id, slot)] / n, 1),
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


def compute_skill_wpa_from_db(
    db_path=None,
    *,
    min_n: int = 20,
    queue_id: int | None = None,
    patch: str | None = None,
    model_path=None,
) -> dict:
    """Convenience wrapper: open ``rewind_history.db`` read-only, load the
    persisted WPA model (or fall back), compute, close.
    """
    from pathlib import Path

    src = Path(db_path) if db_path is not None else (Path("data") / "rewind_history.db")
    if not src.exists():
        return {"ok": False, "error": "rewind_history.db missing"}
    model = load_model(model_path)
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)
    try:
        return compute_skill_wpa(
            conn, min_n=min_n, queue_id=queue_id, patch=patch, model=model
        )
    finally:
        conn.close()
