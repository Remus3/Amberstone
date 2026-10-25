"""tft/sources/tft_log.py - the TFT.log source (slice TFT-02).

docs/TFT_PROGRAM.md section 0 item 4 and section 3.2 stage 0: the standalone
client's live Unreal log (`TFT.log`, beside TFTEoGStats.json; rotated to
`TFT-backup-<utc>.log` per launch) is ~24 MB / ~76k lines per match and mixes
auth, chat and telemetry lines in. RC reads it two ways only:

  * BOUNDED: `TftLogTail` keeps a byte offset and reads at most
    `max_bytes_per_poll` per poll from it - never the whole file on a poll.
    A line longer than `max_line_bytes` is dropped (counted), a partial last
    line waits for its newline, the UTF-8 BOM is skipped, CRLF is accepted,
    and a rotated file (shorter than the offset, or a different first 64
    bytes) restarts at 0. The file is opened per poll with FILE_SHARE_DELETE
    on Windows, so a poll never blocks the client renaming its own log.
  * ALLOWLIST-ONLY: `parse_line` turns a line into a `LogEvent` only when the
    WHOLE line matches one anchored rule of `ALLOWLIST`; nothing else is kept,
    not even in a log line. Unit ids must have the game api shape, so a VO
    actor holding a display name is rejected with its line.

Allowlisted signals (shapes re-measured s135 against the live logs, templated):
phase transitions (`ETFTPhaseType::` CombatDeparture / PlanningDeparture /
DraftDeparture / Planning), the three VO cues `Unit.Purchase`, `Unit.StarUp.<n>Star`
and `Army.Round.UnitCombatVictory` (hints: interrupt channels block cues, so
never a purchase ledger), "Player TeamPlanner data saved" and the carousel /
gameplay music switches. Stamps are UTC (the "Log file open" header is local
time; measured +5 h offset on the s134 logs) and become epoch seconds.

Conf (section 1.1, src `tft_log`): 1.0 for phase stamps, planner saves and
music; 0.6 for VO hints. The event table has no conf column, so it rides in
the payload.

`LogIngest` writes events into the round store at the (match_id, round_seq)
a `locate(ts)` callable returns (`tft.sources.eog_file.EogIngest.locate`). An
event is placed only `settle_s` after its stamp, so the EoG rewrite that opens
its round has been seen; events with no match yet wait in a bounded buffer and
age out when they belong to no match.
"""
from __future__ import annotations

import calendar
import collections
import datetime
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from tft import tft_standalone as p0

_log = logging.getLogger(__name__)

SRC = "tft_log"
EXTRACTOR_VERSION = "tft02-log/1"
PHASE_CONF = 1.0
HINT_CONF = 0.6  # VO cues are partial (interrupt channels block some)
MAX_BYTES_PER_POLL = 1 << 20
MAX_LINE_BYTES = 8192  # the longest allowlisted line is ~230 bytes
HEADER_BYTES = 64  # rotation fingerprint: "Log file open, <local time>" + the next line
BUFFER_MAX = 512
SETTLE_S = 5.0
PENDING_MAX_AGE_S = 900.0
_BOM = b"\xef\xbb\xbf"


def tft_log_path() -> Path:
    """TFT.log sits beside the per-round stats file (the P0 path seam)."""
    return p0.eog_stats_path().with_name("TFT.log")


def _open_shared(path: Path):
    """Read-only BINARY open that never blocks the client's own log rotation.

    The client renames TFT.log to TFT-backup-<utc>.log at each launch. A plain
    Windows open() lacks FILE_SHARE_DELETE, so a rename landing while a poll
    holds the file fails with WinError 32 (measured on RC's own day-log:
    tools/lcu_push_watcher.py `_win_open_shared_delete`). POSIX needs nothing.
    Raises OSError (the message carries no path: it can hold a user name)."""
    if sys.platform != "win32":
        return open(path, "rb")
    import ctypes  # noqa: PLC0415 - Windows-only, imported lazily
    import msvcrt  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.restype = wintypes.HANDLE
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    generic_read, share_all, open_existing, attr_normal = 0x80000000, 0x7, 3, 0x80
    h = create(str(path), generic_read, share_all, None, open_existing, attr_normal, None)
    if not h or h == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "TFT.log open failed")
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError:
        kernel32.CloseHandle(wintypes.HANDLE(h))
        raise
    return os.fdopen(fd, "rb")  # the fd owns the handle now


@dataclass(frozen=True)
class LogEvent:
    kind: str  # a tft.rounds.schema EVENT_KINDS value
    ts: float  # epoch seconds (UTC stamp)
    payload: dict


_STAMP = (r"\[(?P<y>\d{4})\.(?P<mo>\d{2})\.(?P<d>\d{2})-(?P<h>\d{2})\.(?P<mi>\d{2})\."
          r"(?P<s>\d{2}):(?P<ms>\d{3})\]\[ *\d{1,6}\]")
_CLIENT = r"TFT: \[Client\] "
_UNIT = r"\{(?P<unit>(?:DA|TFT[0-9]*)_[A-Za-z0-9_]{1,57})\}"
_VO = (r"TFTAudioEventSubsystem: Trigger\[Audio\.Event\.VO\.<cue>\] "
       r"Actor\[TFTCharacter_\d{1,12} " + _UNIT + r"\] "
       r"Plays Event\[A_VO_[A-Za-z0-9_]{1,80}\] with Interrupt Channel \[AC_VO_[A-Za-z]{1,32}\]")


def _rule(body: str):
    return re.compile("^" + _STAMP + body + "$")


# (name, event kind, anchored rule, payload builder)
_RULES = (
    ("phase", "phase", _rule(
        _CLIENT + r"TFTPerformanceSubsystem_\d{1,12}: Scheduled phase garbage collection - "
        r"time since last GC start: \[\d{1,7}(?:\.\d{1,6})?\] / "
        r"Phase\[ETFTPhaseType::(?P<phase>[A-Za-z]{1,32})\]"),
     lambda m: {"phase": m["phase"], "conf": PHASE_CONF}),
    ("phase_ceremony", "phase", _rule(
        _CLIENT + r"TFTTopCeremonySubsystem: Cleanup top ceremony at round "
        r"phase\[ETFTPhaseType::(?P<phase>[A-Za-z]{1,32})\]"),
     lambda m: {"phase": m["phase"], "conf": PHASE_CONF}),
    ("purchase_vo", "purchase_vo", _rule(_CLIENT + _VO.replace("<cue>", r"Unit\.Purchase")),
     lambda m: {"unit": m["unit"], "conf": HINT_CONF}),
    ("starup_vo", "starup_vo", _rule(_CLIENT + _VO.replace("<cue>", r"Unit\.StarUp\.(?P<star>[1-4])Star")),
     lambda m: {"unit": m["unit"], "star": int(m["star"]), "conf": HINT_CONF}),
    ("victory_vo", "victory_vo", _rule(
        _CLIENT + _VO.replace("<cue>", r"Army\.Round\.UnitCombatVictory")),
     lambda m: {"unit": m["unit"], "conf": HINT_CONF}),
    ("planner_saved", "planner_saved", _rule(
        _CLIENT + r"TFTPlannerSubsystem_\d{1,12}: Player TeamPlanner data saved\."),
     lambda m: {"conf": PHASE_CONF}),
    ("music", "carousel_music", _rule(
        r"LogTFTMusic: UTFTMusicPlayerSubsystem::SwitchToMusic - Switched to music "
        r"\[MS_Music_Set\d{1,3}_Gameplay(?P<carousel>_Carousel)?\]"),
     lambda m: {"track": "carousel" if m["carousel"] else "gameplay", "conf": PHASE_CONF}),
)
ALLOWLIST = tuple((name, kind) for name, kind, _rx, _build in _RULES)
# cheap substring gate before any regex: ~76k lines per match, a handful allowlisted
_HINTS = ("ETFTPhaseType::", "Audio.Event.VO.", "TeamPlanner data saved", "SwitchToMusic")


def _epoch(m) -> Optional[float]:
    try:
        parts = tuple(int(m[k]) for k in ("y", "mo", "d", "h", "mi", "s"))
        datetime.datetime(*parts)  # validates the calendar date / clock
    except ValueError:
        return None
    return calendar.timegm(parts + (0, 0, 0)) + int(m["ms"]) / 1000.0


def parse_line(line) -> Optional[LogEvent]:
    """One log line -> LogEvent when the whole line matches an allowlisted
    rule, else None. Never raises."""
    if not isinstance(line, str) or not line.startswith("[") or len(line) > MAX_LINE_BYTES:
        return None
    line = line.rstrip("\r\n \t")
    if not any(h in line for h in _HINTS):
        return None
    for _name, kind, rx, build in _RULES:
        m = rx.match(line)
        if m is None:
            continue
        ts = _epoch(m)
        return None if ts is None else LogEvent(kind, ts, build(m))
    return None


# ---------------------------------------------------------------- the bounded tail


class TftLogTail:
    """Offset tail over TFT.log: bounded reads, allowlist parse (see module)."""

    def __init__(self, path=None, *, max_bytes_per_poll: int = MAX_BYTES_PER_POLL,
                 max_line_bytes: int = MAX_LINE_BYTES, start: str = "begin"):
        if start not in ("begin", "end"):
            raise ValueError("start must be 'begin' or 'end'")
        self._path = Path(path) if path is not None else None
        self.max_bytes_per_poll = max(1, int(max_bytes_per_poll))
        self.max_line_bytes = max(1, int(max_line_bytes))
        self._start = start
        self.offset = 0
        self._header = None
        self._carry = b""
        self._skipping = False  # inside an overlong line: drop up to its newline
        self.stats = {"polls": 0, "bytes": 0, "last_read": 0, "max_read": 0, "lines": 0,
                      "events": 0, "dropped_long": 0, "rotations": 0, "errors": 0}

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else tft_log_path()

    def poll(self) -> list:
        """The allowlisted events in the bytes appended since the last poll
        (at most max_bytes_per_poll of them). Never raises."""
        self.stats["polls"] += 1
        self.stats["last_read"] = 0
        try:
            return self._poll()
        except OSError:
            return []
        except Exception as exc:  # noqa: BLE001 - fail-soft: never into the poll loop
            self.stats["errors"] += 1
            _log.debug("tft log: poll failed (%s)", type(exc).__name__)
            return []

    def _reset(self, header: bytes) -> None:
        self.offset, self._carry, self._skipping, self._header = 0, b"", False, header

    def _poll(self) -> list:
        with _open_shared(self.path) as fh:
            size = os.fstat(fh.fileno()).st_size
            head = fh.read(HEADER_BYTES)
            if self._header is None:
                self._header = head
                if self._start == "end" and size:
                    self.offset = size
                    fh.seek(size - 1)
                    self._skipping = fh.read(1) != b"\n"
            else:
                n = min(len(head), len(self._header))
                if size < self.offset or head[:n] != self._header[:n]:
                    self.stats["rotations"] += 1
                    self._reset(head)
                elif len(head) > len(self._header):
                    self._header = head
            if size <= self.offset:
                return []
            fh.seek(self.offset)
            from_zero = self.offset == 0
            data = fh.read(min(self.max_bytes_per_poll, size - self.offset))
        self.offset += len(data)
        self.stats["bytes"] += len(data)
        self.stats["last_read"] = len(data)
        self.stats["max_read"] = max(self.stats["max_read"], len(data))
        if from_zero and data.startswith(_BOM):
            data = data[len(_BOM):]
        return self._lines(data)

    def _lines(self, data: bytes) -> list:
        parts = (self._carry + data).split(b"\n")
        tail = parts.pop()
        events = []
        for raw in parts:
            if self._skipping:  # the rest of an overlong line
                self._skipping = False
                continue
            if len(raw) > self.max_line_bytes:
                self.stats["dropped_long"] += 1
                continue
            self.stats["lines"] += 1
            ev = parse_line(raw.decode("utf-8", "replace"))
            if ev is not None:
                events.append(ev)
        if self._skipping:
            tail = b""
        elif len(tail) > self.max_line_bytes:
            self.stats["dropped_long"] += 1
            self._skipping = True
            tail = b""
        self._carry = tail
        self.stats["events"] += len(events)
        return events


# ---------------------------------------------------------------- into the round store


class LogIngest:
    """Tail -> round store. `locate(ts)` returns (match_id, round_seq or None)
    or None when no match owns ts yet (see the module docstring)."""

    def __init__(self, store, tail: TftLogTail, locate: Callable, *,
                 clock: Callable[[], float] = time.time, settle_s: float = SETTLE_S,
                 buffer_max: int = BUFFER_MAX, max_pending_age_s: float = PENDING_MAX_AGE_S):
        self.store = store
        self.tail = tail
        self.locate = locate
        self.clock = clock
        self.settle_s = settle_s
        self.buffer_max = max(1, int(buffer_max))
        self.max_pending_age_s = max_pending_age_s
        self._pending = collections.deque()
        self._newest = None
        self.stats = {"read": 0, "written": 0, "pending": 0, "dropped_buffer": 0,
                      "dropped_stale": 0, "write_dropped": 0, "errors": 0}

    def poll(self) -> int:
        """Read new events and write every placeable one; returns how many
        were written (enqueued). Never raises."""
        try:
            return self._poll()
        except Exception as exc:  # noqa: BLE001 - fail-soft
            self.stats["errors"] += 1
            _log.debug("tft log: ingest failed (%s)", type(exc).__name__)
            return 0

    def _poll(self) -> int:
        for ev in self.tail.poll():
            self.stats["read"] += 1
            self._pending.append(ev)
            if self._newest is None or ev.ts > self._newest:
                self._newest = ev.ts
        while len(self._pending) > self.buffer_max:
            self._pending.popleft()
            self.stats["dropped_buffer"] += 1
        now = self.clock()
        keep, written = collections.deque(), 0
        for ev in self._pending:
            if now < ev.ts + self.settle_s:
                keep.append(ev)
                continue
            where = self.locate(ev.ts)
            if where is None:
                if self._newest - ev.ts > self.max_pending_age_s:
                    self.stats["dropped_stale"] += 1
                else:
                    keep.append(ev)
                continue
            mid, seq = where
            if self.store.put_event(mid, ev.kind, ev.payload, ts=ev.ts, round_seq=seq, src=SRC):
                written += 1
            else:
                self.stats["write_dropped"] += 1
        self._pending = keep
        self.stats["pending"] = len(keep)
        self.stats["written"] += written
        return written
