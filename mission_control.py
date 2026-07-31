# arch: Mission Control process entry (:8895) | section=mc | frozen=no
"""Mission Control entry point.

Run under pythonw.exe by the RC-MissionControl scheduled task. Deliberately
independent of RC: this process is NOT supervisor-managed and does NOT watch
restart_trigger.txt, so an RC restart for a game-overlay change cannot touch
the control plane. That independence is the whole point of S10.

Its own log file, not the shared logs/YYYY-MM-DD.log - two processes
appending to one file on Windows is a lock hazard, and a control-plane log
interleaved with game-dashboard chatter is hardest to read at exactly the
moment it matters.
"""
from __future__ import annotations

import datetime as _dt
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _setup_logging() -> None:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y-%m-%d")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(logs / f"mission_control-{stamp}.log",
                                      encoding="utf-8")],
    )


def main() -> int:
    _setup_logging()
    from mc import server
    return server.main()


if __name__ == "__main__":
    sys.exit(main())
