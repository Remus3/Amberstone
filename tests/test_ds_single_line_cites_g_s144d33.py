"""Guard: two more DS tests cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0:

- ``test_kit_conversion_gate_rm86.py`` cited ``abilities.py:220-263`` for
  "the loader drops ``effects_descriptions``"; that range now spans the
  ``AbilityForm`` field list and most of ``AbilityForm.from_dict``, the
  loader that reads no such key. It also cited
  ``test_cost_aware_top_f2.py:60-62`` for the absent-param == explicit-default
  pattern, which is ``test_default_off_byte_identical``.
- ``test_sr_quest_line_deny_rm93.py`` cited
  ``tests/test_enchanter_pool_hsp_rm90.py:31-36`` (twice, once in an assert
  message) for the adjudicated World Atlas quest-line doctrine; the path was
  wrong (the file lives under ``agents/daemon_slayer/tests``) and the
  test-pin is ``test_world_atlas_support_quest_line_absent``.
- Sibling: the ``rank.py`` SR deny comment (above ``_SR_EXCLUDED_ITEM_IDS``)
  carried the same ``tests/test_enchanter_pool_hsp_rm90.py:31-36`` cite.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import abilities

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "test_kit_conversion_gate_rm86.py": (
        "``abilities.AbilityForm.from_dict``",
        "``test_cost_aware_top_f2.test_default_off_byte_identical``",
    ),
    "test_sr_quest_line_deny_rm93.py": (
        "``test_enchanter_pool_hsp_rm90.test_world_atlas_support_quest_line_absent``",
        "test_enchanter_pool_hsp_rm90.test_world_atlas_support_quest_line_absent.",
    ),
}


def _test_function(module_name: str, func_name: str) -> str:
    path = TESTS / module_name
    text = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{module_name}: no def {func_name}")


def test_pattern_matches_the_old_shapes():
    for sample in (
        "(``abilities.py:220-263``). Seeding therefore follows the",
        "Mirrors the real default-off pattern at test_cost_aware_top_f2.py:60-62",
        "enchanter pool in ``tests/test_enchanter_pool_hsp_rm90.py:31-36``: these",
        '"category error pinned in test_enchanter_pool_hsp_rm90.py:31-36.",',
    ):
        assert _LINE_CITE.search(sample), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    # Join implicitly concatenated string pieces so a split message still reads.
    flat = " ".join(text.replace("#", " ").split()).replace('" "', "")
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_ability_form_loader_drops_effects_descriptions():
    names = {f.name for f in dataclasses.fields(abilities.AbilityForm)}
    assert "effects_descriptions" not in names
    assert "damage_blocks" in names
    assert "effects_descriptions" not in inspect.getsource(abilities)


def test_cost_aware_default_off_is_absent_equals_explicit_default():
    src = _test_function(
        "test_cost_aware_top_f2.py", "test_default_off_byte_identical"
    )
    assert "self._ids(), self._ids(cost_ceiling=None)" in src


def test_enchanter_pool_pins_the_world_atlas_quest_line_out():
    src = _test_function(
        "test_enchanter_pool_hsp_rm90.py",
        "test_world_atlas_support_quest_line_absent",
    )
    assert '("3869", "3870", "3871", "3876", "3877")' in src
    assert "self.assertNotIn(iid, self.reg)" in src
    assert '["gold"]["total"]), 400)' in src


def test_rank_sr_deny_comment_cites_the_quest_line_test_by_symbol():
    text = (REPO / "agents" / "daemon_slayer" / "rank.py").read_text(
        encoding="utf-8"
    )
    assert "test_enchanter_pool_hsp_rm90.py:" not in text
    flat = " ".join(text.replace("#", " ").split())
    assert (
        "pinned for the enchanter pool by "
        "test_enchanter_pool_hsp_rm90.test_world_atlas_support_quest_line_absent:"
    ) in flat
