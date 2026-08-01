"""A-21 / RM-90 Slice S2 - positive ally-reach overrides for four engage tanks.

``_champion_ally_reach`` derives its index from the ``affects`` free-text field
on each ability form. Measured at 16.14.1 the derivation admits 38 champions and
OMITS Blitzcrank, Leona, Nautilus and Poppy - four Support-role, tank-routed
champions in the RM-90 cohort. Their raw ``affects`` values are ``Self`` /
``Enemies`` only (verified by ``test_the_four_are_invisible_to_the_raw_parser``
below), so no amount of parser widening reaches them without also admitting 27
unrelated champions whose ability PROSE merely mentions an allied turret or
minion. The module already carries a negative override (``_ALLY_REACH_EXCLUDED``
for Ornn / Sejuani); this slice adds its positive twin in the same idiom.

Leona is the strong case and the reason a prose scan is tempting: her Sunlight
passive reads "Allied champions' damaging attacks and abilities against a marked
target will consume the mark", i.e. a real ally-facing grant that ``affects``
cannot express because the MARK sits on the enemy. The other three are admitted
on the same THIN, proximity-positive basis the module docstring already applies
to Nunu P and Rell E.

ASCII only.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer import _champion_ally_reach as car
from agents.daemon_slayer._champion_ally_reach import (
    _ALLY_REACH_INCLUDED,
    champion_ally_reach,
)

# The four champions this slice adds. Named, never certified by count.
_ADDED = ("Blitzcrank", "Leona", "Nautilus", "Poppy")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _REPO_ROOT / "data" / "daemon_slayer"


def _abilities() -> dict:
    patch = (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    raw = json.loads(
        (_DS_DATA / patch / "champion_abilities.json").read_text(encoding="utf-8")
    )
    return raw.get("data", raw)


class TestAllyReachPositiveOverrides(unittest.TestCase):

    def setUp(self):
        car._ally_reach_index.cache_clear()

    def tearDown(self):
        car._ally_reach_index.cache_clear()

    def test_the_four_now_reach_allies(self):
        for champ in _ADDED:
            with self.subTest(champion=champ):
                self.assertTrue(champion_ally_reach(champ))

    def test_the_four_are_invisible_to_the_raw_parser(self):
        """Proves the override is load-bearing, not a no-op restatement.

        If any of the four ever gains a real ``allies`` token upstream, this
        fails and the override for that champion should be retired rather than
        left as dead weight.
        """
        body = _abilities()
        for champ in _ADDED:
            with self.subTest(champion=champ):
                tokens: list[str] = []
                for key in ("P", "Q", "W", "E", "R"):
                    for form in body.get(champ, {}).get(key) or []:
                        tokens += car._affects_tokens(form.get("affects"))
                self.assertNotIn(car._ALLY_TOKEN, tokens)

    def test_every_override_name_exists_in_the_registry(self):
        """Anti-typo guard: a renamed / misspelled id must not silently no-op."""
        body = _abilities()
        for champ in sorted(_ALLY_REACH_INCLUDED):
            with self.subTest(champion=champ):
                self.assertIn(champ, body)

    def test_include_and_exclude_sets_are_disjoint(self):
        self.assertEqual(
            _ALLY_REACH_INCLUDED & car._ALLY_REACH_EXCLUDED, frozenset()
        )

    def test_exclusions_still_win_after_the_widening(self):
        for champ in ("Ornn", "Sejuani"):
            with self.subTest(champion=champ):
                self.assertFalse(champion_ally_reach(champ))

    def test_non_ally_control_champions_unmoved(self):
        """Rammus / Malphite are the Term A gate controls - still False."""
        for champ in ("Rammus", "Malphite"):
            with self.subTest(champion=champ):
                self.assertFalse(champion_ally_reach(champ))

    def test_derived_champions_unmoved(self):
        """The affects-derived members must survive the widening untouched."""
        for champ in ("Alistar", "Braum", "Thresh", "Taric", "Rakan"):
            with self.subTest(champion=champ):
                self.assertTrue(champion_ally_reach(champ))

    def test_index_grew_by_exactly_the_four(self):
        derived = {
            car._norm_key(c)
            for c in _abilities()
            if any(
                car._ALLY_TOKEN in car._affects_tokens(form.get("affects"))
                for key in ("P", "Q", "W", "E", "R")
                for form in (_abilities().get(c, {}).get(key) or [])
                if isinstance(form, dict)
            )
        } - {car._norm_key(c) for c in car._ALLY_REACH_EXCLUDED}
        index = car._ally_reach_index()
        self.assertEqual(
            index - derived, {car._norm_key(c) for c in _ADDED}
        )

    def test_the_four_now_move_locket_under_team_blended(self):
        """S2 acceptance, measured on the real scorer (in-process, no :8860).

        Locket of the Iron Solari is the ONE real support core item that
        ``_item_ally_grant`` prices today (Knight's Vow / Zeke's / Bandlepipes /
        Solstice Sleigh are hard-excluded at ``_item_ally_grant.py:95-105``).
        Before this slice the four sat pinned in the low twenties under BOTH
        objectives; they must now behave like the derived cohort - a strict
        improvement under ``team_blended`` - while the two documented non-reach
        controls stay byte-identical.
        """
        from agents.daemon_slayer.data_loader import DataSnapshot
        from agents.daemon_slayer.ehp import rank_items_by_ehp

        snapshot = DataSnapshot.load()

        def locket_rank(champion: str, score_by: str):
            res = rank_items_by_ehp(
                snapshot, champion, 11, [], mode="SR",
                enemy_ad_share=0.5, enemy_ap_share=0.5,
                top_n=200, score_by=score_by,
            )
            ids = [r.item_id for r in res.ranked]
            return ids.index("3190") + 1 if "3190" in ids else None

        for champ in _ADDED:
            with self.subTest(champion=champ):
                off = locket_rank(champ, "blended")
                on = locket_rank(champ, "team_blended")
                self.assertIsNotNone(off)
                self.assertIsNotNone(on)
                self.assertLess(on, off)

        for champ in ("Malphite", "Ornn"):
            with self.subTest(control=champ):
                self.assertEqual(
                    locket_rank(champ, "blended"),
                    locket_rank(champ, "team_blended"),
                )

    def test_fail_soft_stays_inert_on_a_bad_patch_pointer(self):
        """A load failure must still yield an EMPTY set - overrides included.

        The documented contract is that a broken data file makes the whole
        team_blended seam inert, never partially live off a hard-coded list.
        """
        self.assertEqual(car._ally_reach_index("no-such-patch"), frozenset())


if __name__ == "__main__":
    unittest.main()
