"""
coaches/tft_pbe_coach.py

TFT Set 17: Space Gods PBE coaching - Double Up focus.
Duplicate of tft_coach.py with Set 17-specific engine and data.

Architecture:
  TftStateReader      - polls Riot Live Client API (same as live)
  TftPbeCoachEngine   - Set 17 text coaching (gods, new traits, Double Up)
  TftLiveAnalysis     - vision-based coaching (reused, Set 17 champ list)
  TftOverlay          - 3 tkinter windows (reused)
"""

import sys
import logging
import threading
import time
from pathlib import Path

from coaches._base_coach import safe_write

logger = logging.getLogger("rc.coaches.tft_pbe")

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

try:
    from tft.tft_state_reader   import TftStateReader
    from tft.tft_pbe_engine     import TftPbeCoachEngine
    from tft.tft_live_analysis  import TftLiveAnalysis
    _HAS_TFT = True
except Exception as _e:
    logger.error("TFT PBE subsystem import failed: %s", _e)
    _HAS_TFT = False


def _read_api_key(app_dir: Path) -> str:
    for p in [app_dir / "API-Key-Claude.txt"]:
        if p.exists():
            k = p.read_text(encoding="utf-8").strip()
            if k.startswith("sk-ant-"):
                return k
    return __import__("os").environ.get("ANTHROPIC_API_KEY", "")


class Coach:
    """
    TFT PBE coach for Set 17: Space Gods Double Up.
    Uses PBE-specific engine with Set 17 system prompt.
    """

    GAME_MODES = ("TFT",)

    def __init__(self, data_file, debug: bool = False):
        self._data_file      = Path(data_file) if not isinstance(data_file, Path) else data_file
        self._debug          = debug
        self._running        = False
        self._poll_thread    = None
        self._overlay        = {}
        self._last_data      = {}
        self._tft_data_file  = self._data_file.parent / "tft_pbe_coaching_data.json"
        self._live_data_file = self._data_file.parent / "tft_pbe_live_data.json"

        self._ensure_data_files()

        if not _HAS_TFT:
            logger.warning("TFT PBE subsystems unavailable - coach will not function")
            return

        api_key = _read_api_key(_APP_DIR)

        self._reader = TftStateReader()
        self._engine = TftPbeCoachEngine(self._tft_data_file, debug=debug)

        # Vision-based live analysis (board/bench/shop + comp advice)
        self._live: TftLiveAnalysis = TftLiveAnalysis(
            api_key   = api_key,
            data_file = self._live_data_file,
        )

        self._running     = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="TftPbeStatePoll"
        )
        self._poll_thread.start()
        self._live.start()
        logger.info("TFT PBE Coach started (Set 17 Double Up, vision enabled)")

    def submit_state(self, state: dict) -> None:
        pass  # TFT self-polls

    def reset_state(self) -> None:
        if hasattr(self, "_engine"):
            self._engine.reset_state()
        if hasattr(self, "_live"):
            self._live._known_augments = []
            self._live._last_write     = {}
            self._live._last_round     = (0, 0)
        self._ensure_data_files()
        logger.info("TFT PBE state reset")

    def shutdown(self) -> None:
        self._running = False
        if hasattr(self, "_live"):
            self._live.shutdown()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2.0)
        if hasattr(self, "_engine"):
            self._engine.shutdown()
        logger.info("TFT PBE Coach shutdown complete")

    def _force_refresh_all(self):
        """CTRL+Right Click: force vision scan + re-run engine."""
        logger.info("Force refresh ALL triggered (PBE)")
        if hasattr(self, "_live"): self._live.force_scan()
        if hasattr(self, "_engine") and self._last_data:
            if hasattr(self._engine, "_last_call"): self._engine._last_call = 0
            self._engine.submit(self._last_data)

    # -- Poll loop -------------------------------------------------------------

    def _poll_loop(self):
        _last_sr = (0, 0)
        while self._running:
            try:
                state = self._reader.read()
                if state:
                    # Inject PBE round events (gods instead of carousel)
                    self._inject_pbe_events(state)
                    self._last_data = state
                    self._engine.submit(state)

                    # Notify live analysis
                    self._live.notify_coach_state(state)
                    sr = (state.get("stage", 0), state.get("round", 0))
                    if sr != _last_sr:
                        _last_sr = sr
                        self._live.notify_round(state)

            except Exception as exc:
                logger.debug("TFT PBE poll error: %s", exc)
            time.sleep(1.5)

    @staticmethod
    def _inject_pbe_events(state: dict):
        """Override round events with Set 17 god schedule."""
        from tft.tft_pbe_data import ROUND_EVENTS, PVE_ROUNDS, GOD_ROUNDS, BOON_ROUND, TEMPO_MILESTONES
        round_key = (state.get("stage", 1), state.get("round", 1))
        stage_round_str = state.get("stage_round", f"{round_key[0]}-{round_key[1]}")

        state["round_event"] = ROUND_EVENTS.get(round_key, "pvp")
        state["is_pve"]      = round_key in PVE_ROUNDS
        state["is_carousel"] = False  # No carousel in Set 17
        state["is_god_round"] = round_key in GOD_ROUNDS
        state["is_boon_round"] = round_key == BOON_ROUND
        state["tempo_note"]  = TEMPO_MILESTONES.get(stage_round_str, "")

    # -- Helpers ---------------------------------------------------------------

    def _ensure_data_files(self):
        for path, default in [
            (self._tft_data_file, {
                "mode": "tft_pbe", "action": "", "board": "", "econ": "",
                "rolldown": "", "items": "", "god": "",
                "placement": "", "upgrade": "", "risk": "",
            }),
            (self._live_data_file, {
                "mode": "tft_pbe_live", "comp": "", "build": "", "buy": "",
                "sell": "", "keep": "", "augment_play": "", "loss": "",
                "augment_select": False,
            }),
        ]:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    safe_write(path, default)
            except Exception as exc:
                logger.warning("Could not create PBE data file %s: %s", path, exc)
