"""s170 — Pick & Ban Recommendations backend (item #4).

Provides GET /api/champ-select/pickban-recs?role=BOT[&queue=420] which
returns the "performance" row that the champ-select view's P&B panel
needs. Currently the panel (web/js/panels/champ_select.js:2060) renders
hardcoded `_PB_PLACEHOLDERS`; this endpoint replaces the performance
row with real per-champion WR + ban suggestions computed from
``data/rewind_history.db``.

Mastery + meta rows still drive off placeholders for now — mastery
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
      "reason": str   (e.g. "67% WR · 6 games · highest WR with ≥3 games")
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

log = logging.getLogger("rc.web_dashboard")

_REWIND_DB = Path("data") / "rewind_history.db"

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
# ranked + Quickplay. Excludes ARAM/Arena/Brawl/Coop because P&B is
# SR-only (no bans in those modes anyway).
_DEFAULT_SR_QUEUES = (400, 420, 430, 440, 490)

# Minimum games threshold. Below this the WR isn't statistically
# meaningful; we skip the performance row rather than recommend a
# 100%-WR 1-game champion.
_MIN_GAMES_PICK = 3
_MIN_GAMES_BAN  = 2


def _resolve_operator_puuid(conn: sqlite3.Connection) -> str | None:
    """The operator is the puuid that appears in the most matches in
    rewind_history.db. Resolving from the DB rather than configuration
    keeps the endpoint self-contained — no env var, no cross-module
    dependency on ``core.riot_api``.
    """
    cur = conn.execute(
        "SELECT puuid FROM participants "
        "GROUP BY puuid "
        "ORDER BY COUNT(*) DESC LIMIT 1"
    )
    row = cur.fetchone()
    return row[0] if row else None


def _normalize_role(raw: str) -> str | None:
    return _ROLE_ALIASES.get((raw or "").upper())


def _query_performance(conn: sqlite3.Connection, puuid: str, role: str,
                       queue_ids: tuple[int, ...]) -> dict | None:
    """Top WR pick for the operator in this role + queue set. Picks
    the highest WR with at least ``_MIN_GAMES_PICK`` games; ties broken
    by higher game count (more reliable signal).
    """
    placeholders = ",".join("?" * len(queue_ids))
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
        GROUP BY champion_id
        HAVING games >= ?
        ORDER BY (CAST(wins AS REAL) / games) DESC, games DESC
        LIMIT 1
        """,
        (puuid, role, *queue_ids, _MIN_GAMES_PICK),
    )
    row = cur.fetchone()
    if not row:
        return None
    champ_id, champ_name, games, wins = row
    wr_pct = int(round(100 * wins / games)) if games else 0
    return {
        "champId":   int(champ_id),
        "champName": str(champ_name or "?"),
        "games":     int(games),
        "wins":      int(wins),
        "wr_pct":    wr_pct,
        "reason":    f"{wr_pct}% WR · {games} games · highest WR with ≥{_MIN_GAMES_PICK} games",
    }


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
        ORDER BY (CAST(losses AS REAL) / encounters) DESC, encounters DESC
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
        # half the time — sub-50% loss rate isn't a ban-worthy threat.
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

        # Queue filter: ?queue=420 → (420,); ?queue=400,420 → (400, 420);
        # omitted → default SR queue set.
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
            perf = _query_performance(conn, puuid, role, queue_ids)
            bans = _query_bans(conn, puuid, role, queue_ids)
        finally:
            conn.close()

        h._send(200, json.dumps({
            "ok": True,
            "role": role,
            "queue_ids": list(queue_ids),
            "performance": perf,
            "performance_bans": bans,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/champ-select/pickban-recs: %s", exc)
        h._send(500, json.dumps({"ok": False, "error": str(exc)[:200]}).encode(),
                "application/json")


# Route table — imported by dashboard/_dispatch.py at module load.

def _equals(p: str):
    """Local copy of routes_coach._equals to avoid the cross-import."""
    def m(path: str) -> bool: return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/champ-select/pickban-recs"), _serve_pickban_recs),
]
