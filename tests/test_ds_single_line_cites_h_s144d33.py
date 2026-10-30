"""Guard: three more DS engine modules cite by symbol, not line (RM-1053 part).

Measured 2026-10-30 at ENGINE 1.290.0:

- ``_rune_hsp_amp.py`` cited ``_hsp_amp.py:23`` for the item-keyed helper
  (the ``def`` is one line above it, ``sum_wielder_hsp_pct``),
  ``_hsp_amp.py:27-30`` for the "(1 + hsp_pct)" convention (that range is now
  the signature tail and the first docstring line; the convention sits in the
  ``sum_wielder_hsp_pct`` docstring) and ``_hsp_amp.py:5-7`` for the no-vamp
  contract (still in the ``_hsp_amp`` module docstring).
- Sibling: ``_scaling_hsp.py`` carried the same ``_hsp_amp.py:27-30`` cite
  for the same convention.
- ``_ability_wiki_damage_registry.py`` (the Zaahen Q AD-family split comment)
  cited ``tests/test_cdragon_ratio_matcher.py:33`` and
  ``tests/test_cdragon_surplus_ad_a29.py:83``: both land on the ``_AD_FIELDS``
  tuple, and the whole-snapshot sweeps that enforce the rule are
  ``test_no_same_family_double_count_flag_on`` and
  ``test_no_ad_family_double_count_flag_on``.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import _hsp_amp

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
DS_TESTS = DS / "tests"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "_rune_hsp_amp.py": (
        "the item-keyed ``_hsp_amp.sum_wielder_hsp_pct``. That helper sums",
        "convention documented in the ``_hsp_amp.sum_wielder_hsp_pct`` docstring",
        "the contract stated in the ``_hsp_amp`` module docstring.",
    ),
    "_scaling_hsp.py": (
        'convention in the ``_hsp_amp.sum_wielder_hsp_pct`` docstring. The AP half',
    ),
    "_ability_wiki_damage_registry.py": (
        "``test_cdragon_ratio_matcher.test_no_same_family_double_count_flag_on``",
        "``test_cdragon_surplus_ad_a29.test_no_ad_family_double_count_flag_on``",
    ),
}

_SWEEPS = {
    "test_cdragon_ratio_matcher.py": "test_no_same_family_double_count_flag_on",
    "test_cdragon_surplus_ad_a29.py": "test_no_ad_family_double_count_flag_on",
}


def _tree(path: Path) -> tuple[str, ast.Module]:
    text = path.read_text(encoding="utf-8")
    return text, ast.parse(text)


def test_pattern_matches_the_old_shapes():
    for sample in (
        "helper (``_hsp_amp.py:23``) sums ``heal_shield_amp_pct`` across",
        'the "(1 + hsp_pct)" convention documented at ``_hsp_amp.py:27-30``:',
        'model and the "(1 + hsp_pct)" convention at ``_hsp_amp.py:27-30``. The',
        "omnivamp / spellvamp / drain) - the contract stated at ``_hsp_amp.py:5-7``.",
        "# tests/test_cdragon_ratio_matcher.py:33 +",
        "# tests/test_cdragon_surplus_ad_a29.py:83 - both sweep the WHOLE",
    ):
        assert _LINE_CITE.search(sample), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    text = (DS / name).read_text(encoding="utf-8")
    flat = " ".join(text.replace("#", " ").split())
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_hsp_amp_carries_the_cited_claims():
    module_doc = " ".join((_hsp_amp.__doc__ or "").split())
    assert "it does NOT amplify vamp (lifesteal / omnivamp / spellvamp / drain)" in (
        module_doc
    )
    func_doc = " ".join((_hsp_amp.sum_wielder_hsp_pct.__doc__ or "").split())
    assert '"(1 + hsp_pct)" convention' in func_doc
    assert "Redemption 0.10 + Mikael 0.12 = 0.22" in func_doc


@pytest.mark.parametrize("module_name", sorted(_SWEEPS))
def test_ad_family_sweeps_cover_the_whole_snapshot(module_name):
    text, tree = _tree(DS_TESTS / module_name)
    fields = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "_AD_FIELDS" for t in node.targets)
    ]
    assert len(fields) == 1, module_name
    assert ast.literal_eval(fields[0]) == ("total_ad_pct", "bonus_ad_pct")
    funcs = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == _SWEEPS[module_name]
    ]
    assert len(funcs) == 1, f"{module_name}: no def {_SWEEPS[module_name]}"
    src = ast.get_source_segment(text, funcs[0]) or ""
    assert "for cid in on.champion_ids():" in src
    assert "for f in _AD_FIELDS) > 1" in src
