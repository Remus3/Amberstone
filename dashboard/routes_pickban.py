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
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import champion_info_overrides as _cio

log = logging.getLogger("rc.web_dashboard")

_REWIND_DB = Path("data") / "rewind_history.db"
_COUNTERS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "champion_counters.json"
_DDRAGON_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"

# Cost lever 2: both heavy DB handlers below (pickban-recs + personal-record)
# resolve the operator puuid and run several JOINs per request, and fire on
# every draft action (hover / lock). rewind_history.db only changes
# post-game (the catchup writer), so the result is stable for the life of a
# draft. Cache it on a 300s TTL keyed by the request params AND the db mtime -
# any write to the db (a new match) busts every key, so a cache hit can never
# serve stale data and tests that rebuild the fixture db never collide.
_PB_CACHE_TTL_S = 300.0
_PB_CACHE: dict[tuple, tuple[float, dict]] = {}
_PB_CACHE_LOCK = threading.Lock()
# Cycle-8 audit: every new db mtime (post-game write) re-keys the cache
# and the dead keys were never evicted, so the dict grew without bound
# over long uptimes. Cap + drop-oldest keeps it flat (same pattern as
# routes_personal_vs._cache_put).
_PB_CACHE_MAX = 256
_PB_CACHE_EVICT = 64

# Cycle-41 audit: :8888 binds `::` - all interfaces, measured 2026-08-31 with
# Get-NetTCPConnection - not loopback, and every route below takes a
# comma-separated championId list straight off the query string.
# /api/champ-select/personal-record then runs ONE `_query_co_participant`
# (a correlated EXISTS over `participants`) per id in `allies` and per id in
# `enemies`. MEASURED against the live 1.87 GB rewind_history.db: 291 ms cold,
# 13.5 ms warm, per id. The stdlib HTTP request line admits 65536 bytes, so a
# single GET carries roughly 32000 one-digit ids - about 7 minutes of solid
# CPU on one handler thread holding a read connection.
# dashboard/_handler.py already caps POST bodies (`_MAX_POST_BYTES`, cycle 4,
# which closed the sibling "negative Content-Length pinned a handler thread
# from the tailnet"); the GET side had no equivalent and this is it.
#
# 32 clears every real lobby with headroom: an SR draft peaks at 10 picks +
# 10 bans = 20, and Arena carries 16 players. Worst case is now bounded at
# roughly 32 * 13.5 ms = 0.43 s.
_MAX_ID_PARAMS = 32


def _db_mtime() -> float:
    try:
        return _REWIND_DB.stat().st_mtime
    except OSError:
        return 0.0


def _reset_caches() -> None:
    """Test hook - drop the pickban / personal-record TTL caches."""
    with _PB_CACHE_LOCK:
        _PB_CACHE.clear()

# Module-level lazy index. Re-built on first call after a process
# restart; operator-edited JSON picks up on next restart_trigger.
_COUNTERS_INDEX: dict | None = None
_CHAMP_NAME_TO_ID: dict[str, int] | None = None
_CHAMP_ID_TO_NAME: dict[int, str] | None = None
# LIFT 1b: numeric championId -> (attack, magic) from info.attack/info.magic.
_CHAMP_ID_TO_INFO: dict[int, tuple[int, int]] | None = None


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
        # isinstance guards keep the handler below provably narrow: a
        # structurally wrong (but valid) JSON body can no longer raise
        # AttributeError out of .get()/.items().
        counters = raw.get("counters") if isinstance(raw, dict) else None
        for k, v in (counters if isinstance(counters, dict) else {}).items():
            if not isinstance(v, list):
                continue
            out[_norm_name(k)] = list(v)
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # A5 (docs/specs/2026-07-19-silent-except-triage.md): NEVER cache a
        # failed load. Returning uncached leaves the module-level global at
        # None so the next call retries instead of pinning an empty map for
        # the whole process lifetime.
        log.debug("pickban: counters load failed: %s", exc)
        return out
    _COUNTERS_INDEX = out
    return out


def _ddragon_champ_entries() -> dict:
    """Read the DDragon champion file and return its ``data`` mapping.

    Raises only ``OSError`` (read) or ``json.JSONDecodeError`` (parse): the
    isinstance guards mean a structurally wrong body degrades to ``{}``
    instead of raising AttributeError out of ``.get()`` / ``.values()``.
    That is what lets the three callers below hold a provably narrow
    ``(OSError, json.JSONDecodeError)`` handler."""
    raw = json.loads(_DDRAGON_CHAMPS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data", raw)
    return data if isinstance(data, dict) else {}


def _load_champ_name_to_id() -> dict[str, int]:
    """Normalized name -> numeric id. Keys via `_norm_name` so any case +
    spacing variant resolves cleanly."""
    global _CHAMP_NAME_TO_ID
    if _CHAMP_NAME_TO_ID is not None:
        return _CHAMP_NAME_TO_ID
    out: dict[str, int] = {}
    try:
        data = _ddragon_champ_entries()
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
    except (OSError, json.JSONDecodeError) as exc:
        # A5: do not cache a failed load - see _load_counters_index.
        log.debug("pickban: champ name->id load failed: %s", exc)
        return out
    _CHAMP_NAME_TO_ID = out
    return out


def _load_champ_id_to_name() -> dict[int, str]:
    global _CHAMP_ID_TO_NAME
    if _CHAMP_ID_TO_NAME is not None:
        return _CHAMP_ID_TO_NAME
    out: dict[int, str] = {}
    try:
        data = _ddragon_champ_entries()
        for entry in data.values():
            if isinstance(entry, dict) and entry.get("key") and entry.get("name"):
                try:
                    out[int(entry["key"])] = str(entry["name"])
                except (TypeError, ValueError):
                    continue
    except (OSError, json.JSONDecodeError) as exc:
        # A5: do not cache a failed load - see _load_counters_index.
        log.debug("pickban: champ id->name load failed: %s", exc)
        return out
    _CHAMP_ID_TO_NAME = out
    return out


def _load_champ_id_to_info() -> dict[int, tuple[int, int]]:
    """LIFT 1b: numeric championId -> (attack, magic). Mirrors
    ``_load_champ_id_to_name``'s structure + module-level lazy cache; reads
    info.attack / info.magic (DDragon "damage profile" ints 1-10) from
    _DDRAGON_CHAMPS_PATH. A champ with missing/malformed info is skipped."""
    global _CHAMP_ID_TO_INFO
    if _CHAMP_ID_TO_INFO is not None:
        return _CHAMP_ID_TO_INFO
    out: dict[int, tuple[int, int]] = {}
    try:
        data = _ddragon_champ_entries()
        for entry in data.values():
            if not (isinstance(entry, dict) and entry.get("key")):
                continue
            info = entry.get("info")
            if not isinstance(info, dict):
                continue
            # Curated override for DDragon-zeroed champs (Seraphine 0/0 would be
            # invisible in the mix, Qiyana 0/4 would mis-lean AP) - see
            # core.champion_info_overrides.
            info = _cio.merged_info(entry.get("name"), info)
            try:
                cid = int(entry["key"])
                attack = int(info["attack"])
                magic = int(info["magic"])
            except (KeyError, TypeError, ValueError):
                continue
            out[cid] = (attack, magic)
    except (OSError, json.JSONDecodeError) as exc:
        # A5: do not cache a failed load - see _load_counters_index.
        log.debug("pickban: champ id->info load failed: %s", exc)
        return out
    _CHAMP_ID_TO_INFO = out
    return out


def _compute_team_damage_mix(team_ids: tuple[int, ...]) -> dict:
    """LIFT 1b PURE function: sum info.attack + info.magic over the team and
    return the physical-vs-magic damage lean. Ids absent from the info map
    are skipped (so an unknown id never skews the mix). When no valid champ
    remains, n_champs is 0 and both percentages are 0.

    physical_pct = round(100 * sum_attack / (sum_attack + sum_magic)) when
    the denominator > 0 else 0; magical_pct = 100 - physical_pct (when the
    denominator > 0; else 0). Per-champ lean = "AD" if attack > magic,
    "AP" if magic > attack, else "EVEN"."""
    info_map = _load_champ_id_to_info()
    per_champ: list[dict] = []
    sum_attack = 0
    sum_magic = 0
    for cid in team_ids:
        pair = info_map.get(int(cid))
        if pair is None:
            continue
        attack, magic = pair
        sum_attack += attack
        sum_magic += magic
        if attack > magic:
            lean = "AD"
        elif magic > attack:
            lean = "AP"
        else:
            lean = "EVEN"
        per_champ.append({
            "champId": int(cid),
            "attack":  int(attack),
            "magic":   int(magic),
            "lean":    lean,
        })
    denom = sum_attack + sum_magic
    if denom > 0:
        physical_pct = int(round(100 * sum_attack / denom))
        magical_pct = 100 - physical_pct
    else:
        physical_pct = 0
        magical_pct = 0
    return {
        "ok": True,
        "team_ids": [int(c) for c in team_ids],
        "n_champs": len(per_champ),
        "sum_attack": sum_attack,
        "sum_magic": sum_magic,
        "physical_pct": physical_pct,
        "magical_pct": magical_pct,
        "per_champ": per_champ,
    }


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


def _counters_vs_comp(enemy_ids: tuple[int, ...],
                      exclude_ids: tuple[int, ...],
                      limit: int = 5) -> list[dict]:
    """RC2 E4 (P2): aggregate "pick into this comp" counters vs the LIVE
    enemy team.

    Walks the per-champion counters index for every enemy champion and
    tallies, for each candidate counter, HOW MANY of the enemy champs it
    counters (its coverage of the comp). Candidates that hit more of the
    enemy comp rank higher - the glanceable single-decision prompt that
    wins the short pick window.

    `enemy_ids` are LCU numeric championIds; `exclude_ids` are already
    picked/banned ids (and need not include the enemy ids - those are
    skipped automatically so a candidate already on the enemy team is
    never recommended back). Returns up to `limit` rows shaped:
        {champId, name, counters_count, vs_names: [str, ...], note}
    Ranked by counters_count desc, then name asc (stable). Empty when the
    comp is empty or the counters index yields no candidates.
    """
    enemy_ids = tuple(int(x) for x in enemy_ids if int(x) > 0)
    if not enemy_ids:
        return []
    counters_idx = _load_counters_index()
    name_to_id = _load_champ_name_to_id()
    id_to_name = _load_champ_id_to_name()
    # Never recommend a champion already on the enemy team or already
    # picked/banned on the board.
    skip = set(int(x) for x in exclude_ids if int(x) > 0)
    skip.update(enemy_ids)

    # candidate champId -> {"name": str, "vs": [enemy display names]}
    agg: dict[int, dict] = {}
    for ecid in enemy_ids:
        enemy_name = id_to_name.get(int(ecid))
        if not enemy_name:
            continue
        for counter_name in (counters_idx.get(_norm_name(enemy_name)) or []):
            cand_id = name_to_id.get(_norm_name(counter_name))
            if not cand_id or int(cand_id) in skip:
                continue
            slot = agg.setdefault(int(cand_id),
                                  {"name": str(counter_name), "vs": []})
            if enemy_name not in slot["vs"]:
                slot["vs"].append(enemy_name)

    rows: list[dict] = []
    for cand_id, slot in agg.items():
        vs_names = slot["vs"]
        count = len(vs_names)
        if count <= 0:
            continue
        if count == 1:
            note = f"counters {vs_names[0]}"
        elif count == 2:
            note = f"counters {vs_names[0]} + {vs_names[1]}"
        else:
            note = f"counters {count} of their comp"
        rows.append({
            "champId":        int(cand_id),
            "name":           str(slot["name"]),
            "counters_count": int(count),
            "vs_names":       list(vs_names),
            "note":           note,
        })
    # Coverage desc, then name asc for a stable glance order.
    rows.sort(key=lambda r: (-r["counters_count"], r["name"]))
    return rows[:max(1, int(limit))]

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

# Loss-rate floor for a ban suggestion - below this the operator wins
# half-or-more of the matchup, so it is not a threat worth banning.
_BAN_MIN_LOSS_PCT = 50

# Summoner-spell id for Cleanse (D), checked by the CC-cleanse advisory.
_CLEANSE_SUMMONER_ID = 1

# A3 (QA 2026-07-03, docs/qa/CHAMP_SELECT_QA_2026-07-03.md): the s209
# mood system (comfort / limit / new / synergy re-ranking) is REMOVED.
# The mood tabs had been hidden in the UI since 2026-05-23 while a stale
# sessionStorage mood kept filtering pick recs. The endpoint now always
# serves the raw top-N picks by score (highest observed WR at role,
# >= _MIN_GAMES_PICK games) plus the mood-invariant last-in-queue row.
# A stray legacy ``mood=`` query arg is tolerated and IGNORED - never a
# 400 - so pre-A3 clients keep working during the frontend transition.


def _pct(numerator: int, denominator: int) -> int:
    """Rounded integer percentage; 0 when the denominator is 0."""
    return int(round(100 * numerator / denominator)) if denominator else 0


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
# single dicts, so the panel rows render cascade-filtered picks. Each
# query takes ``exclude_ids`` so the caller can pass already-banned +
# already-picked + already-shown ids to skip; SQL builds a NOT IN
# clause when present. Each query takes ``top`` for the result list
# length (default 1 for back-compat with the single-row endpoint shape).
# --------------------------------------------------------------------


def _exclude_clause(exclude_ids: tuple[int, ...],
                    col: str = "champion_id") -> tuple[str, tuple[int, ...]]:
    """Returns (sql_fragment, params). When exclude_ids is empty we emit
    a no-op fragment (`AND 1=1`) so the f-string concatenation stays
    grammatical regardless of operator filter state. ``col`` qualifies the
    column so self-join callers pass e.g. "op.champion_id" directly instead
    of string-replacing the fragment after the fact."""
    if not exclude_ids:
        return ("AND 1=1", ())
    placeholders = ",".join("?" * len(exclude_ids))
    return (f"AND {col} NOT IN ({placeholders})", exclude_ids)


def _query_performance_band(conn: sqlite3.Connection, puuid: str, role: str,
                            queue_ids: tuple[int, ...], *,
                            having_sql: str, having_params: tuple[int, ...],
                            reason_suffix: str,
                            exclude_ids: tuple[int, ...] = (),
                            top: int = 1) -> list[dict]:
    """Shared body for the performance pick query: operator's top-N
    highest-WR champions at this role, filtered by a games-count
    HAVING predicate (``having_sql`` + ``having_params``). Ties broken by
    higher game count (more reliable signal) then champion_id (stable).
    ``exclude_ids`` skips banned + already-shown ids."""
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
        HAVING {having_sql}
        ORDER BY (CAST(wins AS REAL) / games) DESC, games DESC, champion_id ASC
        LIMIT ?
        """,
        (puuid, role, *queue_ids, *excl_params, *having_params, top),
    )
    out: list[dict] = []
    for champ_id, champ_name, games, wins in cur.fetchall():
        wr_pct = _pct(wins, games)
        out.append({
            "champId":   int(champ_id),
            "champName": str(champ_name or "?"),
            "games":     int(games),
            "wins":      int(wins),
            "wr_pct":    wr_pct,
            "reason":    f"{wr_pct}% WR - {games} games {reason_suffix}",
        })
    return out


def _query_performance_comfort(conn: sqlite3.Connection, puuid: str, role: str,
                               queue_ids: tuple[int, ...],
                               exclude_ids: tuple[int, ...] = (),
                               top: int = 1) -> list[dict]:
    """Operator's top-N highest-WR champions at this role with
    >=_MIN_GAMES_PICK games. ``exclude_ids`` skips banned + already-shown."""
    return _query_performance_band(
        conn, puuid, role, queue_ids,
        having_sql="games >= ?", having_params=(_MIN_GAMES_PICK,),
        reason_suffix="- safe pick", exclude_ids=exclude_ids, top=top)


def _query_performance(conn: sqlite3.Connection, puuid: str, role: str,
                       queue_ids: tuple[int, ...],
                       exclude_ids: tuple[int, ...] = (),
                       top: int = 1) -> list[dict]:
    """Raw top-N picks by score (A3, QA 2026-07-03): the operator's
    highest-WR champions at this role with >= _MIN_GAMES_PICK games,
    with ``exclude_ids`` cascade-filtering out banned + already-picked
    + already-shown ids. The s209 mood dispatcher (comfort / limit /
    new / synergy) that used to live here was removed with the mood UI;
    this is the former "comfort" query, kept under the stable
    entrypoint name."""
    return _query_performance_comfort(
        conn, puuid, role, queue_ids, exclude_ids, top)


# --------------------------------------------------------------------
# Item 168 (2026-05-24): P&B panel restructured to 3 stacked sub-panels.
# Helpers below feed the new shape:
#   * ``_query_last_in_queue``   - 4th pick = operator's most-recent
#                                  champion in the SAME queue_id.
#   * ``_query_struggle_ban``    - 4th ban = operator's at-role highest
#                                  loss-rate enemy with >=2 encounters.
#   * ``_compose_cleanse_advisory`` - dynamic explanation prose hooking
#                                  into enemy-team CC pressure. Runs at
#                                  request time (not cached) so the line
#                                  shifts as enemies lock in.
# Each is best-effort; on engine miss/db miss the field returns None
# instead of 500-ing the whole endpoint.
# --------------------------------------------------------------------


def _query_last_in_queue(conn: sqlite3.Connection, puuid: str,
                          queue_ids: tuple[int, ...],
                          exclude_ids: tuple[int, ...] = ()) -> dict | None:
    """Operator's most-recently-played champion in matches whose queue_id
    is in ``queue_ids``. When the panel passes the live queue_id (e.g.
    420 Ranked Solo) the result is the operator's last Ranked Solo champ,
    answering "what did I play last time in this queue". ``exclude_ids``
    skips any champ already banned/picked in the current draft.
    """
    if not queue_ids:
        return None
    placeholders = ",".join("?" * len(queue_ids))
    excl_sql, excl_params = _exclude_clause(exclude_ids, "p.champion_id")
    cur = conn.execute(
        f"""
        SELECT p.champion_id, p.champion_name, p.win,
               m.game_creation_ts
        FROM participants p
        JOIN matches m ON m.match_id = p.match_id
        WHERE p.puuid = ?
          AND m.queue_id IN ({placeholders})
          {excl_sql}
        ORDER BY m.game_creation_ts DESC, p.champion_id ASC
        LIMIT 1
        """,
        (puuid, *queue_ids, *excl_params),
    )
    row = cur.fetchone()
    if not row:
        return None
    champ_id, champ_name, win, ts = row
    return {
        "champId":   int(champ_id),
        "champName": str(champ_name or "?"),
        "games":     1,
        "wins":      int(win or 0),
        "wr_pct":    100 if win else 0,
        "reason":    "last played in this queue"
                     + (" - won" if win else " - lost"),
        "source":    "last_in_queue",
    }


def _query_loss_matchups(conn: sqlite3.Connection, puuid: str, role: str,
                         queue_ids: tuple[int, ...], *, limit: int,
                         exclude_ids: tuple[int, ...] = ()) -> list[dict]:
    """Shared self-join body for ban recommendations: enemy champions in
    the operator's role on the opposing team, ranked by the operator's
    loss rate against them. Filtered to >=_MIN_GAMES_BAN encounters and a
    >50% loss rate (a matchup the operator wins half-or-more is not a
    threat). Returns up to ``limit`` rows {champId,name,encounters,losses,
    pct}, tie-broken by more encounters then champion_id. ``exclude_ids``
    skips champs already on the board."""
    placeholders = ",".join("?" * len(queue_ids))
    excl_sql, excl_params = _exclude_clause(exclude_ids, "enemy.champion_id")
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
          {excl_sql}
        GROUP BY enemy.champion_id
        HAVING encounters >= ?
        ORDER BY (CAST(losses AS REAL) / encounters) DESC,
                 encounters DESC, enemy.champion_id ASC
        LIMIT ?
        """,
        (puuid, role, *queue_ids, *excl_params, _MIN_GAMES_BAN, limit),
    )
    out: list[dict] = []
    for champ_id, champ_name, encounters, losses in cur.fetchall():
        if not encounters:
            continue
        pct = _pct(losses, encounters)
        if pct < _BAN_MIN_LOSS_PCT:
            continue
        out.append({
            "champId":    int(champ_id),
            "name":       str(champ_name or "?"),
            "encounters": int(encounters),
            "losses":     int(losses),
            "pct":        pct,
        })
    return out


def _query_struggle_ban(conn: sqlite3.Connection, puuid: str, role: str,
                         queue_ids: tuple[int, ...],
                         exclude_ids: tuple[int, ...] = ()) -> dict | None:
    """Operator's single highest loss-rate enemy at this role with
    >=_MIN_GAMES_BAN encounters and >50% loss rate - the lane matchup they
    personally lose to most. Excludes champs already banned. None when no
    qualifying struggle exists."""
    rows = _query_loss_matchups(conn, puuid, role, queue_ids,
                                limit=1, exclude_ids=exclude_ids)
    if not rows:
        return None
    top = rows[0]
    top["source"] = "struggle"
    return top


def _compose_cleanse_advisory(enemy_cids: tuple[int, ...],
                               my_summoners: tuple[int, ...]) -> str | None:
    """Heuristic CC-cleanse advisory. Reads enemy locked champs, counts
    heavy-CC sources (stun/root/charm/fear/snare>=1.0s per champion
    based on the DS engine's per-spell CC registry). When the count
    crosses 3 and the operator's summoner pair doesn't already include
    Cleanse (id 1), surface a short prose tip.

    Returns None when nothing to say (CC count below threshold OR
    cleanse already equipped OR engine module unimportable).
    """
    if not enemy_cids:
        return None
    try:
        # Cycle-8 audit: the registry lives in the _per_spell_cc
        # submodule (agents/daemon_slayer/_per_spell_cc.py), NOT the
        # package root - the old package-root import raised ImportError
        # and the swallow below kept this advisory silently dead.
        from agents.daemon_slayer import cc_conditional as _cc_cond
        from agents.daemon_slayer._per_spell_cc import (
            _PER_SPELL_CC_DURATIONS,
        )
    except Exception:  # noqa: BLE001
        return None
    try:
        # Registry keys are canonical DDragon ids ("TwistedFate",
        # "MonkeyKing"); DDragon hands us display names ("Twisted
        # Fate", "Wukong"). Same bridge routes_peel_priority uses.
        from core.archetype_picks import canonical_champion_id as _canon
    except Exception:  # noqa: BLE001
        def _canon(n: str) -> str:
            return n
    # Reverse champion-id -> name via DDragon dictionary (already
    # loaded as a module-level cache by _load_champ_id_to_name).
    id_to_name = _load_champ_id_to_name()
    heavy_cc_champs: list[str] = []
    HEAVY_THRESHOLD = 1.0  # seconds of single-spell hard CC
    for cid in enemy_cids:
        name = id_to_name.get(int(cid))
        if not name:
            continue
        canon = _canon(name) or name
        per_spell = (_PER_SPELL_CC_DURATIONS.get(canon)
                     or _PER_SPELL_CC_DURATIONS.get(name) or {})
        # Conditional entries (from cc_conditional) also count if
        # their CC duration crosses threshold.
        cond_entries = _cc_cond.get_conditional_entries(canon) if hasattr(
            _cc_cond, "get_conditional_entries") else []
        max_cc = 0.0
        for spell_key, durations in per_spell.items():
            if not durations:
                continue
            # durations may be list-of-floats (per-rank); take the max.
            try:
                m = max(float(d) for d in durations if d is not None)
                if m > max_cc:
                    max_cc = m
            # ValueError: empty after the None filter, or float("x").
            # TypeError: durations not iterable, or a non-coercible element.
            except (TypeError, ValueError, AttributeError):
                continue
        for entry in cond_entries:
            # ConditionalCcEntry carries per-rank ``durations_s`` (the
            # old ``duration_seconds`` getattr never existed -> 0.0).
            try:
                durs = getattr(entry, "durations_s", ()) or ()
                d = max((float(x) for x in durs if x is not None),
                        default=0.0)
                if d > max_cc:
                    max_cc = d
            # AttributeError: a ``durations_s`` property that itself raises.
            # TypeError / ValueError: non-iterable or non-coercible values.
            except (TypeError, ValueError, AttributeError):
                continue
        if max_cc >= HEAVY_THRESHOLD:
            heavy_cc_champs.append(name)
    if len(heavy_cc_champs) < 3:
        return None
    has_cleanse = _CLEANSE_SUMMONER_ID in (my_summoners or ())
    if has_cleanse:
        return None
    sample = ", ".join(heavy_cc_champs[:3])
    return (f"enemy CC heavy ({len(heavy_cc_champs)} champs incl. "
            f"{sample}) - consider Cleanse (D) over current spell")


def _query_bans(conn: sqlite3.Connection, puuid: str, role: str,
                queue_ids: tuple[int, ...]) -> list[dict]:
    """Top 3 enemy champions in the operator's role they have lost to most
    often (>=_MIN_GAMES_BAN encounters, >50% loss rate). Self-join: tracked
    = operator's row, enemy = the role counterpart on the opposing team."""
    return _query_loss_matchups(conn, puuid, role, queue_ids, limit=3)


# --------------------------------------------------------------------
# s239 (AUTONOMOUS_AUDIT opportunity #2): the per-user CONTEXTUAL read.
# The performance query above RECOMMENDS picks; these REPORT the operator's
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
        "wr_pct":      _pct(wins, games),
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
        out["role_wr_pct"] = _pct(rw, rg) if rg else None
    return out


def _query_co_participant(conn: sqlite3.Connection, puuid: str, champ_id: int,
                          queue_ids: tuple[int, ...], *,
                          same_team: bool,
                          with_losses: bool = False) -> dict:
    """Operator's lifetime record in matches where ``champ_id`` shared the
    board: on the operator's team (``same_team=True``, A2 - any ally,
    independent of what the operator played) or the opposing team
    (``same_team=False``, A1 - any enemy, lane-agnostic). Always returns
    an entry; ``games`` may be 0 (A5). When ``with_losses`` the dict
    carries a ``losses`` field (ban-side "how often this champ beats me")."""
    placeholders = ",".join("?" * len(queue_ids))
    if same_team:
        team_pred = "co.team_id = op.team_id\n              AND co.puuid != op.puuid"
    else:
        team_pred = "co.team_id != op.team_id"
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
            SELECT 1 FROM participants co
            WHERE co.match_id = op.match_id
              AND {team_pred}
              AND co.champion_id = ?
          )
        """,
        (champ_id, puuid, *queue_ids, champ_id),
    ).fetchone()
    games = int(games or 0)
    wins = int(wins or 0)
    champ_name = name or _load_champ_id_to_name().get(int(champ_id)) or "?"
    out: dict = {
        "champId":   int(champ_id),
        "champName": str(champ_name),
        "games":     games,
        "wins":      wins,
        "wr_pct":    _pct(wins, games),
    }
    if with_losses:
        out["losses"] = games - wins
    return out


def _query_with_ally(conn: sqlite3.Connection, puuid: str, ally_id: int,
                      queue_ids: tuple[int, ...]) -> dict:
    """Operator's lifetime record in matches where ``ally_id`` was on
    their team (A2)."""
    return _query_co_participant(conn, puuid, ally_id, queue_ids,
                                 same_team=True)


def _query_vs_enemy(conn: sqlite3.Connection, puuid: str, enemy_id: int,
                    queue_ids: tuple[int, ...]) -> dict:
    """Operator's lifetime record in matches where ``enemy_id`` was on the
    OPPOSING team, any lane (A1). Carries ``losses`` for the ban framing."""
    return _query_co_participant(conn, puuid, enemy_id, queue_ids,
                                 same_team=False, with_losses=True)


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


def _send_json(h, code: int, payload: dict) -> None:
    """Send a JSON body with the standard content type + encoding."""
    h._send(code, json.dumps(payload).encode("utf-8"), "application/json")


def _send_json_err(h, code: int, msg: str) -> None:
    """Standard error envelope: {"ok": False, "error": <msg>}."""
    _send_json(h, code, {"ok": False, "error": msg})


def _oversized(h, **id_lists: tuple[int, ...]) -> bool:
    """Reject any id list longer than ``_MAX_ID_PARAMS`` with a 400 naming
    the offending parameter, and return True so the caller returns at once.

    Over-cap is a 400 and NEVER a silent truncation: a junk *token* stays
    dropped (that is `_parse_csv_ints`'s documented contract, so a typo does
    not 400 a whole draft), but a junk *length* is not a typo - truncating
    30000 ids would serve a plausible answer to a hostile request and leave
    no trace. Kwargs order is preserved, so the first oversized parameter is
    reported deterministically.

    Callers MUST invoke this before opening a connection: the cap exists to
    stop the per-id SQL fan-out, so a rejected request has to cost zero
    queries or it buys nothing on the expensive path."""
    for name, ids in id_lists.items():
        if len(ids) > _MAX_ID_PARAMS:
            _send_json_err(
                h, 400,
                f"{name}: {len(ids)} ids exceeds the limit of "
                f"{_MAX_ID_PARAMS}")
            return True
    return False


def _parse_queue_ids(qs: dict) -> tuple[int, ...] | None:
    """?queue=420 -> (420,); ?queue=400,420 -> (400, 420); absent/blank ->
    _DEFAULT_SR_QUEUES. Returns None on a malformed value so the caller can
    400 - distinguishes bad input from "use the default set"."""
    queue_raw = (qs.get("queue") or [""])[0]
    if not queue_raw:
        return _DEFAULT_SR_QUEUES
    try:
        queue_ids = tuple(int(x) for x in queue_raw.split(",") if x.strip())
    except ValueError:
        return None
    return queue_ids or _DEFAULT_SR_QUEUES


def _cache_get(h, key: tuple, t0: float) -> bool:
    """Send a fresh cached payload for ``key`` (refreshing elapsed_ms) and
    return True on a hit; False when the caller must compute. TTL + db-mtime
    keying stays identical across both routes."""
    with _PB_CACHE_LOCK:
        hit = _PB_CACHE.get(key)
    if hit and (t0 - hit[0]) < _PB_CACHE_TTL_S:
        payload = dict(hit[1])
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        _send_json(h, 200, payload)
        return True
    return False


def _cache_put(key: tuple, t0: float, payload: dict) -> None:
    with _PB_CACHE_LOCK:
        _PB_CACHE[key] = (t0, dict(payload))
        if len(_PB_CACHE) > _PB_CACHE_MAX:
            victims = sorted(_PB_CACHE.items(),
                             key=lambda kv: kv[1][0])[:_PB_CACHE_EVICT]
            for k, _ in victims:
                _PB_CACHE.pop(k, None)


def _open_ro_with_puuid(h):
    """Open the read-only rewind connection + resolve the operator puuid.
    Returns (conn, puuid); on no-operator sends a 503, closes, and returns
    (None, None). Caller owns conn.close() via try/finally on the hit path.
    read-only uri mode: the catchup script is the only writer and WAL means
    reads don't block its writes."""
    conn = sqlite3.connect(f"file:{_REWIND_DB}?mode=ro", uri=True, timeout=2.0)
    # Cycle 41 (resource lifetime): the caller's try/finally only starts once
    # this function RETURNS, so a raise from `_resolve_operator_puuid` - a
    # corrupt file is DatabaseError, a missing `participants` table is
    # OperationalError, both reachable off a half-written db - left this
    # connection with no deterministic close on the one path that matters.
    # Close it here and re-raise; the handler's outer guard still 500s.
    try:
        puuid = _resolve_operator_puuid(conn)
    except BaseException:
        conn.close()
        raise
    if not puuid:
        conn.close()
        _send_json_err(h, 503, "no operator puuid in rewind_history.db")
        return None, None
    return conn, puuid


def _build_pickban_recs(conn, puuid, role, queue_ids,
                        exclude_ids, top):
    """Run the raw top-N pick query + the dependent ban / last-in-queue /
    struggle cascades against an open connection. Returns
    (picks, bans, last_in_queue, struggle_ban)."""
    picks = _query_performance(conn, puuid, role, queue_ids,
                               exclude_ids=exclude_ids, top=top)
    # s210 v2 / s214: bans follow the FIRST recommended pick - its
    # hard counters from champion_counters.json, else the operator's
    # role-level worst matchups.
    bans: list[dict] = []
    if picks and picks[0].get("champName"):
        bans = _counters_for_champion(picks[0]["champName"])
    if not bans:
        bans = _query_bans(conn, puuid, role, queue_ids)
    # Item 168: 4th pick = most-recent champ in the exact queue, excluding
    # the already-chosen picks so we don't duplicate.
    pick_excl = tuple(exclude_ids) + tuple(
        int(p.get("champId") or 0) for p in picks if p.get("champId"))
    last_in_queue = _query_last_in_queue(
        conn, puuid, queue_ids, exclude_ids=pick_excl)
    # Item 168: 4th ban = personal struggle, excluding bans[].
    ban_excl = tuple(exclude_ids) + tuple(
        int(b.get("champId") or 0) for b in bans if b.get("champId"))
    struggle_ban = _query_struggle_ban(
        conn, puuid, role, queue_ids, exclude_ids=ban_excl)
    return picks, bans, last_in_queue, struggle_ban


def _serve_pickban_recs(h) -> None:
    try:
        qs = parse_qs(urlparse(h.path).query)
        role = _normalize_role((qs.get("role") or [""])[0])
        if not role:
            _send_json_err(h, 400, "role required (TOP|JUNGLE|MIDDLE|BOTTOM|UTILITY)")
            return

        queue_ids = _parse_queue_ids(qs)
        if queue_ids is None:
            _send_json_err(h, 400, "queue must be comma-separated ints")
            return

        # A3 (QA 2026-07-03): the s209 `mood` query param is REMOVED from
        # the backend. A stray legacy `mood=` (or `allies=`, which only
        # ever fed the synergy mood) is tolerated and ignored - never a
        # 400 - so pre-A3 clients keep working.

        # s214: cascade-filter inputs. `exclude` = banned/picked/shown ids;
        # `top` = picks to return (1..5). Item 168: enemies + my_summoners
        # feed the advisory.
        exclude_ids = _parse_csv_ints((qs.get("exclude") or [""])[0])
        enemy_ids   = _parse_csv_ints((qs.get("enemies") or [""])[0])
        my_summs    = _parse_csv_ints((qs.get("my_summoners") or [""])[0])
        try:
            top_raw = int((qs.get("top") or ["1"])[0])
        except ValueError:
            top_raw = 1
        top = max(1, min(5, top_raw))

        # Cycle 41: cap before the connection. `exclude` becomes one `?`
        # placeholder per id in every query this route runs, so uncapped it
        # walks into SQLite's variable ceiling and 500s instead of naming
        # the bad input.
        if _oversized(h, queue=queue_ids, exclude=exclude_ids,
                      enemies=enemy_ids, my_summoners=my_summs):
            return

        if not _REWIND_DB.exists():
            _send_json_err(h, 503, "rewind_history.db missing")
            return

        t0 = time.time()
        cache_key = ("pickban", _db_mtime(), role, queue_ids,
                     tuple(exclude_ids), tuple(enemy_ids),
                     tuple(my_summs), top)
        if _cache_get(h, cache_key, t0):
            return
        conn, puuid = _open_ro_with_puuid(h)
        if conn is None:
            return
        try:
            picks, bans, last_in_queue, struggle_ban = _build_pickban_recs(
                conn, puuid, role, queue_ids, exclude_ids, top)
        finally:
            conn.close()
        # Item 168: cleanse advisory composed outside the DB cursor.
        cleanse_advisory = _compose_cleanse_advisory(enemy_ids, my_summs)

        # s214 response: `performance` = first pick (back-compat single
        # dict); `performance_picks` = full raw top-N list for the 3-row
        # layouts. A3: no `mood` field - picks are raw top-N by score.
        payload = {
            "ok": True,
            "role": role,
            "queue_ids": list(queue_ids),
            "performance": picks[0] if picks else None,
            "performance_picks": picks,
            "performance_bans": bans,
            # Item 168 additions; legacy fields above stay untouched.
            "last_in_queue":  last_in_queue,
            "struggle_ban":   struggle_ban,
            "cleanse_advisory": cleanse_advisory,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
        _cache_put(cache_key, t0, payload)
        _send_json(h, 200, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/champ-select/pickban-recs: %s", exc)
        # Raw exception text stays in the log only (CLAUDE.md error rule).
        _send_json_err(h, 500, "internal error - see logs")


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

        queue_ids = _parse_queue_ids(qs)
        if queue_ids is None:
            _send_json_err(h, 400, "queue must be comma-separated ints")
            return

        # Cycle 41: cap before the connection. This route is the sharp one -
        # one correlated-subquery per ally id and per enemy id.
        if _oversized(h, allies=ally_ids, enemies=enemy_ids,
                      queue=queue_ids):
            return

        if not _REWIND_DB.exists():
            _send_json_err(h, 503, "rewind_history.db missing")
            return

        t0 = time.time()
        cache_key = ("personal", _db_mtime(), champ_id, role,
                     tuple(ally_ids), tuple(enemy_ids), queue_ids)
        if _cache_get(h, cache_key, t0):
            return
        conn, puuid = _open_ro_with_puuid(h)
        if conn is None:
            return
        try:
            champ = (_query_champ_record(conn, puuid, champ_id, queue_ids, role)
                     if champ_id else None)
            with_allies = [_query_with_ally(conn, puuid, a, queue_ids)
                           for a in ally_ids]
            vs_enemies = [_query_vs_enemy(conn, puuid, e, queue_ids)
                          for e in enemy_ids]
        finally:
            conn.close()

        payload = {
            "ok": True,
            "queue_ids": list(queue_ids),
            "role": role,
            "champ": champ,
            "with_allies": with_allies,
            "vs_enemies": vs_enemies,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
        _cache_put(cache_key, t0, payload)
        _send_json(h, 200, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/champ-select/personal-record: %s", exc)
        _send_json_err(h, 500, "internal error - see logs")


def _serve_counter_picks(h) -> None:
    """RC2 E4 (P2) - GET /api/champ-select/counter-picks. Given the live
    enemy comp (``enemies`` = locked enemy championIds) and the operator's
    already picked/banned ids (``exclude``), return the top counter picks
    for the operator's OPEN slot - the at-a-glance "pick into this comp"
    list. ``role`` is accepted for parity with pickban-recs (and future
    role-aware filtering) but the counters index is role-agnostic today.

    Reads only the counters index + DDragon name maps (no rewind_history.db
    query), so it stays cheap + always available even when the operator
    history DB is missing.
    """
    try:
        qs = parse_qs(urlparse(h.path).query)
        enemy_ids = _parse_csv_ints((qs.get("enemies") or [""])[0])
        exclude_ids = _parse_csv_ints((qs.get("exclude") or [""])[0])
        # role is optional + advisory only; normalize for the echo field.
        role = _normalize_role((qs.get("role") or [""])[0])
        try:
            top_raw = int((qs.get("top") or ["5"])[0])
        except ValueError:
            top_raw = 5
        limit = max(1, min(5, top_raw))

        # Cycle 41: in-memory walk rather than SQL, but still O(n) over
        # attacker-sized input on a shared handler thread - same cap.
        if _oversized(h, enemies=enemy_ids, exclude=exclude_ids):
            return

        counters = _counters_vs_comp(enemy_ids, exclude_ids, limit=limit)
        # Attach a champion icon path so the JS renders the portrait without
        # a second id->slug round-trip. DDragon slug = the counters index
        # display name resolved back through name->id is the numeric id; the
        # JS already owns CHAMPS.byId for the slug, so we pass champId only.
        payload = {
            "ok": True,
            "role": role,
            "enemy_ids": list(int(x) for x in enemy_ids if int(x) > 0),
            "counters": counters,
        }
        _send_json(h, 200, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/champ-select/counter-picks: %s", exc)
        _send_json_err(h, 500, "internal error - see logs")


def _serve_team_damage_mix(h) -> None:
    """LIFT 1b - GET /api/champ-select/team-damage-mix?team_ids=103,64,...
    Returns the operator ally team's physical-vs-magic damage lean (summed
    info.attack / info.magic). Pure read off the DDragon info map - no
    rewind_history.db query, so it stays cheap + always available."""
    try:
        qs = parse_qs(urlparse(h.path).query)
        team_ids = _parse_csv_ints((qs.get("team_ids") or [""])[0])
        # Cycle 41: a team is 5 champions; the cap keeps the echo list and
        # the sum bounded by the same rule as every sibling route.
        if _oversized(h, team_ids=team_ids):
            return
        payload = _compute_team_damage_mix(team_ids)
        _send_json(h, 200, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/champ-select/team-damage-mix: %s", exc)
        # Raw exception text stays in the log only (CLAUDE.md error rule).
        _send_json_err(h, 500, "internal error - see logs")


# Route table - imported by dashboard/_dispatch.py at module load.

def _equals(p: str):
    """Local copy of routes_coach._equals to avoid the cross-import."""
    def m(path: str) -> bool: return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/champ-select/pickban-recs"), _serve_pickban_recs),
    (_equals("/api/champ-select/personal-record"), _serve_personal_record),
    (_equals("/api/champ-select/counter-picks"), _serve_counter_picks),
    (_equals("/api/champ-select/team-damage-mix"), _serve_team_damage_mix),
]
