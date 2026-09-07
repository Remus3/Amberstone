# arch: tests for dashboard idempotency table + fire_lane/queue_intent actions | section=tests | frozen=no
"""S2 - one operator INTENT equals one idempotency key.

Two things under test:

1. ``dashboard._idempotency`` - a bounded, TTL'd, in-process replay table keyed
   by a client-minted UUID.
2. The two new ``dashboard.routes_loop_control`` actions - ``fire_lane`` and
   ``queue_intent`` - which are gated on that table.

The central behaviour is that a REPLAYED key returns the ORIGINAL stored result
and performs NO second side effect. That is the layer that survives a frozen UI:
disabling a button only stops the click, it does not stop the request that a
wedged browser already has in flight, nor a phone retrying over Tailscale. The
proof here is not "the response looks the same" - it is that the intent file's
BYTES and MTIME are unchanged across the replay and that the writer was called
exactly once.

A lane refusal is a normal answer, not an error: HTTP 200 with ok=false. The
four pre-existing actions (stop / resume / set_directive / clear_directive) are
re-asserted verbatim here as a regression gate - they take no idempotency key
and their response shape must not grow.

``ops.loop.lanes`` (S1) is stubbed in every test; nothing here depends on that
file existing.
"""
from __future__ import annotations

import json
import sys
import threading
import types

import pytest

from dashboard import _idempotency as idem
from dashboard import routes_loop_control as mod

LANES = ("upgrade", "uiux", "research", "ds", "repo", "true-audit", "gated",
         "queue")

KEY_A = "3f2a1b4c-5d6e-4f70-8192-a3b4c5d6e7f8"
KEY_B = "8c7b6a59-4d3e-4c2b-9a10-fedcba987654"


# --------------------------------------------------------------------------- harness
class FakeHandler:
    """Minimal handler stand-in capturing _send(status, body, ctype)."""

    def __init__(self, path: str = "/api/loop-control") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


@pytest.fixture(autouse=True)
def clean_table():
    """The replay table is process-global - isolate every test."""
    idem.clear()
    yield
    idem.clear()


@pytest.fixture
def ctldir(tmp_path, monkeypatch):
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    return ctl


def _post(body):
    h = FakeHandler()
    mod._serve_loop_control(h, body)
    assert h.sent is not None
    status, raw, ctype = h.sent
    return status, json.loads(raw.decode("utf-8")), ctype


class FakeLanes:
    """Stand-in for ops/loop/lanes.py (S1) - records every acquire attempt."""

    LANES = LANES

    def __init__(self, result=None):
        self.calls: list[dict] = []
        self.released: list = []
        self._result = result

    def try_acquire_lane(self, lane, *, run_id, worktree, root=None):
        self.calls.append({"lane": lane, "run_id": run_id,
                           "worktree": worktree, "root": root})
        if self._result is not None:
            return dict(self._result)
        return {"ok": True, "lane": lane, "run_id": run_id,
                "worktree": worktree, "token": "C:/tmp/lanes/slot0.json"}

    def lane_state(self, root=None, now=None):
        return {"state": "FREE", "lane": None, "pid": None, "run_id": None,
                "worktree": None, "age_s": None}

    def release_lane(self, token, root=None):
        # S5: the route hands the lane straight back when the launcher is
        # missing, so the stub has to record it or that path goes untested.
        self.released.append(token)
        return True


@pytest.fixture
def lanes(monkeypatch):
    fake = FakeLanes()
    monkeypatch.setattr(mod, "_lanes", lambda: fake)
    # S5: a successful claim now LAUNCHES. Stub the launcher alongside the lock
    # so these tests keep measuring the idempotency contract and never spawn a
    # process. Refusal tests do not reach it.
    monkeypatch.setattr(mod, "_launcher", lambda: FakeLauncher())
    return fake


class FakeLauncher:
    """Stand-in for ops.loop.lane_launcher - records, never spawns."""

    calls: list = []

    def __init__(self, exc=None):
        self.exc = exc

    def launch_lane(self, lane, *, run_id, token, **kw):
        FakeLauncher.calls.append({"lane": lane, "run_id": run_id, "token": token})
        if self.exc is not None:
            raise self.exc
        return {"lane": lane, "run_id": run_id, "pid": 4242,
                "worktree": rf"C:\rc-worktrees\rc-lane-{lane}",
                "log": rf"C:\Riot Commander\ops\loop\reports\lane_{lane}.log",
                "prompt": r"C:\Riot Commander\tools\headless-upgrade.md",
                "started_at": 1.0}


def _snapshot(d):
    """Byte + mtime census of a directory tree - the mutation detector."""
    out = {}
    for p in sorted(d.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(d).as_posix()] = (p.read_bytes(), st.st_mtime_ns)
        else:
            out[p.relative_to(d).as_posix()] = None
    return out


# ======================================================================= _idempotency
def test_seen_returns_none_for_unknown_key():
    assert idem.seen(KEY_A) is None


def test_remember_then_seen_returns_the_stored_result():
    idem.remember(KEY_A, {"ok": True, "detail": "queued"})
    assert idem.seen(KEY_A) == {"ok": True, "detail": "queued"}


def test_stored_result_is_immune_to_caller_mutation():
    payload = {"ok": True, "nested": {"n": 1}}
    idem.remember(KEY_A, payload)
    payload["ok"] = False
    payload["nested"]["n"] = 99
    got = idem.seen(KEY_A)
    assert got == {"ok": True, "nested": {"n": 1}}
    got["ok"] = "clobbered"
    assert idem.seen(KEY_A)["ok"] is True


def test_ttl_expiry_makes_seen_return_none(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(idem, "_now", lambda: clock[0])
    idem.remember(KEY_A, {"ok": True}, ttl_s=10.0)
    clock[0] = 1009.0
    assert idem.seen(KEY_A) == {"ok": True}
    clock[0] = 1011.0
    assert idem.seen(KEY_A) is None


def test_seen_ttl_argument_narrows_the_window(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(idem, "_now", lambda: clock[0])
    idem.remember(KEY_A, {"ok": True}, ttl_s=900.0)
    clock[0] = 1005.0
    assert idem.seen(KEY_A, ttl_s=1.0) is None


def test_purge_evicts_only_expired_and_returns_the_count(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(idem, "_now", lambda: clock[0])
    idem.remember(KEY_A, {"ok": True}, ttl_s=10.0)
    idem.remember(KEY_B, {"ok": True}, ttl_s=10000.0)
    clock[0] = 1050.0
    assert idem.purge() == 1
    assert idem.seen(KEY_B) == {"ok": True}
    assert idem.purge() == 0


def test_purge_accepts_an_explicit_now(monkeypatch):
    monkeypatch.setattr(idem, "_now", lambda: 1000.0)
    idem.remember(KEY_A, {"ok": True}, ttl_s=10.0)
    assert idem.purge(now=1005.0) == 0
    assert idem.purge(now=1500.0) == 1


def test_table_is_bounded_and_evicts_oldest_first():
    overflow = idem.MAX_ENTRIES + 8
    keys = [f"{i:032x}" for i in range(overflow)]
    for k in keys:
        idem.remember(k, {"ok": True, "n": k})
    assert idem.size() <= idem.MAX_ENTRIES
    assert idem.seen(keys[0]) is None
    assert idem.seen(keys[-1]) == {"ok": True, "n": keys[-1]}


@pytest.mark.parametrize("key", [
    KEY_A,
    "deadbeef",
    "0",
    "f" * 64,
    "3F2A1B4C-5D6E-4F70-8192-A3B4C5D6E7F8",
])
def test_valid_key_shapes_accepted(key):
    assert idem.is_valid_key(key) is True


@pytest.mark.parametrize("key", [
    "",
    "f" * 65,
    "not a key",
    "../../etc/passwd",
    "zzzz",
    "key;rm -rf",
    None,
    12345,
    ["a"],
])
def test_invalid_key_shapes_rejected(key):
    assert idem.is_valid_key(key) is False


# ======================================================================= queue_intent
def test_queue_intent_halt_save_writes_file_and_STOP(ctldir):
    status, payload, _ = _post({"action": "queue_intent", "intent": "halt_save",
                                "idempotency_key": KEY_A})
    assert status == 200 and payload["ok"] is True
    assert payload["action"] == "queue_intent" and payload["intent"] == "halt_save"
    assert payload["file"] == "INTENT_HALT_SAVE.json"
    assert payload["state"] == "stopped"
    assert "replayed" not in payload

    doc = json.loads((ctldir / "INTENT_HALT_SAVE.json").read_text(encoding="utf-8"))
    assert doc["intent"] == "halt_save"
    assert doc["key"] == KEY_A
    assert doc["consumed"] is False
    assert isinstance(doc["ts"], float)
    # halt_save also raises the existing halt flag - a queued intent never kills.
    assert (ctldir / "STOP").exists()
    assert not list(ctldir.glob("*.tmp"))


def test_queue_intent_done_continue_does_not_write_STOP(ctldir):
    status, payload, _ = _post({"action": "queue_intent", "intent": "done_continue",
                                "idempotency_key": KEY_A})
    assert status == 200 and payload["ok"] is True
    assert payload["file"] == "INTENT_DONE_CONTINUE.json"
    assert (ctldir / "INTENT_DONE_CONTINUE.json").exists()
    assert not (ctldir / "STOP").exists()
    assert payload["state"] == "idle"


def test_queue_intent_records_the_fixed_next_session_path(ctldir):
    _post({"action": "queue_intent", "intent": "done_continue",
           "idempotency_key": KEY_A})
    doc = json.loads((ctldir / "INTENT_DONE_CONTINUE.json").read_text(encoding="utf-8"))
    # Single well-known path, OVERWRITE-on-write, no timestamp suffix. Relative
    # to the REPO ROOT since 2026-09-06 - it used to be "Desktop/..." and the
    # Desktop now holds only a shortcut, so the hand-off is tracked in git and
    # a stale one is visible in a diff. Still RC- namespaced: the shortcuts are
    # a shared surface, and the prefix is what stops a doctored intent doc from
    # naming an arbitrary write target.
    assert doc["next_session_path"] == "RC-NEXT-SESSION.txt"
    assert mod.NEXT_SESSION_PATH == "RC-NEXT-SESSION.txt"


def test_queue_intent_replay_returns_stored_result_and_no_second_side_effect(ctldir, monkeypatch):
    writes: list[str] = []
    real_awrite = mod._awrite

    def counting_awrite(path, text):
        writes.append(str(path))
        real_awrite(path, text)

    monkeypatch.setattr(mod, "_awrite", counting_awrite)

    status_1, first, _ = _post({"action": "queue_intent", "intent": "done_continue",
                                "idempotency_key": KEY_A})
    assert status_1 == 200
    target = ctldir / "INTENT_DONE_CONTINUE.json"
    before_bytes = target.read_bytes()
    before_mtime = target.stat().st_mtime_ns
    writes_after_first = list(writes)

    status_2, second, _ = _post({"action": "queue_intent", "intent": "done_continue",
                                 "idempotency_key": KEY_A})

    assert status_2 == 200
    assert second.pop("replayed") is True
    assert second == first                      # the ORIGINAL stored result
    assert target.read_bytes() == before_bytes  # byte-identical
    assert target.stat().st_mtime_ns == before_mtime
    assert writes == writes_after_first         # writer never ran a second time


def test_queue_intent_replay_returns_the_original_state_not_a_fresh_read(ctldir):
    _status, first, _ = _post({"action": "queue_intent", "intent": "done_continue",
                               "idempotency_key": KEY_A})
    assert first["state"] == "idle"
    # World moves on underneath us - the replay must still answer the ORIGINAL.
    (ctldir / "STOP").write_text("halted elsewhere", encoding="utf-8")
    _status2, second, _ = _post({"action": "queue_intent", "intent": "done_continue",
                                 "idempotency_key": KEY_A})
    assert second["state"] == "idle"
    assert second["replayed"] is True


def test_queue_intent_distinct_keys_are_distinct_intents(ctldir):
    _post({"action": "queue_intent", "intent": "done_continue", "idempotency_key": KEY_A})
    first = (ctldir / "INTENT_DONE_CONTINUE.json").read_text(encoding="utf-8")
    _status, payload, _ = _post({"action": "queue_intent", "intent": "done_continue",
                                 "idempotency_key": KEY_B})
    assert "replayed" not in payload
    doc = json.loads((ctldir / "INTENT_DONE_CONTINUE.json").read_text(encoding="utf-8"))
    assert doc["key"] == KEY_B
    assert json.loads(first)["key"] == KEY_A


def test_queue_intent_missing_key_is_400(ctldir):
    status, payload, _ = _post({"action": "queue_intent", "intent": "done_continue"})
    assert status == 400 and payload["ok"] is False
    assert not (ctldir / "INTENT_DONE_CONTINUE.json").exists()


@pytest.mark.parametrize("bad", ["", "not a key", "f" * 65, 12345, None])
def test_queue_intent_malformed_key_is_400(ctldir, bad):
    status, payload, _ = _post({"action": "queue_intent", "intent": "done_continue",
                                "idempotency_key": bad})
    assert status == 400 and payload["ok"] is False
    assert not (ctldir / "INTENT_DONE_CONTINUE.json").exists()


def test_queue_intent_unknown_intent_is_400_and_not_remembered(ctldir):
    status, payload, _ = _post({"action": "queue_intent", "intent": "self_destruct",
                                "idempotency_key": KEY_A})
    assert status == 400 and payload["ok"] is False
    assert "valid" in payload
    assert idem.seen(KEY_A) is None
    assert not list(ctldir.glob("INTENT_*.json"))


# ======================================================================= S7 steer
@pytest.fixture
def steerchan(tmp_path, monkeypatch):
    """Point the real steer module at a tmp log - the route is NOT stubbed here.

    Stubbing it would leave the route's own tier validation and error mapping
    untested, which is the half that decides what the operator sees.
    """
    import importlib
    steer = importlib.import_module("ops.loop.steer")
    # `ctldir` already owns tmp_path/"control", so the steer channel gets its
    # own dir - two fixtures racing one mkdir is a FileExistsError, not a test.
    ctl = tmp_path / "steer_control"
    ctl.mkdir()
    monkeypatch.setattr(steer, "CONTROL_DIR", ctl)
    monkeypatch.setattr(steer, "STEER_LOG", ctl / "STEER.jsonl")
    monkeypatch.setattr(steer, "STEER_CURSOR", ctl / "STEER.cursor")
    return steer


def test_steer_appends_and_reports_the_id(ctldir, steerchan):
    status, payload, _ = _post({"action": "steer", "tier": "note",
                                "text": "focus the overlay, not the dashboard",
                                "idempotency_key": KEY_A})
    assert status == 200 and payload["ok"] is True
    assert payload["tier"] == "note" and payload["id"] == 1
    assert [r["text"] for r in steerchan.pending()] == [
        "focus the overlay, not the dashboard"]


def test_a_replayed_steer_does_not_append_twice(ctldir, steerchan):
    """The layer that survives a phone retrying over Tailscale."""
    _post({"action": "steer", "text": "once", "idempotency_key": KEY_A})
    status, payload, _ = _post({"action": "steer", "text": "once",
                                "idempotency_key": KEY_A})
    assert status == 200 and payload["replayed"] is True
    assert len(steerchan.pending()) == 1, "the replay appended a second steer"


def test_an_empty_steer_is_400_and_not_remembered(ctldir, steerchan):
    status, payload, _ = _post({"action": "steer", "text": "   ",
                                "idempotency_key": KEY_A})
    assert status == 400 and payload["ok"] is False
    assert steerchan.pending() == []
    assert idem.seen(KEY_A) is None


def test_an_unknown_steer_tier_is_400(ctldir, steerchan):
    """INTERRUPT must be REJECTED here, not silently downgraded to a note.

    Stage S9 owns it, it needs operator sign-off, and a route that quietly
    accepted the word would make the panel look like it already worked.
    """
    status, payload, _ = _post({"action": "steer", "tier": "interrupt",
                                "text": "stop everything",
                                "idempotency_key": KEY_A})
    assert status == 400
    assert "interrupt" in payload["error"]
    assert steerchan.pending() == []
    assert idem.seen(KEY_A) is None


def test_steer_requires_an_idempotency_key(ctldir, steerchan):
    status, payload, _ = _post({"action": "steer", "text": "no key"})
    assert status == 400 and payload["ok"] is False
    assert steerchan.pending() == []


def test_a_missing_steer_module_is_503(ctldir, monkeypatch):
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "ops.loop.steer", None)
    monkeypatch.setattr(mod.importlib, "import_module",
                        lambda name: (_ for _ in ()).throw(
                            ModuleNotFoundError(name)))
    status, payload, _ = _post({"action": "steer", "text": "x",
                                "idempotency_key": KEY_A})
    assert status == 503
    assert "steer channel unavailable" in payload["error"]


# ======================================================================= S5 launch
def test_a_successful_claim_launches_the_lane(ctldir, lanes, monkeypatch):
    FakeLauncher.calls = []
    monkeypatch.setattr(mod, "_launcher", lambda: FakeLauncher())
    status, payload, _ = _post({"action": "fire_lane", "lane": "upgrade",
                                "run_id": "abc12345",
                                "worktree": "C:/wt/upgrade",
                                "idempotency_key": KEY_A})
    assert status == 200 and payload["ok"] is True
    assert payload["pid"] == 4242
    assert "running" in payload["detail"]
    assert FakeLauncher.calls == [{"lane": "upgrade", "run_id": "abc12345",
                                   "token": "C:/tmp/lanes/slot0.json"}]


def test_a_launch_failure_is_503_and_is_NOT_remembered(ctldir, lanes, monkeypatch):
    """The idempotency table only remembers SETTLED answers.

    Remembering a launch fault would replay it forever, so the operator's next
    arm - which mints a fresh key anyway - must be able to actually retry.
    """
    boom = FakeLauncher(exc=RuntimeError("git worktree add failed"))
    monkeypatch.setattr(mod, "_launcher", lambda: boom)
    status, payload, _ = _post({"action": "fire_lane", "lane": "upgrade",
                                "run_id": "abc12345",
                                "worktree": "C:/wt/upgrade",
                                "idempotency_key": KEY_A})
    assert status == 503
    assert payload["ok"] is False
    assert "launch failed" in payload["error"]
    assert idem.seen(KEY_A) is None, "a fault must not be replayable"


def test_a_missing_launcher_is_503_and_releases_the_lane(ctldir, monkeypatch):
    fake = FakeLanes()
    monkeypatch.setattr(mod, "_lanes", lambda: fake)

    def _boom():
        raise ModuleNotFoundError("ops.loop.lane_launcher")

    monkeypatch.setattr(mod, "_launcher", _boom)
    status, payload, _ = _post({"action": "fire_lane", "lane": "upgrade",
                                "run_id": "abc12345",
                                "worktree": "C:/wt/upgrade",
                                "idempotency_key": KEY_A})
    assert status == 503
    assert "launcher unavailable" in payload["error"]
    assert fake.released == ["C:/tmp/lanes/slot0.json"], (
        "a lane that cannot launch must be handed straight back")
    assert idem.seen(KEY_A) is None


def test_an_omitted_worktree_is_filled_by_the_server(ctldir, lanes, monkeypatch):
    """The browser must never carry filesystem layout.

    The lock keeps its worktree-mandatory contract; the DEFAULT just comes from
    the launcher instead of from a string in the page.
    """
    FakeLauncher.calls = []
    monkeypatch.setattr(mod, "_launcher", lambda: FakeLauncher())
    monkeypatch.setattr(FakeLauncher, "worktree_path",
                        staticmethod(lambda lane: rf"C:\rc-worktrees\rc-lane-{lane}"),
                        raising=False)
    status, payload, _ = _post({"action": "fire_lane", "lane": "upgrade",
                                "run_id": "abc12345",
                                "idempotency_key": KEY_A})
    assert status == 200 and payload["ok"] is True
    assert fake_worktree_seen(lanes) == r"C:\rc-worktrees\rc-lane-upgrade"


def fake_worktree_seen(lanes):
    return lanes.calls[-1]["worktree"]


def test_an_unresolvable_worktree_is_still_a_400(ctldir, lanes, monkeypatch):
    class NoPath:
        @staticmethod
        def worktree_path(lane):
            raise RuntimeError("no base configured")

    monkeypatch.setattr(mod, "_launcher", lambda: NoPath)
    status, payload, _ = _post({"action": "fire_lane", "lane": "upgrade",
                                "run_id": "abc12345",
                                "idempotency_key": KEY_A})
    assert status == 400
    assert "worktree" in payload["error"]
    assert idem.seen(KEY_A) is None


# ======================================================================= fire_lane
def test_fire_lane_acquires_and_returns_the_token(ctldir, lanes):
    status, payload, _ = _post({"action": "fire_lane", "lane": "uiux",
                                "run_id": "abc12345",
                                "worktree": "C:/wt/uiux",
                                "idempotency_key": KEY_A})
    assert status == 200 and payload["ok"] is True
    assert payload["action"] == "fire_lane"
    assert payload["lane"] == "uiux"
    assert payload["token"] == "C:/tmp/lanes/slot0.json"
    assert lanes.calls == [{"lane": "uiux", "run_id": "abc12345",
                            "worktree": "C:/wt/uiux", "root": None}]


def test_fire_lane_refusal_is_200_ok_false_and_mutates_nothing(ctldir, monkeypatch):
    (ctldir / "cycle.txt").write_text("7", encoding="utf-8")
    fake = FakeLanes(result={"ok": False, "refused": "lane_held",
                             "holder": "upgrade", "pid": 9380})
    monkeypatch.setattr(mod, "_lanes", lambda: fake)

    before = _snapshot(ctldir)
    status, payload, _ = _post({"action": "fire_lane", "lane": "ds",
                                "run_id": "beef0001",
                                "worktree": "C:/wt/ds",
                                "idempotency_key": KEY_A})
    after = _snapshot(ctldir)

    # A refusal is a normal answer, NOT an error status.
    assert status == 200
    assert payload["ok"] is False
    assert payload["refused"] == "lane_held"
    assert payload["holder"] == "upgrade"
    assert payload["pid"] == 9380
    assert after == before


def test_fire_lane_refusal_replay_does_not_retry_the_acquire(ctldir, monkeypatch):
    fake = FakeLanes(result={"ok": False, "refused": "lane_held",
                             "holder": "upgrade", "pid": 9380})
    monkeypatch.setattr(mod, "_lanes", lambda: fake)
    _status, first, _ = _post({"action": "fire_lane", "lane": "ds",
                               "run_id": "beef0001", "worktree": "C:/wt/ds",
                               "idempotency_key": KEY_A})
    status, second, _ = _post({"action": "fire_lane", "lane": "ds",
                               "run_id": "beef0001", "worktree": "C:/wt/ds",
                               "idempotency_key": KEY_A})
    assert status == 200
    assert second.pop("replayed") is True
    assert second == first
    assert len(fake.calls) == 1


def test_fire_lane_replay_does_not_acquire_twice(ctldir, lanes):
    _status, first, _ = _post({"action": "fire_lane", "lane": "repo",
                               "run_id": "cafe0001", "worktree": "C:/wt/repo",
                               "idempotency_key": KEY_A})
    status, second, _ = _post({"action": "fire_lane", "lane": "repo",
                               "run_id": "cafe0001", "worktree": "C:/wt/repo",
                               "idempotency_key": KEY_A})
    assert status == 200
    assert second.pop("replayed") is True
    assert second == first
    assert len(lanes.calls) == 1


def test_fire_lane_missing_key_is_400_and_never_acquires(ctldir, lanes):
    status, payload, _ = _post({"action": "fire_lane", "lane": "repo",
                                "run_id": "cafe0001", "worktree": "C:/wt/repo"})
    assert status == 400 and payload["ok"] is False
    assert lanes.calls == []


def test_fire_lane_unknown_lane_is_400(ctldir, lanes):
    status, payload, _ = _post({"action": "fire_lane", "lane": "nuke",
                                "run_id": "cafe0001", "worktree": "C:/wt/x",
                                "idempotency_key": KEY_A})
    assert status == 400 and payload["ok"] is False
    assert payload["valid"] == list(LANES)
    assert lanes.calls == []


@pytest.mark.parametrize("field", ["run_id", "worktree"])
def test_fire_lane_requires_run_id_and_worktree(ctldir, lanes, field):
    body = {"action": "fire_lane", "lane": "repo", "run_id": "cafe0001",
            "worktree": "C:/wt/repo", "idempotency_key": KEY_A}
    body.pop(field)
    status, payload, _ = _post(body)
    assert status == 400 and payload["ok"] is False
    assert field in payload["error"]
    assert lanes.calls == []


def test_fire_lane_propagates_a_lanes_value_error_as_400(ctldir, monkeypatch):
    class Rejecting(FakeLanes):
        def try_acquire_lane(self, lane, *, run_id, worktree, root=None):
            raise ValueError("worktree is mandatory")

    monkeypatch.setattr(mod, "_lanes", lambda: Rejecting())
    status, payload, _ = _post({"action": "fire_lane", "lane": "repo",
                                "run_id": "cafe0001", "worktree": "C:/Riot Commander",
                                "idempotency_key": KEY_A})
    assert status == 400 and payload["ok"] is False
    assert "worktree is mandatory" in payload["error"]
    assert idem.seen(KEY_A) is None


def test_fire_lane_is_graceful_when_lanes_module_is_absent(ctldir, monkeypatch):
    def boom():
        raise ModuleNotFoundError("No module named 'ops.loop.lanes'")

    monkeypatch.setattr(mod, "_lanes", boom)
    status, payload, _ = _post({"action": "fire_lane", "lane": "repo",
                                "run_id": "cafe0001", "worktree": "C:/wt/repo",
                                "idempotency_key": KEY_A})
    assert status == 503 and payload["ok"] is False
    assert "lanes" in payload["error"]
    assert idem.seen(KEY_A) is None


def test_lanes_import_seam_reads_sys_modules(monkeypatch):
    stub = types.ModuleType("ops.loop.lanes")
    stub.LANES = LANES
    monkeypatch.setitem(sys.modules, "ops.loop.lanes", stub)
    assert mod._lanes() is stub


# ======================================================================= registration
def test_new_actions_are_registered():
    for action in ("stop", "resume", "set_directive", "clear_directive",
                   "fire_lane", "queue_intent"):
        assert action in mod._VALID_ACTIONS


def test_route_is_still_post_only_single_path():
    assert mod.GET_ROUTES == []
    assert len(mod.POST_ROUTES) == 1
    matcher, _fn = mod.POST_ROUTES[0]
    assert matcher("/api/loop-control") is True
    assert matcher("/api/loop-status") is False


# ============================================== regression: the four legacy actions
def test_legacy_stop_shape_is_unchanged(ctldir):
    status, payload, ctype = _post({"action": "stop", "reason": "operator halt"})
    assert status == 200 and ctype == "application/json"
    assert payload == {"ok": True, "action": "stop", "state": "stopped",
                       "detail": "operator halt"}
    assert (ctldir / "STOP").read_text(encoding="utf-8") == "operator halt"


def test_legacy_resume_shape_is_unchanged(ctldir):
    (ctldir / "STOP").write_text("halted", encoding="utf-8")
    status, payload, _ = _post({"action": "resume"})
    assert status == 200
    assert payload == {"ok": True, "action": "resume", "state": "idle",
                       "detail": "STOP cleared"}
    assert not (ctldir / "STOP").exists()


def test_legacy_set_directive_shape_is_unchanged(ctldir):
    status, payload, _ = _post({"action": "set_directive", "text": "Do the thing."})
    assert status == 200
    assert payload == {"ok": True, "action": "set_directive", "state": "idle",
                       "detail": "13 chars queued"}
    assert (ctldir / "directive_override.md").read_text(encoding="utf-8") == "Do the thing."


def test_legacy_clear_directive_shape_is_unchanged(ctldir):
    (ctldir / "directive_override.md").write_text("queued", encoding="utf-8")
    status, payload, _ = _post({"action": "clear_directive"})
    assert status == 200
    assert payload == {"ok": True, "action": "clear_directive", "state": "idle",
                       "detail": "override cleared"}
    assert not (ctldir / "directive_override.md").exists()


def test_legacy_actions_need_no_idempotency_key_and_do_not_fill_the_table(ctldir):
    for body in ({"action": "stop"}, {"action": "resume"},
                 {"action": "set_directive", "text": "x"},
                 {"action": "clear_directive"}):
        status, payload, _ = _post(body)
        assert status == 200 and payload["ok"] is True
        assert "replayed" not in payload
    assert idem.size() == 0


def test_legacy_unknown_action_still_400_with_valid_list(ctldir):
    status, payload, _ = _post({"action": "nuke"})
    assert status == 400 and payload["ok"] is False
    assert "valid" in payload


# ------------------------------------------------- LANE 8 CYCLE 29: concurrency
# The replay gate is a check-then-act. seen() and remember() are each locked,
# but the SEQUENCE seen -> side effect -> remember is not, and the dashboard is
# a ThreadingHTTPServer (dashboard/server.py:54), so two same-key requests run
# on two threads. A retry storm from a wedged phone is CONCURRENT, not
# sequential - which is the one shape this module exists to stop and the one
# shape it did not stop. "interrupt itself is the most important entry in the
# list, because a phone retrying over Tailscale must not kill twice."
def test_concurrent_duplicate_key_fires_the_side_effect_exactly_once(
        ctldir, monkeypatch):
    """Two threads, one key, one side effect - the whole point of the module."""
    # Pin the wait well above this test's own probe windows so the assertions
    # measure the CLAIM protocol, not the shipped INFLIGHT_WAIT_S - which is
    # deliberately short (2 s) and would otherwise time the waiter out mid-probe.
    monkeypatch.setattr(mod, "INFLIGHT_WAIT_S", 30.0)
    calls = []
    entered = threading.Semaphore(0)
    release = threading.Event()

    def _slow_intent(body, key):
        calls.append(key)
        entered.release()
        # Hold the owner inside the side effect so the second thread reaches
        # the gate while the first is provably still mid-flight.
        release.wait(10)
        return 200, {"ok": True, "action": "queue_intent", "intent": "halt_save",
                     "detail": "halt_save queued", "state": "stopped"}

    monkeypatch.setattr(mod, "_queue_intent", _slow_intent)
    body = {"action": "queue_intent", "intent": "halt_save",
            "idempotency_key": KEY_A}
    out = {}

    def run(tag):
        out[tag] = mod.apply_action("queue_intent", dict(body))

    a = threading.Thread(target=run, args=("a",), name="idem-a")
    a.start()
    assert entered.acquire(timeout=10), "thread A never entered the side effect"

    b = threading.Thread(target=run, args=("b",), name="idem-b")
    b.start()
    # B either enters the side effect too (the defect - observed immediately)
    # or blocks on A's claim (correct). Both outcomes are observable, so this
    # is deterministic in each direction rather than a sleep race.
    doubled = entered.acquire(timeout=2.0)
    release.set()
    a.join(10)
    b.join(10)

    assert not doubled, "both threads ran the side effect - the gate is not atomic"
    assert calls == [KEY_A], f"the side effect ran {len(calls)} times, expected 1"
    assert not a.is_alive() and not b.is_alive()
    assert out["a"][0] == 200 and out["b"][0] == 200
    # The waiter gets the OWNER's settled answer, unchanged, flagged replayed -
    # the same contract a sequential replay already had, so the client in
    # web/mc/mc.js needs no change.
    assert out["b"][1]["replayed"] is True
    assert out["b"][1]["detail"] == "halt_save queued"
    assert "replayed" not in out["a"][1]


def test_a_waiter_acts_when_the_owner_abandons_a_non_200(ctldir, monkeypatch):
    """A 400/503 is not an answer to replay - it is a request that never
    happened, so the second caller must be allowed to act rather than inherit
    the failure. Pins the abandon path, not just the settle path."""
    # Pin the wait well above this test's own probe windows so the assertions
    # measure the CLAIM protocol, not the shipped INFLIGHT_WAIT_S - which is
    # deliberately short (2 s) and would otherwise time the waiter out mid-probe.
    monkeypatch.setattr(mod, "INFLIGHT_WAIT_S", 30.0)
    calls = []
    entered = threading.Semaphore(0)
    release = threading.Event()

    def _flaky(body, key):
        calls.append(key)
        entered.release()
        if len(calls) == 1:
            release.wait(10)
            return 503, {"ok": False, "action": "queue_intent", "error": "busy"}
        return 200, {"ok": True, "action": "queue_intent", "detail": "second won"}

    monkeypatch.setattr(mod, "_queue_intent", _flaky)
    body = {"action": "queue_intent", "intent": "halt_save",
            "idempotency_key": KEY_B}
    out = {}

    def run(tag):
        out[tag] = mod.apply_action("queue_intent", dict(body))

    a = threading.Thread(target=run, args=("a",), name="abandon-a")
    a.start()
    assert entered.acquire(timeout=10)
    b = threading.Thread(target=run, args=("b",), name="abandon-b")
    b.start()
    # B must WAIT for A rather than act alongside it. Without this assertion the
    # test passes on the UNFIXED check-then-act too - both threads act there, so
    # every remaining assertion below is satisfied for the wrong reason and the
    # test pins nothing. Caught by an adversarial pass, not by the mutation run,
    # because mutating `abandon` to `settle` does kill it while a full revert
    # does not (feedback_parallel_slice_stubs_and_vacuous_regression_tests).
    assert not entered.acquire(timeout=2.0),         "B ran the side effect while A still owned the key"
    release.set()
    a.join(10)
    b.join(10)

    assert out["a"][0] == 503, "the owner's own failure must reach the owner"
    assert out["b"][0] == 200, "the waiter inherited a failure it should retry"
    assert calls == [KEY_B, KEY_B], "the waiter never got to act"
    assert idem.size() == 1, "only the settled 200 is remembered"


def test_an_in_flight_duplicate_is_refused_in_a_shape_every_panel_renders(
        ctldir, monkeypatch):
    """A duplicate that outlasts the wait is REFUSED, not reported as failed.

    Each Mission Control panel renders its own way and only _mcFire
    (web/mc/mc.js:161, queue_intent) treats a bare ok=false as a refusal;
    _mcFireLane (mc.js:221) and _mcIrqFire (mc.js:363) branch on `refused` and
    otherwise fall through to "<label> failed:". Without `refused` the operator
    would be told a still-running INTERRUPT had FAILED. The text must also not
    invite a re-send: every client mints a fresh key per send, so a retry is a
    new key this gate cannot dedupe, and it would run the side effect twice.
    """
    monkeypatch.setattr(mod, "INFLIGHT_WAIT_S", 0.05)
    release = threading.Event()
    entered = threading.Semaphore(0)

    def _slow_intent(body, key):
        entered.release()
        release.wait(10)
        return 200, {"ok": True, "action": "queue_intent", "detail": "done"}

    monkeypatch.setattr(mod, "_queue_intent", _slow_intent)
    body = {"action": "queue_intent", "intent": "halt_save",
            "idempotency_key": KEY_A}
    out = {}
    a = threading.Thread(target=lambda: out.setdefault(
        "a", mod.apply_action("queue_intent", dict(body))), name="slow-a")
    a.start()
    assert entered.acquire(timeout=10), "the owner never entered the side effect"

    status, payload = mod.apply_action("queue_intent", dict(body))
    release.set()
    a.join(10)

    assert status == 200, "must not be 503 - mc.js:51 calls every 503 an auth fault"
    assert payload["ok"] is False
    assert payload["in_flight"] is True
    assert payload["refused"] == "in_flight",         "without `refused` the lane and interrupt panels render this as FAILED"
    assert "do not re-send" in payload["detail"]
    assert "retry" not in payload["detail"],         "advising a retry mints a NEW key, which this gate cannot dedupe"


def test_a_raising_settle_still_releases_the_claim(ctldir, monkeypatch):
    """The claim is released even when settle() ITSELF raises.

    _INFLIGHT has no TTL and purge() does not touch it, so a key left reserved
    is reserved until the process restarts: every later request on it blocks
    for INFLIGHT_WAIT_S and is then refused, forever. Guarding only the side
    effect misses this, because settle -> remember -> _remember_locked
    deep-copies the payload BEFORE releasing. Raised by an adversarial pass
    after the first version of the unwind covered the side effect alone.
    """
    monkeypatch.setattr(mod, "_queue_intent",
                        lambda body, key: (200, {"ok": True, "action": "x"}))

    def _boom(key, result, ttl_s=None):
        raise RuntimeError("settle exploded")

    monkeypatch.setattr(idem, "settle", _boom)
    body = {"action": "queue_intent", "intent": "halt_save",
            "idempotency_key": KEY_A}
    with pytest.raises(RuntimeError):
        mod.apply_action("queue_intent", dict(body))

    # The key must be claimable again - NOT stuck reporting inflight.
    state, _value = idem.claim(KEY_A)
    assert state == "claimed", (
        f"the claim was stranded: claim() returned {state!r}. Every later "
        "request on this key would block then be refused until restart.")
