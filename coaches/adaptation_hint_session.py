"""Session timeline adaptation surface.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the cross-mode "what did
I play" aggregates (`session_summary`, `session_games`).
`coaches.adaptation_hint` re-exports these names so existing call sites
keep working unchanged.

Consumers: the supervisor's ``GET /api/session`` and
``GET /api/session-games`` (``agents/_supervisor_http.py``), which call
these with no try around the call and serialize with
``allow_nan=False``, and the ``--session`` / ``--games`` CLI. So every
value read from a mode DB is treated as untrusted (s144 true-audit cycle
139, RM-1809..RM-1817; pinned by
``tests/test_adaptation_hint_session_true_audit_s144.py``):

* a K / D / A triple counts only when all three are finite numbers in
  ``[0, _MAX_STAT]``; anything else (TEXT, inf, negative, absurd) leaves
  that game out of the KDA sample but still counts the game;
* ``win`` is 1, 0 or None; ``duration_sec`` is a finite number in
  ``[0, _MAX_DURATION_SEC]`` or None;
* champion / source labels are one printable line of at most
  ``_MAX_LABEL_CHARS`` characters (a non-text or blank champion is
  "Unknown", a non-text or blank source is None);
* TEXT cells holding invalid UTF-8 decode with replacement instead of
  raising, so one corrupt cell cannot drop a whole mode;
* only rows whose ``started_at`` is TEXT are session rows (SQLite sorts a
  BLOB above every TEXT, so a BLOB passed the ``>=`` filter);
* a mode whose read fails contributes nothing (never a partial mode) and
  the failure is logged at WARNING;
* every connection is closed (``with sqlite3.connect()`` alone only
  commits);
* a non-str ``since_iso`` falls back to the start of today, and a
  ``limit`` that is not a positive int does not clamp.

Well-formed rows give the same output as before the audit.
"""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from datetime import datetime

from coaches._adaptation_common import (
    SUPPORTED_MODES,
    _db,
    _start_of_today_iso,
    logger,
)

# Largest per-game kill / death / assist count treated as real data.
_MAX_STAT = 10 ** 6
# Largest per-game duration treated as real data (about 115 days).
_MAX_DURATION_SEC = 10 ** 7
# Longest champion / source label passed through.
_MAX_LABEL_CHARS = 64


def _since(since_iso) -> str:
    if isinstance(since_iso, datetime):
        return since_iso.isoformat()
    if isinstance(since_iso, str) and since_iso:
        return since_iso
    return _start_of_today_iso()


def _number(v, cap: int):
    """``v`` when it is a finite int / float in ``[0, cap]``, else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if v < 0 or v > cap:
        return None
    return v


def _kda(r, has_kda: bool):
    """The row's (k, d, a) when all three are usable, else None."""
    if not has_kda:
        return None
    k = _number(r["kills"], _MAX_STAT)
    d = _number(r["deaths"], _MAX_STAT)
    a = _number(r["assists"], _MAX_STAT)
    if k is None or d is None or a is None:
        return None
    return k, d, a


def _win(v) -> int | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v == 1:
            return 1
        if v == 0:
            return 0
    return None


def _label(v) -> str | None:
    """One printable line of at most ``_MAX_LABEL_CHARS``, or None."""
    if not isinstance(v, str):
        return None
    s = "".join(ch if ch.isprintable() else " " for ch in v)
    s = " ".join(s.split())[:_MAX_LABEL_CHARS].rstrip()
    return s or None


def _decode_text(b: bytes) -> str:
    return b.decode("utf-8", "replace")


def _connect(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.text_factory = _decode_text
    return conn


def _kda_cols(conn) -> tuple[bool, str]:
    # KDA columns may not exist if this DB predates round 23
    # *and* startup migration hasn't run.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    has_kda = {"kills", "deaths", "assists"} <= cols
    return has_kda, (", kills, deaths, assists" if has_kda else "")


def session_summary(since_iso: str | None = None) -> dict:
    """Aggregate every ``matches`` row across all mode DBs where
    ``started_at >= since_iso``.

    Default ``since_iso``: start of today, local timezone.

    Returns::

        {
          "since": "<iso>",
          "games": 12,
          "wins": 7,
          "losses": 5,
          "win_rate": 0.583,
          "avg_kda": {"k": 9.5, "d": 6.1, "a": 14.3, "ratio": 3.9, "sample": 12},
          "per_mode": {"aram": {...}, "sr_ranked": {...}},
          "champions": [
            {"champion": "Ahri", "games": 4, "wins": 3, "kda_ratio": 4.1, ...},
            ...
          ]
        }

    Never raises on missing DBs; each absent mode becomes an empty slot
    in ``per_mode`` with zero counts.
    """
    since = _since(since_iso)
    totals = {"games": 0, "wins": 0, "losses": 0,
              "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0}
    per_mode: dict[str, dict] = {}
    champ_acc: dict[str, dict] = {}   # keyed by champion only (cross-mode)

    for mode in SUPPORTED_MODES:
        db = _db(mode)
        mode_slot = {"games": 0, "wins": 0, "losses": 0,
                     "kda_sample": 0, "kda_ratio": None}
        per_mode[mode] = mode_slot
        if db is None:
            continue
        try:
            with closing(_connect(db)) as conn:
                has_kda, extra = _kda_cols(conn)
                rows = conn.execute(
                    f"""SELECT champion, win{extra}
                        FROM matches
                        WHERE typeof(started_at) = 'text'
                          AND started_at >= ?""",
                    (since,),
                ).fetchall()
        except sqlite3.Error as e:
            logger.warning("session_summary: skipped mode %s: %s", mode, e)
            continue
        mode_k = mode_d = mode_a = mode_ksample = 0
        for r in rows:
            champ = _label(r["champion"]) or "Unknown"
            totals["games"] += 1
            mode_slot["games"] += 1
            ca = champ_acc.setdefault(champ, {
                "champion": champ, "games": 0, "wins": 0, "losses": 0,
                "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0,
                "modes": set(),
            })
            ca["games"] += 1
            ca["modes"].add(mode)
            win = _win(r["win"])
            if win == 1:
                totals["wins"] += 1
                mode_slot["wins"] += 1
                ca["wins"] += 1
            elif win == 0:
                totals["losses"] += 1
                mode_slot["losses"] += 1
                ca["losses"] += 1
            kda = _kda(r, has_kda)
            if kda is not None:
                k, d, a = kda
                totals["k_sum"] += k
                totals["d_sum"] += d
                totals["a_sum"] += a
                totals["kda_sample"] += 1
                ca["k_sum"] += k
                ca["d_sum"] += d
                ca["a_sum"] += a
                ca["kda_sample"] += 1
                mode_k += k
                mode_d += d
                mode_a += a
                mode_ksample += 1
        if mode_ksample:
            mk = mode_k / mode_ksample
            md = mode_d / mode_ksample
            ma = mode_a / mode_ksample
            mode_slot["kda_sample"] = mode_ksample
            mode_slot["kda_ratio"] = round((mk + ma) / max(md, 1.0), 2)

    # Overall KDA.
    avg_kda: dict | None = None
    if totals["kda_sample"]:
        k = totals["k_sum"] / totals["kda_sample"]
        d = totals["d_sum"] / totals["kda_sample"]
        a = totals["a_sum"] / totals["kda_sample"]
        avg_kda = {
            "k": round(k, 2), "d": round(d, 2), "a": round(a, 2),
            "ratio": round((k + a) / max(d, 1.0), 2),
            "sample": totals["kda_sample"],
        }

    wr = (totals["wins"] / (totals["wins"] + totals["losses"])
          if (totals["wins"] + totals["losses"]) else None)

    champs_list = []
    for ca in champ_acc.values():
        c_kda = None
        if ca["kda_sample"]:
            k = ca["k_sum"] / ca["kda_sample"]
            d = ca["d_sum"] / ca["kda_sample"]
            a = ca["a_sum"] / ca["kda_sample"]
            c_kda = round((k + a) / max(d, 1.0), 2)
        reported = ca["wins"] + ca["losses"]
        champs_list.append({
            "champion": ca["champion"],
            "games": ca["games"],
            "wins": ca["wins"],
            "losses": ca["losses"],
            "win_rate": (round(ca["wins"] / reported, 3) if reported else None),
            "kda_ratio": c_kda,
            "kda_sample": ca["kda_sample"],
            "modes": sorted(ca["modes"]),
        })
    champs_list.sort(key=lambda c: (-c["games"], -(c["kda_ratio"] or 0.0)))

    return {
        "since": since,
        "games": totals["games"],
        "wins": totals["wins"],
        "losses": totals["losses"],
        "win_rate": (round(wr, 3) if wr is not None else None),
        "avg_kda": avg_kda,
        "per_mode": per_mode,
        "champions": champs_list,
    }


def _game_row(r, mode: str, has_kda: bool) -> dict:
    kda = None
    kda_ratio = None
    triple = _kda(r, has_kda)
    if triple is not None:
        k, d, a = triple
        kda = {"k": k, "d": d, "a": a}
        kda_ratio = round((k + a) / max(d, 1), 2)
    ended = r["ended_at"]
    return {
        "started_at": r["started_at"],
        "ended_at": ended if isinstance(ended, str) else None,
        "mode": mode,
        # Same "Unknown" fallback as the summary: the --games CLI formats
        # this with a str spec, so None would raise there.
        "champion": _label(r["champion"]) or "Unknown",
        "win": _win(r["win"]),
        "duration_sec": _number(r["duration_sec"], _MAX_DURATION_SEC),
        "kda": kda,
        "kda_ratio": kda_ratio,
        "source": _label(r["source"]),
    }


def session_games(since_iso: str | None = None, limit: int | None = None) -> list[dict]:
    """Chronological timeline of matches across all mode DBs since
    ``since_iso`` (default: start of today, local time).

    Each row::

        {
          "started_at": "<iso>", "ended_at": "<iso or None>",
          "mode": "aram", "champion": "Ahri",
          "win": 1 or 0 or None,
          "duration_sec": 1234,
          "kda": {"k": 10, "d": 3, "a": 15} or None,
          "kda_ratio": 8.33 or None,
          "source": "live-phase3",
        }

    Sorted oldest-first so the dashboard can render a simple scrolling
    feed without re-sorting. ``limit`` (a positive int) clamps the tail
    (most recent N). Missing DBs / missing KDA cols are handled
    gracefully; a mode whose read fails contributes no rows.
    """
    since = _since(since_iso)
    rows: list[dict] = []
    for mode in SUPPORTED_MODES:
        db = _db(mode)
        if db is None:
            continue
        try:
            with closing(_connect(db)) as conn:
                has_kda, extra = _kda_cols(conn)
                fetched = conn.execute(
                    f"""SELECT started_at, ended_at, champion, win,
                               duration_sec, source{extra}
                        FROM matches
                        WHERE typeof(started_at) = 'text'
                          AND started_at >= ?
                        ORDER BY started_at""",
                    (since,),
                ).fetchall()
        except sqlite3.Error as e:
            logger.warning("session_games: skipped mode %s: %s", mode, e)
            continue
        rows.extend(_game_row(r, mode, has_kda) for r in fetched)
    rows.sort(key=lambda r: r["started_at"] or "")
    if (isinstance(limit, int) and not isinstance(limit, bool)
            and limit > 0 and len(rows) > limit):
        rows = rows[-limit:]
    return rows
