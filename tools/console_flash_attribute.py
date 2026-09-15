"""Join a console-window capture to a process-start trace, post hoc.

A console flash lives about 20-40 ms, so nothing can identify its owner while it
is on screen: a window lookup costs about 65 ms on this box (measured
2026-09-14 from the inter-event spacing of a per-event CIM sampler), which is
longer than the window. The capture is therefore split in three and joined here:

* ``tools/console_flash_detector.py``  - stamps every console window at RECEIPT,
  before any lookup, and logs hwnd / pid / exe / class.
* ``tools/console_flash_trace.ps1``    - records ProcessName / pid / ppid /
  creation time per process start, with no inline lookup of any kind.
* ``tools/console_flash_control.py``   - the positive control, which says which
  spawns were deliberate and which of those carried CREATE_NO_WINDOW.

WHAT THIS MODULE REFUSES, AND WHY.

A pid-only join is wrong by construction on Windows. Measured 2026-09-14: a
conhost pid was re-issued eight minutes after a flash, so joining on pid alone
credited a window to a process that did not exist when the window appeared. So
a candidate is refused when its start is AFTER the event, and a pid carrying
more than one start at or before the event is refused as ambiguous rather than
resolved by picking the nearest - the record genuinely cannot say which one
owned the window, and a confident wrong answer is worse than UNATTRIBUTED.

Absence is reported, never assumed:

* no trace at all (the tracer printed START-TRACE UNAVAILABLE, or there is no
  trace stream) makes EVERY event UNATTRIBUTED with that reason;
* a heartbeat gap over 90 s is a DEAD-WINDOW - a span in which the detector
  proved nothing, which must never read as a quiet machine (a 63-byte sampler
  log with no END was exactly this shape on 2026-09-14);
* a control spawn with a START line and no joined event is reported as such,
  because that is what distinguishes "spawned and did not show a window" from
  "was never sampled".

OUTPUT IS BASENAMES ONLY BY DEFAULT. A real capture's command lines carry the
account home directory and the names of neighbouring projects on this box, and
``.log`` is outside tests/test_no_hardcoded_home_path.py's runnable suffixes, so
nothing downstream would catch them. ``--command-lines`` renders them when the
tracer was run with its own opt-in switch; that output is never committed.

No subprocess is spawned from this module - it is pure parsing so that CI can
hold it without a Windows desktop.

Usage:
  python.exe tools/console_flash_attribute.py <detector log> [<trace log> ...]
  python.exe tools/console_flash_attribute.py <merged log> --out report.txt
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent

#: A heartbeat interval longer than this proves nothing happened only in the
#: sense that nothing was WATCHED. Three times the detector's 30 s cadence.
DEAD_WINDOW_SECONDS = 90.0

#: MEASURED 2026-09-15 by this repository's own positive control, and the reason
#: this constant exists at all. Win32_ProcessStartTrace TIME_CREATED is an
#: EVENT-GENERATION stamp, not a process creation time: WMI delivered the start
#: of a cmd.exe at 18:36:57.868 that the control had spawned at 18:36:56.466 and
#: the detector had already seen a window for at 18:36:56.497 - 1.40 s of
#: delivery lag, and the same batch stamp shared by a process and its conhost.
#: A literal "started after the event, so it cannot own it" rule refused all
#: four genuine control pairs on that run.
#:
#: So the rule is kept and BOUNDED rather than dropped. 5 s is about 3.5x the
#: measured lag and three orders of magnitude below the eight-minute pid recycle
#: this join exists to refuse, so the refutation the tolerance could have
#: destroyed still holds. Widening this past a few seconds re-admits that
#: failure; do not raise it without a new measurement.
TRACE_LAG_SECONDS = 5.0

DEAD_WINDOW = "DEAD-WINDOW"
ROOT_UNKNOWN = "ROOT-UNKNOWN"
TRACE_UNAVAILABLE = "START-TRACE UNAVAILABLE"
UNATTRIBUTED = "UNATTRIBUTED"

REASON_NO_TRACE = "no process trace (START-TRACE UNAVAILABLE)"
REASON_NO_RECORD = "no trace record carries this pid"
REASON_START_AFTER_EVENT = "every trace record for this pid starts after the event"
REASON_PID_RECYCLED = "pid re-issued at or before the event - owner is ambiguous"

_CMD_MARKER = " cmd="


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_stamp(raw: str) -> Optional[datetime]:
    """ISO-8601, with or without a trailing ``Z``. Naive stamps are read as UTC."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        out = datetime.fromisoformat(text)
    except ValueError:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out


def _tokens(line: str) -> Dict[str, str]:
    """``key=value`` pairs after the leading marker word(s).

    Values never contain whitespace, with one exception: a command line, which
    is always last and is taken as the whole remainder after `` cmd=``.
    """
    body = line
    head, marker, tail = line.partition(_CMD_MARKER)
    out: Dict[str, str] = {}
    if marker:
        body = head
        out["cmd"] = tail.strip()
    for chunk in body.split()[1:]:
        key, sep, value = chunk.partition("=")
        if sep:
            out[key] = value
    return out


def _as_int(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        return None


@dataclass(frozen=True)
class ConsoleEvent:
    stamp: datetime
    pid: int
    hwnd: str
    exe: str
    cls: str
    lineno: int


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    ppid: Optional[int]
    name: str
    created: datetime
    kind: str
    cmd: str = ""


@dataclass(frozen=True)
class ControlSpawn:
    seq: int
    flagged: bool
    name: str
    pid: int
    stamp: datetime


@dataclass
class Capture:
    """Everything a merged capture stream carries, parsed but not interpreted."""

    detector_start: Optional[datetime] = None
    detector_end: Optional[datetime] = None
    heartbeats: List[datetime] = field(default_factory=list)
    events: List[ConsoleEvent] = field(default_factory=list)
    hook_lost: List[str] = field(default_factory=list)
    controls: List[ControlSpawn] = field(default_factory=list)
    records: List[ProcessRecord] = field(default_factory=list)
    trace_seen: bool = False
    trace_available: bool = False
    trace_reason: str = ""


def parse_capture(text: str) -> Capture:
    """Parse a detector log, a trace log, a control log, or all three merged.

    Merged is the normal case: the line markers are disjoint on purpose so the
    streams can be concatenated in any order without a schema negotiation.
    """
    cap = Capture()
    for lineno, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        marker = line.split(maxsplit=1)[0]
        tok = _tokens(line)
        stamp = parse_stamp(tok.get("ts", ""))

        if marker == "START":
            cap.detector_start = stamp
        elif marker == "END":
            cap.detector_end = stamp
        elif marker == "HEARTBEAT":
            if stamp is not None:
                cap.heartbeats.append(stamp)
        elif marker == "HOOK":
            cap.hook_lost.append(line)
        elif marker == "EVENT":
            pid = _as_int(tok.get("pid"))
            if stamp is None or pid is None:
                continue
            cap.events.append(ConsoleEvent(
                stamp=stamp, pid=pid, hwnd=tok.get("hwnd", ""),
                exe=tok.get("exe", ""), cls=tok.get("cls", ""), lineno=lineno,
            ))
        elif marker == "CONTROL":
            pid = _as_int(tok.get("pid"))
            seq = _as_int(tok.get("seq"))
            if stamp is None or pid is None or seq is None:
                continue
            cap.controls.append(ControlSpawn(
                seq=seq, flagged=tok.get("flagged", "0") not in ("0", "false", "False"),
                name=tok.get("name", ""), pid=pid, stamp=stamp,
            ))
        elif marker == "START-TRACE":
            cap.trace_seen = True
            if "UNAVAILABLE" in line.split(maxsplit=2)[:2]:
                cap.trace_available = False
                cap.trace_reason = tok.get("reason", "") or TRACE_UNAVAILABLE
            else:
                cap.trace_available = True
        elif marker in ("PROCESS", "SNAPSHOT"):
            pid = _as_int(tok.get("pid"))
            created = parse_stamp(tok.get("created", "")) or stamp
            if pid is None or created is None:
                continue
            cap.records.append(ProcessRecord(
                pid=pid, ppid=_as_int(tok.get("ppid")), name=tok.get("name", ""),
                created=created, kind=marker, cmd=tok.get("cmd", ""),
            ))
    return cap


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


@dataclass
class EventAttribution:
    event: ConsoleEvent
    record: Optional[ProcessRecord]
    reason: str
    chain: List[ProcessRecord] = field(default_factory=list)
    chain_text: str = ROOT_UNKNOWN


@dataclass
class ControlOutcome:
    control: ControlSpawn
    events: List[ConsoleEvent] = field(default_factory=list)


@dataclass
class DeadWindow:
    start: datetime
    end: datetime
    seconds: float


@dataclass
class Report:
    attributions: List[EventAttribution] = field(default_factory=list)
    controls: List[ControlOutcome] = field(default_factory=list)
    dead_windows: List[DeadWindow] = field(default_factory=list)
    heartbeat_after_controls: bool = False
    trace_available: bool = False
    trace_reason: str = ""
    hook_lost: List[str] = field(default_factory=list)
    command_lines: bool = False


def _by_pid(records: Sequence[ProcessRecord]) -> Dict[int, List[ProcessRecord]]:
    index: Dict[int, List[ProcessRecord]] = {}
    seen = set()
    for rec in records:
        key = (rec.pid, rec.created)
        if key in seen:
            continue
        seen.add(key)
        index.setdefault(rec.pid, []).append(rec)
    for bucket in index.values():
        bucket.sort(key=lambda r: r.created)
    return index


def _ancestry(record: ProcessRecord,
              index: Dict[int, List[ProcessRecord]]) -> List[ProcessRecord]:
    chain = [record]
    seen = {record.pid}
    cur = record
    while True:
        ppid = cur.ppid
        if ppid is None or ppid in seen:
            break
        # Same horizon as the event join: a parent and its child frequently
        # share ONE delivery batch stamp (measured 2026-09-15 - cmd.exe 7812 and
        # its conhost both stamped 18:36:57.868207), so a strict `<` would cut
        # every chain at its first hop.
        parents = [
            r for r in index.get(ppid, ())
            if r.created <= cur.created + timedelta(seconds=TRACE_LAG_SECONDS)
        ]
        if not parents:
            break
        cur = parents[-1]
        chain.append(cur)
        seen.add(cur.pid)
    return chain


def _chain_text(chain: Sequence[ProcessRecord], command_lines: bool) -> str:
    parts = []
    for rec in chain:
        token = "{}({})".format(rec.name or "?", rec.pid)
        if command_lines and rec.cmd:
            token += f" [{rec.cmd}]"
        parts.append(token)
    parts.append(ROOT_UNKNOWN)
    return " <- ".join(parts)


def attribute(capture: Capture, *, command_lines: bool = False) -> Report:
    """Join every console event to the process that owned it, or say why not."""
    index = _by_pid(capture.records)
    # The trace's start stamp is an UPPER BOUND on the real start, lagging it by
    # a measured 1.4 s (see TRACE_LAG_SECONDS). The horizon below is what the
    # rule "a process cannot own a window that predates it" becomes once the
    # measurement is admitted; it is deliberately far tighter than the recycle
    # interval that motivated the rule.
    horizon = timedelta(seconds=TRACE_LAG_SECONDS)
    report = Report(
        trace_available=capture.trace_available,
        trace_reason=capture.trace_reason,
        hook_lost=list(capture.hook_lost),
        command_lines=command_lines,
    )

    for event in sorted(capture.events, key=lambda e: e.stamp):
        if not capture.trace_available:
            report.attributions.append(
                EventAttribution(event=event, record=None, reason=REASON_NO_TRACE))
            continue
        candidates = index.get(event.pid, [])
        if not candidates:
            report.attributions.append(
                EventAttribution(event=event, record=None, reason=REASON_NO_RECORD))
            continue
        eligible = [r for r in candidates if r.created <= event.stamp + horizon]
        if not eligible:
            report.attributions.append(EventAttribution(
                event=event, record=None, reason=REASON_START_AFTER_EVENT))
            continue
        if len(eligible) > 1:
            report.attributions.append(EventAttribution(
                event=event, record=None, reason=REASON_PID_RECYCLED))
            continue
        chain = _ancestry(eligible[0], index)
        report.attributions.append(EventAttribution(
            event=event, record=eligible[0], reason="", chain=chain,
            chain_text=_chain_text(chain, command_lines),
        ))

    for control in sorted(capture.controls, key=lambda c: c.seq):
        outcome = ControlOutcome(control=control)
        for item in report.attributions:
            if item.record is None or item.event.stamp < control.stamp:
                continue
            pids = {rec.pid for rec in item.chain} | {item.event.pid}
            if control.pid in pids:
                outcome.events.append(item.event)
        report.controls.append(outcome)

    markers = [m for m in [capture.detector_start] if m is not None]
    markers.extend(capture.heartbeats)
    if capture.detector_end is not None:
        markers.append(capture.detector_end)
    markers.sort()
    for first, second in zip(markers, markers[1:]):
        gap = (second - first).total_seconds()
        if gap > DEAD_WINDOW_SECONDS:
            report.dead_windows.append(DeadWindow(start=first, end=second, seconds=gap))

    if capture.controls and capture.heartbeats:
        last_control = max(c.stamp for c in capture.controls)
        report.heartbeat_after_controls = any(h > last_control for h in capture.heartbeats)

    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _stamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def render(report: Report) -> str:
    lines = ["CONSOLE FLASH ATTRIBUTION"]
    if report.trace_available:
        lines.append("process trace: available")
    else:
        lines.append("process trace: {} ({})".format(
            TRACE_UNAVAILABLE, report.trace_reason or "no trace stream in the capture"))
    for lost in report.hook_lost:
        lines.append(f"detector: {lost}")
    lines.append("")

    lines.append(f"EVENTS ({len(report.attributions)})")
    if not report.attributions:
        lines.append("  none - no console window was detected in this capture")
    for item in report.attributions:
        head = "  {} hwnd={} pid={} cls={}".format(
            _stamp_text(item.event.stamp), item.event.hwnd or "?",
            item.event.pid, item.event.cls or "?")
        lines.append(head)
        if item.record is None:
            lines.append(f"    {UNATTRIBUTED}: {item.reason}")
        else:
            lines.append(f"    {item.chain_text}")
    lines.append("")

    lines.append(f"CONTROLS ({len(report.controls)})")
    for outcome in report.controls:
        state = f"EVENT x{len(outcome.events)}" if outcome.events else "no event"
        lines.append("  seq={} flagged={} name={} pid={} -> {}".format(
            outcome.control.seq, int(outcome.control.flagged),
            outcome.control.name or "?", outcome.control.pid, state))
    if report.controls:
        lines.append("  heartbeat after the last control: {}".format(
            "yes" if report.heartbeat_after_controls else "NO"))
    lines.append("")

    lines.append("LIVENESS")
    if report.dead_windows:
        for span in report.dead_windows:
            lines.append(f"  {DEAD_WINDOW} {_stamp_text(span.start)} -> {_stamp_text(span.end)} ({span.seconds:.1f}s unwatched)")
    else:
        lines.append(f"  no heartbeat gap over {DEAD_WINDOW_SECONDS:.0f}s")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_atomic(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="ascii", errors="replace")
    tmp.replace(target)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="join a console-window capture to a process-start trace")
    parser.add_argument("logs", nargs="+", type=Path,
                        help="detector log, trace log and/or control log, in any order")
    parser.add_argument("--command-lines", action="store_true",
                        help="render captured command lines (never commit this output)")
    parser.add_argument("--out", type=Path, default=None,
                        help="write the report here instead of stdout")
    args = parser.parse_args(list(argv) if argv is not None else None)

    chunks = []
    for path in args.logs:
        if not path.exists():
            sys.stderr.write(f"missing capture log: {path.name}\n")
            return 2
        chunks.append(path.read_text(encoding="utf-8", errors="replace"))

    report = attribute(parse_capture("\n".join(chunks)),
                       command_lines=args.command_lines)
    text = render(report)
    if args.out is not None:
        _write_atomic(args.out, text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
