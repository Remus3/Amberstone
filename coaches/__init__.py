"""
coaches/__init__.py
Dynamic coach loader - only imports the module needed for the active game mode.
Supports PBE toggle for TFT Set 17 via config/coach_settings.json {"tft_pbe": true}.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

_log = logging.getLogger("rc.coaches")

_MODE_MAP = {
    # Summoner's Rift
    "CLASSIC":          "coaches.sr_coach",
    "PRACTICETOOL":     "coaches.sr_coach",
    # ARAM + Mayhem
    "ARAM":             "coaches.aram_coach",
    "ARAM_UNRANKED_5x5":"coaches.aram_coach",
    # Arena 2v2v2v2
    "ARENA":            "coaches.arena_coach",
    "CHERRY":           "coaches.arena_coach",
    # Brawl / Rotating modes
    "NEXUSBLITZ":       "coaches.brawl_coach",
    "ULTBOOK":          "coaches.brawl_coach",    # URF / ARURF
    "GAMEMODEX":        "coaches.brawl_coach",    # One For All / others
    "ONEFORALL":        "coaches.brawl_coach",
    "URF":              "coaches.brawl_coach",
    "ARURF":            "coaches.brawl_coach",
    # TFT - all variants use the same TFT coach (mode variant detected internally)
    "TFT":              "coaches.tft_coach",
    "TFT_RANKED":       "coaches.tft_coach",
    "TFT_UNRANKED":     "coaches.tft_coach",
    "TFT_DOUBLE_UP":    "coaches.tft_coach",      # Double Up / Duo
    "TFT_TURBO":        "coaches.tft_coach",      # Hyper Roll
    "TFT_PAIRS":        "coaches.tft_coach",      # Double Up alias
}

# Game mode prefixes that indicate a given base mode
_PREFIX_MAP = [
    ("TFT",        "coaches.tft_coach"),
    ("ARAM",       "coaches.aram_coach"),
    ("ARENA",      "coaches.arena_coach"),
    ("CHERRY",     "coaches.arena_coach"),
    ("NEXUS",      "coaches.brawl_coach"),
    ("URF",        "coaches.brawl_coach"),
    ("ULTBOOK",    "coaches.brawl_coach"),
    ("GAMEMODEX",  "coaches.brawl_coach"),
]

_loaded: dict = {}


def _is_tft_pbe() -> bool:
    """Check config for PBE toggle."""
    try:
        cfg_path = Path(__file__).parent.parent / "config" / "coach_settings.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            return bool(cfg.get("tft_pbe", False))
    except Exception:  # noqa: BLE001
        pass
    return False


def load_coach(game_mode: str, data_file: str, debug: bool = False) -> object | None:
    # Exact match first
    module_path = _MODE_MAP.get(game_mode)

    # Prefix match if no exact
    if not module_path:
        gm_upper = game_mode.upper()
        for prefix, path in _PREFIX_MAP:
            if gm_upper.startswith(prefix):
                module_path = path
                break

    # Default fallback
    if not module_path:
        module_path = "coaches.sr_coach"

    # PBE override: if TFT mode and pbe flag is set, use PBE coach
    if module_path == "coaches.tft_coach" and _is_tft_pbe():
        module_path = "coaches.tft_pbe_coach"
        _log.info("TFT PBE mode enabled - using Set 17 coach")

    if module_path in _loaded:
        return _loaded[module_path]

    _log.info("Loading coach for mode=%s  module=%s", game_mode, module_path)
    try:
        import importlib
        mod  = importlib.import_module(module_path)
        inst = mod.Coach(data_file, debug=debug)
        _loaded[module_path] = inst
        return inst
    except Exception as exc:  # noqa: BLE001
        _log.error("Failed to load coach %s: %s", module_path, exc)
        return None


def unload_all() -> None:
    for path, coach in list(_loaded.items()):
        try:
            if hasattr(coach, "shutdown"):
                coach.shutdown()
        except Exception as exc:  # noqa: BLE001
            _log.warning("Error unloading %s: %s", path, exc)
    _loaded.clear()
