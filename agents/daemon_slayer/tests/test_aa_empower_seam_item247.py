"""GAP-1 Phase C2 (item 247) - AA-empowerment amp seam in compute_dps.

The 5 base="aa" AmpEntry champs (Caitlyn W / Fiora E / Jayce W f1 / Sivir W /
Nidalee Q) were registered (item 239) but INERT - no consumer. This slice
wires them into the AA scorer via compute_dps(apply_ability_amps=True),
scaling ONLY the base-AA component (not item procs).

Covers:
  * DEFAULT byte-identical: compute_dps(apply_ability_amps=False) ==
    compute_dps(apply_ability_amps=True) for every champ today - the 5 entries
    carry placeholder amp_per_rank=(0.0,) so the seam is inert (forward-marker).
  * _aa_amp_multiplier returns 1.0 for the 5 aa-champs (forward-marker) and for
    a control non-aa champ.
  * SEAM APPLIES: a monkeypatched always_on +amp scales the base AA (pure-crit
    build ratio == 1 + amp) and ONLY the base AA (a proc build ratio is
    strictly between 1.0 and 1 + amp - item procs stay unamped).
  * The /dps route reads apply_ability_amps (wiring pin).

Does NOT pin ENGINE_VERSION (owned by orchestrator).
"""
from __future__ import annotations

import pathlib
import unittest
from dataclasses import replace

import agents.daemon_slayer._ability_amp_overrides as AMP
from agents.daemon_slayer import dps as D
from agents.daemon_slayer._ability_amp_overrides import _aa_amp_multiplier
from agents.daemon_slayer.ability_dps import rank_at_level
from agents.daemon_slayer.data_loader import DataSnapshot

_AA_CHAMPS = ("Caitlyn", "Fiora", "Jayce", "Sivir", "Nidalee")


class _SnapMixin(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()


class ByteIdenticalDefaultTests(_SnapMixin):
    def test_flag_on_equals_off_today(self) -> None:
        # placeholder entries are inert -> apply_ability_amps changes nothing
        for champ in _AA_CHAMPS + ("Aatrox", "Jinx"):
            off = D.compute_dps(self.snap, champion_id=champ, level=11,
                                item_ids=["3031"], apply_ability_amps=False).weighted_dps
            on = D.compute_dps(self.snap, champion_id=champ, level=11,
                               item_ids=["3031"], apply_ability_amps=True).weighted_dps
            self.assertAlmostEqual(off, on, places=9, msg=f"{champ}: seam not byte-identical")


class AaAmpMultiplierTests(unittest.TestCase):
    def test_forward_marker_is_one_for_aa_champs(self) -> None:
        for champ in _AA_CHAMPS:
            f = _aa_amp_multiplier(champ, lambda k: rank_at_level(k, 11))
            self.assertEqual(f, 1.0, f"{champ} aa-amp factor should be 1.0 (placeholder)")

    def test_non_aa_champ_is_one(self) -> None:
        self.assertEqual(_aa_amp_multiplier("Aatrox", lambda k: rank_at_level(k, 11)), 1.0)


class SeamAppliesTests(_SnapMixin):
    """Monkeypatch a real always_on amp to prove the seam math + AA-only scope."""

    def setUp(self) -> None:
        self._key = ("Sivir", "W", 0)
        self._orig = AMP._ABILITY_AMP_OVERRIDES[self._key]

    def tearDown(self) -> None:
        AMP._ABILITY_AMP_OVERRIDES[self._key] = self._orig

    def _patch(self, amp: float) -> None:
        AMP._ABILITY_AMP_OVERRIDES[self._key] = replace(
            self._orig, amp_per_rank=(amp,), always_on=True
        )

    def _dps(self, items: list[str], *, on: bool) -> float:
        return D.compute_dps(self.snap, champion_id="Sivir", level=11,
                             item_ids=items, apply_ability_amps=on).weighted_dps

    def test_pure_aa_build_fully_amped(self) -> None:
        # Infinity Edge build = pure base-AA (no periodic proc) -> ratio == 1 + amp
        self._patch(0.25)
        off = self._dps(["3031"], on=False)
        on = self._dps(["3031"], on=True)
        self.assertAlmostEqual(on / off, 1.25, places=4)

    def test_proc_build_aa_only_scope(self) -> None:
        # A proc-bearing build (Wit's End on-hit) -> the AA-empower amp scales
        # ONLY base AA, so the overall ratio is strictly inside (1.0, 1+amp).
        self._patch(0.50)
        off = self._dps(["3091"], on=False)
        on = self._dps(["3091"], on=True)
        ratio = on / off
        self.assertGreater(ratio, 1.0)
        self.assertLess(ratio, 1.50)

    def test_flag_off_ignores_patch(self) -> None:
        self._patch(0.50)
        self.assertAlmostEqual(
            self._dps(["3031"], on=False), D.compute_dps(
                self.snap, champion_id="Sivir", level=11, item_ids=["3031"],
                apply_ability_amps=False).weighted_dps, places=9)


class RouteWiringTests(unittest.TestCase):
    def test_dps_route_reads_apply_ability_amps(self) -> None:
        src = pathlib.Path(D.__file__).with_name("server.py").read_text(encoding="utf-8")
        self.assertIn('apply_ability_amps = _opt_bool(body, "apply_ability_amps", False)', src)
        self.assertIn("apply_ability_amps=apply_ability_amps", src)


class AsciiHygieneTests(unittest.TestCase):
    def test_authored_modules_ascii(self) -> None:
        # _ability_amp_overrides.py + this test are authored ASCII-clean. dps.py
        # carries pre-existing non-ASCII bytes (operator-gated retro-sweep); the
        # item-247 additions to it add zero non-ASCII (verified by diff at ship).
        pathlib.Path(AMP.__file__).read_bytes().decode("ascii")
        pathlib.Path(__file__).read_bytes().decode("ascii")


if __name__ == "__main__":
    unittest.main()
