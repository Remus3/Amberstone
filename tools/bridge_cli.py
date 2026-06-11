# arch: consolidated bridge CLI entrypoint (Phase 6) | section=bridge | frozen=no
"""tools/bridge_cli.py - single entrypoint for the small bridge CLIs.

Phase 6 of RC_FUTUREPROOFING_PLAN consolidates seven scripts that each
re-implemented the same SSL/HTTP/state-file boilerplate:

    bridge_task.py          → `bridge_cli task ...`
    bridge_post_result.py   → `bridge_cli post-result ...`
    bridge_pull_tasks.py    → `bridge_cli pull ...`
    bridge_fetch.py         → `bridge_cli fetch`
    bridge_ping.py          → `bridge_cli ping`
    bridge_heartbeat.py     → `bridge_cli heartbeat`
    bridge_post.py          → `bridge_cli post [<source>]`

The original files are kept as ~10-line shims that call into `main([cmd, ...])`
so cron tasks (`C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/bridge_pull_tasks.py --target legion`) keep working
without scheduled-task XML edits.

Behavior is preserved exactly - flag names, defaults, exit codes, and JSON
output shapes match the originals byte-for-byte. The frozen scripts
`bridge_post_result.py` and `bridge_pull_tasks.py` are converted under
explicit operator approval (Phase 6 sign-off recorded in the plan).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Iterable, Optional

LEGION_BRIDGE = "https://legion-rc:8888/api/bridge"
VISION_HEALTH = "http://legion-rc:8889/health"
VISION_AUTH_TOKEN = "8e8f131e212b329438218eca27372dde"

DEFAULT_TIMEOUT = 4.0
HEARTBEAT_INTERVAL_S = 60.0
HEARTBEAT_BACKOFF_CAP_S = 600.0
LOOKBACK_S = 86400              # bridge_pull_tasks window
FETCH_FALLBACK_LOOKBACK_S = 1800  # first-run window for bridge_fetch
MAX_SUMMARY_LEN = 220           # bridge_post (Stop hook) cap

_LOCAL = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
PROCESSED_FILE = os.path.join(_LOCAL, "rc-bridge-tasks-processed.txt")
LAST_SEEN_FILE = os.path.join(_LOCAL, "rc-bridge-last-seen.txt")

# Self-signed mkcert dashboard cert; bearer-token auth is the actual identity.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _post_envelope(envelope: dict, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    body = json.dumps(envelope).encode()
    req = urllib.request.Request(
        LEGION_BRIDGE, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        ack = json.loads(r.read())
    _record_post(envelope.get("kind", "note"), envelope.get("target") or "")
    return ack


def _post_simple(payload: dict, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        LEGION_BRIDGE, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return json.loads(r.read())


def _fetch_messages(since: float, *, target: Optional[str] = None,
                    limit: int = 100,
                    timeout: float = DEFAULT_TIMEOUT) -> dict:
    qs = f"since={since}&limit={limit}"
    if target:
        qs += f"&target={target}"
    url = f"{LEGION_BRIDGE}?{qs}"
    with urllib.request.urlopen(url, timeout=timeout, context=_SSL_CTX) as r:
        return json.loads(r.read())


def _read_processed() -> set:
    try:
        with open(PROCESSED_FILE, encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception:
        return set()


def _mark_processed(task_id: str) -> None:
    try:
        with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
            f.write(task_id + "\n")
    except Exception:
        pass


def _read_last_seen() -> float:
    try:
        return float(open(LAST_SEEN_FILE, encoding="utf-8").read().strip())
    except Exception:
        return time.time() - FETCH_FALLBACK_LOOKBACK_S


def _write_last_seen(ts: float) -> None:
    try:
        with open(LAST_SEEN_FILE, "w", encoding="utf-8") as f:
            f.write(str(ts))
    except Exception:
        pass


def _record_post(kind: str, target: str) -> None:
    """Record a successful POST. Best-effort - never raises."""
    try:
        from core.prom_metrics import BridgeMetrics
        BridgeMetrics.posts_total.inc(kind=kind or "note",
                                      target=target or "(none)")
    except Exception:
        pass


def _record_fetch(status: str) -> None:
    try:
        from core.prom_metrics import BridgeMetrics
        BridgeMetrics.fetches_total.inc(status=status)
    except Exception:
        pass


def _record_pull(target: str, found: int) -> None:
    try:
        from core.prom_metrics import BridgeMetrics
        BridgeMetrics.pulls_total.inc(target=target,
                                      status="found" if found else "empty")
        BridgeMetrics.pull_pending.set(float(found), target=target)
    except Exception:
        pass


# Subcommand handlers -------------------------------------------------------


def cmd_task(args: argparse.Namespace) -> int:
    # Auto-pick kind: note when no prompt, task otherwise.
    kind = args.kind
    if kind is None:
        kind = "task" if args.prompt else "note"
    if kind == "task" and not args.prompt:
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
    if kind == "task":
        body["prompt"] = args.prompt
    envelope = {
        "kind":    kind,
        "id":      task_id,
        "source":  source,
        "target":  args.target,
        "summary": args.summary,
        "body":    body,
    }
    try:
        ack = _post_envelope(envelope)
    except Exception as exc:
        print(f"bridge post failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"task_id": task_id, "ts": ack.get("ts"),
                      "target": args.target, "summary": args.summary},
                     indent=2))
    return 0


def cmd_post_result(args: argparse.Namespace) -> int:
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
    if args.suggestions:
        body["suggestions"] = list(args.suggestions)
    if args.reply_to:
        target = args.reply_to
    else:
        target = "legion" if args.source == "gamepc" else "gamepc"

    if target == "peer":
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            root = os.path.dirname(here)
            if root not in sys.path:
                sys.path.insert(0, root)
            from core import bridge as _core_bridge
        except Exception as exc:
            print(f"core.bridge import failed: {exc}", file=sys.stderr)
            return 1
        ok, detail = _core_bridge.send(
            source=args.source,
            summary=args.summary,
            kind="result",
            target="peer",
            body=body,
            in_reply_to=args.task_id,
        )
        if not ok:
            print(f"bridge.send failed: {detail}", file=sys.stderr)
            return 1
        if not args.no_mark:
            _mark_processed(args.task_id)
        _record_post("result", "peer")
        print(json.dumps({"posted": True, "task_id": args.task_id,
                          "route": "core.bridge.send→peer",
                          "detail": detail}, indent=2))
        return 0

    envelope = {
        "kind":         "result",
        "in_reply_to":  args.task_id,
        "source":       args.source,
        "target":       target,
        "summary":      args.summary,
        "body":         body,
    }
    try:
        ack = _post_envelope(envelope)
    except Exception as exc:
        print(f"bridge post failed: {exc}", file=sys.stderr)
        return 1
    if not args.no_mark:
        _mark_processed(args.task_id)
    print(json.dumps({"posted": True, "task_id": args.task_id,
                      "route": "post→legion-rc", "ts": ack.get("ts")},
                     indent=2))
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    since = time.time() - LOOKBACK_S
    try:
        data = _fetch_messages(since)
    except Exception as exc:
        _record_fetch("error")
        print(json.dumps({"error": str(exc), "tasks": []}), flush=True)
        return 0
    msgs = data.get("messages") or []
    answered = {m["in_reply_to"] for m in msgs
                if m.get("kind") == "result" and m.get("in_reply_to")}
    processed = _read_processed()
    target_aliases = {"legion": {"legion", "rc"}, "gamepc": {"gamepc"}}
    accepted = target_aliases.get(args.target, {args.target})
    tasks = [m for m in msgs
             if m.get("kind") == "task"
             and m.get("target") in accepted
             and m.get("id")
             and m["id"] not in answered
             and m["id"] not in processed]
    tasks.sort(key=lambda m: m.get("ts", 0))
    out = {"now": data.get("now", time.time()),
           "target": args.target,
           "count": len(tasks),
           "tasks": tasks}
    _record_pull(args.target, len(tasks))
    _record_fetch("success")
    print(json.dumps(out, indent=2), flush=True)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    since = _read_last_seen()
    try:
        url = f"{LEGION_BRIDGE}?since={since}&limit=20"
        with urllib.request.urlopen(url, timeout=1.5, context=_SSL_CTX) as r:
            data = json.loads(r.read())
    except Exception:
        _record_fetch("error")
        return 0
    msgs = data.get("messages") or []
    _write_last_seen(data.get("now", time.time()))
    if not msgs:
        _record_fetch("empty")
        return 0
    peer_msgs = [m for m in msgs
                 if str(m.get("source", "")).lower() != "legion"]
    if not peer_msgs:
        _record_fetch("self_only")
        return 0
    lines = ["[Cross-Claude bridge - recent activity from the other machine]"]
    for m in peer_msgs:
        ts = time.strftime("%H:%M:%S", time.localtime(m.get("ts", 0)))
        src = m.get("source", "?")
        sm = m.get("summary", "")
        lines.append(f"  [{ts} · {src}] {sm}")
    print("\n".join(lines))
    _record_fetch("success")
    return 0


def cmd_ping(args: argparse.Namespace) -> int:
    host = platform.node()
    token = f"bridge-ping {host} {time.time():.3f}"
    print(f"== bridge_ping  host={host}  legion={LEGION_BRIDGE}")

    t0 = time.time()
    try:
        ts = _post_ping(token)
        post_ms = (time.time() - t0) * 1000
        print(f"  [ok]  POST     {post_ms:6.1f}ms   server_ts={ts}")
    except urllib.error.URLError as e:
        print(f"  [FAIL] POST     URLError: {e.reason}")
        print(f"         check: Legion running? HTTPS port 8888 reachable? "
              f"cert trusted? Try: curl -sk {LEGION_BRIDGE}?since=0")
        return 1
    except Exception as e:
        print(f"  [FAIL] POST     {type(e).__name__}: {e}")
        return 1

    t0 = time.time()
    try:
        msgs = _read_ping(ts - 1.0)
        read_ms = (time.time() - t0) * 1000
        match = any(m.get("summary") == token for m in msgs)
        if match:
            print(f"  [ok]  GET      {read_ms:6.1f}ms   read-back matched")
        else:
            print(f"  [WARN] GET     {read_ms:6.1f}ms   read-back missed "
                  f"({len(msgs)} msgs in window)")
            return 2
    except Exception as e:
        print(f"  [FAIL] GET      {type(e).__name__}: {e}")
        return 2

    t0 = time.time()
    try:
        h = _vision_health()
        hms = (time.time() - t0) * 1000
        uptime = h.get("uptime_s", 0)
        print(f"  [ok]  VISION   {hms:6.1f}ms   alive={h.get('alive')} "
              f"uptime={uptime/3600:.1f}h")
    except Exception as e:
        print(f"  [WARN] VISION  {type(e).__name__}: {e}")
        return 3

    print("== bridge healthy  (post+read+vision all ok)")
    return 0


def _post_ping(summary: str) -> float:
    body = json.dumps({"source": f"ping-{platform.node()}",
                       "summary": summary}).encode("utf-8")
    req = urllib.request.Request(
        LEGION_BRIDGE, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3.0, context=_SSL_CTX) as r:
        data = json.loads(r.read())
    _record_post("ping", "")
    return float(data.get("ts", 0))


def _read_ping(since: float) -> list:
    url = f"{LEGION_BRIDGE}?since={since}&limit=5"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=3.0, context=_SSL_CTX) as r:
        return json.loads(r.read()).get("messages", [])


def _vision_health() -> dict:
    req = urllib.request.Request(VISION_HEALTH,
                                 headers={"X-RC-Token": VISION_AUTH_TOKEN})
    with urllib.request.urlopen(req, timeout=3.0) as r:
        return json.loads(r.read())


def cmd_heartbeat(args: argparse.Namespace) -> int:
    log = logging.getLogger()
    if not log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s heartbeat %(message)s",
        )
    source = f"heartbeat-{platform.node().lower()}"
    log.info("starting - %s every %ds -> %s",
             source, HEARTBEAT_INTERVAL_S, LEGION_BRIDGE)
    start_ts = time.time()
    consec_fail = 0
    once = bool(getattr(args, "once", False))
    while True:
        t0 = time.time()
        try:
            uptime_h = (time.time() - start_ts) / 3600
            _post_heartbeat(source, f"alive uptime={uptime_h:.2f}h")
            if consec_fail:
                log.info("recovered after %d failures", consec_fail)
            consec_fail = 0
        except urllib.error.URLError as e:
            consec_fail += 1
            log.warning("post failed (%dx): %s", consec_fail, e.reason)
        except Exception as e:
            consec_fail += 1
            log.warning("post error (%dx): %s", consec_fail, e)
        if once:
            return 0 if consec_fail == 0 else 1
        sleep_for = HEARTBEAT_INTERVAL_S if consec_fail < 3 else min(
            HEARTBEAT_BACKOFF_CAP_S,
            HEARTBEAT_INTERVAL_S * (2 ** (consec_fail - 2)),
        )
        elapsed = time.time() - t0
        time.sleep(max(0.0, sleep_for - elapsed))


def _post_heartbeat(source: str, summary: str) -> None:
    body = json.dumps({"source": source, "summary": summary}).encode("utf-8")
    req = urllib.request.Request(
        LEGION_BRIDGE, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3.0, context=_SSL_CTX) as r:
        json.loads(r.read())
    _record_post("heartbeat", "")


def cmd_post(args: argparse.Namespace) -> int:
    """Stop-hook poster - extract last assistant text from the transcript
    referenced by the JSON payload on stdin, then POST a one-line summary."""
    source = args.source or "unknown"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    summary = _extract_summary(payload)
    if not summary:
        return 0
    try:
        _post_simple({"source": source, "summary": summary}, timeout=1.5)
        _record_post("note", "")
    except Exception:
        # Bridge unreachable - fail silently per Stop-hook contract.
        pass
    return 0


def _extract_summary(payload: dict) -> str:
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return ""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
    except Exception:
        return ""
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("role") != "assistant" and row.get("type") != "assistant":
            continue
        content = row.get("content") or row.get("message", {}).get("content", [])
        if isinstance(content, str):
            return _shorten_summary(content)
        if isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    txt = blk.get("text", "")
                    if txt.strip():
                        return _shorten_summary(txt)
    return ""


def _shorten_summary(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= MAX_SUMMARY_LEN:
        return text
    cut = text[:MAX_SUMMARY_LEN].rsplit(" ", 1)[0]
    return cut + "..."


# Argparse wiring -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridge_cli",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("task",
                        help="dispatch a task to the other Claude")
    pt.add_argument("--target", required=True, choices=["legion", "gamepc"])
    pt.add_argument("--source", default=None)
    pt.add_argument("--summary", required=True)
    pt.add_argument("--prompt", default=None)
    pt.add_argument("--body", default="{}")
    pt.add_argument("--id", default=None)
    pt.add_argument("--kind", default=None, choices=["task", "note"])

    pr = sub.add_parser("post-result",
                        help="post a kind=result envelope back through the bridge")
    pr.add_argument("task_id")
    pr.add_argument("--source", default="gamepc",
                    choices=["gamepc", "legion"])
    pr.add_argument("--summary", default="(no summary)")
    pr.add_argument("--body", default="{}")
    pr.add_argument("--from-stdin", action="store_true")
    pr.add_argument("--exit-code", type=int, default=None)
    pr.add_argument("--no-mark", action="store_true")
    pr.add_argument("--reply-to", default=None,
                    choices=["legion", "gamepc", "peer"])
    pr.add_argument("--suggestions", action="append", default=None)

    pp = sub.add_parser("pull",
                        help="fetch pending kind=task envelopes targeted at this machine")
    pp.add_argument("--target", default="gamepc",
                    choices=["gamepc", "legion"])

    sub.add_parser("fetch",
                   help="UserPromptSubmit hook - print recent peer activity")

    sub.add_parser("ping",
                   help="round-trip bridge + vision health probe")

    ph = sub.add_parser("heartbeat",
                        help="long-running alive heartbeat (default: forever)")
    ph.add_argument("--once", action="store_true",
                    help="post one heartbeat and exit (test harness)")

    pp2 = sub.add_parser("post",
                         help="Stop-hook poster - extract summary from stdin transcript and post")
    pp2.add_argument("source", nargs="?", default="unknown")

    return parser


_HANDLERS = {
    "task":        cmd_task,
    "post-result": cmd_post_result,
    "pull":        cmd_pull,
    "fetch":       cmd_fetch,
    "ping":        cmd_ping,
    "heartbeat":   cmd_heartbeat,
    "post":        cmd_post,
}


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return _HANDLERS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
