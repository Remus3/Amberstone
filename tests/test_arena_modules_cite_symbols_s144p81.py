"""RM-1354: the four Arena precompute modules cite coaches/arena_coach.py by symbol.

core/arena_augment_playline.py, core/arena_target_rule.py,
core/arena_deterministic_coach.py and core/arena_coach_shadow.py carried
`coaches/arena_coach.py:<line>` anchors (`:138`, `:148`, `:171`, `:459`, `:943`,
`:781-788`). A line number is a measurement at one commit and all of them had
drifted. The prose now names the symbol; these guards keep it that way and pin
that each cited symbol still exists in the coach.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "core/arena_augment_playline.py",
    "core/arena_target_rule.py",
    "core/arena_deterministic_coach.py",
    "core/arena_coach_shadow.py",
)

# `arena_coach.py:138`, `arena_coach.py:781-788`, a bare `at :943`, `lines 12`.
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
        "``coaches/arena_coach.py:171`` asks the live Haiku call",
        "(set at ``coaches/arena_coach.py:459``, persisted\n    apiName-mapped at ``:943``)",
        "rule at ``coaches/arena_coach.py:148`` is",
        "read from\n    ``coaches/arena_coach.py:781-787``)",
        '"trade efficiently and kite" (coaches/arena_coach.py:138).',
        "(coaches/arena_coach.py:781-788). Used to",
    ):
        assert _LINE_CITE.search(old), old


@pytest.mark.parametrize(
    "needle",
    [
        "_SYSTEM_PROMPT = ",
        "Target priority: 1)",
        "trade efficiently and kite",
        "self._picked_augments",
        '"augments_picked":',
        "current.update({",
        '"round_strategy":',
        '"target_priority":',
    ],
)
def test_every_symbol_the_modules_cite_still_exists_in_the_coach(needle):
    coach = (ROOT / "coaches" / "arena_coach.py").read_text(encoding="utf-8")
    assert needle in coach, f"arena_coach.py lost {needle}"


def test_augment_advice_line_is_inside_system_prompt_not_user_template():
    """The playline prose names _SYSTEM_PROMPT; pin that the line lives there."""
    coach = (ROOT / "coaches" / "arena_coach.py").read_text(encoding="utf-8")
    start = coach.index("_SYSTEM_PROMPT = ")
    end = coach.index("_USER_TEMPLATE = ")
    assert start < coach.index("Augment advice: <if augment select") < end


@pytest.mark.parametrize(
    "rel, name",
    [
        ("core/arena_augment_playline.py", "_SYSTEM_PROMPT"),
        ("core/arena_augment_playline.py", "augments_picked"),
        ("core/arena_target_rule.py", "_SYSTEM_PROMPT"),
        ("core/arena_deterministic_coach.py", "current.update"),
        ("core/arena_deterministic_coach.py", "_SYSTEM_PROMPT"),
        ("core/arena_coach_shadow.py", "current.update"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in (ROOT / rel).read_text(encoding="utf-8")
