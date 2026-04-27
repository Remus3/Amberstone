"""
coaches/tft_coach.py
Phase 1 Step 5 — TFT coach facade (Tk/overlay only).

This module is now a thin facade that manages the TFT overlay lifecycle.
Runtime polling, coaching orchestration, and TftLiveAnalysis are owned by
core/tft_worker.TftWorker — not this class.

Responsibilities retained here:
  - Overlay construction / attachment / teardown (Tk — main thread only)
  - _poll_overlay_files() Tk timer loop (reads JSON artifacts for UI)
  - _force_refresh_all() right-click callback (delegates to worker)
  - reset_state() — clears data files and engine/live state via worker refs
  - shutdown() — overlay teardown only (app.py owns TftWorker lifecycle)

Responsibilities that moved to TftWorker:
  - TftStateReader ownership
  - TftCoachEngine ownership and coaching submission
  - TftLiveAnalysis ownership and vision loop
  - _poll_loop() background thread

Single authoritative TFT coaching path: TftWorker._run().
No parallel TFT poll loop exists in this file after Step 5.
"""

import json
import logging
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger("rc.coaches.tft")

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_active_instance = None   # module-level ref for mid-game reattach via ops.reattach_overlay


def _read_api_key(app_dir: Path) -> str:
    for p in [app_dir / "API-Key-Claude.txt"]:
        if p.exists():
            k = p.read_text(encoding="utf-8").strip()
            if k.startswith("sk-ant-"):
                return k
    return __import__("os").environ.get("ANTHROPIC_API_KEY", "")


def _coach_board_to_placement(board_text):
    """Convert coach board to grid positions. Handles both grid format and FRONT/BACK format."""
    if not board_text or board_text == "\u2014":
        return ""
    import re as _re
    if _re.search(r'[A-Z][a-z]+\s+[A-Da-d]\d', board_text):
        return board_text
    _skip = {"tank","carry","support","role","unit","unknown","left","right","center",
             "spread","wide","row","col","engage","mid","roles","or","the","and"}
    _ranged = {"ashe","jinx","caitlyn","vayne","aphelios","xayah","ezreal","sivir",
               "kogmaw","missfortune","twitch","draven","samira","smolder","jhin",
               "xerath","lux","syndra","orianna","vel'koz","seraphine","ziggs"}
    _mage = {"lissandra","anivia","swain","brand","cassiopeia","malzahar","ryze",
             "azir","viktor","heimerdinger","vex","karma","ahri","neeko","zilean"}
    parts = _re.split(r'\|', board_text)
    all_names = []
    for part in parts:
        part = _re.sub(r'^(FRONT|BACK|MID)[:\s]*', '', part.strip(), flags=_re.IGNORECASE)
        for w in _re.split(r'\s+', part):
            name = w.strip(" [](),")
            if name and len(name) >= 3 and name[0].isupper() and name.lower() not in _skip:
                all_names.append(name)
    tanks, melee, ranged_u, mages = [], [], [], []
    for name in all_names:
        nl = name.lower().split()[0]
        if nl in _ranged:  ranged_u.append(name)
        elif nl in _mage:  mages.append(name)
        else:              tanks.append(name)
    units = []
    _cols_a = [1, 3, 5, 7]; _cols_d_mage = [3, 4]; _cols_d_ranged = [6, 7]
    for i, name in enumerate(tanks):
        col = _cols_a[i] if i < len(_cols_a) else 2 + i
        units.append(f"{name} A{min(col, 7)}")
    for i, name in enumerate(mages):
        col = _cols_d_mage[i] if i < len(_cols_d_mage) else 2 + i
        units.append(f"{name} D{min(col, 7)}")
    for i, name in enumerate(ranged_u):
        col = _cols_d_ranged[i] if i < len(_cols_d_ranged) else 5 + i
        units.append(f"{name} D{min(col, 7)}")
    return ", ".join(units)


class Coach:
    """
    TFT coach facade — manages overlay Tk lifecycle only.

    The runtime poll loop, TftCoachEngine, TftLiveAnalysis, and
    TftStateReader are owned by TftWorker (core/tft_worker.py).
    app.py creates TftWorker and passes it to this facade via
    set_worker() after construction.
    """
    GAME_MODES = ("TFT",)

    def __init__(self, data_file, debug: bool = False):
        self._data_file      = Path(data_file) if not isinstance(data_file, Path) else data_file
        self._debug          = debug
        self._overlay: dict  = {}
        self._last_data: dict = {}
        self._tft_data_file  = self._data_file.parent / "tft_coaching_data.json"
        self._live_data_file = self._data_file.parent / "tft_live_data.json"
        # TftWorker reference — set by app.py via set_worker() after construction
        self._worker = None
        self._ensure_data_files()
        self.reset_state()
        logger.info("TFT Coach facade created (runtime loop in TftWorker)")

    # ── Worker wiring ─────────────────────────────────────────────────────────

    def set_worker(self, worker) -> None:
        """
        Wire the TftWorker after it is created by app.py.
        Called before attach_overlay().
        """
        self._worker = worker

    # ── Legacy API (kept for compatibility) ───────────────────────────────────

    def submit_state(self, state: dict) -> None:
        """No-op: TftWorker owns coaching submission."""
        pass

    def reset_state(self) -> None:
        """Reset TFT components and clear data files."""
        # Delegate to worker if available
        if self._worker is not None:
            if getattr(self._worker, "_engine", None) is not None:
                try:
                    self._worker._engine.reset_state()
                except Exception:
                    pass
            if getattr(self._worker, "_live", None) is not None:
                try:
                    live = self._worker._live
                    live._known_augments = []
                    live._last_write     = {}
                    live._last_round     = (0, 0)
                except Exception:
                    pass
        # Clear data files
        import json as _j
        for path, default in [
            (self._tft_data_file, {
                "mode": "tft", "action": "", "board": "", "econ": "",
                "rolldown": "", "items": "", "god_pick": "", "placement": "",
                "upgrade": "", "risk": "",
            }),
            (self._live_data_file, {
                "mode": "tft_live", "stage_round": "", "level": 0, "hp": 0,
                "board_units": [], "bench_units": [], "shop_units": [],
                "traits_active": [], "augments": [], "augment_select": False,
                "comp": "", "build": "", "buy": "", "sell": "", "keep": "",
                "augment_play": "", "loss": "", "unit_placement": "",
                "unit_swap": "",
            }),
        ]:
            try:
                path.write_text(_j.dumps(default, indent=2), encoding="utf-8")
            except Exception:
                pass
        logger.info("TFT state reset — data files cleared")

    def shutdown(self) -> None:
        """
        Tear down the overlay only.

        Phase 1 Step 5.1: app.py is the sole owner of TftWorker lifecycle.
        This method no longer calls self._worker.shutdown() — that is done
        exclusively by app.py._on_game_end() to avoid dual shutdown paths.
        """
        # Clear worker reference without shutting it down — app.py owns that
        self._worker = None
        self._teardown_overlay()
        # Clear data files so lobby shows blank, not last game's data
        self.reset_state()
        logger.info("TFT Coach facade shutdown complete (overlay only)")

    def _force_refresh_all(self) -> None:
        """Right-click: force vision scan + immediate coach engine re-run."""
        logger.info("Force refresh ALL triggered (right-click)")
        if self._worker is not None:
            try:
                self._worker.force_scan()
            except Exception:
                pass
            # Reset engine debounce so it re-runs at next poll
            if getattr(self._worker, "_engine", None) is not None:
                try:
                    self._worker._engine._last_call = 0
                    if self._last_data:
                        self._worker._engine.submit(self._last_data)
                except Exception:
                    pass

    # ── Overlay lifecycle (Tk — main thread only) ─────────────────────────────

    def attach_overlay(self, root) -> None:
        """
        Create and attach TFT overlay windows to the Tk root.
        Wires the AI status bar into the worker's TftLiveAnalysis.
        Must be called from the Tk main thread.
        """
        global _active_instance
        _active_instance = self
        try:
            from tft.tft_overlay import TftRightTop, TftRightBot, TftBottomStrip, TftAiStatusBar, TftCoachStatusBar
            from core.tk_ai_bar_proxy import TkAiBarProxy
            ai_bar = TftAiStatusBar(root)
            ai_bar.set_interval(15.0)
            coach_bar = TftCoachStatusBar(root)
            self._overlay = {
                "rtop":   TftRightTop(root),
                "rbot":   TftRightBot(root),
                "bottom": TftBottomStrip(root),
                "ai_bar": ai_bar,
                "coach_bar": coach_bar,
            }
            # Phase 1 Step 5.4: create a thread-safe proxy around the real AI bar.
            # TftLiveAnalysis (worker thread) will call set_scanning/set_done/
            # notify_scan_scheduled on the proxy, which marshals onto the Tk main
            # thread via root.after(0, ...).  No raw Tk widget is ever held by
            # the worker-owned runtime.
            ai_bar_proxy = TkAiBarProxy(root=root, bar=ai_bar)
            # Wire the proxy (not the raw widget) into the worker
            if self._worker is not None:
                self._worker.wire_ai_bar(ai_bar_proxy)

            # Bind CTRL+right-click force scan on each panel
            for key, win in self._overlay.items():
                if key == "ai_bar":
                    continue
                if hasattr(win, "bind_force_scan"):
                    win.bind_force_scan(self._force_refresh_all, ai_bar=ai_bar)

            # Wire rtop force scan callback + comp ctrl ref
            _rtop2 = self._overlay.get("rtop")
            _rbot2 = self._overlay.get("rbot")
            if _rtop2 and _rbot2 and hasattr(_rtop2, "set_comp_ctrl_ref"):
                _cc = getattr(_rbot2, "_comp_ctrl", None)
                if _cc: _rtop2.set_comp_ctrl_ref(_cc)
            # Wire rtop force scan callback for AUG button
            _rtop_ref = self._overlay.get("rtop")
            if _rtop_ref and hasattr(_rtop_ref, "set_force_scan_cb"):
                _rtop_ref.set_force_scan_cb(self._force_refresh_all)
            # Wire bottom strip AUG button
            _bot_aug = self._overlay.get("bottom")
            if _bot_aug and hasattr(_bot_aug, "set_force_scan_cb"):
                _bot_aug.set_force_scan_cb(self._force_refresh_all)

            # Wire rbot → bottom so comp selection updates center board
            _rbot = self._overlay.get("rbot")
            _bot  = self._overlay.get("bottom")
            if _rbot and _bot and hasattr(_rbot, "set_bottom_strip"):
                _rbot.set_bottom_strip(_bot)
                # Push current selected comp immediately if available
                try:
                    import json as _j; from pathlib import Path as _P
                    _cs = _j.loads((_P(__file__).parent.parent / "data" / "comp_state.json").read_text(encoding="utf-8"))
                    _sel = _cs.get("selected", "")
                    if _sel and hasattr(_rbot, "_item_ctrl"):
                        from tft.comp_control import _load_meta as _lm
                        _meta = _lm()
                        _cd = _meta.get("comps", {}).get(_sel)
                        if _cd:
                            root.after(800, lambda cd=_cd: _bot.set_board_from_placement(cd))
                except Exception:
                    pass
            root.after(500, lambda: self._poll_overlay_files(root))
            logger.info("TFT overlay attached (AI bar active, worker wired)")

            # Wire comp selection from RightBot to BottomStrip
            rbot   = self._overlay.get("rbot")
            bottom = self._overlay.get("bottom")
            if rbot and bottom and hasattr(rbot, "get_comp_ctrl"):
                ctrl = rbot.get_comp_ctrl()
                if ctrl:
                    _orig_cb = ctrl._on_select
                    def _comp_bridge(name, data, _b=bottom, _orig=_orig_cb):
                        if _orig:
                            _orig(name, data)
                        _b.set_comp_positions(data)
                        logger.info("Comp bridge: %s -> BottomStrip positions set",
                                    name or "FLEX")
                    ctrl._on_select = _comp_bridge
        except Exception as e:
            logger.error("TFT overlay attach failed: %s", e)

    def detach_overlay(self) -> None:
        self._teardown_overlay()

    def _poll_overlay_files(self, root) -> None:
        """
        Tk timer loop: reads JSON artifacts and pushes to overlay windows.
        Runs on the Tk main thread via root.after().
        Worker may still be running; this only reads files, never touches worker state.
        """
        if not self._overlay:
            return
        # Check if worker is still alive (or was never started)
        worker_alive = self._worker is not None and self._worker.is_alive()
        if not worker_alive and self._worker is not None:
            # Worker stopped — do one last poll then stop scheduling
            pass  # allow one final read below

        try:
            data = {}
            if self._tft_data_file.exists():
                data = json.loads(self._tft_data_file.read_text(encoding="utf-8"))

            # Merge fresh reader state from worker into data dict for UI accuracy
            _last = self._last_data
            if _last:
                for _k in ("stage", "round", "level", "stage_round",
                           "alive_others", "dead_others", "variant",
                           "game_time_s", "kills", "deaths"):
                    _v = _last.get(_k)
                    if _v is not None:
                        data[_k] = _v
                # Vision HP preferred over API HP
                try:
                    _ld = json.loads(self._live_data_file.read_text(encoding="utf-8"))
                    _vh = _ld.get("hp")
                    if _vh and isinstance(_vh, (int, float)) and 0 < float(_vh) <= 100:
                        data["health"] = int(float(_vh))
                    _vs = _ld.get("stage_round", "")
                    if _vs and "-" in str(_vs):
                        try:
                            _vp  = str(_vs).split("-")
                            _vst = int(_vp[0]); _vrn = int(_vp[1])
                            _ast = data.get("stage", 1); _arn = data.get("round", 1)
                            _v_idx = _vst * 10 + _vrn
                            _a_idx = _ast * 10 + _arn
                            _diff  = _v_idx - _a_idx
                            if 1 <= _vst <= 9 and 1 <= _vrn <= 9 and -2 <= _diff <= 8:
                                data["stage"]       = _vst
                                data["round"]       = _vrn
                                data["stage_round"] = _vs
                        except (ValueError, IndexError):
                            pass
                except Exception:
                    pass

            for win in self._overlay.values():
                try:
                    win.update(data)
                except Exception:
                    pass

            if self._live_data_file.exists():
                live = json.loads(self._live_data_file.read_text(encoding="utf-8"))
                up = live.get("unit_placement", "") or ""
                known_board = {
                    str(u).lower().split()[0]
                    for u in (live.get("board_units") or [])
                    if u and u not in ("unknown", "empty", "SPECTATING")
                }
                _is_duo = data.get("variant") == "double_up"
                _is_spectating = any(
                    str(u) == "SPECTATING"
                    for u in (live.get("bench_units") or [])
                )
                if len(known_board) < 2 and not (
                    _is_duo and (_is_spectating or not live.get("board_units"))
                ):
                    known_board = set()
                elif len(known_board) < 2 and _is_duo:
                    known_board = set()

                if data.get("board"):
                    coach_placement = _coach_board_to_placement(data.get("board", ""))
                    if coach_placement:
                        if known_board:
                            filtered = []
                            for chunk in coach_placement.split(","):
                                name = (
                                    chunk.strip().split()[0].lower()
                                    if chunk.strip() else ""
                                )
                                if any(
                                    name.startswith(kb) or kb.startswith(name)
                                    for kb in known_board
                                ):
                                    filtered.append(chunk.strip())
                            coach_placement = ", ".join(filtered)
                        elif _is_duo and (_is_spectating or not live.get("board_units")):
                            pass  # keep coach_placement as-is
                        if (coach_placement.count(",") >= up.count(",")
                                or coach_placement.count(",") >= 2):
                            live["unit_placement"] = coach_placement

                bottom = self._overlay.get("bottom")
                rbot   = self._overlay.get("rbot")
                if bottom and hasattr(bottom, "update_live"):
                    bottom.update_live(live)
                if rbot and hasattr(rbot, "update_live"):
                    rbot.update_live(live)

        except Exception as exc:
            logger.debug("TFT overlay file poll error: %s", exc)

        # Reschedule only while worker is alive or overlay is still present
        if self._overlay and worker_alive:
            # Detect comp_state change and push to ChampItemControl + board
            try:
                import json as _j; from pathlib import Path as _P
                _cs  = _j.loads((_P(__file__).parent.parent / "data" / "comp_state.json").read_text(encoding="utf-8"))
                _sel = _cs.get("selected", "")
                if _sel and _sel != self._last_sel_comp:
                    self._last_sel_comp = _sel
                    from tft.comp_control import _load_meta as _lm
                    _meta = _lm()
                    _cd = _meta.get("comps", {}).get(_sel, {})
                    if _cd:
                        # Update board placement (bottom center)
                        _bot = self._overlay.get("bottom")
                        if _bot and hasattr(_bot, "set_board_from_placement"):
                            root.after(0, lambda cd=_cd: _bot.set_board_from_placement(cd))
                        # Update ChampItemControl (top-right items panel)
                        _rbot = self._overlay.get("rbot")
                        if _rbot:
                            _ci = getattr(_rbot, "_champ_item", None) or getattr(_rbot, "_item_ctrl", None)
                            if _ci and hasattr(_ci, "set_comp"):
                                root.after(0, lambda s=_sel, cd=_cd: _ci.set_comp(s, cd))
                        # Update Lv4/Lv7 strip
                        _bot2 = self._overlay.get("bottom")
                        if _bot2 and hasattr(_bot2, "_bottom_strip"):
                            root.after(0, lambda cd=_cd: _bot2._bottom_strip.set_board_from_placement(cd))
                        logger.info("Comp changed -> %s: pushed to ChampItemControl + board", _sel)
            except Exception as _exc:
                logger.debug("comp_state poll: %s", _exc)

            root.after(500, lambda: self._poll_overlay_files(root))

    def _teardown_overlay(self) -> None:
        for win in list(self._overlay.values()):
            try:
                if hasattr(win, "destroy_clock"):
                    win.destroy_clock()
                win.destroy()
            except Exception:
                pass
        self._overlay = {}

    def _ensure_data_files(self) -> None:
        for path, default in [
            (self._tft_data_file, {
                "mode": "tft", "action": "", "board": "", "econ": "",
                "rolldown": "", "items": "", "god_pick": "", "placement": "",
                "upgrade": "", "risk": "",
            }),
            (self._live_data_file, {
                "mode": "tft_live", "comp": "", "build": "", "buy": "",
                "sell": "", "keep": "", "augment_play": "", "loss": "",
                "augment_select": False,
            }),
        ]:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text(json.dumps(default, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.warning("Could not create data file %s: %s", path, exc)
