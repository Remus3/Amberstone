# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit: the session checklist (FLEET-COMMON item 13, operator order 2026-10-05).

Every session kind - interactive, headless lane, loop tick, inbox responder -
prints a "Session <n> checklist" at start (and each time a lane or loop fires),
reprints ONLY the remaining tasks after every 4 or more completions (new ones
marked "+"), and runs /done unprompted when none remain. A headless fire also
writes the same list into its item-12 progress file as "checklist" so the
operator sees what every fire is doing without reading logs. Why: read from a
phone, the operator wants the tasks only.

    cl = Checklist(12, [item("C1", "Vendor kit v7 and run the suite",
                             "builder running", 240),
                        item("C2", "Answer MAIN's v7 order")],
                   note="C2 waits until C1 lands because the answer names the commit.")
    emit(cl.start())                   # header, one line per task, then /done
    msg = cl.complete("C1")            # str once 4+ completed since the last print
    cl.add("C3", "File the widget defect")
    if cl.all_done(): ...              # run /done now, unprompted
    fleet_headless.write_progress(root, "lane-0", pct, step, eta_s, "running",
                                  checklist=cl.rows())

A lane writes progress/lane-<i>.json (lane_task(i), i = its lane-lock index) in
the MAIN checkout, never inside its worktree, so the lane widget reads one
named file per live lane. Since kit v12 fleet_headless.write_progress resolves
the main checkout itself: pass the worktree cwd as root, no main_tree() call.

Standalone: imports nothing from the rest of the kit. ASCII source; the box
glyph is emitted as U+2610. v10: emit() prints safely where print() fails - a
cp1252 console gets "[ ]" for the box, and pythonw (no stdout) prints nothing
(RSC 0523 item 7).

v20 (CHECKLIST-ETA-CLOCK, operator order 2026-10-18): a running row that has a
start time reads `(<state>, <pct>% ~<rem>m of <total>m [h:mmAM/PM])`. rem and
total round UP to 0.5 min; total is re-estimated from elapsed / pct on each
update (eta_s only while pct is 0); the bracket is the local finish time,
recomputed on every start / update. The Checklist stamps "started" the first
time a row gets a state; a row without one keeps the old `~ETA` form.

v21 (KIT-ETA-REMAIN, operator order 2026-10-19): every running row shows the
time it STARTED and the clock carries the word Remain - one form everywhere:
`started <h:mmAM/PM> - <pct>% ~<rem> of <total> Remain [<finish h:mmAM/PM>]`.
The start is rounded DOWN to the minute, the finish UP. A running row with no
start reads `<pct>% ~<rem> Remain` (no start, no clock). A session prints its
chat checklist through render() / Checklist, never hand-typed ETA prose.
"""

import contextlib
import datetime as _dt
import math
import re
import time

BOX = "\u2610"
DONE_LINE = BOX + " /done"
UPDATE_EVERY = 4
TASK_MAX = 120
STATE_MAX = 40
ROWS_MAX = 20
PENDING = "pending"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,15}$")


def lane_task(index):
    """Progress-file task name for lane-lock index i: progress/lane-<i>.json."""
    i = int(index)
    if not 0 <= i <= 9:
        raise ValueError(f"lane index {index!r} outside 0..9")
    return f"lane-{i}"


def fmt_eta(eta_s):
    """FLEET-COMMON item 3 ETA units: s under 120 s, m under 120 m, h beyond."""
    if eta_s is None:
        return ""
    s = max(0, int(eta_s))
    if s < 120:
        return f"~{s}s"
    if s < 7200:
        return f"~{round(s / 60)}m"
    return f"~{round(s / 3600)}h"


def fmt_half_min(sec):
    """Seconds -> minutes rounded UP to 0.5: "30m", "22.5m", "0m". A 0.5 s
    tolerance keeps render jitter (ms between stamp and print) from adding
    half a minute."""
    n = max(0, math.ceil((max(0.0, float(sec)) - 0.5) / 30.0))
    return f"{n // 2}.5m" if n % 2 else f"{n // 2}m"


def fmt_clock(epoch, down=False):
    """Local wall-clock h:mmAM/PM, rounded UP to the minute (DOWN with
    down=True, v21: the start time)."""
    if down:
        t = _dt.datetime.fromtimestamp(math.floor(float(epoch) + 1e-6)).replace(second=0)
    else:
        t = _dt.datetime.fromtimestamp(math.ceil(float(epoch) - 1e-6))
        if t.second:
            t += _dt.timedelta(seconds=60 - t.second)
    return f"{t.hour % 12 or 12}:{t.minute:02d}{'AM' if t.hour < 12 else 'PM'}"


def started_clock(started):
    """v21: `started h:mmAM/PM` (rounded down), or "" when unreadable."""
    start = to_epoch(started)
    return "" if start is None else f"started {fmt_clock(start, down=True)}"


def to_epoch(value):
    """Epoch seconds from a number or an ISO-8601 text; None when unreadable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    try:
        return _dt.datetime.fromisoformat(str(value).strip()).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def eta_clock(pct, eta_s, started, now, updated=None):
    """`<pct>% ~<rem>m of <total>m Remain [h:mmAM/PM]` (v21 adds Remain), or
    "" without enough input.
    pct > 0 with a start: total = elapsed (to `updated`, else now) / pct and
    the finish is started + total. Otherwise the finish is updated + eta_s.
    rem counts down from now to that fixed finish."""
    pct = 0 if pct is None else max(0, min(100, int(pct)))
    start = to_epoch(started)
    ref = to_epoch(updated) or float(now)
    if pct > 0 and start is not None and ref > start:
        total = (ref - start) * 100.0 / pct
        finish = start + total
    elif eta_s is not None:
        finish = ref + max(0, int(eta_s))
        if start is not None and start <= ref:
            total = finish - start
        else:
            total = (finish - ref) * 100.0 / (100 - pct) if pct < 100 else finish - ref
    else:
        return ""
    rem = max(0.0, finish - float(now))
    return f"{pct}% ~{fmt_half_min(rem)} of {fmt_half_min(total)} Remain [{fmt_clock(finish)}]"


def run_clock(pct, eta_s, started, now, updated=None):
    """v21 (KIT-ETA-REMAIN) the one running-row form:
    `started h:mmAM/PM - <pct>% ~<rem> of <total> Remain [h:mmAM/PM]`; with no
    start `<pct>% ~<rem> Remain` (no clock); "" without enough input."""
    if to_epoch(started) is not None:
        clk = eta_clock(pct, eta_s, started, now, updated)
        return f"{started_clock(started)} - {clk}" if clk else ""
    rem = fmt_eta(eta_s)
    if not rem:
        return ""
    return (f"{max(0, min(100, int(pct)))}% " if pct is not None else "") + rem + " Remain"


def item(id, task, state=None, eta_s=None, pct=None, started=None):  # noqa: A002
    """One validated checklist row {id, task, state, eta_s}, plus "pct" and
    "started" (epoch seconds) when given (v20)."""
    if not isinstance(id, str) or not _ID.match(id):
        raise ValueError(f"checklist id {id!r} must be 1-16 chars [A-Za-z0-9._-]")
    if not isinstance(task, str) or not task.strip() or "\n" in task or "\r" in task:
        raise ValueError(f"task for {id} must be one non-empty line")
    task = task.strip()
    if len(task) > TASK_MAX:
        raise ValueError(f"task for {id} longer than {TASK_MAX} chars - one line")
    if state is not None:
        if not isinstance(state, str) or "\n" in state or len(state) > STATE_MAX:
            raise ValueError(f"state for {id} must be one line of <= {STATE_MAX} chars")
        state = state.strip() or None
    if eta_s is not None:
        eta_s = max(0, int(eta_s))
    row = {"id": id, "task": task, "state": state, "eta_s": eta_s}
    if pct is not None:
        row["pct"] = max(0, min(100, int(pct)))
    started = to_epoch(started)
    if started is not None:
        row["started"] = started
    return row


def line(row, added=False, now=None):
    """`<box> <ID>: <task> (<state>, started h:mmAM/PM - <pct>% ~<rem>m of
    <total>m Remain [h:mmAM/PM])` for a running row with a start time (v21),
    else `(<state>, <pct>% ~ETA Remain)`; the
    parenthesis only while a task has a state other than pending; `+` before
    the ID marks an added task."""
    state = row.get("state")
    tail = ""
    if state and state != PENDING:
        eta = run_clock(row.get("pct"), row.get("eta_s"), row.get("started"),
                        time.time() if now is None else now)
        tail = f" ({state}, {eta})" if eta else f" ({state})"
    return f"{BOX} {'+' if added else ''}{row['id']}: {row['task']}{tail}"


def render(session, rows, note=None, added=(), remaining=False, now=None):
    """The whole block. remaining=True is the after-4-completions update."""
    head = f"Session {int(session)} checklist" + (" - remaining" if remaining else "")
    out = [head] + [line(r, r["id"] in added, now) for r in rows] + [DONE_LINE]
    if note:
        note = " ".join(str(note).split())
        if note:
            out.append(note)
    return "\n".join(out)


class Checklist:
    """Tracks one session's tasks; prints per item 13."""

    def __init__(self, session, items=(), note=None, clock=time.time):
        self.session = int(session)
        self.note = note
        self._clock = clock
        self._rows = []
        self._done = set()
        self._added = set()
        self._since_print = 0
        for r in items:
            self._append(r if isinstance(r, dict) else item(*r))

    def _append(self, row):
        row = item(row["id"], row["task"], row.get("state"), row.get("eta_s"),
                   row.get("pct"), row.get("started"))
        if any(r["id"] == row["id"] for r in self._rows):
            raise ValueError(f"duplicate checklist id {row['id']}")
        self._stamp(row)
        self._rows.append(row)
        return row

    def _stamp(self, row):
        """v20: the first non-pending state starts the row's clock."""
        if row.get("state") and row["state"] != PENDING and "started" not in row:
            row["started"] = float(self._clock())

    def _row(self, id):  # noqa: A002
        for r in self._rows:
            if r["id"] == id:
                return r
        raise KeyError(id)

    def start(self):
        """Session start / lane fire: every open task, then /done."""
        self._since_print = 0
        self._added.clear()
        return render(self.session, self.remaining(), self.note, now=self._clock())

    def add(self, id, task, state=None, eta_s=None, pct=None):  # noqa: A002
        row = self._append(item(id, task, state, eta_s, pct))
        self._added.add(row["id"])
        return row

    def set_state(self, id, state, eta_s=None, pct=None):  # noqa: A002
        """New state / ETA; pct (v20) re-estimates the total from elapsed / pct."""
        r = self._row(id)
        new = item(id, r["task"], state, eta_s, pct)
        r["state"], r["eta_s"] = new["state"], new["eta_s"]
        if "pct" in new:
            r["pct"] = new["pct"]
        self._stamp(r)

    def complete(self, id):  # noqa: A002
        """Mark done. Returns the remaining-only update once 4+ tasks completed
        since the last print, else None. Returns None when nothing remains:
        the caller then runs /done (all_done())."""
        self._row(id)
        if id in self._done:
            return None
        self._done.add(id)
        self._since_print += 1
        if self._since_print < UPDATE_EVERY or self.all_done():
            return None
        return self.update()

    def update(self):
        """Remaining tasks only, added ones marked +; resets the counter."""
        text = render(self.session, self.remaining(), self.note,
                      added=set(self._added), remaining=True, now=self._clock())
        self._since_print = 0
        self._added.clear()
        return text

    def remaining(self):
        return [dict(r) for r in self._rows if r["id"] not in self._done]

    def all_done(self):
        return not self.remaining()

    def rows(self):
        """The progress-file "checklist" field: remaining tasks, in order."""
        return self.remaining()[:ROWS_MAX]


ASCII_BOX = "[ ]"


def _write(out, text):
    """Write one line and flush; (text written) or None. Never raises."""
    try:
        out.write(text + "\n")
    except UnicodeEncodeError:
        text = text.replace(BOX, ASCII_BOX).encode("ascii", "replace").decode("ascii")
        try:
            out.write(text + "\n")
        except (OSError, ValueError):
            return None
    except (OSError, ValueError, AttributeError):
        return None
    with contextlib.suppress(OSError, ValueError, AttributeError):
        out.flush()
    return text


def emit(text, stream=None, tee=None):
    """Print text; never raise for the console. A stream that cannot encode the
    box gets "[ ]" instead; a missing stream (pythonw) prints nothing. Returns
    the text actually written, or None.
    v20 (KIT-EMIT-FLUSH, CS 1212 item 2): the stream is flushed after the
    line, and an optional tee stream (a log sink) gets the same line; a tee
    failure is ignored and never changes the return value."""
    import sys
    out = sys.stdout if stream is None else stream
    if tee is not None:
        _write(tee, text)
    if out is None:
        return None
    return _write(out, text)
