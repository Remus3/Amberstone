"""RM-176 - the extra shot's crit must read the BUILD's crit, effects included.

REGRESSION. ``dps.py`` credits an every-AA extra shot with its own critical
strike when the champion's ``_extra_shot_overrides`` entry sets ``can_crit``
(``dps.py:1577``). That term used to read the bare build stat
``stats["crit"]``, which is the DDragon stat line only. It OMITS crit that
arrives from an ``ItemEffect.crit_chance_bonus_flat``, and the engine folds
those two together into ``crit_total`` at ``dps.py:1148`` - the same value the
base auto-attack resolves against at ``dps.py:1390``.

The measured consequence, Akshan level 13 on a lone Yun Tal Wildarrows
(``3032``): the item's DDragon stat block carries ZERO crit and the whole 25
percent arrives as ``crit_chance_bonus_flat=0.25`` on the effect
(``_effects_data.py:1263``), so the shot resolved completely flat while the
base auto beside it resolved at crit 0.25 - a 15.79 percent under-credit on
the shot. Worse, that made the entire ``apply_extra_shot_procs`` flag
arithmetically INERT on that build: Yun Tal carries no ``every_n_attacks``
proc for the on-hit-application half to accelerate, so with the crit half
silently zeroed the flag ON and OFF produced bit-identical ``weighted_dps``.
A seam that is settable, note-emitting and arithmetically inert is the exact
failure class this file exists to catch.

WHAT IS PINNED:
  * effect-sourced crit reaches the shot (the fix),
  * the flag is no longer inert on that build (the symptom),
  * DDragon-sourced crit is unchanged and NOT double-counted (Infinity Edge -
    this path was already correct, so it pins that the fix did not widen),
  * a champion whose every-AA on-hit passive is not a second attack is
    untouched even on a crit-carrying build (Warwick Eternal Hunger is on-hit
    magic; the guard is ``can_crit``, not "has an AA-routed passive"),
  * a build with no crit source at all is byte-identical (the fix is a no-op
    where there is nothing to credit).

OFFLINE ONLY: no live :8860, no network.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import _extra_shot_overrides as eso
from agents.daemon_slayer import _passive_damage_overrides as pdo
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import DEFAULT_CRIT_BONUS, compute_dps
from agents.daemon_slayer.effects import collect_effects, total_crit_damage_bonus

AKSHAN = "Akshan"
# The RM-176 build. Its crit is 100 percent effect-sourced, which is what makes
# it the discriminating case rather than just another crit build.
YUN_TAL = "3032"
# Control build: crit on the DDragon stat line, plus a crit-DAMAGE bonus, so the
# expected ratio moves for a reason the fix must NOT have touched.
INFINITY_EDGE = "3031"
# No crit on either channel - the fix must be the exact identity here.
BERSERKERS = "3006"

LEVEL = 13
TARGET = dict(
    target_armor=100.0,
    target_mr=60.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)

# Measured 2026-08-08 at ENGINE 1.275.1 / patch 16.15.1. Asserted alongside the
# engine-derived form so a silent move in DEFAULT_CRIT_BONUS (or in an item's
# crit-damage line) fails here instead of quietly re-deriving itself green.
YUN_TAL_SHOT_RATIO = 1.1875
INFINITY_EDGE_SHOT_RATIO = 1.2625

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _dps(champion: str, build, **kwargs):
    return compute_dps(
        _snap(),
        champion_id=champion,
        level=LEVEL,
        item_ids=list(build),
        mode="SR",
        **TARGET,
        **kwargs,
    )


def _shot_pair(champion: str, build):
    """Per-hit on-hit damage with the shot seam OFF and ON.

    ``per_attack_on_hit_damage`` is the channel the routed passive is added to
    (``dps.py:1589``). Every build in this file carries no OTHER on-hit source
    and no ``every_n_attacks`` proc, so the OFF -> ON movement in this field is
    the shot's crit term alone and nothing else.
    """
    off = _dps(champion, build, apply_passive_damage=True)
    on = _dps(
        champion, build, apply_passive_damage=True, apply_extra_shot_procs=True
    )
    return off, on


def _crit_bonus(build) -> float:
    """The engine's own crit multiplier for a build - ``dps.py:958``."""
    return DEFAULT_CRIT_BONUS + total_crit_damage_bonus(collect_effects(list(build)))


class SnapshotItemIdentityTests(unittest.TestCase):
    """Every id used below, verified against the shipped snapshot.

    Matching by name would survive a Riot id reshuffle and quietly test a
    different item, so the ids are the contract and the names are the assertion.
    """

    def test_yun_tal_carries_no_ddragon_crit_and_all_of_it_on_the_effect(self) -> None:
        item = _snap().items[YUN_TAL]
        self.assertEqual(item["name"], "Yun Tal Wildarrows")
        self.assertEqual(
            float((item.get("stats") or {}).get("FlatCritChanceMod", 0.0) or 0.0), 0.0
        )
        effects = collect_effects([YUN_TAL])
        self.assertEqual(len(effects), 1)
        self.assertAlmostEqual(effects[0].crit_chance_bonus_flat, 0.25, places=12)

    def test_infinity_edge_carries_ddragon_crit_and_a_crit_damage_bonus(self) -> None:
        item = _snap().items[INFINITY_EDGE]
        self.assertEqual(item["name"], "Infinity Edge")
        self.assertAlmostEqual(
            float(item["stats"]["FlatCritChanceMod"]), 0.25, places=12
        )
        self.assertAlmostEqual(
            total_crit_damage_bonus(collect_effects([INFINITY_EDGE])), 0.30, places=12
        )

    def test_berserkers_carries_crit_on_neither_channel(self) -> None:
        item = _snap().items[BERSERKERS]
        self.assertEqual(item["name"], "Berserker's Greaves")
        self.assertEqual(
            float((item.get("stats") or {}).get("FlatCritChanceMod", 0.0) or 0.0), 0.0
        )
        self.assertAlmostEqual(_crit_bonus([BERSERKERS]), DEFAULT_CRIT_BONUS, places=12)


class EffectSourcedCritReachesTheShotTests(unittest.TestCase):
    """The regression proper - the bug and the symptom it produced."""

    def test_the_bare_build_stat_is_zero_on_this_build(self) -> None:
        # Without this the two tests below would pass for the wrong reason: the
        # whole point is that the old reader saw 0.0 where the engine saw 0.25.
        off, _on = _shot_pair(AKSHAN, [YUN_TAL])
        self.assertEqual(float(off.stats.get("crit", 0.0)), 0.0)
        self.assertAlmostEqual(
            collect_effects([YUN_TAL])[0].crit_chance_bonus_flat, 0.25, places=12
        )

    def test_effect_sourced_crit_scales_the_shot(self) -> None:
        off, on = _shot_pair(AKSHAN, [YUN_TAL])
        self.assertGreater(off.per_attack_on_hit_damage, 0.0)
        ratio = on.per_attack_on_hit_damage / off.per_attack_on_hit_damage
        expected = 1.0 + 0.25 * _crit_bonus([YUN_TAL])
        self.assertAlmostEqual(ratio, expected, places=12)
        self.assertAlmostEqual(ratio, YUN_TAL_SHOT_RATIO, places=4)

    def test_the_flag_is_no_longer_inert_on_the_yun_tal_build(self) -> None:
        # Bit-identical ON and OFF is what the defect looked like from outside,
        # so the inequality - not the ratio above - is the symptom assertion.
        off, on = _shot_pair(AKSHAN, [YUN_TAL])
        self.assertGreater(on.weighted_dps, off.weighted_dps)


class DDragonCritIsUnchangedTests(unittest.TestCase):
    """Control: the path that was already correct must still be correct."""

    def test_infinity_edge_ratio_folds_chance_and_damage_bonus_once(self) -> None:
        off, on = _shot_pair(AKSHAN, [INFINITY_EDGE])
        self.assertAlmostEqual(float(off.stats["crit"]), 0.25, places=12)
        ratio = on.per_attack_on_hit_damage / off.per_attack_on_hit_damage
        expected = 1.0 + 0.25 * (DEFAULT_CRIT_BONUS + 0.30)
        self.assertAlmostEqual(ratio, expected, places=12)
        self.assertAlmostEqual(ratio, INFINITY_EDGE_SHOT_RATIO, places=4)

    def test_ddragon_crit_is_not_double_counted(self) -> None:
        # A naive fix - adding crit_from_effects ON TOP of stats["crit"] - would
        # be invisible on the Yun Tal build (stat 0) and would show up here as
        # 0.50 crit instead of 0.25.
        off, on = _shot_pair(AKSHAN, [INFINITY_EDGE])
        ratio = on.per_attack_on_hit_damage / off.per_attack_on_hit_damage
        doubled = 1.0 + 0.50 * (DEFAULT_CRIT_BONUS + 0.30)
        self.assertNotAlmostEqual(ratio, doubled, places=6)


class ExclusionControlTests(unittest.TestCase):
    """The fix must not widen past what the registry marks ``can_crit``."""

    def test_akshan_is_the_only_registered_shot_and_it_crits(self) -> None:
        # Anchors the exclusion set below: if a can_crit=False entry is ever
        # added, this fails and its byte-identity control must be written too.
        self.assertEqual(
            {c for c, e in eso.EXTRA_SHOT_OVERRIDES.items() if e.can_crit}, {AKSHAN}
        )

    def test_an_aa_routed_passive_with_no_shot_entry_is_untouched(self) -> None:
        """Warwick and friends: on-hit passives, not second attacks.

        These champions DO get a routed per-hit passive under
        ``apply_passive_damage``, so they exercise the exact code path the fix
        lives on - the guard is the ``can_crit`` lookup, not the absence of a
        passive. Run on crit-carrying builds so a dropped guard would bite.
        """
        exclusions = sorted(
            champ
            for (champ, _slot, _idx) in pdo._AA_ROUTED_ON_HIT_KEYS
            if champ not in eso.EXTRA_SHOT_OVERRIDES
        )
        self.assertIn("Warwick", exclusions)
        for champ in exclusions:
            for build in ([YUN_TAL], [INFINITY_EDGE]):
                with self.subTest(champion=champ, build=tuple(build)):
                    off, on = _shot_pair(champ, build)
                    self.assertEqual(on.to_dict(), off.to_dict())

    def test_warwick_actually_has_a_routed_passive_on_these_builds(self) -> None:
        # Guards the test above from passing vacuously: byte-identity would be
        # trivially true if no passive were routed at all.
        off, _on = _shot_pair("Warwick", [YUN_TAL])
        self.assertGreater(off.per_attack_on_hit_damage, 0.0)


class ZeroCritBuildTests(unittest.TestCase):
    def test_a_build_with_no_crit_source_is_byte_identical(self) -> None:
        off, on = _shot_pair(AKSHAN, [BERSERKERS])
        self.assertEqual(float(off.stats.get("crit", 0.0)), 0.0)
        self.assertEqual(
            on.per_attack_on_hit_damage, off.per_attack_on_hit_damage
        )
        self.assertEqual(on.weighted_dps, off.weighted_dps)


if __name__ == "__main__":
    unittest.main()
