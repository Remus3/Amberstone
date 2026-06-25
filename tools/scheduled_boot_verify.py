"""scheduled_boot_verify.py - runs from Windows Task Scheduler on Legion.

Fires once at the scheduled time and records a durable cold-boot
verification record (hostname + LastBootUpTime) to
%LOCALAPPDATA%\\rc-boot-verify\\<ts>.jsonl. Exits 0 when the boot facts
were captured, 1 otherwise.

The RC<->Peer cross-Claude bridge was decommissioned 2026-06-24; the
former behavior (dispatch a no-op task to /api/bridge and poll for a
kind:result reply) is removed. The boot-verification signal now lives
purely in the local JSONL record - nothing is posted off-box.

Pairs with a one-time scheduled remote agent (trig_01Xk1YCJbrPBPRXA3LmKTWfk)
that opens a tracking GitHub issue at the same moment - together they
cover the cold-boot persistence test that warm verification missed.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

_OUT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "rc-boot-verify"
_OUT_DIR.mkdir(parents=True, exist_ok=True)


def _last_boot_iso() -> str | None:
    """Best-effort LastBootUpTime as an ISO string via CIM. Returns None
    when the query fails (non-Windows CI, locked-down host, etc.).
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime."
             "ToString('o')"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    val = (out.stdout or "").strip()
    return val or None


def main() -> int:
    started = time.time()
    record = {
        "started": started,
        "hostname": platform.node(),
        "last_boot": _last_boot_iso(),
        "outcome": None,
    }
    if record["last_boot"]:
        record["outcome"] = "boot_verified"
        rc = 0
    else:
        record["outcome"] = "last_boot_unavailable"
        rc = 1
    _write(record, started)
    return rc


def _write(record: dict, ts: float) -> None:
    fname = _OUT_DIR / f"{int(ts)}.jsonl"
    try:
        fname.write_text(json.dumps(record, default=str) + "\n", encoding="utf-8")
    except OSError as exc:
        # Best-effort. Nothing else listens to stderr from a scheduled task.
        sys.stderr.write(f"could not write {fname}: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
