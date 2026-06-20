# arch: tests for loop_controller cycle_source precedence (RC2) | section=tests | frozen=no
"""The loop controller's cycle_source() picks the per-cycle directive source.

RC2 adds a `cycle_command` mode: a self-directing slash command (e.g.
/RC2-Continue) typed VERBATIM after /clear each cycle, skipping the gemini
director but KEEPING the gemini auditor. Precedence: operator override >
cycle_command > fixed_directive > gemini director. Default-absent both keys =>
'director' (byte-identical to the historical loop). Loaded by file path so the
module's argv-driven CFG load does not need a real launch.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CTRL = _ROOT / "ops" / "loop" / "loop_controller.py"
_RC2_CFG = _ROOT / "ops" / "loop" / "config.rc2.json"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("loop_controller_uut_rc2", _CTRL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_absent_is_director(lc):
    assert lc.cycle_source({}, None) == "director"
    assert lc.cycle_source({}, "") == "director"  # empty override is falsy


def test_cycle_command_selected(lc):
    assert lc.cycle_source({"cycle_command": "/RC2-Continue"}, None) == "cycle_command"


def test_cycle_command_outranks_fixed(lc):
    cfg = {"cycle_command": "/RC2-Continue", "fixed_directive": "x"}
    assert lc.cycle_source(cfg, None) == "cycle_command"


def test_override_outranks_cycle_command(lc):
    assert lc.cycle_source({"cycle_command": "/RC2-Continue"}, "do X") == "override"


def test_fixed_when_no_cycle_command(lc):
    assert lc.cycle_source({"fixed_directive": "x"}, None) == "fixed"


def test_rc2_config_is_valid_and_self_directing():
    """The shipped RC2 loop config drives /clear + /RC2-Continue with the
    done-sentinel final step, and keeps the gemini auditor (no fixed_directive)."""
    cfg = json.loads(_RC2_CFG.read_text(encoding="utf-8"))
    cc = cfg.get("cycle_command", "")
    assert cc.startswith("/RC2-Continue"), "cycle_command must lead with the slash command"
    assert "done_sentinel.py" in cc, "cycle_command must include the FINAL done-sentinel step"
    assert cfg.get("clear_each_cycle") is True, "RC2 loop must /clear each cycle"
    assert "fixed_directive" not in cfg, "fixed_directive would disable the gemini auditor"
    assert cfg.get("gemini_model"), "gemini auditor needs a model"
    # ASCII hard rule: no banned glyphs in the typed command.
    banned = {0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D}
    assert not [c for c in cc if ord(c) in banned], "cycle_command must be ASCII-clean"
