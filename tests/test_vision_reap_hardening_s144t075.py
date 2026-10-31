"""s144 true-audit cycle 75: vision_server/_reap.py kills only real vision servers.

The reap runs inside a freshly started vision server, right before it binds
:8889, and kills every OTHER process it judges to be a vision server. Before
this cycle that judgement was a SUBSTRING test over the space-joined command
line, so the kill list was wider than its name:

  F1  Any process whose command line merely MENTIONS the marker was killed:
      an editor holding moon_vision_server.py open, a grep / rg for the name,
      a tool passed the file as an argument, a shell running a launch string,
      and `python -m vision_server_<anything>` (the "-m vision_server" marker
      is a prefix of every such module name).
  F2  The new server's own ANCESTORS were not excluded. A launcher that
      re-executes the interpreter (a venv redirector carries the same
      `pythonw moon_vision_server.py` command line) sits above the real
      server, and the Windows launchers hold their child in a kill-on-close
      job, so reaping the parent takes the new server down with it.
  F3  The default killer built a FRESH psutil.Process(pid) at kill time,
      discarding the identity captured at enumeration. A pid recycled in
      between was killed blind; psutil's own pid-reuse check only works on
      the handle that observed the process.
  F4  The module says the sweep "must never raise", but an exception from
      the process iteration itself escaped find_stale_vision_pids and
      reap_stale_vision_instances, and so main() died before the bind -
      under pythonw with the traceback going nowhere.
  F5  A missing psutil turned the whole defence off with no log line.

No test here kills anything: every kill goes through an injected killer or a
fake handle, and the one live-table test only ENUMERATES.
"""
from __future__ import annotations

import os
import sys

import pytest

from vision_server import _reap

PYW = r"C:\Program Files\Python\pythonw.exe"
SCRIPT = r"C:\Example Repo\moon_vision_server.py"


class _Log:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    def info(self, msg, *args):
        pass

    def debug(self, msg, *args):
        pass


@pytest.fixture
def rec(monkeypatch):
    r = _Log()
    monkeypatch.setattr(_reap, "log", r)
    return r


@pytest.fixture(autouse=True)
def _no_real_kill(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("a test reached the real psutil kill path")
    monkeypatch.setattr(_reap, "_default_kill", boom)


# -- F1: the predicate -------------------------------------------------------
@pytest.mark.parametrize("argv", [
    [PYW, SCRIPT],
    [r"C:\Program Files\Python\python.exe", SCRIPT],
    [r"C:\Program Files\Python\python3.14.exe", "-u", SCRIPT],
    [PYW, "-X", "utf8", SCRIPT],
    [PYW, "-Xutf8", r"C:\r\MOON_VISION_SERVER.PY"],
    ["/usr/bin/python3", "/r/moon_vision_server.py"],
    [r"C:\Program Files\Python\python.exe", "-m", "vision_server"],
    [r"C:\Program Files\Python\python.exe", "-B", "-mvision_server"],
    [PYW, r"C:\r\moon_vision_server.pyw"],
    [r"C:\Program Files\Python\python3.14t.exe", SCRIPT],                           # free-threaded
    [r"C:\Program Files\Python\python_d.exe", SCRIPT],                              # debug build
    [PYW, "-Im", "vision_server"],                                # cluster
    [PYW, "-Bmvision_server"],                                    # glued
    [PYW, "-W", "ignore", "-X", "dev", SCRIPT],                   # opt args
    [PYW, "--check-hash-based-pycs", "always", SCRIPT],           # long w/ arg
    [PYW, "-E", "-s", SCRIPT],                                    # plain flags
    [PYW, "--", SCRIPT],                                          # -- then file
])
def test_real_vision_server_argv_matches(argv):
    assert _reap.is_vision_server_argv(argv) is True


@pytest.mark.parametrize("argv", [
    [r"C:\Program Files\Code\Code.exe", SCRIPT],                                # editor
    ["notepad.exe", SCRIPT],                                      # editor
    ["rg.exe", "moon_vision_server", "."],                        # search
    ["git.exe", "grep", "-m vision_server"],                      # search
    [r"C:\Windows\cmd.exe", "/c", "pythonw moon_vision_server.py"],  # shell
    ["py.exe", SCRIPT],                                           # launcher
    [PYW, r"C:\r\tools\probe.py", "--file", SCRIPT],              # an arg
    [PYW, "-m", "vision_server_tools"],                           # prefix
    [PYW, "-m", "pytest", "-k", "moon_vision_server"],            # pytest
    [PYW, "-c", "import moon_vision_server"],                     # -c code
    [PYW, "-c", "moon_vision_server.py"],                         # -c code
    [PYW, "-Bc", "moon_vision_server.py"],                        # -c cluster
    [PYW, "-Im", "vision_server_tools"],                          # cluster prefix
    [PYW, "-m"],                                                  # dangling -m
    [r"C:\Program Files\Python\pythonx.exe", SCRIPT],                               # not python
    [PYW, "-X", SCRIPT],                                          # -X eats it
    [PYW, "-", SCRIPT],                                           # stdin prog
    [PYW, "-E", "-", "-m", "vision_server"],                      # stdin prog
    [PYW, "--", "-m", "vision_server"],                           # -- ends opts
    [PYW, "--"],                                                  # dangling --
    [PYW, r"C:\r\moon_vision_server_old.py"],                     # near name
    [PYW],                                                        # bare REPL
    [],                                                           # no argv
    None,                                                         # denied
    "pythonw moon_vision_server.py",                              # not a list
    [PYW, None],                                                  # junk elem
])
def test_non_vision_argv_does_not_match(argv):
    assert _reap.is_vision_server_argv(argv) is False


def test_find_keeps_processes_that_only_mention_the_marker():
    procs = [
        (1, [PYW, SCRIPT]),                                  # self
        (2, [PYW, SCRIPT]),                                  # orphan - stale
        (3, [r"C:\Program Files\Code\Code.exe", SCRIPT]),                  # editor - keep
        (4, ["rg.exe", "moon_vision_server"]),               # grep - keep
        (5, [PYW, "-m", "vision_server_tools"]),             # keep
        (6, [r"C:\Program Files\Python\python.exe", "-m", "vision_server"]),   # stale
    ]
    assert _reap.find_stale_vision_pids(1, procs=procs, ancestors=()) == [2, 6]


# -- F2: ancestors -----------------------------------------------------------
def test_ancestors_of_the_new_server_are_never_stale():
    procs = [
        (10, [r"C:\Example Venv\Scripts\pythonw.exe", SCRIPT]),   # redirector parent
        (20, [PYW, SCRIPT]),                              # the new server
        (30, [PYW, SCRIPT]),                              # a real orphan
    ]
    assert _reap.find_stale_vision_pids(20, procs=procs, ancestors=[10]) == [30]


def test_reap_never_kills_an_ancestor():
    killed = []
    procs = [(10, [PYW, SCRIPT]), (20, [PYW, SCRIPT]), (30, [PYW, SCRIPT])]
    got = _reap.reap_stale_vision_instances(
        exclude_pid=20, procs=procs, killer=killed.append, ancestors=[10])
    assert got == [30] and killed == [30]


def test_live_ancestor_lookup_includes_the_parent():
    anc = _reap._ancestor_pids(os.getpid())
    assert os.getppid() in anc
    assert os.getpid() not in anc


def test_ancestor_lookup_never_raises_for_a_dead_pid():
    assert _reap._ancestor_pids(2 ** 31 - 2) == set()


def test_default_ancestor_lookup_is_used_when_not_injected(monkeypatch):
    seen = []

    def fake(pid):
        seen.append(pid)
        return {10}
    monkeypatch.setattr(_reap, "_ancestor_pids", fake)
    procs = [(10, [PYW, SCRIPT]), (20, [PYW, SCRIPT]), (30, [PYW, SCRIPT])]
    killed = []
    got = _reap.reap_stale_vision_instances(exclude_pid=20, procs=procs,
                                            killer=killed.append)
    assert seen == [20]
    assert got == [30] and killed == [30]


def test_non_iterable_injected_ancestors_does_not_raise():
    assert _reap.find_stale_vision_pids(
        1, procs=[(2, [PYW, SCRIPT])], ancestors=5) == [2]


def test_raising_ancestors_iterator_does_not_raise():
    def anc():
        yield 3
        raise ValueError("lookup died")
    assert _reap.find_stale_vision_pids(
        1, procs=[(2, [PYW, SCRIPT])], ancestors=anc()) == [2]


def test_unhashable_exclude_pid_does_not_raise():
    assert _reap.find_stale_vision_pids(
        [1], procs=[(2, [PYW, SCRIPT])], ancestors=()) == [2]


def test_entry_raising_on_index_skips_only_itself():
    class BadGet:
        def __getitem__(self, _i):
            raise ValueError("bad row")
    procs = [BadGet(), (7, [PYW, SCRIPT])]
    assert _reap.find_stale_vision_pids(1, procs=procs, ancestors=()) == [7]


# -- F3: kill through the enumerated handle ----------------------------------
class _Handle:
    def __init__(self):
        self.kills = 0

    def kill(self):
        self.kills += 1


def test_default_kill_goes_through_the_enumerated_handle():
    h_orphan, h_self = _Handle(), _Handle()
    procs = [(1, [PYW, SCRIPT], h_self), (2, [PYW, SCRIPT], h_orphan)]
    got = _reap.reap_stale_vision_instances(exclude_pid=1, procs=procs,
                                            ancestors=())
    assert got == [2]
    assert h_orphan.kills == 1 and h_self.kills == 0


def test_handle_kill_failure_is_logged_and_not_counted(rec):
    class Gone:
        def kill(self):
            raise ProcessLookupError("pid reused")
    procs = [(2, [PYW, SCRIPT], Gone()), (3, [PYW, SCRIPT], _Handle())]
    got = _reap.reap_stale_vision_instances(exclude_pid=1, procs=procs,
                                            ancestors=())
    assert got == [3]
    assert any("could not reap" in w and "2" in w for w in rec.warnings)


# -- F4: never raises --------------------------------------------------------
def _exploding_procs():
    yield (2, [PYW, SCRIPT])
    raise RuntimeError("process table read failed")


def test_enumeration_error_does_not_escape_find(rec):
    assert _reap.find_stale_vision_pids(1, procs=_exploding_procs(),
                                        ancestors=()) == [2]
    assert any("enumeration" in w for w in rec.warnings)


def test_enumeration_error_does_not_escape_reap(rec):
    killed = []
    got = _reap.reap_stale_vision_instances(
        exclude_pid=1, procs=_exploding_procs(), killer=killed.append,
        ancestors=())
    assert got == [2] and killed == [2]


def test_malformed_entry_is_skipped_not_raised(rec):
    procs = [("x",), None, (2, [PYW, SCRIPT])]
    assert _reap.find_stale_vision_pids(1, procs=procs, ancestors=()) == [2]


def test_ancestor_lookup_error_does_not_escape_reap(monkeypatch, rec):
    def bad(_pid):
        raise RuntimeError("parents() failed")
    monkeypatch.setattr(_reap, "_ancestor_pids", bad)
    killed = []
    got = _reap.reap_stale_vision_instances(
        exclude_pid=1, procs=[(2, [PYW, SCRIPT])], killer=killed.append)
    assert got == [2]


# -- F5: a disabled defence says so ------------------------------------------
def test_missing_psutil_is_a_logged_noop(monkeypatch, rec):
    monkeypatch.setitem(sys.modules, "psutil", None)   # import -> ImportError
    assert list(_reap._enumerate_processes()) == []
    assert any("psutil" in w for w in rec.warnings)
    assert _reap._ancestor_pids(os.getpid()) == set()


# -- live table, read-only ---------------------------------------------------
def test_live_enumeration_yields_argv_lists_and_handles():
    rows = list(_reap._enumerate_processes())
    assert rows, "the live process table should not be empty"
    mine = [r for r in rows if r[0] == os.getpid()]
    assert mine, "the current process should be enumerated"
    pid, argv, handle = mine[0]
    assert isinstance(argv, list) and argv
    assert hasattr(handle, "kill")


def test_live_find_excludes_self_and_never_raises():
    stale = _reap.find_stale_vision_pids(os.getpid())
    assert isinstance(stale, list)
    assert os.getpid() not in stale
    assert all(isinstance(p, int) for p in stale)
