"""RM-812 - tests must not write the live logs / dbs of the checkout they run in.

MEASURED 2026-10-23 (session 129) in a git worktree, where no daemon writes, by
a before/after digest of the WHOLE checkout around ONE test file, so every
change attributes to that file:

  tests/test_agent_relay_audit.py
      a child `import tools.liveclient_relay` -> logs/liveclient_relay.log
      (the import-time FileHandler, tools/liveclient_relay.py `_LOG_FILE`).
  tests/test_api_key_single_lookup_env_apikey.py
      a child `import vision_server._config` -> <repo>/moon_vision_server.log,
      287 bytes (the import-time basicConfig FileHandler); the same import
      in-process opened it at 0 bytes, because the file sits OUTSIDE logs/ and
      the conftest FileHandler redirect let it through;
      in-process `performance_tracker.save_rating` -> `coaches.feedback
      .apply_grade` -> `CacheEngine(<repo>/data/decisions.db)` (5 tests, the
      `performance_tracker.save_rating` consumer row).
  tests/test_p2w1_app_a.py
      in-process `vision_server._config` -> moon_vision_server.log, 0 bytes.
  tests/test_supervisor_ephemeral_auth_env.py, tests/test_headless_route_spawn_paths.py
      in-process `spawn_ephemeral_llm` -> logs/agents/agent<N>.log and
      task-<id>.log, plain file I/O on `_supervisor_ephemeral.LOG_ROOT`, which
      is bound from `_supervisor_common` at import (no tmp seam at all).
  agents/agent3_testing/suite/test_supervisor.py
      the supervisor child -> logs/ws/{ingest,push}.log and
      logs/agents/supervisor.log (pinned in that file).

Each writer now takes its location from an environment variable the suite
points at tmp: RC_LIVECLIENT_RELAY_LOG, RC_VISION_SERVER_LOG and RC_DECISIONS_DB
ride the kit test guard's ENV_ROOTS (per test, children inherit - the RM-776 /
RM-788 shape); RC_PHASE3_LOG_DIR is set by tests/conftest.py at IMPORT, because
`LOG_ROOT` is bound when `agents._supervisor_common` is first imported, which
is during collection. The assertions below are POSITIVE (the write landed in
tmp) rather than a stat of the live file: on Legion the live relay, vision
server, coach and supervisor write those same files, so a live-file stat would
blame a test for a daemon's line (the RM-148 trap).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests import _fleet_guard_config
from tests import conftest as rc_conftest

REPO = Path(__file__).resolve().parents[1]
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

RM812_ENV_ROOTS = {
    "RC_LIVECLIENT_RELAY_LOG": "liveclient_relay.log",
    "RC_VISION_SERVER_LOG": "moon_vision_server.log",
    "RC_DECISIONS_DB": "decisions.db",
}


def _child(code: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run ``code`` in a fresh interpreter with THIS test's environment, so the
    kit's per-test ENV_ROOTS values are what the child inherits."""
    return subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, r'{REPO}');\n" + code],
        cwd=str(cwd), env=dict(os.environ), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120, creationflags=_FLAGS)


def _last_line(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode == 0, f"child failed rc={proc.returncode}:\n{proc.stderr[-1500:]}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"child printed nothing:\n{proc.stderr[-1500:]}"
    return lines[-1].strip()


# ---------------------------------------------------------------------------
# The suite wiring.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("var", sorted(RM812_ENV_ROOTS))
def test_the_kit_guard_points_each_rm812_root_at_tmp_path(var, tmp_path):
    assert _fleet_guard_config.ENV_ROOTS.get(var) == RM812_ENV_ROOTS[var], var
    value = os.environ.get(var)
    assert value == str(tmp_path / RM812_ENV_ROOTS[var]), var


def test_the_conftest_moves_the_supervisor_log_root_at_import():
    value = (os.environ.get("RC_PHASE3_LOG_DIR") or "").strip()
    assert value, "tests/conftest.py did not set RC_PHASE3_LOG_DIR at import"
    assert not Path(value).resolve().is_relative_to(REPO), value
    from agents import _supervisor_common as common
    from agents import _supervisor_ephemeral as eph
    from agents import supervisor as sup
    for mod in (common, eph, sup):
        assert not Path(mod.LOG_ROOT).resolve().is_relative_to(REPO), (
            f"{mod.__name__}.LOG_ROOT is the live tree: {mod.LOG_ROOT}")


# ---------------------------------------------------------------------------
# tools/liveclient_relay.py
# ---------------------------------------------------------------------------

def test_relay_log_file_honours_the_env_then_falls_back(monkeypatch, tmp_path):
    import tools.liveclient_relay as relay
    assert relay.LOG_FILE_ENV == "RC_LIVECLIENT_RELAY_LOG"
    default = REPO / "logs" / "liveclient_relay.log"
    assert relay._DEFAULT_LOG_FILE == default
    monkeypatch.setenv(relay.LOG_FILE_ENV, str(tmp_path / "relay.log"))
    assert relay._log_file() == tmp_path / "relay.log"
    for blank in ("", "   "):
        monkeypatch.setenv(relay.LOG_FILE_ENV, blank)
        assert relay._log_file() == default
    monkeypatch.delenv(relay.LOG_FILE_ENV, raising=False)
    assert relay._log_file() == default


def test_a_relay_child_logs_into_the_redirect_not_the_live_log(tmp_path):
    marker = f"rm812-relay-{uuid.uuid4().hex}"
    out = _child(
        "import logging\n"
        "import tools.liveclient_relay as r\n"
        f"r.log.info('{marker}')\n"
        "logging.shutdown()\n"
        "print(r._LOG_FILE)\n",
        cwd=tmp_path)
    written = Path(_last_line(out))
    assert written == tmp_path / RM812_ENV_ROOTS["RC_LIVECLIENT_RELAY_LOG"], written
    assert written != REPO / "logs" / "liveclient_relay.log"
    assert marker in written.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# vision_server/_config.py
# ---------------------------------------------------------------------------

def test_a_vision_config_child_logs_into_the_redirect_not_the_repo_root(tmp_path):
    # cwd=tmp_path: the module also mkdirs a CWD-relative moon_sync_inbox/.
    marker = f"rm812-vision-{uuid.uuid4().hex}"
    out = _child(
        "import json, logging\n"
        "from vision_server import _config as c\n"
        f"c.log.info('{marker}')\n"
        "files = [h.baseFilename for h in logging.getLogger().handlers\n"
        "         if getattr(h, 'baseFilename', None)]\n"
        "logging.shutdown()\n"
        "print(json.dumps([c.LOG_PATH_ENV, str(c._LOG_PATH), files]))\n",
        cwd=tmp_path)
    env_name, default, files = json.loads(_last_line(out))
    assert env_name == "RC_VISION_SERVER_LOG"
    # `_LOG_PATH` stays the anchored DEFAULT (tests/test_p2w1_app_a.py pins it).
    assert Path(default) == REPO / "moon_vision_server.log"
    target = tmp_path / RM812_ENV_ROOTS["RC_VISION_SERVER_LOG"]
    assert [Path(f) for f in files] == [target], files
    assert marker in target.read_text(encoding="utf-8", errors="replace")


def test_an_in_process_handler_on_the_repo_root_vision_log_lands_in_tmp():
    """The env var cannot reach an import made during COLLECTION (no fixture has
    run yet), so the conftest FileHandler redirect covers this one live log
    file outside logs/ as well. delay=True: nothing is opened."""
    live = REPO / "moon_vision_server.log"
    moved = Path(rc_conftest._tmp_log_path(str(live)))
    assert moved != live
    assert moved.resolve().is_relative_to(rc_conftest._SUITE_LOG_DIR.resolve())
    handler = logging.FileHandler(str(live), encoding="utf-8", delay=True)
    try:
        assert Path(handler.baseFilename) != live
        assert Path(handler.baseFilename).resolve().is_relative_to(
            rc_conftest._SUITE_LOG_DIR.resolve())
    finally:
        handler.close()
    # A sibling file at the repo root is NOT swept along.
    other = REPO / "some_other_root_file.log"
    assert rc_conftest._tmp_log_path(str(other)) == str(other)


# ---------------------------------------------------------------------------
# data/decisions.db (modules/cache_engine.py, coaches/feedback.py,
# coach_integration/_coach.py)
# ---------------------------------------------------------------------------

def test_decisions_db_path_honours_the_env_then_falls_back(monkeypatch, tmp_path):
    from modules import cache_engine
    assert cache_engine.DECISIONS_DB_ENV == "RC_DECISIONS_DB"
    default = REPO / "data" / "decisions.db"
    monkeypatch.setenv(cache_engine.DECISIONS_DB_ENV, str(tmp_path / "x.db"))
    assert cache_engine.decisions_db_path() == tmp_path / "x.db"
    for blank in ("", "   "):
        monkeypatch.setenv(cache_engine.DECISIONS_DB_ENV, blank)
        assert cache_engine.decisions_db_path() == default
    monkeypatch.delenv(cache_engine.DECISIONS_DB_ENV, raising=False)
    assert cache_engine.decisions_db_path() == default


def test_apply_grade_default_cache_lands_in_the_redirect(tmp_path):
    from coaches import feedback
    state = {"my_champion": "Ahri", "game_time_s": 900, "patch_version": "x"}
    assert feedback.apply_grade("A", state) is True
    assert (tmp_path / RM812_ENV_ROOTS["RC_DECISIONS_DB"]).is_file()


def test_save_rating_feedback_cache_lands_in_the_redirect(monkeypatch, tmp_path):
    """The measured route: save_rating -> apply_grade(grade, game_state)."""
    import coaches.experimental_builder as eb
    import performance_tracker as pt
    from modules import cache_engine

    opened: list = []
    real = cache_engine.CacheEngine

    def _spy(db_path, *a, **kw):
        opened.append(Path(db_path))
        return real(db_path, *a, **kw)

    monkeypatch.setattr(cache_engine, "CacheEngine", _spy)
    monkeypatch.setattr(eb, "consume_active", lambda: None)
    monkeypatch.setattr(pt, "_match_db", None)
    pt.save_rating(str(tmp_path / "root"), "Ahri", {
        "game_mode": "CLASSIC", "game_seconds": 1200,
        "cs_per_min": 6.0, "deaths": 3, "kills": 5,
        "assists": 7, "gold": 12000, "kda": "5/3/7",
    }, 10)
    assert opened == [tmp_path / RM812_ENV_ROOTS["RC_DECISIONS_DB"]], opened


def test_coach_integration_builds_its_cache_on_the_redirect(monkeypatch, tmp_path):
    from modules import cache_engine
    from coach_integration._coach import CoachIntegration

    opened: list = []
    monkeypatch.setattr(cache_engine, "CacheEngine",
                        lambda db_path, *a, **kw: opened.append(Path(db_path)) or object())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    CoachIntegration(tmp_path / "sr_coaching_data.json")
    assert opened == [tmp_path / RM812_ENV_ROOTS["RC_DECISIONS_DB"]], opened


# ---------------------------------------------------------------------------
# agents/_supervisor_common.py LOG_ROOT (logs/agents)
# ---------------------------------------------------------------------------

def test_supervisor_log_root_honours_the_env_then_falls_back(tmp_path):
    from agents import _supervisor_common as common
    assert common.LOG_DIR_ENV == "RC_PHASE3_LOG_DIR"
    default = REPO / "logs" / "agents"
    assert common._resolve_log_root({common.LOG_DIR_ENV: str(tmp_path)}) == tmp_path
    for env in ({}, {common.LOG_DIR_ENV: ""}, {common.LOG_DIR_ENV: "   "}):
        assert common._resolve_log_root(env) == default, env


def test_an_ephemeral_spawn_writes_its_logs_under_the_suite_root(monkeypatch):
    """The measured in-process route (test_supervisor_ephemeral_auth_env et al.):
    spawn_ephemeral_llm appends agent<N>.log and task-<id>.log by plain I/O."""
    from agents import _supervisor_ephemeral as eph
    from agents.supervisor import spawn_ephemeral_llm
    from ops.loop import fleet_route
    from tests._module_view import bind_subprocess

    def _fake_run(cmd, **kw):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="{}", stderr="")

    task_id = f"t-rm812-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(eph.shutil, "which", lambda name: "/fake/claude")
    for mod in (eph, sys.modules["agents.supervisor"], fleet_route, fleet_route.kit()):
        bind_subprocess(monkeypatch, mod, run=_fake_run)
    # Agent 7 has a real charter and writes no failure stub (as in
    # tests/test_supervisor_ephemeral_auth_env.py).
    spawn_ephemeral_llm("7", task_id, "demo", {})
    task_log = Path(eph.LOG_ROOT) / f"task-{task_id}.log"
    assert task_log.is_file(), task_log
    assert not task_log.resolve().is_relative_to(REPO), task_log
    assert not (REPO / "logs" / "agents" / f"task-{task_id}.log").exists()


# ---------------------------------------------------------------------------
# Sibling sweep, same session: a whole-checkout digest around the touched test
# files found two more default-path writers on the RM-406 mechanism's blind
# side - a module global read at CALL time that conftest's _PROD_PATH_GLOBALS
# did not carry:
#   tests/phase2_smoke/test_sr_aram_worker.py::TestSrAramWorkerContract::
#       test_worker_sr_coaching_gate_disabled -> core/sr_aram_worker.py
#       _submit_coaching -> core.feature_policy.write_disabled_placeholder("sr")
#       -> _SR_ARTIFACT = <repo>/coaching_data.json, the LIVE SR coach output
#       (its sibling _DATA_DIR was already redirected).
#   tests/test_p2w1_app_b.py::test_try_fetch_timeline_* ->
#       lcu/lcu_postgame_collector._save_raw_document -> _get_conn() ->
#       _DB_PATH = <repo>/data/postgame_stats.db.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mod_name, attr", [
    ("core.feature_policy", "_SR_ARTIFACT"),
    ("lcu.lcu_postgame_collector", "_DB_PATH"),
])
def test_sweep_found_default_path_writers_are_redirected(mod_name, attr):
    import importlib

    rows = {(m, a) for m, a, _leaf, _is_dir in rc_conftest._PROD_PATH_GLOBALS}
    assert (mod_name, attr) in rows, f"{mod_name}.{attr} is not redirected"
    current = Path(getattr(importlib.import_module(mod_name), attr))
    assert not current.resolve().is_relative_to(REPO), current
