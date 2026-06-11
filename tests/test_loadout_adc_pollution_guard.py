"""Item 208 carry - ranged-ADC carry-path pollution guard.

Two layers, both keyed on base attackrange (>= 350 = ranged), never on a
champion name list:

1. DATA GUARD: no carry-context row in data/champion_loadouts.json for a
   ranged champion may contain the four melee/tank items that polluted
   the generated builds (Trinity Force / Bastionbreaker / Heartsteel /
   Umbral Glaive). Melee carries (Nilah, 225) are exempt by the range
   gate - Trinity Force is a legitimate item there. Pantheon's Sup Roam
   Umbral Glaive is operator-pinned and survives the same way (175).

2. SCORER GATE: the shared carry-scoring branch in
   core.daemon_slayer_client.rank_for_primary_archetype must drop the
   same four items for ranged champions. Every loadout regen path
   (tools/champion_loadout_autogen.fetch_items, core/build_order.
   plan_build_order via tools/champion_loadout_align) and the live coach
   dispatch flow through that branch, so a patch regen cannot reproduce
   the pollution even if the live engine predates its own pool filter
   (agents/daemon_slayer/rank.py item 213, which gates at Marksman tag
   + attackrange >= 500 and therefore misses Graves at 425).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from core import daemon_slayer_client
from tools.champion_loadout_align import _detect_archetype

_ROOT = Path(__file__).resolve().parent.parent
_LOADOUTS_PATH = _ROOT / "data" / "champion_loadouts.json"
_DS_DATA_DIR = _ROOT / "data" / "daemon_slayer"

# Pinned literals on purpose - the guard must not silently follow a
# drifted constant in the production module. Divine Sunderer was added
# deliberately by the item-s8 sweep (2026-06-10): same engine lineage,
# 7 ranged-carry arena rows (Jhin / Jinx / Nami / Seraphine /
# Twisted Fate / Ziggs / Zilean).
RANGED_FLOOR = 350.0
FLAGGED_ITEMS = frozenset({
    "Trinity Force",
    "Bastionbreaker",
    "Heartsteel",
    "Umbral Glaive",
    "Divine Sunderer",
})

# Operator-pinned hand-curations are not generated pollution. Corki's SR
# "ad" path keeps Trinity Force by item-269 hand-fix (tools/
# hotfix_sibling_pollution_item269._CORKI - Sheen rides Corki's
# magic-damage passive, a historically real core) and that fixed state
# is itself test-pinned. The collapsed entry's items mirror the primary
# path, so the mirror row rides the same exemption. Same principle as
# Pantheon's Sup Roam Umbral Glaive (which the range gate already
# exempts at 175).
OPERATOR_PINNED = frozenset({
    ("Corki", "sr-collapsed/ad", "Trinity Force"),
    ("Corki", "sr-collapsed(items)", "Trinity Force"),
})


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _attackrange_by_name() -> dict[str, float]:
    """Display-name + DDragon-id keyed base attackrange map from the
    current DS champion snapshot (falls back to 16.12.1 so the guard
    stays anchored if current.txt is ever blank)."""
    patch = ""
    try:
        patch = (_DS_DATA_DIR / "current.txt").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    path = _DS_DATA_DIR / (patch or "16.12.1") / "champions.json"
    data = json.loads(path.read_text(encoding="utf-8")).get("data") or {}
    out: dict[str, float] = {}
    for cid, rec in data.items():
        stats = (rec or {}).get("stats") or {}
        try:
            rng = float(stats.get("attackrange") or 0.0)
        except (TypeError, ValueError):
            continue
        out[_norm(cid)] = rng
        name = (rec or {}).get("name")
        if name:
            out[_norm(name)] = rng
    return out


def _carry_row_violations() -> list[tuple[str, str, str]]:
    """Return (champion, row_key, item) for every flagged item sitting in
    a carry-context row of a ranged champion. Carry context is resolved
    by the align tool's own archetype detector so the guard and the
    regen pipeline can never disagree about what counts as carry."""
    loadouts = json.loads(_LOADOUTS_PATH.read_text(encoding="utf-8"))
    champs = loadouts.get("champions") or {}
    ranges = _attackrange_by_name()
    violations: list[tuple[str, str, str]] = []

    def check_items(champ: str, row_key: str, items: list) -> None:
        for it in items or []:
            if it in FLAGGED_ITEMS and (champ, row_key, it) not in OPERATOR_PINNED:
                violations.append((champ, row_key, it))

    for champ, entry in champs.items():
        if ranges.get(_norm(champ), 0.0) < RANGED_FLOOR:
            continue
        for vk, v in (entry.get("variants") or {}).items():
            if not isinstance(v, dict):
                continue
            if v.get("_collapsed"):
                paths = v.get("build_paths") or []
                for i, p in enumerate(paths):
                    if not isinstance(p, dict):
                        continue
                    pk = str(p.get("key") or "")
                    if _detect_archetype(pk, p) != "carry":
                        continue
                    check_items(champ, f"{vk}/{pk}", p.get("items") or [])
                    # The collapsed entry's own items mirror the primary
                    # path, so a polluted carry primary leaks twice.
                    if i == 0:
                        check_items(champ, f"{vk}(items)", v.get("items") or [])
            else:
                if _detect_archetype(vk, v) != "carry":
                    continue
                check_items(champ, vk, v.get("items") or [])
    return violations


class LoadoutDataGuardTests(unittest.TestCase):
    def test_no_flagged_items_on_ranged_carry_rows(self) -> None:
        violations = _carry_row_violations()
        self.assertEqual(
            violations, [],
            msg=(
                "melee/tank items present on ranged-ADC carry rows "
                f"({len(violations)}): {violations}"
            ),
        )


def _rows(*names: str):
    return [
        daemon_slayer_client.RankedItem(
            item_id=f"9{i:03d}", item_name=nm,
            delta_dps=200.0 - i, gold=3000,
        )
        for i, nm in enumerate(names)
    ]


class CarryRangedGateTests(unittest.TestCase):
    """Root-cause pin: the carry branch's ranged gate."""

    def test_constants_pinned(self) -> None:
        self.assertEqual(
            daemon_slayer_client.CARRY_RANGED_ATTACKRANGE_FLOOR, RANGED_FLOOR
        )
        self.assertEqual(
            daemon_slayer_client.CARRY_RANGED_OFFCLASS_ITEM_NAMES, FLAGGED_ITEMS
        )

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_ranged_carry_drops_all_five(self, mock_rank) -> None:
        mock_rank.return_value = _rows(
            "Trinity Force", "Bastionbreaker", "Heartsteel",
            "Umbral Glaive", "Divine Sunderer", "Infinity Edge",
        )
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Tristana", "carry", level=11, item_ids=[],
        )
        names = [r["item_name"] for r in out["ranked"]]
        self.assertEqual(names, ["Infinity Edge"])

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_graves_425_is_gated_below_engine_500_floor(self, mock_rank) -> None:
        mock_rank.return_value = _rows("Trinity Force", "The Collector")
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Graves", "carry", level=11, item_ids=[],
        )
        names = [r["item_name"] for r in out["ranked"]]
        self.assertEqual(names, ["The Collector"])

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_melee_carry_nilah_keeps_melee_items(self, mock_rank) -> None:
        mock_rank.return_value = _rows("Trinity Force", "Heartsteel")
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Nilah", "carry", level=11, item_ids=[],
        )
        names = [r["item_name"] for r in out["ranked"]]
        self.assertEqual(names, ["Trinity Force", "Heartsteel"])

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_melee_pantheon_keeps_umbral_glaive(self, mock_rank) -> None:
        mock_rank.return_value = _rows("Umbral Glaive", "Eclipse")
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Pantheon", "carry", level=11, item_ids=[],
        )
        names = [r["item_name"] for r in out["ranked"]]
        self.assertEqual(names, ["Umbral Glaive", "Eclipse"])

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_unknown_champion_fails_soft_to_melee(self, mock_rank) -> None:
        mock_rank.return_value = _rows("Trinity Force")
        out = daemon_slayer_client.rank_for_primary_archetype(
            "NotARealChampion", "carry", level=11, item_ids=[],
        )
        names = [r["item_name"] for r in out["ranked"]]
        self.assertEqual(names, ["Trinity Force"])

    @mock.patch("core.daemon_slayer_client.rank_bruiser_for")
    def test_bruiser_branch_is_not_gated(self, mock_rank) -> None:
        # Melee items stay legitimate on a ranged champ's bruiser rows
        # (e.g. Tristana's auto-arena-flavor-bruiser path).
        mock_rank.return_value = [
            daemon_slayer_client.BruiserRankedItem(
                item_id="3078", item_name="Trinity Force",
                delta_dps=100.0, delta_ehp=200.0, hybrid_delta_pct=8.0,
                gold=3333,
            )
        ]
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Tristana", "bruiser", level=11, item_ids=[],
        )
        names = [r["item_name"] for r in out["ranked"]]
        self.assertEqual(names, ["Trinity Force"])


if __name__ == "__main__":
    unittest.main()
