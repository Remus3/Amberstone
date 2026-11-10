"""Operator role x game-time-bracket personal benchmark (read-only).

Surfaces the operator's OWN historical SR averages - level / cs / teamfight /
kda - bucketed by role and game-time bracket, for the WP-A4 vertical
"You vs benchmark" stats panel. This is a DESCRIPTIVE personal-corpus lens (the
player's own baselines in, e.g., "mid lane, a game past 14 minutes"), NOT a
global / meta / Riot / Claude number.

WHY NOT core.benchmarks: that module reads champion_benchmarks.json, which is
per-champion only and carries no role, no game-time bracket, and no kda - so it
cannot answer "role X at bracket Y". The grounded source that DOES carry all of
those is the rewind match corpus (data/rewind_history.db): the operator's
tracked participant row per match, joined to the match for duration + kp. See
docs/OVERLAY_BUILD_MASTER_PLAN.md WP-A4a + RC_WORK_TRACKER.md (the deviation
from the plan's named module is recorded there).

Operator identification needs NO puuid: each match row carries the tracked
(operator) champion + team, so the operator participant is the row with that
(champion_id, team_id) in that match - a clean per-match join. The
participants table has no unique key beyond its AUTOINCREMENT id (its
INSERT OR IGNORE never ignores), so a re-ingested match can carry the operator
row more than once: each match is counted ONCE (its first row by id).

The DB is gitignored (large, local-only). corpus_present() is False on a clean
checkout / CI, where role_bracket_grid() returns {} (an empty grid) rather than
raising - the route then renders an empty column, never an error.

Grid shape (nested, JSON-friendly; every number finite):
  { <role>: { <bracket>: {
      "n": <int matches in the cell>,
      "lvl": {"avg": float, "p50": float, "n": int},
      "cs":  {"avg": float, "p50": float, "n": int},
      "tf":  {"avg": float, "p50": float, "n": int},
      "kda": {"avg": float, "p50": float, "n": int},
  } } }
A stat with no usable value reads {"avg": None, "p50": None, "n": 0}.

Value hygiene: SQLite is dynamically typed, so a numeric column can hold TEXT,
a BLOB or a +/-Inf REAL. A value that is not a finite, non-negative number
costs only ITSELF (that stat for that match is skipped); a NULL kills / deaths
/ assists reads as 0 (the kda of a row with any junk component is skipped). A
value above _MAX_STAT (1e12) is junk as well, so no avg or median can overflow
to inf. A row whose duration is not a finite positive number has no bracket
and is skipped whole.

Caching: one in-memory grid, rebuilt when the corpus signature changes - the
(mtime_ns, size) of the .db AND of its -wal sidecar, compared for equality.
The corpus runs WAL (scripts/rewind_scraper.py), where a commit only touches
the -wal file until a checkpoint, and a restored backup can carry an OLDER
mtime; both must trigger a re-read. A rebuild that fails (a sqlite3.Error such
as a transient lock) keeps the last good grid and is retried once the
signature changes or _RETRY_AFTER_S passes, never on every call. Callers get a
private copy of the grid, never the cache's own dicts.
"""
from __future__ import annotations

import copy
import math
import sqlite3
import stat as stat_mod
import string
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REWIND_DB_PATH = ROOT / "data" / "rewind_history.db"

# Canonical role keys (the panel's row set) + the Riot team_position -> role map.
VALID_ROLES = ("top", "jungle", "mid", "bot", "support")
_POSITION_ROLE = {
    "TOP": "top",
    "JUNGLE": "jungle",
    "MIDDLE": "mid",
    "BOTTOM": "bot",
    "UTILITY": "support",
}
# Common UI / caller aliases onto the canonical keys (the route normalizes these
# so adc/middle/sup all resolve rather than 400).
ROLE_ALIASES = {
    "top": "top", "toplane": "top",
    "jungle": "jungle", "jg": "jungle", "jungler": "jungle",
    "mid": "mid", "middle": "mid", "midlane": "mid",
    "bot": "bot", "bottom": "bot", "adc": "bot", "marksman": "bot", "carry": "bot",
    "support": "support", "sup": "support", "supp": "support", "utility": "support",
}

# Game-time brackets over match duration (seconds). 14 min / 25 min boundaries -
# the two-bucket early / mid split (overlay item 8 lock-step with
# core.rank_tier_bench + web/js/panels/stats_panel.js; the old "late" >=35:00
# bucket is retired). The panel picks the bracket from the live game time
# (lc.game_time) so "You" is compared to same-length games. This module is now
# DEPRECATED-ALIVE (the reworked panel reads rank_tier_bench); the boundaries
# stay aligned so the two never drift.
VALID_BRACKETS = ("early", "mid")
_BRACKET_EARLY_MAX_S = 840    # < 14:00
_BRACKET_MID_MAX_S = 1500     # nominal 14:00 - 24:59 label; >= 840 folds to mid

# ASCII whitespace only: str.strip() with no argument also eats NBSP, NEL,
# U+3000 and the ASCII separators U+001C-U+001F. string.whitespace is exactly
# the six ASCII blanks (space, tab, LF, CR, VT, FF).
_ASCII_BLANKS = string.whitespace

# Seconds before a failed rebuild is retried when the corpus signature has not
# changed (a changed signature retries at once).
_RETRY_AFTER_S = 60.0

# sqlite3.connect busy timeout (seconds) for the read-only scan.
_CONNECT_TIMEOUT_S = 2.0

# Largest value read as a real stat. Every column read here is a count, a
# level, a kill-participation figure or a duration, all far below this; a
# finite value near the float max (1.5e308) would overflow to inf in the
# avg's sum or the even-n median's pair sum, so it is junk too.
_MAX_STAT = 1e12


def _num(value) -> float | None:
    """A corpus value as a finite float in [0, _MAX_STAT], else None.

    NULL, bool, BLOB, non-numeric TEXT, +/-Inf / NaN, negatives and values
    above _MAX_STAT are all None: every stat this module reads is a count, a
    level or a duration."""
    if value is None or isinstance(value, (bool, bytes, bytearray, memoryview)):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(f) or f < 0 or f > _MAX_STAT:
        return None
    return f


def _bracket_for_duration(secs) -> str | None:
    s = _num(secs)
    if s is None or s <= 0:
        return None
    if s < _BRACKET_EARLY_MAX_S:
        return "early"
    return "mid"


def normalize_role(raw) -> str | None:
    """Map a caller role string (canonical or alias) to a canonical key, or None
    if unrecognized. Case-insensitive over ASCII; a non-str or non-ASCII value
    is None (str.lower() maps KELVIN SIGN to "k", and str.strip() eats
    Unicode blanks), and only ASCII whitespace is stripped."""
    if not isinstance(raw, str) or not raw.isascii():
        return None
    key = raw.strip(_ASCII_BLANKS).lower()
    if not key:
        return None
    return ROLE_ALIASES.get(key)


def corpus_present() -> bool:
    """True when the rewind corpus DB is on disk (False on a clean checkout /
    CI, where the grid is empty)."""
    try:
        return REWIND_DB_PATH.is_file()
    except OSError:
        return False


def _signature() -> tuple | None:
    """(mtime_ns, size) of the corpus .db and of its -wal sidecar, or None
    when the .db is absent, unreadable or not a regular file."""
    try:
        st = REWIND_DB_PATH.stat()
    except (OSError, ValueError):
        return None
    if not stat_mod.S_ISREG(st.st_mode):
        return None
    try:
        wst = Path(f"{REWIND_DB_PATH}-wal").stat()
        wal = (wst.st_mtime_ns, wst.st_size)
    except (OSError, ValueError):
        wal = None
    return (st.st_mtime_ns, st.st_size, wal)


class _GridCache:
    def __init__(self) -> None:
        self._grid: dict | None = None
        self._sig: tuple | None = None
        self._failed_sig: tuple | None = None
        self._failed_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> dict:
        sig = _signature()
        if sig is None:
            return {}
        with self._lock:
            if self._grid is not None and sig == self._sig:
                return copy.deepcopy(self._grid)
            if (sig == self._failed_sig
                    and time.monotonic() - self._failed_at < _RETRY_AFTER_S):
                return copy.deepcopy(self._grid) if self._grid is not None else {}
            grid = _scan()
            if grid is None:
                self._failed_sig = sig
                self._failed_at = time.monotonic()
                return copy.deepcopy(self._grid) if self._grid is not None else {}
            self._grid = grid
            self._sig = sig
            self._failed_sig = None
            return copy.deepcopy(grid)

    def clear(self) -> None:
        with self._lock:
            self._grid = None
            self._sig = None
            self._failed_sig = None
            self._failed_at = 0.0


_cache = _GridCache()

# The operator (tracked) participant joined to the match. game_mode='CLASSIC' is
# Summoner's Rift (the stats panel scope); duration > 0 drops unfinished rows.
# ORDER BY p.id makes "first row per match" deterministic for the dedupe.
_QUERY = """
SELECT m.match_id          AS mid,
       m.game_duration_s   AS dur,
       p.team_position     AS pos,
       p.champ_level       AS lvl,
       p.total_minions_killed   AS tmk,
       p.neutral_minions_killed AS nmk,
       p.kills             AS k,
       p.deaths            AS d,
       p.assists           AS a,
       m.tracked_kp        AS kp
FROM matches m
JOIN participants p
  ON p.match_id = m.match_id
 AND p.champion_id = m.tracked_champion_id
 AND p.team_id = m.tracked_team_id
WHERE m.game_mode = 'CLASSIC'
  AND m.game_duration_s > 0
ORDER BY p.id
"""


def _median(vals: list[float]) -> float:
    n = len(vals)
    s = sorted(vals)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _stat(vals: list[float]) -> dict:
    if not vals:
        return {"avg": None, "p50": None, "n": 0}
    return {
        "avg": round(sum(vals) / len(vals), 2),
        "p50": round(_median(vals), 2),
        "n": len(vals),
    }


def _cs(tmk, nmk) -> float | None:
    """Lane + jungle minions; NULL reads as 0 (the old COALESCE), junk -> None."""
    parts = []
    for v in (tmk, nmk):
        if v is None:
            parts.append(0.0)
            continue
        f = _num(v)
        if f is None:
            return None
        parts.append(f)
    total = parts[0] + parts[1]
    return total if math.isfinite(total) else None


def _kda(k, d, a) -> float | None:
    """(kills + assists) / max(deaths, 1); NULL reads as 0, junk -> None."""
    vals = []
    for v in (k, d, a):
        if v is None:
            vals.append(0.0)
            continue
        f = _num(v)
        if f is None:
            return None
        vals.append(f)
    kk, dd, aa = vals
    out = (kk + aa) / (dd if dd > 0 else 1.0)
    return out if math.isfinite(out) else None


def _decode_text(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def _scan() -> dict | None:
    """One read-only scan of the rewind corpus into the role x bracket grid,
    or None when the scan failed (a sqlite3.Error).

    Read-only (mode=ro) so a concurrent RC-RewindCatchup writer never blocks or
    is blocked (the DB runs WAL). The URI goes through Path.as_uri, which
    percent-encodes the path: an f-string "file:{path}?mode=ro" let a '#', '?'
    or '%' in the checkout path truncate the URI or open a different file."""
    try:
        if not REWIND_DB_PATH.is_file():
            return {}
        uri = Path(REWIND_DB_PATH).absolute().as_uri() + "?mode=ro"
    except (OSError, ValueError):
        return None
    # accumulators: (role, bracket) -> {"rows": n, "lvl":[], "cs":[], ...}
    acc: dict[tuple[str, str], dict] = {}
    seen: set = set()
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=_CONNECT_TIMEOUT_S)
        try:
            # A TEXT value that is not valid UTF-8 would otherwise raise
            # OperationalError mid-scan and empty the whole grid; decoded
            # with replacement it is junk that costs only its own row.
            conn.text_factory = _decode_text
            for mid, dur, pos, lvl, tmk, nmk, k, d, a, kp in conn.execute(_QUERY):
                if mid in seen:
                    continue
                seen.add(mid)
                role = (_POSITION_ROLE.get(pos.strip(_ASCII_BLANKS).upper())
                        if isinstance(pos, str) and pos.isascii() else None)
                bracket = _bracket_for_duration(dur)
                if role is None or bracket is None:
                    continue
                cell = acc.setdefault(
                    (role, bracket),
                    {"rows": 0, "lvl": [], "cs": [], "tf": [], "kda": []})
                cell["rows"] += 1
                for key, val in (("lvl", _num(lvl)), ("cs", _cs(tmk, nmk)),
                                 ("tf", _num(kp)), ("kda", _kda(k, d, a))):
                    if val is not None:
                        cell[key].append(val)
        finally:
            conn.close()
    except sqlite3.Error:
        return None

    grid: dict = {}
    for (role, bracket), lists in acc.items():
        grid.setdefault(role, {})[bracket] = {
            "n": lists["rows"],
            "lvl": _stat(lists["lvl"]),
            "cs": _stat(lists["cs"]),
            "tf": _stat(lists["tf"]),
            "kda": _stat(lists["kda"]),
        }
    return grid


def role_bracket_grid() -> dict:
    """Return the full role x bracket grid (signature-cached, a private copy).
    {} when the corpus is absent. Never raises - a DB error keeps the last good
    grid, or {} when there is none."""
    return _cache.get()


def _reset_cache() -> None:
    """Test-only: drop the in-memory grid cache."""
    _cache.clear()
