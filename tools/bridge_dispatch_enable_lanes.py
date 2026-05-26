# arch: dispatch bridge ops_request to enable auto-action lanes on peer | section=bridge | frozen=no
"""tools/bridge_dispatch_enable_lanes.py - item 199 Slice A helper.

Builds an ops_request bridge task envelope that asks a peer (gamepc or peer)
to re-run tools/bridge_watcher_install.ps1 with -EnableLanes set, so the
peer's RC-BridgeWatcher-<Node> scheduled task XML carries the
--enable-auto-action-lanes flag.

Background:
    - docs/AUTO_ACTION_LANES_GATE_PROBE.md ships the operator recipe; this
      script automates step (1)+(2) by enqueuing them through the bridge
      instead of requiring the operator to run powershell on each peer.
    - tools/bridge_watcher_install.ps1 -EnableLanes was landed item 189
      Slice A under explicit frozen-file grant (commit 93695ca). The script
      below depends on that surface being present on the peer's copy.
    - Phase 3 enablement gate (N>=50 samples, >=95% success) is NOT cleared.
      This script is PREP only; do NOT invoke until the gate clears unless
      you pass --force.

The envelope shape is a kind=task / body.verb=reinstall_bridge_watcher_with_lanes
ops_request that the peer's process-bridge-tasks skill or its
bridge_watcher_actions classifier can pick up + execute.

Usage:
    py tools/bridge_dispatch_enable_lanes.py --target gamepc --lanes read
    py tools/bridge_dispatch_enable_lanes.py --target peer --lanes read,ops
    py tools/bridge_dispatch_enable_lanes.py --target gamepc --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

INSTALL_PS1_URL = "https://legion-rc:8888/agent/bridge_watcher_install.ps1"
INSTALL_PS1_PATH = Path(__file__).resolve().parent / "bridge_watcher_install.ps1"
DASHBOARD_HEALTH_URL = "https://127.0.0.1:8888/api/health/all"
LEGION_BRIDGE = "https://legion-rc:8888/api/bridge"
DEFAULT_TIMEOUT = 4.0

VALID_LANE_STRINGS = {"", "read", "ops", "read,ops", "ops,read"}
VALID_TARGETS = ("gamepc", "peer")
VERB = "reinstall_bridge_watcher_with_lanes"

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_log = logging.getLogger("bridge_dispatch_enable_lanes")


def compute_install_ps1_checksum(path: Path = INSTALL_PS1_PATH) -> str:
    """Return sha256 hex digest of the local install.ps1.

    The peer pulls install.ps1 from Legion's /agent/ HTTP serve; the digest
    lets the peer verify it pulled the same bytes we authored against.
    """
    if not path.is_file():
        raise FileNotFoundError(f"install.ps1 not at {path}")
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def build_envelope(target: str, lanes: str, *, checksum: str,
                   source: str = "legion",
                   task_id: Optional[str] = None,
                   issued_ts: Optional[float] = None) -> dict:
    """Build a kind=task envelope matching tools/bridge_cli.py cmd_task shape.

    The body carries the verb + source_url + checksum_sha256 so the peer
    side can verify the pull before running powershell.
    """
    if target not in VALID_TARGETS:
        raise ValueError(f"target must be one of {VALID_TARGETS}, got {target!r}")
    if lanes not in VALID_LANE_STRINGS:
        raise ValueError(
            f"lanes must be one of {sorted(VALID_LANE_STRINGS)}, got {lanes!r}")
    tid = task_id or f"task-{uuid.uuid4().hex[:12]}"
    issued = issued_ts if issued_ts is not None else time.time()
    prompt = (
        "Re-run bridge_watcher_install.ps1 with -EnableLanes "
        f"{lanes!r} so the RC-BridgeWatcher-<Node> scheduled task XML "
        "carries --enable-auto-action-lanes. Pull the install.ps1 from "
        f"{INSTALL_PS1_URL} (sha256 verify against checksum_sha256 in this "
        "body). Then run: powershell -ExecutionPolicy Bypass -File "
        "<pulled-path> -Node <gamepc|peer> -EnableLanes "
        f"{lanes!r}. Verify via: schtasks /Query /TN "
        "RC-BridgeWatcher-<Node> /XML | findstr enable-auto-action-lanes."
    )
    body = {
        "issued":          issued,
        "verb":            VERB,
        "source_url":      INSTALL_PS1_URL,
        "checksum_sha256": checksum,
        "lanes":           lanes,
        "prompt":          prompt,
    }
    return {
        "kind":    "task",
        "id":      tid,
        "source":  source,
        "target":  target,
        "summary": f"enable auto-action-lanes {lanes!r} on {target}",
        "body":    body,
    }


def peer_already_enabled(target: str, lanes: str, *,
                         timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Best-effort idempotence check via dashboard /api/health/all.

    The watcher heartbeat does NOT currently surface enabled_lanes (a separate
    item-199 carry-forward). Until that lands, return False (caller still
    posts the envelope). Once the heartbeat carries the field, this short-
    circuits redundant dispatches.
    """
    try:
        req = urllib.request.Request(DASHBOARD_HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=_SSL_CTX) as r:
            payload = json.loads(r.read())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            ValueError) as exc:
        _log.info("peer health probe failed (%s); assuming not enabled", exc)
        return False
    peers = payload.get("peers") or {}
    peer = peers.get(target) or {}
    enabled = peer.get("enabled_lanes")
    if enabled is None:
        return False
    if isinstance(enabled, str):
        return enabled == lanes
    if isinstance(enabled, (list, tuple, set)):
        want = {p for p in lanes.split(",") if p}
        have = {str(x) for x in enabled}
        return want == have
    return False


def post_envelope(envelope: dict, *,
                  url: str = LEGION_BRIDGE,
                  timeout: float = DEFAULT_TIMEOUT) -> dict:
    """POST the envelope to the Legion bridge endpoint.

    Mirrors tools/bridge_cli.py::_post_envelope (no shared import to avoid
    coupling this PREP-only helper to the frozen bridge_cli surface).
    """
    body = json.dumps(envelope).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return json.loads(r.read())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bridge_dispatch_enable_lanes",
        description=(__doc__ or "").splitlines()[0],
    )
    p.add_argument("--target", required=True, choices=VALID_TARGETS,
                   help="peer to enable auto-action lanes on")
    p.add_argument("--lanes", default="read",
                   choices=sorted(VALID_LANE_STRINGS - {""}),
                   help="lanes string to pass to -EnableLanes "
                        "(default: read; 'read,ops' is the 2nd-stage promotion)")
    p.add_argument("--dry-run", action="store_true",
                   help="build the envelope + print as JSON; do NOT POST")
    p.add_argument("--force", action="store_true",
                   help="skip the dashboard idempotence check + always POST")
    p.add_argument("--source", default="legion",
                   help="envelope source field (default: legion)")
    p.add_argument("--id", default=None,
                   help="explicit task id (default: task-<uuid12>)")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        checksum = compute_install_ps1_checksum()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    envelope = build_envelope(args.target, args.lanes,
                              checksum=checksum,
                              source=args.source,
                              task_id=args.id)
    if args.dry_run:
        print(json.dumps(envelope, indent=2))
        return 0
    if not args.force and peer_already_enabled(args.target, args.lanes):
        print(json.dumps({"status": "already enabled",
                          "target": args.target, "lanes": args.lanes}))
        return 0
    try:
        ack = post_envelope(envelope)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        print(f"bridge post failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "task_id": envelope["id"],
        "target":  args.target,
        "lanes":   args.lanes,
        "ts":      ack.get("ts"),
        "summary": envelope["summary"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
