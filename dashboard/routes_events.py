# arch: /api/events resumable SSE over the live event ring | section=dashboard | frozen=no
"""/api/events - RM-604 / X-04 (external reference F, clean-room).

Discrete live events (core/live_event_deriver.py kinds) over SSE, with
resume. Sits beside /api/state-stream (dashboard/routes_state.py), which keeps
pushing the WHOLE state on change; this channel pushes only transitions.

Request
  ``?since=<id>`` wins; else the ``Last-Event-ID`` header (EventSource sends
  it on auto-reconnect); else a FRESH client: it gets one ``hello`` message
  carrying the current head and no backlog. First knowledge is state, so a
  late joiner reads /api/state and then follows events from that head.
  An id is 1.._ID_MAX_DIGITS ASCII digits. A ``?since=`` that is present but
  not an id answers 400 ``{"error": "bad_since"}`` before any header (the
  caller asked for something specific; s144 true-audit). A bad
  ``Last-Event-ID`` reads as a fresh client: EventSource sends that header on
  its own, and a 400 would end its reconnects for good.

SSE wire (no ``event:`` lines, so EventSource.onmessage sees everything; the
kind is in the JSON):
  ``id: N`` + ``data: {..., "id": N, "kind": ...}``   one per event
  ``id: B`` + ``data: {"kind": "gap", "from": A, "to": B}``  ids A..B fell
        off the back of the bounded ring; re-read /api/state
  ``id: H`` + ``data: {"kind": "hello", "head": H, "state": "/api/state"}``
  ``: hb``  comment after HEARTBEAT_S_DEFAULT idle seconds (ignored by
        EventSource; drops a dead connection)

Non-SSE GET (no ``text/event-stream`` in Accept): one JSON body
``{"head", "events", "gap", "state"}`` with the same since/Last-Event-ID
rules, for pollers and late joiners. ``head`` comes from the same ring read
as ``events`` (the last event, else the gap end, else the resume point), so
resuming from it never repeats or skips an event.

Read-only GET, same exposure as /api/state and /api/state-stream (no token
gate on GETs; dashboard/_handler.py gates control POSTs only). Connection
lifetime and subscriber caps mirror the state stream. Every stream write is
bounded by _WRITE_STALL_S on the socket, so a client that stops reading
frees its thread and its subscriber slot instead of holding them forever
(the lifetime cap is only checked between writes).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from core import live_event_hub

log = logging.getLogger("rc.routes_events")

HEARTBEAT_S_DEFAULT = 15.0
_HEARTBEAT_S = HEARTBEAT_S_DEFAULT   # max idle gap before a heartbeat comment
_SSE_MAX_DURATION_S = 600.0          # same cap as /api/state-stream
_SSE_MAX_SUBSCRIBERS = 8             # same cap as /api/state-stream
_WAIT_SLICE_S = 1.0                  # our choice; bounds shutdown latency
_WRITE_STALL_S = 60.0                # same bound as /api/recordings body writes
_ID_MAX_DIGITS = 20                  # ids are ms-seeded (13 digits); int() caps at 4300
_sse_count = 0
_sse_count_lock = threading.Lock()


def _get_hub() -> live_event_hub.LiveEventHub:
    live_event_hub.ensure_installed()
    return live_event_hub.get_hub()


class _BadSinceError(ValueError):
    """?since= is present but not an id."""


def _parse_id(raw: object) -> Optional[int]:
    """1.._ID_MAX_DIGITS ASCII digits, else None. Never raises.

    ``str.isdigit`` alone is not enough: it accepts superscripts (U+00B2),
    which int() rejects, and int() also refuses runs past 4300 digits.
    """
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not (0 < len(raw) <= _ID_MAX_DIGITS and raw.isascii() and raw.isdigit()):
        return None
    return int(raw)


def _resume_from(h) -> Optional[int]:
    """?since= wins over Last-Event-ID; None means a fresh client.

    Raises _BadSinceError for a ?since= that is present but not an id (an empty
    ``?since=`` is absent: parse_qs drops it; whitespace-only is not an id).
    """
    q = parse_qs(urlsplit(getattr(h, "path", "") or "").query)
    raw = (q.get("since") or [None])[0]
    if raw is not None:
        since = _parse_id(raw)
        if since is None:
            raise _BadSinceError(raw[:32])
        return since
    headers = getattr(h, "headers", None)
    try:
        return _parse_id(headers.get("Last-Event-ID") if headers is not None else None)
    except Exception:  # noqa: BLE001
        return None


def _wants_sse(h) -> bool:
    headers = getattr(h, "headers", None)
    try:
        accept = (headers.get("Accept") if headers is not None else "") or ""
    except Exception:  # noqa: BLE001
        accept = ""
    return "text/event-stream" in accept


def _frame(mid: Optional[int], obj: dict) -> bytes:
    head = f"id: {mid}\n" if mid is not None else ""
    return (head + "data: " + json.dumps(obj, separators=(",", ":")) + "\n\n").encode("utf-8")


def _serve_json(h, hub, after: Optional[int]) -> None:
    if after is None:
        head, gap, evs = hub.head, None, []
    else:
        # head comes from the SAME ring read as the events: hub.head takes
        # the lock separately, and an event landing between the two reads
        # made head lag the events returned (s144 true-audit F3).
        gap, evs = hub.since(after)
        head = evs[-1]["id"] if evs else (gap["to"] if gap is not None else after)
    body = {"head": head, "events": evs, "gap": gap, "state": "/api/state"}
    h._send(200, json.dumps(body).encode("utf-8"), "application/json")


def _arm_write_stall(h):
    """Bound every socket write by _WRITE_STALL_S. Returns (sock, prior) to
    restore, or None when the handler has no settable socket (tests)."""
    sock = getattr(h, "connection", None)
    if not callable(getattr(sock, "settimeout", None)):
        return None
    try:
        prior = sock.gettimeout()
        sock.settimeout(_WRITE_STALL_S)
    except OSError:
        return None
    return sock, prior


def _restore_timeout(armed) -> None:
    if armed is None:
        return
    sock, prior = armed
    try:
        sock.settimeout(prior)
    except OSError:
        pass


def _serve_events(h) -> None:
    global _sse_count
    try:
        hub = _get_hub()
    except Exception as exc:  # noqa: BLE001
        log.warning("api/events hub: %s", exc)
        h._send(500, b'{"error":"events_unavailable"}', "application/json")
        return
    try:
        after = _resume_from(h)
    except _BadSinceError:
        h._send(400, b'{"error":"bad_since"}', "application/json")
        return
    if not _wants_sse(h):
        _serve_json(h, hub, after)
        return
    with _sse_count_lock:
        if _sse_count >= _SSE_MAX_SUBSCRIBERS:
            h._send(503, b'{"error":"too_many_subscribers"}', "application/json")
            return
        _sse_count += 1
    armed = None
    try:
        armed = _arm_write_stall(h)
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-store")
        h.send_header("Connection", "close")
        h.send_header("X-Accel-Buffering", "no")
        h.end_headers()
        try:
            h.wfile.write(b"retry: 2000\n\n")
            if after is None:
                after = hub.head
                h.wfile.write(_frame(after, {"kind": "hello", "head": after,
                                             "state": "/api/state"}))
            h.wfile.flush()
        except (OSError, ConnectionError):
            return
        start = time.monotonic()
        last_write = start
        while time.monotonic() - start < _SSE_MAX_DURATION_S:
            gap, evs = hub.since(after)
            chunks = []
            if gap is not None:
                chunks.append(_frame(gap["to"], gap))
                after = gap["to"]
            for ev in evs:
                chunks.append(_frame(ev["id"], ev))
                after = ev["id"]
            now = time.monotonic()
            if not chunks and now - last_write >= _HEARTBEAT_S:
                chunks.append(b": hb\n\n")
            if chunks:
                try:
                    h.wfile.write(b"".join(chunks))
                    h.wfile.flush()
                except (OSError, ConnectionError):
                    return
                last_write = now
            remaining = _SSE_MAX_DURATION_S - (time.monotonic() - start)
            if remaining <= 0:
                break
            hub.wait(after, min(_WAIT_SLICE_S, _HEARTBEAT_S, remaining))
    finally:
        _restore_timeout(armed)
        with _sse_count_lock:
            _sse_count -= 1
