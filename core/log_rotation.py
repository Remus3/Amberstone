# arch: size rotation for logs outside core/log_setup | section=core | frozen=no
"""
core/log_rotation.py - size caps for the logs core/log_setup does not own.

RM-718 (a). `core/log_setup.py` (frozen) rotates RC's own dated daily log, and
`core/log_retention.py` trims the top-level `logs/*.log*` to 100 MiB. Two
writers outside RC's process bypassed both and never rotated: measured
2026-10-24, `logs/replay_roster.log` was 59.5 MB (tools/replay_roster_pull.py
appended its `--log-file` forever, ~40 KB per hourly run) and
`logs/lcu_agent.log` 27.3 MB (tools/lcu_agent.py used a plain FileHandler).
Together they held 87 of the dir's 94.3 MiB.

Two shapes, one rotation scheme (`name`, `name.1` .. `name.N`; the oldest
generation is dropped, so the bound is (1 + backup_count) * max_bytes):

  - `rotate_if_oversize(path)` for a ONE-SHOT writer that opens its log once
    per run (a scheduled task): rotate at open time, then append.
  - `rotating_file_handler(path)` for a LONG-LIVED writer: a stdlib
    RotatingFileHandler whose refused rollover degrades to appending.

Windows refuses to rename a file another process holds open. Both shapes
therefore treat a refused rename as "keep appending to the oversize file":
the bound slips until the next attempt, but no record is lost and nothing
raises into the writer. A refused rotation changes NOTHING on disk: the base
file is staged aside first (the step a holder refuses), and a later refusal
rolls every applied rename back, so no backup generation is lost to it.

NEVER LOG FROM HERE. tools/lcu_agent.py puts the handler on the ROOT logger
(basicConfig), so a record emitted by this module during a rollover re-enters
the same handler mid-rollover. Verifier repro 2026-10-24: a refusal warning
logged before the retry deadline was set recursed - 121 refusal lines, 3
RecursionErrors, dropped records. A refusal is written straight into the log
file instead, once per streak, and counted on the handler.
"""
from __future__ import annotations

import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Union

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 2

# After a refused rollover, how long the handler appends before trying again.
# Without a pause every record would close, fail to rename and reopen the file.
_RETRY_AFTER_S = 60.0

PathLike = Union[str, os.PathLike]


def _validate_backups(backup_count: int) -> None:
    if backup_count < 1:
        raise ValueError(
            f"backup_count must be >= 1, got {backup_count!r} - zero backups "
            "turns a rotation into an unrecoverable truncation"
        )


def _validate(max_bytes: int, backup_count: int) -> None:
    if max_bytes <= 0:
        raise ValueError(
            f"max_bytes must be >= 1, got {max_bytes!r} - a non-positive cap "
            "rotates on every write"
        )
    _validate_backups(backup_count)


def _backup(path: Path, i: int) -> Path:
    return path.with_name(f"{path.name}.{i}")


def refusal_note(path: PathLike, err: BaseException) -> str:
    """The one line a writer appends to its own log when a rotation is refused."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    return (f"{stamp} WARNING log rotation refused for {Path(path).name} "
            f"({type(err).__name__}: {err}) - appending to the oversize file\n")


def try_rotate(path: PathLike, backup_count: int = DEFAULT_BACKUP_COUNT) -> Optional[OSError]:
    """Shift `path` -> `path.1` -> ... -> `path.<backup_count>`, all or nothing.

    Returns None on success (the previous `path.<backup_count>` is dropped),
    or the OSError that stopped it - in which case every file is where it was.
    A missing `path` returns FileNotFoundError. Never logs (module docstring).

    Order: 1) stage the base file aside - the rename a holder refuses, tried
    before anything else is touched; 2) move the oldest backup to a drop name
    instead of overwriting it; 3) shift the rest up; 4) staged -> `.1`. A
    refusal after step 1 undoes every applied rename in reverse.
    """
    _validate_backups(backup_count)
    path = Path(path)
    if not path.is_file():
        return FileNotFoundError(2, "no such log file", str(path))
    staged = path.with_name(path.name + ".rotating")
    try:
        os.replace(path, staged)
    except OSError as exc:
        return exc
    applied: list[tuple[Path, Path]] = [(path, staged)]
    oldest = _backup(path, backup_count)
    dropped = path.with_name(path.name + ".dropping")
    try:
        if oldest.is_file():
            os.replace(oldest, dropped)
            applied.append((oldest, dropped))
        for i in range(backup_count - 1, 0, -1):
            src = _backup(path, i)
            if src.is_file():
                dst = _backup(path, i + 1)
                os.replace(src, dst)
                applied.append((src, dst))
        os.replace(staged, _backup(path, 1))
    except OSError as exc:
        for src, dst in reversed(applied):
            try:
                # rename, not replace: never overwrite a file that appeared at
                # the original name in the meantime.
                os.rename(dst, src)
            except OSError:
                pass
        return exc
    if dropped.exists():
        try:
            dropped.unlink()
        except OSError:
            pass  # matches logs/*.log*, so core/log_retention sweeps it later
    return None


def rotate(path: PathLike, backup_count: int = DEFAULT_BACKUP_COUNT) -> bool:
    """True when `path` was rotated; False when it is missing or the rotation
    was refused (nothing changed - see try_rotate)."""
    return try_rotate(path, backup_count) is None


def rotate_if_oversize(
    path: PathLike,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> bool:
    """Rotate `path` when it is at or over `max_bytes`. Returns True if it
    rotated. A missing or unreadable file is left alone."""
    _validate(max_bytes, backup_count)
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < max_bytes:
        return False
    return rotate(path, backup_count)


class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler whose failed rollover degrades to appending.

    The stdlib doRollover closes the stream, then renames. When the rename
    raises (Windows: another process holds the file), the exception surfaces in
    emit(), the record is dropped through handleError(), and the stream is left
    None - so every following record retries the rename and is dropped too.

    Here a refused rollover reopens the same file, writes the record, and
    waits `_RETRY_AFTER_S` before trying again. The retry deadline is set
    BEFORE anything else happens and a re-entrancy guard blocks a nested
    rollover, so nothing reached from inside doRollover can recurse into it.
    `refused_rollovers` counts the current streak of refusals (a success
    resets it); the first refusal of a streak is noted in the file itself.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._retry_at = 0.0
        self._in_rollover = False
        self.refused_rollovers = 0
        self.last_refusal: Optional[str] = None

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if self._in_rollover or time.monotonic() < self._retry_at:
            return False
        return bool(super().shouldRollover(record))

    def doRollover(self) -> None:
        if self._in_rollover:
            return
        self._in_rollover = True
        # Deadline first: whatever runs below, a nested emit cannot retry.
        self._retry_at = time.monotonic() + _RETRY_AFTER_S
        try:
            if self.stream:
                self.stream.close()
                self.stream = None  # type: ignore[assignment]
            err = try_rotate(Path(self.baseFilename), self.backupCount)
            if not self.delay:
                self.stream = self._open()
            if err is None:
                self._retry_at = 0.0
                self.refused_rollovers = 0
                return
            self.refused_rollovers += 1
            self.last_refusal = f"{type(err).__name__}: {err}"
            if self.refused_rollovers == 1:
                if self.stream is None:
                    self.stream = self._open()
                # Straight into the file, never through logging.
                self.stream.write(refusal_note(self.baseFilename, err))
                self.stream.flush()
        finally:
            self._in_rollover = False


def rotating_file_handler(
    path: PathLike,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    encoding: str = "utf-8",
) -> SafeRotatingFileHandler:
    """A size-bounded file handler: at most (1 + backup_count) files of about
    `max_bytes` each."""
    _validate(max_bytes, backup_count)
    return SafeRotatingFileHandler(
        str(path), maxBytes=max_bytes, backupCount=backup_count, encoding=encoding,
    )
