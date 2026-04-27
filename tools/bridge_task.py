"""bridge_task.py — dispatch a task to the *other* Claude via the bridge.

Used by Legion's Claude (or Game-PC's) to send a unit of work for the other
side to execute. The receiving Claude polls the bridge with `bridge_pull_tasks`
under `/loop`, executes via its own tools, and posts back with
`bridge_post_result.py <task_id> "<result_text>"`.

Usage:
    py tools/bridge_task.py --target gamepc \\
        --summary "Install RC root cert" \\
        --prompt "Run elevated PS: Import-Certificate ..."

    py tools/bridge_task.py --target legion \\
        --summary "Need vision frame for monitor 0" \\
        --prompt "Capture the current League frame and report any anomalies"

Optional fields on `--body` are merged in as JSON, e.g.
    --body '{"timeout_s": 90, "expect": "thumbprint regex match"}'

Prints the task envelope (incl. generated id) on stdout so the caller
can quote it back when polling for the matching result.
"""
import argparse
import json
import ssl
import sys
import time
import urllib.request
import uuid

LEGION_BRIDGE = "https://192.168.8.230:8888/api/bridge"
TIMEOUT = 4.0

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


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
    p.add_argument("--target", required=True, choices=["legion", "gamepc"],
                   help="who should pick up this task")
    p.add_argument("--source", default=None,
                   help="who's posting (default: opposite of target)")
    p.add_argument("--summary", required=True,
                   help="one-line description shown in the bridge log")
    p.add_argument("--prompt", default=None,
                   help="the instruction the receiving Claude executes "
                        "(required for kind=task, ignored for kind=note)")
    p.add_argument("--body", default="{}",
                   help="optional JSON merged into the task body (e.g. timeout_s)")
    p.add_argument("--id", default=None,
                   help="task id (auto-generated if omitted)")
    p.add_argument("--kind", default=None, choices=["task", "note"],
                   help="task = unit of work for the other Claude; "
                        "note = log-only, no execution expected. "
                        "Defaults to 'task' if --prompt given, else 'note'.")
    args = p.parse_args()
    # Auto-pick kind: if no --prompt, treat as a log-only note. Lets the
    # cycle-summary callers omit --kind without a CLI failure.
    if args.kind is None:
        args.kind = "task" if args.prompt else "note"
    if args.kind == "task" and not args.prompt:
        print("--prompt is required when --kind=task", file=sys.stderr)
        return 2
    try:
        extra = json.loads(args.body)
    except Exception as exc:
        print(f"bad --body JSON: {exc}", file=sys.stderr)
        return 2
    source = args.source or ("legion" if args.target == "gamepc" else "gamepc")
    task_id = args.id or f"task-{uuid.uuid4().hex[:12]}"
    body = {"issued": time.time(), **extra}
    if args.kind == "task":
        body["prompt"] = args.prompt
    envelope = {
        "kind":    args.kind,
        "id":      task_id,
        "source":  source,
        "target":  args.target,
        "summary": args.summary,
        "body":    body,
    }
    try:
        ack = post(envelope)
    except Exception as exc:
        print(f"bridge post failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"task_id": task_id, "ts": ack.get("ts"),
                      "target": args.target, "summary": args.summary},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
