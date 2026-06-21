# arch: top8 + mains backend | section=dashboard | frozen=no
"""Lobby auxiliary routes - server-side persistence for the pre-game
lobby view's Top 8 list, plus the enriched ``main_champs`` data the
Mains panel renders.

Origin-independent storage. The previous Top 8 implementation
(``localStorage.rc-top8-list`` in ``main.js``) only persisted per-origin
in the browser, so an operator hitting the dashboard from multiple
URLs (legion-rc, 192.168.8.230, 127.0.0.1) had separate, drifting
lists - and a Chrome cache-clear or browser restart wiped everything.
Server-side storage on Legion is the single source of truth.

Schema (``data/top8_list.json``):

    [
      {
        "riot_id":      "SamplePlayer#Trist",   # full Riot ID, name#tag
        "summoner_name": "SamplePlayer",        # legacy alias (pre-Riot-ID)
        "note":          "duo, last 12 games",
        "rank":          { "tier": "DIAMOND", "division": "II", "lp": 67 },
        "level":         412,
        "icon_id":       4567,
        "added_ts":      1778561234,
      },
      ...                                    # up to TOP8_MAX entries
    ]

Mains schema (``/api/mains?puuid=...`` response):

    {
      "ok": true,
      "puuid": "...",
      "main_champs": [
        {
          "name":           "Vayne",
          "icon":           "/data/ddragon/16.9.1/img/champion/Vayne.png",
          "mastery_level":  7,
          "mastery_points": 487213,
          "last_match":     { "result": "WIN", "kda": "12/4/8", "ts": 1778560000 },
          "overall":        { "games": 24, "wins": 14, "losses": 10,
                              "total_kda": "8.3/4.1/6.7" },
          "averaged":       { "cs_pm": 7.8, "vision_pm": 0.9, "dmg_pm": 612 },
        }, ...
      ]
    }

Both endpoints are read-only against external systems - they touch
local files only (``data/top8_list.json``, ``match_history.db``,
``rewind_history.db``) so they never block on Riot API or LCU.
"""
import json
import logging
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from dashboard._dispatch import equals, prefix

log = logging.getLogger("rc.web_dashboard")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_TOP8_PATH = _DATA_DIR / "top8_list.json"
_MATCH_DB = _DATA_DIR / "match_history.db"
_REWIND_DB = _DATA_DIR / "rewind_history.db"

_TOP8_MAX = 8


# -- Top 8 storage ----------------------------------------------------

def _load_top8() -> list:
    try:
        if not _TOP8_PATH.exists():
            return []
        with _TOP8_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            log.warning("top8: not a list, returning empty (got %r)", type(data))
            return []
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("top8: load failed: %s", exc)
        return []


def _save_top8(entries: list) -> None:
    """Atomic write - mirrors core.atomic_write_json's tmp+replace pattern.
    Caller is responsible for sanitizing entries; this just persists."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".top8_list.", suffix=".tmp", dir=str(_DATA_DIR))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(_TOP8_PATH))
    except Exception:
        try: os.unlink(tmp_path)
        except OSError: pass
        raise


def _sanitize_top8_entry(raw) -> dict | None:
    """Coerce a single entry into the saved schema. Drops fields we
    don't recognise so client bugs can't poison the file."""
    if not isinstance(raw, dict):
        return None
    rid = str(raw.get("riot_id") or "").strip()
    sn  = str(raw.get("summoner_name") or "").strip()
    if not rid and not sn:
        return None
    out = {
        "riot_id":       rid,
        "summoner_name": sn,
        "note":          str(raw.get("note") or "").strip(),
        "added_ts":      int(raw.get("added_ts") or time.time()),
    }
    rank = raw.get("rank")
    if isinstance(rank, dict):
        out["rank"] = {
            "tier":     str(rank.get("tier") or "").upper(),
            "division": str(rank.get("division") or "").upper(),
            "lp":       int(rank.get("lp") or 0),
        }
    if raw.get("level") is not None:
        try: out["level"] = int(raw["level"])
        except (TypeError, ValueError): pass
    if raw.get("icon_id") is not None:
        try: out["icon_id"] = int(raw["icon_id"])
        except (TypeError, ValueError): pass
    if raw.get("puuid"):
        out["puuid"] = str(raw["puuid"])
    return out


def _serve_top8_get(h) -> None:
    entries = _load_top8()
    h._send(200, json.dumps({"ok": True, "entries": entries}).encode(),
            "application/json")


def _serve_top8_post(h, payload) -> None:
    """Overwrite the entire list. Body shape: {entries: [...]} - the
    client always sends the full sorted list, no PATCH semantics.
    Returns the canonicalized list (post-sanitization) so the client
    can render exactly what got persisted."""
    raw = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        h._send(400, json.dumps({"error": "entries[] required"}).encode(),
                "application/json")
        return
    sanitized = []
    for e in raw[:_TOP8_MAX]:
        s = _sanitize_top8_entry(e)
        if s is not None:
            sanitized.append(s)
    try:
        _save_top8(sanitized)
    except Exception as exc:  # noqa: BLE001
        log.warning("top8 save: %s", exc)
        # Raw exception text stays in the log only (CLAUDE.md error rule).
        h._send(500, json.dumps({"error": "internal error - see logs"}).encode(),
                "application/json")
        return
    h._send(200, json.dumps({"ok": True, "entries": sanitized}).encode(),
            "application/json")


# -- Mains data -------------------------------------------------------

# Canonical source: rewind_history.db.participants - populated by
# scripts/rewind_catchup.py (s167) from Match-V5. The operator's puuid
# is the most-frequent in the table (currently ~2845 entries vs the
# next at 715). The same resolver pattern is used in routes_pickban.py.
# match_history.db is *also* present but is the legacy lightweight log
# (per-game grade + KDA only, no per-participant join); the rewind DB
# has cleaner stats for the Mains panel.

# Cycle-8 audit: the pre-s209 `_ddragon_version()` helper (a self-HTTP
# probe of /api/health/all with a stale "16.9.1" fallback pin) lost its
# last caller when the Mains icon path moved to /icons/champions/ and
# was removed as dead code.


def _resolve_operator_puuid(conn: sqlite3.Connection) -> str | None:
    """Most-frequent puuid in participants is the operator's. Mirrors
    routes_pickban._resolve_operator_puuid; kept local to avoid a
    cross-module import."""
    # ``puuid ASC`` tertiary keeps a COUNT(*) tie deterministic
    # (mirrors routes_pickban._resolve_operator_puuid).
    cur = conn.execute(
        "SELECT puuid FROM participants "
        "GROUP BY puuid ORDER BY COUNT(*) DESC, puuid ASC LIMIT 1"
    )
    row = cur.fetchone()
    return row[0] if row else None


def _query_mains_for_puuid(conn: sqlite3.Connection, puuid: str,
                           top_n: int) -> list:
    """Per-champion aggregate stats for one puuid, ranked by games
    played. Last-match details are resolved via a follow-on query so
    GROUP BY doesn't have to pick a representative row."""
    cur = conn.cursor()
    cur.execute("""
        SELECT champion_name AS champ,
               COUNT(*) AS games,
               SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN win=0 THEN 1 ELSE 0 END) AS losses,
               SUM(kills), SUM(deaths), SUM(assists),
               SUM(COALESCE(total_minions_killed,0) + COALESCE(neutral_minions_killed,0)) AS cs,
               SUM(vision_score), SUM(total_damage_dealt_to_champs) AS dmg,
               SUM(time_played) AS played_s
        FROM participants
        WHERE puuid = ?
          AND champion_name IS NOT NULL
          AND champion_name != ''
        GROUP BY champion_name
        ORDER BY games DESC
        LIMIT ?
    """, (puuid, top_n))
    agg_rows = cur.fetchall()
    out_rows = []
    for r in agg_rows:
        champ, games, wins, losses, ks, ds, as_, cs, vs, dmg, played_s = r
        wins, losses = wins or 0, losses or 0
        played_min = max(1, (played_s or 0) / 60)
        # Last match for this champ - join participants->matches.
        cur.execute("""
            SELECT p.win, p.kills, p.deaths, p.assists, m.game_creation_ts
            FROM participants p
            LEFT JOIN matches m ON m.match_id = p.match_id
            WHERE p.puuid = ? AND p.champion_name = ?
            ORDER BY m.game_creation_ts DESC
            LIMIT 1
        """, (puuid, champ))
        lm = cur.fetchone()
        last_match = {}
        if lm:
            last_match = {
                "result": "WIN" if lm[0] else "LOSS",
                "kda": f"{lm[1] or 0}/{lm[2] or 0}/{lm[3] or 0}",
                "ts": int((lm[4] or 0) // 1000),  # game_creation_ts is ms
            }
        # s209: champion icons live under /icons/champions/<slug>.png served
        # from data/icons/champions/ (172 PNGs). The DB stores DDragon-style
        # slugs already (LeeSin, MonkeyKing, etc.) so no normalization needed.
        # Pre-s209 emitted /data/ddragon/<patch>/img/champion/... which 404s
        # because the data/ddragon/ mount doesn't exist on disk.
        out_rows.append({
            "name": champ,
            "icon": f"/icons/champions/{champ}.png",
            "last_match": last_match,
            "overall": {
                "games":  games or 0,
                "wins":   wins,
                "losses": losses,
                "total_kda": f"{ks or 0}/{ds or 0}/{as_ or 0}",
            },
            "averaged": {
                "cs_pm":     round((cs or 0) / played_min, 1),
                "vision_pm": round((vs or 0) / played_min, 2),
                "dmg_pm":    int((dmg or 0) / played_min),
            },
        })
    return out_rows


def _operator_mains(puuid: str | None, top_n: int = 8) -> list:
    """Top-N main champions for the given puuid (or the operator's
    if none provided). Reads rewind_history.db read-only."""
    if not _REWIND_DB.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{_REWIND_DB}?mode=ro", uri=True)
        try:
            if not puuid:
                puuid = _resolve_operator_puuid(conn)
            if not puuid:
                return []
            return _query_mains_for_puuid(conn, puuid, top_n)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("mains: rewind_history query failed: %s", exc)
        return []


def _mastery_overlay(rows: list, mastery_state: dict | None) -> list:
    """Layer LCU mastery (mastery_level + mastery_points) onto the
    SQLite-derived stat rows. The agent's LCU mastery hook posts
    state.mastery shaped as ``{champion_name: {level, points, ...}}``."""
    if not isinstance(mastery_state, dict):
        return rows
    for r in rows:
        m = mastery_state.get(r["name"])
        if isinstance(m, dict):
            r["mastery_level"]  = m.get("level")
            r["mastery_points"] = m.get("points")
    return rows


def _read_live_mastery() -> dict:
    """Pull LCU mastery off the most recent state envelope so /api/mains
    can layer mastery_level/_points onto SQLite-derived stats without
    needing the client to pass them in. The /api/state response chain
    already enriches lcu.mastery via the Legion LCU agent (s168)."""
    try:
        import ssl as _ssl
        import urllib.request as _ur
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        req = _ur.Request("https://127.0.0.1:8888/api/state")
        with _ur.urlopen(req, timeout=1.0, context=ctx) as r:
            body = json.loads(r.read())
        return ((body.get("lcu") or {}).get("mastery")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _serve_mains_get(h) -> None:
    """GET /api/mains[?puuid=...]. With an explicit puuid, returns
    that user's mains (party-tab use case). Without one, falls back
    to the operator's puuid (most-frequent in participants)."""
    try:
        qs = parse_qs(urlparse(h.path).query)
        puuid = (qs.get("puuid") or [""])[0].strip()
        rows = _operator_mains(puuid or None, top_n=8)
        # Mastery layer is operator-only; party members have their own
        # mastery via LCU agent but we don't surface it here yet.
        if not puuid:
            rows = _mastery_overlay(rows, _read_live_mastery())
        h._send(200, json.dumps({
            "ok": True,
            "puuid": puuid,
            "main_champs": rows,
        }).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        # Cycle-8 audit: this was the only slice handler doing real work
        # without a wrapper - an unexpected exception escaped do_GET and
        # reset the connection instead of answering.
        log.warning("api/mains: %s", exc)
        h._send(500, json.dumps(
            {"ok": False, "error": "internal error - see logs"}).encode(),
            "application/json")


# -- route table ------------------------------------------------------

GET_ROUTES = [
    (equals("/api/top8"),  _serve_top8_get),
    (equals("/api/mains"), _serve_mains_get),
]

POST_ROUTES = [
    (equals("/api/top8"),  _serve_top8_post),
]
