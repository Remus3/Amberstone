"""RM-16 / item 269 L4 - Arena auto-flavor "Mage" mislabel sweep.

Item 273 Slice A relabeled 8 AD-dominant Arena "Mage" paths and closed
the item-269 L4 carry; ``tests/test_arena_mage_mislabel_item273.py`` is
the data guard for that fix. Two gaps remained, and this module closes
them:

1. That guard pins its AP/AD ground truth to ``16.11.1`` while the live
   engine patch has moved on (``data/daemon_slayer/current.txt``). This
   module resolves the CURRENT patch so the sweep cannot silently drift
   onto a stale item table.
2. Nothing guarded the RULE that produces the label. The Arena flavor
   slot is ``THIRD_ARCH_HEURISTIC[primary]`` in
   ``tools/champion_loadout_autogen.py`` (with a collision fallback that
   walks ``archetype_picks.ARCHETYPES`` in canonical order). A "Mage"
   flavor is only defensible over an AP-axis kit; mapping an AD-axis
   primary onto a mage flavor is exactly how the original mislabels were
   generated. That rule is now pinned here rather than being re-audited
   from the emitted data after every regen.

Ground truth for the kit axis is ``archetype_picks.kit_damage_axis``
(the patch ``champions.json`` damage distribution), NOT DDragon role
tags - role tags encode lane, not the AD-vs-AP axis a kit itemizes.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import archetype_picks  # noqa: E402
from tools.champion_loadout_autogen import (  # noqa: E402
    THIRD_ARCH_HEURISTIC,
    resolve_archetype_triplet,
)

_DS_DIR = _ROOT / "data" / "daemon_slayer"
_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Archetypes whose itemization is AP-axis (or axis-neutral enough that a
# mage flavor is a legitimate operator alternative). A flavor of "mage"
# hung off any OTHER primary is the item-269 defect shape.
_AP_CAPABLE_PRIMARIES = frozenset({"mage", "assassin", "enchanter"})

# Vacuity floors. A silently-empty roster or loadout file would make
# every per-item assertion below pass for the wrong reason.
_MIN_CHAMPIONS = 160
_MIN_MAGE_PATHS = 40


def _current_patch() -> str:
    return (_DS_DIR / "current.txt").read_text(encoding="utf-8").strip()


def _ap_ad_maps(patch: str) -> tuple[dict[str, float], dict[str, float]]:
    """name -> max flat AP, name -> max flat AD across all id variants.

    Arena ships 22-prefixed mirror ids that share a display name with
    their base item, so we take the max across every id carrying a name.
    """
    with (_DS_DIR / patch / "items.json").open("r", encoding="utf-8") as f:
        data = json.load(f)["data"]
    ap_map: dict[str, float] = {}
    ad_map: dict[str, float] = {}
    for _iid, rec in data.items():
        nm = rec.get("name", "")
        if not nm:
            continue
        st = rec.get("stats") or {}
        ap_map[nm] = max(ap_map.get(nm, 0), st.get("FlatMagicDamageMod") or 0)
        ad_map[nm] = max(ad_map.get(nm, 0), st.get("FlatPhysicalDamageMod") or 0)
    return ap_map, ad_map


def _roster() -> list[str]:
    """Champion display names from the current-patch DDragon table."""
    patch = _current_patch()
    path = _ROOT / "data" / "meta_build" / "ddragon" / patch / "champion.json"
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)["data"]
    return sorted(rec["name"] for rec in data.values() if rec.get("name"))


class ArenaAutoFlavorMageRuleTests(unittest.TestCase):
    """Rule-level guard: the labeller itself, before any data is emitted."""

    def test_third_arch_heuristic_never_hangs_mage_off_an_ad_primary(self) -> None:
        """A "mage" flavor may only be complementary to an AP-capable
        primary. carry / bruiser / tank -> mage is the item-269 shape."""
        offenders = [
            f"{primary} -> {third}"
            for primary, third in THIRD_ARCH_HEURISTIC.items()
            if third == "mage" and primary not in _AP_CAPABLE_PRIMARIES
        ]
        self.assertEqual(
            offenders,
            [],
            "THIRD_ARCH_HEURISTIC maps an AD-axis primary onto a 'mage' "
            "flavor - this regenerates the item-269 mislabels:\n  "
            + "\n  ".join(offenders),
        )

    def test_no_champion_resolves_a_mage_flavor_over_an_ad_kit(self) -> None:
        """Full-roster sweep of the emitting rule. For every champion,
        the resolved flavor archetype must not be "mage" when the kit's
        decisive damage axis is AD."""
        roster = _roster()
        self.assertGreaterEqual(
            len(roster), _MIN_CHAMPIONS, "roster too small - sweep would be vacuous"
        )
        offenders: list[str] = []
        for champ in roster:
            primary, secondary = archetype_picks.default_for_champion(champ)
            triplet = dict(resolve_archetype_triplet(primary, secondary))
            if triplet.get("flavor") != "mage":
                continue
            if archetype_picks.kit_damage_axis(champ) == "ad":
                offenders.append(
                    f"{champ} primary={primary} secondary={secondary} "
                    f"flavor=mage kit_axis=ad"
                )
        self.assertEqual(
            offenders,
            [],
            "Champions whose Arena auto-flavor resolves to 'Mage' over an "
            "AD-axis kit:\n  " + "\n  ".join(offenders),
        )


class ArenaMagePathsCurrentPatchTests(unittest.TestCase):
    """Data guard, re-run against the CURRENT engine patch."""

    @classmethod
    def setUpClass(cls) -> None:
        with _LOADOUTS.open("r", encoding="utf-8") as f:
            cls.loadouts = json.load(f)
        cls.ap_map, cls.ad_map = _ap_ad_maps(_current_patch())

    def _mage_paths(self):
        for champ, rec in self.loadouts.get("champions", {}).items():
            arena = (rec.get("variants") or {}).get("arena-collapsed")
            if not arena:
                continue
            for bp in arena.get("build_paths") or []:
                label = bp.get("label") or ""
                key = bp.get("key") or ""
                if "Mage" in label or "mage" in key:
                    yield champ, bp

    def test_mage_path_sample_is_not_vacuous(self) -> None:
        self.assertGreaterEqual(
            len(list(self._mage_paths())),
            _MIN_MAGE_PATHS,
            "too few Arena 'Mage' build paths - the sweep below would be "
            "vacuous; check data/champion_loadouts.json",
        )

    def test_no_arena_mage_path_is_ad_dominant_at_current_patch(self) -> None:
        """Every Arena "Mage" path - primary, secondary AND flavor slot -
        must carry at least as many pure-AP as pure-AD items. Hybrid
        items (flat AP and flat AD, e.g. Twilight's Edge) count toward
        neither side."""
        offenders: list[str] = []
        for champ, bp in self._mage_paths():
            items = bp.get("items") or []
            ap_c = sum(
                1
                for i in items
                if self.ap_map.get(i, 0) > 0 and self.ad_map.get(i, 0) == 0
            )
            ad_c = sum(
                1
                for i in items
                if self.ad_map.get(i, 0) > 0 and self.ap_map.get(i, 0) == 0
            )
            if ad_c > ap_c:
                offenders.append(
                    f"{champ} '{bp.get('label')}' pureAP={ap_c} pureAD={ad_c} "
                    f"items={items}"
                )
        self.assertEqual(
            offenders,
            [],
            "AD-dominant Arena 'Mage' build paths at the current patch:\n  "
            + "\n  ".join(offenders),
        )

    def test_every_arena_mage_path_has_an_ap_item(self) -> None:
        """A 'Mage' path with zero flat-AP items is a hard mislabel."""
        offenders = [
            f"{champ} '{bp.get('label')}' items={bp.get('items')}"
            for champ, bp in self._mage_paths()
            if not any(self.ap_map.get(i, 0) > 0 for i in (bp.get("items") or []))
        ]
        self.assertEqual(
            offenders,
            [],
            "Arena 'Mage' build paths with ZERO AP items:\n  "
            + "\n  ".join(offenders),
        )

    def test_every_mage_path_item_resolves_at_current_patch(self) -> None:
        """Guards the patch pin itself: an item name that no longer
        exists in the current items.json would silently read as 0 AP and
        0 AD, quietly weakening every assertion above."""
        offenders: list[str] = []
        for champ, bp in self._mage_paths():
            for item in bp.get("items") or []:
                if item not in self.ap_map:
                    offenders.append(f"{champ} '{bp.get('label')}' unknown item {item}")
        self.assertEqual(
            offenders,
            [],
            "Arena 'Mage' path items missing from the current-patch item "
            "table:\n  " + "\n  ".join(sorted(set(offenders))),
        )


if __name__ == "__main__":
    unittest.main()
