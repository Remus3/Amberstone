"""RM-1356: the ARAM / macro-tree modules cite their neighbours by symbol.

core/aram_deterministic_coach.py, aram_fight_risk.py, macro_context.py,
macro_decision_tree.py, opening_tendency.py and playstyle_labels.py carried
`<file>.py:<line>` anchors into aram_coach, enemy_cc_threat_context,
vision_tracker, event_callouts, decision_detector, macro_response,
mia_reachability, champion_movespeed, duration_winrate and
_deterministic_coaching. Most had drifted (`aram_coach.py:332` and
`decision_detector.py:362` no longer pointed at what the prose said). The prose
now names the symbol; these guards keep it that way and pin that every cited
symbol still exists.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "core/aram_deterministic_coach.py",
    "core/aram_fight_risk.py",
    "core/macro_context.py",
    "core/macro_decision_tree.py",
    "core/opening_tendency.py",
    "core/playstyle_labels.py",
)

# `vision_tracker.py:376-388`, `file.py:105,603-617`, a bare `at :943`,
# `lines 12`.
_LINE_CITE = re.compile(
    r"[A-Za-z_/.]+\.(?:py|js|json):\d+"
    r"|\bat ``?:\d+|\bat :\d+|\bto :\d+"
    r"|\blines? \d{2,}"
)


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "consumable pick (coaches/aram_coach.py:332).",
        "the coaches/aram_coach.py:295-298 OBJECTIVE prompt",
        "from core/enemy_cc_threat_context.py:149-231``)",
        "shape - vision_tracker.py:376-388)",
        "(core/decision_detector.py:362 uses >= 12s).",
        "core/mia_reachability.py:66 and core/champion_movespeed.py:58.",
        "mirrors core/duration_winrate.py:57-64)",
    ):
        assert _LINE_CITE.search(old), old


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("coaches/aram_coach.py", "=== OBJECTIVE ==="),
        ("coaches/aram_coach.py", "Item extra:"),
        ("core/enemy_cc_threat_context.py", "def enemy_cc_threat_line"),
        ("core/enemy_cc_threat_context.py", "def _kind"),
        ("core/vision_tracker.py", "def _compute_enemies"),
        ("core/vision_tracker.py", "out[key] = {"),
        ("core/event_callouts.py", "SR_BARON_FIRST_S ="),
        ("core/decision_detector.py", "DECISION_REGISTRY"),
        ("core/decision_detector.py", "def register_detector"),
        ("core/decision_detector.py", "def detect_lane_roam_window"),
        ("core/decision_detector.py", "def detect_objective_contest_with_missing"),
        ("core/macro_response.py", "def macro_response_callout"),
        ("core/mia_reachability.py", "_SR_MAP_EXTENT ="),
        ("core/champion_movespeed.py", "_SR_MAP_EXTENT ="),
        ("core/duration_winrate.py", "def _open_ro"),
        ("dashboard/_deterministic_coaching.py",
         "from core.event_callouts import _sort_key as _callout_sort_key"),
    ],
)
def test_every_symbol_the_modules_cite_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "rel, name",
    [
        ("core/aram_deterministic_coach.py", "=== OBJECTIVE ==="),
        ("core/aram_deterministic_coach.py", "Item extra:"),
        ("core/aram_fight_risk.py", "enemy_cc_threat_line"),
        ("core/macro_context.py", "_compute_enemies"),
        ("core/macro_context.py", "_callout_sort_key"),
        ("core/macro_decision_tree.py", "register_detector"),
        ("core/macro_decision_tree.py", "macro_response_callout"),
        ("core/macro_decision_tree.py", "detect_lane_roam_window"),
        ("core/macro_decision_tree.py", "detect_objective_contest_with_missing"),
        ("core/opening_tendency.py", "_SR_MAP_EXTENT"),
        ("core/playstyle_labels.py", "_open_ro"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in (ROOT / rel).read_text(encoding="utf-8")
