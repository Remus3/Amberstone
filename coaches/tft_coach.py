# arch: TFT Set 17 mode coach | section=coaching | frozen=no
"""
coaches/tft_coach.py
Phase 1 Step 5 - TFT coach facade (post-T2 #6 dashboard-only).

This module is a thin facade. Runtime polling, coaching orchestration, and
TftLiveAnalysis are owned by core/tft_worker.TftWorker - not this class.

Responsibilities retained here:
  - _force_refresh_all() right-click callback (delegates to worker)
  - reset_state() - clears data files and engine/live state via worker refs
  - shutdown() - clears worker reference and resets data (app.py owns TftWorker lifecycle)

Responsibilities that moved to TftWorker:
  - TftStateReader ownership
  - TftCoachEngine ownership and coaching submission
  - TftLiveAnalysis ownership and vision loop
  - _poll_loop() background thread

Single authoritative TFT coaching path: TftWorker._run().
"""

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from coaches._base_coach import safe_write

logger = logging.getLogger("rc.coaches.tft")

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

if TYPE_CHECKING:
    from core.tft_worker import TftWorker

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
    TFT coach facade - manages overlay Tk lifecycle only.

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
        # TftWorker reference - set by app.py via set_worker() after construction
        self._worker = None
        self._ensure_data_files()
        self.reset_state()
        logger.info("TFT Coach facade created (runtime loop in TftWorker)")

    # -- Worker wiring ---------------------------------------------------------

    def set_worker(self, worker: "TftWorker") -> None:
        """Wire the TftWorker after it is created by app.py."""
        self._worker = worker

    # -- Legacy API (kept for compatibility) -----------------------------------

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
        # Clear data files (atomic - the dashboard polls these mid-write)
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
                safe_write(path, default)
            except Exception:
                pass
        logger.info("TFT state reset - data files cleared")

    def shutdown(self) -> None:
        """
        Reset facade state at game end.

        Phase 1 Step 5.1: app.py is the sole owner of TftWorker lifecycle.
        This method does NOT call self._worker.shutdown() - that is done
        exclusively by app.py._on_game_end() to avoid dual shutdown paths.
        """
        # Clear worker reference without shutting it down - app.py owns that
        self._worker = None
        # Clear data files so lobby shows blank, not last game's data
        self.reset_state()
        logger.info("TFT Coach facade shutdown complete")

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
                    safe_write(path, default)
            except Exception as exc:
                logger.warning("Could not create data file %s: %s", path, exc)
