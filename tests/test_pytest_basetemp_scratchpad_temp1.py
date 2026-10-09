"""Guard: no pytest ``--basetemp`` inside a Claude session scratchpad (MAIN FIX TEMP-1).

MAIN measured 2026-10-09 that long-lived RC sessions ran pytest with
``--basetemp`` pointed INSIDE the session scratchpad, one scratchpad reaching
8.5k entries. pytest's own retention (``tmp_path_retention_policy`` /
``tmp_path_retention_count`` in ``pytest.ini``) does not apply to an explicit
basetemp that changes per run, and MAIN's scratchpad cleaner protects a live
session, so every copy stayed. Temp file count is boot time on this box.

The rule (CLAUDE.md, RC tree-specific section): use the default tmp_path. If a
run truly needs an explicit basetemp, use the ONE fixed path
``<scratchpad>/pytest-basetemp`` (pytest clears it at the start of each run),
so no scratchpad ever holds more than one basetemp.

Enforced by ``tests/_basetemp_guard.py``, whose ``pytest_configure`` the
rootdir ``conftest.py`` re-exports so it reaches BOTH suites. This file pins
the classifier, the re-export and the real behaviour (a subprocess pytest is
refused with a usage error before any basetemp directory is created).
"""

from __future__ import annotations

import ast
import configparser
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests import _basetemp_guard as guard  # noqa: E402


def _scratchpad(root: Path) -> Path:
    return root / "Temp" / "claude" / "E--Proj" / "0000-session" / "scratchpad"


# ---- classifier -------------------------------------------------------------

def test_no_basetemp_is_allowed():
    assert guard.basetemp_problem(None) is None
    assert guard.basetemp_problem("") is None


def test_basetemp_outside_any_scratchpad_is_allowed(tmp_path):
    assert guard.basetemp_problem(str(tmp_path / "bt")) is None


def test_ad_hoc_basetemp_inside_scratchpad_is_refused(tmp_path):
    sp = _scratchpad(tmp_path)
    for name in ("bt1", "verify-s1/green", "pytest-basetemp-2", "basetemp"):
        problem = guard.basetemp_problem(str(sp / name))
        assert problem is not None, name
        assert "pytest-basetemp" in problem
        assert "TEMP-1" in problem


def test_the_scratchpad_itself_is_refused(tmp_path):
    assert guard.basetemp_problem(str(_scratchpad(tmp_path))) is not None


def test_the_one_fixed_path_and_its_xdist_children_are_allowed(tmp_path):
    fixed = _scratchpad(tmp_path) / guard.FIXED_NAME
    assert guard.FIXED_NAME == "pytest-basetemp"
    assert guard.basetemp_problem(str(fixed)) is None
    assert guard.basetemp_problem(str(fixed / "popen-gw0")) is None


def test_scratchpad_match_is_case_insensitive(tmp_path):
    sp = tmp_path / "TEMP" / "Claude" / "E--Proj" / "s" / "ScratchPad"
    assert guard.basetemp_problem(str(sp / "bt1")) is not None
    assert guard.basetemp_problem(str(sp / "PYTEST-BASETEMP")) is None


def test_a_dir_merely_named_scratchpad_outside_claude_temp_is_allowed(tmp_path):
    # Only the harness layout <..>/claude/<project>/<session>/scratchpad counts.
    assert guard.basetemp_problem(str(tmp_path / "scratchpad" / "bt1")) is None


# ---- wiring -----------------------------------------------------------------

def test_rootdir_conftest_reexports_the_guard_hook():
    tree = ast.parse((REPO / "conftest.py").read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tests._basetemp_guard":
            if any(a.name == "pytest_configure" and a.asname in (None, "pytest_configure")
                   for a in node.names):
                found = True
    assert found, "conftest.py must `from tests._basetemp_guard import pytest_configure`"


def test_pytest_ini_keeps_failed_only_retention_of_one():
    cp = configparser.ConfigParser()
    cp.read(REPO / "pytest.ini", encoding="utf-8")
    assert cp.get("pytest", "tmp_path_retention_policy").strip() == "failed"
    assert cp.get("pytest", "tmp_path_retention_count").strip() == "1"


# ---- behaviour (real pytest, subprocess) --------------------------------------

_PROBE = "def test_ok():\n    assert True\n"


def _run(tmp_path: Path, basetemp: Path):
    probe = tmp_path / "probe"
    probe.mkdir(exist_ok=True)
    (probe / "test_probe_basetemp.py").write_text(_PROBE, encoding="ascii")
    (probe / "pytest.ini").write_text("[pytest]\n", encoding="ascii")
    env = dict(os.environ)
    for k in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_CURRENT_TEST"):
        env.pop(k, None)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", "tests._basetemp_guard", "--rootdir", str(probe),
         "-c", str(probe / "pytest.ini"), "--basetemp", str(basetemp),
         str(probe / "test_probe_basetemp.py")],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=120,
        **kwargs,
    )


def test_subprocess_pytest_refuses_ad_hoc_scratchpad_basetemp(tmp_path):
    bad = _scratchpad(tmp_path) / "bt7"
    r = _run(tmp_path, bad)
    out = r.stdout + r.stderr
    assert r.returncode == 4, out
    assert "TEMP-1" in out
    assert not bad.exists(), "the refused basetemp must never be created"


def test_subprocess_pytest_accepts_the_fixed_scratchpad_basetemp(tmp_path):
    good = _scratchpad(tmp_path) / guard.FIXED_NAME
    r = _run(tmp_path, good)
    assert r.returncode == 0, r.stdout + r.stderr
