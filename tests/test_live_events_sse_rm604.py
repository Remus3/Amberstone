"""RM-604 / X-04 (external reference F, clean-room): /api/events channel.

Bounded ring with monotonic ids, resume via ?since= (wins) or Last-Event-ID,
a `gap` message for a client that fell off the back, a heartbeat, a JSON GET
mode for late joiners, and the RM-605 replay server auto-serving events once
the deriver exists. Synthetic fixtures only.
"""
from __future__ import annotations

import io
import json
import sys
import threading
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import live_event_deriver as led  # noqa: E402
from core import live_event_hub as hub_mod  # noqa: E402
from dashboard import routes_events as rev  # noqa: E402

LEG = frozenset({"3031"})


def _snap(t, zed_dead=False, lux_level=3):
    return {
        "activePlayer": {"summonerName": "SynthLux#T1"},
        "allPlayers": [
            {"championName": "Lux", "summonerName": "SynthLux#T1", "team": "ORDER",
             "isDead": False, "level": lux_level, "items": []},
            {"championName": "Zed", "summonerName": "SynthZed#T2", "team": "CHAOS",
             "isDead": zed_dead, "level": 4, "items": []},
        ],
        "gameData": {"gameMode": "CLASSIC", "gameTime": t},
        "events": {"Events": []},
    }


def _hub(ring_max=1024, seed=1000):
    return hub_mod.LiveEventHub(ring_max=ring_max, id_seed=seed,
                                completed_ids=lambda: LEG)


def _feed_deaths(h, n, t0=100.0):
    """Alternate Zed dead/alive so each step after the first emits one event."""
    h.observe(_snap(t0))
    for i in range(n):
        h.observe(_snap(t0 + 1 + i, zed_dead=(i % 2 == 0)))


# -- ring -------------------------------------------------------------------

def test_ring_ids_monotonic_and_since_returns_only_newer():
    r = hub_mod.EventRing(maxlen=8, id_seed=10)
    ids = [r.append({"kind": "death"}) for _ in range(3)]
    assert ids == [11, 12, 13]
    gap, evs = r.since(11)
    assert gap is None
    assert [e["id"] for e in evs] == [12, 13]


def test_ring_is_bounded_and_overflow_yields_gap():
    r = hub_mod.EventRing(maxlen=4, id_seed=0)
    for _ in range(10):
        r.append({"kind": "death"})
    assert len(r) == 4
    gap, evs = r.since(2)
    assert gap == {"kind": "gap", "from": 3, "to": 6}
    assert [e["id"] for e in evs] == [7, 8, 9, 10]
    gap2, evs2 = r.since(6)          # exactly at the edge: nothing missed
    assert gap2 is None and [e["id"] for e in evs2] == [7, 8, 9, 10]


def test_ring_default_capacity_is_bounded_1024():
    assert hub_mod.RING_MAX == 1024
    r = hub_mod.EventRing()
    for _ in range(1500):
        r.append({"kind": "x"})
    assert len(r) == 1024


def test_ring_client_ahead_of_head_gets_resync_gap():
    r = hub_mod.EventRing(maxlen=4, id_seed=100)
    r.append({"kind": "x"})
    gap, evs = r.since(500)
    assert gap == {"kind": "gap", "from": 101, "to": 101}
    assert evs == []


# -- hub --------------------------------------------------------------------

def test_hub_first_snapshot_emits_nothing():
    h = _hub()
    assert h.observe(_snap(100.0, zed_dead=True)) == []
    assert h.head == 1000


def test_hub_none_reading_reprimes_without_events():
    h = _hub()
    h.observe(_snap(100.0))
    h.observe(None)
    assert h.observe(_snap(102.0, zed_dead=True)) == []
    assert h.head == 1000


def test_hub_assigns_ids_to_derived_events():
    h = _hub()
    _feed_deaths(h, 3)
    gap, evs = h.since(1000)
    assert gap is None
    assert [e["id"] for e in evs] == [1001, 1002, 1003]
    assert [e["kind"] for e in evs] == ["death", "respawn", "death"]


def test_listener_resets_on_no_game_snapshot():
    h = _hub()

    class S:
        def __init__(self, data):
            self.data = data
            self.no_game = data is None

    with mock.patch.object(hub_mod, "_HUB", h):
        hub_mod.on_liveclient_snapshot(S(_snap(100.0)))
        hub_mod.on_liveclient_snapshot(S(None))
        hub_mod.on_liveclient_snapshot(S(_snap(101.0, zed_dead=True)))
    assert h.head == 1000


# -- SSE route --------------------------------------------------------------

class _H:
    def __init__(self, path="/api/events", headers=None):
        self.path = path
        self.headers = dict({"Accept": "text/event-stream"} if headers is None else headers)
        self.wfile = io.BytesIO()
        self.connection = None
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


def _run_sse(h, the_hub, duration=0.15, heartbeat=15.0):
    with mock.patch.object(rev, "_get_hub", return_value=the_hub), \
            mock.patch.object(rev, "_SSE_MAX_DURATION_S", duration), \
            mock.patch.object(rev, "_HEARTBEAT_S", heartbeat), \
            mock.patch.object(rev, "_WAIT_SLICE_S", 0.02):
        rev._serve_events(h)
    return h.wfile.getvalue().decode("utf-8")


def _messages(text):
    out = []
    for block in text.split("\n\n"):
        mid, data = None, None
        for line in block.splitlines():
            if line.startswith("id: "):
                mid = int(line[4:])
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if data is not None:
            out.append((mid, data))
    return out


def test_reconnect_with_last_event_id_receives_only_missed_events():
    h = _hub()
    _feed_deaths(h, 5)                       # ids 1001..1005
    req = _H(headers={"Accept": "text/event-stream", "Last-Event-ID": "1003"})
    msgs = _messages(_run_sse(req, h))
    assert [m[0] for m in msgs] == [1004, 1005]
    assert all(m[1]["id"] == m[0] for m in msgs)
    assert [m[1]["kind"] for m in msgs] == ["respawn", "death"]


def test_since_query_wins_over_last_event_id():
    h = _hub()
    _feed_deaths(h, 5)
    req = _H(path="/api/events?since=1001",
             headers={"Accept": "text/event-stream", "Last-Event-ID": "1004"})
    msgs = _messages(_run_sse(req, h))
    assert [m[0] for m in msgs] == [1002, 1003, 1004, 1005]


def test_client_fallen_off_the_back_gets_gap_then_ring():
    h = _hub(ring_max=3)
    _feed_deaths(h, 8)                       # ids 1001..1008, ring keeps 1006..1008
    req = _H(headers={"Accept": "text/event-stream", "Last-Event-ID": "1002"})
    msgs = _messages(_run_sse(req, h))
    assert msgs[0][1] == {"kind": "gap", "from": 1003, "to": 1005}
    assert msgs[0][0] == 1005                # resume point moves past the gap
    assert [m[0] for m in msgs[1:]] == [1006, 1007, 1008]


def test_fresh_client_gets_hello_at_head_and_no_backlog():
    h = _hub()
    _feed_deaths(h, 4)
    msgs = _messages(_run_sse(_H(), h))
    assert msgs == [(1004, {"kind": "hello", "head": 1004, "state": "/api/state"})]


def test_live_events_stream_to_connected_client():
    h = _hub()
    h.observe(_snap(100.0))
    req = _H(headers={"Accept": "text/event-stream", "Last-Event-ID": "1000"})

    def later():
        h.observe(_snap(101.0, zed_dead=True))
    t = threading.Timer(0.05, later)
    t.start()
    msgs = _messages(_run_sse(req, h, duration=0.4))
    t.join()
    assert [(m[0], m[1]["kind"]) for m in msgs] == [(1001, "death")]


def test_heartbeat_comment_when_idle():
    h = _hub()
    h.observe(_snap(100.0))
    req = _H(headers={"Accept": "text/event-stream", "Last-Event-ID": "1000"})
    text = _run_sse(req, h, duration=0.3, heartbeat=0.05)
    assert ": hb" in text
    assert _messages(text) == []
    assert rev.HEARTBEAT_S_DEFAULT == 15.0


def test_bad_last_event_id_is_treated_as_fresh():
    h = _hub()
    _feed_deaths(h, 2)
    req = _H(headers={"Accept": "text/event-stream", "Last-Event-ID": "abc"})
    msgs = _messages(_run_sse(req, h))
    assert msgs[0][1]["kind"] == "hello"


def test_json_get_for_late_joiners_and_polling():
    h = _hub()
    _feed_deaths(h, 3)
    req = _H(headers={"Accept": "application/json"})
    with mock.patch.object(rev, "_get_hub", return_value=h):
        rev._serve_events(req)
    status, body, ctype = req.sent
    assert status == 200 and ctype == "application/json"
    obj = json.loads(body)
    assert obj == {"head": 1003, "events": [], "gap": None, "state": "/api/state"}
    req2 = _H(path="/api/events?since=1001", headers={})
    with mock.patch.object(rev, "_get_hub", return_value=h):
        rev._serve_events(req2)
    obj2 = json.loads(req2.sent[1])
    assert [e["id"] for e in obj2["events"]] == [1002, 1003]
    assert obj2["head"] == 1003


def test_subscriber_cap_returns_503():
    h = _hub()
    req = _H()
    with mock.patch.object(rev, "_get_hub", return_value=h), \
            mock.patch.object(rev, "_sse_count", rev._SSE_MAX_SUBSCRIBERS):
        rev._serve_events(req)
    assert req.sent[0] == 503


def test_route_is_registered_on_the_dashboard():
    from dashboard import routes_state
    handlers = [fn for m, fn in routes_state.GET_ROUTES if m("/api/events")]
    assert handlers == [rev._serve_events]
    assert [fn for m, fn in routes_state.GET_ROUTES if m("/api/events?since=3")] \
        == [rev._serve_events]


# -- RM-605 replay auto-serves the deriver ----------------------------------

def test_replay_discovers_the_deriver_and_serves_events():
    from tools import replay_session as rs
    src = rs.discover_events_source()
    assert src is led.derive_events
    state = rs.ReplayState({}, events_source=src)
    for i, dead in enumerate([False, True, False]):
        state.publish({"kind": "frame", "seq": i, "captured_at": 1.0 + i,
                       "snapshot": _snap(100.0 + i, zed_dead=dead)})
    server = rs.make_server(state, port=0, events_source=src)
    port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events",
                                    timeout=5) as r:
            body = json.loads(r.read())
        assert [(e["id"], e["kind"], e["champion"]) for e in body["events"]] == [
            (1, "death", "Zed"), (2, "respawn", "Zed")]
        assert body["replay"] is True
    finally:
        server.shutdown()
        server.server_close()
