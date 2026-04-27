"""bridge_pull_tasks.py — fetch pending tasks targeted at *this* machine.

Run by the local Claude under `/loop` (or manually). Outputs JSON with a
`tasks` array of task envelopes that haven't been responded to yet.

Argument:
    --target gamepc    when this machine is Game-PC (default)
    --target legion    when this machine is Legion

State file (per machine):
    %LOCALAPPDATA%\\rc-bridge-tasks-processed.txt   — task ids already done

Behaviour:
    1. GET /api/bridge?since=<24h-ago> — fetches recent activity
    2. Filters to kind=task with target=<this-machine>
    3. Drops tasks whose id appears in the processed file OR for which a
       kind=result with in_reply_to=<that id> already exists in the log
    4. Prints the remaining as JSON for the caller (Claude) to read

Designed to be safe to run repeatedly — only emits *new, unhandled* tasks.

Output schema:
    {"now": <server time>, "tasks": [<envelope>, ...]}
    each envelope: {ts, source, target, kind:"task", id, summary, body}
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
LOOKBACK_S = 86400   # only consider tasks issued within last 24 h

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_local = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
PROCESSED_FILE = os.path.join(_local, "rc-bridge-tasks-processed.txt")


def read_processed() -> set:
    try:
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def fetch(since: float, target: str) -> dict:
    url = f"{LEGION_BRIDGE}?since={since}&limit=100&target={target}"
    with urllib.request.urlopen(url, timeout=TIMEOUT, context=_SSL_CTX) as r:
        return json.loads(r.read())


def fetch_all(since: float) -> dict:
    """Fetch ALL kinds (need results too, to know what's already answered)."""
    url = f"{LEGION_BRIDGE}?since={since}&limit=100"
    with urllib.request.urlopen(url, timeout=TIMEOUT, context=_SSL_CTX) as r:
        return json.loads(r.read())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="gamepc",
                   choices=["gamepc", "legion"],
                   help="this machine's bridge label (default: gamepc)")
    args = p.parse_args()

    since = time.time() - LOOKBACK_S
    try:
        data = fetch_all(since)
    except Exception as exc:
        print(json.dumps({"error": str(exc), "tasks": []}), flush=True)
        return 0
    msgs = data.get("messages") or []
    # Tasks for me + already-answered task ids
    answered: set = set()
    for m in msgs:
        if m.get("kind") == "result" and m.get("in_reply_to"):
            answered.add(m["in_reply_to"])
    processed = read_processed()
    tasks = [m for m in msgs
             if m.get("kind") == "task"
             and m.get("target") == args.target
             and m.get("id")
             and m["id"] not in answered
             and m["id"] not in processed]
    # Sort oldest-first so the loop processes them in dispatch order
    tasks.sort(key=lambda m: m.get("ts", 0))
    out = {"now": data.get("now", time.time()),
           "target": args.target,
           "count": len(tasks),
           "tasks": tasks}
    print(json.dumps(out, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
