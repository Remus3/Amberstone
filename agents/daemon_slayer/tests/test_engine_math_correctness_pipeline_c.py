"""Engine-math CORRECTNESS verification tests (parallel-audit pipeline C).

These are property / derivation tests: every expected value is recomputed
from the Riot formula in-test (no hardcoded magic numbers, no fragile
cross-item comparison asserts). They harden the suite against silent
regressions in the five audit areas below. As of ENGINE_VERSION 1.5.0
all five are believed correct; this file proves it and trips loudly if
any one drifts.

Audit areas (subagent C scope):

1. Penetration pipeline order - flat reduction -> % reduction -> % pen
   -> flat pen - in ``effects.effective_target_armor`` /
   ``effective_target_mr``. The ``ability_dps.py`` comment was recently
   corrected to match; we assert the SHARED function (which both
   ``dps.compute_dps`` and ``ability_dps`` call) applies exactly that
   order by deriving the expected post-pipeline resist from first
   principles and proving the order is non-commutative.

2. Attack-speed scaling - ``base * (1 + perlevel%/100 * (level-1))``,
   plus item bonus AS stacking ``base * (1 + Sigma pct)`` end-to-end
   through the engine. Believed correct Riot math - PROVEN here, NOT
   changed.

3. Per-level ABILITY proc lambdas in ``_effects_data.py`` are
   intentionally LINEAR in level (optionally with a monotone cap, e.g.
   Kraken Slayer ``min(200, 150 + 5*(level-1))``), NEVER quadratic.
   This is distinct from champion base-stat growth which IS Riot-
   quadratic since the 1.5.0 fix. A regression that "fixed" a linear
   ability lambda by making it quadratic would make the per-level
   deltas ACCELERATE - this test trips on that.

4. ``core.build_order`` unique-passive family rule still holds (no
   family literal in code; engine dedup forced; >=6 families). Defers
   to the dedicated guard test; this is a lightweight cross-check so
   pipeline C's report has a direct signal. NO family map is added.

5. Champion base-stat growth uses the quadratic multiplier
   ``(n-1)*(0.7025 + 0.0175*(n-1))`` end-to-end through the engine's
   ``_scale_champion_base`` (not just the unit ``scaled`` helper),
   exact at L1 (mult 0) and L18 (mult 17.0), strictly below linear in
   between.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import (
    CallContext,
    ItemEffect,
    effective_target_armor,
    effective_target_mr,
)
from agents.daemon_slayer.engine import _scale_champion_base, build_champion
from agents.daemon_slayer.stats import (
    CHAMPION_SCALING_RULES,
    attack_speed_scaling,
    growth_multiplier,
    scaled,
)


def _riot_growth(n: int) -> float:
    """Independent re-derivation of the Riot per-level growth multiplier.

    Deliberately a SEPARATE expression from stats.growth_multiplier so a
    typo in the engine cannot also silently pass the test (the test does
    not call the function it is verifying to compute its own expected).
    ``(n-1)*0.7025 + (n-1)^2*0.0175`` is the algebraic expansion of
    ``(n-1)*(0.7025 + 0.0175*(n-1))``.
    """
    k = n - 1
    return k * 0.7025 + k * k * 0.0175


def _riot_scaled(base: float, perlevel: float, n: int) -> float:
    return base + perlevel * _riot_growth(n)


def _ctx(level: int = 11) -> CallContext:
    return CallContext(base_ad=0.0, bonus_ad=0.0, level=level)


# --------------------------------------------------------------------------
# Area 5 + the unit formula: champion base-stat growth is Riot-quadratic
# --------------------------------------------------------------------------
class GrowthMultiplierPropertyTests(unittest.TestCase):
    """growth_multiplier matches the independently-derived Riot formula at
    EVERY level, with the two endpoint identities exact."""

    def test_matches_independent_riot_formula_every_level(self) -> None:
        for n in range(1, 19):
            self.assertAlmostEqual(
                growth_multiplier(n), _riot_growth(n), places=12,
                msg=f"growth_multiplier({n}) diverges from Riot formula",
            )

    def test_endpoint_identities_exact(self) -> None:
        # L1 multiplier is exactly 0 (no growth); L18 is exactly 17.0
        # (the quadratic and linear curves coincide only here).
        self.assertEqual(growth_multiplier(1), 0.0)
        self.assertAlmostEqual(growth_multiplier(18), 17.0, places=12)

    def test_strictly_below_linear_between_endpoints(self) -> None:
        # The exact 1.5.0-fix guard: quadratic < naive linear (n-1) for
        # every interior level. If someone reverts to linear scaling this
        # whole property collapses.
        for n in range(2, 18):
            self.assertLess(
                growth_multiplier(n), float(n - 1),
                msg=f"growth at L{n} not strictly below linear - "
                "linear-scaling regression?",
            )

    def test_scaled_helper_equals_base_plus_perlevel_times_growth(self) -> None:
        # Property over a grid of (base, perlevel, level) triples - no
        # hardcoded outputs; expected is recomputed from the formula.
        for base, per in ((690.0, 98.0), (38.0, 4.2), (69.0, 4.5),
                           (0.0, 0.0), (580.0, 99.0)):
            for n in range(1, 19):
                self.assertAlmostEqual(
                    scaled(base, per, n), _riot_scaled(base, per, n),
                    places=9,
                    msg=f"scaled({base},{per},{n}) != Riot quadratic",
                )

    def test_zero_perlevel_is_flat_all_levels(self) -> None:
        # crit has critperlevel == 0 for every champion - must stay flat.
        for n in range(1, 19):
            self.assertEqual(scaled(123.0, 0.0, n), 123.0)


class EngineScalesChampionBaseQuadraticTests(unittest.TestCase):
    """End-to-end: the ENGINE's _scale_champion_base applies the quadratic
    multiplier to real champion records, not just the unit helper."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _raw_stats(self, champ_id: str) -> dict:
        c = self.snap.champion(champ_id)
        return c.get("stats") or (c.get("ddragon") or {}).get("stats") or {}

    def test_scale_champion_base_is_quadratic_for_scaled_rules(self) -> None:
        # For each non-AS scaling rule, the engine output must equal
        # base + perlevel * Riot-quadratic-growth at every level.
        for champ_id in ("Garen", "Lux", "Aatrox", "Malphite"):
            raw = self._raw_stats(champ_id)
            for n in (1, 6, 11, 13, 18):
                scaled_block, _raw_base = _scale_champion_base(raw, n)
                for rule in CHAMPION_SCALING_RULES:
                    if rule.multiplicative_item_pct:
                        continue  # AS handled separately (different math)
                    base = float(raw.get(rule.base_field, 0.0))
                    per = float(raw.get(rule.perlevel_field, 0.0))
                    expected = _riot_scaled(base, per, n)
                    self.assertAlmostEqual(
                        scaled_block[rule.canonical_key], expected, places=6,
                        msg=f"{champ_id} {rule.canonical_key}@L{n}: engine "
                        f"{scaled_block[rule.canonical_key]} != Riot "
                        f"quadratic {expected}",
                    )

    def test_endpoints_exact_interior_below_linear(self) -> None:
        # L1 == base; L18 == base + perlevel*17; interior strictly below
        # the (buggy) linear value. Proves the curve, not a point.
        raw = self._raw_stats("Garen")
        hp_b = float(raw["hp"])
        hp_pl = float(raw["hpperlevel"])
        s1, _ = _scale_champion_base(raw, 1)
        s18, _ = _scale_champion_base(raw, 18)
        self.assertAlmostEqual(s1["hp"], hp_b, places=6)
        self.assertAlmostEqual(s18["hp"], hp_b + hp_pl * 17.0, places=6)
        for n in range(2, 18):
            sn, _ = _scale_champion_base(raw, n)
            linear = hp_b + hp_pl * (n - 1)
            self.assertLess(
                sn["hp"], linear,
                msg=f"Garen hp@L{n} {sn['hp']} not below linear {linear} "
                "- engine regressed to linear scaling",
            )


# --------------------------------------------------------------------------
# Area 2: attack-speed scaling (Riot math - prove, do NOT change)
# --------------------------------------------------------------------------
class AttackSpeedScalingPropertyTests(unittest.TestCase):
    """AS uses base * (1 + perlevel%/100 * (level-1)) - LINEAR in level,
    distinct from the quadratic base-stat growth. Item AS stacks into
    the same multiplicative bonus sum."""

    def test_unit_formula_property_grid(self) -> None:
        for base_as, per_pct in ((0.651, 2.5), (0.625, 3.65),
                                  (0.658, 2.0), (0.638, 3.0)):
            for n in range(1, 19):
                expected = base_as * (1.0 + (per_pct / 100.0) * (n - 1))
                self.assertAlmostEqual(
                    attack_speed_scaling(base_as, per_pct, n), expected,
                    places=9,
                    msg=f"AS({base_as},{per_pct},{n}) != Riot AS formula",
                )

    def test_as_is_linear_in_level_not_quadratic(self) -> None:
        # Equal level steps must give equal AS deltas (linearity). If AS
        # were ever "fixed" to the quadratic growth curve this fails.
        base_as, per_pct = 0.651, 2.5
        deltas = [
            attack_speed_scaling(base_as, per_pct, n + 1)
            - attack_speed_scaling(base_as, per_pct, n)
            for n in range(1, 18)
        ]
        for d in deltas[1:]:
            self.assertAlmostEqual(d, deltas[0], places=12,
                                   msg="AS growth is not linear in level")

    def test_as_level_1_is_base(self) -> None:
        self.assertAlmostEqual(attack_speed_scaling(0.651, 2.5, 1),
                               0.651, places=9)


class AttackSpeedItemStackEndToEndTests(unittest.TestCase):
    """Engine end-to-end: item AS% stacks into base * (1 + Sigma pct)
    alongside the per-level bonus (the engine's documented AS rule)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_item_as_pct_stacks_on_base_with_level_bonus(self) -> None:
        champ_id = "Aatrox"
        c = self.snap.champion(champ_id)
        raw = c.get("stats") or (c.get("ddragon") or {}).get("stats") or {}
        base_as = float(raw.get("attackspeed", 0.0))
        per_pct = float(raw.get("attackspeedperlevel", 0.0))
        level = 13

        no_item = build_champion(self.snap, champ_id, level, item_ids=[])
        as_no_item = no_item.stats["as"]
        # Per-level bonus only: base * (1 + perlevel%/100 * (level-1)).
        expected_no_item = base_as * (1.0 + (per_pct / 100.0) * (level - 1))
        self.assertAlmostEqual(as_no_item, expected_no_item, places=6)

        # Berserker's Greaves (3006). Engine rule: rebuild from base so
        # the item pct stacks ADDITIVELY with the per-level bonus
        # fraction: base * (1 + level_bonus_frac + item_frac). item_frac
        # is read from the item's DDragon PercentAttackSpeedMod (data-
        # derived, not a hardcoded constant) so this asserts the engine's
        # AS-combine math, not a memorized number.
        item = self.snap.item("3006")
        item_as_frac = float(item.get("stats", {})
                             .get("PercentAttackSpeedMod", 0.0))
        self.assertGreater(item_as_frac, 0.0,
                           "Berserker's Greaves should carry "
                           "PercentAttackSpeedMod in the snapshot")
        with_item = build_champion(self.snap, champ_id, level,
                                   item_ids=["3006"])
        as_with_item = with_item.stats["as"]
        level_frac = (per_pct / 100.0) * (level - 1)
        expected_with_item = base_as * (1.0 + level_frac + item_as_frac)
        self.assertAlmostEqual(as_with_item, expected_with_item, places=6,
                               msg="engine AS item-stack rule diverged "
                               "from base*(1 + level_frac + item_frac)")


# --------------------------------------------------------------------------
# Area 1: penetration pipeline order (flat red -> % red -> % pen -> flat pen)
# --------------------------------------------------------------------------
class ArmorPenPipelineOrderTests(unittest.TestCase):
    """effective_target_armor must apply, in order:

        armor - red_flat
        * (1 - red_pct)
        * (1 - pen_pct)
        - (pen_flat + lethality*level_scale)

    Order is NON-commutative (multiply-before-subtract vs subtract-
    before-multiply give different results), so a derived scenario with
    every stage non-trivial pins the order exactly. ability_dps.py and
    compute_dps both call this shared function, so verifying it once
    covers both call sites.
    """

    def test_full_pipeline_derived_value(self) -> None:
        target_armor = 100.0
        red_flat, red_pct, pen_pct, pen_flat = 10.0, 0.30, 0.35, 12.0
        eff = [
            ItemEffect(item_id="t1", name="redflat",
                       armor_reduction_flat=red_flat),
            ItemEffect(item_id="t2", name="redpct",
                       armor_reduction_pct=red_pct),
            ItemEffect(item_id="t3", name="penpct", armor_pen_pct=pen_pct),
            ItemEffect(item_id="t4", name="penflat",
                       armor_pen_flat=pen_flat),
        ]
        # Derive expected in the documented order.
        a = target_armor - red_flat          # 90
        a = a * (1.0 - red_pct)             # 63
        a = a * (1.0 - pen_pct)             # 40.95
        a = a - pen_flat                     # 28.95
        expected = max(0.0, a)
        got = effective_target_armor(target_armor, eff, level=None)
        self.assertAlmostEqual(got, expected, places=9)

    def test_order_is_not_commutative_proof(self) -> None:
        # Prove the engine uses THIS order and not a plausible wrong one
        # (e.g. subtract all flats first, then all %s). The two orders
        # must yield different numbers for this scenario, and the engine
        # must match only the documented one.
        target_armor = 120.0
        red_flat, red_pct, pen_pct, pen_flat = 15.0, 0.25, 0.40, 18.0
        eff = [
            ItemEffect(item_id="r1", name="rf",
                       armor_reduction_flat=red_flat),
            ItemEffect(item_id="r2", name="rp",
                       armor_reduction_pct=red_pct),
            ItemEffect(item_id="r3", name="pp", armor_pen_pct=pen_pct),
            ItemEffect(item_id="r4", name="pf", armor_pen_flat=pen_flat),
        ]
        documented = (((target_armor - red_flat) * (1 - red_pct))
                      * (1 - pen_pct)) - pen_flat
        wrong_all_flat_first = ((target_armor - red_flat - pen_flat)
                                * (1 - red_pct) * (1 - pen_pct))
        self.assertNotAlmostEqual(documented, wrong_all_flat_first, places=3)
        got = effective_target_armor(target_armor, eff, level=None)
        self.assertAlmostEqual(got, documented, places=9)
        self.assertNotAlmostEqual(got, wrong_all_flat_first, places=3)

    def test_lethality_is_level_scaled_into_flat_pen(self) -> None:
        # lethality folds into the flat-pen term at 0.6 + 0.4*level/18,
        # i.e. 60% at L1, 100% at L18 (linear). Derive at three levels.
        target_armor = 80.0
        lethality = 20.0
        eff = [ItemEffect(item_id="L1", name="leth", lethality=lethality)]
        for level, scale in ((1, 0.6 + 0.4 * 1 / 18.0),
                             (11, 0.6 + 0.4 * 11 / 18.0),
                             (18, 1.0)):
            expected = max(0.0, target_armor - lethality * scale)
            got = effective_target_armor(target_armor, eff, level=level)
            self.assertAlmostEqual(got, expected, places=9,
                                   msg=f"lethality level-scale wrong @L{level}")

    def test_floors_at_zero(self) -> None:
        eff = [ItemEffect(item_id="b1", name="big", armor_pen_flat=999.0)]
        self.assertEqual(
            effective_target_armor(50.0, eff, level=None), 0.0)

    def test_negative_armor_passthrough(self) -> None:
        # Pen/reduction is a no-op on already-negative armor (external
        # shred). Documented behavior - must hold.
        eff = [ItemEffect(item_id="n1", name="pp", armor_pen_pct=0.40,
                          armor_pen_flat=10.0)]
        self.assertEqual(
            effective_target_armor(-25.0, eff, level=18), -25.0)

    def test_no_modifiers_passthrough_preserves_input(self) -> None:
        self.assertEqual(
            effective_target_armor(57.0,
                                   [ItemEffect(item_id="z1", name="x")],
                                   level=11), 57.0)


class MagicPenPipelineOrderTests(unittest.TestCase):
    """effective_target_mr is the symmetric magic-side pipeline:
    mr - red_flat ; * (1 - red_pct) ; * (1 - pen_pct) ; - pen_flat.
    No lethality term on the magic side (lethality is physical-only)."""

    def test_full_pipeline_derived_value(self) -> None:
        target_mr = 90.0
        red_flat, red_pct, pen_pct, pen_flat = 8.0, 0.20, 0.40, 15.0
        eff = [
            ItemEffect(item_id="m1", name="mrf",
                       mr_reduction_flat=red_flat),
            ItemEffect(item_id="m2", name="mrp",
                       mr_reduction_pct=red_pct),
            ItemEffect(item_id="m3", name="mpp", magic_pen_pct=pen_pct),
            ItemEffect(item_id="m4", name="mpf", magic_pen_flat=pen_flat),
        ]
        m = target_mr - red_flat
        m = m * (1.0 - red_pct)
        m = m * (1.0 - pen_pct)
        m = m - pen_flat
        expected = max(0.0, m)
        self.assertAlmostEqual(
            effective_target_mr(target_mr, eff), expected, places=9)

    def test_order_not_commutative_proof(self) -> None:
        target_mr = 100.0
        red_pct, pen_flat = 0.30, 20.0
        eff = [
            ItemEffect(item_id="o1", name="mrp",
                       mr_reduction_pct=red_pct),
            ItemEffect(item_id="o2", name="mpf",
                       magic_pen_flat=pen_flat),
        ]
        documented = target_mr * (1 - red_pct) - pen_flat       # 50.0
        wrong_flat_first = (target_mr - pen_flat) * (1 - red_pct)  # 56.0
        self.assertNotAlmostEqual(documented, wrong_flat_first, places=3)
        got = effective_target_mr(target_mr, eff)
        self.assertAlmostEqual(got, documented, places=9)
        self.assertNotAlmostEqual(got, wrong_flat_first, places=3)

    def test_floors_at_zero_and_negative_passthrough(self) -> None:
        self.assertEqual(
            effective_target_mr(
                30.0,
                [ItemEffect(item_id="f1", name="v", magic_pen_flat=99.0)]),
            0.0)
        self.assertEqual(
            effective_target_mr(
                -15.0,
                [ItemEffect(item_id="f2", name="v", magic_pen_pct=0.5)]),
            -15.0)

    def test_no_lethality_term_on_magic_side(self) -> None:
        # lethality must NOT affect MR even with a level (physical-only).
        eff = [ItemEffect(item_id="g1", name="leth", lethality=30.0)]
        self.assertEqual(effective_target_mr(60.0, eff), 60.0)


class PipelineSharedAcrossCallSitesTests(unittest.TestCase):
    """compute_dps and ability_dps both import effective_target_armor /
    effective_target_mr from effects - so the corrected ability_dps.py
    comment ('flat reduction -> % reduction -> % pen -> flat pen') is
    backed by the SAME code path proven above. Assert the symbol identity
    so a future refactor cannot fork the pipeline silently."""

    def test_dps_and_ability_dps_use_same_pen_functions(self) -> None:
        from agents.daemon_slayer import ability_dps as adps
        from agents.daemon_slayer import dps as ddps
        self.assertIs(adps.effective_target_armor, effective_target_armor)
        self.assertIs(adps.effective_target_mr, effective_target_mr)
        self.assertIs(ddps.effective_target_armor, effective_target_armor)
        self.assertIs(ddps.effective_target_mr, effective_target_mr)


# --------------------------------------------------------------------------
# Area 3: per-level ABILITY proc lambdas in _effects_data.py are LINEAR
# --------------------------------------------------------------------------
class AbilityProcLambdaLinearityTests(unittest.TestCase):
    """Periodic-proc ``bonus_damage`` callables that scale with
    ``c.level`` are intentionally LINEAR in level, optionally with a
    monotone CAP (e.g. Kraken Slayer Bring It Down =
    ``min(200, 150 + 5*(level-1))``, Navori = ``min(168, 120 +
    4*(level-1))``). This is distinct from champion base-stat growth
    which IS Riot-quadratic since the 1.5.0 fix.

    The diagnostic property of a quadratic regression is ACCELERATING
    successive deltas. A correct linear (or linear-then-clamped) proc
    has non-increasing deltas that take at most two distinct values:
    the constant ramp slope, then 0 once capped. We assert:

      * deltas are non-increasing (no acceleration -> not quadratic), and
      * the set of distinct deltas has size <= 2 (a single ramp slope
        plus an optional 0 cap tail) - any genuine curvature produces
        many distinct, increasing deltas.

    We do NOT assert a specific slope (that is per-item data, not the
    property under audit) and we do NOT "fix" any lambda - a correct
    linear lambda passing here is the expected, valuable outcome.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.effects import ITEM_EFFECTS
        cls.effects = ITEM_EFFECTS

    def _proc_vals_over_levels(self, proc) -> list[float] | None:
        if not callable(proc.bonus_damage):
            return None
        vals: list[float] = []
        for lvl in range(1, 19):
            try:
                v = proc.resolve_damage(_ctx(lvl))
            except Exception:
                return None  # context-dependent beyond level - skip
            vals.append(float(v))
        return vals

    def test_level_scaling_procs_are_linear_or_clamped_never_quadratic(
        self,
    ) -> None:
        checked = 0
        for eff in self.effects.values():
            for proc in eff.periodics:
                vals = self._proc_vals_over_levels(proc)
                if vals is None:
                    continue
                deltas = [round(b - a, 9)
                          for a, b in zip(vals, vals[1:])]
                if all(abs(d) < 1e-9 for d in deltas):
                    continue  # constant in level - not a scaling proc
                checked += 1
                # 1) No acceleration: deltas must be non-increasing. A
                #    quadratic-up scaling has strictly increasing deltas.
                for i in range(1, len(deltas)):
                    self.assertLessEqual(
                        deltas[i], deltas[i - 1] + 1e-9,
                        msg=f"{eff.name}/{proc.name}: per-level deltas "
                        f"ACCELERATE ({deltas}) - looks quadratic. "
                        "Ability proc scalings must stay linear.",
                    )
                # 2) Shape is a single ramp (+ optional cap tail): at
                #    most two distinct delta values. Genuine curvature
                #    yields many distinct deltas.
                distinct = sorted({d for d in deltas})
                self.assertLessEqual(
                    len(distinct), 2,
                    msg=f"{eff.name}/{proc.name}: >2 distinct per-level "
                    f"deltas {distinct} - not a linear(+clamp) scaling; "
                    "a quadratic 'fix' likely leaked in.",
                )
                # If two distinct values, the cap tail must be the 0 one
                # (ramp then clamp), i.e. the smaller value is ~0.
                if len(distinct) == 2:
                    self.assertAlmostEqual(
                        min(distinct), 0.0, places=9,
                        msg=f"{eff.name}/{proc.name}: two slopes "
                        f"{distinct} but neither is a flat cap - "
                        "non-linear scaling.",
                    )
        self.assertGreater(
            checked, 0,
            "no level-scaling periodic procs exercised - registry shape "
            "changed; re-verify this test still covers the property",
        )

    def test_kraken_slayer_is_linear_ramp_then_clamp_at_cap(self) -> None:
        # Anchor one well-known proc against its exact Riot shape derived
        # from the endpoints: Kraken Slayer "Bring It Down" ramps
        # linearly 150 -> 200 then clamps. The ramp slope and cap are
        # derived, not hardcoded magic: slope = (cap - start)/(cap_level
        # - 1) where the proc reaches its max and holds.
        target = None
        for eff in self.effects.values():
            if "Kraken" not in eff.name:
                continue
            for proc in eff.periodics:
                vals = self._proc_vals_over_levels(proc)
                if vals and abs(vals[0] - 150.0) < 1e-6:
                    target = vals
                    break
            if target:
                break
        self.assertIsNotNone(target,
                             "Kraken Slayer scaling proc not found")
        start, cap = target[0], target[-1]
        # The value at every level must equal min(cap, linear ramp from
        # the first two samples' slope) - i.e. piecewise-linear, never
        # above the cap, never accelerating.
        slope = target[1] - target[0]
        for i, v in enumerate(target):
            lvl = i + 1
            expected = min(cap, start + slope * (lvl - 1))
            self.assertAlmostEqual(
                v, expected, places=6,
                msg=f"Kraken Slayer @L{lvl}={v} not on the linear-ramp"
                f"-then-clamp line (expected {expected})",
            )
        self.assertGreater(slope, 0.0)
        self.assertEqual(cap, max(target))


# --------------------------------------------------------------------------
# Area 4: build_order unique-passive family rule (cross-check)
# --------------------------------------------------------------------------
class BuildOrderFamilyRuleCrossCheckTests(unittest.TestCase):
    """Lightweight cross-check so pipeline C reports a direct signal. The
    authoritative anti-drift guard is tests/test_build_order_no_double_
    guard.py; here we just confirm (a) the planner source carries NO
    family literal and forces engine dedup, and (b) the engine still
    defines >=6 unique-passive families. We add NO family map (forbidden
    by the guardrails) - only verify the existing rule holds."""

    def test_planner_has_no_family_literal_and_forces_dedup(self) -> None:
        from pathlib import Path

        from agents.daemon_slayer.effects import ITEM_EFFECTS
        src_path = (Path(__file__).resolve().parents[3]
                    / "core" / "build_order.py")
        src = src_path.read_text(encoding="utf-8")
        # Strip docstring/comments - only executable code must be clean.
        code_lines: list[str] = []
        in_doc = False
        for ln in src.splitlines():
            s = ln.strip()
            if s.startswith('"""') and not in_doc:
                in_doc = not (s.count('"""') >= 2)
                continue
            if in_doc:
                if s.endswith('"""') or s.count('"""') >= 1:
                    in_doc = False
                continue
            code_lines.append(ln.split("#", 1)[0])
        code = "\n".join(code_lines).lower()
        families = {
            e.unique_passive_key
            for e in ITEM_EFFECTS.values()
            if getattr(e, "unique_passive_key", "")
        }
        for fam in families:
            self.assertNotIn(f'"{fam}"', code)
            self.assertNotIn(f"'{fam}'", code)
        self.assertIn('filter_shared_uniques"] = True', src)

    def test_engine_defines_at_least_six_families(self) -> None:
        from agents.daemon_slayer.effects import ITEM_EFFECTS
        families = {
            e.unique_passive_key
            for e in ITEM_EFFECTS.values()
            if getattr(e, "unique_passive_key", "")
        }
        for known in ("spellblade", "lifeline", "immolate"):
            self.assertIn(known, families,
                          f"{known!r} family vanished from effects.py")
        self.assertGreaterEqual(
            len(families), 6,
            f"expected >=6 unique-passive families, found "
            f"{len(families)}: {sorted(families)}",
        )


if __name__ == "__main__":
    unittest.main()
