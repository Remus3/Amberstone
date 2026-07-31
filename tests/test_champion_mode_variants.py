"""Guard: DDragon THROWBACK-MODE rows stay OUT of the engine registries.

DDragon 16.15.1 shipped a parallel legacy-mode registry beside the live one:

* 60 ``Jade_<Champion>`` rows at ``base_key + 60000``, taking
  ``data/meta/ddragon_champions.json`` from 173 to 233 entries. They are NOT
  aliases - each carries its own (older-patch) stat line, Jade_Ahri hp 460/+80
  against Ahri 590/+104 - and Meraki 404s all 60, so they have no ability
  formulas, no wiki sidecar, no archetype pick and no build order.
* 162 items in ``[770000, 780000)``, a keyspace absent from 16.14.1 entirely.
  Mirrors sit at ``base_id + 770000``; the rest are RETIRED items (Sightstone,
  Zz'Rot Portal, Hex Core mk-1, Eggnog).

The item half is the sharp one: most of the band flags ``maps["12"]``, and RC
models ARAM on map 12, so admitting it takes the map-12-legal pool from 251 to
403 with 95 base/mirror duplicates. A normal ARAM game does not sell Elixir of
Agility.

Policy: partition at every PRODUCER, so no consumer needs to know.

1. ``scripts/data_pipeline`` drops the rows on download, so ``data/meta/*`` -
   RC's live-roster cache, read by ~15 modules that treat it as "what is in
   play" - is correct without touching any of them.
2. ``tools/daemon_slayer_extract`` drops them from the DS snapshot, which keeps
   every patch dir the same shape and keeps the ~20 DS test helpers that read
   ``items.json`` raw and sweep it by id SUFFIX honest.
3. ``DataSnapshot.load`` and ``core.build_order_precompute.full_roster``
   partition again at load - belt and braces for a snapshot extracted before
   this policy existed.

The FAITHFUL upstream copy lives at ``data/meta_build/ddragon/<patch>/``, so
nothing is lost - and that is what these tests read as their source.

Filtering restores exactly the 16.14.1 shape - 173 champions, 706 items - which
is the measurement saying 16.15.1 added no canonical content on either axis.
Revisit when a throwback mode is wired into mode detection; the live Flash row
already advertises a ``KIWI_JADE`` mode, so an ARAM-Mayhem-Jade variant is the
likely first contact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.daemon_slayer.mode_variants import (
    VARIANT_CHAMPION_KEY_FLOOR,
    VARIANT_ITEM_ID_RANGE,
    canonical_champions,
    canonical_items,
    is_mode_variant_champion,
    is_mode_variant_item,
)

_ROOT = Path(__file__).resolve().parent.parent
# RC's LIVE-ROSTER cache - filtered by scripts/data_pipeline on download.
_LIVE = _ROOT / "data" / "meta" / "ddragon_champions.json"


def _patch() -> str:
    return (_ROOT / "data" / "daemon_slayer" / "current.txt").read_text(
        encoding="utf-8"
    ).strip()


def _upstream_rows(bundle: str) -> dict:
    """The FAITHFUL upstream copy kept by tools/ddragon_mirror_refresh.py."""
    path = _ROOT / "data" / "meta_build" / "ddragon" / _patch() / bundle
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _live_rows() -> dict:
    return json.loads(_LIVE.read_text(encoding="utf-8"))["data"]


def _snapshot_items_on_disk() -> dict:
    path = _ROOT / "data" / "daemon_slayer" / _patch() / "items.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


class TestUpstreamIsTheSource:
    """Source-read pins against the FAITHFUL upstream bundle: prove the input
    the filter is filtering, and prove the filtered view is filtered."""

    def test_upstream_ships_both_the_base_and_the_variant_row(self):
        rows = _upstream_rows("champion.json")
        assert "Ahri" in rows, "canonical Ahri missing from the upstream bundle"
        assert "Jade_Ahri" in rows, (
            "Jade_Ahri missing upstream - if DDragon dropped the throwback rows "
            "this whole guard is moot; re-measure before deleting it"
        )

    def test_live_cache_is_the_filtered_view(self):
        live = _live_rows()
        assert "Ahri" in live
        assert [k for k in live if k.startswith("Jade_")] == [], (
            "throwback rows reached data/meta - ~15 modules read this file as "
            "the live roster; re-run scripts/data_pipeline.py cmd_ddragon"
        )

    def test_live_item_cache_is_the_filtered_view(self):
        doc = json.loads(
            (_ROOT / "data" / "meta" / "ddragon_items.json").read_text(
                encoding="utf-8"
            )
        )
        rows = doc.get("data", doc)
        assert [i for i in rows if is_mode_variant_item(i)] == []

    def test_variant_row_is_not_an_alias_of_the_base_row(self):
        rows = _upstream_rows("champion.json")
        base, variant = rows["Ahri"], rows["Jade_Ahri"]
        assert variant["name"] == base["name"], "variant should share the display name"
        assert int(variant["key"]) == int(base["key"]) + VARIANT_CHAMPION_KEY_FLOOR
        assert variant["stats"]["hp"] != base["stats"]["hp"], (
            "variant carries its OWN stat line - if these ever match, the rows "
            "really are aliases and the dedup story changes"
        )

    def test_every_variant_key_sits_above_the_floor_and_no_base_key_does(self):
        rows = _upstream_rows("champion.json")
        variant_keys = [int(v["key"]) for k, v in rows.items() if k.startswith("Jade_")]
        base_keys = [int(v["key"]) for k, v in rows.items() if not k.startswith("Jade_")]
        assert variant_keys, "no Jade_ rows found in the mirror"
        assert min(variant_keys) >= VARIANT_CHAMPION_KEY_FLOOR
        assert max(base_keys) < VARIANT_CHAMPION_KEY_FLOOR, (
            "a canonical champion key crossed the variant floor - the key-based "
            "partition is no longer safe and must be re-derived"
        )

    def test_snapshot_on_disk_is_already_canonical(self):
        """The extract partitions, so the snapshot matches every historical dir.

        This is deliberately NOT a load-only policy: ~20 DS test helpers read
        ``items.json`` raw and sweep it by id SUFFIX, so a band left on disk
        makes 773131 a phantom sibling of Sword of the Divine everywhere.
        """
        low, high = VARIANT_ITEM_ID_RANGE
        band = [i for i in _snapshot_items_on_disk() if low <= int(i) < high]
        assert band == [], f"throwback band reached the snapshot: {band[:5]}"


class TestPredicates:
    """Champions partition on the KEY; items partition on a CLOSED id band."""

    def test_key_above_floor_is_a_variant_whatever_the_id(self):
        assert is_mode_variant_champion("Foo", {"id": "Foo", "key": "60999"}) is True

    def test_champion_name_prefix_alone_does_not_drop_a_row(self):
        assert is_mode_variant_champion("Jade_Foo", {"id": "Jade_Foo", "key": "7"}) is False

    def test_unparseable_champion_key_is_kept(self):
        # Fail-safe: never drop a row we cannot classify.
        assert is_mode_variant_champion("Foo", {}) is False
        assert is_mode_variant_champion("Foo", {"key": "abc"}) is False

    def test_item_band_is_closed_at_both_ends(self):
        assert is_mode_variant_item(771001) is True
        assert is_mode_variant_item("773521") is True
        # 220000 Arena mirrors below the band and 994403 above it must survive.
        assert is_mode_variant_item(223072) is False
        assert is_mode_variant_item(994403) is False
        assert is_mode_variant_item(769999) is False
        assert is_mode_variant_item(780000) is False

    def test_unparseable_item_id_is_kept(self):
        assert is_mode_variant_item(None) is False
        assert is_mode_variant_item("boots") is False

    def test_canonical_champions_drops_only_the_variants(self):
        rows = _upstream_rows("champion.json")
        kept = canonical_champions(rows)
        assert len(kept) == len(rows) - 60
        assert "Ahri" in kept and "Jade_Ahri" not in kept

    def test_canonical_items_drops_only_the_band(self):
        rows = _upstream_rows("item.json")
        kept = canonical_items(rows)
        assert len(kept) == len(rows) - 162
        assert "1001" in kept and "771001" not in kept


class TestEngineRegistries:
    """What the scorers and the HZ tables actually see."""

    def test_snapshot_roster_excludes_variants(self):
        from agents.daemon_slayer.data_loader import DataSnapshot

        champs = DataSnapshot.load().champions
        offenders = [k for k, v in champs.items() if is_mode_variant_champion(k, v)]
        assert offenders == [], f"throwback champions leaked: {offenders}"
        assert "Ahri" in champs

    def test_snapshot_items_exclude_the_band(self):
        from agents.daemon_slayer.data_loader import DataSnapshot

        items = DataSnapshot.load().items
        offenders = [i for i in items if is_mode_variant_item(i)]
        assert offenders == [], f"throwback items leaked: {offenders}"
        assert "1001" in items

    def test_aram_legal_pool_has_no_base_mirror_duplicates(self):
        """The reason the item half matters: RC models ARAM on map 12."""
        from agents.daemon_slayer.data_loader import DataSnapshot

        items = DataSnapshot.load().items
        low, _ = VARIANT_ITEM_ID_RANGE
        aram = [i for i, v in items.items() if (v.get("maps") or {}).get("12")]
        dupes = [i for i in aram if str(int(i) + low) in items]
        assert dupes == [], f"map-12 pool carries mirror duplicates: {dupes}"

    def test_shipped_pickban_table_excludes_variants(self):
        """The generator has its OWN roster derivation reading the snapshot
        raw. Unfixed it shipped 233 rows whose every pair failed to score."""
        path = _ROOT / "data" / "daemon_slayer" / _patch() / "pickban_targets.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        rows = doc["targets"]
        assert [c for c in rows if str(c).startswith("Jade_")] == []
        assert "Ahri" in rows
        assert len(rows) == 173

    def test_full_roster_excludes_variants(self):
        from core.build_order_precompute import full_roster

        ids = full_roster()
        assert [i for i in ids if i.startswith("Jade_")] == []
        assert "Ahri" in ids

    def test_registry_size_pins(self):
        """Characterization pins. A real content change (new champion, new item)
        legitimately moves these - update them from the mirror, do not delete
        the pins."""
        from agents.daemon_slayer.data_loader import DataSnapshot
        from core.build_order_precompute import full_roster

        snap = DataSnapshot.load()
        assert len(full_roster()) == 173
        assert len(snap.champions) == 173
        assert len(snap.items) == 706


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
