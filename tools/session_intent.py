#!/usr/bin/env python
r"""CLI for the S3 session-intent seam - what the done ritual actually calls.

    python tools/session_intent.py --peek
    python tools/session_intent.py --consume --prompt-file <path>
    python tools/session_intent.py --consume --prompt-file -      (stdin)

`--peek` is the safe-boundary check: it prints {"pending": <doc>|null} and
always exits 0, so it can sit at the top of a ritual without a failure mode of
its own. `--write-prompt` writes Desktop/RC-NEXT-SESSION.txt unconditionally and
is what every /done calls; `--consume` writes the same file and marks the intent
consumed, printing the result dict; it exits 1 when there was nothing to
consume or the intent was already consumed, so a script can branch on it.

Everything real lives in ops/loop/intents.py - this file is transport only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops.loop import intents  # noqa: E402 - after the sys.path bootstrap


def _read_prompt(spec: str) -> str:
    if spec == "-":
        return sys.stdin.read()
    return Path(spec).read_text(encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--peek", action="store_true",
                      help="print the pending intent (or null) and exit 0")
    mode.add_argument("--consume", action="store_true",
                      help="write the bootstrap prompt and mark it consumed")
    mode.add_argument("--write-prompt", action="store_true",
                      help="write the bootstrap prompt only; no intent needed")
    ap.add_argument("--prompt-file",
                    help="path to the bootstrap prompt, or - for stdin")
    ap.add_argument("--control-dir", default=None,
                    help="override the control dir (tests / worktrees)")
    args = ap.parse_args(argv)

    if args.peek:
        print(json.dumps({"pending": intents.pending(root=args.control_dir)},
                         indent=2))
        return 0

    if not args.prompt_file:
        print(json.dumps({"ok": False, "reason": "missing_prompt_file"}))
        return 2
    try:
        prompt = _read_prompt(args.prompt_file)
    except OSError as exc:
        print(json.dumps({"ok": False, "reason": "unreadable_prompt_file",
                          "error": str(exc)}))
        return 2
    try:
        if args.write_prompt:
            # Unconditional: every /done hands the next session a running start.
            # Does NOT consume an intent - a queued one stays pending for the
            # --consume call in section 10b.
            result = intents.write_prompt(prompt=prompt)
        else:
            result = intents.consume(prompt=prompt, root=args.control_dir)
    except ValueError as exc:
        print(json.dumps({"ok": False, "reason": "empty_prompt",
                          "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
