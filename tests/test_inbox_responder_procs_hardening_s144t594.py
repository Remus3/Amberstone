"""popen_capture / kill_tree keep their "never raises, never orphans" contract
on wrong-typed input (S144-T-594).

`tools/inbox_responder_procs.py` promises that `popen_capture` never raises for
a process-level fault and that every child it starts is either reaped or
killed. Measured before this slice (Python 3.14, Windows):

- `timeout_s=float("inf")` or `1e308` raised OverflowError and `"5"` raised
  TypeError out of the seam, AFTER the child had started - the child was left
  running and the runner's cycle died. `None` meant "wait forever", which is
  the wedge the module's kill arithmetic exists to bound.
- `timeout_s=float("nan")` started the child, `communicate` raised ValueError,
  and the seam returned exc="ValueError" with the child still running: a
  non-timeout `communicate` failure never killed the child.
- an argv element that is not a str (None, an int) raised TypeError out of
  Popen; a bare string argv was split into one argument per character.
- `env={"PATH": None}` raised TypeError out of Popen.
- a str `stdin_bytes` crashed subprocess's stdin writer thread (a traceback on
  stderr), the child waited on stdin for the full timeout and was filed as a
  timeout.
- `kill_tree(0)` on POSIX called `os.killpg(0, SIGKILL)`, which signals the
  CALLER'S OWN process group; a bool pid read as 1.

Every case below is driven through doubles except the env case, which needs no
child: Popen rejects the environment before any process exists.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests._module_view import bind_module_view, bind_subprocess  # noqa: E402
from tools import inbox_responder_procs as procs  # noqa: E402


class FakeProc:
    def __init__(self, *, communicate_exc=None, pid=31337):
        self.pid = pid
        self.returncode = 0
        self.communicate_calls = []
        self.wait_calls = []
        self.kill_calls = 0
        self._communicate_exc = communicate_exc

    def communicate(self, **kwargs):
        self.communicate_calls.append(kwargs)
        if self._communicate_exc is not None:
            raise self._communicate_exc
        return (b"out", b"err")

    def wait(self, *args, **kwargs):
        self.wait_calls.append((args, kwargs))
        return self.returncode

    def kill(self):
        self.kill_calls += 1


class Recorder:
    def __init__(self, proc=None):
        self.proc = proc if proc is not None else FakeProc()
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return self.proc


def _install(monkeypatch, proc=None):
    rec = Recorder(proc)
    bind_subprocess(monkeypatch, procs, Popen=rec)
    assert procs.subprocess.Popen is rec
    return rec


def _capture(argv=("fake-exe", "--flag"), **overrides):
    kwargs = dict(cwd=None, env=None, stdin_bytes=b"envelope", timeout_s=7, kill_budget=procs.KillBudget(1))
    kwargs.update(overrides)
    return procs.popen_capture(argv, **kwargs)


# ---------------------------------------------------------------------------
# A non-timeout communicate failure must not orphan the child
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc", [OSError("pipe gone"), ValueError("bad"), subprocess.SubprocessError("x")])
def test_a_non_timeout_communicate_failure_kills_the_child(monkeypatch, exc):
    fake = FakeProc(communicate_exc=exc)
    _install(monkeypatch, fake)
    killed = []
    monkeypatch.setattr(procs, "kill_tree", lambda pid: killed.append(pid))

    res = _capture()

    assert res.exc == type(exc).__name__
    assert fake.kill_calls == 1, "the child must not outlive a failed communicate"
    assert fake.wait_calls == [], "the kill is 0 s - no wait on this path"
    assert killed == [], "the per-cycle tree-kill allowance is for timeouts only"
    assert res.timed_out is False
    assert res.exit_code is None


def test_a_kill_that_itself_fails_after_a_communicate_failure_is_swallowed(monkeypatch):
    class KillRaises(FakeProc):
        def kill(self):
            self.kill_calls += 1
            raise OSError("already gone")

    fake = KillRaises(communicate_exc=OSError("pipe gone"))
    _install(monkeypatch, fake)

    res = _capture()

    assert fake.kill_calls == 1
    assert res.exc == "OSError"


# ---------------------------------------------------------------------------
# timeout_s is validated BEFORE any child exists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "exc_name"),
    [
        (None, "TypeError"),
        ("5", "TypeError"),
        (True, "TypeError"),
        (False, "TypeError"),
        ([5], "TypeError"),
        (float("nan"), "ValueError"),
        (float("inf"), "ValueError"),
        (float("-inf"), "ValueError"),
        (1e308, "ValueError"),
        (10**400, "ValueError"),
        (procs.MAX_TIMEOUT_S + 1, "ValueError"),
        (procs.MAX_TIMEOUT_S + 0.5, "ValueError"),
        (0, "ValueError"),
        (0.0, "ValueError"),
        (-1, "ValueError"),
    ],
    ids=lambda v: repr(v)[:24],
)
def test_a_bad_timeout_is_refused_without_spawning(monkeypatch, bad, exc_name):
    rec = _install(monkeypatch)

    res = _capture(timeout_s=bad)

    assert rec.calls == [], f"timeout_s={bad!r} must be refused before Popen"
    assert res.exc == exc_name
    assert res.exit_code is None
    assert res.timed_out is False
    assert res.stdout == b"" and res.stderr == b""


@pytest.mark.parametrize("good", [0.5, 7, 240, procs.MAX_TIMEOUT_S], ids=repr)
def test_a_good_timeout_still_reaches_communicate_unchanged(monkeypatch, good):
    rec = _install(monkeypatch)

    res = _capture(timeout_s=good)

    assert len(rec.calls) == 1
    assert rec.proc.communicate_calls[0]["timeout"] == good
    assert res.exc is None
    assert res.exit_code == 0


# ---------------------------------------------------------------------------
# argv is validated BEFORE any child exists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "exc_name"),
    [
        ("fake-exe", "TypeError"),
        (b"fake-exe", "TypeError"),
        (None, "TypeError"),
        (5, "TypeError"),
        (["fake-exe", None], "TypeError"),
        (["fake-exe", 5], "TypeError"),
        (["fake-exe", b"--flag"], "TypeError"),
        ([], "ValueError"),
        ((), "ValueError"),
    ],
    ids=repr,
)
def test_a_bad_argv_is_refused_without_spawning(monkeypatch, bad, exc_name):
    rec = _install(monkeypatch)

    res = _capture(argv=bad)

    assert rec.calls == [], f"argv={bad!r} must be refused before Popen"
    assert res.exc == exc_name
    assert res.exit_code is None


def test_a_path_argv_element_is_accepted_and_passed_through_unchanged(monkeypatch):
    rec = _install(monkeypatch)
    exe = Path("some") / "tool.exe"

    res = _capture(argv=[exe, "--x"])

    assert res.exc is None
    assert rec.calls[0][0] == [exe, "--x"]


def test_a_tuple_or_generator_argv_reaches_popen_as_a_list(monkeypatch):
    rec = _install(monkeypatch)

    _capture(argv=(a for a in ["fake-exe", "--flag"]))

    assert rec.calls[0][0] == ["fake-exe", "--flag"]


# ---------------------------------------------------------------------------
# stdin_bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["envelope", 5, ["a"], 1.5], ids=repr)
def test_a_non_bytes_stdin_is_refused_without_spawning(monkeypatch, bad):
    rec = _install(monkeypatch)

    res = _capture(stdin_bytes=bad)

    assert rec.calls == []
    assert res.exc == "TypeError"


@pytest.mark.parametrize(
    ("given", "sent"),
    [(None, b""), (bytearray(b"ba"), b"ba"), (memoryview(b"mv"), b"mv"), (b"", b"")],
    # A memoryview's repr carries its address, so each xdist worker would
    # collect a different id; name it by its bytes instead.
    ids=lambda v: f"memoryview({bytes(v)!r})" if isinstance(v, memoryview) else repr(v),
)
def test_none_and_bytes_like_stdin_are_sent_as_bytes(monkeypatch, given, sent):
    rec = _install(monkeypatch)

    res = _capture(stdin_bytes=given)

    assert res.exc is None
    got = rec.proc.communicate_calls[0]["input"]
    assert type(got) is bytes
    assert got == sent


# ---------------------------------------------------------------------------
# A TypeError from Popen itself (a junk environment) is recorded, not raised
# ---------------------------------------------------------------------------


def test_a_popen_type_error_is_recorded_not_raised(monkeypatch):
    def boom(argv, **kwargs):
        raise TypeError("environment can only contain strings")

    bind_subprocess(monkeypatch, procs, Popen=boom)

    res = _capture()

    assert res.exc == "TypeError"
    assert res.exit_code is None


def test_a_junk_environment_on_the_real_popen_is_recorded_not_raised():
    # Popen refuses the environment before CreateProcess / fork, so no child
    # process is ever created here.
    res = procs.popen_capture(
        [sys.executable, "-c", "pass"],
        cwd=None,
        env={"PATH": None},
        stdin_bytes=b"",
        timeout_s=5,
        kill_budget=procs.KillBudget(1),
    )
    assert res.exc == "TypeError"
    assert res.exit_code is None


# ---------------------------------------------------------------------------
# kill_tree never signals a pid that is not a real child pid
# ---------------------------------------------------------------------------


_BAD_PIDS = [0, -1, -4321, True, False, None, "555", 5.0, 1.5]


@pytest.mark.parametrize("bad", _BAD_PIDS, ids=repr)
def test_kill_tree_off_nt_never_signals_a_bad_pid(monkeypatch, bad):
    seen = []
    bind_module_view(monkeypatch, procs, "os", name="posix", killpg=lambda pid, sig: seen.append((pid, sig)))

    procs.kill_tree(bad)

    assert seen == [], f"kill_tree({bad!r}) must not reach os.killpg"


@pytest.mark.parametrize("bad", _BAD_PIDS, ids=repr)
def test_kill_tree_on_nt_never_runs_taskkill_for_a_bad_pid(monkeypatch, bad):
    bind_module_view(monkeypatch, procs, "os", name="nt")
    seen = []
    bind_subprocess(monkeypatch, procs, run=lambda argv, **kw: seen.append(argv))

    procs.kill_tree(bad)

    assert seen == []


def test_kill_tree_still_signals_a_real_positive_pid_on_both_platforms(monkeypatch):
    seen = []
    bind_module_view(monkeypatch, procs, "os", name="posix", killpg=lambda pid, sig: seen.append(pid))
    procs.kill_tree(555)
    assert seen == [555]

    bind_module_view(monkeypatch, procs, "os", name="nt")
    ran = []
    bind_subprocess(monkeypatch, procs, run=lambda argv, **kw: ran.append(argv))
    procs.kill_tree(556)
    assert ran == [["taskkill", "/F", "/T", "/PID", "556"]]
