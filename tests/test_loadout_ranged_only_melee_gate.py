"""Ranged-only item (Runaan's Hurricane) must never reach a MELEE champion's
static loadout - not in the champ-select variant chooser (list_variants) nor
in the LCU item-set push (resolve).

Root cause (2026-07-12)
-----------------------
The LIVE Daemon Slayer scorer gained a melee ranged-only purchasability gate
on 2026-07-02 (agents/daemon_slayer/rank.py: RANGED_ONLY_ITEM_IDS, applied in
_filter_candidates at the pool chokepoint). The PARALLEL static-loadout serve
path - coaches/loadout_resolver.py, which feeds BOTH the champ-select build
chooser (/api/loadout/list) AND the item-1 rune-follows-build LCU item-set
push (/api/loadout/apply via resolve()) - was never given the same gate. So
melee champions still DISPLAYED and PUSHED Runaan's Hurricane (id 3085), an
item the in-game shop blocks for melee. Operator observed this live on
2026-07-11 (Xin Zhao; memory open_bug_terminus_wrong_build_recommend - the
report named "Terminus", a conflation with the actual Runaan's Hurricane +
Yun Tal Wildarrows carried in Xin Zhao's sr jg-bruiser build).

Ground truth reused (no magic sets):
  * RANGED_ONLY_ITEM_IDS / MELEE_ATTACKRANGE_CEILING from rank.py.
  * attackrange from data/meta/ddragon_champions.json.

Terminus (3302) is deliberately NOT gated: it carries no requiredChampion and
no ranged flag in DDragon, so it is melee-buyable in-game. Gating it would be
the exact over-broad error the rank.py ranged-only doc warns against, so a
guard here asserts Terminus SURVIVES on a melee on-hit build.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.rank import (
    MELEE_ATTACKRANGE_CEILING,
    RANGED_ONLY_ITEM_IDS,
)
from coaches import loadout_resolver

_ROOT = Path(__file__).resolve().parent.parent
_DDRAGON_CHAMPS = _ROOT / "data" / "meta" / "ddragon_champions.json"

_RUNAAN_ID = "3085"
_RUNAAN_NAME = "Runaan's Hurricane"
_TERMINUS_ID = "3302"


def _attackrange_by_key() -> dict[str, float]:
    """name + slug -> base attackrange, mirroring loadout_resolver's own
    dual-key champion lookup so either the display name ("Xin Zhao") or the
    DDragon slug ("XinZhao") resolves."""
    out: dict[str, float] = {}
    d = json.loads(_DDRAGON_CHAMPS.read_text(encoding="utf-8"))
    for slug, info in (d.get("data") or {}).items():
        rng = (info.get("stats") or {}).get("attackrange")
        if rng is None:
            continue
        out[slug] = float(rng)
        nm = info.get("name")
        if nm:
            out[nm] = float(rng)
    return out


def _is_melee(champ_key: str, ranges: dict[str, float]) -> bool:
    rng = ranges.get(champ_key)
    if rng is None:
        want = loadout_resolver._norm(champ_key)
        for k, r in ranges.items():
            if loadout_resolver._norm(k) == want:
                rng = r
                break
    if rng is None:
        return False
    return rng <= MELEE_ATTACKRANGE_CEILING


def _served_item_ids(row: dict) -> set[str]:
    """Every item id a served variant row exposes: the collapsed top-level
    list AND every build_path row (both are user-selectable / pushable)."""
    ids: set[str] = set(str(i) for i in (row.get("item_ids") or []))
    for p in row.get("build_paths") or []:
        ids |= {str(i) for i in (p.get("item_ids") or [])}
    return ids


def _served_item_names(row: dict) -> set[str]:
    names: set[str] = set(row.get("item_names") or [])
    for p in row.get("build_paths") or []:
        names |= set(p.get("items") or [])
    return names


class GroundTruthSanityTests(unittest.TestCase):
    def test_runaan_is_the_ranged_only_id(self) -> None:
        self.assertIn(_RUNAAN_ID, RANGED_ONLY_ITEM_IDS)
        self.assertEqual(MELEE_ATTACKRANGE_CEILING, 250.0)

    def test_xin_zhao_is_melee(self) -> None:
        ranges = _attackrange_by_key()
        self.assertTrue(_is_melee("Xin Zhao", ranges))
        self.assertTrue(_is_melee("XinZhao", ranges))

    def test_varus_is_ranged(self) -> None:
        ranges = _attackrange_by_key()
        self.assertFalse(_is_melee("Varus", ranges))


class XinZhaoReproTests(unittest.TestCase):
    """The reproduction + fix oracle. RED before the resolver gate (Runaan's
    present in Xin Zhao's served sr build + LCU push), GREEN after."""

    def test_list_variants_sr_has_no_runaan(self) -> None:
        rows = loadout_resolver.list_variants("Xin Zhao", "sr")
        self.assertTrue(rows, "no sr variants served for Xin Zhao")
        for row in rows:
            ids = _served_item_ids(row)
            names = _served_item_names(row)
            self.assertNotIn(
                _RUNAAN_ID, ids,
                f"Runaan's (ranged-only) served to melee Xin Zhao in variant "
                f"{row.get('key')!r}",
            )
            self.assertNotIn(_RUNAAN_NAME, names)

    def test_resolve_push_excludes_runaan(self) -> None:
        # sr-collapsed:jg-bruiser is the polluted primary path (Runaan's +
        # Yun Tal). The LCU item-set push must not contain the ranged-only id.
        res = loadout_resolver.resolve("Xin Zhao", "sr-collapsed:jg-bruiser", "sr")
        self.assertTrue(res.get("ok"), res)
        self.assertNotIn(_RUNAAN_NAME, res.get("raw_items") or [])
        item_cmd = res.get("item_cmd") or {}
        pushed = {
            str(it.get("id"))
            for blk in (item_cmd.get("blocks") or [])
            for it in (blk.get("items") or [])
        }
        self.assertNotIn(
            _RUNAAN_ID, pushed,
            "Runaan's (ranged-only) pushed to the LCU item-set for melee Xin Zhao",
        )


class SiblingMeleeSweepTests(unittest.TestCase):
    """The same resolver chokepoint feeds EVERY champion. No melee champion's
    served loadout (any mode, any build_path) may contain a ranged-only item.
    RED now for 47 melee champions; GREEN after the gate."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ranges = _attackrange_by_key()
        raw = json.loads(loadout_resolver._LOADOUTS_PATH.read_text(encoding="utf-8"))
        cls.champs = list((raw.get("champions") or {}).keys())

    def test_no_melee_champion_serves_a_ranged_only_item(self) -> None:
        offenders: list[str] = []
        for champ in self.champs:
            if not _is_melee(champ, self.ranges):
                continue
            for mode in ("sr", "aram", "arena"):
                for row in loadout_resolver.list_variants(champ, mode):
                    bad = _served_item_ids(row) & RANGED_ONLY_ITEM_IDS
                    if bad:
                        offenders.append(
                            f"{champ}/{mode}/{row.get('key')}: {sorted(bad)}"
                        )
        self.assertFalse(
            offenders,
            f"{len(offenders)} melee served-build(s) carry a ranged-only item:\n"
            + "\n".join(offenders[:60]),
        )


class NoOverFilterTests(unittest.TestCase):
    """Guard the fix is narrow: ranged champions KEEP Runaan's, and the
    melee-legal Terminus is NEVER stripped from a melee on-hit build."""

    def test_ranged_varus_keeps_runaan(self) -> None:
        served: set[str] = set()
        for mode in ("sr", "aram"):
            for row in loadout_resolver.list_variants("Varus", mode):
                served |= _served_item_ids(row)
        self.assertIn(
            _RUNAAN_ID, served,
            "Runaan's wrongly stripped from ranged marksman Varus (over-filter)",
        )

    def test_melee_irelia_keeps_terminus(self) -> None:
        # Irelia (melee) has an ARAM on-hit path with Terminus (melee-legal).
        # Terminus must survive the ranged-only gate; only Runaan's is stripped.
        served: set[str] = set()
        for row in loadout_resolver.list_variants("Irelia", "aram"):
            served |= _served_item_ids(row)
        self.assertIn(
            _TERMINUS_ID, served,
            "Terminus (melee-legal on-hit) wrongly stripped from melee Irelia",
        )
        self.assertNotIn(_RUNAAN_ID, served)


class RawDataGuardTests(unittest.TestCase):
    """Recurrence guard at the SOURCE. The serve-time gate sanitizes output,
    but the raw champion_loadouts.json must ALSO stay clean so a future
    autogen / align / hotfix run cannot silently re-pollute the data. Reads
    rank.py's authoritative RANGED_ONLY_ITEM_IDS (no local copy to drift)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ranges = _attackrange_by_key()
        cls.by_name = loadout_resolver._load_items_by_name()
        cls.raw = json.loads(
            loadout_resolver._LOADOUTS_PATH.read_text(encoding="utf-8")
        )

    def _ids(self, names: list[str]) -> set[str]:
        out: set[str] = set()
        for nm in names or []:
            rid = self.by_name.get(loadout_resolver._norm(nm))
            if rid:
                out.add(str(rid))
        return out

    def test_raw_data_has_no_ranged_only_on_melee(self) -> None:
        offenders: list[str] = []
        for champ, cd in (self.raw.get("champions") or {}).items():
            if not _is_melee(champ, self.ranges):
                continue
            for vk, var in (cd.get("variants") or {}).items():
                lists = [("(variant.items)", var.get("items") or [])]
                lists += [
                    (p.get("key"), p.get("items") or [])
                    for p in (var.get("build_paths") or [])
                ]
                for key, items in lists:
                    bad = self._ids(items) & RANGED_ONLY_ITEM_IDS
                    if bad:
                        offenders.append(f"{champ}/{vk}/{key}: {sorted(bad)}")
        self.assertFalse(
            offenders,
            f"{len(offenders)} raw melee row(s) carry a ranged-only item "
            f"(re-run tools/hotfix_ranged_only_melee_loadouts.py):\n"
            + "\n".join(offenders[:40]),
        )


class ModuleAsciiTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(raw) if b > 127]
        self.assertFalse(bad, f"non-ascii bytes at {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
