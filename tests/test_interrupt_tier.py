# arch: tests for the Mission Control INTERRUPT tier (S9) | section=tests | frozen=no
"""S9 - the tier that actually stops a turn and kills agents.

NOTE and STEER (S7) execute nothing, which is what makes them safe on a single
click. INTERRUPT is a different act and gets a different contract, stated by
`docs/MISSION_CONTROL_PLAN.md`: "the button must NAME the agents it will kill
before you confirm."

Naming them is the easy half. The half these tests exist for is that a name
shown at preview time is a claim about a moment that has already passed. A
process set can change between the preview and the confirm - a worker exits, a
lane is reclaimed, a new lane fires, Windows reuses the pid. A confirm that
just re-enumerates and kills whatever it finds would kill processes the
operator never saw, while the UI truthfully reported the ones it did. The
victim list would be honest and the kill would still be wrong.

So the preview mints a FINGERPRINT over the exact victim set, the confirm
carries it back, and the server re-probes and REFUSES on any mismatch. That is
what turns "named before the confirm" from a UI courtesy into an enforced
property. The fingerprint covers process START TIME as well as pid, because pid
alone cannot tell a live worker from its recycled number.

Every seam that touches a real process (enumeration, killing) is injected. No
test in this file may kill anything.
"""
from __future__ import annotations

import importlib

import pytest

interrupt = importlib.import_module("ops.loop.interrupt")
steer = importlib.import_module("ops.loop.steer")


# --------------------------------------------------------------------------- helpers
def _proc(pid, name="claude.exe", started=1000.0, cmdline="claude -p", ppid=0):
    """One row in the shape the probe seam yields."""
    return {"pid": pid, "name": name, "started": started,
            "cmdline": cmdline, "ppid": ppid}


@pytest.fixture
def chan(tmp_path, monkeypatch):
    """Sandbox the steer log so the interrupt audit trail lands in tmp."""
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(steer, "CONTROL_DIR", ctl)
    monkeypatch.setattr(steer, "STEER_LOG", ctl / "STEER.jsonl")
    monkeypatch.setattr(steer, "STEER_CURSOR", ctl / "STEER.cursor")
    return ctl


class FakeKiller:
    """Records what it was asked to kill. Kills nothing."""

    def __init__(self, fail=()):
        self.killed = []
        self.fail = set(fail)

    def __call__(self, pid):
        self.killed.append(pid)
        return pid not in self.fail


# --------------------------------------------------------------------------- naming
def test_preview_names_the_lane_holder(monkeypatch):
    """The whole point: the operator sees WHICH process dies, before confirming."""
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [
        {"pid": 4242, "kind": "lane", "lane": "ds", "run_id": "abc123"}])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [
        _proc(4242, name="powershell.exe", cmdline="run_lane.ps1 -Lane ds")])

    out = interrupt.preview()

    assert out["count"] == 1
    victim = out["victims"][0]
    assert victim["pid"] == 4242
    assert victim["kind"] == "lane"
    assert victim["lane"] == "ds"
    assert victim["name"] == "powershell.exe"


def test_preview_includes_descendants_not_just_the_lock_holder(monkeypatch):
    """A lane is powershell -> claude. Killing only the holder orphans the worker.

    The lock records the powershell pid; the process doing the work is its
    child. A victim list naming only the parent would let the operator confirm
    a kill that leaves the real agent running.
    """
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [
        {"pid": 100, "kind": "lane", "lane": "repo", "run_id": "r1"}])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [
        _proc(100, name="powershell.exe"),
        _proc(201, name="claude.exe", ppid=100),
        _proc(302, name="node.exe", ppid=201),
    ])

    out = interrupt.preview()

    assert [v["pid"] for v in out["victims"]] == [100, 201, 302]
    assert out["victims"][1]["kind"] == "child"
    assert out["victims"][2]["kind"] == "child"


def test_preview_with_nothing_running_names_nobody(monkeypatch):
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [])

    out = interrupt.preview()

    assert out["count"] == 0
    assert out["victims"] == []
    assert out["fingerprint"] == interrupt.EMPTY_FINGERPRINT


# --------------------------------------------------------------------------- fingerprint
def test_fingerprint_is_stable_for_the_same_victim_set():
    a = [_proc(1), _proc(2)]
    assert interrupt.fingerprint(a) == interrupt.fingerprint(list(reversed(a)))


def test_fingerprint_changes_when_a_victim_joins():
    before = interrupt.fingerprint([_proc(1)])
    after = interrupt.fingerprint([_proc(1), _proc(2)])
    assert before != after


def test_fingerprint_changes_when_a_victim_leaves():
    before = interrupt.fingerprint([_proc(1), _proc(2)])
    after = interrupt.fingerprint([_proc(1)])
    assert before != after


def test_fingerprint_distinguishes_a_recycled_pid(chan):
    """Same pid, different process. Windows reuses pids and the confirm must not.

    This is the case a pid-only fingerprint cannot see: the previewed worker
    exits, Windows hands its number to something unrelated, and the confirm
    kills a stranger while reporting the name the operator approved.
    """
    original = interrupt.fingerprint([_proc(5150, started=1000.0)])
    recycled = interrupt.fingerprint([_proc(5150, started=9999.0)])
    assert original != recycled


# --------------------------------------------------------------------------- the guard
def test_execute_refuses_a_stale_fingerprint_and_kills_nothing(chan, monkeypatch):
    """The TOCTOU guard. A changed process set means the operator's list is a lie."""
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [
        {"pid": 100, "kind": "lane", "lane": "ds", "run_id": "r1"}])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [_proc(100)])
    stale = interrupt.preview()["fingerprint"]

    # The world moves: the previewed worker is gone, a different one is up.
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [
        {"pid": 777, "kind": "lane", "lane": "uiux", "run_id": "r2"}])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [_proc(777)])
    killer = FakeKiller()

    out = interrupt.execute(stale, key="k1", killer=killer)

    assert out["ok"] is False
    assert out["refused"] == "victims_changed"
    assert killer.killed == []
    # And the caller is told what it would have been, so the UI can re-arm.
    assert out["fingerprint"] != stale
    assert [v["pid"] for v in out["victims"]] == [777]


def test_execute_kills_exactly_the_named_pids(chan, monkeypatch):
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [
        {"pid": 100, "kind": "lane", "lane": "ds", "run_id": "r1"}])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [
        _proc(100, name="powershell.exe"), _proc(201, name="claude.exe", ppid=100)])
    fp = interrupt.preview()["fingerprint"]
    killer = FakeKiller()

    out = interrupt.execute(fp, key="k1", killer=killer)

    assert out["ok"] is True
    assert sorted(killer.killed) == [100, 201]
    assert out["killed"] == [201, 100]


def test_execute_kills_children_before_parents(chan, monkeypatch):
    """Reap the leaf first, or the parent's exit re-parents a live child away.

    Killing powershell first hands its claude child to the OS and the next
    enumeration no longer links them, so the child survives an interrupt that
    reported success.
    """
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [
        {"pid": 10, "kind": "lane", "lane": "ds", "run_id": "r1"}])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [
        _proc(10, name="powershell.exe"),
        _proc(20, name="claude.exe", ppid=10),
        _proc(30, name="node.exe", ppid=20),
    ])
    fp = interrupt.preview()["fingerprint"]
    killer = FakeKiller()

    interrupt.execute(fp, key="k1", killer=killer)

    assert killer.killed == [30, 20, 10]


def test_execute_refuses_when_there_is_nobody_to_kill(chan, monkeypatch):
    """An empty interrupt is a mis-click, not a success."""
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [])
    killer = FakeKiller()

    out = interrupt.execute(interrupt.EMPTY_FINGERPRINT, key="k1", killer=killer)

    assert out["ok"] is False
    assert out["refused"] == "no_victims"
    assert killer.killed == []


def test_execute_reports_a_victim_it_could_not_kill(chan, monkeypatch):
    """Partial failure must be visible - a silent partial kill reads as done."""
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [
        {"pid": 100, "kind": "lane", "lane": "ds", "run_id": "r1"}])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [
        _proc(100), _proc(201, ppid=100)])
    fp = interrupt.preview()["fingerprint"]
    killer = FakeKiller(fail={100})

    out = interrupt.execute(fp, key="k1", killer=killer)

    assert out["ok"] is False
    assert out["failed"] == [100]
    assert out["killed"] == [201]


# --------------------------------------------------------------------------- audit trail
def test_an_executed_interrupt_is_recorded_in_the_steer_log(chan, monkeypatch):
    """Every accepted, refused and collapsed event lands in the safety ledger."""
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [
        {"pid": 100, "kind": "lane", "lane": "ds", "run_id": "r1"}])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [_proc(100)])
    fp = interrupt.preview()["fingerprint"]

    interrupt.execute(fp, key="k9", killer=FakeKiller())

    logged = steer._read_all()
    assert len(logged) == 1
    assert logged[0]["tier"] == interrupt.TIER
    assert logged[0]["key"] == "k9"
    assert "100" in logged[0]["text"]


def test_a_refused_interrupt_is_also_recorded(chan, monkeypatch):
    """A refusal that leaves no trace is a mis-fire nobody can audit later."""
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [])

    interrupt.execute(interrupt.EMPTY_FINGERPRINT, key="k8", killer=FakeKiller())

    logged = steer._read_all()
    assert len(logged) == 1
    assert logged[0]["tier"] == interrupt.TIER
    assert "no_victims" in logged[0]["text"]


def test_the_audit_record_survives_a_steer_log_failure(chan, monkeypatch):
    """A broken ledger must not turn a real interrupt into an exception.

    The kill has already happened by then; raising would tell the caller the
    interrupt failed while the processes are gone.
    """
    monkeypatch.setattr(interrupt, "_holders", lambda root=None: [
        {"pid": 100, "kind": "lane", "lane": "ds", "run_id": "r1"}])
    monkeypatch.setattr(interrupt, "_probe", lambda pids: [_proc(100)])
    fp = interrupt.preview()["fingerprint"]

    def boom(*a, **kw):
        raise OSError("ledger unwritable")

    monkeypatch.setattr(interrupt, "_record", boom)
    out = interrupt.execute(fp, key="k1", killer=FakeKiller())

    assert out["ok"] is True


# --------------------------------------------------------------------------- taskkill argv
def test_taskkill_does_not_pass_the_tree_flag():
    """/T would let taskkill walk the tree ITSELF and kill what it finds now.

    This module already enumerated the tree and named every member to the
    operator. Handing the walk to taskkill re-does it at kill time, so any
    descendant spawned after the preview dies unnamed - the exact hazard the
    fingerprint exists to prevent, reintroduced one argv entry later.

    Pinned as exact argv because it was previously documented in a docstring
    and enforced by nothing: adding /T left all 124 tests green. The repo
    already pins argv this way in tests/test_loop_executor.py.
    """
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)

        class R:
            returncode = 0
        return R()

    import subprocess as sp
    real = sp.run
    sp.run = fake_run
    try:
        interrupt._taskkill(1234)
    finally:
        sp.run = real

    assert seen["cmd"] == ["taskkill", "/F", "/PID", "1234"]
    assert "/T" not in seen["cmd"]


def test_enumeration_without_psutil_refuses_rather_than_naming_a_partial_list(
        monkeypatch):
    """A degraded probe would drop every descendant AND void the recycled-pid
    guard, behind one log line. Refuse instead."""
    import builtins
    real_import = builtins.__import__

    def no_psutil(name, *a, **kw):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_psutil)
    with pytest.raises(interrupt.InterruptUnavailable):
        interrupt._probe([4242])


# --------------------------------------------------------------------------- no downgrade
def test_the_guidance_channel_refuses_to_carry_an_interrupt(chan):
    """INTERRUPT must never be silently demoted to a NOTE.

    `normalize_tier` maps every unknown tier to the default, so before this
    guard a caller asking for tier="interrupt" on the guidance path got a note
    that executes nothing - a button that reports it killed the agents and did
    not. The plan is explicit: INTERRUPT is "never downgraded to a note".
    """
    with pytest.raises(ValueError):
        steer.append("stop everything", tier=interrupt.TIER)


def test_interrupt_is_not_a_guidance_tier():
    assert interrupt.TIER not in steer.TIERS
