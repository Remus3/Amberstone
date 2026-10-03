# arch: vision server config + Anthropic client | section=vision | frozen=no
"""Configuration constants, logging, API key resolution, and lazy Anthropic client.

Split out of moon_vision_server.py during Phase 2.4. Owns:
- PORT / model / auth constants.
- The single shared logger ``log``.
- ``_API_KEY`` + ``_get_client()`` (thread-safe lazy init).
- ``_START_TIME`` + ``SYNC_DIR``.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

# -- Logger -----------------------------------------------------------------
# P2-W1-app-A CWD hardening: anchor the log file to the repo root (this
# module's grandparent dir) instead of the process CWD. dashboard/server.py
# spawns this server by file path, so a CWD other than the repo root would
# otherwise scatter moon_vision_server.log to wherever the spawn happened.
_LOG_PATH = Path(__file__).resolve().parent.parent / "moon_vision_server.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(str(_LOG_PATH), encoding="utf-8")]
)
log = logging.getLogger("moon_vision")

# -- Constants --------------------------------------------------------------
PORT         = 8889
VISION_MODEL = "claude-haiku-4-5-20251001"
COACH_MODEL  = "claude-haiku-4-5-20251001"
# AUDIT (2026-04-22): token resolved via core.vision_token (env var, config
# file, legacy default). AUDIT 2026-04-28 (proposal 1.7): no in-source
# fallback. core.vision_token is the only resolver; if it can't be imported,
# fail loud rather than silently authenticate every probe with a constant.
from core.vision_token import get_vision_token as _get_vision_token
AUTH_TOKEN   = _get_vision_token()
AUTH_HEADER  = "X-RC-Token"
SYNC_DIR     = Path("moon_sync_inbox")
SYNC_DIR.mkdir(exist_ok=True)
_START_TIME  = time.time()


# -- API key + Anthropic client ---------------------------------------------
def _load_key(app_dir: Path | None = None, home: Path | None = None) -> str:
    """ENVIRONMENT first, then API-Key-Claude.txt in three legacy places.

    RM-487 (2026-10-03): this read the three files FIRST and the env var
    LAST - the stale-wins order ba4bb74be flipped in every other consumer,
    so a forgotten key file holding a revoked key beat a rotated env var.
    The read_text was also unguarded, and this runs at IMPORT time, so a
    non-UTF8 key file took the whole :8889 server down. "env first" means
    first VALID (sk-ant- prefix), matching coaches/_base_coach.read_api_key.
    Never raises. Pinned by tests/test_api_key_load_order.py.
    """
    env = os.environ.get("ANTHROPIC_API_KEY", "")
    if env.strip().startswith("sk-ant-"):
        return env.strip()
    root = app_dir if app_dir is not None else Path(__file__).parent.parent
    hdir = home if home is not None else Path.home()
    for p in [root / "API-Key-Claude.txt",
              hdir / "API-Key-Claude.txt",
              hdir / "Desktop" / "API-Key-Claude.txt"]:
        try:
            if p.exists():
                k = p.read_text(encoding="utf-8").strip()
                if k.startswith("sk-ant-"):
                    log.info("Key from %s", p)
                    return k
        except (OSError, UnicodeDecodeError):
            continue
    return env


_API_KEY = _load_key()
_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client, _API_KEY
    if _client is None:
        with _client_lock:
            if _client is None:
                import anthropic
                if not _API_KEY:
                    _API_KEY = _load_key()
                _client = anthropic.Anthropic(api_key=_API_KEY, base_url="https://api.anthropic.com")
    return _client


def api_key_present() -> bool:
    return bool(_API_KEY)
