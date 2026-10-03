"""NOW-7: the report-only logger-leak detector records a planted leak, records
nothing for a clean test, and is inert when RC_LOGGER_LEAK_REPORT is unset.

The unit half drives snapshot/diff/record directly. The end-to-end half runs a
throwaway pytest in a SUBPROCESS with the detector loaded via ``-p``, because
the in-process hook is already registered on this very run and would observe
itself.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

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
        rows = [r for r in llr.diff(before, llr.snapshot()) if r[0].startswith("now7.brand_new")]
    finally:
        lg.propagate = True
    assert rows == [("now7.brand_new_cut_logger_zz", "propagate", True, False, True)]


def test_flag_parsing():
    assert llr.is_enabled({"RC_LOGGER_LEAK_REPORT": "1"}) is True
    assert llr.is_enabled({}) is False
    assert llr.is_enabled({"RC_LOGGER_LEAK_REPORT": "0"}) is False
    assert llr.is_enabled({"RC_LOGGER_LEAK_REPORT": ""}) is False


_PLANTED = '''
import logging

def test_a_leaker():
    logging.getLogger("now7.e2e.leaker").propagate = False

def test_b_clean():
    lg = logging.getLogger("now7.e2e.clean")
    lg.propagate = False
    lg.propagate = True
'''


def _run_child(tmp_path, flag):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "test_planted.py").write_text(_PLANTED, encoding="utf-8")
    report_dir = tmp_path / "report"
    env = dict(os.environ)
    env.pop("RC_LOGGER_LEAK_REPORT", None)
    env.pop("PYTEST_XDIST_WORKER", None)
    if flag is not None:
        env["RC_LOGGER_LEAK_REPORT"] = flag
    env["RC_LOGGER_LEAK_REPORT_DIR"] = str(report_dir)
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", "tests._logger_leak_report", "--rootdir", str(proj), str(proj)],
        cwd=str(proj), env=env, capture_output=True, text=True, timeout=120,
        creationflags=flags,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = []
    if report_dir.is_dir():
        for f in report_dir.glob("*.jsonl"):
            rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
    return rows


def test_end_to_end_enabled_records_only_the_leaker(tmp_path):
    rows = [r for r in _run_child(tmp_path, "1") if r["logger"].startswith("now7.e2e")]
    assert len(rows) == 1
    assert rows[0]["nodeid"].endswith("test_planted.py::test_a_leaker")
    assert rows[0]["logger"] == "now7.e2e.leaker"
    assert rows[0]["attribute"] == "propagate"


def test_end_to_end_inert_when_unset(tmp_path):
    assert _run_child(tmp_path, None) == []
