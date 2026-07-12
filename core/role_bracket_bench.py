"""Operator role x game-time-bracket personal benchmark (read-only).

Surfaces the operator's OWN historical SR averages - level / cs / teamfight /
kda - bucketed by role and game-time bracket, for the WP-A4 vertical
"You vs benchmark" stats panel. This is a DESCRIPTIVE personal-corpus lens (the
player's own baselines in, e.g., "mid lane, a 25-35 min game"), NOT a global /
meta / Riot / Claude number.

WHY NOT core.benchmarks: that module reads champion_benchmarks.json, which is
per-champion only and carries no role, no game-time bracket, and no kda - so it
cannot answer "role X at bracket Y". The grounded source that DOES carry all of
those is the rewind match corpus (data/rewind_history.db): the operator's
tracked participant row per match, joined to the match for duration + kp. See
docs/OVERLAY_BUILD_MASTER_PLAN.md WP-A4a + RC_WORK_TRACKER.md (the deviation
from the plan's named module is recorded there).

Operator identification needs NO puuid: each match row carries the tracked
(operator) champion + team, so the operator participant is the unique row with
that (champion_id, team_id) in that match - a clean per-match join.

The DB is gitignored (large, local-only). corpus_present() is False on a clean
checkout / CI, where role_bracket_grid() returns {} (an empty grid) rather than
raising - the route then renders an empty column, never an error.

Grid shape (nested, JSON-friendly):
  { <role>: { <bracket>: {
      "n": <int matches in the cell>,
      "lvl": {"avg": float, "p50": float, "n": int},
      "cs":  {"avg": float, "p50": float, "n": int},
      "tf":  {"avg": float, "p50": float, "n": int},
      "kda": {"avg": float, "p50": float, "n": int},
  } } }

Cached in-memory, invalidated on the DB file mtime (one scan per refresh).
"""
from __future__ import annotations

import sqlite3
import threading
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


def _bracket_for_duration(secs: float) -> str | None:
    try:
        s = float(secs)
    except (TypeError, ValueError):
        return None
    if s <= 0:
        return None
    if s < _BRACKET_EARLY_MAX_S:
        return "early"
    return "mid"


def normalize_role(raw: str) -> str | None:
    """Map a caller role string (canonical or alias) to a canonical key, or None
    if unrecognized. Case-insensitive."""
    if not raw:
        return None
    return ROLE_ALIASES.get(str(raw).strip().lower())


def corpus_present() -> bool:
    """True when the rewind corpus DB is on disk (False on a clean checkout /
    CI, where the grid is empty)."""
    return REWIND_DB_PATH.is_file()


class _GridCache:
    def __init__(self) -> None:
        self._grid: dict | None = None
        self._mtime: float = 0.0
        self._lock = threading.Lock()

    def get(self) -> dict:
        try:
            mtime = REWIND_DB_PATH.stat().st_mtime
        except FileNotFoundError:
            return {}
        with self._lock:
            if self._grid is None or mtime > self._mtime:
                self._grid = _build_grid()
                self._mtime = mtime
            return self._grid or {}

    def clear(self) -> None:
        with self._lock:
            self._grid = None
            self._mtime = 0.0


_cache = _GridCache()

# The operator (tracked) participant joined to the match. game_mode='CLASSIC' is
# Summoner's Rift (the stats panel scope); duration > 0 drops unfinished rows.
_QUERY = """
SELECT m.game_duration_s   AS dur,
       p.team_position     AS pos,
       p.champ_level       AS lvl,
       (COALESCE(p.total_minions_killed,0) + COALESCE(p.neutral_minions_killed,0)) AS cs,
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


def _build_grid() -> dict:
    """One read-only scan of the rewind corpus into the role x bracket grid.

    Read-only (mode=ro) so a concurrent RC-RewindCatchup writer never blocks or
    is blocked (the DB runs WAL on Windows). Any DB error -> {} (empty grid):
    the route degrades to an empty column, never a 500 from here."""
    if not REWIND_DB_PATH.is_file():
        return {}
    # accumulators: (role, bracket) -> {"lvl":[], "cs":[], "tf":[], "kda":[]}
    acc: dict[tuple[str, str], dict[str, list[float]]] = {}
    try:
        uri = f"file:{REWIND_DB_PATH.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            for dur, pos, lvl, cs, k, d, a, kp in conn.execute(_QUERY):
                role = _POSITION_ROLE.get((pos or "").strip().upper())
                bracket = _bracket_for_duration(dur)
                if role is None or bracket is None:
                    continue
                cell = acc.setdefault((role, bracket),
                                      {"lvl": [], "cs": [], "tf": [], "kda": []})
                if lvl is not None:
                    cell["lvl"].append(float(lvl))
                if cs is not None:
                    cell["cs"].append(float(cs))
                if kp is not None:
                    cell["tf"].append(float(kp))
                kk = float(k or 0)
                dd = float(d or 0)
                aa = float(a or 0)
                cell["kda"].append((kk + aa) / (dd if dd > 0 else 1.0))
        finally:
            conn.close()
    except sqlite3.Error:
        return {}

    grid: dict = {}
    for (role, bracket), lists in acc.items():
        n = max(len(lists["lvl"]), len(lists["cs"]),
                len(lists["tf"]), len(lists["kda"]))
        grid.setdefault(role, {})[bracket] = {
            "n": n,
            "lvl": _stat(lists["lvl"]),
            "cs": _stat(lists["cs"]),
            "tf": _stat(lists["tf"]),
            "kda": _stat(lists["kda"]),
        }
    return grid


def role_bracket_grid() -> dict:
    """Return the full role x bracket grid (mtime-cached). {} when the corpus is
    absent. Never raises - a DB error yields an empty grid."""
    return _cache.get()


def _reset_cache() -> None:
    """Test-only: drop the in-memory grid cache."""
    _cache.clear()
