"""``dashboard/routes_ds_knobs.py`` must treat its ``items`` param as an
INVENTORY list, not a raw slot dump.

Sibling of the ``dashboard/_liveclient.py`` ``owned_item_ids`` defect and of
the ``dashboard/routes_ds_relscore.py`` guard: the panel feeding this route
(``web/js/panels/ds_knobs.js``) reads ``cs.my_owned_items`` / ``cs.owned_items``,
which originate from the Live Client inventory array. That array serializes
the trinket and the consumable rows inline with shop items, so an unfiltered
parse counts them against the six rankable DS slots. A five-item build plus a
ward trinket then trips the ``len(items) >= DEFAULT_SLOT_COUNT`` gate and the
route answers ``build_complete`` while a real slot is still open - the panel
goes dark in the slot where last-item advice matters most.

The authoritative set is ``core.daemon_slayer_resolver.NON_INVENTORY_IDS``
(the s156 definition); this route reuses it rather than forking a copy.

The filter sits in ``_parse_item_list`` so it covers all three consumers of
the parsed list at once: the build-complete gate, the cache key, and the
ranker call.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from core.daemon_slayer_resolver import NON_INVENTORY_IDS
from dashboard import routes_ds_knobs as rt

_MARKSMAN = "Caitlyn"
_TRINKET = "3340"        # Stealth Ward
_POTION = "2003"         # Health Potion
# Five real, slot-occupying items for the marksman.
_FIVE_REAL = ["3153", "3172", "3085", "3036", "3031"]


class StubHandler:
    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None
        self.last_ct: str | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        if not self.last_body:
            return {}
        return json.loads(self.last_body.decode("utf-8"))


def _do(path: str) -> StubHandler:
    h = StubHandler(path=path)
    rt._serve_ds_knobs(h)
    return h


class ParseItemListFilterTests(unittest.TestCase):
    def test_trinket_is_dropped(self):
        self.assertEqual(rt._parse_item_list("3153,3340,3172"),
                         ["3153", "3172"])

    def test_consumables_are_dropped(self):
        self.assertEqual(rt._parse_item_list("3153,2003,2031,2055"), ["3153"])

    def test_every_shared_non_inventory_id_is_dropped(self):
        raw = ",".join(["3153", *sorted(NON_INVENTORY_IDS), "3172"])
        self.assertEqual(rt._parse_item_list(raw), ["3153", "3172"])

    def test_real_items_and_order_survive(self):
        self.assertEqual(rt._parse_item_list(",".join(_FIVE_REAL)), _FIVE_REAL)

    def test_blank_entries_still_stripped(self):
        self.assertEqual(rt._parse_item_list("3153, ,3340,,3172"),
                         ["3153", "3172"])

    def test_empty_input_still_empty(self):
        self.assertEqual(rt._parse_item_list(""), [])


class BuildCompleteGateTests(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()

    def test_five_items_plus_trinket_is_not_build_complete(self):
        raw = ",".join([*_FIVE_REAL, _TRINKET])
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&items={raw}")
        self.assertEqual(h.last_status, 200)
        self.assertNotEqual(h.parsed().get("reason"), "build_complete")

    def test_four_items_plus_trinket_and_potion_is_not_build_complete(self):
        raw = ",".join([*_FIVE_REAL[:4], _TRINKET, _POTION])
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&items={raw}")
        self.assertEqual(h.last_status, 200)
        self.assertNotEqual(h.parsed().get("reason"), "build_complete")

    def test_six_real_items_is_still_build_complete(self):
        raw = ",".join([*_FIVE_REAL, "6673"])
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&items={raw}")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed().get("reason"), "build_complete")


class CacheKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()

    def test_trinket_does_not_split_the_cache_entry(self):
        base = ",".join(_FIVE_REAL[:2])
        _do(f"/api/ds-knobs?champion={_MARKSMAN}&items={base}")
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&items={base},{_TRINKET}")
        self.assertTrue(h.parsed().get("cached"))


class AsciiHygieneTests(unittest.TestCase):
    def test_no_banned_glyphs(self):
        # Built from ordinals so this guard file is itself pure ASCII.
        banned = tuple(chr(c) for c in (0x2013, 0x2014, 0x201C, 0x201D,
                                        0x2018, 0x2019))
        for p in (pathlib.Path(rt.__file__), pathlib.Path(__file__)):
            text = p.read_text(encoding="utf-8")
            for g in banned:
                self.assertNotIn(g, text, f"{p.name} carries {g!r}")


if __name__ == "__main__":
    unittest.main()
