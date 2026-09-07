"""R144 slice E - flat Ability-Haste registry mirror-id coverage guard.

Defect class under audit (the R135 zero-stat fallthrough / R143 mirror class):
``core/daemon_slayer_resolver.name_to_id`` hands the engine MIRROR ids -
``32xxxx`` under mode="sr", ``22xxxx`` under mode="arena", plus the
``44xxxx`` / ``66xxxx`` / ``12xxxx`` families. A registry keyed only on BARE
4-digit ids misses those lookups and ``item_ability_haste`` falls through to a
silent 0.0 with no raise and no log.

MEASURED RESULT for 16.14.1: NO GAP. ``_ITEM_ABILITY_HASTE`` already carries
125 mirror records against 95 bare ids, and the four resolver hits that land
outside the registry are all ids the catalog grants NO Ability Haste at all -
correct absence, not a defect (see ``AH_FREE_RESOLVER_HITS`` below).

This file is the standing guard that keeps it that way across patch bumps.
It deliberately does NOT normalize or prefix-strip a mirror back to its base:
the mirrors are not magnitude-identical and diverge in BOTH directions
(Ionian Boots 3158 is 10 bare but 40 at Arena 223158; Cosmic Drive 4629 is 25
bare but 35 at 224629; Nashor's Tooth 3115 is 15 bare but 10 at 223115).
Coverage is enumerated per id, and this guard proves the enumeration is
complete rather than replacing it with arithmetic.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._item_ability_haste import (
    _ITEM_ABILITY_HASTE,
    item_ability_haste,
)
from core.daemon_slayer_resolver import name_to_id

_ROOT = Path(__file__).resolve().parents[3]
_CURRENT_TXT = _ROOT / "data" / "daemon_slayer" / "current.txt"

# The modes core/daemon_slayer_resolver exposes, i.e. every mode a live coach
# can hand to name_to_id (_MODE_TO_DDRAGON_MAP_ID).
MODES = ("sr", "aram", "arena", "brawl")

# The documented parse: flat AH lives in the FIRST <stats> block of the
# localized description, as "<attention>N</attention> Ability Haste".
# Same derivation as ops/audit/item_ah_drift_check.py.
_STATS_BLOCK = re.compile(r"<stats>(.*?)</stats>", re.S)
_AH = re.compile(r"<attention>([0-9.]+)</attention>\s*Ability Haste")

# Resolver hits that land OUTSIDE the registry and MUST stay outside it.
# Measured 16.14.1: each of these ids has no Ability Haste line in its stats
# block at all, so its absence from the registry is correct - adding a record
# would invent haste the item does not grant. TRAP 3 of the slice directive.
#   (bare_id, item_name, mode, resolved_id)
AH_FREE_RESOLVER_HITS: tuple[tuple[str, str, str, str], ...] = (
    ("3039", "Atma's Reckoning", "sr", "663039"),
    ("3039", "Atma's Reckoning", "arena", "223039"),
    ("3222", "Mikael's Blessing", "arena", "223222"),
    ("6667", "Radiant Virtue", "arena", "446667"),
)

# Mirror ids whose magnitude diverges from their bare id in BOTH directions.
# These are the concrete counter-examples to a prefix-strip "fix".
DIVERGENT_MIRRORS: tuple[tuple[str, str, str, float, float], ...] = (
    ("3158", "223158", "Ionian Boots of Lucidity", "arena", 10.0, 40.0),
    ("4629", "224629", "Cosmic Drive", "arena", 25.0, 35.0),
    ("3115", "223115", "Nashor's Tooth", "arena", 15.0, 10.0),
    ("3110", "323110", "Frozen Heart", "sr", 20.0, 25.0),
    ("3193", "663193", "Gargoyle Stoneplate", "sr", 15.0, 10.0),
)


def _patch() -> str:
    return _CURRENT_TXT.read_text(encoding="utf-8").strip()


def _catalog() -> dict:
    path = _ROOT / "data" / "meta_build" / "ddragon" / _patch() / "item.json"
    # TRACKED in git for every patch current.txt can point at, so absence means
    # the committed catalog was deleted or current.txt moved ahead of its
    # DDragon pull - a failure, not an absent capability.
    assert path.exists(), (
        f"current.txt points at patch {_patch()!r} but the tracked DDragon "
        f"catalog {path} is not committed"
    )
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _derive_ah(catalog: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for iid, entry in catalog.items():
        block = _STATS_BLOCK.search(entry.get("description", "") or "")
        if not block:
            continue
        hit = _AH.search(block.group(1))
        if hit:
            out[iid] = float(hit.group(1))
    return out


class CatalogParityTests(unittest.TestCase):
    """The registry is set-equal AND value-equal to the catalog derivation.

    This is the completeness backbone: the derivation walks the WHOLE
    catalog keyspace, mirrors included, so parity here means no mirror id
    that grants AH can be missing from the pin.
    """

    def setUp(self) -> None:
        self.catalog = _catalog()
        self.derived = _derive_ah(self.catalog)

    def test_no_catalog_ah_id_missing_from_registry(self) -> None:
        missing = sorted(set(self.derived) - set(_ITEM_ABILITY_HASTE), key=int)
        self.assertEqual(
            missing,
            [],
            "catalog grants AH for ids absent from the registry (silent 0.0): "
            + ", ".join(f"{i}={self.derived[i]}" for i in missing),
        )

    def test_no_registry_id_absent_from_catalog(self) -> None:
        stale = sorted(set(_ITEM_ABILITY_HASTE) - set(self.derived), key=int)
        self.assertEqual(stale, [], f"registry pins ids the catalog dropped: {stale}")

    def test_every_registry_magnitude_matches_catalog(self) -> None:
        for iid, pinned in sorted(_ITEM_ABILITY_HASTE.items(), key=lambda kv: int(kv[0])):
            with self.subTest(item_id=iid):
                self.assertAlmostEqual(pinned, self.derived[iid], places=6)


class ResolverMirrorCoverageTests(unittest.TestCase):
    """Every id name_to_id can return is covered, or provably AH-free."""

    def setUp(self) -> None:
        self.catalog = _catalog()
        self.derived = _derive_ah(self.catalog)
        self.names = {k: (v.get("name") or "") for k, v in self.catalog.items()}
        self.bare = sorted((i for i in _ITEM_ABILITY_HASTE if len(i) == 4), key=int)

    def test_registry_carries_both_bare_and_mirror_ids(self) -> None:
        mirrors = [i for i in _ITEM_ABILITY_HASTE if len(i) > 4]
        self.assertTrue(self.bare, "registry has no bare 4-digit ids")
        self.assertTrue(mirrors, "registry has no mirror ids - the R143 defect class")

    def test_resolved_ids_are_covered_or_ah_free(self) -> None:
        for bare in self.bare:
            name = self.names.get(bare, "")
            self.assertTrue(name, f"catalog has no name for pinned id {bare}")
            for mode in MODES:
                resolved = name_to_id(name, mode=mode)
                if resolved is None:
                    continue
                with self.subTest(bare=bare, name=name, mode=mode, resolved=resolved):
                    if resolved in _ITEM_ABILITY_HASTE:
                        continue
                    self.assertNotIn(
                        resolved,
                        self.derived,
                        f"{name} resolves to {resolved} under mode={mode}; the "
                        "catalog grants it AH but the registry misses it "
                        "(silent 0.0 fallthrough)",
                    )

    def test_ah_free_resolver_hits_stay_out_of_the_registry(self) -> None:
        """TRAP 3 - absence of an AH grant in the catalog is correct as-is."""
        for bare, name, mode, resolved in AH_FREE_RESOLVER_HITS:
            with self.subTest(item=name, mode=mode, resolved=resolved):
                self.assertEqual(name_to_id(name, mode=mode), resolved)
                self.assertIn(resolved, self.catalog)
                self.assertNotIn(resolved, self.derived)
                self.assertNotIn(resolved, _ITEM_ABILITY_HASTE)
                self.assertEqual(item_ability_haste(resolved), 0.0)
                # the bare id itself does carry AH - only the mirror is free
                self.assertGreater(item_ability_haste(bare), 0.0)


class MirrorDivergenceTests(unittest.TestCase):
    """Mirrors are not magnitude-identical - never prefix-strip them."""

    def test_divergent_mirrors_keep_their_own_magnitude(self) -> None:
        for bare, mirror, name, mode, bare_ah, mirror_ah in DIVERGENT_MIRRORS:
            with self.subTest(item=name, mode=mode):
                self.assertAlmostEqual(item_ability_haste(bare), bare_ah, places=6)
                self.assertAlmostEqual(item_ability_haste(mirror), mirror_ah, places=6)
                self.assertNotAlmostEqual(bare_ah, mirror_ah, places=6)

    def test_divergence_runs_in_both_directions(self) -> None:
        higher = [m for m in DIVERGENT_MIRRORS if m[5] > m[4]]
        lower = [m for m in DIVERGENT_MIRRORS if m[5] < m[4]]
        self.assertTrue(higher, "no mirror measured above its bare id")
        self.assertTrue(lower, "no mirror measured below its bare id")


if __name__ == "__main__":
    unittest.main()
