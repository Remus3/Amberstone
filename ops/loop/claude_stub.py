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
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# core/polled_json.py holds the repo's atomic-write contract - LANE 8 CYCLE 48,
# RM-250 sibling sweep. This is the DRY-RUN twin of done_sentinel.py and writes
# the same claude.done destination, so it shared that module's fixed
# "claude.done.tmp" scratch name; the two are exactly the pair a per-writer
# scratch name exists to separate. Plain import first; absolute-path bind as the
# script-context fallback.
try:
    from core.polled_json import atomic_write_bytes as _atomic_write_bytes
except ModuleNotFoundError:
    _pj_name = "rc_core_polled_json"
    if _pj_name in sys.modules:
        _atomic_write_bytes = sys.modules[_pj_name].atomic_write_bytes
    else:
        try:
            _pj_spec = importlib.util.spec_from_file_location(
                _pj_name,
                Path(__file__).resolve().parents[2] / "core" / "polled_json.py")
            _pj = importlib.util.module_from_spec(_pj_spec)
            sys.modules[_pj_name] = _pj
            _pj_spec.loader.exec_module(_pj)
        except OSError as _exc:
            sys.modules.pop(_pj_name, None)
            raise ModuleNotFoundError(
                "core/polled_json.py could not be loaded by absolute path"
            ) from _exc
        _atomic_write_bytes = _pj.atomic_write_bytes

# This module sits at <repo>/ops/loop/, so the checkout is two levels up. This
# was an absolute C: literal, which is right on exactly one host and silently
# wrong everywhere else - and it matters more here than it looks: the dry-run
# stub exists to prove the loop's plumbing without spend, so a stub that can
# only run on Legion cannot prove the plumbing anywhere it would actually be in
# doubt. See tests/test_loop_module_root_resolution.py.
ROOT = Path(__file__).resolve().parents[2]
CTL = ROOT / "ops" / "loop" / "control"
# CREATE_NO_WINDOW: 0 on non-Windows so the module still imports/tests in CI.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def head():
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30,
                              creationflags=NO_WINDOW).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""

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
            _atomic_write_bytes(CTL / "claude.done",
                                json.dumps(payload).encode("utf-8"))
            print("stub: wrote claude.done", payload, flush=True)
            while (CTL / "claude.done").exists() and not (CTL / "STOP").exists():
                time.sleep(1)  # wait for controller to consume
        time.sleep(1)

if __name__ == "__main__":
    main()
