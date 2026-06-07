#!/usr/bin/env python
"""DRY-RUN simulator: plays BOTH the AHK typist and the Claude executor.

Used for logic test passes (1 + 2) so the controller runs end to end with NO GUI
and NO Anthropic spend. Watches control/gemini.ready, acks like AHK (typed.flag +
deletes gemini.ready), simulates work, writes control/claude.done.

Fault injection for pass 2:
  --regressions 1  claude.done.regressions=true (controller must route FIX-first)
  --hang           never write claude.done (controller must hit deadline -> STOP)
  --delay N        seconds of fake work (default 3)
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = r"C:\Riot Commander"
CTL = Path(ROOT) / "ops" / "loop" / "control"

def head():
    return subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--regressions", type=int, default=0)
    ap.add_argument("--hang", action="store_true")
    a = ap.parse_args()
    print(f"claude_stub: watching {CTL}\\gemini.ready (hang={a.hang} regress={a.regressions})", flush=True)
    while True:
        if (CTL / "STOP").exists():
            print("stub: STOP seen, exit", flush=True); return
        if (CTL / "gemini.ready").exists():
            # act as AHK: consume the ready flag (its deletion = the typed signal)
            (CTL / "gemini.ready").unlink(missing_ok=True)
            print("stub: gemini.ready consumed (AHK sim)", flush=True)
            if a.hang:
                print("stub: HANG mode - not writing claude.done", flush=True)
                while not (CTL / "STOP").exists():
                    time.sleep(2)
                return
            time.sleep(a.delay)  # fake Claude work
            payload = {"cycle": 0, "sha": head(), "tests_pass": 1342,
                       "regressions": bool(a.regressions), "ts": time.time()}
            tmp = CTL / "claude.done.tmp"
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, CTL / "claude.done")
            print("stub: wrote claude.done", payload, flush=True)
            while (CTL / "claude.done").exists() and not (CTL / "STOP").exists():
                time.sleep(1)  # wait for controller to consume
        time.sleep(1)

if __name__ == "__main__":
    main()
