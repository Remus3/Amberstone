"""ops/loop/proc_tree.py hardening (S144-T-731, true-audit lane).

No real process is started or killed here: subprocess.run, os.kill, the clock and the
sleep are stand-ins, and the job is a fake, so every case runs on any platform.

- kill_tree never hands a non-pid to a kill: 0 and negatives are process GROUPS to
  os.kill (0 = the caller's own group, -1 = every process it may signal), a bool is not
  a pid, and a value past pid_t raises OverflowError; a junk pid no longer raises out
  before the job sweep, which is the half that reaches an orphaned grandchild.
- grace_s / poll_s are bounded: an infinite grace no longer spins forever on a job that
  will not empty, a junk grace no longer raises after the taskkill, and a zero, negative
  or NaN poll no longer busy-spins or raises ValueError out of time.sleep.
- KillJob.close reports whether the requested outcome held: kill=False whose
  kill-on-close swap the OS refused ends the job's processes on CloseHandle, and that
  is now a False the caller can log instead of silence.
- a job stand-in without a handle attribute is treated as no job.
"""
from __future__ import annotations

import math

import pytest

from ops.loop import proc_tree as PT
from tests._module_view import bind_module_view, bind_subprocess


class _FakeJob:
    """A job stand-in: kill() empties it after `kills_to_empty` calls (None = never)."""

    def __init__(self, pids=(111, 222), kills_to_empty=1):
        self.handle = 7
        self._pids = list(pids)
        self._kills_to_empty = kills_to_empty
        self.kills = 0

    def kill(self):
        self.kills += 1
        if self._kills_to_empty is not None and self.kills >= self._kills_to_empty:
            self._pids = []
        return True

    def pids(self):
        return list(self._pids)


@pytest.fixture
def recorder(monkeypatch):
    """Record every taskkill run and os.kill instead of doing either."""
    calls = {"run": [], "kill": []}

    class _Done:
        returncode = 0

    def fake_run(argv, **kw):
        calls["run"].append(list(argv))
        return _Done()

    def fake_kill(pid, sig):
        calls["kill"].append((pid, sig))

    bind_subprocess(monkeypatch, PT, run=fake_run)
    bind_module_view(monkeypatch, PT, "os", kill=fake_kill)
    return calls


@pytest.fixture
def fake_clock(monkeypatch):
    """monotonic advances only when the code sleeps; sleeps are recorded, never slept."""
    state = {"now": 1000.0, "sleeps": []}

    def sleep(s):
        if not (isinstance(s, (int, float)) and math.isfinite(s) and s > 0):
            raise ValueError(f"bad sleep {s!r}")
        if len(state["sleeps"]) > 100000:
            raise RuntimeError("unbounded kill loop")
        state["sleeps"].append(s)
        state["now"] += s

    monkeypatch.setattr(PT.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(PT.time, "sleep", sleep)
    return state


BAD_PIDS = [0, -1, -4242, True, False, None, "1234", 12.0, 2 ** 31, 2 ** 40, object()]
BAD_PID_IDS = ["zero", "minus-one", "negative", "true", "false", "none", "str", "float",
               "past-pid_t", "huge", "object"]


@pytest.mark.parametrize("windows", [True, False])
@pytest.mark.parametrize("pid", BAD_PIDS, ids=BAD_PID_IDS)
def test_a_non_pid_never_reaches_a_kill(monkeypatch, recorder, windows, pid):
    monkeypatch.setattr(PT, "_IS_WINDOWS", windows)
    out = PT.kill_tree(pid)
    assert recorder["run"] == [] and recorder["kill"] == []
    assert out == {"job": False, "taskkill_rc": None, "survivors": None}


@pytest.mark.parametrize("windows", [True, False])
@pytest.mark.parametrize("pid", BAD_PIDS, ids=BAD_PID_IDS)
def test_a_non_pid_still_runs_the_job_sweep(monkeypatch, recorder, fake_clock, windows, pid):
    monkeypatch.setattr(PT, "_IS_WINDOWS", windows)
    job = _FakeJob()
    out = PT.kill_tree(pid, job=job)
    assert job.kills >= 1
    assert out == {"job": True, "taskkill_rc": None, "survivors": []}


def test_a_real_pid_on_windows_is_taskkilled_by_its_integer(monkeypatch, recorder):
    monkeypatch.setattr(PT, "_IS_WINDOWS", True)
    out = PT.kill_tree(4242)
    assert len(recorder["run"]) == 1
    assert recorder["run"][0][1:] == ["/F", "/T", "/PID", "4242"]
    assert out == {"job": False, "taskkill_rc": 0, "survivors": None}


def test_a_real_pid_off_windows_is_sigkilled_once(monkeypatch, recorder):
    monkeypatch.setattr(PT, "_IS_WINDOWS", False)
    PT.kill_tree(4242)
    assert len(recorder["kill"]) == 1
    pid, sig = recorder["kill"][0]
    assert pid == 4242 and int(sig) > 0
    assert recorder["run"] == []


def test_an_infinite_grace_is_bounded(monkeypatch, recorder, fake_clock):
    monkeypatch.setattr(PT, "_IS_WINDOWS", True)
    job = _FakeJob(kills_to_empty=None)
    out = PT.kill_tree(4242, job=job, grace_s=math.inf)
    assert out["survivors"] == [111, 222]
    assert sum(fake_clock["sleeps"]) <= PT._GRACE_MAX_S + 1.0


@pytest.mark.parametrize("grace", [None, "10", math.nan, object(), True],
                         ids=["none", "str", "nan", "object", "bool"])
def test_a_junk_grace_uses_the_default(monkeypatch, recorder, fake_clock, grace):
    monkeypatch.setattr(PT, "_IS_WINDOWS", True)
    job = _FakeJob(kills_to_empty=None)
    out = PT.kill_tree(4242, job=job, grace_s=grace)
    assert out["survivors"] == [111, 222]
    assert 9.0 <= sum(fake_clock["sleeps"]) <= 10.0 + 1.0


@pytest.mark.parametrize("grace, low_s, high_s",
                         [(10 ** 400, 299.0, PT._GRACE_MAX_S + 1.0), (-10 ** 400, 0.0, 0.0)],
                         ids=["huge", "huge-negative"])
def test_an_int_past_float_range_grace_is_clamped_not_raised(
        monkeypatch, recorder, fake_clock, grace, low_s, high_s):
    monkeypatch.setattr(PT, "_IS_WINDOWS", True)
    job = _FakeJob(kills_to_empty=None)
    out = PT.kill_tree(4242, job=job, grace_s=grace)
    assert out["survivors"] == [111, 222]
    assert low_s <= sum(fake_clock["sleeps"]) <= high_s


@pytest.mark.parametrize("poll, expect", [(10 ** 400, PT._POLL_MAX_S),
                                          (-10 ** 400, PT._POLL_MIN_S)],
                         ids=["huge", "huge-negative"])
def test_an_int_past_float_range_poll_is_clamped_not_raised(
        monkeypatch, recorder, fake_clock, poll, expect):
    monkeypatch.setattr(PT, "_IS_WINDOWS", True)
    job = _FakeJob(kills_to_empty=None)
    out = PT.kill_tree(4242, job=job, grace_s=2.0, poll_s=poll)
    assert out["survivors"] == [111, 222]
    assert fake_clock["sleeps"] and set(fake_clock["sleeps"]) == {expect}


def test_a_negative_grace_is_one_sweep(monkeypatch, recorder, fake_clock):
    monkeypatch.setattr(PT, "_IS_WINDOWS", True)
    job = _FakeJob(kills_to_empty=None)
    out = PT.kill_tree(4242, job=job, grace_s=-5)
    assert job.kills == 1 and fake_clock["sleeps"] == []
    assert out["survivors"] == [111, 222]


@pytest.mark.parametrize("poll", [0, 0.0, -1, math.nan, math.inf, None, "0.1", True],
                         ids=["zero", "zero-float", "negative", "nan", "inf", "none", "str",
                              "bool"])
def test_a_junk_poll_never_busy_spins_or_raises(monkeypatch, recorder, fake_clock, poll):
    monkeypatch.setattr(PT, "_IS_WINDOWS", True)
    job = _FakeJob(kills_to_empty=None)
    out = PT.kill_tree(4242, job=job, grace_s=2.0, poll_s=poll)
    assert out["survivors"] == [111, 222]
    assert fake_clock["sleeps"], "the loop never slept"
    assert all(PT._POLL_MIN_S <= s <= PT._POLL_MAX_S for s in fake_clock["sleeps"])


def test_a_job_stand_in_without_a_handle_is_no_job(monkeypatch, recorder):
    monkeypatch.setattr(PT, "_IS_WINDOWS", True)
    out = PT.kill_tree(4242, job=object())
    assert out == {"job": False, "taskkill_rc": 0, "survivors": None}


class _FakeK32:
    def __init__(self, set_ok=1, terminate_ok=1):
        self.set_ok, self.terminate_ok = set_ok, terminate_ok
        self.closed, self.set_calls, self.terminated = [], [], []

    def SetInformationJobObject(self, handle, cls, ptr, size):  # noqa: N802 - Win32 name
        self.set_calls.append(handle)
        return self.set_ok

    def TerminateJobObject(self, handle, code):  # noqa: N802 - Win32 name
        self.terminated.append(handle)
        return self.terminate_ok

    def CloseHandle(self, handle):  # noqa: N802 - Win32 name
        self.closed.append(handle)
        return 1


def test_close_reports_a_refused_breakaway_swap():
    k32 = _FakeK32(set_ok=0)
    job = PT.KillJob(k32, 55)
    assert job.close(kill=False) is False
    assert k32.set_calls == [55] and k32.closed == [55] and job.handle is None


def test_close_reports_a_clean_swap():
    k32 = _FakeK32(set_ok=1)
    job = PT.KillJob(k32, 56)
    assert job.close(kill=False) is True
    assert k32.closed == [56] and job.handle is None


@pytest.mark.parametrize("terminate_ok", [1, 0])
def test_close_with_kill_ends_the_tree_either_way(terminate_ok):
    """A refused TerminateJobObject still ends the tree: the handle closing is the last
    handle of a kill-on-close job."""
    k32 = _FakeK32(terminate_ok=terminate_ok)
    job = PT.KillJob(k32, 57)
    assert job.close(kill=True) is True
    assert k32.terminated == [57] and k32.closed == [57]


def test_close_of_a_closed_job_is_a_no_op_false():
    k32 = _FakeK32()
    job = PT.KillJob(k32, 58)
    job.close(kill=False)
    assert job.close(kill=True) is False
    assert k32.closed == [58] and k32.terminated == []
