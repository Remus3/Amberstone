# arch: post task result back to issuing machine | section=bridge | frozen=yes
"""bridge_post_result.py - Phase 6 shim. Real code lives in tools/bridge_cli.py.

Frozen contract (cron + /loop /process-bridge-tasks invoke this by file path):
    py tools/bridge_post_result.py <task_id> [--source ...] [--summary ...]
        [--body ...] [--from-stdin] [--exit-code N] [--no-mark]
        [--reply-to legion|gamepc|peer] [--suggestions ...]

Side effects preserved:
    - Appends task_id to %LOCALAPPDATA%\\rc-bridge-tasks-processed.txt
    - For --reply-to=peer, routes via core.bridge.send() (cross-tailnet bearer-auth)
    - For legion/gamepc, POSTs to https://legion-rc:8888/api/bridge

Equivalent to: `py tools/bridge_cli.py post-result <task_id> ...`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bridge_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["post-result"] + sys.argv[1:]))
