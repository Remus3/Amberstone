"""RC2 E6 - summoner-spell flip-back fix + WR-tailored selection + remember-last-used.

Operator-reported BUG: in champ-select, when the operator MANUALLY changes
summoner spells, RC pushes them once but then FLIPS them BACK to the generic
default on the very next poll (every 1.0s after P6.2). Root cause: _poll()
calls _sync_spells() every poll and _sync_spells unconditionally PATCHes the
mode-default pair whenever the live pair differs - so a manual change is
reverted within ~1s. The rune push already has _last_applied_champion
idempotency; the spell push had none.

E6 mirrors that idempotency for spells and adds three behaviors:

  1. STOP THE FLIP-BACK: spell auto-push fires ONCE per champion lock, then
     does NOT re-push. A detected manual change (session pair != what RC last
     pushed) (a) stops overwriting AND (b) records that pair as the remembered
     preference for champion+mode.
  2. REMEMBER last-used per champion per MODE in spell_prefs.json under
     {"by_champ": {"<MODE>": {"<champion>": [s1, s2]}}}. On the next lock of
     that champ+mode the remembered pair is pushed, not the generic default.
  3. HIGHEST-ROLE-WR ON FIRST LOCK: with no remembered pair, pick the highest
     win-rate spell pair for the champ+mode from the postgame corpus; fall back
     to spells_for_role when there's no WR data.
  4. The per-champ regional WR% per candidate pair is exposed as data.

Pure fakes throughout - never touches a live LCU client or the real DB.
"""
from __future__ import annotations

import json
import sqlite3
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
_SNOWBALL = 32
_EXHAUST = 3
_BARRIER = 21
_MYSEL = "/lol-champ-select/v1/session/my-selection"


class _FakeLcu:
    """Minimal fake of the LcuClient surface RuneWriter touches.

    set_summoner_spells mirrors the real LcuPregame.set_summoner_spells
    idempotency contract (PATCH only when current_pair differs). The
    champ-select session is settable so a test can drive multiple polls.
    """

    def __init__(self, session=None) -> None:
        self.calls: list[dict] = []
        self._session = session

    # --- the surface _sync_spells / _poll use ---
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

    # rune-write surface (so a full _poll doesn't explode); pretend success
    def get_all_rune_pages(self):
        return []

    def _patches(self):
        return [c for c in self.calls
                if c["method"] == "PATCH" and c["path"] == _MYSEL]


def _session(cell, champ_id, s1, s2, position="BOTTOM"):
    return {
        "localPlayerCellId": cell,
        "myTeam": [
            {"cellId": cell, "championId": champ_id, "championPickIntent": 0,
             "assignedPosition": position, "spell1Id": s1, "spell2Id": s2},
            {"cellId": cell + 1, "championId": 0, "championPickIntent": 0,
             "spell1Id": 0, "spell2Id": 0},
        ],
        "actions": [],
    }


def _new_writer(lcu, *, prefs_path=None, mode="CLASSIC",
                champ_map=None):
    rw = RuneWriter(lcu)
    rw._detect_game_mode = lambda: mode  # type: ignore[method-assign]
    rw._champ_id_map = champ_map or {99: "Lux", 51: "Caitlyn"}
    if prefs_path is not None:
        # point the module's spell-prefs file at our temp copy so reads/writes
        # never touch the repo's data/spell_prefs.json
        rw._spell_prefs_path = prefs_path  # type: ignore[attr-defined]
    return rw


class _TmpPrefsMixin:
    """Gives each test an isolated spell_prefs.json temp file and restores
    the module-level path after."""

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
# (a) NO RE-PUSH after a manual change (the flip-back bug)
# ===========================================================================

class NoRepushAfterManualChangeTests(_TmpPrefsMixin, unittest.TestCase):
    def test_first_lock_pushes_once_then_manual_change_is_not_reverted(self):
        # Lock Lux on SR. RC pushes a pair once. Operator then manually
        # switches to Flash+Ignite. The NEXT poll must NOT flip it back.
        sess = _session(0, 99, _FLASH, _HEAL, position="MIDDLE")
        lcu = _FakeLcu(sess)
        rw = _new_writer(lcu, mode="CLASSIC")

        rw._poll()  # first lock -> exactly one push
        first_patches = len(lcu._patches())
        self.assertGreaterEqual(first_patches, 1,
                                "first lock should push a spell pair once")

        # Reflect RC's push into the live session, then operator overrides it.
        pushed = lcu._patches()[-1]["data"]
        # Operator manually picks Flash+Ignite (differs from whatever RC set).
        sess["myTeam"][0]["spell1Id"] = _FLASH
        sess["myTeam"][0]["spell2Id"] = _IGNITE

        before = len(lcu._patches())
        rw._poll()   # poll #2 - must detect manual change, NOT re-push
        rw._poll()   # poll #3 - still must not re-push
        after = len(lcu._patches())
        self.assertEqual(after, before,
                         "manual change must NOT be flipped back on later polls")
        self.assertIsNotNone(pushed)

    def test_manual_change_is_recorded_as_remembered_pref(self):
        sess = _session(0, 99, _FLASH, _HEAL, position="MIDDLE")
        lcu = _FakeLcu(sess)
        rw = _new_writer(lcu, mode="CLASSIC")
        rw._poll()  # first lock push

        # Operator overrides to Flash+Exhaust.
        sess["myTeam"][0]["spell1Id"] = _FLASH
        sess["myTeam"][0]["spell2Id"] = _EXHAUST
        rw._poll()  # detect + record

        prefs = self._read_prefs()
        self.assertIn("by_champ", prefs)
        self.assertIn("SR", prefs["by_champ"])
        self.assertEqual(prefs["by_champ"]["SR"].get("Lux"), [_FLASH, _EXHAUST])


# ===========================================================================
# (b) REMEMBERED pair applied on next lock of that champ+mode
# ===========================================================================

class RememberedPairAppliedTests(_TmpPrefsMixin, unittest.TestCase):
    def test_remembered_pair_pushed_on_next_lock(self):
        # Seed a remembered pref for Caitlyn on SR = Flash+Barrier.
        self.prefs_path.write_text(json.dumps({
            "sr_mode": "teleport",
            "by_champ": {"SR": {"Caitlyn": [_FLASH, _BARRIER]}},
        }), encoding="utf-8")

        # Client randomised Flash+Heal; RC must push the REMEMBERED pair.
        sess = _session(0, 51, _FLASH, _HEAL, position="BOTTOM")
        lcu = _FakeLcu(sess)
        rw = _new_writer(lcu, mode="CLASSIC")
        rw._poll()

        patches = lcu._patches()
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]["data"],
                         {"spell1Id": _FLASH, "spell2Id": _BARRIER})

    def test_remembered_pref_is_mode_scoped(self):
        # A Caitlyn ARAM pref must NOT leak into an SR lock.
        self.prefs_path.write_text(json.dumps({
            "by_champ": {"ARAM": {"Caitlyn": [_FLASH, _SNOWBALL]}},
        }), encoding="utf-8")
        pair = rw_mod.load_champ_spell_pref("Caitlyn", "SR")
        self.assertIsNone(pair)
        pair_aram = rw_mod.load_champ_spell_pref("Caitlyn", "ARAM")
        self.assertEqual(pair_aram, (_FLASH, _SNOWBALL))


# ===========================================================================
# (c) HIGHEST-WR pair on first lock (no remembered pref)
# ===========================================================================

def _make_wr_db(rows):
    """In-memory sqlite with one sr_player_stats table holding (champion_name,
    spell1_id, spell2_id, team_result) rows. Mirrors the postgame schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE sr_player_stats ("
        " champion_name TEXT, spell1_id INTEGER, spell2_id INTEGER,"
        " team_result TEXT)"
    )
    conn.executemany(
        "INSERT INTO sr_player_stats(champion_name,spell1_id,spell2_id,team_result)"
        " VALUES (?,?,?,?)", rows,
    )
    conn.commit()
    return conn


class HighestWrPairTests(unittest.TestCase):
    def setUp(self):
        from dashboard import routes_adaptive_summoners as ras
        self.ras = ras

    def test_best_pair_is_highest_winrate_above_min_n(self):
        # Caitlyn SR: Flash+Heal 1/4 (25%), Flash+Teleport 4/5 (80%).
        rows = (
            [("Caitlyn", _FLASH, _HEAL, "WIN")] * 1 +
            [("Caitlyn", _FLASH, _HEAL, "LOSS")] * 3 +
            [("Caitlyn", _FLASH, _TELEPORT, "WIN")] * 4 +
            [("Caitlyn", _FLASH, _TELEPORT, "LOSS")] * 1
        )
        conn = _make_wr_db(rows)
        best = self.ras.best_wr_spell_pair(conn, "Caitlyn", "SR", min_n=3)
        self.assertEqual(best, (_FLASH, _TELEPORT))

    def test_low_n_pairs_excluded(self):
        # The 100% pair has only n=1; below min_n it must NOT win.
        rows = (
            [("Caitlyn", _FLASH, _EXHAUST, "WIN")] * 1 +
            [("Caitlyn", _FLASH, _TELEPORT, "WIN")] * 5 +
            [("Caitlyn", _FLASH, _TELEPORT, "LOSS")] * 5
        )
        conn = _make_wr_db(rows)
        best = self.ras.best_wr_spell_pair(conn, "Caitlyn", "SR", min_n=4)
        self.assertEqual(best, (_FLASH, _TELEPORT))

    def test_no_wr_data_returns_none(self):
        conn = _make_wr_db([])
        best = self.ras.best_wr_spell_pair(conn, "Caitlyn", "SR", min_n=3)
        self.assertIsNone(best)

    def test_first_lock_uses_wr_pair_then_falls_back_to_role(self):
        # With WR selection patched to return None, first lock must fall back
        # to spells_for_role (BOTTOM -> Flash+Heal).
        from lcu.lcu_pregame import spells_for_role
        sess = _session(0, 51, _FLASH, _IGNITE, position="BOTTOM")
        lcu = _FakeLcu(sess)
        rw = RuneWriter(lcu)
        rw._detect_game_mode = lambda: "CLASSIC"  # type: ignore[method-assign]
        rw._champ_id_map = {51: "Caitlyn"}
        rw._wr_spell_pair = lambda champ, mode: None  # type: ignore[method-assign]
        # no remembered pref (default repo prefs have no by_champ for Caitlyn)
        rw._poll()
        patches = lcu._patches()
        self.assertEqual(len(patches), 1)
        self.assertEqual(
            tuple(patches[0]["data"][k] for k in ("spell1Id", "spell2Id")),
            spells_for_role("BOTTOM"),
        )


# ===========================================================================
# (d) WR% data exposed via routes_adaptive_summoners
# ===========================================================================

class WrDataExposedTests(unittest.TestCase):
    def setUp(self):
        from dashboard import routes_adaptive_summoners as ras
        self.ras = ras

    def test_compute_returns_pairs_with_wr_pct_and_n(self):
        rows = (
            [("Caitlyn", _FLASH, _HEAL, "WIN")] * 2 +
            [("Caitlyn", _FLASH, _HEAL, "LOSS")] * 2 +
            [("Caitlyn", _FLASH, _TELEPORT, "WIN")] * 6 +
            [("Caitlyn", _FLASH, _TELEPORT, "LOSS")] * 4
        )
        conn = _make_wr_db(rows)
        out = self.ras.compute_champ_spell_winrates(
            conn, "Caitlyn", "SR", min_n=1)
        self.assertIsInstance(out, list)
        self.assertGreaterEqual(len(out), 2)
        for row in out:
            self.assertIn("pair", row)
            self.assertIn("wr_pct", row)
            self.assertIn("n", row)
        # sorted highest WR first; Flash+TP (60%) ahead of Flash+Heal (50%)
        self.assertEqual(out[0]["pair"], [_FLASH, _TELEPORT])
        self.assertEqual(out[0]["n"], 10)
        self.assertEqual(out[0]["wr_pct"], 60.0)

    def test_spell_winrates_route_registered(self):
        paths = [m for (m, _fn) in self.ras.GET_ROUTES]
        self.assertTrue(
            any(m("/api/champ-select/spell-winrates") for m in paths),
            "spell-winrates route must be registered in GET_ROUTES",
        )


if __name__ == "__main__":
    unittest.main()
