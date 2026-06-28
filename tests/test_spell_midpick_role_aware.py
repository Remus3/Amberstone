"""RC2 - mid-pick summoner-spell flip-back fix (role-aware + revert-stop).

Operator-reported BUG (Caitlyn ADC ranked draft): "summoner spells keep
reverting to flash + teleport". Root cause: in _sync_spells the MID-PICK
branch (the `if not champion:` block) pushed the GENERIC mode default
resolve_spell_pair("", mode) - Flash+Teleport (4,12) for SR, role-BLIND - on
EVERY ~1s poll, overwriting the operator's manual spell choice during the long
pre-lock hover window of ranked draft.

The POST-LOCK branch already (a) resolves a role-aware pair and (b) respects a
manual change via _spell_manual_override + _spell_pushed_pair. This file is the
RED characterization for giving the MID-PICK branch those same two properties:

  1. role-aware: mid-pick + assignedPosition BOTTOM pushes Flash+Heal (4,7),
     NOT Flash+Teleport (4,12); TOP pushes spells_for_role TOP (4,12).
  2. no-role mid-pick falls back to the generic resolve_spell_pair (no crash).
  3. revert-stop: once RC pushes the default, a later poll where the live pair
     differs (operator changed it) records _midpick_manual_override and does
     NOT push again.
  4. _reset_spell_state clears the two new mid-pick state vars.

Pure fakes throughout - never touches a live LCU client or the real DB.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from lcu import lcu_rune_writer as rw_mod  # noqa: E402
from lcu.lcu_rune_writer import RuneWriter  # noqa: E402

_FLASH = 4
_TELEPORT = 12
_HEAL = 7
_IGNITE = 14
_EXHAUST = 3
_MYSEL = "/lol-champ-select/v1/session/my-selection"


class _FakeLcu:
    """Minimal fake of the LcuClient surface RuneWriter touches.

    Mirrors the test_spell_autopush_e6 fake: set_summoner_spells honours the
    idempotency contract (PATCH only when current_pair differs); the session is
    settable so a test can drive multiple polls.
    """

    def __init__(self, session=None) -> None:
        self.calls: list[dict] = []
        self._session = session

    def get_champ_select(self):
        return self._session

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

    def get_all_rune_pages(self):
        return []

    def _patches(self):
        return [c for c in self.calls
                if c["method"] == "PATCH" and c["path"] == _MYSEL]


def _midpick_session(cell, s1, s2, position="BOTTOM"):
    """Champ-select session with NO champion locked or hovered for my cell.

    championId == 0 and championPickIntent == 0 so RuneWriter._detect_my_champion
    returns "" (mid-pick). assignedPosition carries the role.
    """
    return {
        "localPlayerCellId": cell,
        "myTeam": [
            {"cellId": cell, "championId": 0, "championPickIntent": 0,
             "assignedPosition": position, "spell1Id": s1, "spell2Id": s2},
            {"cellId": cell + 1, "championId": 0, "championPickIntent": 0,
             "spell1Id": 0, "spell2Id": 0},
        ],
        "actions": [],
    }


def _new_writer(lcu, *, mode="CLASSIC"):
    rw = RuneWriter(lcu)
    rw._detect_game_mode = lambda: mode  # type: ignore[method-assign]
    rw._champ_id_map = {99: "Lux", 51: "Caitlyn"}
    return rw


class _TmpPrefsMixin:
    """Isolated spell_prefs.json temp file; restores the module path after."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.prefs_path = Path(self._tmpdir.name) / "spell_prefs.json"
        self.prefs_path.write_text(json.dumps({
            "aram_mode": "snowball", "sr_mode": "teleport",
        }), encoding="utf-8")
        self._orig_path = rw_mod._SPELL_PREFS_PATH
        rw_mod._SPELL_PREFS_PATH = self.prefs_path

    def tearDown(self):
        rw_mod._SPELL_PREFS_PATH = self._orig_path
        self._tmpdir.cleanup()

    def _read_prefs(self):
        return json.loads(self.prefs_path.read_text(encoding="utf-8"))


# ===========================================================================
# (a) ROLE-AWARE mid-pick push (the core bug: NOT Flash+Teleport for an ADC)
# ===========================================================================

class MidPickRoleAwareTests(_TmpPrefsMixin, unittest.TestCase):
    def test_midpick_bottom_pushes_flash_heal_not_teleport(self):
        # Caitlyn-style ADC hover on SR, role BOTTOM. The client randomised
        # Flash+Ignite. RC must push the role default Flash+Heal (4,7),
        # NOT the generic SR default Flash+Teleport (4,12).
        sess = _midpick_session(0, _FLASH, _IGNITE, position="BOTTOM")
        lcu = _FakeLcu(sess)
        rw = _new_writer(lcu, mode="CLASSIC")

        rw._poll()

        patches = lcu._patches()
        self.assertEqual(len(patches), 1, "mid-pick should push once")
        self.assertEqual(patches[0]["data"],
                         {"spell1Id": _FLASH, "spell2Id": _HEAL})
        self.assertNotEqual(patches[0]["data"],
                            {"spell1Id": _FLASH, "spell2Id": _TELEPORT})

    def test_midpick_top_pushes_role_pair(self):
        # Role TOP -> spells_for_role TOP == Flash+Teleport (4,12).
        from lcu.lcu_pregame import spells_for_role
        sess = _midpick_session(0, _FLASH, _HEAL, position="TOP")
        lcu = _FakeLcu(sess)
        rw = _new_writer(lcu, mode="CLASSIC")

        rw._poll()

        patches = lcu._patches()
        self.assertEqual(len(patches), 1)
        self.assertEqual(
            tuple(patches[0]["data"][k] for k in ("spell1Id", "spell2Id")),
            spells_for_role("TOP"),
        )

    def test_midpick_no_role_falls_back_to_generic_pair(self):
        # assignedPosition "" (e.g. blind / no-role lobby) -> generic
        # resolve_spell_pair("", mode) fallback; must not crash.
        sess = _midpick_session(0, _IGNITE, _EXHAUST, position="")
        lcu = _FakeLcu(sess)
        rw = _new_writer(lcu, mode="CLASSIC")

        rw._poll()

        patches = lcu._patches()
        self.assertEqual(len(patches), 1)
        want = rw_mod.resolve_spell_pair("", "CLASSIC")
        self.assertEqual(
            tuple(patches[0]["data"][k] for k in ("spell1Id", "spell2Id")),
            want,
        )


# ===========================================================================
# (b) REVERT-STOP: a manual change during the hover window is not flipped back
# ===========================================================================

class MidPickRevertStopTests(_TmpPrefsMixin, unittest.TestCase):
    def test_manual_change_during_hover_is_not_reverted(self):
        # RC pushes the BOTTOM default once. Operator then manually switches to
        # Flash+Ignite while still hovering (no lock). Later polls must NOT
        # flip it back to Flash+Heal.
        sess = _midpick_session(0, _FLASH, _IGNITE, position="BOTTOM")
        lcu = _FakeLcu(sess)
        rw = _new_writer(lcu, mode="CLASSIC")

        rw._poll()  # first poll -> one push of the role default
        first = len(lcu._patches())
        self.assertGreaterEqual(first, 1)

        # Reflect RC's push into the session, then operator overrides it.
        sess["myTeam"][0]["spell1Id"] = _FLASH
        sess["myTeam"][0]["spell2Id"] = _IGNITE

        before = len(lcu._patches())
        rw._poll()   # must detect the manual change, NOT re-push
        rw._poll()   # still must not re-push
        after = len(lcu._patches())
        self.assertEqual(after, before,
                         "mid-pick manual change must NOT be flipped back")
        self.assertTrue(rw._midpick_manual_override,
                        "manual override flag must be set after the drift")

    def test_midpick_does_not_write_champ_pref(self):
        # No champion key exists mid-pick, so save_champ_spell_pref must NOT be
        # called - by_champ stays absent from prefs.
        sess = _midpick_session(0, _FLASH, _IGNITE, position="BOTTOM")
        lcu = _FakeLcu(sess)
        rw = _new_writer(lcu, mode="CLASSIC")

        rw._poll()
        sess["myTeam"][0]["spell1Id"] = _FLASH
        sess["myTeam"][0]["spell2Id"] = _EXHAUST
        rw._poll()

        prefs = self._read_prefs()
        self.assertNotIn("by_champ", prefs)


# ===========================================================================
# (c) _reset_spell_state clears the new mid-pick state vars
# ===========================================================================

class ResetClearsMidpickStateTests(unittest.TestCase):
    def test_reset_clears_midpick_state(self):
        lcu = _FakeLcu(None)
        rw = RuneWriter(lcu)
        rw._midpick_pushed_pair = (_FLASH, _HEAL)
        rw._midpick_manual_override = True

        rw._reset_spell_state()

        self.assertIsNone(rw._midpick_pushed_pair)
        self.assertFalse(rw._midpick_manual_override)

    def test_init_defaults_midpick_state(self):
        lcu = _FakeLcu(None)
        rw = RuneWriter(lcu)
        self.assertIsNone(rw._midpick_pushed_pair)
        self.assertFalse(rw._midpick_manual_override)


if __name__ == "__main__":
    unittest.main()
