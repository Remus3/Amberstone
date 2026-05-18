# arch: game start/end transitions, worker management | section=orchestration | frozen=yes
"""
app/_game_lifecycle.py - GameLifecycleManager extracted from app/__init__.py (ARCH-001 Phase 4)

Owns the entire game start/end transition, worker management, state processing,
and auto-field derivation.  The most complex manager - all game logic lives here.

OverlayApp delegates:
  _on_game_start()       → self.lifecycle.on_game_start(canon_mode)
  _on_game_end()         → self.lifecycle.on_game_end()
  _start_game_poll()     → self.lifecycle.start_game_poll()
  _game_poll_worker()    → self.lifecycle.game_poll_worker(gen)
  _drain_game_q()        → self.lifecycle.drain_game_q()
  _drain_tft_q()         → self.lifecycle.drain_tft_q()
  _try_read_api_key()    → self.lifecycle.try_read_api_key()
  _process_worker_result() → self.lifecycle.process_worker_result(result)
  _process_game_state()  → self.lifecycle.process_game_state(state, ...)
  _apply_auto_fields()   → self.lifecycle.apply_auto_fields(state)
"""
import json
import logging
import os
import sys
import traceback
from pathlib import Path

from core.game_snapshot import (
    GameEnvelope, ClientSnapshot, RiftSnapshot, AramSnapshot, TftSnapshot,
    MODE_CLIENT, MODE_SR, MODE_ARAM, MODE_TFT, MODE_ARENA, MODE_BRAWL,
    mode_from_game_mode_string,
)
from core.theme import EXCLUDED_MODES

SCRIPT_DIR   = Path(__file__).parent.parent
POLL_GAME_MS = 1500

try:
    from core.sr_aram_worker import SrAramWorker, WorkerResult; HAS_WORKER = True
except ImportError: HAS_WORKER = False
try:
    from core.tft_worker import TftWorker, TftWorkerResult; HAS_TFT_WORKER = True
except ImportError: HAS_TFT_WORKER = False
try:
    from item_advisor import get_purchase_advice; HAS_ADVISOR = True
except ImportError: HAS_ADVISOR = False
try:
    from performance_tracker import save_rating, save_tft_rating; HAS_TRACKER = True
except Exception: HAS_TRACKER = False

try:
    from lcu.lcu_postgame_collector import get_collector as _get_postgame_collector
    HAS_POSTGAME = True
except ImportError: HAS_POSTGAME = False

_log = logging.getLogger("rc.app.lifecycle")


def _safe_log(label: str) -> None:
    try: _log.error("%s:\n%s", label, traceback.format_exc())
    except Exception: pass


class GameLifecycleManager:
    """
    Owns game start/end transitions, worker management, and state processing.
    All methods run on the asyncio loop thread (drained from worker queues
    via app.scheduler.schedule).
    """

    def __init__(self, app: "OverlayApp") -> None:  # type: ignore[name-defined]
        self.app = app

    # ── Game start / end ─────────────────────────────────────────────────────

    def on_game_start(self, canon_mode: str) -> None:
        app = self.app
        _log.info("New game detected")
        dbg = "--debug" in sys.argv or os.environ.get("RIOT_COMMANDER_DEBUG") == "1"
        app._update_envelope(canon_mode, payload=None)

        _non_tft = canon_mode in (MODE_SR, MODE_ARAM, MODE_ARENA, MODE_BRAWL)
        if _non_tft and app._sr_aram_worker is not None:
            app._sr_aram_worker.reset_reader_state(reason="game_start")

        cmap = {
            "_tft_mode":   ("coaches.tft_coach",   "Coach", "tft_coaching_data.json"),
            "_arena_mode": ("coaches.arena_coach",  "Coach", "arena_coaching_data.json"),
            "_brawl_mode": ("coaches.brawl_coach",  "Coach", "brawl_coaching_data.json"),
            "_aram_mode":  ("coaches.aram_coach",   "Coach", "aram_coaching_data.json"),
        }
        _policy_map = {
            "_tft_mode":   ("tft",   "live_coaching"),
            "_arena_mode": ("arena", "live_coaching"),
            "_brawl_mode": ("brawl", "live_coaching"),
            "_aram_mode":  ("aram",  "live_coaching"),
        }
        for flag, (mp, cn, dn) in cmap.items():
            if getattr(app, flag, False):
                _log.info("%s game detected", flag.replace("_mode", "").upper())
                _coaching_allowed = True
                try:
                    from core.feature_policy import (
                        is_allowed as _fp_allowed,
                        write_disabled_placeholder as _fp_write,
                    )
                    _pm, _pf = _policy_map.get(flag, (None, None))
                    if _pm is not None and not _fp_allowed(_pm, _pf):
                        _coaching_allowed = False
                        _fp_write(_pm)
                except Exception:
                    pass
                try:
                    import importlib
                    mod = importlib.import_module(mp)
                    if HAS_TFT_WORKER and flag == "_tft_mode":
                        _api = self._try_read_api_key()
                        while not app._tft_q.empty():
                            try: app._tft_q.get_nowait()
                            except Exception: pass
                        app._tft_worker = TftWorker(
                            result_queue=app._tft_q,
                            data_dir=SCRIPT_DIR / "data",
                            api_key=_api,
                            debug=dbg,
                        )
                        app._tft_coach = getattr(mod, cn)(SCRIPT_DIR / "data" / dn, debug=dbg)
                        app._tft_coach.set_worker(app._tft_worker)
                        app._tft_worker.start()
                        if app._tft_worker is not None:
                            app.scheduler.schedule(1500, self._drain_tft_q)
                    elif _coaching_allowed:
                        app._tft_coach = getattr(mod, cn)(SCRIPT_DIR / "data" / dn, debug=dbg)
                except Exception:
                    _safe_log(f"{flag} coach start failed")
                return
        for f in ("action","immediate","next","fight_rule","wave",
                  "objective","reset_item","risk","map"):
            app.data[f] = ""
        app.data["win_pct"] = None
        app.data["log"]     = []
        app._write_data()
        if app._coach:
            try: app._coach.reset_state()
            except Exception: pass

    def on_game_end(self) -> None:
        app = self.app
        _log.info("Game ended")
        # POSTGAME: Trigger end-of-game data collection (isolated, never used for coaching)
        if HAS_POSTGAME:
            try:
                _pgc = _get_postgame_collector()
                if _pgc is not None:
                    _gm = (app._game_state.get("game_mode", "CLASSIC")
                           if app._game_state else "CLASSIC")
                    _pgc.trigger(_gm)
            except Exception as _pgc_exc:
                _log.debug("postgame trigger error: %s", _pgc_exc)
        _sp = app._tft_mode or app._arena_mode or app._brawl_mode or app._aram_mode
        if _sp:
            if HAS_TRACKER:
                try:
                    if app._tft_mode:
                        lp = SCRIPT_DIR / "data" / "tft_live_data.json"
                        cp = SCRIPT_DIR / "data" / "tft_coaching_data.json"
                        tl = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else {}
                        tc = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
                        g, n = save_tft_rating(SCRIPT_DIR, tl, tc)
                        if g: _log.info("TFT rating saved: %s", g)
                    elif app._game_state:
                        enriched = dict(app._game_state)
                        mn  = "ARAM" if app._aram_mode else "Arena" if app._arena_mode else "Brawl"
                        cfm = {
                            "ARAM":  "aram_coaching_data.json",
                            "Arena": "arena_coaching_data.json",
                            "Brawl": "brawl_coaching_data.json",
                        }
                        cf = SCRIPT_DIR / "data" / cfm.get(mn, "")
                        if cf.exists():
                            try:
                                cd = json.loads(cf.read_text(encoding="utf-8"))
                                enriched["coach_action"]   = cd.get("action", "")
                                enriched["coach_analysis"] = (
                                    cd.get("comp_analysis", "") or cd.get("round_strategy", "")
                                )
                                if app._arena_mode:
                                    enriched["arena_rounds_won"] = cd.get("wins", 0)
                                    enriched["arena_rank"]       = cd.get("rank", "?")
                            except Exception:
                                pass
                        g, n = save_rating(
                            SCRIPT_DIR,
                            enriched.get("champion", ""),
                            enriched,
                            enriched.get("ally_kills_total", 1),
                        )
                        if g: _log.info("%s rating saved: %s", mn, g)
                except Exception:
                    _safe_log("Special mode rating save error")
            if app._tft_coach:
                try: app._tft_coach.shutdown()
                except Exception: _safe_log("Special coach shutdown error")
                app._tft_coach = None
            if app._tft_worker is not None:
                try: app._tft_worker.shutdown()
                except Exception: _safe_log("TftWorker shutdown error")
                app._tft_worker = None
            while not app._tft_q.empty():
                try: app._tft_q.get_nowait()
                except Exception: pass
            if not app._tft_mode and app._sr_aram_worker is not None:
                app._sr_aram_worker.reset_reader_state(reason="game_end")
            try: app._update_envelope(MODE_CLIENT, ClientSnapshot())
            except Exception: pass
            return
        if HAS_TRACKER and app._game_state:
            gm = app._game_state.get("game_mode", "CLASSIC")
            if gm not in EXCLUDED_MODES:
                try:
                    save_rating(
                        SCRIPT_DIR,
                        app._game_state.get("champion", ""),
                        app._game_state,
                        app._game_state.get("ally_kills_total", 1),
                    )
                    _log.info("Performance rating saved")
                except Exception:
                    _safe_log("save_rating error")
        for f in ("action","immediate","next","fight_rule","wave",
                  "objective","reset_item","risk","map"):
            app.data[f] = ""
        app.data["win_pct"] = None
        app.data["log"]     = []
        app._write_data()
        if app._coach:
            try: app._coach.reset_state()
            except Exception: pass
        if app._sr_aram_worker is not None:
            app._sr_aram_worker.reset_reader_state(reason="game_end")
        try: app._update_envelope(MODE_CLIENT, ClientSnapshot())
        except Exception: pass

    # ── Worker start / drain ─────────────────────────────────────────────────

    def start_game_poll(self) -> None:
        app = self.app
        if app._sr_aram_worker is not None:
            app._sr_aram_worker.start()
            app.scheduler.schedule(POLL_GAME_MS, self._drain_game_q)
        else:
            _log.warning("SrAramWorker unavailable; game polling disabled")

    def game_poll_worker(self, my_gen: int) -> None:
        """Legacy stub - kept for restart_game_poll fallback path only."""
        _log.warning("Legacy _game_poll_worker called (gen=%d)", my_gen)

    def _drain_game_q(self) -> None:
        """Loop thread: drain SrAramWorker result queue and apply updates."""
        app = self.app
        try:
            while not app._sr_aram_q.empty():
                result = app._sr_aram_q.get_nowait()
                if isinstance(result, WorkerResult):
                    self._process_worker_result(result)
                else:
                    self._process_game_state(result)
        except Exception:
            pass
        app.scheduler.schedule(POLL_GAME_MS, self._drain_game_q)

    def _drain_tft_q(self) -> None:
        """Loop thread: drain TftWorker results → TftSnapshot → envelope."""
        app = self.app
        try:
            if not app._tft_mode:
                while not app._tft_q.empty():
                    try: app._tft_q.get_nowait()
                    except Exception: pass
                return
            while not app._tft_q.empty():
                result = app._tft_q.get_nowait()
                if not isinstance(result, TftWorkerResult) or result.state is None:
                    continue
                if not app._tft_mode:
                    break
                try:
                    from tft.tft_state_reader import TftStateReader as _TSR
                    payload = _TSR.to_tft_snapshot(result.state)
                except Exception:
                    payload = None
                if payload is None:
                    try: payload = TftSnapshot.from_state_dict(result.state)
                    except Exception: payload = None
                if payload is not None:
                    try: app._update_envelope(MODE_TFT, payload)
                    except Exception: _safe_log("TftSnapshot envelope update error")
                    app._game_state = payload.raw_state
                if app._tft_coach is not None:
                    app._tft_coach._last_data = result.state
        except Exception:
            pass
        if app._tft_worker is not None and app._tft_worker.is_alive() and app._tft_mode:
            app.scheduler.schedule(1500, self._drain_tft_q)

    def _try_read_api_key(self) -> str:
        try:
            p = SCRIPT_DIR / "API-Key-Claude.txt"
            if p.exists():
                k = p.read_text(encoding="utf-8").strip()
                if k.startswith("sk-ant-"):
                    return k
        except Exception:
            pass
        return os.environ.get("ANTHROPIC_API_KEY", "")

    # ── State processing ─────────────────────────────────────────────────────

    def _process_worker_result(self, result) -> None:
        """Apply a WorkerResult from SrAramWorker to the authoritative GameEnvelope."""
        app = self.app
        try:
            if result.end_signal:
                # AUDIT-OPUS BUG-1 fix: clear _game_state AFTER _on_game_end
                app._none_streak  = 0
                app._was_in_game  = False
                self.on_game_end()
                app._game_state   = None
                if app._auto_mode and app.mode == "game":
                    app._switch_mode("client", auto=True)
                return
            if result.state is None:
                return
            if app._tft_mode:
                return
            self._process_game_state(result.state,
                                     is_first=result.is_first,
                                     canon_mode=result.canon_mode)
        except Exception:
            _safe_log("_process_worker_result error")

    def _process_game_state(self, state, is_first=None, canon_mode=None) -> None:
        app = self.app
        try:
            if state:
                app._none_streak = 0
                if not app._was_in_game:
                    try:
                        gm = state.get("game_mode", "CLASSIC").upper()
                        canon_mode = mode_from_game_mode_string(gm)
                        app._was_in_game = True
                        self.on_game_start(canon_mode)
                    except Exception:
                        _safe_log("_on_game_start error")
                        app._was_in_game = True
                    if app._auto_mode and app.mode != "game":
                        app._switch_mode("game", auto=True)
                if app._tft_mode:
                    return
                env_mode = app.state.envelope.mode
                if env_mode == MODE_ARAM and app.reader:
                    payload = app.reader.to_aram_snapshot(state)
                elif env_mode in (MODE_SR, MODE_ARENA, MODE_BRAWL) and app.reader:
                    payload = app.reader.to_rift_snapshot(state)
                else:
                    if env_mode == MODE_TFT:
                        try:
                            from tft.tft_state_reader import TftStateReader as _TSR
                            payload = _TSR.to_tft_snapshot(state)
                        except Exception:
                            payload = None
                        if payload is None:
                            try: payload = TftSnapshot.from_state_dict(state)
                            except Exception: payload = None
                    else:
                        payload = None
                if payload is None and env_mode in (MODE_SR, MODE_ARENA, MODE_BRAWL):
                    try:
                        payload = RiftSnapshot(); payload.raw_state = state
                    except Exception:
                        payload = RiftSnapshot.emergency_raw_state_only(state)
                    if payload is not None:
                        _log.warning("RiftSnapshot factory None; using emergency payload")
                elif payload is None and env_mode == MODE_ARAM:
                    try:
                        payload = AramSnapshot(); payload.raw_state = state
                    except Exception:
                        payload = AramSnapshot.emergency_raw_state_only(state)
                    if payload is not None:
                        _log.warning("AramSnapshot factory None; using emergency payload")
                if payload is not None:
                    try:
                        app.state.set_envelope(env_mode, payload)
                    except Exception:
                        _safe_log("GameEnvelope update error")
                    app._game_state = payload.raw_state
                else:
                    app._game_state = state
                hd = (
                    state.get("champion", "Unknown") not in ("", "Unknown")
                    or state.get("game_seconds", 0) > 5
                    or state.get("hp_max", 1) > 1
                )
                if hd:
                    self._apply_auto_fields(state)
            else:
                app._none_streak += 1
                if app._was_in_game and app._none_streak >= 5:
                    # AUDIT-OPUS BUG-1 fix: clear _game_state AFTER _on_game_end
                    app._none_streak = 0
                    app._was_in_game = False
                    self.on_game_end()
                    app._game_state  = None
                    if app._auto_mode and app.mode == "game":
                        app._switch_mode("client", auto=True)
        except Exception:
            _safe_log("_process_game_state error")

    def _apply_auto_fields(self, state: dict) -> None:
        """Derive and write auto-calculated overlay fields from current game state."""
        from app._state_authority import StateAuthority
        app = self.app
        if app._tft_mode:
            return
        changed = False
        app.data["ally_comp"]  = state.get("ally_comp", [])
        app.data["enemy_comp"] = state.get("enemy_comp", [])
        de = state.get("dead_enemies", []); dc = len(de); kw = dc >= 2
        ao = state.get("objectives", ""); co = app.data.get("objective", "")
        sw = ("contest","trade","rotate","push","setup","take","give","group","split","fight")
        hc = bool(co) and any(w in co.lower() for w in sw)
        if kw or not hc or not co:
            no = f"ACT \u2014 {dc} enemies dead  |  {ao}" if kw else ao
            if app.data.get("objective") != no:
                app.data["objective"] = no; changed = True
        ar = state.get("risk_derived", "")
        if ar and app.data.get("risk") != ar:
            app.data["risk"] = ar; changed = True
        am = state.get("map_derived", "")
        if am and app.data.get("map") != am:
            app.data["map"] = am; changed = True
        aw = state.get("wave_state_str", "")
        if not aw and app._coach and not app._aram_mode:  # ARAM CS != wave state
            try:
                wr = app._coach._wave.update(
                    state.get("cs", 0), state.get("game_seconds", 0)
                )
                aw = wr.replace("_", " ").replace("or", "/") if wr else ""
            except Exception:
                pass
        if aw and app.data.get("wave") != aw:
            app.data["wave"] = aw; changed = True
        try:
            app.data["win_pct"] = StateAuthority.calc_win_pct(state); changed = True
        except Exception:
            pass
        ares = ""
        if HAS_ADVISOR:
            try:
                adv = get_purchase_advice(
                    champion=state.get("champion", ""),
                    current_items=state.get("items", []),
                    gold=state.get("gold", 0),
                    enemy_champs=state.get("enemy_comp", []),
                )
                ares = adv.get("display", "")
                ni   = adv.get("next_item", "")
                nc   = adv.get("next_cost", 0)
                hg   = state.get("gold", 0)
                nm   = max(0, nc - hg)
                state["next_item_str"] = (
                    f"{ni} \u2014 need {nm}g more" if ni and nm > 0 else
                    f"{ni} \u2014 can buy now"    if ni else ""
                )
            except Exception:
                ares = state.get("reset_derived", "")
                state["next_item_str"] = ""
        else:
            ares = state.get("reset_derived", "")
            state["next_item_str"] = ""
        if ares and app.data.get("reset_item") != ares:
            app.data["reset_item"] = ares; changed = True
        if changed:
            app._update_content()

    # ── Public delegation API (called via OverlayApp stubs) ──────────────────

    def try_read_api_key(self) -> str:
        return self._try_read_api_key()

    def drain_game_q(self) -> None:
        self._drain_game_q()

    def drain_tft_q(self) -> None:
        self._drain_tft_q()

    def process_worker_result(self, result) -> None:
        self._process_worker_result(result)

    def process_game_state(self, state, is_first=None, canon_mode=None) -> None:
        self._process_game_state(state, is_first=is_first, canon_mode=canon_mode)

    def apply_auto_fields(self, state: dict) -> None:
        self._apply_auto_fields(state)
