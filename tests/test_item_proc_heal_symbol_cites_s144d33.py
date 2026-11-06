"""Guard: _item_proc_heal.py cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. agents/daemon_slayer/_item_proc_heal.py
carried 9 line cites and every one had drifted (cited -> line before this
edit): the 2502 Anguish ``PeriodicProc`` ``_effects_data.py:2040-2047`` ->
2104-2114, the Arena 222502 one ``:3711-3716`` -> 3970-3978, the
"utility-only" note ``:2050`` (that note has since been rewritten and now
says NOT utility), ``ItemHeal.resolve_magnitude`` ``_effects_types.py:457-464``
-> 489, the ehp ``target_mr`` prose ``ehp.py:188`` -> 202,
``ehp._armor_factor`` ``ehp.py:147-157`` -> 161, the ``rune_heal_hp`` fold
``ehp.py:1534`` -> the ``heal_total`` sum in ``compute_ehp``; the tanky
target ``tests/test_ad_axis_ability_damage_rm39.py:30`` names a path that no
longer exists (the file lives under agents/daemon_slayer/tests, as
``_TARGET_KW``); and the RM-103 quote ``ROADMAP.md:268-270`` now lives in
docs/ROADMAP_HISTORY.md.

The module's prose claims were re-read against the engine and hold; the tests
below pin the ones the docstring leans on, so a refactor that breaks one turns
this red rather than leaving the prose stale.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "_item_proc_heal.py"

# ``_effects_data.py:2040``, ``ROADMAP.md:268``, and the bare continuation
# ``:3711-3716`` that leaned on the previous cite's module.
_LINE_CITE = re.compile(r"\w\.(?:py|md):\d|``:\d")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _resolve(module: str, dotted: str) -> ast.AST:
    body = ast.parse(_source(DS / f"{module}.py")).body
    node: ast.AST | None = None
    for part in dotted.split("."):
        node = next(
            (n for n in body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name == part),
            None,
        )
        if node is None:
            raise AssertionError(f"{module}.py has no {dotted}")
        body = node.body
    assert node is not None
    return node


def _segment(module: str, dotted: str) -> str:
    return ast.get_source_segment(
        _source(DS / f"{module}.py"), _resolve(module, dotted)) or ""


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``_effects_data.py:2040-2047`` for SR 2502 and ``:3711-3716`` for",
        "``ehp._armor_factor`` (``ehp.py:147-157``) because",
        'counterfactual was measured at (ROADMAP.md:268-270: "1 champ',
        "``tests/test_ad_axis_ability_damage_rm39.py:30`` and the 1.223.0",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``data/daemon_slayer/16.14.1/items_meraki.json`` item 2502",
        "``ehp._armor_factor`` because ``ehp`` is this module's",
        "the 1.223.0 CHANGELOG entry's golden-diff target pair",
        '``ITEM_EFFECTS["2502"]`` in ``_effects_data.py``',
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(_source(TARGET).splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_every_named_symbol_resolves():
    text = _source(TARGET)
    for module, dotted in (
        ("_effects_types", "ItemHeal.resolve_magnitude"),
        ("ehp", "_armor_factor"),
        ("ehp", "_collect_heals"),
        ("ehp", "compute_ehp"),
    ):
        assert dotted in text, (module, dotted)
        _resolve(module, dotted)
    assert "agents/daemon_slayer/tests/test_ad_axis_ability_damage_rm39.py" \
        in text
    assert "docs/ROADMAP_HISTORY.md" in text


def test_both_anguish_rows_are_damage_only_periodics():
    # The prose: the package models the DAMAGE half for 2502 and 222502 as an
    # Anguish PeriodicProc and carries no heal for either, so _collect_heals
    # skips them and this module is the only heal credit (no double count).
    from agents.daemon_slayer._effects_data import ITEM_EFFECTS

    for iid in ("2502", "222502"):
        eff = ITEM_EFFECTS[iid]
        assert [p.name for p in eff.periodics] == ["Anguish"], iid
        assert eff.periodics[0].every_n_seconds == 4.0, iid
        assert eff.heal is None, iid
        assert "_item_proc_heal.py" in eff.note, iid


def test_item_heal_resolve_magnitude_has_no_resist_input():
    # The prose: resolve_magnitude takes only base_ad / bonus_hp / bonus_ad /
    # missing_hp / is_ranged - no victim-resist input.
    fn = _resolve("_effects_types", "ItemHeal.resolve_magnitude")
    assert isinstance(fn, ast.FunctionDef)
    assert [a.arg for a in fn.args.args] == [
        "self", "base_ad", "bonus_hp", "bonus_ad", "missing_hp", "is_ranged"]
    assert "resolve_magnitude(" in _segment("ehp", "_collect_heals")


def test_ehp_has_no_executable_target_mr_reference():
    # The prose: ehp.py carries ZERO executable references to target_mr; its
    # only mention is docstring prose.
    tree = ast.parse(_source(DS / "ehp.py"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg) or (isinstance(node, ast.keyword) and node.arg):
            names.add(node.arg)
    assert "target_mr" not in names


def test_inlined_mitigation_agrees_with_ehp_armor_factor():
    from agents.daemon_slayer import ehp
    from agents.daemon_slayer._item_proc_heal import _magic_mitigation_factor

    for mr in (-40.0, -10.0, 0.0, 30.0, 60.0, 150.0):
        assert _magic_mitigation_factor(mr) == ehp._armor_factor(mr), mr


def test_proc_heal_joins_the_pool_before_heal_amp():
    # The prose: the proc heal folds into heal_item_total BEFORE
    # heal_amp_mult, matching the rune_heal_hp precedent.
    seg = _segment("ehp", "compute_ehp")
    assert "heal_item_total += _item_proc_heal_fn(" in seg
    assert ("heal_item_total + heal_lifesteal + rune_heal_hp + "
            "rune_self_heal_hp\n    ) * heal_amp_mult") in seg


def test_cited_tanky_target_and_rm103_quote_still_exist():
    rm39 = _source(DS / "tests" / "test_ad_axis_ability_damage_rm39.py")
    assert '"target_mr": 60.0,' in rm39
    assert "_TARGET_KW = {" in rm39
    hist = _source(REPO / "docs" / "ROADMAP_HISTORY.md")
    assert "1 champ in range, 1 trigger per fight window" in hist
