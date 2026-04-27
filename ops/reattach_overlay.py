"""
ops/reattach_overlay.py
Hot-reload this module to force a re-attach of the TFT overlay on the live instance.
Uses coaches.tft_coach._active_instance registered at attach_overlay() time.
"""
import sys
import logging
import time
import tkinter as tk
from pathlib import Path

_log = logging.getLogger("rc.reattach")
_dbg = Path("C:/Riot Commander/ops/runtime/reattach_debug.txt")

def _write(msg):
    try:
        existing = _dbg.read_text(encoding="utf-8") if _dbg.exists() else ""
        _dbg.write_text(existing + msg + "\n", encoding="utf-8")
    except Exception:
        pass

_write(f"=== reattach run at {time.strftime('%H:%M:%S')} ===")

try:
    coach = None
    root  = None

    # Strategy 1: module-level _active_instance in coaches.tft_coach
    tft_mod = sys.modules.get("coaches.tft_coach")
    if tft_mod and hasattr(tft_mod, "_active_instance") and tft_mod._active_instance:
        coach = tft_mod._active_instance
        _write(f"Found coach via coaches.tft_coach._active_instance: {coach}")

    # Strategy 2: coaches.tft_pbe_coach
    if coach is None:
        pbe_mod = sys.modules.get("coaches.tft_pbe_coach")
        if pbe_mod and hasattr(pbe_mod, "_active_instance") and pbe_mod._active_instance:
            coach = pbe_mod._active_instance
            _write("Found coach via coaches.tft_pbe_coach._active_instance")

    # Get root from tkinter
    try:
        root = tk._default_root
        _write(f"tk root: {root}")
    except Exception as te:
        _write(f"tk root error: {te}")

    if coach and root:
        _write("Tearing down and re-attaching overlay...")
        coach._teardown_overlay()
        root.after(100, lambda c=coach, r=root: c.attach_overlay(r))
        _write("REATTACH SCHEDULED OK")
        _log.info("reattach_overlay: attach_overlay scheduled on main thread")
    elif coach is None:
        _write("No coach instance found — will work on next game start")
        _log.warning("reattach_overlay: no active coach instance found")
    else:
        _write(f"No root (coach={coach})")
        _log.warning("reattach_overlay: found coach but no tk root")

except Exception as e:
    _write(f"ERROR: {e}")
    _log.error("reattach_overlay: %s", e)
    import traceback; traceback.print_exc()
