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
the MAIN checkout - fleet_lanes.main_tree(cwd) - never inside its worktree, so
the lane widget reads one named file per live lane.

Standalone: imports nothing from the rest of the kit. ASCII source; the box
glyph is emitted as U+2610. v10: emit() prints safely where print() fails - a
cp1252 console gets "[ ]" for the box, and pythonw (no stdout) prints nothing
(RSC 0523 item 7).
"""

import re

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


def item(id, task, state=None, eta_s=None):  # noqa: A002 - the spec's field name
    """One validated checklist row {id, task, state, eta_s}."""
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
    return {"id": id, "task": task, "state": state, "eta_s": eta_s}


def line(row, added=False):
    """`<box> <ID>: <task> (<state, ~ETA>)`; the parenthesis only while a task
    has a state other than pending; `+` before the ID marks an added task."""
    state = row.get("state")
    tail = ""
    if state and state != PENDING:
        eta = fmt_eta(row.get("eta_s"))
        tail = f" ({state}, {eta})" if eta else f" ({state})"
    return f"{BOX} {'+' if added else ''}{row['id']}: {row['task']}{tail}"


def render(session, rows, note=None, added=(), remaining=False):
    """The whole block. remaining=True is the after-4-completions update."""
    head = f"Session {int(session)} checklist" + (" - remaining" if remaining else "")
    out = [head] + [line(r, r["id"] in added) for r in rows] + [DONE_LINE]
    if note:
        note = " ".join(str(note).split())
        if note:
            out.append(note)
    return "\n".join(out)


class Checklist:
    """Tracks one session's tasks; prints per item 13."""

    def __init__(self, session, items=(), note=None):
        self.session = int(session)
        self.note = note
        self._rows = []
        self._done = set()
        self._added = set()
        self._since_print = 0
        for r in items:
            self._append(r if isinstance(r, dict) else item(*r))

    def _append(self, row):
        row = item(row["id"], row["task"], row.get("state"), row.get("eta_s"))
        if any(r["id"] == row["id"] for r in self._rows):
            raise ValueError(f"duplicate checklist id {row['id']}")
        self._rows.append(row)
        return row

    def _row(self, id):  # noqa: A002
        for r in self._rows:
            if r["id"] == id:
                return r
        raise KeyError(id)

    def start(self):
        """Session start / lane fire: every open task, then /done."""
        self._since_print = 0
        self._added.clear()
        return render(self.session, self.remaining(), self.note)

    def add(self, id, task, state=None, eta_s=None):  # noqa: A002
        row = self._append(item(id, task, state, eta_s))
        self._added.add(row["id"])
        return row

    def set_state(self, id, state, eta_s=None):  # noqa: A002
        r = self._row(id)
        new = item(id, r["task"], state, eta_s)
        r["state"], r["eta_s"] = new["state"], new["eta_s"]

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
                      added=set(self._added), remaining=True)
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


def emit(text, stream=None):
    """Print text; never raise for the console. A stream that cannot encode the
    box gets "[ ]" instead; a missing stream (pythonw) prints nothing. Returns
    the text actually written, or None."""
    import sys
    out = sys.stdout if stream is None else stream
    if out is None:
        return None
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
    return text
