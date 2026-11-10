"""S144-D-266..268 - the DS ability-amp registries say what they model.

WHY. ``_ability_amp_overrides._amp_multiplier`` never raises: it clamps the
rank into ``amp_per_rank``, returns ``1 + addend`` for an ``always_on`` entry
WITHOUT reading ``condition``, and reads an unknown ``condition`` as
probability 0.0. So every authoring slip in the registry is silent:

* a per-rank amp collapsed to one value reads that value at every rank;
* an ``always_on`` entry that also names a condition never applies the gate
  its author wrote down;
* a conditional entry whose condition is not a key of
  ``_DEFAULT_AMP_PROBABILITY`` (a typo, or a ``cc_conditional`` tag the amp
  map does not carry, such as ``nth_hit``) is multiplied by 0.0 - inert while
  it reads as a live amp;
* ``_aa_amp_multiplier`` MULTIPLIES every ``base == "aa"`` entry of a champion
  and its docstring says each champion has at most one, which nothing pinned.

Existing tests pin the named rows one by one (item 239 / 247 / 257 / 258).
These pin the registry-wide shape, each with a planted-defect control:

* S144-D-266: a 1-long ``amp_per_rank`` is the documented INERT placeholder
  ``(0.0,)`` on a ``base == "aa"`` row whose note says INERT, and the live form
  it sits on carries a per-rank block (so a non-zero flat value there would be
  a per-rank amp collapsed to one number); every non-zero amp is per-rank and
  its note does not call it INERT.
* S144-D-267: bases are ``ability`` / ``aa``; an ``always_on`` row names no
  condition; a conditional row with a non-zero amp names a condition the
  probability map carries; at most one ``base == "aa"`` row per champion. The
  module docstring said Fiora E was "AUTHORED (condition ``nth_hit``)"; the row
  is ``always_on`` with no condition, and ``nth_hit`` is not an amp-map key, so
  the docstring is corrected and pinned.
* S144-D-268: the condition tags the module says mirror ``cc_conditional``
  (``channel``, ``frenzy_state``) equal those COND_* values, and their
  probabilities equal the ``cc_conditional`` SOURCE defaults (read from the
  source literal, so an operator JSON override of the live cc map cannot fail
  this); the two tags the module says have no COND_* analogue (``isolation``,
  ``w_flight``) are not cc tags; every amp-map key is a module ``_COND_*``
  constant with a probability in (0, 1].

MEASURED 2026-11-09 (live snapshot, patch 16.22.1): 7 per-form amp rows
(2 ``ability``, 5 ``aa``), 1 cross-spell row; 4 flat rows, all ``(0.0,)``
``aa`` placeholders over a per-rank live block (Caitlyn W Headshot 35:215,
Jayce W f1 70:110 % AD, Sivir W bounce 40:50 % AD, Nidalee Q f1 per-rank
base); 4 per-rank non-zero rows; one conditional non-zero row per map key
used (isolation, w_flight). A guard plus a docstring fix; no registry value
changes, so the scorer output is byte-identical.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest

from agents.daemon_slayer import _ability_amp_overrides as amp_mod
from agents.daemon_slayer import cc_conditional
from agents.daemon_slayer._ability_amp_overrides import (
    _ABILITY_AMP_OVERRIDES,
    _CROSS_SPELL_AMP_OVERRIDES,
    _DEFAULT_AMP_PROBABILITY,
    AmpEntry,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot

Key = tuple[str, str, int]
REGISTRIES: dict[str, dict[Key, Any]] = {
    "_ABILITY_AMP_OVERRIDES": _ABILITY_AMP_OVERRIDES,
    "_CROSS_SPELL_AMP_OVERRIDES": _CROSS_SPELL_AMP_OVERRIDES,
}
BASES = frozenset({"ability", "aa"})


@pytest.fixture(scope="module")
def ab() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load()


def _block_varies_by_rank(block: Any) -> bool:
    """True when any per-rank field of a DamageBlock holds two distinct values."""
    for f in dataclasses.fields(block):
        value = getattr(block, f.name)
        if not isinstance(value, tuple) or not value:
            continue
        if f.name == "raw_modifiers":
            for mod in value:
                vals = mod.get("values") if isinstance(mod, dict) else None
                if vals and len(set(vals)) > 1:
                    return True
        elif all(isinstance(x, (int, float)) for x in value) and len(set(value)) > 1:
            return True
    return False


def live_form_varies(ab: AbilitiesSnapshot) -> Callable[[Key], bool]:
    def varies(key: Key) -> bool:
        champ, slot, form_index = key
        if not ab.has_champion(champ):
            return False
        forms = ab.get_abilities(champ).get(slot) or ()
        if not 0 <= form_index < len(forms):
            return False
        return any(_block_varies_by_rank(b) for b in forms[form_index].damage_blocks)

    return varies


def check_flat_placeholders(registries: dict[str, dict[Key, Any]], varies: Callable[[Key], bool]) -> list[str]:
    """S144-D-266: a flat amp is an INERT ``aa`` zero over a per-rank live block."""
    out: list[str] = []
    for reg_name, reg in registries.items():
        for key, entry in reg.items():
            ranks = tuple(entry.amp_per_rank)
            nonzero = any(r != 0 for r in ranks)
            inert_note = "INERT" in entry.note
            if len(ranks) == 1:
                if nonzero:
                    out.append(f"{reg_name}{key}: flat non-zero amp {ranks}")
                if getattr(entry, "base", None) != "aa":
                    out.append(f"{reg_name}{key}: flat amp on a non-aa row")
                if not inert_note:
                    out.append(f"{reg_name}{key}: flat zero amp not documented INERT")
                if not varies(key):
                    out.append(f"{reg_name}{key}: placeholder over a rank-flat live form")
            elif nonzero and inert_note:
                out.append(f"{reg_name}{key}: live per-rank amp documented INERT")
            elif not nonzero:
                out.append(f"{reg_name}{key}: per-rank tuple of zeros {ranks}")
    return out


def check_gates(registries: dict[str, dict[Key, Any]], prob_map: dict[str, float]) -> list[str]:
    """S144-D-267: base, always_on / condition and one-aa-row-per-champion agree."""
    out: list[str] = []
    aa_rows: Counter[str] = Counter()
    for reg_name, reg in registries.items():
        for key, entry in reg.items():
            base = getattr(entry, "base", None)
            if isinstance(entry, AmpEntry) and base not in BASES:
                out.append(f"{reg_name}{key}: base {base!r}")
            if base == "aa":
                aa_rows[key[0]] += 1
            nonzero = any(r != 0 for r in entry.amp_per_rank)
            if entry.always_on and entry.condition:
                out.append(f"{reg_name}{key}: always_on row names condition {entry.condition!r}")
            if not entry.always_on and nonzero and entry.condition not in prob_map:
                out.append(f"{reg_name}{key}: condition {entry.condition!r} reads probability 0.0")
    for champ, n in sorted(aa_rows.items()):
        if n > 1:
            out.append(f"{champ}: {n} base='aa' rows (the AA factor multiplies them)")
    return out


def test_s144d266_flat_amps_are_inert_aa_placeholders_over_per_rank_forms(ab: AbilitiesSnapshot) -> None:
    flat = [k for reg in REGISTRIES.values() for k, e in reg.items() if len(e.amp_per_rank) == 1]
    live = [k for reg in REGISTRIES.values() for k, e in reg.items() if any(e.amp_per_rank)]
    assert len(flat) >= 3, "flat walk went empty"
    assert len(live) >= 3, "per-rank walk went empty"
    assert check_flat_placeholders(REGISTRIES, live_form_varies(ab)) == []


def test_s144d266_checker_flags_planted_defects(ab: AbilitiesSnapshot) -> None:
    caitlyn = _ABILITY_AMP_OVERRIDES["Caitlyn", "W", 0]
    mord = _ABILITY_AMP_OVERRIDES["Mordekaiser", "Q", 0]
    varies = live_form_varies(ab)
    planted = (
        {("Caitlyn", "W", 0): dataclasses.replace(caitlyn, amp_per_rank=(0.2,))},
        {("Caitlyn", "W", 0): dataclasses.replace(caitlyn, note="placeholder")},
        {("Mordekaiser", "Q", 0): dataclasses.replace(mord, amp_per_rank=(0.0,))},
        {("Mordekaiser", "Q", 0): dataclasses.replace(mord, note=mord.note + " INERT")},
        {("Mordekaiser", "Q", 0): dataclasses.replace(mord, amp_per_rank=(0.0,) * 5)},
    )
    for reg in planted:
        assert check_flat_placeholders({"p": reg}, varies), reg
    assert check_flat_placeholders({"p": {("Caitlyn", "W", 0): caitlyn}}, lambda _k: False)
    assert check_flat_placeholders({"p": {("Caitlyn", "W", 0): caitlyn}}, varies) == []


def test_s144d267_bases_conditions_and_aa_rows_agree() -> None:
    conditional = [k for reg in REGISTRIES.values() for k, e in reg.items() if not e.always_on and any(e.amp_per_rank)]
    assert len(conditional) >= 2, "conditional walk went empty"
    assert check_gates(REGISTRIES, _DEFAULT_AMP_PROBABILITY) == []


def test_s144d267_checker_flags_planted_defects() -> None:
    mord = _ABILITY_AMP_OVERRIDES["Mordekaiser", "Q", 0]
    fiora = _ABILITY_AMP_OVERRIDES["Fiora", "E", 0]
    planted = (
        {("Mordekaiser", "Q", 0): dataclasses.replace(mord, base="AA")},
        {("Mordekaiser", "Q", 0): dataclasses.replace(mord, condition="isolaton")},
        {("Fiora", "E", 0): dataclasses.replace(fiora, condition="nth_hit")},
        {
            ("Fiora", "E", 0): fiora,
            ("Fiora", "Q", 0): dataclasses.replace(fiora, amp_per_rank=(0.0,)),
        },
    )
    for reg in planted:
        assert check_gates({"p": reg}, _DEFAULT_AMP_PROBABILITY), reg
    assert check_gates({"p": {("Mordekaiser", "Q", 0): mord}}, {})


def test_s144d267_fiora_e_is_always_on_and_the_docstring_says_so() -> None:
    fiora = _ABILITY_AMP_OVERRIDES["Fiora", "E", 0]
    assert fiora.always_on is True
    assert fiora.condition == ""
    assert "nth_hit" not in _DEFAULT_AMP_PROBABILITY
    doc = inspect.getdoc(amp_mod) or ""
    assert "condition ``nth_hit``" not in doc
    assert "AUTHORED ``always_on``" in doc


def _cc_source_default_probabilities() -> dict[str, float]:
    """The ``cc_conditional._DEFAULT_CONDITION_PROBABILITY`` SOURCE literal."""
    tree = ast.parse(inspect.getsource(cc_conditional))
    for node in tree.body:
        target = getattr(node, "target", None)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(target, ast.Name)
            and target.id == "_DEFAULT_CONDITION_PROBABILITY"
            and isinstance(node.value, ast.Dict)
        ):
            return {
                getattr(cc_conditional, k.id): ast.literal_eval(v)
                for k, v in zip(node.value.keys, node.value.values, strict=True)
                if isinstance(k, ast.Name)
            }
    raise AssertionError("cc_conditional default probability literal not found")


def _module_cond_constants() -> dict[str, str]:
    return {
        name: value for name, value in vars(amp_mod).items() if name.startswith("_COND_") and isinstance(value, str)
    }


def test_s144d268_amp_condition_tags_mirror_cc_conditional() -> None:
    cc_tags = {v for n, v in vars(cc_conditional).items() if n.startswith("COND_") and isinstance(v, str)}
    cc_default = _cc_source_default_probabilities()
    assert len(cc_default) >= 10, "cc source literal walk went empty"
    mirrored = {
        amp_mod._COND_CHANNEL: cc_conditional.COND_CHANNEL_COMPLETION,
        amp_mod._COND_FRENZY_STATE: cc_conditional.COND_FRENZY_STATE,
    }
    for amp_tag, cc_tag in mirrored.items():
        assert amp_tag == cc_tag
        assert _DEFAULT_AMP_PROBABILITY[amp_tag] == cc_default[cc_tag], amp_tag
    for own_tag in (amp_mod._COND_ISOLATION, amp_mod._COND_W_FLIGHT):
        assert own_tag not in cc_tags, own_tag


def test_s144d268_probability_map_keys_are_module_tags_in_unit_interval() -> None:
    tags = set(_module_cond_constants().values())
    assert len(tags) >= 4, "module _COND_ walk went empty"
    assert set(_DEFAULT_AMP_PROBABILITY) == tags
    for tag, prob in _DEFAULT_AMP_PROBABILITY.items():
        assert 0.0 < prob <= 1.0, (tag, prob)
    used = {e.condition for reg in REGISTRIES.values() for e in reg.values() if e.condition}
    assert used <= tags, used - tags
