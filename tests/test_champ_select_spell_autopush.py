"""CS2 - LCU summoner-spell auto-push (Flash+Teleport SR default).

Operator-reported bug: on first champ-select load the League client
defaults summoner spells to Flash+Heal or Flash+Teleport at RANDOM,
forcing a manual fix every game. RC already reads the intended pair
from data/spell_prefs.json (sr_mode=teleport -> Flash+Teleport) but the
pre-CS2 RuneWriter only pushed spells ONCE, as a side-effect of a
successful rune-page write. If the rune POST failed (3-page account cap)
or the client re-randomised spells after RC's single push, the wrong
spells stuck.

CS2 makes the spell push self-correcting and independent of the rune
write: every champ-select poll, compare the live spells against the
intended pair and PATCH /lol-champ-select/v1/session/my-selection only
when they differ. These tests pin:

  1. resolve_spell_pair() returns the intended (s1, s2) per mode from the
     existing spell_prefs.json source (Flash+TP for SR, Flash+Snowball
     for ARAM).
  2. RuneWriter._sync_spells() PATCHes the my-selection body shape
     {spell1Id, spell2Id} when the live pair differs.
  3. It is idempotent - no PATCH fires when the live pair already matches.
  4. It fails soft - no PATCH / no crash when not in champ-select, when
     the local cell is missing, or when LCU calls error.

Uses a fake LCU client (mirrors the lcu_pregame.set_summoner_spells
contract) - never touches a live client.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from lcu.lcu_rune_writer import RuneWriter, resolve_spell_pair  # noqa: E402

_FLASH = 4
_TELEPORT = 12
_HEAL = 7
_SNOWBALL = 32
_MYSEL = "/lol-champ-select/v1/session/my-selection"


class _FakeLcu:
    """Minimal fake of the LcuClient surface RuneWriter._sync_spells uses.

    Records every _request call. set_summoner_spells mirrors the real
    lcu_pregame.LcuPregame.set_summoner_spells idempotency contract: it
    only PATCHes when current_pair differs from the target.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def _request(self, method, path, data=None):
        self.calls.append({"method": method, "path": path, "data": data})
        return {"ok": True}

    def set_summoner_spells(self, s1, s2, *, current_pair=None):
        if current_pair is not None:
            try:
                cur = (int(current_pair[0]), int(current_pair[1]))
            except (ValueError, IndexError, TypeError):
                cur = (0, 0)
            if cur == (int(s1), int(s2)):
                return True
        return self._request("PATCH", _MYSEL,
                             data={"spell1Id": s1, "spell2Id": s2}) is not None

    @staticmethod
    def _session(my_cell, s1, s2):
        return {
            "localPlayerCellId": my_cell,
            "myTeam": [
                {"cellId": my_cell, "spell1Id": s1, "spell2Id": s2},
                {"cellId": my_cell + 1, "spell1Id": 0, "spell2Id": 0},
            ],
        }

    def _patches(self):
        return [c for c in self.calls
                if c["method"] == "PATCH" and c["path"] == _MYSEL]


class ResolveSpellPairTests(unittest.TestCase):
    def test_sr_default_is_flash_teleport(self):
        # spell_prefs.json sr_mode=teleport - exactly what the operator wants.
        self.assertEqual(resolve_spell_pair("Caitlyn", "CLASSIC"),
                         (_FLASH, _TELEPORT))

    def test_aram_default_is_flash_snowball(self):
        self.assertEqual(resolve_spell_pair("Caitlyn", "ARAM"),
                         (_FLASH, _SNOWBALL))

    def test_kiwi_mayhem_routes_to_aram_pair(self):
        # ARAM Mayhem reports gameMode=KIWI; it must use the ARAM pair.
        self.assertEqual(resolve_spell_pair("Ziggs", "KIWI"),
                         (_FLASH, _SNOWBALL))

    def test_returns_two_positive_ints(self):
        s1, s2 = resolve_spell_pair("Lux", "CLASSIC")
        self.assertIsInstance(s1, int)
        self.assertIsInstance(s2, int)
        self.assertGreater(s1, 0)
        self.assertGreater(s2, 0)


class SyncSpellsTests(unittest.TestCase):
    def setUp(self):
        self.lcu = _FakeLcu()
        self.rw = RuneWriter(self.lcu)

    def test_patch_fires_when_live_spells_differ(self):
        # Client randomised Flash+Heal; intended is Flash+Teleport (SR).
        sess = _FakeLcu._session(0, _FLASH, _HEAL)
        out = self.rw._sync_spells(sess, "CLASSIC")
        self.assertTrue(out)
        patches = self.lcu._patches()
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]["data"],
                         {"spell1Id": _FLASH, "spell2Id": _TELEPORT})

    def test_body_shape_is_spell1id_spell2id(self):
        sess = _FakeLcu._session(0, _HEAL, _FLASH)
        self.rw._sync_spells(sess, "CLASSIC")
        body = self.lcu._patches()[0]["data"]
        self.assertIn("spell1Id", body)
        self.assertIn("spell2Id", body)
        self.assertEqual(set(body.keys()), {"spell1Id", "spell2Id"})

    def test_idempotent_no_patch_when_already_correct(self):
        # Live spells already Flash+Teleport - no LCU write should fire.
        sess = _FakeLcu._session(0, _FLASH, _TELEPORT)
        out = self.rw._sync_spells(sess, "CLASSIC")
        self.assertTrue(out)
        self.assertEqual(len(self.lcu._patches()), 0)

    def test_aram_corrects_to_flash_snowball(self):
        sess = _FakeLcu._session(2, _FLASH, _HEAL)
        self.rw._sync_spells(sess, "ARAM")
        self.assertEqual(self.lcu._patches()[0]["data"],
                         {"spell1Id": _FLASH, "spell2Id": _SNOWBALL})

    def test_failsoft_when_session_none(self):
        out = self.rw._sync_spells(None, "CLASSIC")
        self.assertFalse(out)
        self.assertEqual(len(self.lcu.calls), 0)

    def test_failsoft_when_not_a_dict(self):
        out = self.rw._sync_spells("not a session", "CLASSIC")
        self.assertFalse(out)
        self.assertEqual(len(self.lcu.calls), 0)

    def test_failsoft_when_local_cell_missing_from_team(self):
        # localPlayerCellId points at a cell not present in myTeam.
        sess = {
            "localPlayerCellId": 9,
            "myTeam": [{"cellId": 0, "spell1Id": _FLASH, "spell2Id": _HEAL}],
        }
        out = self.rw._sync_spells(sess, "CLASSIC")
        self.assertFalse(out)
        self.assertEqual(len(self.lcu._patches()), 0)

    def test_failsoft_when_set_raises(self):
        class _Boom(_FakeLcu):
            def set_summoner_spells(self, *a, **k):
                raise RuntimeError("lcu down")

        boom = _Boom()
        rw = RuneWriter(boom)
        sess = _FakeLcu._session(0, _FLASH, _HEAL)
        # Must swallow and return False, never propagate.
        out = rw._sync_spells(sess, "CLASSIC")
        self.assertFalse(out)


class SyncSpellsCalledEveryPollTests(unittest.TestCase):
    """CS2 core: spell sync must run on every champ-select poll,
    independent of whether a rune write happened or succeeded."""

    def test_poll_syncs_spells_even_without_champion_selected(self):
        # No champion picked yet (champ_id/intent 0) - the old code
        # early-returned before touching spells. CS2 must still correct
        # the randomised default while the operator is mid-pick.
        sess = {
            "localPlayerCellId": 0,
            "myTeam": [{"cellId": 0, "championId": 0,
                        "championPickIntent": 0,
                        "spell1Id": _FLASH, "spell2Id": _HEAL}],
            "actions": [],
        }

        class _PollLcu(_FakeLcu):
            def get_champ_select(self):
                return sess

        poll_lcu = _PollLcu()
        rw = RuneWriter(poll_lcu)

        # Force SR mode detection without a live lobby.
        rw._detect_game_mode = lambda: "CLASSIC"  # type: ignore[method-assign]

        rw._poll()

        patches = poll_lcu._patches()
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]["data"],
                         {"spell1Id": _FLASH, "spell2Id": _TELEPORT})


if __name__ == "__main__":
    unittest.main()
