"""Atomic JSON writers + dashboard write actions.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

CLAUDE.md hard rule: "Atomic writes only - tmp.write_text + tmp.replace.
Overlays poll mid-write." All writers under `data/` and root
`coaching_data.json` go through `atomic_write_json()` so an overlay
reading mid-write either sees the previous full file or the new full
file - never a torn one.

`set_pregame()` additionally holds the shared `core.coaching_data_lock`
because root `coaching_data.json` is also written by the SR coach
(`coach_integration._write_fields`) and the supervisor's aftergame
collector - without the lock, a concurrent R-M-W can clobber the
pregame field (NOTE-003 fix).

`force_vision_scan()` writes a sentinel that BaseCoach._vision_loop
polls - same effect as the Ctrl+Tab hotkey.
"""
from __future__ import annotations

import json
import time

from dashboard._context import APP_DIR, read_json


def atomic_write_json(rel: str, data: dict) -> None:
    # Lane 8 cycle 19: this was a bare `tmp.replace(p)`. On Windows os.replace
    # transiently raises PermissionError (WinError 5) while a reader holds the
    # destination open - and these files are POLLED BY DESIGN, so that
    # contention is routine, not exceptional. MEASURED on this machine: a plain
    # open(target, "r") by a reader was enough to raise it, leaving an orphan
    # .tmp behind. The operator-visible symptom is the dashboard Refresh button
    # returning 500 {"error":"command_failed"} and doing nothing.
    #
    # `core.polled_json` is the in-tree answer (bounded ~275 ms backoff, then
    # re-raise). Reused rather than re-rolled so the two backoff tables cannot
    # drift. SERIALIZATION stays here and is deliberately NOT delegated to
    # polled_json.atomic_write_json: that passes ensure_ascii=False, which
    # would change the bytes written for any non-ASCII coaching text.
    #
    # Lane 8 cycle 24: the tmp+rename itself now IS delegated, via
    # atomic_write_bytes. The hand-rolled version derived its scratch name from
    # the destination alone, so two writers of one file opened the same scratch
    # file - and coaching_data.json has a second writer in another process
    # (app/__init__.py:253). Bytes, not write_text, because write_text rewrites
    # LF as CRLF on Windows (reference_windows_write_text_crlf_byte_count).
    from core.polled_json import atomic_write_bytes
    body = json.dumps(data, indent=2)
    atomic_write_bytes(APP_DIR / rel, body.encode("utf-8"))


def set_pregame(text: str) -> None:
    """Write user-supplied text into root coaching_data.json.pregame field.
    Coach reads this on next poll cycle. Atomic write to avoid mid-read.
    Holds the shared coaching_data_lock so a coach R-M-W in another thread
    can't clobber this update (NOTE-003 fix)."""
    from core.coaching_data_lock import coaching_data_lock
    with coaching_data_lock():
        data = read_json("coaching_data.json")
        data["pregame"] = text
        atomic_write_json("coaching_data.json", data)


def force_vision_scan() -> None:
    """Trigger BaseCoach._vision_loop forced scan (matches Ctrl+Tab hotkey)."""
    atomic_write_json("data/force_scan.json", {"force": time.time()})
