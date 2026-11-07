"""
core/draft_elo_db.py - rewind_history.db queries for the draft Elo aggregator.

Companion to ``core.draft_elo`` (pure math). This module owns the
sqlite queries that turn the local match history into smoothed
win-rate priors per champ / per pair / per matchup. Composes on
``core.smoothed_rates`` (Laplace + shrink) per CLAUDE.md #90.

WHY rewind-history rather than aggregator D: the draft tool L (the community fork) triage
LOCKED rewind-history as the source-of-truth (aggregator D scrape is a
license dead-end). Sample sizes are smaller but the smoothing layer
absorbs that - a 5-game pair sample gets pulled hard toward 0.5 by
Laplace alpha=1 + shrink k=5.

Public API:

  solo_winrate(conn, champion_id, queue_ids) -> (wins, games, smoothed)
  pair_winrate(conn, c1, c2, queue_ids, side) -> (wins, games, smoothed)
      side in {"ally", "enemy"}. Ally pairs are same-team wins; enemy
      pairs use the OPPOSITE team's win flag (enemy pair "won" if their
      team won the game, which is OUR loss - the route layer inverts
      sense if needed).
  matchup_winrate(conn, ally_champ, enemy_champ, queue_ids) -> (wins, games, smoothed)
      Same-match cross-team pair. ``wins`` is the ALLY perspective
      (ally wins / total games where both champs appeared on opposing
      teams).

All three return the Laplace-smoothed rate (DEFAULT_ALPHA=1.0). Raw
win/game counts are returned alongside for caller transparency.

Input contract (true-audit S144-T-555): champion and queue ids are ints
(``operator.index``; a bool, float or str is a TypeError, so ``64.9`` no
longer reads champion 64 and ``"420"`` is no longer the queue set
{4, 2, 0}). ``queue_ids=None`` means DEFAULT_SR_QUEUES; an EMPTY
iterable is a ValueError, never "no filter" (it used to widen every
query to every queue, mixing ARAM / Arena / One for All rows into the
SR priors). At most MAX_QUEUE_IDS distinct queue ids. An id outside
SQLite's signed 64-bit range cannot be stored, so it reads as zero games
instead of raising OverflowError. ``side`` is "ally" or "enemy"; any
other value is a ValueError (it used to mean "enemy" silently).

A MIRROR (champ_a == champ_b on opposing teams) is counted from the
participant-row perspective: one match is two rows with exactly one
win, so it reads (n, 2n, 0.5).

Queue semantics: ``team_id`` is the 100 / 200 side. In subteam queues
(Arena 1700 / 1710 and similar) it is NOT the duo team, so pair and
matchup counts there have no draft meaning; the default SR set never
includes them.

PERF (measured 2026-11-06 on the live db, about 30k participant rows):
the plan searches ``matches`` by ``idx_matches_queue`` then
``participants`` by ``idx_participants_match``; there is NO index on
``participants.champion_id`` (only champion_name, match_id, puuid).
A pair query costs about 3.7 ms, so a full 5+5 draft (5 solos + 10 ally
pairs + 10 enemy pairs + 25 matchups = 50 queries) is about 0.2 s.
Callers cache the result; the route layer has a 5 min TTL.
"""
from __future__ import annotations

import operator
import os
import sqlite3
from pathlib import Path, PurePath
from typing import Iterable, Optional, Union

from core import smoothed_rates as _sr


# Anchored to the repo root, never the CWD (RM-1022).
_REWIND_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"

# Default queue set used by the draft Elo route (the SR ranked + draft
# + flex + quickplay queues). Caller can pass a different set per call.
DEFAULT_SR_QUEUES: tuple[int, ...] = (400, 420, 430, 440, 490)

# Most distinct queue ids one call may filter on. Riot has a few dozen
# live queues; the cap keeps a caller far below SQLite's bound-variable
# limit, which used to surface as a raw OperationalError.
MAX_QUEUE_IDS = 64

_SIDES = ("ally", "enemy")

# SQLite INTEGER is a signed 64-bit value; Python binds nothing wider.
_SQLITE_INT_MIN = -(2 ** 63)
_SQLITE_INT_MAX = 2 ** 63 - 1

# Returned when no row can match (an unstorable id): the same neutral
# answer an unknown champion gets from the query itself.
_NO_GAMES = (0, 0, 0.5)


def _resolve_db_path() -> Path:
    """Resolve the rewind DB path at CALL time.

    The ``RC_REWIND_DB`` env override lets tests point ``open_ro`` at a
    self-contained fixture (data/rewind_history.db is gitignored, so it
    is absent on a clean checkout / CI) and lets ops repoint the DB
    without a code edit. Resolving at call time - not as a def-time
    default arg - is what makes the override take effect.
    """
    env = os.environ.get("RC_REWIND_DB")
    return Path(env) if env else _REWIND_DB


def open_ro(db_path: Optional[Union[Path, str]] = None) -> sqlite3.Connection:
    """Open the rewind_history db read-only. Returns a Connection.

    ``db_path`` defaults to ``_resolve_db_path()`` (honors RC_REWIND_DB).
    Read-only via a ``file:`` URI with ``mode=ro``, so a missing file
    raises ``sqlite3.OperationalError`` and is never created. The path
    is made absolute and percent-encoded (``Path.as_uri``): pasting it
    raw let a ``#``, ``?`` or ``%xx`` in a directory name end or rewrite
    the URI path, which opened a DIFFERENT file. A UNC path still opens
    (``_ro_uri``).
    Callers close the
    connection; the route layer wraps it in a try/finally.
    """
    path = Path(db_path) if db_path is not None else _resolve_db_path()
    return sqlite3.connect(_ro_uri(path.resolve()), uri=True,
                           isolation_level=None, check_same_thread=False)


def _ro_uri(abs_path: PurePath) -> str:
    """The read-only ``file:`` URI for an ABSOLUTE path.

    ``as_uri`` percent-encodes the path. For a UNC path it puts the
    server in the URI authority (``file://server/share/...``), which
    SQLite refuses ("invalid uri authority"); an empty authority with a
    ``//server/share`` path (``file:////server/share/...``) opens the
    share, as the old raw-path URI did.
    """
    uri = abs_path.as_uri()
    if not uri.startswith("file:///"):
        uri = "file:////" + uri[len("file://"):]
    return uri + "?mode=ro"


def _as_int(value: object, what: str) -> int:
    """Return ``value`` as an int, or raise TypeError.

    ``operator.index`` accepts int and int-like types (``__index__``)
    and refuses float and str. bool is an int subclass but never an id.
    """
    if isinstance(value, bool):
        raise TypeError(f"{what} must be an int, not bool")
    try:
        return operator.index(value)
    except TypeError:
        raise TypeError(
            f"{what} must be an int, not {type(value).__name__}"
        ) from None


def _storable(value: int) -> bool:
    return _SQLITE_INT_MIN <= value <= _SQLITE_INT_MAX


def _queue_filter(queue_ids: Optional[Iterable[int]]) -> Optional[list[int]]:
    """Validate a queue filter; return the ids to bind, or None.

    None means DEFAULT_SR_QUEUES. An empty iterable is a ValueError: the
    old code dropped the IN clause for it, so the query counted EVERY
    queue. Duplicates collapse. Returns None when no id can be stored
    in SQLite, i.e. when the filter can match nothing.
    """
    if queue_ids is None:
        queue_ids = DEFAULT_SR_QUEUES
    if isinstance(queue_ids, (str, bytes, bytearray)):
        raise TypeError("queue_ids must be an iterable of ints, not text")
    try:
        items = iter(queue_ids)
    except TypeError:
        raise TypeError(
            f"queue_ids must be an iterable of ints, not "
            f"{type(queue_ids).__name__}"
        ) from None
    ids: list[int] = []
    seen: set[int] = set()
    for item in items:
        value = _as_int(item, "queue id")
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
        if len(ids) > MAX_QUEUE_IDS:
            raise ValueError(
                f"at most {MAX_QUEUE_IDS} distinct queue ids per query"
            )
    if not ids:
        raise ValueError(
            "queue_ids is empty; pass None for the default SR queue set"
        )
    bindable = [v for v in ids if _storable(v)]
    return bindable or None


def _placeholders(qids: list[int]) -> str:
    """A parameterized IN-list body for ``qids`` (never empty here)."""
    return ",".join("?" for _ in qids)


def _rate(row: Optional[tuple]) -> tuple[int, int, float]:
    """(wins, games, smoothed) from a ``SUM(win), COUNT(*)`` row."""
    if not row:
        return _NO_GAMES
    wins, games = int(row[0]), int(row[1])
    return (wins, games, _sr.laplace_rate(wins, games))


def solo_winrate(
    conn: sqlite3.Connection,
    champion_id: int,
    queue_ids: Optional[Iterable[int]] = None,
) -> tuple[int, int, float]:
    """Smoothed solo win rate for ``champion_id`` across queues.

    Counts every participant row for the champion across the requested
    queue set. ``wins`` is the raw count, ``games`` is the row count,
    and ``smoothed`` is the Laplace-smoothed rate from
    ``core.smoothed_rates.laplace_rate``.
    """
    champ = _as_int(champion_id, "champion_id")
    qids = _queue_filter(queue_ids)
    if qids is None or not _storable(champ):
        return _NO_GAMES
    sql = (
        "SELECT COALESCE(SUM(p.win), 0) AS wins, COUNT(*) AS games "
        "FROM participants p "
        "JOIN matches m ON m.match_id = p.match_id "
        "WHERE p.champion_id = ? "
        f"AND m.queue_id IN ({_placeholders(qids)})"
    )
    return _rate(conn.execute(sql, [champ, *qids]).fetchone())


def pair_winrate(
    conn: sqlite3.Connection,
    champ_a: int,
    champ_b: int,
    queue_ids: Optional[Iterable[int]] = None,
    side: str = "ally",
) -> tuple[int, int, float]:
    """Smoothed pair win rate for two champions.

    ``side="ally"`` -> same-team pair: count matches where both
    appeared on the SAME team. Wins = matches where THAT team won.

    ``side="enemy"`` -> opposing-team pair: count matches where both
    appeared on OPPOSING teams. Wins = matches where champ_a's team
    won (so the caller treats the rate as champ_a's perspective; for
    "enemy pair WR" the caller passes the actual enemy champs and
    inverts the sense at the call site).

    Any other ``side`` is a ValueError.
    """
    if not isinstance(side, str) or side not in _SIDES:
        raise ValueError('side must be "ally" or "enemy"')
    a = _as_int(champ_a, "champ_a")
    b = _as_int(champ_b, "champ_b")
    qids = _queue_filter(queue_ids)
    if qids is None or not (_storable(a) and _storable(b)):
        return _NO_GAMES
    side_clause = (
        "p1.team_id = p2.team_id"
        if side == "ally" else
        "p1.team_id <> p2.team_id"
    )
    sql = (
        "SELECT COALESCE(SUM(p1.win), 0) AS wins, COUNT(*) AS games "
        "FROM participants p1 "
        "JOIN participants p2 ON p2.match_id = p1.match_id "
        "AND p2.id <> p1.id "
        "JOIN matches m ON m.match_id = p1.match_id "
        "WHERE p1.champion_id = ? AND p2.champion_id = ? "
        f"AND {side_clause} "
        f"AND m.queue_id IN ({_placeholders(qids)})"
    )
    return _rate(conn.execute(sql, [a, b, *qids]).fetchone())


def matchup_winrate(
    conn: sqlite3.Connection,
    ally_champ: int,
    enemy_champ: int,
    queue_ids: Optional[Iterable[int]] = None,
) -> tuple[int, int, float]:
    """Smoothed lane matchup win rate.

    Cross-team pair query: count matches where ``ally_champ`` and
    ``enemy_champ`` appeared on OPPOSING teams. Wins is the count of
    games where ally_champ's team won.

    Lane filtering is intentionally NOT applied. The rewind history
    schema carries ``team_position`` per participant but matching by
    lane (ally TOP vs enemy TOP only) drops sample sizes below the
    smoothing threshold; the broader cross-team count is the trustable
    prior. Specific lane matchups can be added as a future tightening
    if sample density grows.
    """
    return pair_winrate(conn, ally_champ, enemy_champ, queue_ids, side="enemy")
