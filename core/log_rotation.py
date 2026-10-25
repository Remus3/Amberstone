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
raises into the writer.
"""
from __future__ import annotations

import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Union

_log = logging.getLogger("rc.log_rotation")

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


def rotate(path: PathLike, backup_count: int = DEFAULT_BACKUP_COUNT) -> bool:
    """Shift `path` -> `path.1` -> ... -> `path.<backup_count>`.

    The previous `path.<backup_count>` is overwritten (dropped). Returns True
    when `path` itself was moved aside; False when it is missing or a rename
    was refused, in which case `path` is left where it is for the caller to
    keep appending to.
    """
    _validate_backups(backup_count)
    path = Path(path)
    try:
        if not path.is_file():
            return False
        for i in range(backup_count - 1, 0, -1):
            src = _backup(path, i)
            if src.is_file():
                os.replace(src, _backup(path, i + 1))
        os.replace(path, _backup(path, 1))
        return True
    except OSError as exc:
        _log.warning("log rotation refused for %s (%s) - appending instead", path, exc)
        return False


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
    waits `_RETRY_AFTER_S` before trying again.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._retry_at = 0.0

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if time.monotonic() < self._retry_at:
            return False
        return bool(super().shouldRollover(record))

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None  # type: ignore[assignment]
        if not rotate(Path(self.baseFilename), self.backupCount):
            self._retry_at = time.monotonic() + _RETRY_AFTER_S
        if not self.delay:
            self.stream = self._open()


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
