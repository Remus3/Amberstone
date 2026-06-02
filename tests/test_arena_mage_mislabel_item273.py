"""Characterization + drift guard for item 273 - Arena "Mage"-labeled
build paths must not be AD-dominant mislabels.

Item 269 L4 carry (confirmed item 273): the Arena auto-seed in
``tools/champion_loadout_autogen.py`` assigns an archetype triplet
(primary/secondary/flavor) per champion from
``core/archetype_picks.py`` defaults, then asks the DS Arena scorer for
the top items of each slot. For AP-flex champions (Kha'Zix, Qiyana,
Smolder, Talon, Varus, Zed, Pyke, Senna) the "mage" slot resolves to
AD lethality/bruiser items (Bloodthirster / Ravenous Hydra /
Hemomancer's Helm / Manamune) because Arena AP items are sparse for an
AD kit. The "Mage" LABEL then sits over an AD-dominant build.

This is a LABEL defect only - the build items are a legitimate AD
bruiser/lifesteal path; only the archetype label is wrong. The fix
relabels each AD-dominant "Mage" Arena path to the AD archetype its
items actually represent (Bruiser). Arena INTENTIONALLY keeps
bruiser-ADC items (Trinity Force / Heartsteel / Divine Sunderer on
ADCs is genuine Arena meta) - this guard is ONLY about the Mage label
over an AD-dominant item set, not item content.

AP-ness source of truth: ``data/daemon_slayer/16.11.1/items.json``
``data`` map, ``stats.FlatMagicDamageMod`` per item name (max across
id variants, since Arena ships 22-prefixed mirror ids). Twilight's Edge
is a HYBRID item (flat AP 100 AND flat AD 70) so it counts as neither
a pure-AP nor a pure-AD item.
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
_ITEMS = _ROOT / "data" / "daemon_slayer" / "16.11.1" / "items.json"


def _ap_ad_maps() -> tuple[dict[str, float], dict[str, float]]:
    """name -> max flat AP, name -> max flat AD across all id variants."""
    with _ITEMS.open("r", encoding="utf-8") as f:
        data = json.load(f)["data"]
    ap_map: dict[str, float] = {}
    ad_map: dict[str, float] = {}
    for _iid, rec in data.items():
        nm = rec.get("name", "")
        if not nm:
            continue
        st = rec.get("stats") or {}
        ap = st.get("FlatMagicDamageMod") or 0
        ad = st.get("FlatPhysicalDamageMod") or 0
        ap_map[nm] = max(ap_map.get(nm, 0), ap)
        ad_map[nm] = max(ad_map.get(nm, 0), ad)
    return ap_map, ad_map


def _is_mage_path(bp: dict) -> bool:
    return "Mage" in (bp.get("label") or "") or "mage" in (bp.get("key") or "")


def _iter_arena_mage_paths(loadouts: dict):
    """Yield (champ, build_path) for every Arena 'Mage' build path."""
    for champ, rec in loadouts.get("champions", {}).items():
        av = (rec.get("variants") or {}).get("arena-collapsed")
        if not av:
            continue
        for bp in av.get("build_paths", []) or []:
            if _is_mage_path(bp):
                yield champ, bp


class ArenaMageMislabelItem273Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with _LOADOUTS.open("r", encoding="utf-8") as f:
            cls.loadouts = json.load(f)
        cls.ap_map, cls.ad_map = _ap_ad_maps()

    def _pure_counts(self, items: list[str]) -> tuple[int, int]:
        """Return (pure_AP_count, pure_AD_count). Hybrid items (both AP
        and AD flat) count toward neither."""
        ap_c = 0
        ad_c = 0
        for it in items:
            ap = self.ap_map.get(it, 0)
            ad = self.ad_map.get(it, 0)
            if ap > 0 and ad == 0:
                ap_c += 1
            elif ad > 0 and ap == 0:
                ad_c += 1
        return ap_c, ad_c

    def test_no_arena_mage_path_is_ad_dominant(self) -> None:
        """RED before fix: every Arena 'Mage' build path must carry at
        least as many pure-AP items as pure-AD items. An AD-dominant
        'Mage' path is a mislabel."""
        offenders: list[str] = []
        for champ, bp in _iter_arena_mage_paths(self.loadouts):
            items = bp.get("items", []) or []
            ap_c, ad_c = self._pure_counts(items)
            if ad_c > ap_c:
                offenders.append(
                    f"{champ} '{bp.get('label')}' pureAP={ap_c} "
                    f"pureAD={ad_c} items={items}"
                )
        self.assertEqual(
            offenders,
            [],
            "AD-dominant Arena 'Mage' build paths found - relabel them "
            "to the AD archetype the items represent:\n  "
            + "\n  ".join(offenders),
        )

    def test_every_arena_mage_path_has_an_ap_item(self) -> None:
        """Any remaining 'Mage' path must contain at least one item with
        flat AP (pure-AP or hybrid). A truly 0-AP 'Mage' path is a hard
        mislabel."""
        offenders: list[str] = []
        for champ, bp in _iter_arena_mage_paths(self.loadouts):
            items = bp.get("items", []) or []
            if not any(self.ap_map.get(it, 0) > 0 for it in items):
                offenders.append(f"{champ} '{bp.get('label')}' items={items}")
        self.assertEqual(
            offenders,
            [],
            "Arena 'Mage' build paths with ZERO AP items:\n  "
            + "\n  ".join(offenders),
        )

    def test_no_duplicate_archetype_key_within_arena_variant(self) -> None:
        """Relabeling must not create two build paths sharing the same
        terminal archetype key within one champion's Arena variant."""
        offenders: list[str] = []
        for champ, rec in self.loadouts.get("champions", {}).items():
            av = (rec.get("variants") or {}).get("arena-collapsed")
            if not av:
                continue
            archs = [
                (bp.get("key") or "").split("-")[-1]
                for bp in av.get("build_paths", []) or []
            ]
            seen = set()
            for a in archs:
                if a and a in seen:
                    offenders.append(f"{champ} duplicate arch key '{a}' in {archs}")
                seen.add(a)
        self.assertEqual(
            offenders,
            [],
            "Duplicate archetype keys within an Arena variant:\n  "
            + "\n  ".join(offenders),
        )

    def test_ascii_only_in_loadout_labels_and_keys(self) -> None:
        """Arena build-path labels/keys/reasons stay 7-bit ASCII."""
        offenders: list[str] = []
        for champ, rec in self.loadouts.get("champions", {}).items():
            av = (rec.get("variants") or {}).get("arena-collapsed")
            if not av:
                continue
            for bp in av.get("build_paths", []) or []:
                for field in ("label", "key", "reason"):
                    val = bp.get(field) or ""
                    try:
                        val.encode("ascii")
                    except UnicodeEncodeError:
                        offenders.append(f"{champ} {field}={val!r}")
        self.assertEqual(offenders, [], "non-ASCII in Arena build-path fields")


if __name__ == "__main__":
    unittest.main()
