# arch: Mission Control bearer-token gate (POST only, fails closed) | section=mc | frozen=no
"""Bearer-token auth for the Mission Control POST surface.

Resolution order mirrors core/vision_token.py, first hit wins:
  1. env RC_MC_TOKEN
  2. config/mission_control_token.txt (first line, stripped)

There is NO hardcoded fallback and NO fail-open. If neither source yields a
token, every POST is refused with 503. This is the inverse of RC's usual
fail-soft rule and it is deliberate: S9 added an action that KILLS PROCESSES,
so an unconfigured control plane must refuse rather than serve.

GET is not gated here. The bind scope (loopback + tailnet only, see
mc/server.py) is the perimeter for read-only status.

The token is never logged, never echoed in a response body, and never placed
in a URL or query string.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "config" / "mission_control_token.txt"

_BEARER = "Bearer "

# Byte-identical for "no header" and "wrong token" - a caller must not be able
# to tell which of the two it hit.
_UNAUTHORIZED = {"ok": False, "error": "unauthorized"}
_UNCONFIGURED = {"ok": False, "error": "auth not configured"}


def resolve_token() -> str | None:
    """The active token, or None when the server has none configured."""
    env = os.environ.get("RC_MC_TOKEN", "").strip()
    if env:
        return env
    try:
        first = TOKEN_FILE.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return first or None


def check(auth_header: str | None) -> tuple[bool, int, dict]:
    """Gate one request. Returns (ok, status, body).

    status and body are only meaningful when ok is False; the caller sends
    them verbatim and does no further work."""
    token = resolve_token()
    if token is None:
        return False, 503, dict(_UNCONFIGURED)
    if not auth_header or not auth_header.startswith(_BEARER):
        return False, 401, dict(_UNAUTHORIZED)
    supplied = auth_header[len(_BEARER):].strip()
    if not hmac.compare_digest(supplied, token):
        return False, 401, dict(_UNAUTHORIZED)
    return True, 200, {}
