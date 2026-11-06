"""Champion-aggregate / KDA-trend adaptation surface.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the leaderboard / streak
data (`top_champions`, `kda_trends`). `coaches.adaptation_hint`
re-exports these names so existing call sites keep working unchanged.

Trust boundary (s144 true-audit cycle 150, RM-1876..RM-1885): every
column and every ``aggregates_json`` field is read from a mode DB RC did
not validate on the way in, and the results are served by the supervisor
with ``allow_nan=False`` (``/api/adaptation``, ``/api/trending``) and fed
to the digest, the cold-streak pass and the CLI. So both functions never
raise on a bad row, never emit a non-finite or absurd (> 1e12) number,
never let a dropped row take a top-N slot, and name a champion only as
one printable line of at most 64 chars. Well-formed rows give
byte-identical output.
"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing

from coaches._adaptation_common import _db, logger

_MAX_ABS = 1e12
_MAX_LABEL_CHARS = 64
# Largest value bound to a SQLite parameter / used as a slice bound; a
# Python int past 2**63 - 1 raises OverflowError out of parameter binding.
_MAX_BOUND = 2 ** 62
# What decoding one aggregates_json cell can raise: malformed text
# (JSONDecodeError, a ValueError), undecodable BLOB bytes
# (UnicodeDecodeError, a ValueError), a non-text cell (TypeError), and a
# deeply nested document (RecursionError).
_DECODE_ERRORS = (ValueError, TypeError, RecursionError)


def _finite(v) -> float | None:
    """A finite float with |v| <= 1e12 from a real (non-bool) number."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) and abs(f) <= _MAX_ABS else None


def _number(v) -> float | None:
    """``_finite`` that also accepts numeric text (``int("20")`` and
    ``float("0.5")`` were accepted before, so a TEXT cell keeps parsing)."""
    if isinstance(v, str):
        s = v.strip()[:64]
        try:
            v = int(s)
        except ValueError:
            try:
                v = float(s)
            except ValueError:
                return None
    return _finite(v)


def _count(v) -> int | None:
    """A non-negative int (a finite float truncates, like ``int()`` did),
    else None."""
    f = _number(v)
    if f is None or f < 0:
        return None
    return int(v) if isinstance(v, int) else int(f)


def _bound(v, default: int) -> int:
    """A caller's ``n`` / floor as an int SQLite can bind; a bool or a
    non-int falls back to ``default``."""
    if isinstance(v, bool) or not isinstance(v, int):
        return default
    return max(-_MAX_BOUND, min(_MAX_BOUND, v))


def _floor(v, default):
    """A caller's ``min_games`` / ``min_sample``: a real finite number
    (a float floor was accepted before), else ``default``."""
    if isinstance(v, int) and not isinstance(v, bool):
        return _bound(v, default)
    f = _finite(v)
    return default if f is None else f


def _text(b: bytes):
    """sqlite3 text_factory: a TEXT cell holding invalid UTF-8 comes back
    as its raw bytes (which every validator here rejects) instead of
    raising OperationalError mid-fetch and losing the whole mode."""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b


def _label(v) -> str | None:
    """One printable line of at most ``_MAX_LABEL_CHARS``, or None."""
    if not isinstance(v, str):
        return None
    text = "".join(ch if ch.isprintable() else " " for ch in v[:1024])
    text = " ".join(text.split())[:_MAX_LABEL_CHARS].strip()
    return text or None


def _aggregates(raw) -> dict | None:
    """The decoded ``aggregates_json`` object; ``{}`` for an empty or
    undecodable cell (unchanged), None for a decoded non-object."""
    try:
        aj = json.loads(raw or "{}")
    except _DECODE_ERRORS:
        return {}
    return aj if isinstance(aj, dict) else None


def _scalar(v):
    """A JSON-safe scalar: str / None / bool pass, a number must be
    finite and bounded, anything else is None."""
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, int):
        return v if abs(v) <= _MAX_ABS else None
    return _finite(v)


def _kda_block(v) -> dict | None:
    """A KDA sub-object with every value scrubbed to a JSON-safe scalar."""
    if not isinstance(v, dict):
        return None
    return {str(k): _scalar(x) for k, x in v.items()}


def _top_entry(r) -> dict | None:
    champion = _label(r["champion"])
    games = _count(r["games_played"])
    if champion is None or games is None:
        return None
    aj = _aggregates(r["aggregates_json"])
    if aj is None:
        aj = {}
    rss = aj.get("recent_sample_size")
    return {
        "champion": champion,
        "games_played": games,
        "wins": _count(r["wins"]) or 0,
        "losses": _count(r["losses"]) or 0,
        "win_rate": _number(r["avg_rating"]),
        "recent_win_rate": _finite(aj.get("recent_win_rate")),
        "recent_sample_size": (_count(rss) or 0) if rss else 0,
        "avg_duration_sec": _finite(aj.get("avg_duration_sec")),
        "avg_kda": _kda_block(aj.get("avg_kda")),
        "recent_kda": _kda_block(aj.get("recent_kda")),
    }


def top_champions(mode: str, n: int = 10, min_games: int = 20) -> list[dict]:
    """Top-N champions by games_played in ``mode`` with at least
    ``min_games`` sample. Useful for dashboards + LLM context.

    A row with no usable champion name or games count is skipped and
    never takes one of the N slots; ``n <= 0`` lists nothing.
    """
    n = _bound(n, 10)
    min_games = _floor(min_games, 20)
    db = _db(mode)
    if db is None or n <= 0:
        return []
    out: list[dict] = []
    skipped = 0
    try:
        with closing(sqlite3.connect(db)) as conn:
            conn.row_factory = sqlite3.Row
            conn.text_factory = _text
            # No SQL LIMIT: a skipped row must not consume a slot, so the
            # cursor is read until N rows survive validation.
            cur = conn.execute(
                """
                SELECT champion, games_played, wins, losses,
                       avg_rating, aggregates_json
                FROM adaptation_buckets
                WHERE games_played >= ?
                ORDER BY games_played DESC
                """,
                (min_games,),
            )
            for r in cur:
                entry = _top_entry(r)
                if entry is None:
                    skipped += 1
                    continue
                out.append(entry)
                if len(out) >= n:
                    break
    except sqlite3.Error as e:
        logger.debug("top_champions err %s: %s", mode, e)
        return []
    if skipped:
        logger.debug("top_champions %s: skipped %d bad row(s)", mode, skipped)
    return out


def _streak_entry(r, min_sample: int) -> dict | None:
    champion = _label(r["champion"])
    if champion is None:
        return None
    aj = _aggregates(r["aggregates_json"])
    if not aj:
        return None
    avg = aj.get("avg_kda")
    rec = aj.get("recent_kda")
    if not avg or not rec:
        return None
    if not isinstance(avg, dict) or not isinstance(rec, dict):
        return None
    raw_sample = rec.get("sample")
    sample = _count(raw_sample) if raw_sample else 0
    if sample is None or sample < min_sample:
        return None
    ratios = []
    for raw in (avg.get("ratio"), rec.get("ratio"), rec.get("delta_ratio")):
        f = _number(raw) if raw else 0.0
        if f is None:
            return None
        ratios.append(f)
    baseline, recent, delta = ratios
    return {
        "champion": champion,
        "baseline_ratio": baseline,
        "recent_ratio": recent,
        "delta": delta,
        "sample": sample,
    }


def kda_trends(mode: str, n: int = 3, min_sample: int = 5) -> dict:
    """Identify champions on KDA streaks (hot or cold) in ``mode``.

    Uses ``recent_kda.delta_ratio`` - positive means the last-N window
    is outperforming the all-time baseline, negative means the player
    is underperforming on that champion recently.

    Returns ``{"mode": mode, "hot": [...], "cold": [...]}`` where each
    entry has ``{champion, baseline_ratio, recent_ratio, delta,
    sample}``. Both lists are sorted by |delta| desc. Empty lists if
    the mode DB is missing, no champion has enough sample, or
    ``n <= 0``. A row with a non-object field, a junk / non-finite /
    absurd ratio or sample, or no usable champion name is skipped.
    """
    n = _bound(n, 3)
    min_sample = _floor(min_sample, 5)
    db = _db(mode)
    empty = {"mode": mode, "hot": [], "cold": []}
    if db is None or n <= 0:
        return empty
    entries: list[dict] = []
    skipped = 0
    try:
        with closing(sqlite3.connect(db)) as conn:
            conn.row_factory = sqlite3.Row
            conn.text_factory = _text
            rows = conn.execute(
                "SELECT champion, aggregates_json FROM adaptation_buckets"
            ).fetchall()
    except sqlite3.Error as e:
        logger.debug("kda_trends err %s: %s", mode, e)
        return empty
    for r in rows:
        entry = _streak_entry(r, min_sample)
        if entry is None:
            skipped += 1
            continue
        entries.append(entry)
    if skipped:
        logger.debug("kda_trends %s: skipped %d row(s)", mode, skipped)
    hot = sorted((e for e in entries if e["delta"] > 0),
                 key=lambda e: e["delta"], reverse=True)[:n]
    cold = sorted((e for e in entries if e["delta"] < 0),
                  key=lambda e: e["delta"])[:n]
    return {"mode": mode, "hot": hot, "cold": cold}
