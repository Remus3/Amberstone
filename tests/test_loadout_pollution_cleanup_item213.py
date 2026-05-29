"""Drift guard for item-213 loadout-data pollution cleanup.

Operator ask (2026-05-28): "search and correct item/rune/summoner spell
pollution for ALL champions, rebuild as necessary to provide the 2-3+
item build paths for all modes".

This test locks the post-cleanup invariants on
``data/champion_loadouts.json``:

  (a) No "Golden Spatula" (any naming variant) in any SR or ARAM
      build_path. It is the ARAM joke/anvil item (id 994403) plus the
      Arena prismatic anvil tokens (224403 / 444403 etc); it is never a
      coachable core item.
  (b) No two build_paths within a single collapsed variant share the
      same item-list (order-insensitive). The redundant ``auto-*`` seed
      paths that duplicated the curated paths are dropped.
  (c) Every collapsed variant (``sr-collapsed`` / ``aram-collapsed`` /
      ``arena-collapsed``) carries >= 2 build_paths, each with >= 4
      items.
  (d) A sample of ranged ADCs (Caitlyn / Jinx / Ezreal / Varus /
      Kai'Sa) have NO melee/tank off-class items
      (Plated Steelcaps / Trinity Force / Bastionbreaker /
      Sundered Sky / Umbral Glaive) in their SR + ARAM PRIMARY paths.
  (e) ASCII hygiene - the data file stays 7-bit ASCII (CLAUDE.md hard
      rule; resolved item NAME strings only).

Re-run ``tools/champion_loadout_cleanup_pollution_item213.py`` on the
affected slice if any assertion trips.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Joke / anvil / placeholder item NAMES that must never appear as a
# coachable build-path item in SR or ARAM (case-insensitive match).
_JOKE_NAMES = {
    "golden spatula",
    "the golden spatula",
    "stat bonus",
    "legendary fighter item",
    "legendary marksman item",
    "legendary assassin item",
    "legendary mage item",
    "legendary tank item",
    "legendary enchanter item",
    "juice of power",
    "juice of vitality",
    "juice of haste",
}

# Off-class melee / tank items that must not pollute a ranged-ADC's
# SR + ARAM primary path (test sample item 213 / ALPHA marksman fix).
_OFFCLASS_MELEE = {
    "plated steelcaps",
    "trinity force",
    "bastionbreaker",
    "sundered sky",
    "umbral glaive",
}

_RANGED_ADC_SAMPLE = ["Caitlyn", "Jinx", "Ezreal", "Varus", "Kai'Sa"]


def _norm(s: str) -> str:
    return (s or "").strip().lower()


class LoadoutPollutionCleanupItem213Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with _LOADOUTS.open("r", encoding="utf-8") as f:
            cls.loadouts = json.load(f)
        cls.champions = cls.loadouts.get("champions") or {}

    def _iter_collapsed(self):
        """Yield (champ, variant_key, mode, variant) for collapsed variants."""
        for cn, c in self.champions.items():
            for vk, v in (c.get("variants") or {}).items():
                if not v.get("_collapsed"):
                    continue
                mode = (
                    "sr"
                    if "sr" in vk
                    else ("aram" if "aram" in vk else "arena")
                )
                yield cn, vk, mode, v

    def test_a_no_golden_spatula_in_sr_or_aram(self) -> None:
        offenders: list[str] = []
        for cn, vk, mode, v in self._iter_collapsed():
            if mode not in ("sr", "aram"):
                continue
            for bp in v.get("build_paths") or []:
                for it in bp.get("items") or []:
                    if "spatula" in _norm(it):
                        offenders.append(
                            f"{cn}|{vk}|{bp.get('key')}: {it!r}"
                        )
        self.assertEqual(
            offenders,
            [],
            f"Golden Spatula leaked into SR/ARAM build_paths: {offenders[:15]}",
        )

    def test_b_no_duplicate_item_list_within_variant(self) -> None:
        dups: list[str] = []
        for cn, vk, mode, v in self._iter_collapsed():
            seen: dict[frozenset, str] = {}
            for bp in v.get("build_paths") or []:
                key = frozenset(_norm(i) for i in (bp.get("items") or []))
                if not key:
                    continue
                if key in seen:
                    dups.append(
                        f"{cn}|{vk}: {bp.get('key')!r} duplicates "
                        f"{seen[key]!r}"
                    )
                else:
                    seen[key] = bp.get("key")
        self.assertEqual(
            dups,
            [],
            f"duplicate item-list build_paths within a variant: {dups[:15]}",
        )

    def test_c_every_variant_two_paths_four_items(self) -> None:
        bad: list[str] = []
        for cn, vk, mode, v in self._iter_collapsed():
            bps = v.get("build_paths") or []
            if len(bps) < 2:
                bad.append(f"{cn}|{vk}: only {len(bps)} build_paths")
                continue
            for bp in bps:
                n = len(bp.get("items") or [])
                if n < 4:
                    bad.append(
                        f"{cn}|{vk}|{bp.get('key')}: only {n} items"
                    )
        self.assertEqual(
            bad,
            [],
            f"variants below 2 paths / 4 items: {bad[:20]}",
        )

    def test_d_ranged_adc_primary_no_melee(self) -> None:
        offenders: list[str] = []
        for cn in _RANGED_ADC_SAMPLE:
            c = self.champions.get(cn)
            self.assertIsNotNone(c, f"sample champion {cn} missing")
            for mode in ("sr", "aram"):
                v = (c.get("variants") or {}).get(mode + "-collapsed")
                if not v:
                    continue
                bps = v.get("build_paths") or []
                if not bps:
                    continue
                primary = bps[0]
                for it in primary.get("items") or []:
                    if _norm(it) in _OFFCLASS_MELEE:
                        offenders.append(
                            f"{cn}|{mode}|{primary.get('key')}: {it!r}"
                        )
        self.assertEqual(
            offenders,
            [],
            f"ranged-ADC primary path carries off-class melee: {offenders}",
        )

    def test_e_ascii_hygiene(self) -> None:
        raw = _LOADOUTS.read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(
            non_ascii[:10],
            [],
            "champion_loadouts.json must be 7-bit ASCII; first offending "
            f"byte offsets: {non_ascii[:10]}",
        )


if __name__ == "__main__":
    unittest.main()
