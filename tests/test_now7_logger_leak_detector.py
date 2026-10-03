"""NOW-7: the logger-leak detector and its ARMED gate.

Report mode (RC_LOGGER_LEAK_REPORT=1) records a planted leak, records nothing
for a clean test, and is inert when disarmed. Armed mode (the default) turns a
planted leak RED at the leaker, keeps a class-scoped set/restore GREEN, drops
a created logger's own level, attributes a setup-phase leak to its owner at
the module boundary, and is inert in a nested child pytest.

The unit half drives snapshot/diff/record/classify directly. The end-to-end
half runs a throwaway pytest in a SUBPROCESS with the detector loaded via
``-p``, because the in-process hooks are already registered on this very run
and would observe themselves. The child env drops the outer-run stamps, or the
child would correctly classify itself as nested and do nothing.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests import _logger_leak_report as llr

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _fresh_logger(name):
    lg = logging.getLogger(name)
    lg.propagate = True
    lg.setLevel(logging.NOTSET)
    lg.disabled = False
    for h in list(lg.handlers):
        lg.removeHandler(h)
    return lg


def test_planted_leak_is_recorded(tmp_path):
    lg = _fresh_logger("now7.planted")
    handler = logging.NullHandler()
    before = llr.snapshot()
    try:
        lg.propagate = False
        lg.setLevel(logging.INFO)
        lg.addHandler(handler)
        rows = llr.diff(before, llr.snapshot())
    finally:
        _fresh_logger("now7.planted")
    mine = {(r[0], r[1]) for r in rows if r[0] == "now7.planted"}
    assert mine == {("now7.planted", "propagate"), ("now7.planted", "level"),
                    ("now7.planted", "handlers")}
    out = tmp_path / "r.jsonl"
    assert llr.record("t::x", [r for r in rows if r[0] == "now7.planted"], out) == 3
    parsed = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    prop = next(p for p in parsed if p["attribute"] == "propagate")
    assert prop == {"nodeid": "t::x", "logger": "now7.planted", "attribute": "propagate",
                    "before": True, "after": False, "created": False}


def test_clean_mutate_and_restore_records_nothing(tmp_path):
    lg = _fresh_logger("now7.clean")
    before = llr.snapshot()
    lg.propagate = False
    lg.propagate = True
    rows = [r for r in llr.diff(before, llr.snapshot()) if r[0].startswith("now7.")]
    assert rows == []
    out = tmp_path / "r.jsonl"
    assert llr.record("t::y", rows, out) == 0
    assert not out.exists()


def test_new_logger_with_default_state_is_not_a_leak():
    before = llr.snapshot()
    logging.getLogger("now7.brand_new_default_logger_zz")
    rows = [r for r in llr.diff(before, llr.snapshot()) if r[0].startswith("now7.brand_new")]
    assert rows == []


def test_new_logger_with_cut_propagation_is_a_leak():
    before = llr.snapshot()
    lg = logging.getLogger("now7.brand_new_cut_logger_zz")
    try:
        lg.propagate = False
        rows = [r for r in llr.leak_rows(before, llr.snapshot()) if r[0].startswith("now7.brand_new")]
    finally:
        lg.propagate = True
    assert rows == [("now7.brand_new_cut_logger_zz", "propagate", True, False, True)]


def test_import_owned_changes_are_dropped_only_while_unchanged():
    before = llr.snapshot()
    mine = "now7.brand_new_pil_like_zz"
    lg = logging.getLogger(mine)
    h = logging.NullHandler()
    try:
        lg.setLevel(logging.WARNING)
        lg.addHandler(h)
        after = llr.snapshot()
        owned = {(mine, "level"): logging.WARNING, (mine, "handlers"): (h,)}
        raw = [r for r in llr.diff(before, after) if r[0] == mine]
        by_import = [r for r in llr.leak_rows(before, after, owned) if r[0] == mine]
        by_test = [r for r in llr.leak_rows(before, after) if r[0] == mine]
        lg.setLevel(logging.DEBUG)  # a test changes it AFTER the import
        later = [r for r in llr.leak_rows(before, llr.snapshot(), owned) if r[0] == mine]
    finally:
        lg.removeHandler(h)
        lg.setLevel(logging.NOTSET)
    assert {r[1] for r in raw} == {"level", "handlers"}
    assert by_import == []
    assert {r[1] for r in by_test} == {"level", "handlers"}
    assert [r[1] for r in later] == ["level"]


def test_import_watch_brackets_a_module_imported_during_a_test(tmp_path, monkeypatch):
    # This test is itself running under the in-process gate, so the watcher
    # is live right now (a test is in progress).
    if not llr._active():
        pytest.skip("detector disarmed for this run (RC_LOGGER_LEAK_GATE=0)")
    assert any(isinstance(f, llr._ImportWatch) for f in sys.meta_path)
    modname = "now7_import_watch_probe_zz"
    (tmp_path / f"{modname}.py").write_text(
        "import logging\nlogging.getLogger('now7.import_probe').setLevel(logging.ERROR)\n",
        encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    lg = logging.getLogger("now7.import_probe")
    try:
        mod = __import__(modname)
        assert llr._IMPORT_OWNED.get(("now7.import_probe", "level")) == logging.ERROR
        # the real loader is put back once the module has executed
        assert not isinstance(mod.__loader__, llr._BracketLoader)
        assert not isinstance(mod.__spec__.loader, llr._BracketLoader)
    finally:
        sys.modules.pop(modname, None)
        lg.setLevel(logging.NOTSET)


def test_pytest_capture_handlers_are_not_snapshotted(caplog):
    root = logging.getLogger()
    assert any(type(h).__module__.startswith("_pytest") for h in root.handlers)
    assert not any(type(h).__module__.startswith("_pytest")
                   for h in llr.snapshot()["<root>"]["handlers"])


def test_flag_parsing():
    assert llr.is_enabled({"RC_LOGGER_LEAK_REPORT": "1"}) is True
    assert llr.is_enabled({}) is False
    assert llr.is_enabled({"RC_LOGGER_LEAK_REPORT": "0"}) is False
    assert llr.is_enabled({"RC_LOGGER_LEAK_REPORT": ""}) is False
    assert llr.gate_armed({}) is True
    assert llr.gate_armed({"RC_LOGGER_LEAK_GATE": "0"}) is False
    assert llr.gate_armed({"RC_LOGGER_LEAK_REPORT": "1"}) is False


def test_classify_process_outer_worker_and_nested():
    # Fake stamp maps (never os.environ); verdicts read into locals first.
    stamps = {}
    first = llr.classify_process(stamps, 100)
    outer_pid = stamps[llr.ENV_OUTER]
    again = llr.classify_process(stamps, 100)
    # a child pytest of the outer run inherits the stamp -> nested, inert
    child = llr.classify_process(dict(stamps), 200)
    # an xdist worker of the outer run stamps itself and stays active ...
    worker_stamps = dict(stamps, PYTEST_XDIST_WORKER="gw0")
    worker = llr.classify_process(worker_stamps, 300)
    worker_pid = worker_stamps[llr.ENV_WORKER]
    # ... and a child pytest spawned by a test on that worker is nested
    worker_child = llr.classify_process(dict(worker_stamps), 400)
    assert (first, outer_pid, again, child) == (True, "100", True, False)
    assert (worker, worker_pid, worker_child) == (True, "300", False)


def test_this_run_is_classified_as_outer():
    # The live suite must not be inert by accident: this process is the outer
    # run or one of its xdist workers.
    assert llr._IS_OUTER is True


_PLANTED = '''
import logging

def test_a_leaker():
    logging.getLogger("now7.e2e.leaker").propagate = False

def test_b_clean():
    lg = logging.getLogger("now7.e2e.clean")
    lg.propagate = False
    lg.propagate = True
'''

_GATE_MAIN = '''
import logging
import unittest

import pytest


def test_a_leaker():
    logging.getLogger("now7.gate.leaker").setLevel(logging.DEBUG)


def test_b_caplog_restores(caplog):
    caplog.set_level(logging.DEBUG, logger="now7.gate.caplog")


def test_c_created_logger_own_level_is_dropped():
    import now7_fakepil  # noqa: F401 - import-time logger at WARNING, like PIL


class ClassScopedRestore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._lg = logging.getLogger("now7.gate.cls")
        cls._prev = cls._lg.level
        cls._lg.setLevel(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        cls._lg.setLevel(cls._prev)

    def test_one(self):
        pass

    def test_two(self):
        pass


@pytest.fixture(scope="class")
def cls_level():
    lg = logging.getLogger("now7.gate.pycls")
    prev = lg.level
    lg.setLevel(logging.ERROR)
    yield
    lg.setLevel(prev)


@pytest.mark.usefixtures("cls_level")
class TestPyClassScoped:
    def test_x(self):
        pass

    def test_y(self):
        pass
'''

_GATE_FIXTURE = '''
import logging

import pytest


@pytest.fixture
def leaky():
    logging.getLogger("now7.gate.fixture").propagate = False
    yield


def test_uses_leaky(leaky):
    pass


def test_after():
    pass
'''


def _child_env(report_dir, **extra):
    env = dict(os.environ)
    for k in (llr.ENV_FLAG, llr.ENV_GATE, llr.ENV_OUTER, llr.ENV_WORKER, "PYTEST_XDIST_WORKER"):
        env.pop(k, None)
    env[llr.ENV_DIR] = str(report_dir)
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env.update(extra)
    return env


def _run(proj, env, *extra_args):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly",
         "-p", "tests._logger_leak_report", "--rootdir", str(proj), *extra_args, str(proj)],
        cwd=str(proj), env=env, capture_output=True, text=True, timeout=120,
        creationflags=flags,
    )


def _rows(report_dir):
    rows = []
    if report_dir.is_dir():
        for f in report_dir.glob("*.jsonl"):
            rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
    return rows


def _run_child(tmp_path, **extra):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "test_planted.py").write_text(_PLANTED, encoding="utf-8")
    report_dir = tmp_path / "report"
    proc = _run(proj, _child_env(report_dir, **extra))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return _rows(report_dir)


def test_end_to_end_report_mode_records_only_the_leaker(tmp_path):
    rows = [r for r in _run_child(tmp_path, RC_LOGGER_LEAK_REPORT="1")
            if r["logger"].startswith("now7.e2e")]
    assert len(rows) == 1
    assert rows[0]["nodeid"].endswith("test_planted.py::test_a_leaker")
    assert rows[0]["logger"] == "now7.e2e.leaker"
    assert rows[0]["attribute"] == "propagate"
    assert rows[0]["kind"] == "call"


def test_end_to_end_inert_when_disarmed(tmp_path):
    assert _run_child(tmp_path, RC_LOGGER_LEAK_GATE="0") == []


def _junit_errors(proj, env):
    xml = proj.parent / "junit.xml"
    proc = _run(proj, env, f"--junitxml={xml}")
    cases = {}
    for tc in ET.parse(xml).getroot().iter("testcase"):
        errs = [e.get("message", "") + (e.text or "") for e in tc.findall("error")]
        errs += [e.get("message", "") + (e.text or "") for e in tc.findall("failure")]
        cases[tc.get("name")] = errs
    return proc, cases


def _gate_project(tmp_path):
    proj = tmp_path / "gate"
    proj.mkdir()
    (proj / "test_gate_main.py").write_text(_GATE_MAIN, encoding="utf-8")
    (proj / "test_gate_fixture.py").write_text(_GATE_FIXTURE, encoding="utf-8")
    (proj / "now7_fakepil.py").write_text(
        "import logging\nlogging.getLogger(__name__).setLevel(logging.WARNING)\n",
        encoding="utf-8")
    return proj


def test_armed_gate_reds_the_leaker_and_keeps_scoped_restores_green(tmp_path):
    proj = _gate_project(tmp_path)
    proc, cases = _junit_errors(proj, _child_env(tmp_path / "report"))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    # RED at the leaker, with the logger and the change named
    assert len(cases["test_a_leaker"]) == 1, out
    assert "now7.gate.leaker.level" in cases["test_a_leaker"][0]
    assert "leaker test_gate_main.py::test_a_leaker" in cases["test_a_leaker"][0]
    # GREEN: caplog, a created logger's own level, unittest + pytest class scope
    for clean in ("test_b_caplog_restores", "test_c_created_logger_own_level_is_dropped",
                  "test_one", "test_two", "test_x", "test_y"):
        assert cases[clean] == [], (clean, out)
    # a setup-phase (fixture) leak is held to the module boundary, then raised
    # there NAMING the fixture's test as the leaker
    assert cases["test_uses_leaky"] == [], out
    assert len(cases["test_after"]) == 1, out
    assert "leaker test_gate_fixture.py::test_uses_leaky" in cases["test_after"][0]
    assert "now7.gate.fixture.propagate" in cases["test_after"][0]
    assert len(cases) == 9, cases


def test_gate_is_inert_in_a_nested_child_pytest(tmp_path):
    proj = _gate_project(tmp_path)
    # a foreign outer stamp makes the child classify itself as nested
    env = _child_env(tmp_path / "report", **{llr.ENV_OUTER: "1"})
    proc, cases = _junit_errors(proj, env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert all(v == [] for v in cases.values()), cases
