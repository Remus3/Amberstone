"""RM-804 - DDragon passive-text numbers the engine does not take from DDragon.

DDragon 16.21.1 moved numbers inside the passive PROSE (not the ``<stats>``
block) of seven engine-registered items. The RM-766 verifier listed them from
the 16.20.1 -> 16.21.1 description diff; none had a guard, so a stale number in
an engine note (Turbo Chemtank "4% max HP") survived the patch silently.

Source doctrine (CLAUDE.md Settled): item PEN / LETHALITY magnitudes come from
DDragon ``<stats>`` only (``tests/test_item_pen_ddragon_sync.py``); Meraki
stays the source for item PASSIVE FORMULAS. The Meraki snapshot at 16.21.1 is
unchanged for all seven (content patch 25.15), and every clause DDragon moved
is one the engine does NOT model numerically, so no modeled number moves:

  * 443079 Turbo Chemtank - canister heal 4% -> 20% max HP (not modeled).
  * 6621 / 226621 / 326621 Dawncore - First Light AP per 100% base mana regen
    10 -> 15 (AP half not modeled; the modeled HSP half, 2% / 3% / 2% per
    step in ``_scaling_hsp``, did not move).
  * 444636 Night Harvester (Arena) - Soulrend Move Speed 40% -> 60%, duration
    1.5 -> 1 s (MS not modeled; the modeled Soulrend damage did not move).
  * 447100 Mirage Blade - Blur dash / blink cooldown cut 20% -> 15% (5% for
    ultimates; not modeled).
  * 447110 Moonflair Spellblade - Relentless empowered attacks 2 -> 3, cooldown
    cut per attack 0.5 -> 0.3 s (not modeled).
  * 2520 Bastionbreaker - Sabotage duration 90 -> 25000 s (utility-only, not
    modeled; looks like an upstream placeholder, Meraki still reads 90).
  * 6697 / 226697 Hubris - every Eminence number is GONE from the 16.21.1
    prose, so DDragon cannot be the source. RM-804 kept the Meraki
    15 (+2 per stack) on both rows; RM-808 (a) then settled the SR row on the
    CommunityDragon 16.21 game data (15 + 3 melee, x0.667 ranged), which also
    explains DDragon 16.20.1's 12 + 3 (the 16.20 bin read the same). The
    Arena row still equals Meraki's 15 (+2).

What this module pins:

  1. ``test_live_ddragon_matches_the_reviewed_numbers`` - the current.txt
     DDragon prose still carries the numbers reviewed at 16.21.1. It reddens on
     the next patch that moves one, which forces the re-review RM-766 missed.
  2. ``test_engine_note_cites_the_live_ddragon_numbers`` - every engine note
     that quotes one of these clauses quotes the live DDragon number (it
     FAILED before the RM-804 fix on all seven cited rows).
  3. the unmodeled clauses carry no engine credit, and the modeled halves
     (Dawncore HSP, Hubris Eminence) follow their recorded sources, each as a
     computed quantity.

ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import math
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._scaling_hsp import (
    SCALING_HSP_PER_MANA_REGEN_STEP,
    sum_scaling_hsp_pct,
)
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    collect_effects,
    total_takedown_bonus_ad,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

_NUM = r"(\d+(?:\.\d+)?)"

# id -> (DDragon prose regex, numbers reviewed at DDragon 16.21.1, note regex).
# The prose regex runs over the tag-stripped description; the note regex over
# ITEM_EFFECTS[id].note. A ``None`` note regex means the engine note does not
# quote the clause (2520 Sabotage: utility-only, the figure is a placeholder).
_DAWNCORE_PROSE = rf"and {_NUM} Ability Power per 100% Base Mana Regen"
_DAWNCORE_NOTE = rf"{_NUM} AP per 100% base mana regen"
REVIEWED: dict[str, tuple[str, tuple[float, ...], str | None]] = {
    "443079": (
        rf"restores {_NUM}% max Health",
        (20.0,),
        rf"restor(?:es|ing) {_NUM}% max HP",
    ),
    "6621": (_DAWNCORE_PROSE, (15.0,), _DAWNCORE_NOTE),
    "226621": (_DAWNCORE_PROSE, (15.0,), _DAWNCORE_NOTE),
    "326621": (_DAWNCORE_PROSE, (15.0,), _DAWNCORE_NOTE),
    "444636": (
        rf"grants you {_NUM}% Move Speed for {_NUM} seconds",
        (60.0, 1.0),
        rf"{_NUM}% move speed for {_NUM} ?s",
    ),
    "447100": (
        rf"Dash and Blink Abilities by {_NUM}% \(reduced to {_NUM}% for Ultimates\)",
        (15.0, 5.0),
        rf"by {_NUM}% \({_NUM}% for ultimates\)",
    ),
    "447110": (
        rf"for your next {_NUM} Attacks\b.*?Cooldowns by {_NUM} seconds",
        (3.0, 0.3),
        rf"next {_NUM} attacks\b.*?by {_NUM} ?s\b",
    ),
    "2520": (
        rf"grants Sabotage for {_NUM} seconds",
        (25000.0,),
        None,
    ),
}

# Clauses the engine deliberately does not model: these rows must stay
# defensive_only with no periodic proc (the canister heal, the First Light AP
# half, Blur, Relentless).
UNMODELED_DEFENSIVE_ONLY = ("443079", "6621", "226621", "326621", "447100", "447110")

_HUBRIS_IDS = ("6697", "226697", "126697")

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _current_patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _ddragon_items() -> dict:
    path = _DATA_ROOT / _current_patch() / "items.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _meraki_items() -> dict:
    path = _DATA_ROOT / _current_patch() / "items_meraki.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def _plain(text: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", text or "")).strip()


def _numbers(pattern: str, text: str) -> tuple[float, ...] | None:
    found = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if found is None:
        return None
    return tuple(float(g) for g in found.groups())


class LiveDdragonReviewTests(unittest.TestCase):
    """The DDragon prose numbers still read what RM-804 reviewed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = _current_patch()
        cls.ddragon = _ddragon_items()

    def test_reviewed_table_is_not_empty(self) -> None:
        # An empty table would pass every loop below vacuously.
        self.assertEqual(len(REVIEWED), 8)
        self.assertEqual(sum(1 for row in REVIEWED.values() if row[2]), 7)

    def test_live_ddragon_matches_the_reviewed_numbers(self) -> None:
        for iid, (prose, reviewed, _note) in REVIEWED.items():
            with self.subTest(item_id=iid):
                self.assertIn(iid, self.ddragon, f"{iid} missing at DDragon {self.patch}")
                text = _plain(self.ddragon[iid].get("description", ""))
                live = _numbers(prose, text)
                self.assertIsNotNone(
                    live,
                    f"{iid} clause no longer parses at DDragon {self.patch}: re-review "
                    "the engine row against the new prose (RM-804) and update REVIEWED",
                )
                self.assertEqual(
                    live, reviewed,
                    f"DDragon {self.patch} moved {iid} "
                    f"{self.ddragon[iid].get('name')} {reviewed} -> {live}: re-review the "
                    "engine row (RM-804), then update REVIEWED and the engine note",
                )


class EngineNoteSyncTests(unittest.TestCase):
    """Engine notes that quote a moved clause quote the LIVE DDragon number."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = _current_patch()
        cls.ddragon = _ddragon_items()

    def test_engine_note_cites_the_live_ddragon_numbers(self) -> None:
        for iid, (prose, _reviewed, note_re) in REVIEWED.items():
            if note_re is None:
                continue
            with self.subTest(item_id=iid):
                live = _numbers(prose, _plain(self.ddragon[iid].get("description", "")))
                self.assertIsNotNone(live)
                note = ITEM_EFFECTS[iid].note
                cited = _numbers(note_re, note)
                self.assertIsNotNone(
                    cited, f"{iid} note does not quote the clause: {note!r}"
                )
                self.assertEqual(
                    cited, live,
                    f"{iid} note quotes {cited}, DDragon {self.patch} reads {live}",
                )

    def test_note_regexes_reject_the_pre_fix_wording(self) -> None:
        # The 1.289.0 notes, verbatim: each must fail its own row, so a revert
        # cannot pass test_engine_note_cites_the_live_ddragon_numbers. The
        # Turbo Chemtank note still parses (4%), so it fails on the VALUE.
        stale = {
            "443079": (
                "Turbo Chemtank: CC-immunity canister mechanic - ignore next "
                "immobilize, drop canister restoring 4% max HP. CC mitigation + "
                "heal, no DPS proc"
            ),
            "447110": (
                "Moonflair Spellblade: Relentless resets basic attack timer and "
                "empowers next 2 attacks after ability cast - attack-reset/haste "
                "mechanic, not a simple damage proc (ability-cast schema gap)"
            ),
        }
        for iid, note in stale.items():
            with self.subTest(item_id=iid):
                live = _numbers(
                    REVIEWED[iid][0], _plain(self.ddragon[iid].get("description", ""))
                )
                self.assertNotEqual(_numbers(REVIEWED[iid][2], note), live)
        self.assertEqual(_numbers(REVIEWED["443079"][2], stale["443079"]), (4.0,))


class UnmodeledClauseTests(unittest.TestCase):
    """The moved clauses earn no engine credit - nothing numeric to re-pin."""

    def test_unmodeled_rows_stay_defensive_only_without_procs(self) -> None:
        for iid in UNMODELED_DEFENSIVE_ONLY:
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS[iid]
                self.assertTrue(eff.defensive_only)
                self.assertEqual(eff.periodics, ())
                self.assertEqual(eff.takedown_bonus_ad_base, 0.0)

    def test_night_harvester_credits_soulrend_damage_only(self) -> None:
        # Soulrend's MS lives in passive prose only; DDragon's structured stats
        # carry no PercentMovementSpeedMod for 444636, so the R58 MS-utility
        # seam (structured stats) reads nothing either.
        eff = ITEM_EFFECTS["444636"]
        self.assertEqual([p.name for p in eff.periodics], ["Soulrend"])
        self.assertNotIn("PercentMovementSpeedMod", _ddragon_items()["444636"]["stats"])

    def test_bastionbreaker_sabotage_is_not_credited(self) -> None:
        eff = ITEM_EFFECTS["2520"]
        self.assertEqual([p.name for p in eff.periodics], ["Shaped Charge"])
        self.assertEqual(eff.takedown_bonus_ad_base, 0.0)
        self.assertEqual(eff.takedown_bonus_ad_per_stack, 0.0)


class ModeledHalfSourceTests(unittest.TestCase):
    """The modeled halves of the moved clauses follow their recorded sources."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ddragon = _ddragon_items()
        cls.meraki = _meraki_items()

    def test_dawncore_hsp_step_follows_the_live_first_light_prose(self) -> None:
        # The HSP half of First Light did not move at 16.21.1 (2% / 3% / 2%).
        for iid, step in SCALING_HSP_PER_MANA_REGEN_STEP.items():
            with self.subTest(item_id=iid):
                text = _plain(self.ddragon[iid]["description"])
                live = _numbers(rf"Gain {_NUM}% Heal and Shield Power and", text)
                self.assertIsNotNone(live)
                self.assertAlmostEqual(step * 100.0, live[0], places=9)
                # Steps come from the item's own PRINTED regen (R197 reading:
                # floor(printed / 100)), re-derived here from the <stats> block:
                # SR 100% -> 1, Arena 200% -> 2, ARAM 150% -> 1.
                block = re.search(
                    r"<stats>(.*?)</stats>", self.ddragon[iid]["description"], re.DOTALL
                )
                self.assertIsNotNone(block)
                printed = _numbers(rf"{_NUM}% Base Mana Regen", _plain(block.group(1)))
                self.assertIsNotNone(printed)
                self.assertAlmostEqual(
                    sum_scaling_hsp_pct([iid]),
                    math.floor(printed[0] / 100.0) * step,
                    places=12,
                )

    def test_hubris_eminence_follows_meraki(self) -> None:
        # RM-808 (a) settled the SR row on the CommunityDragon 16.21 game data
        # (15 + 3 melee, ranged split; test_hubris_eminence_cdragon_rm808a.py),
        # where Meraki 25.15 is stale. The Arena and ARAM rows' MELEE values
        # still equal Meraki's 15 (+2), which is what this pin keeps.
        eminence = [
            p for p in self.meraki["6697"]["passives"] if p.get("name") == "Eminence"
        ]
        self.assertEqual(len(eminence), 1)
        found = re.search(
            r"\{\{as\|(\d+)\|ad\}\} \(\+ (\d+) per stack\)", eminence[0]["effects"]
        )
        self.assertIsNotNone(found, eminence[0]["effects"])
        base, per_stack = float(found.group(1)), float(found.group(2))
        for iid in ("226697", "126697"):
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS[iid]
                self.assertEqual(
                    (eff.takedown_bonus_ad_base, eff.takedown_bonus_ad_per_stack),
                    (base, per_stack),
                )
                # Computed: one assumed stack -> base + per_stack bonus AD.
                self.assertAlmostEqual(
                    total_takedown_bonus_ad(collect_effects([iid]), 1.0),
                    base + per_stack,
                    places=12,
                )

    def test_hubris_ddragon_prose_renders_no_eminence_numbers(self) -> None:
        # Why the engine cannot take Eminence from DDragon at 16.21.1. Reverses
        # if: DDragon renders the numbers again - then re-check the SR row
        # against them (16.20.1 SR read 12 + 3 per champion killed).
        for iid in ("6697", "226697"):
            with self.subTest(item_id=iid):
                text = _plain(self.ddragon[iid]["description"])
                clause = text.split("Eminence", 1)[1]
                self.assertIsNone(
                    re.search(r"gain \d", clause),
                    f"DDragon renders Eminence numbers again for {iid}: {clause!r}",
                )


if __name__ == "__main__":
    unittest.main()
