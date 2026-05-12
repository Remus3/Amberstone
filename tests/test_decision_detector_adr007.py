"""Tests for ADR-007 (s169) additions to core/decision_detector.py.

Covers:
  - Tightened detect_low_hp_backable (25% HP / 90s alive)
  - New detect_jungler_gank_likely (Smite + missing outside own jungle)
  - New detect_throwing_lead (2 deaths within 45s post-8min)
  - DecisionLoop.heartbeat() counter + reset + file-backed read

Pure-function tests for detectors — no live game, no relay, no
supervisor. Snapshot dicts are hand-built minimal fixtures matching
the Live Client API shape.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.decision_detector import (
    DecisionLoop,
    detect_jungler_gank_likely,
    detect_low_hp_backable,
    detect_throwing_lead,
    read_heartbeat,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _smite_spells() -> dict:
    return {
        "summonerSpellOne": {"displayName": "Smite", "rawDescription": ""},
        "summonerSpellTwo": {"displayName": "Flash", "rawDescription": ""},
    }


def _flash_ignite() -> dict:
    return {
        "summonerSpellOne": {"displayName": "Flash", "rawDescription": ""},
        "summonerSpellTwo": {"displayName": "Ignite", "rawDescription": ""},
    }


def _base_snapshot(*, game_time: float = 600.0,
                   game_mode: str = "CLASSIC",
                   self_name: str = "Me#NA1",
                   self_hp_pct: float = 1.0,
                   self_team: str = "ORDER",
                   self_is_dead: bool = False,
                   events: list | None = None,
                   enemies_have_smite: bool = True) -> dict:
    """Minimal Live Client snapshot. Two-player teams to keep the
    fixture small; tests that need a specific JG name set
    enemies_have_smite=True (default) so the first enemy in allPlayers
    is the JG."""
    max_hp = 2000.0
    cur_hp = max_hp * self_hp_pct
    all_players = [
        {
            "summonerName": self_name,
            "riotIdGameName": self_name,
            "team": self_team,
            "championName": "Me",
            "isDead": self_is_dead,
            "summonerSpells": _flash_ignite(),
        },
    ]
    enemy_team = "CHAOS" if self_team == "ORDER" else "ORDER"
    all_players.append({
        "summonerName": "EnemyJG#NA1",
        "riotIdGameName": "EnemyJG#NA1",
        "team": enemy_team,
        "championName": "Lee Sin",
        "isDead": False,
        "summonerSpells": _smite_spells() if enemies_have_smite else _flash_ignite(),
    })
    all_players.append({
        "summonerName": "EnemyMid#NA1",
        "riotIdGameName": "EnemyMid#NA1",
        "team": enemy_team,
        "championName": "Syndra",
        "isDead": False,
        "summonerSpells": _flash_ignite(),
    })
    return {
        "gameData": {"gameTime": game_time, "gameMode": game_mode},
        "activePlayer": {
            "summonerName": self_name,
            "riotIdGameName": self_name,
            "championStats": {"currentHealth": cur_hp, "maxHealth": max_hp},
        },
        "allPlayers": all_players,
        "events": {"Events": events or []},
    }


def _vision_state_with_missing_jg(*, missing_for_s: float,
                                  last_seen_zone: str,
                                  jg_name: str = "EnemyJG#NA1") -> dict:
    return {
        "enemies": {
            jg_name: {
                "champion": "Lee Sin",
                "summoner_name": jg_name,
                "team": "CHAOS",
                "is_dead": False,
                "visible": False,
                "missing_for_s": missing_for_s,
                "last_seen_zone": last_seen_zone,
            },
        },
    }


# ── detect_low_hp_backable ────────────────────────────────────────────────────


class TestLowHpBackable:
    """ADR-007 tightening: HP threshold 40%→25%, alive 45s→90s."""

    def test_fires_at_20pct_hp_with_120s_alive(self):
        snap = _base_snapshot(
            game_time=600.0,
            self_hp_pct=0.20,
            events=[{"EventName": "ChampionKill",
                     "VictimName": "Me#NA1", "EventTime": 480.0}],
        )
        d = detect_low_hp_backable(snap, {})
        assert d is not None
        assert d.type == "low_hp_back"
        assert "back" in d.options

    def test_does_not_fire_at_30pct_hp(self):
        """30% used to fire; now needs <25%."""
        snap = _base_snapshot(
            game_time=600.0,
            self_hp_pct=0.30,
            events=[{"EventName": "ChampionKill",
                     "VictimName": "Me#NA1", "EventTime": 480.0}],
        )
        assert detect_low_hp_backable(snap, {}) is None

    def test_does_not_fire_when_alive_lt_90s(self):
        """Alive 60s used to be enough (45s threshold); now needs ≥90s."""
        snap = _base_snapshot(
            game_time=600.0,
            self_hp_pct=0.20,
            events=[{"EventName": "ChampionKill",
                     "VictimName": "Me#NA1", "EventTime": 540.0}],
        )
        assert detect_low_hp_backable(snap, {}) is None

    def test_does_not_fire_when_dead(self):
        snap = _base_snapshot(self_hp_pct=0.10, self_is_dead=True)
        assert detect_low_hp_backable(snap, {}) is None

    def test_does_not_fire_when_max_hp_zero(self):
        snap = _base_snapshot()
        snap["activePlayer"]["championStats"]["maxHealth"] = 0
        assert detect_low_hp_backable(snap, {}) is None


# ── detect_jungler_gank_likely ────────────────────────────────────────────────


class TestJunglerGankLikely:

    def test_fires_when_jg_missing_outside_jungle(self):
        snap = _base_snapshot(game_time=400.0)
        vs = _vision_state_with_missing_jg(
            missing_for_s=25.0, last_seen_zone="top_river",
        )
        d = detect_jungler_gank_likely(snap, vs)
        assert d is not None
        assert d.type == "jungler_gank"
        assert d.options == ["safe", "punish"]
        assert d.context["last_seen_zone"] == "top_river"

    def test_skips_when_jg_in_own_jungle(self):
        # Enemy (CHAOS) JG in red_top_jungle is in their own jungle.
        snap = _base_snapshot(game_time=400.0)
        vs = _vision_state_with_missing_jg(
            missing_for_s=25.0, last_seen_zone="red_top_jungle",
        )
        assert detect_jungler_gank_likely(snap, vs) is None

    def test_skips_when_jg_missing_short(self):
        snap = _base_snapshot(game_time=400.0)
        vs = _vision_state_with_missing_jg(
            missing_for_s=10.0, last_seen_zone="top_river",
        )
        assert detect_jungler_gank_likely(snap, vs) is None

    def test_skips_when_no_smite_on_enemy_team(self):
        snap = _base_snapshot(game_time=400.0, enemies_have_smite=False)
        vs = _vision_state_with_missing_jg(
            missing_for_s=25.0, last_seen_zone="top_river",
        )
        assert detect_jungler_gank_likely(snap, vs) is None

    def test_skips_on_aram(self):
        snap = _base_snapshot(game_time=400.0, game_mode="ARAM")
        vs = _vision_state_with_missing_jg(
            missing_for_s=25.0, last_seen_zone="top_river",
        )
        assert detect_jungler_gank_likely(snap, vs) is None

    def test_skips_pre_3min(self):
        snap = _base_snapshot(game_time=120.0)
        vs = _vision_state_with_missing_jg(
            missing_for_s=25.0, last_seen_zone="top_river",
        )
        assert detect_jungler_gank_likely(snap, vs) is None

    def test_defers_to_objective_when_dragon_imminent(self):
        # Dragon spawn at 300; we're at 280 — within the 60s window.
        snap = _base_snapshot(game_time=280.0)
        vs = _vision_state_with_missing_jg(
            missing_for_s=25.0, last_seen_zone="top_river",
        )
        assert detect_jungler_gank_likely(snap, vs) is None

    def test_id_bucketed_to_90s_windows(self):
        # game_time // 90 — 400→4, 440→4, 460→5. Pick 400 + 440 for the
        # same-bucket assertion, 550 (→6) for new-bucket.
        snap = _base_snapshot(game_time=400.0)
        vs = _vision_state_with_missing_jg(
            missing_for_s=25.0, last_seen_zone="top_river",
        )
        d1 = detect_jungler_gank_likely(snap, vs)
        snap["gameData"]["gameTime"] = 440.0    # +40s, same bucket
        d2 = detect_jungler_gank_likely(snap, vs)
        assert d1 is not None and d2 is not None
        assert d1.id == d2.id   # same bucket → same id (no re-fire)

        snap["gameData"]["gameTime"] = 550.0    # bucket 6, new bucket
        d3 = detect_jungler_gank_likely(snap, vs)
        assert d3 is not None and d3.id != d1.id


# ── detect_throwing_lead ──────────────────────────────────────────────────────


class TestThrowingLead:

    def _snap_with_my_deaths(self, *, game_time: float,
                             death_times: list[float]):
        events = [
            {"EventName": "ChampionKill",
             "VictimName": "Me#NA1", "EventTime": t}
            for t in death_times
        ]
        return _base_snapshot(game_time=game_time, events=events)

    def test_fires_on_two_deaths_within_45s(self):
        # 2 deaths within 90s window, spread 30s, past 8min mark.
        snap = self._snap_with_my_deaths(
            game_time=600.0, death_times=[550.0, 580.0],
        )
        d = detect_throwing_lead(snap, {})
        assert d is not None
        assert d.type == "throwing_lead"
        assert d.context["death_count"] == 2

    def test_skips_pre_8min(self):
        snap = self._snap_with_my_deaths(
            game_time=400.0, death_times=[350.0, 380.0],
        )
        assert detect_throwing_lead(snap, {}) is None

    def test_skips_on_single_death(self):
        snap = self._snap_with_my_deaths(
            game_time=600.0, death_times=[550.0],
        )
        assert detect_throwing_lead(snap, {}) is None

    def test_skips_when_deaths_too_spread(self):
        # Two deaths but >45s apart → not a cluster.
        snap = self._snap_with_my_deaths(
            game_time=600.0, death_times=[510.0, 580.0],
        )
        assert detect_throwing_lead(snap, {}) is None

    def test_ignores_old_deaths_outside_90s_window(self):
        # First death at 480, second at 580 → first is outside the 90s
        # window from game_time=600 (window_start=510). Should treat as
        # only 1 death in window.
        snap = self._snap_with_my_deaths(
            game_time=600.0, death_times=[480.0, 580.0],
        )
        assert detect_throwing_lead(snap, {}) is None

    def test_ignores_other_players_deaths(self):
        snap = _base_snapshot(
            game_time=600.0,
            events=[
                {"EventName": "ChampionKill",
                 "VictimName": "EnemyJG#NA1", "EventTime": 560.0},
                {"EventName": "ChampionKill",
                 "VictimName": "EnemyMid#NA1", "EventTime": 580.0},
            ],
        )
        assert detect_throwing_lead(snap, {}) is None


# ── DecisionLoop heartbeat ────────────────────────────────────────────────────


class TestHeartbeat:

    def test_initial_heartbeat_zero(self):
        loop = DecisionLoop()
        hb = loop.heartbeat()
        assert hb["counter"] == 0
        assert hb["last_eval_unix"] is None
        assert hb["alive"] is False
        assert hb["detectors"] > 0   # registry is non-empty

    def test_heartbeat_alive_within_5s(self):
        loop = DecisionLoop()
        # Simulate a recent eval.
        with loop._heartbeat_lock:
            loop._eval_count = 7
            loop._last_eval_unix = time.time() - 1.0
        hb = loop.heartbeat()
        assert hb["counter"] == 7
        assert hb["alive"] is True
        assert hb["age_s"] is not None and hb["age_s"] < 5.0

    def test_heartbeat_stale_past_5s(self):
        loop = DecisionLoop()
        with loop._heartbeat_lock:
            loop._eval_count = 3
            loop._last_eval_unix = time.time() - 10.0
        hb = loop.heartbeat()
        assert hb["alive"] is False
        assert hb["age_s"] >= 10.0

    def test_read_heartbeat_missing_file(self, tmp_path, monkeypatch):
        # Point _HEARTBEAT_PATH at a missing file location.
        import core.decision_detector as dd
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH",
                            tmp_path / "missing.json")
        hb = read_heartbeat()
        assert hb["counter"] == 0
        assert hb["alive"] is False
        assert hb["last_eval_unix"] is None

    def test_read_heartbeat_roundtrip(self, tmp_path, monkeypatch):
        import core.decision_detector as dd
        path = tmp_path / "hb.json"
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", path)
        # Write a fresh heartbeat (alive).
        payload = {
            "counter": 42,
            "last_eval_unix": time.time() - 1.0,
            "age_s": 1.0,
            "alive": True,
            "game_time": 600.0,
            "detectors": 7,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        hb = read_heartbeat()
        assert hb["counter"] == 42
        # read_heartbeat() recomputes age_s + alive at read time.
        assert hb["alive"] is True
        assert hb["age_s"] < 5.0

    def test_read_heartbeat_recomputes_alive_when_stale(self, tmp_path, monkeypatch):
        import core.decision_detector as dd
        path = tmp_path / "hb.json"
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", path)
        # File says alive=True but timestamp is 30s old — read must
        # detect that and flip alive False.
        payload = {
            "counter": 50,
            "last_eval_unix": time.time() - 30.0,
            "age_s": 0.5,         # stale snapshot
            "alive": True,        # stale snapshot
            "game_time": 800.0,
            "detectors": 7,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        hb = read_heartbeat()
        assert hb["alive"] is False
        assert hb["age_s"] >= 30.0
