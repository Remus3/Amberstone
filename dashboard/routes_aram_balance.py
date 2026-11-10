"""GET /api/aram-balance - per-champion ARAM balance modifiers.

Surfaces the seven Riot ARAM modifiers RC already loads into the DS
snapshot but never displays:

  aramDamageDealt / aramDamageTaken / aramHealing / aramShielding /
  aramTenacity / aramAttackSpeed   (MULTIPLIERS, neutral = 1.0)
  aramAbilityHaste                 (ADDITIVE FLAT, neutral = 0)

Only NON-NEUTRAL fields are emitted per champion; fully-neutral champs
are omitted entirely (see core.aram_balance_context.balance_grid_map).
The consumer is web/js/panels/aram_balance.js.

Replies (true-audit s144 S144-T-755,
tests/test_routes_aram_balance_true_audit_s144.py):

  200 {"ok": true, "patch": "16.22.1", "champions": {"Aatrox":
       {"aramDamageDealt": 1.05}, ...}}
      ``patch`` is data/daemon_slayer/current.txt read BOM-tolerant and
      kept only when it is a canonical ASCII patch (``16.22`` or
      ``16.22.1``); anything else (several lines, a path, markup,
      non-ASCII digits, an oversized file) is "" and the grid is still
      served.
  503 {"ok": false, "error": "aram-balance unavailable - see logs"}
      The grid is EMPTY. core.aram_balance_context degrades to an empty
      map on any read failure, and the panel renders a champion missing
      from a resolved map as the positive claim "no ARAM changes", so an
      empty grid is answered as unavailable (the panel shows its failure
      state and retries) rather than as "nothing changed". Every live
      patch carries non-neutral champions (132 on 16.22.1). The grid is
      built once at import of core.aram_balance_context, so a failed
      load stays 503 until an RC restart; the route itself caches
      nothing about the failure.
  500 {"ok": false, "error": "aram-balance failed - see logs"}
      Any other failure (RM-835: a fixed line, never exception text;
      dashboard._errors.send_error logs the cause scrubbed).

The (patch, grid) pair is memoized at module scope only once BOTH are
good: the grid is built once at import of core.aram_balance_context, so a
process restart picks up a new patch. A failed or junk patch read and an
empty grid are not memoized, so the next request reads again.

The reply is written OUTSIDE the catch-all: a failure while writing it
(the client went away) propagates to the dispatcher, which closes the
connection, instead of a second status line being written onto the same
response.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

from dashboard._dispatch import equals
from dashboard._errors import send_error

log = logging.getLogger("rc.web_dashboard")

_DS_DIR = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"

# A canonical patch: ASCII digits only (a bare \d would also take
# Arabic-Indic / fullwidth digits), major.minor with an optional build.
_PATCH_RE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}(?:\.[0-9]{1,4})?")
# current.txt holds one short token; a larger file is not a patch.
_PATCH_READ_CAP = 64

_UNAVAILABLE = "aram-balance unavailable - see logs"
_FAILED = "aram-balance failed - see logs"

# The good (patch, grid) pair, or None until one has been read. Replaced
# whole under the lock, never mutated; only this module reads it.
_GRID = None
_PATCH = None
_LOCK = threading.Lock()
_EMPTY_LOGGED = False


def _read_patch() -> str:
    """The canonical patch from current.txt, or "" when it cannot be read
    or is not a canonical ASCII patch. Never raises; logs the failure
    class only, never the file's content."""
    try:
        with open(_DS_DIR / "current.txt", "rb") as fh:
            raw = fh.read(_PATCH_READ_CAP + 1)
    except OSError as exc:
        log.warning("aram-balance: current.txt unreadable (%s)",
                    type(exc).__name__)
        return ""
    if len(raw) > _PATCH_READ_CAP:
        log.warning("aram-balance: current.txt is not a patch (oversized)")
        return ""
    try:
        # utf-8-sig: a PowerShell 5.1 -Encoding UTF8 write leaves a BOM.
        text = raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        log.warning("aram-balance: current.txt is not UTF-8")
        return ""
    if not _PATCH_RE.fullmatch(text):
        log.warning("aram-balance: current.txt is not a canonical patch")
        return ""
    return text


def _get_grid():
    """(patch, champions map). Memoized once both are good; a "" patch or
    an empty grid is returned but not memoized."""
    global _GRID, _PATCH
    with _LOCK:
        if _GRID is not None:
            return _PATCH, _GRID
        from core.aram_balance_context import balance_grid_map

        patch = _read_patch()
        grid = balance_grid_map()
        if patch and grid:
            _PATCH, _GRID = patch, grid
        return patch, grid


def _reset_caches() -> None:
    """Test-only: clear the memoized grid + patch and the log-once flag."""
    global _GRID, _PATCH, _EMPTY_LOGGED
    with _LOCK:
        _GRID = None
        _PATCH = None
        _EMPTY_LOGGED = False


def _log_empty_once() -> None:
    global _EMPTY_LOGGED
    with _LOCK:
        if _EMPTY_LOGGED:
            return
        _EMPTY_LOGGED = True
    log.warning("aram-balance: the balance grid is empty (the ARAM data did "
                "not load - see the aram_balance_context warning); "
                "answering 503 until it does")


def _serve_aram_balance(h) -> None:
    """GET /api/aram-balance -> {ok, patch, champions}."""
    try:
        patch, grid = _get_grid()
        if grid:
            status = 200
            payload = {"ok": True, "patch": patch, "champions": grid}
        else:
            _log_empty_once()
            status = 503
            payload = {"ok": False, "error": _UNAVAILABLE}
        # allow_nan=False: a bare NaN / Infinity token is not JSON and the
        # browser's parser rejects the whole reply.
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        # RM-835: a fixed line, never str(exc); send_error logs the cause
        # once, scrubbed, with its type name and the traceback. A failure
        # to write this reply propagates to the dispatcher.
        send_error(h, exc, public_msg=_FAILED, fields={"ok": False},
                   log_traceback=True)
        return
    h._send(status, body, "application/json")


GET_ROUTES = [
    (equals("/api/aram-balance"), _serve_aram_balance),
]

POST_ROUTES: list = []
