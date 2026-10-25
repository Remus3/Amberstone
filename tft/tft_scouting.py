# arch: TFT opponent scouting digest (LCU identities + Riot TFT API / LCU history) | section=tft | frozen=no
"""TFT opponent scouting: who is in this lobby, and how have they been playing.

Given the opponent identities of a TFT game, build one digest per opponent -
rank / tier / LP, ranked games this set, average placement and top-4 rate over
the last N matches (default 10), most-played traits and carries, the last
match's comp, the current top-4 / bottom-4 streak and a one-line "threat"
summary - and publish them atomically to ``data/tft_scouting.json`` for the
dashboard view. LLM-free and deterministic.

IDENTITY SOURCES, BY PHASE (measured 2026-10-25, GET only):
  Lobby / Matchmaking / ReadyCheck - NONE for opponents. ``/lol-lobby/v2/lobby``
    and ``/lol-gameflow/v1/session`` ``gameData.teamOne`` list the PARTY only.
  GameStart / InProgress - ``/lol-gameflow/v1/session`` ``gameData.teamOne`` /
    ``teamTwo`` (schema: puuid, summonerId, summonerName ...). UNVERIFIED
    whether a TFT game lists all 8 there, so the watcher tries it at game start
    and degrades to an honest "no_opponents" state when it does not.
  PreEndOfGame / EndOfGame - ``/lol-end-of-game/v1/tft-eog-stats`` ``players[]``
    carries riot ids for all 8, with puuid + summonerId ZEROED for every
    non-local player. Used as the fallback for a game whose session never
    listed opponents.
  Any phase - ``/lol-match-history/v1/products/tft/{puuid}/matches`` (the queried
    player's own row carries their real puuid + riot id; other rows are zeroed).

PUUID FORMS. The LCU puuid is a 36-char UUID; the Riot Web API puuid is a
78-char per-KEY encryption (memory reference_riot_puuid_rotation), so an LCU
puuid is never sent to the Web API. The Web API path starts from the riot id
(Account-V1). The LCU path starts from a real LCU puuid, or resolves one from a
riot id with ``GET /lol-summoner/v1/alias/lookup`` (verified on the local
account 2026-10-25).

DATA SOURCES, IN ORDER (``Scouter.sources``):
  riot_api - Account-V1 -> TFT-League-V1 -> TFT-Match-V1, through
    core/riot_api.py inside ``tft_key_scope()`` (ADR-006: the one module that
    talks to *.api.riotgames.com). MEASURED 2026-10-25: the LoL product key 403s
    every /tft/* route, so until a TFT-entitled key is dropped into
    ``API-Key-Riot-TFT.txt`` this path answers "not_enabled" once and is skipped
    for ``RIOT_OFF_TTL_S``.
  lcu - ``/lol-ranked/v1/ranked-stats/{puuid}`` (queueMap.RANKED_TFT) and the
    LCU TFT match history. Client-side data, no Web API key, GET only.
  The Riot path needs a riot id. Game-start session entries are expected to
  carry only an LCU puuid (summonerName is "" on current clients), so those
  opponents are served by the LCU path; the Riot path serves riot-id
  identities (the EOG fallback, or a session that does carry names).

ADR-006 ENVELOPE. The Web API key must not drive real-time in-game advisory.
This is a STATIC history digest captured ONCE per game at game start (the TFT
analogue of the loading screen - TFT has no champ select) and never refreshed
mid-game; it carries no live game state. Kill switch: ``RC_TFT_SCOUTING=0``.

Fail-soft: every network failure degrades one opponent's card to a friendly
message; the raw outcome goes to the log (logs/), never into the artifact.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("rc.tft_scouting")

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT / "data" / "tft_scouting.json"
CACHE_PATH = ROOT / "data" / "tft_scouting_cache.json"

SCHEMA = "rc.tft_scouting.v1"
DEFAULT_N = 10
MAX_N = 20
MAX_OPPONENTS = 7
DIGEST_TTL_S = 900.0
CACHE_MAX_ENTRIES = 300
RIOT_OFF_TTL_S = 900.0
RUN_DEADLINE_S = 240.0
RETRY_ATTEMPTS = 3
ENV_KILL = "RC_TFT_SCOUTING"

# Double Up ("pairs") placements are team-shaped; every other TFT game type is
# an 8-player free-for-all whose placement means the same thing.
_EXCLUDED_GAME_TYPES = frozenset({"pairs"})

_TIERS = ("IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
          "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER")
_APEX = frozenset({"MASTER", "GRANDMASTER", "CHALLENGER"})

_RATE_LIMIT = frozenset({"429", "rate_limited"})

_MESSAGES = {
    "not_found": "No public TFT profile found (bot or renamed account).",
    "rate_limited": "Riot is busy right now - this card will fill in next game.",
    "deadline": "Ran out of time loading this profile - it will fill in next game.",
    "no_identity": "This player's identity is hidden.",
    "unavailable": "Profile unavailable right now.",
}
_RUN_MESSAGES = {
    "no_opponents": "Opponents are not visible yet - scouting runs once the game lists them.",
    "unavailable": "Scouting is unavailable right now.",
    "partial": "Some profiles could not be loaded.",
    "disabled": "TFT scouting is turned off.",
}

_ZERO_PUUID_RE = re.compile(r"^[0\-]+$")
_PREFIX_RE = re.compile(r"^(?:TFT[0-9A-Za-z]*_|DA_\d+_|DA_)")
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_SET_SUFFIX_RE = re.compile(r"(?<=[A-Za-z])\d{1,2}$")


# -- small helpers ------------------------------------------------------------

def _ascii(text: Any) -> str:
    return str(text or "").encode("ascii", "replace").decode("ascii")


def _int(v: Any, default: Optional[int] = None) -> Optional[int]:
    if isinstance(v, bool):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def real_puuid(value: Any) -> str:
    """A usable LCU / API puuid, or "". Zeroed puuids (the EOG / match-history
    privacy form for non-local players) and junk are not identities."""
    s = str(value or "").strip()
    if len(s) < 8 or _ZERO_PUUID_RE.match(s):
        return ""
    return s


def clean_name(api_name: Any) -> str:
    """``TFT13_Jinx`` / ``DA_18_Blossom`` / ``DA_Karma18`` (the Set 18 client also
    puts the set number AFTER the name) / ``TFT_Item_InfinityEdge`` -> display."""
    raw = str(api_name or "")
    s = _PREFIX_RE.sub("", raw)
    if s.startswith("Item_"):
        s = s[len("Item_"):]
    s = _SET_SUFFIX_RE.sub("", s)
    s = _CAMEL_RE.sub(" ", s).replace("_", " ").strip()
    return _ascii(s or raw)


def kill_switch_off() -> bool:
    return str(os.environ.get(ENV_KILL, "1")).strip().lower() in ("0", "false", "off", "no")


# -- identities ---------------------------------------------------------------

@dataclass
class Identity:
    game_name: str = ""
    tag_line: str = ""
    lcu_puuid: str = ""
    slot: int = 0

    @property
    def riot_id(self) -> str:
        if self.game_name and self.tag_line:
            return f"{self.game_name}#{self.tag_line}"
        return self.game_name

    @property
    def key(self) -> str:
        if self.game_name and self.tag_line:
            return "rid:" + self.riot_id.lower()
        return "lcu:" + self.lcu_puuid if self.lcu_puuid else ""


def _identity_from_entry(entry: Any) -> Optional[Identity]:
    if not isinstance(entry, dict):
        return None
    gn = str(entry.get("gameName") or entry.get("riotIdGameName") or "").strip()
    tl = str(entry.get("tagLine") or entry.get("riotIdTagLine")
             or entry.get("riotIdTagline") or entry.get("gameTag") or "").strip()
    if not gn:
        for k in ("riotId", "riotIdPlusTagLine", "summonerName"):
            v = str(entry.get(k) or "").strip()
            if "#" in v:
                gn, _, tl = v.partition("#")
                gn, tl = gn.strip(), tl.strip()
                break
    tl = tl.lstrip("#")
    ident = Identity(game_name=gn, tag_line=tl, lcu_puuid=real_puuid(entry.get("puuid")))
    return ident if ident.key else None


def _collect(entries, is_self: Callable[[dict], bool]) -> list:
    out: list = []
    seen: set = set()
    for e in entries:
        if not isinstance(e, dict) or is_self(e):
            continue
        ident = _identity_from_entry(e)
        if ident is None or ident.key in seen:
            continue
        seen.add(ident.key)
        ident.slot = len(out)
        out.append(ident)
        if len(out) >= MAX_OPPONENTS:
            break
    return out


def is_tft_session(session: Any) -> bool:
    if not isinstance(session, dict):
        return False
    gd = session.get("gameData") if isinstance(session.get("gameData"), dict) else {}
    q = gd.get("queue") if isinstance(gd.get("queue"), dict) else {}
    mp = session.get("map") if isinstance(session.get("map"), dict) else {}
    return "TFT" in (str(q.get("gameMode") or "").upper(), str(mp.get("gameMode") or "").upper())


def session_game_id(session: Any) -> str:
    gd = session.get("gameData") if isinstance(session, dict) else None
    gid = gd.get("gameId") if isinstance(gd, dict) else None
    s = str(gid or "").strip()
    return "" if s in ("", "0") else s


def identities_from_session(session: Any, self_puuid: str = "",
                            self_summoner_id: Any = None) -> list:
    """Opponents from ``/lol-gameflow/v1/session`` (teamOne + teamTwo)."""
    if not isinstance(session, dict):
        return []
    gd = session.get("gameData") if isinstance(session.get("gameData"), dict) else {}
    entries: list = []
    for team in ("teamOne", "teamTwo"):
        t = gd.get(team)
        if isinstance(t, list):
            entries.extend(t)
    me_p = real_puuid(self_puuid)
    me_s = _int(self_summoner_id, 0) or 0

    def is_self(e: dict) -> bool:
        if e.get("isLocalPlayer") is True:
            return True
        if me_p and real_puuid(e.get("puuid")) == me_p:
            return True
        return bool(me_s) and _int(e.get("summonerId"), 0) == me_s

    return _collect(entries, is_self)


def identities_from_eog(eog: Any, self_puuid: str = "") -> list:
    """Opponents from ``/lol-end-of-game/v1/tft-eog-stats`` ``players[]``."""
    if not isinstance(eog, dict):
        return []
    players = eog.get("players") if isinstance(eog.get("players"), list) else []
    me_p = real_puuid(self_puuid)

    def is_self(e: dict) -> bool:
        return e.get("isLocalPlayer") is True or bool(me_p and real_puuid(e.get("puuid")) == me_p)

    return _collect(players, is_self)


# -- match + rank normalisation ------------------------------------------------

def match_row(match: Any, *, puuid: str = "", riot_id: str = "") -> Optional[dict]:
    """One player's row of a TFT match, from either shape:
    Riot TFT-Match-V1 ``{"metadata", "info"}`` or LCU history ``{"metadata", "json"}``.
    The player is matched by real puuid first, then by riot id."""
    if not isinstance(match, dict):
        return None
    info = match.get("info") if isinstance(match.get("info"), dict) else match.get("json")
    if not isinstance(info, dict):
        return None
    parts = info.get("participants") if isinstance(info.get("participants"), list) else []
    want_p = real_puuid(puuid)
    want_r = riot_id.lower()
    me = None
    if want_p:
        me = next((p for p in parts if isinstance(p, dict)
                   and real_puuid(p.get("puuid")) == want_p), None)
    if me is None and want_r:
        for p in parts:
            if not isinstance(p, dict):
                continue
            rid = f"{p.get('riotIdGameName') or ''}#{p.get('riotIdTagline') or p.get('riotIdTagLine') or ''}"
            if rid.lower() == want_r:
                me = p
                break
    if me is None:
        return None
    placement = _int(me.get("placement"))
    if placement is None or not 1 <= placement <= 8:
        return None
    md = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
    ts_ms = _int(info.get("game_datetime")) or _int(md.get("timestamp")) or 0
    traits = []
    for t in me.get("traits") or []:
        if isinstance(t, dict) and t.get("name"):
            traits.append({"name": str(t["name"]), "num_units": _int(t.get("num_units"), 0),
                           "style": _int(t.get("style"), 0),
                           "tier_current": _int(t.get("tier_current"), 0)})
    units = []
    for u in me.get("units") or []:
        if isinstance(u, dict) and u.get("character_id"):
            items = u.get("itemNames") if isinstance(u.get("itemNames"), list) else []
            units.append({"character_id": str(u["character_id"]),
                          "tier": _int(u.get("tier"), 1), "rarity": _int(u.get("rarity"), 0),
                          "items": [str(i) for i in items if i]})
    return {
        "match_id": str(md.get("match_id") or info.get("gameId") or ""),
        "ts_s": ts_ms // 1000 if ts_ms > 10**11 else ts_ms,
        "set": _int(info.get("tft_set_number")),
        "game_type": str(info.get("tft_game_type") or "standard").lower(),
        "queue_id": _int(info.get("queue_id") or info.get("queueId")),
        "placement": placement,
        "level": _int(me.get("level")),
        "traits": traits,
        "units": units,
        "riot_name": str(me.get("riotIdGameName") or ""),
        "riot_tag": str(me.get("riotIdTagline") or me.get("riotIdTagLine") or ""),
    }


def _rank(tier: str, division: str, lp: Any, wins: Any, losses: Any) -> dict:
    tier = str(tier or "").upper()
    if tier not in _TIERS:
        return {"ranked": False, "tier": None, "division": None, "lp": None,
                "wins": _int(wins, 0), "losses": _int(losses, 0),
                "games": (_int(wins, 0) or 0) + (_int(losses, 0) or 0), "display": "Unranked"}
    division = str(division or "").upper()
    if tier in _APEX or division not in ("I", "II", "III", "IV"):
        division = ""
    lp_i = _int(lp, 0)
    w, losses_i = _int(wins, 0) or 0, _int(losses, 0) or 0
    disp = " ".join(x for x in (tier, division, f"{lp_i} LP") if x)
    return {"ranked": True, "tier": tier, "division": division or None, "lp": lp_i,
            "wins": w, "losses": losses_i, "games": w + losses_i, "display": disp}


def rank_from_riot_entries(entries: Any) -> Optional[dict]:
    """TFT-League-V1 list -> rank dict (RANKED_TFT only). ``[]`` = unranked."""
    if not isinstance(entries, list):
        return None
    e = next((x for x in entries if isinstance(x, dict)
              and str(x.get("queueType") or "").upper() == "RANKED_TFT"), None)
    if e is None:
        return _rank("", "", None, 0, 0)
    return _rank(e.get("tier"), e.get("rank"), e.get("leaguePoints"), e.get("wins"), e.get("losses"))


def rank_from_lcu_ranked(stats: Any) -> Optional[dict]:
    """``/lol-ranked/v1/ranked-stats/{puuid}`` -> rank dict. Unranked LCU form:
    tier "" (or NONE) and division "NA" (measured 2026-10-25)."""
    if not isinstance(stats, dict):
        return None
    qm = stats.get("queueMap") if isinstance(stats.get("queueMap"), dict) else {}
    e = qm.get("RANKED_TFT")
    if not isinstance(e, dict):
        return _rank("", "", None, 0, 0)
    return _rank(e.get("tier"), e.get("division"), e.get("leaguePoints"), e.get("wins"), e.get("losses"))


# -- digest -------------------------------------------------------------------

def _primary_traits(row: dict, k: int = 2) -> list:
    active = [t for t in row.get("traits") or [] if (t.get("tier_current") or 0) > 0
              or (t.get("style") or 0) > 0]
    active.sort(key=lambda t: (-(t.get("style") or 0), -(t.get("num_units") or 0), t["name"]))
    return active[:k]


def _carries(row: dict, k: int = 2) -> list:
    units = sorted(row.get("units") or [],
                   key=lambda u: (-len(u.get("items") or []), -(u.get("tier") or 0),
                                  -(u.get("rarity") or 0), u["character_id"]))
    carried = [u for u in units if len(u.get("items") or []) >= 2][:k]
    if not carried and units and units[0].get("items"):
        carried = units[:1]
    return carried


def _streak(placements: list) -> dict:
    if not placements:
        return {"kind": "none", "length": 0}
    kind = "top4" if placements[0] <= 4 else "bot4"
    n = 0
    for p in placements:
        if (p <= 4) != (kind == "top4"):
            break
        n += 1
    return {"kind": kind, "length": n}


def compute_threat(rank: Optional[dict], sample: dict, streak: dict,
                   top_traits: list, top_carries: list) -> dict:
    """Deterministic 0-100 threat score + level + ONE ASCII summary line."""
    n = sample.get("n") or 0
    avg = sample.get("avg_placement")
    top4 = sample.get("top4_rate")
    ranked = bool(rank and rank.get("ranked"))
    rank_txt = rank["display"] if rank else "Rank unknown"
    if n < 3 and not ranked:
        msg = (f"{rank_txt} - only {n} recent game{'s' if n != 1 else ''}"
               if n else f"{rank_txt} - no recent TFT games")
        return {"level": "unknown", "score": None, "summary": _ascii(msg)}
    score = 50.0
    if avg is not None and n >= 3:
        score += 30.0 * max(-1.0, min(1.0, (4.5 - avg) / 2.5))
        score += 20.0 * ((top4 or 0.0) - 0.5)
    if ranked:
        score += 20.0 * (_TIERS.index(rank["tier"]) / (len(_TIERS) - 1) - 0.4)
    if streak.get("length", 0) >= 3:
        score += 5.0 if streak["kind"] == "top4" else -5.0
    score = int(round(max(0.0, min(100.0, score))))
    level = "high" if score >= 65 else "medium" if score >= 45 else "low"
    parts = [rank_txt]
    if avg is not None:
        parts.append(f"avg {avg:.1f}, top4 {int(round((top4 or 0) * 100))}% (last {n})")
    if streak.get("length", 0) >= 2:
        word = "top-4" if streak["kind"] == "top4" else "bottom-4"
        parts.append(f"{streak['length']} {word} in a row")
    plays = "/".join(t["name"] for t in top_traits[:2])
    carry = top_carries[0]["name"] if top_carries else ""
    if plays or carry:
        parts.append(" ".join(x for x in (f"plays {plays}" if plays else "",
                                          f"carry {carry}" if carry else "") if x))
    return {"level": level, "score": score, "summary": _ascii(" - ".join(parts))}


def build_digest(ident: Identity, rank: Optional[dict], rows: list, *,
                 n: int = DEFAULT_N, source: str = "", current_set: Optional[int] = None) -> dict:
    rows = sorted((r for r in rows if isinstance(r, dict)), key=lambda r: -(r.get("ts_s") or 0))
    ffa = [r for r in rows if r.get("game_type") not in _EXCLUDED_GAME_TYPES][:n]
    placements = [r["placement"] for r in ffa]
    k = len(placements)
    set_counts = Counter(str(r["set"]) for r in ffa if r.get("set") is not None)
    sample = {
        "n": k,
        "avg_placement": round(sum(placements) / k, 2) if k else None,
        "top4_rate": round(sum(1 for p in placements if p <= 4) / k, 2) if k else None,
        "first_rate": round(sum(1 for p in placements if p == 1) / k, 2) if k else None,
        "set_counts": dict(set_counts),
        "set_games": None,
    }
    trait_c: Counter = Counter()
    carry_c: Counter = Counter()
    for r in ffa:
        for t in _primary_traits(r):
            trait_c[clean_name(t["name"])] += 1
        for u in _carries(r):
            carry_c[clean_name(u["character_id"])] += 1
    top_traits = [{"name": nm, "count": c} for nm, c in
                  sorted(trait_c.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    top_carries = [{"name": nm, "count": c} for nm, c in
                   sorted(carry_c.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    last = ffa[0] if ffa else (rows[0] if rows else None)
    last_match = None
    if last:
        last_match = {
            "placement": last["placement"],
            "level": last.get("level"),
            "set": last.get("set"),
            "played_at": last.get("ts_s") or None,
            "traits": [f"{clean_name(t['name'])} {t.get('num_units') or 0}"
                       for t in _primary_traits(last, 3)],
            "carries": [{"name": clean_name(u["character_id"]), "star": u.get("tier"),
                         "items": [clean_name(i) for i in u.get("items") or []]}
                        for u in _carries(last)],
        }
    streak = _streak(placements)
    riot_id = ident.riot_id
    if not riot_id and rows and rows[0].get("riot_name"):
        riot_id = rows[0]["riot_name"] + ("#" + rows[0]["riot_tag"] if rows[0].get("riot_tag") else "")
    digest = {
        "slot": ident.slot,
        "riot_id": riot_id,
        "status": "ready",
        "source": source,
        "cached": False,
        "rank": rank,
        "games_this_set": rank["games"] if rank and rank.get("ranked") else None,
        "sample": sample,
        "top_traits": top_traits,
        "top_carries": top_carries,
        "last_match": last_match,
        "streak": streak,
        "threat": compute_threat(rank, sample, streak, top_traits, top_carries),
        "message": "",
    }
    apply_current_set(digest, current_set)
    return digest


def apply_current_set(digest: dict, current_set: Optional[int]) -> None:
    sample = digest.get("sample") if isinstance(digest.get("sample"), dict) else None
    if sample is None:
        return
    counts = sample.get("set_counts") or {}
    if current_set is None and counts:
        current_set = max(_int(s, 0) or 0 for s in counts)
    sample["set_games"] = int(counts.get(str(current_set), 0)) if current_set is not None else None


def unavailable_digest(ident: Identity, reason: str) -> dict:
    return {
        "slot": ident.slot, "riot_id": ident.riot_id, "status": "unavailable",
        "source": None, "cached": False, "rank": None, "games_this_set": None,
        "sample": None, "top_traits": [], "top_carries": [], "last_match": None,
        "streak": {"kind": "none", "length": 0},
        "threat": {"level": "unknown", "score": None, "summary": ""},
        "reason": reason,
        "message": _MESSAGES.get(reason, _MESSAGES["unavailable"]),
    }


def pending_digest(ident: Identity) -> dict:
    d = unavailable_digest(ident, "pending")
    d.update(status="pending", message="Loading...")
    return d


# -- on-disk digest cache ---------------------------------------------------------

class DigestCache:
    """Small TTL'd JSON cache of finished digests, keyed by a hash of the
    identity (so a repeat opponent inside the TTL costs zero calls). The raw
    Riot responses are cached separately by core/riot_api_cache."""

    def __init__(self, path: Path = CACHE_PATH, ttl_s: float = DIGEST_TTL_S,
                 clock: Callable[[], float] = time.time) -> None:
        self._path = Path(path)
        self._ttl = float(ttl_s)
        self._clock = clock
        self._lock = threading.Lock()
        self._data: Optional[dict] = None

    @staticmethod
    def _hkey(ident: Identity) -> str:
        return hashlib.sha256(ident.key.encode("utf-8")).hexdigest()[:24]

    def _load(self) -> dict:
        if self._data is None:
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._data = raw if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self._data = {}
        return self._data

    def get(self, ident: Identity) -> Optional[dict]:
        with self._lock:
            row = self._load().get(self._hkey(ident))
            if not isinstance(row, dict) or not isinstance(row.get("digest"), dict):
                return None
            if self._clock() - self._at(row) > self._ttl:
                return None
            return json.loads(json.dumps(row["digest"]))

    @staticmethod
    def _at(row: Any) -> float:
        """The row's write time; a damaged value reads as expired, never raises."""
        try:
            return float(row.get("at") or 0) if isinstance(row, dict) else 0.0
        except (TypeError, ValueError):
            return 0.0

    def put(self, ident: Identity, digest: dict) -> None:
        with self._lock:
            data = self._load()
            now = self._clock()
            data[self._hkey(ident)] = {"at": now, "digest": digest}
            live = {k: v for k, v in data.items() if isinstance(v, dict)
                    and now - self._at(v) <= self._ttl}
            if len(live) > CACHE_MAX_ENTRIES:
                keep = sorted(live.items(), key=lambda kv: -self._at(kv[1]))
                live = dict(keep[:CACHE_MAX_ENTRIES])
            self._data = live
            try:
                _atomic_write_json(self._path, live)
            except OSError as exc:
                log.warning("tft_scouting: digest cache write failed: %s", exc)


def _atomic_write_json(path: Path, obj: Any) -> None:
    """ASCII JSON (riot ids escaped) through the repo's one sanctioned atomic
    writer (per-writer scratch name, fsync, replace-with-retry, LF bytes)."""
    from core.polled_json import atomic_write_text
    atomic_write_text(Path(path),
                      json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=True) + "\n")


# -- the scouter -------------------------------------------------------------------

LcuGet = Callable[[str], Any]


class Scouter:
    """Fetch + digest + publish. ``scout()`` is synchronous (tests, the thread
    body); ``start()`` runs it on a daemon thread and supersedes a run still in
    flight for an older game."""

    def __init__(self, *, lcu_get: Optional[LcuGet] = None, riot: Any = None,
                 artifact_path: Path = ARTIFACT_PATH, cache: Optional[DigestCache] = None,
                 n: int = DEFAULT_N, regional: str = "americas", platform: str = "na1",
                 sources: tuple = ("riot_api", "lcu"),
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time,
                 deadline_s: float = RUN_DEADLINE_S) -> None:
        self._lcu_get = lcu_get
        self._riot = riot
        self._artifact = Path(artifact_path)
        self._cache = cache if cache is not None else DigestCache(clock=clock)
        self.n = max(1, min(MAX_N, int(n)))
        self.regional = regional
        self.platform = platform
        self.sources = tuple(sources)
        self._sleep = sleep
        self._clock = clock
        self._deadline_s = float(deadline_s)
        self._riot_off_until = 0.0
        self._riot_state = "unused"
        self._lcu_state = "unused"
        self._token = 0
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # -- publish --
    def _write(self, doc: dict, token: Optional[int]) -> None:
        with self._write_lock:
            if token is not None and token != self._token:
                return
            try:
                _atomic_write_json(self._artifact, doc)
            except OSError as exc:
                log.warning("tft_scouting: artifact write failed: %s", exc)

    def write_status(self, status: str, *, game_id: Optional[str] = None,
                     phase: str = "", identity_source: str = "") -> dict:
        now = self._clock()
        doc = self._doc(status, game_id, phase, identity_source, [], now, now)
        doc["message"] = _RUN_MESSAGES.get(status, "")
        with self._lock:
            self._token += 1
            token = self._token
        self._write(doc, token)
        return doc

    def _doc(self, status, game_id, phase, identity_source, opponents, started, finished) -> dict:
        counts = Counter(o.get("status") for o in opponents)
        return {
            "schema": SCHEMA, "status": status,
            "game_id": str(game_id) if game_id else None,
            "phase": phase or None, "identity_source": identity_source or None,
            "started_at": started, "updated_at": self._clock(), "finished_at": finished,
            "n_matches": self.n,
            "sources": {"riot_api": self._riot_state, "lcu": self._lcu_state},
            "counts": {"ready": counts.get("ready", 0), "pending": counts.get("pending", 0),
                       "unavailable": counts.get("unavailable", 0)},
            "message": "", "opponents": opponents,
        }

    # -- run --
    def start(self, identities: list, **kw) -> bool:
        if kill_switch_off():
            self.write_status("disabled", game_id=kw.get("game_id"))
            return False
        with self._lock:
            self._token += 1
            token = self._token
        t = threading.Thread(target=self._run_safe, args=(list(identities), token, kw),
                             daemon=True, name="TftScouting")
        self._thread = t
        t.start()
        return True

    def _run_safe(self, identities, token, kw) -> None:
        try:
            self._run(identities, token, **kw)
        except Exception as exc:  # noqa: BLE001 - a background run must never raise
            log.warning("tft_scouting: run failed: %s", exc, exc_info=True)

    def scout(self, identities: list, **kw) -> dict:
        with self._lock:
            self._token += 1
            token = self._token
        return self._run(list(identities), token, **kw)

    def _run(self, identities: list, token: int, *, game_id: Optional[str] = None,
             phase: str = "", identity_source: str = "",
             current_set: Optional[int] = None) -> dict:
        started = self._clock()
        deadline = started + self._deadline_s
        idents = [i for i in identities if isinstance(i, Identity)][:MAX_OPPONENTS]
        if not idents:
            doc = self._doc("no_opponents", game_id, phase, identity_source, [], started, started)
            doc["message"] = _RUN_MESSAGES["no_opponents"]
            self._write(doc, token)
            return doc
        cards = [pending_digest(i) for i in idents]
        self._write(self._doc("scouting", game_id, phase, identity_source, cards, started, None),
                    token)
        for idx, ident in enumerate(idents):
            if token != self._token:
                log.info("tft_scouting: run for game %s superseded", game_id)
                return {}
            try:
                cards[idx] = self._scout_one(ident, deadline)
            except Exception as exc:  # noqa: BLE001 - one bad card never sinks the run
                log.warning("tft_scouting: slot %d failed: %s", ident.slot, exc, exc_info=True)
                cards[idx] = unavailable_digest(ident, "unavailable")
            self._write(self._doc("scouting", game_id, phase, identity_source, cards, started,
                                  None), token)
        run_set = current_set
        if run_set is None:
            seen = [_int(s, 0) or 0 for c in cards if isinstance(c.get("sample"), dict)
                    for s in (c["sample"].get("set_counts") or {})]
            run_set = max(seen) if seen else None
        for c in cards:
            apply_current_set(c, run_set)
        ready = sum(1 for c in cards if c["status"] == "ready")
        status = "ready" if ready == len(cards) else "partial" if ready else "unavailable"
        doc = self._doc(status, game_id, phase, identity_source, cards, started, self._clock())
        doc["current_set"] = run_set
        doc["message"] = _RUN_MESSAGES.get(status, "")
        self._write(doc, token)
        log.info("tft_scouting: game %s %s (%d/%d ready, riot_api=%s lcu=%s)",
                 game_id, status, ready, len(cards), self._riot_state, self._lcu_state)
        return doc

    def _scout_one(self, ident: Identity, deadline: float) -> dict:
        cached = self._cache.get(ident)
        if cached is not None:
            cached["slot"] = ident.slot
            cached["cached"] = True
            return cached
        reasons: list = []
        for src in self.sources:
            if src == "riot_api":
                got, why = self._via_riot(ident, deadline)
            elif src == "lcu":
                got, why = self._via_lcu(ident)
            else:
                continue
            if got is not None:
                digest = build_digest(ident, got["rank"], got["rows"], n=self.n, source=src)
                if got.get("partial"):
                    digest["partial"] = True
                else:
                    self._cache.put(ident, digest)
                return digest
            reasons.append(why)
        log.info("tft_scouting: slot %d unavailable (%s)", ident.slot, ",".join(reasons))
        for r in ("rate_limited", "deadline", "not_found", "no_identity"):
            if r in reasons:
                return unavailable_digest(ident, r)
        return unavailable_digest(ident, "unavailable")

    # -- Riot Web API path --
    def _riot_mod(self):
        if self._riot is None:
            from core import riot_api
            self._riot = riot_api
        return self._riot

    def _mark_riot_off(self, state: str) -> None:
        self._riot_state = state
        self._riot_off_until = self._clock() + RIOT_OFF_TTL_S
        log.info("tft_scouting: riot_api path off for %ds (%s)", int(RIOT_OFF_TTL_S), state)

    def _retry(self, fn: Callable[[], Any], scope, deadline: float) -> Any:
        """Call ``fn`` up to RETRY_ATTEMPTS times, waiting out the limiter's
        cooldown between attempts - which `note_429` set from Riot's
        Retry-After header - but only while the run deadline allows."""
        R = self._riot_mod()
        for attempt in range(RETRY_ATTEMPTS):
            before = len(scope.outcomes)
            out = fn()
            if out is not None:
                return out
            new = scope.outcomes[before:]
            if not any(o in _RATE_LIMIT for o in new):
                return None
            now = self._clock()
            if attempt == RETRY_ATTEMPTS - 1 or now >= deadline:
                return None
            try:
                cd = float(R.bucket_snapshot().get("cooldown_remaining_s") or 0.0)
            except Exception:  # noqa: BLE001
                cd = 0.0
            self._sleep(min(max(cd + 0.25, 1.0), max(0.0, deadline - now)))
        return None

    def _via_riot(self, ident: Identity, deadline: float):
        if not (ident.game_name and ident.tag_line):
            return None, "no_identity"
        if self._clock() < self._riot_off_until:
            return None, self._riot_state
        if self._clock() >= deadline:
            # Past the run deadline every call could still wait up to the
            # limiter's 5 s acquire; the LCU path (no Web API budget) takes over.
            return None, "deadline"
        R = self._riot_mod()
        try:
            with R.tft_key_scope(), R.track_outcomes() as sc:
                acct = self._retry(lambda: R.get_account_by_riot_id(
                    ident.game_name, ident.tag_line, region=self.regional), sc, deadline)
                puuid = acct.get("puuid") if isinstance(acct, dict) else None
                if not puuid:
                    # No outcome at all = an RM-163 negative-cache hit, which
                    # only a 404/403 can have written.
                    return None, self._classify(sc.outcomes or ["not_found"])
                entries = self._retry(lambda: R.get_tft_league_entries(
                    puuid, region=self.platform), sc, deadline)
                if entries is None and ("forbidden" in sc.outcomes or sc.rate_limited):
                    return None, self._classify(sc.outcomes)
                ids = self._retry(lambda: R.get_tft_match_ids(
                    puuid, count=self.n, region=self.regional), sc, deadline)
                if ids is None:
                    return None, self._classify(sc.outcomes)
                rows = []
                truncated = ""
                for mid in ids[: self.n]:
                    if self._clock() >= deadline:
                        truncated = "deadline"
                        break
                    before = len(sc.outcomes)
                    m = self._retry(lambda mid=mid: R.get_tft_match(mid, region=self.regional),
                                    sc, deadline)
                    if m is None and any(o in _RATE_LIMIT for o in sc.outcomes[before:]):
                        truncated = "rate_limited"
                        break   # still limited after the retries: the rest would be too
                    row = match_row(m, puuid=puuid, riot_id=ident.riot_id)
                    if row:
                        rows.append(row)
                rank = rank_from_riot_entries(entries)
                if truncated and not rows:
                    return None, truncated
        except Exception as exc:  # noqa: BLE001
            log.warning("tft_scouting: riot_api path raised: %s", exc)
            return None, "error"
        self._riot_state = "ok"
        # A truncated sample is shown but never cached: a 15-min "ready" card
        # built from 1 of 10 matches would read as a thin history.
        return {"rank": rank, "rows": rows, "partial": bool(truncated)}, "ok"

    def _classify(self, outcomes: list) -> str:
        """Why the Riot path produced nothing. A 403 on these routes is the
        measured entitlement answer, so it turns the path off for
        RIOT_OFF_TTL_S instead of being re-paid per opponent."""
        if "forbidden" in outcomes:
            self._mark_riot_off("not_enabled")
            return "not_enabled"
        if "no_key" in outcomes:
            self._mark_riot_off("no_key")
            return "no_key"
        if any(o in _RATE_LIMIT for o in outcomes):
            self._riot_state = "rate_limited"
            return "rate_limited"
        if "not_found" in outcomes:
            return "not_found"
        self._riot_state = "error"
        return "error"

    # -- LCU path (GET only) --
    def _lcu(self, endpoint: str) -> Any:
        try:
            return self._lcu_get(endpoint) if self._lcu_get else None
        except Exception as exc:  # noqa: BLE001
            log.debug("tft_scouting: lcu GET %s raised: %s", endpoint.split("?")[0], exc)
            return None

    def _via_lcu(self, ident: Identity):
        if self._lcu_get is None:
            return None, "lcu_unavailable"
        puuid = ident.lcu_puuid
        if not puuid and ident.game_name and ident.tag_line:
            q = urllib.parse.quote
            r = self._lcu("/lol-summoner/v1/alias/lookup?gameName="
                          f"{q(ident.game_name, safe='')}&tagLine={q(ident.tag_line, safe='')}")
            puuid = real_puuid(r.get("puuid")) if isinstance(r, dict) else ""
            if not puuid:
                return None, "not_found"
        if not puuid:
            return None, "no_identity"
        q_p = urllib.parse.quote(puuid, safe="")
        hist = self._lcu(f"/lol-match-history/v1/products/tft/{q_p}/matches?begin=0&count={self.n}")
        ranked = self._lcu(f"/lol-ranked/v1/ranked-stats/{q_p}")
        games = hist.get("games") if isinstance(hist, dict) else None
        if not isinstance(games, list) and not isinstance(ranked, dict):
            self._lcu_state = "error"
            return None, "unavailable"
        rows = [r for r in (match_row(g, puuid=puuid, riot_id=ident.riot_id)
                            for g in games or []) if r]
        self._lcu_state = "ok"
        return {"rank": rank_from_lcu_ranked(ranked), "rows": rows}, "ok"


# -- the game-start watcher ---------------------------------------------------------

_IN_GAME = ("GameStart", "InProgress")
_POST_GAME = ("PreEndOfGame", "EndOfGame", "WaitingForStats")


class ScoutingWatcher:
    """Polls the LCU gameflow phase (GET only) and fires ONE scouting run per
    TFT game: at game start from the gameflow session, or - when the session
    never listed opponents - once post-game from the EOG stats."""

    def __init__(self, scouter: Scouter, lcu_get: LcuGet, *, interval_s: float = 4.0) -> None:
        self._scouter = scouter
        self._get = lcu_get
        self.interval_s = float(interval_s)
        self._done: set = set()
        self._no_opp: set = set()
        self._self_puuid = ""
        self._self_sid: Any = None
        self._self_gid = ""
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _me(self, gid: str) -> None:
        """Our own puuid / summonerId, re-read ONCE PER GAME: an account switch
        or client re-login without an RC restart must not leave a stale self,
        which would scout the local player as an opponent (verifier s134)."""
        if self._self_puuid and self._self_gid == gid:
            return
        cur = self._get("/lol-summoner/v1/current-summoner")
        if isinstance(cur, dict) and real_puuid(cur.get("puuid")):
            self._self_puuid = real_puuid(cur.get("puuid"))
            self._self_sid = cur.get("summonerId")
            self._self_gid = gid
        else:
            self._self_puuid, self._self_sid, self._self_gid = "", None, ""

    def tick(self) -> Optional[str]:
        """One poll. Returns what it did (for tests / logs)."""
        phase = self._get("/lol-gameflow/v1/gameflow-phase")
        if isinstance(phase, bytes):
            phase = phase.decode("utf-8", "replace")
        phase = str(phase or "").strip().strip('"')
        if phase in _IN_GAME:
            session = self._get("/lol-gameflow/v1/session")
            if not is_tft_session(session):
                return "not_tft"
            gid = session_game_id(session)
            if not gid or gid in self._done:
                return "idle"
            self._me(gid)
            if not self._self_puuid:
                # Without our own puuid the local player would be scouted as an
                # opponent (and push a real one past the 7-cap). Retry next tick.
                return "no_self"
            ids = identities_from_session(session, self._self_puuid, self._self_sid)
            if ids:
                self._done.add(gid)
                self._no_opp.discard(gid)
                self._scouter.start(ids, game_id=gid, phase=phase,
                                    identity_source="lcu_gameflow_session")
                return "started"
            if gid not in self._no_opp:
                self._no_opp.add(gid)
                self._scouter.write_status("no_opponents", game_id=gid, phase=phase,
                                           identity_source="lcu_gameflow_session")
                log.info("tft_scouting: game %s session lists no opponents", gid)
            return "no_opponents"
        if phase in _POST_GAME and self._no_opp:
            eog = self._get("/lol-end-of-game/v1/tft-eog-stats")
            if not isinstance(eog, dict):
                return "idle"
            gid = str(eog.get("gameId") or "")
            if gid not in self._no_opp:
                return "idle"
            self._me(gid)
            ids = identities_from_eog(eog, self._self_puuid)
            self._no_opp.discard(gid)
            self._done.add(gid)
            if ids:
                self._scouter.start(ids, game_id=gid, phase=phase, identity_source="lcu_eog")
                return "started_post_game"
            return "idle"
        return "idle"

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the poller must survive anything
                log.debug("tft_scouting: watcher tick failed: %s", exc)
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TftScoutWatch")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def default_lcu_get() -> LcuGet:
    """A GET-only LCU reader on a dedicated client (``lcu/lcu_client.py`` is
    frozen and only READ here; the one method string this module ever sends is
    "GET")."""
    from lcu.lcu_client import LcuClient
    client = LcuClient()
    lock = threading.Lock()

    def get(endpoint: str) -> Any:
        with lock:
            try:
                client._refresh_conn_if_changed()
                if not client._port:
                    client.connect()
                if not client._port:
                    return None
                return client._request("GET", endpoint)
            except Exception:  # noqa: BLE001
                return None

    return get


_WATCHER: Optional[ScoutingWatcher] = None
_WATCHER_LOCK = threading.Lock()


def start_scouting_watcher() -> Optional[ScoutingWatcher]:
    """Idempotent entry point (called from dashboard/server.py start_dashboard).
    Returns None when the kill switch ``RC_TFT_SCOUTING=0`` is set."""
    global _WATCHER
    if kill_switch_off():
        log.info("tft_scouting: disabled by %s", ENV_KILL)
        return None
    with _WATCHER_LOCK:
        if _WATCHER is None:
            get = default_lcu_get()
            _WATCHER = ScoutingWatcher(Scouter(lcu_get=get), get)
        _WATCHER.start()
        return _WATCHER


__all__ = [
    "ARTIFACT_PATH", "SCHEMA", "DigestCache", "Identity", "Scouter", "ScoutingWatcher",
    "build_digest", "clean_name", "compute_threat", "identities_from_eog",
    "identities_from_session", "is_tft_session", "match_row", "rank_from_lcu_ranked",
    "rank_from_riot_entries", "real_puuid", "start_scouting_watcher",
]
