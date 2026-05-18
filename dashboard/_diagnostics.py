"""Diagnostics payload cache.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

`_build_diagnostics()` (in `dashboard.builders`) fans out to several
heavy probes - DB introspection, log tail, RC + vision health - and
sustains ~2 s. The dashboard hits `/api/diagnostics` on view-activate
and nothing polls it, so a 30 s TTL feels instant on repeat opens
without staling the data.

Single-flight: while one thread is rebuilding the payload, others wait
on the lock and reuse the result rather than each running their own
~2 s rebuild.
"""
from __future__ import annotations

import json
import threading
import time

from dashboard.builders import _build_diagnostics

_DIAG_CACHE: dict = {"payload": b"", "expires": 0.0}
_DIAG_TTL_S = 30.0
_DIAG_LOCK = threading.Lock()


def diagnostics_cached() -> bytes:
    now = time.time()
    cur = _DIAG_CACHE
    if cur.get("payload") and now < cur.get("expires", 0):
        return cur["payload"]
    with _DIAG_LOCK:
        cur = _DIAG_CACHE
        if cur.get("payload") and time.time() < cur.get("expires", 0):
            return cur["payload"]
        payload = json.dumps(_build_diagnostics()).encode("utf-8")
        _DIAG_CACHE["payload"] = payload
        _DIAG_CACHE["expires"] = time.time() + _DIAG_TTL_S
    return payload
