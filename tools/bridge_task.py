# arch: dispatch a task to the other Claude via the bridge | section=bridge | frozen=no
"""bridge_task.py - Phase 6 shim. Real code lives in tools/bridge_cli.py.

Preserves the original CLI surface:
    py tools/bridge_task.py --target gamepc --summary "..." --prompt "..."

Equivalent to: `py tools/bridge_cli.py task --target gamepc ...`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bridge_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["task"] + sys.argv[1:]))
