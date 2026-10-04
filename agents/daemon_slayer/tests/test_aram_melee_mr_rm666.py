"""RM-666 (L-06): classic ARAM grants melee champions +15 bonus magic resistance.

Source: the League wiki ARAM page, Champions section, read 2026-10-04:
"Melee champions gain 15 bonus magic resistance". The behaviour pointer came
from external reference L; the constant is the wiki's, re-read by us, and
nothing was taken from that reference's code.

Scope decision (recorded in the RM-666 report): the addend lives in
``engine._apply_mode_modifiers`` behind its existing ``mode == "ARAM"`` gate,
so it reaches every scorer that resolves stats through ``build_champion``.
The wiki's ARAM: Mayhem page says "All regular ARAM rules also apply", and RC
routes KIWI to the ARAM coach which calls DS with mode ARAM, so Mayhem gets
this addend through the same gate. Mayhem's OWN global melee armor/MR grant is
NOT modelled here (the page does not say whether it stacks with, or is, the
ARAM grant).

The melee test is the canonical split (``_melee_ranged``, base attackrange
< 350) that ``rank._champion_is_melee`` wraps; ``engine`` cannot import
``rank`` (rank -> dps -> engine), so a parity test pins the engine-side
predicate to ``rank._champion_is_melee`` over the whole roster.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.engine import (
    ARAM_MELEE_BONUS_MR,
    _apply_mode_modifiers,
    _aram_champion_is_melee,
    build_champion,
)
from agents.daemon_slayer.rank import _champion_is_melee


class AramMeleeMrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_constant_is_the_wiki_value(self) -> None:
        self.assertEqual(ARAM_MELEE_BONUS_MR, 15.0)

    def test_melee_champion_gains_15_mr_in_aram(self) -> None:
        sr = build_champion(self.snap, "Aatrox", level=1, mode="SR")
        aram = build_champion(self.snap, "Aatrox", level=1, mode="ARAM")
        self.assertAlmostEqual(aram.stats["mr"] - sr.stats["mr"], 15.0)

    def test_melee_bonus_holds_at_level_18_with_items(self) -> None:
        items = ["3065"]  # Spirit Visage: flat MR item, the grant is additive
        sr = build_champion(self.snap, "Garen", level=18, item_ids=items, mode="SR")
        aram = build_champion(self.snap, "Garen", level=18, item_ids=items, mode="ARAM")
        self.assertAlmostEqual(aram.stats["mr"] - sr.stats["mr"], 15.0)

    def test_ranged_champion_gets_nothing(self) -> None:
        for champ in ("Ashe", "Lux", "Urgot"):
            sr = build_champion(self.snap, champ, level=1, mode="SR")
            aram = build_champion(self.snap, champ, level=1, mode="ARAM")
            self.assertEqual(aram.stats["mr"], sr.stats["mr"], champ)

    def test_boundary_champions_follow_the_canonical_split(self) -> None:
        # Rakan 300 and Lillia 325 are melee; Urgot 350 is ranged (RM-123).
        for champ in ("Rakan", "Lillia"):
            sr = build_champion(self.snap, champ, level=1, mode="SR")
            aram = build_champion(self.snap, champ, level=1, mode="ARAM")
            self.assertAlmostEqual(aram.stats["mr"] - sr.stats["mr"], 15.0, msg=champ)

    def test_other_modes_untouched(self) -> None:
        base = build_champion(self.snap, "Aatrox", level=1, mode="SR")
        for mode in ("ARENA", "URF", "KIWI"):
            r = build_champion(self.snap, "Aatrox", level=1, mode=mode)
            self.assertEqual(r.stats["mr"], base.stats["mr"], mode)

    def test_note_is_emitted(self) -> None:
        r = build_champion(self.snap, "Aatrox", level=1, mode="ARAM")
        self.assertTrue(any("melee +15 MR" in n for n in r.notes), r.notes)

    def test_bonus_counts_as_bonus_not_base(self) -> None:
        r = build_champion(self.snap, "Aatrox", level=1, mode="ARAM")
        self.assertAlmostEqual(r.stats["mr"] - r.base_stats["mr"], 15.0)

    def test_malformed_record_fails_closed(self) -> None:
        out, _ = _apply_mode_modifiers({"mr": 30.0}, {}, "ARAM", {})
        self.assertEqual(out["mr"], 30.0)

    def test_engine_predicate_matches_rank_predicate_over_roster(self) -> None:
        for cid, rec in self.snap.champions.items():
            self.assertEqual(
                _aram_champion_is_melee(rec), _champion_is_melee(rec), cid
            )


if __name__ == "__main__":
    unittest.main()
