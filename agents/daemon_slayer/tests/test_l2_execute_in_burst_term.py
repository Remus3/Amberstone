"""L2 (DS crit-burst fix, 2026-07-13): arm the Collector execute in the burst term.

Spec: docs/specs/2026-07-13-ds-crit-burst-fix.md lever L2 + root-cause #2.

Root cause: ``rank.py`` ``_safe_burst`` - the burst helper the fight-length-
reweight knob calls for ``baseline_burst`` (rank.py:991) and every candidate
``trial_burst`` (rank.py:1090) - invoked ``compute_burst_damage`` WITHOUT
``assume_takedown``, so it defaulted to False. The Collector (6676) kill-state
execute (5% target max HP TRUE damage) is gated on ``assume_takedown``
(burst.py:1051), so it stayed 0.0 and NEVER surfaced through the fight-length
burst term for a crit ADC.

L2 passes ``assume_takedown=True`` at that ONE call site so the execute (and the
takedown / kill-state offense credit) enters the fight-length burst term. The
global ``compute_burst_damage`` default stays False so every OTHER caller / test
is byte-identical.

Assertions are deterministic + faithful to the engine, NOT a fragile ranking
claim: the execute is EXACTLY 5% of target max HP (0.05 * 2000 = 100.0 TRUE - no
resist, no low-HP amp at the default), so the seam delta is a fixed literal.
An ordering assertion would NOT be a clean discriminator here - Collector already
surfaces for Jhin at fl=0.5 via its crit component (see test_jhin_fight_length.py),
so "Collector enters top-N" is true even on the pre-L2 (execute-off) engine.

  RED  (current):  _safe_burst == the assume_takedown=False burst (no execute).
  GREEN (post-L2): _safe_burst == the assume_takedown=True burst  (+100 execute).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import _safe_burst

# The Collector (SR canonical id) carries the 5% max-HP kill-state execute.
_COLLECTOR = "6676"
# Jhin - the spec's fight-length pilot (allow-map fl=0.5), a crit ADC whose burst
# term is exactly what L2 targets. The seam is champion-agnostic; Jhin is chosen
# for spec faithfulness and a clean nonzero burst.
_CHAMP = "Jhin"
_LEVEL = 13
_ARMOR = 80.0
_TARGET_HP = 2000.0
_EXECUTE = 0.05 * _TARGET_HP  # 100.0 TRUE damage (Collector Death, Meraki 16.13.1)


def _burst(snap, item_ids, *, assume_takedown):
    return compute_burst_damage(
        snap, _CHAMP, level=_LEVEL, item_ids=list(item_ids), mode="SR",
        target_armor=_ARMOR, target_mr=0.0, target_max_hp=_TARGET_HP,
        target_bonus_hp=0.0, assume_takedown=assume_takedown,
    )


def _safe(snap, item_ids):
    # Mirror of the exact call rank_items makes for baseline_burst / trial_burst.
    return _safe_burst(
        snap, champion_id=_CHAMP, level=_LEVEL, item_ids=tuple(item_ids),
        mode="SR", target_armor=_ARMOR, target_mr=0.0, target_max_hp=_TARGET_HP,
        target_bonus_hp=0.0, augments=None,
    )


class SafeBurstArmsExecute(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_safe_burst_credits_collector_execute(self) -> None:
        # _safe_burst is the burst helper the fight-length knob calls. After L2 it
        # arms assume_takedown, so a Collector build's burst picks up the execute.
        safe = _safe(self.snap, [_COLLECTOR])
        off = _burst(self.snap, [_COLLECTOR], assume_takedown=False).total_burst_damage
        on = _burst(self.snap, [_COLLECTOR], assume_takedown=True).total_burst_damage
        # Sanity: the execute is a real, nonzero term for this build (off < on).
        self.assertGreater(on, off)
        # RED (current) -> GREEN (post-L2): _safe_burst now credits the execute.
        self.assertGreater(safe, off)
        # PRECISE: _safe_burst matches the assume_takedown=True burst exactly.
        self.assertAlmostEqual(safe, on, places=3)

    def test_execute_magnitude_mirrors_rank_items_burst_gain(self) -> None:
        # rank_items computes burst_gain = _safe_burst(new_build) - _safe_burst(
        # current_build) (rank.py:1090 / :991). The empty baseline carries no
        # execute, so the Collector candidate's burst_gain rises by EXACTLY the
        # 5% execute once L2 arms the seam.
        gain_with = _safe(self.snap, [_COLLECTOR]) - _safe(self.snap, [])
        gain_without = (
            _burst(self.snap, [_COLLECTOR], assume_takedown=False).total_burst_damage
            - _burst(self.snap, [], assume_takedown=False).total_burst_damage
        )
        # RED (current: both assume_takedown=False -> equal) -> GREEN (post-L2).
        self.assertGreater(gain_with, gain_without)
        self.assertAlmostEqual(gain_with - gain_without, _EXECUTE, places=1)


class GlobalDefaultUnchanged(unittest.TestCase):
    """GUARD: L2 changes ONLY the _safe_burst call site, not the global default."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_compute_burst_default_still_no_execute(self) -> None:
        # A direct compute_burst_damage call with the default assume_takedown
        # (False) must STILL yield a 0.0 execute - proving L2 did not flip the
        # global default. This invariant holds before AND after L2.
        res = compute_burst_damage(
            self.snap, _CHAMP, level=_LEVEL, item_ids=[_COLLECTOR], mode="SR",
            target_armor=_ARMOR, target_mr=0.0, target_max_hp=_TARGET_HP,
            target_bonus_hp=0.0,
        )
        self.assertEqual(res.execute_finisher_damage, 0.0)
        # Explicit False is identical to the omitted default.
        res_false = compute_burst_damage(
            self.snap, _CHAMP, level=_LEVEL, item_ids=[_COLLECTOR], mode="SR",
            target_armor=_ARMOR, target_mr=0.0, target_max_hp=_TARGET_HP,
            target_bonus_hp=0.0, assume_takedown=False,
        )
        self.assertEqual(res_false.execute_finisher_damage, 0.0)
        self.assertEqual(res.total_burst_damage, res_false.total_burst_damage)


class EngineVersionPin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.218.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        import pathlib

        src = pathlib.Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII bytes: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
