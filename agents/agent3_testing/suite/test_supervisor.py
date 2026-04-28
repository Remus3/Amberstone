"""Smoke tests: supervisor starts, WS+web ports open, DBs exist, migration ran."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
# AUDIT P-audit3-m03 (2026-04-22): prefer the current interpreter, with
# env override for deliberate cross-version testing. No hardcoded paths
# that silently break after an upgrade.
PY = Path(os.environ.get("RC_PYTHON") or sys.executable)

from lib.modes import PHASE3_MODES
MODE_DBS = [f"{m}.db" for m in PHASE3_MODES]


def test_mode_dbs_exist() -> None:
    for name in MODE_DBS:
        p = _PROJECT_ROOT / "data" / "db" / name
        assert p.exists(), f"missing mode db {p}"
        assert p.stat().st_size > 0


def test_resolved_decisions_written() -> None:
    p = _PROJECT_ROOT / "agents" / "state" / "resolved_decisions.json"
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == "phase3-1.1"
    assert data["topology"]["legion_pc"] == "192.168.8.230"
    assert data["topology"]["game_pc"] == "192.168.8.237"
    assert data["db"]["files"] == MODE_DBS


def test_migration_ran() -> None:
    """Every mode DB except brawl should contain rewind_migration rows."""
    import sqlite3
    counts: dict[str, int] = {}
    for name in MODE_DBS:
        p = _PROJECT_ROOT / "data" / "db" / name
        with sqlite3.connect(p) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE source='rewind_migration'"
            ).fetchone()
            counts[name] = int(row[0])
    assert counts["aram.db"] > 0
    assert counts["sr_ranked.db"] > 0
    assert counts["arena.db"] > 0
    # brawl is expected empty (rewind pre-dates brawl mode)


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.mark.timeout(30)
def test_supervisor_starts_and_binds_ports(tmp_path: Path) -> None:
    """Spawn supervisor as subprocess; confirm :8890 and :8891 accept connections."""
    # Make sure no lockfile stops us — checked by supervisor itself.
    env = os.environ.copy()
    proc = subprocess.Popen(
        [str(PY), "-m", "agents.supervisor"],
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 15
        web_ok = ws_ok = False
        while time.time() < deadline:
            if not web_ok and _port_open("127.0.0.1", 8890):
                web_ok = True
            if not ws_ok and _port_open("127.0.0.1", 8891):
                ws_ok = True
            if web_ok and ws_ok:
                break
            time.sleep(0.5)
        assert web_ok, "web port 8890 never opened"
        assert ws_ok, "ws port 8891 never opened"

        # Heartbeat interval is 5s — give 15s to witness at least one
        # distinct post-startup refresh.
        lock = _PROJECT_ROOT / "agents" / "state" / "lockfile"
        first_hb: str | None = None
        for _ in range(15):
            if lock.exists():
                data = json.loads(lock.read_text(encoding="utf-8") or "{}")
                hb = data.get("heartbeat_at")
                if hb is not None:
                    if first_hb is None:
                        first_hb = hb
                    elif hb != first_hb:
                        break  # second distinct heartbeat — loop is alive
            time.sleep(1)
        else:
            pytest.fail("lockfile heartbeat never refreshed to a second value")
    finally:
        # Hard kill — spec forbids Stop-Process, use taskkill.
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
