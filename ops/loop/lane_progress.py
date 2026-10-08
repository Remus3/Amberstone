#!/usr/bin/env python
r"""Session checklist + item-12 progress file for every headless fire (kit v7).

FLEET-COMMON item 13 (operator order 2026-10-05, MAIN 0215 sections 2d + 4d).
Every time a headless lane or the loop fires it:
  - builds a `fleet_checklist.Checklist` (session n = the fire's run count),
  - PRINTS the block to its log at fire start, and the remaining-only update
    once 4+ tasks completed,
  - WRITES it as the "checklist" field (remaining tasks only) of its item-12
    progress file via `fleet_headless.write_progress(checklist=)`, at fire
    start and after every task.

WHERE. A lane writes `ops/loop/control/progress/lane-<i>.json`, i = its
lane-lock index, in the MAIN checkout - `fleet_lanes.main_tree` - never inside
its worktree, so the lane widget reads one named file per live lane. The main
checkout is resolved from THIS file's checkout (`main_checkout()`), which is
`main_tree(cwd)` whenever the runner starts inside the repo or one of its
worktrees, and stays right when a scheduled task starts it from an unrelated
cwd (where `main_tree(cwd)` would answer that unrelated directory).

The loop controller holds no lane lock, so it has no index; it writes the same
shape to `progress/loop.json` rather than borrow an index a real lane may hold.

NEVER FAILS A LANE. A progress write that raises is reported through `emit`
and swallowed: the file is an operator's window onto the run, not part of it.
Every line reaches `emit` through the kit's `fleet_checklist.emit()` (kit v10,
MAIN 2026-10-08 0839 step 5), so a sink that cannot encode the U+2610 box
(print() to a cp1252 file under pythonw) gets "[ ]" and a dead sink is
swallowed - a print fault never escapes into the fire (`launch_lane` calls
`start()` before the try that releases its lane on failure).

The three kit modules are CONSUMED, never edited (byte-pinned by
ops/fleet_kit/MANIFEST.json).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_KIT = _HERE.parent / "fleet_kit"


def _bind_kit(name: str):
    """Package import first (one module object per process), absolute-path
    bind as the fallback for the script / launcher context."""
    try:
        return importlib.import_module(f"ops.fleet_kit.{name}")
    except ImportError:
        pass
    modname = f"rc_fleet_kit_{name}"
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, _KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


fleet_checklist = _bind_kit("fleet_checklist")
fleet_headless = _bind_kit("fleet_headless")
fleet_lanes = _bind_kit("fleet_lanes")

LOOP_TASK = "loop"

# Test seam: tests/conftest.py points this at a tmp dir so no test writes the
# operator's live progress dir. Production never sets it.
ROOT_OVERRIDE: Path | None = None
ROOT_ENV = "RC_LANE_PROGRESS_ROOT"


def main_checkout() -> Path:
    """The MAIN checkout of the tree this file lives in (worktree-safe)."""
    if ROOT_OVERRIDE is not None:
        return Path(ROOT_OVERRIDE)
    # Inherited by child processes, which a module attribute is not: the suite
    # launches the controller as a SUBPROCESS (tests/test_loop_concurrency.py),
    # and without this its dry-run cycle wrote the live progress/loop.json
    # (measured 2026-10-05).
    env = os.environ.get(ROOT_ENV, "").strip()
    if env:
        return Path(env)
    return fleet_lanes.main_tree(_HERE.parents[1])


class _LineSink:
    """A one-line `emit(str)` callable seen as the write() stream the kit's
    fleet_checklist.emit() prints to. The callable's own failures surface as
    the stream's, so emit() applies its fallbacks to them: a UnicodeEncodeError
    (print() to a cp1252 file under pythonw) is retried with "[ ]" for the box,
    and an OSError / ValueError / AttributeError is swallowed."""

    def __init__(self, fn):
        self._fn = fn

    def write(self, text: str) -> int:
        self._fn(text[:-1] if text.endswith("\n") else text)
        return len(text)


class LaneProgress:
    """One fire's checklist, mirrored to its log and its progress file."""

    def __init__(self, task: str, session: int, items, *, root=None,
                 note=None, emit=None):
        self.task = str(task)
        self.root = main_checkout() if root is None else Path(root)
        self.cl = fleet_checklist.Checklist(int(session), items, note=note)
        self.emit = emit if emit is not None else (lambda _s: None)
        self._total = len(self.cl.remaining())

    def _say(self, text: str):
        """Print to the fire's sink through fleet_checklist.emit() (kit v10,
        MAIN 2026-10-08 0839 step 5): never print() directly, never raise."""
        return fleet_checklist.emit(text, _LineSink(self.emit))

    @classmethod
    def for_lane(cls, index: int, session: int, items, **kw) -> "LaneProgress":
        return cls(fleet_checklist.lane_task(index), session, items, **kw)

    # ---- the file ----------------------------------------------------------
    def _pct(self) -> int:
        if not self._total:
            return 100
        left = len(self.cl.remaining())
        return int(round(100 * (self._total - left) / self._total))

    def _eta(self):
        etas = [r["eta_s"] for r in self.cl.remaining() if r.get("eta_s") is not None]
        return sum(etas) if etas else None

    def _write(self, step: str, status: str):
        try:
            return fleet_headless.write_progress(
                self.root, self.task, self._pct(), step, self._eta(), status,
                checklist=self.cl.rows())
        except (OSError, ValueError) as exc:
            self._say(f"{self.task}: progress write failed: {exc}")
            return None

    # ---- the fire ----------------------------------------------------------
    def start(self, step: str = "fire start") -> str:
        text = self.cl.start()
        self._say(text)
        self._write(step, "running")
        return text

    def set_state(self, id_: str, state, eta_s=None, step: str | None = None):
        self.cl.set_state(id_, state, eta_s)
        self._write(step or f"{id_} {state or 'pending'}", "running")

    def complete(self, id_: str, step: str | None = None):
        update = self.cl.complete(id_)
        if update:
            self._say(update)
        done = self.cl.all_done()
        self._write(step or f"{id_} done", "done" if done else "running")
        return update

    def fail(self, reason: str):
        self._say(f"{self.task}: failed - {reason}")
        self._write(f"failed: {reason}", "failed")
