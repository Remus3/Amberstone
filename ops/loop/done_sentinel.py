#!/usr/bin/env python
r"""Final /headless-upgrade step: write control/claude.done atomically.

Claude runs this as the LAST action of every loop cycle (the directive's FINAL STEP):
    "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" ops/loop/done_sentinel.py --tests <pass_count> --regressions <0|1>
cycle is read from control/cycle.txt; sha is the live git HEAD.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = r"C:\Riot Commander"
CTL = Path(ROOT) / "ops" / "loop" / "control"
# CREATE_NO_WINDOW: 0 on non-Windows so the module still imports/tests in CI.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def head():
    # Bound the git read: this is Claude's FINAL cycle action, so a wedged git
    # would hang the executor turn and starve the controller of claude.done.
    # Degrade to "" - the controller falls back to its own head() read.
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30,
                              creationflags=NO_WINDOW).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", default="?")
    ap.add_argument("--regressions", type=int, default=0)
    a = ap.parse_args()
    try:
        cycle = int((CTL / "cycle.txt").read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001
        cycle = 0
    payload = {"cycle": cycle, "sha": head(), "tests_pass": a.tests,
               "regressions": bool(a.regressions), "ts": time.time()}
    tmp = CTL / "claude.done.tmp"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, CTL / "claude.done")
    print("WROTE claude.done", payload)

if __name__ == "__main__":
    main()
