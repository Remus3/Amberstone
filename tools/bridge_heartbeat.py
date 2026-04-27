"""
bridge_heartbeat.py — periodic "alive" heartbeat to Legion's bridge.

Run on either machine as a long-lived process; posts a tiny bridge
message every INTERVAL_S seconds so the dashboard can surface "last
seen from gamepc" and "last seen from legion" at a glance.

Usage:
    py C:\\RC-Agent\\bridge_heartbeat.py              # on Game-PC
    py C:\\Riot Commander\\tools\\bridge_heartbeat.py # on Legion

Scheduled task (optional, run at logon, hidden):
    schtasks /Create /TN "RC-BridgeHeartbeat" /SC ONLOGON /RL HIGHEST /F ^
        /TR "py C:\\RC-Agent\\bridge_heartbeat.py"
"""
import json
import logging
import platform
import ssl
import sys
import time
import urllib.error
import urllib.request

LEGION_BRIDGE = "https://192.168.8.230:8888/api/bridge"
INTERVAL_S    = 60.0
SOURCE        = f"heartbeat-{platform.node().lower()}"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s heartbeat %(message)s")
log = logging.getLogger()

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _post(summary: str) -> None:
    body = json.dumps({"source": SOURCE, "summary": summary}).encode("utf-8")
    req = urllib.request.Request(
        LEGION_BRIDGE, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3.0, context=_CTX) as r:
        json.loads(r.read())


def main() -> int:
    log.info("starting — %s every %ds -> %s", SOURCE, INTERVAL_S, LEGION_BRIDGE)
    consec_fail = 0
    while True:
        t0 = time.time()
        try:
            uptime_h = (time.time() - _start) / 3600
            _post(f"alive uptime={uptime_h:.2f}h")
            if consec_fail:
                log.info("recovered after %d failures", consec_fail)
            consec_fail = 0
        except urllib.error.URLError as e:
            consec_fail += 1
            log.warning("post failed (%dx): %s", consec_fail, e.reason)
        except Exception as e:
            consec_fail += 1
            log.warning("post error (%dx): %s", consec_fail, e)
        # Backoff on repeated failure so a down Legion doesn't flood logs.
        sleep_for = INTERVAL_S if consec_fail < 3 else min(
            600.0, INTERVAL_S * (2 ** (consec_fail - 2))
        )
        elapsed = time.time() - t0
        time.sleep(max(0.0, sleep_for - elapsed))


_start = time.time()
if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("stopped.")
