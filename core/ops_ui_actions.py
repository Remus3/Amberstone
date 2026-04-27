"""
core/ops_ui_actions.py
Phase 1 Step 6 — Allowlisted manual deploy/rollback action runner.

Exposes exactly three manual actions:
  - preflight:     run rc_transactional_deploy.py --preflight
  - snapshot:      run rc_transactional_deploy.py --snapshot
  - rollback_last: run rc_transactional_deploy.py --rollback-last

Design rules:
  - No arbitrary shell command entry.
  - No raw PowerShell command textbox.
  - Actions run asynchronously on a daemon thread so the Tk main thread
    never blocks.
  - Results are delivered via a callback(ok: bool, summary: str).
  - Failures are caught and delivered cleanly — never crash the caller.
  - rollback_last requires explicit confirmation from the caller before
    this module runs it (confirmed= parameter must be True).

Python 3.9 compatible.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

_log = logging.getLogger("rc.ops_ui_actions")

# Project root — one level above this file (core/)
_PROJECT_DIR = Path(__file__).parent.parent
_DEPLOY_SCRIPT = _PROJECT_DIR / "ops" / "rc_transactional_deploy.py"

# Allowlisted action map: name -> CLI flag
_ALLOWED_ACTIONS: dict = {
    "preflight":     "--preflight",
    "snapshot":      "--snapshot",
    "rollback_last": "--rollback-last",
}

# Timeout for each action subprocess (seconds)
_ACTION_TIMEOUT = 60


class ActionResult:
    """Immutable result returned to the UI callback."""
    __slots__ = ("ok", "summary", "action")

    def __init__(self, action: str, ok: bool, summary: str) -> None:
        self.action  = action
        self.ok      = ok
        self.summary = summary

    def __repr__(self) -> str:
        return f"ActionResult(action={self.action!r}, ok={self.ok}, summary={self.summary!r})"


def run_action_async(
    action: str,
    callback: Callable[[ActionResult], None],
    confirmed: bool = False,
) -> None:
    """
    Run an allowlisted deploy action asynchronously.

    Parameters
    ----------
    action    : str
        One of "preflight", "snapshot", "rollback_last".
    callback  : callable(ActionResult)
        Called on the action's daemon thread when the action completes.
        The callback must marshal any Tk updates via root.after().
    confirmed : bool
        Must be True for "rollback_last".  If False, the action is
        rejected immediately without launching a subprocess.

    Thread model
    ------------
    The subprocess is launched on a new daemon thread. The callback is
    called on that same thread. Tk callers MUST use root.after(0, fn)
    inside the callback if they need to update widgets.
    """
    if action not in _ALLOWED_ACTIONS:
        result = ActionResult(action, False, f"Unknown action: {action!r}")
        try:
            callback(result)
        except Exception:
            pass
        return

    if action == "rollback_last" and not confirmed:
        result = ActionResult(action, False, "Rollback requires explicit confirmation.")
        try:
            callback(result)
        except Exception:
            pass
        return

    t = threading.Thread(
        target=_run_worker,
        args=(action, callback),
        daemon=True,
        name=f"OpsAction-{action}",
    )
    t.start()


def _run_worker(action: str, callback: Callable[[ActionResult], None]) -> None:
    """Worker thread: runs the subprocess, delivers result to callback."""
    flag = _ALLOWED_ACTIONS[action]
    cmd  = [sys.executable, str(_DEPLOY_SCRIPT), flag]
    ok      = False
    summary = ""

    try:
        if not _DEPLOY_SCRIPT.exists():
            summary = f"Deploy script not found: {_DEPLOY_SCRIPT}"
            _log.error(summary)
        else:
            proc = subprocess.run(
                cmd,
                cwd=str(_PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=_ACTION_TIMEOUT,
            )
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            ok = (proc.returncode == 0)
            if ok:
                summary = stdout[-400:] if stdout else f"{action} completed (rc=0)"
            else:
                combined = (stdout + "\n" + stderr).strip()
                summary = combined[-400:] if combined else f"{action} failed (rc={proc.returncode})"
    except subprocess.TimeoutExpired:
        summary = f"{action} timed out after {_ACTION_TIMEOUT}s"
        _log.warning(summary)
    except Exception as exc:
        summary = f"{action} error: {exc}"
        _log.error(summary)

    result = ActionResult(action, ok, summary)
    try:
        callback(result)
    except Exception as exc:
        _log.error("ops_ui_actions callback error: %s", exc)
