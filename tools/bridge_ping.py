"""
bridge_ping.py — end-to-end bridge validator.

Run on either machine. Posts a ping message to Legion's /api/bridge,
immediately re-reads the bridge, and prints PASS/FAIL with round-trip
latency. Also probes /upload-frame on the vision relay so you can tell
which leg is broken when things go quiet.

Usage:
    py C:\\RC-Agent\\bridge_ping.py               # on Game-PC
    py C:\\Riot Commander\\tools\\bridge_ping.py  # on Legion

Exit codes:
    0 = both legs healthy
    1 = bridge post failed (HTTPS/cert/port issue on Legion)
    2 = bridge post ok but read-back did not see the message
    3 = bridge ok, vision relay /health unreachable
"""
import json
import os
import platform
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

LEGION_BRIDGE = "https://192.168.8.230:8888/api/bridge"
VISION_HEALTH = "http://192.168.8.230:8889/health"
AUTH_TOKEN    = "8e8f131e212b329438218eca27372dde"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _post_bridge(summary: str) -> float:
    body = json.dumps({"source": f"ping-{platform.node()}",
                       "summary": summary}).encode("utf-8")
    req = urllib.request.Request(
        LEGION_BRIDGE, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3.0, context=_CTX) as r:
        data = json.loads(r.read())
    return float(data.get("ts", 0))


def _read_bridge(since: float) -> list:
    url = f"{LEGION_BRIDGE}?since={since}&limit=5"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=3.0, context=_CTX) as r:
        return json.loads(r.read()).get("messages", [])


def _vision_health() -> dict:
    req = urllib.request.Request(VISION_HEALTH,
                                 headers={"X-RC-Token": AUTH_TOKEN})
    with urllib.request.urlopen(req, timeout=3.0) as r:
        return json.loads(r.read())


def main() -> int:
    host = platform.node()
    token = f"bridge-ping {host} {time.time():.3f}"
    print(f"== bridge_ping  host={host}  legion={LEGION_BRIDGE}")

    # Leg 1: POST
    t0 = time.time()
    try:
        ts = _post_bridge(token)
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

    # Leg 2: read-back
    t0 = time.time()
    try:
        since = ts - 1.0
        msgs = _read_bridge(since)
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

    # Leg 3: vision relay
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

    total = (time.time() - t0) * 1000  # last leg only; sum approximate
    print(f"== bridge healthy  (post+read+vision all ok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
