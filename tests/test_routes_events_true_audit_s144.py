"""s144 true-audit of dashboard/routes_events.py (/api/events, RM-604).

Four findings, each pinned here (synthetic hubs only, no live game):
  F1  _parse_id fed int() anything str.isdigit() accepts: a superscript digit
      ("%C2%B2" -> U+00B2) or a run past the 4300-digit int limit raised
      ValueError out of the route, so the request got no response at all.
  F2  a ?since= that is present but not an id was silently ignored (and on the
      SSE path it was parsed only AFTER the 200 headers were on the wire). It
      now answers 400 before any header; a bad Last-Event-ID still reads as a
      fresh client (EventSource sends it on its own).
  F3  the JSON body read ``head`` and ``since()`` under two separate locks, so
      an event landing between them made ``head`` lag the events it carried;
      a poller resuming from ``head`` got those events twice.
  F4  a client that stops reading held its dispatcher thread and one of the 8
      subscriber slots forever (no write bound; the 600 s cap is checked only
      between writes). Writes are now bounded by _WRITE_STALL_S.
"""
from __future__ import annotations

import io
import json
import socket
import socketserver
import sys
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import live_event_hub as hub_mod  # noqa: E402
from dashboard import routes_events as rev  # noqa: E402

SUP2 = chr(0x00B2)   # SUPERSCRIPT TWO


class _H:
    def __init__(self, path="/api/events", headers=None, wfile=None, connection=None):
        self.path = path
        self.headers = dict({"Accept": "text/event-stream"} if headers is None else headers)
        self.wfile = io.BytesIO() if wfile is None else wfile
        self.connection = connection
        self.code = None
        self.sent = None

    def send_response(self, code):
        self.code = code

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)


def _hub(ring_max=1024, seed=1000):
    return hub_mod.LiveEventHub(ring_max=ring_max, id_seed=seed)


def _fill(h, n, kind="death", **extra):
    for _ in range(n):
        h._ring.append(dict({"kind": kind}, **extra))


def _serve(req, the_hub, duration=0.1):
    with mock.patch.object(rev, "_get_hub", return_value=the_hub), \
            mock.patch.object(rev, "_SSE_MAX_DURATION_S", duration), \
            mock.patch.object(rev, "_WAIT_SLICE_S", 0.02):
        rev._serve_events(req)


# -- F1: _parse_id never raises --------------------------------------------

def test_parse_id_rejects_non_ascii_digits_without_raising():
    assert SUP2.isdigit()                   # the trap: isdigit() says yes
    assert rev._parse_id(SUP2) is None
    assert rev._parse_id("1" + chr(0x0663)) is None  # ARABIC-INDIC DIGIT THREE


def test_parse_id_rejects_digit_runs_past_the_bound_without_raising():
    assert rev._parse_id("9" * 5000) is None
    assert rev._parse_id("9" * (rev._ID_MAX_DIGITS + 1)) is None
    assert rev._parse_id("9" * rev._ID_MAX_DIGITS) == int("9" * rev._ID_MAX_DIGITS)


def test_parse_id_keeps_plain_ids():
    assert rev._parse_id(" 1761234567890 ") == 1761234567890
    assert rev._parse_id("0") == 0
    for bad in ("", "-1", "+1", "1.5", "abc", None, 7):
        assert rev._parse_id(bad) is None


def test_superscript_last_event_id_reads_as_fresh_client():
    h = _hub()
    _fill(h, 2)
    req = _H(headers={"Accept": "text/event-stream", "Last-Event-ID": SUP2})
    _serve(req, h)
    assert req.code == 200
    assert b'"kind":"hello"' in req.wfile.getvalue()


# -- F2: a bad ?since= is a 400, answered before any header -----------------

def test_superscript_since_is_400_on_json_path():
    h = _hub()
    req = _H(path="/api/events?since=%C2%B2", headers={})
    _serve(req, h)
    assert req.sent is not None and req.sent[0] == 400
    assert json.loads(req.sent[1]) == {"error": "bad_since"}


def test_huge_since_is_400_on_sse_path_before_headers():
    h = _hub()
    req = _H(path="/api/events?since=" + "9" * 5000)
    with mock.patch.object(rev, "_sse_count", 0):
        _serve(req, h)
        assert rev._sse_count == 0           # no slot taken, none leaked
    assert req.code is None                  # no 200 status line went out
    assert req.sent[0] == 400
    assert req.wfile.getvalue() == b""


def test_non_numeric_since_is_400_not_silently_fresh():
    h = _hub()
    _fill(h, 3)
    req = _H(path="/api/events?since=abc", headers={})
    _serve(req, h)
    assert req.sent[0] == 400


def test_blank_since_still_falls_back_to_last_event_id():
    h = _hub()
    _fill(h, 3)                              # ids 1001..1003
    req = _H(path="/api/events?since=",
             headers={"Accept": "application/json", "Last-Event-ID": "1001"})
    _serve(req, h)
    body = json.loads(req.sent[1])
    assert req.sent[0] == 200
    assert [e["id"] for e in body["events"]] == [1002, 1003]


# -- F3: JSON head never lags the events it carries -------------------------

class _RacingHub(hub_mod.LiveEventHub):
    """Appends one event right after ``head`` is read, as observe() can."""

    def __init__(self):
        super().__init__(id_seed=1000)
        self._raced = False

    @property
    def head(self):
        h = self._ring.head
        if not self._raced:
            self._raced = True
            self._ring.append({"kind": "death"})
        return h


def test_json_head_matches_last_event_returned():
    h = _RacingHub()
    _fill(h, 2)                              # ids 1001..1002
    req = _H(path="/api/events?since=1000", headers={})
    _serve(req, h)
    body = json.loads(req.sent[1])
    ids = [e["id"] for e in body["events"]]
    assert ids[:2] == [1001, 1002]
    assert body["head"] == ids[-1]           # resume from head: no duplicates
    req2 = _H(path=f"/api/events?since={body['head']}", headers={})
    _serve(req2, h)
    ids2 = [e["id"] for e in json.loads(req2.sent[1])["events"]]
    assert not set(ids) & set(ids2)
    assert sorted(ids + ids2) == list(range(1001, h.head + 1))


class _LateRacingHub(hub_mod.LiveEventHub):
    """Appends one event right after ``since`` returns."""

    def __init__(self):
        super().__init__(id_seed=1000)
        self._raced = False

    def since(self, after):
        out = super().since(after)
        if not self._raced:
            self._raced = True
            self._ring.append({"kind": "death"})
        return out


def test_json_head_is_not_read_after_the_events_either():
    h = _LateRacingHub()
    _fill(h, 2)                              # ids 1001..1002, 1003 lands late
    req = _H(path="/api/events?since=1000", headers={})
    _serve(req, h)
    body = json.loads(req.sent[1])
    assert [e["id"] for e in body["events"]] == [1001, 1002]
    assert body["head"] == 1002              # a poller must still get 1003


def test_whitespace_since_is_400():
    req = _H(path="/api/events?since=%20", headers={})
    _serve(req, _hub())
    assert req.sent[0] == 400


def test_json_head_after_gap_is_gap_end_when_ring_empty():
    h = _hub(seed=5000)
    req = _H(path="/api/events?since=10", headers={})
    _serve(req, h)
    body = json.loads(req.sent[1])
    assert body["gap"] == {"kind": "gap", "from": 11, "to": 5000}
    assert body["head"] == 5000 and body["events"] == []


def test_json_head_when_nothing_new_is_the_resume_point():
    h = _hub()
    _fill(h, 2)
    req = _H(path="/api/events?since=1002", headers={})
    _serve(req, h)
    body = json.loads(req.sent[1])
    assert body == {"head": 1002, "events": [], "gap": None, "state": "/api/state"}


# -- F4: a stalled reader frees its slot ------------------------------------

def test_stalled_reader_releases_thread_and_slot():
    """Real socket pair, client never reads: the stream must end by itself."""
    srv, cli = socket.socketpair()
    try:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        cli.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        srv.settimeout(None)
        h = _hub(ring_max=64)
        req = _H(headers={"Accept": "text/event-stream", "Last-Event-ID": "1000"},
                 wfile=socketserver._SocketWriter(srv), connection=srv)
        done = threading.Event()

        def feed():
            # Measured: a Windows loopback pair takes ~2.7 MB in 64 KB sends
            # before one blocks, and a single huge send can complete whole,
            # so keep the stream writing small frames until it ends.
            while not done.is_set():
                with h._cond:
                    _fill(h, 4, champion="X" * 16000)
                    h._cond.notify_all()
                done.wait(0.002)

        threading.Thread(target=feed, daemon=True).start()

        def run():
            try:
                with mock.patch.object(rev, "_get_hub", return_value=h), \
                        mock.patch.object(rev, "_WRITE_STALL_S", 0.3, create=True):
                    rev._serve_events(req)
            finally:
                done.set()

        with mock.patch.object(rev, "_sse_count", 0):
            t = threading.Thread(target=run, daemon=True)
            t.start()
            finished = done.wait(10.0)
            if not finished:                 # unblock the writer, then fail
                cli.close()
                done.wait(5.0)
            assert finished, "stalled reader held the SSE thread"
            assert rev._sse_count == 0
        assert srv.gettimeout() is None      # prior timeout restored
    finally:
        for s in (srv, cli):
            try:
                s.close()
            except OSError:
                pass


def test_write_stall_arms_and_restores_the_socket_timeout():
    calls = []

    class Conn:
        def __init__(self):
            self.t = 7.0

        def gettimeout(self):
            return self.t

        def settimeout(self, v):
            calls.append(v)
            self.t = v

    conn = Conn()
    h = _hub()
    req = _H(connection=conn)
    _serve(req, h, duration=0.05)
    assert calls[0] == rev._WRITE_STALL_S
    assert conn.t == 7.0


def test_sse_without_a_socket_still_streams():
    h = _hub()
    _fill(h, 2)
    req = _H(headers={"Accept": "text/event-stream", "Last-Event-ID": "1000"})
    _serve(req, h)
    assert req.wfile.getvalue().count(b"data: ") == 2


# -- characterization: payload text cannot split an SSE frame ----------------

def test_newlines_in_event_fields_cannot_forge_frames():
    h = _hub()
    h._ring.append({"kind": "death", "champion": "Zed\n\ndata: {\"kind\":\"forged\"}\r\n"})
    req = _H(headers={"Accept": "text/event-stream", "Last-Event-ID": "1000"})
    _serve(req, h)
    blocks = [b for b in req.wfile.getvalue().decode().split("\n\n") if b.strip()]
    datas = [ln for b in blocks for ln in b.splitlines() if ln.startswith("data: ")]
    assert len(datas) == 1
    assert json.loads(datas[0][6:])["kind"] == "death"


def test_write_stall_outlasts_a_heartbeat_gap():
    assert rev._WRITE_STALL_S > rev.HEARTBEAT_S_DEFAULT
