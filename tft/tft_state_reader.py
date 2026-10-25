"""
tft/tft_state_reader.py - Riot Live Client API reader for TFT.
Variant detection via queue id / mode strings (map 22 is every TFT game, not
Double Up - S134). Stage/round from OCR (free),
else the round clock (observed round starts from the standalone per-round
file, S134), with the time table as the last fallback.
"""
import json
import ssl
import logging
import urllib.request
import threading
import time
from typing import TYPE_CHECKING, NamedTuple, Optional

from core.game_host import GAME_HOST

if TYPE_CHECKING:
    from core.game_snapshot import TftSnapshot

logger = logging.getLogger("rc.tft.reader")
TFT_API = f"https://{GAME_HOST}:2999/liveclientdata/allgamedata"
_TIME_TO_ROUND = [
    # Set 17 Space Gods Double Up - calibrated from 3 confirmed live data points:
    # t=32s->1-2, t=348s->2-5, t~1002s->4-6, t=1879s->7-4
    # Fit: ~51 seconds per round on average
    (0,   1, 1), (32,  1, 2), (82,  1, 3),
    (144, 2, 1), (195, 2, 2), (246, 2, 3), (297, 2, 4), (348, 2, 5), (399, 2, 6),
    (450, 3, 1), (501, 3, 2), (552, 3, 3), (603, 3, 4), (654, 3, 5), (705, 3, 6),
    (756, 4, 1), (807, 4, 2), (858, 4, 3), (909, 4, 4), (960, 4, 5), (1011, 4, 6), (1062, 4, 7),
    (1113, 5, 1), (1164, 5, 2), (1215, 5, 3), (1266, 5, 4), (1317, 5, 5), (1368, 5, 6),
    (1419, 6, 1), (1470, 6, 2), (1521, 6, 3), (1572, 6, 4), (1623, 6, 5), (1674, 6, 6),
    (1725, 7, 1), (1776, 7, 2), (1827, 7, 3), (1878, 7, 4),
]
# Set 18, the FALLBACK gameTime -> round table (re-fit S134 on two live Set 18
# normal games: ops/runtime/tft_qa/20261025-070350, QA_REPORT.md section 2,
# and 20261025-081234, section 3). Each game's round start = midpoint of the
# previous round's last frame and this round's first frame on the HUD stage
# label (frames 20-45 s apart); clock zero from the LCU EOG gameLength. The
# games ran at different paces (2-3..6-1: about 65 and 60.5 s per round; 6-1
# began at 2029 and 1849 s), so no fixed table tracks both: a row here is the
# MEAN of the two games' starts, which keeps the table within 2 rounds of
# every frame of either game (the game-1-only table was 3 rounds behind
# game 2 by 6-1). It is used only when no round start was OBSERVED (see
# RoundClock below). Stage 1 has 4 rounds and stages 2+ have 7
# (CommunityDragon StageRoundData agrees). Guards:
# tests/test_tft_round_clock_s134.py, tests/test_tft_set18_schedule_lt01.py.
_TIME_TO_ROUND_SET18 = [
    # 1-1 / 1-2 / 1-3: game-data phase durations (game 2 saw 1-3 by 74 s);
    # 1-4, 2-1, 2-2: game 2 only (game 1's recorder joined at 2-2).
    (0,    1, 1), (25,   1, 2), (65,   1, 3), (104,  1, 4),
    (151,  2, 1), (216,  2, 2),
    # MEASURED in both games: the mean start.
    (308,  2, 3), (371,  2, 4), (406,  2, 5), (474,  2, 6), (550,  2, 7),
    (584,  3, 1), (672,  3, 2), (758,  3, 3), (822,  3, 4), (865,  3, 5), (928,  3, 6), (1002, 3, 7),
    (1048, 4, 1), (1124, 4, 2), (1213, 4, 3), (1282, 4, 4), (1322, 4, 5), (1388, 4, 6), (1465, 4, 7),
    (1510, 5, 1), (1574, 5, 2), (1648, 5, 3), (1722, 5, 4), (1755, 5, 5), (1833, 5, 6), (1898, 5, 7),
    (1939, 6, 1),
    # EXTRAPOLATED (both games ended in 6-1): 6-1 lasts like the measured x-1
    # rounds (about 76 s), then 63 s per round, the two games' mean pace.
    (2015, 6, 2), (2078, 6, 3), (2141, 6, 4), (2204, 6, 5), (2267, 6, 6), (2330, 6, 7),
    (2393, 7, 1), (2456, 7, 2), (2519, 7, 3), (2582, 7, 4), (2645, 7, 5), (2708, 7, 6), (2771, 7, 7),
]


def _time_table(set_number=None):
    """The gameTime -> round table for a set: Set 18's measured table, else the
    legacy Set 17 calibration (the only table for any other set)."""
    return _TIME_TO_ROUND_SET18 if set_number == 18 else _TIME_TO_ROUND


def time_table(set_number=None):
    """The set-aware gameTime -> round table for other modules (S134): the
    resolved set's (tft/tft_set.py resolve_set) when set_number is None.
    _TIME_TO_ROUND keeps its name and meaning (the Set 17 calibration) for
    readers that import it directly (core/tft_stage_gate.py, RM-615)."""
    if set_number is None:
        try:
            from tft import tft_set
            set_number = tft_set.resolve_set()
        except Exception:  # noqa: BLE001
            set_number = None
    return _time_table(set_number)


# TFT queues that are Double Up (lol-game-queues, measured 2026-10-25:
# 1160 "Double Up", assetMutator TFT_PAIRS). Not map 22: that is every TFT game.
DOUBLE_UP_QUEUES = frozenset({1160})


def _estimate_round(t, set_number=None):
    s, r = 1, 1
    for ms, st, rn in _time_table(set_number):
        if t >= ms: s, r = st, rn
        else: break
    return s, r


# -- round clock: an OBSERVED round start first, the time table last (S134) ---
# The standalone client rewrites its per-round stats file (tft/tft_standalone.py
# read_eog; statsBlock.gameLengthSeconds) at each planning phase, so every new
# gameLengthSeconds is the game-clock start of a round. Measured 2026-10-25 by
# watching the file passively through a third live Set 18 game: starts 582,
# 647, 741, 821, 932, 1010, 1073, 1138, 1239, 1311, 1420 s - one rewrite per
# round with a planning phase and NONE for a carousel (821 -> 932 and
# 1311 -> 1420 each span an x-3 plus the x-4 carousel). The first start
# seen in a game is placed by the time table (nearest table start); each later
# one is the next round that has a planning phase. So the round follows the
# game's own pace, which differed by ~5 s per round between the QA games.
# The file also carries every player's health: when NO player's health moved
# between two starts, the round that began at the first was PvE (a PvP round
# always has a loser), which pins it to the nearest PvE round of the schedule
# - an observed stage anchor that also corrects a late first placement (in the
# watched game 582 -> 647 kept all 8 healths: 2-7, while the table said 3-1).
# A gap longer than _MISSED_GAP_S means rewrites were missed (RC was down): the
# table's progression over that gap counts the rounds, never less than one.
_MISSED_GAP_S = 180.0


def _row_index(table, t) -> int:
    """Index of the table row in force at game time t (0 before any row)."""
    i = 0
    for k, (ms, _, _) in enumerate(table):
        if t >= ms: i = k
        else: break
    return i


def _no_planning_rounds(schedule) -> frozenset:
    """Rounds of a schedule that have no planning phase (a carousel), so the
    per-round file is not rewritten at their start."""
    return frozenset(rk for rk, ev in schedule.events.items() if ev == "carousel")


class RoundClock:
    """The current (stage, round) from observed round starts; the time table
    only before the first one (or for a game with no per-round file)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self, game=None, table=None) -> None:
        self._game, self._table, self._t, self._i = game, table, None, None
        self._hp = None

    def _skip(self, i: int, skip) -> int:
        while i < len(self._table) - 1 and tuple(self._table[i][1:]) in skip:
            i += 1
        return i

    def note_start(self, game, t: float, table, skip=frozenset(), hp=None,
                   pve=frozenset()) -> None:
        """Record an observed round start ``t`` (game-clock s) of ``game``.

        ``skip``: rounds with no planning phase (no rewrite). ``hp``: every
        player's health at this start, in file order. ``pve``: the
        schedule's PvE rounds.
        """
        if not table:
            return
        hp = tuple(hp) if hp else None
        if hp and not any(isinstance(h, (int, float)) and not isinstance(h, bool)
                          and h > 0 for h in hp):
            hp = None  # all missing / zero: not a health reading at all
        if (game != self._game or table is not self._table
                or self._t is None or t < self._t - 1.0):
            self.reset(game, table)
            rows = [k for k, row in enumerate(table) if tuple(row[1:]) not in skip]
            self._i = min(rows or [0], key=lambda k: abs(table[k][0] - t))
            self._t, self._hp = t, hp
            return
        if t - self._t < 1.0:
            return  # the same rewrite read again
        if hp and self._hp and hp == self._hp and t - self._t <= _MISSED_GAP_S:
            rows = [k for k, row in enumerate(table) if tuple(row[1:]) in pve]
            if rows:  # nobody lost health: the round just played was PvE
                self._i = min(rows, key=lambda k: abs(k - self._i))
        step = 1
        if t - self._t > _MISSED_GAP_S:
            step = max(1, _row_index(table, t) - _row_index(table, self._t))
        self._i = self._skip(min(self._i + step, len(table) - 1), skip)
        self._t, self._hp = t, hp

    def round_at(self, t: float, table, skip=frozenset()) -> tuple:
        """(stage, round) at game time ``t``. A round with no planning phase
        (``skip``, a carousel) gets no rewrite of its own, so once the round
        that began at the last observed start has run its table length, the
        clock moves into the carousel that follows it."""
        if self._i is None or table is not self._table or t < self._t - 1.0:
            _, s, r = table[_row_index(table, t)] if table else (0, 1, 1)
            return s, r
        i = self._i
        if t - self._t > _MISSED_GAP_S:
            # no start seen for too long (the file went stale): carry the
            # last observed round forward by the table's progression
            i = min(len(table) - 1,
                    i + max(0, _row_index(table, t) - _row_index(table, self._t)))
        elif (i + 1 < len(table) and tuple(table[i + 1][1:]) in skip
                and t - self._t >= table[i + 1][0] - table[i][0]):
            i += 1
        _, s, r = table[i]
        return s, r

_last_logged_sr = None  # for calibration logging
def _log_round_calibration(t, stage, rnd):
    global _last_logged_sr
    sr = f"{stage}-{rnd}"
    if sr != _last_logged_sr:
        logger.debug("Round calibration: t=%.1fs -> %s", t, sr)
        _last_logged_sr = sr

class TftStateReader:
    _variant_logged = False  # reset each game in __init__
    def __init__(self) -> None:
        self._ssl=ssl.create_default_context();self._ssl.check_hostname=False;self._ssl.verify_mode=ssl.CERT_NONE
        self._my_name="";self._last_level=1;self._last_gold=0
        self._confirmed_stage=1;self._confirmed_round=1  # forward-only OCR guard
        self._round_clock = RoundClock()  # S134: observed round starts
        # OCR subsystem - runs in background, provides free stage/round/level/gold/hp
        self._ocr = None
        self._ocr_cache: dict = {}
        self._ocr_lock = threading.Lock()
        self._ocr_thread = None
        self._ocr_running = False
        try:
            from tft.tft_ocr_reader import TftOcrReader
            self._ocr = TftOcrReader()
            if self._ocr.available:
                self._ocr_running = True
                self._ocr_thread = threading.Thread(
                    target=self._ocr_loop, daemon=True, name="TftOcr")
                self._ocr_thread.start()
                logger.info("OCR subsystem started (free round/HP/level/gold reads)")
            else:
                logger.warning("OCR subsystem unavailable - using time table for round")
        except Exception as e:  # noqa: BLE001
            logger.warning("OCR init failed: %s - falling back to time table", e)

    def _ocr_loop(self):
        """Background OCR thread - reads every 2s, caches results."""
        while self._ocr_running:
            try:
                data = self._ocr.read()
                if data:
                    with self._ocr_lock:
                        self._ocr_cache.update(data)
            except Exception as e:  # noqa: BLE001
                logger.debug("OCR loop error: %s", e)
            time.sleep(2.0)

    def _ocr_data(self) -> dict:
        """Thread-safe snapshot of latest OCR data."""
        with self._ocr_lock:
            return dict(self._ocr_cache)

    def shutdown(self) -> None:
        self._ocr_running = False

    # ------------------------------------------------------------------
    # arch: phase 1 step 3 - snapshot factory helper (only path that may produce TftSnapshot)
    # ------------------------------------------------------------------

    @staticmethod
    def to_tft_snapshot(state_dict: dict) -> "Optional[TftSnapshot]":
        """
        Convert a _parse() dict to a TftSnapshot.
        Called by app.py after the TFT state reader returns a valid state.
        Returns None if state_dict is None.
        """
        if state_dict is None:
            return None
        try:
            from core.game_snapshot import TftSnapshot
            return TftSnapshot.from_state_dict(state_dict)
        except Exception:  # noqa: BLE001
            return None
    def read(self) -> Optional[dict]:
        try: raw=self._fetch()
        except Exception as e: logger.debug("TFT API: %s",e); return None  # noqa: BLE001
        if not raw or not isinstance(raw,dict): return None
        gd=raw.get("gameData",{})
        if "TFT" not in gd.get("gameMode",""): return None
        # RM-840: a set id in the live game data (if :2999 carries one -
        # UNMEASURED, live-game-gated) overrides the newest-set default in
        # tft/tft_set.py. Fail-soft: never blocks the read.
        try:
            from tft import tft_set
            tft_set.note_live_set_from_game_data(gd)
        except Exception: pass  # noqa: BLE001
        return self._parse(raw,gd=gd)
    @staticmethod
    def detect_variant(gd: dict) -> str:
        terrain=(gd.get("mapTerrain") or "").lower();mode=(gd.get("gameMode") or "").lower()
        map_name=(gd.get("mapName") or "").lower();map_num=gd.get("mapNumber",0)
        if not TftStateReader._variant_logged:
            logger.info("TFT variant: terrain=%s mode=%s map=%s num=%s",terrain,mode,map_name,map_num)
            TftStateReader._variant_logged=True
        # S134: map 22 is the STANDARD TFT map (both QA games: queue 1090
        # NORMAL_TFT on map 22), so it says nothing about Double Up; the old
        # "mapNumber 22 = Double Up" rule put every normal game in Double Up
        # mode. Double Up is its own queue (DOUBLE_UP_QUEUES).
        qid = gd.get("queueId")
        if isinstance(qid, str) and qid.strip().isdigit(): qid = int(qid.strip())
        if isinstance(qid, int) and not isinstance(qid, bool) and qid in DOUBLE_UP_QUEUES: return "double_up"
        if "turbo" in terrain or "turbo" in mode: return "hyper_roll"
        if "double" in terrain or "duo" in terrain or "pairs" in mode or "double" in map_name or "doubleup" in mode: return "double_up"
        if "hyperroll" in terrain or "hyperroll" in mode: return "hyper_roll"
        return "standard"
    def _fetch(self):
        try:
            req=urllib.request.Request(TFT_API)
            with urllib.request.urlopen(req,context=self._ssl,timeout=3) as r: return json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            # S134 P0: the standalone Unreal TFT client has no :2999 listener;
            # fall back to the synthesized standalone source (process + LCU
            # phase + per-round stats file). None there re-raises the :2999
            # error so read() keeps its "no game" contract.
            raw = _standalone_raw()
            if raw is not None:
                return raw
            raise
    def _parse(self,raw,gd=None):
        ap=raw.get("activePlayer",{});gd=raw.get("gameData",{});all_p=raw.get("allPlayers",[])
        gt=float(gd.get("gameTime",0));lv=int(ap.get("level",self._last_level));gold=0
        mn=ap.get("summonerName") or ap.get("riotIdGameName") or self._my_name or ""
        if mn: self._my_name=mn
        try:  # LT-01: the round table and schedule follow the resolved set
            from tft import tft_set
            set_n = tft_set.resolve_set()
        except Exception: set_n = None  # noqa: BLE001
        # S134: an observed round start (standalone per-round file) places the
        # round; the set's time table is the fallback. OCR still overrides.
        sched = round_schedule(set_n); tbl = _time_table(set_n)
        clock = getattr(self, "_round_clock", None)
        if clock is None: clock = self._round_clock = RoundClock()
        obs = _observed_round_start(raw); skip = _no_planning_rounds(sched)
        # The per-round cadence was measured on Set 18 only; the Set 17 table
        # lacks rows (1-4, x-7) and names no plain carousel, so counting
        # starts against it would drift: other sets keep the table.
        if obs is not None and tbl is _TIME_TO_ROUND_SET18:
            clock.note_start(obs[0], obs[1], tbl, skip, hp=obs[2], pve=sched.pve)
        self._last_level=lv; stage,rnd=clock.round_at(gt, tbl, skip); _log_round_calibration(gt, stage, rnd)
        est_stage = stage
        me={};others=[]
        for p in (all_p if isinstance(all_p,list) else []):
            if not isinstance(p,dict): continue
            pn=p.get("summonerName") or p.get("riotIdGameName") or ""
            if pn==mn or pn==self._my_name: me=p
            else: others.append(p)
        items=[]
        for it in (me.get("items",[]) or []):
            if isinstance(it,dict):
                n=it.get("displayName") or it.get("name") or ""
                if n: items.append(n)
            elif isinstance(it,str) and it: items.append(it)
        sc=me.get("scores",{}) or {};k=sc.get("kills",0);d=sc.get("deaths",0)
        alive=sum(1 for p in others if not p.get("isDead",False))
        dead=sum(1 for p in others if p.get("isDead",False))
        sr=f"{stage}-{rnd}"  # round labels: round_schedule() below (RM-855)
        variant=TftStateReader.detect_variant(gd or {})
        # -- OCR override: cross-validated against time-table ----------------
        ocr = self._ocr_data()
        if ocr.get("stage_round"):
            try:
                sp = ocr["stage_round"].split("-")
                os, ornd = int(sp[0]), int(sp[1])
                # Sanity bounds, not a set schedule: stage 1-7, round <= 4 in stage 1, <= 7 after
                max_rnd = 4 if os == 1 else 7
                if 1 <= os <= 7 and 1 <= ornd <= max_rnd:
                    # Cross-validate: OCR stage must be within 2 of the
                    # round clock's estimate (observed start, else table)
                    tbl_stage = est_stage
                    stage_delta = abs(os - tbl_stage)
                    # Forward-only: OCR must not go backward more than 1 stage
                    ocr_idx  = os * 10 + ornd
                    prev_idx = self._confirmed_stage * 10 + self._confirmed_round
                    going_backward = (ocr_idx < prev_idx - 10) and gt > 60
                    if (gt < 30 or stage_delta <= 2) and not going_backward:
                        # Accept OCR reading
                        stage, rnd, sr = os, ornd, ocr["stage_round"]
                        # Update confirmed tracker
                        if ocr_idx >= prev_idx:
                            self._confirmed_stage = os
                            self._confirmed_round = ornd
                        logger.debug("OCR round=%s (table=%s delta=%d)", sr,
                                     f"{tbl_stage}-*", stage_delta)
                    else:
                        reason = "backward" if going_backward else f"delta={stage_delta}>2"
                        logger.debug("OCR round=%s rejected: %s (confirmed=%d-%d)",
                                     ocr["stage_round"], reason,
                                     self._confirmed_stage, self._confirmed_round)
            except Exception: pass  # noqa: BLE001
        if ocr.get("level") and 1 <= ocr["level"] <= 10:
            lv = ocr["level"]
        if ocr.get("gold") is not None and 0 <= ocr["gold"] <= 999:
            gold = ocr["gold"]
        # OCR HP stored in cache but merged at coach layer (vision HP preferred over OCR)
        # Store raw OCR hp in state for fallback
        ocr_hp = ocr.get("hp")
        # -----------------------------------------------------------------
        rf = sched.fields(stage, rnd)  # RM-855: the resolved set's schedule
        out = {"game_mode":gd.get("gameMode","TFT"),"game_time_s":gt,"level":lv,"gold":gold,
            "health":0 if me.get("isDead") else (
                int(float(me.get("health") or me.get("tftHP") or 0))
                if (me.get("health") or me.get("tftHP")) and 0 < float(me.get("health") or me.get("tftHP") or 0) <= 100
                else ocr_hp  # fallback to OCR hp if API has none
            ),"is_dead":me.get("isDead",False),
            "interest":0,"streak":k-d,"kills":k,"deaths":d,
            "stage":stage,"round":rnd,"stage_round":sr,
            "round_event":rf["round_event"],"is_pve":rf["is_pve"],"is_carousel":rf["is_carousel"],
            "is_god_round":rf["is_god_round"],"tempo_note":rf["tempo_note"],
            "round_schedule":rf["round_schedule"],"items":items,"items_str":", ".join(items) or "none",
            "alive_others":alive,"dead_others":dead,"total_players":1+len(others),
            "board":[],"bench":[],"shop":[],"traits":{},"augments":[],
            "board_size":0,"bench_count":0,"board_str":"unavailable","bench_str":"unavailable",
            "shop_str":"unavailable","traits_str":"unavailable","augments_str":"unavailable",
            "xp_current":0,"xp_needed":0,"xp_remaining":0,"variant":variant,
            "data_source":"live_client"}
        _apply_standalone(out, raw)  # S134 P0: standalone-client board/standing
        return out


# -- standalone Unreal TFT client (S134 P0) -------------------------------------
def _standalone_raw():
    """The synthesized standalone-client allgamedata dict, or None. Fail-soft."""
    try:
        from tft import tft_standalone
        return tft_standalone.synth_allgamedata()
    except Exception as e:  # noqa: BLE001
        logger.debug("standalone TFT source: %s", e)
        return None


def _observed_round_start(raw):
    """(game id, round start s, every player's health) from the standalone
    per-round file carried in a synthesized raw dict, or None (a :2999 read,
    no fresh file). Fail-soft."""
    if not isinstance(raw, dict):
        return None
    try:
        from tft import tft_standalone
        if raw.get("rc_source") != tft_standalone.SOURCE_TAG:
            return None
    except Exception:  # noqa: BLE001
        return None
    st = raw.get("rc_standalone")
    if not isinstance(st, dict) or not st.get("eog"):
        return None
    t = st.get("game_length_s")
    if isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0:
        return None
    players = raw.get("allPlayers") if isinstance(raw.get("allPlayers"), list) else []
    hp = tuple(p.get("health") for p in players if isinstance(p, dict))
    return str(st.get("game_id") or ""), float(t), hp


def _apply_standalone(out: dict, raw) -> None:
    """Overlay the per-round board / standing from the standalone source.

    Only for a raw dict the standalone module produced; a :2999 read is left
    byte-identical except for its ``data_source`` provenance tag. HP already
    arrives through allPlayers (the local player's ``health``).
    """
    if not isinstance(raw, dict):
        return
    try:
        from tft import tft_standalone
        if raw.get("rc_source") != tft_standalone.SOURCE_TAG:
            return
        out["data_source"] = tft_standalone.SOURCE_TAG
        st = raw.get("rc_standalone") if isinstance(raw.get("rc_standalone"), dict) else {}
        local = st.get("local") if isinstance(st.get("local"), dict) else {}
        board = [u for u in (local.get("board") or []) if isinstance(u, dict)]
        if board:
            out["board"] = board
            out["board_size"] = len(board)
            out["board_str"] = ", ".join(
                f"{u.get('name')}*{u.get('star', 1)}" for u in board)
        if local.get("standing"):
            out["standing"] = local.get("standing")
    except Exception as e:  # noqa: BLE001
        logger.debug("standalone TFT overlay: %s", e)


# -- round schedule per resolved set (RM-855) ----------------------------------
# Before RM-855 _parse read the Set 17 Realm of the Gods tables in
# tft/tft_pbe_data.py for every game, so once RM-840 made Set 18 the default a
# Set 18 game carried Set 17 god rounds, PvE rounds and tempo notes (a tempo
# note reaches the coach prompt as "Milestone: ...").
#
# Three schedules, chosen through tft/tft_set.py resolve_set:
#   set17_realm_of_gods  the tft_pbe_data tables, only when the resolved set
#                        is the set those tables declare (CONSTANTS_SET) AND
#                        its own meta records Realm of the Gods
#                        (tft/tft_prompt.py set_has_gods, the gate the coaches
#                        use for the god-round prompt and parse).
#   set18_measured       Set 18 (LT-01, session 134), read off the HUD round
#                        strip of a live Set 18 game (QA_REPORT.md section 2,
#                        ops/runtime/tft_qa/20261025-070350): carousel x-4,
#                        PvE x-7 (stages 2-6 seen in the strip), augment 2-1 /
#                        3-2 / 4-2 and none in stages 5-6. CommunityDragon
#                        StageRoundData agrees and adds what the game did not
#                        show: stage 1 = carousel + 3 minion PvE rounds, stage
#                        7 = stage 6's shape. No god round, no tempo note.
#   neutral_unverified   every other set: an unknown or un-ingested set, a set
#                        whose files cannot be read. No event, PvE, god or
#                        tempo label; round_event is the schema default "pvp"
#                        (core/game_snapshot.py TftSnapshot), which means "no
#                        event known", not a claim that the round is PvP.
# Another set's schedule or timings are never borrowed for a set.
SCHEDULE_GODS = "set17_realm_of_gods"
SCHEDULE_SET18 = "set18_measured"
SCHEDULE_NEUTRAL = "neutral_unverified"

# round_event "pve" (not a monster name) because the HUD shows only "PvE"; the
# game data names them (2-7 krugs, 3-7 wolves, 4-7 raptors, 5-7 drake, 6-7 /
# 7-7 herald; 1-2..1-4 minions).
_SET18_EVENTS = {
    (1, 1): "carousel", (1, 2): "pve", (1, 3): "pve", (1, 4): "pve",
    (2, 1): "augment", (3, 2): "augment", (4, 2): "augment",
    **{(s, 4): "carousel" for s in range(2, 8)},
    **{(s, 7): "pve" for s in range(2, 8)},
}
_SET18_PVE = frozenset(rk for rk, ev in _SET18_EVENTS.items() if ev == "pve")


class RoundSchedule(NamedTuple):
    set_number: Optional[int]
    label: str
    events: dict        # (stage, round) -> event name
    pve: frozenset      # {(stage, round)}
    gods: frozenset     # {(stage, round)}
    tempo: dict         # "stage-round" -> note

    def fields(self, stage: int, rnd: int) -> dict:
        rk = (stage, rnd)
        event = self.events.get(rk, "pvp")
        return {"round_event": event,
                "is_pve": rk in self.pve,
                "is_god_round": rk in self.gods,
                # a plain carousel only (Set 17's "opening_carousel" and god
                # rounds keep the pre-LT-01 False)
                "is_carousel": event == "carousel",
                "tempo_note": self.tempo.get(f"{stage}-{rnd}", ""),
                "round_schedule": self.label}


_last_schedule: Optional[tuple] = None  # (set, label) last logged


def round_schedule(set_number=None, *, root=None) -> RoundSchedule:
    """The round schedule for the resolved set (live set > RC_TFT_SET > newest).

    Never raises: a resolver or data failure yields the neutral schedule.
    """
    global _last_schedule
    n = None
    sched = None
    try:
        from tft import tft_set
        n = set_number if set_number is not None else tft_set.resolve_set(root=root)
        from tft import tft_pbe_data as d
        from tft import tft_prompt
        if n == d.CONSTANTS_SET and tft_prompt.set_has_gods(n, root=root):
            sched = RoundSchedule(n, SCHEDULE_GODS, dict(d.ROUND_EVENTS),
                                  frozenset(d.PVE_ROUNDS), frozenset(d.GOD_ROUNDS),
                                  dict(d.TEMPO_MILESTONES))
        elif n == 18:
            sched = RoundSchedule(n, SCHEDULE_SET18, dict(_SET18_EVENTS),
                                  _SET18_PVE, frozenset(), {})
    except Exception as e:  # noqa: BLE001
        logger.debug("TFT round schedule: set data unreadable, neutral: %s", e)
    if sched is None:
        sched = RoundSchedule(n, SCHEDULE_NEUTRAL, {}, frozenset(), frozenset(), {})
    if (sched.set_number, sched.label) != _last_schedule:
        _last_schedule = (sched.set_number, sched.label)
        logger.info("TFT round schedule: set %s -> %s", sched.set_number, sched.label)
    return sched
