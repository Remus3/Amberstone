"""Immolate family - CATALOG-DERIVED sweep plus the damage-routing invariants.

DS audit-loop iteration (2026-08-14), immolate lane. The audit verdict was
NO-CHANGE: every one of the seven Immolate ids in the shipped 16.15.1 catalog
is registered, carries the family dedup key, ticks once per second, and states
the magnitude its source states. Nothing in the engine moved. This file is the
DURABLE half of that audit - the same pattern R153 / R160 shipped for the
penetration catalogs, applied to the one immolate axis that had no sweep.

WHY A SWEEP AND NOT MORE PINS. Immolate already has two guards and they are
both keyed on HARDCODED id tuples:

* ``test_meraki_formula_audit_pipeline_a.py`` pins the three SR magnitudes
  (Sunfire 20 + 1% bonus HP, Hollow Radiance 15 + 1% bonus HP, Bami's flat 15)
  against the Meraki passive formulas.
* ``test_immolate_provenance_notes.py`` pins the four ARENA ids - the three
  mirrors absent from Meraki plus ``223069``, whose formula Meraki files under
  the row's ``active`` key with an EMPTY ``passives`` list.

Neither re-derives the family from the item catalog, so an EIGHTH Immolate item
shipped by a future patch - or a new Arena mirror of an existing one - would be
credited nothing at all and no test in the repo would notice. That is exactly
the failure class the R153 docstring calls "pen stated in prose, omitted from
the structured block": a registration gap, not a magnitude drift. The sweep
below re-reads the catalog on every run, so the gap fails here immediately.

SOURCE OF TRUTH, and the carve-out that applies. Immolate magnitudes are
PASSIVE FORMULAS, so the Meraki bulk is authoritative for them (the DDragon
``<stats>`` carve-out covers PEN / LETHALITY / RESIST-REDUCTION magnitudes,
which Immolate is not). Verified at 16.15.1:

* ``3068`` Sunfire Aegis - "20 (+ 1% bonus health) magic damage every second".
* ``6660`` Bami's Cinder - "15 magic damage every second", FLAT: HP scaling
  starts at the upgrades, not the component.
* ``6664`` Hollow Radiance - "15 (+ 1% bonus health) magic damage every
  second".
* ``223069`` Void Immolation - "20 (+ 1.5% of your MAXIMUM health) TRUE damage
  every second". Both halves differ from its SR relatives: TRUE rather than
  magical, and MAXIMUM rather than bonus health. Filed under ``active``.
* ``223068`` / ``226660`` / ``226664`` are absent from Meraki at every patch on
  disk and their DDragon descriptions leave the magnitude placeholder empty, so
  they inherit their SR twin's formula. That inheritance is the pre-existing
  documented position; this file does not re-open it, it only pins that the ids
  stay registered and stay in the dedup family.

The catalog is read from whichever layout is present: ``data/meta`` in the repo,
the per-patch vendored copy in the Share handoff package. Both were measured to
yield an identical swept set (706 items, the same seven ids).

WHAT IS DELIBERATELY NOT RE-ASSERTED. Exact magnitudes stay in
``test_meraki_formula_audit_pipeline_a.py`` and the Arena provenance notes stay
in ``test_immolate_provenance_notes.py``; duplicating either would add
maintenance and catch nothing. The 5-second activation window on ``223069``
against the SR items' 3 seconds is a KNOWN and documented modelling gap -
``PeriodicProc`` carries no window field, so both are modelled at full-rotation
uptime and crediting the difference needs a schema lift. It is not asserted here
because it is not true of the engine today.
"""

from __future__ import annotations

import itertools
import json
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import MAGICAL, TRUE, CallContext
from agents.daemon_slayer.dps import _armor_factor, _periodic_proc_dps
from agents.daemon_slayer.effects import collect_effects

_REPO_ROOT = Path(__file__).resolve().parents[3]
_META_CATALOG = _REPO_ROOT / "data" / "meta" / "ddragon_items.json"
_PATCH_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

_PROC_NAME = "Immolate"
_DEDUP_KEY = "immolate"

# The census measured against the 16.15.1 catalog. Pinned so that a patch which
# ADDS an Immolate item fails here (registration gap) instead of shipping an
# uncredited aura, and one which REMOVES a mirror fails instead of leaving a
# stale registry row. Update it together with the ITEM_EFFECTS rows.
_EXPECTED_SWEEP = ("223068", "223069", "226660", "226664", "3068", "6660", "6664")

# The single TRUE-damage member. Its damage type and its MAXIMUM-health basis
# are the two properties that separate it from every other member, and both are
# easy to "normalize" away by mistake, so both are pinned below.
_TRUE_DAMAGE_ID = "223069"

# Scale off caster BONUS health (Sunfire / Hollow Radiance and their mirrors).
_BONUS_HP_SCALING = ("3068", "223068", "6664", "226664")

# Flat at the component tier - no health scaling of any kind.
_FLAT_MAGNITUDE = ("6660", "226660")


def _catalog() -> dict:
    """The full DDragon item catalog, from whichever layout is on disk."""
    if _META_CATALOG.is_file():
        raw = _META_CATALOG.read_text(encoding="utf-8")
    else:
        patch = (_PATCH_ROOT / "current.txt").read_text(encoding="utf-8").strip()
        raw = (_PATCH_ROOT / patch / "items.json").read_text(encoding="utf-8")
    return json.loads(raw)["data"]


def _swept_immolate_ids() -> dict[str, str]:
    """item_id -> name for every catalog row whose description names Immolate.

    Re-derived on every run. ``223069`` is titled "Void Immolation" and names
    the passive "Immolate" in its description like the rest, so a description
    scan catches it without a name special-case.
    """
    return {
        iid: entry.get("name", "")
        for iid, entry in _catalog().items()
        if _PROC_NAME in (entry.get("description") or "")
    }


def _ctx(**overrides) -> CallContext:
    """A CallContext with the three required fields supplied.

    ``base_ad`` / ``bonus_ad`` / ``level`` have no defaults on the dataclass;
    Immolate reads none of them, so their values are arbitrary but must be
    present for construction.
    """
    base = {"base_ad": 60.0, "bonus_ad": 0.0, "level": 13}
    base.update(overrides)
    return CallContext(**base)


def _immolate_proc(item_id: str):
    """The single Immolate PeriodicProc on a registered family member."""
    effect = ITEM_EFFECTS[item_id]
    procs = [p for p in effect.periodics if p.name == _PROC_NAME]
    assert len(procs) == 1, f"{item_id} must carry exactly one Immolate proc"
    return procs[0]


class ImmolateCatalogSweepTests(unittest.TestCase):
    """The registration half - re-derived from the catalog every run."""

    def test_sweep_matches_the_measured_census(self) -> None:
        self.assertEqual(sorted(_swept_immolate_ids()), sorted(_EXPECTED_SWEEP))

    def test_both_catalog_layouts_are_not_required_simultaneously(self) -> None:
        # The resolver must work off the layout that is actually present; a
        # missing data/meta must fall back to the per-patch vendored copy.
        self.assertTrue(
            _META_CATALOG.is_file() or (_PATCH_ROOT / "current.txt").is_file(),
            "neither catalog layout is available - the sweep cannot run",
        )

    def test_every_swept_id_is_registered_with_an_immolate_proc(self) -> None:
        for iid, name in sorted(_swept_immolate_ids().items()):
            with self.subTest(item_id=iid, name=name):
                effect = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(
                    effect,
                    f"{iid} ({name}) states Immolate in the catalog but has no "
                    "ITEM_EFFECTS row - its aura is credited NOTHING",
                )
                self.assertIn(
                    _PROC_NAME,
                    [p.name for p in effect.periodics],
                    f"{iid} ({name}) is registered but carries no Immolate proc",
                )

    def test_every_swept_id_carries_the_family_dedup_key(self) -> None:
        # Riot enforces Immolate as a unique passive. A member missing the key
        # would tick a second time in a build that owns two of them.
        for iid in sorted(_swept_immolate_ids()):
            with self.subTest(item_id=iid):
                self.assertEqual(ITEM_EFFECTS[iid].unique_passive_key, _DEDUP_KEY)

    def test_dedup_key_has_no_members_outside_the_sweep(self) -> None:
        keyed = {
            iid
            for iid, eff in ITEM_EFFECTS.items()
            if eff.unique_passive_key == _DEDUP_KEY
        }
        self.assertEqual(keyed, set(_swept_immolate_ids()))

    def test_every_immolate_proc_ticks_once_per_second(self) -> None:
        for iid in sorted(_swept_immolate_ids()):
            with self.subTest(item_id=iid):
                proc = _immolate_proc(iid)
                self.assertEqual(proc.every_n_seconds, 1.0)
                self.assertEqual(proc.every_n_attacks, 0)


class ImmolateDamageTypePartitionTests(unittest.TestCase):
    """Void Immolation is TRUE damage; every other member is magical."""

    def test_true_damage_row_is_exactly_void_immolation(self) -> None:
        true_ids = {
            iid
            for iid in _swept_immolate_ids()
            if _immolate_proc(iid).damage_type == TRUE
        }
        self.assertEqual(true_ids, {_TRUE_DAMAGE_ID})

    def test_every_other_member_is_magical(self) -> None:
        for iid in sorted(_swept_immolate_ids()):
            if iid == _TRUE_DAMAGE_ID:
                continue
            with self.subTest(item_id=iid):
                self.assertEqual(_immolate_proc(iid).damage_type, MAGICAL)


class ImmolateScalingBasisTests(unittest.TestCase):
    """Which health pool each member reads - the basis, not the coefficient.

    Property-style: vary ONE pool at a time and assert the proc does or does
    not respond. This pins the max-HP vs bonus-HP distinction on ``223069``
    without duplicating the exact-magnitude pins in pipeline_a.
    """

    _HP_VALUES = (0.0, 1000.0, 2500.0)

    def test_void_immolation_reads_maximum_health_not_bonus(self) -> None:
        proc = _immolate_proc(_TRUE_DAMAGE_ID)
        # Responds to caster_max_hp ...
        seen = {
            proc.resolve_damage(_ctx(caster_max_hp=hp)) for hp in self._HP_VALUES
        }
        self.assertEqual(len(seen), len(self._HP_VALUES))
        # ... and is INVARIANT under caster_bonus_hp.
        for hp in self._HP_VALUES:
            with self.subTest(caster_bonus_hp=hp):
                self.assertAlmostEqual(
                    proc.resolve_damage(_ctx(caster_bonus_hp=hp)),
                    proc.resolve_damage(_ctx(caster_bonus_hp=0.0)),
                    places=9,
                )

    def test_sr_members_read_bonus_health_not_maximum(self) -> None:
        for iid in _BONUS_HP_SCALING:
            proc = _immolate_proc(iid)
            with self.subTest(item_id=iid):
                seen = {
                    proc.resolve_damage(_ctx(caster_bonus_hp=hp))
                    for hp in self._HP_VALUES
                }
                self.assertEqual(len(seen), len(self._HP_VALUES))
                for hp in self._HP_VALUES:
                    self.assertAlmostEqual(
                        proc.resolve_damage(_ctx(caster_max_hp=hp)),
                        proc.resolve_damage(_ctx(caster_max_hp=0.0)),
                        places=9,
                    )

    def test_component_tier_is_flat_in_both_pools(self) -> None:
        for iid in _FLAT_MAGNITUDE:
            proc = _immolate_proc(iid)
            with self.subTest(item_id=iid):
                for hp in self._HP_VALUES:
                    self.assertAlmostEqual(
                        proc.resolve_damage(
                            _ctx(caster_bonus_hp=hp, caster_max_hp=hp)
                        ),
                        proc.resolve_damage(_ctx()),
                        places=9,
                    )

    def test_every_member_is_linear_in_target_count(self) -> None:
        # Immolate is an AoE aura - every member multiplies by
        # targets_in_rotation, so N targets is exactly N times one target.
        for iid in sorted(_swept_immolate_ids()):
            proc = _immolate_proc(iid)
            one = proc.resolve_damage(
                _ctx(caster_bonus_hp=1800.0, caster_max_hp=3000.0)
            )
            for targets in (2.0, 3.0, 5.0):
                with self.subTest(item_id=iid, targets=targets):
                    self.assertAlmostEqual(
                        proc.resolve_damage(
                            _ctx(
                                caster_bonus_hp=1800.0,
                                caster_max_hp=3000.0,
                                targets_in_rotation=targets,
                            )
                        ),
                        one * targets,
                        places=6,
                    )


class ImmolateFamilyDedupTests(unittest.TestCase):
    """The dedup key is present - prove the CONSUMER acts on it."""

    def test_every_pair_collapses_to_one_effect(self) -> None:
        for a, b in itertools.combinations(sorted(_swept_immolate_ids()), 2):
            with self.subTest(pair=(a, b)):
                self.assertEqual(len(collect_effects([a, b])), 1)

    def test_whole_family_in_one_build_collapses_to_one_effect(self) -> None:
        self.assertEqual(len(collect_effects(list(_EXPECTED_SWEEP))), 1)


class ImmolateResistRoutingTests(unittest.TestCase):
    """The DPS consumer must route each member against the right resist.

    ``dps._periodic_proc_dps`` selects ``resist = 0.0`` for TRUE, the target's
    armor for PHYSICAL and the target's MR otherwise. Immolate has no physical
    member, so the two live invariants are: the true member ignores BOTH
    resists, and the magical members respond to MR and ignore armor.
    """

    _DURATION = 10.0
    _RESISTS = (0.0, 40.0, 120.0, 250.0)

    def _dps(self, item_id: str, *, armor: float, mr: float) -> float:
        ctx = _ctx(
            caster_bonus_hp=1800.0, caster_max_hp=3000.0, target_armor=armor,
            target_mr=mr,
        )
        return _periodic_proc_dps(
            collect_effects([item_id]),
            0.0,
            self._DURATION,
            armor,
            mr,
            1.0,
            ctx,
        )

    def test_true_immolate_ignores_both_resists(self) -> None:
        baseline = self._dps(_TRUE_DAMAGE_ID, armor=0.0, mr=0.0)
        self.assertGreater(baseline, 0.0)
        for armor in self._RESISTS:
            for mr in self._RESISTS:
                with self.subTest(armor=armor, mr=mr):
                    self.assertAlmostEqual(
                        self._dps(_TRUE_DAMAGE_ID, armor=armor, mr=mr),
                        baseline,
                        places=9,
                    )

    def test_magical_immolate_is_mitigated_by_mr_exactly(self) -> None:
        for iid in sorted(set(_swept_immolate_ids()) - {_TRUE_DAMAGE_ID}):
            baseline = self._dps(iid, armor=0.0, mr=0.0)
            with self.subTest(item_id=iid):
                self.assertGreater(baseline, 0.0)
                for mr in self._RESISTS:
                    self.assertAlmostEqual(
                        self._dps(iid, armor=0.0, mr=mr),
                        baseline * _armor_factor(mr),
                        places=9,
                    )

    def test_magical_immolate_ignores_target_armor(self) -> None:
        for iid in sorted(set(_swept_immolate_ids()) - {_TRUE_DAMAGE_ID}):
            baseline = self._dps(iid, armor=0.0, mr=60.0)
            with self.subTest(item_id=iid):
                for armor in self._RESISTS:
                    self.assertAlmostEqual(
                        self._dps(iid, armor=armor, mr=60.0), baseline, places=9
                    )


if __name__ == "__main__":
    unittest.main()
