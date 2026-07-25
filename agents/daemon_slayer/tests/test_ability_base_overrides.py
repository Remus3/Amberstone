"""A-03 / RM-81 - stale ability base-damage override registry.

Pins the six champions characterized at
``docs/research/DS_ABILITY_SHAPING_NOTES.md:562-571`` (the shape-corrected
re-run table), the DEFAULT-OFF contract, and the negative control that every
champion NOT in the registry is byte-identical with the flag ON.

The expected numbers below are hard-coded in the TEST, deliberately NOT read
back out of the registry - a test that only re-reads the registry it is
supposed to be checking proves nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.daemon_slayer import ability_dps
from agents.daemon_slayer._ability_base_overrides import (
    _ABILITY_BASE_OVERRIDES,
    AbilityBaseOverride,
    apply_base_overrides,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.data_loader import DataSnapshot

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# (champion, key, form_index, block attribute, stale leading series, corrected)
# Stale endpoints from DS_ABILITY_SHAPING_NOTES.md:566-571; the intermediate
# ranks are the values literally on disk in
# data/daemon_slayer/16.14.1/champion_abilities.json. Corrected series are the
# linear ramp across the same rank count (the wiki "{{ap|X to Y}}" semantics
# the notes' method section, :528-532, states the harness used).
_EXPECTED: tuple[tuple[str, str, int, str, tuple, tuple], ...] = (
    (
        "Mordekaiser",
        "Q",
        0,
        "Magic Damage",
        (80.0, 117.647059, 155.294118, 192.941176, 230.588235),
        (80.0, 115.0, 150.0, 185.0, 220.0),
    ),
    (
        "Naafiri",
        "R",
        0,
        "Physical Damage",
        (150.0, 250.0, 350.0),
        (150.0, 225.0, 300.0),
    ),
    (
        "Heimerdinger",
        "W",
        0,
        "Initial Rocket Magic Damage",
        (40.0, 65.0, 90.0, 115.0, 140.0),
        (50.0, 75.0, 100.0, 125.0, 150.0),
    ),
    (
        "Azir",
        "W",
        0,
        "Magic Damage",
        (50.0, 67.647059, 85.294118, 102.941176, 120.588235),
        (50.0, 65.0, 80.0, 95.0, 110.0),
    ),
    (
        "Malzahar",
        "W",
        0,
        "Magic Damage",
        (17.0, 22.5, 28.0, 33.5, 39.0),
        (12.0, 14.0, 16.0, 18.0, 20.0),
    ),
    (
        "Ahri",
        "R",
        0,
        "Magic Damage",
        (60.0, 90.0, 120.0),
        (75.0, 125.0, 175.0),
    ),
)

_TOL = 1e-2


def _patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _spell(result, key: str):
    """The ``AbilitySpellDps`` for ``key`` (``per_spell`` is a tuple, not a map)."""
    for spell in result.per_spell:
        if spell.key == key:
            return spell
    raise AssertionError(f"no spell {key!r} in per_spell")


def _first_base(form, attribute: str) -> tuple[float, ...]:
    for block in form.damage_blocks:
        if block.attribute == attribute:
            assert block.base is not None
            return block.base
    raise AssertionError(f"no block {attribute!r} on {form.key}")


@pytest.fixture(scope="module")
def snap_off() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load(data_root=_DATA_ROOT)


@pytest.fixture(scope="module")
def snap_on() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load(
        data_root=_DATA_ROOT, apply_ability_base_overrides=True
    )


def test_registry_covers_exactly_the_six_documented_champions() -> None:
    assert {k[0] for k in _ABILITY_BASE_OVERRIDES} == {
        "Mordekaiser",
        "Naafiri",
        "Heimerdinger",
        "Azir",
        "Malzahar",
        "Ahri",
    }
    assert len(_ABILITY_BASE_OVERRIDES) == 6
    for entries in _ABILITY_BASE_OVERRIDES.values():
        for entry in entries:
            assert isinstance(entry, AbilityBaseOverride)
            # Every override must cite its DS_ABILITY_SHAPING_NOTES.md line.
            assert "DS_ABILITY_SHAPING_NOTES.md:" in entry.source


def test_stale_values_are_still_on_disk_verbatim() -> None:
    """The registry is anchored to the extract; if a re-extract fixes a number
    this test fails loudly rather than the override double-correcting."""
    path = _DATA_ROOT / _patch() / "champion_abilities.json"
    data = json.loads(path.read_text(encoding="utf-8"))["data"]
    for cid, key, form_index, attribute, stale, _corrected in _EXPECTED:
        blocks = data[cid][key][form_index]["damage_blocks"]
        found = [b for b in blocks if b.get("attribute") == attribute]
        assert found, f"{cid} {key} block {attribute!r} missing from the extract"
        base = found[0]["base"]
        assert len(base) >= len(stale)
        for i, want in enumerate(stale):
            assert abs(base[i] - want) <= _TOL, f"{cid} {key} rank {i}"


def test_default_is_off_and_still_stale(snap_off: AbilitiesSnapshot) -> None:
    for cid, key, form_index, attribute, stale, _corrected in _EXPECTED:
        base = _first_base(snap_off.get_ability(cid, key, form_index), attribute)
        for i, want in enumerate(stale):
            assert abs(base[i] - want) <= _TOL, f"{cid} {key} rank {i} moved with flag OFF"


def test_flag_on_corrects_all_six(snap_on: AbilitiesSnapshot) -> None:
    for cid, key, form_index, attribute, _stale, corrected in _EXPECTED:
        base = _first_base(snap_on.get_ability(cid, key, form_index), attribute)
        for i, want in enumerate(corrected):
            assert abs(base[i] - want) <= _TOL, f"{cid} {key} rank {i} not corrected"


def test_trailing_per_level_tail_is_preserved(
    snap_off: AbilitiesSnapshot, snap_on: AbilitiesSnapshot
) -> None:
    """Mordekaiser Q / Azir W / Malzahar W store an 18-element base - a 5-entry
    rank series CONCATENATED with a 13-entry per-level tail (the shape defect at
    DS_ABILITY_SHAPING_NOTES.md:592-617). Only the rank head is overridden."""
    for cid, key, attribute in (
        ("Mordekaiser", "Q", "Magic Damage"),
        ("Azir", "W", "Magic Damage"),
        ("Malzahar", "W", "Magic Damage"),
    ):
        off = _first_base(snap_off.get_ability(cid, key, 0), attribute)
        on = _first_base(snap_on.get_ability(cid, key, 0), attribute)
        assert len(off) == 18
        assert len(on) == len(off)
        assert off[5:] == on[5:]


def test_negative_control_every_other_form_is_byte_identical(
    snap_off: AbilitiesSnapshot, snap_on: AbilitiesSnapshot
) -> None:
    """Champions NOT in the registry - and the untouched keys/forms of the six -
    must be identical objects field-for-field with the flag ON."""
    keys = set(_ABILITY_BASE_OVERRIDES)
    off = {(c, k, f.form_index): f for c, k, f in snap_off.iter_forms()}
    on = {(c, k, f.form_index): f for c, k, f in snap_on.iter_forms()}
    assert set(off) == set(on)
    moved = set()
    for ident, form_off in off.items():
        if form_off != on[ident]:
            moved.add(ident)
    assert moved == keys
    # And the count of NON-registry forms is large (the control is not vacuous).
    assert len(off) - len(moved) > 900


def test_non_registry_champion_dps_unchanged() -> None:
    """Ziggs (an ability-route champion the notes list as SENSITIVE harness
    control at :546) must score identically with the flag ON."""
    data = DataSnapshot.load(data_root=_DATA_ROOT)
    for champ in ("Ziggs", "Zed", "Lux"):
        a = ability_dps.compute_ability_dps(
            data,
            champ,
            level=18,
            target_armor=100.0,
            target_mr=70.0,
            abilities_snapshot=AbilitiesSnapshot.load(data_root=_DATA_ROOT),
        )
        b = ability_dps.compute_ability_dps(
            data,
            champ,
            level=18,
            target_armor=100.0,
            target_mr=70.0,
            abilities_snapshot=AbilitiesSnapshot.load(
                data_root=_DATA_ROOT, apply_ability_base_overrides=True
            ),
        )
        assert a.total_ability_dps == b.total_ability_dps


@pytest.mark.parametrize(
    "cid,key",
    [
        ("Mordekaiser", "Q"),
        ("Naafiri", "R"),
        ("Heimerdinger", "W"),
        ("Azir", "W"),
        ("Malzahar", "W"),
        ("Ahri", "R"),
    ],
)
def test_ability_dps_moves_for_each_of_the_six(
    cid: str, key: str, snap_off: AbilitiesSnapshot, snap_on: AbilitiesSnapshot
) -> None:
    """Level 18 = every spell at max rank, where all six drifts are non-zero.
    (At rank 0 Mordekaiser Q / Naafiri R / Azir W are unchanged by construction
    - the drift is in the per-rank slope, not the rank-1 value.)"""
    data = DataSnapshot.load(data_root=_DATA_ROOT)
    before = ability_dps.compute_ability_dps(
        data, cid, level=18, target_armor=100.0, target_mr=70.0,
        abilities_snapshot=snap_off,
    )
    after = ability_dps.compute_ability_dps(
        data, cid, level=18, target_armor=100.0, target_mr=70.0,
        abilities_snapshot=snap_on,
    )
    assert _spell(before, key).raw_damage_per_cast != _spell(after, key).raw_damage_per_cast
    assert _spell(before, key).dps != _spell(after, key).dps


def test_rank_zero_is_exact_for_naafiri_r(
    snap_off: AbilitiesSnapshot, snap_on: AbilitiesSnapshot
) -> None:
    """Naafiri R rank 0 is 150 in BOTH series - the correction is 350 -> 300 at
    max rank only. Level 6 (R rank 0) must therefore be byte-identical, which
    proves the override is a slope fix and not a blanket rescale."""
    data = DataSnapshot.load(data_root=_DATA_ROOT)
    before = ability_dps.compute_ability_dps(
        data, "Naafiri", level=6, target_armor=100.0, target_mr=70.0,
        abilities_snapshot=snap_off,
    )
    after = ability_dps.compute_ability_dps(
        data, "Naafiri", level=6, target_armor=100.0, target_mr=70.0,
        abilities_snapshot=snap_on,
    )
    assert _spell(before, "R").raw_damage_per_cast == _spell(after, "R").raw_damage_per_cast
    assert _spell(before, "R").dps == _spell(after, "R").dps


def test_override_is_skipped_when_the_extract_is_already_correct(
    snap_on: AbilitiesSnapshot,
) -> None:
    """Anti-double-correction guard: feed a form whose base ALREADY equals the
    corrected series and assert the hook is a no-op."""
    form = snap_on.get_ability("Ahri", "R", 0)
    again = apply_base_overrides("Ahri", "R", form)
    assert again is form
