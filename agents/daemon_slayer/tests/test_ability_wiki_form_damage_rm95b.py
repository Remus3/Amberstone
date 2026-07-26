"""RM-95b residual - the ONE form-level wiki damage block that is genuinely missing.

MEASURED POPULATION (2026-07-26). The RM-95b B2 adjudication walked the live
16.14.1 ``--full-roster`` wiki extract down to three forms that name a real
damage label and carry no ``attribute_kind == "damage"`` block: Jayce W Hyper
Charge, Mel W Rebuttal, Quinn R Skystrike. The ROADMAP row called all three
"three hand-authored registry entries". Re-measured against the live snapshot
and the live evaluator, that count is **1, not 3**:

* **Jayce W Hyper Charge** - NOT a data gap. Meraki already ships the leveling
  numbers (``Damage Modifier``, ``[70, 78, 86, 94, 102, 110] % AD``), and the
  form the engine serves for Jayce W is form 0 ``Lightning Field``, which
  scores a real 380.0 raw at L13. Hyper Charge is the Mercury-Cannon alternate
  and is an AUTO-ATTACK rider (a percent of AD on each of 3 attacks), so
  crediting it on the ability clock is exactly the face-value credit the RM-86
  spec fences ("a BOOLEAN gate is decisively refuted; the conversion vector
  must be CONTINUOUS"). Modelling change, not a missing number.
* **Mel W Rebuttal** - NOT a data gap either. Meraki ships the numbers
  (``Replicated Projectile Damage Modifier``, ``[40, 45, 50, 55, 60] %`` of the
  original damage plus ``5 % per 100 AP``). The quantity is a percentage of an
  incoming projectile whose magnitude no registry carries, which is the same
  assumed-ally-stat-prior class that closed RM-90 S3 BLOCKED-UNFALSIFIABLE. It
  correctly evaluates to 0.0 today.
* **Quinn R Skystrike** - REAL. The form carries ZERO blocks of any kind, and
  the form the engine actually serves for Quinn R (form 0, ``Behind Enemy
  Lines``) carries only a movement-speed modifier. So Quinn's ultimate
  contributes ``raw_damage_per_cast == 0.0`` to her own ability lane while the
  wiki states a plain base-plus-bonus-AD formula.

SOURCE (live, fetched 2026-07-26 from the same host + endpoint
``tools/daemon_slayer_wiki_ability_extract.py:108-110`` uses):

    Template:Data Quinn/Skystrike
    |leveling = {{st|Physical Damage|{{ap|60 to 120}} {{as|(+ 35% '''bonus''' AD)}}}}
    |damagetype = Physical

This file pins the build and, just as importantly, pins the two REFUTATIONS in
code so the "population is 3" reading cannot be re-derived from the ROADMAP
prose alone.
"""

from __future__ import annotations

import pytest

from agents.daemon_slayer import _registries as registries
from agents.daemon_slayer._ability_wiki_form_damage import (
    WIKI_FORM_DAMAGE_ENTRIES,
    apply_wiki_form_damage,
)
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.data_loader import DataSnapshot

# The sweep-standard tanky target (ROADMAP PROBE HAZARD block).
TARGET = dict(
    target_armor=100.0,
    target_mr=60.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


@pytest.fixture(scope="module")
def ab_off() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load(apply_wiki_form_damage=False)


@pytest.fixture(scope="module")
def ab_on() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load(apply_wiki_form_damage=True)


def _spell(snap: DataSnapshot, ab: AbilitiesSnapshot, champ: str, key: str) -> dict:
    result = compute_ability_dps(
        snap, champ, 13, item_ids=[], mode="SR", abilities_snapshot=ab, **TARGET
    ).to_dict()
    for row in result["per_spell"]:
        if row["key"] == key:
            return row
    raise AssertionError(f"{champ} has no {key} row")


# --------------------------------------------------------------------------
# RED 1 - the served form for Quinn R scores zero without the seam.
# --------------------------------------------------------------------------


def test_quinn_r_scores_zero_with_seam_off(snap, ab_off):
    row = _spell(snap, ab_off, "Quinn", "R")
    assert row["form_name"] == "Behind Enemy Lines"
    assert row["raw_damage_per_cast"] == 0.0
    assert row["dps"] == 0.0


# --------------------------------------------------------------------------
# RED 2 - with the seam ON the wiki formula is served on the R clock.
# --------------------------------------------------------------------------


def test_quinn_r_scores_the_wiki_formula_with_seam_on(snap, ab_on):
    row = _spell(snap, ab_on, "Quinn", "R")
    # An ult ranks at 6 / 11 / 16, so at L13 R sits at rank 2 (the row's
    # 0-based ``rank`` field reads 1) and the served base term is _ramp()[1]
    # == 90.0. Bonus AD with no items is 0, so the asserted quantity is the
    # base term alone - a data assertion, not a stat-table assertion.
    assert row["rank"] == 1
    assert row["raw_damage_per_cast"] == pytest.approx(90.0)
    assert row["dps"] > 0.0


def test_registry_entry_matches_the_quoted_wiki_leveling_line():
    assert len(WIKI_FORM_DAMAGE_ENTRIES) == 1, (
        "population is 1, not 3 - see the module docstring for the two "
        "refutations (Jayce W auto-rider, Mel W reflection-of-unknown)"
    )
    entry = WIKI_FORM_DAMAGE_ENTRIES[0]
    assert (entry.champion_id, entry.key, entry.form_index) == ("Quinn", "R", 0)
    assert entry.block["attribute_kind"] == "damage"
    # {{ap|60 to 120}} over an ult's 3 ranks, linearly expanded.
    assert entry.block["base"] == [60.0, 90.0, 120.0]
    # (+ 35% bonus AD), rank-flat.
    assert entry.block["bonus_ad_pct"] == [35.0, 35.0, 35.0]


# --------------------------------------------------------------------------
# SERVED-FORM GUARD - the entry targets the form the engine actually reads.
# --------------------------------------------------------------------------


def test_quinn_r_served_form_index_is_still_zero():
    """If the form registry ever routes Quinn R elsewhere this entry silently
    stops being read, so pin the assumption rather than leaving it implicit."""
    overrides, source = registries.get_form_index_for("Quinn")
    assert overrides.get("R", 0) == 0
    assert source == "default"


def test_entry_lands_at_block_index_zero(ab_on):
    """``_select_blocks`` reads ``damage_blocks[0]`` under the default
    ``block_strategy="first"`` and ``get_block_index_for("Quinn")`` carries no
    override, so the authored block must be PREPENDED, not appended."""
    overrides, _ = registries.get_block_index_for("Quinn")
    assert overrides == {}
    form = ab_on.champions["Quinn"]["R"][0]
    blocks = list(form.damage_blocks)
    assert blocks[0].attribute_kind == "damage"
    assert "Skystrike" in blocks[0].attribute
    assert tuple(blocks[0].base) == (60.0, 90.0, 120.0)
    assert tuple(blocks[0].bonus_ad_pct) == (35.0, 35.0, 35.0)
    # the pre-existing movement-speed modifier is preserved, just demoted
    assert [b.attribute for b in blocks[1:]] == ["Total Movement Speed Increase"]


# --------------------------------------------------------------------------
# DEFAULT-OFF + BLAST RADIUS.
# --------------------------------------------------------------------------


def test_seam_defaults_off(snap):
    """The shipped default must be byte-identical to an explicit False."""
    default = AbilitiesSnapshot.load()
    row = _spell(snap, default, "Quinn", "R")
    assert row["raw_damage_per_cast"] == 0.0


def test_every_other_champion_is_byte_identical(ab_off, ab_on):
    off_ids = sorted(ab_off.champions)
    assert sorted(ab_on.champions) == off_ids
    moved = []
    for cid in off_ids:
        for key, forms_off in ab_off.champions[cid].items():
            forms_on = ab_on.champions[cid][key]
            blocks_off = [list(f.damage_blocks) for f in forms_off]
            blocks_on = [list(f.damage_blocks) for f in forms_on]
            if blocks_off != blocks_on:
                moved.append((cid, key))
    assert moved == [("Quinn", "R")]


# --------------------------------------------------------------------------
# ANTI-DOUBLE-APPLY - a future Meraki re-extract makes this inert.
# --------------------------------------------------------------------------


def test_entry_does_not_apply_when_a_damage_block_already_exists():
    data = {
        "Quinn": {
            "R": [
                {
                    "name": "Behind Enemy Lines",
                    "damage_blocks": [
                        {"attribute": "Physical Damage", "attribute_kind": "damage",
                         "base": [1.0, 2.0, 3.0]}
                    ],
                }
            ]
        }
    }
    applied = apply_wiki_form_damage(data)
    assert applied == ()
    assert len(data["Quinn"]["R"][0]["damage_blocks"]) == 1
    assert data["Quinn"]["R"][0]["damage_blocks"][0]["base"] == [1.0, 2.0, 3.0]


def test_entry_is_a_noop_when_the_champion_is_absent():
    data: dict = {}
    assert apply_wiki_form_damage(data) == ()
    assert data == {}


def test_applying_twice_does_not_stack_the_block():
    data = {"Quinn": {"R": [{"name": "Behind Enemy Lines", "damage_blocks": []}]}}
    assert apply_wiki_form_damage(data) == ("Quinn/R",)
    assert apply_wiki_form_damage(data) == ()
    assert len(data["Quinn"]["R"][0]["damage_blocks"]) == 1


# --------------------------------------------------------------------------
# THE TWO REFUTATIONS, pinned in code.
# --------------------------------------------------------------------------


def test_jayce_w_is_not_a_data_gap(snap, ab_off):
    """The served form already scores real damage, and Hyper Charge's numbers
    are already on disk - so there is nothing to author."""
    row = _spell(snap, ab_off, "Jayce", "W")
    assert row["form_name"] == "Lightning Field"
    assert row["raw_damage_per_cast"] > 0.0
    hyper = ab_off.champions["Jayce"]["W"][1]
    assert hyper.name == "Hyper Charge"
    assert hyper.damage_blocks[0].attribute_kind == "modifier"
    mods = hyper.damage_blocks[0].raw_modifiers[0]
    assert mods["values"] == [70, 78, 86, 94, 102, 110]
    assert all(u == "% AD" for u in mods["units"])
    assert not any(e.champion_id == "Jayce" for e in WIKI_FORM_DAMAGE_ENTRIES)


def test_mel_w_is_a_reflection_with_no_prior(snap, ab_off):
    """Rebuttal's numbers are on disk as a percent OF THE ORIGINAL DAMAGE; no
    registry carries an incoming-damage prior, so 0.0 is the correct read."""
    row = _spell(snap, ab_off, "Mel", "W")
    assert row["form_name"] == "Rebuttal"
    assert row["raw_damage_per_cast"] == 0.0
    block = ab_off.champions["Mel"]["W"][0].damage_blocks[0]
    assert block.attribute_kind == "modifier"
    assert block.raw_modifiers[0]["values"] == [40, 45, 50, 55, 60]
    assert all(
        "of the original damage" in u for u in block.raw_modifiers[0]["units"]
    )
    assert not any(e.champion_id == "Mel" for e in WIKI_FORM_DAMAGE_ENTRIES)
