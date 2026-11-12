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

v30 (KIT-CHECKLIST-CAPS, ruling docs/rulings/2026-11-08-kit-checklist-caps.md
(a), built into v30 because v30 missed its queue night): one text rule, clip()
- an over-long task is CLIPPED to TASK_MAX ending "..." (no longer raised);
whitespace collapses, non-ASCII becomes "?". One row rule, cap_rows(): past
ROWS_MAX the rows are cut and their ids kept. Checklist.rows() stays capped;
Checklist.more() names what was cut. Checklist.start()/update() (render with
cap=True) print ONE overflow line directly above the /done box:
`(+<N> more past the 20-row cap: <ID>, <ID>, ...)` - the kit's line, not the
trailing sentence. A direct render() without cap=True prints as before.

v30 (SUPERVISION-STALL): past 2x (floor 300 s) the suffix is STALE instead of OVERRUN.
scan() and the CLI `python fleet_checklist.py stale [DIR ...]` list the running
progress rows past OVERRUN or STALE (ruling docs/rulings/2026-11-08-sweep2-candidates.md
item 1), read before any status answer; exit 3 when a STALE row exists.
"""

import contextlib
import datetime as _dt
import json
import math
import re
import sys
import time
from pathlib import Path

BOX = "\u2610"
DONE_LINE = BOX + " /done"
UPDATE_EVERY = 4
TASK_MAX = 120
STATE_MAX = 40
ROWS_MAX = 20
OVER_IDS_MAX = 160  # = fleet_board.TEXT_MAX (A3)
PENDING = "pending"
ID_MAX = 48  # v26 (VW FIX 0612): = fleet_board.ID_MAX, was 16
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0," + str(ID_MAX - 1) + r"}$")


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


OVERRUN_FACTOR = 1.5  # v29: FLEET-COMMON 3 reports an overrun at 1.5x
OVERRUN_FLOOR_S = 60


def overrun(eta_s, updated, now):
    """v29 (SUPERVISION-GAP): a row last written at `updated` claiming eta_s more
    seconds, now past OVERRUN_FACTOR times that (floor OVERRUN_FLOOR_S). False
    without an ETA or a readable write time: no claim, no overrun."""
    then = to_epoch(updated)
    if eta_s is None or then is None:
        return False
    return float(now) - then > max(OVERRUN_FACTOR * max(0, eta_s), OVERRUN_FLOOR_S)


STALE_FACTOR = 2.0  # v30 (SUPERVISION-STALL): FLEET-COMMON 12, a row past 2x
STALE_FLOOR_S = 300  # mirrors fleet_statusline.js STALE_FLOOR_S


def stale(eta_s, updated, now):
    """v30: a row last written at `updated` claiming eta_s more seconds, now past
    STALE_FACTOR times that (floor STALE_FLOOR_S). False without an ETA or a
    readable write time."""
    then = to_epoch(updated)
    if eta_s is None or then is None:
        return False
    return float(now) - then > max(STALE_FACTOR * max(0, eta_s), STALE_FLOOR_S)


def run_clock(pct, eta_s, started, now, updated=None):
    """v21 (KIT-ETA-REMAIN) the one running-row form:
    `started h:mmAM/PM - <pct>% ~<rem> of <total> Remain [h:mmAM/PM]`; with no
    start `<pct>% ~<rem> Remain` (no clock); "" without enough input.
    v29: either form ends ` OVERRUN` past overrun().
    v30: ` STALE` instead past stale()."""
    late = (" STALE" if stale(eta_s, updated, now)
            else " OVERRUN" if overrun(eta_s, updated, now) else "")
    if to_epoch(started) is not None:
        clk = eta_clock(pct, eta_s, started, now, updated)
        return f"{started_clock(started)} - {clk}{late}" if clk else ""
    rem = fmt_eta(eta_s)
    if not rem:
        return ""
    return (f"{max(0, min(100, int(pct)))}% " if pct is not None else "") + rem + " Remain" + late


def clip(text, limit=TASK_MAX):
    """One marked text rule (KIT-CHECKLIST-CAPS A1, the fleet_board._clip form):
    whitespace collapsed to single spaces, ASCII with ? for anything else, and
    past limit cut to exactly limit chars ending "..."."""
    text = " ".join(str(text or "").split())
    text = text.encode("ascii", "replace").decode("ascii")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def cap_rows(rows, limit=ROWS_MAX):
    """One row rule (A2): (kept, over_ids) - the first `limit` rows, and the
    ids of every row past it, in order."""
    rows = list(rows)
    return rows[:limit], [r["id"] for r in rows[limit:]]


def over_line(over_ids):
    """A3: the one overflow line, or None. Starts with "(", never the box, so a
    strict board parse never takes it for a row; the id list is clipped to
    OVER_IDS_MAX (fleet_board.TEXT_MAX) and ends "..." when cut."""
    over_ids = list(over_ids or ())
    if not over_ids:
        return None
    ids = clip(", ".join(over_ids), OVER_IDS_MAX)
    return f"(+{len(over_ids)} more past the {ROWS_MAX}-row cap: {ids})"


def item(id, task, state=None, eta_s=None, pct=None, started=None):  # noqa: A002
    """One validated checklist row {id, task, state, eta_s}, plus "pct" and
    "started" (epoch seconds) when given (v20)."""
    if not isinstance(id, str) or not _ID.match(id):
        raise ValueError(f"checklist id {id!r} must be 1-{ID_MAX} chars [A-Za-z0-9._-]")
    if not isinstance(task, str) or not task.strip() or "\n" in task or "\r" in task:
        raise ValueError(f"task for {id} must be one non-empty line")
    task = clip(task)  # v30 A1: clipped with a marker, never raised over length
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
                        time.time() if now is None else now, row.get("updated"))
        tail = f" ({state}, {eta})" if eta else f" ({state})"
    return f"{BOX} {'+' if added else ''}{row['id']}: {row['task']}{tail}"


def render(session, rows, note=None, added=(), remaining=False, now=None, cap=False,
           over=()):
    """The whole block. remaining=True is the after-4-completions update.
    v30: cap=True cuts the rows at ROWS_MAX and prints the overflow line above
    the /done box (over= names cut ids explicitly); the note still comes last."""
    over = list(over or ())
    if cap:
        rows, cut = cap_rows(rows)
        over = cut + [x for x in over if x not in cut]
    head = f"Session {int(session)} checklist" + (" - remaining" if remaining else "")
    out = [head] + [line(r, r["id"] in added, now) for r in rows]
    more = over_line(over)
    if more:
        out.append(more)
    out.append(DONE_LINE)
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
        return render(self.session, self.remaining(), self.note, now=self._clock(),
                      cap=True)

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
                      added=set(self._added), remaining=True, now=self._clock(),
                      cap=True)
        self._since_print = 0
        self._added.clear()
        return text

    def remaining(self):
        return [dict(r) for r in self._rows if r["id"] not in self._done]

    def all_done(self):
        return not self.remaining()

    def rows(self):
        """The progress-file "checklist" field: remaining tasks, in order."""
        return cap_rows(self.remaining())[0]

    def more(self):
        """v30 A2: {"count": N, "ids": [...]} for the rows past ROWS_MAX, else None."""
        over = cap_rows(self.remaining())[1]
        return {"count": len(over), "ids": over} if over else None


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


STEP_MAX = 60
DEFAULT_PROGRESS = Path("ops") / "loop" / "control" / "progress"


def scan(dirs, now=None):
    """v30 (SUPERVISION-STALL): every running progress row in dirs past OVERRUN
    or STALE, as [{"task", "verdict", "age_s", "eta_s", "step"}], STALE first
    then oldest first. Age is now minus `updated`, else the file mtime.
    Unreadable files are skipped; never raises."""
    now = time.time() if now is None else float(now)
    hits = []
    for d in dirs or ():
        try:
            paths = sorted(p for p in Path(d).iterdir() if p.suffix == ".json")
        except (OSError, TypeError, ValueError):
            continue
        for path in paths:
            name = path.name
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                mtime = path.stat().st_mtime
            except (OSError, ValueError, UnicodeError):
                continue
            if not isinstance(row, dict) or row.get("status") != "running":
                continue
            eta = row.get("eta_s")
            try:
                eta = None if eta is None or isinstance(eta, bool) else max(0, int(eta))
            except (TypeError, ValueError, OverflowError):
                eta = None
            then = to_epoch(row.get("updated")) or mtime
            if stale(eta, then, now):
                verdict = "STALE"
            elif overrun(eta, then, now):
                verdict = "OVERRUN"
            else:
                continue
            task = row.get("task") if isinstance(row.get("task"), str) else name[:-5]
            hits.append({"task": clip(task or name[:-5], STEP_MAX), "verdict": verdict,
                         "age_s": max(0.0, now - then), "eta_s": eta,
                         "step": clip(row.get("step") if isinstance(row.get("step"), str)
                                      else "", STEP_MAX)})
    hits.sort(key=lambda h: (h["verdict"] != "STALE", -h["age_s"]))
    return hits


def stale_lines(hits):
    """One ASCII line per hit, or the single line `stale: none`."""
    if not hits:
        return ["stale: none"]
    return [f"{h['task']}: {h['verdict']} silent {fmt_half_min(h['age_s'])}, "
            f"eta {fmt_half_min(h['eta_s'] or 0)}, step {h['step']}" for h in hits]


def main(argv=None):
    """CLI: `stale [DIR ...]` (default ops/loop/control/progress under the cwd).
    Exit 3 when any STALE hit, else 0; 2 on a usage error."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != "stale":
        _write(sys.stderr, "usage: fleet_checklist.py stale [DIR ...]")
        return 2
    hits = scan(argv[1:] or [Path.cwd() / DEFAULT_PROGRESS])
    for text in stale_lines(hits):
        emit(text)
    return 3 if any(h["verdict"] == "STALE" for h in hits) else 0


if __name__ == "__main__":
    sys.exit(main())
