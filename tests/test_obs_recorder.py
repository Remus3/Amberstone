"""RM-637 (directive X-37, ADR-016): OBS recorder state machine against a FAKE
obs-websocket v5 peer (an in-process asyncio websocket server on 127.0.0.1,
ephemeral port). Nothing here starts OBS, connects to a real OBS, writes
config/coach_settings.json or records anything. Every payload is synthetic and
name-scrubbed."""
from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from core import obs_recorder as orc
from core.liveclient_cache import Snapshot
from tests._asyncio_isolation import run_coro

GB = 1_000_000_000

READ_ONLY = {"GetRecordStatus", "GetVersion", "GetProfileParameter",
             "GetRecordDirectory", "GetCurrentProgramScene",
             "GetSceneItemList", "GetGroupSceneItemList"}
CONTROL = {"StartRecord", "StopRecord", "CreateRecordChapter"}


class FakeObs:
    """Minimal obs-websocket v5 peer. Answers the read-only probes, Start /
    Stop / CreateRecordChapter, and emits RecordStateChanged events."""

    def __init__(self, *, recording=False, ws_version="5.7.3",
                 output_mode="Simple", rec_format="hybrid_mp4",
                 scene_items=None, groups=None, record_dir="/synthetic/vids",
                 start_ok=True, chapter_ok=True, emit_started=True,
                 scene_fail=False, status_path=False):
        self.recording = recording
        self.ws_version = ws_version
        self.output_mode = output_mode
        self.rec_format = rec_format
        self.scene_items = scene_items if scene_items is not None else [
            {"sourceName": "Display", "inputKind": "monitor_capture",
             "sceneItemEnabled": True, "isGroup": False}]
        self.groups = groups or {}
        self.record_dir = record_dir
        self.start_ok = start_ok
        self.chapter_ok = chapter_ok
        self.emit_started = emit_started
        self.scene_fail = scene_fail
        self.status_path = status_path
        self.requests: list = []
        self.subs = None
        self.n = 0
        self.path = "/synthetic/vids/operator.mp4" if recording else None
        self.duration_ms = 0
        self.bytes = 0
        self.conns: list = []

    async def handler(self, ws):
        self.conns.append(ws)
        await ws.send(json.dumps({"op": 0, "d": {"obsWebSocketVersion": self.ws_version,
                                                 "rpcVersion": 1}}))
        ident = json.loads(await ws.recv())
        self.subs = ident["d"].get("eventSubscriptions")
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("op") != 6:
                    continue
                await self._answer(ws, msg["d"])
        except Exception:  # noqa: BLE001
            pass
        finally:
            if ws in self.conns:
                self.conns.remove(ws)

    async def _reply(self, ws, d, ok=True, data=None, code=100):
        out = {"requestType": d["requestType"], "requestId": d["requestId"],
               "requestStatus": {"result": ok, "code": code if ok else 500}}
        if data is not None:
            out["responseData"] = data
        await ws.send(json.dumps({"op": 7, "d": out}))

    async def _event(self, ws, state, path):
        await ws.send(json.dumps({"op": 5, "d": {
            "eventType": "RecordStateChanged", "eventIntent": 64,
            "eventData": {"outputActive": state.endswith("STARTED"),
                          "outputState": state, "outputPath": path}}}))

    async def broadcast(self, state, path):
        for ws in list(self.conns):
            await self._event(ws, state, path)

    async def _answer(self, ws, d):
        rt = d["requestType"]
        rd = d.get("requestData") or {}
        self.requests.append((rt, rd))
        if rt == "GetRecordStatus":
            if self.recording:
                self.duration_ms += 2000
                self.bytes += 8_400_000
            data = {"outputActive": self.recording, "outputPaused": False,
                    "outputDuration": self.duration_ms, "outputBytes": self.bytes}
            if self.status_path:
                data["outputPath"] = self.path
            await self._reply(ws, d, data=data)
        elif rt == "GetVersion":
            await self._reply(ws, d, data={"obsVersion": "32.1.2",
                                           "obsWebSocketVersion": self.ws_version,
                                           "rpcVersion": 1})
        elif rt == "GetProfileParameter":
            cat, name = rd.get("parameterCategory"), rd.get("parameterName")
            val = None
            if (cat, name) == ("Output", "Mode"):
                val = self.output_mode
            elif name == "RecFormat2" and cat in ("SimpleOutput", "AdvOut"):
                val = self.rec_format
            await self._reply(ws, d, data={"parameterValue": val,
                                           "defaultParameterValue": None})
        elif rt == "GetRecordDirectory":
            await self._reply(ws, d, data={"recordDirectory": self.record_dir})
        elif rt == "GetCurrentProgramScene":
            await self._reply(ws, d, data={"currentProgramSceneName": "Main",
                                           "sceneName": "Main"})
        elif rt == "GetSceneItemList" and self.scene_fail:
            await self._reply(ws, d, ok=False, code=600)
        elif rt == "GetSceneItemList":
            name = rd.get("sceneName")
            items = self.scene_items if name == "Main" else self.groups.get(name, [])
            await self._reply(ws, d, data={"sceneItems": items})
        elif rt == "GetGroupSceneItemList":
            await self._reply(ws, d, data={"sceneItems": self.groups.get(rd.get("sceneName"), [])})
        elif rt == "StartRecord":
            if not self.start_ok or self.recording:
                await self._reply(ws, d, ok=False)
                return
            self.recording = True
            self.n += 1
            self.path = f"/synthetic/vids/rc-{self.n}.mp4"
            self.duration_ms = 0
            self.bytes = 0
            await self._reply(ws, d)
            await self._event(ws, "OBS_WEBSOCKET_OUTPUT_STARTING", None)
            if self.emit_started:
                await self._event(ws, "OBS_WEBSOCKET_OUTPUT_STARTED", self.path)
        elif rt == "StopRecord":
            if not self.recording:
                await self._reply(ws, d, ok=False)
                return
            self.recording = False
            await self._reply(ws, d, data={"outputPath": self.path})
            await self._event(ws, "OBS_WEBSOCKET_OUTPUT_STOPPED", self.path)
        elif rt == "CreateRecordChapter":
            await self._reply(ws, d, ok=self.chapter_ok)
        else:
            await self._reply(ws, d, ok=False, code=204)

    async def drop_all(self):
        for ws in list(self.conns):
            await ws.close()

    def types(self):
        return [r[0] for r in self.requests]


class Clock:
    def __init__(self, t=10_000.0):
        self.t = t

    def __call__(self):
        return self.t


def lc(clock, gt, events=(), deaths=0, failure=""):
    if failure:
        return Snapshot(data=None, ts=0.0, fetched_at=clock.t, failure=failure)
    data = {"gameData": {"gameTime": gt, "gameMode": "CLASSIC"},
            "events": {"Events": list(events)},
            "activePlayer": {"riotId": "Tester#T1"},
            "allPlayers": [{"riotId": "Tester#T1", "scores": {"deaths": deaths}},
                           {"riotId": "Other#X", "scores": {"deaths": 9}}]}
    return Snapshot(data=data, ts=clock.t, fetched_at=clock.t)


def ev(eid, name, t, **kw):
    return {"EventID": eid, "EventName": name, "EventTime": t, **kw}


SESSION = {"phase": "InProgress",
           "gameData": {"gameId": 7001, "queue": {"id": 420, "gameMode": "CLASSIC"}}}


def make(fake_port, tmp_path, clock, *, enabled=True, policy=True, free=500 * GB,
         rc_bytes=0, **rec):
    cfg = {"host": "127.0.0.1", "port": fake_port, "password": "",
           "record": {"enabled": enabled, **rec}}
    return orc.ObsRecorder(
        cfg, sidecar_dir=tmp_path / "recordings",
        policy_fn=(lambda m, q: policy) if not callable(policy) else policy,
        free_bytes_fn=lambda _p: free, rc_bytes_fn=lambda _d: rc_bytes,
        clock=clock, started_timeout_s=1.0)


async def _with_fake(fake, body):
    async with serve(fake.handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        return await body(port)


def sidecar(tmp_path, mid="7001"):
    return json.loads((tmp_path / "recordings" / f"{mid}.json").read_text())


async def _start_game(rec, clock, events=()):
    rec.on_gameflow_session(SESSION)
    rec.on_gameflow_phase("InProgress")
    rec.on_liveclient_snapshot(lc(clock, 0.0, events))
    await rec.tick()


# -- flag off: inert ---------------------------------------------------------

def test_flag_off_is_inert(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, enabled=False)
        await _start_game(rec, clock)
        await rec.tick()
        await rec.close()
        return rec
    run_coro(body_wrap(fake, body))
    assert fake.requests == [] and fake.subs is None
    assert not (tmp_path / "recordings").exists()


def body_wrap(fake, body):
    return _with_fake(fake, body)


def test_flag_default_is_off():
    assert orc.record_enabled({}) is False
    assert orc.record_enabled({"record": {}}) is False
    assert orc.record_enabled({"record": {"enabled": "true"}}) is False
    assert orc.record_enabled({"enabled": True}) is False  # publisher flag is not ours
    assert orc.record_enabled({"record": {"enabled": True}}) is True


def test_install_if_enabled_noop_when_off(monkeypatch):
    monkeypatch.setattr(orc, "_load_obs_config", lambda: {"record": {"enabled": False}})
    called = []
    monkeypatch.setattr(orc, "start_background", lambda *a, **k: called.append(1))
    assert orc.install_if_enabled() is False
    assert called == []


def test_policy_deny_is_inert(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, policy=False)
        await _start_game(rec, clock)
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert fake.requests == []
    assert not (tmp_path / "recordings").exists()


def test_policy_receives_mode_and_queue(tmp_path):
    fake = FakeObs()
    clock = Clock()
    seen = []

    async def body(port):
        rec = make(port, tmp_path, clock, policy=lambda m, q: seen.append((m, q)) or False)
        await _start_game(rec, clock)
    run_coro(body_wrap(fake, body))
    assert seen == [("sr", 420)]


# -- start conditions --------------------------------------------------------

def test_no_start_without_liveclient_or_in_wrong_phase(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        rec.on_gameflow_session(SESSION)
        rec.on_gameflow_phase("InProgress")
        await rec.tick()  # Live Client has not answered
        assert fake.requests == []
        rec.on_liveclient_snapshot(lc(clock, 0.0, failure="http"))
        await rec.tick()
        assert fake.requests == []
        rec.on_gameflow_phase("ChampSelect")
        rec.on_liveclient_snapshot(lc(clock, 0.0))
        await rec.tick()
        assert fake.requests == []
        rec.on_gameflow_phase("InProgress")
        await rec.tick()
        assert "StartRecord" in fake.types()
        await rec.close()
    run_coro(body_wrap(fake, body))


def test_start_on_inprogress_and_liveclient(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        assert rec.ownership() == (True, False)
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert fake.subs == orc.EVENT_SUB_OUTPUTS
    assert "StartRecord" in fake.types()
    assert set(fake.types()) <= READ_ONLY | CONTROL
    sc = sidecar(tmp_path)
    assert sc["owner"] == "rc"
    assert sc["ownership_token"] == "/synthetic/vids/rc-1.mp4"
    assert sc["status"] == "recording"
    assert sc["queue_id"] == 420


def test_never_writes_obs_settings(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        clock.t += 5
        rec.on_liveclient_snapshot(lc(clock, 2.0, [ev(1, "FirstBlood", 1.5)]))
        await rec.tick()
        rec.on_gameflow_phase("EndOfGame")
        await rec.tick()
    run_coro(body_wrap(fake, body))
    for t in fake.types():
        assert not t.startswith("Set"), t
        assert t in READ_ONLY | CONTROL, t


# -- ownership -----------------------------------------------------------------

def test_operator_owned_recording_untouched(tmp_path):
    fake = FakeObs(recording=True)
    fake.duration_ms = 60_000
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        assert rec.ownership() == (False, False)
        clock.t += 30
        rec.on_gameflow_phase("EndOfGame")
        await rec.tick()
    run_coro(body_wrap(fake, body))
    assert "StartRecord" not in fake.types()
    assert "StopRecord" not in fake.types()
    assert fake.recording is True
    sc = sidecar(tmp_path)
    assert sc["owner"] == "operator"
    assert sc["obs_output_path"] is None
    assert sc["stop_reason"] == "end_of_game"


def test_operator_restart_mid_game_revokes_ownership(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        assert rec.ownership() == (True, False)
        # Operator stops RC's recording and starts their own.
        await fake.broadcast("OBS_WEBSOCKET_OUTPUT_STOPPED", "/synthetic/vids/rc-1.mp4")
        fake.recording = True
        fake.path = "/synthetic/vids/mine.mp4"
        await fake.broadcast("OBS_WEBSOCKET_OUTPUT_STARTED", "/synthetic/vids/mine.mp4")
        clock.t += 2
        rec.on_liveclient_snapshot(lc(clock, 1.0))
        await rec.tick()
        assert rec.ownership() == (False, False)
        rec.on_gameflow_phase("EndOfGame")
        await rec.tick()
    run_coro(body_wrap(fake, body))
    assert "StopRecord" not in fake.types()
    assert fake.recording is True
    sc = sidecar(tmp_path)
    assert sc["diagnostics"]["ownership_lost"] == "stopped_externally"


def test_no_started_event_means_no_ownership(tmp_path):
    fake = FakeObs(emit_started=False)
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        assert rec.ownership() == (False, False)
        rec.on_gameflow_phase("EndOfGame")
        await rec.tick()
    run_coro(body_wrap(fake, body))
    assert "StopRecord" not in fake.types()
    assert sidecar(tmp_path)["diagnostics"]["started_event_missing"] is True


# -- refusals ------------------------------------------------------------------

@pytest.mark.parametrize("items,groups,refused", [
    ([{"sourceName": "GC", "inputKind": "game_capture", "sceneItemEnabled": True,
       "isGroup": False}], {}, True),
    ([{"sourceName": "GC", "inputKind": "game_capture", "sceneItemEnabled": False,
       "isGroup": False}], {}, False),
    ([{"sourceName": "Grp", "inputKind": None, "sceneItemEnabled": True, "isGroup": True}],
     {"Grp": [{"sourceName": "GC", "inputKind": "game_capture",
               "sceneItemEnabled": True, "isGroup": False}]}, True),
    ([{"sourceName": "Nested", "inputKind": None, "sceneItemEnabled": True,
       "isGroup": False, "sourceType": "OBS_SOURCE_TYPE_SCENE"}],
     {"Nested": [{"sourceName": "GC", "inputKind": "game_capture",
                  "sceneItemEnabled": True, "isGroup": False}]}, True),
])
def test_game_capture_refusal(tmp_path, items, groups, refused):
    fake = FakeObs(scene_items=items, groups=groups)
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert ("StartRecord" in fake.types()) is (not refused)
    sc = sidecar(tmp_path)
    if refused:
        assert sc["owner"] == "none"
        assert sc["diagnostics"]["refused"] == "game_capture_in_active_scene"


def test_disk_precondition_refuses_start(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, free=27 * GB)
        await _start_game(rec, clock)
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert "StartRecord" not in fake.types()
    assert sidecar(tmp_path)["diagnostics"]["refused"].startswith("disk:")


def test_cap_refuses_start(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, rc_bytes=55 * GB)
        await _start_game(rec, clock)
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert "StartRecord" not in fake.types()
    assert "cap" in sidecar(tmp_path)["diagnostics"]["refused"]


def test_obs_unreachable_writes_sidecar_without_recording(tmp_path):
    clock = Clock()

    async def body():
        rec = make(1, tmp_path, clock)  # nothing listens on port 1
        await _start_game(rec, clock)
        rec.on_gameflow_phase("EndOfGame")
        await rec.tick()
    run_coro(body())
    sc = sidecar(tmp_path)
    assert sc["owner"] == "none"
    assert sc["diagnostics"]["refused"] == "obs_unreachable"


def test_one_attempt_per_game(tmp_path):
    fake = FakeObs(start_ok=False)
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        for _ in range(3):
            clock.t += 1
            await rec.tick()
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert fake.types().count("StartRecord") == 1
    assert sidecar(tmp_path)["diagnostics"]["refused"] == "start_failed"


# -- stop conditions -----------------------------------------------------------

def test_transport_failures_stop_after_n(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, liveclient_failures_to_stop=4)
        await _start_game(rec, clock)
        for i in range(3):
            rec.on_liveclient_snapshot(lc(clock, 0, failure="transport"))
        await rec.tick()
        assert "StopRecord" not in fake.types()
        rec.on_liveclient_snapshot(lc(clock, 0, failure="transport"))
        await rec.tick()
    run_coro(body_wrap(fake, body))
    assert "StopRecord" in fake.types()
    assert sidecar(tmp_path)["stop_reason"] == "liveclient_transport_failures"


def test_parse_and_http_errors_never_stop(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, liveclient_failures_to_stop=4)
        await _start_game(rec, clock)
        for i in range(40):
            kind = ("parse", "http", "transport")[i % 3]
            rec.on_liveclient_snapshot(lc(clock, 0, failure=kind))
            await rec.tick()
        assert "StopRecord" not in fake.types()
        assert rec.ownership() == (True, False)
        await rec.close()
    run_coro(body_wrap(fake, body))


def test_game_end_event_stops(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        clock.t += 3
        rec.on_liveclient_snapshot(lc(clock, 900.0, [ev(50, "GameEnd", 900.0, Result="Win")]))
        await rec.tick()
    run_coro(body_wrap(fake, body))
    assert "StopRecord" in fake.types()
    assert sidecar(tmp_path)["stop_reason"] == "game_end_event"


def test_disk_guard_trip_stops_rc_owned(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        await rec.request_disk_stop({"stop_record": True, "stop_replay_buffer": False})
        await rec.tick()
    run_coro(body_wrap(fake, body))
    assert "StopRecord" in fake.types()
    assert sidecar(tmp_path)["stop_reason"] == "disk_guard"


def test_disk_guard_trip_never_stops_operator_owned(tmp_path):
    fake = FakeObs(recording=True)
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        await rec.request_disk_stop({"stop_record": True, "stop_replay_buffer": False})
        await rec.tick()
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert "StopRecord" not in fake.types()
    # banner only: the operator's game keeps being tracked, not finalized
    sc = sidecar(tmp_path)
    assert sc["status"] == "recording" and sc["stop_reason"] is None


def test_disk_guard_wired_through_recorder(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        guard = rec.make_disk_guard(free_bytes_fn=lambda _p: 1 * GB,
                                    banner_path=tmp_path / "banner.json")
        res = await guard.check_once(now=0.0)
        assert res["tripped"] is True
        await rec.tick()
    run_coro(body_wrap(fake, body))
    assert "StopRecord" in fake.types()


# -- chapters ------------------------------------------------------------------

@pytest.mark.parametrize("ws_version,fmt,mode,expect", [
    ("5.7.3", "hybrid_mp4", "Simple", True),
    ("5.5.0", "hybrid_mp4", "Advanced", True),
    ("5.4.2", "hybrid_mp4", "Simple", False),
    ("5.7.3", "mkv", "Simple", False),
    ("5.7.3", "mp4", "Advanced", False),
])
def test_chapters_only_when_supported(tmp_path, ws_version, fmt, mode, expect):
    fake = FakeObs(ws_version=ws_version, rec_format=fmt, output_mode=mode)
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        clock.t += 70
        rec.on_liveclient_snapshot(lc(clock, 65.0, [ev(1, "ChampionKill", 64.0,
                                                       VictimName="Other#X")]))
        await rec.tick()
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert ("CreateRecordChapter" in fake.types()) is expect
    if expect:
        chap = [r for r in fake.requests if r[0] == "CreateRecordChapter"][0][1]
        assert chap["chapterName"].startswith("ChampionKill")


def test_chapter_failure_degrades_silently(tmp_path):
    fake = FakeObs(chapter_ok=False)
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        for i in range(1, 4):
            clock.t += 10
            rec.on_liveclient_snapshot(lc(clock, 10.0 * i, [ev(i, "TurretKilled", 10.0 * i)]))
            await rec.tick()
        assert rec.ownership() == (True, False)
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert fake.types().count("CreateRecordChapter") == 1


# -- stall detector ------------------------------------------------------------

def test_stall_detector_counts_frozen_duration(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, stall_polls=2)
        await _start_game(rec, clock)
        orig = fake._answer

        async def frozen(ws, d):
            if d["requestType"] == "GetRecordStatus":
                fake.duration_ms -= 2000  # cancel the advance: OBS output stalled
            await orig(ws, d)
        fake._answer = frozen
        for _ in range(4):
            clock.t += 2
            rec.on_liveclient_snapshot(lc(clock, clock.t - 10_000))
            await rec.tick()
        rec.on_gameflow_phase("EndOfGame")
        await rec.tick()
    run_coro(body_wrap(fake, body))
    assert sidecar(tmp_path)["diagnostics"]["stall_count"] >= 1


def test_no_stall_when_duration_advances(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, stall_polls=2)
        await _start_game(rec, clock)
        for _ in range(4):
            clock.t += 2
            await rec.tick()
        rec.on_gameflow_phase("EndOfGame")
        await rec.tick()
    run_coro(body_wrap(fake, body))
    assert sidecar(tmp_path)["diagnostics"]["stall_count"] == 0


# -- sidecar contents ------------------------------------------------------------

def test_full_game_sidecar(tmp_path):
    fake = FakeObs()
    clock = Clock()
    past = [ev(0, "GameStart", 0.0), ev(1, "ChampionKill", 5.0, VictimName="Tester#T1")]

    async def body(port):
        rec = make(port, tmp_path, clock)
        # attach: these past events form the baseline and are never emitted
        await _start_game(rec, clock, events=past)
        # loading: frozen 0
        for _ in range(3):
            clock.t += 5
            rec.on_liveclient_snapshot(lc(clock, 0.0, past))
            await rec.tick()
        # play starts: video 15+ s, game time advances
        clock.t += 5
        rec.on_liveclient_snapshot(lc(clock, 1.0, past))
        clock.t += 100
        cur = past + [ev(2, "ChampionKill", 100.0, VictimName="Tester#T1"),
                      ev(3, "DragonKill", 101.0)]
        rec.on_liveclient_snapshot(lc(clock, 101.0, cur, deaths=1))
        await rec.tick()
        clock.t += 10
        rec.on_gameflow_phase("PreEndOfGame")
        await rec.tick()
    run_coro(body_wrap(fake, body))
    sc = sidecar(tmp_path)
    assert sc["status"] == "final"
    assert sc["owner"] == "rc"
    assert sc["obs_output_path"] == "/synthetic/vids/rc-1.mp4"
    assert sc["queue_id"] == 420
    assert sc["match_id"] == "7001"
    assert sc["stop_reason"] == "end_of_game"
    assert sc["death_count"] == 1
    assert sc["alignment"]["proven"] is True
    # record start at t0; first advance at t0+20 game 1.0 -> offset 19
    assert sc["game_time_offset_s"] == pytest.approx(19.0)
    names = [b["name"] for b in sc["bookmarks"]]
    assert names == ["ChampionKill", "DragonKill"]  # baseline events excluded
    b0 = sc["bookmarks"][0]
    assert b0["event_id"] == 2 and b0["game_time"] == 100.0
    assert b0["video_time"] == pytest.approx(119.0)
    assert b0["provisional"] is False
    for k in ("attach", "record_start", "record_stop"):
        assert isinstance(sc["wall"][k], (int, float))
    d = sc["diagnostics"]
    assert d["obs_websocket_version"] == "5.7.3"
    assert d["record_format"] == "hybrid_mp4"
    assert d["chapters_supported"] is True
    assert d["chapters_created"] == 2
    assert "start_game_time_s" in sc


def test_sidecar_is_atomic_and_name_safe(tmp_path):
    fake = FakeObs()
    clock = Clock()
    sess = {"gameData": {"gameId": "../../evil", "queue": {"id": 450, "gameMode": "ARAM"}}}

    async def body(port):
        rec = make(port, tmp_path, clock)
        rec.on_gameflow_session(sess)
        rec.on_gameflow_phase("InProgress")
        rec.on_liveclient_snapshot(lc(clock, 0.0))
        await rec.tick()
        await rec.close()
    run_coro(body_wrap(fake, body))
    files = sorted(p.name for p in (tmp_path / "recordings").iterdir())
    assert files == ["evil.json"]


def test_mid_game_attach_emits_no_past_events(tmp_path):
    fake = FakeObs()
    clock = Clock()
    past = [ev(i, "ChampionKill", 30.0 * i) for i in range(1, 6)]

    async def body(port):
        rec = make(port, tmp_path, clock)
        rec.on_gameflow_session(SESSION)
        rec.on_gameflow_phase("InProgress")
        rec.on_liveclient_snapshot(lc(clock, 600.0, past))
        await rec.tick()
        clock.t += 2
        rec.on_liveclient_snapshot(lc(clock, 601.0, past))
        rec.on_gameflow_phase("EndOfGame")
        await rec.tick()
    run_coro(body_wrap(fake, body))
    sc = sidecar(tmp_path)
    assert sc["bookmarks"] == []
    assert "CreateRecordChapter" not in fake.types()


# -- publisher lane helpers ------------------------------------------------------

def test_request_response_hands_events_to_callback():
    from core.obs_publisher import request_response
    got = []

    class _Ws:
        def __init__(self):
            self.q = asyncio.Queue()

        async def send(self, raw):
            rid = json.loads(raw)["d"]["requestId"]
            await self.q.put(json.dumps({"op": 5, "d": {"eventType": "X"}}))
            await self.q.put(json.dumps({"op": 7, "d": {"requestId": rid,
                                                       "requestStatus": {"result": True}}}))

        async def recv(self):
            return await self.q.get()

    d = run_coro(request_response(_Ws(), "GetVersion", on_event=got.append))
    assert d["requestStatus"]["result"] is True
    assert got == [{"eventType": "X"}]


# -- wiring ----------------------------------------------------------------------

def test_optional_tap_calls_recorder_install(monkeypatch):
    from core import liveclient_cache as lcc
    calls = []
    monkeypatch.setattr(orc, "install_if_enabled", lambda: calls.append(1) or False)
    lcc._install_optional_taps()
    assert calls == [1]


def test_start_background_off_registers_nothing(monkeypatch):
    from core import liveclient_cache as lcc
    added = []
    monkeypatch.setattr(lcc, "add_listener", lambda fn: added.append(fn))
    monkeypatch.setattr(orc, "_load_obs_config",
                        lambda: {"enabled": True, "record": {"enabled": False}})
    assert orc.install_if_enabled() is False
    assert orc.start_background({"record": {}}) is False
    assert added == [] and orc._recorder is None


def test_example_config_record_block_default_off():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    cfg = json.loads((root / "config" / "coach_settings.example.json").read_text(encoding="utf-8"))
    assert cfg["obs"]["record"]["enabled"] is False
    assert orc.record_enabled(cfg["obs"]) is False


def test_sidecar_dir_is_gitignored():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q",
                        "data/recordings/7001.json"], capture_output=True)
    assert r.returncode == 0


def test_consecutive_parse_or_http_errors_never_stop(tmp_path):
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, liveclient_failures_to_stop=4)
        await _start_game(rec, clock)
        for kind in ("parse",) * 12 + ("http",) * 12:
            rec.on_liveclient_snapshot(lc(clock, 0, failure=kind))
        await rec.tick()
        assert "StopRecord" not in fake.types()
        # interleaved with transport: a parse reply proves the transport
        # answered, so the run of transport failures restarts
        for kind in ("transport", "transport", "transport", "parse") * 5:
            rec.on_liveclient_snapshot(lc(clock, 0, failure=kind))
        await rec.tick()
        assert "StopRecord" not in fake.types()
        await rec.close()
    run_coro(body_wrap(fake, body))


def test_tick_itself_is_gated_on_the_flag(tmp_path):
    """Defense in depth: even if inputs reached a disabled recorder, tick()
    never talks to OBS."""
    fake = FakeObs()
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock, enabled=False)
        rec._phase = "InProgress"
        rec._session_info = {"game_id": 1, "queue_id": 420, "game_mode": "CLASSIC"}
        rec._lc_data = lc(clock, 0.0).data
        await rec.tick()
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert fake.requests == [] and fake.subs is None


# -- verifier follow-ups -----------------------------------------------------------

def test_unreadable_scene_refuses_start(tmp_path):
    fake = FakeObs(scene_fail=True)
    clock = Clock()

    async def body(port):
        rec = make(port, tmp_path, clock)
        await _start_game(rec, clock)
        await rec.close()
    run_coro(body_wrap(fake, body))
    assert "GetSceneItemList" in fake.types()
    assert "StartRecord" not in fake.types()
    sc = sidecar(tmp_path)
    assert sc["owner"] == "none"
    assert sc["diagnostics"]["refused"] == "scene_probe_failed"


async def _reconnect_then_end(rec, fake, clock, *, mutate):
    await _start_game(rec, clock)
    assert rec.ownership() == (True, False)
    await fake.drop_all()
    await asyncio.sleep(0.1)
    clock.t += 60
    mutate()
    rec.on_liveclient_snapshot(lc(clock, 50.0))
    # first tick notices the dead socket, later ones reconnect and re-verify
    for _ in range(3):
        await rec.tick()
    owned = rec.ownership()
    rec.on_gameflow_phase("EndOfGame")
    await rec.tick()
    return owned


def test_reconnect_same_recording_keeps_ownership(tmp_path):
    fake = FakeObs()
    clock = Clock()

    def same():
        fake.duration_ms = 60_000  # continuous since RC's start

    async def body(port):
        rec = make(port, tmp_path, clock)
        return await _reconnect_then_end(rec, fake, clock, mutate=same)
    owned = run_coro(body_wrap(fake, body))
    assert owned == (True, False)
    assert "StopRecord" in fake.types()
    assert sidecar(tmp_path)["diagnostics"]["ownership_lost"] is None


def test_reconnect_after_operator_restart_revokes_ownership(tmp_path):
    fake = FakeObs()
    clock = Clock()

    def restarted():
        # Missed while disconnected: operator stopped RC's file and started
        # their own; OBS is recording again but the duration restarted.
        fake.path = "/synthetic/vids/mine.mp4"
        fake.duration_ms = 4_000

    async def body(port):
        rec = make(port, tmp_path, clock)
        return await _reconnect_then_end(rec, fake, clock, mutate=restarted)
    owned = run_coro(body_wrap(fake, body))
    assert owned == (False, False)
    assert "StopRecord" not in fake.types()
    assert fake.recording is True
    assert sidecar(tmp_path)["diagnostics"]["ownership_lost"] == "unconfirmed_after_reconnect"


def test_reconnect_path_mismatch_revokes_ownership(tmp_path):
    fake = FakeObs(status_path=True)
    clock = Clock()

    def other_path():
        fake.duration_ms = 60_000  # duration alone would look continuous
        fake.path = "/synthetic/vids/mine.mp4"

    async def body(port):
        rec = make(port, tmp_path, clock)
        return await _reconnect_then_end(rec, fake, clock, mutate=other_path)
    owned = run_coro(body_wrap(fake, body))
    assert owned == (False, False)
    assert "StopRecord" not in fake.types()


def test_reconnect_with_recording_stopped_revokes_ownership(tmp_path):
    fake = FakeObs()
    clock = Clock()

    def stopped():
        fake.recording = False
        fake.duration_ms = 60_000  # duration alone would look continuous

    async def body(port):
        rec = make(port, tmp_path, clock)
        return await _reconnect_then_end(rec, fake, clock, mutate=stopped)
    owned = run_coro(body_wrap(fake, body))
    assert owned == (False, False)
    assert "StopRecord" not in fake.types()


def test_module_docstring_states_push_only_limit():
    doc = orc.__doc__ or ""
    assert "mid-game" in doc and "push-only" in doc
