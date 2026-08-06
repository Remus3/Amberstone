"""core/log_retention.py - lane 8 deep audit (cycle 9).

The module is started at RC boot from main.py:158 and deletes files on an
hourly timer for the process lifetime, yet carried zero test references.
Measured on Legion 2026-08-05: logs/ held 55 *.log* files totalling 99.6 MB
against the module's own 100 MB cap, and the OLDEST was 9.0 days - inside the
14-day age policy. So the age pass deletes nothing and the very next sweep
that crosses the cap runs the size pass over files the age policy had just
declared keep-worthy, including whatever file a live logging handler has open.

Characterization tests pin the behaviour that is correct and must not drift.
Regression tests are named for the weakness they close.
"""
import logging
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import log_retention


def _write(path: Path, size: int, age_days: float) -> Path:
    path.write_bytes(b"x" * size)
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))
    return path


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Every test starts from a stopped module and leaves it stopped."""
    log_retention.stop()
    yield
    log_retention.stop()


# -- Characterization: behaviour that is correct today ---------------------

def test_age_pass_deletes_only_files_past_the_cutoff(tmp_path):
    old = _write(tmp_path / "old.log", 10, age_days=30)
    young = _write(tmp_path / "young.log", 10, age_days=1)

    deleted, freed = log_retention.prune(tmp_path, max_age_days=14, max_total_mb=100)

    assert deleted == 1
    assert freed == 10
    assert not old.exists()
    assert young.exists()


def test_non_log_files_are_never_candidates(tmp_path):
    keep = _write(tmp_path / "notes.txt", 10, age_days=90)
    rotated = _write(tmp_path / "rc.log.1", 10, age_days=90)

    deleted, _ = log_retention.prune(tmp_path, max_age_days=14, max_total_mb=100)

    assert deleted == 1
    assert keep.exists()
    assert not rotated.exists()


def test_missing_dir_is_a_noop(tmp_path):
    assert log_retention.prune(tmp_path / "absent", max_age_days=14) == (0, 0)


def test_size_pass_deletes_oldest_first_and_stops_under_cap(tmp_path):
    """The size cap is a HARD cap: it deletes inside the age window when it
    has to. The module docstring used to claim the opposite ("past 14 days
    only"), which would make the cap unenforceable - the code is authoritative
    and this test pins it."""
    oldest = _write(tmp_path / "a.log", 500_000, age_days=3)
    middle = _write(tmp_path / "b.log", 500_000, age_days=2)
    newest = _write(tmp_path / "c.log", 500_000, age_days=1)

    deleted, freed = log_retention.prune(tmp_path, max_age_days=14, max_total_mb=1)

    assert deleted == 1
    assert freed == 500_000
    assert not oldest.exists()
    assert middle.exists() and newest.exists()


def test_unlink_failure_does_not_abort_the_sweep(tmp_path, monkeypatch):
    stubborn = _write(tmp_path / "a-locked.log", 10, age_days=30)
    other = _write(tmp_path / "b-free.log", 10, age_days=30)
    real_unlink = Path.unlink

    def _fake_unlink(self, *a, **kw):
        if self.name == "a-locked.log":
            raise PermissionError("held open by another process")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", _fake_unlink)

    deleted, _ = log_retention.prune(tmp_path, max_age_days=14, max_total_mb=100)

    assert deleted == 1
    assert stubborn.exists()
    assert not other.exists()


# -- Regression: the active log file must never be a deletion candidate ----

def _recording_unlink(monkeypatch) -> list:
    """Record every unlink TARGET, then delegate to the real unlink.

    Asserting only that the active file still exists is vacuous on Windows,
    which refuses to unlink a file a handler holds open - the file survives
    whether or not the module protects it. The honest assertion is that the
    module never ATTEMPTED the unlink. The spy delegates rather than raising,
    because a raising spy proves nothing against fail-soft code that swallows
    the exception either way.
    """
    attempted: list = []
    real_unlink = Path.unlink

    def _spy(self, *a, **kw):
        attempted.append(Path(self))
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", _spy)
    return attempted


def test_size_pass_never_deletes_a_file_a_live_handler_has_open(tmp_path, monkeypatch):
    """Weakness 1. The size pass sorted oldest-first with no exclusion, so the
    file the running logger is appending to was a deletion candidate like any
    other. Windows refuses the unlink of an open file, which masked this as a
    silent no-op rather than a fix; nothing in the module protected it.
    Here the ACTIVE file is deliberately the OLDEST, so it is first in line."""
    active = _write(tmp_path / "active.log", 500_000, age_days=3)
    victim = _write(tmp_path / "victim.log", 500_000, age_days=2)
    _write(tmp_path / "keep.log", 500_000, age_days=1)

    handler = logging.FileHandler(active, encoding="utf-8")
    logging.getLogger().addHandler(handler)
    try:
        attempted = _recording_unlink(monkeypatch)
        deleted, _ = log_retention.prune(tmp_path, max_age_days=14, max_total_mb=1)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()

    assert active not in attempted, "the live handler's file was a deletion candidate"
    assert active.exists()
    assert not victim.exists(), "the next-oldest unprotected file should go instead"
    assert deleted == 1


def test_age_pass_never_deletes_a_file_a_live_handler_has_open(tmp_path, monkeypatch):
    """Weakness 1, second half: protection has to be uniform across both
    passes. A handler whose file carries an old mtime is otherwise deleted by
    the age sweep before the size sweep is ever reached."""
    active = _write(tmp_path / "active.log", 10, age_days=90)

    handler = logging.FileHandler(active, encoding="utf-8")
    logging.getLogger().addHandler(handler)
    try:
        attempted = _recording_unlink(monkeypatch)
        deleted, _ = log_retention.prune(tmp_path, max_age_days=14, max_total_mb=100)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()

    assert active not in attempted
    assert active.exists()
    assert deleted == 0


def test_cap_that_cannot_be_met_is_reported(tmp_path, monkeypatch, caplog):
    """Weakness 2. Every per-file failure was logged at DEBUG and the sweep
    returned normally, so a retention loop that has not reclaimed a byte in
    weeks - the permission-denied case on Windows - looked identical to a
    healthy one at INFO. The dir being left over cap must surface."""
    for i, age in enumerate((5, 4, 3)):
        _write(tmp_path / f"f{i}.log", 500_000, age_days=age)

    def _always_denied(self, *a, **kw):
        raise PermissionError("held open by another process")

    monkeypatch.setattr(Path, "unlink", _always_denied)

    with caplog.at_level(logging.WARNING, logger="rc.log_retention"):
        deleted, _ = log_retention.prune(tmp_path, max_age_days=14, max_total_mb=1)

    assert deleted == 0
    assert any(
        "still over cap" in r.getMessage() for r in caplog.records
    ), "an unmeetable size cap must be reported, not swallowed at DEBUG"


def test_info_line_distinguishes_age_deletions_from_cap_deletions(tmp_path, caplog):
    """Weakness 6. The success line read "(age>14d or total>100MB)", so a live
    log could not say WHICH policy deleted a file. That is exactly the
    question this audit needed to answer about 13 historical sweeps on Legion
    and could not - the two passes have very different blast radii and one of
    them reaches inside the age window."""
    _write(tmp_path / "ancient.log", 500_000, age_days=30)
    _write(tmp_path / "a.log", 500_000, age_days=3)
    _write(tmp_path / "b.log", 500_000, age_days=2)
    _write(tmp_path / "c.log", 500_000, age_days=1)

    with caplog.at_level(logging.INFO, logger="rc.log_retention"):
        deleted, _ = log_retention.prune(tmp_path, max_age_days=14, max_total_mb=1)

    assert deleted == 2
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "1 past 14d" in msg, msg
    assert "1 to hold the 1MB cap" in msg, msg


# -- Regression: policy knobs are validated --------------------------------

@pytest.mark.parametrize("bad", [0, -1, -365])
def test_nonpositive_max_age_days_is_rejected(tmp_path, bad):
    """Weakness 3. max_age_days <= 0 puts the cutoff at or after now, so the
    age pass deletes EVERY log file in the directory. An unvalidated knob on a
    destructive sweep is a config typo away from erasing the log corpus."""
    _write(tmp_path / "a.log", 10, age_days=0.1)
    with pytest.raises(ValueError):
        log_retention.prune(tmp_path, max_age_days=bad)
    assert (tmp_path / "a.log").exists()


@pytest.mark.parametrize("bad", [0, -1])
def test_nonpositive_max_total_mb_is_rejected(tmp_path, bad):
    """Weakness 3, second knob: a cap of 0 makes the size pass delete every
    file it is permitted to touch."""
    _write(tmp_path / "a.log", 10, age_days=1)
    with pytest.raises(ValueError):
        log_retention.prune(tmp_path, max_age_days=14, max_total_mb=bad)
    assert (tmp_path / "a.log").exists()


@pytest.mark.parametrize("bad", [0, -5])
def test_nonpositive_interval_is_rejected(tmp_path, bad):
    """Weakness 3, third knob: interval_s <= 0 turns the hourly sweep into a
    hot loop that walks and stats the log dir without pause."""
    with pytest.raises(ValueError):
        log_retention.start(tmp_path, interval_s=bad)
    assert not log_retention.is_running()


# -- Regression: lifecycle must not leak or latch --------------------------

def test_stop_keeps_a_thread_that_failed_to_join_and_start_refuses_a_second(
    tmp_path, monkeypatch, caplog
):
    """Weakness 4. stop() joined with a timeout and then set _thread = None
    unconditionally. A sweep still walking a large dir outlived its join, the
    reference was dropped, and the next start() both passed the idempotence
    check AND called _stop.clear() - resurrecting the abandoned loop. Two
    delete loops then ran forever with only the newest one tracked."""
    released = threading.Event()
    entered = threading.Event()

    def _blocking_prune(*a, **kw):
        entered.set()
        released.wait(30)
        return (0, 0)

    monkeypatch.setattr(log_retention, "prune", _blocking_prune)
    monkeypatch.setattr(log_retention, "_use_app_loop", lambda: None)
    monkeypatch.setattr(log_retention, "_STOP_JOIN_TIMEOUT_S", 0.2)

    try:
        log_retention.start(tmp_path, interval_s=3600)
        assert entered.wait(5), "worker never entered prune"

        with caplog.at_level(logging.WARNING, logger="rc.log_retention"):
            log_retention.stop()

        assert any(
            "did not exit" in r.getMessage() for r in caplog.records
        ), "a worker that outlived its join must be reported"

        before = threading.active_count()
        log_retention.start(tmp_path, interval_s=3600)
        assert threading.active_count() == before, (
            "start() spawned a second sweep loop while the first was alive"
        )
    finally:
        released.set()
        time.sleep(0.3)


def test_start_recovers_after_the_scheduled_task_has_finished(tmp_path, monkeypatch):
    """Weakness 5. The idempotence check read `_task is not None`, so once the
    AppLoop task ended - cancelled, or dead on an unexpected error - the flag
    latched and start() returned early for the rest of the process lifetime.
    Retention then stayed silently off until RC restarted."""

    class _DoneTask:
        def done(self):
            return True

        def cancel(self):
            return False

    class _Sched:
        def __init__(self):
            self.spawned = 0

        def spawn_task(self, coro):
            self.spawned += 1
            coro.close()
            return _DoneTask()

    sched = _Sched()
    monkeypatch.setattr(log_retention, "_use_app_loop", lambda: sched)

    log_retention.start(tmp_path, interval_s=3600)
    assert sched.spawned == 1

    log_retention.start(tmp_path, interval_s=3600)
    assert sched.spawned == 2, "a finished task latched start() off permanently"
