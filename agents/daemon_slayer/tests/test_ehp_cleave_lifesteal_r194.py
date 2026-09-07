"""R194 slice C (RM-116c) - lifesteal credit on Ravenous Hydra Cleave + Crescent.

WHY this test exists: ``ehp._vamp_heal_pool`` prices the wielder's lifesteal off
``AD * AS * window`` - the AUTO-ATTACK throughput and nothing else. Ravenous
Hydra's Cleave (the AoE rider on every basic) and its Ravenous Crescent active
are BOTH additional physical damage that Meraki 16.14.1 explicitly says benefit
from life steal at 100% effectiveness, and neither reaches the heal pool today.
A melee bruiser fighting three enemies therefore reads the sustain of a
single-target duel.

Premise text, ``data/daemon_slayer/16.14.1/items_meraki.json`` items."3074"
(pinned by ``MerakiPremiseTests`` so a patch re-extract that drops the clause
fails loudly rather than silently leaving the credit armed):

  Cleave: "Basic attacks [[on-hit]] deal {{as|{{rd|40% AD|20% AD}}|ad}}
  {{as|physical damage}} to other enemies in a {{tip|cr|icononly = true}} 350
  radius centered around the target. This damage benefits from
  {{as|{{sti|life steal}}}} at 100% effectiveness."

  Ravenous Crescent: "Deal {{as|80% AD}} {{as|physical damage}} to enemies
  within a {{tip|cr|icononly = true}} 450 radius in front of you. This damage
  benefits from {{as|{{sti|life steal}}}} at 100% effectiveness."

The three sibling Tiamat-tree items carry NO such clause, which is why the
credited set is exactly Ravenous Hydra plus its Arena mirror rather than the
whole ``hydra_cleave`` family.

The seam under test is ``compute_ehp(..., assume_cleave_lifesteal=True,
targets_in_rotation=n)``. DEFAULT-OFF is the acceptance bar: with the flag
absent every existing EHP number must be BYTE-IDENTICAL, including when a
caller passes ``targets_in_rotation`` alone.

Coverage classes:

* ``MerakiPremiseTests`` - the vendored Meraki text still says what this seam
  was built on, and the three siblings still do not.
* ``SuffixSweepTests`` - the credited id set is derived by ID SUFFIX (never by
  name) and resolves to exactly the two ids the 16.14.1 index ships.
* ``DefaultOffByteIdenticalTests`` - flag absent (with and without
  ``targets_in_rotation``) reproduces the measured HEAD a8bb2428 baselines.
* ``ArmedCleaveCreditTests`` - armed, the heal pool grows by exactly
  ``lifesteal * (cleave_over_window + crescent)`` and rides the EXISTING
  lifesteal lane (heal_total, which blended_ehp has carried since ENGINE
  1.28.0) rather than inventing a sustain-only one.
* ``NoDoubleCountTests`` - the cleave damage reaches the pool through exactly
  one path; the item carries no ``ItemHeal`` and no vamp stat that would
  re-credit it, and the armed delta equals the closed form exactly.
* ``NarrowSetExclusionTests`` - unrelated proc types (physical burn, tank
  Immolate aura, spellblade, and the three lifesteal-silent hydras) contribute
  zero even when the seam is armed.
* ``ArenaMirrorTests`` - the Arena mirror 223074 is credited on its own id
  (R161 doctrine B) and by the same closed form.
* ``HydraFamilyDedupTests`` - the ``hydra_cleave`` unique-passive family is
  honoured, so a build whose family winner is a lifesteal-silent hydra gets no
  credit.
"""

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.mode_variants import canonical_items
from agents.daemon_slayer.engine import build_champion
from agents.daemon_slayer.ehp import (
    _FIGHT_WINDOW_S,
    VAMP_ELIGIBLE_CLEAVE_ITEM_IDS,
    _cleave_vamp_damage,
    compute_ehp,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
# Resolve the LIVE patch. A hardcoded dir goes stale on every refresh, and only
# the current snapshot is guaranteed on disk, so the pin breaks the
# self-contained guard. The Meraki clause text this seam reads is content-stable
# across a DDragon minor (both patches carry Meraki content 25.15).
_PATCH = (
    _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"
).read_text(encoding="utf-8").strip()
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)
_ITEMS_PATH = _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items.json"

_LIFESTEAL_CLAUSE = "{{as|{{sti|life steal}}}} at 100% effectiveness"

# Measured on HEAD a8bb2428 with the seam NOT yet implemented (the OFF path must
# reproduce these to the last bit): Aatrox L13 [3074, 3072] SR - lifesteal 0.27,
# base_ad 114.75, total ad 259.75, as 0.8463.
_AATROX_ITEMS = ["3074", "3072"]
_AATROX_OFF_HEAL_LIFESTEAL = 356.11880850000006
_AATROX_OFF_HEAL_TOTAL = 356.11880850000006
_AATROX_OFF_SUSTAIN_EHP = 4288.590672867818
_AATROX_OFF_BLENDED_EHP = 4288.590672867818
# Aatrox L13 [223074, 3072] ARENA - the Arena mirror carries the base nominal.
_AATROX_ARENA_ITEMS = ["223074", "3072"]
_AATROX_ARENA_OFF_HEAL_LIFESTEAL = 403.304265

_RAVENOUS_CLEAVE_AD_RATIO = 0.40
_RAVENOUS_CRESCENT_AD_RATIO = 0.80


def _resolved_ad_as(snap, champion, level, items, mode):
    """(base_ad, bonus_ad, attack_speed, lifesteal) straight off the engine."""
    r = build_champion(snap, champion, level, item_ids=items, mode=mode)
    base_ad = float(r.base_stats["ad"])
    total_ad = float(r.stats["ad"])
    return (
        base_ad,
        total_ad - base_ad,
        float(r.stats["as"]),
        float(r.stats.get("lifesteal", 0.0)),
    )


def _expected_cleave_damage(base_ad, bonus_ad, attack_speed, targets):
    """Closed form of the credited pre-mitigation damage over the fight window.

    Independent restatement of the seam's arithmetic - Cleave fires once per
    basic attack against ``max(0, n - 1)`` secondary targets, Crescent lands one
    cast in the window. Written from the Meraki coefficients above rather than
    from the implementation so the two cannot drift together.
    """
    total_ad = base_ad + bonus_ad
    attacks = attack_speed * _FIGHT_WINDOW_S
    cleave = attacks * max(0.0, targets - 1.0) * _RAVENOUS_CLEAVE_AD_RATIO * total_ad
    crescent = _RAVENOUS_CRESCENT_AD_RATIO * total_ad
    return cleave + crescent


class MerakiPremiseTests(unittest.TestCase):
    """The vendored Meraki 16.14.1 text this seam was built on."""

    @classmethod
    def setUpClass(cls):
        cls.items = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))["items"]

    def test_ravenous_cleave_states_full_lifesteal_effectiveness(self):
        passives = self.items["3074"]["passives"]
        cleave = [p for p in passives if p["name"] == "Cleave"]
        self.assertEqual(len(cleave), 1)
        self.assertIn(_LIFESTEAL_CLAUSE, cleave[0]["effects"])

    def test_ravenous_crescent_states_full_lifesteal_effectiveness(self):
        actives = self.items["3074"]["active"]
        crescent = [a for a in actives if a["name"] == "Ravenous Crescent"]
        self.assertEqual(len(crescent), 1)
        self.assertIn(_LIFESTEAL_CLAUSE, crescent[0]["effects"])

    def test_ravenous_coefficients_are_the_engine_values(self):
        passives = self.items["3074"]["passives"]
        cleave = [p for p in passives if p["name"] == "Cleave"][0]
        self.assertIn("40% AD", cleave["effects"])
        actives = self.items["3074"]["active"]
        crescent = [a for a in actives if a["name"] == "Ravenous Crescent"][0]
        self.assertIn("80% AD", crescent["effects"])

    def test_sibling_hydras_carry_no_lifesteal_clause(self):
        # Tiamat 3077, Titanic 3748, Profane 6698 - the rest of the
        # hydra_cleave family. None of them states the clause, which is the
        # whole justification for the narrow credited set.
        for item_id in ("3077", "3748", "6698"):
            entry = self.items[item_id]
            blocks = list(entry.get("passives") or []) + list(entry.get("active") or [])
            for block in blocks:
                self.assertNotIn(
                    _LIFESTEAL_CLAUSE,
                    block["effects"],
                    f"{item_id} {block['name']} unexpectedly claims lifesteal",
                )


class SuffixSweepTests(unittest.TestCase):
    """The credited id set is derived by SUFFIX, never by item name."""

    def test_set_matches_the_index_suffix_sweep(self):
        data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
        data = data.get("data", data)
        # Sweep the CANONICAL set, which is what the engine scores. The snapshot
        # on disk is extracted verbatim and from 16.15.1 carries the throwback
        # band, so a raw sweep also matches 773074 - an item no live mode sells.
        data = canonical_items(data)
        by_suffix = {k for k in data if k.endswith("3074")}
        self.assertEqual(by_suffix, {"3074", "223074"})
        self.assertEqual(VAMP_ELIGIBLE_CLEAVE_ITEM_IDS, by_suffix)

    def test_every_credited_id_has_an_item_effect_entry(self):
        for item_id in VAMP_ELIGIBLE_CLEAVE_ITEM_IDS:
            self.assertIn(item_id, ITEM_EFFECTS)


class DefaultOffByteIdenticalTests(unittest.TestCase):
    """Flag absent -> the pre-seam measured numbers, exactly."""

    def setUp(self):
        self.snap = DataSnapshot.load()

    def test_off_matches_measured_head_baseline(self):
        r = compute_ehp(self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR")
        self.assertEqual(r.heal_lifesteal, _AATROX_OFF_HEAL_LIFESTEAL)
        self.assertEqual(r.heal_total, _AATROX_OFF_HEAL_TOTAL)
        self.assertEqual(r.effective_ehp_with_sustain, _AATROX_OFF_SUSTAIN_EHP)
        self.assertEqual(r.blended_ehp, _AATROX_OFF_BLENDED_EHP)
        self.assertEqual(r.heal_cleave_lifesteal, 0.0)

    def test_targets_in_rotation_alone_does_not_arm_the_seam(self):
        # The whole point of the separate flag: a caller that knows the enemy
        # count must not silently change every existing EHP number.
        r = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR",
            targets_in_rotation=4.0,
        )
        self.assertEqual(r.heal_lifesteal, _AATROX_OFF_HEAL_LIFESTEAL)
        self.assertEqual(r.heal_cleave_lifesteal, 0.0)

    def test_explicit_false_equals_flag_absent(self):
        absent = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR"
        )
        explicit = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR",
            assume_cleave_lifesteal=False, targets_in_rotation=3.0,
        )
        self.assertEqual(explicit.heal_lifesteal, absent.heal_lifesteal)
        self.assertEqual(
            explicit.effective_ehp_with_sustain, absent.effective_ehp_with_sustain
        )

    def test_helper_returns_zero_when_not_armed(self):
        self.assertEqual(
            _cleave_vamp_damage(
                ["3074"], base_ad=100.0, bonus_ad=150.0, attack_speed=0.9,
                targets_in_rotation=5.0,
            ),
            0.0,
        )


class ArmedCleaveCreditTests(unittest.TestCase):
    """Armed -> exactly the Meraki closed form, sustain-only."""

    def setUp(self):
        self.snap = DataSnapshot.load()
        self.base_ad, self.bonus_ad, self.aspd, self.ls = _resolved_ad_as(
            self.snap, "Aatrox", 13, _AATROX_ITEMS, "SR"
        )

    def test_armed_three_targets_credits_cleave_and_crescent(self):
        r = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR",
            assume_cleave_lifesteal=True, targets_in_rotation=3.0,
        )
        expected_damage = _expected_cleave_damage(
            self.base_ad, self.bonus_ad, self.aspd, 3.0
        )
        self.assertAlmostEqual(
            r.heal_cleave_lifesteal, self.ls * expected_damage, places=9
        )
        self.assertAlmostEqual(
            r.heal_lifesteal,
            _AATROX_OFF_HEAL_LIFESTEAL + self.ls * expected_damage,
            places=9,
        )

    def test_armed_single_target_credits_crescent_only(self):
        # The built-in safety: at targets_in_rotation=1.0 the cleave term is
        # exactly 0.0 (max(0, n - 1) = 0), so only the Crescent active lands.
        r = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR",
            assume_cleave_lifesteal=True, targets_in_rotation=1.0,
        )
        crescent_only = _RAVENOUS_CRESCENT_AD_RATIO * (self.base_ad + self.bonus_ad)
        self.assertAlmostEqual(
            r.heal_cleave_lifesteal, self.ls * crescent_only, places=9
        )

    def test_credit_scales_with_target_count(self):
        heals = []
        for n in (1.0, 2.0, 3.0, 5.0):
            r = compute_ehp(
                self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR",
                assume_cleave_lifesteal=True, targets_in_rotation=n,
            )
            heals.append(r.heal_cleave_lifesteal)
        self.assertEqual(heals, sorted(heals))
        self.assertLess(heals[0], heals[-1])

    def test_armed_credit_rides_the_existing_lifesteal_lane(self):
        # MEASURED, not assumed: heal_lifesteal feeds heal_total, and
        # blended_ehp has carried heal_total since ENGINE 1.28.0 (see the
        # ehp.py sustain-blend comment). So the credit moves blended_ehp too -
        # exactly what the AA-throughput half of the same lifesteal stat
        # already does. This asserts the new term inherits that lane rather
        # than inventing a sustain-only one.
        off = compute_ehp(self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR")
        on = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR",
            assume_cleave_lifesteal=True, targets_in_rotation=3.0,
        )
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        self.assertGreater(
            on.effective_ehp_with_sustain, off.effective_ehp_with_sustain
        )
        # The sustain DELTA (vamp-only view) is unchanged: both halves of the
        # lifesteal stat sit inside heal_total, which both sides of that
        # subtraction already account for identically.
        self.assertAlmostEqual(
            on.effective_ehp_with_sustain - on.blended_ehp,
            off.effective_ehp_with_sustain - off.blended_ehp,
            places=9,
        )

    def test_build_without_ravenous_is_an_exact_no_op(self):
        # Arming the seam on a build that carries no credited item must not
        # move a single number - the seam is item-keyed, not build-wide.
        off = compute_ehp(self.snap, "Aatrox", 13, item_ids=["3072"], mode="SR")
        on = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=["3072"], mode="SR",
            assume_cleave_lifesteal=True, targets_in_rotation=5.0,
        )
        self.assertEqual(on.heal_lifesteal, off.heal_lifesteal)
        self.assertEqual(on.heal_cleave_lifesteal, 0.0)


class NoDoubleCountTests(unittest.TestCase):
    """The cleave damage reaches the heal pool through exactly one path."""

    def setUp(self):
        self.snap = DataSnapshot.load()

    def test_ravenous_carries_no_item_heal_entry(self):
        # _collect_heals is the OTHER way HP could enter the pool for this
        # item. Both ids must carry heal=None or the credit would double.
        for item_id in VAMP_ELIGIBLE_CLEAVE_ITEM_IDS:
            self.assertIsNone(ITEM_EFFECTS[item_id].heal, item_id)

    def test_ravenous_grants_no_omnivamp_or_spellvamp(self):
        # The sustain blend adds spellvamp + omnivamp pools off the same AA
        # throughput. If Ravenous granted either, the cleave damage would be
        # priced twice once those lanes are armed.
        r = build_champion(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR"
        )
        self.assertEqual(float(r.stats.get("spellvamp", 0.0)), 0.0)
        self.assertEqual(float(r.stats.get("omnivamp", 0.0)), 0.0)

    def test_item_heal_pool_is_unchanged_by_the_seam(self):
        off = compute_ehp(self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR")
        on = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR",
            assume_cleave_lifesteal=True, targets_in_rotation=3.0,
        )
        self.assertEqual(on.heal_item_total, off.heal_item_total)

    def test_armed_delta_equals_the_closed_form_exactly(self):
        # If any second path were also feeding the pool the delta would exceed
        # the closed form.
        base_ad, bonus_ad, aspd, ls = _resolved_ad_as(
            self.snap, "Aatrox", 13, _AATROX_ITEMS, "SR"
        )
        off = compute_ehp(self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR")
        on = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR",
            assume_cleave_lifesteal=True, targets_in_rotation=3.0,
        )
        delta = on.heal_lifesteal - off.heal_lifesteal
        self.assertAlmostEqual(
            delta,
            ls * _expected_cleave_damage(base_ad, bonus_ad, aspd, 3.0),
            places=9,
        )

    def test_duplicate_ravenous_ids_credit_once(self):
        # The hydra_cleave unique-passive family means a second Ravenous does
        # not proc a second Cleave.
        single = _cleave_vamp_damage(
            ["3074"], base_ad=100.0, bonus_ad=150.0, attack_speed=0.9,
            targets_in_rotation=3.0, assume_cleave_lifesteal=True,
        )
        doubled = _cleave_vamp_damage(
            ["3074", "3074"], base_ad=100.0, bonus_ad=150.0, attack_speed=0.9,
            targets_in_rotation=3.0, assume_cleave_lifesteal=True,
        )
        self.assertGreater(single, 0.0)
        self.assertEqual(doubled, single)


class NarrowSetExclusionTests(unittest.TestCase):
    """Unrelated proc types stay out even with the seam armed."""

    def _damage(self, items):
        return _cleave_vamp_damage(
            items, base_ad=100.0, bonus_ad=150.0, attack_speed=0.9,
            targets_in_rotation=4.0, assume_cleave_lifesteal=True,
        )

    def test_lifesteal_silent_hydras_are_excluded(self):
        # Tiamat 3077, Titanic 3748, Profane 6698, Stridebreaker 6631 - same
        # Cleave shape, no Meraki lifesteal clause.
        for item_id in ("3077", "3748", "6698", "6631"):
            self.assertEqual(self._damage([item_id]), 0.0, item_id)

    def test_tank_immolate_aura_is_excluded(self):
        # Sunfire Aegis 3068 - a magic AoE aura keyed on targets_in_rotation,
        # the nearest structural look-alike to a cleave.
        self.assertEqual(self._damage(["3068"]), 0.0)

    def test_spellblade_procs_are_excluded(self):
        # Trinity Force 3078 / Lich Bane 3100 / Iceborn Gauntlet 6662.
        for item_id in ("3078", "3100", "6662"):
            self.assertEqual(self._damage([item_id]), 0.0, item_id)

    def test_burn_and_dot_procs_are_excluded(self):
        # Liandry's 6653 (ability DoT) and Blade of the Ruined King 3153
        # (physical on-hit) - neither is lifesteal-labelled AoE.
        for item_id in ("6653", "3153"):
            self.assertEqual(self._damage([item_id]), 0.0, item_id)

    def test_unknown_item_id_is_excluded(self):
        self.assertEqual(self._damage(["999999"]), 0.0)

    def test_mixed_build_credits_only_ravenous(self):
        mixed = self._damage(["3068", "3078", "3074", "6653"])
        alone = self._damage(["3074"])
        self.assertGreater(alone, 0.0)
        self.assertEqual(mixed, alone)


class ArenaMirrorTests(unittest.TestCase):
    """R161 doctrine B - the Arena mirror is credited on its own id."""

    def setUp(self):
        self.snap = DataSnapshot.load()

    def test_arena_mirror_off_path_is_byte_identical(self):
        r = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ARENA_ITEMS, mode="ARENA"
        )
        self.assertEqual(r.heal_lifesteal, _AATROX_ARENA_OFF_HEAL_LIFESTEAL)
        self.assertEqual(r.heal_cleave_lifesteal, 0.0)

    def test_arena_mirror_is_credited_when_armed(self):
        base_ad, bonus_ad, aspd, ls = _resolved_ad_as(
            self.snap, "Aatrox", 13, _AATROX_ARENA_ITEMS, "ARENA"
        )
        r = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ARENA_ITEMS, mode="ARENA",
            assume_cleave_lifesteal=True, targets_in_rotation=3.0,
        )
        self.assertGreater(r.heal_cleave_lifesteal, 0.0)
        self.assertAlmostEqual(
            r.heal_cleave_lifesteal,
            ls * _expected_cleave_damage(base_ad, bonus_ad, aspd, 3.0),
            places=9,
        )

    def test_mirror_and_base_share_one_magnitude(self):
        base = _cleave_vamp_damage(
            ["3074"], base_ad=100.0, bonus_ad=150.0, attack_speed=0.9,
            targets_in_rotation=3.0, assume_cleave_lifesteal=True,
        )
        mirror = _cleave_vamp_damage(
            ["223074"], base_ad=100.0, bonus_ad=150.0, attack_speed=0.9,
            targets_in_rotation=3.0, assume_cleave_lifesteal=True,
        )
        self.assertEqual(mirror, base)


class HydraFamilyDedupTests(unittest.TestCase):
    """The hydra_cleave unique-passive family decides who procs."""

    def _damage(self, items):
        return _cleave_vamp_damage(
            items, base_ad=100.0, bonus_ad=150.0, attack_speed=0.9,
            targets_in_rotation=3.0, assume_cleave_lifesteal=True,
        )

    def test_ravenous_first_wins_the_family(self):
        self.assertGreater(self._damage(["3074", "6698"]), 0.0)

    def test_lifesteal_silent_hydra_first_denies_the_credit(self):
        # Profane wins the family first-seen-wins, so Ravenous's Cleave never
        # procs in game and must not be credited here either.
        self.assertEqual(self._damage(["6698", "3074"]), 0.0)


if __name__ == "__main__":
    unittest.main()
