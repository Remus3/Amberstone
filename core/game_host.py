# arch: local game-host config | section=core
"""
core/game_host.py - single source of truth for the host running League.

RC_GAME_HOST is where League's Live Client API (:2999) and the LCU lockfile-
based API are reachable. After the 1-PC consolidation (2026-05) League runs on
Legion itself, so the default is 127.0.0.1 (the game host is Legion-local).
Set the RC_GAME_HOST env var to override if the game ever runs on a different
host.

Contract of GAME_HOST (read once, at import): it is the URL AUTHORITY HOST
every reader interpolates as ``f"https://{GAME_HOST}:{port}{path}"``, and the
LCU readers attach the lockfile password to that request as Basic auth. So the
env value is validated before it is used (S144-T-765..769):

- unset, blank or whitespace-only -> the default 127.0.0.1;
- surrounding whitespace is stripped (a trailing space from a .bat `set`);
- an IPv4 address in canonical dotted-quad form is kept as is;
- an IPv6 address is emitted BRACKETED (``[::1]``), the form a URL needs; a
  scope id (``fe80::1%eth0``) is refused (it would need ``%25`` escaping);
- a hostname is lower-cased (DNS is case-insensitive) with one trailing dot
  dropped; it must be ASCII LDH labels of 1-63 chars, 253 chars in all, and
  its last label may not be all digits (``999.1.1.1``, ``127.1`` and
  ``127.000.0.1`` are not hosts, and a resolver may read them as octal or
  short-form addresses);
- anything else - userinfo (``127.0.0.1@evil.example`` sends the request and
  the password to evil.example), a port, a path, a query, a fragment, a
  scheme, whitespace or control bytes inside, non-ASCII - is REFUSED: the
  default is used and one warning naming the env var and a truncated preview
  of the value is logged. Refusing to the loopback default never sends the
  LCU password off the box.
"""
import ipaddress
import logging
import os
import re

ENV_VAR = "RC_GAME_HOST"
DEFAULT_GAME_HOST = "127.0.0.1"

_MAX_HOST_LEN = 253      # RFC 1035 name length, presentation form
_PREVIEW_LEN = 64        # chars of a refused value shown in the warning
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")

_log = logging.getLogger(__name__)


def _ipv6_authority(text: str):
    """``[compressed]`` for a plain IPv6 address, else None."""
    try:
        ip = ipaddress.IPv6Address(text)
    except ValueError:
        return None
    if ip.scope_id is not None:
        return None
    return f"[{ip.compressed}]"


def canonical_host(raw):
    """The URL authority host for ``raw``, or None when it is not one.

    Pure: no logging, no default. ``resolve_game_host`` adds both."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or not text.isascii():
        return None
    if text.startswith("["):
        if not text.endswith("]"):
            return None
        return _ipv6_authority(text[1:-1])
    if ":" in text:
        return _ipv6_authority(text)
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError:
        pass
    host = text.lower().removesuffix(".")
    if not host or len(host) > _MAX_HOST_LEN:
        return None
    labels = host.split(".")
    if not all(_LABEL_RE.match(label) for label in labels):
        return None
    if labels[-1].isdigit():
        return None
    return host


def _preview(raw) -> str:
    if isinstance(raw, str):
        return repr(raw[:_PREVIEW_LEN])
    return f"<{type(raw).__name__}>"


def resolve_game_host(raw) -> str:
    """Validated game host for an RC_GAME_HOST value (see module docstring).

    Never raises: unset / blank -> the default silently; an invalid value ->
    the default plus one logged warning."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return DEFAULT_GAME_HOST
    host = canonical_host(raw)
    if host is None:
        _log.warning(
            "%s refused (%s): not a hostname or IP address; using %s",
            ENV_VAR, _preview(raw), DEFAULT_GAME_HOST,
        )
        return DEFAULT_GAME_HOST
    return host


GAME_HOST = resolve_game_host(os.environ.get(ENV_VAR))
