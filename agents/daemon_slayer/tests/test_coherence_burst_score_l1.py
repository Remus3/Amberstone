"""L1 crit-burst fix: coherence_rerank must respect the burst-inclusive score.

Root cause #1 (docs/specs/2026-07-13-ds-crit-burst-fix.md, lever L1): when a
carry champion's fight_length is engaged, agents.daemon_slayer.rank.rank_for
returns rows ordered by the burst-inclusive ``effective_score``
(= burst_delta + delta_dps * fight_length), but
core.build_planner.coherence.coherence_rerank re-sorts them by raw ``delta_dps``
(through _coherence_adj), throwing the fight_length reweight away - proven
byte-identical across fight_length values (the live chokepoint
core/daemon_slayer_client.py:1293-1322). L1 threads an OPTIONAL ``fight_length``
into coherence_rerank so the re-rank BASE becomes ``effective_score`` when the
knob is engaged (> 0), while staying byte-identical on the default (disengaged:
None or <= 0) path.

These tests drive the pure re-rank helper with FAKE ranker rows (no live :8893,
no DataSnapshot load), so they are deterministic and server-free. The rows use
DOMINANT score gaps so the metric coherence dock (stat_fit / anti_synergy_penalty
in DPS units, ~tens) can never flip the delta-vs-effective ordering under test.
Jinx is a crit ADC that resolves as the carry archetype and is NOT a
caster-marksman, so the re-rank engages (the same champ the sibling
tests/test_carry_coherence_rerank.py exercises).

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from core.build_planner.coherence import coherence_rerank

_IE = "3031"       # Infinity Edge - crit amplifier (LOW delta, HIGH effective)
_BORK = "3153"     # Blade of the Ruined King - on-hit (HIGH delta, LOW effective)
_CHAMP = "Jinx"    # crit ADC: carry archetype, not caster-marksman -> engages


@dataclass(frozen=True)
class _FakeRow:
    """Minimal ranker-row stand-in exposing the fields _coherence_adj reads."""

    item_id: str
    item_name: str
    delta_dps: float
    effective_score: float


def _rows():
    # delta_dps order and effective_score order DISAGREE by construction:
    #   delta:      BORK (2000) > IE (200)
    #   effective:  IE  (2000) > BORK (200)
    # The ~1800 gaps dwarf the coherence dock (_MU/_W in DPS units, ~tens), so
    # the ordering under test is decided purely by the chosen BASE.
    return [
        _FakeRow(_IE, "Infinity Edge", delta_dps=200.0, effective_score=2000.0),
        _FakeRow(
            _BORK, "Blade of the Ruined King",
            delta_dps=2000.0, effective_score=200.0,
        ),
    ]


class CoherenceBurstScoreL1Test(unittest.TestCase):
    def test_fight_length_engaged_ranks_by_effective_score(self):
        """RED before L1: with fight_length engaged (> 0), coherence_rerank must
        rank the HIGH-effective_score row (IE 3031) above the HIGH-delta_dps row
        (BORK 3153) - i.e. NOT the raw delta_dps order. Fails on current code,
        which ignores effective_score (no fight_length param at all)."""
        out = [
            r.item_id
            for r in coherence_rerank(_rows(), _CHAMP, top=6, fight_length=0.5)
        ]
        self.assertIn(_IE, out)
        self.assertIn(_BORK, out)
        self.assertLess(
            out.index(_IE), out.index(_BORK),
            f"fight_length engaged must surface the burst-inclusive core IE "
            f"(3031) above the on-hit stat-stick BORK (3153) - got {out}",
        )

    def test_fight_length_disengaged_is_delta_order(self):
        """GUARD: with fight_length None (the default path), coherence_rerank is
        byte-identical to today - the raw delta_dps order (BORK above IE) - and
        the explicit-None call equals the no-arg default call. Proves L1 adds no
        regression on the disengaged path."""
        default_out = [r.item_id for r in coherence_rerank(_rows(), _CHAMP, top=6)]
        none_out = [
            r.item_id
            for r in coherence_rerank(_rows(), _CHAMP, top=6, fight_length=None)
        ]
        # Explicit None == default (the new optional param defaults to disengaged).
        self.assertEqual(none_out, default_out)
        # And the disengaged order is the raw delta_dps order: BORK (high delta)
        # ranks above IE (low delta).
        self.assertLess(
            default_out.index(_BORK), default_out.index(_IE),
            f"fight_length disengaged must keep the delta_dps order (BORK above "
            f"IE) - got {default_out}",
        )

    def test_nonpositive_fight_length_treated_as_disengaged(self):
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


if __name__ == "__main__":
    unittest.main()
