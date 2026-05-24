"""Drift guard for champion_loadouts.json unique-passive-family no-double rule.

Item 167 (2026-05-24) ship-time: lock the invariant that every variant
in ``data/champion_loadouts.json`` has at most ONE item per
unique-passive family (spellblade, lifeline, immolate, hydra_cleave,
fiendhunter_barrage, hellfire_char, innervating_fill).

The DS engine's ``filter_shared_uniques=True`` enforces this server-
side for the DS-vs-enemy-comp build, and ``core/build_order.py`` is
engine-authoritative for the planner path. This test extends that
guarantee to the curated variants the build chooser surfaces.

Test failure surfaces the exact (champion, variant_key, item_a,
item_b, family) tuple so the operator can pinpoint where to re-run
``tools/champion_loadout_align.py`` for the affected slice.
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


def _norm(s: str) -> str:
    return (s or "").lower().strip().replace(" ", "").replace(
        "'", "").replace("-", "").replace(",", "").replace(".", "")


def _build_name_to_family() -> dict[str, str]:
    from agents.daemon_slayer._effects_data import ITEM_EFFECTS
    out: dict[str, str] = {}
    for iid, eff in ITEM_EFFECTS.items():
        upk = getattr(eff, "unique_passive_key", None)
        nm = getattr(eff, "name", None)
        if upk and nm:
            out[_norm(nm)] = upk
    return out


class CuratedLoadoutsNoUniqueClashTests(unittest.TestCase):
    """Every variant in champion_loadouts.json must respect the
    unique-passive no-double rule. Same invariant the DS engine
    enforces via filter_shared_uniques=True."""

    @classmethod
    def setUpClass(cls) -> None:
        with _LOADOUTS.open("r", encoding="utf-8") as f:
            cls.loadouts = json.load(f)
        cls.fam_map = _build_name_to_family()

    def test_no_variant_has_unique_family_clash(self) -> None:
        clashes: list[str] = []
        for cn, c in (self.loadouts.get("champions") or {}).items():
            for vk, v in (c.get("variants") or {}).items():
                seen: dict[str, str] = {}
                for it in (v.get("items") or []):
                    fam = self.fam_map.get(_norm(it))
                    if not fam:
                        continue
                    if fam in seen:
                        clashes.append(
                            f"{cn}|{vk}: {seen[fam]!r} + {it!r} "
                            f"both in unique-passive family {fam!r}"
                        )
                    else:
                        seen[fam] = it
        # Cap noise at 25 examples on failure.
        if clashes:
            shown = clashes[:25]
            extra = max(0, len(clashes) - 25)
            msg = (
                f"{len(clashes)} unique-passive family clashes in "
                f"data/champion_loadouts.json. First {len(shown)}:\n  "
                + "\n  ".join(shown)
                + (f"\n  ... +{extra} more" if extra else "")
                + "\nRe-run tools/champion_loadout_align.py on the "
                  "affected slice."
            )
            self.fail(msg)

    def test_name_to_family_map_is_nonempty(self) -> None:
        # If this fails, the DS engine effects registry has shifted shape
        # (unique_passive_key attribute renamed?) and the guard above
        # would pass vacuously - hard-fail the test instead.
        self.assertGreater(
            len(self.fam_map), 10,
            "name_to_family map < 10 entries; DS effects registry shape changed?"
        )
        # Spot-check known families.
        self.assertEqual(self.fam_map.get(_norm("Trinity Force")), "spellblade")
        self.assertEqual(self.fam_map.get(_norm("Sunfire Aegis")), "immolate")
        self.assertEqual(self.fam_map.get(_norm("Sterak's Gage")), "lifeline")


if __name__ == "__main__":
    unittest.main()
