"""Y-01: the post-game live writer pins the just-ended game's id.

External reference M (behaviour only; nothing copied). Before this change
``lib/rewind_live_writer.py`` asked Match-V5 for ``count=1`` recent ids, took
``ids[0]`` and returned ``already_present`` with NO retry when that id was
already in the DB. If Match-V5 had not indexed the just-ended game inside the
90 s delay, ``ids[0]`` was the PREVIOUS game, so the new game silently waited
for the Sunday catchup and the status claimed success it did not have.

The fix passes the gameId through a NON-frozen seam: the LCU post-game
collector (which already reads ``eog['gameId']``) writes an atomic pin file,
and the writer builds ``<PLATFORM>_<gameId>`` (platform from config, never the
regional route) and makes staged attempts against THAT id.

Every Riot call here is a fake. No fixture names a real player.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import riot_api  # noqa: E402
from lib import rewind_live_writer as rlw  # noqa: E402

PREV_GAME = "5000000001"
TARGET_GAME = "5000000002"
NEXT_GAME = "5000000003"
PREV_ID = f"NA1_{PREV_GAME}"
TARGET_ID = f"NA1_{TARGET_GAME}"

FULL_DETAIL = {
    "info": {
        "platformId": "NA1",
        "queueId": 450,
        "gameMode": "ARAM",
        "gameType": "MATCHED_GAME",
        "mapId": 12,
        "gameVersion": "16.10.501",
        "gameDuration": 1200,
        "gameCreation": 1700000000000,
        "gameEndTimestamp": 1700001200000,
        "endOfGameResult": "GameComplete",
        "tournamentCode": "",
        "participants": [],
        "teams": [],
    }
}


class _FakeTimer:
    """Records a staged attempt instead of starting a thread.

    ``alive`` lets a test fill the in-flight cap with timers that count as
    pending, exactly as a real waiting Timer thread would.
    """

    created: list["_FakeTimer"] = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.kwargs = dict(kwargs or {})
        self.daemon = False
        self.started = False
        self.alive = False
        _FakeTimer.created.append(self)

    def start(self):
        self.started = True
        self.alive = True

    def is_alive(self):
        return self.alive

    def fire(self):
        """Run the staged attempt the way the Timer thread would."""
        self.alive = False
        return self.function(**self.kwargs)


class _PinBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rlw_pin_"))
        self.db_path = self.tmp / "rewind_history.db"
        self.pin_path = self.tmp / "last_game_end.json"
        for target, value in (("DB_PATH", self.db_path),
                              ("PIN_PATH", self.pin_path)):
            p = mock.patch.object(rlw, target, value)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"RC_RIOT_PLATFORM": "NA1"})
        env.start()
        self.addCleanup(env.stop)
        _FakeTimer.created = []
        tp = mock.patch.object(rlw.threading, "Timer", _FakeTimer)
        tp.start()
        self.addCleanup(tp.stop)
        rlw._reset_staging_for_tests()
        self.addCleanup(rlw._reset_staging_for_tests)
        from scripts.rewind_scraper import SCHEMA
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ----------------------------------------------------------

    def write_pin(self, game_id=TARGET_GAME, queue_id=450, game_mode="ARAM",
                  riot_id=None, written_at=None):
        rlw.write_game_end_pin(game_id, queue_id=queue_id,
                               game_mode=game_mode, riot_id=riot_id)
        if written_at is not None:
            data = json.loads(self.pin_path.read_text(encoding="utf-8"))
            data["written_at"] = written_at
            self.pin_path.write_text(json.dumps(data), encoding="utf-8")

    def seed(self, *match_ids):
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.executemany(
                "INSERT INTO matches (match_id) VALUES (?)",
                [(m,) for m in match_ids])
            conn.commit()
        finally:
            conn.close()

    def present(self, match_id):
        conn = sqlite3.connect(str(self.db_path))
        try:
            return conn.execute("SELECT 1 FROM matches WHERE match_id=?",
                                (match_id,)).fetchone() is not None
        finally:
            conn.close()

    def parked(self):
        conn = sqlite3.connect(str(self.db_path))
        try:
            try:
                return conn.execute(
                    "SELECT match_id, kind FROM fetch_retry").fetchall()
            except sqlite3.Error:
                return []
        finally:
            conn.close()

    def first_attempt(self, scheduled_at=None, chain="chain-a", **kw):
        return rlw._do_live_fetch_and_insert(
            scheduled_at=time.time() if scheduled_at is None else scheduled_at,
            chain=chain, backoff_s=(), sleep=lambda _s: None, **kw)

    def riot(self, ids_seq, match_seq=None, account=None):
        """Patch core.riot_api with scripted fakes. Returns the call log."""
        calls = {"ids": [], "match": [], "timeline": [], "account": []}
        ids_iter = iter(ids_seq)
        match_iter = iter(match_seq or [])

        def fake_ids(puuid, count=20, region="americas", **_kw):
            calls["ids"].append((puuid, count, region))
            try:
                return next(ids_iter)
            except StopIteration:
                return ids_seq[-1]

        def fake_match(match_id, region="americas"):
            calls["match"].append((match_id, region))
            try:
                outcome, value = next(match_iter)
            except StopIteration:
                outcome, value = "ok", FULL_DETAIL
            riot_api._record_outcome(outcome)
            return value

        def fake_timeline(match_id, region="americas"):
            calls["timeline"].append(match_id)
            riot_api._record_outcome("not_found")
            return None

        def fake_account(name, tag, region="americas"):
            calls["account"].append((name, tag, region))
            return account

        for name, fn in (("get_recent_matches", fake_ids),
                         ("get_match", fake_match),
                         ("get_match_timeline", fake_timeline),
                         ("get_account_by_riot_id", fake_account)):
            p = mock.patch.object(riot_api, name, fn)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (("is_configured", True),):
            p = mock.patch.object(riot_api, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(rlw, "_resolve_latest_puuid",
                              return_value="state-puuid")
        p.start()
        self.addCleanup(p.stop)
        return calls


class TargetPinnedRetryTests(_PinBase):

    def test_previous_match_first_then_target_ends_ok_for_target(self):
        """THE defect: ids[0] is the previous game on the first probe."""
        self.seed(PREV_ID)
        self.write_pin()
        calls = self.riot([[PREV_ID], [TARGET_ID, PREV_ID]])

        r1 = self.first_attempt()
        self.assertEqual(r1["status"], "not_indexed_retry_scheduled", r1)
        self.assertEqual(r1["match_id"], TARGET_ID)
        self.assertEqual(calls["match"], [],
                         "detail must not be fetched before the target is listed")
        self.assertEqual(len(_FakeTimer.created), 1)

        # The next game ends and overwrites the pin BEFORE the staged attempt
        # fires: the staged attempt must still ask for the FIRST target.
        self.write_pin(game_id=NEXT_GAME)
        r2 = _FakeTimer.created[0].fire()
        self.assertEqual(r2["status"], "ok", r2)
        self.assertEqual(r2["match_id"], TARGET_ID)
        self.assertEqual(calls["match"], [(TARGET_ID, rlw.REGION_REGIONAL)])
        self.assertTrue(self.present(TARGET_ID))
        self.assertFalse(self.present(f"NA1_{NEXT_GAME}"))

    def test_already_present_only_when_target_itself_present(self):
        self.seed(PREV_ID, TARGET_ID)
        self.write_pin()
        calls = self.riot([[TARGET_ID, PREV_ID]])
        r = self.first_attempt()
        self.assertEqual(r["status"], "already_present")
        self.assertEqual(r["match_id"], TARGET_ID)
        self.assertEqual(calls["match"], [])
        self.assertEqual(_FakeTimer.created, [])

    def test_previous_present_target_absent_is_never_already_present(self):
        self.seed(PREV_ID)
        self.write_pin()
        self.riot([[PREV_ID]])
        r = self.first_attempt()
        self.assertNotEqual(r["status"], "already_present", r)

    def test_404_on_listed_target_is_retried(self):
        self.write_pin()
        calls = self.riot([[TARGET_ID]],
                          match_seq=[("not_found", None), ("ok", FULL_DETAIL)])
        r1 = self.first_attempt()
        self.assertEqual(r1["status"], "not_indexed_retry_scheduled", r1)
        self.assertEqual(len(_FakeTimer.created), 1)
        r2 = _FakeTimer.created[0].fire()
        self.assertEqual(r2["status"], "ok", r2)
        self.assertEqual([m for m, _ in calls["match"]], [TARGET_ID, TARGET_ID])

    def test_last_attempt_never_indexed_parks_target_for_catchup(self):
        self.seed(PREV_ID)
        self.write_pin()
        self.riot([[PREV_ID]])
        result = self.first_attempt()
        fired = 0
        while result["status"].endswith("_retry_scheduled"):
            result = _FakeTimer.created[-1].fire()
            fired += 1
            self.assertLessEqual(fired, len(rlw.STAGED_DELAYS_S))
        self.assertEqual(fired, len(rlw.STAGED_DELAYS_S))
        self.assertEqual(result["status"], "target_not_indexed", result)
        self.assertEqual(result["match_id"], TARGET_ID)
        self.assertEqual(self.parked(), [(TARGET_ID, "match")])

    def test_staged_delays_follow_the_fixed_schedule(self):
        self.write_pin()
        self.riot([[PREV_ID]])
        result = self.first_attempt()
        while result["status"].endswith("_retry_scheduled"):
            result = _FakeTimer.created[-1].fire()
        self.assertEqual([t.interval for t in _FakeTimer.created],
                         list(rlw.STAGED_DELAYS_S))
        self.assertTrue(all(t.daemon for t in _FakeTimer.created))


class PlatformTests(_PinBase):

    def test_target_uses_configured_platform_not_regional_route(self):
        os.environ["RC_RIOT_PLATFORM"] = "euw1"
        self.write_pin()
        calls = self.riot([[f"EUW1_{TARGET_GAME}"]])
        r = self.first_attempt()
        self.assertEqual(r["match_id"], f"EUW1_{TARGET_GAME}", r)
        self.assertFalse(r["match_id"].lower().startswith(
            rlw.REGION_REGIONAL.lower()))
        self.assertEqual(calls["match"][0][0], f"EUW1_{TARGET_GAME}")


class DedupeAndCapTests(_PinBase):

    def test_concurrent_chains_for_one_target_are_deduped(self):
        self.seed(PREV_ID)
        self.write_pin()
        self.riot([[PREV_ID]])
        r1 = self.first_attempt(chain="chain-a")
        self.assertEqual(r1["status"], "not_indexed_retry_scheduled")
        r2 = self.first_attempt(chain="chain-b")
        self.assertEqual(r2["status"], "duplicate_target", r2)
        self.assertEqual(r2["match_id"], TARGET_ID)
        self.assertEqual(len(_FakeTimer.created), 1,
                         "the duplicate chain must not stage its own Timer")

    def test_target_released_after_terminal_status(self):
        self.write_pin()
        self.riot([[TARGET_ID]])
        r1 = self.first_attempt(chain="chain-a")
        self.assertEqual(r1["status"], "ok", r1)
        r2 = self.first_attempt(chain="chain-b")
        self.assertEqual(r2["status"], "already_present", r2)

    def test_staged_timer_cap_counted_at_accept_time(self):
        for _ in range(rlw.MAX_STAGED_TIMERS):
            t = _FakeTimer(1.0, lambda: None)
            t.start()
            rlw._track_timer_for_tests(t)
        before = len(_FakeTimer.created)
        rlw.schedule_live_insert(object(), delay_s=1.0)
        self.assertEqual(len(_FakeTimer.created), before + 1)
        self.assertFalse(_FakeTimer.created[-1].started,
                         "a Timer over the cap must not be started")

        self.write_pin()
        self.riot([[PREV_ID]])
        r = self.first_attempt()
        self.assertEqual(r["status"], "staged_cap_reached", r)
        self.assertEqual(r["match_id"], TARGET_ID)
        self.assertEqual(self.parked(), [(TARGET_ID, "match")],
                         "work dropped at the cap is parked for the catchup")

    def test_finished_timers_free_their_slot(self):
        for _ in range(rlw.MAX_STAGED_TIMERS):
            t = _FakeTimer(1.0, lambda: None)
            t.start()
            t.alive = False  # already fired
            rlw._track_timer_for_tests(t)
        rlw.schedule_live_insert(object(), delay_s=1.0)
        self.assertTrue(_FakeTimer.created[-1].started)


class EventModeTests(_PinBase):

    def test_q2400_ends_event_mode_excluded_without_any_riot_call(self):
        self.write_pin(queue_id=2400, game_mode="KIWI")
        calls = self.riot([[PREV_ID]])
        r = self.first_attempt()
        self.assertEqual(r["status"], "event_mode_excluded", r)
        self.assertEqual(r["match_id"], TARGET_ID)
        self.assertEqual(calls["ids"], [])
        self.assertEqual(calls["match"], [])
        self.assertEqual(_FakeTimer.created, [])
        self.assertEqual(self.parked(), [])

    def test_ordinary_aram_is_not_event_mode(self):
        self.write_pin(queue_id=450, game_mode="ARAM")
        self.riot([[TARGET_ID]])
        r = self.first_attempt()
        self.assertEqual(r["status"], "ok", r)


class PinSourceTests(_PinBase):

    def test_stale_pin_from_an_earlier_game_is_not_pinned(self):
        now = time.time()
        self.write_pin(written_at=now - 3600)
        self.riot([[PREV_ID]])
        r = self.first_attempt(scheduled_at=now)
        self.assertEqual(r["status"], "awaiting_pin_retry_scheduled", r)

    def test_no_pin_only_the_last_attempt_takes_the_fallback(self):
        self.riot([[PREV_ID]], match_seq=[("ok", FULL_DETAIL)])
        r = self.first_attempt()
        statuses = [r["status"]]
        while r["status"].endswith("_retry_scheduled"):
            r = _FakeTimer.created[-1].fire()
            statuses.append(r["status"])
        self.assertEqual(statuses[:-1],
                         ["awaiting_pin_retry_scheduled"] * len(rlw.STAGED_DELAYS_S))
        self.assertTrue(r.get("fallback"), r)
        self.assertFalse(r.get("pinned"), r)

    def test_pin_written_after_first_probe_is_picked_up(self):
        self.riot([[TARGET_ID]])
        r1 = self.first_attempt()
        self.assertEqual(r1["status"], "awaiting_pin_retry_scheduled")
        self.write_pin()
        r2 = _FakeTimer.created[-1].fire()
        self.assertEqual(r2["status"], "ok", r2)
        self.assertTrue(r2["pinned"])

    def test_live_riot_id_from_pin_resolves_the_puuid(self):
        """LEDGER 357 FUTURE: the live LCU Riot ID beats the stale state."""
        self.write_pin(riot_id=("SamplePlayer", "TST"))
        calls = self.riot([[TARGET_ID]], account={"puuid": "live-puuid"})
        r = self.first_attempt()
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(calls["account"],
                         [("SamplePlayer", "TST", rlw.REGION_REGIONAL)])
        self.assertEqual(calls["ids"][0][0], "live-puuid")

    def test_unresolvable_riot_id_falls_back_to_state_puuid(self):
        self.write_pin(riot_id=("SamplePlayer", "TST"))
        calls = self.riot([[TARGET_ID]], account=None)
        r = self.first_attempt()
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(calls["ids"][0][0], "state-puuid")

    def test_account_lookup_raising_falls_back_to_state_puuid(self):
        """Verifier fix 2: a raising Account-V1 must not end the chain."""
        self.write_pin(riot_id=("SamplePlayer", "TST"))
        calls = self.riot([[TARGET_ID]])
        with mock.patch.object(riot_api, "get_account_by_riot_id",
                               side_effect=RuntimeError("boom")):
            r = self.first_attempt()
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(calls["ids"][0][0], "state-puuid")

    def test_non_finite_written_at_is_rejected(self):
        """Verifier fix 3: NaN compares False, so it slipped the age check;
        +inf is 'newer than everything'. Both are garbage, not a pin."""
        now = time.time()
        for bad in ("NaN", "Infinity"):
            self.pin_path.write_text(
                f'{{"game_id": "{TARGET_GAME}", "written_at": {bad}}}',
                encoding="utf-8")
            self.assertIsNone(rlw._read_game_end_pin(now), bad)

    def test_pin_write_is_atomic_and_shaped(self):
        rlw.write_game_end_pin(TARGET_GAME, queue_id=450, game_mode="ARAM",
                               riot_id=("SamplePlayer", "TST"))
        data = json.loads(self.pin_path.read_text(encoding="utf-8"))
        self.assertEqual(data["game_id"], TARGET_GAME)
        self.assertEqual(data["queue_id"], 450)
        self.assertEqual(data["game_name"], "SamplePlayer")
        self.assertEqual(data["tag_line"], "TST")
        self.assertIsInstance(data["written_at"], float)
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])

    def test_pin_write_rejects_non_numeric_game_id(self):
        self.assertFalse(rlw.write_game_end_pin("M-bad"))
        self.assertFalse(self.pin_path.exists())


class NeverRaisesTests(_PinBase):

    def test_riot_exception_is_swallowed(self):
        self.write_pin()
        self.riot([[TARGET_ID]])
        with mock.patch.object(riot_api, "get_recent_matches",
                               side_effect=RuntimeError("boom")):
            r = self.first_attempt()
        self.assertEqual(r["status"], "error", r)

    def test_garbage_pin_is_swallowed(self):
        self.pin_path.write_text("{not json", encoding="utf-8")
        self.riot([[PREV_ID]])
        r = self.first_attempt()
        self.assertEqual(r["status"], "awaiting_pin_retry_scheduled", r)

    def test_schedule_live_insert_stages_a_chain(self):
        rlw.schedule_live_insert(object(), delay_s=7.0)
        t = _FakeTimer.created[-1]
        self.assertTrue(t.started and t.daemon)
        self.assertEqual(t.interval, 7.0)
        self.assertIsInstance(t.kwargs.get("scheduled_at"), float)
        self.assertTrue(t.kwargs.get("chain"))


class CollectorSeamTests(unittest.TestCase):
    """The collector publishes the pin from the gameId it already reads."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pgc_pin_"))
        p = mock.patch.object(rlw, "PIN_PATH", self.tmp / "last_game_end.json")
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _collector(self, eog, summoner):
        import lcu.lcu_postgame_collector as mod
        col = object.__new__(mod.PostgameCollector)
        col._fetch_eog_stats_block = lambda: eog
        col._try_fetch_timeline = lambda *_a: None
        col._lcu_get = lambda path: (
            summoner if path == "/lol-summoner/v1/current-summoner" else None)
        return mod, col

    def test_eog_capture_writes_pin(self):
        eog = {"gameId": int(TARGET_GAME), "queueId": 2400, "gameMode": "KIWI",
               "teams": []}
        mod, col = self._collector(
            eog, {"gameName": "SamplePlayer", "tagLine": "TST"})
        with mock.patch.object(mod, "_save_eog"):
            self.assertTrue(col._capture("ARAM"))
        data = json.loads(rlw.PIN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["game_id"], TARGET_GAME)
        self.assertEqual(data["queue_id"], 2400)
        self.assertEqual(data["game_mode"], "KIWI")
        self.assertEqual((data["game_name"], data["tag_line"]),
                         ("SamplePlayer", "TST"))

    def _history_collector(self, game, trigger_at):
        mod, col = self._collector(None, None)
        summoner = {"puuid": "lcu-puuid", "gameName": "SamplePlayer",
                    "tagLine": "TST"}
        hist = {"games": {"games": [game]}}

        def lcu_get(path):
            if path == "/lol-summoner/v1/current-summoner":
                return summoner
            if "/matches?" in path:
                return hist
            return None
        col._lcu_get = lcu_get
        col._trigger_at = trigger_at
        return mod, col

    def _history_game(self, game_id, ended_at):
        duration_s = 1200
        return {"gameId": int(game_id), "queueId": 450, "gameMode": "ARAM",
                "gameCreation": int((ended_at - duration_s) * 1000),
                "gameDuration": duration_s, "participants": [],
                "participantIdentities": [], "teams": []}

    def test_history_game_that_ended_before_the_trigger_is_not_pinned(self):
        """Verifier fix 1: LCU history has not picked up the just-ended game,
        so its first entry is the PREVIOUS game - it must not be pinned."""
        trigger_at = time.time()
        game = self._history_game(PREV_GAME, ended_at=trigger_at - 1800)
        mod, col = self._history_collector(game, trigger_at)
        with mock.patch.object(mod, "_save_eog"):
            col._capture_via_history("ARAM")
        self.assertFalse(rlw.PIN_PATH.exists(),
                         "a stale history game must never get a fresh pin")

    def test_history_game_that_just_ended_is_pinned(self):
        trigger_at = time.time()
        game = self._history_game(TARGET_GAME, ended_at=trigger_at - 30)
        mod, col = self._history_collector(game, trigger_at)
        with mock.patch.object(mod, "_save_eog"):
            self.assertTrue(col._capture_via_history("ARAM"))
        data = json.loads(rlw.PIN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["game_id"], TARGET_GAME)

    def test_history_game_without_timing_or_trigger_is_not_pinned(self):
        trigger_at = time.time()
        game = self._history_game(TARGET_GAME, ended_at=trigger_at - 30)
        del game["gameCreation"]
        mod, col = self._history_collector(game, trigger_at)
        with mock.patch.object(mod, "_save_eog"):
            col._capture_via_history("ARAM")
        self.assertFalse(rlw.PIN_PATH.exists())
        game = self._history_game(TARGET_GAME, ended_at=trigger_at - 30)
        mod, col = self._history_collector(game, None)
        with mock.patch.object(mod, "_save_eog"):
            col._capture_via_history("ARAM")
        self.assertFalse(rlw.PIN_PATH.exists())

    def test_trigger_records_the_trigger_time(self):
        import lcu.lcu_postgame_collector as mod
        col = object.__new__(mod.PostgameCollector)
        col._trigger = threading.Event()
        t0 = time.time()
        col.trigger("ARAM")
        self.assertGreaterEqual(col._trigger_at, t0)

    def test_pin_failure_never_costs_the_capture(self):
        eog = {"gameId": int(TARGET_GAME), "teams": []}
        mod, col = self._collector(eog, None)
        with mock.patch.object(mod, "_save_eog"), \
                mock.patch.object(rlw, "write_game_end_pin",
                                  side_effect=OSError("disk")):
            self.assertTrue(col._capture("CLASSIC"))


def test_no_frozen_file_is_the_seam():
    """The wire in the frozen lifecycle stays byte-identical in shape."""
    text = (ROOT / "app" / "_game_lifecycle.py").read_text(encoding="utf-8")
    assert "schedule_live_insert(app)" in text
    assert "write_game_end_pin" not in text


def test_threading_lock_is_the_write_lock():
    assert isinstance(rlw._WRITE_LOCK, type(threading.Lock()))


if __name__ == "__main__":
    unittest.main()
