"""
coaches/feedback.py - close the adaptation feedback loop.

After a match ends, performance_tracker assigns the user a grade
(S/A/B/C/D/F). This module translates that grade into a confidence
multiplier and applies it to the cache entry for the final coach state
of that match. Future cache hits for similar states are weighted by
past success.

Design rules:
- One-call API: `apply_grade(grade, last_state)`. Caller passes the
  last-known coach state (typically the SR coach's `_last_state`).
- Non-fatal: any error is logged at debug level and swallowed. Never
  crashes the rating-save path.
- Lazy import of `cache_engine` so this module is cheap to import even
  in environments where the cache DB doesn't exist yet.

Grade → multiplier table (chosen so a long S-streak quickly saturates
confidence at 1.0, while a B/C run is roughly stable):

    S  → 1.5  (capped at 1.0)
    A  → 1.2
    B  → 1.0  (no-op - neutral grade keeps things steady)
    C  → 0.95 (mild down-weight)
    D  → 0.8
    F  → flag_bad (existing path; halves confidence + records feedback row)

The multipliers are calibrated so:
- 3 consecutive A grades take a fresh 1.0 entry → still 1.0 (capped)
- 3 consecutive D grades take 1.0 → 0.512 (still cached, weighted down)
- 1 F grade takes 1.0 → 0.5 (matches existing flag_bad behavior)
- An S after a streak of D's recovers ~22% per win
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from modules.cache_engine import CacheEngine

_log = logging.getLogger("rc.coaches.feedback")

# Grade -> confidence multiplier. F is handled separately via flag_bad().
_GRADE_MULT = {
    "S": 1.5,
    "A": 1.2,
    "B": 1.0,
    "C": 0.95,
    "D": 0.8,
}


def apply_grade(grade: str, last_state: Optional[dict],
                cache: CacheEngine | None = None,
                db_path: Optional[str] = None) -> bool:
    """Apply post-match grade to the cache entry for `last_state`.

    `cache`     - optional CacheEngine instance (use existing handle from
                  the SR coach when available)
    `db_path`   - optional path to the cache DB; constructs a fresh
                  CacheEngine if `cache` not given

    Returns True if a cache update was attempted, False if skipped
    (missing state, unknown grade, or no cache available).
    """
    if not isinstance(last_state, dict) or not last_state:
        _log.debug("apply_grade: skipped (no last_state)")
        return False
    g = (grade or "").strip().upper()
    if g not in _GRADE_MULT and g != "F":
        _log.debug("apply_grade: skipped (unknown grade %r)", grade)
        return False

    if cache is None:
        try:
            from modules.cache_engine import CacheEngine
            from pathlib import Path
            if db_path is None:
                db_path = str(Path(__file__).resolve().parent.parent
                              / "data" / "decisions.db")
            cache = CacheEngine(db_path)
        except Exception as exc:
            _log.debug("apply_grade: cache init failed: %s", exc)
            return False

    try:
        if g == "F":
            cache.flag_bad(last_state)
            _log.info("feedback: grade F → flag_bad applied to last state")
        else:
            mult = _GRADE_MULT[g]
            if mult == 1.0:
                # B grade - explicitly skip the write (no-op multiplier)
                _log.debug("feedback: grade B (mult=1.0) → no-op")
                return True
            cache.bump_confidence(last_state, mult, flag=f"grade_{g}")
            _log.info("feedback: grade %s → confidence × %.2f applied", g, mult)
        return True
    except Exception as exc:
        _log.debug("apply_grade: cache update failed: %s", exc)
        return False
