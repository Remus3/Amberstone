"""P1-L7 data-ingestion correctness hardening.

Audit lane: are item stats parsed CORRECTLY and COMPLETELY from the
vendored Meraki/DDragon snapshot into what the scorers consume?

Architecture verified by this lane (locked in here so a future parse
regression fails loudly):

* The DS engine's item *stat* model is DDragon ``items.json`` (705 entries),
  mapped through ``stats.ITEM_STAT_KEY_MAP``. ``items_meraki.json`` is the
  TRIMMED Meraki snapshot (name/id/tier/rank/removed/simpleDescription/
  passives/active/shop/noEffects only) - the extractor deliberately drops
  the stat buckets because DDragon already carries them. So Meraki feeds
  passive prose + shop metadata, NOT stats.
* The scorer item universe is ``snapshot.items`` filtered by
  ``_is_purchasable`` (gold.purchasable AND gold.total>0) and
  ``_is_legal_in_mode`` (maps[map_id]).
* The "22..."-prefixed Arena mirrors (e.g. 223031 Infinity Edge) are
  SEPARATE DDragon entries with their OWN (legitimately different) stats -
  Arena IE is 55 AD vs SR IE 75 AD. The engine keys items by raw DDragon
  id, so this is correct. The byName -> 22-alias quirk is a JS dashboard
  PNG-resolution concern (web/js/lib/items_index.js), NOT this stat path.
* Unique-passive family keys are engine-authoritative (effects registry
  keyed by item id), NOT parsed from Meraki/DDragon tags - out of the
  ingestion lane by design.

Every expected value is read from the vendored snapshot inside the test
(no hardcoded magic numbers); no fragile cross-item comparison asserts.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    _is_legal_in_mode,
    _is_purchasable,
    MODE_MAP_ID,
)
from agents.daemon_slayer.stats import ITEM_STAT_KEY_MAP, aggregate_item_stats

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _REPO_ROOT / "data" / "daemon_slayer"

# DDragon stat keys whose engine kind is a unit-fraction percentage, not a
# flat add. Used only to assert the parse never confuses % with flat - the
# expected canonical/kind still comes from ITEM_STAT_KEY_MAP itself.
_PCT_DDRAGON_KEYS = {
    "PercentMovementSpeedMod",
    "PercentAttackSpeedMod",
    "PercentLifeStealMod",
    "PercentSpellVampMod",
}


class SnapshotPatchIntegrity(unittest.TestCase):
    """current.txt == manifest version == loaded patch; no id collisions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.current_txt = (
            (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
        )

    def test_loaded_patch_matches_current_txt(self) -> None:
        self.assertEqual(self.snap.patch, self.current_txt)

    def test_manifest_version_matches_current_txt(self) -> None:
        self.assertEqual(
            self.snap.manifest.get("ddragon_version"), self.current_txt
        )

    def test_item_count_matches_manifest(self) -> None:
        self.assertEqual(
            len(self.snap.items),
            self.snap.manifest.get("ddragon_item_count"),
        )

    def test_no_colliding_item_ids(self) -> None:
        str_ids = list(self.snap.items.keys())
        int_ids = {int(i) for i in str_ids}
        self.assertEqual(len(str_ids), len(int_ids))


class StatKeyMapCompleteness(unittest.TestCase):
    """Every DDragon stat key present in the snapshot is mapped (no drop)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_every_present_ddragon_stat_key_is_mapped(self) -> None:
        present: set[str] = set()
        for rec in self.snap.items.values():
            present.update((rec.get("stats") or {}).keys())
        self.assertTrue(present, "snapshot defines no item stats at all")
        unmapped = sorted(k for k in present if k not in ITEM_STAT_KEY_MAP)
        self.assertEqual(
            unmapped,
            [],
            f"DDragon stat keys silently dropped by ITEM_STAT_KEY_MAP: {unmapped}",
        )

    def test_pct_keys_map_to_pct_kind_flat_keys_to_flat(self) -> None:
        # Guards against a %-vs-flat confusion in the map.
        for ddragon_key, (_canonical, kind) in ITEM_STAT_KEY_MAP.items():
            if ddragon_key in _PCT_DDRAGON_KEYS:
                self.assertEqual(
                    kind, "pct", f"{ddragon_key} should map to pct kind"
                )
            elif ddragon_key.startswith("Flat"):
                self.assertEqual(
                    kind, "flat", f"{ddragon_key} should map to flat kind"
                )


class RoundTripFidelity(unittest.TestCase):
    """Engine aggregate == raw DDragon source for a representative spread.

    Item ids are chosen for archetype coverage; the EXPECTED numbers are
    recomputed from each item's own ``stats`` block in the snapshot - no
    literal stat values are hardcoded.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # (id, human label) - pure AD / AP / crit / on-hit-AS / tank / lethality
    # / hybrid / boots / component / Arena-only mirror.
    SPREAD = [
        ("3031", "Infinity Edge (crit + AD)"),
        ("3157", "Zhonya's Hourglass (AP + armor)"),
        ("3006", "Berserker's Greaves (flat MS + pct AS)"),
        ("3047", "Plated Steelcaps (flat MS + armor)"),
        ("3094", "Rapid Firecannon (crit + pct AS + pct MS)"),
        ("3071", "Black Cleaver (HP + AD)"),
        ("6692", "Eclipse (AD; lethality is a passive, not a stat key)"),
        ("3065", "Spirit Visage (MR + HP)"),
        ("3742", "Dead Man's Plate (HP + armor + pct MS)"),
        ("1038", "B.F. Sword (pure-AD component)"),
        ("1054", "Doran's Shield (HP + flat HP regen)"),
        ("223031", "Arena Infinity Edge (22-mirror, own stats)"),
        ("446671", "Galeforce (Arena-only, map 30)"),
    ]

    def _expected_from_source(self, src: dict) -> dict:
        exp: dict[str, float] = {}
        for ddragon_key, value in src.items():
            mapped = ITEM_STAT_KEY_MAP.get(ddragon_key)
            if mapped is None:
                continue
            canonical, kind = mapped
            slot = f"{canonical}_{kind}"
            exp[slot] = exp.get(slot, 0.0) + float(value)
        return exp

    def test_spread_round_trips_bit_exact(self) -> None:
        for item_id, label in self.SPREAD:
            with self.subTest(item=item_id, label=label):
                rec = self.snap.item(item_id)
                src = rec.get("stats") or {}
                self.assertTrue(
                    src, f"{label}: snapshot item {item_id} has no stats block"
                )
                got = aggregate_item_stats([src])
                expected = self._expected_from_source(src)
                self.assertEqual(
                    got,
                    expected,
                    f"{label}: aggregate {got} != source-derived {expected}",
                )

    def test_arena_mirror_keeps_its_own_stats_not_base_id(self) -> None:
        # 223031 is a distinct DDragon entry; engine must use ITS stats,
        # never silently fall back to base 3031. They legitimately differ
        # (Arena IE 55 AD vs SR IE 75 AD) - assert distinctness w/o
        # hardcoding either number.
        base = self.snap.item("3031").get("stats") or {}
        mirror = self.snap.item("223031").get("stats") or {}
        self.assertIn("FlatPhysicalDamageMod", base)
        self.assertIn("FlatPhysicalDamageMod", mirror)
        self.assertNotEqual(
            base["FlatPhysicalDamageMod"],
            mirror["FlatPhysicalDamageMod"],
            "fixture drift: Arena IE should differ from SR IE; if Riot "
            "equalized them this guard is stale, not a bug",
        )
        # Engine aggregate must reflect the mirror's own AD, not the base's.
        agg = aggregate_item_stats([mirror])
        self.assertEqual(agg["ad_flat"], float(mirror["FlatPhysicalDamageMod"]))


class ScorerReachableCoverage(unittest.TestCase):
    """No scorer-reachable item loses a stat DDragon actually defines."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _reachable(self):
        wired_modes = [m for m in MODE_MAP_ID]  # SR, ARAM, ARENA
        for item_id, rec in self.snap.items.items():
            if not _is_purchasable(rec):
                continue
            if any(_is_legal_in_mode(rec, m) for m in wired_modes):
                yield item_id, rec

    def test_some_items_are_reachable(self) -> None:
        # Sanity floor: the filter pipeline must not exclude everything.
        self.assertGreater(sum(1 for _ in self._reachable()), 200)

    def test_no_reachable_item_has_unmapped_stat_key(self) -> None:
        offenders = []
        for item_id, rec in self._reachable():
            for k in (rec.get("stats") or {}):
                if k not in ITEM_STAT_KEY_MAP:
                    offenders.append((item_id, rec.get("name"), k))
        self.assertEqual(
            offenders, [], f"reachable items with silently-zeroed stat: {offenders}"
        )

    def test_no_reachable_item_with_stats_aggregates_to_empty(self) -> None:
        # A non-empty DDragon stats block must never collapse to {} - that
        # would mean the engine sees a fully zero-stat item the shop says
        # has stats.
        offenders = []
        for item_id, rec in self._reachable():
            src = rec.get("stats") or {}
            if src and not aggregate_item_stats([src]):
                offenders.append((item_id, rec.get("name"), src))
        self.assertEqual(
            offenders, [], f"reachable items zeroed by aggregate: {offenders}"
        )


class MerakiSnapshotShape(unittest.TestCase):
    """items_meraki.json is the trimmed prose/shop snapshot, not stats.

    Pins the documented contract so a future extractor change that starts
    (or stops) shipping a field is caught.
    """

    @classmethod
    def setUpClass(cls) -> None:
        snap = DataSnapshot.load()
        path = _DS_DATA / snap.patch / "items_meraki.json"
        cls.doc = json.loads(path.read_text(encoding="utf-8"))
        cls.items = cls.doc.get("items", {})

    def test_top_level_envelope(self) -> None:
        for key in ("fetched_at", "source", "count", "items"):
            self.assertIn(key, self.doc)
        self.assertEqual(self.doc["count"], len(self.items))

    def test_entries_carry_prose_and_shop_not_stat_buckets(self) -> None:
        self.assertTrue(self.items, "items_meraki.json has no items")
        expected_fields = {
            "name",
            "id",
            "tier",
            "rank",
            "removed",
            "simpleDescription",
            "passives",
            "active",
            "shop",
            "noEffects",
        }
        sample_ids = list(self.items)[:50]
        for iid in sample_ids:
            entry = self.items[iid]
            with self.subTest(item=iid):
                self.assertEqual(set(entry.keys()), expected_fields)
                # The trimmed snapshot must NOT carry DDragon-style stat
                # buckets (that's items.json's job).
                self.assertNotIn("stats", entry)

    def test_shop_prices_are_well_formed_when_present(self) -> None:
        for iid, entry in self.items.items():
            shop = entry.get("shop") or {}
            prices = shop.get("prices")
            if not prices:
                continue
            with self.subTest(item=iid):
                self.assertIsInstance(prices.get("total"), (int, float))
                self.assertGreaterEqual(prices.get("total", 0), 0)


if __name__ == "__main__":
    unittest.main()
