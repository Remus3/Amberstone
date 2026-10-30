"""Guard: ability_dps and engine cite the AH lane and AD fold by symbol (s).

Measured 2026-10-30 at ENGINE 1.290.0. Five line cites in two DS modules had
all rotted:

- ``ability_dps.py`` cited ``engine.py:270`` for the write of
  ``scaled["aram_ability_haste"]`` (now in ``engine._apply_mode_modifiers``
  at :305), and cited ``ability_dps.py:926-929`` twice for the
  ``_classify_primary_scaling`` fold of ``total_ad_pct`` + ``bonus_ad_pct``
  over ``damage``-kind blocks (now :972-980).
- ``engine.py`` cited ``ability_dps.py:647`` twice for
  ``ability_dps._total_ability_haste`` (now :666).

The tests below pin the cites, and the facts they restated, by symbol. The
two ``ability_dps.py`` lines the pattern also matches are not cites: an
f-string slice ``[:4]`` and the DS port ``:8860``; they are stripped before
matching, not exempted by line number.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import ability_dps, engine

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b")

TARGETS = {
    "ability_dps.py": (
        "``aram_ability_haste`` delta (``engine._apply_mode_modifiers`` "
        "writes it).",
        "``ap_pct_sum`` above, read the same way "
        "``_classify_primary_scaling`` reads those blocks. "
        "END-appended and defaulted",
        "columns ``_classify_primary_scaling`` already folds together. "
        "Same ``damage``-blocks-only gate",
    ),
    "engine.py": (
        "CONSUMED since ENGINE 1.23.0 by "
        "``ability_dps._total_ability_haste``, which adds it to item AH "
        "before the cooldown math.",
        "ability_dps._total_ability_haste - NOT exposure-only.",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "``aram_ability_haste`` delta (engine.py:270). SR + every",
        "# reads those blocks (ability_dps.py:926-929). END-appended",
        "(ability_dps.py:926-929). Same ``damage``-blocks-only gate",
        "(``ability_dps.py:647``), which adds it to item AH before the",
        "# ability_dps._total_ability_haste (ability_dps.py:647) - NOT",
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


def test_not_a_cite_strip_keeps_real_cites():
    assert _NOT_A_CITE.sub("", "form_name[:4]:<6") == "form_name:<6"
    assert _NOT_A_CITE.sub("", "rides the :8860 reply") == "rides the  reply"
    assert _LINE_CITE.search(_NOT_A_CITE.sub("", "see :88601 and [:4]"))
    assert _LINE_CITE.search(_NOT_A_CITE.sub("", "see engine.py:8860"))


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_apply_mode_modifiers_writes_the_aram_ah_delta():
    src = inspect.getsource(engine._apply_mode_modifiers)
    assert re.search(r'scaled\["aram_ability_haste"\]\s*=\s*aram_ah', src)
    assert re.search(r'if mode != "ARAM":\s*return scaled, notes', src)


def test_total_ability_haste_adds_the_delta_in_aram_only():
    scaled = {"aram_ability_haste": 10.0}
    assert ability_dps._total_ability_haste(scaled, "SR", 5.0) == 5.0
    assert ability_dps._total_ability_haste(scaled, "ARENA", 5.0) == 5.0
    assert ability_dps._total_ability_haste(scaled, "ARAM", 5.0) == 15.0
    assert ability_dps._total_ability_haste({}, "ARAM", 5.0) == 5.0


def _damage_kind_ad_fold(fn) -> tuple[bool, set[str]]:
    tree = ast.parse(inspect.getsource(fn).lstrip())
    gated = any(
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "attribute_kind"
        and isinstance(node.ops[0], ast.NotEq)
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value == "damage"
        for node in ast.walk(tree)
    )
    summed = {
        node.args[0].attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sum"
        and node.args
        and isinstance(node.args[0], ast.Attribute)
    }
    return gated, summed


def test_classify_and_form_ad_pct_sum_fold_the_same_ad_columns():
    for fn in (ability_dps._classify_primary_scaling,
               ability_dps._form_ad_pct_sum):
        gated, summed = _damage_kind_ad_fold(fn)
        assert gated, fn.__name__
        assert {"total_ad_pct", "bonus_ad_pct"} <= summed, fn.__name__
    _, form_summed = _damage_kind_ad_fold(ability_dps._form_ad_pct_sum)
    assert form_summed == {"total_ad_pct", "bonus_ad_pct"}
