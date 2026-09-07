#!/usr/bin/env python
r"""Final /headless-upgrade step: write control/claude.done atomically.

Claude runs this as the LAST action of every loop cycle (the directive's FINAL STEP):
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" ops/loop/done_sentinel.py --tests <pass_count> --regressions <0|1>
cycle is read from control/cycle.txt; sha is the live git HEAD.
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
# RM-250 sibling sweep. Plain import first; absolute-path bind as the fallback
# for the script context (this module runs under `if __name__ == "__main__"`,
# where sys.path[0] is ops/loop and the repo root is on no path entry).
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
# wrong everywhere else - the sibling controller shipped the same habit and it
# cost a platform-split nightly-CI failure before anyone noticed the config was
# never being read. See tests/test_loop_module_root_resolution.py.
ROOT = Path(__file__).resolve().parents[2]
CTL = ROOT / "ops" / "loop" / "control"
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
    # LANE 8 CYCLE 48 (RM-250 sibling sweep). claude.done is polled by the
    # controller, so a bare os.replace could lose this write to a WinError 5.
    # The scratch name was also the FIXED literal "claude.done.tmp" - shared
    # with ops/loop/claude_stub.py, which writes the same destination, so the
    # two could interleave. core/polled_json gives a per-writer scratch name,
    # the bounded ~275 ms retry, and cleanup on every failure path.
    _atomic_write_bytes(CTL / "claude.done",
                        json.dumps(payload).encode("utf-8"))
    print("WROTE claude.done", payload)

if __name__ == "__main__":
    main()
