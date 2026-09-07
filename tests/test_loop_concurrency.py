"""F1 P3 concurrency governor: slots, named mutexes, single-controller lock.

Ported from the Sibling-A suite (carrier head 8a7d61a, 2026-07-26). These are
the tests that have to be right BEFORE any live concurrent carrier plus RC run, because
the failure they guard against is not a crash - it is two loops quietly
double-booking a shared resource and blaming the result on something else.

ops/loop/slots.py and ops/loop/winmutex.py are BYTE-IDENTICAL across both repos
by contract, so nothing here may assume RC paths; every test injects its own
root. test_shared_modules_are_byte_identical_to_the_carrier is the mirror-side drift
guard the carrier handoff asked for.
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


def _sibling_roots() -> list[Path]:
    """Where the byte-identical carrier repos live ON THIS MACHINE.

    Read from the same per-host config the cross-repo inbox poller uses
    (`ops/moon_sync_repos.json`, gitignored, `RC_MOON_SYNC_REPOS` overrides),
    because those paths name private sibling projects and differ per install.

    LOAD-BEARING, and the failure mode is quiet: every cross-repo guard below
    SKIPS when the sibling tree is missing, so a wrong or empty value here
    surfaces as SKIPs that read as green rather than as a red test. If you are
    relying on the byte-identity guard, assert it actually ran.
    """
    raw = os.environ.get("RC_MOON_SYNC_REPOS", "")
    if raw:
        return [Path(p.strip()) for p in raw.split(os.pathsep) if p.strip()]
    try:
        blob = json.loads(
            (ROOT / "ops" / "moon_sync_repos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Path(str(p)) for p in (blob.get("repos") or []) if str(p).strip()]


def _carrier_copy(relative: Path):
    """The first sibling checkout that actually carries `relative`, or None."""
    for root in _sibling_roots():
        cand = root / relative
        if cand.is_file():
            return cand
    return None


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
def test_shared_modules_are_byte_identical_to_the_carrier(name: str):
    """A divergence here is not a merge conflict anyone notices - it is a silent
    concurrency bug where both loops believe they hold the only slot."""
    other = _carrier_copy(Path("ops") / "loop" / name)
    if other is None:
        pytest.skip("no sibling carrier checkout configured on this machine")
    rc = ROOT / "ops" / "loop" / name
    assert hashlib.sha256(rc.read_bytes()).hexdigest() == \
        hashlib.sha256(other.read_bytes()).hexdigest(), \
        f"{name} has drifted from the sibling carrier copy - shared by contract"


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

@pytest.mark.skipif(sys.platform != "win32", reason="windows mutex semantics")
def test_mutex_is_reentrant_for_the_same_thread():
    """Windows mutexes are owned per-thread; nesting must not self-deadlock.

    Skipped off win32 for the same reason as the serialization test below, but
    it hid better because it fails the other way: the POSIX no-op nests happily,
    so this went GREEN on every Linux checkout while proving nothing about
    re-entrancy. A vacuous pass is worse than a red - it reports coverage no
    non-Windows run has ever actually exercised.
    """
    with winmutex.hold("Global\\LWRC_TEST_RC_NEST", timeout=5):
        with winmutex.hold("Global\\LWRC_TEST_RC_NEST", timeout=5):
            pass


@pytest.mark.skipif(sys.platform != "win32", reason="windows mutex semantics")
def test_mutex_serializes_two_threads():
    """peak == 1 is assertable only where the primitive EXISTS. hold() short
    circuits at winmutex.py:57 on any non-win32 platform and yields unheld by
    design, so off Windows this asserted a guarantee the module openly declines
    to make - it was red on every Linux checkout including nightly CI run
    30261946219. The absent thing is the Win32 named-mutex NAMESPACE, an
    environment capability, which is exactly what the skip doctrine reserves a
    skip for; the code under test is present and fine. Coverage is not dropped:
    the three test_posix_no_op_* tests below pin the other branch, and they run
    on EVERY platform because they reach it by monkeypatching sys.platform.
    """
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
    """All three repos must use the SAME names or they serialize against nothing.

    ROTATED 2026-09-06 in carrier commit `1de8d4e`, operator-approved, and copied here
    in the same round. The names are now opaque:

        Global\\LWRC_GEMINI  ->  Global\\MX-7C41A9E2
        Global\\LW_GPU       ->  Global\\MX-2E58D3B6

    This is the FIRST re-pin of winmutex.py that is not docstring-only - the
    values move, so a tree on the old names serializes against nothing while
    looking healthy. That is why the rotation was executed with every loop
    stopped: between the first tree landing the new names and the last, two
    loops can hold DIFFERENT names and both believe they are exclusive. Not a
    broken build - the mutual exclusion silently absent.

    RC verified the precondition on its own box before copying: no live
    loop_controller (the RUNNING.lock pid was dead), and an empty
    C:\\ProgramData\\shared-loop\\slots.
    """
    assert winmutex.GEMINI_MUTEX == "Global\\MX-7C41A9E2"
    assert winmutex.GPU_MUTEX == "Global\\MX-2E58D3B6"


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


def test_acquired_is_logged_only_when_actually_held():
    """ACQUIRED must be gated on a real acquisition, and the fail-open path must
    emit a DISTINCT marker. An unconditional ACQUIRED opens a window that the
    gated RELEASED never closes, so the one case where the mutex did NOT
    serialize becomes the one case invisible to the overlap check."""
    src = (ROOT / "ops" / "loop" / "winmutex.py").read_text(encoding="utf-8")
    body = src[src.index("acquired = rc in"):src.index("yield handle")]
    assert "if acquired:" in body, "ACQUIRED must be gated on acquired"
    assert "UNSERIALIZED" in body, "the fail-open branch needs a distinct marker"
    gated = body[body.index("if acquired:"):]
    assert "ACQUIRED" in gated


def test_unserialized_marker_wording_is_the_judge_contract():
    """p5_probe greps for this exact token; every emit site must use it."""
    src = (ROOT / "ops" / "loop" / "winmutex.py").read_text(encoding="utf-8")
    assert src.count("winmutex: UNSERIALIZED") == 3, (
        "all three unserialized paths (CreateMutexW failure, unexpected wait "
        "result, and the non-Windows no-op) must emit the same marker the "
        "judge hard-fails on")


def test_posix_no_op_branch_is_traced_not_silent(monkeypatch):
    """f1-phase6 item 9. Off Windows there is no named-mutex primitive, so hold
    degrades to a no-op - which is defensible. Yielding SILENTLY is not: every
    overlap guard in this file then passes VACUOUSLY on a POSIX runner, and the
    controller.log the judge reads carries no trace that nothing was serialized.
    Rejected alternative: an fcntl fallback. POSIX record locks are per-PROCESS,
    so test_mutex_serializes_two_threads (threads in ONE process) would stay red
    without a second RLock layer - the wrong size of change for a file that is
    byte-identical across two repos."""
    lines: list[str] = []
    monkeypatch.setattr(sys, "platform", "linux")
    with winmutex.hold("Global\\LWRC_TEST_RC_POSIX", timeout=5, log=lines.append) as h:
        assert h is None, "the POSIX branch holds no handle"
    assert any(ln.startswith("winmutex: UNSERIALIZED Global\\LWRC_TEST_RC_POSIX")
               for ln in lines), \
        f"the no-op branch must emit the judge's marker, got {lines!r}"
    assert not any("ACQUIRED" in ln for ln in lines), \
        "a no-op must never claim ACQUIRED - it would open a window RELEASED never closes"


def test_posix_no_op_branch_survives_a_caller_that_passes_no_log(monkeypatch):
    """log= is optional on the two Windows fail-open branches; the new one must
    stay optional too or an unlogged caller crashes off-Windows."""
    monkeypatch.setattr(sys, "platform", "linux")
    with winmutex.hold("Global\\LWRC_TEST_RC_POSIX_NOLOG") as h:
        assert h is None


def test_posix_no_op_lets_a_second_caller_in_while_the_first_holds(monkeypatch):
    """The POSIX mirror of test_mutex_timeout_raises_when_held_elsewhere, and
    the half that test_mutex_serializes_two_threads stops covering off Windows.
    The marker assertions above prove the no-op ANNOUNCES itself; only an actual
    second entry into a held name proves what it is announcing, and it must be
    proven rather than assumed - a future fcntl or RLock fallback would keep
    emitting the marker while quietly changing this behaviour, and the guard
    that noticed would be the one deleted as redundant.

    Overlap is established by events, not by timing: the first caller is parked
    inside its block until the second has been and gone. The marker is counted
    PER ENTRY because a log-reading judge sizes the breach by line count - one
    line per name would render N unprotected calls as a single incident.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    name = "Global\\LWRC_TEST_RC_POSIX_OVERLAP"
    lines: list[str] = []
    inside = threading.Event()
    release = threading.Event()

    def holder():
        with winmutex.hold(name, timeout=5, log=lines.append):
            inside.set()
            release.wait(timeout=10)

    t = threading.Thread(target=holder)
    t.start()
    try:
        assert inside.wait(timeout=10), "the first caller never entered its block"
        with winmutex.hold(name, timeout=0.2, log=lines.append) as h:
            assert h is None, "the POSIX branch holds no handle"
            assert not release.is_set(), \
                "the first caller must still be inside or this proves no overlap"
    finally:
        release.set()
        t.join(timeout=10)

    marker = "winmutex: UNSERIALIZED " + name
    assert sum(ln.startswith(marker) for ln in lines) == 2, \
        f"one marker per unprotected entry, not one per name, got {lines!r}"
    assert not any("ACQUIRED" in ln for ln in lines), \
        "a no-op must never claim ACQUIRED - it opens a window RELEASED never closes"


# ---- f1-phase6 item 5a: pinned parity constants -----------------------------
#
# slots.py and winmutex.py are BYTE-IDENTICAL between this repo and
# Sibling-A by contract. The mirror test at the top of this file compares
# against the carrier tree directly, which is the stronger check - but it SKIPS when
# the sibling tree is absent, so on a CI runner (one repo checked out, no
# sibling) parity is enforced by NOBODY. These pins close that hole: each repo's
# CI can prove parity alone, against a value both sides agreed to.
#
# RE-PINNING IS A JOINT ACT. Never regenerate these from whatever the file
# happens to be locally - that turns the guard into a rubber stamp and would
# launder a unilateral drift into "agreed". Change the shared file on one side,
# hand the other side the exact bytes, re-hash BOTH trees, confirm they match,
# and only then write the new digest here and in the carrier's copy in the same round.
#
# This block is itself byte-identical with the carrier copy in
# C:\Sibling-A\tests\test_loop_concurrency.py, modulo the repo name in
# the prose above. Keep it that way.
SHARED_SHA256 = {
    # re-pinned 2026-08-01: the module docstring named TWO repos and there are
    # now three (Sibling-C joined the bucket and vendored this file byte-identical
    # the same day). Docstring only - no code, no protocol, no behaviour.
    # RC authored the bytes, the carrier applied them first and carried the red window,
    # RC and RM followed; all three re-hashed from their OWN disk rather than
    # trusting the digest in the hand-off note.
    # previous 95077a62527c9764e896e3bd1da9027e5efd2b15631feb725fe6138cee5054f9
    #
    # re-pinned 2026-09-06: Sibling-C is archived (read-only at
    # a sibling private repo, working copy deleted) and Sibling-B takes
    # the vacated slot, so line 5 of the docstring names it instead. Docstring
    # only - no code, no protocol, no behaviour, and the bucket stays at 3
    # because it models ANTHROPIC ACCOUNT concurrency and the participant count
    # did not change. THIS TIME THE CARRIER AUTHORED THE BYTES and carried the red
    # window; RC copied the file verbatim off the carrier's live tree with a byte-level
    # copy (not a text write - `write_text` would CRLF-mangle it on Windows and
    # the pin is on bytes) and re-hashed from its OWN disk, which is how this
    # value was obtained rather than by trusting RM's hand-off note. Resin
    # Compute vendors LAST: it has no pin to break until it has one.
    # previous 5297f2d041030398a9ba240aad527b2b01a86d6e7f57a196719af8f0a91cb0a6
    #
    # re-pinned 2026-09-06 (carrier commit 374c79e): the hold() release-path leak.
    # BEHAVIOURAL, not docstring - a new release() with bounded unlink retry and
    # payload neutralisation, and hold()'s finally rewritten so the release line
    # can no longer be logged for a release that did not happen. The third carrier found the
    # leak, RC confirmed all three legs and reclaimed two ghost lanes, the carrier
    # measured the open question and authored the bytes.
    #
    # ONE SUBTLETY WORTH KEEPING: the neutralising write is IN PLACE, and that
    # is deliberate. Measured by the carrier on Windows - with a reader's handle open,
    # unlink FAILS (WinError 32) and tmp-then-os.replace ALSO FAILS (WinError 5),
    # but an in-place rewrite SUCCEEDS. So this one write is a documented
    # exception to the repo's atomic-write hard rule; applying that rule here
    # would silently restore the leak. Do not "fix" it into tmp+replace.
    # previous 1c4f8af43ff349709c11bf3fe622e922b24cb720771c49a522b13a4d5e58c492
    "slots.py": "629c3d511d2500f92d25fbe102a7a8c73644c027291f46b8796565a1e839f865",
    # re-pinned 2026-09-06: the carrier authored (commit 1de8d4e), operator-approved, and
    # this is the FIRST winmutex re-pin that is not docstring-only - the mutex
    # name VALUES rotated to opaque strings and the header prose naming the
    # vendor, the metered account and the failover behaviour was scrubbed. RC
    # copied the carrier's bytes with a byte-level copy off the live tree and re-hashed
    # from its OWN disk; the digest in the carrier's hand-off note was used as a value to
    # CHECK against, never as the source. Verified byte-identical to the carrier on disk,
    # 6190 bytes, zero CR bytes, pure ASCII.
    # previous f1b4b011112685efb88616c52752657cf896fbb0993b2d2d264e7b3edde8b4f4
    # before that c21bfe4f309c9ed27e68f7cdf0458d001a9942e6a35c61869e6dedd16cc23b79
    "winmutex.py": "0b112a4f6bfa88cf5f537f8869225c1821ebfe97428b1e899979797ddd71a61e",
}


@pytest.mark.parametrize("name", sorted(SHARED_SHA256))
def test_shared_module_matches_the_pinned_cross_repo_digest(name: str):
    """Parity provable from ONE checkout, so CI is not blind to cross-repo drift.

    This is the check that would have caught item 9 landing on the carrier side
    alone: the sibling-tree comparison above goes green-by-skip on any runner
    without both trees, which is every runner.
    """
    digest = hashlib.sha256((ROOT / "ops" / "loop" / name).read_bytes()).hexdigest()
    assert digest == SHARED_SHA256[name], (
        f"{name} no longer matches the digest agreed with Sibling-A. "
        f"If this change is intended, re-sync BOTH trees and re-pin on BOTH "
        f"sides in the same round - do not just update this constant.")


# ---- the shared surface that is a VALUE, not a file -------------------------
#
# A byte-digest pin structurally cannot cover this one. max_concurrent_lanes is
# the TOTAL number of concurrent executor calls allowed on this box across BOTH
# repos, enforced by slots.py against the single shared root
# C:\ProgramData\shared-loop\slots. Each repo reads its OWN config, so if the two
# values disagree the governor silently permits max(rc, lw) holders - RC's
# config.json calls that "theater" in its own note. Nothing asserted it.

def _lane_counts(root: Path) -> dict[str, int]:
    """Every ops/loop/config*.json in a tree that declares the lane count."""
    found = {}
    for cfg in sorted((root / "ops" / "loop").glob("config*.json")):
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "max_concurrent_lanes" in data:
            found[cfg.name] = data["max_concurrent_lanes"]
    return found


def test_rc_configs_agree_on_the_lane_count():
    """One RC config disagreeing with another is the same bug as disagreeing
    with the carrier: whichever config the running mode loaded sets the ceiling."""
    counts = _lane_counts(ROOT)
    assert counts, "no RC ops/loop/config*.json declares max_concurrent_lanes"
    assert len(set(counts.values())) == 1, (
        f"RC config files disagree on max_concurrent_lanes: {counts}. The value "
        f"is a shared ceiling, so every mode's config must carry the same one.")


def test_rc_and_the_carrier_agree_on_the_lane_count():
    """Cross-repo half. Skips off-box, so the RC-internal test above is the one
    CI actually runs - keep both."""
    for root in _sibling_roots():
        other = _lane_counts(root)
        if not other:
            continue
        rc = _lane_counts(ROOT)
        assert set(rc.values()) == set(other.values()), (
            f"RC {rc} and the sibling carrier at {root} disagree on "
            f"max_concurrent_lanes. Both loops enforce it against the same slot "
            f"root, so the effective ceiling becomes the LARGER of the two and "
            f"the governor is theater. Change it on both sides in one round.")
        return
    pytest.skip("no sibling carrier checkout configured on this machine")
