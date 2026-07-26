"""Session-independent watchdog for the replay ingest chain.

    python tools/replay_chain_watch.py            # one pass, safe to re-run
    python tools/replay_chain_watch.py --status   # report only, change nothing

WHY THIS EXISTS. The long ingests (timeline_ingest, build_rank_baselines) are
detached processes and survive a closed session, but the FOLLOW-UPS were
session-held: re-enabling RC-ReplayRosterPull and running the pattern miner.
If the session ends first, those never happen - and the roster task staying
Disabled is not cosmetic. `/replays` serves only the 5 most recent retained
files per account with NO fetch-by-match-id route, so any game that rotates out
while the task is off is lost permanently. Measured twice on 2026-07-26: two
specifically requested matches had already rotated out and were unrecoverable.

Run as a scheduled task so the OS owns it, not a chat session. Idempotent by
construction: it re-enables an already-enabled task never, and only mines when
the corpus has grown since the last mine.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import replay_roster as rr                          # noqa: E402

ROOT = Path(__file__).parent.parent
TASK = "RC-ReplayRosterPull"
RATES = ROOT / "data" / "event_pattern_rates.json"
BUSY_PATTERNS = ("timeline_ingest", "build_rank_baselines",
                 "replay_roster_pull", "ladder_role_scout")


def _ps(cmd: str) -> str:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                             capture_output=True, text=True, timeout=60)
        return (out.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001 - a probe must never abort the watch
        return f"<error {exc}>"


def busy() -> list:
    """Which ingest processes still hold the Riot rate budget."""
    running = []
    for pat in BUSY_PATTERNS:
        n = _ps("(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                f"Where-Object {{ $_.CommandLine -like '*{pat}*' }} | "
                "Measure-Object).Count")
        if n.isdigit() and int(n) > 0:
            running.append(pat)
    return running


def task_state() -> str:
    return _ps(f"(Get-ScheduledTask -TaskName '{TASK}').State")


def timelines_count() -> int:
    d = rr.default_corpus_root() / "timelines"
    return len(list(d.glob("*.json"))) if d.exists() else 0


def needs_mine() -> bool:
    """Mine when the corpus has grown since the last rates file was written."""
    if not RATES.exists():
        return timelines_count() > 0
    try:
        prev = int(__import__("json").loads(
            RATES.read_text(encoding="utf-8")).get("matches") or 0)
    except Exception:  # noqa: BLE001
        return True
    return timelines_count() > prev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replay chain watchdog.")
    ap.add_argument("--status", action="store_true",
                    help="report only, change nothing")
    args = ap.parse_args(argv)

    running = busy()
    state = task_state()
    n = timelines_count()
    print(f"timelines={n} task={TASK}:{state} busy={running or 'none'}")

    if args.status:
        return 0

    if running:
        print("ingest still running - nothing to do")
        return 0

    if state == "Disabled":
        _ps(f"Enable-ScheduledTask -TaskName '{TASK}' | Out-Null")
        print(f"re-enabled {TASK} -> {task_state()}")
    else:
        print(f"{TASK} already {state}")

    if needs_mine():
        print("corpus grew since last mine - running miner")
        res = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "mine_event_patterns.py"),
             "--out", str(RATES)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=3600)
        tail = (res.stdout or "").strip().splitlines()[-12:]
        print("\n".join(tail) or (res.stderr or "").strip()[-500:])
    else:
        print("miner up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
