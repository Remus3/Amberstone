# arch: recording disk guard - pure budget math + ownership-scoped producer | section=core | frozen=no
"""core/disk_guard.py - disk budget for OBS match recording.

RM-637 (directive X-37, ADR-016 "Disk budget"). Behaviour observed in external
references C/E/G/H, re-implemented clean-room. The thresholds below are the
ADR-016 adjudicated values (RC's own numbers, not copied from any source):

  * floor: 20 GB free on the recording volume;
  * finalize buffer: 2 GB;
  * trip threshold = max(floor, rate x 60 s x 1.5 + finalize buffer);
  * start precondition: free >= floor + 8 GB AND 8 GB of room left under the
    60 GB cap of RC-recorded bytes;
  * live rate from GetRecordStatus ``outputBytes`` deltas; 5.0 MB/s fallback
    only when that read fails (G6-03 measured about 4.2 MB/s at 1440p60);
  * checked every 60 s.

On a trip RC stops ONLY an RC-owned recording (and an RC-owned replay buffer);
for an operator-owned one it raises the banner flag and nothing else. Sending
files to the Recycle Bin frees no space, so retention is never counted on.

The pure half (constants, ``trip_threshold_bytes``, ``should_trip``,
``start_precondition``, ``RateEstimator``, ``trip_actions``) has no I/O. The thin
half is ``rc_recorded_bytes`` (reads sidecars) and the ``DiskGuard`` producer,
which runs as its OWN task: the supervisor and the health monitor are frozen.

Lane 8 (true-audit) s144 cycle 61 hardening, one regression test each in
tests/test_disk_guard_true_audit_s144.py:

  F1  the not-owned banner no longer claims a recording is running: RC
      refuses to start below 28 GB free but keeps the game (and its record
      dir) until game end, so a trip with NOTHING recording lands there;
  F2  a stop that raised, or an ownership read that raised, shows
      BANNER_TEXT_NOT_STOPPED (warned), never "Recording stopped" or the
      not-owned text;
  F3  the banner write is deduped against the last SUCCESSFUL write, so a
      failed write (a poller holding the file) is retried next check, and
      the failure is a warning, not DEBUG;
  F4  the first check of a process always writes, clearing a stale active
      banner left by an earlier process;
  F5  a blind guard (free space unreadable while a record dir is set) warns
      once per streak, naming the exception type only;
  F6  outputBytes / clock must be a finite non-negative number (no bool, no
      str, no int that overflows float): inf could false-trip a stop and an
      over-large int raised OverflowError out of every check; a non-finite
      rate falls back in trip_threshold_bytes;
  F7  start_precondition fails CLOSED on a non-numeric / non-finite /
      negative free or RC-recorded value (NaN used to pass both checks), and
      check_once treats such a free value as unknown instead of raising;
  F8  a non-finite or non-positive interval is refused (0 busy-spun run(),
      inf never checked again);
  F9  rc_recorded_bytes counts one file named two ways once (normpath) and
      never resolves a relative sidecar path against the process cwd.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

_log = logging.getLogger("rc.disk_guard")

GB = 1_000_000_000  # decimal, matching how Windows Explorer and OBS report

FLOOR_BYTES = 20 * GB
FINALIZE_BUFFER_BYTES = 2 * GB
START_HEADROOM_BYTES = 8 * GB
CAP_BYTES = 60 * GB
FALLBACK_RATE_BPS = 5.0e6
CHECK_INTERVAL_S = 60.0
SAFETY_FACTOR = 1.5

_APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BANNER_PATH = _APP_DIR / "ops" / "runtime" / "disk_guard.json"

BANNER_TEXT = ("Recording stopped to protect disk space. Free some space on "
               "the recording drive to record the next match.")
# F1: true whether or not anything is recording (RC may have refused to start).
BANNER_TEXT_OPERATOR = ("Recording drive is nearly full. RC stops only "
                        "recordings it started, so it stopped nothing.")
# F2: the stop raised or ownership could not be read; nothing was stopped.
BANNER_TEXT_NOT_STOPPED = ("Recording drive is nearly full and RC could not "
                           "stop the recording. Free some space on the "
                           "recording drive now.")


# -- pure ------------------------------------------------------------------

def _finite_nonneg(value: Any) -> Optional[float]:
    """``value`` as a float when it is a real int / float, finite and >= 0;
    else None. bool and str are refused (F6 / F7)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        f = float(value)
    except OverflowError:
        return None
    if not math.isfinite(f) or f < 0:
        return None
    return f


def trip_threshold_bytes(rate_bps: float,
                         interval_s: float = CHECK_INTERVAL_S) -> float:
    """Free bytes below which the guard trips. Never below the floor.
    A rate that is not a finite number uses the fallback rate (F6)."""
    try:
        r = float(rate_bps)
    except (TypeError, ValueError, OverflowError):
        r = FALLBACK_RATE_BPS
    r = max(0.0, r) if math.isfinite(r) else FALLBACK_RATE_BPS
    return max(float(FLOOR_BYTES),
               r * float(interval_s) * SAFETY_FACTOR + FINALIZE_BUFFER_BYTES)


def should_trip(free_bytes: float, rate_bps: float,
                interval_s: float = CHECK_INTERVAL_S) -> bool:
    return float(free_bytes) < trip_threshold_bytes(rate_bps, interval_s)


def start_precondition(free_bytes: Optional[float],
                       rc_recorded: float) -> tuple[bool, str]:
    """(ok, reason). Refuses when free space is unknown (fail closed).

    F7: a free value that is not a finite non-negative number is unknown,
    and so is such an RC-recorded value (``None`` alone still means 0)."""
    free = _finite_nonneg(free_bytes)
    if free is None:
        return False, "free space unknown on the recording volume"
    rc = 0.0 if rc_recorded is None else _finite_nonneg(rc_recorded)
    if rc is None:
        return False, "RC-recorded bytes unknown; cap cannot be checked"
    need_free = FLOOR_BYTES + START_HEADROOM_BYTES
    if free < need_free:
        return False, (f"free {free / GB:.1f} GB below "
                       f"{need_free / GB:.0f} GB start floor")
    room = CAP_BYTES - rc
    if room < START_HEADROOM_BYTES:
        return False, (f"cap: RC recordings use {rc / GB:.1f} GB "
                       f"of the {CAP_BYTES / GB:.0f} GB cap")
    return True, ""


class RateEstimator:
    """Bytes/s from successive GetRecordStatus ``outputBytes`` reads."""

    def __init__(self) -> None:
        self._last: Optional[tuple[float, float]] = None
        self._rate: Optional[float] = None

    def update(self, output_bytes: Any, mono: float) -> Optional[float]:
        # Failed or junk read (None, bool, str, non-finite, negative, an int
        # past float range): keep the last measurement AND the last real
        # sample, so junk never becomes the baseline (F6).
        b = _finite_nonneg(output_bytes)
        t = _finite_nonneg(mono)
        if b is None or t is None:
            return self._rate
        prev, self._last = self._last, (b, t)
        if prev is None:
            return self._rate
        db, dt = b - prev[0], t - prev[1]
        if dt <= 0 or db < 0:
            # zero dt, or the counter went backwards (a new recording)
            return self._rate
        if db > 0:
            self._rate = db / dt
        return self._rate

    def measured(self) -> Optional[float]:
        return self._rate

    def effective_rate(self) -> float:
        return self._rate or FALLBACK_RATE_BPS


def trip_actions(rc_owns_record: bool, rc_owns_replay: bool) -> dict:
    """What a trip does: stops only what RC owns; the banner always shows."""
    return {"stop_record": bool(rc_owns_record),
            "stop_replay_buffer": bool(rc_owns_replay),
            "banner": True}


# -- thin IO ---------------------------------------------------------------

def rc_recorded_bytes(recordings_dir: Path) -> int:
    """Sum of on-disk sizes of RC-owned recordings named in sidecars.

    Only paths recorded in RC sidecars count (ADR-016: no folder glob, no
    assumed RC-owned folder). Duplicate paths count once, however spelled
    (F9: normpath + normcase); a relative path is not a recording location
    and counts zero (it would resolve against the process cwd); missing
    files and unreadable sidecars count zero."""
    total = 0
    seen: set[str] = set()
    try:
        files = sorted(Path(recordings_dir).glob("*.json"))
    except OSError:
        return 0
    for sc in files:
        try:
            d = json.loads(sc.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or d.get("owner") != "rc":
            continue
        p = d.get("obs_output_path")
        if not isinstance(p, str) or not p or not os.path.isabs(p):
            continue
        key = os.path.normcase(os.path.normpath(p)).replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            total += Path(p).stat().st_size
        except OSError:
            continue
    return total


def free_bytes_for(path: Any) -> Optional[int]:
    try:
        if not path:
            return None
        return int(shutil.disk_usage(str(path)).free)
    except (OSError, ValueError, TypeError):
        return None


def _atomic_write_json(path: Path, data: dict) -> None:
    """tmp + replace through core.polled_json (per-writer scratch name,
    bounded PermissionError retry, scratch cleanup on failure)."""
    from core.polled_json import atomic_write_bytes
    atomic_write_bytes(Path(path), json.dumps(data, indent=2, ensure_ascii=True).encode("ascii"))


class DiskGuard:
    """Producer: one check every ``interval_s`` while a recording is live.

    Every collaborator is injected so the guard never reaches OBS or a disk
    on its own: ``status_fn`` (async, GetRecordStatus responseData or None),
    ``record_dir_fn`` (recording directory or None), ``ownership_fn``
    (``(rc_owns_record, rc_owns_replay)``), ``stop_fn`` (async, receives the
    trip actions; called ONLY when RC owns something) and ``free_bytes_fn``.
    """

    def __init__(self, *, status_fn: Callable[[], Awaitable[Any]],
                 record_dir_fn: Callable[[], Any],
                 ownership_fn: Callable[[], tuple],
                 stop_fn: Callable[[dict], Awaitable[Any]],
                 free_bytes_fn: Callable[[Any], Optional[int]] = free_bytes_for,
                 banner_path: Optional[Path] = None,
                 interval_s: float = CHECK_INTERVAL_S) -> None:
        self._status_fn = status_fn
        self._record_dir_fn = record_dir_fn
        self._ownership_fn = ownership_fn
        self._stop_fn = stop_fn
        self._free_fn = free_bytes_fn
        self._banner_path = banner_path or DEFAULT_BANNER_PATH
        interval = _finite_nonneg(interval_s)
        if not interval:
            # F8: 0 / negative busy-spins run(); inf / NaN never checks again.
            raise ValueError("interval_s must be a finite number > 0")
        self._interval = interval
        self._rate = RateEstimator()
        self._banner: dict = {"active": False, "text": "", "updated": None}
        # F3 / F4: (active, text) of the last SUCCESSFUL write; None until the
        # first one, so a process always writes once (clearing a stale file).
        self._written: Optional[tuple[bool, str]] = None
        self._blind = False
        self._stop = asyncio.Event()

    def banner_state(self) -> dict:
        return dict(self._banner)

    def _set_banner(self, active: bool, text: str, extra: dict) -> None:
        # In-memory state first, so banner_state() is current even when the
        # file already matches after an earlier failed write.
        if (active, text) != (self._banner.get("active"), self._banner.get("text")):
            self._banner = {"active": active, "text": text,
                            "updated": time.time(), **extra}
        if self._written == (active, text):
            return
        try:
            _atomic_write_json(Path(self._banner_path), self._banner)
        except OSError as exc:
            _log.warning("disk guard banner write failed (%s); retrying next "
                         "check", type(exc).__name__)
            return
        self._written = (active, text)

    def _read_free(self) -> Optional[float]:
        """Free bytes on the recording volume, or None when unknown.

        No record dir (no game) is quietly unknown. A record dir whose free
        space cannot be read, or a collaborator that raises, leaves the guard
        BLIND: warned once per streak, exception type only (F5); a value that
        is not a finite non-negative number is unknown, not a crash (F7)."""
        try:
            record_dir = self._record_dir_fn()
            if not record_dir:
                self._blind = False
                return None
            raw = self._free_fn(record_dir)
            # keep the caller's int (the banner JSON and res carry it as is)
            free = raw if _finite_nonneg(raw) is not None else None
            why = "unreadable"
        except Exception as exc:  # noqa: BLE001 - injected collaborators
            free, why = None, type(exc).__name__
        if free is not None:
            self._blind = False
            return free
        if not self._blind:
            self._blind = True
            _log.warning("disk guard cannot read free space on the recording "
                         "volume (%s); recordings are NOT protected until it "
                         "can", why)
        return None

    async def check_once(self, now: Optional[float] = None) -> dict:
        mono = time.monotonic() if now is None else float(now)
        status = None
        try:
            status = await self._status_fn()
        except Exception as exc:  # noqa: BLE001
            _log.debug("disk guard status read failed: %s", exc)
        out_bytes = status.get("outputBytes") if isinstance(status, dict) else None
        self._rate.update(out_bytes, mono)
        rate = self._rate.effective_rate()
        source = "live" if self._rate.measured() else "fallback"
        free = self._read_free()
        res = {"tripped": False, "free_bytes": free, "rate_bps": rate,
               "rate_source": source,
               "threshold_bytes": trip_threshold_bytes(rate, self._interval)}
        if free is None:
            # Unknown free space never stops a recording: the guard cannot
            # prove danger, and a false stop loses the operator's match.
            return res
        if not should_trip(free, rate, self._interval):
            self._set_banner(False, "", {})
            return res
        res["tripped"] = True
        known = True
        try:
            owns_rec, owns_rb = self._ownership_fn()
        except Exception as exc:  # noqa: BLE001 - injected collaborator
            owns_rec, owns_rb, known = False, False, False
            _log.warning("disk guard ownership read failed (%s); nothing "
                         "stopped", type(exc).__name__)
        actions = trip_actions(owns_rec, owns_rb)
        res["actions"] = actions
        if not known:
            text = BANNER_TEXT_NOT_STOPPED
        elif actions["stop_record"] or actions["stop_replay_buffer"]:
            try:
                await self._stop_fn(actions)
                text = BANNER_TEXT
            except Exception as exc:  # noqa: BLE001 - injected collaborator
                _log.warning("disk guard stop failed (%s)", type(exc).__name__)
                text = BANNER_TEXT_NOT_STOPPED
        else:
            text = BANNER_TEXT_OPERATOR
        self._set_banner(True, text, {"free_bytes": free})
        _log.warning("disk guard tripped: free=%s threshold=%.0f actions=%s",
                     free, res["threshold_bytes"], actions)
        return res

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        """Own producer loop. Fail-soft: a raising check never ends it."""
        while not self._stop.is_set():
            try:
                await self.check_once()
            except Exception as exc:  # noqa: BLE001
                _log.debug("disk guard check failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except (asyncio.TimeoutError, TimeoutError):
                pass
