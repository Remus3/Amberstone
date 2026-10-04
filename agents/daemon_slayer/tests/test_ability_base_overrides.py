"""A-03 / RM-81 - stale ability base-damage override registry.

Pins the six champions characterized at
``docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:562-571`` (the shape-corrected
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
    # RM-480 residual (2026-10-03): V26.15 re-tuned Hounds' Pursuit to
    # 125 / 200 / 275 (wiki-measured), so the A-03 target 150 : 300 is itself
    # stale. The on-disk guard is unchanged.
    (
        "Naafiri",
        "R",
        0,
        "Physical Damage",
        (150.0, 250.0, 350.0),
        (125.0, 200.0, 275.0),
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


_RM81_SIX = {"Mordekaiser", "Naafiri", "Heimerdinger", "Azir", "Malzahar", "Ahri"}
# RM-480: the seven HIGH stale-ability rows of the 16.18.1 ratio-aware sweep.
_RM480_SEVEN = {"Poppy", "Qiyana", "Thresh", "Kennen", "Chogath", "Cassiopeia", "Leblanc"}


def test_registry_covers_exactly_the_documented_champions() -> None:
    assert {k[0] for k in _ABILITY_BASE_OVERRIDES} == _RM81_SIX | _RM480_SEVEN
    # 13 + Qiyana Q form 1 (RM-480 residual).
    assert len(_ABILITY_BASE_OVERRIDES) == 14
    for (cid, _key, _form), entries in _ABILITY_BASE_OVERRIDES.items():
        for entry in entries:
            assert isinstance(entry, AbilityBaseOverride)
            if cid == "Naafiri":
                # RM-480 residual: re-targeted to the V26.15 wiki values.
                assert "wiki" in entry.source
            elif cid in _RM81_SIX:
                # The RM-81 six cite their DS_ABILITY_SHAPING_NOTES.md line.
                assert "DS_ABILITY_SHAPING_NOTES.md:" in entry.source
                assert entry.field == "base"
            else:
                # The RM-480 seven cite the staleness report they came from.
                assert "ability_staleness.json" in entry.source


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


def test_naafiri_r_rank_zero_now_moves(
    snap_off: AbilitiesSnapshot, snap_on: AbilitiesSnapshot
) -> None:
    """RM-480 residual: the A-03 entry was a slope fix (rank 0 = 150 in both
    series). V26.15 cut rank 0 to 125 and the bonus AD ratio 120 -> 100, so the
    re-targeted entry moves Naafiri R at level 6 (R rank 0) too - DOWNWARD."""
    data = DataSnapshot.load(data_root=_DATA_ROOT)
    before = ability_dps.compute_ability_dps(
        data, "Naafiri", level=6, target_armor=100.0, target_mr=70.0,
        abilities_snapshot=snap_off,
    )
    after = ability_dps.compute_ability_dps(
        data, "Naafiri", level=6, target_armor=100.0, target_mr=70.0,
        abilities_snapshot=snap_on,
    )
    assert _spell(after, "R").raw_damage_per_cast < _spell(before, "R").raw_damage_per_cast


def test_override_is_skipped_when_the_extract_is_already_correct(
    snap_on: AbilitiesSnapshot,
) -> None:
    """Anti-double-correction guard: feed a form whose base ALREADY equals the
    corrected series and assert the hook is a no-op."""
    form = snap_on.get_ability("Ahri", "R", 0)
    again = apply_base_overrides("Ahri", "R", form)
    assert again is form


# --------------------------------------------------------------------------
# RM-480 - the registry now overrides per-rank RATIO fields as well as base.
#
# (champion, key, form_index, block attribute, field, stale on disk, corrected)
# Stale = data/daemon_slayer/16.18.1/champion_abilities.json verbatim.
# Corrected = the per-rank lists RENDERED by wiki.leagueoflegends.com on
# 2026-09-21 (read-only fetch), which agree with the wiki column of
# data/daemon_slayer/16.18.1/ability_staleness.json at both endpoints.
_RM480: tuple[tuple[str, str, int, str, str, tuple, tuple], ...] = (
    ("Poppy", "Q", 0, "Physical Damage", "bonus_ad_pct",
     (100.0,) * 5, (75.0,) * 5),
    ("Poppy", "Q", 0, "Physical Damage", "target_max_hp_pct",
     (9.0,) * 5, (7.0, 7.5, 8.0, 8.5, 9.0)),
    ("Poppy", "Q", 0, "Total Physical Damage", "bonus_ad_pct",
     (200.0,) * 5, (150.0,) * 5),
    ("Poppy", "Q", 0, "Total Physical Damage", "target_max_hp_pct",
     (18.0,) * 5, (14.0, 15.0, 16.0, 17.0, 18.0)),
    ("Qiyana", "Q", 0, "Physical Damage", "base",
     (60.0, 90.0, 120.0, 150.0, 180.0), (80.0, 110.0, 140.0, 170.0, 200.0)),
    ("Qiyana", "Q", 0, "Reduced Damage", "base",
     (45.0, 67.5, 90.0, 112.5, 135.0), (60.0, 82.5, 105.0, 127.5, 150.0)),
    ("Thresh", "E", 0, "Magic Damage", "ap_pct",
     (70.0,) * 5, (60.0,) * 5),
    ("Thresh", "E", 0, "Magic Damage", "base",
     (75.0, 120.0, 165.0, 210.0, 255.0), (65.0, 110.0, 155.0, 200.0, 245.0)),
    ("Kennen", "R", 0, "Magic Damage Per Bolt", "ap_pct",
     (22.5,) * 3, (25.0,) * 3),
    ("Kennen", "R", 0, "Magic Damage Per Bolt", "base",
     (40.0, 75.0, 110.0), (40.0, 80.0, 120.0)),
    ("Kennen", "R", 0, "Total Single-Target Damage", "ap_pct",
     (168.75,) * 3, (187.5,) * 3),
    ("Kennen", "R", 0, "Total Single-Target Damage", "base",
     (300.0, 562.5, 825.0), (300.0, 600.0, 900.0)),
    ("Chogath", "E", 0, "Magic Damage", "base",
     (20.0, 40.0, 60.0, 80.0, 100.0), (30.0, 50.0, 70.0, 90.0, 110.0)),
    ("Chogath", "E", 0, "Total Magic Damage", "base",
     (60.0, 120.0, 180.0, 240.0, 300.0), (90.0, 150.0, 210.0, 270.0, 330.0)),
    ("Cassiopeia", "E", 0, "Bonus Magic Damage", "ap_pct",
     (55.0,) * 5, (45.0,) * 5),
    ("Cassiopeia", "E", 0, "Bonus Magic Damage", "base",
     (20.0, 40.0, 60.0, 80.0, 100.0), (20.0, 45.0, 70.0, 95.0, 120.0)),
    ("Leblanc", "R", 0, "Magic Damage", "ap_pct",
     (75.0,) * 3, (90.0,) * 3),
    ("Leblanc", "R", 0, "Magic Damage", "base",
     (150.0, 300.0, 450.0), (150.0, 315.0, 480.0)),
)


def _block(form, attribute: str):
    for block in form.damage_blocks:
        if block.attribute == attribute:
            return block
    raise AssertionError(f"no block {attribute!r} on {form.key}")


def _close(got, want) -> bool:
    return got is not None and len(got) >= len(want) and all(
        abs(got[i] - w) <= _TOL for i, w in enumerate(want)
    )


def test_poppy_q_ratio_override_applies_with_flag_on(snap_on: AbilitiesSnapshot) -> None:
    """The first RM-480 red: a RATIO field (not base) is corrected."""
    blk = _block(snap_on.get_ability("Poppy", "Q", 0), "Physical Damage")
    assert _close(blk.bonus_ad_pct, (75.0,) * 5)
    assert _close(blk.target_max_hp_pct, (7.0, 7.5, 8.0, 8.5, 9.0))
    # Base 30..130 is current on the wiki and must NOT move.
    assert _close(blk.base, (30.0, 55.0, 80.0, 105.0, 130.0))


@pytest.mark.parametrize(
    "cid", ["Poppy", "Qiyana", "Thresh", "Kennen", "Chogath", "Cassiopeia", "Leblanc"]
)
def test_rm480_stale_guard_on_disk_and_corrected_with_flag_on(
    cid: str, snap_off: AbilitiesSnapshot, snap_on: AbilitiesSnapshot
) -> None:
    path = _DATA_ROOT / _patch() / "champion_abilities.json"
    data = json.loads(path.read_text(encoding="utf-8"))["data"]
    rows = [r for r in _RM480 if r[0] == cid]
    assert rows
    for _c, key, fi, attr, fld, stale, corrected in rows:
        disk = [b for b in data[cid][key][fi]["damage_blocks"] if b.get("attribute") == attr]
        assert disk and _close(disk[0].get(fld), stale), f"{cid} {key} {attr} {fld} on disk"
        off = getattr(_block(snap_off.get_ability(cid, key, fi), attr), fld)
        assert _close(off, stale), f"{cid} {key} {attr} {fld} moved with flag OFF"
        on = getattr(_block(snap_on.get_ability(cid, key, fi), attr), fld)
        assert _close(on, corrected), f"{cid} {key} {attr} {fld} not corrected"
        assert len(on) == len(off)


def test_leblanc_r_all_seven_blocks_corrected_by_index(
    snap_off: AbilitiesSnapshot, snap_on: AbilitiesSnapshot
) -> None:
    """RM-480 residual: every Mimic block, addressed by BLOCK INDEX because
    "Total Magic Damage" appears twice (block 2 Sigil of Malice total, block 6
    Ethereal Chains total). Wiki-measured 2026-10-03; AP ratios unchanged
    except Distortion (block 3)."""
    want_base = {
        0: (70.0, 150.0, 230.0), 1: (140.0, 300.0, 460.0), 2: (210.0, 450.0, 690.0),
        3: (150.0, 315.0, 480.0), 4: (70.0, 150.0, 230.0), 5: (140.0, 300.0, 460.0),
        6: (210.0, 450.0, 690.0),
    }
    want_ap = {0: 40.0, 1: 80.0, 2: 120.0, 3: 90.0, 4: 40.0, 5: 85.0, 6: 125.0}
    off = snap_off.get_ability("Leblanc", "R", 0).damage_blocks
    on = snap_on.get_ability("Leblanc", "R", 0).damage_blocks
    assert on[2].attribute == on[6].attribute == "Total Magic Damage"
    for i, base in want_base.items():
        assert _close(on[i].base, base), (i, on[i].base)
        assert _close(on[i].ap_pct, (want_ap[i],) * 3), (i, on[i].ap_pct)
        assert off[i].base[0] == base[0] and off[i].base[2] != base[2]


def test_qiyana_q_empowered_form_corrected(
    snap_off: AbilitiesSnapshot, snap_on: AbilitiesSnapshot
) -> None:
    """RM-480 residual: Elemental Wrath (form 1), wiki-measured 2026-10-03."""
    want = {
        "Physical Damage": (80.0, 110.0, 140.0, 170.0, 200.0),
        "Reduced Damage": (60.0, 82.5, 105.0, 127.5, 150.0),
        "Increased Damage": (128.0, 176.0, 224.0, 272.0, 320.0),
        "Subsequent Increased Damage": (108.0, 148.5, 189.0, 229.5, 270.0),
    }
    off = snap_off.get_ability("Qiyana", "Q", 1)
    on = snap_on.get_ability("Qiyana", "Q", 1)
    for attr, base in want.items():
        assert _close(_block(on, attr).base, base), attr
        assert not _close(_block(off, attr).base, base), attr
        assert _block(on, attr).bonus_ad_pct == _block(off, attr).bonus_ad_pct


def test_naafiri_r_ratio_and_packmate_corrected(snap_on: AbilitiesSnapshot) -> None:
    """V26.15 (wiki 2026-10-03): 125/200/275 (+100% bonus AD); per packmate
    12.5/20/27.5 (+10% bonus AD)."""
    form = snap_on.get_ability("Naafiri", "R", 0)
    blk = _block(form, "Physical Damage")
    assert _close(blk.base, (125.0, 200.0, 275.0))
    assert _close(blk.bonus_ad_pct, (100.0,) * 3)
    pack = _block(form, "Physical Damage per Packmate")
    assert _close(pack.base, (12.5, 20.0, 27.5))
    assert _close(pack.bonus_ad_pct, (10.0,) * 3)


def test_kennen_r_cooldown_is_flat_120_with_flag_on(
    snap_off: AbilitiesSnapshot, snap_on: AbilitiesSnapshot
) -> None:
    """RM-480 residual: V26.04 "Cooldown increased to 120 seconds at all ranks
    from 120 / 100 / 80" (wiki patch history, fetched 2026-10-03). The detector
    row [120, 120] is TRUE, not the parse error LEDGER 1453 called it. A
    FORM-level field, so the entry carries no block attribute."""
    assert snap_off.get_ability("Kennen", "R", 0).cooldown == (120.0, 100.0, 80.0)
    assert snap_on.get_ability("Kennen", "R", 0).cooldown == (120.0, 120.0, 120.0)


def test_form_field_entry_shape_is_enforced() -> None:
    with pytest.raises(ValueError):
        # cooldown is form-level: a block attribute is meaningless there.
        AbilityBaseOverride(attribute="Magic Damage", stale=(1.0,), corrected=(2.0,),
                            source="x", note="x", field="cooldown")
    with pytest.raises(ValueError):
        # a block field needs a block attribute.
        AbilityBaseOverride(attribute="", stale=(1.0,), corrected=(2.0,),
                            source="x", note="x", field="base")


def test_rm81_six_output_unchanged_by_the_ratio_lift(snap_on: AbilitiesSnapshot) -> None:
    """Every non-base field of the six original rows is untouched by the lift."""
    for cid, key, fi, attr, _stale, _corrected in _EXPECTED:
        if cid == "Naafiri":
            # RM-480 residual: V26.15 moved the ratio too (pinned in
            # test_naafiri_r_ratio_and_packmate_corrected).
            continue
        on = _block(snap_on.get_ability(cid, key, fi), attr)
        raw = AbilitiesSnapshot.load(data_root=_DATA_ROOT).get_ability(cid, key, fi)
        off = _block(raw, attr)
        from dataclasses import replace

        assert replace(on, base=off.base) == off


# ---- synthetic unit tests of apply_base_overrides --------------------------

def _fake_form():
    from agents.daemon_slayer.abilities import DamageBlock

    blk = DamageBlock(
        attribute="Magic Damage",
        attribute_kind="damage",
        base=(10.0, 20.0, 30.0),
        ap_pct=(50.0, 50.0, 50.0),
    )
    other = DamageBlock(
        attribute="Other Damage",
        attribute_kind="damage",
        base=(1.0, 2.0, 3.0),
        ap_pct=(10.0, 10.0, 10.0),
    )
    form = AbilitiesSnapshot.load(data_root=_DATA_ROOT).get_ability("Ahri", "R", 0)
    from dataclasses import replace

    return replace(form, damage_blocks=(blk, other))


def _entry(attr, fld, stale, corrected):
    return AbilityBaseOverride(
        attribute=attr, stale=stale, corrected=corrected,
        source="synthetic ability_staleness.json", note="test", field=fld,
    )


def test_mixed_base_and_ratio_on_one_block(monkeypatch) -> None:
    from agents.daemon_slayer import _ability_base_overrides as mod

    form = _fake_form()
    monkeypatch.setitem(mod._ABILITY_BASE_OVERRIDES, ("Ahri", "R", form.form_index), (
        _entry("Magic Damage", "base", (10.0, 20.0, 30.0), (11.0, 22.0, 33.0)),
        _entry("Magic Damage", "ap_pct", (50.0,) * 3, (60.0,) * 3),
    ))
    out = apply_base_overrides("Ahri", "R", form)
    assert out.damage_blocks[0].base == (11.0, 22.0, 33.0)
    assert out.damage_blocks[0].ap_pct == (60.0,) * 3
    assert out.damage_blocks[1] == form.damage_blocks[1]


def test_partial_mismatch_skips_the_whole_form(monkeypatch) -> None:
    from agents.daemon_slayer import _ability_base_overrides as mod

    form = _fake_form()
    monkeypatch.setitem(mod._ABILITY_BASE_OVERRIDES, ("Ahri", "R", form.form_index), (
        _entry("Magic Damage", "base", (10.0, 20.0, 30.0), (11.0, 22.0, 33.0)),
        # Stale guard does NOT match what is loaded (50 on disk).
        _entry("Other Damage", "ap_pct", (99.0,) * 3, (12.0,) * 3),
    ))
    assert apply_base_overrides("Ahri", "R", form) is form


def test_unknown_field_raises() -> None:
    with pytest.raises(ValueError):
        _entry("Magic Damage", "not_a_field", (1.0,), (2.0,))
    with pytest.raises(ValueError):
        # A real DamageBlock field that is not a ratio key the detector knows.
        _entry("Magic Damage", "raw_modifiers", (1.0,), (2.0,))


def test_allowed_fields_match_the_detector_ratio_keys() -> None:
    import dataclasses
    import sys

    from agents.daemon_slayer import _ability_base_overrides as mod
    from agents.daemon_slayer.abilities import DamageBlock

    tools = _REPO_ROOT / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import ds_wiki_staleness_check as det

    assert set(mod._ALLOWED_FIELDS) == {"base", *det._RATIO_KEYS}
    real = {f.name for f in dataclasses.fields(DamageBlock)}
    assert set(mod._ALLOWED_FIELDS) <= real
