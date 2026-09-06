"""Vision-server bearer token resolver.

Resolution order (first hit wins):
  1. Env var ``RC_VISION_TOKEN``.
  2. File ``config/vision_token.txt`` (first line, stripped).

There is NO hardcoded fallback (the legacy default was retired by the
2026-04-28 audit, proposal 1.7): a missing token raises RuntimeError at
import time so a misconfigured deploy fails loud instead of silently
authenticating every request with a known constant.

## Rotation procedure

  1. Generate a new token:
     ``python -c "import secrets; print(secrets.token_hex(16))"``
  2. On Legion - write it to ``C:\\Riot Commander\\config\\vision_token.txt``
     (first line, no newline required) OR set ``RC_VISION_TOKEN`` env
     var for the supervisor process.
  3. For the Legion-local relay agents - either set ``RC_VISION_TOKEN``
     in their environment OR drop the same content at
     ``tools/vision_token.txt`` (the relay tools' built-in resolver
     looks in the same relative location next to their scripts).
  4. Restart the supervisor on Legion (``echo x > restart_trigger.txt``)
     + restart the Legion-local relay agents.
  5. **Kill the :8889 listener by PID.** Step 4 is NOT enough on its own -
     measured 2026-09-06, and it is the step that makes a rotation look
     done while :8889 still accepts the OLD token. ``vision_server/
     _config.py`` reads ``AUTH_TOKEN`` once at import, and the process
     serving :8889 is a DETACHED child (``moon_vision_server.py``, spawned
     by ``dashboard/server.py``) that SURVIVES a supervisor restart. The
     dashboard's "self-heal" is a one-shot ``connect_ex`` at startup, so on
     the next boot it finds :8889 already up and does nothing - the stale
     token then persists indefinitely. Find the owner with
     ``Get-NetTCPConnection -LocalPort 8889 -State Listen``, ``taskkill /F
     /PID <it>``, THEN write restart_trigger.txt again so the startup check
     misses the port and respawns it on the new token.
  6. Verify ``get_vision_token_source()`` returns ``"env"`` or
     ``"config"``, and prove it on the wire: the new token must return 200
     from ``GET http://127.0.0.1:8889/latest-lcu`` and the OLD one 401.
     Checking only the resolver proves the FILE changed, not the listener.

## The MCP coupling, which a rotation used to drag along

``tools/ds_matchdb_mcp_server.py`` ``_resolve_token`` ends its chain by
falling through to ``get_vision_token()``, so before 2026-09-06 rotating
the vision token silently re-credentialed the :8861 MCP server too. That
side-effect is on the record twice - ``docs/_archive/2026-05-16-doc-sync/
audit-notes.md`` FIX-022 hit it, separated the two, and the separation did
not survive. ``tools/mcp_token.txt`` now exists (gitignored) so the
fallback can never fire again. If you delete it, the coupling comes back.

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

# AUDIT 2026-04-28 (proposal 1.7): legacy hardcoded fallback retired.
# Resolution is env var OR config file ONLY; absence raises RuntimeError
# so a misconfigured deploy fails loud at import time instead of silently
# authenticating every request with a known constant.
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "vision_token.txt"

TokenSource = Literal["env", "config"]


def _resolve() -> tuple[str, TokenSource]:
    env = os.environ.get("RC_VISION_TOKEN")
    if env and env.strip():
        return env.strip(), "env"
    try:
        if _CONFIG_PATH.exists():
            first_line = _CONFIG_PATH.read_text(encoding="utf-8").splitlines()[0].strip()
            if first_line:
                return first_line, "config"
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError):
        pass
    raise RuntimeError(
        "vision_token: no token configured. Set RC_VISION_TOKEN env var "
        f"OR write a token to {_CONFIG_PATH}. See module docstring for "
        "rotation procedure."
    )


def get_vision_token() -> str:
    """Return the active token. See module docstring for resolution order."""
    return _resolve()[0]


def get_vision_token_source() -> TokenSource:
    """Return which source produced the active token: ``env`` or
    ``config``. Ops can call this to confirm a rotation took effect
    without logging the token itself."""
    return _resolve()[1]


def is_using_legacy_fallback() -> bool:
    # 2026-04-28 (proposal 1.7): legacy fallback retired; always False.
    # Kept as a no-op shim for callers (e.g., dashboards) that probe it.
    return False


def debug() -> None:
    """Print the active source + first/last 4 chars of the token. Never
    prints the full secret - safe for copy-paste troubleshooting."""
    tok, src = _resolve()
    if len(tok) >= 8:
        masked = f"{tok[:4]}...{tok[-4:]}"
    else:
        masked = "(short)"
    logger.info(f"vision_token source={src} token={masked} len={len(tok)}")


# Log resolution source once at import time so operators see it in the
# supervisor log without having to probe. A missing token raises here -
# allow that to propagate so a misconfigured deploy fails loud.
logger.info("vision_token: resolved from %s", get_vision_token_source())

# Module-level constant for sites that can't call a function at import time.
VISION_TOKEN = get_vision_token()
