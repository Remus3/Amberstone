# arch: fetch pending bridge tasks targeted at this machine | section=bridge | frozen=yes
"""bridge_pull_tasks.py — Phase 6 shim. Real code lives in tools/bridge_cli.py.

Frozen contract (the /process-bridge-tasks skill spec parses this script's
JSON output by exact shape):
    py tools/bridge_pull_tasks.py [--target legion|gamepc]

Output schema preserved:
    {"now": <ts>, "target": "...", "count": N, "tasks": [<envelope>, ...]}

Side effects preserved:
    - Reads %LOCALAPPDATA%\\rc-bridge-tasks-processed.txt to skip handled ids
    - Filters to kind=task with target=this machine (legion accepts rc alias)
    - Drops tasks already answered (kind=result with in_reply_to)
    - Sorts oldest-first

Equivalent to: `py tools/bridge_cli.py pull --target ...`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bridge_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["pull"] + sys.argv[1:]))
