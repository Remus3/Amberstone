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
from pathlib import Path

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

# What a malformed MATCH (bad frame / participant values) can raise inside
# the per-match sweep. Deliberately narrow, mirroring core.item_wpa:
# sqlite3.Error is not here (it must propagate - a locked DB is not a bad
# row), and neither is any other class (a defect must surface, not be
# logged once per match and answered ok=True).
_MATCH_DATA_ERRORS = (TypeError, ValueError, ArithmeticError)

# Anchored to the repo root, never the CWD (RM-1022).
_REWIND_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"


def _opt_int(value: object) -> int | None:
    """``int(value)``, or ``None`` when it is missing, a bool or not a
    number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _participant_meta(
    conn: sqlite3.Connection, match_id: str
) -> dict[int, tuple[int, int, int]]:
    """Return ``{participant_id: (team_id, win, champion_id)}`` for a match.

    ``win`` is always 0 or 1. A participant whose outcome is unknown (a
    NULL, out-of-range or non-numeric ``win``) is ABSENT: reading an
    unknown outcome as a loss would bias observed_winrate down. A
    participant whose id is not a number is absent too; a NULL or
    non-numeric team / champion reads as 0, which the caller skips.
    """
    cur = conn.execute(
        "SELECT participant_id, team_id, win, champion_id "
        "FROM participants WHERE match_id=?",
        (match_id,),
    )
    out: dict[int, tuple[int, int, int]] = {}
    for pid, team_id, win, champ_id in cur:
        pid_i = _opt_int(pid)
        win_i = _opt_int(win)
        if pid_i is None or win_i not in (0, 1):
            continue
        out[pid_i] = (_opt_int(team_id) or 0, win_i, _opt_int(champ_id) or 0)
    return out


def _has_level_up_type(conn: sqlite3.Connection) -> bool:
    """Whether ``timeline_events`` carries the ``level_up_type`` column.

    The real corpus does (scripts/rewind_scraper.py stores Riot's
    ``levelUpType``); a minimal fixture or an older DB may not.
    """
    cols = conn.execute("PRAGMA table_info(timeline_events)").fetchall()
    return any(len(c) > 1 and c[1] == "level_up_type" for c in cols)


def _first_maxed_basics(
    conn: sqlite3.Connection, match_id: str, *,
    skip_evolve: bool | None = None,
) -> dict[int, tuple[int, int]]:
    """For each participant, the ``(skill_slot, timestamp_ms)`` of the first
    BASIC ability (slot 1/2/3) to reach rank ``_MAX_RANK``.

    Walks ``SKILL_LEVEL_UP`` events in time order, counting points per slot;
    the first slot to hit 5 wins (and locks the participant out). Returns
    ``{participant_id: (slot, ts_ms)}``; a participant whose game ended
    before any basic hit 5 is absent.

    Only NORMAL skill-ups are rank points. An ``EVOLVE`` skill-up (Kha'Zix
    evolutions, Kai'Sa and Viktor upgrades) is a separate event Riot logs
    on the same slot, so counting it dated maxes early, moved them to the
    wrong slot or invented them. A NULL ``level_up_type`` reads as NORMAL.
    ``skip_evolve`` defaults to whether the column exists.

    A participant with a basic-slot skill-up whose timestamp is NULL or not
    a number is ABSENT: the order of their points is unknowable. Other
    participants of the match are unaffected.
    """
    if skip_evolve is None:
        skip_evolve = _has_level_up_type(conn)
    lut_col = "level_up_type" if skip_evolve else "NULL"
    cur = conn.execute(
        f"SELECT timestamp_ms, participant_id, skill_slot, {lut_col} "
        "FROM timeline_events WHERE match_id=? "
        "AND event_type='SKILL_LEVEL_UP' "
        "ORDER BY timestamp_ms ASC, id ASC",
        (match_id,),
    )
    ranks: dict[int, dict[int, int]] = {}
    maxed: dict[int, tuple[int, int]] = {}
    unordered: set[int] = set()
    for ts_ms, pid, slot, lut in cur:
        pid_i = _opt_int(pid)
        slot_i = _opt_int(slot)
        if pid_i is None or slot_i not in _BASIC_SLOTS:
            continue
        if lut is not None and str(lut) != "NORMAL":
            continue
        ts_i = _opt_int(ts_ms)
        if ts_i is None:
            unordered.add(pid_i)
            continue
        if pid_i in maxed:
            continue
        per = ranks.setdefault(pid_i, {})
        per[slot_i] = per.get(slot_i, 0) + 1
        if per[slot_i] >= _MAX_RANK:
            maxed[pid_i] = (slot_i, ts_i)
    for pid_i in unordered:
        maxed.pop(pid_i, None)
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

    ``min_n`` must be an ``int >= 0`` (``bool`` refused); anything else is
    a ``ValueError`` raised before the sweep.

    Fail-soft on DATA, fail-loud on everything else (the core.item_wpa
    contract):
      * a match with no frames or no participants, a max before any frame,
        a participant with an unknown outcome and a participant whose
        skill-up order is unreadable are each skipped (see
        ``_participant_meta`` / ``_first_maxed_basics``);
      * a match whose frames are malformed (``TypeError`` / ``ValueError``
        / ``ArithmeticError``) is skipped WHOLE: its contribution is rolled
        back, so a skipped match is never half-counted;
      * ``sqlite3.Error`` (for example "database is locked") PROPAGATES - a
        partial sweep must not be served, or cached, as a complete corpus
        (/api/skill-wpa maps it to a 503);
      * any other exception is a defect and propagates too.
    """
    if isinstance(min_n, bool) or not isinstance(min_n, int) or min_n < 0:
        raise ValueError("min_n must be an int >= 0")
    t0 = time.perf_counter()

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

    skip_evolve = _has_level_up_type(conn)

    for mid in match_ids:
        # Per-match observations, merged only when the whole match is read
        # cleanly, so a match skipped half-way contributes nothing.
        obs: list[tuple[tuple[int, int], float, float, float]] = []
        try:
            frames = _load_frames(conn, mid)
            if not frames:
                continue
            meta = _participant_meta(conn, mid)
            if not meta:
                continue
            maxed = _first_maxed_basics(conn, mid, skip_evolve=skip_evolve)
            for pid, (slot, ts_ms) in maxed.items():
                pm = meta.get(pid)
                if pm is None:
                    continue
                team_id, win, champ_id = pm
                if champ_id <= 0:
                    continue
                rows = _interpolate_frame_for_event(frames, ts_ms)
                if rows is None:  # max before any frame
                    continue
                t_s = float(ts_ms) / 1000.0
                exp = _expected_win_for_team(rows, t_s, team_id, model)
                if exp is None:
                    continue
                obs.append(((champ_id, slot), float(win), float(exp), t_s))
        except _MATCH_DATA_ERRORS as exc:
            log.warning("compute_skill_wpa: match %s skipped -> %s: %s",
                        mid, type(exc).__name__, exc)
            continue
        for key, win_f, exp_f, t_s in obs:
            n_obs[key] = n_obs.get(key, 0) + 1
            sum_obs[key] = sum_obs.get(key, 0.0) + win_f
            sum_exp[key] = sum_exp.get(key, 0.0) + exp_f
            sum_ts[key] = sum_ts.get(key, 0.0) + t_s

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
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
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

    Returns ``{"ok": False, "error": "rewind_history.db missing"}`` when
    the DB is absent (or the path is not a regular file). ``sqlite3.Error``
    from the sweep propagates (see ``compute_skill_wpa``).

    The read-only URI goes through ``Path.as_uri``, which percent-encodes
    the path: an f-string ``file:{path}?mode=ro`` let a '#' in the checkout
    path cut the URI short, so SQLite opened (and, with ``?mode=ro`` lost
    in the fragment, CREATED) a different file.
    """
    src = Path(db_path) if db_path is not None else _REWIND_DB
    if not src.is_file():
        return {"ok": False, "error": "rewind_history.db missing"}
    model = load_model(model_path)
    uri = src.absolute().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        return compute_skill_wpa(
            conn, min_n=min_n, queue_id=queue_id, patch=patch, model=model
        )
    finally:
        conn.close()
