"""Defensive RESOLVE-RUNE resist-grant credit to the EHP denominator (R132, ENGINE 1.225.0).

RED-first coverage for the NEW default-OFF ``apply_rune_resist_grants`` seam on
``compute_ehp``. Before this slice the engine modelled runes as OFFENSE ONLY: a
grep of ``ehp.py`` for ``rune`` / ``perk`` / ``keystone`` returned ZERO matches,
``rank.py`` likewise, and ``rune_procs.py`` registers Aftershock (8439) only for
its magic-damage explosion - its own formula string says verbatim
"(resist-bonus side not modeled)". Three current-patch (DDragon 16.14.1) Resolve
runes therefore earn ZERO EHP for the bonus armor / magic resist they grant:

  * 8439 Aftershock (verbatim ``runesReforged.json`` longDesc): "After
    immobilizing an enemy champion, increase your Armor and Magic Resist by 45 +
    75% of your Bonus Resists for 2.5s. Then explode, dealing magic damage to
    nearby enemies.<br><br>Damage: 25 - 120 (+8% of your bonus health)<br>
    Cooldown: 20s<br><br>Resistance bonus from Aftershock capped at: 80-150
    (based on level)<br>" -> a flat 45 PLUS a percent-of-BONUS term, under a
    LEVEL-SCALED CAP (80 at level 1 rising to 150 at level 18).
  * 8429 Conditioning (verbatim): "After 12 min gain +8 Armor and +8 Magic Resist
    and increase your Armor and Magic Resist by 3%." -> a flat 8/8 PLUS a
    percent-of-TOTAL term, gated on a game-time threshold, PERMANENT once online.
  * 8242 Unflinching (verbatim): "Gain 10 Armor and Magic Resist when crowd
    controlled and for 2 seconds after." -> a flat 10/10, conditional on being CC'd.

THE CAP IS THE LOAD-BEARING PART OF AFTERSHOCK. The grant is
``min(45 + 0.75 * bonus_resist, cap_by_level)``, NOT the uncapped
``45 + 0.75 * bonus_resist``. The cap BINDS precisely on the high-bonus-resist tank
cohort that actually runs Aftershock: at 150 bonus armor the uncapped value is
157.5, over the level-18 cap of 150. A cap-free implementation over-credits exactly
the champions this feed exists for, so ``test_aftershock_cap_binds_at_high_bonus_resist``
is the discriminating test in this module.

This module is the RUNE-side lane of the FOURTH (resist-denominator) survivability
axis, mirroring the ITEM-side ``_item_resist_grants`` registry: the champion
registry ``_passive_resist_overrides.resist_grants`` is champion-keyed and the item
registry is item-keyed, so a RUNE id can never match either.

Contract:
  * OFF (default) -> ``rune_resist_armor`` / ``rune_resist_mr`` == 0.0 ->
    physical/magical/true/blended/cc_blended/sustain EHP BYTE-IDENTICAL to the
    pre-seam value, to an explicit ``False`` run, AND to a run that passes
    ``rune_ids`` while the flag stays OFF.
  * ON + Aftershock / Conditioning / Unflinching -> BOTH resisted axes rise
    (all three grant armor AND magic resist); true EHP stays byte-identical.
  * The MAGNITUDE of every grant is EXACT DDragon; only the FIRING MIDPOINT is an
    assumption (the ``_ACTIVE_RESIST_PROB`` / ``_ITEM_RESIST_STACK_PROB`` precedent).
  * An offensive or non-resist rune id (Press the Attack 8005, Dark Harvest 8128,
    and the Resolve-tree-but-not-a-resist Demolish 8446 / Overgrowth 8451)
    contributes 0.0 with the flag ON - the registry is a seeded allowlist, not a
    tree-wide sweep.

OFFLINE ONLY: no live :8893, no network. Every assertion runs against the
committed data snapshot and the pure registry function.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._rune_resist_grants import (
    _AFTERSHOCK_CAP_AT_LEVEL_1,
    _AFTERSHOCK_CAP_AT_LEVEL_18,
    _ASSUMED_GAME_MINUTE,
    _CONDITIONING_ONLINE_MINUTE,
    _RUNE_ACTIVE_RESIST_PROB,
    _RUNE_RESIST_GRANTS,
    aftershock_resist_cap,
    rune_resist_grants,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


# Shared resist frame for the pure-registry tests. base_* are the champion's base
# per-level resists; total_* are the RESOLVED build resists, so
# bonus = total - base (the same convention _item_resist_grants uses).
_BASE_ARMOR = 40.0
_BASE_MR = 32.0


def _grant(rune_ids, *, level=13, total_armor=100.0, total_mr=80.0,
           game_minute=None):
    kwargs = {}
    if game_minute is not None:
        kwargs["game_minute"] = game_minute
    return rune_resist_grants(
        rune_ids,
        level=level,
        total_armor=total_armor,
        total_mr=total_mr,
        base_armor=_BASE_ARMOR,
        base_mr=_BASE_MR,
        **kwargs,
    )


# ---------------- registry shape ----------------


class RuneResistRegistryShapeTests(unittest.TestCase):
    def test_seeded_ids_are_exactly_the_three_resolve_resist_runes(self) -> None:
        self.assertEqual(set(_RUNE_RESIST_GRANTS), {"8439", "8429", "8242"})

    def test_every_entry_carries_a_note_and_a_sane_probability(self) -> None:
        for rid, entry in _RUNE_RESIST_GRANTS.items():
            self.assertTrue(entry.note, msg=rid)
            self.assertGreater(entry.conditional_probability, 0.0, msg=rid)
            self.assertLessEqual(entry.conditional_probability, 1.0, msg=rid)

    def test_all_three_grant_both_axes_symmetrically(self) -> None:
        # Every seeded rune's longDesc grants Armor AND Magic Resist in equal
        # measure, so the armor and mr sides of each entry must match.
        for rid, entry in _RUNE_RESIST_GRANTS.items():
            self.assertEqual(entry.armor, entry.mr, msg=rid)
            self.assertEqual(entry.armor_pct, entry.mr_pct, msg=rid)


# ---------------- Aftershock: the level-scaled cap ----------------


class AftershockCapTests(unittest.TestCase):
    def test_cap_endpoints_match_ddragon_80_to_150(self) -> None:
        self.assertAlmostEqual(
            aftershock_resist_cap(1), _AFTERSHOCK_CAP_AT_LEVEL_1, places=9
        )
        self.assertAlmostEqual(
            aftershock_resist_cap(18), _AFTERSHOCK_CAP_AT_LEVEL_18, places=9
        )
        self.assertAlmostEqual(aftershock_resist_cap(1), 80.0, places=9)
        self.assertAlmostEqual(aftershock_resist_cap(18), 150.0, places=9)

    def test_cap_is_monotonic_in_level(self) -> None:
        caps = [aftershock_resist_cap(lv) for lv in range(1, 19)]
        self.assertEqual(caps, sorted(caps))
        self.assertLess(caps[0], caps[-1])

    def test_cap_clamps_outside_1_to_18(self) -> None:
        self.assertAlmostEqual(aftershock_resist_cap(0), 80.0, places=9)
        self.assertAlmostEqual(aftershock_resist_cap(25), 150.0, places=9)

    def test_aftershock_cap_binds_at_high_bonus_resist(self) -> None:
        # THE discriminating test. Level 18, 150 bonus armor: the UNCAPPED value
        # is 45 + 0.75 * 150 = 157.5, which EXCEEDS the level-18 cap of 150. A
        # cap-free implementation returns 157.5 * prob and over-credits the exact
        # tank cohort this feed targets.
        a, m = _grant(
            ["8439"], level=18,
            total_armor=_BASE_ARMOR + 150.0, total_mr=_BASE_MR + 150.0,
        )
        capped = 150.0 * _RUNE_ACTIVE_RESIST_PROB
        uncapped = (45.0 + 0.75 * 150.0) * _RUNE_ACTIVE_RESIST_PROB
        self.assertAlmostEqual(a, capped, places=9)
        self.assertAlmostEqual(m, capped, places=9)
        self.assertLess(a, uncapped)

    def test_aftershock_below_cap_scales_with_the_75_percent_term(self) -> None:
        # Below the cap the grant is exactly 45 + 0.75 * bonus, so doubling the
        # bonus resist from 50 to 100 must add exactly 0.75 * 50 (pre-midpoint).
        low_a, low_m = _grant(
            ["8439"], level=18,
            total_armor=_BASE_ARMOR + 50.0, total_mr=_BASE_MR + 50.0,
        )
        high_a, high_m = _grant(
            ["8439"], level=18,
            total_armor=_BASE_ARMOR + 100.0, total_mr=_BASE_MR + 100.0,
        )
        self.assertAlmostEqual(
            low_a, (45.0 + 0.75 * 50.0) * _RUNE_ACTIVE_RESIST_PROB, places=9
        )
        self.assertAlmostEqual(
            high_a, (45.0 + 0.75 * 100.0) * _RUNE_ACTIVE_RESIST_PROB, places=9
        )
        self.assertAlmostEqual(
            high_a - low_a, 0.75 * 50.0 * _RUNE_ACTIVE_RESIST_PROB, places=9
        )
        self.assertAlmostEqual(high_m - low_m, high_a - low_a, places=9)

    def test_aftershock_cap_binds_earlier_at_low_level(self) -> None:
        # Same bonus resist, two levels: the level-1 cap (80) binds where the
        # level-18 cap (150) does not, so the low-level grant must be strictly
        # smaller. This is an invariant, not a hand-computed constant.
        bonus = 120.0
        low, _ = _grant(
            ["8439"], level=1,
            total_armor=_BASE_ARMOR + bonus, total_mr=_BASE_MR + bonus,
        )
        high, _ = _grant(
            ["8439"], level=18,
            total_armor=_BASE_ARMOR + bonus, total_mr=_BASE_MR + bonus,
        )
        self.assertLess(low, high)
        self.assertAlmostEqual(low, 80.0 * _RUNE_ACTIVE_RESIST_PROB, places=9)

    def test_aftershock_never_negative_on_below_base_build(self) -> None:
        # A build resolving BELOW base per-level must clamp the bonus term to 0,
        # leaving the flat 45 only - never a negative grant.
        a, m = _grant(
            ["8439"], level=13, total_armor=10.0, total_mr=10.0,
        )
        self.assertAlmostEqual(a, 45.0 * _RUNE_ACTIVE_RESIST_PROB, places=9)
        self.assertAlmostEqual(m, 45.0 * _RUNE_ACTIVE_RESIST_PROB, places=9)


# ---------------- Conditioning: flat + percent-of-total, time gated ----------------


class ConditioningTests(unittest.TestCase):
    def test_conditioning_flat_plus_percent_of_total(self) -> None:
        # +8 flat and +3% of TOTAL resist (not bonus). At 200 armor / 100 mr:
        # armor = 8 + 6 = 14, mr = 8 + 3 = 11. Permanent once online -> prob 1.0.
        a, m = _grant(
            ["8429"], level=13, total_armor=200.0, total_mr=100.0,
            game_minute=_CONDITIONING_ONLINE_MINUTE + 3.0,
        )
        self.assertAlmostEqual(a, 8.0 + 0.03 * 200.0, places=9)
        self.assertAlmostEqual(m, 8.0 + 0.03 * 100.0, places=9)

    def test_conditioning_percent_is_of_total_not_bonus(self) -> None:
        # Discriminates pct_base: a percent-of-BONUS reading would give
        # 8 + 0.03 * (200 - 40) = 12.8 for armor, not 14.0.
        a, _ = _grant(
            ["8429"], level=13, total_armor=200.0, total_mr=100.0,
            game_minute=_CONDITIONING_ONLINE_MINUTE + 3.0,
        )
        self.assertAlmostEqual(a, 14.0, places=9)
        self.assertNotAlmostEqual(a, 8.0 + 0.03 * (200.0 - _BASE_ARMOR), places=6)

    def test_conditioning_is_zero_before_the_twelve_minute_mark(self) -> None:
        a, m = _grant(
            ["8429"], level=13, total_armor=200.0, total_mr=100.0,
            game_minute=_CONDITIONING_ONLINE_MINUTE - 1.0,
        )
        self.assertEqual((a, m), (0.0, 0.0))

    def test_conditioning_online_threshold_is_twelve_minutes(self) -> None:
        self.assertAlmostEqual(_CONDITIONING_ONLINE_MINUTE, 12.0, places=9)

    def test_default_assumed_game_minute_is_explicit_and_past_the_gate(self) -> None:
        # The time assumption must be a named, tunable constant - not an implicit
        # lategame assumption buried in the fold.
        self.assertGreaterEqual(_ASSUMED_GAME_MINUTE, _CONDITIONING_ONLINE_MINUTE)
        default_a, _ = _grant(["8429"], level=13, total_armor=200.0, total_mr=100.0)
        explicit_a, _ = _grant(
            ["8429"], level=13, total_armor=200.0, total_mr=100.0,
            game_minute=_ASSUMED_GAME_MINUTE,
        )
        self.assertAlmostEqual(default_a, explicit_a, places=9)

    def test_conditioning_is_unaffected_by_level(self) -> None:
        # No level scaling in the longDesc - only the 12-minute gate.
        for lv in (1, 6, 13, 18):
            a, m = _grant(
                ["8429"], level=lv, total_armor=200.0, total_mr=100.0,
                game_minute=_ASSUMED_GAME_MINUTE,
            )
            self.assertAlmostEqual(a, 14.0, places=9, msg=str(lv))
            self.assertAlmostEqual(m, 11.0, places=9, msg=str(lv))


# ---------------- Unflinching: flat, conditional ----------------


class UnflinchingTests(unittest.TestCase):
    def test_unflinching_is_a_flat_ten_ten_at_the_midpoint(self) -> None:
        a, m = _grant(["8242"], level=13, total_armor=200.0, total_mr=100.0)
        self.assertAlmostEqual(a, 10.0 * _RUNE_ACTIVE_RESIST_PROB, places=9)
        self.assertAlmostEqual(m, 10.0 * _RUNE_ACTIVE_RESIST_PROB, places=9)

    def test_unflinching_does_not_scale_with_resists_or_level(self) -> None:
        # Purely flat: identical across wildly different resist frames + levels.
        first = _grant(["8242"], level=1, total_armor=30.0, total_mr=30.0)
        second = _grant(["8242"], level=18, total_armor=400.0, total_mr=300.0)
        self.assertEqual(first, second)


# ---------------- composition + negative space ----------------


class RuneResistCompositionTests(unittest.TestCase):
    def test_unknown_offensive_and_non_resist_resolve_runes_yield_zero(self) -> None:
        # 8005 Press the Attack + 8128 Dark Harvest are offensive keystones;
        # 8446 Demolish + 8451 Overgrowth + 8473 Bone Plating + 8453 Revitalize
        # are Resolve-tree runes that are NOT resist grants. None may leak.
        for ids in (
            [], ["8005"], ["8128"], ["8446"], ["8451"], ["8473"], ["8453"],
            ["9999"], ["8005", "8446", "8451"],
        ):
            self.assertEqual(_grant(ids), (0.0, 0.0), msg=str(ids))

    def test_distinct_runes_sum(self) -> None:
        after = _grant(["8439"])
        cond = _grant(["8429"])
        unfl = _grant(["8242"])
        both = _grant(["8439", "8429", "8242"])
        self.assertAlmostEqual(both[0], after[0] + cond[0] + unfl[0], places=9)
        self.assertAlmostEqual(both[1], after[1] + cond[1] + unfl[1], places=9)

    def test_a_repeated_rune_id_is_credited_once(self) -> None:
        # A rune cannot be equipped twice; a duplicated id must not double-credit.
        single = _grant(["8439"])
        doubled = _grant(["8439", "8439"])
        self.assertEqual(single, doubled)

    def test_int_ids_resolve_identically_to_string_ids(self) -> None:
        self.assertEqual(_grant([8439]), _grant(["8439"]))
        self.assertEqual(_grant([8429, 8242]), _grant(["8429", "8242"]))

    def test_every_grant_is_strictly_positive_on_both_axes(self) -> None:
        for rid in _RUNE_RESIST_GRANTS:
            a, m = _grant([rid])
            self.assertGreater(a, 0.0, msg=rid)
            self.assertGreater(m, 0.0, msg=rid)


# ---------------- DEFAULT-OFF byte identity (the load-bearing guard) ----------------


class RuneResistOffByteIdenticalTests(unittest.TestCase):
    _FIELDS = (
        "physical_ehp", "magical_ehp", "true_ehp", "blended_ehp",
        "cc_blended_ehp", "effective_ehp_with_sustain", "ehp_without_sustain",
        "armor", "mr",
    )

    def _ehp(self, **kw):
        return compute_ehp(
            _snap(), champion_id="Ornn", level=13,
            item_ids=["3068", "3075"], mode="SR", **kw,
        )

    def test_flag_absent_equals_explicit_false_with_runes_supplied(self) -> None:
        # THE most important assertion in this module: with the seam OFF the
        # engine output is EXACTLY what it was before the seam existed, even when
        # a full Resolve rune page is handed in.
        absent = self._ehp()
        off = self._ehp(
            apply_rune_resist_grants=False, rune_ids=["8439", "8429", "8242"],
        )
        for field in self._FIELDS:
            self.assertAlmostEqual(
                getattr(absent, field), getattr(off, field), places=9, msg=field
            )

    def test_rune_ids_alone_do_not_arm_the_seam(self) -> None:
        # Supplying rune_ids WITHOUT the flag must stay byte-identical - the flag
        # is the only gate.
        absent = self._ehp()
        ids_only = self._ehp(rune_ids=["8439", "8429", "8242"])
        for field in self._FIELDS:
            self.assertAlmostEqual(
                getattr(absent, field), getattr(ids_only, field),
                places=9, msg=field,
            )

    def test_off_fields_are_zero(self) -> None:
        off = self._ehp(
            apply_rune_resist_grants=False, rune_ids=["8439"],
        )
        self.assertEqual(off.rune_resist_armor, 0.0)
        self.assertEqual(off.rune_resist_mr, 0.0)

    def test_on_with_no_runes_is_byte_identical(self) -> None:
        absent = self._ehp()
        armed_empty = self._ehp(apply_rune_resist_grants=True, rune_ids=[])
        for field in self._FIELDS:
            self.assertAlmostEqual(
                getattr(absent, field), getattr(armed_empty, field),
                places=9, msg=field,
            )
        self.assertEqual(armed_empty.rune_resist_armor, 0.0)
        self.assertEqual(armed_empty.rune_resist_mr, 0.0)

    def test_on_with_only_offensive_runes_is_byte_identical(self) -> None:
        absent = self._ehp()
        armed = self._ehp(
            apply_rune_resist_grants=True, rune_ids=["8005", "8128", "8446"],
        )
        for field in self._FIELDS:
            self.assertAlmostEqual(
                getattr(absent, field), getattr(armed, field), places=9, msg=field
            )

    def test_to_dict_exposes_both_new_fields(self) -> None:
        payload = self._ehp().to_dict()
        self.assertEqual(payload["rune_resist_armor"], 0.0)
        self.assertEqual(payload["rune_resist_mr"], 0.0)


# ---------------- ON credit lands on the denominator ----------------


class RuneResistOnCreditTests(unittest.TestCase):
    def _ehp(self, *, on, runes, champ="Ornn", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level,
            item_ids=["3068", "3075"], mode="SR",
            apply_rune_resist_grants=on, rune_ids=list(runes),
        )

    def test_aftershock_raises_both_resisted_axes_not_true(self) -> None:
        off = self._ehp(on=False, runes=["8439"])
        on = self._ehp(on=True, runes=["8439"])
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        # A resist grant is a DENOMINATOR term - true damage ignores resists.
        self.assertAlmostEqual(on.true_ehp, off.true_ehp, places=9)
        self.assertGreater(on.rune_resist_armor, 0.0)
        self.assertGreater(on.rune_resist_mr, 0.0)

    def test_reported_armor_and_mr_stay_the_resolved_build_stats(self) -> None:
        # Matches the passive-resist / item-resist convention: the grant is
        # internal to the EHP math and does NOT rewrite the reported stat block.
        off = self._ehp(on=False, runes=["8439"])
        on = self._ehp(on=True, runes=["8439"])
        self.assertAlmostEqual(on.armor, off.armor, places=9)
        self.assertAlmostEqual(on.mr, off.mr, places=9)

    def test_all_three_runes_beat_any_single_rune(self) -> None:
        single = self._ehp(on=True, runes=["8242"])
        full = self._ehp(on=True, runes=["8439", "8429", "8242"])
        self.assertGreater(full.rune_resist_armor, single.rune_resist_armor)
        self.assertGreater(full.rune_resist_mr, single.rune_resist_mr)
        self.assertGreater(full.physical_ehp, single.physical_ehp)

    def test_credit_is_independent_of_the_item_seam(self) -> None:
        # The rune lane and the item lane are separate registries; arming the
        # rune seam must not disturb the item field, and vice versa.
        on = self._ehp(on=True, runes=["8439"])
        self.assertEqual(on.item_resist_armor, 0.0)
        self.assertEqual(on.item_resist_mr, 0.0)


# ---------------- engine version pin ----------------


class EngineVersionTests(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        from agents.daemon_slayer import ENGINE_VERSION

        self.assertEqual(ENGINE_VERSION, "1.244.0")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
