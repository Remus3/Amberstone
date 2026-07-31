#!/usr/bin/env python
r"""INTERRUPT tier - the one Mission Control act that stops a turn and kills.

NOTE and STEER (`ops/loop/steer.py`) execute nothing. That is the whole reason
they are safe on a single click, and it is why they live in a module that has
no idea what a process is. INTERRUPT is a different act, so it gets a different
contract: `docs/MISSION_CONTROL_PLAN.md` requires that the button "NAME the
agents it will kill before you confirm."

NAMING IS THE EASY HALF. A name shown at preview time is a claim about a moment
that has already passed. Between the preview and the confirm a worker can exit,
a lane can be reclaimed, a new lane can fire, and Windows can hand the dead
worker's pid to something unrelated. A confirm that simply re-enumerates and
kills whatever it finds would kill processes the operator never saw - while the
UI had truthfully named the ones it did. The list would be honest and the kill
would still be wrong.

So the preview mints a FINGERPRINT over the exact victim set, the confirm hands
it back, and this module re-probes and REFUSES on any mismatch. That is what
turns "named before the confirm" from a UI courtesy into an enforced property.
The fingerprint covers process START TIME as well as pid, because a pid alone
cannot distinguish a live worker from its recycled number.

DESCENDANTS ARE VICTIMS TOO. The lane lock records the pid of the powershell
runner (`ops/loop/run_lane.ps1`); the process doing the work is the `claude -p`
child underneath it. Naming only the lock holder would let the operator confirm
a kill that leaves the actual agent running. Victims are reaped deepest-first,
because killing a parent first re-parents its live children away and the next
enumeration no longer links them.

Every seam that touches a real process is injectable, so the tests can prove
all of the above without killing anything.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
CONTROL_DIR = _HERE / "control"
CONTROLLER_LOCK = CONTROL_DIR / "RUNNING.lock"

log = logging.getLogger("rc.loop.interrupt")

# NOT a member of steer.TIERS. INTERRUPT is an act, not guidance, and the
# guidance channel refuses to carry it rather than demoting it to a note.
TIER = "interrupt"


class InterruptUnavailable(RuntimeError):
    """The victim tree cannot be enumerated, so nothing may be named or killed."""

# The fingerprint of "nobody is running". A confirm carrying this is still
# refused (`no_victims`) - an empty interrupt is a mis-click, not a success.
EMPTY_FINGERPRINT = "0" * 16

# A cmdline is for identifying a process in the UI, not for reproducing it.
MAX_CMDLINE = 160

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _bind(modname: str, filename: str):
    """Same late-bind the rest of ops/loop uses - never a second module object."""
    try:
        return importlib.import_module(f"ops.loop.{filename[:-3]}")
    except ImportError:
        pass
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, _HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


lanes = _bind("rc_loop_lanes", "lanes.py")
steer = _bind("rc_loop_steer", "steer.py")


# --------------------------------------------------------------------------- holders
def _holders(root=None) -> list:
    """The lock holders an interrupt would target, each with its provenance.

    Only a RUNNING lock contributes. A RECLAIMABLE one names a pid that is
    already gone, and listing it would put a victim on screen that cannot be
    killed - the operator would confirm a kill of something dead and read the
    resulting no-op as a failure.
    """
    out: list = []
    try:
        lane = dict(lanes.lane_state(root=root))
    except Exception as exc:  # noqa: BLE001 - a missing lane lock is not fatal
        log.warning("interrupt: lane_state failed: %s", exc)
        lane = {}
    if lane.get("state") == lanes.RUNNING and lane.get("pid"):
        out.append({"pid": int(lane["pid"]), "kind": "lane",
                    "lane": lane.get("lane"), "run_id": lane.get("run_id")})

    rec = _read_json(CONTROLLER_LOCK)
    pid = rec.get("pid")
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        pid = None
    if pid and lanes.slots.pid_alive(pid):
        out.append({"pid": pid, "kind": "controller", "lane": None,
                    "run_id": rec.get("run_id")})
    return out


def _read_json(path: Path) -> dict:
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return rec if isinstance(rec, dict) else {}


# --------------------------------------------------------------------------- probe
def _probe(pids) -> list:
    """Every seed pid plus its descendants, breadth-first, parents before children.

    psutil rather than a shell: `wmic` is gone from modern Windows (memory
    `reference_get_wmiobject_broken`) and spawning a process to enumerate
    processes adds one more thing that can fail while the operator waits.
    """
    seeds = [int(p) for p in pids if p]
    if not seeds:
        return []
    try:
        import psutil
    except ImportError as exc:
        # RAISE, never degrade. The tempting fallback is to name the seed pids
        # alone with started=None, and it silently voids TWO of the three
        # safety properties at once: every descendant drops off the victim list
        # (so the confirm reports 1 and the real worker survives), and the
        # fingerprint collapses to pid-only, which is exactly the recycled-pid
        # case it exists to catch. Both behind one log line nobody reads. A
        # tier that cannot enumerate honestly must refuse to run.
        raise InterruptUnavailable(
            "psutil is required to enumerate the victim tree; refusing to "
            "name a partial kill list") from exc

    out: list = []
    seen: set = set()
    queue = list(seeds)
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                row = {"pid": pid, "name": proc.name(),
                       "started": proc.create_time(),
                       "cmdline": " ".join(proc.cmdline())[:MAX_CMDLINE],
                       "ppid": proc.ppid()}
                kids = [c.pid for c in proc.children()]
        except Exception:  # noqa: BLE001 - psutil raises a family of these
            continue
        out.append(row)
        queue.extend(kids)
    return out


# --------------------------------------------------------------------------- fingerprint
def fingerprint(procs) -> str:
    """A digest over the exact victim set: pid AND start time, order-independent.

    Start time is what makes a recycled pid a DIFFERENT victim. Without it the
    confirm cannot tell the previewed worker from whatever inherited its number
    after it exited.
    """
    rows = sorted((int(p["pid"]), repr(p.get("started")))
                  for p in procs if p.get("pid"))
    if not rows:
        return EMPTY_FINGERPRINT
    blob = "\n".join(f"{pid}:{started}" for pid, started in rows)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- preview
def _victims(root=None) -> list:
    """The named kill list, parents before children, each tagged with its origin."""
    holders = _holders(root=root)
    by_pid = {h["pid"]: h for h in holders}
    rows = _probe([h["pid"] for h in holders])
    out = []
    for row in rows:
        origin = by_pid.get(row["pid"])
        out.append({
            "pid": row["pid"],
            "name": row.get("name") or "?",
            "kind": origin["kind"] if origin else "child",
            "lane": origin.get("lane") if origin else None,
            "run_id": origin.get("run_id") if origin else None,
            "cmdline": row.get("cmdline") or "",
            "ppid": row.get("ppid"),
            "started": row.get("started"),
        })
    return out


def preview(root=None) -> dict:
    """Who dies, and the token that pins this exact answer. Kills nothing.

    Read-only by construction - it takes no lock, writes no file and needs no
    idempotency key, because asking twice is the same world.
    """
    vics = _victims(root=root)
    return {"ok": True, "victims": vics, "count": len(vics),
            "fingerprint": fingerprint(vics), "ts": time.time()}


# --------------------------------------------------------------------------- kill
def _taskkill(pid: int) -> bool:
    """taskkill /F, never Stop-Process - it hangs the MCP pipe (CLAUDE.md).

    /T is deliberately NOT passed: this module already enumerated the tree and
    named every member to the operator, and letting taskkill walk the tree
    itself would kill descendants that appeared after the preview - the exact
    unnamed-victim case the fingerprint exists to prevent.
    """
    try:
        out = subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                             capture_output=True, timeout=20,
                             creationflags=_NO_WINDOW)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("interrupt: taskkill %s failed: %s", pid, exc)
        return False


def _depth(victim, by_pid) -> int:
    """How far below a lock holder a victim sits. Deeper is reaped first."""
    depth, cur, guard = 0, victim, 0
    while guard < 64:
        parent = by_pid.get(cur.get("ppid"))
        if parent is None:
            return depth
        depth += 1
        cur = parent
        guard += 1
    return depth


def _record(text: str, key) -> None:
    """Append the act to the safety ledger under the INTERRUPT tier."""
    steer.record(text, tier=TIER, key=key, source="mission-control")


def execute(expected_fingerprint, *, key, root=None, killer=None) -> dict:
    """Kill the named victims, or refuse. Never kills an unnamed process.

    `expected_fingerprint` is what `preview` handed the client. It is re-probed
    here rather than trusted, so a set that moved between the preview and this
    call is a REFUSAL carrying the fresh list, not a kill of whatever is there
    now.

    `killer` is the injection seam - the default really does kill, and no test
    should.
    """
    killer = _taskkill if killer is None else killer
    vics = _victims(root=root)
    actual = fingerprint(vics)

    if not vics:
        out = {"ok": False, "refused": "no_victims", "victims": [],
               "count": 0, "fingerprint": actual, "killed": [], "failed": []}
        _safe_record("INTERRUPT refused: no_victims (nothing is running)", key)
        return out

    if str(expected_fingerprint or "") != actual:
        # The operator approved a list that no longer describes the machine.
        out = {"ok": False, "refused": "victims_changed", "victims": vics,
               "count": len(vics), "fingerprint": actual,
               "killed": [], "failed": []}
        _safe_record(
            "INTERRUPT refused: victims_changed - the process set moved "
            f"between preview and confirm (now {len(vics)}: "
            f"{_names(vics)})", key)
        return out

    by_pid = {v["pid"]: v for v in vics}
    order = sorted(vics, key=lambda v: (-_depth(v, by_pid), v["pid"]))
    killed, failed = [], []
    for victim in order:
        (killed if killer(victim["pid"]) else failed).append(victim["pid"])

    out = {"ok": not failed, "victims": vics, "count": len(vics),
           "fingerprint": actual, "killed": killed, "failed": failed}
    verb = "killed" if not failed else "PARTIAL"
    _safe_record(f"INTERRUPT {verb}: {_names(vics)} "
                 f"(killed {killed}, failed {failed})", key)
    return out


def _names(vics) -> str:
    return ", ".join(f"{v['pid']} {v['name']}"
                     + (f" [{v['lane']}]" if v.get("lane") else "")
                     for v in vics)


def _safe_record(text: str, key) -> None:
    """Ledger failures must not turn a completed kill into an exception.

    By the time this runs the processes are already gone; raising here would
    tell the caller the interrupt failed while the machine says otherwise.
    """
    try:
        _record(text, key)
    except Exception as exc:  # noqa: BLE001 - the audit trail is best-effort
        log.warning("interrupt: could not record to the steer log: %s", exc)
