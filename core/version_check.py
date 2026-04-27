"""
core/version_check.py — Detect League client and game version.

Reads the League client version from the Riot Live Client Data API
or from the League install directory. Stores in data/client_version.json
for reference and compatibility checking.

Usage:
    from core.version_check import check_version
    info = check_version()
    # info = {"game_version": "26.07", "client_version": "16.7.760.9654", ...}
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

_log = logging.getLogger("rc.version")

_VERSION_FILE = "client_version.json"


def check_version(app_dir: Path = None) -> dict:
    """
    Attempt to read the League client version. Returns a dict with:
      game_version, client_version, tft_version, timestamp, source
    Saves to data/client_version.json for persistence.
    """
    if app_dir is None:
        app_dir = Path(__file__).parent.parent

    info = {
        "game_version": None,
        "client_version": None,
        "tft_version": None,
        "timestamp": None,
        "source": None,
    }

    # Try Live Client Data API (only works during a game)
    api_info = _try_live_api()
    if api_info:
        info.update(api_info)
        info["source"] = "live_api"

    info["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if info["game_version"]:
        # Only persist when we got a real version — prevents the prior
        # cached-good version from being clobbered by a successful API
        # call that returned an empty `gameVersion` field.
        _save(app_dir, info)
        _log.info("League version: game=%s client=%s tft=%s",
                  info["game_version"], info["client_version"], info["tft_version"])
    else:
        _log.debug("Version check: no active game detected, loading cached")
        cached = _load(app_dir)
        if cached:
            info = cached

    return info


def get_cached_version(app_dir: Path = None) -> Optional[dict]:
    """Load the last saved version info without making API calls."""
    if app_dir is None:
        app_dir = Path(__file__).parent.parent
    return _load(app_dir)


def _try_live_api() -> Optional[dict]:
    """Query Riot's Live Client Data API for game version."""
    try:
        import urllib.request
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url = "https://192.168.8.237:2999/liveclientdata/gamestats"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2, context=ctx) as resp:
            data = json.loads(resp.read())
            return {
                "game_version": data.get("gameVersion", ""),
                "client_version": None,  # not in this endpoint
                "tft_version": None,
            }
    except Exception:
        return None


def _save(app_dir: Path, info: dict):
    try:
        data_dir = app_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        p = data_dir / _VERSION_FILE
        # Atomic write: tmp + replace so a mid-write interruption never
        # leaves the file empty/partial. Mirrors the pattern used by
        # `_atomic_write_json` (web_dashboard) and `safe_write` (BaseCoach).
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(info, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception as exc:
        _log.debug("Version save failed: %s", exc)


def _load(app_dir: Path) -> Optional[dict]:
    try:
        p = app_dir / "data" / _VERSION_FILE
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None
