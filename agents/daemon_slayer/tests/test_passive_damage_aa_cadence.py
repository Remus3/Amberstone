"""Passive-damage cadence routing - compute_dps on_hit -> AA cadence seam.

04_GAPS_AND_ROADMAP section 2 ("Passive-damage cadence routing"): the
passive-damage registry tagged every entry with a ``cadence`` string that
was metadata-only - the injected P-form synthetic block is inert in every
scorer (``compute_ability_dps`` skips the P slot; ``compute_dps`` never read
the registry). ENGINE 1.100.0 ships the consumer: ``compute_dps`` gains an
OPT-IN ``apply_passive_damage`` flag that routes an allowlisted every-AA
``on_hit`` passive's per-hit bonus onto the auto-attack cadence.

Contract proven here:
  * DEFAULT-OFF byte-identical - the seam adds nothing for the default
    ``apply_passive_damage=False`` call.
  * Flag-on, allowlisted every-AA passive (Warwick Eternal Hunger / Orianna
    Clockwork Winding): per-hit bonus surfaces in ``per_attack_on_hit_damage``
    and the steady DPS delta is exactly ``per_hit * eff_as`` across phases.
  * Flag-on, NON-allowlisted on_hit passive (Ziggs Short Fuse): byte-identical
    - the mark-consume / internal-CD / empowered-first-hit entries carry
    forward inert (their amortization needs the structured cadence + a live
    re-rank check; the default-on flip is gated).
  * Flag-on, no passive entry (Caitlyn): byte-identical.

Hand-verified pin: Warwick Eternal Hunger base = lerp(12, 46) at level 11
(rank 10) = 12 + 34 * 10/17 = 32.0 magic; itemless build has 0 bonus AD / 0
AP and target MR 0 -> mitigation 1.0 -> per-hit bonus 32.0 exactly.
"""

from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer._passive_damage_overrides import (
    _AA_ROUTED_ON_HIT_KEYS,
    aa_routed_on_hit_entry,
)


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _both(self, cid: str, level: int = 11, items=None):
        off = compute_dps(self.snap, cid, level, item_ids=items)
        on = compute_dps(
            self.snap, cid, level, item_ids=items, apply_passive_damage=True
        )
        return off, on


class DefaultOffByteIdenticalTests(_Base):
    def test_default_equals_explicit_false(self) -> None:
        for cid in ("Warwick", "Orianna", "Ziggs", "Caitlyn"):
            with self.subTest(cid=cid):
                d = compute_dps(self.snap, cid, 11)
                f = compute_dps(self.snap, cid, 11, apply_passive_damage=False)
                self.assertEqual(d.weighted_dps, f.weighted_dps)
                self.assertEqual(
                    d.per_attack_on_hit_damage, f.per_attack_on_hit_damage
                )
                self.assertEqual(d.notes, f.notes)


class WarwickEveryAaRoutedTests(_Base):
    def test_warwick_per_hit_exact_and_dps_delta(self) -> None:
        off, on = self._both("Warwick", 11)
        # Eternal Hunger 12:46 -> 32.0 at L11, magic, mit 1.0, itemless.
        self.assertAlmostEqual(on.per_attack_on_hit_damage, 32.0, places=6)
        self.assertAlmostEqual(off.per_attack_on_hit_damage, 0.0, places=6)
        eff_as = float(on.stats["as"])
        self.assertAlmostEqual(
            on.weighted_dps - off.weighted_dps, 32.0 * eff_as, places=4
        )
        self.assertTrue(
            any("Eternal Hunger routed to AA cadence" in n for n in on.notes)
        )

    def test_warwick_phase_dps_all_shifted_by_same_term(self) -> None:
        off, on = self._both("Warwick", 11)
        eff_as = float(on.stats["as"])
        term = 32.0 * eff_as
        for phase in off.phase_dps:
            self.assertAlmostEqual(
                on.phase_dps[phase] - off.phase_dps[phase], term, places=4
            )


class OriannaEveryAaRoutedTests(_Base):
    def test_orianna_routes_nonzero_with_stack_midpoint(self) -> None:
        off, on = self._both("Orianna", 11)
        self.assertGreater(on.per_attack_on_hit_damage, 0.0)
        self.assertAlmostEqual(off.per_attack_on_hit_damage, 0.0, places=6)
        eff_as = float(on.stats["as"])
        self.assertAlmostEqual(
            on.weighted_dps - off.weighted_dps,
            on.per_attack_on_hit_damage * eff_as,
            places=4,
        )


class NonAllowlistedAndNoEntryByteIdenticalTests(_Base):
    def test_ziggs_on_hit_but_not_allowlisted_byte_identical(self) -> None:
        # Ziggs Short Fuse IS an on_hit entry but has an internal cooldown,
        # so it is deliberately NOT routed in v1.
        off, on = self._both("Ziggs", 11)
        self.assertEqual(off.weighted_dps, on.weighted_dps)
        self.assertEqual(
            off.per_attack_on_hit_damage, on.per_attack_on_hit_damage
        )
        self.assertEqual(off.notes, on.notes)

    def test_caitlyn_no_passive_entry_byte_identical(self) -> None:
        off, on = self._both("Caitlyn", 11)
        self.assertEqual(off.weighted_dps, on.weighted_dps)
        self.assertEqual(off.notes, on.notes)


class AllowlistAndHelperTests(_Base):
    def test_allowlist_membership(self) -> None:
        self.assertIn(("Warwick", "P", 0), _AA_ROUTED_ON_HIT_KEYS)
        self.assertIn(("Orianna", "P", 0), _AA_ROUTED_ON_HIT_KEYS)
        self.assertNotIn(("Ziggs", "P", 0), _AA_ROUTED_ON_HIT_KEYS)

    def test_helper_returns_entry_for_allowlisted(self) -> None:
        routed = aa_routed_on_hit_entry("Warwick")
        self.assertIsNotNone(routed)
        key, entry = routed
        self.assertEqual(key, ("Warwick", "P", 0))
        self.assertEqual(entry.cadence, "on_hit")

    def test_helper_returns_none_for_non_allowlisted(self) -> None:
        self.assertIsNone(aa_routed_on_hit_entry("Ziggs"))
        self.assertIsNone(aa_routed_on_hit_entry("Caitlyn"))
        self.assertIsNone(aa_routed_on_hit_entry(""))


class EngineVersionTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.100.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_test_file_is_ascii(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(non_ascii, [], f"non-ASCII bytes: {non_ascii[:8]}")


if __name__ == "__main__":
    unittest.main()
