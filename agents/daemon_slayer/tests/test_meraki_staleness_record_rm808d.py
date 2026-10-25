"""RM-808 (d) - Meraki staleness, recorded per item.

The Meraki item snapshot the extractor vendors is stuck at content patch 25.15
(``data/daemon_slayer/<patch>/manifest.json`` ``meraki_items.content_patch``)
while DDragon and the game are at 16.21. CLAUDE.md Settled keeps Meraki as the
source for item PASSIVE FORMULAS, so every row where Meraki is stale is
recorded here with the source the engine follows instead, each against the
CommunityDragon 16.21 game data (``items.cdtb.bin.json``, Items/<id>
mDataValues, measured 2026-10-24):

  * 447100 Mirage Blade (Arena) - Blur dash / blink cooldown cut.
      Meraki 25.15: 12%, 4% for ultimates.  DDragon 16.20.1: 20% / 5%;
      16.21.1: 15% / 5%.  Game 16.21: DashCDPerHit 0.15, UltDashCDPerHit 0.05.
      Engine: follows DDragon in the note; the clause is NOT modeled
      (defensive_only, no proc), so no engine number depends on Meraki.
  * 443079 Turbo Chemtank (Arena) - Meraki 25.15 still describes the
      PRE-REWORK "Supercharged" active (cleanse + 3 s crowd-control immunity);
      DDragon 16.21.1 and the game describe the canister passive (pickup cuts
      the cooldown 15 s and restores 20% max HP; game 16.21 PickupCooldownRefund
      15, PickupHealthGain 0.20).  Engine: follows DDragon in the note; NOT
      modeled (defensive_only, no proc).
  * 6697 Hubris Eminence - Meraki 15 (+2 per stack) vs game 15 + 3 melee,
      x0.667 ranged: the engine follows the game data (RM-808 (a),
      test_hubris_eminence_cdragon_rm808a.py).
  * 6621 / 226621 / 326621 Dawncore First Light AP - Meraki 10 vs DDragon /
      game 15: the engine follows the game data and now models it (RM-808 (b),
      test_dawncore_first_light_ap_rm808b.py).

Each pin below reddens when its recorded Meraki claim stops parsing - i.e. when
a newer Meraki snapshot lands - which forces the re-check this record exists
for. Reverses if: Meraki publishes a content patch at or past the DDragon patch
(then re-derive every row here and drop the ones that agree).

ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer.effects import ITEM_EFFECTS

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _ddragon() -> dict:
    return json.loads(
        (_DATA_ROOT / _patch() / "items.json").read_text(encoding="utf-8")
    )["data"]


def _meraki() -> dict:
    return json.loads(
        (_DATA_ROOT / _patch() / "items_meraki.json").read_text(encoding="utf-8")
    )["items"]


def _plain(text: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", text or "")).strip()


def _meraki_text(row: dict) -> str:
    parts = []
    for key in ("passives", "active"):
        for p in row.get(key) or []:
            parts.append(f"{p.get('name')}: {p.get('effects')}")
    return " | ".join(parts)


# id -> (Meraki-claim regex, numbers it reads, live DDragon regex, numbers it
# reads, CommunityDragon 16.21 game values in the same order). A ``None`` number
# tuple marks a claim that is a mechanic, not a number.
RECORD: dict[str, tuple[str, tuple[float, ...] | None, str, tuple[float, ...], tuple[float, ...]]] = {
    "447100": (
        r"by (\d+)%, modified to (\d+)% for your ultimate",
        (12.0, 4.0),
        r"Dash and Blink Abilities by (\d+)% \(reduced to (\d+)% for Ultimates\)",
        (15.0, 5.0),
        (15.0, 5.0),
    ),
    "443079": (
        r"Supercharged: Removes all .*crowd control",
        None,
        r"reduces the Cooldown by (\d+) seconds and restores (\d+)% max Health",
        (15.0, 20.0),
        (15.0, 20.0),
    ),
}


class MerakiSnapshotAgeTests(unittest.TestCase):
    def test_meraki_content_patch_is_the_recorded_stale_one(self) -> None:
        manifest = json.loads(
            (_DATA_ROOT / _patch() / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["meraki_items"]["content_patch"], "25.15")


class PerItemRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ddragon = _ddragon()
        cls.meraki = _meraki()

    def test_record_is_not_empty(self) -> None:
        self.assertEqual(sorted(RECORD), ["443079", "447100"])

    def test_meraki_still_reads_the_stale_claim(self) -> None:
        for iid, (mk_re, mk_nums, _dd_re, _dd_nums, _game) in RECORD.items():
            with self.subTest(item_id=iid):
                text = _meraki_text(self.meraki[iid])
                found = re.search(mk_re, text, re.DOTALL)
                self.assertIsNotNone(
                    found,
                    f"Meraki no longer reads the recorded stale claim for {iid}: "
                    f"re-check the row (RM-808 d) - {text[:300]!r}",
                )
                if mk_nums is not None:
                    self.assertEqual(tuple(float(g) for g in found.groups()), mk_nums)

    def test_live_ddragon_agrees_with_the_game_data(self) -> None:
        for iid, (_mk_re, mk_nums, dd_re, dd_nums, game) in RECORD.items():
            with self.subTest(item_id=iid):
                found = re.search(dd_re, _plain(self.ddragon[iid]["description"]))
                self.assertIsNotNone(found)
                live = tuple(float(g) for g in found.groups())
                self.assertEqual(live, dd_nums)
                self.assertEqual(live, game)
                # The staleness is real: Meraki disagrees with the live source.
                self.assertNotEqual(mk_nums, live)

    def test_turbo_chemtank_meraki_has_no_canister_mechanic(self) -> None:
        text = _meraki_text(self.meraki["443079"]).lower()
        self.assertNotIn("cannister", text)
        self.assertNotIn("canister", text)
        self.assertIn("cannister", _plain(self.ddragon["443079"]["description"]).lower())

    def test_engine_rows_follow_ddragon_and_model_nothing(self) -> None:
        mirage = ITEM_EFFECTS["447100"]
        self.assertIn("15% (5% for ultimates)", mirage.note)
        self.assertNotIn("12%", mirage.note)
        chem = ITEM_EFFECTS["443079"]
        self.assertIn("canister", chem.note)
        self.assertIn("20% max HP", chem.note)
        self.assertNotIn("Supercharged", chem.note)
        for eff in (mirage, chem):
            with self.subTest(item_id=eff.item_id):
                self.assertTrue(eff.defensive_only)
                self.assertEqual(eff.periodics, ())
                self.assertEqual(eff.bonus_ap_stacked, 0.0)
                self.assertEqual(eff.takedown_bonus_ad_base, 0.0)

    def test_resolved_rows_follow_the_game_data_not_meraki(self) -> None:
        # Cross-references: the two Meraki-stale rows whose numbers ARE modeled.
        self.assertEqual(ITEM_EFFECTS["6697"].takedown_bonus_ad_per_stack, 3.0)
        for iid, ap in (("6621", 15.0), ("226621", 30.0), ("326621", 15.0)):
            with self.subTest(item_id=iid):
                self.assertEqual(ITEM_EFFECTS[iid].bonus_ap_stacked, ap)


if __name__ == "__main__":
    unittest.main()
