"""Guard: five more DS tests cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0:

- ``test_rune_offense_jack_of_all_trades_r156.py`` cited ``engine.py:318-320``
  for the shape a resolved build uses to produce ``aggregate_item_stats``
  totals; that call now sits ~50 lines lower, inside ``build_champion``.
- ``test_rune_resist_signature_convention_r134.py`` and
  ``test_kit_conversion_hybrid_rm115_p4.py`` cited ``kit_conversion.py:16-18``
  for "the module supplies the vector, each ranker scales its own key"; those
  lines are the "WHY A CURATED REGISTRY" heading, and the claim is the module
  docstring's opening section. ``test_kit_conversion_hybrid_rm115_p4.py``
  also cited ``kit_conversion.py:54-58`` (twice) for the Olaf Stridebreaker
  not-reachable note; it now opens two lines higher, in the docstring's
  REACHABILITY section.
- ``test_ability_wiki_damage_locke_zaahen.py`` cited
  ``test_cdragon_ratio_matcher.py:33`` + ``test_cdragon_surplus_ad_a29.py:83``
  for the repo-wide one-field-per-stat-family guards; both lines are the
  ``_AD_FIELDS`` constants, not the guard tests.
- ``test_arena_augment_name_alias_rm331.py`` cited ``augments.py:227`` for the
  swallowed ``except (KeyError, AttributeError): continue`` (now ~150 lines
  lower, in ``compute_augment_stats``) and ``test_arena_augment_e2e_p1l26.py``
  ``:245-259`` for the unregistered-augment byte-identity test (now two lines
  higher).

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import augments, engine, kit_conversion

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "test_rune_offense_jack_of_all_trades_r156.py": ("``engine.build_champion``",),
    "test_rune_resist_signature_convention_r134.py": (
        "``kit_conversion`` module",
    ),
    "test_kit_conversion_hybrid_rm115_p4.py": (
        "``kit_conversion`` module",
        "``kit_conversion`` REACHABILITY",
    ),
    "test_ability_wiki_damage_locke_zaahen.py": (
        "``test_cdragon_ratio_matcher.test_no_same_family_double_count_flag_on``",
        "``test_cdragon_surplus_ad_a29.test_no_ad_family_double_count_flag_on``",
    ),
    "test_arena_augment_name_alias_rm331.py": (
        "``augments.compute_augment_stats``",
        "``test_unknown_augment_zero_overlay_through_rank``",
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
        "canonical ``{axis}_{flat|pct}`` slot, and ``engine.py:318-320`` is",
        "# above: the seam is a SORT-KEY transform (``kit_conversion.py:16-18``",
        '"""Repo-wide machine guard (``test_cdragon_ratio_matcher.py:33`` +',
        "``test_cdragon_surplus_ad_a29.py:83``): no damage block may hold two",
        "miss was swallowed at ``agents/daemon_slayer/augments.py:227``",
        "``test_arena_augment_e2e_p1l26.py:245-259`` asserts that",
        "Do NOT anchor on Stridebreaker: ``kit_conversion.py:54-58`` records",
        '"""Guard the documented negative (kit_conversion.py:54-58).',
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
    flat = " ".join(text.replace("#", " ").split())
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_build_champion_aggregates_the_resolved_build_stats():
    src = inspect.getsource(engine.build_champion)
    assert 'item_stat_blocks = [rec.get("stats", {}) for rec in item_records]' in src
    assert "aggregate_item_stats(item_stat_blocks)" in src


def test_kit_conversion_docstring_says_each_ranker_scales_its_own_key():
    doc = " ".join((kit_conversion.__doc__ or "").split())
    assert "This module supplies the conversion vector. It does NOT apply it;" in doc
    assert "each ranker scales its own SORT key" in doc


def test_kit_conversion_docstring_files_stridebreaker_as_unreachable():
    doc = " ".join((kit_conversion.__doc__ or "").split())
    reach = doc.index("REACHABILITY")
    assert doc.index(
        "NOT reachable at any setting, and filed as L2 objective-coverage work:"
        " Olaf's Stridebreaker rising"
    ) > reach


@pytest.mark.parametrize(
    ("module_name", "func_name"),
    [
        ("test_cdragon_ratio_matcher.py", "test_no_same_family_double_count_flag_on"),
        ("test_cdragon_surplus_ad_a29.py", "test_no_ad_family_double_count_flag_on"),
    ],
)
def test_family_guards_sweep_every_block(module_name, func_name):
    src = _test_function(module_name, func_name)
    assert "for cid in on.champion_ids():" in src
    assert "for f in _AD_FIELDS) > 1" in src


def test_compute_augment_stats_swallows_an_unknown_augment():
    src = inspect.getsource(augments.compute_augment_stats)
    assert re.search(r"except \(KeyError, AttributeError\):\s+continue", src)


def test_unregistered_augment_test_asserts_baseline_identity():
    src = _test_function(
        "test_arena_augment_e2e_p1l26.py",
        "test_unknown_augment_zero_overlay_through_rank",
    )
    assert 'augments=["NoSuchAugment_p1l26_zzz"]' in src
    assert "unk.baseline_dps, base.baseline_dps" in src
