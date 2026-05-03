"""bridge_watcher_health_publisher.py — peer-side sidecar for fleet health.

Polls the local bridge_watcher_health.json every PUBLISH_INTERVAL_S seconds
and POSTs to Legion's /api/health/peer/<node>. Lets Legion's
/api/health/all roll up fleet-wide watcher health (queue depth, auto-action
counters, $ spent, last poll status).

Runs on Game-PC + Peer. Each peer's install dir varies:
  - Game-PC : C:\\RC-Agent\\
  - Peer     : <peer-vip>\\tools\\

Auth: same Bearer secret as the cross-Claude bridge (resolved via
core.bridge.shared_secret() if importable, else fallback to reading
ops/local_paths.json directly).

Deploy: register via Task Scheduler at logon, RestartOnFailure 3x/1m,
StopIfGoingOnBatteries=true (this is observability, not critical path).

CLI:
  python bridge_watcher_health_publisher.py --node gamepc \\
      --health-file C:/RC-Agent/bridge_watcher_health.json \\
      --legion-url https://legion-rc:8888 \\
      --interval 60 \\
      [--token-file path/to/local_paths.json]   # if can't import core.bridge

The script is intentionally robust — failures are logged, not raised; the
peer's primary work shouldn't be impacted by Legion being down.
"""
from __future__ import annotations

import argparse
import json
import logging
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("rc.health_publisher")

_VALID_NODES = {"gamepc", "peer"}
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _resolve_token(token_file: Path | None) -> str | None:
    """Try core.bridge.shared_secret() first; fall back to reading
    ops/local_paths.json directly."""
    try:
        from core import bridge as _b
        secret = _b.shared_secret()
        if secret:
            return secret
    except Exception as exc:
        log.debug("core.bridge import failed: %s", exc)

    if token_file and token_file.exists():
        try:
            data = json.loads(token_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # bridge_shared_secret is the canonical RC key (matches
                # core/bridge.py:_load_config). The legacy aliases stay for
                # peers that wrote their token file before the rename.
                return (data.get("bridge_shared_secret")
                        or data.get("rc_peer_bridge_secret")
                        or data.get("bridge_secret")
                        or data.get("shared_secret"))
        except Exception as exc:
            log.warning("token_file read failed: %s", exc)
    return None


def _read_health(health_file: Path) -> dict | None:
    try:
        return json.loads(health_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("health_file read failed: %s", exc)
        return None


def _publish_once(node: str, health: dict, legion_url: str, token: str) -> bool:
    body = json.dumps(health).encode()
    url = f"{legion_url.rstrip('/')}/api/health/peer/{node}"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0, context=_SSL_CTX) as r:
            r.read()
        return True
    except urllib.error.HTTPError as exc:
        log.warning("publish http %s: %s", exc.code, exc.read()[:200])
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("publish failed: %s", exc)
    return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--node", choices=sorted(_VALID_NODES), required=True)
    p.add_argument("--health-file", required=True,
                   help="path to local bridge_watcher_health.json")
    p.add_argument("--legion-url", default="https://legion-rc:8888",
                   help="Legion dashboard base URL")
    p.add_argument("--interval", type=int, default=60,
                   help="seconds between publishes")
    p.add_argument("--token-file", default=None,
                   help="path to ops/local_paths.json (only needed if "
                        "core.bridge isn't importable)")
    p.add_argument("--once", action="store_true",
                   help="publish once and exit (for testing)")
    args = p.parse_args()

    health_file = Path(args.health_file)
    token_file = Path(args.token_file) if args.token_file else None
    token = _resolve_token(token_file)
    if not token:
        log.error("could not resolve bearer token — set --token-file or "
                  "ensure core.bridge is importable")
        return 2

    log.info("publisher starting node=%s legion=%s interval=%ds health=%s",
             args.node, args.legion_url, args.interval, health_file)

    consecutive_fail = 0
    while True:
        health = _read_health(health_file)
        if health is None:
            consecutive_fail += 1
            log.warning("health file unreadable (consecutive=%d)", consecutive_fail)
        else:
            ok = _publish_once(args.node, health, args.legion_url, token)
            if ok:
                if consecutive_fail:
                    log.info("publish OK (recovered from %d failures)",
                             consecutive_fail)
                consecutive_fail = 0
            else:
                consecutive_fail += 1

        if args.once:
            return 0 if consecutive_fail == 0 else 1

        # Light backoff after sustained failures so we don't hammer a down
        # Legion. Cap at 5x interval.
        sleep_s = args.interval * min(1 + consecutive_fail // 5, 5)
        time.sleep(sleep_s)


if __name__ == "__main__":
    sys.exit(main())
