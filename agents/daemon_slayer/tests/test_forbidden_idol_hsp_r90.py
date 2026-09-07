"""ENGINE 1.188.0 (R90, 2026-07-10) - Forbidden Idol (3114) HSP registry credit.

R90 is a sibling_carrier refinement of R60's wielder Heal/Shield Power (HSP) amp
seam. R60 credited the five FINISHED HSP carriers (Redemption / Mikael / Ardent /
Moonstone / Staff of Flowing Water) in the curated ``enchanter_items.json``
registry - the source ``sum_wielder_hsp_pct()`` reads. A fresh adversarial
Meraki(16.13.1)-vs-registry refute pass found the shared COMPONENT those five
build FROM - Forbidden Idol (3114) - was itself ABSENT from the registry, so a
build holding the raw component got ZERO HSP amp though it grants +8% Heal and
Shield Power (wiki: V12.14 reduced to 8% from 10%, no later HSP change; the
finished items carry the higher 0.10).

The fix is a pure registry data-add: it reuses R60's EXISTING ``assume_hsp_amp``
default-OFF seam (``ehp.py`` self-shield pool + ``sustain.py`` REGEN self-heal).
NO new field, NO new flag, NO engine change. DEFAULT-OFF (``assume_hsp_amp=False``)
forces hsp_pct 0.0 -> BYTE-IDENTICAL. Forbidden Idol is a non-terminal component,
so it never leaks into the default ``rank_items_by_hps`` candidate output
(``include_components`` defaults False). The live default-ON flip stays
operator-gated (``docs/LIVE_GAME_GATED_SYNC.md``).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.hps import rank_items_by_hps
from agents.daemon_slayer.sustain import compute_sustain
from agents.daemon_slayer._hsp_amp import sum_wielder_hsp_pct

_FORBIDDEN_IDOL = "3114"      # heal_shield_amp_pct 0.08 (the HSP component)
_REDEMPTION = "3107"          # heal_shield_amp_pct 0.10 (finished carrier)
_STERAKS = "3053"             # ItemShield ANY (self-shield), no HSP


class ForbiddenIdolHspSumTests(unittest.TestCase):
    """3114 contributes its +8% HSP to the additive wielder-HSP sum."""

    def test_forbidden_idol_hsp_value(self) -> None:
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([_FORBIDDEN_IDOL]), 0.08, places=6
        )

    def test_additive_with_finished_carrier(self) -> None:
        # Component 0.08 + Redemption 0.10 = 0.18 (additive per the (1+hsp) model).
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([_FORBIDDEN_IDOL, _REDEMPTION]), 0.18, places=6
        )

    def test_int_id_coerced(self) -> None:
        self.assertAlmostEqual(sum_wielder_hsp_pct([3114]), 0.08, places=6)


class ForbiddenIdolEhpSeamTests(unittest.TestCase):
    """ehp.py: 3114's HSP amps the wielder's own ItemShield pool (DEFAULT-OFF)."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_off_is_byte_identical_default(self) -> None:
        # Explicit flag OFF must equal the omitted-flag default, byte-for-byte.
        base = compute_ehp(
            self.snap, "Aatrox", 11,
            item_ids=[_STERAKS, _FORBIDDEN_IDOL], mode="SR",
        )
        off = compute_ehp(
            self.snap, "Aatrox", 11,
            item_ids=[_STERAKS, _FORBIDDEN_IDOL], mode="SR",
            assume_hsp_amp=False,
        )
        self.assertEqual(off.to_dict(), base.to_dict())
        # No Spirit Visage + Forbidden Idol has no heal_amp_pct -> shield amp 1.0.
        self.assertAlmostEqual(off.shield_amp_mult, 1.0, places=6)
        self.assertGreater(off.shield_any, 0.0)

    def test_on_amps_own_shield_by_exact_hsp_pct(self) -> None:
        # Sterak (ANY self-shield) + Forbidden Idol (HSP 0.08). Seam ON scales the
        # shield pool by exactly (1 + 0.08). shield_amp_mult surfaces it.
        off = compute_ehp(
            self.snap, "Aatrox", 11,
            item_ids=[_STERAKS, _FORBIDDEN_IDOL], mode="SR",
        )
        on = compute_ehp(
            self.snap, "Aatrox", 11,
            item_ids=[_STERAKS, _FORBIDDEN_IDOL], mode="SR",
            assume_hsp_amp=True,
        )
        self.assertAlmostEqual(
            on.shield_amp_mult, off.shield_amp_mult * 1.08, places=6
        )
        # Pre-amp shield fields are unchanged (build identical); only the
        # multiplier moved. physical_ehp rises by the amped shield delta.
        self.assertAlmostEqual(on.shield_any, off.shield_any, places=6)
        self.assertGreater(on.physical_ehp, off.physical_ehp)


class ForbiddenIdolSustainSeamTests(unittest.TestCase):
    """sustain.py: 3114's HSP amps REGEN self-heal sustain only (DEFAULT-OFF)."""

    def test_off_is_byte_identical_default(self) -> None:
        base = compute_sustain("DrMundo")
        off = compute_sustain(
            "DrMundo", item_ids=[_FORBIDDEN_IDOL], assume_hsp_amp=False
        )
        self.assertEqual(off.to_dict(), base.to_dict())

    def test_on_amps_regen_by_exact_hsp_pct(self) -> None:
        # DrMundo's kit sustain is REGEN-only (P + R, both unconditional).
        off = compute_sustain("DrMundo")
        on = compute_sustain(
            "DrMundo", item_ids=[_FORBIDDEN_IDOL], assume_hsp_amp=True
        )
        self.assertGreater(off.sustain_score, 0.0)
        self.assertAlmostEqual(
            on.sustain_score, off.sustain_score * 1.08, places=6
        )
        self.assertAlmostEqual(
            on.total_sustain_score, off.total_sustain_score * 1.08, places=6
        )


class ForbiddenIdolNoRankLeakTests(unittest.TestCase):
    """3114 is a non-terminal component -> never in default ranked output."""

    def test_component_absent_from_default_ranking(self) -> None:
        # include_components defaults False; 3114 builds into finished items, so
        # adding it to the registry must NOT surface it as a ranked candidate.
        snap = DataSnapshot.load()
        r = rank_items_by_hps(snap, "Soraka", level=11, top_n=40)
        top_ids = {row.item_id for row in r.ranked}
        self.assertNotIn(_FORBIDDEN_IDOL, top_ids)


if __name__ == "__main__":
    unittest.main()
