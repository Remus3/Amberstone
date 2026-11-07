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

    def kill_tree(self):
        self.killed += 1
        return 0


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
    def __init__(self, polled):
        self.pid = 4242
        self._polled = polled

    def poll(self):
        return self._polled


def test_kill_tree_is_taskkill_f_t_on_the_launched_pid_only():
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, "", "")

    assert ls.PopenChild(_FakeProc(None), run=run).kill_tree() == 0
    assert len(calls) == 1
    argv, kw = calls[0]
    assert argv == ["taskkill", "/F", "/T", "/PID", "4242"]
    if sys.platform == "win32":
        assert kw["creationflags"] == 0x08000000


def test_kill_tree_on_an_exited_child_runs_nothing():
    calls = []
    assert ls.PopenChild(_FakeProc(0), run=lambda *a, **k: calls.append(a)).kill_tree() is None
    assert calls == []


def test_source_never_uses_stop_process_or_detached_process():
    assert "Stop-Process" not in SRC
    assert "DETACHED_PROCESS" not in SRC
    assert "0x00000008" not in SRC


def test_launch_child_writes_the_childs_output_to_the_log(tmp_path):
    log = tmp_path / "child.txt"
    child = ls.launch_child([sys.executable, "-c", "print('na6-child-ok')"], log)
    assert child.wait(60) == 0
    assert "na6-child-ok" in log.read_text(encoding="ascii")
