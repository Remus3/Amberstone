# arch: regression - scenario_matrix honors caller sequence for burst/combo/rune_burst | section=daemon_slayer | frozen=no
"""Regression: ``sweep_scenarios(sequence=...)`` must be HONORED by the
``burst`` / ``combo`` / ``rune_burst`` metrics, not silently dropped.

Operator-reported (Udyr): "a scenario of just an empowered R" returned an
AD build comparable to a full-AP build. Root cause was NOT an AD field on
Udyr R (its blocks are pure MAGIC + ap_pct - verified). The defect was in
``scenario_matrix._score_cell``: the ``sequence`` arg was consumed ONLY by
``mana_bounded_dps``; the ``combo`` branch hardcoded the default Q-AA-W-R
and the ``burst`` / ``rune_burst`` branches passed no ``combo_sequence`` to
``compute_burst_damage`` (so they ran the full max-priority rotation). An
operator passing ``sequence=["R"]`` to interrogate R in isolation therefore
scored the FULL combo - which for an auto-attacker like Udyr is dominated
by AAs + Q's %max-hp PHYSICAL on-hit, making an AD build look competitive
on what was meant to be a pure-AP R-only scenario.

Contract after the fix:
  * ``combo`` / ``burst`` / ``rune_burst`` HONOR a caller-supplied sequence
    (an R-only scenario isolates R -> AP build > AD build, since R is magic).
  * a caller-supplied sequence CHANGES the value vs the default rotation
    (so ``seq=["R"]`` != ``seq=["Q","AA","W","R"]`` for combo).
  * ``sequence=None`` stays BYTE-IDENTICAL to today's default-rotation path
    (live :8893 / beam / rank never pass a sequence -> unaffected).
  * ``dps`` stays sequence-agnostic (the AA scorer has no sequence concept).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.scenario_matrix import sweep_scenarios

# Udyr: on-hit auto-attacker whose R (Wingborne Storm) is pure MAGIC/AP but
# whose Q on-hit + AAs are PHYSICAL. The clearest reproduction champion.
_CHAMP = "Udyr"
# Pure-AD vs pure-AP builds (real ids from data/daemon_slayer/<patch>/).
_AD = ("3006", "3031", "3036", "3072", "3153", "3074")
_AP = ("3020", "3089", "3157", "4645", "3135", "3116")
# Single target profile: (armor, mr, max_hp, bonus_hp).
_TP = ((80.0, 60.0, 2200.0, 0.0),)
_LVL = (11,)

_SNAP = DataSnapshot.load()


def _val(metric, items, sequence):
    cells = sweep_scenarios(
        _CHAMP, list(_LVL), [list(items)], list(_TP),
        modes=("SR",), metric=metric, sequence=sequence, snapshot=_SNAP,
    )
    return float(cells[0].value)


class ComboSequenceHonoredTests(unittest.TestCase):
    def test_combo_r_only_isolates_r_ap_beats_ad(self):
        """combo seq=['R'] isolates R (magic) -> AP build > AD build."""
        ad = _val("combo", _AD, ["R"])
        ap = _val("combo", _AP, ["R"])
        self.assertGreater(
            ap, ad,
            f"R-only combo should favor AP (R is magic); got AD={ad} AP={ap}",
        )

    def test_combo_r_only_differs_from_full_rotation(self):
        """seq=['R'] must NOT equal the default Q-AA-W-R combo (seq honored)."""
        r_only = _val("combo", _AD, ["R"])
        full = _val("combo", _AD, ["Q", "AA", "W", "R"])
        self.assertNotAlmostEqual(
            r_only, full, places=3,
            msg=f"sequence ignored: combo[R]={r_only} == combo[full]={full}",
        )

    def test_combo_none_is_default_rotation(self):
        """sequence=None stays the default Q-AA-W-R rotation (byte-identical)."""
        none_v = _val("combo", _AD, None)
        full_v = _val("combo", _AD, ["Q", "AA", "W", "R"])
        self.assertAlmostEqual(none_v, full_v, places=6)


class BurstSequenceHonoredTests(unittest.TestCase):
    def test_burst_r_only_isolates_r_ap_beats_ad(self):
        """burst seq=['R'] isolates R -> AP build > AD build (no AA fold)."""
        ad = _val("burst", _AD, ["R"])
        ap = _val("burst", _AP, ["R"])
        self.assertGreater(
            ap, ad,
            f"R-only burst should favor AP (R is magic); got AD={ad} AP={ap}",
        )

    def test_burst_none_unchanged_full_rotation(self):
        """sequence=None keeps the full max-priority rotation (AD-favoring for Udyr)."""
        ad_none = _val("burst", _AD, None)
        ap_none = _val("burst", _AP, None)
        # Udyr full rotation is AA-heavy -> AD competitive/winning; the point
        # is only that None still runs the rotation (large, finite, AD-rich),
        # NOT the tiny R-only number.
        self.assertGreater(ad_none, _val("burst", _AD, ["R"]))
        self.assertGreater(ad_none, 0.0)
        self.assertGreater(ap_none, 0.0)


class RuneBurstSequenceHonoredTests(unittest.TestCase):
    def test_rune_burst_r_only_isolates_r(self):
        """rune_burst seq=['R'] isolates R -> AP build > AD build."""
        ad = _val("rune_burst", _AD, ["R"])
        ap = _val("rune_burst", _AP, ["R"])
        self.assertGreater(ap, ad, f"got AD={ad} AP={ap}")


class DpsStaysSequenceAgnosticTests(unittest.TestCase):
    def test_dps_sequence_none_equals_r(self):
        """dps is the AA scorer - sequence has no effect (contract preserved)."""
        none_v = _val("dps", _AD, None)
        r_v = _val("dps", _AD, ["R"])
        self.assertAlmostEqual(none_v, r_v, places=6)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_and_test_are_ascii(self):
        import agents.daemon_slayer.scenario_matrix as sm
        for p in (Path(sm.__file__), Path(__file__)):
            data = p.read_bytes()
            non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
            self.assertEqual(non_ascii, [], f"non-ASCII bytes in {p.name}")


if __name__ == "__main__":
    unittest.main()
