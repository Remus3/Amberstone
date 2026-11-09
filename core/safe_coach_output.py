"""Friendly degraded-mode wrapper for a coach's tick method (D14).

`safe_coach_output(mode_name)` decorates a coach `_run_coach` (or any other
tick method) so that NO exception escapes it and no raw API error text ever
reaches a dashboard panel. On an exception it:

1. classifies it into one short, operator-actionable reason
   (`classify_coach_error`) and builds `(<Mode> coach paused - <reason>)`;
2. logs the raw error to the `coach` logger as `"<Mode> coach error: <msg>"`
   (the gated drain tools match that first line); an INTERNAL error also
   carries its traceback, so a real bug in a tick is never a silent
   degradation, while an API fault stays one line per tick;
3. publishes the status: through `self.<write_status_fn_name>(status)` when the
   coach defines it, else by patching the `immediate` field of the coach's own
   artifact `self._out` (read the current document, set the one field, write it
   atomically through `core.polled_json`). The live ARAM, Arena and Brawl
   coaches define no status writer, so the artifact patch IS the live path.

The wrapped call returns None after an exception. Every fault inside the
handler itself is logged and swallowed: the decorator never raises.

Classification order: the credit-balance text (Anthropic sends it as an HTTP
400, so it must win over the status code), then the exception's integer
`status_code`, then its type (builtin TimeoutError / ConnectionError and the
SDK's timeout / connection classes, by MRO name so this module never imports
an SDK), and last a word-boundary match on the message. Whole-token matching
is deliberate: a plain substring test once called a KeyError naming
`separate_limit` "rate limited" and a count of 14000 "request invalid".
"""
from __future__ import annotations

import functools
import json
import logging
import re

from core.polled_json import atomic_write_text

_log = logging.getLogger("coach")

# Reason strings shown to the operator inside "(<Mode> coach paused - ...)".
CREDITS = "add API credits"
RATE_LIMITED = "rate limited"
AUTH = "auth error"
INVALID = "request invalid"
TIMEOUT = "API timeout"
UNAVAILABLE = "API unavailable"
UNREACHABLE = "API unreachable"
INTERNAL = "internal error"

_CREDIT_RE = re.compile(r"credit balance")

# 504 is the SDK's DeadlineExceededError (body type timeout_error): a timeout,
# so it is listed here and never falls through to the >= 500 "unavailable" rule.
_STATUS_REASONS = {429: RATE_LIMITED, 401: AUTH, 403: AUTH, 408: TIMEOUT, 504: TIMEOUT,
                   400: INVALID, 413: INVALID, 422: INVALID}

# Exception class names (anywhere in the MRO) that name a transport fault.
_TIMEOUT_TYPES = frozenset({"TimeoutError", "APITimeoutError", "TimeoutException",
                            "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout",
                            "DeadlineExceededError"})
_CONNECTION_TYPES = frozenset({"ConnectionError", "APIConnectionError", "ConnectError",
                               "NetworkError", "URLError"})

# Message fallback, checked in this order. Each pattern names a whole token or
# an SDK error type so an unrelated identifier or number cannot match.
_MESSAGE_RULES = (
    (re.compile(r"\brate[ _-]?limit"), RATE_LIMITED),
    (re.compile(r"authentication|\b401\b"), AUTH),
    (re.compile(r"\b400\b|invalid_request"), INVALID),
    (re.compile(r"timeout|timed out"), TIMEOUT),
    (re.compile(r"overloaded|\b529\b"), UNAVAILABLE),
    (re.compile(r"unreachable|connection[ _](?:error|refused|reset|aborted|closed|lost|pool)"
                r"|\bno connection\b|failed to establish a new connection"), UNREACHABLE),
)


def _guarded(fn, default):
    """fn() or `default` if it raises: the handler reads attributes of objects
    it does not control (a broken __str__ or property must not escape it)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 - any fault degrades to the default
        return default


def _safe_str(exc: BaseException) -> str:
    """str(exc) that cannot raise."""
    return _guarded(lambda: str(exc), f"<unprintable {type(exc).__name__}>")


def classify_coach_error(exc: BaseException) -> str:
    """Return the short operator-facing reason for a coach-tick exception. Never raises."""
    return _guarded(functools.partial(_classify, exc), INTERNAL)


def _classify(exc: BaseException) -> str:
    msg = _safe_str(exc).lower()
    if _CREDIT_RE.search(msg):
        return CREDITS
    code = _guarded(lambda: getattr(exc, "status_code", None), None)
    if type(code) is int:  # exact int: no bool, no subclass with odd __hash__ / __ge__
        if code in _STATUS_REASONS:
            return _STATUS_REASONS[code]
        if code >= 500:
            return UNAVAILABLE
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & _TIMEOUT_TYPES:
        return TIMEOUT
    if names & _CONNECTION_TYPES:
        return UNREACHABLE
    for pattern, reason in _MESSAGE_RULES:
        if pattern.search(msg):
            return reason
    return INTERNAL


def coach_status_text(mode_name: str, exc: BaseException) -> str:
    """The degraded status line, e.g. "(ARAM coach paused - rate limited)"."""
    return f"({mode_name} coach paused - {classify_coach_error(exc)})"


def _patch_artifact(coach, status: str) -> None:
    """Set `immediate` in the coach's artifact, keeping every other field."""
    out_path = getattr(coach, "_out", None)
    if not out_path:
        return
    current = None
    if out_path.exists():
        try:
            loaded = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _log.debug("safe fallback: unreadable %s (%s), using blank artifact",
                       out_path.name, exc)
        else:
            if isinstance(loaded, dict):
                current = loaded
    if current is None:
        current = coach._blank_artifact_data()
    current["immediate"] = f"Immediate: {status}"
    atomic_write_text(out_path, json.dumps(current, indent=2))


def _degrade(coach, exc: BaseException, mode_name: str, write_status_fn_name: str) -> None:
    """Classify, log and publish the paused status for one failed tick."""
    reason = classify_coach_error(exc)
    status = f"({mode_name} coach paused - {reason})"
    # A failing log call (a broken handler or filter) must not cost the status.
    _guarded(functools.partial(_log.error, "%s coach error: %s", mode_name, _safe_str(exc),
                               exc_info=reason == INTERNAL, stacklevel=2), None)
    write_fn = _guarded(lambda: getattr(coach, write_status_fn_name, None), None)
    via = write_status_fn_name if write_fn is not None else "_out"
    try:
        if write_fn is not None:
            write_fn(status)
        else:
            _patch_artifact(coach, status)
    except Exception as wr_e:  # noqa: BLE001 - publishing must not raise
        _log.error("Failed to write safe fallback for %s via %s: %s",
                   mode_name, via, _safe_str(wr_e))


def safe_coach_output(mode_name: str, write_status_fn_name: str = "_write_status_field"):
    """Decorator: a coach tick that degrades to a friendly status, never raises."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:  # noqa: BLE001 - the decorator's whole contract
                # The whole handler runs guarded: whatever the exception, the
                # coach object or the logger does, nothing escapes the tick.
                _guarded(functools.partial(_degrade, self, e, mode_name, write_status_fn_name), None)
                return None
        return wrapper
    return decorator
