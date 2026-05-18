"""Phase 8 step 4 - spells_for_role + set_summoner_spells idempotency.

Doesn't import LcuClient (which opens lockfiles + sockets); tests the
pure helper directly + exercises set_summoner_spells via a minimal
shim that mirrors the LcuPregame mixin's _request/_log surface.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from lcu import lcu_pregame
from lcu.lcu_pregame import (
    SPELL,
    SPELLS_BY_ROLE,
    LcuPregame,
    spells_for_role,
)


class TestSpellsForRole(unittest.TestCase):
    def test_canonical_roles(self):
        self.assertEqual(spells_for_role("TOP"),     (SPELL["flash"], SPELL["teleport"]))
        self.assertEqual(spells_for_role("JUNGLE"),  (SPELL["flash"], SPELL["smite"]))
        self.assertEqual(spells_for_role("MIDDLE"),  (SPELL["flash"], SPELL["ignite"]))
        self.assertEqual(spells_for_role("BOTTOM"),  (SPELL["flash"], SPELL["heal"]))
        self.assertEqual(spells_for_role("UTILITY"), (SPELL["flash"], SPELL["ignite"]))

    def test_aliases_coerced(self):
        self.assertEqual(spells_for_role("mid"),     SPELLS_BY_ROLE["MIDDLE"])
        self.assertEqual(spells_for_role("BOT"),     SPELLS_BY_ROLE["BOTTOM"])
        self.assertEqual(spells_for_role("ADC"),     SPELLS_BY_ROLE["BOTTOM"])
        self.assertEqual(spells_for_role("Support"), SPELLS_BY_ROLE["UTILITY"])
        self.assertEqual(spells_for_role("sup"),     SPELLS_BY_ROLE["UTILITY"])
        self.assertEqual(spells_for_role("jg"),      SPELLS_BY_ROLE["JUNGLE"])

    def test_unknown_falls_back_to_bottom(self):
        # Bottom Flash+Heal is the safest default - Heal can't grief
        # the way Smite (steals jungle camps) or TP (warps you out
        # of base) would.
        self.assertEqual(spells_for_role("FILL"), SPELLS_BY_ROLE["BOTTOM"])
        self.assertEqual(spells_for_role(""),     SPELLS_BY_ROLE["BOTTOM"])
        self.assertEqual(spells_for_role(None),   SPELLS_BY_ROLE["BOTTOM"])

    def test_garbage_types_dont_crash(self):
        self.assertEqual(spells_for_role(42),    SPELLS_BY_ROLE["BOTTOM"])  # type: ignore[arg-type]
        self.assertEqual(spells_for_role([4, 7]), SPELLS_BY_ROLE["BOTTOM"])  # type: ignore[arg-type]

    def test_no_smite_in_non_jungle_defaults(self):
        # Smite should never be a non-jungle default - it's locked to
        # jungle items in modern League and writing it for a laner
        # would brick the slot.
        for role, pair in SPELLS_BY_ROLE.items():
            if role == "JUNGLE":
                continue
            self.assertNotIn(SPELL["smite"], pair, f"{role} default leaks Smite")


class _StubPregame:
    """Minimal stub mirroring just what set_summoner_spells touches:
    a `_request(method, path, data=None)` that records calls + returns
    a fake success response."""

    def __init__(self):
        self.calls: list[dict] = []
        self._next_response = {"ok": True}

    def _request(self, method, path, data=None):
        self.calls.append({"method": method, "path": path, "data": data})
        return self._next_response


# Re-bind the real method onto the stub so we exercise the shipped
# code path (patch the bound class method back).
_StubPregame.set_summoner_spells = LcuPregame.set_summoner_spells  # type: ignore[attr-defined]


class TestSetSummonerSpellsIdempotency(unittest.TestCase):
    def test_patch_fires_when_no_current_pair(self):
        s = _StubPregame()
        ok = s.set_summoner_spells(SPELL["flash"], SPELL["heal"])
        self.assertTrue(ok)
        self.assertEqual(len(s.calls), 1)
        self.assertEqual(s.calls[0]["method"], "PATCH")
        self.assertEqual(s.calls[0]["path"], "/lol-champ-select/v1/session/my-selection")
        self.assertEqual(s.calls[0]["data"],
                         {"spell1Id": SPELL["flash"], "spell2Id": SPELL["heal"]})

    def test_patch_skipped_when_current_matches(self):
        s = _StubPregame()
        ok = s.set_summoner_spells(
            SPELL["flash"], SPELL["heal"],
            current_pair=(SPELL["flash"], SPELL["heal"]),
        )
        self.assertTrue(ok)
        self.assertEqual(len(s.calls), 0, "no LCU call should fire on idempotent skip")

    def test_patch_fires_when_current_differs(self):
        s = _StubPregame()
        ok = s.set_summoner_spells(
            SPELL["flash"], SPELL["heal"],
            current_pair=(SPELL["flash"], SPELL["ignite"]),  # f differs
        )
        self.assertTrue(ok)
        self.assertEqual(len(s.calls), 1)

    def test_patch_fires_when_current_swapped(self):
        # Order matters: (Flash, Heal) != (Heal, Flash) for spell slots.
        s = _StubPregame()
        ok = s.set_summoner_spells(
            SPELL["flash"], SPELL["heal"],
            current_pair=(SPELL["heal"], SPELL["flash"]),
        )
        self.assertTrue(ok)
        self.assertEqual(len(s.calls), 1)

    def test_garbage_current_pair_falls_through_to_patch(self):
        # If the caller passes a malformed current_pair, don't trust it
        # for the idempotency check - fire the PATCH to be safe.
        s = _StubPregame()
        ok = s.set_summoner_spells(
            SPELL["flash"], SPELL["heal"],
            current_pair="not a pair",  # type: ignore[arg-type]
        )
        self.assertTrue(ok)
        self.assertEqual(len(s.calls), 1)

    def test_failed_request_returns_false(self):
        s = _StubPregame()
        s._next_response = None  # _request returns None on LCU failure
        ok = s.set_summoner_spells(SPELL["flash"], SPELL["heal"])
        self.assertFalse(ok)
        self.assertEqual(len(s.calls), 1)


if __name__ == "__main__":
    unittest.main()
