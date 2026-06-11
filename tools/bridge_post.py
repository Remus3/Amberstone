# arch: Stop-hook poster - extract last assistant message and post | section=bridge | frozen=no
"""bridge_post.py - Phase 6 shim. Real code lives in tools/bridge_cli.py.

Stop-hook entrypoint. Reads the Stop-hook payload JSON from stdin, extracts
the last assistant message text, and posts a one-line summary to the bridge.
The single positional arg ('legion' or 'gamepc') tags the source.

    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe C:\\Riot Commander\\tools\\bridge_post.py legion

Equivalent to: `C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/bridge_cli.py post legion`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bridge_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["post"] + sys.argv[1:]))
