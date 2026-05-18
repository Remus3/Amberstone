# arch: end-to-end bridge + vision health validator | section=bridge | frozen=no
"""bridge_ping.py - Phase 6 shim. Real code lives in tools/bridge_cli.py.

Preserves the original CLI surface (no flags) and exit-code contract:
    0 = both legs healthy
    1 = bridge post failed
    2 = bridge post ok but read-back missed
    3 = bridge ok, vision relay unreachable

Equivalent to: `py tools/bridge_cli.py ping`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bridge_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["ping"] + sys.argv[1:]))
