"""S144-D-198..200 - every (champion, key, form_index)-keyed ability registry
resolves to a real form, and a non-SERVED target form is a pinned exception.

WHY. Seven hand-authored ability registries are keyed on
``(champion_id, key, form_index)``:

* ``_ability_amp_overrides._ABILITY_AMP_OVERRIDES``
* ``_ability_amp_overrides._CROSS_SPELL_AMP_OVERRIDES``
* ``_ability_amp_overrides._STAGED_AMP_BLOCK_ROUTES``
* ``_ability_base_overrides._ABILITY_BASE_OVERRIDES``
* ``_ability_overrides.DAMAGE_TYPE_OVERRIDES``
* ``_ability_overrides.NON_DAMAGE_BLOCKS``
* ``_ability_wiki_form_damage.WIKI_FORM_DAMAGE_ENTRIES``

Each is read with a plain dict ``.get`` (or, for the wiki-form registry, a
skip-on-absent loop), so an entry whose champion, key or form index does not
exist, or that names a block attribute the form does not carry, is SILENTLY
inert: no error, no warning, the guard tests that pin one champion stay green.
And ``ability_dps.compute_ability_dps`` looks the amp registries up with the
form it actually SERVES (``form.form_index`` after
``_registries.get_form_index_for``), so an entry authored on a non-served form
never fires on the default path either. The Quinn test in
``test_ability_wiki_form_damage_rm95b.py`` pins that for one entry only.

MEASURED 2026-11-09 (live snapshot, patch 16.22.1, ENGINE 1.291.0): 7 + 1 + 1
+ 14 + 7 + 9 + 1 entries, ZERO dangling, ZERO missing attribute names, and
exactly THREE entries on a non-served form, each deliberate:

* ``("Jayce", "W", 1)`` amp - Hyper Charge, authored INERT (``amp_per_rank``
  0.0); the served Jayce W is form 0 Lightning Field.
* ``("Hwei", "Q", 2)`` staged block route - Severing Bolt; the served Hwei Q is
  form 1, and the route is reached only through an explicit Q form 2
  override (``form_index={"Q": 2}`` over HTTP in
  ``test_rm115_tail_seams_reach_the_client.py``,
  ``form_index_overrides={"Q": 2}`` in-process in
  ``test_staged_amp_block_route_item246.py``).
* ``("Qiyana", "Q", 0)`` base override - Edge of Ixtal; the served Qiyana Q is
  form 1 Elemental Wrath, which carries its own ``("Qiyana", "Q", 1)`` entry.
  Form 0 is a data correction reachable through an explicit form override.

The exception set is pinned EXACTLY, so a new entry on a non-served form goes
red until it is added here with a reason, and an exception whose form becomes
the served one goes red until it is removed.

S144-D-201. The served form itself comes from ``champion_form_index.json``,
and ``compute_ability_dps`` silently falls back to form 0 when that index is
out of range (``if form_idx < 0 or form_idx >= len(forms): form_idx = 0``).
So the served-form check above is only as good as that table: every override
must name a live champion, a live key and an in-range form. Measured the same
day: 16 overrides over 12 champions, all in range.
"""

from __future__ import annotations

from typing import Iterable

import pytest

from agents.daemon_slayer import _registries as registries
from agents.daemon_slayer._ability_amp_overrides import (
    _ABILITY_AMP_OVERRIDES,
    _CROSS_SPELL_AMP_OVERRIDES,
    _STAGED_AMP_BLOCK_ROUTES,
)
from agents.daemon_slayer._ability_base_overrides import (
    _ABILITY_BASE_OVERRIDES,
    _FORM_FIELDS,
)
from agents.daemon_slayer._ability_overrides import (
    DAMAGE_TYPE_OVERRIDES,
    NON_DAMAGE_BLOCKS,
)
from agents.daemon_slayer._ability_wiki_form_damage import WIKI_FORM_DAMAGE_ENTRIES
from agents.daemon_slayer.abilities import AbilitiesSnapshot

Key = tuple[str, str, int]

REGISTRIES: dict[str, Iterable[Key]] = {
    "_ABILITY_AMP_OVERRIDES": _ABILITY_AMP_OVERRIDES,
    "_CROSS_SPELL_AMP_OVERRIDES": _CROSS_SPELL_AMP_OVERRIDES,
    "_STAGED_AMP_BLOCK_ROUTES": _STAGED_AMP_BLOCK_ROUTES,
    "_ABILITY_BASE_OVERRIDES": _ABILITY_BASE_OVERRIDES,
    "DAMAGE_TYPE_OVERRIDES": DAMAGE_TYPE_OVERRIDES,
    "NON_DAMAGE_BLOCKS": NON_DAMAGE_BLOCKS,
    "WIKI_FORM_DAMAGE_ENTRIES": tuple(
        (e.champion_id, e.key, e.form_index) for e in WIKI_FORM_DAMAGE_ENTRIES
    ),
}

# (registry, key) -> why the entry deliberately targets a non-served form.
NON_SERVED_EXCEPTIONS: dict[tuple[str, Key], str] = {
    ("_ABILITY_AMP_OVERRIDES", ("Jayce", "W", 1)): (
        "Hyper Charge amp is authored INERT (0.0); served Jayce W is form 0"
    ),
    ("_STAGED_AMP_BLOCK_ROUTES", ("Hwei", "Q", 2)): (
        "Severing Bolt route; reached via form_index={'Q': 2}, served Q is form 1"
    ),
    ("_ABILITY_BASE_OVERRIDES", ("Qiyana", "Q", 0)): (
        "Edge of Ixtal data fix; served Qiyana Q is form 1 (own entry)"
    ),
}


@pytest.fixture(scope="module")
def ab() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load()


def _dangling(ab: AbilitiesSnapshot, keys: Iterable[Key]) -> list[Key]:
    out: list[Key] = []
    for champ, key, form_index in keys:
        if not ab.has_champion(champ):
            out.append((champ, key, form_index))
            continue
        forms = ab.get_abilities(champ).get(key) or ()
        if not 0 <= form_index < len(forms):
            out.append((champ, key, form_index))
    return out


def _non_served(keys: Iterable[Key]) -> list[Key]:
    return [
        (champ, key, form_index)
        for champ, key, form_index in keys
        if registries.get_form_index_for(champ)[0].get(key, 0) != form_index
    ]


def _attrs(ab: AbilitiesSnapshot, champ: str, key: str, form_index: int) -> set[str]:
    form = ab.get_abilities(champ)[key][form_index]
    return {b.attribute for b in form.damage_blocks}


# ---------------------------------------------------------------------------
# S144-D-198 - no entry dangles.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_registry_is_not_empty(name: str) -> None:
    # An empty registry would make every sweep below pass vacuously.
    assert list(REGISTRIES[name]), name


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_every_entry_resolves_to_a_live_form(ab, name: str) -> None:
    assert _dangling(ab, REGISTRIES[name]) == []


def test_dangling_detector_is_not_vacuous(ab) -> None:
    probes = [
        ("NoSuchChampion", "Q", 0),
        ("Quinn", "Z", 0),
        ("Quinn", "R", 99),
        ("Quinn", "R", -1),
    ]
    assert _dangling(ab, probes) == probes
    assert _dangling(ab, [("Quinn", "R", 0)]) == []


def test_cross_spell_source_key_exists(ab) -> None:
    for (champ, _key, _fi), entry in _CROSS_SPELL_AMP_OVERRIDES.items():
        assert entry.source_key in ab.get_abilities(champ), (champ, entry.source_key)


# ---------------------------------------------------------------------------
# S144-D-199 - a non-served target form is a pinned, reasoned exception.
# ---------------------------------------------------------------------------


def test_non_served_entries_are_exactly_the_pinned_exceptions() -> None:
    measured = {
        (name, k) for name, keys in REGISTRIES.items() for k in _non_served(keys)
    }
    assert measured == set(NON_SERVED_EXCEPTIONS)


def test_every_exception_states_a_reason() -> None:
    for pair, reason in NON_SERVED_EXCEPTIONS.items():
        assert reason.strip(), pair


def test_non_served_detector_is_not_vacuous() -> None:
    # Hwei serves Q form 1 and W form 3 (champion_form_index.json); Quinn
    # carries no override, so every Quinn key serves form 0.
    assert registries.get_form_index_for("Hwei")[0].get("Q") == 1
    assert _non_served([("Hwei", "Q", 0), ("Quinn", "R", 1)]) == [
        ("Hwei", "Q", 0),
        ("Quinn", "R", 1),
    ]
    assert _non_served([("Hwei", "Q", 1), ("Quinn", "R", 0)]) == []


def test_wiki_form_entries_land_on_the_served_form_by_name(ab) -> None:
    # The served form's live name must be the one the entry records, so a
    # Meraki form reorder cannot move the authored block onto another form.
    for e in WIKI_FORM_DAMAGE_ENTRIES:
        served = registries.get_form_index_for(e.champion_id)[0].get(e.key, 0)
        assert e.form_index == served, (e.champion_id, e.key)
        form = ab.get_abilities(e.champion_id)[e.key][e.form_index]
        assert form.name == e.form_name, (e.champion_id, e.key, form.name)


# ---------------------------------------------------------------------------
# S144-D-200 - every named block attribute exists on its target form.
# ---------------------------------------------------------------------------


def test_non_damage_block_attributes_exist(ab) -> None:
    missing = {
        k: sorted(set(names) - _attrs(ab, *k))
        for k, names in NON_DAMAGE_BLOCKS.items()
        if set(names) - _attrs(ab, *k)
    }
    assert missing == {}


def test_base_override_block_attributes_exist(ab) -> None:
    missing = []
    for k, entries in _ABILITY_BASE_OVERRIDES.items():
        have = _attrs(ab, *k)
        for entry in entries:
            if entry.field in _FORM_FIELDS:
                continue
            if entry.attribute not in have:
                missing.append((k, entry.attribute))
    assert missing == []


def test_attribute_detector_is_not_vacuous(ab) -> None:
    have = _attrs(ab, "Hwei", "Q", 2)
    assert "Maximum Damage" in have
    assert "No Such Attribute" not in have


# ---------------------------------------------------------------------------
# S144-D-201 - every served-form override is in range.
# ---------------------------------------------------------------------------


def _form_index_overrides() -> list[Key]:
    table = registries._load_form_index_table().get("champions") or {}
    return [
        (champ, str(key).upper(), int(idx))
        for champ, mapping in table.items()
        for key, idx in mapping.items()
    ]


def test_form_index_table_is_not_empty() -> None:
    assert _form_index_overrides()


def test_every_form_index_override_is_in_range(ab) -> None:
    # An out-of-range index is not an error in compute_ability_dps: it serves
    # form 0 instead, which would also blind the served-form sweep above.
    assert _dangling(ab, _form_index_overrides()) == []
