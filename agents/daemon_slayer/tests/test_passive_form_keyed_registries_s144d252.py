"""S144-D-252..255 - the passive (champion, key, form_index)-keyed override
registries resolve to real forms, every load-time entry is really injected,
and every entry's block label is a name its live ability uses.

WHY. ``test_form_keyed_ability_registries_s144d198.py`` guards the seven
ability-amp / base / damage-type registries keyed on
``(champion_id, key, form_index)``. Fourteen more registries share that key
shape and had no such guard:

* load-time injectors - ``abilities.AbilitiesSnapshot.load`` appends a
  synthetic block to the form whose ``(cid, key, form.form_index)`` matches,
  behind an opt-in flag: ``_PASSIVE_DAMAGE_OVERRIDES`` and
  ``_ALL_OUT_BONUS_OVERRIDES`` (only onto a ``parse_status == "no_damage"``
  form), ``_PASSIVE_HEAL_OVERRIDES`` (only when the form has no heal block)
  and ``_PASSIVE_SHIELD_OVERRIDES`` (only when it has no shield block);
* ``_PASSIVE_REFLECT_OVERRIDES``, read by ``reflect_entry(champion_id)``
  with the default ``key="W", form_index=0`` from ``dps.py`` and ``burst.py``;
* champion aggregators, which sum every row of the champion and read the key
  only for a ``rank_scaled`` value: the cc-mitigation, spell-shield,
  ally-grant, ally flat-HP, health, mitigation, resist, revive and
  survival-window registries.

Each of those gates is silent: an entry whose champion, key or form does not
exist, whose form already parses the block kind, or whose key is not the one
``reflect_entry`` asks for is simply never read. And the injected block takes
the entry's ``attribute`` as its name, so the label is what a reader of the
form sees.

* S144-D-252: every entry of all fourteen names a live champion, a live key
  and an in-range form.
* S144-D-253: with every injector flag ON, every load-time entry's block is
  on its form, except an entry whose form already parses damage, which must
  be one the AA on-hit seam reads straight from the registry
  (``_AA_ROUTED_ON_HIT_KEYS``) - measured: Kayle E, Kog'Maw W. No injected
  heal / shield label is one ``ability_hps`` skips as a meta block, and the
  only load-time entry on a non-served form is Karma W 1 (Renewal), which a
  consumer reaches by routing W to form 1.
* S144-D-254: every reflect row is the one ``reflect_entry(champion_id)``
  returns.
* S144-D-255: every entry's ``attribute`` is its live form's name, or a
  phrase in that form's live Meraki text (a sub-mechanic: Kai'Sa P Caustic
  Wounds, Poppy W Stubborn to a Fault, ...). Two heal rows failed: Rakan Q
  was labelled "Boisterous Bravado" and Yuumi P "Bop 'n' Block", neither in
  the live text (Gleaming Quill / Feline Friendship).

MEASURED 2026-11-09 (live snapshot, patch 16.22.1, ENGINE 1.291.0): 3 + 4 + 4
+ 7 + 34 + 1 + 24 + 3 + 5 + 1 + 22 + 2 + 10 + 10 = 130 entries, ZERO dangling,
ZERO meta labels, every injector entry injected but the two AA-routed rows,
one non-served load-time entry, and the two stale labels above (fixed in
``_passive_heal_overrides.py``; the heal values are unchanged). Each checker
also runs on planted defects so an empty or blind checker cannot pass.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import pytest

from agents.daemon_slayer import _registries as registries
from agents.daemon_slayer._champion_cc_mitigation_overrides import (
    _CHAMPION_CC_MITIGATION_OVERRIDES,
)
from agents.daemon_slayer._champion_spell_shield_overrides import (
    _CHAMPION_SPELL_SHIELD_OVERRIDES,
)
from agents.daemon_slayer._passive_ally_grant_overrides import (
    _ALLY_FLAT_HP_GRANT_OVERRIDES,
    _PASSIVE_ALLY_GRANT_OVERRIDES,
)
from agents.daemon_slayer._passive_damage_overrides import (
    _AA_ROUTED_ON_HIT_KEYS,
    _ALL_OUT_BONUS_OVERRIDES,
    _PASSIVE_DAMAGE_OVERRIDES,
)
from agents.daemon_slayer._passive_heal_overrides import _PASSIVE_HEAL_OVERRIDES
from agents.daemon_slayer._passive_health_overrides import (
    _PASSIVE_HEALTH_OVERRIDES,
)
from agents.daemon_slayer._passive_mitigation_overrides import (
    _PASSIVE_MITIGATION_OVERRIDES,
)
from agents.daemon_slayer._passive_reflect_overrides import (
    _PASSIVE_REFLECT_OVERRIDES,
    reflect_entry,
)
from agents.daemon_slayer._passive_resist_overrides import (
    _PASSIVE_RESIST_OVERRIDES,
)
from agents.daemon_slayer._passive_revive_overrides import (
    _PASSIVE_REVIVE_OVERRIDES,
)
from agents.daemon_slayer._passive_shield_overrides import (
    _PASSIVE_SHIELD_OVERRIDES,
)
from agents.daemon_slayer._passive_survival_window_overrides import (
    _PASSIVE_SURVIVAL_WINDOW_OVERRIDES,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.ability_hps import _is_meta_heal_shield

Key = tuple[str, str, int]

REGISTRIES: dict[str, dict[Key, Any]] = {
    "_CHAMPION_CC_MITIGATION_OVERRIDES": _CHAMPION_CC_MITIGATION_OVERRIDES,
    "_CHAMPION_SPELL_SHIELD_OVERRIDES": _CHAMPION_SPELL_SHIELD_OVERRIDES,
    "_PASSIVE_ALLY_GRANT_OVERRIDES": _PASSIVE_ALLY_GRANT_OVERRIDES,
    "_ALLY_FLAT_HP_GRANT_OVERRIDES": _ALLY_FLAT_HP_GRANT_OVERRIDES,
    "_PASSIVE_DAMAGE_OVERRIDES": _PASSIVE_DAMAGE_OVERRIDES,
    "_ALL_OUT_BONUS_OVERRIDES": _ALL_OUT_BONUS_OVERRIDES,
    "_PASSIVE_HEAL_OVERRIDES": _PASSIVE_HEAL_OVERRIDES,
    "_PASSIVE_HEALTH_OVERRIDES": _PASSIVE_HEALTH_OVERRIDES,
    "_PASSIVE_MITIGATION_OVERRIDES": _PASSIVE_MITIGATION_OVERRIDES,
    "_PASSIVE_REFLECT_OVERRIDES": _PASSIVE_REFLECT_OVERRIDES,
    "_PASSIVE_RESIST_OVERRIDES": _PASSIVE_RESIST_OVERRIDES,
    "_PASSIVE_REVIVE_OVERRIDES": _PASSIVE_REVIVE_OVERRIDES,
    "_PASSIVE_SHIELD_OVERRIDES": _PASSIVE_SHIELD_OVERRIDES,
    "_PASSIVE_SURVIVAL_WINDOW_OVERRIDES": _PASSIVE_SURVIVAL_WINDOW_OVERRIDES,
}

# Load-time injectors: registry -> the attribute_kind of the block it appends.
INJECTORS: dict[str, str] = {
    "_PASSIVE_DAMAGE_OVERRIDES": "damage",
    "_ALL_OUT_BONUS_OVERRIDES": "damage",
    "_PASSIVE_HEAL_OVERRIDES": "heal",
    "_PASSIVE_SHIELD_OVERRIDES": "shield",
}

# (registry, key) -> why a load-time entry deliberately sits on a non-served form.
NON_SERVED_INJECTOR_EXCEPTIONS: dict[tuple[str, Key], str] = {
    ("_PASSIVE_HEAL_OVERRIDES", ("Karma", "W", 1)): (
        "Renewal, the Mantra-empowered W; a consumer routes W -> 1 through "
        "form_index_overrides, the served Karma W is form 0"
    ),
}


@pytest.fixture(scope="module")
def ab() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load()


@pytest.fixture(scope="module")
def ab_injected() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load(
        apply_passive_damage=True,
        apply_passive_heal=True,
        apply_passive_shield=True,
        apply_all_out_bonus=True,
    )


@pytest.fixture(scope="module")
def raw_forms(ab: AbilitiesSnapshot) -> dict[str, Any]:
    path = ab.data_root / ab.patch / "champion_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


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


def _not_injected(
    base: AbilitiesSnapshot,
    injected: AbilitiesSnapshot,
    reg: dict[Key, Any],
    kind: str,
) -> list[Key]:
    out: list[Key] = []
    for (champ, key, form_index), entry in reg.items():
        before = base.get_abilities(champ)[key][form_index].damage_blocks
        after = injected.get_abilities(champ)[key][form_index].damage_blocks
        added = [b for b in after if b not in before]
        if not any(
            b.attribute == entry.attribute and b.attribute_kind == kind
            for b in added
        ):
            out.append((champ, key, form_index))
    return out


def _stale_labels(
    ab: AbilitiesSnapshot,
    raw_forms: dict[str, Any],
    reg: dict[Key, Any],
) -> list[tuple[Key, str]]:
    out: list[tuple[Key, str]] = []
    for (champ, key, form_index), entry in reg.items():
        label = entry.attribute
        live_name = ab.get_abilities(champ)[key][form_index].name
        live_text = json.dumps(
            raw_forms[champ][key][form_index], ensure_ascii=False,
        ).lower()
        # A blank live name would make startswith() pass every label.
        named = bool(live_name) and label.startswith(live_name)
        if not label or (not named and label.lower() not in live_text):
            out.append(((champ, key, form_index), label))
    return out


# ---------------------------------------------------------------------------
# S144-D-252 - no entry dangles.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_registry_is_not_empty(name: str) -> None:
    # An empty registry would make every sweep below pass vacuously.
    assert REGISTRIES[name], name


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_every_entry_resolves_to_a_live_form(ab, name: str) -> None:
    assert _dangling(ab, REGISTRIES[name]) == []


def test_dangling_detector_is_not_vacuous(ab) -> None:
    probes = [
        ("NoSuchChampion", "P", 0),
        ("Rammus", "Z", 0),
        ("Rammus", "W", 9),
        ("Rammus", "W", -1),
    ]
    assert _dangling(ab, probes) == probes
    assert _dangling(ab, [("Rammus", "W", 0)]) == []


# ---------------------------------------------------------------------------
# S144-D-253 - every load-time entry is injected, or read by another seam.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(INJECTORS))
def test_every_injector_entry_lands_on_its_form(ab, ab_injected, name) -> None:
    missed = _not_injected(ab, ab_injected, REGISTRIES[name], INJECTORS[name])
    # The only skip the injectors allow is a form that already parses the
    # kind; such an entry must be one the AA on-hit seam reads directly.
    for champ, key, form_index in missed:
        form = ab.get_abilities(champ)[key][form_index]
        assert name == "_PASSIVE_DAMAGE_OVERRIDES", (name, champ, key)
        assert form.parse_status != "no_damage", (champ, key, form_index)
        assert (champ, key, form_index) in _AA_ROUTED_ON_HIT_KEYS, (
            champ, key, form_index,
        )


def test_the_aa_routed_skips_are_the_measured_two(ab, ab_injected) -> None:
    missed = _not_injected(
        ab, ab_injected, _PASSIVE_DAMAGE_OVERRIDES, "damage",
    )
    assert sorted(missed) == [("Kayle", "E", 0), ("KogMaw", "W", 0)]


def test_injection_detector_is_not_vacuous(ab) -> None:
    # Against the un-injected snapshot every entry reads as missed.
    reg = {("Rammus", "W", 0): _PASSIVE_REFLECT_OVERRIDES[("Rammus", "W", 0)]}
    assert _not_injected(ab, ab, reg, "damage") == [("Rammus", "W", 0)]
    shield = dict(list(_PASSIVE_SHIELD_OVERRIDES.items())[:1])
    assert _not_injected(ab, ab, shield, "shield") == list(shield)


@pytest.mark.parametrize(
    "name", ["_PASSIVE_HEAL_OVERRIDES", "_PASSIVE_SHIELD_OVERRIDES"],
)
def test_no_injected_heal_or_shield_label_is_a_meta_block(name) -> None:
    # ability_hps._select_kind_blocks drops a meta-labelled block, so such an
    # entry would be injected and then never scored.
    assert [
        k for k, e in REGISTRIES[name].items() if _is_meta_heal_shield(e.attribute)
    ] == []
    assert _is_meta_heal_shield("Health Regen per hit")


def test_non_served_injector_entries_are_the_pinned_exceptions() -> None:
    measured = {
        (name, k)
        for name in INJECTORS
        for k in REGISTRIES[name]
        if registries.get_form_index_for(k[0])[0].get(k[1], 0) != k[2]
    }
    assert measured == set(NON_SERVED_INJECTOR_EXCEPTIONS)
    for pair, reason in NON_SERVED_INJECTOR_EXCEPTIONS.items():
        assert reason.strip(), pair


# ---------------------------------------------------------------------------
# S144-D-254 - every reflect row is reachable through reflect_entry.
# ---------------------------------------------------------------------------


def test_every_reflect_row_is_what_reflect_entry_returns() -> None:
    # dps.py and burst.py call reflect_entry(champion_id) with the default
    # key / form, so a row keyed anywhere else is never read.
    for (champ, key, form_index), entry in _PASSIVE_REFLECT_OVERRIDES.items():
        assert reflect_entry(champ) is entry, (champ, key, form_index)


# ---------------------------------------------------------------------------
# S144-D-255 - every block label is a name the live ability uses.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_every_label_is_a_live_ability_name(ab, raw_forms, name) -> None:
    assert _stale_labels(ab, raw_forms, REGISTRIES[name]) == []


def test_rakan_q_and_yuumi_p_carry_their_live_names() -> None:
    assert _PASSIVE_HEAL_OVERRIDES[("Rakan", "Q", 0)].attribute == "Gleaming Quill"
    assert (
        _PASSIVE_HEAL_OVERRIDES[("Yuumi", "P", 0)].attribute == "Feline Friendship"
    )


def test_label_detector_is_not_vacuous(ab, raw_forms) -> None:
    class _E:
        def __init__(self, attribute: str) -> None:
            self.attribute = attribute

    planted = {
        ("Rakan", "Q", 0): _E("Boisterous Bravado"),
        ("Yuumi", "P", 0): _E("Bop 'n' Block"),
        ("Kaisa", "P", 0): _E("Caustic Wounds"),
        ("Rammus", "W", 0): _E("Defensive Ball Curl"),
        ("Shen", "P", 0): _E(""),
    }
    assert sorted(_stale_labels(ab, raw_forms, planted)) == [
        (("Rakan", "Q", 0), "Boisterous Bravado"),
        (("Shen", "P", 0), ""),
        (("Yuumi", "P", 0), "Bop 'n' Block"),
    ]
