"""RM-605 / X-05 (external reference F): session replay.

Covers tools/replay_session.py:
  - record -> replay round-trip serves byte-identical snapshot content at
    --speed 1 (JSON content compared, not timing),
  - pacing at anchor + elapsed/speed from a FIXED anchor: drift stays bounded
    over a simulated 10-minute run with jittery sleeps (fake clock, no real
    sleeping),
  - captured_at re-stamped at publish, --from / --hold, 127.0.0.1-only bind,
  - /api/events is pluggable and absent when no event source exists.

Fixtures are synthetic: no real Riot IDs or summoner names.
"""
from __future__ import annotations

import json
import random
import threading
import urllib.error
import urllib.request

import pytest

from core import live_session_recorder as lsr
from tools import replay_session as rs


class FakeClock:
    """Monotonic fake clock whose sleep() overshoots by a seeded jitter."""

    def __init__(self, start=1000.0, jitter_max=0.0, seed=7):
        self.t = start
        self.jitter_max = jitter_max
        self.rng = random.Random(seed)
        self.sleeps = 0

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps += 1
        self.t += max(0.0, s) + self.rng.uniform(0.0, self.jitter_max)


def _snap(game_time, gold):
    return {
        "activePlayer": {"summonerName": "SyntheticPlayer#TEST", "currentGold": gold},
        "allPlayers": [{"championName": "Lux", "summonerName": "SyntheticPlayer#TEST",
                        "items": [{"itemID": 1001, "slot": 0}]}],
        "gameData": {"gameMode": "CLASSIC", "gameTime": game_time},
        "events": {"Events": [{"EventID": 0, "EventName": "GameStart", "EventTime": 0.0}]},
        "unicode_probe": "plain-ascii",
    }


def _frames(n, step=0.5, t0=5000.0):
    return [{"kind": "frame", "seq": i, "captured_at": t0 + i * step,
             "snapshot": _snap(i * step, 500.0 + i)} for i in range(n)]


def _canon(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


# -- round trip -------------------------------------------------------------

def _record_session(tmp_path, snaps, wall):
    clock = iter(wall)
    rec = lsr.LiveSessionRecorder(
        sessions_dir=tmp_path,
        header_fields=lambda s: {"config_key": "k", "patch": "99.1.1",
                                 "ENGINE_VERSION": "0.0.1-test", "mode_key": "sr"},
        game_id_provider=lambda: "9000000077",
        vision_provider=lambda: {"enemies": []},
        wall_clock=lambda: next(clock),
    )
    for s in snaps:
        rec.record(s)
    rec.flush()
    rec.close()
    return tmp_path / "9000000077.jsonl"


def test_round_trip_byte_identical_snapshot_content_over_http(tmp_path):
    snaps = [_snap(i * 0.5, 500.0 + i) for i in range(20)]
    path = _record_session(tmp_path, snaps, [7000.0 + i * 0.5 for i in range(20)])
    header, frames = lsr.read_session(path)

    clock = FakeClock()
    state = rs.ReplayState(header, wall_clock=lambda: 123456.0)
    server = rs.make_server(state, port=0)
    port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    served = []
    try:
        def publish(frame):
            state.publish(frame)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as r:
                served.append(json.loads(r.read()))

        rs.play(rs.timeline(frames), speed=1.0, publish=publish,
                clock=clock.now, sleep=clock.sleep)
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/liveclientdata/allgamedata", timeout=5) as r:
            raw_last = json.loads(r.read())
    finally:
        server.shutdown()
        server.server_close()

    assert len(served) == len(snaps)
    for orig, got in zip(snaps, served):
        assert _canon(got["snapshot"]) == _canon(orig)
        assert got["vision_state"] == {"enemies": []}
        assert got["replay"] is True
    assert _canon(raw_last) == _canon(snaps[-1])
    # speed 1 on a perfect clock: total wall time == recorded span.
    assert clock.now() - 1000.0 == pytest.approx(19 * 0.5)


def test_captured_at_restamped_at_publish():
    frame = _frames(1)[0]
    out = rs.restamp(frame, now=42.0)
    assert out["captured_at"] == 42.0
    assert out["recorded_captured_at"] == frame["captured_at"]
    assert out["replay"] is True
    assert frame["captured_at"] == 5000.0  # input untouched
    assert out["snapshot"] == frame["snapshot"]


def test_state_publish_restamps_with_wall_clock():
    ticks = iter([100.0, 200.0])
    state = rs.ReplayState({"schema": 1}, wall_clock=lambda: next(ticks))
    fr = _frames(2)
    state.publish(fr[0])
    assert state.payload()["captured_at"] == 100.0
    state.publish(fr[1])
    assert state.payload()["captured_at"] == 200.0


# -- pacing -----------------------------------------------------------------

def _run_pacing(jitter, speed=1.0, n=1200, step=0.5):
    clock = FakeClock(jitter_max=jitter)
    frames = _frames(n, step=step)
    published = []
    anchor = clock.now()
    rs.play(rs.timeline(frames), speed=speed,
            publish=lambda f: published.append((clock.now(), f["captured_at"])),
            clock=clock.now, sleep=clock.sleep)
    t0 = frames[0]["captured_at"]
    drifts = [pub - (anchor + (cap - t0) / speed) for pub, cap in published]
    return drifts, clock


def test_pacing_drift_bounded_over_ten_minutes_with_jitter():
    jitter = 0.03
    drifts, clock = _run_pacing(jitter)          # 1200 frames x 0.5s = 10 min
    assert len(drifts) == 1200
    assert min(drifts) >= 0.0
    # Bounded by ONE sleep's jitter, never the sum of 1200 of them (~18s).
    assert max(drifts) <= jitter + 1e-9
    assert drifts[-1] <= jitter + 1e-9


def test_pacing_speed_scales_wall_time():
    drifts, clock = _run_pacing(0.0, speed=2.0)
    assert max(abs(d) for d in drifts) < 1e-9
    assert clock.now() - 1000.0 == pytest.approx(1199 * 0.5 / 2.0)


def test_pacing_never_sleeps_when_behind():
    clock = FakeClock()
    calls = []

    def slow_publish(f):
        clock.t += 2.0   # publish takes longer than the frame gap
        calls.append(f)

    rs.play(rs.timeline(_frames(5)), speed=1.0, publish=slow_publish,
            clock=clock.now, sleep=clock.sleep)
    assert len(calls) == 5
    assert clock.sleeps == 0


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_play_rejects_bad_speed(bad):
    with pytest.raises(ValueError):
        rs.play([], speed=bad, publish=lambda f: None)


# -- --from -----------------------------------------------------------------

def test_timeline_from_skips_earlier_frames_and_rebases():
    tl = rs.timeline(_frames(10, step=1.0), from_s=3.0)
    assert [f["seq"] for _, f in tl] == list(range(3, 10))
    assert tl[0][0] == 0.0
    assert tl[-1][0] == pytest.approx(6.0)


def test_timeline_from_past_end_is_empty():
    assert rs.timeline(_frames(3), from_s=100.0) == []


# -- CLI / hold / bind ------------------------------------------------------

def test_parse_args_defaults_and_flags(tmp_path):
    a = rs.parse_args([str(tmp_path / "x.jsonl")])
    assert a.speed == 1.0 and a.from_s == 0.0 and a.hold is False
    b = rs.parse_args([str(tmp_path / "x.jsonl"), "--speed", "4", "--from", "90", "--hold"])
    assert b.speed == 4.0 and b.from_s == 90.0 and b.hold is True


def test_no_host_option_exposed(tmp_path):
    with pytest.raises(SystemExit):
        rs.parse_args([str(tmp_path / "x.jsonl"), "--host", "0.0.0.0"])


@pytest.mark.parametrize("host", ["0.0.0.0", "", "192.168.1.5", "localhost", "::"])
def test_make_server_refuses_non_loopback(host):
    with pytest.raises(ValueError):
        rs.make_server(rs.ReplayState({}), port=0, host=host)


def _write_session(tmp_path, n=4):
    p = tmp_path / "s.jsonl"
    hdr = {"kind": "header", "schema": 1, "config_key": "k", "patch": "p",
           "ENGINE_VERSION": "e", "mode_key": "sr"}
    p.write_text("\n".join(json.dumps(x) for x in [hdr] + _frames(n)) + "\n", encoding="utf-8")
    return p


@pytest.mark.parametrize("hold", [False, True])
def test_run_hold_controls_post_end_wait(tmp_path, hold):
    p = _write_session(tmp_path)
    waited = []
    clock = FakeClock()
    rc = rs.run(rs.parse_args([str(p), "--port", "0"] + (["--hold"] if hold else [])),
                clock=clock.now, sleep=clock.sleep, hold_wait=lambda: waited.append(1),
                serve=False)
    assert rc == 0
    assert waited == ([1] if hold else [])


def test_run_rejects_schema_too_new(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"kind": "header", "schema": 999}) + "\n", encoding="utf-8")
    assert rs.run(rs.parse_args([str(p), "--port", "0"]), serve=False) == 2


# -- /api/events pluggable --------------------------------------------------

def test_events_route_absent_without_source():
    state = rs.ReplayState({})
    state.publish(_frames(1)[0])
    server = rs.make_server(state, port=0, events_source=None)
    port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events", timeout=5)
        assert ei.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_events_route_served_with_source_and_since():
    def source(prev, cur):
        if prev is None:
            return []  # first knowledge is state, not an event
        return [{"kind": "tick", "seq": cur["seq"]}]

    state = rs.ReplayState({}, events_source=source)
    for f in _frames(4):
        state.publish(f)
    server = rs.make_server(state, port=0, events_source=source)
    port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events", timeout=5) as r:
            body = json.loads(r.read())
        assert [e["seq"] for e in body["events"]] == [1, 2, 3]
        assert [e["id"] for e in body["events"]] == [1, 2, 3]
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/events?since=2", timeout=5) as r:
            body2 = json.loads(r.read())
        assert [e["id"] for e in body2["events"]] == [3]
    finally:
        server.shutdown()
        server.server_close()


def test_discover_events_source_absent_returns_none(monkeypatch):
    def boom(name):
        raise ImportError(name)

    monkeypatch.setattr(rs.importlib, "import_module", boom)
    assert rs.discover_events_source() is None


def test_docstring_states_never_closes_live_gated_row():
    doc = rs.__doc__ or ""
    assert "live-gated" in doc and "NEVER" in doc
