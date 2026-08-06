# arch: periodic logs/ trimmer (age + hard size cap) | section=core | frozen=no
"""
core/log_retention.py - periodic log dir trimmer.

`core/log_setup.py` (frozen) prunes files >30 days old, but only on RC
startup. A long-lived RC that doesn't restart for a week never reclaims
space; the audit on 2026-05-01 found logs/ at 191 MB.

This module adds:
  - tighter age policy (14 days vs. 30)
  - hard size cap (100 MB): if the dir is STILL over cap after the age
    sweep, delete oldest-first until it is under - including files that
    are inside the age window, because a cap that may only delete what
    the age pass already deleted is not a cap at all
  - hourly periodic sweep from a daemon thread, not just at boot

Sits beside log_setup.py rather than modifying it (frozen file).

AUDIT 2026-08-05 (lane 8 deep audit, cycle 9). The module was started at RC
boot from main.py and had deleted files on an hourly timer for months with
zero test coverage. Measured on Legion that day: logs/ held 55 *.log* files
totalling 99.6 MB against this module's own 100 MB cap, and the OLDEST was
9.0 days - inside the 14-day window. So the age pass reclaimed nothing and
the next sweep to cross the cap would run the size pass over live files.
Five weaknesses were closed; `tests/test_log_retention.py` pins all of them.

  1. NO file was excluded from deletion, including the one the running
     logger has open. Windows refuses to unlink an open file, which turned
     that into a silent no-op rather than a crash and hid the defect - the
     policy itself never protected anything. `_protected_paths()` now pins
     every path a live logging handler holds, in BOTH passes. A pinned file
     still counts toward the cap total; it is only never a candidate.
  2. Every per-file failure was logged at DEBUG and the sweep returned
     normally, so a loop that had not reclaimed a byte in weeks looked
     identical to a healthy one. A dir left over cap now logs a WARNING.
  3. The policy knobs were unvalidated. `max_age_days <= 0` puts the cutoff
     at or after now and erases the whole log corpus; `max_total_mb <= 0`
     does the same via the size pass; `interval_s <= 0` turns the hourly
     sweep into a hot loop. All three now raise ValueError at the entry
     point rather than executing.
  4. `stop()` joined with a timeout and then dropped the thread reference
     unconditionally. A sweep still walking a large dir outlived its join,
     the reference was lost, and the next `start()` both passed the
     idempotence check AND called `_stop.clear()`, resurrecting the
     abandoned loop - two delete loops running with only the newest
     tracked. A worker that outlives its join is now KEPT and reported.
  5. The idempotence check read `_task is not None`, so once the AppLoop
     task ended the flag latched and `start()` returned early for the rest
     of the process lifetime. It now asks the task whether it is done.

Thread safety: the periodic worker is the sole writer. `prune()` is
re-entrant - multiple calls from different threads are safe; worst case one
observes files the other already deleted (handled per-file on unlink).
`start()` and `stop()` serialise on `_start_lock`.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("rc.log_retention")

_DEFAULT_MAX_AGE_DAYS = 14
_DEFAULT_MAX_TOTAL_MB = 100
_DEFAULT_INTERVAL_S = 3600  # 1h

# How long stop() waits for the sweep worker before reporting it stuck.
_STOP_JOIN_TIMEOUT_S = 3.0

_thread: Optional[threading.Thread] = None
_task: Optional[Any] = None  # asyncio.Task / Future
_stop = threading.Event()
_start_lock = threading.RLock()


def _validate_policy(max_age_days: int, max_total_mb: int) -> None:
    """Reject a policy that would erase the log corpus.

    Both knobs are destructive in the same direction: at or below zero the
    corresponding pass deletes everything it is permitted to touch. A typo in
    a config is not a reason to run that sweep.
    """
    if max_age_days <= 0:
        raise ValueError(
            f"max_age_days must be >= 1, got {max_age_days!r} - a cutoff at or "
            "after now deletes every log file"
        )
    if max_total_mb <= 0:
        raise ValueError(
            f"max_total_mb must be >= 1, got {max_total_mb!r} - a cap of zero "
            "deletes every log file"
        )


def _protected_paths() -> set[Path]:
    """Resolved paths that a live logging handler currently has open.

    These are never deletion candidates. Read from the handler objects rather
    than guessed from the date, because log_setup's DailyRotatingFileHandler
    rewrites `baseFilename` in place when the day rolls over, so the name is
    only authoritative on the handler itself.
    """
    protected: set[Path] = set()
    loggers: list[Any] = [logging.getLogger()]
    try:
        loggers.extend(logging.Logger.manager.loggerDict.values())
    except (AttributeError, RuntimeError):  # pragma: no cover - defensive
        pass
    for lg in loggers:
        for handler in list(getattr(lg, "handlers", ()) or ()):
            base = getattr(handler, "baseFilename", None)
            if not base:
                continue
            try:
                protected.add(Path(base).resolve())
            except OSError:  # pragma: no cover - unresolvable path
                continue
    return protected


def _candidates(log_dir: Path) -> list[Path]:
    """All `*.log*` files (matches `log_setup._prune_old_logs` glob).

    Not recursive by design: logs/agents, logs/scrapers and logs/ws carry
    their own retention and are not this module's to delete.
    """
    try:
        return [p for p in log_dir.glob("*.log*") if p.is_file()]
    except OSError:
        return []


def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return path


def prune(
    log_dir: Path,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    max_total_mb: int = _DEFAULT_MAX_TOTAL_MB,
) -> tuple[int, int]:
    """Run one prune sweep. Returns (files_deleted, bytes_freed).

    Policy (run in order):
      1. Delete every `*.log*` whose mtime is older than `max_age_days`.
      2. If the total size of the remaining `*.log*` is still above
         `max_total_mb`, delete oldest-first until under cap. This pass DOES
         reach inside the age window - that is what makes the cap hard.

    A file held open by a live logging handler is exempt from both passes but
    still counts toward the cap total. Per-file errors are logged and skipped
    so one locked file cannot abort the sweep; a sweep that ends over cap is
    reported at WARNING rather than returning silently.

    Raises ValueError on a policy that would erase the corpus.
    """
    _validate_policy(max_age_days, max_total_mb)

    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return (0, 0)

    deleted_age = 0
    deleted_cap = 0
    freed = 0
    cutoff = time.time() - (max_age_days * 86400)
    protected = _protected_paths()

    # Bytes held by files that are exempt from deletion but still on disk.
    pinned_bytes = 0
    # Deletable survivors of pass 1, as (path, mtime, size).
    survivors: list[tuple[Path, float, int]] = []

    # Pass 1: age-based
    for f in _candidates(log_dir):
        try:
            st = f.stat()
        except OSError as exc:
            _log.debug("prune: stat failed for %s: %s", f.name, exc)
            continue
        if _resolve(f) in protected:
            pinned_bytes += st.st_size
            continue
        if st.st_mtime < cutoff:
            try:
                f.unlink()
                deleted_age += 1
                freed += st.st_size
            except OSError as exc:
                _log.debug("prune: unlink failed for %s: %s", f.name, exc)
                survivors.append((f, st.st_mtime, st.st_size))
        else:
            survivors.append((f, st.st_mtime, st.st_size))

    # Pass 2: size-based (only if we're still over cap)
    cap_bytes = max_total_mb * 1024 * 1024
    total = pinned_bytes + sum(sz for _, _, sz in survivors)
    if total > cap_bytes:
        survivors.sort(key=lambda t: t[1])  # oldest first
        for f, _mt, sz in survivors:
            if total <= cap_bytes:
                break
            try:
                f.unlink()
                deleted_cap += 1
                freed += sz
                total -= sz
            except OSError as exc:
                _log.debug("prune: unlink failed for %s: %s", f.name, exc)

    deleted = deleted_age + deleted_cap
    if deleted:
        # Report the two passes SEPARATELY. The old line read
        # "(age>14d or total>100MB)", so a live log could not answer which
        # policy deleted a file - which is exactly the question the 2026-08-05
        # audit needed to answer about 13 historical sweeps and could not.
        _log.info(
            "log retention: deleted %d file(s), freed %.1f MB "
            "(%d past %dd, %d to hold the %dMB cap)",
            deleted, freed / 1024 / 1024,
            deleted_age, max_age_days, deleted_cap, max_total_mb,
        )
    if total > cap_bytes:
        # Reaching here means every remaining file was pinned or refused the
        # unlink - on Windows that is the whole dir being held open. Silence
        # here is what made a retention loop that reclaimed nothing for weeks
        # indistinguishable from a healthy one.
        _log.warning(
            "log retention: %s still over cap after sweep (%.1f MB of %d MB, "
            "%.1f MB pinned by live log handlers) - nothing further is deletable",
            log_dir, total / 1024 / 1024, max_total_mb, pinned_bytes / 1024 / 1024,
        )
    return (deleted, freed)


def _loop(log_dir: Path, interval_s: float, max_age_days: int, max_total_mb: int) -> None:
    # First sweep runs immediately so we don't wait an hour to reclaim
    # space on a freshly-started RC that hasn't been pruned in days.
    while not _stop.is_set():
        try:
            prune(log_dir, max_age_days, max_total_mb)
        except Exception as exc:  # noqa: BLE001 - a daemon sweep must never die
            _log.warning("prune sweep failed: %s", exc)
        _stop.wait(interval_s)


async def _loop_async(log_dir: Path, interval_s: float, max_age_days: int, max_total_mb: int) -> None:
    while not _stop.is_set():
        try:
            prune(log_dir, max_age_days, max_total_mb)
        except Exception as exc:  # noqa: BLE001 - a daemon sweep must never die
            _log.warning("prune sweep failed: %s", exc)
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            return


def _use_app_loop() -> Optional[Any]:
    """The main AppLoop scheduler, or None to fall back to a daemon thread."""
    try:
        from app._loop import get_loop
        return get_loop()
    except Exception:  # noqa: BLE001 - any import/init failure means no loop
        return None


def _task_finished(task: Any) -> bool:
    """True only when the task can be PROVEN finished.

    An object that cannot answer is treated as running, so an unrecognised
    scheduler handle can never cause a second sweep loop to be spawned.
    """
    done = getattr(task, "done", None)
    if not callable(done):
        return False
    try:
        return bool(done())
    except Exception:  # noqa: BLE001 - an unanswerable handle counts as running
        return False


def _worker_alive() -> bool:
    """Whether a sweep worker - thread or scheduled task - is still running."""
    if _thread is not None and _thread.is_alive():
        return True
    if _task is not None and not _task_finished(_task):
        return True
    return False


def is_running() -> bool:
    """Public liveness view for callers and tests."""
    with _start_lock:
        return _worker_alive()


def start(
    log_dir: Path,
    interval_s: float = _DEFAULT_INTERVAL_S,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    max_total_mb: int = _DEFAULT_MAX_TOTAL_MB,
) -> None:
    """Launch the periodic prune loop (idempotent). Prefers spawning on
    the main AppLoop; falls back to a daemon thread otherwise.

    Raises ValueError on a policy or interval that must not be run.
    """
    global _thread, _task
    _validate_policy(max_age_days, max_total_mb)
    if interval_s <= 0:
        raise ValueError(
            f"interval_s must be > 0, got {interval_s!r} - a non-positive "
            "interval turns the hourly sweep into a hot loop"
        )

    with _start_lock:
        if _worker_alive():
            # Never clear _stop while a worker is live: that is what
            # resurrected an abandoned loop after a timed-out stop().
            return
        _thread = None
        _task = None
        _stop.clear()
        sched = _use_app_loop()
        if sched is not None:
            _task = sched.spawn_task(
                _loop_async(Path(log_dir), interval_s, max_age_days, max_total_mb)
            )
            _log.info(
                "log_retention started (interval=%.0fs  max_age=%dd  max_total=%dMB, async)",
                interval_s, max_age_days, max_total_mb,
            )
        else:
            _thread = threading.Thread(
                target=_loop,
                args=(Path(log_dir), interval_s, max_age_days, max_total_mb),
                daemon=True, name="log-retention",
            )
            _thread.start()
            _log.info(
                "log_retention started (interval=%.0fs  max_age=%dd  max_total=%dMB, thread)",
                interval_s, max_age_days, max_total_mb,
            )


def stop() -> None:
    """Stop the periodic loop (mostly for tests).

    A worker that outlives its join is KEPT, not dropped: holding the
    reference is what stops the next start() from spawning a second delete
    loop alongside the one still running.
    """
    global _thread, _task
    with _start_lock:
        _stop.set()
        thread = _thread
        if thread is not None:
            thread.join(timeout=_STOP_JOIN_TIMEOUT_S)
            if thread.is_alive():
                _log.warning(
                    "log_retention: sweep thread did not exit within %.1fs - keeping "
                    "the reference so start() will not spawn a second sweep loop",
                    _STOP_JOIN_TIMEOUT_S,
                )
            else:
                _thread = None
        task = _task
        if task is not None:
            try:
                task.cancel()
            except Exception as exc:  # noqa: BLE001 - cancel is best-effort
                _log.debug("log_retention: task cancel failed: %s", exc)
            _task = None
