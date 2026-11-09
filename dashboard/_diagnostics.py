"""Diagnostics payload cache.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

`_build_diagnostics()` (in `dashboard.builders`) fans out to several
heavy probes - DB introspection, log tail, RC + vision health - and
sustains ~2 s. `/api/diagnostics` (dashboard/routes_diag.py) serves the
bytes verbatim; nothing polls it, so a 30 s TTL feels instant on repeat
opens without staling the data.

Single-flight: while one thread is rebuilding the payload, others wait
on the lock and reuse the result rather than each running their own
~2 s rebuild. A build that raises is not cached: the exception reaches
the caller (routes_diag scrubs it off the wire) and the next call retries.

True-audit s144 (tests/test_diagnostics_cache_true_audit_s144.py):
  - the TTL runs on time.monotonic(), not the wall clock: a backward wall
    step of N seconds used to pin the old payload for N + 30 s;
  - the body is always STRICT JSON: health.json is embedded verbatim and
    its reader (json.loads) accepts NaN / Infinity and turns 1e400 into
    inf, which json.dumps re-emitted as bare `NaN` / `Infinity` tokens that
    every strict parser rejects. A non-finite float is serialized as null;
  - the cache holds ONE immutable (payload, expires) tuple, so the
    lock-free fast path cannot pair one build's payload with another's
    expiry.
"""
from __future__ import annotations

import json
import math
import threading
import time

from dashboard.builders import _build_diagnostics

# One entry: "entry" -> (payload bytes, monotonic expiry). Absent = empty.
_DIAG_CACHE: dict = {}
_DIAG_TTL_S = 30.0
_DIAG_LOCK = threading.Lock()


def _finite_or_none(value):
    """`value` with every non-finite float replaced by None, recursively
    through dicts, lists and tuples (the only containers JSON can hold)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite_or_none(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_or_none(v) for v in value]
    return value


def _encode(data) -> bytes:
    """Strict-JSON UTF-8 bytes for `data`; a non-finite float becomes null."""
    try:
        text = json.dumps(data, allow_nan=False)
    except ValueError:
        # An out-of-range float is the expected cause (the builder output is
        # JSON-derived); sanitize once and dump again, still strict. Any
        # other ValueError (a circular reference, an over-long int) raises
        # again from the second dump and reaches routes_diag's scrubbed 500.
        text = json.dumps(_finite_or_none(data), allow_nan=False)
    return text.encode("utf-8")


def _fresh() -> "bytes | None":
    entry = _DIAG_CACHE.get("entry")
    if entry is not None and time.monotonic() < entry[1]:
        return entry[0]
    return None


def diagnostics_cached() -> bytes:
    payload = _fresh()
    if payload is not None:
        return payload
    with _DIAG_LOCK:
        payload = _fresh()
        if payload is not None:
            return payload
        payload = _encode(_build_diagnostics())
        _DIAG_CACHE["entry"] = (payload, time.monotonic() + _DIAG_TTL_S)
    return payload
