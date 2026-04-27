"""bridge_post_result.py — post a task result back through the bridge.

Used by the receiving Claude (under `/loop`) after it has executed a task
returned by `bridge_pull_tasks.py`. Posts a kind=result envelope with
`in_reply_to` matching the original task id, then appends the task id
to the local processed-file so subsequent polls don't re-emit it.

Usage:
    py tools/bridge_post_result.py <task_id> [--source gamepc|legion] \\
        [--summary "<one-line>"] [--body '<json>'] [--from-stdin]

Examples:
    # quick result via summary only
    py tools/bridge_post_result.py task-abc123 \\
        --source gamepc \\
        --summary "Cert installed; thumbprint 7A:BC:..."

    # capture a command's output via stdin and ship it as the body
    .\\some-thing.ps1 | py tools/bridge_post_result.py task-abc123 \\
        --source gamepc --summary "ran some-thing.ps1" --from-stdin

The summary is the human-readable headline that shows in the bridge log
(and gets injected by the originator's UserPromptSubmit hook). The body
carries any structured payload (stdout, stderr, exit_code, file paths)
the originator's Claude wants to inspect.
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.request

LEGION_BRIDGE = "https://192.168.8.230:8888/api/bridge"
TIMEOUT = 4.0

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_local = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
PROCESSED_FILE = os.path.join(_local, "rc-bridge-tasks-processed.txt")


def mark_processed(task_id: str) -> None:
    try:
        with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
            f.write(task_id + "\n")
    except Exception:
        pass


def post(envelope: dict) -> dict:
    body = json.dumps(envelope).encode()
    req = urllib.request.Request(
        LEGION_BRIDGE, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL_CTX) as r:
        return json.loads(r.read())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task_id", help="id of the task being answered")
    p.add_argument("--source", default="gamepc",
                   choices=["gamepc", "legion"],
                   help="who's posting (default: gamepc)")
    p.add_argument("--summary", default="(no summary)",
                   help="one-line headline for the bridge log")
    p.add_argument("--body", default="{}",
                   help="optional JSON merged into the result body")
    p.add_argument("--from-stdin", action="store_true",
                   help="read stdin and add it to body.stdout")
    p.add_argument("--exit-code", type=int, default=None,
                   help="optional exit code of the action")
    p.add_argument("--no-mark", action="store_true",
                   help="don't append task id to processed file")
    args = p.parse_args()
    try:
        body_extra = json.loads(args.body)
    except Exception as exc:
        print(f"bad --body JSON: {exc}", file=sys.stderr)
        return 2
    body = {"completed": time.time(), **body_extra}
    if args.from_stdin:
        body["stdout"] = sys.stdin.read()
    if args.exit_code is not None:
        body["exit_code"] = args.exit_code
    target = "legion" if args.source == "gamepc" else "gamepc"
    envelope = {
        "kind":         "result",
        "in_reply_to":  args.task_id,
        "source":       args.source,
        "target":       target,
        "summary":      args.summary,
        "body":         body,
    }
    try:
        ack = post(envelope)
    except Exception as exc:
        print(f"bridge post failed: {exc}", file=sys.stderr)
        return 1
    if not args.no_mark:
        mark_processed(args.task_id)
    print(json.dumps({"posted": True, "task_id": args.task_id,
                      "ts": ack.get("ts")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
