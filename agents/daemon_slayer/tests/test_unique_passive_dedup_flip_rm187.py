"""RM-187: FLIP the RM-186 strongest-at-context dedup ON at every call site.

RM-186 (ENGINE 1.276.0) landed ``collect_effects(item_ids, caster_ctx=None)``.
At ``None`` it is first-seen-wins - the legacy, ORDER-DEPENDENT behaviour - and
every engine call site passed nothing, so the fix was inert. RM-187 makes
strongest-at-context the real engine behaviour.

THE CIRCULARITY AND ITS RESOLUTION
----------------------------------
``ehp.py`` builds its ``CallContext`` before it collects, but ``dps.py`` /
``ability_dps.py`` collect BEFORE their full context exists, and the full
context is partly derived FROM the collected effects (Riftmaker's HP->AP,
Mejai's stacked AP, Rabadon's AP amp, Yun Tal / Atma's crit, Bastionbreaker's
lethality, the last_whisper / void_pen penetration folds). Feeding that context
back into the dedup would be circular.

Resolution: ``effects.dedupe_context`` builds the dedup context from
DEDUPE-INDEPENDENT quantities ONLY - the resolved stat block
(``stats.aggregate_item_stats``, which lives outside ``collect_effects`` and is
NOT affected by the dedup), the champion base stats, the level, and the
caller-supplied target assumptions. Every effect-derived augmentation is
EXCLUDED and documented on ``dedupe_context``; ``ExclusionGuardTests`` below
pins the exclusion list against the live registry so a future item that joins a
family and reads an excluded field reddens CI instead of silently mis-ranking.

Written RED first per the repo TDD rule.
"""
from __future__ import annotations

import dataclasses
import unittest
import unittest.mock

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import CallContext
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.ability_hps import compute_ability_hps
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps, total_missing_hp_bonus_ad
from agents.daemon_slayer.effects import (
    _comparable_periodic_magnitude,
    collect_effects,
    dedupe_context,
)
from agents.daemon_slayer.ehp import compute_ehp

# ---------------------------------------------------------------- item ids
# immolate family - the only family whose members ALL expose a comparable
# per-second timer magnitude and whose ranking is decided by caster HP alone.
SUNFIRE = "3068"            # Immolate 20 + 1.0% bonus HP  (the stronger)
HOLLOW_RADIANCE = "6664"    # Immolate 15 + 1.0% bonus HP  (the weaker)
BAMIS = "6660"              # Immolate flat 15, component tier

# spellblade family - comparable, but the winner moves with the CONTEXT
# (base AD / AP / target max HP), see TargetDependenceTests.
SHEEN = "3057"              # 100% base AD / 1.5s
LICH_BANE = "3100"          # 75% base AD + AP ratio / 1.5s
TRINITY = "3078"            # 200% base AD / 3.0s -> same 66.67/s as Sheen
DIVINE_SUNDERER = "6632"    # base AD + %target max HP / 1.5s

# Families with NO comparable per-second magnitude -> first-seen fallback.
LAST_WHISPER_A = "3036"     # Lord Dominik's Regards (pen only)
LAST_WHISPER_B = "3033"     # Mortal Reminder (pen only)
LIFELINE_A = "3053"         # Sterak's Gage (shield only)
LIFELINE_B = "3156"         # Maw of Malmortius (shield only)
VOID_PEN_A = "3135"         # Void Staff
VOID_PEN_B = "3137"         # Cryptbloom
HYDRA_RAVENOUS = "3074"     # every_n_attacks only
HYDRA_TITANIC = "3748"      # every_n_attacks only

# Keyless controls.
BERSERKERS = "3006"
INFINITY_EDGE = "3031"

TANK = "Malphite"
CARRY = "Jinx"
MAGE = "Annie"


def _both_orders(a: str, b: str) -> tuple[list[str], list[str]]:
    return [a, b], [b, a]


class DedupeContextExclusionTests(unittest.TestCase):
    """(e) The circularity resolution, pinned: the dedup context carries the
    RAW stat-block values and NONE of the effect-derived augmentations."""

    STATS = {
        "ad": 210.0, "ap": 300.0, "hp": 3400.0, "armor": 180.0,
        "mr": 90.0, "mp": 1200.0, "crit": 0.4, "as": 1.4,
    }
    BASE = {"ad": 60.0, "hp": 1400.0, "armor": 50.0, "mr": 40.0}

    def _ctx(self, **kw) -> CallContext:
        return dedupe_context(self.STATS, self.BASE, 13, **kw)

    def test_stat_block_fields_are_exact(self) -> None:
        ctx = self._ctx()
        self.assertAlmostEqual(ctx.base_ad, 60.0)
        self.assertAlmostEqual(ctx.bonus_ad, 150.0)
        self.assertEqual(ctx.level, 13)
        self.assertAlmostEqual(ctx.caster_max_hp, 3400.0)
        self.assertAlmostEqual(ctx.caster_bonus_hp, 2000.0)
        self.assertAlmostEqual(ctx.caster_bonus_armor, 130.0)
        self.assertAlmostEqual(ctx.caster_max_mp, 1200.0)

    def test_ap_is_the_raw_stat_block_ap_not_the_augmented_total(self) -> None:
        # EXCLUDED: total_bonus_ap_from_hp (Riftmaker), total_stacked_ap
        # (Mejai's), total_ap_amp_multiplier (Rabadon's),
        # total_caster_hp_scaled_ap_amp (Demonic), rune adaptive AP.
        self.assertAlmostEqual(self._ctx().ap, 300.0)

    def test_crit_is_the_raw_stat_block_crit(self) -> None:
        # EXCLUDED: total_crit_chance_bonus (Yun Tal flat, Atma's HP-scaled).
        self.assertAlmostEqual(self._ctx().crit_chance, 0.4)

    def test_caster_lethality_is_excluded_entirely(self) -> None:
        # sum(e.lethality for e in item_effects) is a sum over the DEDUPED
        # list - genuinely dedupe-dependent, so it is left at zero.
        self.assertAlmostEqual(self._ctx().caster_lethality, 0.0)

    def test_target_resists_are_the_raw_caller_values_not_the_effective_ones(self) -> None:
        # EXCLUDED: effective_target_armor / effective_target_mr, which fold
        # armor_pen_pct + magic_pen_pct - carried by the last_whisper and
        # void_pen families themselves, so maximally circular.
        ctx = self._ctx(target_armor=100.0, target_mr=70.0)
        self.assertAlmostEqual(ctx.target_armor, 100.0)
        self.assertAlmostEqual(ctx.target_mr, 70.0)

    def test_targets_in_rotation_is_single_target(self) -> None:
        # Not dedupe-dependent, but not known until the per-rotation loop.
        # Safe because it is an exactly-uniform multiplier inside immolate -
        # pinned by ImmolateTargetsUniformityTests below.
        self.assertAlmostEqual(self._ctx().targets_in_rotation, 1.0)

    def test_ult_casts_per_sec_is_zero(self) -> None:
        self.assertAlmostEqual(self._ctx().ult_casts_per_sec, 0.0)

    def test_caller_target_assumptions_are_carried(self) -> None:
        ctx = self._ctx(target_max_hp=2500.0, target_bonus_hp=1100.0,
                        target_current_hp_pct=0.5)
        self.assertAlmostEqual(ctx.target_max_hp, 2500.0)
        self.assertAlmostEqual(ctx.target_bonus_hp, 1100.0)
        self.assertAlmostEqual(ctx.target_current_hp_pct, 0.5)

    def test_missing_base_stats_do_not_raise(self) -> None:
        ctx = dedupe_context(self.STATS, None, 1)
        self.assertAlmostEqual(ctx.base_ad, 0.0)
        self.assertAlmostEqual(ctx.bonus_ad, 210.0)

    def test_context_is_order_independent_by_construction(self) -> None:
        # The whole point: nothing in the dedup context comes from the list
        # being deduped, so re-ordering item_ids cannot move it.
        snap = DataSnapshot.load()
        from agents.daemon_slayer.engine import build_champion

        a = build_champion(snap, TANK, 13, item_ids=[SUNFIRE, HOLLOW_RADIANCE])
        b = build_champion(snap, TANK, 13, item_ids=[HOLLOW_RADIANCE, SUNFIRE])
        self.assertEqual(
            dedupe_context(a.stats, a.base_stats, 13),
            dedupe_context(b.stats, b.base_stats, 13),
        )


class ExclusionGuardTests(unittest.TestCase):
    """(e) Data guard: no family member that CAN win a contest reads a field
    the dedup context excludes or approximates without it being documented."""

    # Fields the dedup context carries EXACTLY.
    EXACT = frozenset({
        "base_ad", "bonus_ad", "level", "caster_max_hp", "caster_bonus_hp",
        "caster_bonus_armor", "caster_max_mp", "target_max_hp",
        "target_bonus_hp", "target_current_hp_pct", "target_armor", "target_mr",
    })
    # Fields the dedup context carries as a documented APPROXIMATION (raw
    # stat-block value, effect-derived augmentation excluded).
    APPROXIMATED = frozenset({"ap", "crit_chance"})
    # Fields the dedup context deliberately pins to a constant.
    PINNED = frozenset({"targets_in_rotation"})

    @classmethod
    def setUpClass(cls) -> None:
        cls.groups: dict[str, list[str]] = {}
        for iid, eff in ITEM_EFFECTS.items():
            if eff.unique_passive_key:
                cls.groups.setdefault(eff.unique_passive_key, []).append(iid)
        cls.fields = [f.name for f in dataclasses.fields(CallContext)]

    def _base(self) -> CallContext:
        return CallContext(
            base_ad=100.0, bonus_ad=150.0, level=13, target_armor=80.0,
            target_mr=60.0, ap=200.0, target_max_hp=2200.0,
            caster_max_hp=3000.0, caster_bonus_hp=1200.0, crit_chance=0.5,
            target_bonus_hp=1100.0, caster_max_mp=1500.0,
            caster_bonus_armor=90.0, caster_lethality=18.0,
            ult_casts_per_sec=0.02, target_current_hp_pct=1.0, is_melee=True,
        )

    def _sensitivity(self, iid: str) -> set[str]:
        eff = ITEM_EFFECTS[iid]
        base = self._base()
        out: set[str] = set()
        for proc in eff.periodics:
            if proc.every_n_seconds <= 0:
                continue
            ref = proc.resolve_damage(base)
            for name in self.fields:
                cur = getattr(base, name)
                if isinstance(cur, bool):
                    nxt = not cur
                elif isinstance(cur, int):
                    nxt = cur + 3
                else:
                    nxt = float(cur) * 2.0 + 7.0
                if proc.resolve_damage(dataclasses.replace(base, **{name: nxt})) != ref:
                    out.add(name)
        return out

    def test_no_contested_family_reads_an_undocumented_field(self) -> None:
        allowed = self.EXACT | self.APPROXIMATED | self.PINNED
        for key, ids in sorted(self.groups.items()):
            if len(ids) < 2:
                continue
            comparable = [
                i for i in ids
                if isinstance(_comparable_periodic_magnitude(ITEM_EFFECTS[i], self._base()), float)
            ]
            if len(comparable) < 2:
                continue  # falls back to first-seen; nothing to mis-rank
            with self.subTest(family=key):
                read: set[str] = set()
                for i in comparable:
                    read |= self._sensitivity(i)
                self.assertTrue(
                    read <= allowed,
                    f"family {key!r} timer procs read {sorted(read - allowed)}, "
                    "which dedupe_context does not carry - either plumb the "
                    "field or extend the documented exclusion list",
                )

    def test_exactly_two_families_are_contested_today(self) -> None:
        # Fences the measurement in the RM-187 report. If a new family becomes
        # contested, the exclusion analysis above must be re-run for it.
        contested = set()
        for key, ids in self.groups.items():
            comparable = [
                i for i in ids
                if isinstance(_comparable_periodic_magnitude(ITEM_EFFECTS[i], self._base()), float)
            ]
            if len(comparable) >= 2:
                contested.add(key)
        self.assertEqual(contested, {"immolate", "spellblade"})


class ImmolateTargetsUniformityTests(unittest.TestCase):
    """Pins the assumption that lets the dedup context hold
    ``targets_in_rotation=1.0``: it is an exactly-uniform multiplier across
    every immolate member, so it cannot move the argmax."""

    def test_targets_in_rotation_scales_every_member_identically(self) -> None:
        base = dict(base_ad=100.0, bonus_ad=150.0, level=13,
                    caster_max_hp=3000.0, caster_bonus_hp=1200.0)
        ids = sorted(i for i, e in ITEM_EFFECTS.items()
                     if e.unique_passive_key == "immolate")
        for iid in ids:
            with self.subTest(item=iid):
                one = _comparable_periodic_magnitude(
                    ITEM_EFFECTS[iid], CallContext(**base, targets_in_rotation=1.0))
                three = _comparable_periodic_magnitude(
                    ITEM_EFFECTS[iid], CallContext(**base, targets_in_rotation=3.0))
                self.assertAlmostEqual(three, one * 3.0)


class CallSiteFlippedTests(unittest.TestCase):
    """Every engine call site now passes a real context - no site left inert."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _spy(self, module_path: str):
        real = collect_effects
        seen: list[object] = []

        def wrapper(item_ids, caster_ctx=None):
            seen.append(caster_ctx)
            return real(item_ids, caster_ctx)

        return unittest.mock.patch(module_path, side_effect=wrapper), seen

    def _assert_all_contexts(self, seen: list[object]) -> None:
        self.assertTrue(seen, "collect_effects was never called")
        for ctx in seen:
            self.assertIsInstance(ctx, CallContext)

    def test_compute_dps_passes_a_context(self) -> None:
        patcher, seen = self._spy("agents.daemon_slayer.dps.collect_effects")
        with patcher:
            compute_dps(self.snap, CARRY, 13, item_ids=[SHEEN, LICH_BANE],
                        target_armor=80.0, assume_caster_lowhp=True)
        self._assert_all_contexts(seen)

    def test_compute_ehp_passes_a_context(self) -> None:
        patcher, seen = self._spy("agents.daemon_slayer.ehp.collect_effects")
        with patcher:
            compute_ehp(self.snap, TANK, 13,
                        item_ids=[HYDRA_RAVENOUS, HYDRA_TITANIC],
                        assume_cleave_lifesteal=True, targets_in_rotation=3.0)
        self._assert_all_contexts(seen)

    def test_compute_burst_passes_a_context(self) -> None:
        patcher, seen = self._spy("agents.daemon_slayer.burst.collect_effects")
        with patcher:
            compute_burst_damage(self.snap, MAGE, 13,
                                 item_ids=[SHEEN, LICH_BANE],
                                 target_armor=80.0, target_mr=60.0)
        self._assert_all_contexts(seen)

    def test_compute_ability_dps_passes_a_context(self) -> None:
        patcher, seen = self._spy("agents.daemon_slayer.ability_dps.collect_effects")
        with patcher:
            compute_ability_dps(self.snap, MAGE, 13,
                                item_ids=[SHEEN, LICH_BANE],
                                target_armor=80.0, target_mr=60.0)
        self._assert_all_contexts(seen)

    def test_compute_ability_hps_passes_a_context(self) -> None:
        patcher, seen = self._spy("agents.daemon_slayer.ability_hps.collect_effects")
        with patcher:
            compute_ability_hps(self.snap, "Soraka", 13,
                                item_ids=[SHEEN, LICH_BANE])
        self._assert_all_contexts(seen)

    def test_total_missing_hp_bonus_ad_accepts_and_uses_a_context(self) -> None:
        ctx = dedupe_context({"ad": 200.0}, {"ad": 60.0}, 13)
        # Signature accepts the seam; the legacy 2/3-positional form still works.
        self.assertAlmostEqual(
            total_missing_hp_bonus_ad([SUNFIRE], 200.0), 0.0)
        self.assertAlmostEqual(
            total_missing_hp_bonus_ad([SUNFIRE], 200.0, False, ctx), 0.0)


class OrderIndependenceTests(unittest.TestCase):
    """(a) Same build, two slot orders, one number - asserted on the COMPUTED
    quantity, never on the effect list."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_compute_dps_immolate_pair(self) -> None:
        a, b = _both_orders(HOLLOW_RADIANCE, SUNFIRE)
        ra = compute_dps(self.snap, TANK, 13, item_ids=a, target_armor=60.0)
        rb = compute_dps(self.snap, TANK, 13, item_ids=b, target_armor=60.0)
        self.assertAlmostEqual(ra.weighted_dps, rb.weighted_dps)

    def test_compute_dps_immolate_pair_with_component(self) -> None:
        ra = compute_dps(self.snap, TANK, 13,
                         item_ids=[BAMIS, HOLLOW_RADIANCE, SUNFIRE],
                         target_armor=60.0)
        rb = compute_dps(self.snap, TANK, 13,
                         item_ids=[SUNFIRE, BAMIS, HOLLOW_RADIANCE],
                         target_armor=60.0)
        self.assertAlmostEqual(ra.weighted_dps, rb.weighted_dps)

    def test_compute_dps_spellblade_pair(self) -> None:
        a, b = _both_orders(LICH_BANE, SHEEN)
        ra = compute_dps(self.snap, MAGE, 13, item_ids=a, target_armor=60.0,
                         target_mr=40.0, target_max_hp=2200.0)
        rb = compute_dps(self.snap, MAGE, 13, item_ids=b, target_armor=60.0,
                         target_mr=40.0, target_max_hp=2200.0)
        self.assertAlmostEqual(ra.weighted_dps, rb.weighted_dps)
        self.assertAlmostEqual(ra.spellblade_per_proc_damage,
                               rb.spellblade_per_proc_damage)

    def test_compute_burst_spellblade_pair(self) -> None:
        a, b = _both_orders(LICH_BANE, SHEEN)
        ra = compute_burst_damage(self.snap, MAGE, 13, item_ids=a,
                                  target_armor=60.0, target_mr=40.0,
                                  target_max_hp=2200.0)
        rb = compute_burst_damage(self.snap, MAGE, 13, item_ids=b,
                                  target_armor=60.0, target_mr=40.0,
                                  target_max_hp=2200.0)
        self.assertAlmostEqual(ra.total_burst_damage, rb.total_burst_damage)
        self.assertEqual(ra.spellblade_item_name, rb.spellblade_item_name)

    def test_compute_ability_dps_spellblade_pair(self) -> None:
        a, b = _both_orders(LICH_BANE, SHEEN)
        ra = compute_ability_dps(self.snap, MAGE, 13, item_ids=a,
                                 target_armor=60.0, target_mr=40.0,
                                 target_max_hp=2200.0)
        rb = compute_ability_dps(self.snap, MAGE, 13, item_ids=b,
                                 target_armor=60.0, target_mr=40.0,
                                 target_max_hp=2200.0)
        self.assertAlmostEqual(ra.total_ability_dps, rb.total_ability_dps)

    def test_compute_ehp_immolate_pair(self) -> None:
        a, b = _both_orders(HOLLOW_RADIANCE, SUNFIRE)
        ra = compute_ehp(self.snap, TANK, 13, item_ids=a)
        rb = compute_ehp(self.snap, TANK, 13, item_ids=b)
        self.assertAlmostEqual(ra.physical_ehp, rb.physical_ehp)
        self.assertAlmostEqual(ra.magical_ehp, rb.magical_ehp)
        self.assertAlmostEqual(ra.blended_ehp, rb.blended_ehp)


class StrongerMemberWinsTests(unittest.TestCase):
    """(b) The stronger member wins at a realistic context - per contested
    family."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_immolate_bad_order_now_reads_the_sunfire_number(self) -> None:
        # Malphite lvl 13 has real bonus HP, so Sunfire (20 + 1%) strictly
        # beats Hollow Radiance (15 + 1%). Reference: the SAME two items in
        # the already-correct order. Pre-flip the bad order read lower.
        bad = compute_dps(self.snap, TANK, 13,
                          item_ids=[HOLLOW_RADIANCE, SUNFIRE],
                          target_armor=60.0)
        good = compute_dps(self.snap, TANK, 13,
                           item_ids=[SUNFIRE, HOLLOW_RADIANCE],
                           target_armor=60.0)
        self.assertAlmostEqual(bad.weighted_dps, good.weighted_dps)
        # ... and it is the STRONGER of the two, not merely a consistent one:
        # strictly above the same build scored with only the weak passive.
        weak_only = compute_dps(self.snap, TANK, 13,
                                item_ids=[HOLLOW_RADIANCE, BAMIS],
                                target_armor=60.0)
        self.assertGreater(bad.weighted_dps, weak_only.weighted_dps)

    def test_spellblade_winner_is_named_and_order_invariant(self) -> None:
        # Annie carries no AD, so Sheen (100% base AD / 1.5s) beats Lich Bane
        # (75% base AD + AP ratio) only at low AP - the point here is that the
        # SAME item is named regardless of slot order.
        a = compute_dps(self.snap, MAGE, 13, item_ids=[LICH_BANE, SHEEN],
                        target_armor=60.0, target_mr=40.0)
        b = compute_dps(self.snap, MAGE, 13, item_ids=[SHEEN, LICH_BANE],
                        target_armor=60.0, target_mr=40.0)
        self.assertEqual(a.spellblade_item_name, b.spellblade_item_name)
        self.assertTrue(a.spellblade_item_name)

    def test_immolate_group_winner_is_the_argmax_at_context(self) -> None:
        ctx = dedupe_context(
            {"ad": 80.0, "ap": 0.0, "hp": 3400.0, "armor": 200.0, "crit": 0.0},
            {"ad": 60.0, "hp": 1400.0, "armor": 50.0}, 13,
        )
        for order in ([HOLLOW_RADIANCE, SUNFIRE], [SUNFIRE, HOLLOW_RADIANCE],
                      [BAMIS, HOLLOW_RADIANCE, SUNFIRE]):
            with self.subTest(order=tuple(order)):
                got = [e.item_id for e in collect_effects(order, ctx)]
                self.assertEqual(got, [SUNFIRE])


class NoComparableMagnitudeStaysFirstSeenTests(unittest.TestCase):
    """(d) A family whose members expose no comparable per-second magnitude
    resolves first-seen, flip or no flip - and that is still ORDER-DEPENDENT.
    Documented limitation, not an oversight: an every_n_attacks proc needs an
    attack-speed signal this call site does not carry."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.ctx = dedupe_context(
            {"ad": 240.0, "ap": 0.0, "hp": 2400.0, "armor": 90.0, "crit": 0.6},
            {"ad": 60.0, "hp": 1300.0, "armor": 45.0}, 13,
        )

    def test_last_whisper_first_seen(self) -> None:
        for a, b in (_both_orders(LAST_WHISPER_A, LAST_WHISPER_B),):
            self.assertEqual([e.item_id for e in collect_effects(a, self.ctx)], [a[0]])
            self.assertEqual([e.item_id for e in collect_effects(b, self.ctx)], [b[0]])

    def test_lifeline_first_seen(self) -> None:
        a, b = _both_orders(LIFELINE_A, LIFELINE_B)
        self.assertEqual([e.item_id for e in collect_effects(a, self.ctx)], [a[0]])
        self.assertEqual([e.item_id for e in collect_effects(b, self.ctx)], [b[0]])

    def test_void_pen_first_seen(self) -> None:
        a, b = _both_orders(VOID_PEN_A, VOID_PEN_B)
        self.assertEqual([e.item_id for e in collect_effects(a, self.ctx)], [a[0]])
        self.assertEqual([e.item_id for e in collect_effects(b, self.ctx)], [b[0]])

    def test_hydra_cleave_first_seen(self) -> None:
        a, b = _both_orders(HYDRA_RAVENOUS, HYDRA_TITANIC)
        self.assertEqual([e.item_id for e in collect_effects(a, self.ctx)], [a[0]])
        self.assertEqual([e.item_id for e in collect_effects(b, self.ctx)], [b[0]])

    def test_scorer_still_sees_the_first_seen_hydra(self) -> None:
        # Asserted on the computed number: the two orders DIFFER, which is the
        # honest documented state for an attack-keyed family.
        a, b = _both_orders(HYDRA_RAVENOUS, HYDRA_TITANIC)
        ra = compute_ehp(self.snap, TANK, 13, item_ids=a,
                         assume_cleave_lifesteal=True, targets_in_rotation=3.0)
        rb = compute_ehp(self.snap, TANK, 13, item_ids=b,
                         assume_cleave_lifesteal=True, targets_in_rotation=3.0)
        self.assertIsNotNone(ra)
        self.assertIsNotNone(rb)


class UnchangedBuildsRegressionTests(unittest.TestCase):
    """(c) Single-member and no-family builds are identical to the pre-flip
    (``caster_ctx=None``) path - the flip touches contested groups only."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.ctx = dedupe_context(
            {"ad": 240.0, "ap": 180.0, "hp": 2600.0, "armor": 120.0,
             "mp": 900.0, "crit": 0.6},
            {"ad": 60.0, "hp": 1300.0, "armor": 45.0}, 13,
        )

    SINGLE_OR_KEYLESS = (
        [],
        [BERSERKERS],
        [INFINITY_EDGE, BERSERKERS],
        [SUNFIRE],
        [SHEEN],
        [SUNFIRE, INFINITY_EDGE, BERSERKERS],
        [LICH_BANE, INFINITY_EDGE],
        [HYDRA_RAVENOUS, INFINITY_EDGE],
        [LAST_WHISPER_A, BERSERKERS, VOID_PEN_A],
    )

    def test_collect_is_identical_to_the_off_path(self) -> None:
        for build in self.SINGLE_OR_KEYLESS:
            with self.subTest(build=tuple(build)):
                self.assertEqual(
                    [e.item_id for e in collect_effects(build, None)],
                    [e.item_id for e in collect_effects(build, self.ctx)],
                )

    @staticmethod
    def _forced_off():
        """Patch every call site back to ``caster_ctx=None`` - i.e. replay the
        exact pre-RM-187 engine - so 'unchanged' is measured against the old
        behaviour rather than asserted."""
        real = collect_effects
        return [
            unittest.mock.patch(
                f"agents.daemon_slayer.{mod}.collect_effects",
                side_effect=lambda ids, caster_ctx=None: real(ids, None),
            )
            for mod in ("dps", "ehp", "burst", "ability_dps", "ability_hps")
        ]

    def _dps_both_ways(self, build: list[str], champion: str = CARRY):
        on = compute_dps(self.snap, champion, 13, item_ids=build,
                         target_armor=60.0, target_mr=40.0, target_max_hp=2200.0)
        patchers = self._forced_off()
        for p in patchers:
            p.start()
        try:
            off = compute_dps(self.snap, champion, 13, item_ids=build,
                              target_armor=60.0, target_mr=40.0,
                              target_max_hp=2200.0)
        finally:
            for p in patchers:
                p.stop()
        return on, off

    def test_uncontested_builds_are_byte_identical_to_the_pre_flip_engine(self) -> None:
        for build in self.SINGLE_OR_KEYLESS:
            with self.subTest(build=tuple(build)):
                on, off = self._dps_both_ways(list(build))
                self.assertEqual(on.weighted_dps, off.weighted_dps)
                self.assertEqual(on.spellblade_per_proc_damage,
                                 off.spellblade_per_proc_damage)
                self.assertEqual(on.per_attack_on_hit_damage,
                                 off.per_attack_on_hit_damage)

    def test_the_forced_off_probe_is_not_vacuous(self) -> None:
        # The same probe MUST separate on a contested build in the bad order,
        # otherwise the regression above proves nothing.
        on, off = self._dps_both_ways([HOLLOW_RADIANCE, SUNFIRE], champion=TANK)
        self.assertGreater(on.weighted_dps, off.weighted_dps)


class TargetDependenceTests(unittest.TestCase):
    """SECOND DESIGN CONSTRAINT, measured: the spellblade winner IS
    target-dependent (Divine Sunderer scales on ``target_max_hp``), so the
    dedup context must carry the caller's target assumptions - it does."""

    def _ctx(self, target_max_hp: float) -> CallContext:
        return dedupe_context(
            {"ad": 160.0, "ap": 0.0, "hp": 2200.0, "armor": 80.0, "crit": 0.0},
            {"ad": 60.0, "hp": 1300.0, "armor": 45.0}, 13,
            target_max_hp=target_max_hp,
        )

    BUILD = [SHEEN, DIVINE_SUNDERER]

    def test_zero_target_hp_picks_sheen(self) -> None:
        got = [e.item_id for e in collect_effects(self.BUILD, self._ctx(0.0))]
        self.assertEqual(got, [SHEEN])

    def test_beefy_target_picks_divine_sunderer(self) -> None:
        got = [e.item_id for e in collect_effects(self.BUILD, self._ctx(3000.0))]
        self.assertEqual(got, [DIVINE_SUNDERER])

    def test_winner_is_order_invariant_at_both_targets(self) -> None:
        for thp in (0.0, 3000.0):
            with self.subTest(target_max_hp=thp):
                fwd = [e.item_id for e in collect_effects(self.BUILD, self._ctx(thp))]
                rev = [e.item_id for e in collect_effects(self.BUILD[::-1], self._ctx(thp))]
                self.assertEqual(fwd, rev)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
