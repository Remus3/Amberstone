"""
tft/tft_state_reader.py - Riot Live Client API reader for TFT.
Variant detection via mapNumber (22=Double Up). Stage/round from OCR (free)
with time-table fallback.
"""
import json
import ssl
import logging
import urllib.request
import threading
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.game_snapshot import TftSnapshot

logger = logging.getLogger("rc.tft.reader")
TFT_API = "https://192.168.8.237:2999/liveclientdata/allgamedata"
_TIME_TO_ROUND = [
    # Set 17 Space Gods Double Up - calibrated from 3 confirmed live data points:
    # t=32s→1-2, t=348s→2-5, t≈1002s→4-6, t=1879s→7-4
    # Fit: ~51 seconds per round on average
    (0,   1, 1), (32,  1, 2), (82,  1, 3),
    (144, 2, 1), (195, 2, 2), (246, 2, 3), (297, 2, 4), (348, 2, 5), (399, 2, 6),
    (450, 3, 1), (501, 3, 2), (552, 3, 3), (603, 3, 4), (654, 3, 5), (705, 3, 6),
    (756, 4, 1), (807, 4, 2), (858, 4, 3), (909, 4, 4), (960, 4, 5), (1011, 4, 6), (1062, 4, 7),
    (1113, 5, 1), (1164, 5, 2), (1215, 5, 3), (1266, 5, 4), (1317, 5, 5), (1368, 5, 6),
    (1419, 6, 1), (1470, 6, 2), (1521, 6, 3), (1572, 6, 4), (1623, 6, 5), (1674, 6, 6),
    (1725, 7, 1), (1776, 7, 2), (1827, 7, 3), (1878, 7, 4),
]
def _estimate_round(t):
    s, r = 1, 1
    for ms, st, rn in _TIME_TO_ROUND:
        if t >= ms: s, r = st, rn
        else: break
    return s, r

_last_logged_sr = None  # for calibration logging
def _log_round_calibration(t, stage, rnd):
    global _last_logged_sr
    sr = f"{stage}-{rnd}"
    if sr != _last_logged_sr:
        logger.debug("Round calibration: t=%.1fs → %s", t, sr)
        _last_logged_sr = sr

class TftStateReader:
    _variant_logged = False  # reset each game in __init__
    def __init__(self) -> None:
        self._ssl=ssl.create_default_context();self._ssl.check_hostname=False;self._ssl.verify_mode=ssl.CERT_NONE
        self._my_name="";self._last_level=1;self._last_gold=0
        self._confirmed_stage=1;self._confirmed_round=1  # forward-only OCR guard
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
        except Exception as e:
            logger.warning("OCR init failed: %s - falling back to time table", e)

    def _ocr_loop(self):
        """Background OCR thread - reads every 2s, caches results."""
        while self._ocr_running:
            try:
                data = self._ocr.read()
                if data:
                    with self._ocr_lock:
                        self._ocr_cache.update(data)
            except Exception as e:
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
        except Exception:
            return None
    def read(self) -> Optional[dict]:
        try: raw=self._fetch()
        except Exception as e: logger.debug("TFT API: %s",e); return None
        if not raw or not isinstance(raw,dict): return None
        gd=raw.get("gameData",{})
        if "TFT" not in gd.get("gameMode",""): return None
        return self._parse(raw,gd=gd)
    @staticmethod
    def detect_variant(gd: dict) -> str:
        terrain=(gd.get("mapTerrain") or "").lower();mode=(gd.get("gameMode") or "").lower()
        map_name=(gd.get("mapName") or "").lower();map_num=gd.get("mapNumber",0)
        if not TftStateReader._variant_logged:
            logger.info("TFT variant: terrain=%s mode=%s map=%s num=%s",terrain,mode,map_name,map_num)
            TftStateReader._variant_logged=True
        # mapNumber 22 = Double Up (PBE and live)
        if map_num == 22 or "map22" in map_name:
            return "double_up"
        if "turbo" in terrain or "turbo" in mode: return "hyper_roll"
        if "double" in terrain or "duo" in terrain or "pairs" in mode or "double" in map_name or "doubleup" in mode: return "double_up"
        if "hyperroll" in terrain or "hyperroll" in mode: return "hyper_roll"
        return "standard"
    def _fetch(self):
        req=urllib.request.Request(TFT_API)
        with urllib.request.urlopen(req,context=self._ssl,timeout=3) as r: return json.loads(r.read().decode("utf-8"))
    def _parse(self,raw,gd=None):
        ap=raw.get("activePlayer",{});gd=raw.get("gameData",{});all_p=raw.get("allPlayers",[])
        gt=float(gd.get("gameTime",0));lv=int(ap.get("level",self._last_level));gold=0
        mn=ap.get("summonerName") or ap.get("riotIdGameName") or self._my_name or ""
        if mn: self._my_name=mn
        self._last_level=lv; stage,rnd=_estimate_round(gt); _log_round_calibration(gt, stage, rnd)
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
        from tft.tft_pbe_data import ROUND_EVENTS, PVE_ROUNDS, GOD_ROUNDS, TEMPO_MILESTONES
        rk=(stage,rnd);re_=ROUND_EVENTS.get(rk,"pvp");sr=f"{stage}-{rnd}"
        is_god = rk in GOD_ROUNDS
        variant=TftStateReader.detect_variant(gd or {})
        # ── OCR override: cross-validated against time-table ────────────────
        ocr = self._ocr_data()
        if ocr.get("stage_round"):
            try:
                sp = ocr["stage_round"].split("-")
                os, ornd = int(sp[0]), int(sp[1])
                # Hard bounds: Set 17 max stage 7, max round 7
                max_rnd = 4 if os == 1 else 7
                if 1 <= os <= 7 and 1 <= ornd <= max_rnd:
                    # Cross-validate: OCR stage must be within 2 of time-table
                    tbl_stage, tbl_rnd = _estimate_round(gt)
                    stage_delta = abs(os - tbl_stage)
                    # Forward-only: OCR must not go backward more than 1 stage
                    ocr_idx  = os * 10 + ornd
                    prev_idx = self._confirmed_stage * 10 + self._confirmed_round
                    going_backward = (ocr_idx < prev_idx - 10) and gt > 60
                    if (gt < 30 or stage_delta <= 2) and not going_backward:
                        # Accept OCR reading
                        stage, rnd, sr = os, ornd, ocr["stage_round"]
                        rk = (stage, rnd)
                        re_ = ROUND_EVENTS.get(rk, "pvp")
                        is_god = rk in GOD_ROUNDS
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
            except Exception: pass
        if ocr.get("level") and 1 <= ocr["level"] <= 10:
            lv = ocr["level"]
        if ocr.get("gold") is not None and 0 <= ocr["gold"] <= 999:
            gold = ocr["gold"]
        # OCR HP stored in cache but merged at coach layer (vision HP preferred over OCR)
        # Store raw OCR hp in state for fallback
        ocr_hp = ocr.get("hp")
        # ─────────────────────────────────────────────────────────────────
        return {"game_mode":gd.get("gameMode","TFT"),"game_time_s":gt,"level":lv,"gold":gold,
            "health":0 if me.get("isDead") else (
                int(float(me.get("health") or me.get("tftHP") or 0))
                if (me.get("health") or me.get("tftHP")) and 0 < float(me.get("health") or me.get("tftHP") or 0) <= 100
                else ocr_hp  # fallback to OCR hp if API has none
            ),"is_dead":me.get("isDead",False),
            "interest":0,"streak":k-d,"kills":k,"deaths":d,
            "stage":stage,"round":rnd,"stage_round":sr,
            "round_event":re_,"is_pve":rk in PVE_ROUNDS,"is_carousel":False,"is_god_round":is_god,
            "tempo_note":TEMPO_MILESTONES.get(sr,""),"items":items,"items_str":", ".join(items) or "none",
            "alive_others":alive,"dead_others":dead,"total_players":1+len(others),
            "board":[],"bench":[],"shop":[],"traits":{},"augments":[],
            "board_size":0,"bench_count":0,"board_str":"unavailable","bench_str":"unavailable",
            "shop_str":"unavailable","traits_str":"unavailable","augments_str":"unavailable",
            "xp_current":0,"xp_needed":0,"xp_remaining":0,"variant":variant}
