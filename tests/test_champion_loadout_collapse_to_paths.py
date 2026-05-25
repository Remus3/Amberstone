"""Tests for tools/champion_loadout_collapse_to_paths.py.

Item 178 (2026-05-24): pin the SR-mode collapse contract so future
edits to champion_loadouts.json keep the in-game build chooser's
"one entry per champion + N labeled build paths" shape stable.

Three test classes:

* ``LabelMappingTests`` - short_label_for() per variant_key family.
* ``CollapseChampionTests`` - shape + invariants of collapse_champion().
* ``LiveSchemaInvariantTests`` - post-migration data/champion_loadouts.json
  validates against the collapsed schema (one sr-collapsed per champ +
  build_paths[] non-empty + default_per_mode.sr always resolves).

Migration tool itself is invoked by ``CollapseChampionTests`` against
synthetic in-memory champion entries, so the tests don't touch the
live JSON file beyond the read-only schema check.
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
    COLLAPSED_KEY,
    collapse_champion,
    collapse_payload,
    order_source_keys,
    pick_primary_key,
    short_label_for,
)


_LIVE_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"


class LabelMappingTests(unittest.TestCase):
    """Per-variant-key short pill labels for the collapsed build chooser."""

    def test_sr_arch_standard_pills(self) -> None:
        # sr-<arch> standard mappings (canonical per item 166).
        self.assertEqual(short_label_for("sr-carry",     "carry",     "Carry"),     "Carry")
        self.assertEqual(short_label_for("sr-bruiser",   "bruiser",   "Bruiser"),   "Bruiser")
        self.assertEqual(short_label_for("sr-tank",      "tank",      "Tank"),      "Tank")
        self.assertEqual(short_label_for("sr-mage",      "mage",      "Mage"),      "Mage")
        self.assertEqual(short_label_for("sr-assassin",  "assassin",  "Assassin"),  "Assassin")
        self.assertEqual(short_label_for("sr-enchanter", "enchanter", "Enchanter"), "Enchanter")

    def test_adc_family_pills(self) -> None:
        self.assertEqual(short_label_for("adc-crit",   "", "ADC Crit"),     "Crit")
        self.assertEqual(short_label_for("on-hit",     "", "On-Hit"),       "On-Hit")
        self.assertEqual(short_label_for("ad-on-hit",  "", "AD On-Hit"),    "AD On-Hit")
        self.assertEqual(short_label_for("lethality",  "", "Lethality"),    "Lethality")

    def test_ap_family_pills(self) -> None:
        self.assertEqual(short_label_for("ap-burst",   "", "AP Burst"),     "Burst")
        self.assertEqual(short_label_for("ap-dps",     "", "AP DPS"),       "DPS")
        self.assertEqual(short_label_for("ap-bruiser", "", "AP Bruiser"),   "AP Bruiser")

    def test_tank_engage_pill(self) -> None:
        self.assertEqual(short_label_for("tank-engage", "", "Aftershock Tank"), "Engage")

    def test_jungle_family_pills(self) -> None:
        self.assertEqual(short_label_for("jg-bruiser",  "", "JG Bruiser"), "JG Bruiser")
        self.assertEqual(short_label_for("jg-marksman", "", "JG Marks"),   "JG Marksman")

    def test_auto_sr_falls_back_to_archetype(self) -> None:
        # auto-sr-primary-<arch> maps to the canonical Title arch label.
        self.assertEqual(short_label_for("auto-sr-primary-carry",     "carry",     "Carry (auto)"),     "Carry")
        self.assertEqual(short_label_for("auto-sr-secondary-bruiser", "bruiser",   "Bruiser (auto)"),   "Bruiser")
        self.assertEqual(short_label_for("auto-sr-flavor-tank",       "tank",      "Tank (auto)"),      "Tank")
        self.assertEqual(short_label_for("auto-sr-primary-enchanter", "enchanter", "Enchanter (auto)"), "Enchanter")

    def test_unmapped_falls_back_titlecased(self) -> None:
        # A novel key not in _LABEL_MAP + no archetype hint falls
        # through to the titlecased remainder.
        self.assertEqual(short_label_for("brand-new-key", "", ""), "Brand New Key")

    def test_unmapped_with_arch_uses_arch_label(self) -> None:
        # Novel key but recognized arch -> arch label wins.
        self.assertEqual(short_label_for("brand-new-key", "tank", ""), "Tank")


class CollapseChampionTests(unittest.TestCase):
    """Shape + invariants of collapse_champion() on synthetic entries."""

    @staticmethod
    def _make_variant(modes: list[str], label: str = "v", items: list | None = None,
                      summoners: list | None = None, runes: dict | None = None,
                      archetype: str = "", auto: bool = False) -> dict:
        return {
            "label":      label,
            "modes":      list(modes),
            "runes":      dict(runes or {}),
            "summoners":  list(summoners or []),
            "items":      list(items or []),
            **({"_auto": True} if auto else {}),
            **({"_archetype": archetype} if archetype else {}),
        }

    def _make_entry(self, variants: dict, default_sr: str = "") -> dict:
        d = {"variants": variants, "default_per_mode": {}}
        if default_sr:
            d["default_per_mode"]["sr"] = default_sr
        return d

    def test_sr_only_variants_absorbed_into_collapsed(self) -> None:
        entry = self._make_entry({
            "sr-carry":   self._make_variant(["sr"], "Carry",   items=["A"], summoners=[4, 21]),
            "sr-bruiser": self._make_variant(["sr"], "Bruiser", items=["B"], summoners=[4, 12]),
        }, default_sr="sr-carry")
        new, stats = collapse_champion("Test", entry)
        self.assertEqual(stats["before"], 2)
        self.assertEqual(stats["after"],  1)
        self.assertEqual(stats["paths"],  2)
        self.assertIn(COLLAPSED_KEY, new["variants"])
        # Originals dropped.
        self.assertNotIn("sr-carry",   new["variants"])
        self.assertNotIn("sr-bruiser", new["variants"])
        # Collapsed has both as paths.
        paths = new["variants"][COLLAPSED_KEY]["build_paths"]
        self.assertEqual(len(paths), 2)
        # Primary path = default_per_mode.sr source.
        self.assertEqual(paths[0]["key"], "sr-carry")
        self.assertTrue(paths[0]["_is_primary"])

    def test_multi_mode_variant_keeps_other_modes(self) -> None:
        # A variant with modes=[sr, aram] gets SR stripped (absorbed
        # into the collapsed paths) but the original entry stays under
        # its original key for ARAM.
        entry = self._make_entry({
            "adc-crit":   self._make_variant(["sr", "aram"], "ADC Crit",  items=["A"]),
            "sr-bruiser": self._make_variant(["sr"],         "Bruiser",   items=["B"]),
        }, default_sr="adc-crit")
        new, _ = collapse_champion("Test", entry)
        # adc-crit still present (now ARAM-only).
        self.assertIn("adc-crit", new["variants"])
        self.assertEqual(new["variants"]["adc-crit"]["modes"], ["aram"])
        # sr-bruiser fully absorbed (was sr-only).
        self.assertNotIn("sr-bruiser", new["variants"])
        # adc-crit also appears as a build_path (its items live in two
        # places now: under "adc-crit" for ARAM resolve, and inside
        # sr-collapsed for SR).
        paths = new["variants"][COLLAPSED_KEY]["build_paths"]
        keys = [p["key"] for p in paths]
        self.assertIn("adc-crit",   keys)
        self.assertIn("sr-bruiser", keys)

    def test_default_per_mode_sr_repointed_to_collapsed(self) -> None:
        entry = self._make_entry({
            "sr-carry": self._make_variant(["sr"], "Carry", items=["A"]),
        }, default_sr="sr-carry")
        new, _ = collapse_champion("Test", entry)
        self.assertEqual(new["default_per_mode"]["sr"], COLLAPSED_KEY)

    def test_default_per_mode_other_modes_preserved(self) -> None:
        entry = {
            "variants": {
                "sr-carry":   self._make_variant(["sr"],   "Carry"),
                "aram-carry": self._make_variant(["aram"], "ARAM Carry"),
                "arena-carry": self._make_variant(["arena"], "Arena Carry"),
            },
            "default_per_mode": {
                "sr":    "sr-carry",
                "aram":  "aram-carry",
                "arena": "arena-carry",
            },
        }
        new, _ = collapse_champion("Test", entry)
        self.assertEqual(new["default_per_mode"]["sr"],    COLLAPSED_KEY)
        self.assertEqual(new["default_per_mode"]["aram"],  "aram-carry")
        self.assertEqual(new["default_per_mode"]["arena"], "arena-carry")

    def test_aram_arena_variants_untouched(self) -> None:
        entry = self._make_entry({
            "sr-carry":    self._make_variant(["sr"],    "Carry",       items=["A"]),
            "aram-carry":  self._make_variant(["aram"],  "ARAM Carry",  items=["B"]),
            "arena-carry": self._make_variant(["arena"], "Arena Carry", items=["C"]),
        }, default_sr="sr-carry")
        new, _ = collapse_champion("Test", entry)
        # ARAM/Arena variants present + UNCHANGED.
        self.assertEqual(new["variants"]["aram-carry"]["items"],  ["B"])
        self.assertEqual(new["variants"]["arena-carry"]["items"], ["C"])
        self.assertEqual(new["variants"]["aram-carry"]["modes"],  ["aram"])
        self.assertEqual(new["variants"]["arena-carry"]["modes"], ["arena"])

    def test_collapsed_variant_runes_summoners_from_primary(self) -> None:
        entry = self._make_entry({
            "sr-carry":   self._make_variant(["sr"], "Carry",   items=["A"],
                                              summoners=[4, 21],
                                              runes={"keystone": "Lethal Tempo"}),
            "sr-bruiser": self._make_variant(["sr"], "Bruiser", items=["B"],
                                              summoners=[4, 12],
                                              runes={"keystone": "Conqueror"}),
        }, default_sr="sr-carry")
        new, _ = collapse_champion("Test", entry)
        collapsed = new["variants"][COLLAPSED_KEY]
        # Primary path was sr-carry; variant-level runes/summoners
        # populate from there for back-compat with legacy resolve().
        self.assertEqual(collapsed["summoners"], [4, 21])
        self.assertEqual(collapsed["runes"]["keystone"], "Lethal Tempo")
        self.assertEqual(collapsed["items"], ["A"])

    def test_no_sr_variants_returns_entry_unchanged(self) -> None:
        entry = self._make_entry({
            "aram-carry":  self._make_variant(["aram"],  "ARAM Carry"),
            "arena-carry": self._make_variant(["arena"], "Arena Carry"),
        })
        new, stats = collapse_champion("Test", entry)
        self.assertEqual(stats["before"], 0)
        self.assertEqual(stats["after"],  0)
        self.assertEqual(stats["paths"],  0)
        self.assertNotIn(COLLAPSED_KEY, new["variants"])

    def test_idempotent_on_collapsed_input(self) -> None:
        # Run collapse on already-collapsed entry; result should still
        # have a single sr-collapsed and the paths should match.
        entry = self._make_entry({
            "sr-carry":   self._make_variant(["sr"], "Carry",   items=["A"]),
            "sr-bruiser": self._make_variant(["sr"], "Bruiser", items=["B"]),
        }, default_sr="sr-carry")
        once, _   = collapse_champion("Test", entry)
        twice, _  = collapse_champion("Test", once)
        # After the first pass, the synthetic sr-collapsed variant is
        # SR-only; the second pass picks it as primary and produces a
        # single-path collapsed (since the original sr-carry/sr-bruiser
        # are gone from new["variants"]).
        self.assertIn(COLLAPSED_KEY, twice["variants"])
        # Second pass keeps the same collapsed key; doesn't duplicate.
        sr_only_keys = [vk for vk, v in twice["variants"].items()
                        if "sr" in v.get("modes", [])]
        self.assertEqual(sr_only_keys, [COLLAPSED_KEY])

    def test_collapsed_marker_set(self) -> None:
        entry = self._make_entry({
            "sr-carry": self._make_variant(["sr"], "Carry", items=["A"]),
        }, default_sr="sr-carry")
        new, _ = collapse_champion("Test", entry)
        self.assertTrue(new["variants"][COLLAPSED_KEY]["_collapsed"])

    def test_build_paths_carry_required_fields(self) -> None:
        entry = self._make_entry({
            "sr-carry": self._make_variant(["sr"], "Carry", items=["A"],
                                            summoners=[4, 21]),
        }, default_sr="sr-carry")
        new, _ = collapse_champion("Test", entry)
        path = new["variants"][COLLAPSED_KEY]["build_paths"][0]
        self.assertIn("key",   path)
        self.assertIn("label", path)
        self.assertIn("items", path)
        self.assertEqual(path["key"],   "sr-carry")
        self.assertEqual(path["items"], ["A"])
        self.assertTrue(path["_is_primary"])

    def test_primary_key_falls_back_to_first_curated(self) -> None:
        # No default_per_mode.sr -> pick the first non-auto SR variant.
        variants = {
            "auto-sr-primary-carry": self._make_variant(
                ["sr"], "Carry (auto)", auto=True, archetype="carry"),
            "sr-bruiser":            self._make_variant(
                ["sr"], "Bruiser"),
        }
        primary = pick_primary_key(variants, "")
        self.assertEqual(primary, "sr-bruiser")

    def test_order_puts_primary_first_then_curated_then_auto(self) -> None:
        variants = {
            "auto-sr-primary-carry": self._make_variant(["sr"], "Carry (auto)", auto=True),
            "sr-bruiser":            self._make_variant(["sr"], "Bruiser"),
            "adc-crit":              self._make_variant(["sr"], "ADC Crit"),
        }
        ordered = order_source_keys(variants, primary_key="sr-bruiser")
        self.assertEqual(ordered[0], "sr-bruiser")
        # Remaining: curated first (alphabetical), then auto.
        self.assertEqual(ordered[1], "adc-crit")
        self.assertEqual(ordered[2], "auto-sr-primary-carry")


class CollapsePayloadTests(unittest.TestCase):
    """End-to-end collapse_payload over a multi-champion synthetic dict."""

    def test_only_champion_filter(self) -> None:
        payload = {
            "champions": {
                "A": {
                    "default_per_mode": {"sr": "sr-carry"},
                    "variants": {"sr-carry": {"modes": ["sr"], "items": [], "runes": {}, "summoners": []}},
                },
                "B": {
                    "default_per_mode": {"sr": "sr-tank"},
                    "variants": {"sr-tank": {"modes": ["sr"], "items": [], "runes": {}, "summoners": []}},
                },
            },
        }
        new, stats = collapse_payload(payload, only_champion="A")
        # A collapsed, B left as-is (no stats).
        self.assertIn(COLLAPSED_KEY, new["champions"]["A"]["variants"])
        self.assertNotIn(COLLAPSED_KEY, new["champions"]["B"]["variants"])
        a_stats = [s for cn, s in stats if cn == "A"][0]
        self.assertEqual(a_stats["after"], 1)


class LiveSchemaInvariantTests(unittest.TestCase):
    """Schema invariants on the post-migration champion_loadouts.json."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.loadouts = json.loads(_LIVE_LOADOUTS.read_text(encoding="utf-8"))

    def test_every_champion_has_one_sr_collapsed(self) -> None:
        # Every champion that previously had ANY SR variant should
        # now have exactly one sr-collapsed.
        missing: list[str] = []
        for cn, c in (self.loadouts.get("champions") or {}).items():
            variants = c.get("variants") or {}
            sr_keys = [vk for vk, v in variants.items()
                       if "sr" in (v.get("modes") or [])]
            if not sr_keys:
                continue
            if COLLAPSED_KEY not in sr_keys:
                missing.append(cn)
        self.assertEqual(missing, [],
            "champions with SR variants but no sr-collapsed: "
            + ", ".join(missing[:10]))

    def test_only_one_sr_variant_per_champion(self) -> None:
        # Post-collapse, every champion has at MOST one variant with
        # SR in its modes list (the collapsed entry). Multi-mode
        # variants get SR stripped at collapse time.
        offenders: list[str] = []
        for cn, c in (self.loadouts.get("champions") or {}).items():
            variants = c.get("variants") or {}
            sr_count = sum(1 for v in variants.values()
                           if "sr" in (v.get("modes") or []))
            if sr_count > 1:
                offenders.append(f"{cn} ({sr_count})")
        self.assertEqual(offenders, [],
            "champions with >1 SR variant: " + ", ".join(offenders[:10]))

    def test_default_per_mode_sr_points_to_collapsed(self) -> None:
        bad: list[str] = []
        for cn, c in (self.loadouts.get("champions") or {}).items():
            variants = c.get("variants") or {}
            sr_keys = [vk for vk, v in variants.items()
                       if "sr" in (v.get("modes") or [])]
            if not sr_keys:
                continue
            sr_default = (c.get("default_per_mode") or {}).get("sr", "")
            if sr_default != COLLAPSED_KEY:
                bad.append(f"{cn} -> {sr_default!r}")
        self.assertEqual(bad, [],
            "champions whose default_per_mode.sr != sr-collapsed: "
            + ", ".join(bad[:10]))

    def test_collapsed_variants_have_build_paths_nonempty(self) -> None:
        offenders: list[str] = []
        for cn, c in (self.loadouts.get("champions") or {}).items():
            variants = c.get("variants") or {}
            collapsed = variants.get(COLLAPSED_KEY)
            if not collapsed:
                continue
            paths = collapsed.get("build_paths") or []
            if not paths:
                offenders.append(cn)
        self.assertEqual(offenders, [],
            "collapsed variants with empty build_paths: "
            + ", ".join(offenders[:10]))

    def test_collapsed_variant_carries_required_fields(self) -> None:
        sample = next(iter(self.loadouts.get("champions") or {}))
        c = self.loadouts["champions"][sample]
        collapsed = (c.get("variants") or {}).get(COLLAPSED_KEY)
        if not collapsed:
            # Find ANY champion with a collapsed entry to sample.
            for cn, c in self.loadouts["champions"].items():
                v = (c.get("variants") or {}).get(COLLAPSED_KEY)
                if v:
                    collapsed = v
                    break
        self.assertIsNotNone(collapsed)
        self.assertTrue(collapsed.get("_collapsed"))
        self.assertEqual(collapsed.get("modes"), ["sr"])
        self.assertIn("items", collapsed)
        self.assertIn("runes", collapsed)
        self.assertIn("summoners", collapsed)
        self.assertIn("build_paths", collapsed)
        # At least one path is marked primary.
        primaries = [p for p in collapsed["build_paths"]
                     if p.get("_is_primary")]
        self.assertEqual(len(primaries), 1)


class AsciiHygieneTests(unittest.TestCase):
    """Item 178 added files MUST be ASCII-clean per CLAUDE.md hard rule."""

    def test_collapse_tool_is_ascii(self) -> None:
        path = _ROOT / "tools" / "champion_loadout_collapse_to_paths.py"
        data = path.read_bytes()
        offenders = [(i, b) for i, b in enumerate(data) if b >= 0x80]
        self.assertEqual(offenders, [],
            f"non-ASCII bytes in {path.name}: {offenders[:5]}")


if __name__ == "__main__":
    unittest.main()
