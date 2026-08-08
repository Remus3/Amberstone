"""RM-164 consumer wiring - the live NEXT BUY fallback must be lean-aware.

BEFORE this slice ``core/next_buy_fallback.py`` hardcoded
``_PREFERRED_BUCKET = "balanced"`` and ``fallback_build_ids`` read only that
bucket, so the flat DS build-order table's ``ad_heavy`` / ``ap_heavy`` columns
were computed, shipped on disk, and then discarded on a LIVE served-coaching
path (``dashboard/_liveclient.py`` calls ``fallback_build`` when the curated
``item_advisor.resolve_build`` table returns empty).

MEASURED against ``data/daemon_slayer/16.15.1/build_orders_<mode>.json``:
71 of 173 SR champions, 71 of 173 ARAM and 67 of 173 Arena have at least one
lean bucket whose order differs from ``balanced``. The headline case is
Alistar on SR, where the divergence is at the OPENING slot - ``balanced``
opens 3143 (Randuin's Omen, an ARMOR item) while ``ap_heavy`` opens 2504
(Kaenic Rookern), i.e. today's code serves armor into a full-AP enemy comp.

The enemy roster is already in scope at the call site: ``_liveclient`` builds
``enemy_team`` (Live Client ``allPlayers[].championName``, DISPLAY names) and
hands it to ``resolve_build`` on the line above. No new data source.

The lean classifier is REUSED, not reinvented:
``core.aram_comp_verdict.compute_factors`` (display names -> ad/ap counts) fed
to ``core.aram_item_interaction.shape_from_factors`` (counts -> the coarse
``"<ad_heavy|mixed|ap_heavy>/<frontline>"`` label). Its damage-axis threshold
is 4 of 5 enemies leaning one way.

Covers:
  * per-mode, per-champion property sweep - the returned ids equal EXACTLY the
    bucket the enemy lean names, for all 173 champions in all 3 modes
  * the Alistar SR opening-slot divergence, pinned end to end
  * the LIVE path really carries the lean (not just the function signature)
  * fail-soft - garbage comps, missing buckets, kill switch off, bad mode
"""
from __future__ import annotations

import contextlib
import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

from core import next_buy_fallback as nbf
from dashboard import _liveclient

_ROOT = Path(__file__).resolve().parent.parent
_DS_DIR = _ROOT / "data" / "daemon_slayer"

# Comps chosen so compute_factors puts 5 of 5 (>= the 4-of-5 threshold) on one
# damage axis. Verified in the sweep test below rather than assumed.
AP_COMP = ["Lux", "Ahri", "Syndra", "Veigar", "Brand"]
AD_COMP = ["Zed", "Jinx", "Caitlyn", "Tryndamere", "Garen"]
MIXED_COMP = ["Zed", "Lux", "Garen", "Ahri", "Jinx"]

# Live Client gameMode -> flat build-order table stem.
MODE_STEMS = (("CLASSIC", "sr"), ("ARAM", "aram"), ("CHERRY", "arena"))


def _table(stem: str) -> dict:
    patch = (_DS_DIR / "current.txt").read_text(encoding="utf-8").strip()
    raw = json.loads(
        (_DS_DIR / patch / f"build_orders_{stem}.json").read_text(encoding="utf-8")
    )
    return raw["build_orders"]


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


def _allgamedata(champ: str, enemies, game_mode: str = "CLASSIC") -> dict:
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
        "allPlayers": (
            [_player(champ, "ORDER")]
            + [_player(e, "CHAOS") for e in enemies]
        ),
        "gameData": {"gameTime": 900.0, "gameMode": game_mode},
    }


@contextlib.contextmanager
def _seeded(allgamedata):
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=allgamedata, ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        yield


def _summary(champ, enemies, game_mode="CLASSIC", flag="1") -> dict:
    env = dict(os.environ)
    env["RC_NEXTBUY_DS_FALLBACK"] = flag
    with mock.patch.dict(os.environ, env, clear=True):
        with _seeded(_allgamedata(champ, enemies, game_mode)):
            return _liveclient.liveclient_summary()


def _next_names(out: dict) -> list:
    return [r["name"] for r in (out.get("sr_items") or []) if r.get("next")]


class LeanClassificationTests(unittest.TestCase):
    """The comp -> bucket mapping itself, before any table lookup."""

    def test_comps_classify_as_intended(self):
        cases = ((AP_COMP, "ap_heavy"), (AD_COMP, "ad_heavy"),
                 (MIXED_COMP, "balanced"))
        for comp, expected in cases:
            with self.subTest(comp=tuple(comp)):
                self.assertEqual(nbf.preferred_bucket(comp), expected)

    def test_absent_or_empty_comp_is_balanced(self):
        for comp in (None, [], (), ["", "  ", None]):
            with self.subTest(comp=comp):
                self.assertEqual(nbf.preferred_bucket(comp), "balanced")

    def test_unknown_champion_names_do_not_manufacture_a_lean(self):
        # Unknown names are skipped by compute_factors, so a roster of pure
        # garbage resolves to zero counts and must NOT read as heavy either way.
        self.assertEqual(
            nbf.preferred_bucket(["Zzz", "Qqq", "Www", "Eee", "Rrr"]), "balanced"
        )

    def test_garbage_input_types_are_total(self):
        for comp in ("Lux", 12345, {"a": 1}, [None, {}, 7, object()], object()):
            with self.subTest(comp=repr(comp)):
                self.assertIn(nbf.preferred_bucket(comp),
                              ("balanced", "ad_heavy", "ap_heavy"))


class BucketSelectionPropertyTests(unittest.TestCase):
    """Property sweep: every champion, every mode, every lean.

    The invariant is mathematical - the emitted id list IS the named bucket -
    so it is asserted over the whole roster rather than at a hand-picked pin.
    """

    def test_every_champion_every_mode_gets_the_bucket_its_lean_names(self):
        for game_mode, stem in MODE_STEMS:
            table = _table(stem)
            self.assertEqual(len(table), 173, f"{stem} roster size changed")
            for champ, buckets in table.items():
                for comp, bucket in ((AP_COMP, "ap_heavy"),
                                     (AD_COMP, "ad_heavy"),
                                     (MIXED_COMP, "balanced")):
                    expected = [str(i) for i in buckets[bucket]]
                    got = nbf.fallback_build_ids(champ, game_mode, comp)
                    with self.subTest(mode=stem, champion=champ, bucket=bucket):
                        self.assertEqual(got, expected)

    def test_divergence_is_real_and_the_counts_are_what_was_filed(self):
        # Guards the sweep above against vacuity: if every lean bucket equalled
        # balanced, the sweep would pass while proving nothing.
        expected_counts = {"sr": 71, "aram": 71, "arena": 67}
        for _game_mode, stem in MODE_STEMS:
            table = _table(stem)
            diverging = sum(
                1 for b in table.values()
                if b["ad_heavy"] != b["balanced"] or b["ap_heavy"] != b["balanced"]
            )
            with self.subTest(mode=stem):
                self.assertEqual(diverging, expected_counts[stem])

    def test_omitting_the_comp_preserves_the_pre_slice_balanced_behavior(self):
        for game_mode, stem in MODE_STEMS:
            table = _table(stem)
            for champ, buckets in table.items():
                with self.subTest(mode=stem, champion=champ):
                    self.assertEqual(
                        nbf.fallback_build_ids(champ, game_mode),
                        [str(i) for i in buckets["balanced"]],
                    )


class AlistarOpeningSlotTests(unittest.TestCase):
    """The headline case - the divergence lands on the FIRST item bought."""

    RANDUINS = "3143"
    KAENIC = "2504"

    def test_ids_diverge_at_slot_zero(self):
        ap = nbf.fallback_build_ids("Alistar", "CLASSIC", AP_COMP)
        mixed = nbf.fallback_build_ids("Alistar", "CLASSIC", MIXED_COMP)
        self.assertEqual(ap[0], self.KAENIC)
        self.assertEqual(mixed[0], self.RANDUINS)

    def test_display_names_diverge_at_slot_zero(self):
        ap = nbf.fallback_build("Alistar", "CLASSIC", AP_COMP)
        mixed = nbf.fallback_build("Alistar", "CLASSIC", MIXED_COMP)
        self.assertEqual(ap[0], "Kaenic Rookern")
        self.assertEqual(mixed[0], "Randuin's Omen")


class LivePathTests(unittest.TestCase):
    """The wire, not the signature.

    A lean-aware function that the liveclient never hands a comp to is
    arithmetically inert - a known failure class in this repo - so the
    divergence is asserted through ``liveclient_summary`` itself.
    """

    def test_liveclient_serves_the_ap_bucket_against_an_ap_comp(self):
        names = _next_names(_summary("Alistar", AP_COMP))
        self.assertTrue(names)
        self.assertEqual(names[0], "Kaenic Rookern")

    def test_liveclient_serves_balanced_against_a_mixed_comp(self):
        names = _next_names(_summary("Alistar", MIXED_COMP))
        self.assertTrue(names)
        self.assertEqual(names[0], "Randuin's Omen")

    def test_kill_switch_off_yields_no_fallback_row(self):
        self.assertEqual(_next_names(_summary("Alistar", AP_COMP, flag="0")), [])

    def test_curated_champion_keeps_priority_under_every_lean(self):
        # resolve_build wins whenever it answers, so a curated champion's
        # sr_items must be byte-identical with the fallback ON and OFF. Note
        # resolve_build is ITSELF enemy-comp-aware (measured: Jinx opens
        # Phantom Dancer into AP_COMP and Immortal Shieldbow into MIXED_COMP),
        # so the comparison is per-comp - across comps it legitimately moves.
        for comp in (AP_COMP, AD_COMP, MIXED_COMP):
            on = _summary("Jinx", comp, flag="1").get("sr_items")
            off = _summary("Jinx", comp, flag="0").get("sr_items")
            with self.subTest(comp=tuple(comp)):
                self.assertTrue(on)
                self.assertEqual(json.dumps(on, sort_keys=True),
                                 json.dumps(off, sort_keys=True))


class FailSoftTests(unittest.TestCase):
    """Every public entry point stays total - nothing may raise into liveclient."""

    def test_bad_mode_and_bad_champion_return_empty(self):
        cases = (
            ("Alistar", "TFT", AP_COMP),
            ("Alistar", "PRACTICETOOL", AP_COMP),
            ("Alistar", None, AP_COMP),
            ("Alistar", 42, AP_COMP),
            ("NotAChampion", "CLASSIC", AP_COMP),
            ("", "CLASSIC", AP_COMP),
            (None, "CLASSIC", AP_COMP),
        )
        for champ, mode, comp in cases:
            with self.subTest(champion=champ, mode=mode):
                self.assertEqual(nbf.fallback_build_ids(champ, mode, comp), [])
                self.assertEqual(nbf.fallback_build(champ, mode, comp), [])

    def test_missing_preferred_bucket_degrades_to_balanced(self):
        stub = {"Alistar": {"balanced": ["1001", "1002"]}}
        with mock.patch.object(nbf, "_canon_table", return_value=stub):
            self.assertEqual(
                nbf.fallback_build_ids("Alistar", "CLASSIC", AP_COMP),
                ["1001", "1002"],
            )

    def test_empty_preferred_bucket_degrades_to_balanced(self):
        stub = {"Alistar": {"ap_heavy": [], "balanced": ["1001"]}}
        with mock.patch.object(nbf, "_canon_table", return_value=stub):
            self.assertEqual(
                nbf.fallback_build_ids("Alistar", "CLASSIC", AP_COMP), ["1001"]
            )

    def test_no_balanced_bucket_degrades_to_first_non_empty(self):
        stub = {"Alistar": {"ap_heavy": [], "ad_heavy": ["1004"]}}
        with mock.patch.object(nbf, "_canon_table", return_value=stub):
            self.assertEqual(
                nbf.fallback_build_ids("Alistar", "CLASSIC", AP_COMP), ["1004"]
            )

    def test_a_raising_classifier_does_not_propagate(self):
        with mock.patch.object(nbf, "preferred_bucket",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(nbf.fallback_build_ids("Alistar", "CLASSIC", AP_COMP), [])
            self.assertEqual(nbf.fallback_build("Alistar", "CLASSIC", AP_COMP), [])


if __name__ == "__main__":
    unittest.main()
