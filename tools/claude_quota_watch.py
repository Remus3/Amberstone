"""claude_quota_watch.py - weekly-quota handoff watcher (personal tooling).

Reads teamclaude's account-wide weekly usage (unified7d, via /api/oauth/usage -
NOT proxy traffic, so it sees the MSIX GUI usage even though the GUI bypasses
the proxy). When primary account A crosses the threshold, fires ONE Windows
toast telling the operator to switch the GUI login to account B, and records
the weekly-reset stamp so it does not re-toast for the same window.

Run by scheduled task RC-ClaudeQuotaWatch (see docs/OPERATIONS.md).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import operator_notify  # noqa: E402 - needs the repo root on sys.path

# Account identities are OPERATOR data, not repo data: they differ per install
# and one of them is a personal address, so they are read from the environment
# rather than baked in. Unset -> the watcher no-ops instead of toasting about
# somebody else's account.
ACCT_A = os.environ.get("RC_CLAUDE_ACCT_A", "")   # primary (Max)
ACCT_B = os.environ.get("RC_CLAUDE_ACCT_B", "")   # failover
THRESHOLD = 0.90                        # weekly fraction that triggers handoff
# Resolve the teamclaude shim under THIS account's home, never a hardcoded one:
# a command naming another account's home silently does not run, and a watcher
# that does not run reports nothing.
TC = os.environ.get("RC_TEAMCLAUDE_CMD") or str(
    Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    / "npm"
    / "teamclaude.cmd"
)
STATE = Path.home() / ".config" / "claude_quota_watch_state.json"

# MEASURED 2026-08-01: this script is the console flash on Legion.
#
# It runs from RC-ClaudeQuotaWatch under pythonw.exe, which has NO console of
# its own, on an INTERACTIVE logon type (so it has a desktop), repeating every
# two hours. Spawning a console-subsystem child from a parent with no console
# makes Windows allocate a NEW console window for the child - and `TC` is a
# .cmd shim, so the child is cmd.exe. `-WindowStyle Hidden` does NOT prevent
# this: it governs the PowerShell host window, not console allocation.
#
# Proven rather than reasoned: spawning this exact command from pythonw twice,
# once unflagged and once with the flag, while polling EnumWindows at 8ms -
# unflagged produced a visible ConsoleWindowClass window, flagged produced
# none. A 250ms poll MISSES it, which is why the first watch came back clean.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main() -> None:
    # Without a configured primary there is nothing to watch, and an empty
    # ACCT_A would make the `startswith` below match the FIRST account listed.
    if not ACCT_A:
        return
    try:
        out = subprocess.run([TC, "status", "--json"], capture_output=True,
                             text=True, timeout=30,
                             creationflags=CREATE_NO_WINDOW).stdout
        data = json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return

    acct = next((a for a in data.get("accounts", [])
                 if a.get("name") == ACCT_A or a.get("orgName", "").startswith(ACCT_A)), None)
    if not acct:
        return
    q = acct.get("quota") or {}
    wk = q.get("unified7d")
    reset = q.get("unified7dReset")
    if wk is None:
        return

    state = _load_state()
    if wk >= THRESHOLD and state.get("alerted_reset") != reset:
        pct = round(wk * 100)
        # Y-02: escaped toast, jsonl floor if it fails. The Windows Terminal
        # AppId is the one this watcher always toasted under; kept as-is.
        operator_notify.notify(
            "Claude weekly quota HIGH",
            f"Account A ({ACCT_A}) at {pct}% weekly. Switch the Claude desktop "
            f"login to Account B ({ACCT_B}).",
            priority="high", tags=("claude-quota",),
            app_id=operator_notify.WINDOWS_TERMINAL_APP_ID,
        )
        state["alerted_reset"] = reset
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state), encoding="utf-8")


if __name__ == "__main__":
    main()
