"""RM-909 follow-up (d) - importing agents/_supervisor_common.py must not
configure the shared "rc" logger.

MEASURED 2026-10-27 (s144 queue cycle 17), a fresh interpreter with
RC_PHASE3_LOG_DIR pointed at a temp dir:

  before `import agents._supervisor_common`: rc.handlers == [], rc.level == 0
  after:  rc.handlers == [RotatingFileHandler(<tmp>/supervisor.log),
                          StreamHandler(<stderr>)], rc.level == 20 (INFO)

The module ran `log = _build_logger()` at IMPORT, and `_build_logger` also
teed the "rc" logger - the parent of every RC module's logger - into the
supervisor's handlers and pinned its level at INFO. That tee exists for ONE
process: the Phase 3 supervisor (`python -m agents.supervisor`), where
decision_detector / liveclient_cache run in-process and their `rc.*` records
belong in supervisor.log. Any other importer (about 40 test modules import it
during collection) got every `rc.*` record of the whole worker duplicated to
the sys.stderr object bound at import time, and an `rc.*` DEBUG record dropped
at the "rc" level, so a caplog assertion on one depended on whether some
earlier test file had imported the supervisor.

The tee now lives in `_install_rc_log_tee()`, called by `agents.supervisor
.main()` before the event loop starts, so the supervisor process behaves as
before and an import changes nothing on "rc". The "supervisor" logger itself
is still built at import (its own namespace, used only by the supervisor
modules), and tests/conftest.py still moves its file handler to tmp.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

from tests._asyncio_isolation import run_coro

REPO = Path(__file__).resolve().parents[1]
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _child(code: str, log_dir: Path) -> dict:
    """Run ``code`` in a fresh interpreter whose supervisor log root is
    ``log_dir``; it prints one JSON line, returned parsed."""
    env = dict(os.environ)
    env["RC_PHASE3_LOG_DIR"] = str(log_dir)
    proc = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, r'{REPO}');\n" + code],
        cwd=str(log_dir), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120, creationflags=_FLAGS)
    assert proc.returncode == 0, f"child failed rc={proc.returncode}:\n{proc.stderr[-1500:]}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"child printed nothing:\n{proc.stderr[-1500:]}"
    return json.loads(lines[-1])


def test_importing_the_common_module_leaves_the_rc_logger_alone(tmp_path):
    got = _child(
        "import json, logging\n"
        "rc = logging.getLogger('rc')\n"
        "before = (len(rc.handlers), rc.level)\n"
        "import agents._supervisor_common as c\n"
        "print(json.dumps({'before': before,\n"
        "                  'rc_handlers': [type(h).__name__ for h in rc.handlers],\n"
        "                  'rc_level': rc.level,\n"
        "                  'sup_handlers': len(c.log.handlers)}))\n",
        tmp_path)
    assert got["before"] == [0, logging.NOTSET], got
    assert got["rc_handlers"] == [], got
    assert got["rc_level"] == logging.NOTSET, got
    # The supervisor's own logger is still built at import (file + stderr).
    assert got["sup_handlers"] == 2, got


def test_the_installer_tees_rc_into_the_supervisor_handlers_once(tmp_path):
    marker = f"rm909d-{uuid.uuid4().hex}"
    got = _child(
        "import json, logging\n"
        "import agents._supervisor_common as c\n"
        "c._install_rc_log_tee()\n"
        "c._install_rc_log_tee()\n"
        "rc = logging.getLogger('rc')\n"
        f"logging.getLogger('rc.decision_detector').info('{marker}')\n"
        "out = {'n': len(rc.handlers),\n"
        "       'shared': [h in c.log.handlers for h in rc.handlers],\n"
        "       'level': rc.level}\n"
        "logging.shutdown()\n"
        "print(json.dumps(out))\n",
        tmp_path)
    # Same handler INSTANCES as the supervisor logger, attached once even
    # when the installer runs twice.
    assert got["n"] == 2, got
    assert got["shared"] == [True, True], got
    assert got["level"] == logging.INFO, got
    text = (tmp_path / "supervisor.log").read_text(encoding="utf-8")
    assert marker in text


def test_the_installer_keeps_an_rc_logger_someone_else_configured(tmp_path):
    got = _child(
        "import json, logging\n"
        "rc = logging.getLogger('rc')\n"
        "own = logging.NullHandler()\n"
        "rc.addHandler(own)\n"
        "rc.setLevel(logging.DEBUG)\n"
        "import agents._supervisor_common as c\n"
        "c._install_rc_log_tee()\n"
        "print(json.dumps({'own_only': rc.handlers == [own], 'level': rc.level}))\n",
        tmp_path)
    assert got == {"own_only": True, "level": logging.DEBUG}, got


def test_main_installs_the_tee_before_the_event_loop_runs(monkeypatch):
    from agents import supervisor as sup

    order: list[str] = []

    async def _fake_run() -> int:
        order.append("run")
        return 0

    monkeypatch.setattr(sup, "_install_rc_log_tee", lambda: order.append("tee"))
    monkeypatch.setattr(sup, "_run", _fake_run)
    # main() calls asyncio.run(), which raises on the main thread after any
    # snapshot_panels test in the same worker (the Playwright running-loop
    # marker, tests/_asyncio_isolation.py), so main() runs on an executor
    # thread of a fresh loop; its result and any exception come back here.
    assert run_coro(asyncio.to_thread(sup.main)) == 0
    assert order == ["tee", "run"]


def test_this_process_rc_logger_carries_no_supervisor_handler():
    """The in-suite consequence: whatever test file imported the supervisor
    first, the worker's "rc" logger holds none of its handlers."""
    import agents._supervisor_common as c

    rc = logging.getLogger("rc")
    assert not [h for h in rc.handlers if h in c.log.handlers]
    assert not [h for h in rc.handlers
                if type(h) is logging.StreamHandler
                and getattr(h, "stream", None) in (sys.stderr, sys.__stderr__)]
