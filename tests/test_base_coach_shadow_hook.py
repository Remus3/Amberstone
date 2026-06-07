"""A3: BaseCoach._shadow_log_hints fail-soft shadow-log hook.

Verifies the live-coach dispatch path forwards a canonicalized matchup to
core.ds_coach_shadow.log_coach_hints, returns early on a blank champion, and
swallows any downstream exception (it runs in the hot coach path).
"""
from __future__ import annotations

import pytest

from coaches._base_coach import BaseCoach


class _StubCoach(BaseCoach):
    _MODE_NAME = "aram"

    def _blank_artifact_data(self) -> dict:
        return {}

    def _parse_raw_state(self, raw: dict) -> dict:
        return {}

    def _run_coach(self, state: dict) -> None:
        pass

    def _run_vision(self) -> None:
        pass


def _inst() -> _StubCoach:
    # __new__ skips __init__ so no poll/vision threads spawn in the test.
    obj = _StubCoach.__new__(_StubCoach)
    obj._MODE_NAME = "aram"
    return obj


def test_forwards_canonicalized_matchup(monkeypatch):
    captured = {}

    def _fake(mode, my_champ, enemies, *, game_time_s=None):
        captured["mode"] = mode
        captured["my"] = my_champ
        captured["enemies"] = list(enemies)
        captured["t"] = game_time_s
        return {}

    monkeypatch.setattr("core.ds_coach_shadow.log_coach_hints", _fake)
    state = {
        "champion": "Vayne",
        "enemies": [
            {"name": "Malphite", "is_dead": False},
            {"name": "Ornn"},
            {"name": "Tahm Kench"},  # display-name -> canonical TahmKench
        ],
        "game_seconds": 1200,
    }
    _inst()._shadow_log_hints(state)
    assert captured["mode"] == "aram"
    assert captured["my"] == "Vayne"
    assert captured["enemies"] == ["Malphite", "Ornn", "TahmKench"]
    assert captured["t"] == 1200


def test_blank_champion_returns_early(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "core.ds_coach_shadow.log_coach_hints",
        lambda *a, **k: calls.append(a),
    )
    _inst()._shadow_log_hints({"champion": "", "enemies": [{"name": "Ornn"}]})
    assert calls == []


def test_game_time_s_fallback(monkeypatch):
    captured = {}

    def _fake(mode, my_champ, enemies, *, game_time_s=None):
        captured["t"] = game_time_s
        return {}

    monkeypatch.setattr("core.ds_coach_shadow.log_coach_hints", _fake)
    # no game_seconds; falls back to game_time_s
    _inst()._shadow_log_hints({"champion": "Lux", "game_time_s": 777})
    assert captured["t"] == 777


def test_skips_non_dict_and_nameless_enemies(monkeypatch):
    captured = {}

    def _fake(mode, my_champ, enemies, *, game_time_s=None):
        captured["enemies"] = list(enemies)
        return {}

    monkeypatch.setattr("core.ds_coach_shadow.log_coach_hints", _fake)
    state = {
        "champion": "Lux",
        "enemies": ["notadict", {"is_dead": True}, {"name": "Sion"}],
    }
    _inst()._shadow_log_hints(state)
    assert captured["enemies"] == ["Sion"]


def test_never_raises_when_writer_explodes(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("core.ds_coach_shadow.log_coach_hints", _boom)
    # Must not propagate - the hook runs in the live coach dispatch path.
    _inst()._shadow_log_hints({"champion": "Vayne", "enemies": []})


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
