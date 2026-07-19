"""ENGINE 1.57.0 (2026-05-25) - Death's Dance Defy heal-on-takedown.

Closes the ``ehp.py`` Phase 6 deliberate omission: "Death's Dance Defy
heal (75% bonus AD on takedown over 2s) is DEFERRED to Phase 6.5: the
takedown-rate assumption is uncertain enough that a Phase 6 first-pass
would over- or under-credit it" pending since ENGINE 1.28.0
(2026-05-21).

The shipped schema:

* NEW ``ItemHeal.takedown_gated: bool = False`` field on
  ``_effects_types.py`` ItemHeal dataclass. When True, the consumer
  multiplies the resolved per-trigger magnitude by the operator-
  tunable ``_TAKEDOWN_RATE_PER_FIGHT`` constant. Default False
  preserves ENGINE 1.29.0 byte-identical resolve_magnitude behavior
  for Sundered Sky and any other always-on heal entry.

* NEW ``ehp._TAKEDOWN_RATE_PER_FIGHT = 0.5`` operator-tunable module
  constant. Mirrors the Phase 6.5 ``_MISSING_HP_SHARE_FOR_HEALS = 0.5``
  precedent and the ENGINE 1.33.0 ``_CC_EFFECTIVENESS_FACTOR = 0.5``
  precedent: single-constant calibration midpoint, deliberately not
  varying per-champion or per-mode.

* ``ehp._collect_heals`` gains a ``takedown_rate: float =
  _TAKEDOWN_RATE_PER_FIGHT`` kwarg. For each ItemHeal with
  ``takedown_gated=True``, the resolved magnitude is multiplied by
  ``max(0.0, takedown_rate)`` before contributing to the totals.

* SR 6333 + Arena 226333 Death's Dance promoted from defensive_only
  to heal contributors. Both carry ``ItemHeal(bonus_ad_scaling=0.75,
  takedown_gated=True)`` matching Meraki 16.10.1 Defy: "heals you for
  75% bonus AD over 2 seconds" after takedown.

Coverage classes:

* ``ItemHealTakedownGatedSchemaTests`` - new dataclass field defaults
  + resolve_magnitude is unchanged when the flag is True (consumer-
  side gating, not dataclass-side).

* ``CollectHealsTakedownGatedTests`` - the consumer-side gating math.
  Default takedown_rate yields 50% of magnitude; explicit 0.0/1.0
  pin the boundary behavior.

* ``DDSchemaTests`` - SR 6333 + Arena 226333 carry the canonical
  Meraki-verified Defy shape (75% bonus AD over 2s, takedown_gated).

* ``DDPerFightHealMathTests`` - per-build heal magnitude pins at
  representative bonus_AD values (low / mid / high).

* ``DDSchemaAdditiveTests`` - every non-DD item that lacks the
  takedown_gated flag has byte-identical resolve_magnitude and
  _collect_heals behavior post-schema-lift.

* ``DDIdempotenceTests`` - repeated calls to compute_ehp with DD
  yield identical results (no hidden state).

* ``ComputeEhpIntegrationTests`` - end-to-end via the public
  compute_ehp API confirms DD now contributes a positive heal
  delta vs the no-DD baseline at the default takedown rate.

* ``EngineVersionPinTests`` - pin ENGINE_VERSION 1.57.0.

* ``AsciiHygieneTests`` - 0 non-ASCII bytes in the new file (per
  CLAUDE.md hard rule).
"""
from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_types import ItemHeal
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.ehp import (
    _TAKEDOWN_RATE_PER_FIGHT,
    _collect_heals,
    compute_ehp,
)
from agents.daemon_slayer.data_loader import DataSnapshot


# ---------------- schema (ItemHeal.takedown_gated) ----------------


class ItemHealTakedownGatedSchemaTests(unittest.TestCase):
    """New ``takedown_gated`` field on ItemHeal dataclass."""

    def test_default_is_false(self) -> None:
        # Pre-ENGINE 1.57.0 ItemHeal entries (Sundered Sky) don't
        # specify takedown_gated and must default to False.
        h = ItemHeal()
        self.assertFalse(h.takedown_gated)

    def test_set_true(self) -> None:
        h = ItemHeal(bonus_ad_scaling=0.75, takedown_gated=True)
        self.assertTrue(h.takedown_gated)

    def test_resolve_magnitude_unchanged_when_flag_true(self) -> None:
        # Consumer-side gating: the dataclass resolve_magnitude does
        # NOT apply the takedown rate. This keeps the dataclass
        # convention-agnostic (mirrors missing_hp_pct precedent: the
        # consumer supplies the gating value).
        h = ItemHeal(bonus_ad_scaling=0.75, takedown_gated=True)
        # 0.75 * 100 = 75 (no gating at the dataclass layer)
        self.assertEqual(h.resolve_magnitude(bonus_ad=100), 75.0)

    def test_resolve_magnitude_matches_non_gated_with_same_scaling(self) -> None:
        # An ItemHeal with takedown_gated=True and one without should
        # resolve identically at the dataclass layer (composition-only).
        gated = ItemHeal(bonus_ad_scaling=0.75, takedown_gated=True)
        always_on = ItemHeal(bonus_ad_scaling=0.75, takedown_gated=False)
        self.assertEqual(
            gated.resolve_magnitude(bonus_ad=120),
            always_on.resolve_magnitude(bonus_ad=120),
        )

    def test_full_composition_preserves_flag(self) -> None:
        h = ItemHeal(
            flat=10.0,
            base_ad_scaling=0.5,
            bonus_ad_scaling=0.75,
            takedown_gated=True,
        )
        # Composition still works the same; the flag is metadata only
        # at the dataclass layer.
        self.assertEqual(
            h.resolve_magnitude(base_ad=60, bonus_ad=100),
            10.0 + 0.5 * 60 + 0.75 * 100,
        )


# ---------------- _collect_heals consumer-side gating ----------------


class CollectHealsTakedownGatedTests(unittest.TestCase):
    """Consumer-side gating math in ``_collect_heals``."""

    def test_default_takedown_rate_constant(self) -> None:
        # The module-level constant is the operator-tunable midpoint.
        self.assertEqual(_TAKEDOWN_RATE_PER_FIGHT, 0.5)

    def test_dd_heal_at_default_rate(self) -> None:
        # SR 6333 with bonus_ad=120: per-trigger heal = 0.75 * 120 = 90.
        # Default takedown_rate=0.5 -> 90 * 0.5 = 45.
        total, sources = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=120, is_ranged=False
        )
        self.assertAlmostEqual(total, 45.0)
        self.assertEqual(sources, (("6333", 45.0),))

    def test_dd_heal_at_zero_takedown_rate(self) -> None:
        # takedown_rate=0.0 -> DD contributes 0 (back to defensive_only
        # equivalent on the heal lane).
        total, sources = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=120, is_ranged=False,
            takedown_rate=0.0,
        )
        self.assertEqual(total, 0.0)
        self.assertEqual(sources, ())

    def test_dd_heal_at_full_takedown_rate(self) -> None:
        # takedown_rate=1.0 -> full per-trigger magnitude (every fight).
        # 0.75 * 120 * 1.0 = 90.
        total, sources = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=120, is_ranged=False,
            takedown_rate=1.0,
        )
        self.assertAlmostEqual(total, 90.0)
        self.assertEqual(sources, (("6333", 90.0),))

    def test_negative_takedown_rate_clamped_to_zero(self) -> None:
        # Defense against operator misconfiguration: negative rates
        # floor at zero, not negative magnitudes.
        total, _ = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=120, is_ranged=False,
            takedown_rate=-0.5,
        )
        self.assertEqual(total, 0.0)

    def test_arena_dd_mirrors_sr(self) -> None:
        # Arena 226333 should produce the same heal magnitude as SR
        # 6333 at the same bonus_AD (the schema is mode-mirror).
        total_sr, _ = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=120, is_ranged=False
        )
        total_arena, _ = _collect_heals(
            ["226333"], base_ad=100, bonus_hp=0, bonus_ad=120, is_ranged=False
        )
        self.assertAlmostEqual(total_sr, total_arena)

    def test_dd_plus_sundered_sky_compose(self) -> None:
        # Sundered Sky is always-on (not takedown-gated); DD is gated.
        # Total should be both contributions summed.
        # Sundered Sky melee: 1.0 * base_ad = 80 (at base_ad=80).
        # DD: 0.75 * 120 * 0.5 = 45 (at bonus_ad=120).
        total, sources = _collect_heals(
            ["6333", "6610"],
            base_ad=80, bonus_hp=0, bonus_ad=120, is_ranged=False,
        )
        self.assertAlmostEqual(total, 80.0 + 45.0)
        # 6333 first (preserves equipped order).
        self.assertEqual(sources[0][0], "6333")
        self.assertEqual(sources[1][0], "6610")

    def test_dd_zero_bonus_ad_yields_zero_heal(self) -> None:
        # No bonus AD on the build -> DD heal magnitude is 0 even at
        # full takedown rate.
        total, sources = _collect_heals(
            ["6333"], base_ad=60, bonus_hp=0, bonus_ad=0, is_ranged=False,
            takedown_rate=1.0,
        )
        self.assertEqual(total, 0.0)
        self.assertEqual(sources, ())


# ---------------- DD schema pins ----------------


class DDSchemaTests(unittest.TestCase):
    """SR 6333 + Arena 226333 carry the canonical Defy schema."""

    def test_sr_6333_no_longer_defensive_only(self) -> None:
        dd = ITEM_EFFECTS["6333"]
        self.assertFalse(dd.defensive_only)

    def test_sr_6333_has_heal_entry(self) -> None:
        dd = ITEM_EFFECTS["6333"]
        self.assertIsNotNone(dd.heal)

    def test_sr_6333_heal_is_takedown_gated(self) -> None:
        dd = ITEM_EFFECTS["6333"]
        self.assertTrue(dd.heal.takedown_gated)

    def test_sr_6333_bonus_ad_scaling_75_pct(self) -> None:
        # Meraki 16.10.1: "75% bonus AD over 2 seconds"
        dd = ITEM_EFFECTS["6333"]
        self.assertAlmostEqual(dd.heal.bonus_ad_scaling, 0.75)

    def test_sr_6333_no_other_scaling_pieces(self) -> None:
        # Defy is a pure bonus-AD heal; no flat / base AD / bonus HP
        # / missing HP pieces per Meraki.
        dd = ITEM_EFFECTS["6333"]
        self.assertEqual(dd.heal.flat, 0.0)
        self.assertEqual(dd.heal.base_ad_scaling, 0.0)
        self.assertEqual(dd.heal.bonus_hp_scaling, 0.0)
        self.assertEqual(dd.heal.missing_hp_pct, 0.0)

    def test_sr_6333_no_ranged_modifier_split(self) -> None:
        # Meraki Defy text has no ranged-vs-melee split; default 1.0.
        dd = ITEM_EFFECTS["6333"]
        self.assertEqual(dd.heal.ranged_modifier, 1.0)

    def test_sr_6333_no_heal_amp(self) -> None:
        # DD does NOT amp other heals (Spirit Visage's role).
        dd = ITEM_EFFECTS["6333"]
        self.assertEqual(dd.heal_amp_pct, 0.0)

    def test_arena_226333_mirrors_sr(self) -> None:
        sr = ITEM_EFFECTS["6333"]
        arena = ITEM_EFFECTS["226333"]
        self.assertFalse(arena.defensive_only)
        self.assertIsNotNone(arena.heal)
        self.assertTrue(arena.heal.takedown_gated)
        self.assertAlmostEqual(arena.heal.bonus_ad_scaling, sr.heal.bonus_ad_scaling)

    def test_dd_has_no_periodic_dps_proc(self) -> None:
        # DD still has no DPS proc - the Ignore Pain piece is a
        # damage-smoothing timing transform, not a DPS contribution.
        dd = ITEM_EFFECTS["6333"]
        self.assertEqual(dd.periodics, ())
        arena = ITEM_EFFECTS["226333"]
        self.assertEqual(arena.periodics, ())


# ---------------- DD per-build heal math ----------------


class DDPerFightHealMathTests(unittest.TestCase):
    """Per-build heal magnitude pins at representative bonus_AD values.

    Defy heals 75% bonus AD per trigger. With default takedown_rate=0.5,
    the per-fight heal contribution is 0.375 * bonus_AD. We pin three
    representative bonus_AD values plus the boundary conditions.
    """

    def test_low_bonus_ad_60(self) -> None:
        # 60 bonus AD (Aatrox L11 with DD only) -> 0.75 * 60 * 0.5 = 22.5
        total, _ = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=60, is_ranged=False
        )
        self.assertAlmostEqual(total, 22.5)

    def test_mid_bonus_ad_140(self) -> None:
        # 140 bonus AD (mid-game ADC with DD + a second AD item)
        # -> 0.75 * 140 * 0.5 = 52.5
        total, _ = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=140, is_ranged=False
        )
        self.assertAlmostEqual(total, 52.5)

    def test_high_bonus_ad_280(self) -> None:
        # 280 bonus AD (late-game 4+ AD items) -> 0.75 * 280 * 0.5 = 105
        total, _ = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=280, is_ranged=False
        )
        self.assertAlmostEqual(total, 105.0)

    def test_proportional_to_bonus_ad(self) -> None:
        # Doubling bonus AD should double the heal.
        small, _ = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=50, is_ranged=False
        )
        big, _ = _collect_heals(
            ["6333"], base_ad=100, bonus_hp=0, bonus_ad=100, is_ranged=False
        )
        self.assertAlmostEqual(big, small * 2.0)


# ---------------- Schema-additive guarantee ----------------


class DDSchemaAdditiveTests(unittest.TestCase):
    """Every non-DD item with a heal field stays byte-identical post-lift.

    The takedown_gated field is purely additive. Any ItemHeal entry
    that lacks the flag (or sets it False) must produce the same
    consumer-side magnitude as before ENGINE 1.57.0.
    """

    def test_sundered_sky_unchanged(self) -> None:
        # Sundered Sky has takedown_gated=False (default); its
        # _collect_heals output must match the ENGINE 1.29.0 behavior.
        total, sources = _collect_heals(
            ["6610"], base_ad=120, bonus_hp=0, bonus_ad=0, is_ranged=False
        )
        self.assertAlmostEqual(total, 120.0)
        self.assertEqual(sources, (("6610", 120.0),))

    def test_arena_sundered_sky_unchanged(self) -> None:
        # Arena Sundered Sky 226610 - same shape as SR.
        total, sources = _collect_heals(
            ["226610"], base_ad=120, bonus_hp=0, bonus_ad=0, is_ranged=False
        )
        self.assertAlmostEqual(total, 120.0)

    def test_no_heal_items_unchanged(self) -> None:
        # Items without a heal field (Infinity Edge 3031, etc.) still
        # contribute zero.
        total, sources = _collect_heals(
            ["3031", "3036"], base_ad=100, bonus_hp=0, bonus_ad=120, is_ranged=False
        )
        self.assertEqual(total, 0.0)
        self.assertEqual(sources, ())

    def test_no_other_items_have_takedown_gated_flag(self) -> None:
        # Only DD 6333 and Arena 226333 should carry the
        # takedown_gated flag at ENGINE 1.57.0 (the first consumers).
        # Any future item that uses the flag MUST extend this test.
        expected = {"6333", "226333"}
        actual = set()
        for item_id, eff in ITEM_EFFECTS.items():
            if eff.heal is not None and eff.heal.takedown_gated:
                actual.add(item_id)
        self.assertEqual(actual, expected)

    def test_all_other_heals_have_flag_false(self) -> None:
        # Sundered Sky + any future heal item should NOT carry the
        # gating flag unless they're takedown-conditional like DD.
        for item_id, eff in ITEM_EFFECTS.items():
            if eff.heal is None:
                continue
            if item_id in {"6333", "226333"}:
                continue
            self.assertFalse(
                eff.heal.takedown_gated,
                f"item {item_id} ({eff.name}) has unexpected "
                f"takedown_gated=True",
            )


# ---------------- Idempotence ----------------


class DDIdempotenceTests(unittest.TestCase):
    """Repeated calls yield identical results - no hidden state."""

    def test_collect_heals_idempotent(self) -> None:
        kwargs = dict(
            item_ids=["6333"], base_ad=100, bonus_hp=0, bonus_ad=120,
            is_ranged=False,
        )
        r1 = _collect_heals(**kwargs)
        r2 = _collect_heals(**kwargs)
        r3 = _collect_heals(**kwargs)
        self.assertEqual(r1, r2)
        self.assertEqual(r2, r3)

    def test_compute_ehp_idempotent(self) -> None:
        snap = DataSnapshot.load()
        r1 = compute_ehp(snap, "Aatrox", 11, item_ids=["6333"], mode="SR")
        r2 = compute_ehp(snap, "Aatrox", 11, item_ids=["6333"], mode="SR")
        self.assertEqual(r1.blended_ehp, r2.blended_ehp)
        self.assertEqual(r1.heal_item_total, r2.heal_item_total)
        self.assertEqual(r1.heal_total, r2.heal_total)


# ---------------- compute_ehp end-to-end integration ----------------


class ComputeEhpIntegrationTests(unittest.TestCase):
    """End-to-end via the public compute_ehp API.

    Confirms DD now contributes a positive heal delta vs the no-DD
    baseline at the default takedown rate; that the heal pool grows
    when DD is added; and that Spirit Visage amps the post-takedown-
    gated magnitude (the amp lands AFTER the gating, since both are
    consumer-site multipliers and the amp wraps the gated total).
    """

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_dd_contributes_positive_heal_delta(self) -> None:
        r_base = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[], mode="SR"
        )
        r_dd = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6333"], mode="SR"
        )
        # DD adds 60 AD + 50 armor + heal pool. EHP must strictly grow.
        self.assertGreater(r_dd.blended_ehp, r_base.blended_ehp)
        # Heal pool must grow too (this is the new contribution).
        self.assertGreater(r_dd.heal_item_total, r_base.heal_item_total)
        self.assertGreater(r_dd.heal_total, r_base.heal_total)

    def test_dd_heal_sources_lists_6333(self) -> None:
        r_dd = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6333"], mode="SR"
        )
        source_ids = {src[0] for src in r_dd.heal_sources}
        self.assertIn("6333", source_ids)

    def test_dd_heal_matches_takedown_gated_math(self) -> None:
        # Aatrox L11 with DD only: the heal magnitude must equal
        # 0.75 * bonus_ad * _TAKEDOWN_RATE_PER_FIGHT. We pull
        # bonus_AD from the EhpResult stat block to make the
        # assertion exact regardless of champion base.
        r_dd = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6333"], mode="SR"
        )
        stats = r_dd.stats
        ad = float(stats.get("ad", 0.0))
        # Champion base AD at L11 must come from base_stats. We
        # rebuild it from the no-DD baseline.
        r_base = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[], mode="SR"
        )
        base_ad = float(r_base.stats.get("ad", 0.0))
        bonus_ad = max(0.0, ad - base_ad)
        expected_heal = 0.75 * bonus_ad * _TAKEDOWN_RATE_PER_FIGHT
        # Tolerance for float noise.
        self.assertAlmostEqual(r_dd.heal_item_total, expected_heal, places=2)

    def test_dd_plus_spirit_visage_amplifies_heal(self) -> None:
        # Spirit Visage 3065 amps the heal pool by 1.25. DD's heal
        # contribution should be visible in heal_total even after
        # SV's amp is applied.
        r_dd = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6333"], mode="SR"
        )
        r_dd_sv = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6333", "3065"], mode="SR"
        )
        # SV amps heal_total; the DD-only heal_total should be
        # smaller than the DD+SV heal_total (since SV's 1.25 amp
        # also applies to DD's gated contribution).
        self.assertGreater(r_dd_sv.heal_total, r_dd.heal_total)
        self.assertAlmostEqual(r_dd_sv.heal_amp_mult, 1.25)

    def test_arena_dd_contributes_positive_heal_delta(self) -> None:
        # Arena 226333 must mirror SR 6333 on the heal lane.
        # Compute on a representative ARAM-like setup via mode=SR
        # (the Arena items use mode-agnostic schema; the per-mode
        # legality is rank.py's concern).
        r_base = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[], mode="SR"
        )
        r_arena_dd = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["226333"], mode="SR"
        )
        self.assertGreater(r_arena_dd.heal_item_total, r_base.heal_item_total)


# ---------------- ENGINE version pin ----------------


class EngineVersionPinTests(unittest.TestCase):
    """Pin ENGINE_VERSION at 1.57.0 for this test file's invariants."""

    def test_engine_version_at_1_57_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.227.0")


# ---------------- ASCII hygiene ----------------


class AsciiHygieneTests(unittest.TestCase):
    """0 non-ASCII bytes in this file (CLAUDE.md hard rule)."""

    def test_this_file_is_ascii(self) -> None:
        # The test file itself must be pure ASCII; no em-dash, no
        # smart-quote, no en-dash (per CLAUDE.md "No em-dashes or
        # en-dashes - ever (7-bit ASCII authored content)").
        p = Path(__file__)
        data = p.read_bytes()
        for i, b in enumerate(data):
            if b > 127:
                self.fail(
                    f"non-ASCII byte {b!r} at offset {i} in {p.name}"
                )


if __name__ == "__main__":
    unittest.main()
