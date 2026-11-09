# arch: top8 + mains backend | section=dashboard | frozen=no
"""Lobby auxiliary routes - server-side persistence for the pre-game
lobby view's Top 8 list, plus the enriched ``main_champs`` data the
Mains panel renders.

Origin-independent storage. The previous Top 8 implementation
(``localStorage.rc-top8-list`` in ``main.js``) only persisted per-origin
in the browser, so an operator hitting the dashboard from multiple
URLs (rc-host, 192.0.2.230, 127.0.0.1) had separate, drifting
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
        "user_tag":      "duo",                 # the rest only when sent
        "is_online":     false,
        "games_with_me": null,
        "preferred_role": null,
        "summoner_level": 412,
        "puuid":         "...",
      },
      ...                                    # up to TOP8_MAX entries
    ]

    Every string is type-checked and capped (_MAX_*_LEN); every number is
    a non-negative int or the field is dropped (``rank.lp`` falls to 0,
    ``added_ts`` to now). Unknown fields are dropped.

Mains schema (``/api/mains?puuid=...`` response):

    {
      "ok": true,
      "puuid": "...",
      "main_champs": [
        {
          "name":           "Vayne",
          "champion_id":    67,               # null on a DB without it
          "icon":           "/data/ddragon/16.9.1/img/champion/Vayne.png",
          "mastery_level":  7,
          "mastery_points": 487213,
          "last_match":     { "result": "WIN", "kda": "12/4/8", "ts": 1778560000 },
          "overall":        { "games": 24, "wins": 14, "losses": 10,
                              "total_kda": "8.3/4.1/6.7" },
          "averaged":       { "kp": 58.2, "cs": 184, "vision": 22.0,
                              "dmg": 18500, "cs_per_min": 7.8, "avg5": "A" },
        }, ...
      ]
    }

Both endpoints are read-only against external systems - they touch
local files only (``data/top8_list.json``, ``match_history.db``,
``rewind_history.db``) so they never block on Riot API or LCU.
"""
import json
import logging
import math
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from core.polled_json import atomic_write_json
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_TOP8_PATH = _DATA_DIR / "top8_list.json"
_REWIND_DB = _DATA_DIR / "rewind_history.db"

_TOP8_MAX = 8

# s144 true-audit: caps on every persisted string. A Riot ID is at most
# 16 + 1 + 5 characters and a puuid is 78; the caps leave headroom while
# keeping one POST from parking a 1 MiB note in a file served on every GET.
_MAX_ID_LEN = 64
_MAX_NOTE_LEN = 200
_MAX_PUUID_LEN = 128
_MAX_RANK_LEN = 16


# -- Top 8 storage ----------------------------------------------------

def _load_top8() -> list:
    """The stored list, re-sanitized on the way out.

    s144 true-audit: the file used to be served raw. json.load accepts a
    bare NaN, which then went back out as a non-strict token that the
    browser's r.json() rejects; main.js then sets its cache to [] and the
    operator's next add POSTs a one-entry list over the whole file. Every
    entry now passes the same sanitizer a POST does, capped at TOP8_MAX.
    """
    try:
        if not _TOP8_PATH.exists():
            return []
        with _TOP8_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError) as exc:
        # ValueError covers JSONDecodeError and UnicodeDecodeError;
        # RecursionError is json.load on a deeply nested file, and GET has
        # no wrapper above it (do_GET does not catch a route exception).
        log.warning("top8: load failed: %s", type(exc).__name__)
        return []
    if not isinstance(data, list):
        log.warning("top8: not a list, returning empty (got %s)",
                    type(data).__name__)
        return []
    out = []
    for e in data:
        s = _sanitize_top8_entry(e)
        if s is not None:
            out.append(s)
        if len(out) >= _TOP8_MAX:
            break
    return out


def _save_top8(entries: list) -> None:
    """Atomic write via core.polled_json.atomic_write_json (raises on failure).
    Caller is responsible for sanitizing entries; this just persists."""
    atomic_write_json(_TOP8_PATH, entries)


def _clean_str(value, cap: int) -> str:
    """A stripped, length-capped string, or "" for anything not a str.

    Non-strings used to go through str(), so a dict landed on disk as its
    Python repr."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:cap]


def _nonneg_int(value) -> int | None:
    """A non-negative int from an int, a finite float or a short ASCII
    digit string (the old int() coercion accepted "12"), else None.

    bool is refused (int(True) is 1). int() of inf raises OverflowError and
    of nan ValueError - the bare int() calls this replaces let both escape
    the handler, and do_POST does not catch a route exception, so the
    request died with no HTTP response."""
    if isinstance(value, str):
        s = value.strip()
        return int(s) if s.isascii() and s.isdigit() and len(s) <= 12 \
            else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    n = int(value)
    return n if n >= 0 else None


def _sanitize_top8_entry(raw) -> dict | None:
    """Coerce a single entry into the saved schema. Drops fields we
    don't recognise so client bugs can't poison the file.

    s144 true-audit: every field is type-checked and every string capped,
    and the fields web/js/main.js renders and lets the operator edit
    (``user_tag``, ``is_online``, ``games_with_me``, ``preferred_role``,
    ``summoner_level``) are kept when sent. The client replaces its cache
    with this response, so a dropped ``user_tag`` vanished on save."""
    if not isinstance(raw, dict):
        return None
    rid = _clean_str(raw.get("riot_id"), _MAX_ID_LEN)
    sn = _clean_str(raw.get("summoner_name"), _MAX_ID_LEN)
    if not rid and not sn:
        return None
    added = _nonneg_int(raw.get("added_ts"))
    out = {
        "riot_id":       rid,
        "summoner_name": sn,
        "note":          _clean_str(raw.get("note"), _MAX_NOTE_LEN),
        "added_ts":      added or int(time.time()),
    }
    rank = raw.get("rank")
    if isinstance(rank, dict):
        out["rank"] = {
            "tier":     _clean_str(rank.get("tier"), _MAX_RANK_LEN).upper(),
            "division": _clean_str(rank.get("division"),
                                   _MAX_RANK_LEN).upper(),
            "lp":       _nonneg_int(rank.get("lp")) or 0,
        }
    for key in ("level", "icon_id", "summoner_level"):
        n = _nonneg_int(raw.get(key))
        if n is not None:
            out[key] = n
    puuid = _clean_str(raw.get("puuid"), _MAX_PUUID_LEN)
    if puuid:
        out["puuid"] = puuid
    if "user_tag" in raw:
        out["user_tag"] = _clean_str(raw.get("user_tag"), _MAX_NOTE_LEN)
    if "is_online" in raw:
        out["is_online"] = raw.get("is_online") is True
    if "games_with_me" in raw:
        out["games_with_me"] = _nonneg_int(raw.get("games_with_me"))
    if "preferred_role" in raw:
        out["preferred_role"] = (
            _clean_str(raw.get("preferred_role"), _MAX_RANK_LEN) or None)
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


def _avg5_grade(recent_rows) -> str | None:
    """Letter grade (S/A/B/C/D) from the avg KDA of up to the last 5 games
    for a champ. rewind_history.db carries no RC grade column, so the
    'AVG 5' lobby cell uses a KDA proxy. `recent_rows` are the last-match
    query rows (win, kills, deaths, assists, ts); None when there is no
    recent play to grade."""
    if not recent_rows:
        return None
    k = sum((r[1] or 0) for r in recent_rows)
    d = sum((r[2] or 0) for r in recent_rows)
    a = sum((r[3] or 0) for r in recent_rows)
    kda = (k + a) / max(d, 1)
    if kda >= 4.0:
        return "S"
    if kda >= 3.0:
        return "A"
    if kda >= 2.2:
        return "B"
    if kda >= 1.5:
        return "C"
    return "D"


def _kp_by_champ(conn: sqlite3.Connection, puuid: str) -> dict:
    """Average kill-participation percent per champ for one puuid:
    mean over that champ's games of (kills+assists)/team_kills, where
    team_kills is the per-match per-team kill total (a participants
    self-join). One pass; fail-soft to {} so a schema/sqlite hiccup never
    blocks the mains payload."""
    out: dict = {}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.champion_name,
                   AVG(CAST(p.kills + p.assists AS REAL) / tk.tk) * 100.0
            FROM participants p
            JOIN (SELECT match_id, team_id, SUM(kills) AS tk
                  FROM participants GROUP BY match_id, team_id) tk
              ON tk.match_id = p.match_id AND tk.team_id = p.team_id
            WHERE p.puuid = ? AND tk.tk > 0
              AND p.champion_name IS NOT NULL AND p.champion_name != ''
            GROUP BY p.champion_name
        """, (puuid,))
        for champ_n, kp_avg in cur.fetchall():
            if kp_avg is not None:
                out[champ_n] = round(kp_avg, 1)
    except sqlite3.Error:
        return {}
    return out


def _champion_ids(conn: sqlite3.Connection, puuid: str) -> dict:
    """champion_name -> champion_id for one puuid, the key the LCU mastery
    map uses. Fail-soft to {} (an older DB without the column) so the mains
    payload never depends on it."""
    try:
        cur = conn.execute(
            "SELECT champion_name, MAX(champion_id) FROM participants "
            "WHERE puuid = ? AND champion_id IS NOT NULL "
            "GROUP BY champion_name", (puuid,))
        return {n: int(cid) for n, cid in cur.fetchall()
                if n and isinstance(cid, int) and cid > 0}
    except sqlite3.Error:
        return {}


def _query_mains_for_puuid(conn: sqlite3.Connection, puuid: str,
                           top_n: int) -> list:
    """Per-champion aggregate stats for one puuid, ranked by games
    played. Last-match details are resolved via a follow-on query so
    GROUP BY doesn't have to pick a representative row."""
    cur = conn.cursor()
    # s144 true-audit: cs_per_min is CS from games WITH a time_played over
    # those games' minutes. It used to be all CS over max(1, minutes), so a
    # champ whose rows carry no time_played reported its total CS across
    # every game as a per-minute rate. `champ ASC` and `p.match_id DESC`
    # make ties (and so the LIMIT cut) a rule rather than a query-plan
    # accident.
    cur.execute("""
        SELECT champion_name AS champ,
               COUNT(*) AS games,
               SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN win=0 THEN 1 ELSE 0 END) AS losses,
               SUM(kills), SUM(deaths), SUM(assists),
               SUM(COALESCE(total_minions_killed,0) + COALESCE(neutral_minions_killed,0)) AS cs,
               SUM(vision_score), SUM(total_damage_dealt_to_champs) AS dmg,
               SUM(CASE WHEN time_played > 0 THEN time_played ELSE 0 END)
                   AS played_s,
               SUM(CASE WHEN time_played > 0
                        THEN COALESCE(total_minions_killed,0)
                             + COALESCE(neutral_minions_killed,0)
                        ELSE 0 END) AS cs_timed
        FROM participants
        WHERE puuid = ?
          AND champion_name IS NOT NULL
          AND champion_name != ''
        GROUP BY champion_name
        ORDER BY games DESC, champ ASC
        LIMIT ?
    """, (puuid, top_n))
    agg_rows = cur.fetchall()
    # R30: kill-participation per champ (one self-join pass) so the lobby
    # AVG/Match KP% cell fills from real data instead of "-".
    kp_by_champ = _kp_by_champ(conn, puuid)
    ids_by_champ = _champion_ids(conn, puuid)
    out_rows = []
    for r in agg_rows:
        (champ, games, wins, losses, ks, ds, as_, cs, vs, dmg, played_s,
         cs_timed) = r
        wins, losses = wins or 0, losses or 0
        games = games or 0
        played_min = (played_s or 0) / 60
        # Last 5 for this champ - row 0 is the last match; all 5 grade AVG 5.
        cur.execute("""
            SELECT p.win, p.kills, p.deaths, p.assists, m.game_creation_ts
            FROM participants p
            LEFT JOIN matches m ON m.match_id = p.match_id
            WHERE p.puuid = ? AND p.champion_name = ?
            ORDER BY m.game_creation_ts DESC, p.match_id DESC
            LIMIT 5
        """, (puuid, champ))
        recent = cur.fetchall()
        lm = recent[0] if recent else None
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
            "champion_id": ids_by_champ.get(champ),
            "icon": f"/icons/champions/{champ}.png",
            "last_match": last_match,
            "overall": {
                "games":  games or 0,
                "wins":   wins,
                "losses": losses,
                "total_kda": f"{ks or 0}/{ds or 0}/{as_ or 0}",
            },
            # R30: emit the keys the lobby frontend (_mcAveragedHtml) reads -
            # KP% / Vision / CS / AVG5 / Dmg / CS-per-min - so the AVG/Match
            # grid fills from real rewind data instead of "-". cs/vision/dmg
            # are per-game averages; cs_per_min is per-minute. (The old
            # cs_pm/vision_pm/dmg_pm keys had no consumer and are dropped.)
            "averaged": {
                "kp":         kp_by_champ.get(champ),
                "cs":         round((cs or 0) / games) if games else None,
                "vision":     round((vs or 0) / games, 1) if games else None,
                "dmg":        int((dmg or 0) / games) if games else None,
                "cs_per_min": (round((cs_timed or 0) / played_min, 1)
                               if played_min > 0 else None),
                "avg5":       _avg5_grade(recent),
            },
        })
    return out_rows


def _connect_rewind_ro() -> sqlite3.Connection:
    """Read-only connection to the rewind DB.

    s144 true-audit: the URI was ``f"file:{path}?mode=ro"`` built from the
    raw path, so a ``#`` (fragment) or ``%`` (escape) in the checkout path
    opened the wrong file and the panel went silently empty. as_uri()
    percent-encodes the path."""
    return sqlite3.connect(_REWIND_DB.resolve().as_uri() + "?mode=ro",
                           uri=True)


def _operator_mains(puuid: str | None, top_n: int = 8) -> list:
    """Top-N main champions for the given puuid (or the operator's
    if none provided). Reads rewind_history.db read-only."""
    if not _REWIND_DB.exists():
        return []
    try:
        conn = _connect_rewind_ro()
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
    SQLite-derived stat rows.

    s144 true-audit: lcu/snapshot_shape._maybe_refresh_mastery keys the map
    by integer championId (a string key once it has crossed JSON), and this
    used to look it up by champion NAME, so nothing ever matched. Rows now
    carry ``champion_id``; the id is tried as str and int, then the name
    (the legacy shape this docstring used to promise)."""
    if not isinstance(mastery_state, dict):
        return rows
    for r in rows:
        cid = r.get("champion_id")
        m = None
        if cid is not None:
            m = mastery_state.get(str(cid), mastery_state.get(cid))
        if m is None:
            m = mastery_state.get(r.get("name"))
        if isinstance(m, dict):
            r["mastery_level"] = _nonneg_int(m.get("level"))
            r["mastery_points"] = _nonneg_int(m.get("points"))
    return rows


def _read_live_mastery() -> dict:
    """LCU mastery off the same snapshot /api/state serves as ``lcu``, so
    /api/mains can layer mastery_level/_points onto SQLite-derived stats.

    s144 true-audit: this used to make a self-HTTPS request from inside a
    request handler to a hard-coded :8888 through urllib's default opener
    (which honours a process proxy), to read one key this process already
    builds. It now asks the state builder's LCU reader directly; the import
    is lazy so gathering the route table does not pull in the state builder
    (coaches, team context, the relay pool)."""
    try:
        from dashboard._state_builder import _read_lcu_snapshot
        snap = _read_lcu_snapshot()
    except Exception as exc:  # noqa: BLE001 - fail-soft: mastery is optional
        log.debug("mains: live mastery unavailable: %s", type(exc).__name__)
        return {}
    mastery = snap.get("mastery") if isinstance(snap, dict) else None
    return mastery if isinstance(mastery, dict) else {}


def _serve_mains_get(h) -> None:
    """GET /api/mains[?puuid=...]. With an explicit puuid, returns
    that user's mains (party-tab use case). Without one, falls back
    to the operator's puuid (most-frequent in participants)."""
    try:
        qs = parse_qs(urlparse(h.path).query)
        puuid = (qs.get("puuid") or [""])[0].strip()
        if len(puuid) > _MAX_PUUID_LEN:
            # s144 true-audit: a Riot puuid is 78 characters; anything this
            # long is not one, and is not echoed back.
            h._send(400, json.dumps(
                {"ok": False, "error": "bad puuid"}).encode(),
                "application/json")
            return
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
