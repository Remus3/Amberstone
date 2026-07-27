"""F1 P3 concurrency governor: slots, named mutexes, single-controller lock.

Ported from the Sibling-A suite (LW head 8a7d61a, 2026-07-26). These are
the tests that have to be right BEFORE any live concurrent LW+RC run, because
the failure they guard against is not a crash - it is two loops quietly
double-booking a shared resource and blaming the result on something else.

ops/loop/slots.py and ops/loop/winmutex.py are BYTE-IDENTICAL across both repos
by contract, so nothing here may assume RC paths; every test injects its own
root. test_shared_modules_are_byte_identical_to_lw is the mirror-side drift
guard the LW handoff asked for.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LW_ROOT = Path(r"C:\Sibling-A")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"rc_loop_{name}_under_test", ROOT / "ops" / "loop" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


slots = _load("slots")
winmutex = _load("winmutex")


# ---- mirror-side drift guard ------------------------------------------------

@pytest.mark.parametrize("name", ["slots.py", "winmutex.py"])
def test_shared_modules_are_byte_identical_to_lw(name: str):
    """A divergence here is not a merge conflict anyone notices - it is a silent
    concurrency bug where both loops believe they hold the only slot."""
    lw = LW_ROOT / "ops" / "loop" / name
    if not lw.is_file():
        pytest.skip("Sibling-A tree not present on this machine")
    rc = ROOT / "ops" / "loop" / name
    assert hashlib.sha256(rc.read_bytes()).hexdigest() == \
        hashlib.sha256(lw.read_bytes()).hexdigest(), \
        f"{name} has drifted from the Sibling-A copy - they are shared by contract"


# ---- the core invariant: never more than max_slots holders -----------------

def test_eight_threads_never_exceed_two_concurrent_holders(tmp_path: Path):
    """THE acceptance invariant. 8 contenders, 2 slots, sampled continuously."""
    live = 0
    peak = 0
    lock = threading.Lock()
    errors: list = []

    def worker(i: int):
        nonlocal live, peak
        try:
            with slots.hold(2, root=tmp_path, run_id=f"r{i}", cycle=i,
                            backoff=0.02, jitter=0.02, timeout=30):
                with lock:
                    live += 1
                    peak = max(peak, live)
                time.sleep(0.05)
                with lock:
                    live -= 1
        except Exception as e:  # noqa: BLE001 - surface, do not swallow
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors
    assert peak <= 2, f"slot governor breached: {peak} concurrent holders"
    assert peak == 2, "with 8 contenders both slots should have been used"


def test_all_slots_are_released_after_use(tmp_path: Path):
    with slots.hold(2, root=tmp_path, backoff=0.01, jitter=0.01):
        assert len(list(tmp_path.glob("*.lock"))) == 1
    assert list(tmp_path.glob("*.lock")) == [], "a slot leaked"


def test_slot_is_released_even_when_the_body_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        with slots.hold(1, root=tmp_path, backoff=0.01, jitter=0.01):
            raise ValueError("boom")
    assert list(tmp_path.glob("*.lock")) == [], "an exception leaked a slot"


def test_timeout_raises_rather_than_proceeding_unslotted(tmp_path: Path):
    """A caller that cannot get a slot must fail, never run anyway."""
    with slots.hold(1, root=tmp_path, backoff=0.01, jitter=0.01):
        with pytest.raises(slots.SlotTimeout):
            with slots.hold(1, root=tmp_path, backoff=0.01, jitter=0.01, timeout=0.2):
                pytest.fail("acquired a slot that was already held")


# ---- reaping: a crashed holder must not deadlock the other repo ------------

def test_lock_held_by_a_dead_pid_is_reaped(tmp_path: Path):
    """FAIL-OPEN by design: a stale lock is reclaimed, never respected forever."""
    dead = tmp_path / "0.lock"
    dead.write_text(json.dumps({"pid": 999999999, "repo": "ghost",
                                "run_id": "x", "cycle": 1, "ts": time.time()}),
                    encoding="utf-8")
    assert slots.is_stale(dead, slots.DEFAULT_STALE_AFTER) is True
    with slots.hold(1, root=tmp_path, backoff=0.01, jitter=0.01, timeout=5) as s:
        assert s.name == "0.lock", "the dead holder's slot should be reused"


def test_lock_older_than_stale_after_is_reaped(tmp_path: Path):
    old = tmp_path / "0.lock"
    old.write_text(json.dumps({"pid": os.getpid(), "ts": time.time() - 10_000}),
                   encoding="utf-8")
    assert slots.is_stale(old, stale_after=100.0) is True


def test_live_holder_is_not_reaped(tmp_path: Path):
    """The reaper must not steal a slot from a running process."""
    mine = tmp_path / "0.lock"
    mine.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}),
                    encoding="utf-8")
    assert slots.is_stale(mine, slots.DEFAULT_STALE_AFTER) is False
    assert slots.reap(tmp_path, 1, slots.DEFAULT_STALE_AFTER) == 0


def test_corrupt_lock_cannot_wedge_the_bucket_forever(tmp_path: Path):
    bad = tmp_path / "0.lock"
    bad.write_text("{ not json", encoding="utf-8")
    os.utime(bad, (time.time() - 10_000, time.time() - 10_000))
    assert slots.is_stale(bad, stale_after=100.0) is True


def test_pid_alive_is_true_for_this_process():
    assert slots.pid_alive(os.getpid()) is True


def test_pid_alive_is_false_for_an_impossible_pid():
    assert slots.pid_alive(999999999) is False
    assert slots.pid_alive(0) is False


def test_lock_payload_identifies_the_holder(tmp_path: Path):
    """Cross-repo debugging depends on this: which repo, which run, which cycle."""
    with slots.hold(1, root=tmp_path, repo="RC", run_id="abc123", cycle=7,
                    backoff=0.01, jitter=0.01) as s:
        rec = json.loads(s.read_text(encoding="utf-8"))
    assert rec["repo"] == "RC"
    assert rec["run_id"] == "abc123"
    assert rec["cycle"] == 7
    assert rec["pid"] == os.getpid()


# ---- one controller per repo ------------------------------------------------

def _dry_cfg(tmp_path: Path, ctl: Path, **over):
    cfg = json.loads((ROOT / "ops" / "loop" / "config.dry.json").read_text(encoding="utf-8"))
    cfg.update({"control_dir": str(ctl), "max_cycles": 1, "poll_sec": 1,
                "fixed_directive": "noop", "session_jsonl": ""})
    cfg.update(over)
    cfgp = tmp_path / "cfg.json"
    cfgp.write_text(json.dumps(cfg), encoding="utf-8")
    return cfgp


def test_second_controller_in_the_same_repo_exits_nonzero(tmp_path: Path):
    """Concurrency ACROSS repos is the goal; within one repo it is corruption.

    The control_dir handshake files are not namespaced, so two controllers in
    one repo would consume each other's gemini.ready and claude.done.
    """
    ctl = tmp_path / "control"
    ctl.mkdir()
    cfgp = _dry_cfg(tmp_path, ctl, cycle_deadline_sec=5)

    # A lock held by THIS process: a live pid that is not the controller's.
    (ctl / "RUNNING.lock").write_text(
        json.dumps({"pid": os.getpid(), "run_id": "held", "ts": time.time()}),
        encoding="utf-8")

    r = subprocess.run([sys.executable, str(ROOT / "ops" / "loop" / "loop_controller.py"),
                        str(cfgp)], capture_output=True, text=True, timeout=120)
    assert r.returncode != 0, "a second controller must refuse to start"
    assert "already running" in (r.stderr + r.stdout)


def test_controller_reclaims_a_lock_held_by_a_dead_pid(tmp_path: Path):
    """Fail-open: a crashed controller must not lock the repo out forever."""
    ctl = tmp_path / "control"
    ctl.mkdir()
    cfgp = _dry_cfg(tmp_path, ctl, cycle_deadline_sec=3)
    (ctl / "RUNNING.lock").write_text(
        json.dumps({"pid": 999999999, "run_id": "ghost", "ts": time.time()}),
        encoding="utf-8")

    # Only the CLAIM is under test, so poll for it and kill - letting the cycle
    # run to completion would add two minutes of AHK-handshake timeout per run.
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "ops" / "loop" / "loop_controller.py"), str(cfgp)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        claimed = False
        for _ in range(150):
            if (ctl / "run_id.txt").is_file():
                claimed = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert claimed, "a dead holder must not block a new run from claiming the repo"
        rec = json.loads((ctl / "RUNNING.lock").read_text(encoding="utf-8"))
        assert rec["pid"] == proc.pid, "the live controller should own the lock now"
    finally:
        proc.kill()
        proc.wait(timeout=30)


# ---- named mutexes ---------------------------------------------------------

def test_mutex_is_reentrant_for_the_same_thread():
    """Windows mutexes are owned per-thread; nesting must not self-deadlock."""
    with winmutex.hold("Global\\LWRC_TEST_RC_NEST", timeout=5):
        with winmutex.hold("Global\\LWRC_TEST_RC_NEST", timeout=5):
            pass


def test_mutex_serializes_two_threads():
    live = 0
    peak = 0
    lock = threading.Lock()

    def worker():
        nonlocal live, peak
        with winmutex.hold("Global\\LWRC_TEST_RC_SERIAL", timeout=30):
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.05)
            with lock:
                live -= 1

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    assert peak == 1, f"mutex allowed {peak} concurrent holders"


def test_mutex_names_are_the_shared_contract():
    """Both repos must use the SAME names or they serialize against nothing."""
    assert winmutex.GEMINI_MUTEX == "Global\\LWRC_GEMINI"
    assert winmutex.GPU_MUTEX == "Global\\LW_GPU"


@pytest.mark.skipif(sys.platform != "win32", reason="windows mutex semantics")
def test_mutex_timeout_raises_when_held_elsewhere():
    got = threading.Event()
    release = threading.Event()

    def holder():
        with winmutex.hold("Global\\LWRC_TEST_RC_TIMEOUT", timeout=10):
            got.set()
            release.wait(timeout=10)

    t = threading.Thread(target=holder)
    t.start()
    assert got.wait(timeout=10)
    try:
        with pytest.raises(winmutex.MutexTimeout):
            with winmutex.hold("Global\\LWRC_TEST_RC_TIMEOUT", timeout=0.2):
                pytest.fail("acquired a mutex held by another thread")
    finally:
        release.set()
        t.join(timeout=10)
