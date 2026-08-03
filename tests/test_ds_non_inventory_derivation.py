"""``NON_INVENTORY_IDS`` must be DERIVED from the patch-current DDragon
items.json, not hand-listed.

Root cause (fourth layer found this run; the dashboard source, two routes and
three coaches were fixed first): every one of those fixes routes through the
same shared set, and that set was a hand-typed nine-member frozenset from
s156. It covered the SR trinket row and the SR potion row and nothing else, so
the Arena trinket (``3348`` Arcane Sweeper), the ARAM/Arena snack rows
(``2052`` Poro-Snax, ``2010`` Total Biscuit) and the Arena vouchers still
counted against the six rankable DS slots on every mode but SR.

Both directions are asserted, because the mirror-image bug is worse than the
one being fixed: a set that OVER-filters drops a genuinely occupied slot and
makes the engine recommend an item the operator already owns. DDragon marks
``Watchful Wardstone`` (1100g, 150 HP / 15 MR / 10 armor) and
``Stirring Wardstone`` (350g) as ``consumed: true``, so a naive
"derive from ``consumed``" rule deletes two real legendaries. The stat-block
guard below is what stops that, and ``test_no_member_carries_stats`` is the
machine check that keeps it true across a patch bump.

DDragon also does NOT mark trinkets as ``consumed`` at all (3340 / 3363 / 3364
all carry ``consumed: None``), and ``2031`` Refillable Potion is refilled
rather than consumed - so a pure ``consumed`` derivation would silently drop
four of the audited nine. The shipped rule is a union, and the audited nine are
a hard floor that survives a missing or unreadable data file.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from core import daemon_slayer_resolver as ds_res
from core.daemon_slayer_resolver import NON_INVENTORY_IDS

# The s156 hand-audited set. Every one must survive the move to derivation.
_AUDITED_NINE = {
    "3340", "3363", "3364",
    "2003", "2031", "2055", "2138", "2139", "2140",
}

# Slot-occupying items that must NEVER be filtered. Guardian's Horn is the
# named regression from the slice brief; the two Wardstones are what a naive
# ``consumed: true`` derivation deletes; the rest are boots / starters /
# components / legendaries sampled across the build tree.
_MUST_SURVIVE = {
    "2051": "Guardian's Horn",
    "4638": "Watchful Wardstone",
    "4641": "Stirring Wardstone",
    "1001": "Boots",
    "3006": "Berserker's Greaves",
    "3020": "Sorcerer's Shoes",
    "1055": "Doran's Blade",
    "1056": "Doran's Ring",
    "1054": "Doran's Shield",
    "1082": "Dark Seal",
    "1052": "Amplifying Tome",
    "3031": "Infinity Edge",
    "6672": "Kraken Slayer",
    "3089": "Rabadon's Deathcap",
    "3153": "Blade of the Ruined King",
}


def _ddragon_items() -> dict:
    path = ds_res._items_json_path()
    assert path is not None, "patch-current DDragon items.json is missing"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


class AuditedFloorTests(unittest.TestCase):
    def test_all_nine_audited_ids_survive(self):
        missing = sorted(_AUDITED_NINE - set(NON_INVENTORY_IDS))
        self.assertEqual([], missing, f"derivation lost audited ids: {missing}")

    def test_base_constant_is_exactly_the_audited_nine(self):
        self.assertEqual(_AUDITED_NINE, set(ds_res._NON_INVENTORY_BASE_IDS))


class NewlyCoveredIdTests(unittest.TestCase):
    """The rows the hand-typed set missed. Each is live in the calibration log
    or reachable by mode."""

    def test_poro_snax_is_covered(self):
        self.assertIn("2052", NON_INVENTORY_IDS)

    def test_total_biscuit_is_covered(self):
        self.assertIn("2010", NON_INVENTORY_IDS)

    def test_aram_arena_stealth_ward_variant_is_covered(self):
        # 2056 is the consumable ward; only 3340 is the SR trinket. A name
        # lookup of "Stealth Ward" returns 2056 outside SR.
        self.assertIn("2056", NON_INVENTORY_IDS)

    def test_arena_and_alternate_trinkets_are_covered(self):
        for iid, name in (("3348", "Arcane Sweeper"),
                          ("3349", "Lucent Singularity"),
                          ("6702", "Scouting Ahead"),
                          ("3330", "Scarecrow Effigy")):
            with self.subTest(item=name):
                self.assertIn(iid, NON_INVENTORY_IDS)

    def test_arena_anvil_voucher_is_covered(self):
        self.assertIn("220008", NON_INVENTORY_IDS)


class OverFilterGuardTests(unittest.TestCase):
    """The mirror-image bug: a set that filters a real item removes an
    occupied slot and makes DS recommend something already owned."""

    def test_slot_occupying_items_are_not_filtered(self):
        for iid, name in _MUST_SURVIVE.items():
            with self.subTest(item=name):
                self.assertNotIn(iid, NON_INVENTORY_IDS)

    def test_no_member_carries_stats(self):
        # An item the DS engine can rank contributes stats. Anything with a
        # non-empty DDragon stat block is by definition rankable and must not
        # be filtered out of the slot budget.
        data = _ddragon_items()
        offenders = []
        for iid in sorted(NON_INVENTORY_IDS, key=int):
            rec = data.get(iid) or {}
            stats = {k: v for k, v in (rec.get("stats") or {}).items() if v}
            if stats:
                offenders.append((iid, rec.get("name"), stats))
        self.assertEqual([], offenders, f"stat-carrying items filtered: {offenders}")

    def test_set_is_not_absurdly_wide(self):
        # A runaway rule (e.g. filtering on a tag every item carries) would
        # pass every assertion above by emptying the build tree instead.
        data = _ddragon_items()
        self.assertLess(len(NON_INVENTORY_IDS), len(data) // 4)


class DerivationFallbackTests(unittest.TestCase):
    """A missing or unreadable data file must degrade to the audited nine,
    never to an empty set - an empty set silently restores the s156 defect on
    every mode at once."""

    def test_missing_items_json_yields_the_audited_floor(self):
        self.assertEqual(
            set(_AUDITED_NINE),
            set(ds_res._derive_non_inventory_ids(None)),
        )

    def test_unreadable_items_json_yields_the_audited_floor(self):
        bogus = pathlib.Path(__file__).with_name("does_not_exist_items.json")
        self.assertEqual(
            set(_AUDITED_NINE),
            set(ds_res._derive_non_inventory_ids(bogus)),
        )

    def test_malformed_items_json_yields_the_audited_floor(self):
        tmp = pathlib.Path(__file__).with_name("_tmp_malformed_items.json")
        tmp.write_text("{not json", encoding="utf-8")
        try:
            self.assertEqual(
                set(_AUDITED_NINE),
                set(ds_res._derive_non_inventory_ids(tmp)),
            )
        finally:
            tmp.unlink(missing_ok=True)

    def test_non_mapping_data_yields_the_audited_floor(self):
        # These parse cleanly, so the json guard never sees them; they used to
        # raise on the walk instead, at import time, taking every coach down.
        for body in ('{"data": "oops"}', '{"data": [1, 2]}', '{"data": 7}'):
            with self.subTest(body=body):
                tmp = pathlib.Path(__file__).with_name("_tmp_nonmapping_items.json")
                tmp.write_text(body, encoding="utf-8")
                try:
                    self.assertEqual(
                        set(_AUDITED_NINE),
                        set(ds_res._derive_non_inventory_ids(tmp)),
                    )
                finally:
                    tmp.unlink(missing_ok=True)


class ResolveInventoryEndToEndTests(unittest.TestCase):
    def test_poro_snax_no_longer_reaches_the_engine(self):
        ids = ds_res.resolve_inventory(
            ["Infinity Edge", "Poro-Snax", "Kraken Slayer"], mode="aram")
        self.assertEqual(["3031", "6672"], ids)

    def test_arena_trinket_no_longer_reaches_the_engine(self):
        ids = ds_res.resolve_inventory(
            ["Infinity Edge", "Arcane Sweeper"], mode="arena")
        self.assertNotIn("3348", ids)

    def test_guardians_horn_still_reaches_the_engine(self):
        ids = ds_res.resolve_inventory(["Guardian's Horn"], mode="aram")
        self.assertEqual(["2051"], ids)

    def test_resolve_many_is_untouched(self):
        # Calibration / mirror callers still see the raw live-client set.
        self.assertEqual(
            ["2052", "3031"],
            ds_res.resolve_many(["Poro-Snax", "Infinity Edge"], mode="aram"),
        )


class AsciiHygieneTests(unittest.TestCase):
    def test_no_banned_glyphs(self):
        # Built from ordinals so this guard file is itself pure ASCII.
        banned = tuple(chr(c) for c in (0x2013, 0x2014, 0x201C, 0x201D,
                                        0x2018, 0x2019))
        for p in (pathlib.Path(ds_res.__file__), pathlib.Path(__file__)):
            text = p.read_text(encoding="utf-8")
            for g in banned:
                self.assertNotIn(g, text, f"{p.name} carries {g!r}")


if __name__ == "__main__":
    unittest.main()
