"""s170 - Pick & Ban Recommendations backend (item #4).

Provides GET /api/champ-select/pickban-recs?role=BOT[&queue=420] which
returns the "performance" row that the champ-select view's P&B panel
needs. Currently the panel (web/js/panels/champ_select.js:2060) renders
hardcoded `_PB_PLACEHOLDERS`; this endpoint replaces the performance
row with real per-champion WR + ban suggestions computed from
``data/rewind_history.db``.

Mastery + meta rows still drive off placeholders for now - mastery
needs LCU-side joining and meta needs a current-patch tier list source.
Listed as follow-on work in ROADMAP.

Query shape:
  role   : TOP | JUNGLE | MIDDLE | BOTTOM | UTILITY (LCU form)
           or  TOP | JNG | MID | BOT | SUP (dashboard form; auto-mapped)
  queue  : optional queue_id filter. Defaults to all SR queues
           (400 Normal Draft, 420 Ranked Solo/Duo, 430 Normal Blind,
            440 Ranked Flex, 490 Quickplay).

Response shape (matches the JS placeholder structure):
  {
    "ok": true,
    "role": "BOTTOM",
    "queue_ids": [400, 420, 430, 440, 490],
    "performance": {
      "champId": int, "champName": str,
      "games": int, "wins": int, "wr_pct": int,
      "reason": str   (e.g. "67% WR - 6 games - highest WR with >=3 games")
    } | None,
    "performance_bans": [
      {"champId": int, "name": str,
       "encounters": int, "losses": int, "pct": int}, ...   (up to 3)
    ]
  }
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import smoothed_rates as _sr

log = logging.getLogger("rc.web_dashboard")

_REWIND_DB = Path("data") / "rewind_history.db"
_COUNTERS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "champion_counters.json"
_DDRAGON_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"

# Module-level lazy index. Re-built on first call after a process
# restart; operator-edited JSON picks up on next restart_trigger.
_COUNTERS_INDEX: dict | None = None
_CHAMP_NAME_TO_ID: dict[str, int] | None = None
_CHAMP_ID_TO_NAME: dict[int, str] | None = None


def _norm_name(name: str) -> str:
    """Case-insensitive + punctuation-stripped key for tolerant lookup.
    Bridges the gap between display names ("Kai'Sa") and DDragon slug
    forms ("Kaisa") the DB stores. Both normalise to "kaisa"."""
    import re
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _load_counters_index() -> dict:
    """Returns `{normalized_name: [counter_name, ...]}`. Normalisation
    via `_norm_name` so Kai'Sa / KaiSa / Kaisa all collide cleanly."""
    global _COUNTERS_INDEX
    if _COUNTERS_INDEX is not None:
        return _COUNTERS_INDEX
    out: dict = {}
    try:
        raw = json.loads(_COUNTERS_PATH.read_text(encoding="utf-8"))
        for k, v in (raw.get("counters") or {}).items():
            if not isinstance(v, list):
                continue
            out[_norm_name(k)] = list(v)
    except Exception as exc:
        log.debug("pickban: counters load failed: %s", exc)
    _COUNTERS_INDEX = out
    return out


def _load_champ_name_to_id() -> dict[str, int]:
    """Normalized name -> numeric id. Keys via `_norm_name` so any case +
    spacing variant resolves cleanly."""
    global _CHAMP_NAME_TO_ID
    if _CHAMP_NAME_TO_ID is not None:
        return _CHAMP_NAME_TO_ID
    out: dict[str, int] = {}
    try:
        raw = json.loads(_DDRAGON_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            slug = entry.get("id")
            key = entry.get("key")
            if not (key and name):
                continue
            try:
                cid = int(key)
            except (TypeError, ValueError):
                continue
            for variant in (name, slug):
                if variant:
                    out[_norm_name(variant)] = cid
    except Exception as exc:
        log.debug("pickban: champ name->id load failed: %s", exc)
    _CHAMP_NAME_TO_ID = out
    return out


def _load_champ_id_to_name() -> dict[int, str]:
    global _CHAMP_ID_TO_NAME
    if _CHAMP_ID_TO_NAME is not None:
        return _CHAMP_ID_TO_NAME
    out: dict[int, str] = {}
    try:
        raw = json.loads(_DDRAGON_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for entry in data.values():
            if isinstance(entry, dict) and entry.get("key") and entry.get("name"):
                try:
                    out[int(entry["key"])] = str(entry["name"])
                except (TypeError, ValueError):
                    continue
    except Exception as exc:
        log.debug("pickban: champ id->name load failed: %s", exc)
    _CHAMP_ID_TO_NAME = out
    return out


def _counters_for_champion(name: str) -> list[dict]:
    """Resolve hardcoded counters -> list of {champId, name, pct} dicts.
    `pct` is a static "high counter pressure" value (75) - we don't have
    win-rate data to drive it yet."""
    if not name:
        return []
    counters_idx = _load_counters_index()
    name_to_id = _load_champ_name_to_id()
    raw_list = counters_idx.get(_norm_name(name))
    if not raw_list:
        return []
    out: list[dict] = []
    for counter_name in raw_list[:3]:
        cid = name_to_id.get(_norm_name(counter_name))
        if cid:
            out.append({
                "champId": int(cid),
                "name":    str(counter_name),
                "pct":     75,
            })
    return out

# Role normalization. Front-end uses TOP/JNG/MID/BOT/SUP; LCU uses
# TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY; the DB stores LCU form. Accept
# both at the endpoint boundary and translate to LCU form for the query.
_ROLE_ALIASES: dict[str, str] = {
    "TOP": "TOP",
    "JNG": "JUNGLE", "JUNGLE": "JUNGLE",
    "MID": "MIDDLE", "MIDDLE": "MIDDLE",
    "BOT": "BOTTOM", "BOTTOM": "BOTTOM", "ADC": "BOTTOM",
    "SUP": "UTILITY", "SUPP": "UTILITY", "UTILITY": "UTILITY", "SUPPORT": "UTILITY",
}

# Default queue set when no ?queue= filter is given. All SR draft +
# ranked + Quickplay. Excludes ARAM/Arena/Coop because P&B is
# SR-only (no bans in those modes anyway).
_DEFAULT_SR_QUEUES = (400, 420, 430, 440, 490)

# Minimum games threshold. Below this the WR isn't statistically
# meaningful; we skip the performance row rather than recommend a
# 100%-WR 1-game champion.
_MIN_GAMES_PICK = 3
_MIN_GAMES_BAN  = 2

# s209: mood-aware re-ranking modes. The champ-select panel has a 4-button
# mood toggle that pre-s209 just persisted to sessionStorage with no
# downstream effect. Each mood reshapes the `performance` query:
#
#   comfort - operator's highest-WR pick at this role (>=3 games). Default.
#             "Safe pick - proven track record".
#   limit   - operator's highest-WR pick within the 1-5 games band. Hits
#             the "I've tried this a few times and it's working" sweet
#             spot - a champ they can develop toward mastery.
#   new     - most-popular role champion the operator has never played
#             in this role. Operator-never-played + cross-pool popular.
#   synergy - operator's highest-WR pick at this role limited to matches
#             from the last 60 days. Proxy for "what's working RIGHT NOW";
#             true team-comp synergy needs ally-locked context which the
#             endpoint doesn't yet receive.
#
# Bans are unchanged per mood - what threatens the operator at this role
# is mood-independent.
_VALID_MOODS = frozenset({"comfort", "limit", "new", "synergy"})
_MOOD_DEFAULT = "comfort"

# Sliding window for "synergy" (recent form). 60 days picks up the last
# patch + a buffer for irregular play schedules.
_SYNERGY_WINDOW_DAYS = 60

# Limit Test sample-size band - narrow enough to exclude mains, wide
# enough to surface signal beyond a single coin-flip game.
_LIMIT_GAMES_MIN = 1
_LIMIT_GAMES_MAX = 5


def _resolve_operator_puuid(conn: sqlite3.Connection) -> str | None:
    """The operator is the puuid that appears in the most matches in
    rewind_history.db. Resolving from the DB rather than configuration
    keeps the endpoint self-contained - no env var, no cross-module
    dependency on ``core.riot_api``.
    """
    # ``puuid`` is the stable tertiary so a COUNT(*) tie resolves the
    # same way every call (otherwise SQLite ORDER BY ties are undefined
    # and "who is the operator" - hence every downstream rec - could
    # flip between requests).
    cur = conn.execute(
        "SELECT puuid FROM participants "
        "GROUP BY puuid "
        "ORDER BY COUNT(*) DESC, puuid ASC LIMIT 1"
    )
    row = cur.fetchone()
    return row[0] if row else None


def _normalize_role(raw: str) -> str | None:
    return _ROLE_ALIASES.get((raw or "").upper())


# --------------------------------------------------------------------
# s214: query helpers refactored to return LISTS of picks instead of
# single dicts, so the LIMIT / NEW / SYNERGY moods can populate all 3
# panel rows with cascade-filtered same-mood picks. Each query takes
# ``exclude_ids`` so the caller can pass already-banned + already-picked
# + already-shown ids to skip; SQL builds a NOT IN clause when present.
# Each query takes ``top`` for the result list length (default 1 for
# back-compat with the single-row endpoint shape).
# --------------------------------------------------------------------


def _exclude_clause(exclude_ids: tuple[int, ...]) -> tuple[str, tuple[int, ...]]:
    """Returns (sql_fragment, params). When exclude_ids is empty we emit
    a no-op fragment (`AND 1=1`) so the f-string concatenation stays
    grammatical regardless of operator filter state."""
    if not exclude_ids:
        return ("AND 1=1", ())
    placeholders = ",".join("?" * len(exclude_ids))
    return (f"AND champion_id NOT IN ({placeholders})", exclude_ids)


def _query_performance_comfort(conn: sqlite3.Connection, puuid: str, role: str,
                               queue_ids: tuple[int, ...],
                               exclude_ids: tuple[int, ...] = (),
                               top: int = 1) -> list[dict]:
    """Operator's top-N highest-WR champions at this role with
    >=_MIN_GAMES_PICK games. Ties broken by higher game count (more
    reliable signal). ``exclude_ids`` skips banned + already-shown ids."""
    placeholders = ",".join("?" * len(queue_ids))
    excl_sql, excl_params = _exclude_clause(exclude_ids)
    cur = conn.execute(
        f"""
        SELECT champion_id, champion_name,
               COUNT(*) AS games,
               SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) AS wins
        FROM participants
        WHERE puuid = ?
          AND team_position = ?
          AND match_id IN (
            SELECT match_id FROM matches WHERE queue_id IN ({placeholders})
          )
          {excl_sql}
        GROUP BY champion_id
        HAVING games >= ?
        ORDER BY (CAST(wins AS REAL) / games) DESC, games DESC, champion_id ASC
        LIMIT ?
        """,
        (puuid, role, *queue_ids, *excl_params, _MIN_GAMES_PICK, top),
    )
    out: list[dict] = []
    for champ_id, champ_name, games, wins in cur.fetchall():
        wr_pct = int(round(100 * wins / games)) if games else 0
        out.append({
            "champId":   int(champ_id),
            "champName": str(champ_name or "?"),
            "games":     int(games),
            "wins":      int(wins),
            "wr_pct":    wr_pct,
            "reason":    f"{wr_pct}% WR - {games} games - safe pick",
        })
    return out


def _query_performance_limit(conn: sqlite3.Connection, puuid: str, role: str,
                             queue_ids: tuple[int, ...],
                             exclude_ids: tuple[int, ...] = (),
                             top: int = 1) -> list[dict]:
    """Operator's best champions in the 1-5 games "developing" band -
    enough plays to show signal but not enough to be a true main. The
    intent is "push your range" - surface champs you're trending up on.
    """
    placeholders = ",".join("?" * len(queue_ids))
    excl_sql, excl_params = _exclude_clause(exclude_ids)
    cur = conn.execute(
        f"""
        SELECT champion_id, champion_name,
               COUNT(*) AS games,
               SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) AS wins
        FROM participants
        WHERE puuid = ?
          AND team_position = ?
          AND match_id IN (
            SELECT match_id FROM matches WHERE queue_id IN ({placeholders})
          )
          {excl_sql}
        GROUP BY champion_id
        HAVING games BETWEEN ? AND ?
        ORDER BY (CAST(wins AS REAL) / games) DESC, games DESC, champion_id ASC
        LIMIT ?
        """,
        (puuid, role, *queue_ids, *excl_params,
         _LIMIT_GAMES_MIN, _LIMIT_GAMES_MAX, top),
    )
    out: list[dict] = []
    for champ_id, champ_name, games, wins in cur.fetchall():
        wr_pct = int(round(100 * wins / games)) if games else 0
        out.append({
            "champId":   int(champ_id),
            "champName": str(champ_name or "?"),
            "games":     int(games),
            "wins":      int(wins),
            "wr_pct":    wr_pct,
            "reason":    f"{wr_pct}% WR - {games} games - growth pick (small sample)",
        })
    return out


def _query_performance_new(conn: sqlite3.Connection, puuid: str, role: str,
                           queue_ids: tuple[int, ...],
                           exclude_ids: tuple[int, ...] = (),
                           top: int = 1) -> list[dict]:
    """Top-N most-played champions at this role across the DB that the
    operator has NEVER played in this role. Cross-pool popularity is a
    rough proxy for meta tier when no live tier-list source is wired.
    """
    placeholders = ",".join("?" * len(queue_ids))
    excl_sql, excl_params = _exclude_clause(exclude_ids)
    cur = conn.execute(
        f"""
        SELECT champion_id, champion_name, COUNT(*) AS pool_games
        FROM participants
        WHERE team_position = ?
          AND match_id IN (
            SELECT match_id FROM matches WHERE queue_id IN ({placeholders})
          )
          AND champion_id NOT IN (
            SELECT champion_id FROM participants
            WHERE puuid = ? AND team_position = ?
          )
          {excl_sql}
        GROUP BY champion_id
        ORDER BY pool_games DESC, champion_id ASC
        LIMIT ?
        """,
        (role, *queue_ids, puuid, role, *excl_params, top),
    )
    out: list[dict] = []
    for champ_id, champ_name, pool_games in cur.fetchall():
        out.append({
            "champId":   int(champ_id),
            "champName": str(champ_name or "?"),
            "games":     0,
            "wins":      0,
            "wr_pct":    0,
            "reason":    f"never played in role - {pool_games} games in the pool - try them",
        })
    return out


# s238 (CLAUDE.md #90): the synergy mood was the locked example of
# "pick/ban synergy - today only a raw recent-form proxy". It now ranks
# by the shared Laplace/Beta-smoothed primitive instead of raw
# wins/games, so a 2-0 record no longer outranks a proven 14-8 one. The
# displayed `wr_pct` stays the RAW observed rate (what the operator sees,
# "100% WR"); only the ranking key is smoothed. The `HAVING games >= 2`
# hard floor in the SQL is kept - smoothing softens small-n bias, the
# floor still excludes single-game flukes outright.
def _rank_by_smoothed_wr(raw_rows, reason_suffix: str, top: int) -> list[dict]:
    """(champion_id, champion_name, games, wins) tuples -> ranked row
    dicts (same shape every mood emits). Primary sort = smoothed WR via
    ``core.smoothed_rates.laplace_rate``; secondary = more games (more
    trust); tertiary = champion_id (stable)."""
    scored: list[tuple[float, int, int, dict]] = []
    for champ_id, champ_name, games, wins in raw_rows:
        games = int(games)
        wins = int(wins)
        wr_pct = int(round(100 * wins / games)) if games else 0
        smoothed = _sr.laplace_rate(wins, games)
        scored.append((
            smoothed, games, int(champ_id),
            {
                "champId":   int(champ_id),
                "champName": str(champ_name or "?"),
                "games":     games,
                "wins":      wins,
                "wr_pct":    wr_pct,
                "reason":    f"{wr_pct}% WR - {games} games {reason_suffix}",
            },
        ))
    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    return [d for _, _, _, d in scored[:max(1, top)]]


def _query_performance_synergy(conn: sqlite3.Connection, puuid: str, role: str,
                               queue_ids: tuple[int, ...],
                               exclude_ids: tuple[int, ...] = (),
                               top: int = 1,
                               ally_ids: tuple[int, ...] = ()) -> list[dict]:
    """Operator's highest-WR champion at this role limited to recent
    matches OR - when ``ally_ids`` is provided - joint-WR-with-allies
    scoring across the operator's full history.

    Pre-s214 this mode was just "recent form" (60-day window proxy). The
    new path: when the panel passes the operator's locked allies via
    ``allies=cid,cid,...``, we score each candidate by how often the
    operator won games where they played that candidate AND at least one
    of the locked allies was on their team. ``games_with_allies>=2``
    threshold filters out single-game flukes.

    Falls back to the recent-form proxy when ``ally_ids`` is empty (early
    CS before any ally locks in).
    """
    placeholders = ",".join("?" * len(queue_ids))
    excl_sql, excl_params = _exclude_clause(exclude_ids)
    if ally_ids:
        # Joint-with-allies path: count matches where operator played
        # `champion_id` at `role` AND any teammate's champion_id is in
        # ally_ids on the SAME team. Group by candidate; rank by WR.
        ally_placeholders = ",".join("?" * len(ally_ids))
        cur = conn.execute(
            f"""
            SELECT op.champion_id, op.champion_name,
                   COUNT(DISTINCT op.match_id) AS games,
                   SUM(CASE WHEN op.win=1 THEN 1 ELSE 0 END) AS wins
            FROM participants op
            WHERE op.puuid = ?
              AND op.team_position = ?
              AND op.match_id IN (
                SELECT match_id FROM matches WHERE queue_id IN ({placeholders})
              )
              {excl_sql.replace("champion_id", "op.champion_id")}
              AND EXISTS (
                SELECT 1 FROM participants ally
                WHERE ally.match_id = op.match_id
                  AND ally.team_id = op.team_id
                  AND ally.puuid != op.puuid
                  AND ally.champion_id IN ({ally_placeholders})
              )
            GROUP BY op.champion_id
            HAVING games >= 2
            """,
            (puuid, role, *queue_ids, *excl_params, *ally_ids),
        )
        # s238: smoothed re-rank in Python via the shared primitive
        # (replaces the SQL `ORDER BY raw-WR ... LIMIT`).
        return _rank_by_smoothed_wr(
            cur.fetchall(),
            "alongside locked allies - comp fit (smoothed)", top,
        )
    # Recent-form fallback (pre-s214 behavior, kept for empty-allies path).
    cutoff_ms = int((time.time() - _SYNERGY_WINDOW_DAYS * 86400) * 1000)
    cur = conn.execute(
        f"""
        SELECT p.champion_id, p.champion_name,
               COUNT(*) AS games,
               SUM(CASE WHEN p.win=1 THEN 1 ELSE 0 END) AS wins
        FROM participants p
        JOIN matches m ON m.match_id = p.match_id
        WHERE p.puuid = ?
          AND p.team_position = ?
          AND m.queue_id IN ({placeholders})
          AND m.game_creation_ts >= ?
          {excl_sql.replace("champion_id", "p.champion_id")}
        GROUP BY p.champion_id
        HAVING games >= 2
        """,
        (puuid, role, *queue_ids, cutoff_ms, *excl_params),
    )
    # s238: smoothed re-rank in Python via the shared primitive.
    return _rank_by_smoothed_wr(
        cur.fetchall(),
        f"last {_SYNERGY_WINDOW_DAYS}d - recent form (smoothed)", top,
    )


# Mood -> query dispatcher. Unknown moods fall through to comfort.
_PERFORMANCE_QUERIES = {
    "comfort": _query_performance_comfort,
    "limit":   _query_performance_limit,
    "new":     _query_performance_new,
    "synergy": _query_performance_synergy,
}


def _query_performance(conn: sqlite3.Connection, puuid: str, role: str,
                       queue_ids: tuple[int, ...],
                       mood: str = _MOOD_DEFAULT,
                       exclude_ids: tuple[int, ...] = (),
                       top: int = 1,
                       ally_ids: tuple[int, ...] = ()) -> list[dict]:
    """Mood-aware dispatcher returning a LIST (s214) of up to ``top``
    picks for the requested mood, with ``exclude_ids`` cascade-filtering
    out banned + already-picked + already-shown ids. Falls back to
    comfort when the operator's history is too thin to satisfy the
    selected mood (e.g. no 1-5 games band for `limit`, no recent matches
    for `synergy`). When the fallback fires, every result is tagged
    `fell_back=true` + `requested_mood=<mood>` so the UI can surface
    "no <mood> data - defaulting to comfort"."""
    fn = _PERFORMANCE_QUERIES.get(mood, _query_performance_comfort)
    if fn is _query_performance_synergy:
        result = fn(conn, puuid, role, queue_ids, exclude_ids, top, ally_ids)
    else:
        result = fn(conn, puuid, role, queue_ids, exclude_ids, top)
    if not result and mood != _MOOD_DEFAULT:
        result = _query_performance_comfort(conn, puuid, role, queue_ids, exclude_ids, top)
        for row in result:
            row["fell_back"] = True
            row["requested_mood"] = mood
    return result


def _query_bans(conn: sqlite3.Connection, puuid: str, role: str,
                queue_ids: tuple[int, ...]) -> list[dict]:
    """Top 3 enemy champions in same role the operator has lost to most
    often. Filters to encounters with at least ``_MIN_GAMES_BAN`` games
    so a single loss to a one-trick doesn't recommend the ban.

    Self-join on matches: tracked = operator's row, enemy = the role
    counterpart on the opposing team_id.
    """
    placeholders = ",".join("?" * len(queue_ids))
    cur = conn.execute(
        f"""
        SELECT enemy.champion_id, enemy.champion_name,
               COUNT(*) AS encounters,
               SUM(CASE WHEN tracked.win=0 THEN 1 ELSE 0 END) AS losses
        FROM participants tracked
        JOIN participants enemy
          ON enemy.match_id = tracked.match_id
         AND enemy.team_id != tracked.team_id
         AND enemy.team_position = tracked.team_position
        WHERE tracked.puuid = ?
          AND tracked.team_position = ?
          AND tracked.match_id IN (
            SELECT match_id FROM matches WHERE queue_id IN ({placeholders})
          )
        GROUP BY enemy.champion_id
        HAVING encounters >= ?
        ORDER BY (CAST(losses AS REAL) / encounters) DESC, encounters DESC,
                 enemy.champion_id ASC
        LIMIT 3
        """,
        (puuid, role, *queue_ids, _MIN_GAMES_BAN),
    )
    out: list[dict] = []
    for champ_id, champ_name, encounters, losses in cur.fetchall():
        if not encounters:
            continue
        pct = int(round(100 * losses / encounters))
        # Only surface matchups where operator actually loses more than
        # half the time - sub-50% loss rate isn't a ban-worthy threat.
        if pct < 50:
            continue
        out.append({
            "champId":     int(champ_id),
            "name":        str(champ_name or "?"),
            "encounters":  int(encounters),
            "losses":      int(losses),
            "pct":         pct,
        })
    return out


# --------------------------------------------------------------------
# s239 (AUTONOMOUS_AUDIT opportunity #2): the per-user CONTEXTUAL read.
# The mood queries above RECOMMEND picks; these REPORT the operator's
# actual personal record against the champions already on the board in
# the current draft - "your WR with/against", the differentiator no
# cohort-averaged SaaS can do per-user.
#
# Design assumptions (stated per the project hard rule):
#   A1  "vs enemy"  = that champ ANYWHERE on the opposing team, not
#                     lane-strict (CS doesn't know final lanes; broader
#                     = more games on a stale DB). _query_bans stays
#                     lane-strict for *recommendations* by design.
#   A2  "with ally" = that ally champ on the operator's team regardless
#                     of what the operator played (conditioning on the
#                     operator's champ would shred sample size).
#   A4  displayed wr_pct = RAW observed rate (s238 invariant - this
#                     REPORTS history, it does not RANK, so no smoothing).
#   A5  zero-game entries are still returned (games:0) so the UI can
#                     surface "first time vs/with X" - a real draft signal.
#   A7  ALL-TIME history (no recency window) - so it has live data
#                     despite rewind_history.db recency staleness;
#                     lifetime head-to-head is the meaningful per-user
#                     signal and is recency-independent by design.
# --------------------------------------------------------------------


def _query_champ_record(conn: sqlite3.Connection, puuid: str, champ_id: int,
                         queue_ids: tuple[int, ...],
                         role: str | None = None) -> dict | None:
    """Operator's lifetime record ON ``champ_id``: all-roles headline
    plus an at-role qualifier when ``role`` (LCU form) is supplied.
    Returns None when the operator has never played the champion (so the
    UI can show a clean "no history" instead of a 0/0)."""
    placeholders = ",".join("?" * len(queue_ids))
    name, games, wins = conn.execute(
        f"""
        SELECT champion_name,
               COUNT(*) AS games,
               SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) AS wins
        FROM participants
        WHERE puuid = ?
          AND champion_id = ?
          AND match_id IN (
            SELECT match_id FROM matches WHERE queue_id IN ({placeholders})
          )
        """,
        (puuid, champ_id, *queue_ids),
    ).fetchone()
    games = int(games or 0)
    wins = int(wins or 0)
    if games == 0:
        return None
    champ_name = name or _load_champ_id_to_name().get(int(champ_id)) or "?"
    out: dict = {
        "champId":     int(champ_id),
        "champName":   str(champ_name),
        "games":       games,
        "wins":        wins,
        "wr_pct":      int(round(100 * wins / games)),
        "role":        None,
        "role_games":  None,
        "role_wins":   None,
        "role_wr_pct": None,
    }
    if role:
        rg, rw = conn.execute(
            f"""
            SELECT COUNT(*) AS games,
                   SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) AS wins
            FROM participants
            WHERE puuid = ?
              AND champion_id = ?
              AND team_position = ?
              AND match_id IN (
                SELECT match_id FROM matches WHERE queue_id IN ({placeholders})
              )
            """,
            (puuid, champ_id, role, *queue_ids),
        ).fetchone()
        rg = int(rg or 0)
        rw = int(rw or 0)
        out["role"] = role
        out["role_games"] = rg
        out["role_wins"] = rw
        out["role_wr_pct"] = int(round(100 * rw / rg)) if rg else None
    return out


def _query_with_ally(conn: sqlite3.Connection, puuid: str, ally_id: int,
                      queue_ids: tuple[int, ...]) -> dict:
    """Operator's lifetime record in matches where ``ally_id`` was on
    their team (A2 - independent of what the operator played). Always
    returns an entry; ``games`` may be 0 (A5)."""
    placeholders = ",".join("?" * len(queue_ids))
    name, games, wins = conn.execute(
        f"""
        SELECT
          (SELECT champion_name FROM participants
             WHERE champion_id = ? LIMIT 1) AS champ_name,
          COUNT(*) AS games,
          SUM(CASE WHEN op.win=1 THEN 1 ELSE 0 END) AS wins
        FROM participants op
        WHERE op.puuid = ?
          AND op.match_id IN (
            SELECT match_id FROM matches WHERE queue_id IN ({placeholders})
          )
          AND EXISTS (
            SELECT 1 FROM participants a
            WHERE a.match_id = op.match_id
              AND a.team_id = op.team_id
              AND a.puuid != op.puuid
              AND a.champion_id = ?
          )
        """,
        (ally_id, puuid, *queue_ids, ally_id),
    ).fetchone()
    games = int(games or 0)
    wins = int(wins or 0)
    champ_name = name or _load_champ_id_to_name().get(int(ally_id)) or "?"
    return {
        "champId":   int(ally_id),
        "champName": str(champ_name),
        "games":     games,
        "wins":      wins,
        "wr_pct":    int(round(100 * wins / games)) if games else 0,
    }


def _query_vs_enemy(conn: sqlite3.Connection, puuid: str, enemy_id: int,
                    queue_ids: tuple[int, ...]) -> dict:
    """Operator's lifetime record in matches where ``enemy_id`` was on
    the OPPOSING team, any lane (A1). Always returns an entry; ``games``
    may be 0 (A5). Carries ``losses`` since the ban-side framing is
    "how often does this champ beat me"."""
    placeholders = ",".join("?" * len(queue_ids))
    name, games, wins = conn.execute(
        f"""
        SELECT
          (SELECT champion_name FROM participants
             WHERE champion_id = ? LIMIT 1) AS champ_name,
          COUNT(*) AS games,
          SUM(CASE WHEN op.win=1 THEN 1 ELSE 0 END) AS wins
        FROM participants op
        WHERE op.puuid = ?
          AND op.match_id IN (
            SELECT match_id FROM matches WHERE queue_id IN ({placeholders})
          )
          AND EXISTS (
            SELECT 1 FROM participants e
            WHERE e.match_id = op.match_id
              AND e.team_id != op.team_id
              AND e.champion_id = ?
          )
        """,
        (enemy_id, puuid, *queue_ids, enemy_id),
    ).fetchone()
    games = int(games or 0)
    wins = int(wins or 0)
    champ_name = name or _load_champ_id_to_name().get(int(enemy_id)) or "?"
    return {
        "champId":   int(enemy_id),
        "champName": str(champ_name),
        "games":     games,
        "wins":      wins,
        "losses":    games - wins,
        "wr_pct":    int(round(100 * wins / games)) if games else 0,
    }


def _parse_csv_ints(raw: str) -> tuple[int, ...]:
    """Parse "1,2,3" -> (1,2,3). Silently drops blanks + non-int tokens
    so a malformed param doesn't 400 the whole endpoint."""
    if not raw:
        return ()
    out: list[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return tuple(out)


def _serve_pickban_recs(h) -> None:
    try:
        qs = parse_qs(urlparse(h.path).query)
        role_raw = (qs.get("role") or [""])[0]
        role = _normalize_role(role_raw)
        if not role:
            h._send(400,
                    json.dumps({"ok": False, "error": "role required (TOP|JUNGLE|MIDDLE|BOTTOM|UTILITY)"}).encode(),
                    "application/json")
            return

        # Queue filter: ?queue=420 -> (420,); ?queue=400,420 -> (400, 420);
        # omitted -> default SR queue set.
        queue_raw = (qs.get("queue") or [""])[0]
        if queue_raw:
            try:
                queue_ids = tuple(int(x) for x in queue_raw.split(",") if x.strip())
            except ValueError:
                h._send(400,
                        json.dumps({"ok": False, "error": "queue must be comma-separated ints"}).encode(),
                        "application/json")
                return
            if not queue_ids:
                queue_ids = _DEFAULT_SR_QUEUES
        else:
            queue_ids = _DEFAULT_SR_QUEUES

        # s209: mood param re-weights the performance row. Unknown moods
        # fall through to comfort; the dispatcher itself handles thin-data
        # fallback for limit / new / synergy.
        mood_raw = (qs.get("mood") or [""])[0].lower().strip()
        mood = mood_raw if mood_raw in _VALID_MOODS else _MOOD_DEFAULT

        # s214: cascade-filter inputs. `exclude` = banned/picked/already-shown
        # ids to skip; `allies` = locked teammate champion ids (used by the
        # synergy mood for joint-WR scoring); `top` = number of picks to
        # return (1..5 clamped). Callers stick to top=1 for the legacy
        # `comfort` row and top=3 for LIMIT/NEW/SYNERGY rows 1+2+3.
        exclude_ids = _parse_csv_ints((qs.get("exclude") or [""])[0])
        ally_ids    = _parse_csv_ints((qs.get("allies")  or [""])[0])
        try:
            top_raw = int((qs.get("top") or ["1"])[0])
        except ValueError:
            top_raw = 1
        top = max(1, min(5, top_raw))

        if not _REWIND_DB.exists():
            h._send(503,
                    json.dumps({"ok": False, "error": "rewind_history.db missing"}).encode(),
                    "application/json")
            return

        t0 = time.time()
        # read-only connection; the catchup script is the only writer and
        # WAL mode means reads don't block its writes.
        conn = sqlite3.connect(f"file:{_REWIND_DB}?mode=ro", uri=True, timeout=2.0)
        try:
            puuid = _resolve_operator_puuid(conn)
            if not puuid:
                h._send(503,
                        json.dumps({"ok": False, "error": "no operator puuid in rewind_history.db"}).encode(),
                        "application/json")
                return
            picks = _query_performance(conn, puuid, role, queue_ids, mood,
                                       exclude_ids=exclude_ids, top=top,
                                       ally_ids=ally_ids)
            # s210 v2 / s214: bans follow the FIRST mood-recommended pick.
            # If the row resolved a champion, look up its hard counters
            # from data/meta/champion_counters.json. Falls back to the
            # operator's role-level worst matchups otherwise.
            bans: list[dict] = []
            if picks and picks[0].get("champName"):
                bans = _counters_for_champion(picks[0]["champName"])
            if not bans:
                bans = _query_bans(conn, puuid, role, queue_ids)
        finally:
            conn.close()

        # s214 response shape:
        #   `performance` - first pick (back-compat with pre-s214 callers
        #                   that consumed a single dict)
        #   `performance_picks` - full list of up to `top` picks for the
        #                         mood, used by the new LIMIT/NEW/SYNERGY
        #                         3-row layouts
        first = picks[0] if picks else None
        h._send(200, json.dumps({
            "ok": True,
            "role": role,
            "queue_ids": list(queue_ids),
            "mood": mood,
            "performance": first,
            "performance_picks": picks,
            "performance_bans": bans,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/champ-select/pickban-recs: %s", exc)
        h._send(500, json.dumps({"ok": False, "error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_personal_record(h) -> None:
    """s239 - GET /api/champ-select/personal-record. The per-user
    CONTEXTUAL read: given the champions in the current draft
    (``champ`` = operator's hovered/locked pick, ``allies`` /
    ``enemies`` = locked draft ids), return the operator's actual
    lifetime record. All params optional - early CS has no champ yet."""
    try:
        qs = parse_qs(urlparse(h.path).query)

        champ_raw = (qs.get("champ") or [""])[0].strip()
        try:
            champ_id = int(champ_raw) if champ_raw else 0
        except ValueError:
            champ_id = 0

        # role optional - drives only the champ at-role qualifier.
        role = _normalize_role((qs.get("role") or [""])[0])
        ally_ids = _parse_csv_ints((qs.get("allies") or [""])[0])
        enemy_ids = _parse_csv_ints((qs.get("enemies") or [""])[0])

        queue_raw = (qs.get("queue") or [""])[0]
        if queue_raw:
            try:
                queue_ids = tuple(int(x) for x in queue_raw.split(",") if x.strip())
            except ValueError:
                queue_ids = _DEFAULT_SR_QUEUES
            if not queue_ids:
                queue_ids = _DEFAULT_SR_QUEUES
        else:
            queue_ids = _DEFAULT_SR_QUEUES

        if not _REWIND_DB.exists():
            h._send(503,
                    json.dumps({"ok": False, "error": "rewind_history.db missing"}).encode(),
                    "application/json")
            return

        t0 = time.time()
        conn = sqlite3.connect(f"file:{_REWIND_DB}?mode=ro", uri=True, timeout=2.0)
        try:
            puuid = _resolve_operator_puuid(conn)
            if not puuid:
                h._send(503,
                        json.dumps({"ok": False, "error": "no operator puuid in rewind_history.db"}).encode(),
                        "application/json")
                return
            champ = (_query_champ_record(conn, puuid, champ_id, queue_ids, role)
                     if champ_id else None)
            with_allies = [_query_with_ally(conn, puuid, a, queue_ids)
                           for a in ally_ids]
            vs_enemies = [_query_vs_enemy(conn, puuid, e, queue_ids)
                          for e in enemy_ids]
        finally:
            conn.close()

        h._send(200, json.dumps({
            "ok": True,
            "queue_ids": list(queue_ids),
            "role": role,
            "champ": champ,
            "with_allies": with_allies,
            "vs_enemies": vs_enemies,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/champ-select/personal-record: %s", exc)
        h._send(500, json.dumps({"ok": False, "error": str(exc)[:200]}).encode(),
                "application/json")


# Route table - imported by dashboard/_dispatch.py at module load.

def _equals(p: str):
    """Local copy of routes_coach._equals to avoid the cross-import."""
    def m(path: str) -> bool: return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/champ-select/pickban-recs"), _serve_pickban_recs),
    (_equals("/api/champ-select/personal-record"), _serve_personal_record),
]
