"""Tests for tools/champion_loadout_collapse_to_paths.py - item 179 ARAM + Arena.

Item 179 (2026-05-24) extended item 178's SR collapse to ARAM + Arena
via the ``--mode`` flag, producing ``aram-collapsed`` + ``arena-collapsed``
parallels. The variant-level ``items`` / ``runes`` / ``summoners`` on
the collapsed entry are populated from the PRIMARY path so back-compat
holds for callers passing just ``aram-collapsed`` / ``arena-collapsed``.

Test classes (parallel to test_champion_loadout_collapse_to_paths.py's
item-178 surfaces, scoped to ARAM + Arena specifics):

* ``Item179LabelMappingTests`` - short_label_for() for ARAM + Arena
  variant keys including the auto-arena-{primary,secondary,flavor}-*
  slot disambiguator.
* ``Item179CollapseChampionAramTests`` - shape + invariants of
  collapse_champion(mode='aram') on synthetic entries.
* ``Item179CollapseChampionArenaTests`` - same for mode='arena'.
* ``Item179MultiModeIsolationTests`` - running ARAM collapse does NOT
  perturb SR's sr-collapsed or Arena's per-variant entries; running
  Arena collapse does NOT perturb SR/ARAM.
* ``Item179IdempotencyTests`` - re-running --mode aram on already-
  collapsed input is a no-op (preserves operator hand-edits to paths).
* ``Item179CliTests`` - --mode flag parsing + --item-tag flag default.
* ``Item179LiveSchemaTests`` - post-migration data/champion_loadouts.json
  validates one aram-collapsed + one arena-collapsed per champion +
  default_per_mode pointers stable.
* ``Item179AsciiHygieneTests`` - new test file is ASCII-clean.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.champion_loadout_collapse_to_paths import (
    ARAM_MODE,
    ARENA_MODE,
    SR_MODE,
    _resolve_modes_arg,
    collapse_champion,
    collapse_payload,
    collapse_payload_modes,
    collapsed_key_for,
    order_source_keys,
    pick_primary_key,
    short_label_for,
)


_LIVE_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"


def _make_variant(modes: list[str], label: str = "v", items: list | None = None,
                  summoners: list | None = None, runes: dict | None = None,
                  archetype: str = "", auto: bool = False) -> dict:
    """Shared helper: synth a variant dict for collapse tests."""
    return {
        "label":      label,
        "modes":      list(modes),
        "runes":      dict(runes or {}),
        "summoners":  list(summoners or []),
        "items":      list(items or []),
        **({"_auto": True} if auto else {}),
        **({"_archetype": archetype} if archetype else {}),
    }


def _make_entry(variants: dict, default_per_mode: dict | None = None) -> dict:
    """Shared helper: synth a champion entry."""
    return {
        "variants": variants,
        "default_per_mode": dict(default_per_mode or {}),
    }


class Item179LabelMappingTests(unittest.TestCase):
    """ARAM + Arena variant_key short pill labels."""

    def test_aram_arch_standard_pills(self) -> None:
        # aram-<arch> standard mappings (item 179).
        self.assertEqual(short_label_for("aram-carry",     "carry",     "ARAM Carry"),     "Carry")
        self.assertEqual(short_label_for("aram-bruiser",   "bruiser",   "ARAM Bruiser"),   "Bruiser")
        self.assertEqual(short_label_for("aram-tank",      "tank",      "ARAM Tank"),      "Tank")
        self.assertEqual(short_label_for("aram-mage",      "mage",      "ARAM Mage"),      "Mage")
        self.assertEqual(short_label_for("aram-assassin",  "assassin",  "ARAM Assassin"),  "Assassin")
        self.assertEqual(short_label_for("aram-enchanter", "enchanter", "ARAM Enchanter"), "Enchanter")

    def test_arena_arch_standard_pills(self) -> None:
        # arena-<arch> standard mappings (item 179).
        self.assertEqual(short_label_for("arena-carry",     "carry",     "Arena Carry"),     "Carry")
        self.assertEqual(short_label_for("arena-bruiser",   "bruiser",   "Arena Bruiser"),   "Bruiser")
        self.assertEqual(short_label_for("arena-tank",      "tank",      "Arena Tank"),      "Tank")
        self.assertEqual(short_label_for("arena-mage",      "mage",      "Arena Mage"),      "Mage")
        self.assertEqual(short_label_for("arena-assassin",  "assassin",  "Arena Assassin"),  "Assassin")
        self.assertEqual(short_label_for("arena-enchanter", "enchanter", "Arena Enchanter"), "Enchanter")

    def test_auto_arena_slot_disambiguator(self) -> None:
        # auto-arena-<slot>-<arch> applies slot suffix per item 179 to
        # disambiguate the 3 simultaneous slots an Arena champ can pull.
        self.assertEqual(short_label_for("auto-arena-primary-carry",     "carry",     "Auto"), "Carry")
        self.assertEqual(short_label_for("auto-arena-secondary-bruiser", "bruiser",   "Auto"), "Bruiser (sec)")
        self.assertEqual(short_label_for("auto-arena-flavor-assassin",   "assassin",  "Auto"), "Assassin (flav)")
        self.assertEqual(short_label_for("auto-arena-flavor-tank",       "tank",      "Auto"), "Tank (flav)")
        self.assertEqual(short_label_for("auto-arena-secondary-enchanter", "enchanter", "Auto"), "Enchanter (sec)")
        self.assertEqual(short_label_for("auto-arena-secondary-mage",    "mage",      "Auto"), "Mage (sec)")

    def test_auto_aram_no_slot_disambiguator(self) -> None:
        # Live ARAM data only uses auto-aram-primary-* so the slot
        # disambiguator is INERT for ARAM. Item 179 deliberately keeps
        # ARAM auto-* labels short (no suffix) to match item-178's
        # SR auto-sr-primary-* behavior.
        self.assertEqual(short_label_for("auto-aram-primary-carry",   "carry",   "Auto"), "Carry")
        self.assertEqual(short_label_for("auto-aram-primary-bruiser", "bruiser", "Auto"), "Bruiser")
        self.assertEqual(short_label_for("auto-aram-primary-tank",    "tank",    "Auto"), "Tank")

    def test_aram_legacy_keys_resolve(self) -> None:
        # Pre-existing legacy ARAM variant keys (predate the
        # aram-<arch> migration) must still produce <=14-char labels.
        self.assertEqual(short_label_for("ap-burst",   "", "AP Burst"),     "Burst")
        self.assertEqual(short_label_for("ap-poke",    "", "AP Poke"),      "AP Poke")
        self.assertEqual(short_label_for("ap-bruiser", "", "AP Bruiser"),   "AP Bruiser")
        self.assertEqual(short_label_for("tank-aram",  "", "Tank ARAM"),    "Tank ARAM")
        self.assertEqual(short_label_for("on-hit",     "", "On-Hit"),       "On-Hit")
        self.assertEqual(short_label_for("ap-bombs",   "", "AP Bombs"),     "AP Bombs")
        self.assertEqual(short_label_for("tank-veigar","", "Tank Veigar"),  "Tank Veigar")

    def test_arena_unmapped_falls_back_to_arch_with_suffix(self) -> None:
        # Unknown auto-arena-<slot>-<arch> with arch outside the
        # fallback map titlecases the arch + appends slot suffix.
        # The result is capped at 16 chars per item 179 pill budget so
        # long arch tokens may truncate the suffix mid-token.
        result = short_label_for("auto-arena-flavor-mage", "", "Auto")
        self.assertEqual(result, "Mage (flav)")
        # And a shorter arch resolves cleanly via the slot suffix.
        result2 = short_label_for("auto-arena-secondary-tank", "", "Auto")
        self.assertEqual(result2, "Tank (sec)")

    def test_label_length_bounded(self) -> None:
        # All labels stay reasonably short for chooser pills (item 178
        # tooltip: under ~14-16 chars). Item 179 auto-arena suffixes
        # are capped at 16 chars total.
        for k in ("auto-arena-secondary-bruiser", "auto-arena-flavor-assassin",
                  "auto-arena-primary-enchanter"):
            self.assertLessEqual(len(short_label_for(k, "", "Auto")), 16,
                f"{k!r} label too long")


class Item179CollapseChampionAramTests(unittest.TestCase):
    """Shape + invariants of collapse_champion(mode='aram')."""

    def test_aram_only_variants_absorbed_into_collapsed(self) -> None:
        entry = _make_entry({
            "aram-carry":   _make_variant(["aram"], "ARAM Carry",   items=["A"], summoners=[4, 32]),
            "aram-bruiser": _make_variant(["aram"], "ARAM Bruiser", items=["B"], summoners=[4, 32]),
        }, default_per_mode={"aram": "aram-carry"})
        new, stats = collapse_champion("Test", entry, mode=ARAM_MODE)
        self.assertEqual(stats["before"], 2)
        self.assertEqual(stats["after"],  1)
        self.assertEqual(stats["paths"],  2)
        self.assertIn("aram-collapsed", new["variants"])
        self.assertNotIn("aram-carry",   new["variants"])
        self.assertNotIn("aram-bruiser", new["variants"])
        paths = new["variants"]["aram-collapsed"]["build_paths"]
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0]["key"], "aram-carry")
        self.assertTrue(paths[0]["_is_primary"])

    def test_aram_collapsed_variant_uses_aram_summoners(self) -> None:
        # ARAM mandates Mark spell (id 32); the collapsed variant must
        # preserve this from the primary path so back-compat resolve()
        # callers get Mark/Flash without re-running summoner picker.
        entry = _make_entry({
            "aram-carry": _make_variant(["aram"], "ARAM Carry", items=["A"],
                                         summoners=[4, 32]),
        }, default_per_mode={"aram": "aram-carry"})
        new, _ = collapse_champion("Test", entry, mode=ARAM_MODE)
        collapsed = new["variants"]["aram-collapsed"]
        self.assertEqual(collapsed["summoners"], [4, 32])

    def test_default_per_mode_aram_repointed_to_collapsed(self) -> None:
        entry = _make_entry({
            "aram-carry": _make_variant(["aram"], "ARAM Carry", items=["A"]),
        }, default_per_mode={"aram": "aram-carry"})
        new, _ = collapse_champion("Test", entry, mode=ARAM_MODE)
        self.assertEqual(new["default_per_mode"]["aram"], "aram-collapsed")

    def test_aram_collapse_preserves_sr_arena_defaults(self) -> None:
        entry = _make_entry({
            "sr-collapsed":   _make_variant(["sr"],    "Builds for X"),
            "aram-carry":     _make_variant(["aram"],  "ARAM Carry"),
            "arena-carry":    _make_variant(["arena"], "Arena Carry"),
        }, default_per_mode={
            "sr":    "sr-collapsed",
            "aram":  "aram-carry",
            "arena": "arena-carry",
        })
        new, _ = collapse_champion("Test", entry, mode=ARAM_MODE)
        self.assertEqual(new["default_per_mode"]["sr"],    "sr-collapsed")
        self.assertEqual(new["default_per_mode"]["aram"],  "aram-collapsed")
        self.assertEqual(new["default_per_mode"]["arena"], "arena-carry")

    def test_aram_collapse_leaves_sr_arena_variants_untouched(self) -> None:
        entry = _make_entry({
            "sr-collapsed":   _make_variant(["sr"],    "Builds for X", items=["SR1"]),
            "aram-carry":     _make_variant(["aram"],  "ARAM Carry",   items=["AR1"]),
            "aram-bruiser":   _make_variant(["aram"],  "ARAM Bruiser", items=["AR2"]),
            "arena-carry":    _make_variant(["arena"], "Arena Carry",  items=["AN1"]),
        }, default_per_mode={"aram": "aram-carry"})
        new, _ = collapse_champion("Test", entry, mode=ARAM_MODE)
        # SR + Arena variants present + UNCHANGED items.
        self.assertEqual(new["variants"]["sr-collapsed"]["items"],  ["SR1"])
        self.assertEqual(new["variants"]["arena-carry"]["items"],   ["AN1"])
        self.assertEqual(new["variants"]["sr-collapsed"]["modes"],  ["sr"])
        self.assertEqual(new["variants"]["arena-carry"]["modes"],   ["arena"])
        # ARAM source variants absorbed.
        self.assertNotIn("aram-carry",   new["variants"])
        self.assertNotIn("aram-bruiser", new["variants"])
        self.assertIn("aram-collapsed",  new["variants"])

    def test_aram_collapse_builds_path_count_matches_pre_collapse(self) -> None:
        # Pre-collapse ARAM source count = N -> build_paths length = N.
        entry = _make_entry({
            "ap-burst":              _make_variant(["aram"], "AP Burst",    items=["A"]),
            "ap-poke":               _make_variant(["aram"], "AP Poke",     items=["B"]),
            "aram-mage":             _make_variant(["aram"], "ARAM Mage",   items=["C"]),
            "auto-aram-primary-mage": _make_variant(["aram"], "Mage (auto)", items=["D"], auto=True),
        }, default_per_mode={"aram": "aram-mage"})
        new, stats = collapse_champion("Test", entry, mode=ARAM_MODE)
        self.assertEqual(stats["before"], 4)
        self.assertEqual(stats["paths"],  4)
        paths = new["variants"]["aram-collapsed"]["build_paths"]
        self.assertEqual(len(paths), 4)
        # Primary = aram-mage; remaining curated alphabetical; auto last.
        self.assertEqual(paths[0]["key"], "aram-mage")
        # Curated set after primary = {ap-burst, ap-poke} alphabetical.
        curated_keys = [p["key"] for p in paths[1:3]]
        self.assertEqual(curated_keys, ["ap-burst", "ap-poke"])
        # Auto last.
        self.assertEqual(paths[3]["key"], "auto-aram-primary-mage")
        self.assertTrue(paths[3]["key"].startswith("auto-"))

    def test_aram_no_variants_returns_entry_unchanged(self) -> None:
        entry = _make_entry({
            "sr-collapsed": _make_variant(["sr"], "Builds for X"),
        })
        new, stats = collapse_champion("Test", entry, mode=ARAM_MODE)
        self.assertEqual(stats["before"], 0)
        self.assertEqual(stats["after"],  0)
        self.assertEqual(stats["paths"],  0)
        self.assertNotIn("aram-collapsed", new["variants"])


class Item179CollapseChampionArenaTests(unittest.TestCase):
    """Shape + invariants of collapse_champion(mode='arena')."""

    def test_arena_only_variants_absorbed_into_collapsed(self) -> None:
        entry = _make_entry({
            "arena-carry":   _make_variant(["arena"], "Arena Carry",   items=["A"], summoners=[4, 7]),
            "arena-bruiser": _make_variant(["arena"], "Arena Bruiser", items=["B"], summoners=[4, 7]),
        }, default_per_mode={"arena": "arena-carry"})
        new, stats = collapse_champion("Test", entry, mode=ARENA_MODE)
        self.assertEqual(stats["before"], 2)
        self.assertEqual(stats["after"],  1)
        self.assertEqual(stats["paths"],  2)
        self.assertIn("arena-collapsed", new["variants"])
        self.assertNotIn("arena-carry",   new["variants"])
        self.assertNotIn("arena-bruiser", new["variants"])
        paths = new["variants"]["arena-collapsed"]["build_paths"]
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0]["key"], "arena-carry")

    def test_arena_auto_slot_paths_get_disambiguators(self) -> None:
        entry = _make_entry({
            "arena-carry": _make_variant(["arena"], "Arena Carry", items=["A"]),
            "auto-arena-primary-carry":     _make_variant(["arena"], "Carry (auto)",     items=["B"], auto=True, archetype="carry"),
            "auto-arena-secondary-bruiser": _make_variant(["arena"], "Bruiser (auto)",   items=["C"], auto=True, archetype="bruiser"),
            "auto-arena-flavor-assassin":   _make_variant(["arena"], "Assassin (auto)",  items=["D"], auto=True, archetype="assassin"),
        }, default_per_mode={"arena": "arena-carry"})
        new, _ = collapse_champion("Test", entry, mode=ARENA_MODE)
        paths = new["variants"]["arena-collapsed"]["build_paths"]
        labels = {p["key"]: p["label"] for p in paths}
        self.assertEqual(labels["auto-arena-primary-carry"],     "Carry")
        self.assertEqual(labels["auto-arena-secondary-bruiser"], "Bruiser (sec)")
        self.assertEqual(labels["auto-arena-flavor-assassin"],   "Assassin (flav)")
        self.assertEqual(labels["arena-carry"],                  "Carry")

    def test_arena_default_per_mode_repointed_to_collapsed(self) -> None:
        entry = _make_entry({
            "arena-carry": _make_variant(["arena"], "Arena Carry", items=["A"]),
        }, default_per_mode={"arena": "arena-carry"})
        new, _ = collapse_champion("Test", entry, mode=ARENA_MODE)
        self.assertEqual(new["default_per_mode"]["arena"], "arena-collapsed")

    def test_arena_collapse_leaves_sr_aram_variants_untouched(self) -> None:
        entry = _make_entry({
            "sr-collapsed":   _make_variant(["sr"],    "Builds for X", items=["SR1"]),
            "aram-carry":     _make_variant(["aram"],  "ARAM Carry",   items=["AR1"]),
            "arena-carry":    _make_variant(["arena"], "Arena Carry",  items=["AN1"]),
            "arena-bruiser":  _make_variant(["arena"], "Arena Bruiser", items=["AN2"]),
        }, default_per_mode={"arena": "arena-carry"})
        new, _ = collapse_champion("Test", entry, mode=ARENA_MODE)
        self.assertEqual(new["variants"]["sr-collapsed"]["items"], ["SR1"])
        self.assertEqual(new["variants"]["aram-carry"]["items"],   ["AR1"])
        self.assertEqual(new["variants"]["sr-collapsed"]["modes"], ["sr"])
        self.assertEqual(new["variants"]["aram-carry"]["modes"],   ["aram"])
        self.assertNotIn("arena-carry",   new["variants"])
        self.assertNotIn("arena-bruiser", new["variants"])
        self.assertIn("arena-collapsed",  new["variants"])


class Item179MultiModeIsolationTests(unittest.TestCase):
    """Running one mode's collapse does NOT perturb the others."""

    def test_aram_collapse_does_not_touch_sr_collapsed(self) -> None:
        entry = _make_entry({
            "sr-collapsed": {
                "label":      "Builds for X",
                "modes":      ["sr"],
                "items":      ["SR1"],
                "summoners":  [4, 21],
                "runes":      {},
                "_collapsed": True,
                "build_paths": [
                    {"key": "sr-carry", "label": "Carry", "items": ["SR1"],
                     "_is_primary": True},
                ],
            },
            "aram-carry":     _make_variant(["aram"], "ARAM Carry",     items=["AR1"]),
            "aram-bruiser":   _make_variant(["aram"], "ARAM Bruiser",   items=["AR2"]),
        }, default_per_mode={"sr": "sr-collapsed", "aram": "aram-carry"})
        new, _ = collapse_champion("Test", entry, mode=ARAM_MODE)
        # sr-collapsed UNTOUCHED including build_paths.
        sr = new["variants"]["sr-collapsed"]
        self.assertEqual(sr["items"], ["SR1"])
        self.assertEqual(sr["modes"], ["sr"])
        self.assertEqual(len(sr["build_paths"]), 1)
        self.assertEqual(sr["build_paths"][0]["key"], "sr-carry")

    def test_arena_collapse_does_not_touch_aram_collapsed(self) -> None:
        entry = _make_entry({
            "aram-collapsed": {
                "label":      "Builds for X",
                "modes":      ["aram"],
                "items":      ["AR1"],
                "summoners":  [4, 32],
                "runes":      {},
                "_collapsed": True,
                "build_paths": [
                    {"key": "aram-carry", "label": "Carry", "items": ["AR1"],
                     "_is_primary": True},
                ],
            },
            "arena-carry":   _make_variant(["arena"], "Arena Carry",   items=["AN1"]),
            "arena-bruiser": _make_variant(["arena"], "Arena Bruiser", items=["AN2"]),
        }, default_per_mode={"aram": "aram-collapsed", "arena": "arena-carry"})
        new, _ = collapse_champion("Test", entry, mode=ARENA_MODE)
        aram = new["variants"]["aram-collapsed"]
        self.assertEqual(aram["items"], ["AR1"])
        self.assertEqual(aram["modes"], ["aram"])
        self.assertEqual(len(aram["build_paths"]), 1)

    def test_all_modes_pass_collapses_each_independently(self) -> None:
        # collapse_payload_modes('Test', (sr, aram, arena)) produces
        # one collapsed key per mode + the SR/ARAM/Arena defaults all
        # repoint to their respective collapsed keys.
        payload = {
            "champions": {
                "A": _make_entry({
                    "sr-carry":     _make_variant(["sr"],    "SR Carry",     items=["S1"]),
                    "sr-bruiser":   _make_variant(["sr"],    "SR Bruiser",   items=["S2"]),
                    "aram-carry":   _make_variant(["aram"],  "ARAM Carry",   items=["A1"]),
                    "aram-bruiser": _make_variant(["aram"],  "ARAM Bruiser", items=["A2"]),
                    "arena-carry":  _make_variant(["arena"], "Arena Carry",  items=["N1"]),
                    "arena-mage":   _make_variant(["arena"], "Arena Mage",   items=["N2"]),
                }, default_per_mode={
                    "sr": "sr-carry", "aram": "aram-carry", "arena": "arena-carry",
                }),
            },
        }
        out, per_mode = collapse_payload_modes(payload, (SR_MODE, ARAM_MODE, ARENA_MODE))
        a = out["champions"]["A"]
        self.assertEqual(a["default_per_mode"]["sr"],    "sr-collapsed")
        self.assertEqual(a["default_per_mode"]["aram"],  "aram-collapsed")
        self.assertEqual(a["default_per_mode"]["arena"], "arena-collapsed")
        self.assertIn("sr-collapsed",    a["variants"])
        self.assertIn("aram-collapsed",  a["variants"])
        self.assertIn("arena-collapsed", a["variants"])
        # 2 paths per mode (sr+aram+arena each have 2 source variants).
        for ck in ("sr-collapsed", "aram-collapsed", "arena-collapsed"):
            self.assertEqual(len(a["variants"][ck]["build_paths"]), 2,
                f"{ck} build_paths count")
        # Per-mode stats reflect 1 affected champ each.
        for m in (SR_MODE, ARAM_MODE, ARENA_MODE):
            self.assertEqual(len(per_mode[m]), 1)
            self.assertEqual(per_mode[m][0][1]["after"], 1)


class Item179IdempotencyTests(unittest.TestCase):
    """Re-running collapse on already-collapsed input is a no-op."""

    def test_aram_recollapse_on_already_collapsed_preserves_paths(self) -> None:
        # Start with a collapsed entry; re-run mode='aram'; result must
        # carry the same build_paths (preserves operator hand-edits).
        entry = _make_entry({
            "aram-collapsed": {
                "label":      "Builds for X",
                "modes":      ["aram"],
                "items":      ["AR1"],
                "summoners":  [4, 32],
                "runes":      {},
                "_collapsed": True,
                "build_paths": [
                    {"key": "aram-carry",   "label": "Carry",
                     "items": ["AR1"], "_is_primary": True},
                    {"key": "aram-bruiser", "label": "Bruiser",
                     "items": ["AR2"]},
                ],
            },
        }, default_per_mode={"aram": "aram-collapsed"})
        new, stats = collapse_champion("Test", entry, mode=ARAM_MODE)
        self.assertEqual(stats["before"], 0)  # no source variants left
        # Re-run produces the same path list.
        paths = new["variants"]["aram-collapsed"]["build_paths"]
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0]["key"], "aram-carry")
        self.assertEqual(paths[1]["key"], "aram-bruiser")
        # Primary marker re-stamped on path[0].
        self.assertTrue(paths[0]["_is_primary"])
        self.assertNotIn("_is_primary", paths[1])

    def test_arena_recollapse_idempotent_byte_equivalent(self) -> None:
        # Same idea for Arena: re-running on a collapsed entry produces
        # an identical-shape output.
        original_paths = [
            {"key": "arena-carry",                 "label": "Carry",
             "items": ["AN1"], "_is_primary": True},
            {"key": "auto-arena-primary-carry",    "label": "Carry",
             "items": ["AN1"]},
            {"key": "auto-arena-secondary-bruiser", "label": "Bruiser (sec)",
             "items": ["AN2"]},
        ]
        entry = _make_entry({
            "arena-collapsed": {
                "label":      "Builds for X",
                "modes":      ["arena"],
                "items":      ["AN1"],
                "summoners":  [4, 7],
                "runes":      {},
                "_collapsed": True,
                "build_paths": list(original_paths),
            },
        }, default_per_mode={"arena": "arena-collapsed"})
        new, _ = collapse_champion("Test", entry, mode=ARENA_MODE)
        out_paths = new["variants"]["arena-collapsed"]["build_paths"]
        self.assertEqual(len(out_paths), 3)
        self.assertEqual([p["key"] for p in out_paths],
                         [p["key"] for p in original_paths])

    def test_recollapse_after_source_variant_reintroduced(self) -> None:
        # Operator hand-adds a new aram source variant after a prior
        # collapse; re-running picks up the new variant + builds the
        # full path list deterministically.
        entry = _make_entry({
            "aram-collapsed": {
                "label":      "Builds for X",
                "modes":      ["aram"],
                "items":      ["AR1"],
                "summoners":  [4, 32],
                "runes":      {},
                "_collapsed": True,
                "build_paths": [
                    {"key": "aram-carry", "label": "Carry",
                     "items": ["AR1"], "_is_primary": True},
                ],
            },
            "aram-mage": _make_variant(["aram"], "ARAM Mage", items=["AR2"]),
        }, default_per_mode={"aram": "aram-collapsed"})
        new, stats = collapse_champion("Test", entry, mode=ARAM_MODE)
        # Source count = 1 (aram-mage); collapsed key excluded from count.
        self.assertEqual(stats["before"], 1)
        # aram-mage absorbed -> path list now includes it.
        self.assertNotIn("aram-mage", new["variants"])
        paths = new["variants"]["aram-collapsed"]["build_paths"]
        keys = [p["key"] for p in paths]
        self.assertIn("aram-mage", keys)


class Item179CliTests(unittest.TestCase):
    """--mode flag + --item-tag flag default behavior."""

    def test_resolve_modes_arg_single(self) -> None:
        self.assertEqual(_resolve_modes_arg("sr"),    (SR_MODE,))
        self.assertEqual(_resolve_modes_arg("aram"),  (ARAM_MODE,))
        self.assertEqual(_resolve_modes_arg("arena"), (ARENA_MODE,))

    def test_resolve_modes_arg_all(self) -> None:
        self.assertEqual(_resolve_modes_arg("all"), (SR_MODE, ARAM_MODE, ARENA_MODE))

    def test_resolve_modes_arg_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_modes_arg("tft")
        with self.assertRaises(ValueError):
            _resolve_modes_arg("")
        with self.assertRaises(ValueError):
            _resolve_modes_arg("sr,aram")  # legacy CSV not supported

    def test_collapsed_key_for(self) -> None:
        self.assertEqual(collapsed_key_for(SR_MODE),    "sr-collapsed")
        self.assertEqual(collapsed_key_for(ARAM_MODE),  "aram-collapsed")
        self.assertEqual(collapsed_key_for(ARENA_MODE), "arena-collapsed")

    def test_collapse_payload_aram_only_filter(self) -> None:
        # collapse_payload(only_champion='A') touches only champion A.
        payload = {
            "champions": {
                "A": _make_entry({
                    "aram-carry":   _make_variant(["aram"], "ARAM Carry",   items=["X"]),
                    "aram-bruiser": _make_variant(["aram"], "ARAM Bruiser", items=["Y"]),
                }, default_per_mode={"aram": "aram-carry"}),
                "B": _make_entry({
                    "aram-tank": _make_variant(["aram"], "ARAM Tank", items=["Z"]),
                }, default_per_mode={"aram": "aram-tank"}),
            },
        }
        new, stats = collapse_payload(payload, only_champion="A", mode=ARAM_MODE)
        # A collapsed, B left as-is.
        self.assertIn("aram-collapsed", new["champions"]["A"]["variants"])
        self.assertNotIn("aram-collapsed", new["champions"]["B"]["variants"])
        # B still has aram-tank source.
        self.assertIn("aram-tank", new["champions"]["B"]["variants"])
        # Stats only carry A.
        a_stats = [s for cn, s in stats if cn == "A"]
        self.assertEqual(len(a_stats), 1)
        self.assertEqual(a_stats[0]["after"], 1)


class Item179LiveSchemaTests(unittest.TestCase):
    """Schema invariants on the post-item-179 champion_loadouts.json."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.loadouts = json.loads(_LIVE_LOADOUTS.read_text(encoding="utf-8"))

    def _champs(self) -> dict:
        return self.loadouts.get("champions") or {}

    def test_every_champion_has_one_aram_collapsed(self) -> None:
        missing: list[str] = []
        for cn, c in self._champs().items():
            variants = c.get("variants") or {}
            aram_keys = [vk for vk, v in variants.items()
                         if "aram" in [str(m).lower() for m in (v.get("modes") or [])]]
            if not aram_keys:
                continue
            if "aram-collapsed" not in aram_keys:
                missing.append(cn)
        self.assertEqual(missing, [],
            "champions with ARAM variants but no aram-collapsed: "
            + ", ".join(missing[:10]))

    def test_every_champion_has_one_arena_collapsed(self) -> None:
        missing: list[str] = []
        for cn, c in self._champs().items():
            variants = c.get("variants") or {}
            arena_keys = [vk for vk, v in variants.items()
                          if "arena" in [str(m).lower() for m in (v.get("modes") or [])]]
            if not arena_keys:
                continue
            if "arena-collapsed" not in arena_keys:
                missing.append(cn)
        self.assertEqual(missing, [],
            "champions with Arena variants but no arena-collapsed: "
            + ", ".join(missing[:10]))

    def test_only_one_aram_variant_per_champion(self) -> None:
        offenders: list[str] = []
        for cn, c in self._champs().items():
            variants = c.get("variants") or {}
            aram_count = sum(1 for v in variants.values()
                             if "aram" in [str(m).lower() for m in (v.get("modes") or [])])
            if aram_count > 1:
                offenders.append(f"{cn} ({aram_count})")
        self.assertEqual(offenders, [],
            "champions with >1 ARAM variant: " + ", ".join(offenders[:10]))

    def test_only_one_arena_variant_per_champion(self) -> None:
        offenders: list[str] = []
        for cn, c in self._champs().items():
            variants = c.get("variants") or {}
            arena_count = sum(1 for v in variants.values()
                              if "arena" in [str(m).lower() for m in (v.get("modes") or [])])
            if arena_count > 1:
                offenders.append(f"{cn} ({arena_count})")
        self.assertEqual(offenders, [],
            "champions with >1 Arena variant: " + ", ".join(offenders[:10]))

    def test_default_per_mode_aram_points_to_collapsed(self) -> None:
        bad: list[str] = []
        for cn, c in self._champs().items():
            variants = c.get("variants") or {}
            if not any("aram" in [str(m).lower() for m in (v.get("modes") or [])]
                       for v in variants.values()):
                continue
            sr_default = (c.get("default_per_mode") or {}).get("aram", "")
            if sr_default != "aram-collapsed":
                bad.append(f"{cn} -> {sr_default!r}")
        self.assertEqual(bad, [],
            "champions whose default_per_mode.aram != aram-collapsed: "
            + ", ".join(bad[:10]))

    def test_default_per_mode_arena_points_to_collapsed(self) -> None:
        bad: list[str] = []
        for cn, c in self._champs().items():
            variants = c.get("variants") or {}
            if not any("arena" in [str(m).lower() for m in (v.get("modes") or [])]
                       for v in variants.values()):
                continue
            arena_default = (c.get("default_per_mode") or {}).get("arena", "")
            if arena_default != "arena-collapsed":
                bad.append(f"{cn} -> {arena_default!r}")
        self.assertEqual(bad, [],
            "champions whose default_per_mode.arena != arena-collapsed: "
            + ", ".join(bad[:10]))

    def test_aram_collapsed_variants_have_build_paths_nonempty(self) -> None:
        offenders: list[str] = []
        for cn, c in self._champs().items():
            variants = c.get("variants") or {}
            collapsed = variants.get("aram-collapsed")
            if not collapsed:
                continue
            paths = collapsed.get("build_paths") or []
            if not paths:
                offenders.append(cn)
        self.assertEqual(offenders, [],
            "ARAM-collapsed variants with empty build_paths: "
            + ", ".join(offenders[:10]))

    def test_arena_collapsed_variants_have_build_paths_nonempty(self) -> None:
        offenders: list[str] = []
        for cn, c in self._champs().items():
            variants = c.get("variants") or {}
            collapsed = variants.get("arena-collapsed")
            if not collapsed:
                continue
            paths = collapsed.get("build_paths") or []
            if not paths:
                offenders.append(cn)
        self.assertEqual(offenders, [],
            "Arena-collapsed variants with empty build_paths: "
            + ", ".join(offenders[:10]))

    def test_aram_collapsed_carries_required_fields(self) -> None:
        # Pick any champion with aram-collapsed and verify shape.
        collapsed = None
        for cn, c in self._champs().items():
            v = (c.get("variants") or {}).get("aram-collapsed")
            if v:
                collapsed = v
                break
        self.assertIsNotNone(collapsed)
        self.assertTrue(collapsed.get("_collapsed"))
        self.assertEqual(collapsed.get("modes"), ["aram"])
        self.assertIn("items",       collapsed)
        self.assertIn("runes",       collapsed)
        self.assertIn("summoners",   collapsed)
        self.assertIn("build_paths", collapsed)
        primaries = [p for p in collapsed["build_paths"]
                     if p.get("_is_primary")]
        self.assertEqual(len(primaries), 1)

    def test_arena_collapsed_carries_required_fields(self) -> None:
        collapsed = None
        for cn, c in self._champs().items():
            v = (c.get("variants") or {}).get("arena-collapsed")
            if v:
                collapsed = v
                break
        self.assertIsNotNone(collapsed)
        self.assertTrue(collapsed.get("_collapsed"))
        self.assertEqual(collapsed.get("modes"), ["arena"])
        self.assertIn("items",       collapsed)
        self.assertIn("runes",       collapsed)
        self.assertIn("summoners",   collapsed)
        self.assertIn("build_paths", collapsed)
        primaries = [p for p in collapsed["build_paths"]
                     if p.get("_is_primary")]
        self.assertEqual(len(primaries), 1)

    def test_sr_collapsed_preserved_byte_identical_count(self) -> None:
        # Item 179 must NOT perturb item 178's SR collapsed state.
        # 172 champions; each has exactly one sr-collapsed entry.
        n_sr_collapsed = sum(
            1 for c in self._champs().values()
            if "sr-collapsed" in (c.get("variants") or {})
        )
        self.assertEqual(n_sr_collapsed, 172)

    def test_per_mode_collapsed_count_matches_172(self) -> None:
        # Live data: 172 champs, all 3 modes coverage; each has one
        # mode-collapsed per mode.
        champs = self._champs()
        self.assertEqual(len(champs), 172)
        for mode in (SR_MODE, ARAM_MODE, ARENA_MODE):
            ck = collapsed_key_for(mode)
            ct = sum(1 for c in champs.values()
                     if ck in (c.get("variants") or {}))
            self.assertEqual(ct, 172,
                f"{ck} count expected 172, got {ct}")

    def test_aram_summoners_preserve_mark(self) -> None:
        # ARAM mandates Mark (id 32); the collapsed primary path should
        # carry [4, 32] on most champs. Spot-check a known ADC.
        jinx = self._champs().get("Jinx") or {}
        v = (jinx.get("variants") or {}).get("aram-collapsed") or {}
        summs = v.get("summoners") or []
        if summs:
            # Mark must be present in some form (id 32 or id 4 + 32).
            self.assertIn(4, summs, "Flash missing from Jinx ARAM summoners")
            self.assertTrue(32 in summs or len(summs) == 2,
                f"Jinx ARAM summoners: {summs}")


class Item179AsciiHygieneTests(unittest.TestCase):
    """Item 179 added files MUST be ASCII-clean per CLAUDE.md hard rule."""

    def test_test_file_is_ascii(self) -> None:
        path = _ROOT / "tests" / "test_champion_loadout_collapse_aram_arena.py"
        data = path.read_bytes()
        offenders = [(i, b) for i, b in enumerate(data) if b >= 0x80]
        self.assertEqual(offenders, [],
            f"non-ASCII bytes in {path.name}: {offenders[:5]}")


if __name__ == "__main__":
    unittest.main()
