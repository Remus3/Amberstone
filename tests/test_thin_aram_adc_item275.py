"""Item 275 - thin ARAM ADC carry residual + AP-on-hit label drift guard.

Locks the item-275 hand-curate (tools/hotfix_thin_aram_adc_item275.py):
  * The 4 thin n=4 ADC ARAM carry PRIMARY paths item 269 missed by key
    (Jinx adc-crit / Zeri on-hit / Caitlyn lethality-poke / Varus
    lethality) now carry coherent >=6-item sets.
  * Each extended set is unique-passive-family clash-free.
  * Lulu / Teemo ARAM 'on-hit' relabeled 'AP On-Hit'.
  * The hotfix tool is idempotent.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import hotfix_thin_aram_adc_item275 as hf  # noqa: E402

_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"


def _norm(s: str) -> str:
    return (s or "").lower().strip().replace(" ", "").replace(
        "'", "").replace("-", "").replace(",", "").replace(".", "")


def _family_map() -> dict[str, str]:
    from agents.daemon_slayer._effects_data import ITEM_EFFECTS
    out: dict[str, str] = {}
    for _iid, eff in ITEM_EFFECTS.items():
        upk = getattr(eff, "unique_passive_key", None)
        nm = getattr(eff, "name", None)
        if upk and nm:
            out[_norm(nm)] = upk
    return out


def _aram_path(lo: dict, champ: str, key: str) -> dict | None:
    var = (lo["champions"].get(champ, {}).get("variants", {})
           .get("aram-collapsed"))
    if not var:
        return None
    for bp in var.get("build_paths") or []:
        if bp.get("key") == key:
            return bp
    return None


class ThinAramAdcItem275Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lo = json.loads(_LOADOUTS.read_text(encoding="utf-8"))
        cls.fam = _family_map()

    def test_extended_paths_have_six_items_matching_target(self) -> None:
        for (champ, key), (label, items) in hf._EXTEND.items():
            bp = _aram_path(self.lo, champ, key)
            self.assertIsNotNone(bp, f"{champ}|aram:{key} missing")
            self.assertGreaterEqual(
                len(bp["items"]), 6, f"{champ}|{key} still thin")
            self.assertEqual(bp["items"], items, f"{champ}|{key} items drift")
            self.assertEqual(bp["label"], label, f"{champ}|{key} label drift")

    def test_extended_sets_have_no_unique_family_clash(self) -> None:
        for (champ, key), (_label, items) in hf._EXTEND.items():
            seen: dict[str, str] = {}
            for it in items:
                fam = self.fam.get(_norm(it))
                if not fam:
                    continue
                self.assertNotIn(
                    fam, seen,
                    f"{champ}|{key}: {seen.get(fam)!r} + {it!r} clash {fam!r}")
                seen[fam] = it

    def test_ap_on_hit_relabeled(self) -> None:
        for champ, key in hf._RELABEL_AP_ONHIT:
            bp = _aram_path(self.lo, champ, key)
            self.assertIsNotNone(bp, f"{champ}|aram:{key} missing")
            self.assertEqual(bp["label"], hf._AP_ONHIT_LABEL)
            # Key preserved (label-only change).
            self.assertEqual(bp["key"], key)

    def test_no_thin_named_adc_carry_remains(self) -> None:
        # The 4 named primaries must not be < 5 items anymore.
        for (champ, key), _ in hf._EXTEND.items():
            bp = _aram_path(self.lo, champ, key)
            self.assertGreaterEqual(len(bp["items"]), 5)

    def test_hotfix_idempotent(self) -> None:
        # Applying to a deep copy of the already-fixed live data is a no-op.
        n = hf.apply(copy.deepcopy(self.lo))
        self.assertEqual(n, 0, "hotfix re-apply on fixed data changed rows")

    def test_data_round_trips_ascii(self) -> None:
        text = _LOADOUTS.read_text(encoding="utf-8")
        self.assertEqual(sum(1 for c in text if ord(c) > 127), 0)


if __name__ == "__main__":
    unittest.main()
