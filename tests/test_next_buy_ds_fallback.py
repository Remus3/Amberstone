"""RM-114 / item A-27 - widen the in-game NEXT BUY feed to the full roster.

BEFORE this slice ``item_advisor.resolve_build`` covered exactly 6 of 173
champions (Caitlyn / Jinx / Miss Fortune / Nilah / Tristana / Vayne - the
operator's own pool). Every other champion returned ``[]``, so
``dashboard/_liveclient.py`` emitted no ``sr_items`` row carrying
``next: true`` and ``web/js/lib/next_buy_model.js`` correctly rendered "-"
for the GOLD and TRINKET rows. The widget was faithful; the FEED was empty.

The fix re-sources the missing builds from the STATIC precomputed Daemon
Slayer build-order tables (``data/daemon_slayer/<patch>/build_orders_<mode>.json``)
as a FALLBACK ONLY - no live HTTP call to :8860, so nothing can stall the
liveclient path. The 6 curated builds keep PRIORITY: the DS table is
consulted only when ``resolve_build`` returns an empty list.

KEYSPACE - the flat table is DISPLAY-name keyed ("Miss Fortune",
"Nunu & Willump", "Kha'Zix"); the NEWER ``data/daemon_slayer/build_orders/<patch>/``
subdir is canonical-id keyed ("MissFortune", "Nunu", "Khazix"). This slice
joins on ``core.archetype_picks.canonical_champion_id`` applied to BOTH
sides so a display-name spelling drift cannot silently drop a champion.

Covers:
  * the 6 curated champions produce BYTE-IDENTICAL ``sr_items`` flag ON vs OFF
  * a previously-empty champion now emits a ``next: true`` row
  * kill switch ``RC_NEXTBUY_DS_FALLBACK=0`` restores exact current behavior
  * mode isolation - an Arena game never receives an SR-only item
  * fail-soft - unknown champion / unknown mode / missing table never raises
"""
from __future__ import annotations

import contextlib
import json
import os
import time
import unittest
from unittest import mock

from dashboard import _liveclient

# Ground truth measured 2026-07-24 against item_advisor.CHAMPION_BUILDS.
CURATED = ["Caitlyn", "Jinx", "Miss Fortune", "Nilah", "Tristana", "Vayne"]

# Ahri's SR balanced order carries these two; her Arena order carries
# NEITHER (measured from build_orders_{sr,arena}.json, patch 16.14.1).
AHRI_SR_ONLY = {"Rabadon's Deathcap", "Shadowflame"}
# ... and her Arena order carries these, which her SR order does not.
AHRI_ARENA_ONLY = {"Innervating Locket", "Demonic Embrace"}


def _item(name: str, item_id: str = "0") -> dict:
    return {"displayName": name, "itemID": item_id, "canUse": False, "count": 1}


def _player(champ: str, team: str, owned=None) -> dict:
    return {
        "summonerName": champ,
        "championName": champ,
        "team": team,
        "items": [_item(n) for n in (owned or [])],
        "scores": {"kills": 1, "deaths": 1, "assists": 1,
                   "creepScore": 50, "wardScore": 0.0},
        "summonerSpells": {},
        "level": 9,
    }


def _allgamedata(champ: str, game_mode: str = "CLASSIC", owned=None) -> dict:
    """Minimal but realistic Live Client /allgamedata for one champion."""
    return {
        "activePlayer": {
            "summonerName": champ,
            "level": 9,
            "currentGold": 1500,
            "championStats": {
                "currentHealth": 800, "maxHealth": 1000,
                "resourceValue": 200, "resourceMax": 300,
            },
        },
        "allPlayers": [
            _player(champ, "ORDER", owned=owned),
            _player("Zed", "CHAOS"),
            _player("Lux", "CHAOS"),
        ],
        "gameData": {"gameTime": 900.0, "gameMode": game_mode},
    }


@contextlib.contextmanager
def _seeded(allgamedata):
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=allgamedata, ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        yield


def _summary(champ, game_mode="CLASSIC", owned=None, flag="1") -> dict:
    """liveclient_summary() for one champion at a given kill-switch value."""
    env = dict(os.environ)
    if flag is None:
        env.pop("RC_NEXTBUY_DS_FALLBACK", None)
    else:
        env["RC_NEXTBUY_DS_FALLBACK"] = flag
    with mock.patch.dict(os.environ, env, clear=True):
        with _seeded(_allgamedata(champ, game_mode, owned)):
            return _liveclient.liveclient_summary()


def _next_names(out: dict) -> list:
    return [r["name"] for r in (out.get("sr_items") or []) if r.get("next")]


class CuratedSixUnchangedTests(unittest.TestCase):
    """The 6 curated builds keep PRIORITY and must come through byte-identical."""

    def test_curated_six_sr_items_byte_identical_flag_on_vs_off(self):
        owned_states = [
            [],
            ["Doran's Blade"],
            ["Berserker's Greaves", "Blade of The Ruined King"],
        ]
        for champ in CURATED:
            for owned in owned_states:
                on = _summary(champ, "CLASSIC", owned, flag="1")
                off = _summary(champ, "CLASSIC", owned, flag="0")
                with self.subTest(champion=champ, owned=tuple(owned)):
                    self.assertEqual(
                        json.dumps(on.get("sr_items"), sort_keys=True),
                        json.dumps(off.get("sr_items"), sort_keys=True),
                    )
                    # A curated champion must actually HAVE a build - otherwise
                    # the byte-identity above would be a vacuous [] == [].
                    self.assertTrue(_next_names(on))

    def test_curated_boots_phase_unchanged_by_flag(self):
        for champ in CURATED:
            on = _summary(champ, "CLASSIC", [], flag="1")
            off = _summary(champ, "CLASSIC", [], flag="0")
            with self.subTest(champion=champ):
                self.assertEqual(on.get("sr_boots_phase"),
                                 off.get("sr_boots_phase"))


class WidenedCoverageTests(unittest.TestCase):
    """Previously-empty champions now emit a next-buy row."""

    def test_previously_empty_champion_emits_next_row(self):
        out = _summary("Aatrox", "CLASSIC", [], flag="1")
        names = _next_names(out)
        self.assertTrue(names, "Aatrox should now receive a DS fallback build")
        self.assertIn("Blade of The Ruined King", names)

    def test_apostrophe_and_ampersand_champions_resolve(self):
        # Display-name keyspace edge cases: the join must not drop these.
        for champ in ("Kha'Zix", "Nunu & Willump", "Wukong", "Miss Fortune"):
            with self.subTest(champion=champ):
                out = _summary(champ, "CLASSIC", [], flag="1")
                self.assertTrue(_next_names(out))

    def test_full_roster_coverage_is_widened(self):
        from core.next_buy_fallback import fallback_build
        import json as _json
        from pathlib import Path
        root = Path(_liveclient.__file__).resolve().parent.parent
        ds = root / "data" / "daemon_slayer"
        patch = (ds / "current.txt").read_text(encoding="utf-8").strip()
        table = _json.loads(
            (ds / patch / "build_orders_sr.json").read_text(encoding="utf-8")
        )["build_orders"]
        covered = [c for c in table if fallback_build(c, "CLASSIC")]
        self.assertEqual(len(covered), len(table))
        self.assertGreaterEqual(len(covered), 173)


class KillSwitchTests(unittest.TestCase):
    def test_flag_zero_restores_empty_feed(self):
        out = _summary("Aatrox", "CLASSIC", [], flag="0")
        self.assertEqual(_next_names(out), [])

    def test_default_is_on_when_env_absent(self):
        out = _summary("Aatrox", "CLASSIC", [], flag=None)
        self.assertTrue(_next_names(out))


class ModeIsolationTests(unittest.TestCase):
    def test_arena_never_receives_sr_only_item(self):
        out = _summary("Ahri", "CHERRY", [], flag="1")
        names = set(_next_names(out))
        self.assertTrue(names)
        self.assertFalse(names & AHRI_SR_ONLY,
                         f"SR-only item leaked into Arena: {names & AHRI_SR_ONLY}")
        self.assertTrue(names & AHRI_ARENA_ONLY)

    def test_sr_never_receives_arena_only_item(self):
        out = _summary("Ahri", "CLASSIC", [], flag="1")
        names = set(_next_names(out))
        self.assertTrue(names)
        self.assertFalse(names & AHRI_ARENA_ONLY)

    def test_aram_uses_aram_table(self):
        from core.next_buy_fallback import fallback_build_ids
        # Jinx's ARAM balanced order diverges from SR at index 4
        # (126697 vs 6697) - measured, patch 16.14.1.
        self.assertNotEqual(fallback_build_ids("Jinx", "ARAM"),
                            fallback_build_ids("Jinx", "CLASSIC"))

    def test_unmapped_mode_falls_through_to_empty(self):
        # PRACTICETOOL / TFT / garbage have no table stem -> today's behavior.
        for gm in ("PRACTICETOOL", "TFT", "STRAWBERRY", "GARBAGE", ""):
            with self.subTest(game_mode=gm):
                out = _summary("Aatrox", gm, [], flag="1")
                self.assertEqual(_next_names(out), [])


class FailSoftTests(unittest.TestCase):
    def test_unknown_champion_returns_empty_without_raising(self):
        from core.next_buy_fallback import fallback_build
        self.assertEqual(fallback_build("NotAChampion", "CLASSIC"), [])
        self.assertEqual(fallback_build("", "CLASSIC"), [])
        self.assertEqual(fallback_build(None, "CLASSIC"), [])

    def test_bad_mode_returns_empty_without_raising(self):
        from core.next_buy_fallback import fallback_build
        for gm in (None, "", 17, object()):
            self.assertEqual(fallback_build("Aatrox", gm), [])

    def test_missing_table_degrades_to_empty(self):
        from core import next_buy_fallback as nbf
        nbf.reset_cache()
        with mock.patch(
            "core.laning_scenario_precompute.load_build_orders",
            side_effect=OSError("boom"),
        ):
            self.assertEqual(nbf.fallback_build("Aatrox", "CLASSIC"), [])
        nbf.reset_cache()

    def test_malformed_table_degrades_to_empty(self):
        from core import next_buy_fallback as nbf
        nbf.reset_cache()
        with mock.patch(
            "core.laning_scenario_precompute.load_build_orders",
            return_value={"Aatrox": "not-a-dict"},
        ):
            self.assertEqual(nbf.fallback_build("Aatrox", "CLASSIC"), [])
        nbf.reset_cache()

    def test_summary_never_raises_on_fallback_error(self):
        with mock.patch("core.next_buy_fallback.fallback_build",
                        side_effect=RuntimeError("boom")):
            out = _summary("Aatrox", "CLASSIC", [], flag="1")
        self.assertIsInstance(out, dict)
        self.assertEqual(_next_names(out), [])


class PipelineParityTests(unittest.TestCase):
    """The fallback build must go THROUGH the existing pipeline, not around it."""

    def test_owned_items_are_not_repeated_as_next(self):
        owned = ["Blade of The Ruined King"]
        out = _summary("Aatrox", "CLASSIC", owned, flag="1")
        self.assertNotIn("Blade of The Ruined King", _next_names(out))
        owned_rows = [r for r in out["sr_items"] if r.get("owned")]
        self.assertEqual([r["name"] for r in owned_rows], owned)

    def test_is_redundant_still_filters_fallback_items(self):
        from item_advisor import is_redundant
        out = _summary("Aatrox", "CLASSIC", [], flag="1")
        for name in _next_names(out):
            redundant, _why = is_redundant(name, [])
            self.assertFalse(redundant)

    def test_boots_phase_still_emitted_for_fallback_champion(self):
        out = _summary("Aatrox", "CLASSIC", [], flag="1")
        self.assertIn("sr_boots_phase", out)

    def test_sr_items_capped_at_nine(self):
        out = _summary("Aatrox", "CLASSIC", [], flag="1")
        self.assertLessEqual(len(out.get("sr_items") or []), 9)


if __name__ == "__main__":
    unittest.main()
