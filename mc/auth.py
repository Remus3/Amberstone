# arch: Mission Control bearer-token gate (POST only, fails closed) | section=mc | frozen=no
"""Bearer-token auth for the Mission Control POST surface.

Resolution order mirrors core/vision_token.py, first hit wins:
  1. env RC_MC_TOKEN
  2. config/mission_control_token.txt (first line, stripped; a UTF-8 BOM is
     dropped)

There is NO hardcoded fallback and NO fail-open. If neither source yields a
token, every POST is refused with 503. This is the inverse of RC's usual
fail-soft rule and it is deliberate: S9 added an action that KILLS PROCESSES,
so an unconfigured control plane must refuse rather than serve.

A token must be printable ASCII with no whitespace (0x21-0x7E, the RM-241 rule
of core/vision_token.py): anything else cannot be sent as a header value. A
source holding such a token - or a token file that is not UTF-8 - counts as
UNCONFIGURED (503, never a fall-through from a bad env token to the file),
with a WARNING at most once a minute per problem that names the source and
the problem, never the token and never a decode error (its text quotes a byte
of the secret).

``check`` never raises (s144 true-audit, RM-1608..252): a non-ASCII or
non-str Authorization value is the plain 401, so "no header", "wrong token"
and "garbage token" stay byte-identical. The compare runs on bytes because
``hmac.compare_digest`` raises TypeError on a str holding any non-ASCII.

GET is not gated here. The bind scope (loopback + tailnet only, see
mc/server.py) is the perimeter for read-only status.

The token is never logged, never echoed in a response body, and never placed
in a URL or query string.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "config" / "mission_control_token.txt"

log = logging.getLogger("rc.mc.auth")

_BEARER = "Bearer "

# Byte-identical for "no header" and "wrong token" - a caller must not be able
# to tell which of the two it hit.
_UNAUTHORIZED = {"ok": False, "error": "unauthorized"}
_UNCONFIGURED = {"ok": False, "error": "auth not configured"}

# One WARNING per (source, problem) per interval: an unauthenticated caller
# can drive POSTs, so a per-request line would let a stranger flood logs/.
_WARN_INTERVAL_S = 60.0
_warn_lock = threading.Lock()
_warned_at: dict[tuple[str, str], float] = {}


def _now() -> float:
    return time.monotonic()


def _reset_warnings() -> None:
    """Forget the rate-limit state (tests)."""
    with _warn_lock:
        _warned_at.clear()


def _warn(source: str, problem: str) -> None:
    key = (source, problem)
    now = _now()
    with _warn_lock:
        last = _warned_at.get(key)
        if last is not None and now - last < _WARN_INTERVAL_S:
            return
        _warned_at[key] = now
    log.warning("mission control auth: the %s token %s; every POST is refused "
                "(503) until it is re-written as one printable-ASCII line",
                source, problem)


def _usable(tok: str) -> bool:
    return all(0x21 <= ord(c) <= 0x7E for c in tok)


def resolve_token() -> str | None:
    """The active token, or None when the server has none usable configured."""
    env = os.environ.get("RC_MC_TOKEN", "").strip()
    if env:
        if _usable(env):
            return env
        _warn("RC_MC_TOKEN", "holds whitespace, control or non-ASCII characters")
        return None
    try:
        text = TOKEN_FILE.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        # A ValueError, not an OSError; its text quotes a byte of the token.
        _warn("config file", "is not UTF-8 text")
        return None
    except OSError:
        return None
    # The first line ends at "\n" only (read_text already folded "\r\n"):
    # str.splitlines also breaks on U+2028, U+0085, \x0b, \x0c and \x1c-\x1e,
    # so "abc<U+2028>rest" used to become the token "abc" - a SHORTER secret
    # accepted silently. Such a line is now unusable, so it is a 503.
    first = text.split("\n", 1)[0].strip()
    if not first:
        return None
    if not _usable(first):
        _warn("config file", "holds whitespace, control or non-ASCII characters")
        return None
    return first


def check(auth_header: object) -> tuple[bool, int, dict]:
    """Gate one request. Returns (ok, status, body). Never raises.

    status and body are only meaningful when ok is False; the caller sends
    them verbatim and does no further work."""
    token = resolve_token()
    if token is None:
        return False, 503, dict(_UNCONFIGURED)
    if not isinstance(auth_header, str) or not auth_header.startswith(_BEARER):
        return False, 401, dict(_UNAUTHORIZED)
    supplied = auth_header[len(_BEARER):].strip()
    # surrogatepass: a lone surrogate (a direct caller; the stdlib header
    # parse cannot produce one) would make a plain .encode() raise.
    if not hmac.compare_digest(supplied.encode("utf-8", "surrogatepass"),
                               token.encode("ascii")):
        return False, 401, dict(_UNAUTHORIZED)
    return True, 200, {}
