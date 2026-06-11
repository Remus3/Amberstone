# arch: UserPromptSubmit hook - print recent peer activity | section=bridge | frozen=no
"""bridge_fetch.py - Phase 6 shim. Real code lives in tools/bridge_cli.py.

UserPromptSubmit hook entrypoint:
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe C:\\Riot Commander\\tools\\bridge_fetch.py

Equivalent to: `C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/bridge_cli.py fetch`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bridge_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["fetch"] + sys.argv[1:]))
