"""
core/log_retention.py — periodic log dir trimmer.

`core/log_setup.py` (frozen) prunes files >30 days old, but only on RC
startup. A long-lived RC that doesn't restart for a week never reclaims
space; the audit on 2026-05-01 found logs/ at 191 MB.

This module adds:
  - tighter age policy (14 days vs. 30)
  - hard size cap (100 MB) — deletes oldest *.log* files past 14 days only
    if the dir is still over cap after the age sweep
  - hourly periodic sweep from a daemon thread, not just at boot

Sits beside log_setup.py rather than modifying it (frozen file).

Thread safety: the periodic thread is the sole writer. `prune()` is
re-entrant — multiple calls from different threads are safe; worst case
one observes files the other already deleted (handled with try/except
on unlink).
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

_thread: Optional[threading.Thread] = None
_task: Optional[Any] = None  # asyncio.Task / Future
_stop = threading.Event()
_start_lock = threading.Lock()


def _candidates(log_dir: Path) -> list[Path]:
    """All `*.log*` files (matches `log_setup._prune_old_logs` glob)."""
    try:
        return [p for p in log_dir.glob("*.log*") if p.is_file()]
    except Exception:
        return []


def prune(
    log_dir: Path,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    max_total_mb: int = _DEFAULT_MAX_TOTAL_MB,
) -> tuple[int, int]:
    """Run one prune sweep. Returns (files_deleted, bytes_freed).

    Policy (run in order):
      1. Delete every `*.log*` whose mtime is older than `max_age_days`.
      2. If total size of remaining `*.log*` is still above `max_total_mb`,
         delete oldest-first until under cap.

    Both passes are best-effort: per-file errors are swallowed so one bad
    file doesn't abort the whole sweep.
    """
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return (0, 0)

    deleted = 0
    freed = 0
    cutoff = time.time() - (max_age_days * 86400)

    files = _candidates(log_dir)

    # Pass 1: age-based
    survivors: list[tuple[Path, float, int]] = []
    for f in files:
        try:
            st = f.stat()
        except Exception:
            continue
        if st.st_mtime < cutoff:
            try:
                f.unlink()
                deleted += 1
                freed += st.st_size
            except Exception as exc:
                _log.debug("prune: unlink failed for %s: %s", f.name, exc)
                survivors.append((f, st.st_mtime, st.st_size))
        else:
            survivors.append((f, st.st_mtime, st.st_size))

    # Pass 2: size-based (only if we're still over cap)
    cap_bytes = max_total_mb * 1024 * 1024
    total = sum(sz for _, _, sz in survivors)
    if total > cap_bytes:
        survivors.sort(key=lambda t: t[1])  # oldest first
        for f, _mt, sz in survivors:
            if total <= cap_bytes:
                break
            try:
                f.unlink()
                deleted += 1
                freed += sz
                total -= sz
            except Exception as exc:
                _log.debug("prune: unlink failed for %s: %s", f.name, exc)

    if deleted:
        _log.info(
            "log retention: deleted %d file(s), freed %.1f MB "
            "(age>%dd or total>%dMB)",
            deleted, freed / 1024 / 1024, max_age_days, max_total_mb,
        )
    return (deleted, freed)


def _loop(log_dir: Path, interval_s: float, max_age_days: int, max_total_mb: int) -> None:
    # First sweep runs immediately so we don't wait an hour to reclaim
    # space on a freshly-started RC that hasn't been pruned in days.
    while not _stop.is_set():
        try:
            prune(log_dir, max_age_days, max_total_mb)
        except Exception as exc:
            _log.warning("prune sweep failed: %s", exc)
        _stop.wait(interval_s)


async def _loop_async(log_dir: Path, interval_s: float, max_age_days: int, max_total_mb: int) -> None:
    while not _stop.is_set():
        try:
            prune(log_dir, max_age_days, max_total_mb)
        except Exception as exc:
            _log.warning("prune sweep failed: %s", exc)
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            return


def start(
    log_dir: Path,
    interval_s: float = _DEFAULT_INTERVAL_S,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    max_total_mb: int = _DEFAULT_MAX_TOTAL_MB,
) -> None:
    """Launch the periodic prune loop (idempotent). Prefers spawning on
    the main AppLoop; falls back to a daemon thread otherwise."""
    global _thread, _task
    with _start_lock:
        if (_thread is not None and _thread.is_alive()) or _task is not None:
            return
        _stop.clear()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:
            _sched = None
        if _sched is not None:
            _task = _sched.spawn_task(
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
    """Stop the periodic loop (mostly for tests)."""
    global _thread, _task
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=3)
        _thread = None
    if _task is not None:
        try: _task.cancel()
        except Exception: pass
        _task = None
