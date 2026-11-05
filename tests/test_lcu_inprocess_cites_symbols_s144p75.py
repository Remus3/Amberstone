"""RM-1348: dashboard/_lcu_inprocess.py cites its neighbours by symbol.

The module prose carried fifteen `file.py:<line>` / `:<line>` anchors in
six neighbouring files; a line number is a measurement at one commit and every one had
drifted. The prose now names the symbol. These guards keep it that way and pin
that each named symbol still exists where the prose says it does.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "dashboard" / "_lcu_inprocess.py"

# `name.py:123`, `name.py:12-34`, a bare `(:293)` / `+ :165` anchor, `lines 12`.
_LINE_CITE = re.compile(
    r"[A-Za-z_/.]+\.(?:py|js):\d+"
    r"|\(:\d+|\+ :\d+|\bat :\d+|\(:\d+-\d+\)|\blines? \d{2,}"
)


def test_module_cites_no_file_line_numbers():
    text = MODULE.read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("lcu/snapshot_shape.py", "def shape_snapshot("),
        ("tools/lcu_agent.py", "def capture_state("),
        ("tools/lcu_agent.py", 'state = {"config": dict(CONFIG)}'),
        ("tools/lcu_agent.py", 'state["lcu_port"] = _lcu["port"]'),
        ("tools/lcu_agent.py", "def read_lockfile("),
        ("tools/lcu_agent.py", "def ensure_lcu_conn("),
        ("tools/lcu_agent.py", "def execute_command("),
        ("tools/lcu_agent.py", 'if name == "set_config":'),
        ("tools/lcu_agent.py", "CONFIG = {"),
        ("lcu/lcu_client.py", "def _parse_lockfile_fields("),
        ("lcu/lcu_client.py", "self._lockfile_missing_logged = False"),
        ("dashboard/routes_loadout.py", "def _serve_lcu_cmd_post("),
        ("dashboard/routes_state.py", "def _state_cadence_s("),
        ("dashboard/_state_builder.py", 'os.environ.get("RC_LCU_INPROCESS") == "1"'),
        ("core/decision_detector.py", "class DecisionLoop"),
        ("core/decision_detector.py", "self._last_logged_error_sig"),
    ],
)
def test_every_symbol_the_module_cites_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "name",
    [
        "shape_snapshot", "capture_state", "read_lockfile", "ensure_lcu_conn",
        "execute_command", "_parse_lockfile_fields", "_serve_lcu_cmd_post",
        "_state_cadence_s", "_lockfile_missing_logged", "_last_logged_error_sig",
        "DecisionLoop._loop",
    ],
)
def test_prose_still_names_the_symbol(name):
    # The pin above tracks a live cite, not a symbol the prose stopped using.
    assert name in MODULE.read_text(encoding="utf-8")
