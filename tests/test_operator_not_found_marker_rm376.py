"""RM-376: when the operator is not in `allPlayers`, the live snapshot used
to report `cs: 0`, `kda: "0/0/0"`, `items: []` beside a REAL level / gold /
HP, indistinguishable from a genuine 0/0/0 start.

Decision (consumer census in the commit): the snapshot gains an explicit
`operator_found: False` marker ONLY on the not-found path, and `kda` carries
the operator-approved `"-"` no-data sentinel instead of a measured-looking
"0/0/0" - kda is a display / prompt string at every consumer
(core/game_snapshot.py passes it through as str; coach prompts print it).
Numeric fields keep their types so no arithmetic consumer breaks. The
found path is unchanged: no new key, same values.
"""
from __future__ import annotations

import pytest


def _reader(monkeypatch):
    monkeypatch.setenv("RC_VISION_TOKEN", "rm376-test-token")
    import game_reader.snapshot_normalizer as sn  # noqa: F401
    from game_reader import GameReader
    r = GameReader()
    r._try_lcu_game_id = lambda: ""
    r._read_enemy_runes = lambda enemies: {}
    r._read_my_abilities = lambda: {}
    r._read_my_runes_structured = lambda: {}

    def _get(url, *a, **k):
        raise RuntimeError("hermetic")

    r._get = _get
    return r


def _raw(all_players):
    return {
        "gameData": {"gameTime": 1200.0, "gameMode": "CLASSIC", "mapNumber": 11},
        "activePlayer": {"championName": "Ahri", "riotIdGameName": "Moon",
                         "level": 13, "currentGold": 2400.0},
        "allPlayers": all_players,
        "events": {"Events": []},
    }


_ME = {"riotIdGameName": "Moon", "championName": "Ahri", "team": "ORDER",
       "level": 13, "items": [{"displayName": "Ludens Companion"}],
       "scores": {"creepScore": 150, "kills": 3, "deaths": 1, "assists": 2}}
_ENEMY = {"riotIdGameName": "Foe", "championName": "Zed", "team": "CHAOS",
          "level": 12, "items": [], "scores": {}}


def test_not_found_carries_marker_and_no_data_kda(monkeypatch):
    out = _reader(monkeypatch)._process_game(_raw([_ENEMY]))
    assert out["operator_found"] is False
    assert out["kda"] == "-"
    assert out["level"] == 13            # the REAL fields stay real


@pytest.mark.parametrize("players", [[_ME, _ENEMY]])
def test_found_path_is_unchanged(monkeypatch, players):
    out = _reader(monkeypatch)._process_game(_raw(players))
    assert "operator_found" not in out
    assert out["kda"] == "3/1/2"
    assert out["cs"] == 150
