"""Lane 8 Headless-True-Audit cycle 12 - core/decision_detector.py.

Regression tests for four defects found by the depth audit. Each test is
named for the weakness it pins and was verified RED against the pre-fix
module before the fix landed.

W1 CORRECTNESS  - detect_postfight_objective counted every ChampionKill
                  TWICE (once resolving the killer's team, once the
                  victim's), so the "+3 kill differential" its docstring
                  promises fired at a true +2, and the title rendered
                  DOUBLE the real number to the player ("+4 fight" for a
                  +2 fight). It is the one detector with no test class in
                  tests/test_decision_detector_adr007.py.
W2 CONCURRENCY  - _write_pending / _write_heartbeat used a bare
                  Path.replace. On Windows that raises PermissionError
                  (WinError 5) while a reader holds the destination open,
                  and both callers swallowed it. decisions_pending.json is
                  read cross-process by dashboard/routes_diag.py and
                  dashboard/routes_metrics.py, so the contention is
                  routine by design. Consequence: record_choice() appended
                  to the JSONL log and then silently failed to remove the
                  decision, so one decision logged TWICE and stayed
                  pending forever.
W3 OBSERVABILITY- the ADR-007 heartbeat reported alive with a healthy
                  incrementing counter while detectors raised on every
                  tick. The pill exists so the operator can tell the loop
                  is alive "even when it's silently deciding not to fire",
                  but it could not separate that from "crashing".
W4 INPUT VALID. - list_pending() returned whatever JSON the file held.
                  A non-list (or a list of non-dicts) then wedged
                  reconcile() with TypeError inside the loop's broad
                  except, every tick, forever, without repairing the file.

LANE 8 CYCLE 26 - the W2 tests changed how contention is PRODUCED, not what
they assert. They used to open the destination on a thread and let win32's
share lock supply the PermissionError. POSIX renames straight through an open
read handle, so on the Linux CI runner
test_record_choice_does_not_double_log_when_the_write_fails was RED (the write
succeeded, so record_choice returned a dict instead of None) and the three
transient-reader tests were vacuously GREEN, having provoked no fault at all.
The fault is now injected at the os.replace boundary by
tests/_replace_faults.replace_fails, so the retry loop runs on every platform;
the OS-shaped question is a separate platform-gated test at the end of W2.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest

import core.decision_detector as dd
from core.polled_json import _REPLACE_RETRY_DELAYS_S as _DELAYS
from tests._replace_faults import replace_fails
from core.decision_detector import (
    DecisionLoop,
    DecisionStore,
    _enemy_has_smite,
    detect_postfight_objective,
)


# -- fixtures ------------------------------------------------------------------

def _postfight_snapshot(kills, game_time: float = 905.0) -> dict:
    """Snapshot with a Dragon window open (killed at 620 + 300s respawn =
    920, i.e. +15s from game_time 905) so detect_postfight_objective gets
    past its objective gate and we are measuring the kill-diff arithmetic
    alone. `kills` is a list of (killer_name, victim_name)."""
    events = [{"EventName": "ChampionKill", "EventTime": game_time - 5,
               "KillerName": k, "VictimName": v} for k, v in kills]
    events.append({"EventName": "DragonKill", "EventTime": 620.0})
    return {
        "gameData": {"gameTime": game_time, "gameMode": "CLASSIC"},
        "activePlayer": {"summonerName": "Me"},
        "allPlayers": [
            {"summonerName": "Me", "team": "ORDER"},
            {"summonerName": "A1", "team": "ORDER"},
            {"summonerName": "A2", "team": "ORDER"},
            {"summonerName": "E1", "team": "CHAOS"},
            {"summonerName": "E2", "team": "CHAOS"},
            {"summonerName": "E3", "team": "CHAOS"},
        ],
        "events": {"Events": events},
    }


# -- W1: kill differential is counted once, not twice --------------------------

class TestPostfightKillDiffNotDoubled:

    def test_three_ally_kills_reports_plus_three_not_six(self):
        d = detect_postfight_objective(
            _postfight_snapshot([("Me", "E1"), ("A1", "E2"), ("A2", "E3")]), {})
        assert d is not None, "a true +3 differential must still fire"
        assert d.context["kill_diff"] == 3

    def test_title_shows_the_true_differential(self):
        d = detect_postfight_objective(
            _postfight_snapshot([("Me", "E1"), ("A1", "E2"), ("A2", "E3")]), {})
        assert d is not None
        # The player must not be shown "+6 fight" for a 3-kill swing.
        assert "+3 fight" in d.title
        assert "+6" not in d.title
        assert "kill diff +3" in d.subtitle

    def test_true_plus_two_does_not_fire(self):
        """Docstring promises "+3 (or better)". Doubling made +2 fire."""
        d = detect_postfight_objective(
            _postfight_snapshot([("Me", "E1"), ("A1", "E2")]), {})
        assert d is None

    def test_ally_deaths_subtract_once(self):
        """4 ally kills - 1 ally death = +3. Doubling reported +6."""
        d = detect_postfight_objective(_postfight_snapshot(
            [("Me", "E1"), ("A1", "E2"), ("A2", "E3"), ("Me", "E1"),
             ("E1", "A1")]), {})
        assert d is not None
        assert d.context["kill_diff"] == 3

    def test_non_champion_killer_still_counts_the_victim(self):
        """A turret/minion execute has no KillerName in allPlayers. The
        event must still count once, from the victim's side."""
        snap = _postfight_snapshot(
            [("Me", "E1"), ("A1", "E2"), ("A2", "E3"), ("Turret_T2", "E1")])
        d = detect_postfight_objective(snap, {})
        assert d is not None
        assert d.context["kill_diff"] == 4


# -- W2: atomic replace survives a concurrent reader ---------------------------

class TestWritePendingUnderConcurrentReader:
    """A bare os.replace onto a file a reader holds open raises
    PermissionError (WinError 5) on Windows. core/polled_json measures the
    real contention window at <100 ms and retries for ~275 ms, so a BRIEF
    overlapping read must now succeed. An indefinite hold cannot be beaten
    by any atomic-rename design - what matters there is that the store
    stays CONSISTENT rather than double-logging.

    The fault is INJECTED at os.replace (see the module docstring); it is no
    longer borrowed from a real held handle, which only ever produced it on
    win32. The read that causes it is nonetheless real and cross-process:
    dashboard/routes_diag.py and dashboard/routes_metrics.py both read
    decisions_pending.json from the RC main process."""

    @staticmethod
    def _brief_contention(path):
        """Two failed replaces, then a real one.

        That is the poller's read window expressed deterministically: it must
        CLEAR for the ~275 ms retry to be able to win, so a transient fault is
        what exercises the retry loop. A permanent one exercises exhaustion,
        which is a different test.
        """
        return replace_fails(path, times=2)

    def test_write_pending_survives_a_transient_reader(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "log.jsonl")
        store._write_pending([{"id": "x", "expires_at_game_time": 9e9}])
        with self._brief_contention(pending) as rec:
            assert store._write_pending([]) is True
        assert rec.attempts == 3, "the write did not re-attempt after a fault"
        assert json.loads(pending.read_text(encoding="utf-8")) == []

    def test_record_choice_survives_a_transient_reader(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        log = tmp_path / "decisions_log.jsonl"
        store = DecisionStore(pending_path=pending, log_path=log)
        store._write_pending([{"id": "objective_contest:Dragon:920",
                               "type": "objective_contest",
                               "expires_at_game_time": 9e9}])
        with self._brief_contention(pending) as rec:
            assert store.record_choice("objective_contest:Dragon:920",
                                       "contest") is not None
        assert rec.attempts == 3
        assert json.loads(pending.read_text(encoding="utf-8")) == []

    def test_record_choice_does_not_double_log_when_the_write_fails(
            self, tmp_path):
        """The measured pre-fix behaviour: the JSONL append ran first and
        the pending write's failure was swallowed, so ONE decision logged
        TWICE and never left the pending list. A failed write must now
        record nothing at all.

        The permanent fault is injected rather than borrowed from an
        indefinitely held handle. As a held-handle test this was RED on the
        Linux runner: the rename succeeded, so record_choice returned a dict
        and the double-log branch it guards was never reached there at all."""
        pending = tmp_path / "decisions_pending.json"
        log = tmp_path / "decisions_log.jsonl"
        store = DecisionStore(pending_path=pending, log_path=log)
        store._write_pending([{"id": "objective_contest:Dragon:920",
                               "type": "objective_contest",
                               "expires_at_game_time": 9e9}])
        with replace_fails(pending) as rec:        # every attempt fails
            first = store.record_choice("objective_contest:Dragon:920",
                                        "contest")
            second = store.record_choice("objective_contest:Dragon:920",
                                         "give")
        # Both calls must exhaust the loop: one attempt per backoff delay,
        # plus the initial attempt, twice over.
        assert rec.attempts == 2 * (len(_DELAYS) + 1), (
            f"retry loop not exhausted twice: {rec}")
        assert first is None and second is None
        assert not log.exists() or log.read_text(encoding="utf-8").strip() == ""
        # The decision is still pending, so the player's next click works.
        assert [d["id"] for d in store.list_pending()] == [
            "objective_contest:Dragon:920"]
        assert store.record_choice("objective_contest:Dragon:920",
                                   "contest") is not None
        lines = [ln for ln in log.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
        assert len(lines) == 1, f"one decision must log once, got {lines}"

    def test_heartbeat_write_survives_a_transient_reader(
            self, tmp_path, monkeypatch):
        path = tmp_path / "decisions_heartbeat.json"
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", path)
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        with loop._heartbeat_lock:
            loop._eval_count = 1
            loop._last_eval_unix = time.time()
        loop._write_heartbeat()
        with loop._heartbeat_lock:
            loop._eval_count = 2
        with self._brief_contention(path) as rec:
            loop._write_heartbeat()
        assert rec.attempts == 3, "the heartbeat write did not re-attempt"
        assert json.loads(path.read_text(encoding="utf-8"))["counter"] == 2

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="POSIX rename ignores an open read handle; there is no OS "
               "fault to observe, which is why the tests above inject theirs")
    def test_the_real_os_still_share_locks_a_held_pending_file(self, tmp_path):
        """The one question replace_fails() cannot answer: is it real?

        The tests above simulate the share lock, so this asserts the OS
        property alone - no store, no retry loop - and stays true whatever
        core/decision_detector does next. Red here on win32 would mean the
        premise of the retry loop is gone and the injected faults model a
        condition that no longer occurs."""
        pending = tmp_path / "decisions_pending.json"
        pending.write_text("[]", encoding="utf-8")
        scratch = tmp_path / "decisions_pending.os_probe"
        scratch.write_text("[]", encoding="utf-8")
        with open(pending, encoding="utf-8"):
            with pytest.raises(PermissionError):
                os.replace(scratch, pending)
        scratch.unlink()


# -- W3: the heartbeat admits detector failures --------------------------------

class TestHeartbeatSurfacesDetectorErrors:

    def _run_one_pass(self, loop, snapshot):
        loop._fetch_snapshot = lambda: (snapshot, 0.1)
        loop._read_vision_state = lambda: {}
        loop._poll_s = 0.01          # keep the guard fast; 1 Hz is prod
        t = threading.Thread(target=loop._loop, daemon=True)
        t.start()
        time.sleep(0.3)
        loop._stop.set()
        t.join(timeout=3)

    def test_partial_detector_failure_is_reported(self, tmp_path, monkeypatch):
        """A detector raising on every tick must reach the pill. Before the
        cycle-12 fix it read alive=True with a clean counter and no failure
        signal.

        RM-318 CHANGED THE PROVOCATION, NOT THE ASSERTION. This used to
        drive the fault with `events.Events` arriving as a str, which then
        crashed 2 of 6 detectors; RM-318 hardened exactly that read, so the
        old payload now evaluates cleanly and the test measured 0 errors -
        i.e. it had become a test of a fault it could no longer produce,
        not a test of the heartbeat. The W3 question (does a raising
        detector reach the pill?) is unchanged and is now asked with an
        injected detector that raises unconditionally, which no amount of
        envelope hardening can make green.

        The events.Events-as-str payload itself did not go away: it is a
        row of the RM-318 matrix at the end of this file, where it is now
        asserted NOT to raise."""
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")

        def _raiser(snapshot, vision_state):
            raise AttributeError("'str' object has no attribute 'get'")

        _raiser.__name__ = "detect_throwing_lead"
        monkeypatch.setattr(dd, "DECISION_REGISTRY",
                            list(dd.DECISION_REGISTRY[:-1]) + [_raiser])
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        self._run_one_pass(loop, {
            "gameData": {"gameTime": 900.0, "gameMode": "CLASSIC"},
            "activePlayer": {"summonerName": "Me"},
            "allPlayers": [{"summonerName": "Me", "team": "ORDER"}],
            "events": {"Events": "shape-changed"},
        })
        hb = loop.heartbeat()
        assert hb["counter"] > 0, "loop must still be running"
        assert hb["detector_errors"] == 1
        assert "detect_throwing_lead" in (hb["last_detector_error"] or "")
        assert "AttributeError" in (hb["last_detector_error"] or "")

    def test_the_old_events_payload_no_longer_crashes_any_detector(
            self, tmp_path, monkeypatch):
        """The counterpart to the note above: the exact payload that used
        to crash 2 of 6 is now clean through the real registry. Without
        this, the reframing above could be hiding a regression rather than
        recording a fix."""
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        self._run_one_pass(loop, {
            "gameData": {"gameTime": 900.0, "gameMode": "CLASSIC"},
            "activePlayer": {"summonerName": "Me"},
            "allPlayers": [{"summonerName": "Me", "team": "ORDER"}],
            "events": {"Events": "shape-changed"},
        })
        hb = loop.heartbeat()
        assert hb["counter"] > 0
        assert hb["detector_errors"] == 0
        assert hb["last_detector_error"] is None

    def test_healthy_pass_reports_zero_errors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        self._run_one_pass(loop, _postfight_snapshot([("Me", "E1")]))
        hb = loop.heartbeat()
        assert hb["counter"] > 0
        assert hb["detector_errors"] == 0
        assert hb["last_detector_error"] is None

    def test_read_heartbeat_defaults_carry_the_new_keys(
            self, tmp_path, monkeypatch):
        """The dashboard pill reads through read_heartbeat(); its
        no-file sentinel must carry the same keys as heartbeat()."""
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "missing.json")
        hb = dd.read_heartbeat()
        assert hb["detector_errors"] == 0
        assert hb["last_detector_error"] is None

    def test_read_heartbeat_backfills_keys_for_a_legacy_file(
            self, tmp_path, monkeypatch):
        """A heartbeat file written by the pre-fix loop has neither key.
        read_heartbeat must not KeyError the dashboard route."""
        path = tmp_path / "hb.json"
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", path)
        path.write_text(json.dumps({
            "counter": 12, "last_eval_unix": time.time() - 1.0,
            "age_s": 1.0, "alive": True, "game_time": 600.0, "detectors": 6,
        }), encoding="utf-8")
        hb = dd.read_heartbeat()
        assert hb["counter"] == 12
        assert hb["detector_errors"] == 0
        assert hb["last_detector_error"] is None


# -- W4: a malformed pending file cannot wedge the loop ------------------------

class TestPendingFileShapeValidation:

    @pytest.mark.parametrize("raw", [
        '{"id": "not-a-list"}',       # a dict
        'null',                       # JSON null
        '"a string"',                 # a bare string
        '[1, 2, 3]',                  # list of non-dicts
        '[{"no_id": true}]',          # dicts without the required id
        '[{"id": 17}]',               # id present but not a string
    ])
    def test_list_pending_returns_a_list_of_id_carrying_dicts(
            self, tmp_path, raw):
        pending = tmp_path / "decisions_pending.json"
        pending.write_text(raw, encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        assert store.list_pending() == []

    def test_reconcile_does_not_raise_on_a_malformed_file(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        pending.write_text('{"id": "not-a-list"}', encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        store.reconcile([], game_time=100.0)   # raised TypeError before

    def test_reconcile_repairs_the_malformed_file(self, tmp_path):
        """6e: the fix must also recover the already-bad state, not just
        stop future corruption."""
        pending = tmp_path / "decisions_pending.json"
        pending.write_text('{"id": "not-a-list"}', encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        store.reconcile([], game_time=100.0)
        assert json.loads(pending.read_text(encoding="utf-8")) == []

    def test_good_entries_survive_validation(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        pending.write_text(json.dumps(
            [{"id": "keep:1", "expires_at_game_time": 9e9},
             "junk",
             {"id": "keep:2", "expires_at_game_time": 9e9}]),
            encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        assert [d["id"] for d in store.list_pending()] == ["keep:1", "keep:2"]

    def test_record_choice_on_a_malformed_file_returns_none(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        pending.write_text('[1, 2, 3]', encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        assert store.record_choice("anything", "contest") is None


# -- Findings raised by the adversarial pass on this slice ---------------------

class TestAdversarialFollowups:
    """Four defects the refutation pass on cycle 12 found in the cycle-12
    fix itself. Each was measured, then pinned here."""

    def test_same_team_kill_nets_zero(self):
        """An ally killing an ally is one kill and one death for the same
        team. The first single-count fix credited it +1 - further from the
        truth than the doubled version it replaced, which netted 0."""
        d = detect_postfight_objective(_postfight_snapshot(
            [("Me", "E1"), ("A1", "E2"), ("A2", "E3"), ("Me", "A1")]), {})
        assert d is not None
        assert d.context["kill_diff"] == 3

    def test_enemy_killing_enemy_nets_zero(self):
        d = detect_postfight_objective(_postfight_snapshot(
            [("Me", "E1"), ("A1", "E2"), ("A2", "E3"), ("E1", "E2")]), {})
        assert d is not None
        assert d.context["kill_diff"] == 3

    def test_non_dict_player_row_does_not_raise(self):
        """The self-team lookup was a hand-rolled loop with no isinstance
        guard, so a non-dict allPlayers row ahead of the active player
        raised before the guarded _team_of was ever reached."""
        snap = _postfight_snapshot([("Me", "E1"), ("A1", "E2"), ("A2", "E3")])
        snap["allPlayers"].insert(0, "not-a-dict")
        d = detect_postfight_objective(snap, {})     # must not raise
        assert d is not None
        assert d.context["kill_diff"] == 3

    def test_a_failed_log_append_restores_the_decision(self, tmp_path):
        """THE REGRESSION THE ADVERSARIAL PASS CAUGHT. Ordering the pending
        write first fixed the double-log but opened the mirror hole: if the
        JSONL append then failed, the decision was gone from pending, never
        logged, and the caller was told ok. The invariant is that a decision
        is either still pending or logged exactly once - never neither.

        The log path is a DIRECTORY, so only the append raises. Patching
        Path.open instead makes this test vacuous: write_text() goes through
        Path.open too, so the PENDING write fails first, record_choice
        returns None at the earlier branch, and the test passes without ever
        reaching the code it claims to guard - measured, the mutant survived
        until this was changed."""
        pending = tmp_path / "decisions_pending.json"
        log_dir = tmp_path / "decisions_log.jsonl"
        log_dir.mkdir()
        store = DecisionStore(pending_path=pending, log_path=log_dir)
        store._write_pending([{"id": "objective_contest:Dragon:920",
                               "type": "objective_contest",
                               "expires_at_game_time": 9e9}])
        assert store.record_choice("objective_contest:Dragon:920",
                                   "contest") is None
        # Still pending, so the player's click is not silently swallowed.
        assert [d["id"] for d in store.list_pending()] == [
            "objective_contest:Dragon:920"]
        assert list(log_dir.iterdir()) == []

    def test_last_detector_error_is_length_capped(self, tmp_path, monkeypatch):
        """The string is served by /api/decisions/heartbeat and an exception
        message can quote snapshot fields, including a Riot ID."""
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")

        def _explode(snapshot, vision_state):
            raise ValueError("x" * 5000)

        monkeypatch.setattr(dd, "DECISION_REGISTRY", [_explode])
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        loop._fetch_snapshot = lambda: (_postfight_snapshot([]), 0.1)
        loop._read_vision_state = lambda: {}
        loop._poll_s = 0.01
        t = threading.Thread(target=loop._loop, daemon=True)
        t.start()
        time.sleep(0.3)
        loop._stop.set()
        t.join(timeout=3)
        hb = loop.heartbeat()
        assert hb["detector_errors"] == 1
        assert len(hb["last_detector_error"]) <= dd._MAX_ERR_CHARS

    def test_repeated_failures_do_not_log_every_tick(self, tmp_path,
                                                     monkeypatch, caplog):
        """At 1 Hz an unchanged breakage would write ~3600 WARNING lines an
        hour. Log on change of signature, then at most once a minute."""
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")

        def _explode(snapshot, vision_state):
            raise ValueError("same every time")

        monkeypatch.setattr(dd, "DECISION_REGISTRY", [_explode])
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        loop._fetch_snapshot = lambda: (_postfight_snapshot([]), 0.1)
        loop._read_vision_state = lambda: {}
        loop._poll_s = 0.01
        with caplog.at_level("WARNING", logger="rc.decision_detector"):
            t = threading.Thread(target=loop._loop, daemon=True)
            t.start()
            time.sleep(0.4)
            loop._stop.set()
            t.join(timeout=3)
        warns = [r for r in caplog.records if "detectors failed" in r.message]
        assert loop.heartbeat()["counter"] >= 5, "loop must have ticked a lot"
        assert len(warns) == 1, f"expected one warning, got {len(warns)}"


# -- W5: the Smite probe reads the field its docstring cites -------------------

class TestSmiteFieldNames:

    def test_reads_raw_display_name(self):
        """The docstring cites rawName ...SummonerSmite_DisplayName; the
        code only ever read displayName + rawDescription."""
        p = {"summonerSpells": {"summonerSpellOne": {
            "rawDisplayName":
                "GeneratedTip_SummonerSpell_SummonerSmite_DisplayName"}}}
        assert _enemy_has_smite(p) is True

    def test_full_live_client_shape_still_detected(self):
        p = {"summonerSpells": {"summonerSpellOne": {
            "displayName": "Smite",
            "rawDescription":
                "GeneratedTip_SummonerSpell_SummonerSmite_Description",
            "rawDisplayName":
                "GeneratedTip_SummonerSpell_SummonerSmite_DisplayName"}}}
        assert _enemy_has_smite(p) is True

    def test_non_smite_spells_are_not_detected(self):
        p = {"summonerSpells": {
            "summonerSpellOne": {
                "displayName": "Flash",
                "rawDisplayName":
                    "GeneratedTip_SummonerSpell_SummonerFlash_DisplayName"},
            "summonerSpellTwo": {
                "displayName": "Ignite",
                "rawDisplayName":
                    "GeneratedTip_SummonerSpell_SummonerDot_DisplayName"}}}
        assert _enemy_has_smite(p) is False


# == RM-318: envelope shape-hardening across all six detectors =================
#
# The six registered detectors read the Live Client envelope positionally -
# `snapshot["gameData"]["gameTime"]`, `snapshot["allPlayers"][i]["team"]`,
# `vision_state["enemies"][k]["visible"]` - with `or {}` as the only guard.
# `or {}` defends against a MISSING or FALSY value and against nothing else:
# a truthy value of the wrong TYPE sails straight through it and raises on
# the next attribute or float() call.
#
# MEASURED at 8d4173c31, each detector driven from a WELL-FORMED snapshot
# that makes it fire, then one field retyped (raises / 6 detectors):
#
#   gameData is a str .................. 6/6  AttributeError
#   gameTime is a str .................. 6/6  ValueError
#   gameTime is None ................... 6/6  TypeError
#   activePlayer is a str .............. 4/6  AttributeError
#   events.Events is a str ............. 3/6  AttributeError
#   events.Events holds a non-dict ..... 3/6  AttributeError
#   vision_state is a str .............. 3/6  AttributeError
#   vision_state.enemies is a str ...... 3/6  AttributeError
#   an enemies VALUE is a str .......... 3/6  AttributeError
#   allPlayers[0] is a str ............. 2/6  AttributeError
#   championStats is a str ............. 1/6  AttributeError
#   allPlayers is a str ................ 1/6  AttributeError
#   summonerSpells is a str ............ 1/6  AttributeError
#   gameData is a list ................. 0/6  (GREEN CONTROL)
#   events is a list ................... 0/6  (GREEN CONTROL)
#   allPlayers[-1] is a str ............ 0/6  (GREEN CONTROL, see below)
#
# Three of those rows correct the inherited RM-318 filing, which was taken
# from a MINIMAL snapshot rather than a firing one:
#   - "a string gameData raises in 5/6" is really 6/6. The sixth,
#     detect_low_hp_backable, reads activePlayer FIRST and returns at
#     `mx <= 0`, so a minimal snapshot retires it before it ever touches
#     gameData. Give it real HP and it raises like the rest.
#   - "a non-numeric gameTime raises in 5/6" is 6/6 for the same reason.
#   - "a string element inside allPlayers raises in 1/6" is really 2/6, and
#     it is POSITION-DEPENDENT: detect_low_hp_backable and
#     detect_jungler_gank_likely scan allPlayers with unguarded `p.get(...)`
#     and both `break` on a match, so a bad row AFTER the row they want is
#     never reached and the same payload measures 0/6. A fixture that
#     appends the bad row therefore reports the defect as absent. Both
#     orderings are parametrised below.
#
# The events-as-LIST row is the deliberate green control: `(snapshot.get(
# "events") or {}).get("Events")` is already guarded at :195 / :301 / :350,
# so it passes before the fix as well as after, and the hardening cannot be
# graded on it.

def _rm318_player(name, team, **kw):
    p = {"summonerName": name, "team": team, "isDead": False,
         "championName": name,
         "summonerSpells": {
             "summonerSpellOne": {"displayName": "Flash",
                                  "rawDescription": "",
                                  "rawDisplayName": ""},
             "summonerSpellTwo": {"displayName": "Ignite",
                                  "rawDescription": "",
                                  "rawDisplayName": ""}}}
    p.update(kw)
    return p


_RM318_SMITE = {
    "summonerSpellOne": {"displayName": "Smite", "rawDescription": "",
                         "rawDisplayName": ""},
    "summonerSpellTwo": {"displayName": "Flash", "rawDescription": "",
                         "rawDisplayName": ""}}


def _rm318_env(game_time, events=(), players=None, enemies=None,
               hp=(1000.0, 1000.0)):
    """A well-formed (snapshot, vision_state) pair in Live Client shape."""
    players = players if players is not None else [
        _rm318_player("Me", "ORDER")]
    snapshot = {
        "gameData": {"gameTime": game_time, "gameMode": "CLASSIC"},
        "activePlayer": {
            "summonerName": "Me",
            "championStats": {"currentHealth": hp[0], "maxHealth": hp[1]}},
        "allPlayers": players,
        "events": {"Events": list(events)},
    }
    return snapshot, {"enemies": enemies or {}}


_RM318_MISSING_TWO = {
    "E1": {"is_dead": False, "visible": False, "missing_for_s": 30,
           "last_seen_zone": "mid", "champion": "LeeSin"},
    "E2": {"is_dead": False, "visible": False, "missing_for_s": 30,
           "last_seen_zone": "mid", "champion": "Ahri"},
}


def _rm318_positive(detector_name):
    """A (snapshot, vision_state) pair on which `detector_name` FIRES.

    Load-bearing: the hardening below must leave every one of these firing.
    A detector coerced into returning None for everything would satisfy a
    raise-free matrix while proving nothing, which is the failure mode this
    arm exists to catch.
    """
    if detector_name == "detect_objective_contest_with_missing":
        # Dragon first-spawns at 300; at 260 it is 40s out, inside the
        # 60s alert window, and two enemies are missing.
        return _rm318_env(260.0, enemies=_RM318_MISSING_TWO)
    if detector_name == "detect_low_hp_backable":
        return _rm318_env(300.0, hp=(100.0, 1000.0))
    if detector_name == "detect_lane_roam_window":
        # Dragon taken at 300 -> respawns 600, i.e. 200s out at t=400, so
        # the objective-contest detector does not own this signal.
        return _rm318_env(
            400.0, events=[{"EventName": "DragonKill", "EventTime": 300.0}],
            enemies=_RM318_MISSING_TWO)
    if detector_name == "detect_postfight_objective":
        # Dragon taken at 320 -> respawns 620, 10s out at t=610 (inside the
        # -10..30 window); three ally kills inside the 20s fight window.
        return _rm318_env(610.0, events=[
            {"EventName": "DragonKill", "EventTime": 320.0},
            {"EventName": "ChampionKill", "EventTime": 595.0,
             "KillerName": "Me", "VictimName": "E1"},
            {"EventName": "ChampionKill", "EventTime": 600.0,
             "KillerName": "Me", "VictimName": "E2"},
            {"EventName": "ChampionKill", "EventTime": 605.0,
             "KillerName": "A1", "VictimName": "E3"},
        ], players=[
            _rm318_player("Me", "ORDER"), _rm318_player("A1", "ORDER"),
            _rm318_player("E1", "CHAOS"), _rm318_player("E2", "CHAOS"),
            _rm318_player("E3", "CHAOS")])
    if detector_name == "detect_jungler_gank_likely":
        return _rm318_env(
            400.0, events=[{"EventName": "DragonKill", "EventTime": 300.0}],
            players=[_rm318_player("Me", "ORDER"),
                     _rm318_player("E1", "CHAOS",
                                   summonerSpells=_RM318_SMITE)],
            enemies={"E1": {"is_dead": False, "visible": False,
                            "missing_for_s": 40, "last_seen_zone": "mid",
                            "champion": "LeeSin"}})
    if detector_name == "detect_throwing_lead":
        return _rm318_env(600.0, events=[
            {"EventName": "ChampionKill", "EventTime": 550.0,
             "KillerName": "E1", "VictimName": "Me"},
            {"EventName": "ChampionKill", "EventTime": 570.0,
             "KillerName": "E2", "VictimName": "Me"},
        ])
    raise AssertionError("no RM-318 positive fixture for " + detector_name)


# Each mutator retypes exactly ONE envelope field in place. `vision_state`
# is returned rather than mutated so a mutator can replace it wholesale.

def _mut_game_data_str(s, v):
    s["gameData"] = "12:34 CLASSIC"
    return v


def _mut_game_data_list(s, v):
    s["gameData"] = []
    return v


def _mut_game_time_str(s, v):
    s["gameData"]["gameTime"] = "12:34"
    return v


def _mut_game_time_none(s, v):
    s["gameData"]["gameTime"] = None
    return v


def _mut_active_player_str(s, v):
    s["activePlayer"] = "Me"
    return v


def _mut_champion_stats_str(s, v):
    s["activePlayer"]["championStats"] = "100/1000"
    return v


def _mut_all_players_str(s, v):
    s["allPlayers"] = "Me,A1,E1"
    return v


def _mut_all_players_bad_row_first(s, v):
    s["allPlayers"] = ["Me"] + list(s["allPlayers"])
    return v


def _mut_all_players_bad_row_last(s, v):
    s["allPlayers"] = list(s["allPlayers"]) + ["E9"]
    return v


def _mut_events_is_list(s, v):
    s["events"] = []
    return v


def _mut_events_events_str(s, v):
    s["events"]["Events"] = "ChampionKill"
    return v


def _mut_events_bad_row(s, v):
    s["events"]["Events"] = ["ChampionKill"] + list(s["events"]["Events"])
    return v


def _mut_summoner_spells_str(s, v):
    for p in s["allPlayers"]:
        if isinstance(p, dict):
            p["summonerSpells"] = "Smite,Flash"
    return v


def _mut_vision_state_str(s, v):
    return "no vision"


def _mut_enemies_str(s, v):
    v["enemies"] = "E1,E2"
    return v


def _mut_enemies_value_str(s, v):
    v["enemies"] = {"E1": "mid 30s", "E2": "mid 30s"}
    return v


_RM318_SHAPES = [
    ("game_data_str", _mut_game_data_str),
    ("game_data_list", _mut_game_data_list),
    ("game_time_str", _mut_game_time_str),
    ("game_time_none", _mut_game_time_none),
    ("active_player_str", _mut_active_player_str),
    ("champion_stats_str", _mut_champion_stats_str),
    ("all_players_str", _mut_all_players_str),
    ("all_players_bad_row_first", _mut_all_players_bad_row_first),
    ("all_players_bad_row_last", _mut_all_players_bad_row_last),
    ("events_is_list", _mut_events_is_list),
    ("events_events_str", _mut_events_events_str),
    ("events_bad_row", _mut_events_bad_row),
    ("summoner_spells_str", _mut_summoner_spells_str),
    ("vision_state_str", _mut_vision_state_str),
    ("enemies_str", _mut_enemies_str),
    ("enemies_value_str", _mut_enemies_value_str),
]

_RM318_DETECTOR_NAMES = [
    "detect_objective_contest_with_missing",
    "detect_low_hp_backable",
    "detect_lane_roam_window",
    "detect_postfight_objective",
    "detect_jungler_gank_likely",
    "detect_throwing_lead",
]


class TestRegistryIsWhatWeThinkItIs:
    """The matrix is parametrised by NAME, so it would silently stop
    covering a detector that was renamed or unregistered."""

    def test_registry_holds_exactly_the_six_named_detectors(self):
        assert ([fn.__name__ for fn in dd.DECISION_REGISTRY]
                == _RM318_DETECTOR_NAMES)


class TestRM318PositiveControls:
    """Load-bearing half. Without these the raise-free matrix below is
    satisfied by six detectors that return None unconditionally."""

    @pytest.mark.parametrize("name", _RM318_DETECTOR_NAMES)
    def test_well_formed_envelope_still_fires(self, name):
        fn = getattr(dd, name)
        snapshot, vision = _rm318_positive(name)
        decision = fn(snapshot, vision)
        assert decision is not None, (
            name + " no longer fires on a well-formed firing envelope - "
            "the hardening turned it into a no-op")
        assert isinstance(decision.id, str) and decision.id
        assert isinstance(decision.type, str) and decision.type
        assert isinstance(decision.options, list) and decision.options


class TestRM318MalformedEnvelopeDoesNotRaise:
    """A retyped Live Client field must degrade to "no decision", never to
    an exception. The loop catches per-detector exceptions, so a raise here
    is not a crash - it is a detector that is silently dead for the whole
    game while the heartbeat pill keeps counting up."""

    @pytest.mark.parametrize("name", _RM318_DETECTOR_NAMES)
    @pytest.mark.parametrize("shape,mutate", _RM318_SHAPES,
                             ids=[s[0] for s in _RM318_SHAPES])
    def test_detector_returns_none_or_a_decision(self, name, shape, mutate):
        fn = getattr(dd, name)
        snapshot, vision = _rm318_positive(name)
        vision = mutate(snapshot, vision)
        try:
            result = fn(snapshot, vision)
        except Exception as exc:  # noqa: BLE001 - the assertion IS the point
            raise AssertionError(
                f"{name} raised {type(exc).__name__} on shape "
                f"{shape}: {exc}") from exc
        assert result is None or isinstance(result, dd.Decision)


class TestRM318GreenControls:
    """Pinned as already-passing so the fix cannot be graded on them.

    `(snapshot.get("events") or {}).get("Events") or []` is guarded at
    :195 / :301 / :350 for the LIST case, and `_next_objective_spawn`
    isinstance-guards each event row. These pass at 8d4173c31 and must
    keep passing; they prove nothing about the hardening."""

    @pytest.mark.parametrize("name", _RM318_DETECTOR_NAMES)
    def test_events_as_a_list_was_already_safe(self, name):
        fn = getattr(dd, name)
        snapshot, vision = _rm318_positive(name)
        snapshot["events"] = []
        result = fn(snapshot, vision)
        assert result is None or isinstance(result, dd.Decision)

    @pytest.mark.parametrize("name", _RM318_DETECTOR_NAMES)
    def test_a_trailing_bad_all_players_row_was_already_safe(self, name):
        fn = getattr(dd, name)
        snapshot, vision = _rm318_positive(name)
        snapshot["allPlayers"] = list(snapshot["allPlayers"]) + ["E9"]
        result = fn(snapshot, vision)
        assert result is None or isinstance(result, dd.Decision)


class TestRM318HeartbeatIsNotBlinded:
    """Step 4 of the slice. The cycle-12 `detector_errors` heartbeat makes a
    retyped field VISIBLE; RM-318 prevents it. The prevention must not also
    swallow a GENUINE detector bug - if the hardening had been written as a
    blanket try/except inside each detector, `detector_errors` would report
    0 forever and the pill would go back to being unable to tell "alive and
    deciding not to fire" from "alive and crashing"."""

    def _run_one_pass(self, loop, snapshot, vision):
        # Same shape as TestHeartbeatSurfacesDetectorErrors._run_one_pass.
        # Setting _stop BEFORE calling _loop() runs ZERO passes (the flag
        # is checked at the top of the while), which is how the first draft
        # of this test read 0 errors and looked like a real finding.
        loop._fetch_snapshot = lambda: (snapshot, 0.1)
        loop._read_vision_state = lambda: vision
        loop._poll_s = 0.01
        t = threading.Thread(target=loop._loop, daemon=True)
        t.start()
        time.sleep(0.3)
        loop._stop.set()
        t.join(timeout=3)

    def test_a_genuinely_raising_detector_still_increments_the_counter(
            self, tmp_path, monkeypatch):
        def _boom(snapshot, vision_state):
            raise RuntimeError("genuine logic bug")

        _boom.__name__ = "detect_boom"
        monkeypatch.setattr(dd, "DECISION_REGISTRY",
                            list(dd.DECISION_REGISTRY) + [_boom])
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "pending.json",
            log_path=tmp_path / "log.jsonl"))
        snapshot, vision = _rm318_positive("detect_throwing_lead")
        self._run_one_pass(loop, snapshot, vision)
        hb = loop.heartbeat()
        assert hb["counter"] > 0, "loop must actually have run a pass"
        assert hb["detector_errors"] == 1
        assert hb["last_detector_error"].startswith(
            "detect_boom: RuntimeError")

    def test_a_malformed_envelope_reports_zero_errors_after_the_fix(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "pending.json",
            log_path=tmp_path / "log.jsonl"))
        snapshot, vision = _rm318_positive("detect_throwing_lead")
        snapshot["gameData"] = "12:34 CLASSIC"
        self._run_one_pass(loop, snapshot, vision)
        hb = loop.heartbeat()
        assert hb["counter"] > 0, "loop must actually have run a pass"
        assert hb["detector_errors"] == 0
        assert hb["last_detector_error"] is None
