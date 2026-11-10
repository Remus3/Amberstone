"""S144-Q-123 (RM-718 residue), writer 6: the drain-waves launcher's log is
size-capped.

`ops/loop/drain_waves_2_3.py` `_say` appended every launcher line to
`logs/drain_waves_2_3.log` forever, with no size cap (named by the S144-Q-123
sweep, s144 queue cycle 230 NEXT CANDIDATE). The file is absent live
(measured 2026-11-10), but the launcher is re-runnable: every wave, build,
verifier, merger, retry and refusal adds lines, from up to MAX_PARALLEL
build / verify threads. It now rotates through core/log_rotation BEFORE the
append, at the same 5 MiB x (1 + 2 backups) bound as the other RM-718
writers.

Constraints pinned here:
- the launcher is run as `python ops/loop/drain_waves_2_3.py`; it already
  puts the repo root on sys.path before importing core.polled_json, so
  core.log_rotation is a plain import beside it (no new by-path load); the
  end-to-end test loads the module by path in a subprocess whose cwd and
  sys.path exclude the checkout;
- build / verify threads share one log: the rotation runs under the same
  `_log_lock` as the append, so no thread appends into a file another is
  renaming;
- the log has no in-repo reader (grep for drain_waves_2_3.log: only the
  launcher and its own docstring), so a plain rotation loses no consumer;
- a launcher line is the run's audit trail: a refused or failing rotation
  never drops the line.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from core import log_rotation

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "ops" / "loop" / "drain_waves_2_3.py"
NAME = "drain_waves_2_3.log"


@pytest.fixture
def dw(tmp_path, monkeypatch):
    name = "drain_waves_log_cap_under_test"
    spec = importlib.util.spec_from_file_location(name, SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    d = tmp_path / "logs"
    d.mkdir()
    monkeypatch.setattr(mod, "LOG", d / NAME)
    yield mod
    sys.modules.pop(name, None)


@pytest.fixture
def small_cap(dw, monkeypatch):
    monkeypatch.setattr(dw, "LOG_MAX_BYTES", 100)
    return 100


def _others(dw) -> list[str]:
    return sorted(p.name for p in dw.LOG.parent.iterdir()
                  if p.name != dw.LOG.name)


def _bodies(dw) -> list[str]:
    return [ln.split(" ", 1)[1]
            for ln in dw.LOG.read_text(encoding="ascii").splitlines()]


def test_cap_matches_the_shared_rm718_bound(dw):
    assert dw.LOG_MAX_BYTES == log_rotation.DEFAULT_MAX_BYTES
    assert dw.LOG_BACKUPS == log_rotation.DEFAULT_BACKUP_COUNT


def test_under_the_cap_lines_are_plain_appends(dw, small_cap):
    dw._say("one")
    dw._say("two")
    assert _bodies(dw) == ["one", "two"]
    assert _others(dw) == []


def test_at_the_cap_the_old_file_rotates_before_the_append(dw, small_cap):
    old = b"x" * 99 + b"\n"  # exactly the cap: at, not over, rotates
    assert len(old) == small_cap
    dw.LOG.write_bytes(old)
    dw._say("fresh")
    assert (dw.LOG.parent / (NAME + ".1")).read_bytes() == old
    assert _bodies(dw) == ["fresh"]
    assert _others(dw) == [NAME + ".1"]


def test_just_under_the_cap_does_not_rotate(dw, small_cap):
    dw.LOG.write_bytes(b"y" * 99)
    dw._say("next")
    assert _others(dw) == []
    assert dw.LOG.read_bytes().startswith(b"y" * 99)


def test_two_backups_kept_and_the_oldest_dropped(dw, small_cap):
    for gen in ("a", "b", "c", "d"):
        dw.LOG.write_bytes(gen.encode() * 120)
        dw._say("line-" + gen)
    assert _others(dw) == [NAME + ".1", NAME + ".2"]
    one = dw.LOG.parent / (NAME + ".1")
    two = dw.LOG.parent / (NAME + ".2")
    assert one.read_bytes().startswith(b"d" * 120)
    assert two.read_bytes().startswith(b"c" * 120)


def test_refused_rotation_notes_it_and_keeps_the_line(dw, small_cap,
                                                       monkeypatch):
    dw.LOG.write_bytes(b"z" * 150)

    def refuse(path, backup_count=2):
        return PermissionError(13, "held by another process")

    monkeypatch.setattr(dw.log_rotation, "try_rotate", refuse)
    dw._say("kept")
    raw = dw.LOG.read_text(encoding="ascii")
    assert raw.startswith("z" * 150)
    tail = raw[150:].splitlines()
    assert len(tail) == 2
    assert "log rotation refused for " + NAME in tail[0]
    assert "PermissionError" in tail[0]
    assert tail[1].endswith(" kept")
    assert _others(dw) == []


def test_a_concurrent_rotation_is_not_noted_as_refused(dw, small_cap,
                                                       monkeypatch):
    # FileNotFoundError: the file vanished between the stat and the rotate
    # (another writer rotated it); nothing was refused, so no note.
    dw.LOG.write_bytes(b"w" * 150)
    monkeypatch.setattr(dw.log_rotation, "try_rotate",
                        lambda *a, **k: FileNotFoundError(2, "gone"))
    dw._say("plain")
    raw = dw.LOG.read_text(encoding="ascii")
    assert "refused" not in raw
    assert raw.endswith(" plain\n")


@pytest.mark.parametrize("exc", [OSError(5, "boom"), ValueError("bad")])
def test_a_raising_rotation_never_drops_the_line(dw, small_cap, monkeypatch,
                                                 exc):
    dw.LOG.write_bytes(b"q" * 150)

    def boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(dw.log_rotation, "try_rotate", boom)
    dw._say("survives")
    raw = dw.LOG.read_text(encoding="ascii")
    assert raw.startswith("q" * 150)
    assert raw.endswith(" survives\n")


def test_a_failing_orphan_recovery_never_drops_the_line(dw, small_cap,
                                                       monkeypatch):
    def boom(*_a, **_k):
        raise OSError(5, "recover refused")

    monkeypatch.setattr(dw.log_rotation, "recover_orphans", boom)
    dw._say("still here")
    assert dw.LOG.read_text(encoding="ascii").endswith(" still here\n")


def test_missing_log_is_created_without_a_rotation_attempt(dw, small_cap,
                                                           monkeypatch):
    calls = []
    monkeypatch.setattr(dw.log_rotation, "try_rotate",
                        lambda *a, **k: calls.append(a))
    dw._say("first ever")
    assert calls == []
    assert dw.LOG.read_text(encoding="ascii").endswith(" first ever\n")


def test_missing_logs_dir_is_created_and_the_line_kept(dw, small_cap):
    dw.LOG.parent.rmdir()
    dw._say("new dir")
    assert _bodies(dw) == ["new dir"]


def test_crashed_rotation_scratch_is_recovered_under_the_cap(dw, small_cap):
    # A hard kill mid-rotation leaves the staged base file under a scratch
    # name; the writer's open recovers it even though the live file is small.
    staged = dw.LOG.parent / (NAME + ".rotating-deadbeef")
    staged.write_bytes(b"staged\n")
    dw._say("after crash")
    assert not staged.exists()
    assert (dw.LOG.parent / (NAME + ".1")).read_bytes() == b"staged\n"


def test_rotation_runs_under_the_log_lock(dw, small_cap, monkeypatch):
    """Build / verify threads share the log: a rotation outside _log_lock
    could rename the file while another thread's append is mid-write."""
    dw.LOG.write_bytes(b"k" * 150)
    held = []
    real = dw.log_rotation.try_rotate

    def spy(path, backup_count=2):
        held.append(dw._log_lock.locked())
        return real(path, backup_count)

    monkeypatch.setattr(dw.log_rotation, "try_rotate", spy)
    dw._say("locked")
    assert held == [True]
    assert _bodies(dw) == ["locked"]


def test_stdout_echo_is_unchanged(dw, small_cap, capsys):
    dw.LOG.write_bytes(b"e" * 150)
    dw._say("echoed")
    assert capsys.readouterr().out == "echoed\n"


def test_loaded_by_absolute_path_the_cap_still_works(tmp_path):
    """The `python ops/loop/drain_waves_2_3.py` shape: cwd outside the
    checkout and no repo root on sys.path before the load."""
    log = tmp_path / "logs" / NAME
    script = textwrap.dedent(f"""
        import importlib.util, sys
        from pathlib import Path
        sys.path[:] = [p for p in sys.path
                       if p and not p.startswith({str(REPO_ROOT)!r})]
        spec = importlib.util.spec_from_file_location(
            "rc_drain_waves_pathload", {str(SRC)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.LOG = Path({str(log)!r})
        mod.LOG_MAX_BYTES = 50
        mod.LOG.parent.mkdir(parents=True)
        mod.LOG.write_bytes(b"o" * 60)
        mod._say("by path")
        one = mod.LOG.with_name(mod.LOG.name + ".1")
        sys.stderr.write("ROTATED %s\\n" % (one.read_bytes() == b"o" * 60))
    """)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=str(tmp_path), env=env,
        capture_output=True, text=True, timeout=120, creationflags=flags,
        check=False)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "ROTATED True" in proc.stderr
    assert log.read_text(encoding="ascii").endswith(" by path\n")
