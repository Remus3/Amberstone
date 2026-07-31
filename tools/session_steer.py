#!/usr/bin/env python
r"""session_steer - read the Mission Control steer channel from a ritual or a lane.

Sibling of `tools/session_intent.py` (S3). Same shape, same reasons:

  --peek   ALWAYS exits 0 and never writes, so it can sit at the top of a
           ritual or a lane loop without ever being the thing that fails it.
  --drain  returns the pending steers AND advances the cursor. Exits 1 when
           there was nothing to take, so a caller can branch on it.

A steer is GUIDANCE, not a command. The consumer decides what to do with the
text; nothing here executes anything. That distinction is the whole safety
story of this channel - a queued steer can never kill a turn or an agent.

Usage:
    python tools/session_steer.py --peek
    python tools/session_steer.py --peek --tier note
    python tools/session_steer.py --drain
    python tools/session_steer.py --drain --format text
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_steer():
    """Bind ops/loop/steer.py, preferring the package name so the module object
    is shared with anything that imported it that way - two copies would mean
    two cursors."""
    try:
        import importlib
        return importlib.import_module("ops.loop.steer")
    except ImportError:
        pass
    path = ROOT / "ops" / "loop" / "steer.py"
    spec = importlib.util.spec_from_file_location("rc_loop_steer", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rc_loop_steer"] = mod
    spec.loader.exec_module(mod)
    return mod


def _render(items, fmt: str) -> str:
    if fmt == "text":
        if not items:
            return "(no steers pending)"
        return "\n".join(
            f"[{r.get('tier', '?').upper()} #{r.get('id')}] {r.get('text', '')}"
            for r in items)
    return json.dumps(items, indent=2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="read the steer channel")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--peek", action="store_true",
                      help="list pending steers; never writes; always exits 0")
    mode.add_argument("--drain", action="store_true",
                      help="list pending steers AND advance the cursor")
    ap.add_argument("--tier", choices=("note", "steer"), default=None,
                    help="peek only: restrict to one tier")
    ap.add_argument("--format", choices=("json", "text"), default="json")
    args = ap.parse_args(argv)

    try:
        steer = _load_steer()
    except Exception as exc:  # noqa: BLE001 - a missing channel is not a failure
        if args.peek:
            print(json.dumps({"pending": [], "error": str(exc)}, indent=2))
            return 0
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    if args.peek:
        items = steer.pending(tier=args.tier)
        if args.format == "text":
            print(_render(items, "text"))
        else:
            print(json.dumps({"pending": items, "summary": steer.summary()},
                             indent=2))
        return 0

    items = steer.drain()
    print(_render(items, args.format))
    # Exit 1 on an empty drain so a ritual can branch without parsing output.
    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
