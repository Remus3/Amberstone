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
"""
from __future__ import annotations

import asyncio
import json
import logging
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
BANNER_TEXT_OPERATOR = ("Recording drive is nearly full. RC did not start this "
                        "recording, so it was left running.")


# -- pure ------------------------------------------------------------------

def trip_threshold_bytes(rate_bps: float,
                         interval_s: float = CHECK_INTERVAL_S) -> float:
    """Free bytes below which the guard trips. Never below the floor."""
    try:
        r = max(0.0, float(rate_bps))
    except (TypeError, ValueError):
        r = FALLBACK_RATE_BPS
    return max(float(FLOOR_BYTES),
               r * float(interval_s) * SAFETY_FACTOR + FINALIZE_BUFFER_BYTES)


def should_trip(free_bytes: float, rate_bps: float,
                interval_s: float = CHECK_INTERVAL_S) -> bool:
    return float(free_bytes) < trip_threshold_bytes(rate_bps, interval_s)


def start_precondition(free_bytes: Optional[float],
                       rc_recorded: float) -> tuple[bool, str]:
    """(ok, reason). Refuses when free space is unknown (fail closed)."""
    if free_bytes is None:
        return False, "free space unknown on the recording volume"
    need_free = FLOOR_BYTES + START_HEADROOM_BYTES
    if float(free_bytes) < need_free:
        return False, (f"free {free_bytes / GB:.1f} GB below "
                       f"{need_free / GB:.0f} GB start floor")
    room = CAP_BYTES - float(rc_recorded or 0)
    if room < START_HEADROOM_BYTES:
        return False, (f"cap: RC recordings use {float(rc_recorded) / GB:.1f} GB "
                       f"of the {CAP_BYTES / GB:.0f} GB cap")
    return True, ""


class RateEstimator:
    """Bytes/s from successive GetRecordStatus ``outputBytes`` reads."""

    def __init__(self) -> None:
        self._last: Optional[tuple[float, float]] = None
        self._rate: Optional[float] = None

    def update(self, output_bytes: Any, mono: float) -> Optional[float]:
        if output_bytes is None or isinstance(output_bytes, bool):
            return self._rate  # failed read: keep the last measurement
        try:
            b = float(output_bytes)
        except (TypeError, ValueError):
            return self._rate
        prev, self._last = self._last, (b, float(mono))
        if prev is None:
            return self._rate
        db, dt = b - prev[0], float(mono) - prev[1]
        if dt <= 0 or db < 0:
            # zero dt, or the counter went backwards (a new recording)
            return self._rate
        if db > 0:
            self._rate = db / dt
        return self._rate

    def measured(self) -> Optional[float]:
        return self._rate

    def effective_rate(self) -> float:
        return self._rate if self._rate else FALLBACK_RATE_BPS


def trip_actions(rc_owns_record: bool, rc_owns_replay: bool) -> dict:
    """What a trip does: stops only what RC owns; the banner always shows."""
    return {"stop_record": bool(rc_owns_record),
            "stop_replay_buffer": bool(rc_owns_replay),
            "banner": True}


# -- thin IO ---------------------------------------------------------------

def rc_recorded_bytes(recordings_dir: Path) -> int:
    """Sum of on-disk sizes of RC-owned recordings named in sidecars.

    Only paths recorded in RC sidecars count (ADR-016: no folder glob, no
    assumed RC-owned folder). Duplicate paths count once; missing files and
    unreadable sidecars count zero."""
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
        if not isinstance(p, str) or not p:
            continue
        key = p.replace("\\", "/").lower()
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
        self._interval = float(interval_s)
        self._rate = RateEstimator()
        self._banner: dict = {"active": False, "text": "", "updated": None}
        self._stop = asyncio.Event()

    def banner_state(self) -> dict:
        return dict(self._banner)

    def _set_banner(self, active: bool, text: str, extra: dict) -> None:
        if active == self._banner.get("active") and text == self._banner.get("text"):
            return
        self._banner = {"active": active, "text": text,
                        "updated": time.time(), **extra}
        try:
            _atomic_write_json(Path(self._banner_path), self._banner)
        except OSError as exc:
            _log.debug("disk guard banner write failed: %s", exc)

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
        free = None
        try:
            free = self._free_fn(self._record_dir_fn())
        except Exception:  # noqa: BLE001
            free = None
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
        try:
            owns_rec, owns_rb = self._ownership_fn()
        except Exception:  # noqa: BLE001
            owns_rec, owns_rb = False, False
        actions = trip_actions(owns_rec, owns_rb)
        res["actions"] = actions
        if actions["stop_record"] or actions["stop_replay_buffer"]:
            try:
                await self._stop_fn(actions)
            except Exception as exc:  # noqa: BLE001
                _log.warning("disk guard stop failed: %s", exc)
            text = BANNER_TEXT
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
