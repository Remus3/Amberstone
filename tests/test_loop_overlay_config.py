# arch: tests for the overlay-build loop config | section=tests | frozen=no
"""config.overlay.json drives the headless overlay + adaptive-build program in
cycle_command mode. The per-cycle typed sequence is: /clear (controller-prefixed) ->
'go' (1-token activation) -> /remote-control (operator requirement every new session) ->
/overlay-build-continue, ending in the done-sentinel final step. The gemini director is
skipped (self-directing from docs/OVERLAY_BUILD_MASTER_PLAN.md Section J); the gemini
auditor still reviews every commit."""
from __future__ import annotations

import json
from pathlib import Path

_CFG = Path(__file__).resolve().parent.parent / "ops" / "loop" / "config.overlay.json"


def test_overlay_config_is_valid_json():
    json.loads(_CFG.read_text(encoding="utf-8"))


def test_cycle_command_sequence_and_final_step():
    cfg = json.loads(_CFG.read_text(encoding="utf-8"))
    cc = cfg.get("cycle_command", "")
    lines = cc.split("\n")
    assert lines[0] == "go", "first typed line must be the 1-token activation message"
    assert lines[1] == "/remote-control", "second typed line must be /remote-control"
    assert lines[2].startswith("/overlay-build-continue"), "third line is the continue command"
    assert "done_sentinel.py" in cc, "cycle_command must include the FINAL done-sentinel step"


def test_self_directing_keeps_auditor():
    cfg = json.loads(_CFG.read_text(encoding="utf-8"))
    assert cfg.get("clear_each_cycle") is True, "overlay loop must /clear each cycle"
    assert "fixed_directive" not in cfg, "fixed_directive would disable the gemini auditor"
    assert "director_prompt" not in cfg, "self-directing: no gemini director"
    assert cfg.get("gemini_model"), "gemini auditor needs a model"


def test_cycle_command_is_ascii_clean():
    cfg = json.loads(_CFG.read_text(encoding="utf-8"))
    cc = cfg.get("cycle_command", "")
    banned = {0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D}
    assert not [c for c in cc if ord(c) in banned]
    assert cc.isascii()


def test_runaway_backstops_present():
    cfg = json.loads(_CFG.read_text(encoding="utf-8"))
    assert cfg.get("ignore_no_progress") is False, "keep the no-progress runaway guard"
    assert cfg.get("max_cycles", 0) >= 30, "enough cycles for the WP count"
    assert cfg.get("cycle_deadline_sec", 0) >= 1800
