"""``dashboard/_liveclient.py`` :: ``liveclient_summary`` must emit
``owned_item_ids`` as an INVENTORY list, not a raw slot dump.

The Live Client ``allPlayers[].items`` array serializes the trinket and the
consumable rows inline with shop items, so an unfiltered projection reports
a five-item build as six and a six-item build as seven. Every downstream
consumer that compares the length against the six rankable DS slots then
reads the build as complete one item early and hides the last-item advice.
This is the s156 defect (see ``core.daemon_slayer_resolver.NON_INVENTORY_IDS``)
reaching the dashboard through a second, unfiltered path.

The authoritative non-inventory id set already exists as
``core.daemon_slayer_resolver.NON_INVENTORY_IDS``; the summary must reuse it
rather than carry a private copy that can drift.

The sibling name list ``owned_items`` is DELIBERATELY left unfiltered: the
next-buy widget's TRINKET row (``web/js/lib/next_buy_model.js`` ->
``trinketNudge``) fires only when a trinket display name is present, and the
overlay ward cue reads the raw items array. Filtering names would break both,
so the parallel-order property between the two lists no longer holds and is
pinned as such below.
"""
from __future__ import annotations

import pathlib
import time
import unittest
from unittest import mock

from core.daemon_slayer_resolver import NON_INVENTORY_IDS
from dashboard import _liveclient

_ME = "SamplePlayer"

# Five real, slot-occupying legendaries plus one trinket and one consumable.
_FIVE_REAL = [
    ("3153", "Blade of The Ruined King"),
    ("3172", "Gunmetal Greaves"),
    ("3085", "Runaan's Hurricane"),
    ("3036", "Lord Dominik's Regards"),
    ("3031", "Infinity Edge"),
]
_TRINKET = ("3340", "Stealth Ward")
_CONSUMABLE = ("2003", "Health Potion")


def _items(pairs) -> list:
    return [
        {"itemID": int(iid), "displayName": name, "slot": i, "canUse": True}
        for i, (iid, name) in enumerate(pairs)
    ]


def _allgamedata(item_pairs) -> dict:
    return {
        "activePlayer": {
            "summonerName": _ME,
            "level": 13,
            "currentGold": 900,
            "championStats": {
                "currentHealth": 1800,
                "maxHealth": 2100,
                "resourceValue": 300,
                "resourceMax": 400,
            },
        },
        "allPlayers": [
            {
                "summonerName": _ME,
                "championName": "Ashe",
                "team": "ORDER",
                "items": _items(item_pairs),
                "scores": {"kills": 4, "deaths": 2, "assists": 6,
                           "creepScore": 180, "wardScore": 0.0},
            },
            {
                "summonerName": "Zed",
                "championName": "Zed",
                "team": "CHAOS",
                "items": [],
                "scores": {"kills": 3, "deaths": 3, "assists": 1,
                           "creepScore": 150, "wardScore": 0.0},
            },
        ],
        "gameData": {"gameTime": 900.0, "gameMode": "CLASSIC"},
    }


def _summary(item_pairs) -> dict:
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=_allgamedata(item_pairs), ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        return _liveclient.liveclient_summary()


class OwnedItemIdsInventoryFilterTests(unittest.TestCase):
    def test_trinket_plus_five_items_yields_five_inventory_ids(self):
        out = _summary(_FIVE_REAL + [_TRINKET])
        self.assertEqual(len(out.get("owned_item_ids") or []), 5)
        self.assertEqual(
            out["owned_item_ids"],
            [iid for iid, _ in _FIVE_REAL],
        )

    def test_six_real_items_plus_trinket_is_not_seven(self):
        six = _FIVE_REAL + [("6673", "Immortal Shieldbow")]
        out = _summary(six + [_TRINKET])
        self.assertEqual(len(out.get("owned_item_ids") or []), 6)

    def test_consumables_are_dropped_too(self):
        out = _summary(_FIVE_REAL + [_TRINKET, _CONSUMABLE])
        ids = out.get("owned_item_ids") or []
        self.assertNotIn(_CONSUMABLE[0], ids)
        self.assertNotIn(_TRINKET[0], ids)
        self.assertEqual(len(ids), 5)

    def test_order_is_preserved_for_the_surviving_ids(self):
        pairs = [_TRINKET, _FIVE_REAL[2], _CONSUMABLE, _FIVE_REAL[0]]
        out = _summary(pairs)
        self.assertEqual(out["owned_item_ids"],
                         [_FIVE_REAL[2][0], _FIVE_REAL[0][0]])

    def test_an_all_non_inventory_inventory_yields_empty(self):
        out = _summary([_TRINKET, _CONSUMABLE])
        self.assertEqual(out.get("owned_item_ids"), [])

    def test_no_live_player_still_yields_empty_list(self):
        from core.liveclient_cache import Snapshot
        data = _allgamedata(_FIVE_REAL)
        data["allPlayers"][0]["summonerName"] = "SomebodyElse"
        snap = Snapshot(data=data, ts=time.time())
        with mock.patch("core.liveclient_cache.get", return_value=snap):
            out = _liveclient.liveclient_summary()
        self.assertEqual(out.get("owned_item_ids"), [])


class NameListStaysUnfilteredTests(unittest.TestCase):
    """``owned_items`` (display names) keeps the trinket - the next-buy
    TRINKET row and the ward cue both depend on it being present."""

    def test_owned_items_names_still_carry_the_trinket(self):
        out = _summary(_FIVE_REAL + [_TRINKET])
        self.assertIn(_TRINKET[1], out.get("owned_items") or [])
        self.assertEqual(len(out["owned_items"]), 6)

    def test_ward_cue_still_computed_from_the_raw_items_array(self):
        out = _summary(_FIVE_REAL + [_TRINKET])
        self.assertIsInstance(out.get("ward_cue"), dict)


class SharedNonInventorySetTests(unittest.TestCase):
    """One definition, not two: the summary must reuse the resolver's set."""

    def test_summary_drops_exactly_the_shared_set(self):
        for iid in sorted(NON_INVENTORY_IDS):
            out = _summary(_FIVE_REAL + [(iid, "x")])
            self.assertNotIn(iid, out.get("owned_item_ids") or [])
            self.assertEqual(len(out["owned_item_ids"]), 5, iid)

    def test_module_declares_no_private_copy_of_the_id_set(self):
        src = pathlib.Path(_liveclient.__file__).read_text(encoding="utf-8")
        self.assertIn("NON_INVENTORY_IDS", src)
        self.assertNotIn("3363", src)
        self.assertNotIn("2031", src)


class AsciiHygieneTests(unittest.TestCase):
    def test_no_banned_glyphs(self):
        # Built from ordinals so this guard file is itself pure ASCII.
        banned = tuple(chr(c) for c in (0x2013, 0x2014, 0x201C, 0x201D,
                                        0x2018, 0x2019))
        for p in (pathlib.Path(_liveclient.__file__), pathlib.Path(__file__)):
            text = p.read_text(encoding="utf-8")
            for g in banned:
                self.assertNotIn(g, text, f"{p.name} carries {g!r}")


if __name__ == "__main__":
    unittest.main()
