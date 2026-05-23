"""verify_bridge_roundtrip.py - one-shot verifier for the Legion /loop pattern.

Issued task target=legion source=gamepc → expects Legion's /loop /process-
bridge-tasks (running in any open Claude Code session on Legion) to pick it
up, execute the prompt, and post a kind=result via bridge_post_result.py
--reply-to gamepc.
Result lands on Legion's local /api/bridge log, observable from this script.

Source=gamepc is chosen deliberately: --reply-to gamepc routes through the
local Legion bridge POST (not Peer), so the verdict is observable from
Legion alone - no Peer dependency.

Verdict is written to ops/runtime/bridge_roundtrip_verdict.json AND posted
as a kind=note to the Legion bridge so the operator's next prompt surfaces
it via the UserPromptSubmit hook.

Triggered by Windows scheduled task RC-VerifyBridgeRoundtrip-Once.
"""
import json
import ssl
import sys
import time
import urllib.request
import uuid
from pathlib import Path

LEGION_BRIDGE = "https://legion-rc:8888/api/bridge"
TIMEOUT = 4.0
WAIT_S = 120  # generous buffer over /loop's 1m tick + Claude exec time
POLL_INTERVAL_S = 5

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

ROOT = Path(__file__).resolve().parent.parent
VERDICT_PATH = ROOT / "ops" / "runtime" / "bridge_roundtrip_verdict.json"


def post(envelope: dict) -> dict:
    body = json.dumps(envelope).encode()
    req = urllib.request.Request(
        LEGION_BRIDGE, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL_CTX) as r:
        return json.loads(r.read())


def fetch_since(since: float) -> list:
    url = f"{LEGION_BRIDGE}?since={since}&limit=200"
    with urllib.request.urlopen(url, timeout=TIMEOUT, context=_SSL_CTX) as r:
        return json.loads(r.read()).get("messages") or []


def write_verdict(payload: dict) -> None:
    VERDICT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = VERDICT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for delay in (0, 0.025, 0.05, 0.2):
        if delay:
            time.sleep(delay)
        try:
            tmp.replace(VERDICT_PATH)
            return
        except PermissionError:
            continue


def surface_to_bridge(summary: str, body: dict) -> None:
    """Post a kind=note to Legion's bridge so the operator's next prompt
    surfaces the verdict via the UserPromptSubmit hook."""
    try:
        post({
            "kind":    "note",
            "source":  "rc-verifier",
            "target":  "legion",
            "summary": summary,
            "body":    body,
        })
    except Exception as exc:
        # non-fatal - verdict file is the source of truth
        print(f"surface_to_bridge failed: {exc}", file=sys.stderr)


def main() -> int:
    issued_at = time.time()
    task_id = f"task-verify-{uuid.uuid4().hex[:10]}"

    envelope = {
        "kind":    "task",
        "id":      task_id,
        "source":  "gamepc",        # mimic gamepc→legion path; --reply-to gamepc keeps result local
        "target":  "legion",
        "summary": "RC /loop verify - echo hostname/pid/ts (auto-issued by RC-VerifyBridgeRoundtrip-Once)",
        "body":    {
            "issued":  issued_at,
            "prompt": ("Reply with hostname, current pid, and current epoch ts. "
                       "Use bridge_post_result.py --source legion --reply-to gamepc "
                       "to post the result. This is a low-stakes verifier task - "
                       "no frozen-file writes, no shell command execution required "
                       "beyond reading hostname/pid/ts."),
        },
    }

    try:
        post(envelope)
    except Exception as exc:
        verdict = {
            "verdict":  "ERROR_ISSUE",
            "task_id":  task_id,
            "issued":   issued_at,
            "error":    f"failed to post task: {exc}",
        }
        write_verdict(verdict)
        surface_to_bridge(f"Bridge roundtrip verifier ERROR - could not post task: {exc}", verdict)
        return 1

    deadline = issued_at + WAIT_S
    last_messages: list = []
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_S)
        try:
            last_messages = fetch_since(issued_at - 30)
        except Exception:
            continue
        for m in last_messages:
            if m.get("kind") == "result" and m.get("in_reply_to") == task_id:
                latency = time.time() - issued_at
                verdict = {
                    "verdict":  "PASS",
                    "task_id":  task_id,
                    "issued":   issued_at,
                    "answered": m.get("ts"),
                    "latency_s": round(latency, 2),
                    "result_summary": m.get("summary"),
                    "result_body":    m.get("body"),
                    "result_source":  m.get("source"),
                }
                write_verdict(verdict)
                surface_to_bridge(
                    f"Bridge roundtrip verifier PASS - Legion /loop picked up "
                    f"task {task_id[:18]}... and replied in {latency:.1f}s",
                    verdict,
                )
                return 0

    # Timed out - capture last 5 inbox entries for diagnostic
    tail = []
    for m in last_messages[-5:]:
        tail.append({
            "ts": m.get("ts"), "source": m.get("source"),
            "kind": m.get("kind"), "summary": (m.get("summary") or "")[:120],
            "id": m.get("id"), "in_reply_to": m.get("in_reply_to"),
        })
    verdict = {
        "verdict":   "FAIL_TIMEOUT",
        "task_id":   task_id,
        "issued":    issued_at,
        "waited_s":  WAIT_S,
        "diagnostic": "no kind=result with matching in_reply_to within wait window. "
                      "Likely cause: Legion Claude session not relaunched, /loop not active, "
                      "skill not registered, or bridge_post_result.py raised in skill execution.",
        "inbox_tail": tail,
    }
    write_verdict(verdict)
    surface_to_bridge(
        f"Bridge roundtrip verifier FAIL_TIMEOUT - no result for {task_id[:18]}... "
        f"after {WAIT_S}s. Check ops/runtime/bridge_roundtrip_verdict.json",
        verdict,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
