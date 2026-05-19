"""Coach-facing read API for Agent 4's adaptation aggregates.

Opt-in helper - existing coaches stay unchanged unless they explicitly
import this module. That preserves the "coach Python is propose-and-
queue" charter rule: wiring this into ``_base_coach.py`` or any
mode-specific coach is a future proposal, not this round's work.

Typical use:

    from coaches.adaptation_hint import format_hint_line

    hint = format_hint_line(champion="Ahri", mode="aram",
                            enemies=["Xerath", "Jinx", "Garen"])
    # hint is either "" or a short prose line like:
    #   "Ahri ARAM baseline 54% wr (n=61). Enemy Xerath flags: +46% "
    #   "(strongest counter of active matchups)."

Contracts:
  * Never raises in the happy path - missing DB, missing bucket, missing
    matchup all return empty / None. Coaches call this from a hot path
    and can't tolerate exceptions.
  * Read-only. Agent 4 owns the writes.

Module layout (AUTONOMOUS_AUDIT spec 4.C, 2026-05-18): the former
1602-line monolith was split by concern into sibling modules -
``_adaptation_common`` (shared DB-path / mode-set / threshold internals
+ the ``_db`` resolver + ``_start_of_today_iso``),
``adaptation_hint_champion`` (the coach hot-path),
``adaptation_hint_aggregates`` (leaderboard / KDA streaks),
``adaptation_hint_session`` (today's timeline),
``adaptation_hint_temporal`` (time / day / duration breakdowns),
``adaptation_hint_digest`` (the cross-dimension aggregator), and
``adaptation_hint_cli`` (CLI + text formatters). Every public and
semi-public name is re-exported below so every existing import site -
and the ``DB_DIR`` monkeypatch contract in the test suite (``_db``
resolves the directory off this module at call time) - keeps working
unchanged. Function bodies were extracted byte-verbatim; the
test_adaptation_hint + test_round* suites are the equivalence proof.
"""
from __future__ import annotations

from coaches._adaptation_common import (
    DB_DIR,
    SUPPORTED_MODES,
    _DEFAULT_TOP_COUNTERS,
    _MIN_ABSOLUTE_DELTA,
    _MIN_SAMPLE,
    _PROJECT_ROOT,
    _db,
    _start_of_today_iso,
    logger,
)
from coaches.adaptation_hint_aggregates import kda_trends, top_champions
from coaches.adaptation_hint_champion import (
    for_champion,
    format_hint_line,
    insight_card,
    matchup_delta,
)
from coaches.adaptation_hint_cli import (
    _SEVERITY_BAND,
    _format_day_of_week_text,
    _format_digest_text,
    _format_duration_text,
    _format_games_text,
    _format_session_text,
    _format_time_of_day_text,
    _format_trends_text,
    _parse_since,
    _severity_tag,
    main,
)
from coaches.adaptation_hint_digest import coaching_digest
from coaches.adaptation_hint_session import session_games, session_summary
from coaches.adaptation_hint_temporal import (
    _DURATION_TIERS,
    _WEEKDAY_NAMES,
    day_of_week_analysis,
    duration_analysis,
    time_of_day_analysis,
)

if __name__ == "__main__":
    raise SystemExit(main())
