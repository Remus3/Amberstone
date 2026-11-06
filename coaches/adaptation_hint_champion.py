"""Champion / matchup adaptation-hint surface.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the coach hot-path API
(`for_champion`, `matchup_delta`, `format_hint_line`, `insight_card`).
`coaches.adaptation_hint` re-exports these names so existing call sites
keep working unchanged; behavior on well-formed rows is pinned by the
test_adaptation_hint + test_round* suites and
tests/test_adaptation_hint_champion_true_audit_s144.py.

Trust boundary (s144 true-audit cycle 137): every value read from the mode
DB is untrusted shape. agent 4 writes ``aggregates_json`` /
``modifier_json`` with json.dumps at allow_nan=True, fixtures hand-seed
rows, and the columns are nullable, so a NULL count, a non-object JSON
document, a string where a number belongs or a NaN / Infinity literal all
reach this module. Each one degrades to "no signal for that field" -
nothing here raises, nothing returns a non-finite float (the supervisor's
/api/adaptation serialises ``for_champion`` verbatim) and no DB-sourced
name can put a line break into a coach prompt.
"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from itertools import islice
from typing import Iterable

from coaches._adaptation_common import (
    _DEFAULT_TOP_COUNTERS,
    _MIN_ABSOLUTE_DELTA,
    _MIN_SAMPLE,
    _db,
    logger,
)

# A stored JSON document larger than this is refused unread (the writer
# emits a few KB per champion).
_MAX_JSON_CHARS = 1 << 20
# Containers nested deeper than this are dropped (json.loads recursion).
_MAX_JSON_DEPTH = 16
# At most this many item rows are kept from each aggregates list.
_MAX_ITEM_ROWS = 32
# At most this many enemy names are read from the ``enemies`` argument.
_MAX_ENEMIES = 64
# A DB-sourced name printed into hint text is cut to this many chars.
_MAX_LABEL_CHARS = 64
# Stored counts are clamped into [0, _MAX_COUNT].
_MAX_COUNT = 10 ** 9
_DEFAULT_MAX_CHARS = 240
# A stored number larger than this in magnitude is corrupt (rates and
# deltas live in [-1, 1], durations and KDA ratios are small); bounding it
# keeps every ``x * 100`` and ``:.0f`` in the formatters finite - a finite
# 1e308 would print "inf%" and an int near 10**308 raises OverflowError.
_MAX_MAGNITUDE = 1e12


def _real(v) -> bool:
    """True for a finite, bounded int / float that is not a bool."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v) and abs(v) <= _MAX_MAGNITUDE
    except OverflowError:
        return False


def _to_float(v) -> float | None:
    """A finite, bounded float from an int / float / numeric str, else
    None."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) and abs(f) <= _MAX_MAGNITUDE else None


def _to_count(v) -> int:
    """A non-negative bounded int count; anything unusable is 0."""
    f = _to_float(v)
    if f is None or f <= 0:
        return 0
    return int(min(f, _MAX_COUNT))


def _clean(v, depth: int = 0):
    """Copy of a json.loads value with every non-finite float as None."""
    if depth > _MAX_JSON_DEPTH:
        return None
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _clean(x, depth + 1) for k, x in v.items()
                if isinstance(k, str)}
    if isinstance(v, list):
        return [_clean(x, depth + 1) for x in v]
    return v


def _obj(raw, *, finite: bool = True) -> dict | None:
    """Parse a stored JSON column; only a JSON object is accepted.

    ``finite=True`` (aggregates, passed through to callers) turns every
    NaN / Infinity / overflowing literal into None. ``finite=False``
    (modifier rows, read only through ``_to_float``) keeps them as
    non-finite floats so a NaN delta stays distinguishable from a JSON
    null, which historically means 0.0.
    """
    if raw is None:
        # A NULL column has always read as an empty object.
        raw = "{}"
    if not isinstance(raw, (str, bytes)):
        return None
    if len(raw) > _MAX_JSON_CHARS:
        return None
    try:
        if finite:
            parsed = json.loads(raw or "{}", parse_constant=lambda _c: None)
        else:
            parsed = json.loads(raw or "{}")
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(parsed, dict):
        return None
    if not finite:
        return parsed
    cleaned = _clean(parsed)
    return cleaned if isinstance(cleaned, dict) else None


def _dict_rows(v) -> list[dict]:
    if not isinstance(v, list):
        return []
    return [it for it in v if isinstance(it, dict)][:_MAX_ITEM_ROWS]


def _label(v) -> str | None:
    """One printable, length-capped line for a name, or None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return str(v)[:_MAX_LABEL_CHARS] if _real(v) else None
    if not isinstance(v, str):
        return None
    text = "".join(ch if ch.isprintable() else " " for ch in v[:1024])
    text = " ".join(text.split())[:_MAX_LABEL_CHARS].strip()
    return text or None


def _bounded_int(v, default: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        return default
    return v


def _enemy_set(enemies) -> set | None:
    """Normalise ``enemies``: None / empty = no filter; a bare str is one
    name; otherwise up to ``_MAX_ENEMIES`` str entries (non-str dropped)."""
    if enemies is None or isinstance(enemies, (bytes, bytearray)):
        return None
    if isinstance(enemies, str):
        return {enemies} if enemies else None
    try:
        if not enemies:
            return None
        it = iter(enemies)
    except TypeError:
        return set()
    try:
        return {e for e in islice(it, _MAX_ENEMIES) if isinstance(e, str)}
    except TypeError:
        return set()


def _item_seg(it: dict) -> tuple[str, object, object] | None:
    """(name, delta, matches) for a well-formed item row, else None."""
    name = _label(it.get("name") or it.get("item_id"))
    delta = it.get("delta", 0)
    if name is None or not _real(delta):
        return None
    return name, delta, it.get("matches")


def for_champion(champion: str, mode: str) -> dict:
    """Return the bucket + top activated matchups for (champion, mode).

    Shape::

        {
          "champion": "Ahri",
          "mode": "aram",
          "present": True,
          "games_played": 61,
          "wins": 33,
          "losses": 28,
          "win_rate": 0.541,
          "recent_win_rate": 0.40,
          "recent_sample_size": 10,
          "avg_duration_sec": 1142.3,
          "counters": [
              {"opponent": "Xerath", "sample": 5, "observed_wr": 1.0,
               "baseline_wr": 0.54, "delta": 0.459},
              ...
          ]
        }

    ``present=False`` on missing DB / missing row. Never raises. Counts are
    non-negative ints, every float is finite or None (``win_rate`` is None
    when the stored rating is NULL / non-finite), and a matchup row whose
    JSON is not an object or whose ``delta`` is unusable is skipped.
    """
    out: dict = {
        "champion": champion,
        "mode": mode,
        "present": False,
        "games_played": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "recent_win_rate": None,
        "recent_sample_size": 0,
        "avg_duration_sec": None,
        "counters": [],
    }
    # A non-str key is never a champion name, and an int past 64 bits
    # raises OverflowError out of parameter binding (not a sqlite3.Error).
    db = _db(mode) if isinstance(champion, str) else None
    if db is None:
        return out
    try:
        with closing(sqlite3.connect(db)) as conn:
            conn.row_factory = sqlite3.Row
            # Named columns: a table missing one is an OperationalError
            # (caught below), where SELECT * plus row["x"] raised an
            # uncaught IndexError.
            row = conn.execute(
                "SELECT games_played, wins, losses, avg_rating,"
                " aggregates_json FROM adaptation_buckets WHERE champion = ?",
                (champion,),
            ).fetchone()
            if row is None:
                return out
            out["present"] = True
            out["games_played"] = _to_count(row["games_played"])
            out["wins"] = _to_count(row["wins"])
            out["losses"] = _to_count(row["losses"])
            out["win_rate"] = _to_float(row["avg_rating"])
            aj = _obj(row["aggregates_json"]) or {}
            out["recent_win_rate"] = _to_float(aj.get("recent_win_rate"))
            out["recent_sample_size"] = _to_count(aj.get("recent_sample_size"))
            out["avg_duration_sec"] = _to_float(aj.get("avg_duration_sec"))
            out["top_items"] = _dict_rows(aj.get("top_items"))
            out["first_legendary"] = _dict_rows(aj.get("first_legendary"))
            for key in ("recency_30d", "avg_kda", "recent_kda"):
                blob = aj.get(key)
                out[key] = blob if isinstance(blob, dict) and blob else None

            # Activated matchups sorted by |delta| desc.
            mrows = conn.execute(
                """
                SELECT opponent_signature, sample_count, modifier_json
                FROM matchup_modifiers
                WHERE champion = ? AND activated = 1
                """,
                (champion,),
            ).fetchall()
            scored = []
            for m in mrows:
                # A BLOB / non-text opponent is not a champion name and is
                # not JSON-serialisable for /api/adaptation; skip it.
                if not isinstance(m["opponent_signature"], str):
                    continue
                mj = _obj(m["modifier_json"], finite=False)
                if mj is None:
                    continue
                raw_delta = mj.get("delta")
                delta = 0.0 if raw_delta is None else _to_float(raw_delta)
                # A NaN would pass the abs() gate (NaN < x is False) and
                # surface as "nan%" in coach hint text; _to_float already
                # maps every non-finite or junk delta to None.
                if delta is None or abs(delta) < _MIN_ABSOLUTE_DELTA:
                    continue
                observed = _to_float(mj.get("observed_wr"))
                baseline = _to_float(mj.get("baseline_wr"))
                entry = {
                    "opponent": m["opponent_signature"],
                    "sample": _to_count(m["sample_count"]),
                    "observed_wr": 0.0 if observed is None else observed,
                    "baseline_wr": 0.0 if baseline is None else baseline,
                    "delta": delta,
                }
                kda_ratio = _to_float(mj.get("kda_ratio"))
                if kda_ratio is not None:
                    entry["kda_ratio"] = kda_ratio
                    entry["kda_sample"] = _to_count(mj.get("kda_sample"))
                    kda_delta = _to_float(mj.get("kda_delta"))
                    if kda_delta is not None:
                        entry["kda_delta"] = kda_delta
                scored.append(entry)
            scored.sort(key=lambda d: abs(d["delta"]), reverse=True)
            out["counters"] = scored
    except sqlite3.Error as e:
        logger.debug("for_champion sqlite err %s/%s: %s", champion, mode, e)
    return out


def matchup_delta(champion: str, mode: str, opponent: str) -> float | None:
    """Return the ``delta`` (observed_wr - baseline_wr) for a specific
    (champion x opponent x mode) matchup, or None if not activated /
    below sample threshold / unusable. Cheap single-row lookup."""
    if not isinstance(champion, str) or not isinstance(opponent, str):
        return None
    db = _db(mode)
    if db is None:
        return None
    try:
        with closing(sqlite3.connect(db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT sample_count, modifier_json
                FROM matchup_modifiers
                WHERE champion = ? AND opponent_signature = ?
                """,
                (champion, opponent),
            ).fetchone()
    except sqlite3.Error as e:
        logger.debug("matchup_delta err %s/%s vs %s: %s", champion, mode, opponent, e)
        return None
    if row is None or _to_count(row["sample_count"]) < _MIN_SAMPLE:
        return None
    mj = _obj(row["modifier_json"], finite=False)
    if mj is None:
        return None
    raw = mj.get("delta")
    # Missing delta keeps the historic 0.0; a junk or non-finite one is
    # no-data rather than NaN / inf into coach math.
    return 0.0 if raw is None else _to_float(raw)


def format_hint_line(
    champion: str,
    mode: str,
    enemies: Iterable[str] | None = None,
    top_n: int = _DEFAULT_TOP_COUNTERS,
) -> str:
    """One-liner suitable for inlining into a coach prompt.

    Returns ``""`` (empty string) when there's nothing useful to say -
    so the coach can safely concatenate without conditionals. A segment
    whose stored numbers are missing or malformed is omitted, never printed
    as "None" / "nan". ``enemies`` may be a single name; ``top_n <= 0``
    lists no matchups.
    """
    data = for_champion(champion, mode)
    wr = data["win_rate"]
    name = _label(champion)
    if not data["present"] or not data["games_played"] or wr is None \
            or name is None:
        return ""

    n = data["games_played"]
    recent = data["recent_win_rate"]
    parts = [
        f"{name} {mode.upper().replace('_', ' ')} baseline "
        f"{wr*100:.0f}% wr (n={n})"
    ]
    if recent is not None and data["recent_sample_size"] >= 5:
        direction = "^" if recent > wr + 0.05 else ("v" if recent < wr - 0.05 else "-")
        parts.append(f"recent {recent*100:.0f}% {direction}")

    # 30-day meta-trend bucket (separate from last-N rolling).
    r30 = data.get("recency_30d")
    if isinstance(r30, dict):
        games = r30.get("games", 0)
        wr30 = r30.get("win_rate", 0)
        if _real(games) and games >= 5 and _real(wr30):
            dv = r30.get("delta_vs_alltime", 0.0) or 0.0
            if not _real(dv):
                dv = 0.0
            direction = "^" if dv > 0.05 else ("v" if dv < -0.05 else "-")
            parts.append(f"30d {wr30*100:.0f}% {direction} (n={games})")

    # Typical KDA - survivability signal, independent of win/loss so it
    # lights up even before the first live reconcile.
    kda = data.get("avg_kda")
    if isinstance(kda, dict) and _real(kda.get("sample", 0)) \
            and kda.get("sample", 0) >= 5 \
            and all(_real(kda.get(k)) for k in ("ratio", "k", "d", "a")):
        seg = (
            f"typical KDA {kda['ratio']} "
            f"({kda['k']}/{kda['d']}/{kda['a']}, n={kda['sample']})"
        )
        rkda = data.get("recent_kda")
        if isinstance(rkda, dict) and _real(rkda.get("sample", 0)) \
                and rkda.get("sample", 0) >= 5 and _real(rkda.get("ratio")):
            delta = rkda.get("delta_ratio", 0.0)
            if _real(delta):
                direction = "^" if delta > 0.3 else ("v" if delta < -0.3 else "-")
                sign = "+" if delta >= 0 else ""
                seg += (
                    f" | recent {rkda['ratio']} {direction} "
                    f"({sign}{delta} vs baseline, n={rkda['sample']})"
                )
        parts.append(seg)

    # Highlight matchups actually present on the enemy team, if given.
    enemy_set = _enemy_set(enemies)
    limit = _bounded_int(top_n, _DEFAULT_TOP_COUNTERS)
    flagged: list[str] = []
    for c in data["counters"] if limit > 0 else ():
        if enemy_set is not None and c["opponent"] not in enemy_set:
            continue
        opp = _label(c["opponent"])
        if opp is None:
            continue
        sign = "+" if c["delta"] >= 0 else ""
        seg = f"vs {opp} {sign}{c['delta']*100:.0f}% (n={c['sample']})"
        # Matchup KDA delta - only surface if meaningful (|delta| >= 0.3).
        if "kda_delta" in c and abs(c["kda_delta"]) >= 0.3:
            ksign = "+" if c["kda_delta"] >= 0 else ""
            seg += f" KDA {c['kda_ratio']} ({ksign}{c['kda_delta']})"
        flagged.append(seg)
        if len(flagged) >= limit:
            break

    if flagged:
        parts.append("active matchups: " + ", ".join(flagged))

    # First-legendary signal (most actionable - tells the coach "rush X")
    fl_parts = []
    for it in data.get("first_legendary") or []:
        got = _item_seg(it)
        if got is None or not _real(got[2]):
            continue
        iname, delta, matches = got
        sign = "+" if delta >= 0 else ""
        fl_parts.append(f"{iname} {sign}{delta*100:.0f}% (n={matches})")
        if len(fl_parts) >= 2:
            break
    if fl_parts:
        parts.append("first-leg signal: " + "; ".join(fl_parts))

    # Generic item-outcome signals (any pickup) - lower priority, smaller list
    item_parts = []
    for it in data.get("top_items") or []:
        got = _item_seg(it)
        if got is None or not _real(got[2]):
            continue
        iname, delta, matches = got
        sign = "+" if delta >= 0 else ""
        item_parts.append(f"{iname} {sign}{delta*100:.0f}% (n={matches})")
        if len(item_parts) >= 2:
            break
    if item_parts:
        parts.append("historic items: " + "; ".join(item_parts))

    return ". ".join(parts) + "."


def insight_card(
    champion: str,
    mode: str,
    enemies: Iterable[str] | None = None,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Compact copy-to-clipboard summary - one line, bounded.

    Returns "" when no champion data. Format:
      "Tristana ARAM 72% wr (n=61) ^ | rush Statikk Shiv (+19%) |
       vs Morgana -52% (n=5)"

    Always ends after cutting at a ``|`` boundary so the card never
    ends mid-phrase. ``max_chars`` defaults to 240 - long enough for
    two lines on iPad, short enough for a Discord paste; a non-int
    ``max_chars`` uses the default and ``max_chars <= 0`` returns "".
    """
    limit = _bounded_int(max_chars, _DEFAULT_MAX_CHARS)
    if limit <= 0:
        return ""
    data = for_champion(champion, mode)
    wr = data["win_rate"]
    name = _label(champion)
    if not data["present"] or not data["games_played"] or wr is None \
            or name is None:
        return ""
    segs: list[str] = []
    n = data["games_played"]
    head = f"{name} {mode.upper().replace('_',' ')} {wr*100:.0f}% wr (n={n})"
    r30 = data.get("recency_30d")
    if isinstance(r30, dict):
        games = r30.get("games", 0)
        wr30 = r30.get("win_rate", 0)
        if _real(games) and games >= 5 and _real(wr30):
            dv = r30.get("delta_vs_alltime") or 0
            if not _real(dv):
                dv = 0
            arrow = "^" if dv > 0.05 else ("v" if dv < -0.05 else "-")
            head += f" {arrow}30d {wr30*100:.0f}%"
    segs.append(head)

    # KDA segment - only if we have enough sample to be meaningful.
    kda = data.get("avg_kda")
    if isinstance(kda, dict) and _real(kda.get("sample", 0)) \
            and kda.get("sample", 0) >= 5 and _real(kda.get("ratio")):
        kseg = f"KDA {kda['ratio']}"
        rkda = data.get("recent_kda")
        if isinstance(rkda, dict) and _real(rkda.get("sample", 0)) \
                and rkda.get("sample", 0) >= 5 and _real(rkda.get("ratio")):
            dr = rkda.get("delta_ratio", 0.0) or 0.0
            if _real(dr) and abs(dr) >= 0.3:
                arrow = "^" if dr > 0 else "v"
                kseg += f" {arrow}{rkda['ratio']}"
        segs.append(kseg)

    # First-legendary (most actionable, short)
    first_leg = data.get("first_legendary") or []
    for it in first_leg:
        got = _item_seg(it)
        if got is None:
            continue
        iname, delta, _matches = got
        sign = "+" if delta >= 0 else ""
        verb = "rush" if delta > 0 else "avoid"
        segs.append(f"{verb} {iname} ({sign}{delta*100:.0f}%)")
        break

    # Top items - one mention if space
    items = data.get("top_items") or []
    if items and len(first_leg) < 2:
        for it in items:
            got = _item_seg(it)
            if got is None:
                continue
            iname, delta, _matches = got
            sign = "+" if delta >= 0 else ""
            segs.append(f"{iname} {sign}{delta*100:.0f}%")
            break

    # Enemy-specific counter if provided and in counters list
    enemy_set = _enemy_set(enemies)
    for c in data.get("counters", []):
        if enemy_set is None or c["opponent"] in enemy_set:
            opp = _label(c["opponent"])
            if opp is None:
                continue
            sign = "+" if c["delta"] >= 0 else ""
            segs.append(f"vs {opp} {sign}{c['delta']*100:.0f}% (n={c['sample']})")
            break

    out = " | ".join(segs)
    if len(out) <= limit:
        return out
    # Trim at a separator boundary to keep the card grammatical.
    trimmed = out[:limit]
    if " | " in trimmed:
        trimmed = trimmed.rsplit(" | ", 1)[0]
    return trimmed
