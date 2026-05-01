"""scheduled_boot_verify.py — runs from Windows Task Scheduler on Legion.

Fires once at the scheduled time, dispatches a no-op bridge task to
Game-PC, and watches /api/bridge for an in_reply_to kind:result for up
to 120 s. Exits 0 on success, 1 on no-result, 2 on dispatch failure.

Outputs a single JSON line to %LOCALAPPDATA%\\rc-boot-verify\\<ts>.jsonl
so the result is durable even though the task itself is fire-and-forget.

Pairs with a one-time scheduled remote agent (trig_01Xk1YCJbrPBPRXA3LmKTWfk)
that opens a tracking GitHub issue at the same moment — together they
cover the cold-boot persistence test that warm verification missed.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.request
import uuid
from pathlib import Path

LEGION_BRIDGE = "https://192.168.8.230:8888/api/bridge"
WAIT_S = 120
TASK_TIMEOUT = 4.0

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_OUT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "rc-boot-verify"
_OUT_DIR.mkdir(parents=True, exist_ok=True)


def _post(envelope: dict) -> dict:
    body = json.dumps(envelope).encode()
    req = urllib.request.Request(
        LEGION_BRIDGE, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TASK_TIMEOUT, context=_SSL_CTX) as r:
        return json.loads(r.read())


def _fetch(since: float) -> list:
    url = f"{LEGION_BRIDGE}?since={since}&limit=50"
    with urllib.request.urlopen(url, timeout=TASK_TIMEOUT, context=_SSL_CTX) as r:
        return (json.loads(r.read()).get("messages") or [])


def main() -> int:
    started = time.time()
    task_id = f"task-bootverify-{uuid.uuid4().hex[:8]}"
    envelope = {
        "kind":   "task",
        "id":     task_id,
        "source": "legion-scheduled",
        "target": "gamepc",
        "summary": "post-boot auto-flow check (Task Scheduler)",
        "body": {
            "issued": started,
            "prompt": (
                "Reply via py C:/RC-Agent/bridge_post_result.py with hostname + "
                "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime as ISO. "
                "JSON body must be valid (ConvertTo-Json -Compress). No chat output."
            ),
        },
    }
    out = {"task_id": task_id, "started": started, "outcome": None}
    try:
        ack = _post(envelope)
        out["dispatched_ts"] = ack.get("ts")
    except Exception as exc:
        out["outcome"] = "dispatch_failed"
        out["error"] = str(exc)
        _write(out, started)
        return 2

    deadline = started + WAIT_S
    while time.time() < deadline:
        try:
            items = _fetch(started - 5)
        except Exception:
            time.sleep(3)
            continue
        for m in items:
            if m.get("in_reply_to") == task_id and m.get("kind") == "result":
                out["outcome"] = "result_received"
                out["latency_s"] = round(m.get("ts", 0) - started, 1)
                out["result_summary"] = m.get("summary")
                out["result_body"] = m.get("body")
                _write(out, started)
                return 0
        time.sleep(5)

    out["outcome"] = "no_result_within_wait"
    out["wait_s"] = WAIT_S
    _write(out, started)
    return 1


def _write(record: dict, ts: float) -> None:
    fname = _OUT_DIR / f"{int(ts)}.jsonl"
    try:
        fname.write_text(json.dumps(record, default=str) + "\n", encoding="utf-8")
    except OSError as exc:
        # Best-effort. Nothing else listens to stderr from a scheduled task.
        sys.stderr.write(f"could not write {fname}: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
