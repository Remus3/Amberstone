# arch: log init | section=core | frozen=yes
"""
core/log_setup.py
Centralised logging configuration for Riot Commander.

- Rotating file handler: 3 MB max per file, 3 backup files (9 MB total)
- Verbose/DEBUG when RIOT_COMMANDER_DEBUG=1 or --debug passed
- One log file per session named by date: logs/YYYY-MM-DD.log
- Console output only in debug mode (pythonw.exe has no console)
- Safe under pythonw.exe (sys.stderr may be None)

AUDIT 2026-04-28 (deferred-frozen): the RotatingFileHandler is size-only.
A long-lived RC that crosses midnight kept writing into yesterday's
date-stamped file. The DailyRotatingFileHandler subclass below adds the
time component on top: if the calendar day changes between emits, it
closes the current handle and opens today's file. Size rotation still
works inside a single day.
"""

import os
import sys
import logging
import traceback
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime, date

# Maximum 3 MB per log file, keep 3 backups → 9 MB total ceiling
_MAX_BYTES   = 3 * 1024 * 1024   # 3 MB
_BACKUP_COUNT = 3

# AUDIT-OPUS LOG-001: retention for per-day log files.  The date-stamped
# filename pattern means every calendar day spawns a fresh log + up to 3
# rotation backups.  Without retention this accumulates indefinitely (45 MB
# over 13 days observed during audit).  Purge files older than 30 days on
# every setup() call.
_RETENTION_DAYS = 30

_root_logger_configured = False


class DailyRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that ALSO rolls to a fresh date-stamped file
    when the calendar day changes. Combines size-based rotation (existing
    3 MB / 3 backup behaviour) with daily rotation so a long-lived RC
    doesn't keep writing yesterday's log past midnight.

    The `baseFilename` is rewritten on each day-roll to point at today's
    `logs/YYYY-MM-DD.log`. Size-based backups (`.1`, `.2`, …) accumulate
    against whatever date is current at the moment of overflow.
    """

    def __init__(self, log_dir: Path, *args, **kwargs):
        self._log_dir = Path(log_dir)
        self._current_day = date.today()
        super().__init__(str(self._path_for(self._current_day)), *args, **kwargs)

    def _path_for(self, d: date) -> Path:
        return self._log_dir / f"{d:%Y-%m-%d}.log"

    def shouldRollover(self, record) -> int:
        # Day rollover beats size rollover: if we crossed midnight, swap
        # the file path before the size check sees a stale baseFilename.
        today = date.today()
        if today != self._current_day:
            try:
                if self.stream:
                    self.stream.close()
                    self.stream = None
            except Exception:
                pass
            self._current_day = today
            self.baseFilename = str(self._path_for(today))
            # New day, fresh file — no need to rotate via size logic.
            return 0
        return super().shouldRollover(record)


def _prune_old_logs(log_dir: Path, retention_days: int = _RETENTION_DAYS) -> int:
    """Delete .log / .log.N files older than retention_days. Returns count deleted."""
    import time as _time
    try:
        cutoff = _time.time() - (retention_days * 86400)
    except Exception:
        return 0
    deleted = 0
    try:
        for f in log_dir.glob("*.log*"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except Exception:
                pass
    except Exception:
        pass
    return deleted


def setup(app_dir: Path, debug: bool = False) -> logging.Logger:
    """
    Configure the root logger.  Call once at startup before any other imports.

    Returns the root 'rc' logger.
    """
    global _root_logger_configured
    if _root_logger_configured:
        return logging.getLogger("rc")

    log_dir = app_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # AUDIT-OPUS LOG-001: prune old logs before opening new handler
    try:
        _n_pruned = _prune_old_logs(log_dir)
    except Exception:
        _n_pruned = 0

    level = logging.DEBUG if debug else logging.INFO

    # Formatter
    fmt     = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)-20s %(message)s",
        datefmt="%H:%M:%S",
    )
    verbose = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)-20s "
        "[%(filename)s:%(lineno)d] %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Daily + size rotating file handler ──────────────────────────────────
    fh = DailyRotatingFileHandler(
        log_dir,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
        delay=False,
    )
    fh.setLevel(logging.DEBUG)          # always verbose to file
    fh.setFormatter(verbose)
    log_file = Path(fh.baseFilename)

    # ── Console handler (debug mode only) ────────────────────────────────────
    handlers: list = [fh]
    if debug and sys.stderr:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(fmt)
        handlers.append(ch)

    # ── Root logger ──────────────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in handlers:
        root.addHandler(h)

    # ── Suppress noisy third-party loggers ───────────────────────────────────
    for noisy in ("httpcore", "httpx", "urllib3", "anthropic._base_client"):
        logging.getLogger(noisy).setLevel(
            logging.DEBUG if debug else logging.WARNING
        )

    # ── Fatal crash hook ─────────────────────────────────────────────────────
    _logger = logging.getLogger("rc")

    def _fatal(exc_type, exc_val, tb):
        msg = "".join(traceback.format_exception(exc_type, exc_val, tb))
        _logger.critical("FATAL CRASH:\n%s", msg)
        crash = log_dir / "crash.txt"
        try:
            crash.write_text(msg, encoding="utf-8")
        except Exception:
            pass
    sys.excepthook = _fatal

    try:
        import threading as _t
        def _thread_crash(args):
            msg = "".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback))
            _logger.error("THREAD CRASH (%s):\n%s",
                          getattr(args, "thread", "?"), msg)
            crash = log_dir / "crash.txt"
            try: crash.write_text(msg, encoding="utf-8")
            except Exception: pass
        _t.excepthook = _thread_crash
    except Exception:
        pass

    _root_logger_configured = True
    _logger.info("Riot Commander logging started — level=%s  file=%s",
                 "DEBUG" if debug else "INFO", log_file)
    if _n_pruned:
        _logger.info("log retention: pruned %d file(s) older than %d days",
                     _n_pruned, _RETENTION_DAYS)
    return _logger


def get(name: str) -> logging.Logger:
    """Shorthand: get a named child logger under 'rc'."""
    return logging.getLogger(f"rc.{name}")
