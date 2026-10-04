# arch: regression - RM-236 six snapshot_normalizer defects (quest boots, soul, mirror, SR geometry, cooldown, obj timers) | section=vision | frozen=no
"""RM-236 - six `game_reader/snapshot_normalizer.py` defects, one test group
per item, each pinned to a concrete `/allgamedata` envelope.

(a) quest_boots_owned - validated against the DDragon recipe tree in
    data/daemon_slayer/16.15.1/items.json (and the live patch), not memory.
(b) the dragon soul note counted BOTH teams' drakes.
(c) a mirror matchup + name-match miss picked the ENEMY as self.
(d) SR coordinate math ran ungated on non-SR maps.
(e) my_abilities[*].cooldown was structurally always None.
(f) obj_timers_dict returned None for "objective is up right now".
"""

import json
from pathlib import Path

import pytest

from game_reader import snapshot_normalizer as sn
from game_reader.snapshot_normalizer import _NormalizerMixin

ROOT = Path(__file__).resolve().parent.parent


class _Host(_NormalizerMixin):
    def __init__(self, abilities=None):
        self._enemy_last_seen: dict = {}
        self._enemy_death_time: dict = {}
        self._abilities = abilities

    def _try_lcu_game_id(self):
        return None

    def _get(self, url):
        if url.endswith("/activeplayerabilities") and self._abilities is not None:
            return self._abilities
        raise RuntimeError("subresource not available in this test")


def _player(champ, name, team, level=6, items=(), pos=None, dead=False):
    return {
        "championName": champ, "riotIdGameName": name,
        "summonerName": f"{name}#NA1", "team": team, "level": level,
        "isDead": dead, "scores": {"creepScore": 10, "kills": 0,
                                   "deaths": 0, "assists": 0},
        "items": [{"displayName": i} for i in items],
        "position": pos if pos is not None else {"x": 0.0, "z": 0.0},
    }


def _env(players, *, active_name="Me", active_champ="Ahri", active_level=6,
         game_time=600.0, mode="CLASSIC", map_number=11, events=()):
    gd = {"gameMode": mode, "gameTime": game_time}
    if map_number is not None:
        gd["mapNumber"] = map_number
    return {
        "activePlayer": {"level": active_level, "currentGold": 100,
                         "summonerName": f"{active_name}#NA1",
                         "riotIdGameName": active_name,
                         "championName": active_champ,
                         "championStats": {}},
        "gameData": gd,
        "allPlayers": players,
        "events": {"Events": list(events)},
    }


def _std(items=()):
    return [
        _player("Ahri", "Me", "ORDER", items=items),
        _player("Sona", "Ally", "ORDER"),
        _player("Zed", "En", "CHAOS"),
        _player("Lux", "En2", "CHAOS"),
    ]


# ----------------------------------------------------------------------
# (a) quest boots
# ----------------------------------------------------------------------

def _tier3_from_ddragon(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("data", data)
    depth = {"1001": 0}
    changed = True
    while changed:
        changed = False
        for iid, it in items.items():
            if iid in depth or not isinstance(it, dict):
                continue
            src = [f for f in (it.get("from") or []) if f in depth]
            if src:
                depth[iid] = 1 + min(depth[f] for f in src)
                changed = True
    out = set()
    for iid, d in depth.items():
        it = items.get(iid) or {}
        if d >= 2 and not it.get("into") and (it.get("maps") or {}).get("11"):
            out.add(it["name"].lower())
    return out


@pytest.mark.parametrize("patch", ["16.15.1", "current"])
def test_a_tier3_set_matches_ddragon_recipe_tree(patch):
    if patch == "current":
        patch = (ROOT / "data/daemon_slayer/current.txt").read_text().strip()
    path = ROOT / f"data/daemon_slayer/{patch}/items.json"
    if not path.exists():
        pytest.skip(f"no items.json for {patch}")
    derived = _tier3_from_ddragon(path)
    assert derived, "empty derivation would make this guard vacuous"
    assert set(sn._TIER3_BOOTS) == derived


def test_a_no_boots_three_legendaries_is_not_quest_boots():
    st = _Host()._process_game(_env(_std(
        items=("Luden's Companion", "Rabadon's Deathcap", "Zhonya's Hourglass"))))
    assert st["quest_boots_owned"] is False


def test_a_tier2_boots_alone_is_not_quest_boots():
    st = _Host()._process_game(_env(_std(items=("Sorcerer's Shoes",))))
    assert st["quest_boots_owned"] is False


def test_a_tier3_boots_is_quest_boots():
    st = _Host()._process_game(_env(_std(items=("Spellslinger's Shoes",))))
    assert st["quest_boots_owned"] is True


# ----------------------------------------------------------------------
# (b) dragon soul per side
# ----------------------------------------------------------------------

def _drake(t, killer, dtype="Fire"):
    return {"EventName": "DragonKill", "EventTime": t, "KillerName": killer,
            "DragonType": dtype}


def test_b_two_one_split_is_not_a_soul_point():
    ev = [_drake(400, "Me"), _drake(800, "En"), _drake(1200, "Me")]
    st = _Host()._process_game(_env(_std(), game_time=1300.0, events=ev))
    assert "SOUL" not in st["objectives"]
    assert "[drakes 2-1]" in st["objectives"]


def test_b_three_zero_with_enemy_one_is_soul_point():
    ev = [_drake(400, "Me"), _drake(800, "Ally"), _drake(1200, "En"),
          _drake(1600, "Me")]
    st = _Host()._process_game(_env(_std(), game_time=1700.0, events=ev))
    assert "SOUL POINT - ally" in st["objectives"]


def test_b_elder_and_unknown_killer_not_counted():
    ev = [_drake(400, "Me"), _drake(800, "Me"), _drake(1200, "Baron?"),
          _drake(1600, "Me", "Elder")]
    st = _Host()._process_game(_env(_std(), game_time=1700.0, events=ev))
    assert "SOUL" not in st["objectives"]


# ----------------------------------------------------------------------
# (c) mirror matchup self-identification
# ----------------------------------------------------------------------

def test_c_mirror_name_miss_does_not_pick_enemy():
    players = [
        _player("Ahri", "Enemy", "CHAOS", level=9),
        _player("Ahri", "Renamed", "ORDER", level=6),
        _player("Sona", "Ally", "ORDER"),
        _player("Zed", "En", "CHAOS"),
    ]
    st = _Host()._process_game(_env(players, active_name="NoMatch",
                                    active_level=6))
    assert sorted(st["enemy_comp"]) == ["Ahri", "Zed"]
    assert st["ally_comp"] == ["Sona"]


def test_c_one_for_all_keeps_allies():
    players = [_player("Ahri", n, "ORDER") for n in ("Me", "A1", "A2")]
    players += [_player("Lux", n, "CHAOS") for n in ("E1", "E2")]
    st = _Host()._process_game(_env(players))
    assert st["ally_comp"] == ["Ahri", "Ahri"]
    assert len(st["ally_details"]) == 2


# ----------------------------------------------------------------------
# (d) SR geometry gated off SR
# ----------------------------------------------------------------------

def _deep_players():
    return [
        _player("Ahri", "Me", "ORDER", pos={"x": 11500.0, "z": 3000.0}),
        _player("Sona", "Ally", "ORDER", pos={"x": 1000.0, "z": 1000.0}),
        _player("Zed", "En", "CHAOS", pos={"x": 10500.0, "z": 5000.0}),
    ]


def test_d_sr_still_gets_position_note():
    st = _Host()._process_game(_env(_deep_players()))
    assert "OVEREXTENDED" in st["position_note"]


@pytest.mark.parametrize("mode,mapn", [("ARAM", 12), ("KIWI", 12),
                                       ("ARAM", None)])
def test_d_aram_has_no_sr_zone_text(mode, mapn):
    st = _Host()._process_game(_env(_deep_players(), mode=mode,
                                    map_number=mapn))
    assert st["position_note"] == ""
    assert "drake" not in st["enemy_locs"]
    assert st["gank_threat"] == ""


def test_d_urf_on_sr_map_keeps_geometry():
    st = _Host()._process_game(_env(_deep_players(), mode="URF",
                                    map_number=11))
    assert "OVEREXTENDED" in st["position_note"]


# ----------------------------------------------------------------------
# (e) no phantom cooldown
# ----------------------------------------------------------------------

def test_e_abilities_carry_no_cooldown_key():
    ab = {"Q": {"displayName": "Orb", "abilityLevel": 3},
          "R": {"displayName": "Rush", "abilityLevel": 1}}
    st = _Host(abilities=ab)._process_game(_env(_std()))
    assert st["my_abilities"]["q"] == {"name": "Orb", "level": 3}
    assert all("cooldown" not in v for v in st["my_abilities"].values())


# ----------------------------------------------------------------------
# (f) objective up == 0, not None
# ----------------------------------------------------------------------

def test_f_objective_up_is_zero_not_none():
    st = _Host()._process_game(_env(_std(), game_time=1300.0))
    assert st["obj_timers_dict"] == {"dragon": 0, "baron": 0}


def test_f_respawned_objective_is_zero():
    ev = [_drake(400, "Me")]
    st = _Host()._process_game(_env(_std(), game_time=800.0, events=ev))
    assert st["obj_timers_dict"]["dragon"] == 0


def test_f_countdown_unchanged():
    ev = [_drake(400, "Me")]
    st = _Host()._process_game(_env(_std(), game_time=600.0, events=ev))
    assert st["obj_timers_dict"]["dragon"] == 100
    assert st["obj_timers_dict"]["baron"] == 600
