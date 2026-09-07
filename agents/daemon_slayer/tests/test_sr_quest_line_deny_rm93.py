"""RM-93 - the World Atlas support-quest line is denied on SR as a COMPLETE set.

Pre-RM-93 the shared candidate-pool deny (``rank._SR_EXCLUDED_ITEM_IDS``) held a
strict SUBSET of the line - World Atlas 3865 plus only two of the five Bounty of
Worlds upgrades (Zaz'Zak's 3871, Bloodsong 3877) - so Celestial Opposition 3869,
Dream Maker 3870 and Solstice Sleigh 3876 ranked as a contiguous bottom block on
every SR route (measured 2026-07-18: Vel'Koz #97-#99 of a 144-item pool).

The split was ad hoc rather than principled: 3871 and 3877 are the two line items
carrying modelled damage formulas in ``_effects_data.py``, so they ranked HIGH and
drew a deny; the other three ranked low and were never noticed.

The deny's ORIGINAL rationale ("ARAM-only support-quest upgrades, maps[12]=True /
maps[11]=True upstream bug", commit f297cda1, ENGINE 1.184.0) was factually WRONG
and is pinned as wrong below: DDragon carries ``maps["11"]=True`` AND
``maps["12"]=False`` for every one of the eight line items - i.e. the data
correctly says SR-legal and ARAM-illegal. The World Atlas support quest is a
Summoner's Rift system; Howling Abyss has no support quest at all.

The CORRECT rationale is the one already adjudicated and test-pinned for the
enchanter pool in ``tests/test_enchanter_pool_hsp_rm90.py:31-36``: these are 400g
MUTUALLY EXCLUSIVE quest-progression upgrades - you pick exactly one when Bounty
of Worlds (3867) completes - so ranking them against 3000g legendaries is a
category error. Admitting them was MEASURED to put Bloodsong at rank #2 for
Vel'Koz and #3 for Jinx, which is an RM-92 (non-output item) mispricing, not a
usable recommendation. This slice extends that accepted doctrine from the
enchanter pool to the shared ``_filter_candidates`` SR deny, where it had been
applied inconsistently.

The completeness assertion below is derived from ``3867["into"]`` (DATA), not from
a hard-coded id list, so a sixth upgrade added in a future patch auto-fails this
test until it is denied.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import _SR_EXCLUDED_ITEM_IDS, _filter_candidates

WORLD_ATLAS = "3865"
BOUNTY_OF_WORLDS = "3867"


def _sr_pool_ids(snapshot: DataSnapshot) -> set[str]:
    """Item ids surviving the shared SR candidate filter (default ranking call)."""
    return {
        item_id
        for item_id, _record in _filter_candidates(
            snapshot,
            "SR",
            set(),
            None,
            False,
            None,
        )
    }


class WorldAtlasQuestLineDenyTests(unittest.TestCase):
    """The whole quest line - starter plus every upgrade - is off the SR pool."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = DataSnapshot.load()
        cls.items = cls.snapshot.items
        cls.pool = _sr_pool_ids(cls.snapshot)

    def _upgrade_ids(self) -> list[str]:
        """The five Bounty of Worlds choices, read from the DATA not a literal."""
        into = self.items[BOUNTY_OF_WORLDS].get("into") or []
        self.assertTrue(
            into,
            "3867 Bounty of Worlds lost its 'into' list - the data shape this test "
            "derives completeness from has changed; re-derive before editing the deny.",
        )
        return [str(i) for i in into]

    def test_bounty_of_worlds_still_has_five_upgrade_choices(self) -> None:
        """Shape guard - if Riot adds a sixth, the tests below cover it too."""
        self.assertEqual(len(self._upgrade_ids()), 5)

    def test_whole_world_atlas_line_denied_on_sr(self) -> None:
        """RED before RM-93 on 3869 / 3870 / 3876.

        This is the regression the slice exists to fix.
        """
        leaked = sorted(i for i in self._upgrade_ids() if i in self.pool)
        self.assertEqual(
            leaked,
            [],
            "Bounty of Worlds upgrades leaked into the SR candidate pool: "
            f"{leaked}. They are mutually exclusive 400g quest rewards, not "
            "free-slot purchases - ranking them against legendaries is the "
            "category error pinned in test_enchanter_pool_hsp_rm90.py:31-36.",
        )

    def test_world_atlas_starter_denied_on_sr(self) -> None:
        self.assertNotIn(WORLD_ATLAS, self.pool)

    def test_deny_set_is_sibling_complete(self) -> None:
        """The constant itself covers the starter and every upgrade choice."""
        missing = sorted(
            i
            for i in [WORLD_ATLAS, *self._upgrade_ids()]
            if i not in _SR_EXCLUDED_ITEM_IDS
        )
        self.assertEqual(
            missing,
            [],
            f"_SR_EXCLUDED_ITEM_IDS is sibling-incomplete, missing {missing}.",
        )


class WorldAtlasRationaleTests(unittest.TestCase):
    """Pin the FACTS that justify the deny, so the false rationale cannot return.

    The original comment claimed these were ARAM-only via a maps upstream bug.
    They are not. If these assertions ever fail, the upstream data really did
    change and the deny's justification must be re-argued - not silently kept.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.items = DataSnapshot.load().items

    def test_line_is_sr_legal_and_aram_illegal_in_ddragon(self) -> None:
        into = [str(i) for i in (self.items[BOUNTY_OF_WORLDS].get("into") or [])]
        for item_id in [WORLD_ATLAS, BOUNTY_OF_WORLDS, *into]:
            maps = self.items[item_id].get("maps") or {}
            with self.subTest(item=item_id, name=self.items[item_id].get("name")):
                self.assertTrue(
                    maps.get("11"),
                    "DDragon says this is SR-LEGAL; the deny is a category "
                    "judgement about quest rewards, NOT a maps-flag correction.",
                )
                self.assertFalse(
                    maps.get("12"),
                    "DDragon says this is ARAM-ILLEGAL; the 'ARAM-only' rationale "
                    "in the pre-RM-93 comment was factually wrong.",
                )

    def test_upgrades_are_mutually_exclusive_same_cost_rewards(self) -> None:
        """The real reason to deny: one 400g pick, not a rankable slot purchase."""
        for item_id in [str(i) for i in self.items[BOUNTY_OF_WORLDS]["into"]]:
            with self.subTest(item=item_id, name=self.items[item_id].get("name")):
                self.assertEqual(self.items[item_id]["gold"]["total"], 400)


if __name__ == "__main__":
    unittest.main()
