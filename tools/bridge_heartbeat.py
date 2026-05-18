# arch: long-running alive heartbeat to the bridge | section=bridge | frozen=no
"""bridge_heartbeat.py - Phase 6 shim. Real code lives in tools/bridge_cli.py.

Long-running entrypoint posting an alive note every 60s:
    py C:\\Riot Commander\\tools\\bridge_heartbeat.py

Equivalent to: `py tools/bridge_cli.py heartbeat`.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bridge_cli import main  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(main(["heartbeat"] + sys.argv[1:]))
    except KeyboardInterrupt:
        logging.getLogger().info("stopped.")
