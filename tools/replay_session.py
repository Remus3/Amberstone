"""
tools/replay_session.py - RM-605 / X-05 (external reference F, clean-room).

Serves a session recorded by core/live_session_recorder.py back over HTTP so
UI work, fixture building and PGR development can run without a live game.

    python tools/replay_session.py logs/sessions/<gameId>.jsonl \
        [--speed 1.0] [--from SECONDS] [--hold] [--port 8897]

Routes (127.0.0.1 ONLY - there is deliberately no --host option):
  GET /api/state                    latest frame envelope: {captured_at,
                                    recorded_captured_at, replay: true,
                                    game_time, snapshot, vision_state?, header}
  GET /liveclientdata/allgamedata   the raw recorded :2999 snapshot; the body
                                    mirrors the live endpoint byte-for-byte, so
                                    it carries NO replay field - the marker is
                                    the response header X-RC-Replay: 1 (sent on
                                    every route)
  GET /api/events[?since=<id>]      ONLY when an event source is plugged in
                                    (core/live_event_deriver.py, X-04, if
                                    present); otherwise the route is absent
                                    (404). Events carry monotonic ids over a
                                    bounded ring.

Pacing: frame i is published at  anchor + (t_i - t_from) / speed  where
``anchor`` is read ONCE before the first frame. Every deadline is computed
from that fixed anchor, so an oversleep on one frame is absorbed by the next
wait and sleep jitter never accumulates. A frame that is already late is
published immediately (no sleep). ``captured_at`` is re-stamped with the wall
clock at publish; the original is kept as ``recorded_captured_at``.

--from SECONDS skips to that offset on the RECORDING timeline (captured_at
relative to the first frame). --hold keeps serving the last frame after the
end instead of exiting.

Replay output is NOT live evidence. A replay NEVER closes a live-gated row
(docs/LIVE_GAME_GATED_SYNC.md): every response carries the header
``X-RC-Replay: 1``, the /api/state and /api/events bodies also carry
``replay: true``, and any gated row still needs a real live game. Recordings name other players and
live under gitignored logs/; never commit one.
"""
from __future__ import annotations

import argparse
import collections
import importlib
import json
import math
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.live_session_recorder import (  # noqa: E402
    SessionFormatError,
    read_session,
)

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8897  # our choice; no other RC listener used it (repo grep at time of writing)
EVENT_RING_MAX = 1024  # our choice; bounded so a long replay cannot grow memory
_EVENTS_MODULE = "core.live_event_deriver"
_EVENTS_FUNC = "derive_events"

EventsSource = Callable[[Optional[dict], dict], List[dict]]


# -- timeline / pacing ------------------------------------------------------

def timeline(frames: Sequence[dict], from_s: float = 0.0) -> List[Tuple[float, dict]]:
    """[(offset_s, frame)] rebased so the first kept frame is at 0.0."""
    out: List[Tuple[float, dict]] = []
    if not frames:
        return out
    t0 = float(frames[0].get("captured_at") or 0.0)
    for f in frames:
        rel = float(f.get("captured_at") or t0) - t0
        if rel + 1e-9 >= from_s:
            out.append((rel - from_s, f))
    if out:
        base = out[0][0]
        out = [(rel - base, f) for rel, f in out]
    return out


def play(tl: Sequence[Tuple[float, dict]], speed: float,
         publish: Callable[[dict], Any],
         clock: Callable[[], float] = time.monotonic,
         sleep: Callable[[float], Any] = time.sleep) -> None:
    """Publish each frame at anchor + offset/speed from a FIXED anchor."""
    if not isinstance(speed, (int, float)) or not math.isfinite(speed) or speed <= 0:
        raise ValueError("speed must be a finite number > 0")
    anchor = clock()
    for rel, frame in tl:
        wait = anchor + rel / speed - clock()
        if wait > 0:
            sleep(wait)
        publish(frame)


def restamp(frame: dict, now: float) -> dict:
    out = dict(frame)
    out["recorded_captured_at"] = frame.get("captured_at")
    out["captured_at"] = now
    out["replay"] = True
    return out


# -- state ------------------------------------------------------------------

class ReplayState:
    """Latest published frame plus an optional bounded event ring."""

    def __init__(self, header: dict, wall_clock: Callable[[], float] = time.time,
                 events_source: Optional[EventsSource] = None) -> None:
        self._header = dict(header or {})
        self._wall = wall_clock
        self._events_source = events_source
        self._lock = threading.Lock()
        self._payload: Optional[dict] = None
        self._prev_frame: Optional[dict] = None
        self._events: "collections.deque[dict]" = collections.deque(maxlen=EVENT_RING_MAX)
        self._next_id = 1

    def publish(self, frame: dict) -> None:
        payload = restamp(frame, self._wall())
        payload.pop("kind", None)
        payload["header"] = self._header
        new_events: List[dict] = []
        if self._events_source is not None:
            try:
                new_events = list(self._events_source(self._prev_frame, frame) or [])
            except Exception:  # noqa: BLE001
                new_events = []
        with self._lock:
            self._payload = payload
            self._prev_frame = frame
            for ev in new_events:
                if isinstance(ev, dict):
                    self._events.append(dict(ev, id=self._next_id))
                    self._next_id += 1

    def payload(self) -> Optional[dict]:
        with self._lock:
            return self._payload

    def events_since(self, since: int) -> List[dict]:
        with self._lock:
            return [e for e in self._events if e["id"] > since]


def discover_events_source() -> Optional[EventsSource]:
    """X-04's deriver if this tree has it; None (route absent) otherwise."""
    try:
        mod = importlib.import_module(_EVENTS_MODULE)
    except Exception:  # noqa: BLE001
        return None
    fn = getattr(mod, _EVENTS_FUNC, None)
    return fn if callable(fn) else None


# -- HTTP -------------------------------------------------------------------

class _CappedStartEvent(threading.Event):
    """``Thread._started`` with a ceiling on the wait ``Thread.start()`` makes."""

    def __init__(self, cap_s: float) -> None:
        super().__init__()
        self._cap_s = cap_s

    def wait(self, timeout: Optional[float] = None) -> bool:
        if timeout is None or timeout > self._cap_s:
            timeout = self._cap_s
        return super().wait(timeout)


class _RequestThread(threading.Thread):
    """RM-738: a per-request thread whose ``start()`` cannot park the accept loop.

    ``Thread.start()`` waits on ``self._started`` with no timeout, and only the
    NEW thread sets it (``_bootstrap_inner``, after ``_set_native_id``). A
    thread that dies in bootstrap - MemoryError under commit-charge
    exhaustion, RM-735 / RM-737 - would park ``serve_forever`` for good. Here
    that wait is capped; a thread not started by then is abandoned and the
    server drops the connection. One that starts late sees the abandon in
    ``run()`` and returns without touching the dropped socket.
    """

    def __init__(self, server: "_ReplayHTTPServer", request: Any, client_address: Any) -> None:
        super().__init__(daemon=server.daemon_threads)
        self._started = _CappedStartEvent(server.thread_start_timeout_s)
        self._job: Optional[tuple] = (server, request, client_address)
        self._gate = threading.Lock()
        self._outcome: Optional[str] = None     # "claimed" | "abandoned"

    def run(self) -> None:
        with self._gate:
            if self._outcome is not None:
                return
            self._outcome = "claimed"
            job, self._job = self._job, None
        server, request, client_address = job
        server.process_request_thread(request, client_address)

    def abandon_if_unstarted(self) -> bool:
        if self._started.is_set():
            return False
        with self._gate:
            if self._outcome is not None:
                return False
            self._outcome = "abandoned"
            self._job = None
            return True


class _ReplayHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer whose per-request thread start is capped (RM-738)."""

    # A thread start normally takes well under a millisecond. RM-740 (d),
    # measured 2026-10-14 under a gated -n 8 suite: max 25 ms, 157 ms with a
    # GIL-busy thread in the process; 2.0 s (~13x) is KEPT - a larger cap
    # only parks the accept loop longer behind a start that truly died.
    # tests/test_rm740d_thread_start_caps.py pins both.
    thread_start_timeout_s = 2.0
    thread_start_failures = 0

    def process_request(self, request: Any, client_address: Any) -> None:
        # ThreadingMixIn.process_request with a capped start. The stdlib's
        # _threads bookkeeping is not carried: it never holds daemon threads.
        t = _RequestThread(self, request, client_address)
        start_error: Optional[Exception] = None
        try:
            t.start()
        except Exception as exc:  # noqa: BLE001 - e.g. "can't start new thread"
            # RM-740 (b): a start that raises is a failed start too - dropped,
            # counted and logged here, never left to escape to handle_error.
            # No traceback kept: it would pin this frame (and the request).
            # abandon_if_unstarted() still arbitrates: a thread that did
            # come up before the raise owns its request.
            start_error = exc.with_traceback(None)
        if not t.abandon_if_unstarted():
            return
        # Count and log BEFORE the close (the dashboard's order), so a client
        # that has seen its connection dropped can rely on both.
        self.thread_start_failures += 1
        try:
            if self.thread_start_failures == 1 or self.thread_start_failures % 100 == 0:
                why = (f"did not start within {self.thread_start_timeout_s:.1f}s"
                       if start_error is None else f"start raised {start_error!r}")
                print(f"replay_session: request thread {why} - dropped connection "
                      f"#{self.thread_start_failures} (RM-738)", file=sys.stderr)
        except Exception:  # noqa: BLE001 - stderr can be absent or failing too
            pass
        self.shutdown_request(request)


def make_server(state: ReplayState, port: int = DEFAULT_PORT, host: str = LOOPBACK,
                events_source: Optional[EventsSource] = None) -> ThreadingHTTPServer:
    if host != LOOPBACK:
        raise ValueError(f"replay binds 127.0.0.1 only, refused {host!r}")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            return

        def _json(self, code: int, obj: Any) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            # Every replay response is marked at the HTTP layer, including the
            # raw allgamedata mirror whose body must stay byte-identical.
            self.send_header("X-RC-Replay", "1")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            parts = urlsplit(self.path)
            p = parts.path
            if p == "/api/state":
                payload = state.payload()
                if payload is None:
                    return self._json(404, {"error": "no_frame_yet", "replay": True})
                return self._json(200, payload)
            if p == "/liveclientdata/allgamedata":
                payload = state.payload()
                if payload is None:
                    return self._json(404, {"error": "no_frame_yet"})
                return self._json(200, payload.get("snapshot"))
            if p == "/api/events" and events_source is not None:
                try:
                    since = int((parse_qs(parts.query).get("since") or ["0"])[0])
                except ValueError:
                    since = 0
                return self._json(200, {"events": state.events_since(since), "replay": True})
            return self._json(404, {"error": "not_found"})

    return _ReplayHTTPServer((LOOPBACK, port), Handler)


# -- CLI --------------------------------------------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Replay a recorded RC live session over HTTP.")
    ap.add_argument("session", type=Path)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--from", dest="from_s", type=float, default=0.0,
                    help="start offset in seconds on the recording timeline")
    ap.add_argument("--hold", action="store_true",
                    help="keep serving the last frame after the end")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    return ap.parse_args(argv)


def _wait_forever() -> None:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def run(args: argparse.Namespace, *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = time.sleep,
        hold_wait: Callable[[], Any] = _wait_forever,
        serve: bool = True) -> int:
    try:
        header, frames = read_session(args.session)
    except (OSError, SessionFormatError) as exc:
        print(f"replay_session: {exc}", file=sys.stderr)
        return 2
    events_source = discover_events_source()
    state = ReplayState(header, events_source=events_source)
    server = None
    if serve:
        # RM-761c: a held port is a one-line message and exit 2, not a
        # raw OSError traceback.
        try:
            server = make_server(state, port=args.port, events_source=events_source)
        except OSError as exc:
            print(f"replay_session: cannot bind {LOOPBACK}:{args.port}: {exc}",
                  file=sys.stderr)
            return 2
        threading.Thread(target=server.serve_forever, daemon=True,
                         name="replay-http").start()
        ev_state = "on" if events_source else "absent"
        print(f"replay_session: serving {len(frames)} frames on "
              f"http://{LOOPBACK}:{server.server_address[1]} (events: {ev_state})")
    try:
        play(timeline(frames, args.from_s), args.speed, state.publish,
             clock=clock, sleep=sleep)
        if args.hold:
            hold_wait()
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except ValueError as exc:
        print(f"replay_session: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
