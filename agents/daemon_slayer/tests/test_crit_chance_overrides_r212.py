"""R212 (2026-07-27) - per-champion CRIT CHANCE / CRIT DAMAGE MULTIPLIER seam.

Characterization tests for ``_crit_chance_overrides`` (the registry) + the
``dps.compute_dps(apply_crit_chance_overrides=...)`` seam.

The engine resolves every champion's basic attack as ``ad * (1 + crit *
crit_bonus)`` with ``crit_bonus = DEFAULT_CRIT_BONUS (0.75) +
total_crit_damage_bonus(items)`` (``dps.py:893``). The sibling RM-46 registry
(``_crit_conversion_overrides``) overrides only the crit-DAMAGE-BONUS axis, and
only additively / by replacement. Three axes had no seam anywhere:

  1. a crit-CHANCE multiplier (Yasuo / Yone x2.0),
  2. the >100% crit-chance OVERFLOW conversion (Yasuo / Yone 0.5 bonus AD per
     excess percentage point; Senna 0.35 percent life steal per excess point),
  3. a crit-damage MULTIPLIER on the whole ``(1 + crit_bonus)`` product
     (Jhin's Whisper penalty, 0.86).

GROUND TRUTH lives in ``data/daemon_slayer/<patch>/champion_abilities.json``.
``AbilitiesGroundTruthTests`` re-reads the shipped file and pins the verbatim
fragments the registry was authored from, so a Meraki / Riot prose rewrite fails
here rather than silently rotting the hand-authored numbers.

DEFAULT-OFF: ``compute_dps`` with the flag omitted is byte-identical for EVERY
champion including the four registered ones.

OFFLINE ONLY: no live :8893, no network.
"""
from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path

from agents.daemon_slayer._crit_chance_overrides import (
    _CRIT_CHANCE,
    _JHIN_CRIT_DAMAGE_MULTIPLIER,
    _SENNA_OVERFLOW_LIFESTEAL_PER_PCT,
    _YASUO_YONE_CRIT_CHANCE_MULTIPLIER,
    _YASUO_YONE_OVERFLOW_AD_PER_PCT,
    CritChanceEntry,
    crit_chance_entry,
    overflow_bonus_ad,
    overflow_lifesteal_pct,
    resolve_crit,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import DEFAULT_CRIT_BONUS, compute_dps

_REPO_ROOT = Path(__file__).resolve().parents[3]

YASUO = "Yasuo"
YONE = "Yone"
JHIN = "Jhin"
SENNA = "Senna"
REGISTERED = (YASUO, YONE, JHIN, SENNA)
# Negative controls: crit champions with NO registry entry.
UNREGISTERED = ("Aphelios", "Sivir", "Caitlyn", "Tryndamere", "Ashe", "Garen")

INFINITY_EDGE = "3031"
BERSERKERS = "3006"
PHANTOM_DANCER = "3046"
RAPID_FIRECANNON = "3094"
# IE + PD is exactly 50% crit, which DOUBLES to precisely the cap and overflows
# by nothing. A third crit item is required to exercise the overflow axis.
OVERFLOW_BUILD = (BERSERKERS, INFINITY_EDGE, PHANTOM_DANCER, RAPID_FIRECANNON)

# The wiki note cites Infinity Edge at +40% crit damage; the SHIPPED
# ``_effects_data.py:33`` IE carries crit_damage_bonus=0.30. The verbatim
# identity below is asserted at the NOTE's stated numbers - the point is the
# ORDER of operations ((base + bonuses) x penalty), not IE's current value.
_NOTE_INFINITY_EDGE_CRIT_DAMAGE = 0.40

GATE_LEVEL = 16
GATE_TARGET = dict(
    target_armor=110.0,
    target_mr=52.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)

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
        level=GATE_LEVEL,
        item_ids=list(build),
        mode="SR",
        **GATE_TARGET,
        **kwargs,
    )


def _implied_crit_bonus(result) -> float:
    """Recover crit_bonus from a seam-OFF result's per-hit display fields.

    ``raw_attack_dps = ad * as * (1 + crit * crit_bonus) * aa_empower_amp`` and
    ``aa_empower_amp`` is 1.0 with apply_ability_amps off. Derived rather than
    hardcoded so an item stat-line refresh cannot silently invalidate the
    identity assertions below. OFF results only - with the seam ON the display
    ``ad`` carries the overflow grant that ``stats["ad"]`` does not.
    """
    ad = result.stats["ad"]
    as_ = result.stats["as"]
    crit = min(result.stats["crit"], 1.0)
    assert crit > 0.0, "caller must use a crit build"
    return ((result.raw_attack_dps / (ad * as_)) - 1.0) / crit


class RegistryPopulationTests(unittest.TestCase):
    def test_registry_holds_exactly_the_four_specified_champions(self) -> None:
        self.assertEqual(set(_CRIT_CHANCE), set(REGISTERED))

    def test_every_entry_is_self_keyed_and_carries_a_note(self) -> None:
        for champ, entry in _CRIT_CHANCE.items():
            with self.subTest(champion=champ):
                self.assertIsInstance(entry, CritChanceEntry)
                self.assertEqual(entry.champion_id, champ)
                self.assertTrue(entry.note.strip())

    def test_yasuo_and_yone_pin_the_doubling_and_the_ad_overflow(self) -> None:
        for champ in (YASUO, YONE):
            with self.subTest(champion=champ):
                entry = crit_chance_entry(champ)
                self.assertIsNotNone(entry)
                self.assertAlmostEqual(entry.crit_chance_multiplier, 2.0, places=12)
                self.assertAlmostEqual(entry.overflow_ad_per_pct, 0.5, places=12)
                # Neither the damage multiplier nor the life-steal axis applies.
                self.assertAlmostEqual(entry.crit_damage_multiplier, 1.0, places=12)
                self.assertAlmostEqual(entry.overflow_lifesteal_per_pct, 0.0, places=12)

    def test_senna_pins_the_lifesteal_overflow_only(self) -> None:
        entry = crit_chance_entry(SENNA)
        self.assertIsNotNone(entry)
        self.assertAlmostEqual(entry.overflow_lifesteal_per_pct, 0.35, places=12)
        self.assertAlmostEqual(entry.crit_chance_multiplier, 1.0, places=12)
        self.assertAlmostEqual(entry.crit_damage_multiplier, 1.0, places=12)
        self.assertAlmostEqual(entry.overflow_ad_per_pct, 0.0, places=12)

    def test_jhin_pins_the_crit_damage_multiplier_only(self) -> None:
        entry = crit_chance_entry(JHIN)
        self.assertIsNotNone(entry)
        self.assertAlmostEqual(entry.crit_damage_multiplier, 0.86, places=12)
        self.assertAlmostEqual(entry.crit_chance_multiplier, 1.0, places=12)
        self.assertAlmostEqual(entry.overflow_ad_per_pct, 0.0, places=12)
        self.assertAlmostEqual(entry.overflow_lifesteal_per_pct, 0.0, places=12)

    def test_named_literals_match_the_entries(self) -> None:
        self.assertAlmostEqual(_YASUO_YONE_CRIT_CHANCE_MULTIPLIER, 2.0, places=12)
        self.assertAlmostEqual(_YASUO_YONE_OVERFLOW_AD_PER_PCT, 0.5, places=12)
        self.assertAlmostEqual(_SENNA_OVERFLOW_LIFESTEAL_PER_PCT, 0.35, places=12)
        self.assertAlmostEqual(_JHIN_CRIT_DAMAGE_MULTIPLIER, 0.86, places=12)

    def test_entry_is_frozen(self) -> None:
        entry = crit_chance_entry(YASUO)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.crit_chance_multiplier = 3.0  # type: ignore[misc]

    def test_unregistered_champions_have_no_entry(self) -> None:
        for champ in UNREGISTERED:
            with self.subTest(champion=champ):
                self.assertIsNone(crit_chance_entry(champ))


class AbilitiesGroundTruthTests(unittest.TestCase):
    """Drift guard: the registry numbers were hand-read from these fragments.

    If Riot / Meraki rewrites the prose, this fails and the registry must be
    re-read against the new text before anything downstream is trusted.
    """

    @classmethod
    def setUpClass(cls) -> None:
        patch = (
            _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"
        ).read_text(encoding="utf-8").strip()
        path = (
            _REPO_ROOT / "data" / "daemon_slayer" / patch / "champion_abilities.json"
        )
        cls.data = json.loads(path.read_text(encoding="utf-8"))["data"]

    def _passive(self, champion: str) -> dict:
        blocks = self.data[champion]["P"]
        self.assertIsInstance(blocks, list)
        self.assertTrue(blocks)
        return blocks[0]

    def test_yasuo_and_yone_doubling_plus_overflow_prose(self) -> None:
        for champ, name in ((YASUO, "Way of the Wanderer"), (YONE, "Way of the Hunter")):
            with self.subTest(champion=champ):
                block = self._passive(champ)
                self.assertEqual(block["name"], name)
                text = block["effects_descriptions"][0]
                self.assertIn(
                    f"{champ}'s total critical strike chance is doubled from all "
                    "other sources.",
                    text,
                )
                self.assertIn(
                    "every 1% critical strike chance in excess of 100% is "
                    "converted into 0.5 bonus attack damage.",
                    text,
                )

    def test_senna_lifesteal_overflow_prose(self) -> None:
        block = self._passive(SENNA)
        self.assertEqual(block["name"], "Absolution")
        text = block["effects_descriptions"][2]
        self.assertIn(
            "every 1% critical strike chance in excess of 100% is converted "
            "into 0.35% life steal.",
            text,
        )

    def test_jhin_crit_damage_penalty_notes(self) -> None:
        block = self._passive(JHIN)
        self.assertEqual(block["name"], "Whisper")
        notes = block["notes"]
        # The shipped prose uses U+00D7 MULTIPLICATION SIGN. This file stays
        # 7-bit ASCII (repo hard rule), so the char is escaped, not typed.
        x = chr(0x00D7)
        self.assertIn(
            "The penalty to Jhin's critical damage also reduces the base damage "
            f"((100 + 75) {x} 0.86 rather than 100 + (75 {x} 0.86))",
            notes,
        )
        self.assertIn(f"((100 + 75 + 40) {x} 0.86)", notes)

    def test_jhin_bonus_ad_from_crit_chance_is_a_separate_mechanic(self) -> None:
        # Guards the OUT-OF-SCOPE call: Every Moment Matters' crit -> AD ratio is
        # an AD-scaling term (owned by _passive_as_lock_overrides.ad_per_crit),
        # NOT a crit-resolution term, so it must NOT appear in this registry.
        block = self._passive(JHIN)
        self.assertIn(
            "(+ 0.35% per 1% critical strike chance)",
            block["effects_descriptions"][2],
        )
        from agents.daemon_slayer._passive_as_lock_overrides import as_lock_entry

        self.assertAlmostEqual(as_lock_entry(JHIN).ad_per_crit, 0.35, places=12)


class ResolvePassthroughTests(unittest.TestCase):
    def test_unregistered_champion_is_an_identity_passthrough(self) -> None:
        for champ in UNREGISTERED:
            for crit, bonus in ((0.0, 0.75), (0.25, 1.05), (1.0, 0.75), (0.6, 1.2)):
                with self.subTest(champion=champ, crit=crit, bonus=bonus):
                    got = resolve_crit(champ, crit, bonus)
                    self.assertEqual(got, (crit, bonus, None))

    def test_unknown_champion_id_is_a_passthrough(self) -> None:
        self.assertEqual(resolve_crit("NotAChampion", 0.4, 0.9), (0.4, 0.9, None))

    def test_registered_champion_returns_its_entry(self) -> None:
        for champ in REGISTERED:
            with self.subTest(champion=champ):
                _, _, entry = resolve_crit(champ, 0.25, DEFAULT_CRIT_BONUS)
                self.assertIsNotNone(entry)
                self.assertEqual(entry.champion_id, champ)


class JhinCritDamageMultiplierTests(unittest.TestCase):
    """The two verbatim arithmetic identities from Jhin's Whisper notes."""

    def test_base_penalty_identity(self) -> None:
        # "(100 + 75) x 0.86 rather than 100 + (75 x 0.86)"
        _, bonus, _ = resolve_crit(JHIN, 1.0, DEFAULT_CRIT_BONUS)
        self.assertAlmostEqual(1.0 + 1.0 * bonus, (100 + 75) * 0.86 / 100.0, places=12)

    def test_base_penalty_is_not_the_additive_reading(self) -> None:
        # The note explicitly REJECTS this shape; pin that we do not ship it.
        _, bonus, _ = resolve_crit(JHIN, 1.0, DEFAULT_CRIT_BONUS)
        self.assertNotAlmostEqual(
            1.0 + 1.0 * bonus, (100 + 75 * 0.86) / 100.0, places=6
        )

    def test_infinity_edge_identity(self) -> None:
        # "and stacks with other sources (i.e Infinity Edge) ((100 + 75 + 40) x 0.86)"
        _, bonus, _ = resolve_crit(
            JHIN, 1.0, DEFAULT_CRIT_BONUS + _NOTE_INFINITY_EDGE_CRIT_DAMAGE
        )
        self.assertAlmostEqual(
            1.0 + 1.0 * bonus, (100 + 75 + 40) * 0.86 / 100.0, places=12
        )

    def test_penalty_scales_the_whole_product_at_any_crit_bonus(self) -> None:
        # Invariant form of the two identities above: the entry multiplies
        # (1 + crit_bonus), never the bonus alone.
        for raw in (0.0, 0.15, 0.30, 0.45, 1.15):
            with self.subTest(crit_damage_bonus=raw):
                _, bonus, _ = resolve_crit(JHIN, 1.0, DEFAULT_CRIT_BONUS + raw)
                self.assertAlmostEqual(
                    1.0 + bonus,
                    (1.0 + DEFAULT_CRIT_BONUS + raw) * 0.86,
                    places=12,
                )

    def test_jhin_crit_chance_is_untouched(self) -> None:
        for crit in (0.0, 0.25, 0.6, 1.0):
            with self.subTest(crit=crit):
                eff_crit, _, _ = resolve_crit(JHIN, crit, DEFAULT_CRIT_BONUS)
                self.assertAlmostEqual(eff_crit, crit, places=12)

    def test_penalty_lowers_the_auto_attack_term(self) -> None:
        _, bonus, _ = resolve_crit(JHIN, 1.0, DEFAULT_CRIT_BONUS)
        self.assertLess(bonus, DEFAULT_CRIT_BONUS)


class CritChanceCapTests(unittest.TestCase):
    def test_doubling_below_the_cap(self) -> None:
        for champ in (YASUO, YONE):
            with self.subTest(champion=champ):
                eff, bonus, _ = resolve_crit(champ, 0.25, DEFAULT_CRIT_BONUS)
                self.assertAlmostEqual(eff, 0.50, places=12)
                # The damage axis is untouched for the doubling champions.
                self.assertAlmostEqual(bonus, DEFAULT_CRIT_BONUS, places=12)

    def test_crit_chance_never_exceeds_one_hundred_percent(self) -> None:
        for champ in (YASUO, YONE):
            for raw in (0.50, 0.60, 0.75, 1.0):
                with self.subTest(champion=champ, crit=raw):
                    eff, _, _ = resolve_crit(champ, raw, DEFAULT_CRIT_BONUS)
                    self.assertAlmostEqual(eff, 1.0, places=12)

    def test_exactly_at_the_cap(self) -> None:
        eff, _, _ = resolve_crit(YASUO, 0.50, DEFAULT_CRIT_BONUS)
        self.assertAlmostEqual(eff, 1.0, places=12)

    def test_zero_crit_stays_zero(self) -> None:
        for champ in REGISTERED:
            with self.subTest(champion=champ):
                eff, _, _ = resolve_crit(champ, 0.0, DEFAULT_CRIT_BONUS)
                self.assertAlmostEqual(eff, 0.0, places=12)


class OverflowTests(unittest.TestCase):
    def test_yasuo_overflow_bonus_ad(self) -> None:
        # raw 0.60 -> x2 = 1.20 -> 20 percentage points over -> 20 * 0.5 = 10.0 AD
        entry = crit_chance_entry(YASUO)
        self.assertAlmostEqual(overflow_bonus_ad(entry, 0.60), 10.0, places=12)

    def test_yone_matches_yasuo(self) -> None:
        for raw in (0.55, 0.60, 0.80, 1.0):
            with self.subTest(crit=raw):
                self.assertAlmostEqual(
                    overflow_bonus_ad(crit_chance_entry(YONE), raw),
                    overflow_bonus_ad(crit_chance_entry(YASUO), raw),
                    places=12,
                )

    def test_overflow_is_linear_in_the_excess(self) -> None:
        entry = crit_chance_entry(YASUO)
        for raw, expected in ((0.55, 5.0), (0.70, 20.0), (1.00, 50.0)):
            with self.subTest(crit=raw):
                self.assertAlmostEqual(overflow_bonus_ad(entry, raw), expected, places=12)

    def test_no_excess_yields_zero_ad(self) -> None:
        entry = crit_chance_entry(YASUO)
        for raw in (0.0, 0.10, 0.25, 0.49, 0.50):
            with self.subTest(crit=raw):
                self.assertAlmostEqual(overflow_bonus_ad(entry, raw), 0.0, places=12)

    def test_senna_overflow_lifesteal_percent(self) -> None:
        # raw 1.40 -> 40 percentage points over -> 40 * 0.35 = 14.0 PERCENT
        entry = crit_chance_entry(SENNA)
        self.assertAlmostEqual(overflow_lifesteal_pct(entry, 1.40), 14.0, places=12)

    def test_senna_no_excess_yields_zero_lifesteal(self) -> None:
        entry = crit_chance_entry(SENNA)
        for raw in (0.0, 0.50, 1.0):
            with self.subTest(crit=raw):
                self.assertAlmostEqual(overflow_lifesteal_pct(entry, raw), 0.0, places=12)

    def test_none_entry_yields_zero_on_both_axes(self) -> None:
        self.assertEqual(overflow_bonus_ad(None, 2.0), 0.0)
        self.assertEqual(overflow_lifesteal_pct(None, 2.0), 0.0)

    def test_axes_do_not_cross_contaminate(self) -> None:
        # Yasuo overflows into AD only; Senna into life steal only.
        self.assertEqual(overflow_lifesteal_pct(crit_chance_entry(YASUO), 1.0), 0.0)
        self.assertEqual(overflow_bonus_ad(crit_chance_entry(SENNA), 1.40), 0.0)

    def test_jhin_has_no_overflow_on_either_axis(self) -> None:
        entry = crit_chance_entry(JHIN)
        self.assertEqual(overflow_bonus_ad(entry, 1.40), 0.0)
        self.assertEqual(overflow_lifesteal_pct(entry, 1.40), 0.0)


class DefaultOffSeamTests(unittest.TestCase):
    """The seam must be inert unless explicitly switched on."""

    BUILDS = (
        (BERSERKERS,),
        (BERSERKERS, INFINITY_EDGE),
        (BERSERKERS, PHANTOM_DANCER),
        (BERSERKERS, INFINITY_EDGE, PHANTOM_DANCER),
    )

    def test_omitted_flag_matches_explicit_false_for_registered(self) -> None:
        for champ in REGISTERED:
            for build in self.BUILDS:
                with self.subTest(champion=champ, build=build):
                    self.assertEqual(
                        _dps(champ, build, apply_crit_chance_overrides=False).to_dict(),
                        _dps(champ, build).to_dict(),
                    )

    def test_omitted_flag_matches_explicit_false_for_unregistered(self) -> None:
        for champ in UNREGISTERED:
            with self.subTest(champion=champ):
                self.assertEqual(
                    _dps(
                        champ,
                        (BERSERKERS, INFINITY_EDGE),
                        apply_crit_chance_overrides=False,
                    ).to_dict(),
                    _dps(champ, (BERSERKERS, INFINITY_EDGE)).to_dict(),
                )

    def test_unregistered_champion_is_byte_identical_with_the_flag_on(self) -> None:
        for champ in UNREGISTERED:
            with self.subTest(champion=champ):
                self.assertEqual(
                    _dps(
                        champ,
                        (BERSERKERS, INFINITY_EDGE),
                        apply_crit_chance_overrides=True,
                    ).to_dict(),
                    _dps(champ, (BERSERKERS, INFINITY_EDGE)).to_dict(),
                )

    def test_no_note_on_the_default_path(self) -> None:
        for champ in REGISTERED:
            with self.subTest(champion=champ):
                notes = _dps(champ, (BERSERKERS, INFINITY_EDGE)).notes
                self.assertFalse(
                    any("crit chance override" in n.lower() for n in notes), notes
                )


class SeamIsServedTests(unittest.TestCase):
    """Proof the seam is reachable and NOT inert - the flag must move numbers."""

    def test_yasuo_crit_doubles_when_the_flag_is_on(self) -> None:
        off = _dps(YASUO, (BERSERKERS, INFINITY_EDGE))
        on = _dps(YASUO, (BERSERKERS, INFINITY_EDGE), apply_crit_chance_overrides=True)
        self.assertGreater(off.stats["crit"], 0.0)
        self.assertGreater(on.avg_attack_dmg, off.avg_attack_dmg)
        self.assertGreater(on.weighted_dps, off.weighted_dps)

    def test_yasuo_auto_attack_term_matches_the_doubled_chance(self) -> None:
        build = (BERSERKERS, INFINITY_EDGE)
        off = _dps(YASUO, build)
        on = _dps(YASUO, build, apply_crit_chance_overrides=True)
        crit = min(off.stats["crit"], 1.0)
        doubled = min(1.0, crit * 2.0)
        # crit_bonus is unchanged for Yasuo, so the AA ratio is pure crit chance.
        # Overflow AD would break this identity, so pick a build under the cap.
        self.assertLess(crit * 2.0, 1.0)
        bonus = _implied_crit_bonus(off)
        self.assertAlmostEqual(
            on.avg_attack_dmg / off.avg_attack_dmg,
            (1 + doubled * bonus) / (1 + crit * bonus),
            places=9,
        )

    def test_yone_moves_the_same_direction_as_yasuo(self) -> None:
        build = (BERSERKERS, INFINITY_EDGE)
        off = _dps(YONE, build)
        on = _dps(YONE, build, apply_crit_chance_overrides=True)
        self.assertGreater(on.avg_attack_dmg, off.avg_attack_dmg)

    def test_jhin_penalty_lowers_his_auto_attack_when_the_flag_is_on(self) -> None:
        build = (BERSERKERS, INFINITY_EDGE)
        off = _dps(JHIN, build)
        on = _dps(JHIN, build, apply_crit_chance_overrides=True)
        self.assertGreater(off.stats["crit"], 0.0)
        self.assertLess(on.avg_attack_dmg, off.avg_attack_dmg)
        crit = min(off.stats["crit"], 1.0)
        bonus = _implied_crit_bonus(off)
        self.assertAlmostEqual(
            on.avg_attack_dmg / off.avg_attack_dmg,
            (1 + crit * ((1 + bonus) * 0.86 - 1)) / (1 + crit * bonus),
            places=9,
        )

    def test_zero_crit_build_is_an_identity_even_with_the_flag_on(self) -> None:
        # Nothing to double, no overflow, and the Jhin penalty multiplies a
        # term that is multiplied by crit=0 anyway.
        for champ in REGISTERED:
            with self.subTest(champion=champ):
                off = _dps(champ, (BERSERKERS,))
                on = _dps(champ, (BERSERKERS,), apply_crit_chance_overrides=True)
                self.assertEqual(off.stats["crit"], 0.0)
                self.assertEqual(on.avg_attack_dmg, off.avg_attack_dmg)
                self.assertEqual(on.weighted_dps, off.weighted_dps)

    def test_flag_on_emits_a_note_for_a_registered_champion(self) -> None:
        on = _dps(
            YASUO, (BERSERKERS, INFINITY_EDGE), apply_crit_chance_overrides=True
        )
        self.assertTrue(
            any("crit chance override" in n.lower() for n in on.notes), on.notes
        )

    def test_yasuo_overflow_ad_is_credited_above_the_cap(self) -> None:
        # Three crit items push raw crit past 50%, so the doubling clips at 100%
        # and the excess must convert into bonus AD instead of being discarded.
        off = _dps(YASUO, OVERFLOW_BUILD)
        on = _dps(YASUO, OVERFLOW_BUILD, apply_crit_chance_overrides=True)
        raw = min(off.stats["crit"], 1.0)
        self.assertGreater(raw * 2.0, 1.0)
        expected_ad = (raw * 2.0 - 1.0) * 100.0 * 0.5
        self.assertGreater(expected_ad, 0.0)
        bonus = _implied_crit_bonus(off)
        ad_off = off.stats["ad"]
        self.assertAlmostEqual(
            on.avg_attack_dmg / off.avg_attack_dmg,
            ((ad_off + expected_ad) * (1 + 1.0 * bonus)) / (ad_off * (1 + raw * bonus)),
            places=9,
        )

    def test_overflow_ad_is_absent_when_the_seam_is_off(self) -> None:
        # Control for the test above: the grant must be a seam effect, not a
        # property of the build.
        off = _dps(YASUO, OVERFLOW_BUILD)
        self.assertAlmostEqual(
            off.avg_attack_dmg,
            _dps(YASUO, OVERFLOW_BUILD, apply_crit_chance_overrides=False).avg_attack_dmg,
            places=12,
        )
        self.assertFalse(
            any("overflow bonus AD" in n for n in off.notes), off.notes
        )

    def test_overflow_ad_is_reported_in_the_note(self) -> None:
        on = _dps(YASUO, OVERFLOW_BUILD, apply_crit_chance_overrides=True)
        self.assertTrue(any("overflow bonus AD" in n for n in on.notes), on.notes)


if __name__ == "__main__":
    unittest.main()
