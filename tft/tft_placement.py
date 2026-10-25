"""
tft/tft_placement.py - TFT placement and final boards from LCU post-game data
(RM-616).

Two LCU routes, both GET, both measured 2026-10-25 against the s134 TFT Set 18
normal game (queue 1090):

  EOG_PATH      /lol-end-of-game/v1/tft-eog-stats
                The FAST path. 200 only while the client sits in PreEndOfGame /
                EndOfGame; once it is back in Lobby it answers 404 "Game Client
                stats not found". Carries the local player's HP and the display
                names of units / items / traits.
  HISTORY_PATH  /lol-match-history/v1/products/tft/{puuid}/matches
                The DURABLE path. 200 in any phase, richer: per-player level,
                gold left, last round, elimination time and trait tiers. Used as
                backfill (RC restarts, a missed post-game window) and merged
                with the EOG record of the same game.

Neither carries augments (EOG `augments` is [] for all 8 players although 3
were taken; the history participant has no `augments` key), an HP curve, or
hex positions. Those need vision / the per-round store.

Shape traps, each pinned by tests/test_tft_placement_rm616.py:
  - EOG placement is `ffaStanding` (`rank` equals it); there is no
    `placement` key. History uses `placement`.
  - EOG `setCoreName` is "" on `localPlayer` and "TFTSet18" on the players[]
    entry whose `isLocalPlayer` is true.
  - EOG `items[].id` is 0 for every item: items are keyed by `nameId`.
  - EOG `health` is HP for the local player only; the others read 0-253,
    which is not HP, so it is stored for the local player only.
  - EOG unit `traits[]` omit emblem-granted traits: an item named
    "<Trait> Emblem" adds that trait (the HUD counts it).
  - History unit `name` is "" for every unit; `rarity` + 1 is the cost for
    rarity 0-4 (measured on all 9 local units).
  - Both routes return riot ids for other players (history: puuid zeroed for
    non-local players, the local one real). NOTHING identifying is stored:
    no name, tag, puuid, summoner id, icon or companion. The repo is PUBLIC
    and later engines join this store.

STORE. `data/tft_matches/` (gitignored), one file per (game, source):
`<gameId>.eog.json` and `<gameId>.history.json`. Append-only - a file is
never overwritten once written - and atomic (tmp + replace via
core.polled_json). Single writer: the postgame collector thread. Readers
(`load`, `latest`) merge the two sources of one game; the upcoming per-round
database / Augur engine join on `game_id`.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.polled_json import atomic_write_json

_log = logging.getLogger("rc.tft.placement")

SCHEMA_VERSION = 1
SOURCE_EOG = "eog"
SOURCE_HISTORY = "history"
_SOURCES = (SOURCE_EOG, SOURCE_HISTORY)

EOG_PATH = "/lol-end-of-game/v1/tft-eog-stats"
HISTORY_PATH = "/lol-match-history/v1/products/tft/{puuid}/matches?begin=0&count={count}"

_ROOT = Path(__file__).parent.parent
DEFAULT_STORE_REL = "data/tft_matches"
_STORE_DIR = _ROOT / "data" / "tft_matches"

_MAX_LOBBY = 8
_TS_FMT = "%Y-%m-%d %H:%M:%S"     # the match_history.db timestamp format
_FILE_RE = re.compile(r"^([1-9][0-9]{0,18})\.(eog|history)\.json$")
_STR_CAP = 120


# -- small coercions -------------------------------------------------------------

def _int(v) -> Optional[int]:
    """A real int (bool excluded) or an int-valued float / digit string."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _str(v) -> str:
    return v.strip()[:_STR_CAP] if isinstance(v, str) else ""


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _placement(v) -> Optional[int]:
    p = _int(v)
    return p if p is not None and 1 <= p <= _MAX_LOBBY else None


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime(_TS_FMT)


def _split_camel(s: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)


def display_from_id(raw: str) -> str:
    """Readable name from a client id: DA_18_Yorick -> Yorick,
    DA_Gromp18_AP -> Gromp, DA_FloraFatalis18 -> Flora Fatalis,
    TFT18_Draven -> Draven. Fallback only - EOG display names win."""
    s = _str(raw)
    s = re.sub(r"^(DA_|TFT\d*_|TFT_)", "", s)
    s = re.sub(r"^\d+_", "", s)
    s = re.sub(r"^(Item_|Augment_)", "", s)
    m = re.match(r"[A-Za-z]+", s)
    return _split_camel(m.group(0)) if m else s


# Keys that identify a person in either LCU document (and the history route's
# match / session ids). scrub_raw() drops every one of them, at any depth.
IDENTITY_KEYS = frozenset({
    "puuid", "summonerId", "summonerName", "riotIdGameName", "riotIdTagLine",
    "riotIdTagline", "iconId", "companion", "active_puuid", "accountId",
    "playerId",
})


def scrub_raw(doc):
    """Deep copy of a raw LCU document with every IDENTITY_KEYS entry removed
    and the history route's metadata.participants (a puuid list) dropped.
    The raw-document retention (RM-611) keeps THIS copy for TFT, so the
    local database never holds a riot id or puuid either."""
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            if k in IDENTITY_KEYS:
                continue
            if k == "metadata" and isinstance(v, dict):
                v = {mk: mv for mk, mv in v.items() if mk != "participants"}
            out[k] = scrub_raw(v)
        return out
    if isinstance(doc, list):
        return [scrub_raw(v) for v in doc]
    return doc


# -- session -----------------------------------------------------------------------

def session_game_id(session) -> Optional[int]:
    """gameData.gameId of a /lol-gameflow/v1/session document, else None."""
    gd = session.get("gameData") if isinstance(session, dict) else None
    gid = _int(gd.get("gameId")) if isinstance(gd, dict) else None
    return gid if gid and gid > 0 else None


def session_is_tft(session) -> bool:
    """True when the session's queue or map game mode is TFT."""
    if not isinstance(session, dict):
        return False
    modes = []
    gd = session.get("gameData")
    if isinstance(gd, dict) and isinstance(gd.get("queue"), dict):
        modes.append(gd["queue"].get("gameMode"))
    if isinstance(session.get("map"), dict):
        modes.append(session["map"].get("gameMode"))
    return any(isinstance(m, str) and m.upper() == "TFT" for m in modes)


def history_path(puuid: str, count: int = 5) -> str:
    return HISTORY_PATH.format(puuid=urllib.parse.quote(str(puuid), safe=""),
                               count=max(1, min(20, int(count))))


# -- EOG parse -------------------------------------------------------------------

def _eog_items(raw) -> list[dict]:
    out = []
    for it in _list(raw):
        if not isinstance(it, dict):
            continue
        nid = _str(it.get("nameId"))
        if nid:
            out.append({"name_id": nid, "name": _str(it.get("name"))})
    return out


def _eog_unit(raw) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    cid = _str(raw.get("championId"))
    if not cid:
        return None
    traits = []
    for t in _list(raw.get("traits")):
        if isinstance(t, dict) and (_str(t.get("id")) or _str(t.get("name"))):
            traits.append({"id": _str(t.get("id")) or None,
                           "name": _str(t.get("name")) or display_from_id(t.get("id"))})
    return {"character_id": cid,
            "name": _str(raw.get("name")) or display_from_id(cid),
            "star": _int(raw.get("level")),
            "cost": _int(raw.get("price")),
            "items": _eog_items(raw.get("items")),
            "traits": traits}


def _eog_trait_counts(board: list[dict]) -> list[dict]:
    """Unique-unit count per trait, emblem items included (a unit holding
    "<Trait> Emblem" counts toward <Trait> unless it has it natively)."""
    counts: dict[str, int] = {}
    ids: dict[str, Optional[str]] = {}
    seen: set[str] = set()
    for u in board:
        if u["character_id"] in seen:
            continue
        seen.add(u["character_id"])
        names = set()
        for t in u["traits"]:
            names.add(t["name"])
            ids.setdefault(t["name"], t["id"])
        for it in u["items"]:
            nm = it["name"]
            if nm.endswith(" Emblem") and len(nm) > 7:
                names.add(nm[:-7])
        for nm in names:
            counts[nm] = counts.get(nm, 0) + 1
    return [{"name": nm, "id": ids.get(nm), "units": n}
            for nm, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _augments(raw) -> list:
    out = []
    for a in _list(raw):
        if isinstance(a, str) and a.strip():
            out.append(_str(a))
        elif isinstance(a, dict):
            nm = _str(a.get("nameId")) or _str(a.get("id")) or _str(a.get("name"))
            if nm:
                out.append(nm)
    return out


def _header(source: str, game_id: int, now: Optional[float]) -> dict:
    ts = time.time() if now is None else float(now)
    return {"schema": SCHEMA_VERSION, "source": source, "game_id": game_id,
            "captured_at": _stamp(ts), "captured_at_unix": ts}


def parse_eog(doc, *, now: Optional[float] = None) -> Optional[dict]:
    """Sanitised record from a tft-eog-stats document, or None when the
    document is not one (no positive gameId, no players[] list)."""
    if not isinstance(doc, dict):
        return None
    gid = _int(doc.get("gameId"))
    raw_players = doc.get("players")
    if not gid or gid <= 0 or not isinstance(raw_players, list) or not raw_players:
        return None
    players = []
    local_raw = None
    for p in raw_players:
        if not isinstance(p, dict):
            continue
        if p.get("isLocalPlayer") is True and local_raw is None:
            local_raw = p
        board = [u for u in (_eog_unit(x) for x in _list(p.get("boardPieces"))) if u]
        players.append({
            "placement": _placement(p.get("ffaStanding")) or _placement(p.get("rank")),
            "is_local": p.get("isLocalPlayer") is True,
            "partner_group_id": _int(p.get("partnerGroupId")) or 0,
            "board": board,
            "traits": _eog_trait_counts(board),
            "augments": _augments(p.get("augments")),
        })
    if not players:
        return None
    players.sort(key=lambda p: (p["placement"] is None, p["placement"] or 0))
    lp = doc.get("localPlayer") if isinstance(doc.get("localPlayer"), dict) else {}
    src = local_raw or lp
    local_placement = (_placement(src.get("ffaStanding")) or _placement(src.get("rank"))
                       if src else None)
    hp = _int(src.get("health")) if src else None
    rec = _header(SOURCE_EOG, gid, now)
    rec.update({
        "ended_at": None, "ended_at_unix": None,
        "game_length_s": _int(doc.get("gameLength")),
        "queue_id": _int(doc.get("queueId")),
        "queue_type": _str(doc.get("queueType")),
        "is_ranked": doc.get("isRanked") if isinstance(doc.get("isRanked"), bool) else None,
        "set_core_name": _str((local_raw or {}).get("setCoreName")) or _str(lp.get("setCoreName")),
        "set_number": None,
        "game_type": "",
        "local_placement": local_placement,
        "local_hp": hp if hp is not None and 0 <= hp <= 100 else None,
        "lobby_size": len(players),
        "augments_recorded": any(p["augments"] for p in players),
        "players": players,
    })
    return rec


# -- history parse ---------------------------------------------------------------

def _history_unit(raw) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    cid = _str(raw.get("character_id"))
    if not cid:
        return None
    rarity = _int(raw.get("rarity"))
    return {"character_id": cid,
            "name": _str(raw.get("name")) or display_from_id(cid),
            "star": _int(raw.get("tier")),
            "cost": rarity + 1 if rarity is not None and 0 <= rarity <= 4 else None,
            "items": [{"name_id": _str(n), "name": display_from_id(n)}
                      for n in _list(raw.get("itemNames")) if _str(n)],
            "traits": []}


def _history_traits(raw) -> list[dict]:
    out = []
    for t in _list(raw):
        if not isinstance(t, dict) or not _str(t.get("name")):
            continue
        out.append({"name": _str(t.get("name")), "id": None,
                    "units": _int(t.get("num_units")) or 0,
                    "tier": _int(t.get("tier_current")) or 0})
    out.sort(key=lambda t: (-t["tier"], -t["units"], t["name"]))
    return out


def parse_history_game(game, local_puuid: str, *,
                       now: Optional[float] = None) -> Optional[dict]:
    """Sanitised record from one games[] entry of the TFT match-history
    route. `local_puuid` (the current summoner's) only marks is_local and is
    never stored."""
    j = game.get("json") if isinstance(game, dict) else None
    if not isinstance(j, dict):
        return None
    gid = _int(j.get("game_id")) or _int(j.get("gameId"))
    parts = j.get("participants")
    if not gid or gid <= 0 or not isinstance(parts, list) or not parts:
        return None
    me = _str(local_puuid)
    players = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        players.append({
            "placement": _placement(p.get("placement")),
            "is_local": bool(me) and p.get("puuid") == me,
            "partner_group_id": _int(p.get("partner_group_id")) or 0,
            "level": _int(p.get("level")),
            "gold_left": _int(p.get("gold_left")),
            "last_round": _int(p.get("last_round")),
            "time_eliminated_s": _int(round(p["time_eliminated"]))
            if isinstance(p.get("time_eliminated"), (int, float))
            and not isinstance(p.get("time_eliminated"), bool) else None,
            "board": [u for u in (_history_unit(x) for x in _list(p.get("units"))) if u],
            "traits": _history_traits(p.get("traits")),
            "augments": _augments(p.get("augments")),
        })
    if not players:
        return None
    players.sort(key=lambda p: (p["placement"] is None, p["placement"] or 0))
    local = next((p for p in players if p["is_local"]), None)
    ended = None
    dt = _int(j.get("game_datetime"))
    if dt and dt > 10**11:
        ended = dt / 1000.0
    length = j.get("game_length")
    rec = _header(SOURCE_HISTORY, gid, now)
    rec.update({
        "ended_at": _stamp(ended) if ended else None,
        "ended_at_unix": ended,
        "game_length_s": int(length) if isinstance(length, (int, float))
        and not isinstance(length, bool) and length > 0 else None,
        "queue_id": _int(j.get("queue_id")) or _int(j.get("queueId")),
        "queue_type": "",
        "is_ranked": None,
        "set_core_name": _str(j.get("tft_set_core_name")),
        "set_number": _int(j.get("tft_set_number")),
        "game_type": _str(j.get("tft_game_type")),
        "local_placement": local["placement"] if local else None,
        "local_hp": None,
        "lobby_size": len(players),
        "augments_recorded": any(p["augments"] for p in players),
        "players": players,
    })
    return rec


def parse_history(doc, local_puuid: str, *, now: Optional[float] = None) -> list[dict]:
    """Every parsable game of a match-history response, newest first as the
    route returns them."""
    games = doc.get("games") if isinstance(doc, dict) else None
    if isinstance(games, dict):         # the LoL product nests games.games
        games = games.get("games")
    out = []
    for g in _list(games):
        rec = parse_history_game(g, local_puuid, now=now)
        if rec:
            out.append(rec)
    return out


# -- merge -------------------------------------------------------------------------

_HIST_PLAYER_KEYS = ("level", "gold_left", "last_round", "time_eliminated_s")


def merge(eog: Optional[dict], hist: Optional[dict]) -> Optional[dict]:
    """One view of a game from its EOG and/or history records. EOG wins for
    boards (display names, costs) and the local HP; history wins for the end
    time, set number, per-player level / gold / rounds and trait tiers."""
    if not eog and not hist:
        return None
    base = copy.deepcopy(eog or hist)
    hist = copy.deepcopy(hist) if hist else None
    base["sources"] = [s for s, r in ((SOURCE_EOG, eog), (SOURCE_HISTORY, hist)) if r]
    base.pop("source", None)
    if eog and hist:
        for k in ("ended_at", "ended_at_unix", "set_number", "game_type"):
            if hist.get(k) is not None and hist.get(k) != "":
                base[k] = hist[k]
        for k in ("game_length_s", "queue_id", "set_core_name", "local_placement"):
            if base.get(k) in (None, "") and hist.get(k) not in (None, ""):
                base[k] = hist[k]
        names: dict[str, str] = {}
        for p in base["players"]:
            for u in p["board"]:
                for t in u["traits"]:
                    if t["id"]:
                        names[t["id"]] = t["name"]
        by_place = {p["placement"]: p for p in hist["players"] if p["placement"]}
        for mp in base["players"]:
            hp = by_place.get(mp["placement"])
            if not hp:
                continue
            for k in _HIST_PLAYER_KEYS:
                mp[k] = hp.get(k)
            if hp["traits"]:
                mp["traits"] = [dict(t, id=t["name"], name=names.get(t["name"])
                                     or display_from_id(t["name"]))
                                for t in hp["traits"]]
            if not mp["board"]:
                mp["board"] = hp["board"]
            if not mp["augments"]:
                mp["augments"] = hp["augments"]
        base["augments_recorded"] = any(p["augments"] for p in base["players"])
    elif hist:
        for p in base["players"]:
            p["traits"] = [dict(t, id=t["name"], name=display_from_id(t["name"]))
                           for t in p["traits"]]
    for p in base["players"]:
        for t in p["traits"]:
            if "tier" in t:
                t["active"] = t["tier"] > 0
            else:
                t["active"] = None
    base["ended_at_effective"] = base.get("ended_at") or base.get("captured_at")
    base["ended_at_effective_unix"] = (base.get("ended_at_unix")
                                       or base.get("captured_at_unix"))
    return base


# -- store -------------------------------------------------------------------------

def _dir(store_dir) -> Path:
    return Path(store_dir) if store_dir is not None else _STORE_DIR


def _path(store: Path, game_id: int, source: str) -> Path:
    return store / f"{int(game_id)}.{source}.json"


def persist(record, store_dir=None) -> bool:
    """Write one source record, append-only: False (and nothing written)
    when this (game, source) is already stored or the record is not one."""
    if not isinstance(record, dict) or record.get("source") not in _SOURCES:
        return False
    gid = _int(record.get("game_id"))
    if not gid or gid <= 0:
        return False
    store = _dir(store_dir)
    target = _path(store, gid, record["source"])
    if target.exists():
        return False
    atomic_write_json(target, record)
    _log.info("tft store: game %s %s record written (placement %s)",
              gid, record["source"], record.get("local_placement"))
    return True


def has_record(game_id, source: Optional[str] = None, store_dir=None) -> bool:
    gid = _int(game_id)
    if not gid or gid <= 0:
        return False
    store = _dir(store_dir)
    return any(_path(store, gid, s).exists()
               for s in ((source,) if source else _SOURCES))


def _read(path: Path) -> Optional[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("tft store: unreadable %s: %s", path.name, exc)
        return None
    return d if isinstance(d, dict) and d.get("schema") == SCHEMA_VERSION else None


def load(game_id, store_dir=None) -> Optional[dict]:
    gid = _int(game_id)
    if not gid or gid <= 0:
        return None
    store = _dir(store_dir)
    recs = {}
    for s in _SOURCES:
        p = _path(store, gid, s)
        if p.exists():
            recs[s] = _read(p)
    return merge(recs.get(SOURCE_EOG), recs.get(SOURCE_HISTORY))


def _game_ids(store: Path) -> set[int]:
    try:
        names = [e.name for e in store.iterdir() if e.is_file()]
    except OSError:
        return set()
    return {int(m.group(1)) for m in map(_FILE_RE.match, names) if m}


def latest(store_dir=None) -> Optional[dict]:
    """The merged record of the game that ended last, or None."""
    store = _dir(store_dir)
    best = None
    for gid in _game_ids(store):
        rec = load(gid, store_dir=store)
        if rec and (best is None or (rec["ended_at_effective_unix"] or 0)
                    > (best["ended_at_effective_unix"] or 0)):
            best = rec
    return best


def store_marker(store_dir=None) -> Any:
    """Changes whenever a record lands - a cheap cache-key component."""
    store = _dir(store_dir)
    try:
        st = store.stat()
    except OSError:
        return 0
    return (st.st_mtime_ns, len(_game_ids(store)))
