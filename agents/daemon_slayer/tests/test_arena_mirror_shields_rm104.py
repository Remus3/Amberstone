"""RM-104 (2026-07-19) - Arena mirror shield credit for the four shield-carrying mirrors.

RM-104 filed one defect (Kaenic Rookern's Arena mirror 222504 is double-gated out)
and a verifier found three always-on siblings carrying the identical shape. A
machine sweep over ITEM_EFFECTS then proved the population is EXACTLY those four -
no fifth instance - so this file closes the class, not just the reported case.

THE DEFECT, in two distinct shapes:

  222504 Kaenic Rookern   - DOUBLE-gated. Its entry had no ``shield`` field at all,
                            so ``ehp._collect_shields`` skipped it at the
                            ``eff.shield is None`` continue; AND the default-OFF
                            arming line armed only ``iid == "2504"``, so injecting
                            a shield alone would still have credited zero. Both
                            gates had to open.
  226673 Immortal Shieldbow / 223053 Sterak's Gage / 223156 Maw of Malmortius
                          - SINGLE-gated. Their SR bases are always-on lifelines
                            (``default_off`` False), so these need NO flag - only
                            the missing ``shield`` field. They were silently
                            crediting zero on every Arena build.

MAGNITUDE PROVENANCE - INHERITED-UNSOURCED. Riot retunes Arena mirrors (the
in-feed precedent: Heartsteel's mirror 223084 is 700 HP / 2500g vs the base's
900 HP / 3000g), so the mirror magnitudes were re-sourced rather than copied on
faith. Result: DDragon carries all four mirror entries but SCRUBS every shield
magnitude from the description text, and ``items_meraki.json`` - the only feed
that carries shield formulas at all - contains ZERO Arena mirror entries. No feed
in this repo states these four magnitudes. They are therefore inherited from the
SR base DELIBERATELY and tagged INHERITED-UNSOURCED, not guessed.

WHY INHERITING THE COEFFICIENT IS NONETHELESS CORRECT (measured, not assumed).
The mirrors DO carry retuned base stats - 222504 grants 350 HP vs the base's 400,
223053 grants 300 vs 400, 223156 grants 50 AD vs 60 - which invites the conclusion
that inheriting the shield is wrong. It is not. The shield formulas scale off the
CHAMPION's resolved ``bonus_hp`` / ``bonus_ad`` / ``max_hp`` (ehp.py derives them
from ``build_champion`` over the actual item ids), so the mirror's own stat delta
already flows through and the OUTPUT differs automatically. Measured on Garen L11:
bonus_hp 350 (222504) vs 400 (2504), 300 (223053) vs 400 (3053); bonus_ad 50
(223156) vs 60 (3156). What is inherited is the COEFFICIENT; what differs is the
output, and the engine already computes that difference. Conflating the two would
have produced a wrong "the mirrors must be retuned" correction.

ONE genuinely sourced retune, deliberately NOT modelled: DDragon states the Kaenic
mirror's Magebane window is 10s ("after not taking magic damage for 10 seconds")
against the base's 15s. ``ItemShield`` has no cooldown/uptime field - the uptime
gate is expressed as the binary ``default_off`` seam - so this changes no number.
It is recorded in the registry note because it makes the mirror's uptime strictly
BETTER than the base's, i.e. the conservative default-OFF gate is if anything more
conservative for the mirror than for the item it was written for.

LATENCY: this is a LATENT fix, not a live behaviour change. ``assume_kaenic_shield``
exists only on ``compute_ehp`` - it is not a parameter of ``rank_items_by_ehp`` and
is not surfaced on any :8860 route - so no live scorer can reach the 222504 half.
The three lifeline mirrors ARE always-on and DO reach live EHP, so their half is a
real live correction on Arena builds.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import _collect_shields, compute_ehp

_KAENIC_SR = "2504"
_KAENIC_ARENA = "222504"

# Always-on lifeline mirrors: (mirror_id, base_id)
_LIFELINE_MIRRORS = (
    ("226673", "6673"),   # Immortal Shieldbow
    ("223053", "3053"),   # Sterak's Gage
    ("223156", "3156"),   # Maw of Malmortius
)

_THORNMAIL = "3075"   # no ItemShield - stays zero regardless of any flag


class MirrorShieldFieldTests(unittest.TestCase):
    """All four mirrors now carry an ItemShield (the missing-field half)."""

    def test_kaenic_mirror_has_magic_shield(self) -> None:
        eff = ITEM_EFFECTS[_KAENIC_ARENA]
        self.assertIsNotNone(eff.shield)
        self.assertEqual(eff.shield.damage_type, "magical")

    def test_kaenic_mirror_default_off(self) -> None:
        # Mirrors the SR base's conservative opt-in gate.
        self.assertTrue(ITEM_EFFECTS[_KAENIC_ARENA].shield.default_off)

    def test_lifeline_mirrors_have_shields(self) -> None:
        for mirror, _base in _LIFELINE_MIRRORS:
            with self.subTest(mirror=mirror):
                self.assertIsNotNone(ITEM_EFFECTS[mirror].shield)

    def test_lifeline_mirrors_are_always_on(self) -> None:
        # These need NO flag - default_off False, like their bases.
        for mirror, _base in _LIFELINE_MIRRORS:
            with self.subTest(mirror=mirror):
                self.assertFalse(ITEM_EFFECTS[mirror].shield.default_off)


class MirrorInheritsBaseCoefficientTests(unittest.TestCase):
    """INHERITED-UNSOURCED: each mirror's shield coefficients equal its base's.

    No feed states the mirror magnitudes (see module docstring), so equality with
    the base is the deliberate, documented choice. These assertions pin that
    choice so a future divergence is a conscious edit rather than drift.
    """

    def _assert_same_shape(self, mirror: str, base: str) -> None:
        m = ITEM_EFFECTS[mirror].shield
        b = ITEM_EFFECTS[base].shield
        self.assertEqual(m.damage_type, b.damage_type)
        for field in (
            "flat", "max_hp_scaling", "bonus_hp_scaling", "bonus_ad_scaling",
            "ranged_modifier", "level_lerp_low", "level_lerp_high",
            "level_lerp_high_value",
        ):
            with self.subTest(mirror=mirror, field=field):
                self.assertEqual(
                    getattr(m, field), getattr(b, field),
                    f"{mirror} {field} diverged from base {base}",
                )

    def test_kaenic_mirror_matches_base(self) -> None:
        self._assert_same_shape(_KAENIC_ARENA, _KAENIC_SR)

    def test_lifeline_mirrors_match_bases(self) -> None:
        for mirror, base in _LIFELINE_MIRRORS:
            self._assert_same_shape(mirror, base)


class KaenicMirrorArmingTests(unittest.TestCase):
    """The second gate: assume_kaenic_shield must arm 222504, not just 2504."""

    def test_off_default_drops_mirror(self) -> None:
        totals, sources = _collect_shields(
            [_KAENIC_ARENA], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _KAENIC_ARENA for s in sources))

    def test_on_credits_mirror_magical(self) -> None:
        totals, sources = _collect_shields(
            [_KAENIC_ARENA], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, assume_kaenic_shield=True,
        )
        self.assertAlmostEqual(totals["magical"], 450.0, places=6)  # 0.15 * 3000
        self.assertTrue(any(s[0] == _KAENIC_ARENA for s in sources))

    def test_mirror_and_base_credit_identically_at_equal_stats(self) -> None:
        # Same coefficient -> same magnitude when handed the same max_hp. The
        # real-build difference comes from the mirror's smaller HP grant, which
        # reaches this function as a smaller max_hp, not from the coefficient.
        kw = dict(
            level=11, bonus_hp=1200.0, bonus_ad=0.0, is_ranged=False,
            max_hp=3000.0, assume_kaenic_shield=True,
        )
        base_totals, _ = _collect_shields([_KAENIC_SR], **kw)
        mirror_totals, _ = _collect_shields([_KAENIC_ARENA], **kw)
        self.assertAlmostEqual(
            mirror_totals["magical"], base_totals["magical"], places=6,
        )

    def test_on_no_leak_to_other_types(self) -> None:
        totals, _ = _collect_shields(
            [_KAENIC_ARENA], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, assume_kaenic_shield=True,
        )
        self.assertEqual(totals["physical"], 0.0)
        self.assertEqual(totals["any"], 0.0)
        self.assertEqual(totals["true"], 0.0)


class LifelineMirrorAlwaysOnTests(unittest.TestCase):
    """The three lifeline mirrors credit with NO flag passed at all."""

    def test_each_lifeline_mirror_credits_unflagged(self) -> None:
        for mirror, _base in _LIFELINE_MIRRORS:
            with self.subTest(mirror=mirror):
                totals, sources = _collect_shields(
                    [mirror], level=11, bonus_hp=1000.0, bonus_ad=1000.0,
                    is_ranged=False, max_hp=3000.0,
                )
                self.assertGreater(
                    sum(totals.values()), 0.0,
                    f"{mirror} credited zero shield with no flag",
                )
                self.assertTrue(any(s[0] == mirror for s in sources))

    def test_maw_mirror_lands_in_magical(self) -> None:
        totals, _ = _collect_shields(
            ["223156"], level=11, bonus_hp=0.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0,
        )
        self.assertGreater(totals["magical"], 0.0)
        self.assertEqual(totals["physical"], 0.0)


class MirrorEhpSeamTests(unittest.TestCase):
    """compute_ehp: Kaenic mirror OFF is byte-identical; ON lifts magical only."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_kaenic_mirror_off_is_byte_identical(self) -> None:
        base = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_KAENIC_ARENA], mode="CHERRY",
        )
        off = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_KAENIC_ARENA], mode="CHERRY",
            assume_kaenic_shield=False,
        )
        self.assertEqual(off.to_dict(), base.to_dict())

    def test_kaenic_mirror_on_raises_magical_only(self) -> None:
        off = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_KAENIC_ARENA], mode="CHERRY",
        )
        on = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_KAENIC_ARENA], mode="CHERRY",
            assume_kaenic_shield=True,
        )
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertAlmostEqual(on.physical_ehp, off.physical_ehp, places=6)


class MirrorShieldClassGuardTests(unittest.TestCase):
    """Durable anti-narrow guard: no mirror may lack a shield its base carries.

    This is the test that keeps RM-104 closed. The defect was not four typos - it
    was a class: mirror entries authored by copying an SR entry's prose while
    dropping its ``shield=`` field. Any future mirror added the same way fails
    here at authoring time instead of silently crediting zero EHP for months.
    """

    def test_no_mirror_drops_its_bases_shield(self) -> None:
        bases = {k for k in ITEM_EFFECTS if len(k) <= 4}
        offenders = []
        for iid, eff in ITEM_EFFECTS.items():
            if len(iid) <= 4:
                continue
            candidates = [b for b in bases if iid.endswith(b)]
            if not candidates:
                continue
            base = max(candidates, key=len)
            if ITEM_EFFECTS[base].shield is not None and eff.shield is None:
                offenders.append(f"{iid} ({eff.name}) drops shield of base {base}")
        self.assertEqual(
            offenders, [],
            "mirror(s) missing a shield their SR base carries:\n  "
            + "\n  ".join(offenders),
        )


class MirrorRegressionTests(unittest.TestCase):
    """Mirror metadata preserved; shield-less items unaffected."""

    def test_mirror_names_and_defensive_flags(self) -> None:
        self.assertEqual(ITEM_EFFECTS[_KAENIC_ARENA].name, "Kaenic Rookern")
        self.assertTrue(ITEM_EFFECTS[_KAENIC_ARENA].defensive_only)

    def test_lifeline_family_key_preserved(self) -> None:
        for mirror, _base in _LIFELINE_MIRRORS:
            with self.subTest(mirror=mirror):
                self.assertEqual(
                    ITEM_EFFECTS[mirror].unique_passive_key, "lifeline",
                )

    def test_sterak_mirror_keeps_bonus_ad_stat_layer(self) -> None:
        # 223053 carries a DPS-positive stat layer alongside the lifeline; the
        # shield addition must not disturb it.
        self.assertAlmostEqual(
            ITEM_EFFECTS["223053"].bonus_ad_pct_base_ad, 0.45, places=6,
        )

    def test_shieldless_item_stays_zero(self) -> None:
        totals, _ = _collect_shields(
            [_THORNMAIL], level=11, bonus_hp=1000.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, assume_kaenic_shield=True,
        )
        self.assertTrue(all(v == 0.0 for v in totals.values()))


if __name__ == "__main__":
    unittest.main()
