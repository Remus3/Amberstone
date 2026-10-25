"""tft/sources/eog_file.py - the per-round TFTEoGStats.json source (slice TFT-02).

docs/TFT_PROGRAM.md section 0 item 2: the standalone TFT client rewrites
`%LOCALAPPDATA%/TFT/Saved/Logs/TFTEoGStats.json` once per round at planning
start. Each rewrite carries, for all 8 players, `health`, `ffaStanding` and
`boardPieces` ({championName, starLevel, itemNames, price}) - the section 1.4 source for rows 2, 7, 8, 12 and the opponent boards
of row 16, src `eog_file`, conf 1.0 (section 1.1).

Reuse (slice row: "import tft/tft_standalone.py helpers rather than
re-implement them"): the path seam `eog_stats_path` (env `RC_TFT_EOG_PATH`),
the fresh / torn / non-TFT read `read_eog` and its window `EOG_MAX_AGE_S`
come from the P0 module; `tft.tft_set.parse_set_id` turns "TFTSet18" into 18.

Three layers, each fail-soft (a bad file reads as "nothing new", never an
exception into a poll loop):

  * `parse_eog(doc, salt=...)` - pure: one decoded file -> `EogSnapshot`. Keys
    are read by ALLOWLIST (DOC_FIELDS, STATS_FIELDS, PLAYER_FIELDS,
    PIECE_FIELDS). Identity fields (IDENTITY_KEYS) are read only to derive the
    section 1.2 `player_key` HMAC in memory (KEY_BASIS_FIELDS: the PUUID, or
    when it is absent or all zeros the Riot id, then the summoner name, then a
    per-game slot), and are never copied. Unit and item ids must have the game
    api shape (DA_18_Yorick, DA_GiantSlayer, TFT_Item_...); anything else is
    dropped from that one unit or list.
  * LOCAL PLAYER: only from the injected `local_player_id` - the LCU summoner
    id (an int or digit string, matched against a row's `playerId`) or a PUUID
    (matched against `PUUID`); a callable returning either is resolved on every
    poll. Exactly one matching row is the local player; no id, no match, two
    matches or a failing callable = unknown (`local_key` None, `is_local` None),
    never a guess and never carried from another rewrite. `isInteractable` is
    NOT read: it does not mark the local player in a human lobby (s135 verifier:
    8/8 in every end-of-game copy; mid-match the first interactable row was the
    8th-place player - bug N13). The id is compared in memory, never copied.
  * `EogFileSource` - stats the file each poll and emits a snapshot only for a
    NEW rewrite: identical content is skipped, a changed game length opens the
    next rewrite index, a changed game id restarts it.
  * `EogIngest` - writes snapshots into the TFT-01 round store: the match row
    (found by game_id, else created with a deterministic match_id), player rows
    (slot 1 = local when known, final_standing, eliminated_round_seq), per round all-8
    `player_round` (hp clamped at 0; overkill stays in the raw obs), the board
    `unit_obs` (phase planning_start, zone board), the local `hp_start`
    envelope, one `eog.player` obs per player (raw values), one `eog.round` obs
    and one `eog_rewrite` event. `round_seq` = the match's rewrite count, so a
    restarted process resumes the same match without duplicating a round.
    `locate(ts)` maps a timestamp to (match_id, round_seq) for the TFT.log
    source; fusing round boundaries across sources stays TFT-07's.

Log lines name a rule or a count, never a value (section 1.2).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from bisect import bisect_right
from dataclasses import dataclass, replace
from typing import Callable, Optional

from tft import tft_set
from tft import tft_standalone as p0
from tft.rounds.store import Env, RoundStore, player_key

_log = logging.getLogger(__name__)

SRC = "eog_file"
CONF = 1.0  # section 1.1: 1.0 when the snapshot parsed and is for this round
PHASE = "planning_start"  # the file is rewritten at planning start
EXTRACTOR_VERSION = "tft02-eog/1"
MAX_EOG_BYTES = 1 << 20  # the live file is ~11 KB; a 1 MB cap bounds the read
MATCH_ID_PREFIX = "tft-"
OBS_PLAYER = "eog.player"
OBS_ROUND = "eog.round"
# locate(): a log stamp more than this after the latest rewrite is not this
# match's (a round is ~30-75 s, the carousel a little longer)
ROUND_GAP_MAX_S = 180.0
# locate(): stamps this long before the estimated game start are not this match's
MATCH_START_SLACK_S = 120.0

# -- the key allowlist (the identity guard in tests/test_tft_sources_eog_file.py
# enumerates every key of the file against these sets) -------------------------
DOC_FIELDS = frozenset({"gameId", "gameMode", "queueId", "statsBlock"})
STATS_FIELDS = frozenset({"gameLengthSeconds", "setCoreName", "players"})
PLAYER_FIELDS = frozenset({"health", "ffaStanding", "boardPieces", "augments"})
PIECE_FIELDS = frozenset({"championName", "starLevel", "itemNames", "price"})
# identity: read in memory for the HMAC key at most (KEY_BASIS_FIELDS), never copied
KEY_BASIS_FIELDS = ("PUUID", "riotIdGameName", "riotIdTagLine", "summonerName")
# identity compared in memory with the injected local_player_id, never copied
LOCAL_MATCH_FIELDS = ("playerId", "PUUID")
IDENTITY_KEYS = frozenset({
    "PUUID", "puuid", "riotIdGameName", "riotIdTagLine", "gameName", "tagLine",
    "summonerName", "summonerId", "accountId", "playerId",
    "companionContentId", "companionName", "companionSkinId", "summonerIconID",
})
# never read: cosmetics, event-mode blobs, the Double Up team id
# isInteractable: NOT a local-player signal (bug N13), so it is never read
IGNORED_KEYS = frozenset({"isInteractable", "isRanked", "queueType", "customAugmentContainer",
                          "eventPVEData",
                          "eventSkillDeltas", "partnerGroupId", "playbookItemId",
                          "endOfGameAlias"})

_API = re.compile(r"(?:DA|TFT[0-9]*)_[A-Za-z0-9_]{1,60}")
_SET_CORE = re.compile(r"[A-Za-z0-9_]{1,64}")
_ZERO_ID = re.compile(r"[0\-]*")


@dataclass(frozen=True)
class EogUnit:
    champion_api: str
    star: Optional[int]
    items: tuple
    cost: Optional[int]


@dataclass(frozen=True)
class EogPlayer:
    player_key: str
    index: int  # position in the file's players list (stable within a match)
    hp_raw: Optional[int]  # as written: eliminated players carry negative overkill
    hp: Optional[int]  # hit points, clamped at 0
    alive: Optional[bool]
    standing: Optional[int]  # ffaStanding 1-8 once placed; None while 0
    board: tuple  # EogUnit
    augments: tuple  # api names; measured empty although augments were taken
    is_local: Optional[bool] = None  # None = the local player is not known


@dataclass(frozen=True)
class EogSnapshot:
    game_id: Optional[int]  # memory / match table only: never in an obs or event
    queue_id: Optional[int]
    set_core_name: Optional[str]
    set_id: Optional[int]
    game_length_s: Optional[int]
    mtime: Optional[float]
    players: tuple  # EogPlayer
    local_key: Optional[str] = None
    rewrite_index: Optional[int] = None  # set by EogFileSource (1-based per game)
    fingerprint: str = ""


@dataclass(frozen=True)
class Written:
    match_id: str
    round_seq: int
    snapshot: EogSnapshot


# ---------------------------------------------------------------- parse


def _as_int(v, lo=None, hi=None) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")) or v != int(v):
            return None
        v = int(v)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        return None
    return v


def _api(v) -> Optional[str]:
    return v if isinstance(v, str) and len(v) <= 64 and _API.fullmatch(v) else None


def _api_list(v) -> tuple:
    return tuple(x for x in (v if isinstance(v, list) else ()) if _api(x))


def _identity(p: dict) -> Optional[str]:
    """The section 1.2 identity, bare (so a key derived here equals one derived
    from the same identity anywhere else): the PUUID, else the Riot id
    (name#tag), else the summoner name. An all-zero PUUID counts as absent."""
    puuid = p.get("PUUID")
    if isinstance(puuid, str) and puuid.strip() and not _ZERO_ID.fullmatch(puuid.strip()):
        return puuid.strip()
    name = p.get("riotIdGameName")
    if isinstance(name, str) and name.strip():
        tag = p.get("riotIdTagLine")
        tag = tag.strip() if isinstance(tag, str) else ""
        return f"{name.strip()}#{tag}" if tag else name.strip()
    summ = p.get("summonerName")
    if isinstance(summ, str) and summ.strip():
        return summ.strip()
    return None


def _player_keys(rows, salt, game_id) -> list:
    out, used = [], set()
    for i, p in enumerate(rows):
        basis = _identity(p) or f"tft-eog-slot:{game_id or 0}:{i}"
        key = player_key(basis, salt)
        if key in used:  # two rows with one identity: keep both, distinctly
            key = player_key(f"{basis}:{i}", salt)
        used.add(key)
        out.append(key)
    return out


def _board(pieces) -> tuple:
    out = []
    for pc in pieces if isinstance(pieces, list) else ():
        if not isinstance(pc, dict):
            continue
        api = _api(pc.get("championName"))
        if api is None:
            continue
        out.append(EogUnit(api, _as_int(pc.get("starLevel"), 1, 4),
                           _api_list(pc.get("itemNames")), _as_int(pc.get("price"), 0, 10)))
    return tuple(out)


def _fingerprint(game_id, length, players) -> str:
    body = json.dumps([game_id, length, [
        [p.player_key, p.hp_raw, p.standing, list(p.augments),
         [[u.champion_api, u.star, list(u.items), u.cost] for u in p.board]]
        for p in players]], separators=(",", ":"))
    return hashlib.sha256(body.encode("ascii", "replace")).hexdigest()[:16]


def _with_local(snap: EogSnapshot, local: Optional[str]) -> EogSnapshot:
    players = tuple(replace(p, is_local=None if local is None else p.player_key == local)
                    for p in snap.players)
    return replace(snap, players=players, local_key=local)


def _local_id(v) -> Optional[tuple]:
    """("player_id", int) | ("puuid", str) | None for an injected local id."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return ("player_id", v) if v > 0 else None
    if isinstance(v, str):
        s = v.strip()
        if not s or _ZERO_ID.fullmatch(s):
            return None
        if s.isdigit():
            return ("player_id", int(s)) if int(s) > 0 else None
        return ("puuid", s)
    return None


def _local_index(rows, local_player_id) -> Optional[int]:
    """The index of the ONE row the injected id names, else None."""
    want = _local_id(local_player_id)
    if want is None:
        return None
    kind, val = want
    hits = []
    for i, p in enumerate(rows):
        if kind == "player_id":
            got = p.get("playerId")
            got = int(got) if isinstance(got, str) and got.strip().isdigit() else _as_int(got)
        else:
            got = p.get("PUUID").strip() if isinstance(p.get("PUUID"), str) else None
        if got == val:
            hits.append(i)
    return hits[0] if len(hits) == 1 else None


def parse_eog(doc, *, salt: bytes, mtime: Optional[float] = None,
              local_player_id=None) -> Optional[EogSnapshot]:
    """One decoded TFTEoGStats.json -> EogSnapshot, or None when it is not a
    TFT stats document. `local_player_id` (summoner id / playerId or PUUID)
    names the local player; without a single matching row it stays unknown.
    Never raises."""
    try:
        return _parse(doc, salt, mtime, local_player_id)
    except Exception as exc:  # noqa: BLE001 - a malformed file never reaches a poll loop
        _log.debug("tft eog: parse failed (%s)", type(exc).__name__)
        return None


def _parse(doc, salt, mtime, local_player_id) -> Optional[EogSnapshot]:
    if not isinstance(doc, dict) or "TFT" not in str(doc.get("gameMode") or ""):
        return None
    sb = doc.get("statsBlock")
    if not isinstance(sb, dict) or not isinstance(sb.get("players"), list):
        return None
    rows = [p for p in sb["players"] if isinstance(p, dict)]
    if not rows:
        return None
    game_id = _as_int(doc.get("gameId"), lo=1)
    keys = _player_keys(rows, salt, game_id)
    players = []
    for i, (p, key) in enumerate(zip(rows, keys)):
        hp_raw = _as_int(p.get("health"))
        players.append(EogPlayer(
            player_key=key, index=i, hp_raw=hp_raw,
            hp=None if hp_raw is None else max(hp_raw, 0),
            alive=None if hp_raw is None else hp_raw > 0,
            standing=_as_int(p.get("ffaStanding"), 1, 8),
            board=_board(p.get("boardPieces")), augments=_api_list(p.get("augments"))))
    core = sb.get("setCoreName")
    core = core if isinstance(core, str) and _SET_CORE.fullmatch(core) else None
    length = _as_int(sb.get("gameLengthSeconds"), lo=0)
    li = _local_index(rows, local_player_id)
    snap = EogSnapshot(
        game_id=game_id, queue_id=_as_int(doc.get("queueId"), lo=0), set_core_name=core,
        set_id=tft_set.parse_set_id(core) if core else None, game_length_s=length,
        mtime=None if mtime is None else float(mtime), players=tuple(players),
        fingerprint=_fingerprint(game_id, length, players))
    return _with_local(snap, None if li is None else players[li].player_key)


# ---------------------------------------------------------------- the file source


class EogFileSource:
    """Polls the per-round file and emits each NEW rewrite once.

    Every poll is one stat; the file is read (through the P0 `read_eog`) only
    when its (mtime, size) changed and it is at most `max_bytes`."""

    def __init__(self, *, salt: bytes, local_player_id=None,
                 clock: Callable[[], float] = time.time,
                 max_age_s: float = p0.EOG_MAX_AGE_S, max_bytes: int = MAX_EOG_BYTES):
        self.salt = bytes(salt)
        # int | str | Callable[[], int | str | None] | None - see the module docstring
        self.local_player_id = local_player_id
        self.clock = clock
        self.max_age_s = max_age_s
        self.max_bytes = max_bytes
        self._sig = None
        self._game = None
        self._index = 0
        self._length = None
        self._fp = None
        self.stats = {"polls": 0, "snapshots": 0, "unchanged": 0, "stale_or_torn": 0,
                      "unparsed": 0, "oversize": 0, "errors": 0}

    def poll(self) -> Optional[EogSnapshot]:
        try:
            return self._poll()
        except Exception as exc:  # noqa: BLE001 - fail-soft: never into the poll loop
            self.stats["errors"] += 1
            _log.debug("tft eog: poll failed (%s)", type(exc).__name__)
            return None

    def _poll(self) -> Optional[EogSnapshot]:
        self.stats["polls"] += 1
        try:
            st = p0.eog_stats_path().stat()
        except OSError:
            return None
        sig = (st.st_mtime_ns, st.st_size)
        if sig == self._sig:
            self.stats["unchanged"] += 1
            return None
        if st.st_size > self.max_bytes:
            self._sig = sig
            self.stats["oversize"] += 1
            _log.warning("tft eog: stats file above the %d byte cap; not read", self.max_bytes)
            return None
        doc = p0.read_eog(now=self.clock(), max_age_s=self.max_age_s)
        if doc is None:  # stale, torn mid-write, or not TFT: retried on the next poll
            self.stats["stale_or_torn"] += 1
            return None
        self._sig = sig
        snap = parse_eog(doc, salt=self.salt, mtime=doc.get("_mtime") or st.st_mtime,
                         local_player_id=self._resolve_local_id())
        if snap is None:
            self.stats["unparsed"] += 1
            return None
        return self._sequence(snap)

    def _resolve_local_id(self):
        v = self.local_player_id
        if not callable(v):
            return v
        try:
            return v()
        except Exception as exc:  # noqa: BLE001 - a failing helper = local unknown
            _log.debug("tft eog: local id helper failed (%s)", type(exc).__name__)
            return None

    def _sequence(self, snap: EogSnapshot) -> Optional[EogSnapshot]:
        if snap.game_id != self._game or self._index == 0:
            self._game, self._index, self._length, self._fp = snap.game_id, 0, None, None
        if (snap.fingerprint, snap.local_key) == self._fp:
            self.stats["unchanged"] += 1
            return None
        if self._index == 0 or snap.game_length_s != self._length:
            self._index += 1
        self._length, self._fp = snap.game_length_s, (snap.fingerprint, snap.local_key)
        self.stats["snapshots"] += 1
        return replace(snap, rewrite_index=self._index)


# ---------------------------------------------------------------- into the round store


def match_id_for(game_id, salt: bytes) -> str:
    """The deterministic, non-reversible match_id of a game first seen by the
    EoG source (a restart reopens the same row)."""
    digest = hmac.new(bytes(salt), f"tft-eog-match:{int(game_id)}".encode("ascii"), hashlib.sha256)
    return MATCH_ID_PREFIX + digest.hexdigest()[:16]


def _match_id_without_game(keys, salt: bytes) -> str:
    digest = hmac.new(bytes(salt), ("tft-eog-match-keys:" + ",".join(sorted(keys))).encode("ascii"),
                      hashlib.sha256)
    return MATCH_ID_PREFIX + digest.hexdigest()[:16]


class _Match:
    def __init__(self, match_id, game_id, start):
        self.match_id = match_id
        self.game_id = game_id
        self.start = start
        self.by_length = {}  # game_length_s -> round_seq
        self.first_ts = {}  # round_seq -> first rewrite mtime (planning start)
        self.fps = {}  # round_seq -> fingerprint written by THIS process
        self.top = 0
        self.eliminated = set()

    def times(self):
        return sorted((t, s) for s, t in self.first_ts.items() if t is not None)


class EogIngest:
    """Writes EoG snapshots into the round store (see the module docstring)."""

    def __init__(self, store: RoundStore, *, salt: bytes, source: Optional[EogFileSource] = None,
                 local_player_id=None, extractor_version: str = EXTRACTOR_VERSION):
        """`local_player_id` configures the default source; a passed `source`
        carries its own."""
        self.store = store
        self.salt = bytes(salt)
        self.source = source if source is not None else EogFileSource(
            salt=self.salt, local_player_id=local_player_id)
        self.extractor_version = extractor_version
        self._m: Optional[_Match] = None
        self.stats = {"rounds": 0, "updates": 0, "match_dropped": 0, "errors": 0}

    @property
    def match_id(self) -> Optional[str]:
        return self._m.match_id if self._m else None

    def poll(self) -> Optional[Written]:
        snap = self.source.poll()
        return None if snap is None else self.ingest(snap)

    def ingest(self, snap: EogSnapshot) -> Optional[Written]:
        """Write one snapshot; returns where it landed, or None (never raises)."""
        try:
            return self._ingest(snap)
        except Exception as exc:  # noqa: BLE001 - fail-soft
            self.stats["errors"] += 1
            _log.debug("tft eog: ingest failed (%s)", type(exc).__name__)
            return None

    # -- match / round bookkeeping

    def _match_for(self, snap: EogSnapshot) -> Optional[_Match]:
        if self._m is not None and self._m.game_id == snap.game_id:
            return self._m
        start = snap.mtime
        if snap.mtime is not None and snap.game_length_s is not None:
            start = snap.mtime - snap.game_length_s
        existing = None
        if snap.game_id is not None:
            mid = match_id_for(snap.game_id, self.salt)
            existing = next((m for m in self.store.list_matches()
                             if m.get("game_id") == snap.game_id), None)
        else:
            mid = _match_id_without_game([p.player_key for p in snap.players], self.salt)
        if existing is not None:
            m = _Match(existing["match_id"], snap.game_id, existing.get("started_at") or start)
            self._resume(m)
        else:
            got = self.store.begin_match({
                "match_id": mid, "game_id": snap.game_id, "set_id": snap.set_id,
                "set_core_name": snap.set_core_name, "queue_id": snap.queue_id,
                "started_at": start, "extractor_version": self.extractor_version})
            if got is None:
                self.stats["match_dropped"] += 1
                return None
            m = _Match(got, snap.game_id, start)
        self._m = m
        return m

    def _resume(self, m: _Match) -> None:
        """Seed a match a previous process opened: its rewrite rounds (from the
        eog_rewrite events) and the players already marked eliminated."""
        doc = self.store.get_match(m.match_id) or {}
        for r in doc.get("rounds") or []:
            for e in r.get("events") or []:
                if e.get("kind") != "eog_rewrite" or e.get("src") != SRC:
                    continue
                seq = r["round_seq"]
                length = (e.get("payload") or {}).get("game_length_s")
                m.by_length.setdefault(length, seq)
                ts = e.get("ts")
                if ts is not None and (m.first_ts.get(seq) is None or ts < m.first_ts[seq]):
                    m.first_ts[seq] = ts
                m.top = max(m.top, seq)
        for p in doc.get("players") or []:
            if p.get("eliminated_round_seq") is not None:
                m.eliminated.add(p["player_key"])

    def locate(self, ts) -> Optional[tuple]:
        """(match_id, round_seq) for a wall-clock stamp of the current match:
        round_seq = the last rewrite at or before ts, None before the first
        one. None when there is no match or ts is outside it."""
        m = self._m
        if m is None or not isinstance(ts, (int, float)):
            return None
        if m.start is not None and ts < m.start - MATCH_START_SLACK_S:
            return None
        times = m.times()
        if times and ts > times[-1][0] + ROUND_GAP_MAX_S:
            return None
        i = bisect_right([t for t, _ in times], ts)
        return m.match_id, (times[i - 1][1] if i else None)

    # -- writes

    def _ingest(self, snap: EogSnapshot) -> Optional[Written]:
        m = self._match_for(snap)
        if m is None:
            return None
        seq = m.by_length.get(snap.game_length_s)
        new_round = seq is None
        if new_round:
            m.top += 1
            seq = m.top
            m.by_length[snap.game_length_s] = seq
            m.first_ts[seq] = snap.mtime
            self.stats["rounds"] += 1
        else:
            self.stats["updates"] += 1
        # raw evidence once per distinct content this process saw for the round;
        # a resumed round (no fingerprint here) only refreshes the typed rows
        evidence = new_round or m.fps.get(seq) not in (None, snap.fingerprint)
        m.fps[seq] = snap.fingerprint
        self._write(m, seq, snap, evidence=evidence, new_round=new_round)
        return Written(m.match_id, seq, snap)

    def _write(self, m: _Match, seq: int, snap: EogSnapshot, *, evidence: bool, new_round: bool):
        st, mid, ts, local = self.store, m.match_id, snap.mtime, snap.local_key
        others = [p.player_key for p in snap.players if p.player_key != local]
        slots = {} if local is None else {local: 1, **{k: i for i, k in enumerate(others[:7], 2)}}
        for p in snap.players:
            kw = {}
            if local is not None:
                kw["is_local"] = p.player_key == local
                kw["slot"] = slots.get(p.player_key)
            if p.standing is not None:
                kw["final_standing"] = Env(p.standing, CONF, SRC)
            if p.alive is False and p.player_key not in m.eliminated:
                m.eliminated.add(p.player_key)
                kw["eliminated_round_seq"] = seq
            st.upsert_player(mid, p.player_key, **kw)
        for p in snap.players:
            if p.hp is not None or p.standing is not None:
                st.put_player_round(mid, seq, p.player_key, hp=p.hp, alive=p.alive,
                                    standing=p.standing, conf=CONF, src=SRC)
            st.put_units(mid, seq, PHASE, p.player_key, [
                {"zone": "board", "champion_api": u.champion_api, "star": u.star,
                 "items": list(u.items), "cost": u.cost, "conf": CONF, "src": SRC}
                for u in p.board], zone="board")
        lp = next((p for p in snap.players if p.player_key == local), None)
        if lp is not None and lp.hp is not None:
            st.upsert_round(mid, seq, hp_start=Env(lp.hp, CONF, SRC))
        if evidence:
            for p in snap.players:
                st.record_obs(mid, seq, PHASE, OBS_PLAYER, {
                    "player_key": p.player_key, "is_local": p.is_local, "hp": p.hp_raw,
                    "alive": p.alive, "standing": p.standing, "augments": list(p.augments),
                    "board": [{"champion_api": u.champion_api, "star": u.star,
                               "items": list(u.items), "cost": u.cost} for u in p.board],
                }, CONF, SRC, ts=ts, extractor_version=self.extractor_version)
            st.record_obs(mid, seq, PHASE, OBS_ROUND, {
                "rewrite_index": seq, "game_length_s": snap.game_length_s,
                "players": len(snap.players),
                "players_alive": sum(1 for p in snap.players if p.alive),
                "local_known": local is not None,
            }, CONF, SRC, ts=ts, extractor_version=self.extractor_version)
        if new_round:
            st.put_event(mid, "eog_rewrite", {"rewrite_index": seq,
                                              "game_length_s": snap.game_length_s},
                         ts=ts, round_seq=seq, src=SRC)
