"""Vision-server bearer token resolver.

Resolution order (first hit wins):
  1. Env var ``RC_VISION_TOKEN``.
  2. File ``config/vision_token.txt`` (first line, stripped).
  3. Hardcoded legacy default.

The legacy default is kept so existing Game-PC relay agents keep
authenticating until they're re-deployed with the new resolver.

## Rotation procedure

  1. Generate a new token:
     ``python -c "import secrets; print(secrets.token_hex(16))"``
  2. On Legion — write it to ``C:\\Riot Commander\\config\\vision_token.txt``
     (first line, no newline required) OR set ``RC_VISION_TOKEN`` env
     var for the supervisor process.
  3. On Game-PC — either set ``RC_VISION_TOKEN`` in the environment of
     the tray agents OR drop the same content at
     ``tools/vision_token.txt`` (the Game-PC tools' built-in resolver
     looks in the same relative location next to their scripts).
  4. Restart the supervisor on Legion (``echo x > restart_trigger.txt``)
     + restart the Game-PC relay agents.
  5. Verify ``get_vision_token_source()`` on both sides returns
     ``"env"`` or ``"config"`` — not ``"legacy"``.
  6. Once both sides confirm non-legacy, retire ``_LEGACY_DEFAULT``
     below (delete the constant and the last fallback branch).

Inspection: ``python -c "from core.vision_token import debug; debug()"``
prints the active source + first/last chars of the token so you can
confirm a rotation without exposing the secret in the terminal.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

logger = logging.getLogger("core.vision_token")

# AUDIT (2026-04-22): retire this literal after rotation. Kept today
# because Game-PC tools haven't been redeployed with the resolver —
# removing it would break vision auth across the LAN.
_LEGACY_DEFAULT = "8e8f131e212b329438218eca27372dde"
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "vision_token.txt"

TokenSource = Literal["env", "config", "legacy"]


def _resolve() -> tuple[str, TokenSource]:
    env = os.environ.get("RC_VISION_TOKEN")
    if env and env.strip():
        return env.strip(), "env"
    try:
        if _CONFIG_PATH.exists():
            first_line = _CONFIG_PATH.read_text(encoding="utf-8").splitlines()[0].strip()
            if first_line:
                return first_line, "config"
    except OSError:
        pass
    return _LEGACY_DEFAULT, "legacy"


def get_vision_token() -> str:
    """Return the active token. See module docstring for resolution order."""
    return _resolve()[0]


def get_vision_token_source() -> TokenSource:
    """Return which source produced the active token: ``env``, ``config``,
    or ``legacy``. Ops can call this to confirm a rotation took effect
    without logging the token itself."""
    return _resolve()[1]


def is_using_legacy_fallback() -> bool:
    return get_vision_token_source() == "legacy"


def debug() -> None:
    """Print the active source + first/last 4 chars of the token. Never
    prints the full secret — safe for copy-paste troubleshooting."""
    tok, src = _resolve()
    if len(tok) >= 8:
        masked = f"{tok[:4]}…{tok[-4:]}"
    else:
        masked = "(short)"
    print(f"vision_token source={src} token={masked} len={len(tok)}")


# Log resolution source once at import time so operators see it in the
# supervisor log without having to probe.
try:
    _src = get_vision_token_source()
    if _src == "legacy":
        logger.warning(
            "vision_token: using LEGACY hardcoded fallback — rotate by "
            "setting RC_VISION_TOKEN env var or writing config/vision_token.txt"
        )
    else:
        logger.info("vision_token: resolved from %s", _src)
except Exception:           # never let diagnostics break imports
    pass

# Module-level constant for sites that can't call a function at import time.
VISION_TOKEN = get_vision_token()
