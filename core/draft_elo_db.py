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

PERF: each query is a single SELECT against the participants table,
which is indexed on (champion_id, match_id) per the rewind extractor.
Queue id filter is parameterized. Total round-trip for a full 5+5
draft (5 solos + 10 ally pairs + 10 enemy pairs + 25 matchups = 50
queries) is ~50ms on the live ~29k-row participants table. Caller is
expected to cache the result; the route layer has a 5min TTL.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from core import smoothed_rates as _sr


_REWIND_DB = Path("data") / "rewind_history.db"

# Default queue set used by the draft Elo route (the SR ranked + draft
# + flex + quickplay queues). Caller can pass a different set per call.
DEFAULT_SR_QUEUES: tuple[int, ...] = (400, 420, 430, 440, 490)


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


def open_ro(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open the rewind_history db read-only. Returns a Connection.

    ``db_path`` defaults to ``_resolve_db_path()`` (honors RC_REWIND_DB).
    Read-only via uri=True + mode=ro so no concurrent writer is
    needed. Callers should close the connection; the route layer wraps
    in a try/finally.
    """
    if db_path is None:
        db_path = _resolve_db_path()
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True, isolation_level=None,
                           check_same_thread=False)


def _queue_placeholders(qids: Iterable[int]) -> tuple[str, list[int]]:
    """Build a parameterized IN-list. Returns (sql_fragment, params)."""
    qids = list(qids)
    if not qids:
        return ("", [])
    return (",".join("?" for _ in qids), qids)


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
    qids = queue_ids if queue_ids is not None else DEFAULT_SR_QUEUES
    in_frag, params = _queue_placeholders(qids)
    sql = (
        "SELECT COALESCE(SUM(p.win), 0) AS wins, COUNT(*) AS games "
        "FROM participants p "
        "JOIN matches m ON m.match_id = p.match_id "
        "WHERE p.champion_id = ?"
    )
    args: list = [int(champion_id)]
    if in_frag:
        sql += f" AND m.queue_id IN ({in_frag})"
        args.extend(params)
    row = conn.execute(sql, args).fetchone()
    if not row:
        return (0, 0, 0.5)
    wins, games = int(row[0]), int(row[1])
    return (wins, games, _sr.laplace_rate(wins, games))


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
    """
    qids = queue_ids if queue_ids is not None else DEFAULT_SR_QUEUES
    in_frag, params = _queue_placeholders(qids)
    args: list = [int(champ_a), int(champ_b)]
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
        f"AND {side_clause}"
    )
    if in_frag:
        sql += f" AND m.queue_id IN ({in_frag})"
        args.extend(params)
    row = conn.execute(sql, args).fetchone()
    if not row:
        return (0, 0, 0.5)
    wins, games = int(row[0]), int(row[1])
    return (wins, games, _sr.laplace_rate(wins, games))


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
