"""NA6 (s153): the landing-run sampler's two STOPs.

The s152 NA2 ruling (docs/_archive/2026-11/2026-11-07-s152-na2-gated-suite-
launch-ruling.md, condition 8 and STOPS) names a sampler that runs before a
gated whole-suite launch and enforces its stops. NA6 builds it with two:

- physical-memory STOP: available physical under 1024 MB on TWO consecutive
  reads (a recovered read resets the count);
- game-process STOP: a League / Riot / Vanguard process appearing.

"Stop the run" = `taskkill /F /T /PID <pid>` of the ONE child the sampler
launched itself, never anything else. Every reader, the launcher and the
taskkill runner are injected: no test here reads live memory or kills a
real process, and every path is under tmp_path.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from tools import landing_sampler as ls

SRC = Path(ls.__file__).read_text(encoding="ascii")


# ---------------------------------------------------------------- StopTracker


def test_one_low_physical_read_does_not_stop():
    t = ls.StopTracker()
    assert t.update(900.0, []) is None
    assert t.low_streak == 1


def test_two_consecutive_low_physical_reads_stop():
    t = ls.StopTracker()
    assert t.update(900.0, []) is None
    reason = t.update(1000.0, [])
    assert reason is not None
    assert "physical" in reason
    assert "1000" in reason


def test_a_recovered_read_resets_the_count():
    t = ls.StopTracker()
    assert t.update(900.0, []) is None
    assert t.update(5000.0, []) is None
    assert t.low_streak == 0
    assert t.update(900.0, []) is None
    assert t.update(900.0, []) is not None


def test_exactly_the_floor_is_not_low():
    t = ls.StopTracker()
    assert ls.PHYS_STOP_MB == 1024
    assert ls.PHYS_STOP_READS == 2
    for _ in range(5):
        assert t.update(1024.0, []) is None
    assert t.low_streak == 0


def test_an_unreadable_physical_read_neither_counts_nor_resets():
    t = ls.StopTracker()
    assert t.update(900.0, []) is None
    assert t.update(None, []) is None
    assert t.low_streak == 1
    assert t.update(900.0, []) is not None


def test_game_process_present_stops_on_one_read():
    for image in (
        "League of Legends.exe",
        "LeagueClient.exe",
        "LeagueClientUx.exe",
        "RiotClientServices.exe",
        "Riot Client.exe",
        "vgc.exe",
        "vgtray.exe",
        "TFTClient-Win64-Shipping.exe",
    ):
        t = ls.StopTracker()
        reason = t.update(25000.0, ["python.exe", image])
        assert reason is not None, image
        assert image.lower() in reason


def test_game_process_absent_does_not_stop():
    t = ls.StopTracker()
    names = ["python.exe", "msedge.exe", "vmmem", "svchost.exe", "leaguestats.exe", "vgcx.exe", "riot.txt"]
    for _ in range(3):
        assert t.update(25000.0, names) is None
    assert ls.game_hits(names) == []


def test_an_unreadable_process_list_is_not_a_stop():
    t = ls.StopTracker()
    assert t.update(25000.0, None) is None


# ---------------------------------------------------------------- run_sampler


class _FakeChild:
    def __init__(self, exits_after=None, rc=0):
        self.pid = 4242
        self.waits = 0
        self.killed = 0
        self._exits_after = exits_after
        self._rc = rc

    def wait(self, timeout):
        if self.killed:
            return 1
        self.waits += 1
        if self._exits_after is not None and self.waits > self._exits_after:
            return self._rc
        return None

    def stop(self, reap_s=None):
        self.killed += 1
        return {
            "pid": self.pid,
            "taskkill_rc": 0,
            "taskkill_error": None,
            "fallback": None,
            "child_rc": 1,
            "child_exited": True,
            "tree_confirmed": True,
        }


def _seq(values):
    it = iter(values)
    last = []

    def read():
        with contextlib.suppress(StopIteration):
            last[:] = [next(it)]
        return last[0]

    return read


def _run(tmp_path, child, physical, names, **kw):
    launched = []

    def launch(cmd):
        launched.append(list(cmd))
        return child

    rc = ls.run_sampler(
        ["python", "-c", "pass"],
        tmp_path / "sampler",
        launch=launch,
        physical=physical,
        commit=lambda: 30000.0,
        names=names,
        head=lambda: "abc123",
        interval=0.0,
        clock=lambda: "T",
        **kw,
    )
    return rc, launched


def _samples(tmp_path):
    lines = (tmp_path / "sampler" / "samples.jsonl").read_bytes().decode("ascii")
    assert "\r" not in lines
    return [json.loads(x) for x in lines.splitlines()]


def test_run_two_low_reads_kill_only_the_launched_child_and_void(tmp_path):
    child = _FakeChild()
    rc, launched = _run(tmp_path, child, _seq([25000.0, 900.0, 900.0]), lambda: ["python.exe"])
    assert rc == ls.EXIT_VOID
    assert launched == [["python", "-c", "pass"]]
    assert child.killed == 1
    void = json.loads((tmp_path / "sampler" / "VOID.json").read_text(encoding="ascii"))
    assert void["pid"] == 4242
    assert "physical" in void["reason"]
    rows = _samples(tmp_path)
    assert [r["phase"] for r in rows] == ["pre", "run", "run", "void"]
    assert rows[1]["stop"] is None
    assert rows[2]["stop"] is not None
    assert rows[0]["commit_mb"] == 30000.0
    assert rows[0]["head"] == "abc123"


def test_run_one_low_read_then_recovery_runs_to_the_childs_exit(tmp_path):
    child = _FakeChild(exits_after=4, rc=0)
    rc, _ = _run(tmp_path, child, _seq([25000.0, 900.0, 20000.0, 900.0, 20000.0]), list)
    assert rc == 0
    assert child.killed == 0
    assert not (tmp_path / "sampler" / "VOID.json").exists()
    assert _samples(tmp_path)[-1] == {"phase": "exit", "t": "T", "rc": 0}


def test_run_passes_the_childs_exit_code_through(tmp_path):
    child = _FakeChild(exits_after=1, rc=3)
    rc, _ = _run(tmp_path, child, lambda: 25000.0, list)
    assert rc == 3
    assert child.killed == 0


def test_run_game_process_appearing_mid_run_voids(tmp_path):
    child = _FakeChild()
    rc, _ = _run(tmp_path, child, lambda: 25000.0, _seq([[], [], ["League of Legends.exe"]]))
    assert rc == ls.EXIT_VOID
    assert child.killed == 1
    void = json.loads((tmp_path / "sampler" / "VOID.json").read_text(encoding="ascii"))
    assert "league of legends.exe" in void["reason"]


def test_run_game_process_before_launch_refuses_and_launches_nothing(tmp_path):
    child = _FakeChild()
    rc, launched = _run(tmp_path, child, lambda: 25000.0, lambda: ["vgc.exe"])
    assert rc == ls.EXIT_REFUSED
    assert launched == []
    assert child.killed == 0
    assert (tmp_path / "sampler" / "REFUSED.json").exists()
    assert not (tmp_path / "sampler" / "VOID.json").exists()


# ---------------------------------------------------------------- the kill itself


class _FakeProc:
    """A Popen stand-in: alive until kill() (the handle fallback) or a
    taskkill fake marks it dead. die_on_kill=False = a kill that fails."""

    def __init__(self, alive=True, die_on_kill=True, handle="open"):
        self.pid = 4242
        self.alive = alive
        self.die_on_kill = die_on_kill
        self.kills = 0
        # CPython's Windows Popen keeps its process handle in `_handle`, a
        # Handle(int) whose `closed` turns True only on Close() / GC.
        if handle == "open":
            self._handle = SimpleNamespace(closed=False)
        elif handle == "closed":
            self._handle = SimpleNamespace(closed=True)

    def poll(self):
        return None if self.alive else 1

    def wait(self, timeout=None):
        if self.alive:
            raise subprocess.TimeoutExpired("child", timeout)
        return 1

    def kill(self):
        self.kills += 1
        if self.die_on_kill:
            self.alive = False


def _taskkill(proc, mode):
    """A subprocess.run stand-in for one taskkill outcome."""
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        if mode == "timeout":
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        if mode == "missing":
            raise FileNotFoundError(2, "The system cannot find the file specified", "taskkill")
        if mode == "nonzero":
            return subprocess.CompletedProcess(argv, 128, "", "ERROR: access denied")
        if mode == "not_found":
            return subprocess.CompletedProcess(argv, 128, "", 'ERROR: The process "4242" not found.')
        if mode == "ok":
            proc.alive = False
            return subprocess.CompletedProcess(argv, 0, "SUCCESS", "")
        if mode == "ok_but_alive":
            return subprocess.CompletedProcess(argv, 0, "SUCCESS", "")
        raise AssertionError(mode)

    return run, calls


def test_stop_is_taskkill_f_t_on_the_launched_pid_only():
    proc = _FakeProc()
    run, calls = _taskkill(proc, "ok")
    out = ls.PopenChild(proc, run=run).stop(reap_s=0.0)
    assert len(calls) == 1
    argv, kw = calls[0]
    assert argv == ["taskkill", "/F", "/T", "/PID", "4242"]
    if sys.platform == "win32":
        assert kw["creationflags"] == 0x08000000
    assert out["taskkill_rc"] == 0
    assert out["fallback"] is None
    assert proc.kills == 0
    assert out["child_exited"] is True
    assert out["tree_confirmed"] is True


def test_stop_on_an_exited_child_with_the_handle_held_still_runs_taskkill_t():
    proc = _FakeProc(alive=False)
    run, calls = _taskkill(proc, "ok")
    out = ls.PopenChild(proc, run=run).stop(reap_s=0.0)
    assert [c[0] for c in calls] == [["taskkill", "/F", "/T", "/PID", "4242"]]
    assert proc.kills == 0
    assert out["exited_before_kill"] is True
    assert out["handle_held"] is True
    assert out["child_exited"] is True
    assert out["tree_confirmed"] is True


def test_stop_on_an_exited_child_taskkill_not_found_is_unverified():
    proc = _FakeProc(alive=False)
    run, calls = _taskkill(proc, "not_found")
    out = ls.PopenChild(proc, run=run).stop(reap_s=0.0)
    assert len(calls) == 1
    assert proc.kills == 0
    assert out["exited_before_kill"] is True
    assert out["taskkill_rc"] == 128
    assert out["tree_confirmed"] is False
    assert "descendants unverified" in out["note"]


def test_stop_on_an_exited_child_without_a_held_handle_skips_taskkill():
    for handle in ("closed", None):
        proc = _FakeProc(alive=False, handle=handle)
        run, calls = _taskkill(proc, "ok")
        out = ls.PopenChild(proc, run=run).stop(reap_s=0.0)
        assert calls == [], handle
        assert out["handle_held"] is False, handle
        assert out["tree_confirmed"] is False, handle
        assert "descendants unverified" in out["note"], handle


def test_handle_held_reads_a_real_popen_handle(tmp_path):
    child = ls.launch_child([sys.executable, "-c", "pass"], tmp_path / "c.txt")
    assert child.wait(60) == 0
    assert child.proc.poll() == 0
    assert child.handle_held() is (sys.platform == "win32")


def test_run_child_exited_before_kill_returns_92_with_its_reason(tmp_path, capsys):
    proc = _FakeProc()
    run, _ = _taskkill(proc, "not_found")
    child = ls.PopenChild(proc, run=run)

    def physical():
        proc.alive = proc.alive and physical.n < 2
        physical.n += 1
        return 900.0 if physical.n > 1 else 25000.0

    physical.n = 0
    rc, _ = _run(tmp_path, child, physical, list, reap_s=0.0)
    void = json.loads((tmp_path / "sampler" / "VOID.json").read_text(encoding="ascii"))
    assert rc == ls.EXIT_VOID_UNCONFIRMED
    assert void["exited_before_kill"] is True
    assert "child exited before kill; descendants unverified" in capsys.readouterr().err


# ---------------------------------------------------------------- kill first, writes best-effort


def test_run_the_kill_happens_before_any_write_of_the_stop_tick(tmp_path, monkeypatch):
    events = []
    real_append = ls._append

    class _Child(_FakeChild):
        def stop(self, reap_s=None):
            events.append("stop")
            return super().stop(reap_s)

    def append(path, row):
        events.append("append:" + row["phase"] + (":stop" if row.get("stop") else ""))
        real_append(path, row)

    def head():
        events.append("head")
        return "abc123"

    monkeypatch.setattr(ls, "_append", append)
    rc = ls.run_sampler(
        ["x"],
        tmp_path / "sampler",
        launch=lambda c: _Child(),
        physical=_seq([25000.0, 900.0, 900.0]),
        commit=None,
        names=list,
        head=head,
        interval=0.0,
        clock=lambda: "T",
        reap_s=0.0,
    )
    assert rc == ls.EXIT_VOID
    stop_at = events.index("stop")
    assert events[stop_at - 1] == "append:run", events
    assert events[stop_at + 1 :] == ["head", "append:run:stop", "append:void"], events


def _probe_run(tmp_path, monkeypatch, case):
    """The verifier's probe_void.py cases: a failing write on the stop path."""
    child = _FakeChild()
    real_append = ls._append

    def bad_append(path, row):
        if case == "void_append" and row.get("phase") == "void":
            raise OSError(28, "No space left on device")
        if case == "run_append" and row.get("phase") == "run" and row.get("stop"):
            raise OSError(28, "No space left on device")
        if case == "all_append":
            raise OSError(28, "No space left on device")
        return real_append(path, row)

    monkeypatch.setattr(ls, "_append", bad_append)
    if case == "void_json":

        def bad_marker(path, row):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(ls, "_marker", bad_marker)
    rc = ls.run_sampler(
        ["x"],
        tmp_path / "sampler",
        launch=lambda c: child,
        physical=lambda: 500.0,
        commit=lambda: 1.0,
        names=list,
        interval=0.0,
        reap_s=0.0,
    )
    return rc, child


def test_probe_failed_stop_row_append_still_kills_and_writes_void(tmp_path, monkeypatch, capsys):
    rc, child = _probe_run(tmp_path, monkeypatch, "run_append")
    assert child.killed == 1
    assert (tmp_path / "sampler" / "VOID.json").exists()
    assert rc == ls.EXIT_VOID
    assert "samples.jsonl" in capsys.readouterr().err


def test_probe_failed_void_row_append_still_kills_and_writes_void(tmp_path, monkeypatch):
    rc, child = _probe_run(tmp_path, monkeypatch, "void_append")
    assert child.killed == 1
    assert (tmp_path / "sampler" / "VOID.json").exists()
    assert rc == ls.EXIT_VOID


def test_probe_every_append_failing_still_kills_and_writes_void(tmp_path, monkeypatch):
    rc, child = _probe_run(tmp_path, monkeypatch, "all_append")
    assert child.killed == 1
    assert (tmp_path / "sampler" / "VOID.json").exists()
    assert rc == ls.EXIT_VOID


def test_probe_failed_void_json_write_forces_92_never_1(tmp_path, monkeypatch, capsys):
    rc, child = _probe_run(tmp_path, monkeypatch, "void_json")
    assert child.killed == 1
    assert rc == ls.EXIT_VOID_UNCONFIRMED
    assert "VOID.json NOT written" in capsys.readouterr().err


def test_a_failed_non_stop_row_append_keeps_monitoring(tmp_path, monkeypatch):
    child = _FakeChild()
    real_append = ls._append

    def bad_append(path, row):
        if row.get("phase") in ("pre", "run") and not row.get("stop"):
            raise OSError(28, "No space left on device")
        return real_append(path, row)

    monkeypatch.setattr(ls, "_append", bad_append)
    rc = ls.run_sampler(
        ["x"],
        tmp_path / "sampler",
        launch=lambda c: child,
        physical=_seq([25000.0, 25000.0, 900.0, 900.0]),
        commit=None,
        names=list,
        interval=0.0,
        reap_s=0.0,
    )
    assert rc == ls.EXIT_VOID
    assert child.killed == 1


def test_stop_falls_back_to_the_held_handle_on_every_taskkill_failure():
    for mode, err in (
        ("timeout", "TimeoutExpired"),
        ("missing", "FileNotFoundError"),
        ("nonzero", None),
        ("ok_but_alive", None),
    ):
        proc = _FakeProc()
        run, calls = _taskkill(proc, mode)
        out = ls.PopenChild(proc, run=run).stop(reap_s=0.0)
        assert len(calls) == 1, mode
        assert proc.kills == 1, mode
        assert out["fallback"] == "Popen.kill", mode
        assert out["child_exited"] is True, mode
        assert out["tree_confirmed"] is False, mode
        if err:
            assert out["taskkill_error"].startswith(err), mode
        else:
            assert out["taskkill_error"] is None, mode


def test_stop_reports_a_child_the_fallback_could_not_kill():
    proc = _FakeProc(die_on_kill=False)
    run, _ = _taskkill(proc, "missing")
    out = ls.PopenChild(proc, run=run).stop(reap_s=0.0)
    assert proc.kills == 1
    assert out["child_exited"] is False
    assert out["child_rc"] is None
    assert out["tree_confirmed"] is False


def _run_real_child(tmp_path, proc, mode):
    run, _ = _taskkill(proc, mode)
    child = ls.PopenChild(proc, run=run)
    rc, launched = _run(tmp_path, child, _seq([25000.0, 900.0, 900.0]), list, reap_s=0.0)
    assert launched
    void = json.loads((tmp_path / "sampler" / "VOID.json").read_text(encoding="ascii"))
    return rc, void


def test_run_taskkill_timeout_still_voids_with_the_handle_fallback(tmp_path):
    proc = _FakeProc()
    rc, void = _run_real_child(tmp_path, proc, "timeout")
    assert rc == ls.EXIT_VOID_UNCONFIRMED
    assert void["taskkill_error"].startswith("TimeoutExpired")
    assert void["fallback"] == "Popen.kill"
    assert void["child_exited"] is True
    assert proc.kills == 1


def test_run_missing_taskkill_voids_and_is_not_a_launch_failure(tmp_path):
    proc = _FakeProc()
    rc, void = _run_real_child(tmp_path, proc, "missing")
    assert rc == ls.EXIT_VOID_UNCONFIRMED
    assert void["taskkill_error"].startswith("FileNotFoundError")
    assert void["fallback"] == "Popen.kill"
    assert void["child_exited"] is True


def test_run_nonzero_taskkill_falls_back_and_voids(tmp_path):
    proc = _FakeProc()
    rc, void = _run_real_child(tmp_path, proc, "nonzero")
    assert rc == ls.EXIT_VOID_UNCONFIRMED
    assert void["taskkill_rc"] == 128
    assert void["fallback"] == "Popen.kill"
    assert void["child_exited"] is True


def test_run_child_not_confirmed_dead_returns_92(tmp_path, capsys):
    proc = _FakeProc(die_on_kill=False)
    rc, void = _run_real_child(tmp_path, proc, "nonzero")
    assert rc == ls.EXIT_VOID_UNCONFIRMED == 92
    assert void["child_exited"] is False
    assert "NOT confirmed" in capsys.readouterr().err


def test_run_clean_taskkill_voids_with_90(tmp_path):
    proc = _FakeProc()
    rc, void = _run_real_child(tmp_path, proc, "ok")
    assert rc == ls.EXIT_VOID == 90
    assert void["tree_confirmed"] is True
    assert void["fallback"] is None


def test_run_a_stop_that_raises_still_writes_void(tmp_path):
    class _Raises(_FakeChild):
        def stop(self, reap_s=None):
            raise RuntimeError("boom")

    rc, _ = _run(tmp_path, _Raises(), _seq([25000.0, 900.0, 900.0]), list)
    void = json.loads((tmp_path / "sampler" / "VOID.json").read_text(encoding="ascii"))
    assert rc == ls.EXIT_VOID_UNCONFIRMED
    assert void["stop_error"].startswith("RuntimeError")
    assert void["child_exited"] is False


def test_run_a_launch_failure_is_reported_as_one_and_writes_no_void(tmp_path):
    def launch(cmd):
        raise FileNotFoundError(2, "no such file", cmd[0])

    rc = ls.run_sampler(
        ["nope.exe"],
        tmp_path / "sampler",
        launch=launch,
        physical=lambda: 25000.0,
        commit=None,
        names=list,
        interval=0.0,
        clock=lambda: "T",
    )
    assert rc == ls.EXIT_LAUNCH_FAILED == 93
    assert not (tmp_path / "sampler" / "VOID.json").exists()
    assert _samples(tmp_path)[-1]["phase"] == "launch_failed"


def test_docstring_names_the_tree_kill_pid_reuse_residual():
    assert "pid reuse" in ls.__doc__
    assert "/T" in ls.__doc__


def test_source_never_uses_stop_process_or_detached_process():
    assert "Stop-Process" not in SRC
    assert "DETACHED_PROCESS" not in SRC
    assert "0x00000008" not in SRC


def test_launch_child_writes_the_childs_output_to_the_log(tmp_path):
    log = tmp_path / "child.txt"
    child = ls.launch_child([sys.executable, "-c", "print('na6-child-ok')"], log)
    assert child.wait(60) == 0
    assert "na6-child-ok" in log.read_text(encoding="ascii")
