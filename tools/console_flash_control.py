"""The positive control for the console-flash capture. SPAWNS UNFLAGGED ON PURPOSE.

READ THIS BEFORE "FIXING" THE MISSING creationflags BELOW. Spawns 1 and 2 omit
CREATE_NO_WINDOW deliberately. This module is the only place in the tree that
does, and it is therefore deliberately absent from both SCHEDULED_SPAWNERS and
HOOK_SPAWNERS in tests/test_no_console_flash_scheduled_tools.py - adding it
there would make the guard red on a file whose whole job is to produce the
symptom the guard exists to prevent.

WHY A CONTROL IS NEEDED AT ALL. A capture that sees no console window has two
readings that look identical in the log: the machine was quiet, or the detector
could not see what was there. Only a spawn KNOWN to allocate a console
discriminates between them. So this runs, under pythonw (a parent with no
console of its own):

  1. cmd.exe /c exit      unflagged  -> must produce a console EVENT
  2. git.exe --version    unflagged  -> must produce a console EVENT
                                        (git.exe is PE subsystem 3, CONSOLE -
                                        measured on all three copies)
  3. cmd.exe /c exit      FLAGGED    -> must produce a START line and NO EVENT

then sleeps past one heartbeat so the attributor can prove the detector was
still alive after the last spawn. Step 3 is the half that makes absence
provable: a START with no EVENT says "spawned and did not show a window", which
a missing line alone never says.

IF 1 OR 2 PRODUCES NO EVENT the detector, not the machine, is the thing that
failed, and the console-flash attribution that rests on it is withdrawn.

Output is basenames and ids only, under the gitignored ops/runtime/console_flash/
(.gitignore:178). No command line is ever written - a command line names the
account home directory and neighbouring project directories on this box.

Usage:
  pythonw.exe tools/console_flash_control.py
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "ops" / "runtime" / "console_flash"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

#: Long enough that a 30 s heartbeat lands after the last spawn.
SETTLE_SECONDS = 35.0

#: (sequence, flagged, argv). Order matters: unflagged first, so a capture that
#: dies early still carries the arm that proves the detector works.
CONTROL_SPAWNS = (
    (1, False, ["cmd.exe", "/c", "exit"]),
    (2, False, ["git.exe", "--version"]),
    (3, True, ["cmd.exe", "/c", "exit"]),
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def run(out_path: Path, settle: float = SETTLE_SECONDS) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    with out_path.open("a", encoding="ascii", errors="replace", newline="\n") as fh:
        fh.write(f"CONTROL-START ts={_now()} pid={os.getpid()} out={out_path.name}\n")
        fh.flush()
        for seq, flagged, argv in CONTROL_SPAWNS:
            kwargs = {}
            if flagged:
                kwargs["creationflags"] = _NO_WINDOW
            try:
                proc = subprocess.Popen(  # noqa: S603 - fixed argv, control arm
                    argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    **kwargs)
            except OSError as exc:
                fh.write(f"CONTROL-SKIP ts={_now()} seq={seq} name={os.path.basename(argv[0])} reason={type(exc).__name__}\n")
                fh.flush()
                continue
            line = f"CONTROL ts={_now()} seq={seq} flagged={int(flagged)} name={os.path.basename(argv[0])} pid={proc.pid}"
            fh.write(line + "\n")
            fh.flush()
            lines.append(line)
            proc.wait(timeout=30)
            time.sleep(1.0)
        fh.write(f"CONTROL-END ts={_now()} spawned={len(lines)}\n")
        fh.flush()
    # Outlive the next detector heartbeat so "still alive afterwards" is in the
    # log rather than in someone's memory of having watched.
    time.sleep(settle)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="deliberate unflagged spawns - the console-flash positive control")
    parser.add_argument("--out", type=Path, default=None,
                        help="control log path (default ops/runtime/console_flash/)")
    parser.add_argument("--settle", type=float, default=SETTLE_SECONDS,
                        help="seconds to stay alive after the last spawn")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if sys.platform != "win32":
        sys.stderr.write("console_flash_control runs on Windows only\n")
        return 2
    return run(args.out or (DEFAULT_DIR / "console_flash_control.log"), args.settle)


if __name__ == "__main__":
    raise SystemExit(main())
