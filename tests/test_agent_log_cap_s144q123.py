"""S144-Q-123 (RM-718 residue): the Phase 3 per-agent logs rotate at a size cap.

``logs/agents/agent<N>.log`` is appended by plain file I/O from two modules:
agents/supervisor.py ``_run_deterministic`` (the DETERMINISTIC row) and
agents/_supervisor_ephemeral.py ``spawn_ephemeral_llm`` (the SPAWN / REFUSED /
TIMEOUT / FAIL / AUTH-CAUSE / OK rows). Nothing bounded it: core/log_retention
sweeps only the top-level ``logs/*.log*`` (non-recursive), and
``prune_task_logs`` ages out ``task-*.log`` only and says it never touches the
rollup. Measured 2026-11-08: ``logs/agents/agent6.log`` was 2,078,244 B, 15,811
rows from 2026-04-22 on, still growing with each periodic audit spawn.

Both modules now append through ``agents._supervisor_common.append_agent_log``,
which rotates the file through core/log_rotation (5 MiB, 2 backups) before the
append. The rotation is best effort - a refused rename writes the one-line
refusal note ahead of the row, and any other failure falls back to a plain
append - so a log cap can never cost a task its row. Every write here lands in
tmp_path; the spawn is a fake that raises the route refusal before any process.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import _supervisor_common as common
from tests._repo_walk import REPO_ROOT

_ROW = "2026-11-08T00:00:00+00:00 OK agent=6 task=t-x elapsed=1.0s stdout_bytes=1\n"


def _gens(log: Path) -> list[str]:
    return sorted(p.name for p in log.parent.iterdir())


def test_cap_defaults_follow_core_log_rotation():
    from core import log_rotation

    assert common.AGENT_LOG_MAX_BYTES == log_rotation.DEFAULT_MAX_BYTES
    assert common.AGENT_LOG_BACKUPS == log_rotation.DEFAULT_BACKUP_COUNT


def test_append_creates_the_dir_and_writes_one_lf_row(tmp_path):
    log = tmp_path / "agents" / "agent6.log"
    common.append_agent_log(log, _ROW)
    assert log.read_bytes() == _ROW.encode("utf-8")


def test_under_the_cap_never_rotates(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "AGENT_LOG_MAX_BYTES", 10_000)
    log = tmp_path / "agent6.log"
    for _ in range(5):
        common.append_agent_log(log, _ROW)
    assert _gens(log) == ["agent6.log"]
    assert log.read_bytes().count(b"\n") == 5


def test_size_cap_bounds_the_file_and_the_generations(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "AGENT_LOG_MAX_BYTES", 512)
    log = tmp_path / "agent6.log"
    for i in range(400):
        common.append_agent_log(log, f"row {i:04d} " + "x" * 60 + "\n")
    # The live file never passes the cap by more than the row that tripped it.
    assert log.stat().st_size <= 512 + 80, log.stat().st_size
    # Exactly AGENT_LOG_BACKUPS generations are kept: the chain is bounded.
    assert _gens(log) == ["agent6.log", "agent6.log.1", "agent6.log.2"]
    # The newest row is in the live file and the rows stay in order across .1.
    assert log.read_text(encoding="utf-8").splitlines()[-1].startswith("row 0399 ")
    older = (tmp_path / "agent6.log.1").read_text(encoding="utf-8").splitlines()
    assert older and older[-1] < log.read_text(encoding="utf-8").splitlines()[0]


def test_an_oversize_file_rotates_before_the_append(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "AGENT_LOG_MAX_BYTES", 100)
    log = tmp_path / "agent7.log"
    log.write_bytes(b"old\n" * 40)
    common.append_agent_log(log, _ROW)
    assert log.read_bytes() == _ROW.encode("utf-8")
    assert (tmp_path / "agent7.log.1").read_bytes() == b"old\n" * 40


def test_a_refused_rotation_notes_itself_and_keeps_the_row(tmp_path, monkeypatch):
    from core import log_rotation

    monkeypatch.setattr(common, "AGENT_LOG_MAX_BYTES", 100)
    monkeypatch.setattr(
        log_rotation, "try_rotate",
        lambda path, backup_count=2: PermissionError(32, "held by another process"))
    log = tmp_path / "agent6.log"
    log.write_bytes(b"old\n" * 40)
    common.append_agent_log(log, _ROW)
    text = log.read_text(encoding="utf-8")
    assert text.startswith("old\n" * 40)
    tail = text[len("old\n" * 40):].splitlines(keepends=True)
    assert len(tail) == 2
    assert "log rotation refused for agent6.log" in tail[0]
    assert tail[1] == _ROW
    assert _gens(log) == ["agent6.log"]


def test_a_failing_cap_never_costs_the_row(tmp_path, monkeypatch):
    from core import log_rotation

    def _boom(*_a, **_k):
        raise RuntimeError("rotation exploded")

    monkeypatch.setattr(common, "AGENT_LOG_MAX_BYTES", 100)
    monkeypatch.setattr(log_rotation, "recover_orphans", _boom)
    log = tmp_path / "agent6.log"
    log.write_bytes(b"old\n" * 40)
    common.append_agent_log(log, _ROW)
    assert log.read_bytes() == b"old\n" * 40 + _ROW.encode("utf-8")


def test_a_crashed_rotation_scratch_is_recovered_under_the_cap(tmp_path):
    log = tmp_path / "agent6.log"
    staged = tmp_path / "agent6.log.rotating.4242.deadbeef"
    staged.write_bytes(b"staged generation\n")
    common.append_agent_log(log, _ROW)
    assert not staged.exists()
    assert (tmp_path / "agent6.log.1").read_bytes() == b"staged generation\n"
    assert log.read_bytes() == _ROW.encode("utf-8")


# ---------------------------------------------------------------- the callers

def test_run_deterministic_row_goes_through_the_cap(tmp_path, monkeypatch):
    from agents import supervisor as sup_mod

    monkeypatch.setattr(sup_mod, "LOG_ROOT", tmp_path)
    monkeypatch.setattr(common, "AGENT_LOG_MAX_BYTES", 100)
    log = tmp_path / "agent4.log"
    log.write_bytes(b"old\n" * 40)
    handler = sup_mod.Supervisor.__dict__["_run_deterministic"]
    # user-note is a record-keeping op (agents/agent3_testing/suite/test_round43.py).
    task = SimpleNamespace(id="t-cap-det", op="user-note", owner_agent="4", payload={})
    handler(None, task)
    assert (tmp_path / "agent4.log.1").read_bytes() == b"old\n" * 40
    rows = log.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert " DETERMINISTIC agent=4 task=t-cap-det op=user-note " in rows[0]


def test_ephemeral_spawn_rows_go_through_the_cap(tmp_path, monkeypatch):
    from agents import _supervisor_ephemeral as eph
    from ops.loop import fleet_route
    from tests._module_view import bind_which

    def _refuse(*_a, **_k):
        raise fleet_route.RouteRefused("no-route")

    monkeypatch.setattr(eph, "LOG_ROOT", tmp_path)
    monkeypatch.setattr(eph, "prune_task_logs", lambda *a, **k: 0)
    bind_which(monkeypatch, eph, lambda *_a, **_k: "/fake/claude")
    monkeypatch.setattr(fleet_route, "spawn", _refuse)
    # Over the cap before the spawn; the SPAWN row alone stays under it, so the
    # REFUSED row is appended after it rather than rotating it away.
    monkeypatch.setattr(common, "AGENT_LOG_MAX_BYTES", 1000)
    log = tmp_path / "agent7.log"
    log.write_bytes(b"old\n" * 300)
    with pytest.raises(eph.EphemeralSpawnFailed):
        eph.spawn_ephemeral_llm("7", "t-cap-eph", "demo", {})
    assert (tmp_path / "agent7.log.1").read_bytes() == b"old\n" * 300
    assert not (tmp_path / "agent7.log.2").exists()
    rows = log.read_text(encoding="utf-8").splitlines()
    assert [r.split()[1] for r in rows] == ["SPAWN", "REFUSED"]
    assert all("task=t-cap-eph" in r for r in rows)


_CALLERS = ("agents/supervisor.py", "agents/_supervisor_ephemeral.py")


def _direct_agent_log_appends(src: str) -> list[int]:
    """Lines where an ``agent<N>.log`` path is opened directly for append.

    The agent-log path is bound to a local named ``log_path`` in both callers
    (``log_path = LOG_ROOT / f"agent{...}.log"``); any ``log_path.open(...)`` or
    ``open(log_path, ...)`` bypasses the cap."""
    found = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        method_open = isinstance(fn, ast.Attribute) and fn.attr == "open" \
            and isinstance(fn.value, ast.Name) and fn.value.id == "log_path"
        builtin_open = isinstance(fn, ast.Name) and fn.id == "open" and bool(node.args) \
            and isinstance(node.args[0], ast.Name) and node.args[0].id == "log_path"
        if method_open or builtin_open:
            found.append(node.lineno)
    return found


def test_scan_positive_control():
    src = (
        'log_path = LOG_ROOT / f"agent{a}.log"\n'
        'with log_path.open("a") as f:\n    f.write("x")\n'
        'with open(log_path, "a") as f:\n    f.write("x")\n'
    )
    assert _direct_agent_log_appends(src) == [2, 4]


@pytest.mark.parametrize("rel", _CALLERS)
def test_no_caller_appends_an_agent_log_around_the_cap(rel):
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert 'f"agent{' in src, f"{rel}: the agent-log path moved - the scan would be vacuous"
    assert _direct_agent_log_appends(src) == [], (
        f"{rel}: an agent<N>.log append bypasses append_agent_log (S144-Q-123)")
    assert "append_agent_log(" in src
