"""RM-828 - RM-812 residuals: the live coaching-data lock, the suite temp dirs.

(a) `core/coaching_data_lock.py` fixes `_LOCK_FILE` at IMPORT to the live
    `ops/runtime/coaching_data.lock` and reads it at CALL time, so every test
    that reached `coaching_data_lock()` through a production writer (for
    example `tests/test_p2w1_app_b.py` `test_reset_state_holds_coaching_data_lock`
    via `CoachIntegration.reset_state`, and `tests/test_rm277_app_write_data_lock.py`)
    opened the live lock file and contended with the live app's coaching writes.
    `tests/conftest.py` `_PROD_PATH_GLOBALS` now moves it to tmp. The assertion
    is POSITIVE (the lock file the call opened is the tmp one), not a stat of
    the live file: on Legion the live app opens that same file (RM-148).
(d) `tests/conftest.py` `mkdtemp(prefix="rc-suite-logs-")` and the agent3 suite
    conftest `mkdtemp(prefix="rc-agent3-agent-logs-")` were never removed
    (1271 `rc-suite-logs-*` dirs measured in %TEMP% on 2026-10-27). Each is now
    removed when the interpreter that created it exits, even with a log
    handler still open on a file inside it.
(e) the agent3 conftest said a combined run "keeps whichever tmp dir was set
    first"; `tests/conftest.py` sets `RC_PHASE3_LOG_DIR` unconditionally, so
    the comment now says what happens, and the test below pins that behaviour.

The temp-dir tests run the conftest in a CHILD interpreter, because the cleanup
fires at interpreter exit and the parent's own dir must outlive this test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENT3_CONFTEST = REPO / "agents" / "agent3_testing" / "suite" / "conftest.py"
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

_IMPORT_AGENT3 = (
    "import importlib.util as u\n"
    f"s = u.spec_from_file_location('rm828_agent3_conftest', r'{AGENT3_CONFTEST}')\n"
    "m = u.module_from_spec(s); s.loader.exec_module(m)\n"
)


def _child(code: str, env: dict) -> list:
    proc = subprocess.run(
        [sys.executable, "-c", f"import sys, os, json; sys.path.insert(0, r'{REPO}')\n" + code],
        cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, creationflags=_FLAGS)
    assert proc.returncode == 0, f"child failed rc={proc.returncode}:\n{proc.stderr[-1500:]}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"child printed nothing:\n{proc.stderr[-1500:]}"
    return json.loads(lines[-1])


# ---------------------------------------------------------------------------
# (a) the coaching-data lock file


def test_the_coaching_data_lock_opens_a_tmp_file_not_the_live_one(tmp_path_factory):
    import core.coaching_data_lock as cdl

    live = REPO / "ops" / "runtime" / "coaching_data.lock"
    lock_file = Path(cdl._LOCK_FILE)
    assert lock_file.resolve() != live.resolve()
    assert lock_file.resolve().is_relative_to(tmp_path_factory.getbasetemp().resolve())
    # The redirect dir is shared per worker, so clear the file first: its
    # presence after the call is then this call's own write.
    lock_file.unlink(missing_ok=True)
    with cdl.coaching_data_lock():
        assert lock_file.is_file()


def test_reset_state_takes_the_lock_on_the_tmp_file(tmp_path, tmp_path_factory):
    """The `test_reset_state_holds_coaching_data_lock` path: a production
    writer reaches the module lock by default, with no explicit path."""
    import core.coaching_data_lock as cdl
    from coach_integration._coach import CoachIntegration

    lock_file = Path(cdl._LOCK_FILE)
    assert lock_file.resolve().is_relative_to(tmp_path_factory.getbasetemp().resolve())
    lock_file.unlink(missing_ok=True)
    c = CoachIntegration.__new__(CoachIntegration)
    c.data_file = tmp_path / "coaching_data.json"
    c.reset_state()
    assert c.data_file.is_file()
    assert lock_file.is_file()


# ---------------------------------------------------------------------------
# (d) the suite temp dirs


def test_the_suite_log_dir_is_removed_when_its_process_exits():
    # A handler is left OPEN on a redirected live log inside the dir, as the
    # import-time FileHandlers of the tools under test leave theirs.
    code = (
        "import logging\n"
        "import tests.conftest as c\n"
        "h = logging.FileHandler(str(c._REAL_LOG_DIR / 'rm828_probe.log'), encoding='utf-8')\n"
        "lg = logging.getLogger('rm828.probe'); lg.addHandler(h); lg.warning('probe')\n"
        "print(json.dumps([str(c._SUITE_LOG_DIR), c._SUITE_LOG_DIR.is_dir(),\n"
        "                  h.baseFilename, os.path.isfile(h.baseFilename)]))\n"
    )
    d, existed, log_file, log_existed = _child(code, dict(os.environ))
    # Positive control: the dir and the redirected log were real while it ran.
    assert existed and log_existed
    assert Path(log_file).resolve().is_relative_to(Path(d).resolve())
    assert Path(d).name.startswith("rc-suite-logs-")
    assert not Path(d).exists(), f"{d} outlived its process"


def test_the_agent3_log_dir_is_removed_when_its_process_exits():
    env = dict(os.environ, RC_PHASE3_LOG_DIR="")
    d, existed = _child(_IMPORT_AGENT3 + (
        "d = os.environ['RC_PHASE3_LOG_DIR']\n"
        "print(json.dumps([d, os.path.isdir(d)]))\n"), env)
    assert existed
    assert Path(d).name.startswith("rc-agent3-agent-logs-")
    assert not Path(d).exists(), f"{d} outlived its process"


def test_pytest_unconfigure_removes_both_dirs_without_atexit():
    """The session path on its own: the child leaves through `os._exit`, so no
    atexit hook runs and only `pytest_unconfigure` can have removed the dirs."""
    env = dict(os.environ, RC_PHASE3_LOG_DIR="")
    code = _IMPORT_AGENT3 + (
        "import tests.conftest as c\n"
        "a = m._CREATED_LOG_DIR\n"
        "before = [os.path.isdir(a), c._SUITE_LOG_DIR.is_dir()]\n"
        "m.pytest_unconfigure(None); c.pytest_unconfigure(None)\n"
        "print(json.dumps(before + [os.path.isdir(a), c._SUITE_LOG_DIR.is_dir()]), flush=True)\n"
        "os._exit(0)\n")
    # Read the result first: an assert over the call would render `env`.
    flags = _child(code, env)
    assert flags == [True, True, False, False]


def test_the_agent3_conftest_never_removes_a_dir_it_did_not_create(tmp_path):
    preset = tmp_path / "preset_phase3"
    preset.mkdir()
    (preset / "keep.txt").write_bytes(b"x")
    env = dict(os.environ, RC_PHASE3_LOG_DIR=str(preset))
    (d,) = _child(_IMPORT_AGENT3 + (
        "m.pytest_unconfigure(None)\n"
        "print(json.dumps([os.environ['RC_PHASE3_LOG_DIR']]))\n"), env)
    assert Path(d) == preset
    assert (preset / "keep.txt").is_file()


# ---------------------------------------------------------------------------
# (e) the combined-run comment


def test_a_combined_run_ends_on_the_tests_dir_and_removes_both():
    env = dict(os.environ, RC_PHASE3_LOG_DIR="")
    agent3_dir, tests_suite_dir, final = _child(_IMPORT_AGENT3 + (
        "a = os.environ['RC_PHASE3_LOG_DIR']\n"
        "import tests.conftest as c\n"
        "print(json.dumps([a, str(c._SUITE_LOG_DIR), os.environ['RC_PHASE3_LOG_DIR']]))\n"), env)
    # tests/conftest.py sets it unconditionally, so it wins even when the
    # agent3 conftest ran first.
    assert Path(final) == Path(tests_suite_dir) / "agents"
    assert Path(final) != Path(agent3_dir)
    assert not Path(agent3_dir).exists()
    assert not Path(tests_suite_dir).exists()
    text = AGENT3_CONFTEST.read_text(encoding="utf-8")
    assert "keeps whichever tmp dir was set first" not in text
    assert "tests/conftest.py sets it unconditionally" in text
