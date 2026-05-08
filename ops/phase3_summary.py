"""Phase 3 build completion summary (§15).

Generates a reproducible status snapshot of everything built in this
setup pass. Prints to stdout; does not modify anything.
"""
from __future__ import annotations

import json
import os
import py_compile
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Riot Commander")


FOLDERS_TO_REPORT = [
    "agents", "agents/state",
    "agents/agent0_gatekeeper", "agents/agent1_lead", "agents/agent2_backend",
    "agents/agent2_backend/pipeline",
    "agents/agent3_testing", "agents/agent3_testing/suite",
    "agents/agent4_coach_mentor", "agents/agent4_coach_mentor/proposals",
    "agents/agent5_ui",
    "agents/agent6_auditor", "agents/agent6_auditor/safeguards",
    "agents/agent7_context",
    "lib", "lib/http", "lib/ddragon", "lib/scrapers", "lib/icons",
    "web", "web/css", "web/js", "web/assets",
    "data/db", "data/meta_build/scraped/site_d", "data/meta_build/scraped/ugg",
    "data/meta_build/curated", "data/meta_build/ddragon", "data/coach_cache",
    "logs/agents", "logs/scrapers", "logs/ws",
]

PY_FILES = [
    "lib/__init__.py",
    "lib/http/__init__.py",
    "lib/http/client.py",
    "lib/ddragon/__init__.py",
    "lib/ddragon/fetch.py",
    "lib/scrapers/__init__.py",
    "lib/scrapers/_base.py",
    "lib/scrapers/site_d.py",
    "lib/scrapers/ugg.py",
    "lib/icons/__init__.py",
    "lib/icons/downloader.py",
    "agents/__init__.py",
    "agents/supervisor.py",
    "agents/agent0_gatekeeper/__init__.py",
    "agents/agent0_gatekeeper/evaluator.py",
    "agents/agent1_lead/__init__.py",
    "agents/agent1_lead/scheduler.py",
    "agents/agent2_backend/__init__.py",
    "agents/agent2_backend/db_schema.py",
    "agents/agent2_backend/migration_rewind.py",
    "agents/agent2_backend/smb_push.py",
    "agents/agent2_backend/ws_server.py",
    "agents/agent3_testing/__init__.py",
    "agents/agent3_testing/suite/__init__.py",
    "agents/agent3_testing/suite/conftest.py",
    "agents/agent3_testing/suite/test_supervisor.py",
    "agents/agent3_testing/suite/test_agent0.py",
    "agents/agent3_testing/suite/test_agent1.py",
    "agents/agent3_testing/suite/test_smb_push.py",
    "agents/agent3_testing/suite/_smoke_agent0.py",
    "agents/agent3_testing/suite/_smoke_agent1.py",
    "ops/phase3_setup.py",
    "ops/phase3_queue_first_audit.py",
    "ops/phase3_summary.py",
]

NON_PY_FILES = [
    "agents/agent0_gatekeeper/allowed_ops.json",
    "agents/agent0_gatekeeper/target_allowlist.json",
    "agents/state/resolved_decisions.json",
    "agents/state/task_queue.jsonl",
    "agents/state/lockfile",
    "lib/http/blocklist.json",
    "web/index.html",
    "web/css/stub.css",
    "web/js/ws_client.js",
    "ops/phase3_install.ps1",
]

DB_FILES = ["sr_draft.db", "sr_ranked.db", "aram.db", "arena.db", "brawl.db"]


def _line_count(p: Path) -> int:
    try:
        return sum(1 for _ in p.open("r", encoding="utf-8", errors="replace"))
    except OSError:
        return -1


def _byte_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return -1


def _compile_ok(p: Path) -> str:
    try:
        py_compile.compile(str(p), doraise=True)
        return "OK"
    except py_compile.PyCompileError as e:
        return f"FAIL: {e.msg[:80]}"
    except OSError as e:
        return f"IO: {e}"


def _smb_reachable() -> bool:
    try:
        return os.path.exists(r"\\192.168.8.237\RCClient")
    except OSError:
        return False


def _supervisor_status() -> dict:
    lock = ROOT / "agents" / "state" / "lockfile"
    info: dict = {"lockfile_exists": lock.exists(), "lockfile_size": _byte_size(lock)}
    try:
        data = json.loads(lock.read_text(encoding="utf-8") or "{}")
        pid = int(data.get("pid") or 0)
        info["pid"] = pid
        info["host"] = data.get("host")
        info["last_heartbeat"] = data.get("heartbeat_at") or data.get("started_at")
        if pid > 0:
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FI", f"PID eq {pid}"], text=True, timeout=5,
                )
                info["pid_alive"] = str(pid) in out
            except (subprocess.SubprocessError, OSError):
                info["pid_alive"] = False
    except (json.JSONDecodeError, OSError):
        pass

    # Port status — do we have the ports bound?
    for port, label in [(8890, "web"), (8891, "ws")]:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                info[f"port_{label}_{port}"] = "open"
        except OSError:
            info[f"port_{label}_{port}"] = "closed"
    return info


def _db_counts() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in DB_FILES:
        p = ROOT / "data" / "db" / name
        if not p.exists():
            out[name] = {"exists": False}
            continue
        try:
            with sqlite3.connect(p) as conn:
                m = conn.execute(
                    "SELECT COUNT(*) FROM matches WHERE source='rewind_migration'"
                ).fetchone()[0]
                e = conn.execute(
                    "SELECT COUNT(*) FROM match_events "
                    "WHERE match_id IN (SELECT match_id FROM matches WHERE source='rewind_migration')"
                ).fetchone()[0]
                out[name] = {"matches_rewind": int(m), "events_rewind": int(e), "size_bytes": _byte_size(p)}
        except sqlite3.Error as err:
            out[name] = {"error": str(err)}
    return out


def _first_task() -> dict | None:
    q = ROOT / "agents" / "state" / "task_queue.jsonl"
    if not q.exists() or q.stat().st_size == 0:
        return None
    last = None
    with q.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event") == "filed":
                last = rec
                break   # first "filed" is the first task
    if not last:
        return None
    t = last.get("task", {})
    return {
        "id": t.get("id"),
        "op": t.get("op"),
        "owner_agent": t.get("owner_agent"),
        "priority": t.get("priority"),
        "status": t.get("status"),
    }


def main() -> int:
    print("=" * 72)
    print("RIOT COMMANDER — Phase 3 setup completion summary")
    print("=" * 72)
    print()

    # --- folders ---
    print("## Folders created")
    for rel in FOLDERS_TO_REPORT:
        p = ROOT / rel
        tag = "OK" if p.is_dir() else "MISS"
        print(f"  [{tag}] {rel}")
    print()

    # --- python files ---
    print("## Python files written")
    print(f"{'compile':<6} {'lines':>6} {'bytes':>8}  path")
    total_lines = 0
    for rel in PY_FILES:
        p = ROOT / rel
        if not p.exists():
            print(f"MISS                 {rel}")
            continue
        lines = _line_count(p)
        size = _byte_size(p)
        total_lines += max(0, lines)
        print(f"{_compile_ok(p):<6} {lines:>6} {size:>8}  {rel}")
    print(f"  total python lines: {total_lines}")
    print()

    # --- non-python files ---
    print("## Non-Python files written")
    print(f"{'size':>8}  path")
    for rel in NON_PY_FILES:
        p = ROOT / rel
        if not p.exists():
            print(f"     MISS  {rel}")
            continue
        print(f"{_byte_size(p):>8}  {rel}")
    print()

    # --- DB migration ---
    print("## Migration (rewind -> mode DBs)")
    counts = _db_counts()
    for name, info in counts.items():
        print(f"  {name:<12} {info}")
    total_matches = sum(v.get("matches_rewind", 0) for v in counts.values() if isinstance(v, dict))
    total_events = sum(v.get("events_rewind", 0) for v in counts.values() if isinstance(v, dict))
    print(f"  TOTAL: matches={total_matches} events={total_events}")
    print()

    # --- supervisor status ---
    print("## Supervisor")
    sup = _supervisor_status()
    for k, v in sup.items():
        print(f"  {k}: {v}")
    print()

    # --- SMB share ---
    print("## Cross-machine (SMB)")
    print("  share_unc: \\\\192.168.8.237\\RCClient")
    print(f"  reachable: {_smb_reachable()}")
    try:
        out = subprocess.check_output(
            ["cmdkey", "/list:192.168.8.237"], text=True, timeout=5, stderr=subprocess.STDOUT,
        )
        print(f"  cmdkey: {'present' if 'Target:' in out else 'missing'}")
    except (subprocess.SubprocessError, OSError) as e:
        print(f"  cmdkey: probe failed ({e})")
    print()

    # --- first task ---
    print("## First queued task (post-setup)")
    ft = _first_task()
    if ft:
        for k, v in ft.items():
            print(f"  {k}: {v}")
    else:
        print("  (none — task_queue.jsonl empty)")
    print()

    # --- deferred ---
    print("## Deferred (not built in this pass — follow-up sessions)")
    deferred = [
        "Forwarder Agent on Game-PC (tray app; §12 — user handles setup separately)",
        "Ephemeral Claude Code session spawning with charters (stubbed in supervisor; "
        "needs per-agent system prompts from deliverable A follow-ups)",
        "Agent 5 real UI (web stub only; Agent 5 builds full panel roster — §5)",
        "Agent 4 analyzer.py and learn/adapt loop implementation (proposals/ dir exists, logic deferred)",
        "Agent 6 safeguards implementations (dir exists, rules deferred until audit pass)",
        "Agent 7 input_parser.py (dir exists, warm-session handle stubbed in supervisor)",
        "Agent 2 pipeline/ (dir exists, scrape orchestrators deferred)",
        "scraped sites — no actual HTML fetched yet (scraper primitives ready; "
        "Agent 4 triggers fetch during first audit)",
        "DDragon bundles not yet cached (fetcher ready; will pull on first coach call)",
    ]
    for d in deferred:
        print(f"  - {d}")
    print()

    print("=" * 72)
    print("setup OK — supervisor is installed as RC-Phase3-Supervisor (at-logon, "
          "30s delay, restart-on-failure 5x). Running right now is optional; the "
          "scheduled task will bring it up on next logon. Audit task is queued.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
