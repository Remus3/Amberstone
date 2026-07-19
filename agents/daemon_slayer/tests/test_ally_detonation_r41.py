"""R41 (ENGINE 1.156.0) - ally mark-detonation magic-damage seam.

A handful of champions lay a MARK on an enemy that an ALLY consumes for bonus
damage (the mark-enabler's contribution to TEAM damage, distinct from any
self-amp or all-source vulnerability mark). R12's ``_target_vulnerability_overrides``
explicitly handed this off: it belongs in "an ally-detonation / current-HP-burst
seam ... not this all-source-%amp registry". R41 is that seam.

``agents.daemon_slayer._ally_detonation_overrides`` is a PURE registry (no engine
imports, like ``_target_vulnerability_overrides``): it returns the PRE-mitigation
raw detonation magic damage; the callers (``compute_dps`` / ``compute_burst_damage``)
apply their own MR mitigation + mode + magic-amp + the assumed-ally-proc-rate
amortization (``_ASSUMED_ALLY_DETONATION_PROB`` = 0.5). Both ``compute_*`` gain an
``assume_ally_detonation`` flag, DEFAULT-OFF and byte-identical when off.

Seeded (VERIFIED vs patch-16.13.1 champion_abilities.json, Meraki content 25.15):
  * Leona P "Sunlight": "Allied champions' damaging attacks and abilities against a
    marked target will consume the mark to deal 32 : 151 (based on level) bonus
    magic damage." -> FLAT_MAGIC flat_lo=32, flat_hi=151, MAGIC, 2.5s mark cadence.

Handoff EXECUTED (R43) - the directive named Imperial Mandate 4005 as a "10% current
HP magic" detonation, but that premise was STALE. The official Riot DDragon 16.13.1
item tooltip shows Imperial Mandate REWORKED to "Command: On Immobilizing an enemy
champion, mark them as 7% Vulnerable for 4 seconds" (an all-source damage-amp mark;
passives renamed Control / Command) - the 16.12.1 "Coordinated Fire" 10% current-HP
detonation is GONE. R41 recorded it as a non-fit handoff; R43 seeded the reworked 7%
Vulnerable into ``_target_vulnerability_overrides`` (4005 / Arena 224005 / ARAM
324005) and emptied this seam's non-fit registry.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._ally_detonation_overrides import (
    _ASSUMED_ALLY_DETONATION_PROB,
    _CHAMPION_DETONATION_OVERRIDES,
    _ITEM_DETONATION_OVERRIDES,
    _NONFIT_DETONATION_CANDIDATES,
    AllyDetonationEntry,
    ally_detonation_burst_raw,
    ally_detonation_dps_raw,
    champion_detonation_for,
)
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# Leona Sunlight flat magic at level L: lerp(32, 151) over levels 1..18.
def _leona_flat(level: int) -> float:
    return 32.0 + (151.0 - 32.0) * (level - 1) / 17.0


class SchemaTests(unittest.TestCase):
    def test_entry_defaults(self):
        e = AllyDetonationEntry(source_key="P", kind="FLAT_MAGIC")
        self.assertEqual(e.flat_lo, 0.0)
        self.assertEqual(e.flat_hi, 0.0)
        self.assertEqual(e.current_hp_coeff, 0.0)
        self.assertEqual(e.cadence_s, 0.0)
        self.assertEqual(e.note, "")

    def test_entry_keyword_constructible(self):
        e = AllyDetonationEntry(
            source_key="P", kind="FLAT_MAGIC", flat_lo=32.0, flat_hi=151.0,
            cadence_s=2.5, note="Leona",
        )
        self.assertEqual((e.flat_lo, e.flat_hi, e.cadence_s), (32.0, 151.0, 2.5))


class RegistrySeedTests(unittest.TestCase):
    def test_leona_seeded_flat_magic(self):
        e = champion_detonation_for("Leona")
        self.assertIsNotNone(e)
        self.assertEqual(e.kind, "FLAT_MAGIC")
        self.assertEqual((e.flat_lo, e.flat_hi), (32.0, 151.0))
        self.assertEqual(e.current_hp_coeff, 0.0)
        self.assertEqual(e.cadence_s, 2.5)

    def test_leona_is_the_only_seeded_champion(self):
        self.assertEqual(sorted(_CHAMPION_DETONATION_OVERRIDES), ["Leona"])

    def test_imperial_mandate_not_seeded_as_detonation(self):
        # 16.13.1 rework -> not a current-HP detonation; never seeded here.
        self.assertNotIn("4005", _ITEM_DETONATION_OVERRIDES)
        self.assertEqual(_ITEM_DETONATION_OVERRIDES, {})

    def test_imperial_mandate_handed_off_to_vuln_registry(self):
        # R43 executed the handoff: 4005 reworked to a 7% Vulnerable all-source
        # mark, seeded in _target_vulnerability_overrides, removed from this seam.
        self.assertNotIn("4005", _NONFIT_DETONATION_CANDIDATES)
        self.assertEqual(_NONFIT_DETONATION_CANDIDATES, {})

    def test_unknown_champion_is_none(self):
        self.assertIsNone(champion_detonation_for("Aatrox"))
        self.assertIsNone(champion_detonation_for(""))

    def test_assumed_prob_is_half(self):
        self.assertEqual(_ASSUMED_ALLY_DETONATION_PROB, 0.5)


class RawHelperMathTests(unittest.TestCase):
    def test_burst_raw_leona_flat_ramps_with_level(self):
        self.assertAlmostEqual(ally_detonation_burst_raw("Leona", 1), 32.0, places=6)
        self.assertAlmostEqual(ally_detonation_burst_raw("Leona", 18), 151.0, places=6)
        self.assertAlmostEqual(ally_detonation_burst_raw("Leona", 9), 88.0, places=6)

    def test_dps_raw_is_burst_raw_over_cadence(self):
        for lvl in (1, 9, 18):
            self.assertAlmostEqual(
                ally_detonation_dps_raw("Leona", lvl),
                _leona_flat(lvl) / 2.5, places=6, msg=str(lvl),
            )

    def test_flat_source_ignores_target_current_hp(self):
        # Leona is FLAT_MAGIC (current_hp_coeff 0) - the target HP arg is inert.
        self.assertAlmostEqual(
            ally_detonation_burst_raw("Leona", 18, target_current_hp=3000.0),
            151.0, places=6,
        )

    def test_unregistered_champion_is_zero(self):
        self.assertEqual(ally_detonation_burst_raw("Aatrox", 18), 0.0)
        self.assertEqual(ally_detonation_dps_raw("Aatrox", 18), 0.0)


class ByteIdenticalOffTests(unittest.TestCase):
    def test_compute_dps_off_is_default(self):
        snap = _snap()
        base = compute_dps(snap, "Leona", 18, mode="SR")
        off = compute_dps(snap, "Leona", 18, mode="SR", assume_ally_detonation=False)
        self.assertEqual(off.weighted_dps, base.weighted_dps)
        self.assertEqual(off.phase_dps, base.phase_dps)

    def test_compute_burst_off_is_default(self):
        snap = _snap()
        base = compute_burst_damage(snap, "Leona", 18, mode="SR")
        off = compute_burst_damage(
            snap, "Leona", 18, mode="SR", assume_ally_detonation=False
        )
        self.assertAlmostEqual(
            off.total_burst_damage, base.total_burst_damage, places=6
        )

    def test_non_detonation_champion_identical_on_or_off(self):
        # A champion with no registered detonation source is byte-identical even
        # with the flag ON (additive guarantee).
        snap = _snap()
        off = compute_burst_damage(snap, "Aatrox", 18, mode="SR")
        on = compute_burst_damage(
            snap, "Aatrox", 18, mode="SR", assume_ally_detonation=True
        )
        self.assertAlmostEqual(
            on.total_burst_damage, off.total_burst_damage, places=6
        )


class OnPathDeltaTests(unittest.TestCase):
    def test_burst_on_adds_mitigated_amortized_detonation(self):
        # No items, target_mr=0 -> magic factor 1.0; SR -> mode_mult 1.0; no magic
        # amp. delta == flat(18) * prob == 151 * 0.5 == 75.5.
        snap = _snap()
        off = compute_burst_damage(snap, "Leona", 18, mode="SR", target_mr=0.0)
        on = compute_burst_damage(
            snap, "Leona", 18, mode="SR", target_mr=0.0, assume_ally_detonation=True
        )
        self.assertAlmostEqual(
            on.total_burst_damage - off.total_burst_damage, 75.5, places=4
        )

    def test_dps_on_adds_mitigated_amortized_detonation(self):
        # delta == flat(18)/cadence * prob == 151/2.5 * 0.5 == 30.2.
        snap = _snap()
        off = compute_dps(snap, "Leona", 18, mode="SR", target_mr=0.0)
        on = compute_dps(
            snap, "Leona", 18, mode="SR", target_mr=0.0, assume_ally_detonation=True
        )
        self.assertAlmostEqual(on.weighted_dps - off.weighted_dps, 30.2, places=4)
        # The invariant weighted_dps == phase_dps[selected_phase] survives.
        self.assertAlmostEqual(
            on.weighted_dps, on.phase_dps[on.phase], places=6
        )

    def test_burst_detonation_mitigated_by_mr(self):
        # target_mr=100 -> magic factor 0.5; delta == 151 * 0.5(mit) * 0.5(prob).
        snap = _snap()
        off = compute_burst_damage(snap, "Leona", 18, mode="SR", target_mr=100.0)
        on = compute_burst_damage(
            snap, "Leona", 18, mode="SR", target_mr=100.0, assume_ally_detonation=True
        )
        self.assertAlmostEqual(
            on.total_burst_damage - off.total_burst_damage, 151.0 * 0.5 * 0.5, places=4
        )


class EngineVersionTest(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.225.0")


if __name__ == "__main__":
    unittest.main()
