"""RM-1307: two write-only attributes are gone from TftLiveAnalysis.

`TftLiveAnalysis._last_placement` was assigned in `__init__`, reset on a new
game and set after each analysis, and read by nothing in production (every
other mention in the tree was a test fixture or a docstring).
`TftLiveAnalysis._scanned_mid` was set False in `__init__` and on every round
change and saved / restored with the round bookkeeping, but no branch ever read
it: the mid-round scan it served was removed ("Mid-round scan removed - 1
scan/round is sufficient") and the flag was left behind.

Measured at the removal (every surface, `.py` `.md` `.js` `.ps1` `.json`, minus
docs/_archive and run output): the only non-test, non-docstring mentions were
the writes inside tft/tft_live_analysis.py. The model field
`unitplacement` is NOT the attribute: it is parsed from the reply and published
as `unit_placement`, and stays (pinned below).

If you find yourself adding either back, first confirm a real reader exists.
"""
from __future__ import annotations

import ast
import time
from pathlib import Path

from tft import tft_live_analysis as tla

_SRC = Path(tla.__file__).read_text(encoding="utf-8")
_DEAD = ("_last_placement", "_scanned_mid")


def _names_in_source() -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(_SRC)):
        if isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
    return out


def test_dead_attributes_are_not_in_the_module():
    seen = _names_in_source()
    for name in _DEAD:
        assert name not in seen, f"{name} came back: give it a reader or drop it"
        assert name not in _SRC


def test_model_unitplacement_field_is_still_published():
    assert 'f.get("unitplacement","")' in _SRC
    assert '"unit_placement"' in _SRC


def _mk():
    la = tla.TftLiveAnalysis.__new__(tla.TftLiveAnalysis)
    la._last_round = (0, 0)
    la._round_start_time = 0.0
    la._scanned_planning = False
    return la


def test_apply_round_advance_resets_only_the_planning_flag():
    la = _mk()
    la._apply_round({"stage": 3, "round": 2}, False)
    la._scanned_planning = True
    stamp = la._round_start_time
    time.sleep(0.002)
    la._apply_round({"stage": 3, "round": 3}, False)
    assert la._last_round == (3, 3)
    assert la._scanned_planning is False
    assert la._round_start_time > stamp
    assert len(la._round_before) == 3


def test_apply_round_revert_restores_the_replaced_bookkeeping():
    la = _mk()
    la._apply_round({"stage": 3, "round": 2}, False)
    la._scanned_planning = True
    stamp = la._round_start_time
    la._apply_round({"stage": 3, "round": 3}, False)
    la._apply_round({"stage": 3, "round": 2}, True)
    assert la._last_round == (3, 2)
    assert la._round_start_time == stamp
    assert la._scanned_planning is True
    assert la._round_before is None
