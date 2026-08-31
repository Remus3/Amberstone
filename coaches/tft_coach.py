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

# `_read_api_key` was removed in the lane 8 cycle 34 audit. It read
# API-Key-Claude.txt into a local and had ZERO callers - no direct call, no
# getattr, no string dispatch, no __all__ and no star import (checked in both
# directions). NOTE the name still exists as a PRIVATE DUPLICATE in the twin,
# coaches/tft_pbe_coach.py:38, called at :71; that copy is untouched here and
# is itself unreachable (RM-292b), so this is not a repo-wide removal. The live TFT key path is a different
# symbol entirely: app/_game_lifecycle.py:315 `_try_read_api_key`, which
# reaches the worker without passing through this facade. A dead function
# that loads a secret is a latent secret path with no offsetting benefit,
# so it is gone rather than hardened.


# One TFT board: rows A (front) to D (back), 7 columns. A hex holds exactly
# one unit, so allocation below is greedy against a shared occupancy set - the
# per-class lists are PREFERENCES, not reservations. The head of each list
# reproduces the original hand-picked spread (tanks spaced across the front,
# mages centre-back, ranged on the back flank); the tail exists only so that a
# class with more members than preferred columns still lands somewhere legal
# instead of stacking two units on one hex.
_ALL_HEXES = tuple(f"{row}{col}" for row in "ABCD" for col in range(1, 8))
_TANK_HEXES = ("A1", "A3", "A5", "A7", "A2", "A4", "A6",
               "B1", "B3", "B5", "B7", "B2", "B4", "B6")
_MAGE_HEXES = ("D3", "D4", "D2", "D5", "D1", "C3", "C4", "C2", "C5", "C1")
_RANGED_HEXES = ("D6", "D7", "D5", "C6", "C7", "D2", "D1", "C5", "C2", "C1")


def _claim_hex(preferred, taken):
    """First free hex from ``preferred``, then anywhere legal. None if full."""
    for hexid in preferred:
        if hexid not in taken:
            taken.add(hexid)
            return hexid
    for hexid in _ALL_HEXES:
        if hexid not in taken:
            taken.add(hexid)
            return hexid
    return None


def _coach_board_to_placement(board_text):
    """Convert coach board to grid positions. Handles both grid format and FRONT/BACK format.

    ``board_text`` arrives from a model response, so a non-string is a
    realistic upstream shape change rather than a hypothetical; it yields ""
    rather than the TypeError that ``re.search`` used to raise.
    """
    if not isinstance(board_text, str):
        return ""
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
    tanks, ranged_u, mages = [], [], []
    for name in all_names:
        nl = name.lower().split()[0]
        if nl in _ranged:  ranged_u.append(name)
        elif nl in _mage:  mages.append(name)
        else:              tanks.append(name)
    # Greedy against one shared occupancy set. The previous form indexed a
    # fixed column list and fell back to an arithmetic column, which handed
    # the same hex to two units as soon as a class outgrew its list - three
    # mages returned "Anivia D4, Swain D4" and six tanks returned both
    # "Delta A7" and "Foxtrot A7". A unit that finds no legal hex is dropped
    # rather than stacked; that needs 29 units, which no TFT board reaches.
    units = []
    taken: set = set()
    for names, preferred in (
        (tanks, _TANK_HEXES),
        (mages, _MAGE_HEXES),
        (ranged_u, _RANGED_HEXES),
    ):
        for name in names:
            hexid = _claim_hex(preferred, taken)
            if hexid is not None:
                units.append(f"{name} {hexid}")
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

    def reset_state(self) -> bool:
        """Reset TFT components and clear data files. True if both files landed.

        Returns a verdict because `safe_write` never raises: it logs its own
        fault and returns False, so an `except` around it can never fire and
        the caller has no other channel. This method used to log "data files
        cleared" unconditionally, which was false whenever the write failed -
        reachable for real, since unlike `_ensure_data_files` this path never
        created the parent directory, and a Defender lock can also exhaust
        safe_write's three retries.
        """
        # Delegate to worker if available
        if self._worker is not None:
            if getattr(self._worker, "_engine", None) is not None:
                try:
                    self._worker._engine.reset_state()
                except Exception:  # noqa: BLE001
                    pass
            if getattr(self._worker, "_live", None) is not None:
                try:
                    live = self._worker._live
                    live._known_augments = []
                    live._last_write     = {}
                    live._last_round     = (0, 0)
                except Exception:  # noqa: BLE001
                    pass
        # Clear data files (atomic - the dashboard polls these mid-write).
        # mkdir first: this path used to assume the directory existed, which
        # is the failure mode that made the old unconditional success log wrong.
        failed = []
        for path, default in self._default_payloads():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning("TFT reset: cannot create %s: %s", path.parent, exc)
                failed.append(path.name)
                continue
            # `is False` rather than `not ok`: only a positive failure report
            # from safe_write counts, so a wrapper that returns None cannot
            # manufacture a false alarm.
            if safe_write(path, default) is False:
                failed.append(path.name)
        if failed:
            logger.warning("TFT state reset INCOMPLETE - not cleared: %s",
                           ", ".join(failed))
            return False
        logger.info("TFT state reset - data files cleared")
        return True

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
            except Exception:  # noqa: BLE001
                pass
            # Reset engine debounce so it re-runs at next poll
            if getattr(self._worker, "_engine", None) is not None:
                try:
                    self._worker._engine._last_call = 0
                    if self._last_data:
                        self._worker._engine.submit(self._last_data)
                except Exception:  # noqa: BLE001
                    pass

    def _default_payloads(self):
        """The blank payload for each data file - ONE definition, two callers.

        `_ensure_data_files` and `reset_state` each carried their own literal
        and the two had drifted: the live-data default was 9 keys here against
        19 in reset_state. The 19-key spelling is the canonical one, corroborated
        by core/feature_policy.py:102 `_TFT_LIVE_DISABLED_PAYLOAD` and by the
        live producer tft/tft_live_analysis.py:477 - so the short copy was the
        outlier and is NOT what the two were reconciled onto.
        """
        return [
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
        ]

    def _ensure_data_files(self) -> bool:
        """Seed any missing data file. True if every file is present after."""
        ok = True
        for path, default in self._default_payloads():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning("Could not create data dir %s: %s", path.parent, exc)
                ok = False
                continue
            if not path.exists() and safe_write(path, default) is False:
                logger.warning("Could not create data file %s", path)
                ok = False
        return ok
