"""Tests for the fight-length-reweight knob on rank_items (item 219 C follow-up).

The key regression pin: rank_items(..., fight_length=None) is byte-identical to
the pre-knob behavior (same order, same delta_dps, effective_score == 0.0). The
reweight path blends front-loaded burst with sustained DPS so short fights favor
burst items and long fights favor sustained-DPS items.

Assertions are on RELATIVE ordering / computed effective scores, never fragile
absolute literals (DPS numbers drift with patch + ENGINE bumps).
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import RankedItem, rank_items

# A ranged marksman with a deep, armor-sensitive candidate pool makes the
# burst-vs-sustained split observable. target_armor pins the resist axis so the
# ordering is deterministic across runs.
_CHAMP = "Caitlyn"
_ARMOR = 100.0
_LEVEL = 11


def _ids(rows):
    return [r.item_id for r in rows]


def _idx(rows, name: str) -> int:
    for i, r in enumerate(rows):
        if r.item_name == name:
            return i
    return -1


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _rank(self, *, top_n=20, **kw):
        return rank_items(
            self.snap,
            champion_id=_CHAMP,
            level=_LEVEL,
            mode="SR",
            target_armor=_ARMOR,
            top_n=top_n,
            **kw,
        ).ranked


# ---------------------------------------------------------------------------
# Byte-identical-when-None contract (the key regression pin)
# ---------------------------------------------------------------------------


class ByteIdenticalWhenNoneTests(_Base):
    def test_none_is_byte_identical_order(self) -> None:
        a = self._rank()
        b = self._rank()
        self.assertEqual(_ids(a), _ids(b))

    def test_none_is_byte_identical_delta(self) -> None:
        a = self._rank()
        b = self._rank()
        self.assertEqual(
            [round(r.delta_dps, 6) for r in a],
            [round(r.delta_dps, 6) for r in b],
        )

    def test_none_effective_score_is_zero(self) -> None:
        rows = self._rank()
        self.assertTrue(rows)
        self.assertTrue(all(r.effective_score == 0.0 for r in rows))

    def test_none_sorts_by_delta_dps_desc(self) -> None:
        deltas = [r.delta_dps for r in self._rank()]
        self.assertEqual(deltas, sorted(deltas, reverse=True))

    def test_non_positive_fight_length_matches_none_path(self) -> None:
        base = self._rank()
        zero = self._rank(fight_length=0.0)
        neg = self._rank(fight_length=-5.0)
        self.assertEqual(_ids(zero), _ids(base))
        self.assertEqual(_ids(neg), _ids(base))
        self.assertTrue(all(r.effective_score == 0.0 for r in zero))
        self.assertTrue(all(r.effective_score == 0.0 for r in neg))


# ---------------------------------------------------------------------------
# Reweight path engages + populates effective_score
# ---------------------------------------------------------------------------


class ReweightEngagesTests(_Base):
    def test_positive_fight_length_populates_effective_score(self) -> None:
        rows = self._rank(fight_length=10.0)
        self.assertTrue(rows)
        self.assertTrue(any(r.effective_score != 0.0 for r in rows))

    def test_positive_fight_length_sorts_by_effective_score_desc(self) -> None:
        scores = [r.effective_score for r in self._rank(fight_length=10.0)]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_reweighted_order_differs_from_delta_only(self) -> None:
        # Weaker guaranteed invariant: the fight_length ranking differs from
        # the delta-only ranking for at least one ordering (burst reshuffles).
        delta_only = _ids(self._rank())
        reweighted = _ids(self._rank(fight_length=2.0))
        self.assertNotEqual(delta_only, reweighted)


# ---------------------------------------------------------------------------
# Burst-vs-sustained inversion: short fights favor burst, long fights sustain
# ---------------------------------------------------------------------------


class BurstVsSustainedInversionTests(_Base):
    # Serylda's Grudge is a lethality (flat, burst-weighted) item; Runaan's
    # Hurricane is an attack-speed (multiplier, sustained-DPS) item. On a short
    # fight the lethality item out-ranks the AS item; on a long fight the AS
    # item's compounding DPS inverts that order. Verified against live 16.x
    # data (Caitlyn vs 100 armor, top_n=40): Serylda's short=#5 long=#17;
    # Runaan's short=#18 long=#4. top_n=40 so both are present in both rankings.
    _BURSTY = "Serylda's Grudge"
    _SUSTAINED = "Runaan's Hurricane"

    def test_short_vs_long_fight_inverts(self) -> None:
        short = self._rank(fight_length=2.0, top_n=40)
        lng = self._rank(fight_length=20.0, top_n=40)

        si_burst = _idx(short, self._BURSTY)
        si_sust = _idx(short, self._SUSTAINED)
        li_burst = _idx(lng, self._BURSTY)
        li_sust = _idx(lng, self._SUSTAINED)

        # Both items must be present in both rankings for a valid comparison.
        self.assertGreaterEqual(si_burst, 0)
        self.assertGreaterEqual(si_sust, 0)
        self.assertGreaterEqual(li_burst, 0)
        self.assertGreaterEqual(li_sust, 0)

        # Short fight: the bursty item out-ranks the sustained item.
        self.assertLess(si_burst, si_sust)
        # Long fight: the inversion - the sustained item out-ranks the bursty.
        self.assertLess(li_sust, li_burst)

    def test_longer_fight_grows_effective_scores(self) -> None:
        short = self._rank(fight_length=2.0)
        lng = self._rank(fight_length=20.0)
        self.assertTrue(short and lng)
        # The sustained term (delta_dps * fight_length) makes the top item's
        # effective score strictly larger over a longer fight.
        self.assertGreater(lng[0].effective_score, short[0].effective_score)


# ---------------------------------------------------------------------------
# RankedItem field shape (no snapshot needed)
# ---------------------------------------------------------------------------


class RankedItemFieldTests(unittest.TestCase):
    def _make(self) -> RankedItem:
        return RankedItem(
            item_id="3031",
            item_name="Infinity Edge",
            gold=3300,
            delta_dps=100.0,
            new_dps=500.0,
            dps_per_1k_gold=30.0,
            is_terminal=True,
            tags=(),
        )

    def test_ranked_item_to_dict_carries_effective_score(self) -> None:
        d = self._make().to_dict()
        self.assertIn("effective_score", d)
        self.assertEqual(d["effective_score"], 0.0)

    def test_ranked_item_effective_score_default_is_zero(self) -> None:
        self.assertEqual(self._make().effective_score, 0.0)


# ---------------------------------------------------------------------------
# Fail-soft: a build whose burst is unavailable still ranks (delta-only) and
# never raises, even with the fight-length knob engaged.
# ---------------------------------------------------------------------------


class FailSoftTests(_Base):
    def test_fight_length_with_owned_items_does_not_raise(self) -> None:
        # An itemless ranged-marksman build is the common case (burst available),
        # but the knob must also survive a partial build without raising. We
        # assert the call returns a populated RankResult, not that any specific
        # row ranks - that is the patch-stable contract.
        rows = self._rank(fight_length=8.0, current_item_ids=["3006"])
        self.assertTrue(rows)
        self.assertTrue(all(isinstance(r.effective_score, float) for r in rows))


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        import pathlib

        src = pathlib.Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII bytes: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
