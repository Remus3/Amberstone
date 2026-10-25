# arch: TFT view API (live round, matches, match digest, icons, scouting, engine) + /api/state tft_context | section=dashboard | frozen=no
"""TFT-09 (docs/TFT_PROGRAM.md section 4 + section 7): the read-only JSON routes
the TFT LOBBY / IN-MATCH / POST-MATCH views consume, and the one TFT context
authority on /api/state (`tft_context`, section 4.1).

ROUTES (shapes: docs/API.md "TFT view endpoints")
  GET  /api/tft/live                  open match: latest round bundle, per-round
                                      series, all-8 opponents (HP series, last board)
  GET  /api/tft/matches[?limit=N]     finished + open matches, newest first
  GET  /api/tft/match/<id>[?raw=1]    one match: per-round store doc + the RM-616
       [?fixture=<name>]              post-game record + the engine digest; a
                                      scrubbed fixture instead with ?fixture=
  GET  /api/tft/icon/<cat>/<api>      a cached icon (tft/assets/icon_cache.py);
       [?set=N]                       404 when it is not cached
  GET  /api/tft/scouting              the opponent scouting digest
                                      (data/tft_scouting.json, tft/tft_scouting.py)
  GET  /api/tft/engine/recommend      engine answer on the latest captured round;
       [?comp=<comp_id>&set=N]        withheld while a game is live (B4, RM-189)
  GET  /api/tft/engine/milestones     per-comp top-4 milestones + catalogue rows
  GET  /api/tft/engine/planner        prior-top-4 planner choices with digests
  POST /api/tft/match/<id>/export     scrubbed fixture into data/tft/exports/

DATA SOURCES. The per-round store `data/tft/tft_rounds.db` (tft/rounds, TFT-01;
opened READ-ONLY here, one short-lived connection per read) and the RM-616
post-game store `data/tft_matches/` (tft/tft_placement.py; placement + final
boards of all 8). A match id is the store's match_id; a match only the RM-616
store knows is addressed by its game id (digits).

FAIL-SOFT. A missing or unreadable store reads as empty with a "store" status,
never as an error; an unexpected failure is a 500 with a fixed message and the
raw exception goes to the log only (CLAUDE.md error-handling rule).

NO BLOCKING CALLS ON THE REQUEST THREAD. No route here makes a network call
(no LCU, Riot or CommunityDragon request), starts a subprocess or waits on
another thread. Request-thread work is bounded local reads: one match from the
store, at most `limit` match rows, one icon file. The engine catalogue and
milestones span the operator's whole history, so they are built on a daemon
thread (single-flight per set, re-checked every ENGINE_RECHECK_S) and the routes
serve the last built model ("warming" until the first build lands).

TFT CONTEXT. `tft_context(...)` is called by dashboard/_state_builder.py once
per /api/state build with values that function already holds; it reads no file
except a throttled stat of the RM-616 store directory, and the newest-record
read behind it runs on a daemon thread. Shape (section 4.1):
    {"active": bool, "phase": "lobby" | "match" | "post" | None,
     "queue_id": int | None,
     "source": "mode_key" | "lcu_queue" | "standalone" | "last_match" | None}
  match  - mode_key "tft" from a live flag (source mode_key) or the S134 P0
           standalone verdict (source standalone: the served liveclient summary
           is the standalone one). queue_id = the in-game LCU queue. While the
           flag is still up but the client phase is already post-game
           (PreEndOfGame / EndOfGame / WaitingForStats) the phase is "post".
  lobby  - mode_key "tft" from the LCU lobby / champ-select pre-flip (source
           lcu_queue, queue id via core/queue_modes.py).
  post   - nothing else claims the context, the client phase is post-game or
           idle, and the last finished match is TFT: seen live by this process
           (source = how it was seen) or, after a restart, the newest RM-616
           record ended within POST_WINDOW_S (source last_match). A live
           non-TFT game seen later ends it; so does a lobby / queue phase.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from dashboard._matchers import equals

log = logging.getLogger("rc.web_dashboard")

REPO_ROOT = Path(__file__).resolve().parent.parent
# Committed scrubbed fixtures (tests/fixtures/tft_rounds/, docs/TFT_PROGRAM.md
# section 2) are looked up first, then the local exports dir.
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "tft_rounds"

# Seams (tests point these at tmp_path). None = the store module's default.
ROUNDS_DB_PATH: Optional[Path] = None
EXPORTS_DIR: Optional[Path] = None

LIVE_STALE_AFTER_S = 120.0   # a round older than this is not "live"
LIVE_MIN_INTERVAL_S = 1.0    # /api/tft/live rebuilds at most this often
MATCHES_DEFAULT_LIMIT = 50
MATCHES_MAX_LIMIT = 200
ENGINE_RECHECK_S = 30.0      # engine model re-check cadence (background)
POST_WINDOW_S = 1800.0       # how long after a TFT match ends "post" can hold
POST_STORE_CHECK_S = 5.0     # RM-616 store-dir stat throttle on /api/state
ICON_MAX_BYTES = 4 * 1024 * 1024
ICON_CACHE_MAX = 2048
ICON_CACHE_CONTROL = "private, max-age=3600"

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_FIXTURE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_API_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
_GAME_FILE_RE = re.compile(r"^([1-9][0-9]{0,18})\.(?:eog|history)\.json$")
_MATCH_PATH_RE = re.compile(r"^/api/tft/match/([^/]+)$")
_EXPORT_PATH_RE = re.compile(r"^/api/tft/match/([^/]+)/export$")
_ICON_PATH_RE = re.compile(r"^/api/tft/icon/([^/]+)/([^/]+)$")

_DROP_RAW = ("obs", "frames")          # raw evidence: served only with ?raw=1
_UNIT_PHASE_ORDER = ("planning_end", "combat", "planning_start", "carousel")
_SERIES_DROP = ("units", "shop", "odds", "traits", "augments", "players", "events",
                "frames", "obs")

INTERNAL_ERROR = {"ok": False, "error": "internal error - see logs"}


# ------------------------------------------------------------------ helpers


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=True, default=str).encode("ascii")


def _send_json(h, code: int, obj: Any) -> None:
    h._send(code, _dumps(obj), "application/json")


def _split(h) -> tuple[str, dict]:
    parts = urlsplit(getattr(h, "path", "") or "")
    return parts.path, parse_qs(parts.query or "")


def _q(qs: dict, name: str) -> Optional[str]:
    vals = qs.get(name)
    return vals[0] if vals else None


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _flag(qs: dict, name: str) -> bool:
    return (_q(qs, name) or "").strip().lower() in ("1", "true", "yes")


def _clamp_limit(raw: Optional[str]) -> int:
    n = _int(raw)
    if n is None:
        return MATCHES_DEFAULT_LIMIT
    return max(1, min(MATCHES_MAX_LIMIT, n))


def _rounds_db_path() -> Path:
    if ROUNDS_DB_PATH is not None:
        return Path(ROUNDS_DB_PATH)
    from tft.rounds import store as st
    return st.default_db_path()


def _exports_dir() -> Path:
    if EXPORTS_DIR is not None:
        return Path(EXPORTS_DIR)
    from tft.rounds import store as st
    return st.default_exports_dir()


def _open_store():
    """(store, status): a READ-ONLY RoundStore and "ok", or (None, "absent" /
    "error"). Never raises; nothing is created when the file is missing."""
    path = _rounds_db_path()
    try:
        if not path.is_file():
            return None, "absent"
        from tft.rounds.store import RoundStore
        store = RoundStore.open(path, readonly=True)
    except Exception as exc:  # noqa: BLE001 - a broken store reads as empty
        log.warning("api/tft: rounds store unavailable: %s", exc)
        return None, "error"
    if not store.ok:
        log.info("api/tft: rounds store not readable (%s)", store.error)
        return None, "error"
    return store, "ok"


def _db_marker() -> tuple:
    """Changes whenever the store file or its WAL is written (cheap stats)."""
    path = _rounds_db_path()
    out = []
    for p in (path, path.with_name(path.name + "-wal")):
        try:
            s = p.stat()
            out.append((s.st_mtime_ns, s.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def _strip(doc: Any, keys=_DROP_RAW) -> Any:
    """Deep copy of a store document without the raw-evidence lists."""
    if isinstance(doc, dict):
        return {k: _strip(v, keys) for k, v in doc.items() if k not in keys}
    if isinstance(doc, list):
        return [_strip(v, keys) for v in doc]
    return doc


def _envelope(row: Any, name: str):
    """A store envelope value when it counts as evidence (tft/engine rule)."""
    try:
        from tft.engine.comps import envelope_value
        return envelope_value(row, name)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------- RM-616 store


def _rm616():
    from tft import tft_placement
    return tft_placement


def _rm616_game_ids() -> list:
    """Game ids in the RM-616 store, newest (highest id) first. Riot game ids
    grow over time, so this bounds a listing without loading every record.
    tft_placement has no public lister; its store dir is the module's
    `_STORE_DIR` (the attribute tests/conftest.py redirects)."""
    store_dir = Path(_rm616()._STORE_DIR)
    try:
        names = [e.name for e in store_dir.iterdir() if e.is_file()]
    except OSError:
        return []
    ids = {int(m.group(1)) for m in map(_GAME_FILE_RE.match, names) if m}
    return sorted(ids, reverse=True)


def _rm616_load(game_id) -> Optional[dict]:
    gid = _int(game_id)
    if not gid or gid <= 0:
        return None
    try:
        rec = _rm616().load(gid)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/tft: post-game record unreadable: %s", exc)
        return None
    return rec if isinstance(rec, dict) else None


def _rm616_set(rec: dict) -> Optional[int]:
    n = _int(rec.get("set_number"))
    if n:
        return n
    try:
        from tft import tft_set
        return tft_set.parse_set_id(rec.get("set_core_name"))
    except Exception:  # noqa: BLE001
        return None


def _queue_kind(queue_id) -> Optional[str]:
    q = _int(queue_id)
    if q is None:
        return None
    try:
        from tft.rounds import schema as rs
        return rs.queue_kind_for(q)
    except Exception:  # noqa: BLE001
        return None


def _local_player(rec: Optional[dict]) -> dict:
    players = rec.get("players") if isinstance(rec, dict) else None
    for p in players or []:
        if isinstance(p, dict) and p.get("is_local"):
            return p
    return {}


# ------------------------------------------------------------ match rows


def _summary_from_store(m: dict) -> dict:
    placement = _int(_envelope(m, "placement"))
    return {
        "id": m.get("match_id"), "match_id": m.get("match_id"),
        "game_id": _int(m.get("game_id")), "set_id": _int(m.get("set_id")),
        "queue_id": _int(m.get("queue_id")), "queue_kind": m.get("queue_kind"),
        "placement": placement,
        "placement_src": m.get("placement_src") if placement is not None else None,
        "started_at": _num(m.get("started_at")), "ended_at": _num(m.get("ended_at")),
        "open": m.get("ended_at") is None, "gt_status": m.get("gt_status"),
        "sources": ["rounds_db"],
    }


def _summary_from_rm616(rec: dict) -> dict:
    gid = _int(rec.get("game_id"))
    return {
        "id": str(gid) if gid else None, "match_id": None, "game_id": gid,
        "set_id": _rm616_set(rec), "queue_id": _int(rec.get("queue_id")),
        "queue_kind": _queue_kind(rec.get("queue_id")),
        "placement": _int(rec.get("local_placement")),
        "placement_src": "lcu" if _int(rec.get("local_placement")) is not None else None,
        "started_at": None, "ended_at": _num(rec.get("ended_at_effective_unix")),
        "open": False, "gt_status": None,
        "sources": list(rec.get("sources") or []),
    }


def _merge_summary(row: dict, rec: Optional[dict]) -> dict:
    """A store row enriched by its RM-616 record (same game id)."""
    if not rec:
        return row
    side = _summary_from_rm616(rec)
    out = dict(row)
    if out["placement"] is None and side["placement"] is not None:
        out["placement"], out["placement_src"] = side["placement"], side["placement_src"]
    if out["ended_at"] is None and not out["open"]:
        out["ended_at"] = side["ended_at"]
    for k in ("set_id", "queue_id", "queue_kind"):
        if out[k] is None:
            out[k] = side[k]
    out["sources"] = out["sources"] + [s for s in side["sources"] if s not in out["sources"]]
    return out


def _sort_key(row: dict):
    return -(row.get("ended_at") or row.get("started_at") or 0.0), str(row.get("id") or "")


def build_matches(limit: int = MATCHES_DEFAULT_LIMIT) -> dict:
    """GET /api/tft/matches payload (bounded: `limit` rows per source)."""
    store, status = _open_store()
    store_rows = store.list_matches() if store is not None else []
    gids = _rm616_game_ids()[:limit]
    recs = {}
    for gid in gids:
        rec = _rm616_load(gid)
        if rec is not None:
            recs[gid] = rec
    rows = []
    for m in store_rows[:limit]:
        row = _summary_from_store(m)
        rows.append(_merge_summary(row, recs.pop(row["game_id"], None) if row["game_id"] else None))
    rows.extend(_summary_from_rm616(rec) for rec in recs.values())
    rows.sort(key=_sort_key)
    rows = rows[:limit]
    return {"ok": True, "store": status, "postgame_store": "ok" if gids else "empty",
            "count": len(rows), "matches": rows}


# ------------------------------------------------------------ /api/tft/live

_LIVE_LOCK = threading.Lock()
_LIVE_CACHE: dict = {"key": None, "at": 0.0, "payload": None}


def _round_ts(rnd: dict) -> Optional[float]:
    vals = [_num(rnd.get(k)) for k in ("planning_ts", "combat_ts", "end_ts")]
    for key in ("events", "shop", "obs", "frames"):
        vals.extend(_num(r.get("ts")) for r in rnd.get(key) or [] if isinstance(r, dict))
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def _series_row(rnd: dict) -> dict:
    return {k: v for k, v in rnd.items() if k not in _SERIES_DROP}


def _unit_view(u: dict) -> dict:
    keys = ("zone", "hex_row", "hex_col", "bench_idx", "champion_api", "star", "items",
            "cost", "conf", "src", "pos_conf", "pos_src")
    return {k: u.get(k) for k in keys}


def _latest_phase_units(units: list, player_key: str, zones=("board",)) -> list:
    """One player's unit rows from the most final phase present in a round."""
    mine = [u for u in units if isinstance(u, dict) and u.get("player_key") == player_key
            and u.get("zone") in zones]
    for phase in _UNIT_PHASE_ORDER:
        rows = [u for u in mine if u.get("phase") == phase]
        if rows:
            return rows
    return []


def _opponents(players: list, rounds: list) -> list:
    out = []
    for p in players:
        key = p.get("player_key")
        if not isinstance(key, str):
            continue
        hp_series, last = [], None
        for rnd in rounds:
            for pr in rnd.get("players") or []:
                if pr.get("player_key") == key and pr.get("hp") is not None:
                    hp_series.append([rnd.get("round_seq"), pr.get("hp")])
            board = _latest_phase_units(rnd.get("units") or [], key)
            if board:
                last = (rnd.get("round_seq"), board)
        latest = {}
        for rnd in reversed(rounds):
            row = next((pr for pr in rnd.get("players") or [] if pr.get("player_key") == key), None)
            if row is not None:
                latest = row
                break
        out.append({
            "player_key": key, "slot": p.get("slot"), "is_local": bool(p.get("is_local")),
            "hp": latest.get("hp"), "level_badge": latest.get("level_badge"),
            "alive": latest.get("alive"), "standing": latest.get("standing"),
            "conf": latest.get("conf"), "src": latest.get("src"),
            "hp_series": hp_series,
            "last_board_round_seq": last[0] if last else None,
            "last_board": [_unit_view(u) for u in last[1]] if last else [],
        })
    out.sort(key=lambda o: (o["hp"] is None, -(o["hp"] or 0), o["slot"] or 99))
    return out


def _empty_live(status: str, store_status: str) -> dict:
    return {"ok": True, "status": status, "store": store_status, "fresh": False,
            "age_s": None, "stale_after_s": LIVE_STALE_AFTER_S, "match": None,
            "local_key": None, "round": None, "series": [], "opponents": []}


def build_live(now: Optional[float] = None) -> dict:
    """GET /api/tft/live payload: the open match of the per-round store."""
    now = time.time() if now is None else now
    store, status = _open_store()
    if store is None:
        return _empty_live("no_match", status)
    open_rows = [m for m in store.list_matches() if m.get("ended_at") is None]
    if not open_rows:
        return _empty_live("no_match", status)
    doc = store.get_match(open_rows[0]["match_id"])
    if not doc:
        return _empty_live("no_match", status)
    rounds = doc.get("rounds") or []
    players = doc.get("players") or []
    local_key = next((p.get("player_key") for p in players if p.get("is_local")), None)
    out = _empty_live("no_round", status)
    out.update(match=_summary_from_store(doc["match"]), local_key=local_key,
               series=[_series_row(r) for r in rounds],
               opponents=_opponents(players, rounds))
    if rounds:
        latest = rounds[-1]
        ts = _round_ts(latest)
        age = round(max(0.0, now - ts), 3) if ts is not None else None
        fresh = age is not None and age <= LIVE_STALE_AFTER_S
        out.update(round=_strip(latest), age_s=age, fresh=fresh,
                   status="live" if fresh else "stale")
    return out


def _live_cached(now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    key = _db_marker()
    with _LIVE_LOCK:
        if (_LIVE_CACHE["payload"] is not None and _LIVE_CACHE["key"] == key
                and now - _LIVE_CACHE["at"] < LIVE_STALE_AFTER_S):
            return _refresh_age(_LIVE_CACHE["payload"], _LIVE_CACHE["at"], now)
        if (_LIVE_CACHE["payload"] is not None
                and now - _LIVE_CACHE["at"] < LIVE_MIN_INTERVAL_S):
            return _refresh_age(_LIVE_CACHE["payload"], _LIVE_CACHE["at"], now)
    payload = build_live(now)
    with _LIVE_LOCK:
        _LIVE_CACHE.update(key=key, at=now, payload=payload)
    return payload


def _refresh_age(payload: dict, built_at: float, now: float) -> dict:
    """A cached live payload with its age / freshness moved to `now`."""
    out = dict(payload)
    if out.get("age_s") is not None:
        age = round(out["age_s"] + max(0.0, now - built_at), 3)
        out["age_s"] = age
        out["fresh"] = age <= LIVE_STALE_AFTER_S
        if out.get("status") in ("live", "stale"):
            out["status"] = "live" if out["fresh"] else "stale"
    return out


# ------------------------------------------------------- /api/tft/match/<id>


def _find_store_doc(store, ident: str) -> Optional[dict]:
    doc = store.get_match(ident)
    if doc:
        return doc
    gid = _int(ident)
    if gid:
        for m in store.list_matches():
            if _int(m.get("game_id")) == gid:
                return store.get_match(m["match_id"])
    return None


def _load_fixture(name: str) -> Optional[dict]:
    """A scrubbed fixture document by name, or None. The scrub guard runs on
    every load, so an unscrubbed file is never served."""
    if not _FIXTURE_RE.fullmatch(name or ""):
        return None
    from tft.rounds.store import scrub_violations
    for base in (FIXTURE_DIR, _exports_dir()):
        p = Path(base) / f"{name}.json"
        try:
            if not p.is_file():
                continue
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("api/tft: fixture unreadable: %s", exc)
            return None
        meta = doc.get("fixture") if isinstance(doc, dict) else None
        if not (isinstance(meta, dict) and meta.get("kind") == "tft_rounds_fixture"):
            return None
        if scrub_violations(doc):
            log.warning("api/tft: fixture %s refused by the scrub guard", name)
            return None
        return doc
    return None


def build_match(ident: str, *, raw: bool = False, fixture: Optional[str] = None) -> tuple[int, dict]:
    """(http status, payload) for GET /api/tft/match/<id>."""
    if fixture is not None:
        doc = _load_fixture(fixture)
        if doc is None:
            return 404, {"ok": False, "found": False, "id": fixture, "error": "fixture_not_found"}
        return 200, {"ok": True, "found": True, "id": fixture, "source": "fixture",
                     "match": _summary_from_store(doc.get("match") or {}),
                     "rounds_db": doc if raw else _strip(doc), "postgame": None,
                     "engine": {"status": "fixture"}}
    if not _ID_RE.fullmatch(ident or ""):
        return 404, {"ok": False, "found": False, "id": None, "error": "bad_id"}
    store, status = _open_store()
    doc = _find_store_doc(store, ident) if store is not None else None
    gid = _int((doc or {}).get("match", {}).get("game_id")) if doc else _int(ident)
    rec = _rm616_load(gid) if gid else None
    if doc is None and rec is None:
        return 404, {"ok": False, "found": False, "id": ident, "store": status,
                     "error": "not_found"}
    if doc is not None:
        summary = _merge_summary(_summary_from_store(doc["match"]), rec)
    else:
        summary = _summary_from_rm616(rec)
    return 200, {"ok": True, "found": True, "id": summary["id"], "source": "store",
                 "store": status, "match": summary,
                 "rounds_db": (doc if raw else _strip(doc)) if doc is not None else None,
                 "postgame": rec, "engine": engine_match_digest(summary)}


def export_match(ident: str, body: Any) -> tuple[int, dict]:
    """(http status, payload) for POST /api/tft/match/<id>/export."""
    if not _ID_RE.fullmatch(ident or ""):
        return 404, {"ok": False, "error": "bad_id"}
    name = body.get("name") if isinstance(body, dict) else None
    if name is not None and not (isinstance(name, str) and _FIXTURE_RE.fullmatch(name)):
        return 400, {"ok": False, "error": "bad_name"}
    store, status = _open_store()
    if store is None:
        return 503, {"ok": False, "error": "store_unavailable", "store": status}
    doc = _find_store_doc(store, ident)
    if doc is None:
        return 404, {"ok": False, "error": "not_found"}
    mid = doc["match"]["match_id"]
    name = name or ("tft-" + re.sub(r"[^A-Za-z0-9_-]", "-", str(mid)))[:64]
    from tft.rounds.store import ScrubError
    out_dir = _exports_dir()
    try:
        path = store.export_fixture(mid, out_dir, name=name)
    except ScrubError as exc:
        # RM-835: the reply is fixed and derived from nothing the exception
        # carries; the detail (type + the store's value-free violation paths)
        # goes to the log only.
        log.warning("api/tft: export %s refused by the scrub guard: %s: %s",
                    name, type(exc).__name__, exc)
        return 422, {"ok": False, "error": "scrub_failed"}
    except ValueError:
        return 404, {"ok": False, "error": "not_found"}
    try:
        rel = Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel = Path(path).name
    return 200, {"ok": True, "match_id": mid, "name": name, "path": rel}


# ------------------------------------------------------------ icons

_ICON_LOCK = threading.Lock()
_ICON_CACHE: dict = {}


def _icon_index_marker(n: int):
    from tft.assets import icon_cache
    try:
        return (icon_cache.set_dir(n) / icon_cache.INDEX_NAME).stat().st_mtime_ns
    except (OSError, ValueError):
        return None


def icon_file(category: str, api: str, set_hint: Optional[str] = None) -> Optional[Path]:
    """The cached icon file, or None (= 404). The index lookup is memoised per
    index-file mtime so a board of icons does not re-parse the index per icon."""
    from tft import tft_set
    from tft.assets import icon_cache
    if category not in icon_cache.CATEGORIES or not _API_RE.fullmatch(api or ""):
        return None
    n = tft_set.parse_set_id(set_hint) if set_hint else None
    if n is None:
        n = tft_set.resolve_set(None)
    marker = _icon_index_marker(n)
    if marker is None:
        return None
    key = (n, category, api, marker)
    with _ICON_LOCK:
        if key in _ICON_CACHE:
            return _ICON_CACHE[key]
    path = icon_cache.icon_path(n, category, api)
    with _ICON_LOCK:
        if len(_ICON_CACHE) >= ICON_CACHE_MAX:
            _ICON_CACHE.clear()
        _ICON_CACHE[key] = path
    return path


# ------------------------------------------------------------ scouting


def build_scouting(now: Optional[float] = None) -> dict:
    """GET /api/tft/scouting: the scouting slice's published digest, as is."""
    now = time.time() if now is None else now
    from tft import tft_scouting
    path = Path(tft_scouting.ARTIFACT_PATH)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ok": True, "available": False, "age_s": None, "scouting": None}
    except (OSError, ValueError) as exc:
        log.warning("api/tft/scouting: digest unreadable: %s", exc)
        return {"ok": True, "available": False, "age_s": None, "scouting": None}
    if not isinstance(doc, dict) or doc.get("schema") != tft_scouting.SCHEMA:
        return {"ok": True, "available": False, "age_s": None, "scouting": None}
    updated = _num(doc.get("updated_at"))
    age = round(max(0.0, now - updated), 3) if updated is not None else None
    return {"ok": True, "available": True, "age_s": age, "scouting": doc}


# ------------------------------------------------------------ engine model

_ENGINE_LOCK = threading.Lock()
_ENGINE_MODELS: dict = {}      # set id -> model
_ENGINE_CHECKED: dict = {}     # set id -> last trigger time
_ENGINE_THREADS: dict = {}     # set id -> in-flight refresh thread
_ENGINE_WARNED: dict = {"failed": False}


def _engine_set(qs: Optional[dict] = None) -> int:
    from tft import tft_set
    n = tft_set.parse_set_id(_q(qs or {}, "set")) if qs else None
    return n if n is not None else tft_set.resolve_set(None)


def _gt_local_board(doc: dict, local_key: Optional[str]) -> list:
    from tft.engine.milestones import GT_SOURCE_ORDER
    rows = [r for r in doc.get("gt_board") or [] if isinstance(r, dict)
            and (local_key is None or r.get("player_key") == local_key)]
    for source in GT_SOURCE_ORDER:
        picked = [r for r in rows if r.get("source") == source]
        if picked:
            return picked
    return rows


def _rm616_board(rec: Optional[dict]) -> list:
    out = []
    for u in _local_player(rec).get("board") or []:
        if not isinstance(u, dict) or not u.get("character_id"):
            continue
        items = [i.get("name_id") for i in u.get("items") or []
                 if isinstance(i, dict) and i.get("name_id")]
        out.append({"champion_api": u["character_id"], "star": _int(u.get("star")) or 1,
                    "items": items, "cost": _int(u.get("cost"))})
    return out


def _store_record(doc: dict, rec: Optional[dict]) -> dict:
    """One engine match record from a finished store match (comps.py shape).
    The bundle lists are flattened here because the engine's own store
    adapter (milestones.records_from_store) reads units / shop refreshes at
    match level, where get_match carries none (they live per round)."""
    m = doc["match"]
    players = doc.get("players") or []
    local_key = next((p.get("player_key") for p in players if p.get("is_local")), None)
    rounds = doc.get("rounds") or []
    # No local player row = no unit can be attributed to the operator.
    units = [u for r in rounds for u in r.get("units") or []
             if local_key is not None and u.get("player_key") == local_key]
    shops = [s for r in rounds for s in r.get("shop") or []]
    augments = [a.get("chosen_api") for r in rounds for a in r.get("augments") or []
                if isinstance(a.get("chosen_api"), str)]
    board = _rm616_board(rec) or _gt_local_board(doc, local_key)
    out = {"match_id": m["match_id"], "set_id": m.get("set_id"), "queue_kind": m.get("queue_kind"),
           "placement": m.get("placement"), "placement_conf": m.get("placement_conf"),
           "placement_src": m.get("placement_src"), "final_board": board,
           "rounds": [_series_row(r) for r in rounds], "shop_refreshes": shops, "units": units}
    if out["placement"] is None and rec is not None and _int(rec.get("local_placement")):
        out.update(placement=_int(rec["local_placement"]), placement_conf=1.0, placement_src="lcu")
    if augments:
        out["augments"] = augments
    return out


def _rm616_record(rec: dict) -> dict:
    """An engine match record from an RM-616 post-game record alone (no rounds:
    it feeds the catalogue and mines nothing - comps.py cold start)."""
    gid = _int(rec.get("game_id"))
    return {"match_id": str(gid), "set_id": _rm616_set(rec),
            "queue_kind": _queue_kind(rec.get("queue_id")),
            "placement": _int(rec.get("local_placement")), "placement_conf": 1.0,
            "placement_src": "lcu", "final_board": _rm616_board(rec),
            "rounds": [], "shop_refreshes": [], "units": []}


def _engine_key(n: int) -> tuple:
    store, _status = _open_store()
    ended = []
    if store is not None:
        for m in store.list_matches(set_id=n):
            if m.get("ended_at") is not None:
                ended.append((m.get("match_id"), m.get("ended_at"), m.get("placement"),
                              m.get("gt_status")))
    try:
        rm616 = _rm616().store_marker()
    except Exception:  # noqa: BLE001
        rm616 = None
    return (n, rm616, tuple(sorted(ended, key=lambda t: str(t[0]))))


def build_engine_model(n: int, key: Any = None) -> dict:
    """The engine model for set n: catalogue + milestones + planner from the
    store's finished matches and the RM-616 records. Heavy: daemon thread only
    (and tests)."""
    from tft.engine import comps, milestones, recommend
    setdata = comps.load_set_data(n)
    store, _status = _open_store()
    records, joined = [], set()
    if store is not None:
        for m in store.list_matches(set_id=n):
            if m.get("ended_at") is None:
                continue
            doc = store.get_match(m["match_id"])
            if not doc:
                continue
            gid = _int(m.get("game_id"))
            rec = _rm616_load(gid) if gid else None
            if gid:
                joined.add(gid)
            records.append(_store_record(doc, rec))
    for gid in _rm616_game_ids():
        if gid in joined:
            continue
        rec = _rm616_load(gid)
        if rec is not None and _rm616_set(rec) == setdata.set_id:
            records.append(_rm616_record(rec))
    catalogue = comps.build_catalogue(records, setdata)
    ms = milestones.milestones_by_comp(records, catalogue, setdata)
    planner = recommend.planner_choices(catalogue, ms, setdata)
    return {"set_id": setdata.set_id, "key": key, "built_at": time.time(),
            "setdata": setdata, "catalogue": catalogue, "milestones": ms, "planner": planner,
            "records": {r["match_id"]: r for r in records}}


def _engine_refresh(n: int) -> None:
    try:
        key = _engine_key(n)
        with _ENGINE_LOCK:
            cur = _ENGINE_MODELS.get(n)
            if cur is not None and cur.get("key") == key:
                return
        model = build_engine_model(n, key)
        with _ENGINE_LOCK:
            _ENGINE_MODELS[n] = model
            _ENGINE_WARNED["failed"] = False
    except Exception as exc:  # noqa: BLE001 - a background build must never raise
        if not _ENGINE_WARNED["failed"]:
            _ENGINE_WARNED["failed"] = True
            log.warning("api/tft/engine: model build failed: %s", exc, exc_info=True)


def engine_model(n: int, now: Optional[float] = None) -> Optional[dict]:
    """The last built model for set n (None while warming). Never blocks: a
    stale or missing model triggers one background refresh."""
    now = time.time() if now is None else now
    with _ENGINE_LOCK:
        model = _ENGINE_MODELS.get(n)
        t = _ENGINE_THREADS.get(n)
        due = now - _ENGINE_CHECKED.get(n, -1e18) >= ENGINE_RECHECK_S
        if (t is None or not t.is_alive()) and (model is None or due):
            _ENGINE_CHECKED[n] = now
            t = threading.Thread(target=_engine_refresh, args=(n,), daemon=True,
                                 name="tft-engine-refresh")
            _ENGINE_THREADS[n] = t
            t.start()
    return model


def _engine_join(timeout: float = 10.0) -> None:
    """Test seam: wait for in-flight engine refreshes."""
    with _ENGINE_LOCK:
        threads = list(_ENGINE_THREADS.values())
    for t in threads:
        t.join(timeout)


def _engine_meta() -> dict:
    from tft.engine import engine_meta
    return engine_meta()


def _live_state(live: dict, comp_id: Optional[str]) -> tuple[dict, list]:
    """(engine live state, other players' boards) from a /api/tft/live payload."""
    rnd = live.get("round") or {}
    local = live.get("local_key")
    units = rnd.get("units") or []
    board = _latest_phase_units(units, local, ("board",)) if local else []
    bench = _latest_phase_units(units, local, ("bench",)) if local else []
    shop = rnd.get("shop") or []
    offers = []
    if shop:
        offers = [{"slot": o.get("slot"), "champion_api": o.get("champion_api"),
                   "cost": o.get("cost"), "kind": o.get("kind")}
                  for o in shop[-1].get("offers") or [] if isinstance(o, dict)]
    gold = _envelope(rnd, "gold_end")
    if gold is None:
        gold = _envelope(rnd, "gold_start")
    state = {"label": rnd.get("label"), "level": _envelope(rnd, "level"), "gold": gold,
             "board": board, "bench": bench, "items": [], "offers": offers}
    if comp_id:
        state["target_comp_id"] = comp_id
    keys = {u.get("player_key") for u in units if isinstance(u, dict)} - {local}
    lobby = [b for b in (_latest_phase_units(units, k) for k in sorted(k for k in keys if k)) if b]
    return state, lobby


def _engine_status(model: Optional[dict]) -> str:
    if model is None:
        return "warming"
    return "ready" if (model["catalogue"].get("comps") or []) else "no_history"


def _live_game_now() -> bool:
    """The B4 (RM-189) predicate for a caller with no /api/state envelope in
    hand: core.live_game_gate reads the health flags (a local file)."""
    from core import live_game_gate
    return live_game_gate.live_game_now()


def build_engine_recommend(qs: dict, now: Optional[float] = None) -> dict:
    """The TFT engine's answer on the latest captured round. B4 (RM-189,
    Riot's ban on notifications that dictate player action from the current
    game state):
    shop / slam / level advice is withheld while a game is running - the
    health flags say so (core.live_game_gate) or the round is still fresh -
    so the answer is only ever served pre- or post-game."""
    n = _engine_set(qs)
    model = engine_model(n, now)
    out = dict(_engine_meta(), ok=True, set_id=n, status=_engine_status(model),
               live_status=None, suppressed=None, recommendation=None)
    if model is None:
        return out
    live = _live_cached(now)
    out["live_status"] = live.get("status")
    if live.get("round") is None:
        return out
    if live.get("fresh") or _live_game_now():
        out["suppressed"] = "live_game"
        return out
    from tft.engine import recommend
    comp = _q(qs, "comp")
    state, lobby = _live_state(live, comp if comp and _ID_RE.fullmatch(comp) else None)
    out["recommendation"] = recommend.recommend(state, model["catalogue"], model["milestones"],
                                                model["setdata"], lobby_boards=lobby or None)
    return out


def build_engine_milestones(qs: dict, now: Optional[float] = None) -> dict:
    n = _engine_set(qs)
    model = engine_model(n, now)
    out = dict(_engine_meta(), ok=True, set_id=n, status=_engine_status(model),
               milestones=None, catalogue=[])
    if model is None:
        return out
    out["milestones"] = model["milestones"]
    keys = ("comp_id", "label", "games", "placed_games", "top4_games", "avg_placement",
            "top4_rate")
    out["catalogue"] = [{k: c.get(k) for k in keys} for c in model["catalogue"].get("comps") or []]
    return out


def build_engine_planner(qs: dict, now: Optional[float] = None) -> dict:
    n = _engine_set(qs)
    model = engine_model(n, now)
    out = dict(_engine_meta(), ok=True, set_id=n, status=_engine_status(model),
               live_status=None, planner=None)
    if model is None:
        return out
    live = _live_cached(now)
    out["live_status"] = live.get("status")
    planner = model["planner"]
    if live.get("fresh") and live.get("round") is not None:
        from tft.engine import recommend
        _state, lobby = _live_state(live, None)
        if lobby:
            planner = recommend.planner_choices(model["catalogue"], model["milestones"],
                                                model["setdata"], lobby_boards=lobby)
    out["planner"] = planner
    return out


def engine_match_digest(summary: dict, now: Optional[float] = None) -> dict:
    """The post-match engine block: the comp the match was assigned to and its
    milestones against that comp's top-4 medians."""
    n = summary.get("set_id")
    if n is None:
        return {"status": "no_set"}
    model = engine_model(n, now)
    if model is None:
        return {"status": "warming"}
    rec = model["records"].get(str(summary.get("id")))
    if rec is None:
        return {"status": "not_in_catalogue"}
    from tft.engine import comps, milestones
    cat = model["catalogue"]
    comp_id = (cat.get("assignments") or {}).get(rec["match_id"])
    comp = next((c for c in cat.get("comps") or [] if c.get("comp_id") == comp_id), None)
    if comp is None:
        assigned = comps.assign_comp(rec.get("final_board"), cat, model["setdata"])
        comp_id = assigned["comp_id"] if assigned else None
        comp = next((c for c in cat.get("comps") or [] if c.get("comp_id") == comp_id), None)
    if comp is None:
        return {"status": "no_comp", "comp": None, "milestones": []}
    agg = (model["milestones"].get("comps") or {}).get(comp_id) or {}
    mined = milestones.mine_match(rec, model["setdata"])
    return {"status": "ready", "comp": {"comp_id": comp_id, "label": comp.get("label")},
            "milestones": milestones.compare_to_average(mined, agg)}


# ------------------------------------------------------------ tft_context

_IN_GAME_PHASES = frozenset({"GameStart", "InProgress", "Reconnect"})
_POST_PHASES = frozenset({"PreEndOfGame", "EndOfGame", "WaitingForStats"})
_IDLE_PHASES = frozenset({"", "None"})
_CTX_LOCK = threading.Lock()
_LATCH: dict = {"mode": None, "at": 0.0, "queue_id": None, "source": None}
_POST_STORE: dict = {"checked": -1e18, "marker": object(), "ended": None, "queue_id": None,
                     "thread": None}

INACTIVE_CONTEXT = {"active": False, "phase": None, "queue_id": None, "source": None}


def _ctx(phase: str, queue_id: Any, source: str) -> dict:
    q = _int(queue_id)
    return {"active": True, "phase": phase, "queue_id": q if q and q > 0 else None,
            "source": source}


def _lobby_queue(lcu: dict) -> Optional[int]:
    for key in ("champ_select", "lobby"):
        block = lcu.get(key)
        if isinstance(block, dict):
            q = _int(block.get("queue_id"))
            if q and q > 0:
                return q
    return None


def _post_store_refresh() -> None:
    """Daemon-thread body: the newest RM-616 record's end time + queue."""
    try:
        gids = _rm616_game_ids()
        rec = _rm616_load(gids[0]) if gids else None
        ended = _num(rec.get("ended_at_effective_unix")) if rec else None
        queue_id = _int(rec.get("queue_id")) if rec else None
    except Exception as exc:  # noqa: BLE001
        log.debug("tft_context: post-game store read failed: %s", exc)
        ended, queue_id = None, None
    with _CTX_LOCK:
        _POST_STORE.update(ended=ended, queue_id=queue_id)


def _post_store_newest(now: float) -> tuple:
    """(ended_unix, queue_id) of the newest RM-616 record, from the cache. The
    store dir is stat'ed at most every POST_STORE_CHECK_S; a change starts one
    background read and the next build sees its result."""
    with _CTX_LOCK:
        due = now - _POST_STORE["checked"] >= POST_STORE_CHECK_S
        cached = (_POST_STORE["ended"], _POST_STORE["queue_id"])
        if due:
            _POST_STORE["checked"] = now
    if not due:
        return cached
    try:
        marker = _rm616().store_marker()
    except Exception:  # noqa: BLE001
        marker = None
    with _CTX_LOCK:
        t = _POST_STORE["thread"]
        if marker != _POST_STORE["marker"] and (t is None or not t.is_alive()):
            _POST_STORE["marker"] = marker
            t = threading.Thread(target=_post_store_refresh, daemon=True,
                                 name="tft-context-post-store")
            _POST_STORE["thread"] = t
            t.start()
        return _POST_STORE["ended"], _POST_STORE["queue_id"]


def tft_context(mode_key: Any, preflip_active: bool, lcu_snapshot: Any, lc: Any = None,
                *, now: Optional[float] = None) -> dict:
    """The /api/state `tft_context` block (docs/TFT_PROGRAM.md section 4.1).
    Never raises; every value it reads is already in build_state's hands."""
    now = time.time() if now is None else now
    lcu = lcu_snapshot if isinstance(lcu_snapshot, dict) else {}
    phase = str(lcu.get("phase") or "")
    mode = str(mode_key or "client")
    if mode == "tft" and not preflip_active:
        source = "mode_key"
        try:
            from tft import tft_standalone
            if isinstance(lc, dict) and lc.get("source") == tft_standalone.SOURCE_TAG:
                source = "standalone"
        except Exception:  # noqa: BLE001
            pass
        qid = _int(lcu.get("game_queue_id"))
        with _CTX_LOCK:
            prev_q = _LATCH["queue_id"] if _LATCH["mode"] == "tft" else None
            _LATCH.update(mode="tft", at=now, queue_id=qid or prev_q, source=source)
        # The live flag can outlast the match by a poll or two: a post-game
        # client phase is "post" already (section 4.1), not "match".
        return _ctx("post" if phase in _POST_PHASES else "match", qid or prev_q, source)
    if mode == "tft":
        return _ctx("lobby", _lobby_queue(lcu), "lcu_queue")
    if mode != "client":
        if not preflip_active:          # another mode's live game ends any TFT post
            with _CTX_LOCK:
                _LATCH.update(mode=mode, at=now, queue_id=None, source=None)
        return dict(INACTIVE_CONTEXT)
    if phase not in _POST_PHASES and phase not in _IDLE_PHASES:
        return dict(INACTIVE_CONTEXT)
    with _CTX_LOCK:
        latch = dict(_LATCH)
    if latch["mode"] == "tft" and now - latch["at"] <= POST_WINDOW_S:
        return _ctx("post", latch["queue_id"], latch["source"] or "mode_key")
    ended, queue_id = _post_store_newest(now)
    if ended is None or now - ended > POST_WINDOW_S:
        return dict(INACTIVE_CONTEXT)
    if latch["mode"] not in (None, "tft") and latch["at"] > ended:
        return dict(INACTIVE_CONTEXT)
    return _ctx("post", queue_id, "last_match")


def _reset_for_tests() -> None:
    _engine_join(5.0)
    with _CTX_LOCK:
        t = _POST_STORE["thread"]
    if t is not None:
        t.join(5.0)
    with _CTX_LOCK:
        _LATCH.update(mode=None, at=0.0, queue_id=None, source=None)
        _POST_STORE.update(checked=-1e18, marker=object(), ended=None, queue_id=None,
                           thread=None)
    with _LIVE_LOCK:
        _LIVE_CACHE.update(key=None, at=0.0, payload=None)
    with _ICON_LOCK:
        _ICON_CACHE.clear()
    with _ENGINE_LOCK:
        _ENGINE_MODELS.clear()
        _ENGINE_CHECKED.clear()
        _ENGINE_THREADS.clear()
        _ENGINE_WARNED["failed"] = False


# ------------------------------------------------------------ handlers


def _guard(label: str, fn):
    def handler(h, *args):
        try:
            fn(h, *args)
        except Exception as exc:  # noqa: BLE001 - raw text to the log only
            log.warning("%s: %s", label, exc, exc_info=True)
            try:
                _send_json(h, 500, INTERNAL_ERROR)
            except Exception:  # noqa: BLE001
                pass
    return handler


def _serve_live(h) -> None:
    _send_json(h, 200, _live_cached())


def _serve_matches(h) -> None:
    _path, qs = _split(h)
    _send_json(h, 200, build_matches(_clamp_limit(_q(qs, "limit"))))


def _is_match_path(p: str) -> bool:
    return bool(_MATCH_PATH_RE.match(urlsplit(p).path))


def _serve_match(h) -> None:
    path, qs = _split(h)
    ident = unquote(_MATCH_PATH_RE.match(path).group(1))
    fixture = _q(qs, "fixture")
    code, payload = build_match(ident, raw=_flag(qs, "raw"), fixture=fixture)
    _send_json(h, code, payload)


def _is_icon_path(p: str) -> bool:
    return bool(_ICON_PATH_RE.match(urlsplit(p).path))


def _serve_icon(h) -> None:
    path, qs = _split(h)
    m = _ICON_PATH_RE.match(path)
    category, api = unquote(m.group(1)), unquote(m.group(2))
    p = icon_file(category, api, _q(qs, "set"))
    data = None
    if p is not None:
        try:
            if p.stat().st_size <= ICON_MAX_BYTES:
                data = p.read_bytes()
        except OSError:
            data = None
    # The type comes from the bytes (icon_cache.image_kind), never the file
    # name; bytes that are not an image (an error page) are never served.
    from tft.assets import icon_cache
    kind = icon_cache.image_kind(data) if data is not None else None
    if kind is None:
        _send_json(h, 404, {"ok": False, "error": "not_cached"})
        return
    ctype = "image/png" if kind == "png" else "image/jpeg"
    h._send(200, data, ctype, cache_control=ICON_CACHE_CONTROL)


def _serve_scouting(h) -> None:
    _send_json(h, 200, build_scouting())


def _serve_engine(builder):
    def serve(h) -> None:
        _path, qs = _split(h)
        _send_json(h, 200, builder(qs))
    return serve


def _is_export_path(p: str) -> bool:
    return bool(_EXPORT_PATH_RE.match(urlsplit(p).path))


def _serve_export(h, body) -> None:
    path, _qs = _split(h)
    ident = unquote(_EXPORT_PATH_RE.match(path).group(1))
    code, payload = export_match(ident, body)
    _send_json(h, code, payload)


GET_ROUTES = [
    (equals("/api/tft/live"), _guard("api/tft/live", _serve_live)),
    (equals("/api/tft/matches"), _guard("api/tft/matches", _serve_matches)),
    (_is_match_path, _guard("api/tft/match", _serve_match)),
    (_is_icon_path, _guard("api/tft/icon", _serve_icon)),
    (equals("/api/tft/scouting"), _guard("api/tft/scouting", _serve_scouting)),
    (equals("/api/tft/engine/recommend"),
     _guard("api/tft/engine/recommend", _serve_engine(build_engine_recommend))),
    (equals("/api/tft/engine/milestones"),
     _guard("api/tft/engine/milestones", _serve_engine(build_engine_milestones))),
    (equals("/api/tft/engine/planner"),
     _guard("api/tft/engine/planner", _serve_engine(build_engine_planner))),
]
POST_ROUTES = [
    (_is_export_path, _guard("api/tft/match/export", _serve_export)),
]
