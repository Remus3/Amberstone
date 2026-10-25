"""
coaches/tft_pbe_coach.py

TFT PBE coaching - Double Up focus. Pre-T2 self-polling twin of tft_coach.py,
reached only through coaches/__init__.py load_coach() when
config/coach_settings.json sets "tft_pbe" (load_coach has no production
caller today: app/_game_lifecycle.py builds coaches.tft_coach through
core/coach_registry.py).

RM-845: no set is hard-wired here any more. The set comes from
tft/tft_set.py (live set id > RC_TFT_SET > newest ingested set) and the
engine's system prompt from tft/tft_prompt.py, shared with the live engine;
the Realm of the Gods round schedule is injected only when the resolved set's
round schedule is the Set 17 one (RM-862, tft/tft_state_reader.py
round_schedule).

Architecture:
  TftStateReader      - polls Riot Live Client API (same as live)
  TftPbeCoachEngine   - text coaching, Double Up (tft/tft_pbe_engine.py)
  TftLiveAnalysis     - vision-based coaching (reused; every ingested roster)
  TftOverlay          - 3 tkinter windows (reused)
"""

import sys
import logging
import threading
import time
from pathlib import Path

from coaches._base_coach import read_api_key, safe_write

logger = logging.getLogger("rc.coaches.tft_pbe")

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

try:
    from tft.tft_state_reader   import TftStateReader
    from tft.tft_pbe_engine     import TftPbeCoachEngine
    from tft.tft_live_analysis  import TftLiveAnalysis
    _HAS_TFT = True
except Exception as _e:  # noqa: BLE001
    logger.error("TFT PBE subsystem import failed: %s", _e)
    _HAS_TFT = False


def _read_api_key(app_dir: Path | None = None) -> str:
    """ENVIRONMENT first, API-Key-Claude.txt as fallback - never raises.

    ENV-APIKEY (s112): no longer a private copy; delegates to the ONE shared
    lookup (core.anthropic_key via read_api_key). ``app_dir`` None = the RC
    repo root. Pinned by tests/test_api_key_load_order.py and
    tests/test_api_key_single_lookup_env_apikey.py.
    """
    return read_api_key(app_dir)


class Coach:
    """
    TFT PBE coach, Double Up. Uses the PBE engine, whose system prompt is
    the resolved set's shared build (tft/tft_prompt.py, RM-845).
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

        api_key = _read_api_key()

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
        logger.info("TFT PBE Coach started (Double Up, vision enabled)")

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

            except Exception as exc:  # noqa: BLE001
                logger.debug("TFT PBE poll error: %s", exc)
            time.sleep(1.5)

    @staticmethod
    def _inject_pbe_events(state: dict):
        """Override round events with the Realm of the Gods schedule.

        RM-862: the schedule comes from the resolved set's round schedule
        (tft/tft_state_reader.py round_schedule, RM-855; the RM-858 pattern),
        so the Set 17 tables in tft/tft_pbe_data.py are injected only for
        Set 17 with that mechanic. Before RM-862 the gate was set_has_gods()
        (RM-845), which let any set whose meta records Realm of the Gods (a
        Set 18 or a later ingested set) take the Set 17 rounds. Every other
        set keeps the state reader's own round fields, which already come
        from round_schedule (the neutral schedule); so does a schedule
        failure.
        """
        try:
            from tft import tft_state_reader
            sched = tft_state_reader.round_schedule()
            if sched.label != tft_state_reader.SCHEDULE_GODS:
                return
        except Exception:  # noqa: BLE001
            return
        from tft.tft_pbe_data import BOON_ROUND  # not in RoundSchedule; gods schedule only
        round_key = (state.get("stage", 1), state.get("round", 1))
        stage_round_str = state.get("stage_round", f"{round_key[0]}-{round_key[1]}")
        rf = sched.fields(*round_key)

        state["round_event"] = rf["round_event"]
        state["is_pve"]      = rf["is_pve"]
        state["is_carousel"] = False  # Realm of the Gods replaces the carousel
        state["is_god_round"] = rf["is_god_round"]
        state["is_boon_round"] = round_key == BOON_ROUND
        state["tempo_note"]  = sched.tempo.get(stage_round_str, "")  # keyed on the state's own string

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
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not create PBE data file %s: %s", path, exc)
