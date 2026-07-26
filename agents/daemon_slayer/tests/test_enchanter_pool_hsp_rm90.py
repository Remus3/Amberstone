"""RM-90 / RM-86 (c) - close the enchanter formulas-registry omissions.

`ds.hps` ranks ONLY the items curated in
`data/daemon_slayer/<patch>/enchanter_items.json` (`enchanter_only=True`,
`hps.py:871`); everything else "contributes zero (treated as non-enchanter
items)". That closed pool is the measured root cause of the champion-invariant
enchanter ranking - proven 2026-07-18 by forcing `apply_ability_hsp_amp` ON and
observing the 8-champion order stay byte-identical (RM-86 spec section 10), which
satisfied REFUTE condition 2 and moved finding (c) from RC-1 to RC-2.

This slice adds the genuinely missing Summoner's-Rift-legal heal-and-shield-power
legendaries. The candidate set was derived by scanning the WHOLE 16.14.1 catalog
for purchasable >=1500g items whose text implies heal / shield / HSP, NOT from a
hand-passed list - an earlier hand-passed list of "10 missing enchanter items"
proved to be roughly 80 percent wrong and is guarded against below.

ADDED (both are pure amp items - no direct heal/shield proc):
  * Dawncore 6621, 2500g, maps 11/12/21/35 - stat line "16% Heal and Shield
    Power". TERMINAL (into=None), so it genuinely enters the ranked pool.
  * Whispering Circlet 2526, 2250g, maps 11/12/21/35 - stat line "8% Heal and
    Shield Power". NON-TERMINAL - it builds into Diadem of Songs (2530) - so the
    terminal-only candidate filter drops it from the RANKING, exactly as it drops
    the already-registered component Forbidden Idol (3114). Registering it is
    still correct: compute_hps must credit its 8% amp when a real build holds it
    mid-transform. So the RANKED pool grows by ONE, not two.

Both take their STATED flat HSP stat as `heal_shield_amp_pct`, matching every
existing entry (Ardent 10% -> 0.10, Staff 10% -> 0.10, Mikael's 12% -> 0.12,
Redemption 10% -> 0.10).

DELIBERATELY NOT ADDED, each guarded by a test below so the category error cannot
recur:
  * 3869 / 3870 / 3871 / 3876 / 3877 - the World Atlas support-QUEST line. All
    400g with identical stats (200 HP, 75% base regens, 9 gold per 10s, ward
    charges). Mutually exclusive starter upgrades, not legendaries; ranking them
    against 2200g legendaries is a category error.
  * 3116 Rylai's, 4629 Cosmic Drive, 2065 Shurelya's, 3050 Zeke's Convergence,
    4402 Innervating Locket - real items, but ZERO heal/shield/HSP. Adding them
    with all-zero formulas would score only incidental AP and rank them last,
    which is the same pathology as flipping `enchanter_only=False` (that floats
    Rabadon's 4.370 above Mikael's 4.167).
  * 4016 Wordless Promise, 4011 Sword of Blossoming Dawn - real HSP items but
    ARENA-ONLY (`maps` is {30} alone).
  * 2530 Diadem of Songs - `gold.purchasable` is False; it is the Whispering
    Circlet transform target, not a purchasable candidate.
"""

import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import rank_items_by_hps
from agents.daemon_slayer.rank import _is_terminal

DAWNCORE = "6621"
WHISPERING_CIRCLET = "2526"

_REQUIRED_FIELDS = (
    "name",
    "heal_per_proc_base",
    "heal_per_proc_per_level",
    "heal_per_proc_ap_scaling",
    "heal_procs_per_second",
    "heal_targets_per_proc",
    "shield_per_proc_base",
    "shield_per_proc_per_level",
    "shield_per_proc_ap_scaling",
    "shield_procs_per_second",
    "shield_targets_per_proc",
    "heal_shield_amp_pct",
    "ally_buff_credit_per_second",
    "notes",
)


def _registry() -> dict:
    root = Path(__file__).resolve().parents[3]
    patch = (root / "data" / "daemon_slayer" / "current.txt").read_text().strip()
    path = root / "data" / "daemon_slayer" / patch / "enchanter_items.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


class RegistryAdditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = _registry()

    def test_dawncore_present_with_its_stated_hsp(self):
        self.assertIn(DAWNCORE, self.reg)
        self.assertAlmostEqual(self.reg[DAWNCORE]["heal_shield_amp_pct"], 0.16)

    def test_whispering_circlet_present_with_its_stated_hsp(self):
        self.assertIn(WHISPERING_CIRCLET, self.reg)
        self.assertAlmostEqual(self.reg[WHISPERING_CIRCLET]["heal_shield_amp_pct"], 0.08)

    def test_new_entries_are_pure_amp_no_invented_procs(self):
        # Neither item has a direct heal or shield in its text, so every proc
        # field must be zero. This is the guard against inventing throughput.
        for iid in (DAWNCORE, WHISPERING_CIRCLET):
            with self.subTest(item=iid):
                e = self.reg[iid]
                for f in _REQUIRED_FIELDS:
                    if f.startswith(("heal_per_proc", "shield_per_proc")) or f.endswith(
                        ("procs_per_second", "targets_per_proc")
                    ):
                        self.assertEqual(e[f], 0.0, f"{iid}.{f} must be 0.0")
                self.assertEqual(e["ally_buff_credit_per_second"], 0.0)

    def test_every_entry_carries_the_full_schema(self):
        for iid, entry in self.reg.items():
            with self.subTest(item=iid):
                for f in _REQUIRED_FIELDS:
                    self.assertIn(f, entry, f"{iid} missing {f}")
                self.assertTrue(str(entry["notes"]).strip(), f"{iid} needs notes")


class CategoryGuardTests(unittest.TestCase):
    """Each of these was on a hand-passed 'missing enchanter items' list and is
    wrong for a DIFFERENT reason. Guarding them individually so a future pass
    cannot re-add them without confronting the reason."""

    @classmethod
    def setUpClass(cls):
        cls.reg = _registry()
        cls.snap = DataSnapshot.load()

    def test_world_atlas_support_quest_line_absent(self):
        # 400g mutually-exclusive starter upgrades, not legendaries.
        for iid in ("3869", "3870", "3871", "3876", "3877"):
            with self.subTest(item=iid):
                self.assertNotIn(iid, self.reg)
                self.assertEqual(int(self.snap.items[iid]["gold"]["total"]), 400)

    def test_legendaries_without_any_heal_shield_absent(self):
        for iid in ("3116", "4629", "2065", "3050", "4402"):
            with self.subTest(item=iid):
                self.assertNotIn(iid, self.reg)

    def test_arena_only_hsp_items_absent(self):
        # Real HSP items, but maps is {30} alone - not SR-legal.
        for iid in ("4016", "4011"):
            with self.subTest(item=iid):
                self.assertNotIn(iid, self.reg)
                maps = {k for k, v in (self.snap.items[iid].get("maps") or {}).items() if v}
                self.assertEqual(maps, {"30"})

    def test_non_purchasable_transform_target_absent(self):
        self.assertNotIn("2530", self.reg)
        self.assertFalse(self.snap.items["2530"]["gold"]["purchasable"])


class RankerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ids(self, champ, **kw):
        res = rank_items_by_hps(self.snap, champ, 16, mode="SR", top_n=50, **kw)
        return [r.item_id for r in res.ranked]

    def test_dawncore_enters_the_ranked_pool(self):
        # Dawncore is terminal (into=None), so it is genuinely rankable.
        self.assertIn(DAWNCORE, self._ids("Soraka"))

    def test_whispering_circlet_is_registered_but_not_ranked(self):
        # It is NON-TERMINAL - it builds into Diadem of Songs (2530) - so the
        # terminal-only candidate filter correctly drops it, exactly as it drops
        # the already-registered component Forbidden Idol (3114). Registering it
        # is still right: compute_hps must credit its 8% amp when a real build
        # holds it mid-transform. Same registered-but-unranked shape as 3114.
        rec = self.snap.items[WHISPERING_CIRCLET]
        self.assertFalse(_is_terminal(rec))
        self.assertEqual(rec.get("into"), ["2530"])
        self.assertNotIn(WHISPERING_CIRCLET, self._ids("Soraka"))

    def test_pool_grew_by_exactly_one(self):
        # 9 rankable before this slice (10 registry entries less component 3114);
        # +1 for Dawncore. Whispering Circlet is registered but non-terminal.
        self.assertEqual(len(self._ids("Soraka")), 10)

    def test_ranking_stays_champion_invariant(self):
        # Adding pool members does NOT fix the invariance - it is a pool-CONTENT
        # problem, and these two are generic amp items. Pinned so nobody reads
        # this slice as a fix for RM-86 finding (c).
        champs = ["Soraka", "Janna", "Lulu", "Nami", "Sona", "Yuumi", "Milio", "Karma"]
        orders = {tuple(self._ids(c)) for c in champs}
        self.assertEqual(len(orders), 1)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.256.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self):
        with open(__file__, "rb") as fh:
            raw = fh.read()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII bytes in test file: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
