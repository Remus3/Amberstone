"""Smoke tests: supervisor starts, WS+web ports open, DBs exist, migration ran."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sqlite3
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


def _require_populated_mode_dbs() -> None:
    """Skip when this checkout has no POPULATED mode DBs.

    RM-170 (2026-08-06): ``data/db/*.db`` is gitignored (`.gitignore:32`
    ``**/*.db``), so it is machine-local history, not repo content. A fresh
    clone has none, and a git WORKTREE gets none either - the first supervisor
    boot in that tree calls ``init_all_dbs()`` and creates EMPTY schemas. The
    two assertions below are about a one-time historical ETL
    (``source='rewind_migration'``) that only ever ran on Legion's main
    checkout, so outside it they are unsatisfiable by construction rather than
    a regression. Gate on "matches has ANY rows": if the DB carries match rows
    but none from the migration, that IS a real regression and still fails.
    """
    db_dir = _PROJECT_ROOT / "data" / "db"
    if not db_dir.is_dir():
        pytest.skip(f"no {db_dir} - machine-local match history absent in this checkout")
    aram = db_dir / "aram.db"
    if not aram.exists():
        pytest.skip(f"no {aram} - machine-local match history absent in this checkout")
    with sqlite3.connect(aram) as conn:
        try:
            total = int(conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0])
        except sqlite3.Error as e:  # table absent on a half-initialised DB
            pytest.skip(f"aram.db carries no usable matches table ({e})")
    if total == 0:
        pytest.skip(
            "aram.db is an empty freshly-initialised schema (worktree / fresh "
            "clone) - the rewind_migration history lives only on Legion's main "
            "checkout"
        )


def test_mode_dbs_exist() -> None:
    _require_populated_mode_dbs()
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
    _require_populated_mode_dbs()
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


def _free_port() -> int:
    """Reserve an ephemeral port, then release it for the child to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.timeout(60)
def test_supervisor_starts_and_binds_ports(tmp_path: Path) -> None:
    """Spawn a supervisor on FREE ports; confirm it binds both and heartbeats.

    RM-170 (2026-08-06) made this hermetic. It previously spawned the child on
    the HARDCODED :8890/:8891 and read the SHARED ``agents/state/lockfile``, so
    whenever the live RC-Phase3-Supervisor scheduled task was up (its normal
    state on Legion) the child died at ``agents/supervisor.py:275`` with
    "port 8890 (web) is already in use" - and worse, ``_port_open`` then
    answered TRUE against the LIVE supervisor's listeners, so both port
    assertions passed against the wrong process and only the heartbeat check
    caught it. Measured 4/4 deterministic failures, serial and under xdist.

    Now the child gets its own free ports and its own throwaway state dir via
    RC_PHASE3_WEB_PORT / RC_PHASE3_WS_PORT / RC_PHASE3_STATE_DIR, so nothing is
    listening on those ports but the child, the port assertions cannot be
    satisfied by a bystander, and the live supervisor's lockfile is never
    touched.
    """
    # resolved_decisions.json is TRACKED, so it cannot legitimately be absent -
    # assert rather than skip (a skip here would be an always-passing guard;
    # see tests/test_skip_condition_hygiene.py).
    decisions_src = _PROJECT_ROOT / "agents" / "state" / "resolved_decisions.json"
    assert decisions_src.exists(), (
        f"missing tracked file {decisions_src} - restore it from git, or run "
        "`python ops/phase3_setup.py`"
    )

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # The supervisor fail-closes on this file's version at startup
    # (_verify_decisions_version, agents/_supervisor_common.py).
    shutil.copy2(decisions_src, state_dir / "resolved_decisions.json")

    # agents/supervisor.py calls init_all_dbs() BEFORE the port preflight, so
    # the child manufactures data/db/*.db in whatever tree it is launched from -
    # which is how this test used to create the very precondition its sibling
    # tests inspect, and why this row's failure count looked non-deterministic.
    # Point the mode DBs at a tmp dir so the run leaves the checkout alone.
    db_dir = tmp_path / "db"
    db_dir.mkdir()

    web_port = _free_port()
    ws_port = _free_port()

    env = os.environ.copy()
    env["RC_PHASE3_WEB_PORT"] = str(web_port)
    env["RC_PHASE3_WS_PORT"] = str(ws_port)
    env["RC_PHASE3_STATE_DIR"] = str(state_dir)
    env["RC_PHASE3_DB_DIR"] = str(db_dir)

    proc = subprocess.Popen(
        [str(PY), "-m", "agents.supervisor"],
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 25
        web_ok = ws_ok = False
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.fail(
                    "supervisor exited early (rc="
                    f"{proc.returncode}):\n{proc.communicate()[0]}"
                )
            if not web_ok and _port_open("127.0.0.1", web_port):
                web_ok = True
            if not ws_ok and _port_open("127.0.0.1", ws_port):
                ws_ok = True
            if web_ok and ws_ok:
                break
            time.sleep(0.5)
        assert web_ok, f"web port {web_port} never opened"
        assert ws_ok, f"ws port {ws_port} never opened"

        # Heartbeat interval is 5s - give 20s to witness at least one
        # distinct post-startup refresh.
        lock = state_dir / "lockfile"
        first_hb: str | None = None
        for _ in range(20):
            if lock.exists():
                data = json.loads(lock.read_text(encoding="utf-8") or "{}")
                hb = data.get("heartbeat_at")
                if hb is not None:
                    if first_hb is None:
                        first_hb = hb
                    elif hb != first_hb:
                        break  # second distinct heartbeat - loop is alive
            time.sleep(1)
        else:
            pytest.fail("lockfile heartbeat never refreshed to a second value")
    finally:
        # Hard kill - spec forbids Stop-Process, use taskkill.
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
