"""core/session_hygiene.py - deterministic session-hygiene analytics.

Serves the Haiku-to-ZERO north star (BACKLOG "Session-hygiene + tilt-nudge
cluster"): ZERO API, ZERO LLM. Pure local SQL + math over the tracked
player's OWN stored match history in data/rewind_history.db, one row per
game the player played (so the corpus is already player-scoped).

Every verdict is an ODDS-SHIFT phrased as "your WR is N pts higher/lower in
this context", never causal advice ("you play worse when tired"). We only
observe the player's own historical win-rate conditioned on context; we do
not claim causation.

WHY laplace everywhere: a 2-0 bucket must not outrank a 14-8 one and a
1-game bucket must never read 0% or 100%. Every rate is routed through
core.smoothed_rates.laplace_rate (shared Laplace/Beta primitive, CLAUDE.md
#90) and every bucket also carries a blend()-toward-baseline value so a
consumer can trust small samples less. Raw n rides on every bucket so the
UI can show/hide by confidence.

Read-only. Mirrors core.duration_winrate's _open_ro() file:...?mode=ro seam
(core/duration_winrate.py:57-64) so tests inject a synthetic tmp_path db and
the suite stays clean-checkout safe (the real db is gitignored). Never
writes to the db. Never raises - an absent db or empty corpus returns a
well-formed ok payload with empty buckets and a neutral readiness of 50.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Iterable, Optional

from core.smoothed_rates import blend, laplace_rate, shrink

log = logging.getLogger("rc.session_hygiene")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

_HOUR_MS = 3600 * 1000
_DAY_MS = 24 * _HOUR_MS

# A break longer than this between one game's end and the next game's start
# marks a new play session. 2h is the operator-tunable default.
SESSION_GAP_MS = 2 * _HOUR_MS

# A bucket below this many games does not surface a display WR (it stays a
# None sentinel); mirrors core.duration_winrate.MIN_BUCKET_N so thin cells
# read as "-" rather than a noisy extreme.
MIN_GAMES = 5

# Positions 1..POSITION_CAP; POSITION_CAP is the "Nth or later" tail bucket.
POSITION_CAP = 8

# (label, lo_ms inclusive, hi_ms exclusive | None) over gap-since-previous-game.
RUST_BUCKETS = (
    ("<6h", 0, 6 * _HOUR_MS),
    ("6-24h", 6 * _HOUR_MS, 24 * _HOUR_MS),
    ("1-2d", 24 * _HOUR_MS, 48 * _HOUR_MS),
    ("2d+", 48 * _HOUR_MS, None),
)

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# How many WR points (rate * this) one factor's shrink-blended delta moves the
# readiness score before clamping. 100 keeps a full 1.0-rate swing == 100 pts.
_READINESS_PTS = 100.0

# shrink() confidence thresholds -> tier. With DEFAULT_K=5: shrink(20)=0.8,
# shrink(5)=0.5.
_CONF_HIGH = 0.8
_CONF_MED = 0.5


def _open_ro(db_path: Path) -> Optional[sqlite3.Connection]:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        log.warning("session_hygiene open: %s", exc)
        return None


def _load_rows(conn: sqlite3.Connection,
               queue_ids: Optional[Iterable[int]]) -> list:
    """Return the tracked player's games sorted by creation time ascending.

    Drops rows with a null creation/end ts (cannot be sequenced). Each item:
    (creation_ms, end_ms, win, champ_id).
    """
    where = ["game_creation_ts IS NOT NULL", "game_end_ts IS NOT NULL"]
    params: list = []
    if queue_ids is not None:
        ids = [int(q) for q in queue_ids]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        where.append(f"queue_id IN ({placeholders})")
        params.extend(ids)
    sql = ("SELECT game_creation_ts, game_end_ts, tracked_win, "
           "tracked_champion_id FROM matches WHERE " + " AND ".join(where)
           + " ORDER BY game_creation_ts ASC")
    out = []
    for creation, end, win, champ in conn.execute(sql, params).fetchall():
        out.append((int(creation), int(end), int(bool(win)), champ))
    return out


def _sessionize(rows: list):
    """Annotate each row with (session_id, position_in_session, prev_champ).

    prev_champ is the champion of the immediately preceding game IN THE SAME
    session, or None at a session boundary. Returns a list of dicts.
    """
    annotated = []
    session_id = -1
    position = 0
    prev_end = None
    prev_champ = None
    for creation, end, win, champ in rows:
        new_session = prev_end is None or (creation - prev_end) > SESSION_GAP_MS
        if new_session:
            session_id += 1
            position = 1
            in_session_prev_champ = None
        else:
            position += 1
            in_session_prev_champ = prev_champ
        annotated.append({
            "creation": creation, "end": end, "win": win, "champ": champ,
            "session_id": session_id, "position": position,
            "prev_champ": in_session_prev_champ,
            # gap since the previous game overall (None for the very first).
            "gap_ms": None if prev_end is None else (creation - prev_end),
        })
        prev_end = end
        prev_champ = champ
    return annotated


def _bucket(wins: int, games: int, overall_wr: float, **extra) -> dict:
    """A WR bucket carrying raw n, a display wr (None when thin), and a
    shrink-toward-baseline blended wr (always interior for real inputs)."""
    rate = laplace_rate(wins, games)
    d = {
        "wins": wins,
        "games": games,
        # display: shrunk laplace when the sample is trustworthy, else omitted.
        "wr": round(rate, 4) if games >= MIN_GAMES else None,
        # always present: pulled toward the player's baseline by confidence.
        "wr_blended": round(blend(rate, overall_wr, shrink(games)), 4),
    }
    d.update(extra)
    return d


def _rust_index(gap_ms: int) -> Optional[int]:
    for i, (_label, lo, hi) in enumerate(RUST_BUCKETS):
        if gap_ms >= lo and (hi is None or gap_ms < hi):
            return i
    return None


def compute_session_hygiene(db_path: Path = DEFAULT_DB,
                            now_ms: Optional[int] = None,
                            tz: Optional[tzinfo] = None,
                            queue_ids: Optional[Iterable[int]] = None,
                            conn: Optional[sqlite3.Connection] = None) -> dict:
    """Deterministic session-hygiene verdicts over the player's own corpus.

    now_ms: current epoch ms, injectable for determinism (tests always pass
        it). Only when None do we read the wall clock. tz: timezone for
        hour/weekday bucketing, injectable (default local naive). queue_ids:
        optional queue filter (default: all games). conn: optional injected
        sqlite handle (else a read-only handle to db_path is opened + closed).

    Never raises. An absent db / empty corpus yields ok=True, n=0, empty
    buckets, and a neutral readiness of 50.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    now_ms = int(now_ms)

    own = conn is None
    if own:
        conn = _open_ro(Path(db_path))

    rows: list = []
    if conn is not None:
        try:
            rows = _load_rows(conn, queue_ids)
        except sqlite3.Error as exc:
            log.warning("session_hygiene query: %s", exc)
            rows = []
        finally:
            if own:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    # A game that has not started yet cannot be "played" relative to now. In
    # production now_ms is after every stored game so this is a no-op; it only
    # matters when a caller simulates a now_ms mid-corpus (tests do this).
    rows = [r for r in rows if r[0] <= now_ms]

    annotated = _sessionize(rows)
    total_games = len(annotated)
    total_wins = sum(a["win"] for a in annotated)
    overall_wr = laplace_rate(total_wins, total_games)

    # ---- session detection ------------------------------------------------
    session_ids = {a["session_id"] for a in annotated}
    session_count = len(session_ids)
    last_end = annotated[-1]["end"] if annotated else None
    gap_since_last = None if last_end is None else max(0, now_ms - last_end)
    in_session = bool(last_end is not None and gap_since_last <= SESSION_GAP_MS)
    if in_session:
        last_sid = annotated[-1]["session_id"]
        current_session_games = sum(1 for a in annotated if a["session_id"] == last_sid)
    else:
        current_session_games = 0

    # ---- wr by session position ------------------------------------------
    pos_tally = {p: [0, 0] for p in range(1, POSITION_CAP + 1)}
    for a in annotated:
        p = min(a["position"], POSITION_CAP)
        pos_tally[p][1] += 1
        pos_tally[p][0] += a["win"]
    wr_by_position = []
    for p in range(1, POSITION_CAP + 1):
        w, g = pos_tally[p]
        label = f"{p}+" if p == POSITION_CAP else str(p)
        wr_by_position.append(_bucket(w, g, overall_wr, position=p, label=label))

    # ---- wr by hour / weekday --------------------------------------------
    hour_tally = {h: [0, 0] for h in range(24)}
    wd_tally = {d: [0, 0] for d in range(7)}
    for a in annotated:
        dt = datetime.fromtimestamp(a["creation"] / 1000.0, tz)
        hour_tally[dt.hour][1] += 1
        hour_tally[dt.hour][0] += a["win"]
        wd_tally[dt.weekday()][1] += 1
        wd_tally[dt.weekday()][0] += a["win"]
    wr_by_hour = [
        _bucket(hour_tally[h][0], hour_tally[h][1], overall_wr, hour=h)
        for h in range(24)
    ]
    wr_by_weekday = [
        _bucket(wd_tally[d][0], wd_tally[d][1], overall_wr,
                weekday=d, label=WEEKDAY_LABELS[d])
        for d in range(7)
    ]

    # ---- rust (gap since previous game) ----------------------------------
    rust_tally = [[0, 0] for _ in RUST_BUCKETS]
    for a in annotated:
        if a["gap_ms"] is None:
            continue
        bi = _rust_index(a["gap_ms"])
        if bi is None:
            continue
        rust_tally[bi][1] += 1
        rust_tally[bi][0] += a["win"]
    rust = [
        _bucket(rust_tally[i][0], rust_tally[i][1], overall_wr, label=label)
        for i, (label, _lo, _hi) in enumerate(RUST_BUCKETS)
    ]

    # ---- same-champ requeue (within session only) ------------------------
    same = [0, 0]
    diff = [0, 0]
    for a in annotated:
        if a["prev_champ"] is None:
            continue  # position 1 of a session has no in-session predecessor
        bucket = same if a["champ"] == a["prev_champ"] else diff
        bucket[1] += 1
        bucket[0] += a["win"]
    same_champ_requeue = {
        "same_champ": _bucket(same[0], same[1], overall_wr),
        "diff_champ": _bucket(diff[0], diff[1], overall_wr),
    }

    # ---- readiness --------------------------------------------------------
    readiness = _readiness(
        now_ms, tz, overall_wr, in_session, current_session_games,
        gap_since_last, wr_by_position, wr_by_hour, wr_by_weekday, rust,
    )

    return {
        "ok": True,
        "n": total_games,
        "now_ms": now_ms,
        "session_gap_ms": SESSION_GAP_MS,
        "min_games": MIN_GAMES,
        "overall_wr": round(overall_wr, 4),
        "overall_wins": total_wins,
        "session_detection": {
            "session_count": session_count,
            "current_session_games": current_session_games,
            "gap_since_last_ms": gap_since_last,
            "in_session": in_session,
        },
        "wr_by_session_position": wr_by_position,
        "wr_by_hour": wr_by_hour,
        "wr_by_weekday": wr_by_weekday,
        "rust": rust,
        "same_champ_requeue": same_champ_requeue,
        "readiness": readiness,
    }


def _readiness(now_ms, tz, overall_wr, in_session, current_session_games,
               gap_since_last, wr_by_position, wr_by_hour, wr_by_weekday, rust):
    """Bounded 0-100 "Should I Queue" odds-shift for the CURRENT context.

    Centered at 50 (neutral). Each contributing factor moves it by its
    shrink-blended WR delta vs the player's own baseline, so thin buckets
    barely nudge it. Clamped to [0, 100]. NOT a prediction - an odds-shift.
    """
    now_dt = datetime.fromtimestamp(now_ms / 1000.0, tz)
    next_position = min(current_session_games + 1, POSITION_CAP) if in_session else 1
    hours_since_last = None if gap_since_last is None else gap_since_last / _HOUR_MS

    factors = []

    def add(name, bucket, note):
        # Only contribute when the bucket cleared the trust threshold.
        if bucket is None or bucket["games"] < MIN_GAMES:
            factors.append({"factor": name, "n": bucket["games"] if bucket else 0,
                            "delta_pts": 0.0, "contributed": False, "note": note})
            return
        delta = (bucket["wr_blended"] - overall_wr) * _READINESS_PTS
        factors.append({"factor": name, "n": bucket["games"],
                        "delta_pts": round(delta, 2), "contributed": True,
                        "note": note})

    pos_bucket = next(
        (b for b in wr_by_position if b["position"] == next_position), None)
    add("session_position", pos_bucket, f"next game is #{next_position} this session")

    if gap_since_last is not None:
        ri = _rust_index(int(gap_since_last))
        add("rust", rust[ri] if ri is not None else None,
            f"{hours_since_last:.1f}h since last game")
    else:
        add("rust", None, "no prior game")

    add("hour", wr_by_hour[now_dt.hour], f"local hour {now_dt.hour}")
    add("weekday", wr_by_weekday[now_dt.weekday()], WEEKDAY_LABELS[now_dt.weekday()])

    contributing = [f for f in factors if f["contributed"]]
    adj = sum(f["delta_pts"] for f in contributing)
    score = max(0.0, min(100.0, 50.0 + adj))

    if contributing:
        min_n = min(f["n"] for f in contributing)
        conf_w = shrink(min_n)
        if conf_w >= _CONF_HIGH:
            confidence = "HIGH"
        elif conf_w >= _CONF_MED:
            confidence = "MED"
        else:
            confidence = "LOW"
    else:
        confidence = "LOW"

    return {
        "score": round(score, 1),
        "confidence": confidence,
        "factors": factors,
        "context": {
            "in_session": in_session,
            "current_session_games": current_session_games,
            "next_position": next_position,
            "hours_since_last": (None if hours_since_last is None
                                 else round(hours_since_last, 2)),
            "local_hour": now_dt.hour,
            "local_weekday": now_dt.weekday(),
        },
    }
