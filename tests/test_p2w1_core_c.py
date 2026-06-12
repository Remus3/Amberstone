"""Deep-audit cycle 7 P2 W1 slice C regression tests (core build/DS adjacency).

TDD pins for the slice's FIX-NOW behavior change:

STALE-DATA-PIN fix - the WPA catalog defaults (core.item_wpa /
core.rune_wpa / core.summoner_spell_wpa) resolve the PATCH-CURRENT catalog
instead of a hard-pinned 16.11.1 snapshot. Proven live-stale at audit time:
data/daemon_slayer/current.txt held 16.12.1 while all three modules still
read 16.11.1 files. Worse, lib.ddragon.fetch prunes the meta_build bundle
cache to a current+previous window (item 397), so the pinned rune/summoner
catalogs VANISH one more patch out and those WPA panels would go silently
empty (their loaders fail-soft to {}). The default now follows the live
patch marker (data/daemon_slayer/current.txt for items;
data/meta_build/ddragon/_index.json ``latest_pulled`` for runes/summoners)
and falls back to the pinned snapshot path when the marker or the
patch-current file is absent (fresh checkout) - the pre-fix behavior,
byte-identical.

Explicit ``*_json=`` arguments keep absolute precedence (unchanged API).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import item_wpa, rune_wpa, summoner_spell_wpa

_REPO = Path(__file__).resolve().parent.parent
_DS_CURRENT = _REPO / "data" / "daemon_slayer" / "current.txt"
_DD_INDEX = _REPO / "data" / "meta_build" / "ddragon" / "_index.json"


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class ItemWpaDefaultCatalogTests(unittest.TestCase):
    """core.item_wpa default catalog follows data/daemon_slayer/current.txt."""

    def test_default_tracks_current_txt(self):
        with tempfile.TemporaryDirectory() as td:
            ds = Path(td) / "daemon_slayer"
            ds.mkdir(parents=True)
            (ds / "current.txt").write_text("9.9.9\n", encoding="utf-8")
            cand = ds / "9.9.9" / "items.json"
            _write(cand, {"data": {}})
            with mock.patch.object(item_wpa, "_DS_DIR", ds):
                self.assertEqual(item_wpa._default_items_json(), cand)

    def test_default_falls_back_without_current_txt(self):
        with tempfile.TemporaryDirectory() as td:
            ds = Path(td) / "daemon_slayer"
            ds.mkdir(parents=True)
            with mock.patch.object(item_wpa, "_DS_DIR", ds):
                self.assertEqual(
                    item_wpa._default_items_json(), item_wpa._ITEMS_JSON
                )

    def test_default_falls_back_when_patch_catalog_absent(self):
        with tempfile.TemporaryDirectory() as td:
            ds = Path(td) / "daemon_slayer"
            ds.mkdir(parents=True)
            (ds / "current.txt").write_text("9.9.9", encoding="utf-8")
            with mock.patch.object(item_wpa, "_DS_DIR", ds):
                self.assertEqual(
                    item_wpa._default_items_json(), item_wpa._ITEMS_JSON
                )

    def test_explicit_arg_still_wins(self):
        with tempfile.TemporaryDirectory() as td:
            cat = Path(td) / "items.json"
            _write(cat, {"data": {
                "9001": {
                    "name": "Audit Blade",
                    "gold": {"purchasable": True, "total": 3000},
                    "tags": [],
                    "from": ["1038"],
                    "maps": {"11": True},
                },
            }})
            self.assertEqual(
                item_wpa.load_legendary_ids(cat), {9001: "Audit Blade"}
            )


class RuneWpaDefaultCatalogTests(unittest.TestCase):
    """core.rune_wpa default catalog follows _index.json latest_pulled."""

    def test_default_tracks_index_latest_pulled(self):
        with tempfile.TemporaryDirectory() as td:
            dd = Path(td) / "ddragon"
            _write(dd / "_index.json", {"latest_pulled": "9.9.9"})
            cand = dd / "9.9.9" / "runesReforged.json"
            _write(cand, [])
            with mock.patch.object(rune_wpa, "_DDRAGON_DIR", dd):
                self.assertEqual(rune_wpa._default_runes_json(), cand)

    def test_default_falls_back_without_index(self):
        with tempfile.TemporaryDirectory() as td:
            dd = Path(td) / "ddragon"
            dd.mkdir(parents=True)
            with mock.patch.object(rune_wpa, "_DDRAGON_DIR", dd):
                self.assertEqual(
                    rune_wpa._default_runes_json(), rune_wpa._RUNES_JSON
                )

    def test_default_falls_back_when_bundle_absent(self):
        with tempfile.TemporaryDirectory() as td:
            dd = Path(td) / "ddragon"
            _write(dd / "_index.json", {"latest_pulled": "9.9.9"})
            with mock.patch.object(rune_wpa, "_DDRAGON_DIR", dd):
                self.assertEqual(
                    rune_wpa._default_runes_json(), rune_wpa._RUNES_JSON
                )

    def test_default_falls_back_on_malformed_index(self):
        with tempfile.TemporaryDirectory() as td:
            dd = Path(td) / "ddragon"
            dd.mkdir(parents=True)
            (dd / "_index.json").write_text("{not json", encoding="utf-8")
            with mock.patch.object(rune_wpa, "_DDRAGON_DIR", dd):
                self.assertEqual(
                    rune_wpa._default_runes_json(), rune_wpa._RUNES_JSON
                )


class SummonerSpellWpaDefaultCatalogTests(unittest.TestCase):
    """core.summoner_spell_wpa default catalog follows _index.json."""

    def test_default_tracks_index_latest_pulled(self):
        with tempfile.TemporaryDirectory() as td:
            dd = Path(td) / "ddragon"
            _write(dd / "_index.json", {"latest_pulled": "9.9.9"})
            cand = dd / "9.9.9" / "summoner.json"
            _write(cand, {"data": {}})
            with mock.patch.object(summoner_spell_wpa, "_DDRAGON_DIR", dd):
                self.assertEqual(
                    summoner_spell_wpa._default_summoner_json(), cand
                )

    def test_default_falls_back_without_index(self):
        with tempfile.TemporaryDirectory() as td:
            dd = Path(td) / "ddragon"
            dd.mkdir(parents=True)
            with mock.patch.object(summoner_spell_wpa, "_DDRAGON_DIR", dd):
                self.assertEqual(
                    summoner_spell_wpa._default_summoner_json(),
                    summoner_spell_wpa._SUMMONER_JSON,
                )

    def test_default_falls_back_when_bundle_absent(self):
        with tempfile.TemporaryDirectory() as td:
            dd = Path(td) / "ddragon"
            _write(dd / "_index.json", {"latest_pulled": "9.9.9"})
            with mock.patch.object(summoner_spell_wpa, "_DDRAGON_DIR", dd):
                self.assertEqual(
                    summoner_spell_wpa._default_summoner_json(),
                    summoner_spell_wpa._SUMMONER_JSON,
                )


class LiveRepoCatalogTests(unittest.TestCase):
    """The defaults track the LIVE patch markers in this checkout - the audit
    finding was a 16.11.1 pin while current.txt said 16.12.1. These guards
    skip (not fail) when the tracked data files are absent."""

    def test_item_default_is_current_patch(self):
        if not _DS_CURRENT.is_file():
            self.skipTest("daemon_slayer/current.txt absent")
        patch = _DS_CURRENT.read_text(encoding="utf-8").strip()
        if not (_REPO / "data" / "daemon_slayer" / patch / "items.json").is_file():
            self.skipTest("patch-current items.json absent")
        self.assertEqual(item_wpa._default_items_json().parts[-2], patch)

    def test_rune_default_is_latest_pulled(self):
        if not _DD_INDEX.is_file():
            self.skipTest("meta_build ddragon _index.json absent")
        ver = str(json.loads(_DD_INDEX.read_text(encoding="utf-8")).get(
            "latest_pulled") or "").strip()
        bundle = _REPO / "data" / "meta_build" / "ddragon" / ver
        if not ver or not (bundle / "runesReforged.json").is_file():
            self.skipTest("latest_pulled runes bundle absent")
        self.assertEqual(rune_wpa._default_runes_json().parts[-2], ver)
        # And the catalog actually parses non-empty at that path.
        self.assertTrue(rune_wpa.load_rune_catalog())

    def test_summoner_default_is_latest_pulled(self):
        if not _DD_INDEX.is_file():
            self.skipTest("meta_build ddragon _index.json absent")
        ver = str(json.loads(_DD_INDEX.read_text(encoding="utf-8")).get(
            "latest_pulled") or "").strip()
        bundle = _REPO / "data" / "meta_build" / "ddragon" / ver
        if not ver or not (bundle / "summoner.json").is_file():
            self.skipTest("latest_pulled summoner bundle absent")
        self.assertEqual(
            summoner_spell_wpa._default_summoner_json().parts[-2], ver
        )
        self.assertTrue(summoner_spell_wpa.load_spell_catalog())


if __name__ == "__main__":
    unittest.main()
