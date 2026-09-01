"""RM-323 - three Arena mirrors credited ZERO on-cast magic burst.

Malignance 223118, Stormsurge 224646 and Luden's Echo 226655 each carry a
populated ``periodics`` tuple and a ``note`` that asserts a concrete
magnitude, but none of the three carried ``magic_burst_base`` /
``magic_burst_ap_ratio``. burst.py deliberately excludes periodic procs
from the burst window (only the DSV6 ``assume_magic_burst`` seam at
burst.py:1143-1163 reads those two fields), so magic_burst is the ONLY
path the burst lane has for these rows - they scored 0.00 while their SR
twins scored the full magnitude.

AUTHORITY for the magnitudes is each mirror row's OWN ``note``, per RC
doctrine B ("Arena mirrors credit their OWN DDragon stat line, not the SR
twin's"). DDragon 16.15.1 carries the proc TEXT for all three mirrors but
NO proc magnitude for any of the six ids (SR twins included) - its
``<stats>`` blocks hold base stats only - so DDragon cannot settle the
number and the note is the best available authority. The mirrors ARE
genuinely re-tuned on base stats (223118 is 70 AP / 20 haste vs SR 3118's
90 / 15; 224646 has 4% MS vs 6%; 226655 is 85 AP / 25 haste vs 100 / 10),
which is exactly why the SR twin cannot be assumed - but each mirror
note's proc magnitude was MEASURED to equal its twin's, so base-equality
here is a consequence, not a premise.

The expected values below are written as LITERALS taken from the notes,
never read off the SR row: a test that derives its expectation from the
base row cannot catch both rows being wrong together.

Deliberately NOT audited against ``items_meraki.json`` (CLAUDE.md
carve-out: Meraki carries 320 items vs DDragon's 706 and ZERO rows carry
a ``stats`` key, so magnitude audits there manufacture phantom
mismatches).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    collect_effects,
    total_magic_burst_damage,
)

# (mirror id, SR twin id, note-derived base, note-derived AP ratio)
_MIRROR_PAIRS = (
    ("223118", "3118", 180.0, 0.15),   # Malignance Hatefog (180 + 15% AP)
    ("224646", "4646", 125.0, 0.10),   # Stormsurge Squall (125 + 10% AP)
    ("226655", "6655", 75.0, 0.05),    # Luden's Echo (75 + 5% AP)
)

# Note-derived totals at the two probe AP values, written as literals.
# 180 + 0.15*400 = 240 / 125 + 0.10*400 = 165 / 75 + 0.05*400 = 95.
_EXPECTED_TOTALS = {
    "223118": {0.0: 180.0, 400.0: 240.0},
    "224646": {0.0: 125.0, 400.0: 165.0},
    "226655": {0.0: 75.0, 400.0: 95.0},
}

# Arena mirrors that legitimately credit NOTHING on this seam, so a future
# blanket "every Arena mirror equals its SR twin" sweep fails loudly here.
# 221043 Recurve Bow - "reduced-cost AS + on-hit component - no passive proc".
# 222512 Fiendhunter Bolts - "anti-shield utility; no DPS contribution".
_ZERO_BURST_MIRRORS = ("221043", "222512")

_LUDENS_ARENA = "226655"
_ARENA_BUILD_BASE = ["223020", "223089"]  # Sorcerer's Shoes + Rabadon's
_ARENA_BUILD_WITH = _ARENA_BUILD_BASE + [_LUDENS_ARENA]


class MirrorMagicBurstMagnitude(unittest.TestCase):
    """Each mirror credits its OWN note magnitude on the DSV6 seam."""

    def test_mirror_credits_note_magnitude(self) -> None:
        for mirror_id, _sr_id, _base, _ratio in _MIRROR_PAIRS:
            for caster_ap, expected in _EXPECTED_TOTALS[mirror_id].items():
                with self.subTest(item=mirror_id, ap=caster_ap):
                    got = total_magic_burst_damage(
                        collect_effects([mirror_id]), caster_ap
                    )
                    self.assertAlmostEqual(got, expected, places=4)

    def test_mirror_matches_sr_twin(self) -> None:
        # A measured CONSEQUENCE of the note magnitudes, not the premise -
        # the assertion above pins the literals independently.
        for mirror_id, sr_id, _base, _ratio in _MIRROR_PAIRS:
            for caster_ap in (0.0, 400.0):
                with self.subTest(item=mirror_id, ap=caster_ap):
                    mirror = total_magic_burst_damage(
                        collect_effects([mirror_id]), caster_ap
                    )
                    base = total_magic_burst_damage(
                        collect_effects([sr_id]), caster_ap
                    )
                    self.assertAlmostEqual(mirror, base, places=4)

    def test_registry_fields_pinned(self) -> None:
        for mirror_id, _sr_id, base, ratio in _MIRROR_PAIRS:
            with self.subTest(item=mirror_id):
                eff = ITEM_EFFECTS[mirror_id]
                self.assertAlmostEqual(eff.magic_burst_base, base)
                self.assertAlmostEqual(eff.magic_burst_ap_ratio, ratio)

    def test_periodics_retained(self) -> None:
        # The sustained-DPS valuation must survive the burst fix - the
        # periodic owns compute_dps, the burst magnitude owns the window,
        # and neither double-counts the other.
        for mirror_id, _sr_id, _base, _ratio in _MIRROR_PAIRS:
            with self.subTest(item=mirror_id):
                self.assertEqual(len(ITEM_EFFECTS[mirror_id].periodics), 1)


class ZeroBurstMirrorsStayZero(unittest.TestCase):
    """Negative guard against a blanket mirror==twin sweep."""

    def test_non_proc_mirrors_credit_nothing(self) -> None:
        for item_id in _ZERO_BURST_MIRRORS:
            for caster_ap in (0.0, 400.0):
                with self.subTest(item=item_id, ap=caster_ap):
                    got = total_magic_burst_damage(
                        collect_effects([item_id]), caster_ap
                    )
                    self.assertEqual(got, 0.0)


class ArenaBurstObservable(unittest.TestCase):
    """End-to-end: the fix moves compute_burst_damage under mode=ARENA."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _burst(self, item_ids: list[str]) -> float:
        result = compute_burst_damage(
            self.snap,
            "Veigar",
            11,
            item_ids=item_ids,
            mode="ARENA",
            target_mr=0.0,
            target_max_hp=2000.0,
            assume_magic_burst=True,
        )
        return result.total_burst_damage

    def _burst_seam_off(self, item_ids: list[str]) -> float:
        return compute_burst_damage(
            self.snap,
            "Veigar",
            11,
            item_ids=item_ids,
            mode="ARENA",
            target_mr=0.0,
            target_max_hp=2000.0,
        ).total_burst_damage

    def test_arena_mirror_adds_burst_beyond_its_statblock(self) -> None:
        # The naive form of this check - burst(with mirror) > burst(without)
        # at a single seam setting - is VACUOUS: 226655 carries 85 AP, so the
        # total rises on the stat block alone and the assertion passes even
        # with the burst fields at 0.0 (measured green at HEAD before the
        # fix). The honest observable isolates the SEAM: the ON-minus-OFF
        # delta is zero for a build with no burst carrier and strictly
        # positive once the mirror is present.
        delta_without = (
            self._burst(list(_ARENA_BUILD_BASE))
            - self._burst_seam_off(list(_ARENA_BUILD_BASE))
        )
        delta_with = (
            self._burst(list(_ARENA_BUILD_WITH))
            - self._burst_seam_off(list(_ARENA_BUILD_WITH))
        )
        self.assertAlmostEqual(delta_without, 0.0, places=4)
        self.assertGreater(delta_with, delta_without)
        # At target_mr=0 the MAGIC mitigation factor is 1.0 and mode_mult is
        # 1.0 outside ARAM (burst.py:681-683), so the delta cannot fall below
        # the note's 75.0 base floor.
        self.assertGreaterEqual(delta_with, 75.0)

    def test_full_arena_build_total_rises(self) -> None:
        # The plain before/after the row asked for, kept as the end-user
        # observable: with the seam ON, holding the mirror scores higher.
        without = self._burst(list(_ARENA_BUILD_BASE))
        with_mirror = self._burst(list(_ARENA_BUILD_WITH))
        self.assertGreater(with_mirror, without)


if __name__ == "__main__":
    unittest.main()
