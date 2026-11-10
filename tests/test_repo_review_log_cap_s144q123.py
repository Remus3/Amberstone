"""S144-Q-123 (RM-718 residue), writer 5: the repo-review driver's log is
size-capped.

`ops/loop/repo_review.py` `_say` appended every driver line to
`logs/repo_review.log` forever, with no size cap (filed by the S144-Q-123
sweep at repo_review.py `_say`). The file is absent live (measured
2026-11-09), but the driver is a re-runnable full-tree review: every batch,
retry, refusal and delta pass adds lines, from up to `--parallel N` worker
threads. It now rotates through core/log_rotation BEFORE the append, at the
same 5 MiB x (1 + 2 backups) bound as the other RM-718 writers.

Constraints pinned here:
- the driver is run as `python ops/loop/repo_review.py` (sys.path[0] is
  ops/loop; the repo root is on no path entry), so core/log_rotation is
  reached with the module's own import-then-bind shape (`_load_by_path`, as
  for core/polled_json); the end-to-end test loads the module by path in a
  subprocess whose cwd and sys.path exclude the checkout;
- worker threads share one log: the rotation runs under the same `_log_lock`
  as the append, so no thread appends into a file another is renaming;
- the log has no in-repo reader (grep for repo_review.log: only the driver,
  its test fixture and dated docs), so a plain rotation loses no consumer;
- a driver line is the run's audit trail: a refused or failing rotation never
  drops the line.
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
SRC = REPO_ROOT / "ops" / "loop" / "repo_review.py"


@pytest.fixture
def rr(tmp_path, monkeypatch):
    name = "repo_review_log_cap_under_test"
    spec = importlib.util.spec_from_file_location(name, SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    d = tmp_path / "logs"
    d.mkdir()
    monkeypatch.setattr(mod, "LOG", d / "repo_review.log")
    yield mod
    sys.modules.pop(name, None)


@pytest.fixture
def small_cap(rr, monkeypatch):
    monkeypatch.setattr(rr, "LOG_MAX_BYTES", 100)
    return 100


def _others(rr) -> list[str]:
    return sorted(p.name for p in rr.LOG.parent.iterdir()
                  if p.name != rr.LOG.name)


def _bodies(rr) -> list[str]:
    return [ln.split(" ", 1)[1]
            for ln in rr.LOG.read_text(encoding="ascii").splitlines()]


def test_cap_matches_the_shared_rm718_bound(rr):
    assert rr.LOG_MAX_BYTES == log_rotation.DEFAULT_MAX_BYTES
    assert rr.LOG_BACKUPS == log_rotation.DEFAULT_BACKUP_COUNT


def test_under_the_cap_lines_are_plain_appends(rr, small_cap):
    rr._say("one")
    rr._say("two")
    assert _bodies(rr) == ["one", "two"]
    assert _others(rr) == []


def test_at_the_cap_the_old_file_rotates_before_the_append(rr, small_cap):
    old = b"x" * 99 + b"\n"  # exactly the cap: at, not over, rotates
    assert len(old) == small_cap
    rr.LOG.write_bytes(old)
    rr._say("fresh")
    assert (rr.LOG.parent / "repo_review.log.1").read_bytes() == old
    assert _bodies(rr) == ["fresh"]
    assert _others(rr) == ["repo_review.log.1"]


def test_just_under_the_cap_does_not_rotate(rr, small_cap):
    rr.LOG.write_bytes(b"y" * 99)
    rr._say("next")
    assert _others(rr) == []
    assert rr.LOG.read_bytes().startswith(b"y" * 99)


def test_two_backups_kept_and_the_oldest_dropped(rr, small_cap):
    for gen in ("a", "b", "c", "d"):
        rr.LOG.write_bytes(gen.encode() * 120)
        rr._say("line-" + gen)
    assert _others(rr) == ["repo_review.log.1", "repo_review.log.2"]
    one = rr.LOG.parent / "repo_review.log.1"
    two = rr.LOG.parent / "repo_review.log.2"
    assert one.read_bytes().startswith(b"d" * 120)
    assert two.read_bytes().startswith(b"c" * 120)


def test_refused_rotation_notes_it_and_keeps_the_line(rr, small_cap,
                                                       monkeypatch):
    rr.LOG.write_bytes(b"z" * 150)

    def refuse(path, backup_count=2):
        return PermissionError(13, "held by another process")

    monkeypatch.setattr(rr.log_rotation, "try_rotate", refuse)
    rr._say("kept")
    raw = rr.LOG.read_text(encoding="ascii")
    assert raw.startswith("z" * 150)
    tail = raw[150:].splitlines()
    assert len(tail) == 2
    assert "log rotation refused for repo_review.log" in tail[0]
    assert "PermissionError" in tail[0]
    assert tail[1].endswith(" kept")
    assert _others(rr) == []


def test_a_concurrent_rotation_is_not_noted_as_refused(rr, small_cap,
                                                       monkeypatch):
    # FileNotFoundError: the file vanished between the stat and the rotate
    # (another writer rotated it); nothing was refused, so no note.
    rr.LOG.write_bytes(b"w" * 150)
    monkeypatch.setattr(rr.log_rotation, "try_rotate",
                        lambda *a, **k: FileNotFoundError(2, "gone"))
    rr._say("plain")
    raw = rr.LOG.read_text(encoding="ascii")
    assert "refused" not in raw
    assert raw.endswith(" plain\n")


@pytest.mark.parametrize("exc", [OSError(5, "boom"), ValueError("bad")])
def test_a_raising_rotation_never_drops_the_line(rr, small_cap, monkeypatch,
                                                 exc):
    rr.LOG.write_bytes(b"q" * 150)

    def boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(rr.log_rotation, "try_rotate", boom)
    rr._say("survives")
    raw = rr.LOG.read_text(encoding="ascii")
    assert raw.startswith("q" * 150)
    assert raw.endswith(" survives\n")


def test_a_failing_orphan_recovery_never_drops_the_line(rr, small_cap,
                                                       monkeypatch):
    def boom(*_a, **_k):
        raise OSError(5, "recover refused")

    monkeypatch.setattr(rr.log_rotation, "recover_orphans", boom)
    rr._say("still here")
    assert rr.LOG.read_text(encoding="ascii").endswith(" still here\n")


def test_missing_log_is_created_without_a_rotation_attempt(rr, small_cap,
                                                           monkeypatch):
    calls = []
    monkeypatch.setattr(rr.log_rotation, "try_rotate",
                        lambda *a, **k: calls.append(a))
    rr._say("first ever")
    assert calls == []
    assert rr.LOG.read_text(encoding="ascii").endswith(" first ever\n")


def test_missing_logs_dir_is_created_and_the_line_kept(rr, small_cap):
    rr.LOG.parent.rmdir()
    rr._say("new dir")
    assert _bodies(rr) == ["new dir"]


def test_crashed_rotation_scratch_is_recovered_under_the_cap(rr, small_cap):
    # A hard kill mid-rotation leaves the staged base file under a scratch
    # name; the writer's open recovers it even though the live file is small.
    staged = rr.LOG.parent / "repo_review.log.rotating-deadbeef"
    staged.write_bytes(b"staged\n")
    rr._say("after crash")
    assert not staged.exists()
    assert (rr.LOG.parent / "repo_review.log.1").read_bytes() == b"staged\n"


def test_rotation_runs_under_the_log_lock(rr, small_cap, monkeypatch):
    """Worker threads share the log: a rotation outside _log_lock could rename
    the file while another thread's append is mid-write."""
    rr.LOG.write_bytes(b"k" * 150)
    held = []
    real = rr.log_rotation.try_rotate

    def spy(path, backup_count=2):
        held.append(rr._log_lock.locked())
        return real(path, backup_count)

    monkeypatch.setattr(rr.log_rotation, "try_rotate", spy)
    rr._say("locked")
    assert held == [True]
    assert _bodies(rr) == ["locked"]


def test_loaded_by_absolute_path_the_cap_still_works(tmp_path):
    """The `python ops/loop/repo_review.py` shape: no repo root on sys.path,
    cwd outside the checkout, so core/log_rotation is bound by file path."""
    log = tmp_path / "logs" / "repo_review.log"
    script = textwrap.dedent(f"""
        import importlib.util, sys
        from pathlib import Path
        sys.path[:] = [p for p in sys.path
                       if p and not p.startswith({str(REPO_ROOT)!r})]
        spec = importlib.util.spec_from_file_location(
            "rc_repo_review_pathload", {str(SRC)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.log_rotation.__name__ != "core.log_rotation", \\
            mod.log_rotation.__name__
        assert "core" not in sys.modules, "repo root leaked onto sys.path"
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
