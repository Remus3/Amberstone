# arch: session counter + FLEET-COMMON item 13 checklist block | section=tools | frozen=no
"""session_checklist.py - RC's session counter and the item-13 checklist block.

FLEET-KIT v7, FLEET-COMMON item 13 (operator order 2026-10-05, relayed by MAIN):
every RC session kind prints `Session <n> checklist` at start, one line per task,
`<box> /done` last; reprints only the remaining tasks after 4+ completions; and
runs /done unprompted once none remain. This module is RC's one owner of:

  * the session counter - the `SESSION: <n>` line in the tracked hand-off
    `RC-NEXT-SESSION.txt` (read at session start; /done writes n+1);
  * the session-start block - `tools/rc_facts.py` (the SessionStart hook)
    calls `session_start_block()` and prints it FIRST;
  * the headless progress write - `write_progress()` puts the remaining rows
    into an item-12 progress file as "checklist" (the inbox responder runner).

The rendering itself is the vendored kit's `ops/fleet_kit/fleet_checklist.py`.
Until a tree carries v7 (or if the file is unreadable) a byte-compatible local
renderer stands in, so the hook never loses its block. Source stays 7-bit
ASCII: the box glyph is the escape "\\u2610", never a literal.

CLI (used by tools/done.md section 10):
  python tools/session_checklist.py --current   # n, or "none"
  python tools/session_checklist.py --next      # n + 1 (n absent -> error)
  python tools/session_checklist.py --stamp N   # set/insert `SESSION: N`
  python tools/session_checklist.py --show      # the session-start block
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HANDOFF = ROOT / "RC-NEXT-SESSION.txt"
KIT_CHECKLIST = ROOT / "ops" / "fleet_kit" / "fleet_checklist.py"
KIT_HEADLESS = ROOT / "ops" / "fleet_kit" / "fleet_headless.py"
PROGRESS_REL = Path("ops") / "loop" / "control" / "progress"

BOX = chr(0x2610)  # U+2610 ballot box; ASCII source
SESSION_RE = re.compile(r"^SESSION:[ \t]*(\d+)[ \t]*$", re.MULTILINE)
_NEXT_ACTION_RE = re.compile(r"^Next action:[ \t]*(.+)$", re.MULTILINE)
TASK_MAX = 120

DIRECTIVE = (
    "FLEET item 13: print this block as your FIRST chat output, completed from the "
    "hand-off (one line per task, execution order, /done last); after 4+ completions "
    "reprint ONLY the remaining tasks (new ones marked +); when none remain run /done "
    "unprompted."
)


# ------------------------------------------------------------------ counter

def read_session(path: Path = HANDOFF) -> int | None:
    """The `SESSION: <n>` value in the hand-off, or None when absent/unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = SESSION_RE.search(text)
    return int(m.group(1)) if m else None


def stamp_session(n: int, path: Path = HANDOFF) -> None:
    """Set the hand-off's `SESSION: <n>` line, inserting it after the
    `NEXT SESSION` underline (or first) when absent. Atomic, LF-preserving."""
    n = int(n)
    if n < 1:
        raise ValueError(f"session counter must be >= 1, got {n}")
    path = Path(path)
    data = path.read_bytes().decode("utf-8")
    line = f"SESSION: {n}"
    if SESSION_RE.search(data):
        new = SESSION_RE.sub(line, data, count=1)
    else:
        lines = data.split("\n")
        at = 0
        if len(lines) >= 2 and lines[0].strip() == "NEXT SESSION" and set(lines[1].strip()) == {"-"}:
            at = 2
        lines.insert(at, line)
        new = "\n".join(lines)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(new.encode("utf-8"))
    tmp.replace(path)


def next_action(path: Path = HANDOFF) -> str | None:
    """The hand-off's `Next action:` line, trimmed to one checklist task line."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _NEXT_ACTION_RE.search(text)
    if not m:
        return None
    task = " ".join(m.group(1).split())
    if len(task) > TASK_MAX:
        task = task[: TASK_MAX - 3].rstrip() + "..."
    return task or None


# ------------------------------------------------------------------ rendering

def _load(name: str, path: Path):
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod


def kit_checklist():
    """The vendored kit's fleet_checklist module, or None before v7 lands."""
    if not KIT_CHECKLIST.is_file():
        return None
    try:
        return _load("rc_fleet_kit_fleet_checklist", KIT_CHECKLIST)
    except Exception:  # noqa: BLE001 - a broken kit file must not cost the block
        return None


def _local_render(n: int, rows: list[dict], note: str | None = None) -> str:
    """Byte-compatible stand-in for fleet_checklist.render (pending rows)."""
    out = [f"Session {int(n)} checklist"]
    for r in rows:
        tail = ""
        state = r.get("state")
        if state and state != "pending":
            tail = f" ({state})"
        out.append(f"{BOX} {r['id']}: {r['task']}{tail}")
    out.append(f"{BOX} /done")
    if note:
        out.append(" ".join(note.split()))
    return "\n".join(out)


def render_start(n: int, rows: list[dict], note: str | None = None) -> str:
    """The section-2a start block: kit Checklist when vendored, else local."""
    kit = kit_checklist()
    if kit is not None:
        try:
            return kit.Checklist(n, [kit.item(r["id"], r["task"], r.get("state"), r.get("eta_s"))
                                     for r in rows], note=note).start()
        except Exception:  # noqa: BLE001
            pass
    return _local_render(n, rows, note)


def session_start_block(path: Path = HANDOFF) -> str:
    """What the SessionStart hook prints first. Never raises.

    Seeds C1 from the hand-off's `Next action:`; the session completes the
    list from the rest of the hand-off (DIRECTIVE says so). A missing counter
    is itself the first task, so it cannot go unnoticed.
    """
    try:
        n = read_session(path)
        rows = []
        if n is None:
            rows.append({"id": "C0", "task": "Seed SESSION: <n> in RC-NEXT-SESSION.txt (counter missing)"})
            n = 0
        task = next_action(path)
        rows.append({"id": "C1", "task": task or "Work the hand-off's next action"})
        return render_start(n, rows) + "\n" + DIRECTIVE
    except Exception as exc:  # noqa: BLE001 - a hook must never fail the session start
        return f"Session checklist unavailable: {type(exc).__name__}\n" + DIRECTIVE


# ------------------------------------------------------------------ progress

def write_progress(root, task: str, pct: int, step: str, eta_s, status: str,
                   checklist: list[dict]) -> dict:
    """Item-12 progress file plus the item-13 "checklist" rows.

    Uses the vendored kit's write_progress(checklist=) when it has one (v7);
    an older kit (or none) gets the same document written here, atomically.
    """
    try:
        kit = _load("rc_fleet_kit_fleet_headless", KIT_HEADLESS) if KIT_HEADLESS.is_file() else None
    except Exception:  # noqa: BLE001
        kit = None
    if kit is not None and "checklist" in inspect.signature(kit.write_progress).parameters:
        return kit.write_progress(root, task, pct, step, eta_s, status, checklist=checklist)
    doc = {"task": task, "pct": max(0, min(100, int(pct))), "step": str(step)[:200],
           "eta_s": None if eta_s is None else max(0, int(eta_s)), "status": status,
           "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "checklist": [{"id": r["id"], "task": r["task"], "state": r.get("state"),
                          "eta_s": r.get("eta_s")} for r in checklist]}
    target = Path(root) / PROGRESS_REL / f"{task}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(doc), encoding="ascii", newline="\n")
    tmp.replace(target)
    return doc


# ------------------------------------------------------------------ CLI

def _emit(text: str) -> None:
    """Print text even when stdout's codec cannot encode U+2610 (pythonw cp1252)."""
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.flush()
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.flush()


def main(argv: list[str] | None = None, path: Path = HANDOFF) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--current" in args:
        n = read_session(path)
        _emit("none" if n is None else str(n))
        return 0
    if "--next" in args:
        n = read_session(path)
        if n is None:
            _emit("error: no SESSION line in the hand-off")
            return 1
        _emit(str(n + 1))
        return 0
    if "--stamp" in args:
        n = int(args[args.index("--stamp") + 1])
        stamp_session(n, path)
        _emit(str(read_session(path)))
        return 0
    if "--show" in args or not args:
        _emit(session_start_block(path))
        return 0
    _emit("usage: session_checklist.py [--current | --next | --stamp N | --show]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
