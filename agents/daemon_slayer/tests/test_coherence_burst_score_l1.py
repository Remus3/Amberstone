"""L1 + L4 crit-burst fix: coherence_rerank respects the burst-inclusive score
carried by the REAL client row - and the final ranking is target-sensitive again.

Root cause #1 (docs/specs/2026-07-13-ds-crit-burst-fix.md, lever L1): when a
carry champion's fight_length is engaged, agents.daemon_slayer.rank.rank_for
returns rows ordered by the burst-inclusive ``effective_score``
(= burst_gain + delta_dps * fight_length), and
core.build_planner.coherence.coherence_rerank must sort on THAT (not raw
``delta_dps``) so the fight_length reweight survives.

L4 (2026-07-13) closed the production hole L1 left: the LIVE client row
``core.daemon_slayer_client.RankedItem`` did NOT parse the server's
``effective_score``, so ``_coherence_adj`` read a MISSING attribute -> base 0.0
-> the engaged path collapsed to a target-BLIND kit-fit sort and the reweight was
inert live (the original L1 test passed only because its ``_FakeRow`` fixture
populated ``effective_score`` - a fixture-shaped-to-bug miss). L4 (a) parses
``effective_score`` into ``RankedItem``, and (b) adds a SEPARATE, scaled
eff-branch dock (``_MU_EFF`` / ``_W_EFF``) so the Essence Reaver / Eclipse
artifacts stay docked below the crit core against the ~hundreds-scale
effective_score base (the delta-branch ``_MU`` / ``_W`` stay byte-identical).

These tests drive the pure re-rank helper with the REAL client ``RankedItem``
(now carrying ``effective_score``) - NOT a bespoke fixture type - so they would
have caught the L1 production hole. They are deterministic and server-free.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import unittest

from core.build_planner.coherence import coherence_rerank
from core.daemon_slayer_client import RankedItem

_IE = "3031"       # Infinity Edge - crit amplifier (LOW delta, HIGH effective)
_BORK = "3153"     # Blade of the Ruined King - on-hit (HIGH delta, LOW effective)
_ER = "3508"       # Essence Reaver - spellblade artifact (kit penalty ~2.5)
_COLLECTOR = "6676"  # The Collector - crit / lethality execute
_CHAMP = "Jinx"    # crit ADC: carry archetype, not caster-marksman -> engages


def _rows():
    # REAL client RankedItem rows (the live carry-chokepoint row type). delta_dps
    # order and effective_score order DISAGREE by construction:
    #   delta:      BORK (2000) > IE (200)
    #   effective:  IE  (2000) > BORK (200)
    # The ~1800 gaps dwarf the coherence dock, so the ordering under test is
    # decided purely by the chosen BASE - proving which field coherence sorts on.
    return [
        RankedItem(
            item_id=_IE, item_name="Infinity Edge", delta_dps=200.0, gold=3300,
            effective_score=2000.0,
        ),
        RankedItem(
            item_id=_BORK, item_name="Blade of the Ruined King", delta_dps=2000.0,
            gold=3200, effective_score=200.0,
        ),
    ]


class ClientRowCarriesEffectiveScoreTest(unittest.TestCase):
    """L4 (a): the real client row parses + carries the server effective_score."""

    def test_from_dict_parses_effective_score(self) -> None:
        # The exact field L1 relied on and the pre-L4 client silently dropped.
        row = RankedItem.from_dict({
            "item_id": _IE, "item_name": "Infinity Edge",
            "delta_dps": 20.0, "effective_score": 437.245,
        })
        self.assertEqual(row.effective_score, 437.245)

    def test_from_dict_effective_score_defaults_zero(self) -> None:
        # An older / partial payload without the key defaults to 0.0 (no crash).
        self.assertEqual(RankedItem.from_dict({"item_id": _IE}).effective_score, 0.0)


class CoherenceBurstScoreL1Test(unittest.TestCase):
    def test_fight_length_engaged_ranks_by_effective_score(self) -> None:
        """With fight_length engaged (> 0), coherence_rerank ranks the
        HIGH-effective_score row (IE) above the HIGH-delta_dps row (BORK) - i.e.
        it sorts on the burst-inclusive score the real client row now carries,
        NOT raw delta_dps."""
        out = [
            r.item_id
            for r in coherence_rerank(_rows(), _CHAMP, top=6, fight_length=0.5)
        ]
        self.assertIn(_IE, out)
        self.assertIn(_BORK, out)
        self.assertLess(
            out.index(_IE), out.index(_BORK),
            f"fight_length engaged must surface the burst-inclusive core IE "
            f"({_IE}) above the on-hit stat-stick BORK ({_BORK}) - got {out}",
        )

    def test_fight_length_disengaged_is_delta_order(self) -> None:
        """GUARD: with fight_length None (the default path - every non-mapped
        champ), coherence_rerank is byte-identical to today - the raw delta_dps
        order (BORK above IE) - and the explicit-None call equals the default."""
        default_out = [r.item_id for r in coherence_rerank(_rows(), _CHAMP, top=6)]
        none_out = [
            r.item_id
            for r in coherence_rerank(_rows(), _CHAMP, top=6, fight_length=None)
        ]
        self.assertEqual(none_out, default_out)
        self.assertLess(
            default_out.index(_BORK), default_out.index(_IE),
            f"fight_length disengaged must keep the delta_dps order (BORK above "
            f"IE) - got {default_out}",
        )

    def test_nonpositive_fight_length_treated_as_disengaged(self) -> None:
        """A non-positive fight_length (<= 0) is treated as disengaged (spec:
        'None or <= 0'), so the output matches the delta_dps default path."""
        default_out = [r.item_id for r in coherence_rerank(_rows(), _CHAMP, top=6)]
        zero_out = [
            r.item_id
            for r in coherence_rerank(_rows(), _CHAMP, top=6, fight_length=0.0)
        ]
        neg_out = [
            r.item_id
            for r in coherence_rerank(_rows(), _CHAMP, top=6, fight_length=-1.0)
        ]
        self.assertEqual(zero_out, default_out)
        self.assertEqual(neg_out, default_out)


class TargetSensitivityRegressionTest(unittest.TestCase):
    """L4: the exact bug - the FINAL engaged ranking must respond to the target.

    Pre-L4 the client dropped effective_score, so the engaged path was
    target-BLIND (base 0.0 -> a kit-fit-only sort identical for every target).
    These build two engine outputs for the SAME champ that differ ONLY in
    effective_score - as the real engine's burst term differs vs a squishy vs a
    tanky target - and prove the final order now flips with it, while zeroing
    effective_score (the pre-L4 state) collapses both to the identical order.
    """

    @staticmethod
    def _pair(eff_collector: float, eff_bork: float):
        # Same items / delta / gold; only effective_score differs (the target
        # signal). BORK carries the higher raw delta_dps in both.
        return [
            RankedItem(item_id=_COLLECTOR, item_name="The Collector",
                       delta_dps=30.0, gold=3000, effective_score=eff_collector),
            RankedItem(item_id=_BORK, item_name="Blade of the Ruined King",
                       delta_dps=50.0, gold=3200, effective_score=eff_bork),
        ]

    def test_final_order_flips_with_effective_score(self) -> None:
        # squishy: Collector's execute/lethality burst leads; tanky: BORK leads.
        sq = [r.item_id for r in coherence_rerank(
            self._pair(400.0, 250.0), _CHAMP, top=6, fight_length=0.5)]
        tk = [r.item_id for r in coherence_rerank(
            self._pair(250.0, 400.0), _CHAMP, top=6, fight_length=0.5)]
        self.assertNotEqual(sq, tk, "engaged final ranking must respond to target")
        self.assertLess(sq.index(_COLLECTOR), sq.index(_BORK))
        self.assertLess(tk.index(_BORK), tk.index(_COLLECTOR))

    def test_dropped_effective_score_is_target_blind_the_bug(self) -> None:
        # Reproduce the pre-L4 state: effective_score dropped -> 0.0 for all. The
        # engaged path then ignores the target signal entirely (base 0.0), so two
        # different targets collapse to the IDENTICAL order - the exact bug.
        sq0 = [RankedItem(r.item_id, r.item_name, r.delta_dps, r.gold)
               for r in self._pair(400.0, 250.0)]
        tk0 = [RankedItem(r.item_id, r.item_name, r.delta_dps, r.gold)
               for r in self._pair(250.0, 400.0)]
        self.assertEqual(
            [r.item_id for r in coherence_rerank(sq0, _CHAMP, top=6, fight_length=0.5)],
            [r.item_id for r in coherence_rerank(tk0, _CHAMP, top=6, fight_length=0.5)],
        )


class EffBranchDockTest(unittest.TestCase):
    """L4 (b): the scaled eff-branch dock sinks the ER/Eclipse artifact below the
    crit core against the burst-dominated (~hundreds) effective_score base."""

    def test_essence_reaver_docked_below_infinity_edge(self) -> None:
        # Real measured Jinx @ squishy effective_scores: ER LEADS IE on raw eff
        # (373 vs 287) but carries the spellblade-artifact kit penalty (~2.5). The
        # eff-branch dock (_MU_EFF) must sink ER below IE. The delta-branch _MU=10
        # would leave ER on top (10 * 2.5 = 25 << the 86 eff lead).
        rows = [
            RankedItem(item_id=_ER, item_name="Essence Reaver",
                       delta_dps=35.0, gold=3200, effective_score=373.0),
            RankedItem(item_id=_IE, item_name="Infinity Edge",
                       delta_dps=20.0, gold=3300, effective_score=287.0),
        ]
        out = [r.item_id for r in coherence_rerank(rows, _CHAMP, top=6, fight_length=0.5)]
        self.assertLess(
            out.index(_IE), out.index(_ER),
            f"eff-branch dock must sink Essence Reaver ({_ER}) below the crit "
            f"core IE ({_IE}) - got {out}",
        )


if __name__ == "__main__":
    unittest.main()
