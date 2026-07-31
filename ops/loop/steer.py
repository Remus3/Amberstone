#!/usr/bin/env python
r"""Steer channel - free-text guidance that reaches a running session.

WHY THIS IS A FILE AND NOT THE AHK BRIDGE. `docs/MISSION_CONTROL_PLAN.md`
specified the transport as "the existing AHK bridge writing
`control/_claude_in.txt`". Both halves are wrong, measured 2026-07-31:

  * `control/_claude_in.txt` is the ADJUDICATOR's stdin file
    (`ops/loop/adjudicator.py` ClaudeAdjudicator.ask) - nothing types it.
  * The bridge (`ops/loop/claude_gui_bridge.ahk`) polls `control/gemini.ready`,
    types it into the window named by `control/target_hwnd.txt`, and acks by
    DELETING the ready file. That is the loop controller's own directive
    channel; writing it from the dashboard would collide with a live directive.

And the decisive fact: the bridge was not running and `target_hwnd.txt` held
hwnd 66248, which `IsWindow` reports dead. A GUI transport needs a window. A
headless lane worker (`claude -p`, spawned detached by
`ops/loop/lane_launcher.py`) HAS no window, so the AHK path could never steer
the lanes S5 made real - the exact thing the steer channel is for.

TIERS, HONESTLY. The tier does not change the transport; it changes when the
consumer is expected to look and how it is told to act.

  NOTE   - lands at the next SAFE boundary (the done ritual, a lane step
           boundary). Nothing is interrupted. This is the DEFAULT.
  STEER  - lands at the next consumer poll, which for a cooperating consumer is
           a tool boundary. The turn adapts mid-flight; agents keep running.

Latency is the consumer's poll cadence, not magic. A consumer that only peeks
at its done ritual will see a STEER there and nowhere earlier, and this module
says so rather than implying an interrupt it cannot deliver. INTERRUPT is a
different act entirely - it stops a turn and kills agents - and is deliberately
NOT here (stage S9, operator sign-off).

APPEND-ONLY LOG PLUS A CURSOR. The log is never rewritten: consuming advances a
separate cursor file. A rewrite-on-consume would race two readers into losing
each other's entries, and it would destroy the record of what was said - which
is the only way to audit a steer after the fact.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
CONTROL_DIR = _HERE / "control"
STEER_LOG = CONTROL_DIR / "STEER.jsonl"
STEER_CURSOR = CONTROL_DIR / "STEER.cursor"

TIERS = ("note", "steer")
DEFAULT_TIER = "note"

# S9. INTERRUPT is an ACT, not guidance, and it is deliberately not in TIERS -
# `ops/loop/interrupt.py` owns it. It appears here only because the log is the
# single safety ledger and an interrupt has to be auditable beside the steers
# that preceded it.
#
# The distinction is load-bearing rather than tidy. `normalize_tier` maps every
# unrecognised tier to the default, which was the SAFE answer while INTERRUPT
# existed only as a 400 at the route: an unknown tier degraded to a note that
# executes nothing. Once S9 made INTERRUPT real, that same degrade became the
# hazard - a caller asking to stop the agents would get a note, and the UI
# would report an interrupt that never happened. `append` therefore REFUSES an
# audit-only tier instead of degrading it, and `record` is the only door in.
AUDIT_ONLY_TIERS = ("interrupt",)
LOG_TIERS = TIERS + AUDIT_ONLY_TIERS

# A steer is guidance, not a payload. The cap is generous for a sentence or two
# and small enough that a stray POST cannot grow the log without bound.
MAX_TEXT = 2000

# The named mutex serialises appends across processes. slots.py / winmutex.py
# are BYTE-IDENTICAL-BY-CONTRACT with the Sibling-A copy - CONSUMED here,
# never edited and never re-implemented.
_MUTEX_NAME = "RC-SteerLog"
_MUTEX_TIMEOUT_S = 5.0


def _bind(modname: str, filename: str):
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, _HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


winmutex = _bind("rc_loop_winmutex", "winmutex.py")


def _awrite(path: Path, data: bytes) -> None:
    """Atomic write. Bytes, not text - `write_text` rewrites LF as CRLF on
    Windows and every byte count downstream then lies (measured, S3)."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def normalize_tier(tier) -> str:
    t = str(tier or DEFAULT_TIER).strip().lower()
    return t if t in TIERS else DEFAULT_TIER


def append(text, *, tier=DEFAULT_TIER, key=None, source="dashboard") -> dict:
    """Append one GUIDANCE steer (note / steer). Returns the stored record.

    Raises ValueError on empty text - a blank steer is a mis-click, and storing
    it would make the next consumer act on nothing - and on an audit-only tier,
    which must never be silently demoted to a note (see AUDIT_ONLY_TIERS).
    """
    if str(tier or "").strip().lower() in AUDIT_ONLY_TIERS:
        raise ValueError(
            f"tier {tier!r} is an act, not guidance - use ops/loop/interrupt.py; "
            "this channel executes nothing and must not claim otherwise")
    return record(text, tier=normalize_tier(tier), key=key, source=source)


def record(text, *, tier=DEFAULT_TIER, key=None, source="dashboard") -> dict:
    """Append any LOG_TIERS entry, including audit-only ones. Returns the record.

    The low-level door. `append` is the guidance-only face of it; the interrupt
    module calls this directly so its act lands in the same ledger.
    """
    body = str(text or "").strip()
    if not body:
        raise ValueError("steer text is empty")
    body = body[:MAX_TEXT]
    tier = str(tier or DEFAULT_TIER).strip().lower()
    if tier not in LOG_TIERS:
        tier = DEFAULT_TIER
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "id": None,                       # filled under the mutex
        "tier": tier,
        "text": body,
        "key": (None if key is None else str(key)),
        "source": str(source),
        "ts": time.time(),
    }
    # timeout is KEYWORD-ONLY in winmutex.hold - positional would TypeError.
    with winmutex.hold(_MUTEX_NAME, timeout=_MUTEX_TIMEOUT_S):
        rec["id"] = _next_id()
        line = (json.dumps(rec, ensure_ascii=True) + "\n").encode("utf-8")
        with open(STEER_LOG, "ab") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    return rec


def _read_all() -> list:
    """Every record in the log. A malformed line is SKIPPED, never fatal - a
    half-written tail must not make the whole channel unreadable."""
    try:
        raw = STEER_LOG.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("id") is not None:
            out.append(rec)
    return out


def _next_id() -> int:
    recs = _read_all()
    return (max((int(r["id"]) for r in recs), default=0)) + 1


def cursor() -> int:
    """The highest id already consumed. 0 when nothing has been."""
    try:
        return int(STEER_CURSOR.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _unconsumed() -> list:
    """Every record past the cursor, ANY tier. The raw window."""
    at = cursor()
    return [r for r in _read_all() if int(r.get("id", 0)) > at]


def pending(tier=None) -> list:
    """Unconsumed GUIDANCE, oldest first. NEVER writes - this is the poll path.

    Audit-only tiers are excluded. An INTERRUPT record shares this log so a
    mis-fire is auditable, but it is a record of something that already
    happened, not a work item - and the two consumers of `pending` both treat
    what they get as work. Found by the /done ritual draining a session's own
    INTERRUPT rows as though the operator had sent them, and by the dashboard
    badge (fed by `summary`) claiming guidance was waiting under a sub-head
    that reads "STEER - GUIDANCE, NEVER AN INTERRUPT".

    `tier` narrows further, so a consumer that only honours NOTE at a safe
    boundary can ask for exactly that.
    """
    want = None if tier is None else normalize_tier(tier)
    return [r for r in _unconsumed()
            if r.get("tier") not in AUDIT_ONLY_TIERS
            and (want is None or r.get("tier") == want)]


def audit_trail(limit=None) -> list:
    """The whole ledger, every tier, ignoring the cursor. Read-only.

    The counterpart to `pending`: filtering audit rows out of the WORK path
    must not hide them from the RECORD, since the ledger is the only way to
    audit a mis-fire after the fact.
    """
    rows = _read_all()
    return rows if not limit else rows[-int(limit):]


def drain() -> list:
    """Return pending GUIDANCE and advance the cursor past everything read.

    Two separate things, deliberately. The cursor advances past audit rows too
    even though they are not returned: it is a consumption cursor, and if it
    stalled behind an INTERRUPT record every later drain would re-walk it and
    the dashboard badge would climb without bound.

    It moves to the highest id in the window this call READ, so an entry
    appended between the read and the write is not skipped - it simply stays
    pending for the next drain. Advancing to `_next_id()` would swallow it.
    """
    window = _unconsumed()
    if not window:
        return []
    highest = max(int(r["id"]) for r in window)
    _awrite(STEER_CURSOR, f"{highest}\n".encode("ascii"))
    return [r for r in window if r.get("tier") not in AUDIT_ONLY_TIERS]


def summary() -> dict:
    """Counts for the dashboard. Read-only. Guidance only - see `pending`."""
    items = pending()
    return {
        "pending": len(items),
        "note": sum(1 for r in items if r.get("tier") == "note"),
        "steer": sum(1 for r in items if r.get("tier") == "steer"),
        "newest": (items[-1]["text"][:120] if items else None),
        "cursor": cursor(),
    }
