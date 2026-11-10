"""Lane-8 true-audit of core/defensive_picks.py (s144 cycle 233).

core/defensive_picks.py feeds the live /api/ds-preview "defensive" strip
(dashboard/routes_state.py), the situational build planner, the death
recap and the adaptive-summoners route. Every finding below was measured
red on the pre-audit module; the characterization block pins behaviour
the hardening must keep.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import core.defensive_picks as dp
from core.failed_load_gate import FailedLoadGate

_REPO = Path(__file__).resolve().parent.parent
_ITEMS_FILE = _REPO / "data" / "meta" / "ddragon_items.json"

_HIGH_THREAT = {"ad_threat": 8.0, "ap_threat": 8.0, "burst_threat": 8.0,
                "tank_pressure": 6.0}


@pytest.fixture
def fresh_index(tmp_path, monkeypatch):
    """Point the champ-info loader at a tmp file with a clean cache + gate."""
    target = tmp_path / "ddragon_champions.json"
    monkeypatch.setattr(dp, "_CHAMPS_PATH", target)
    monkeypatch.setattr(dp, "_CHAMP_INFO", None)
    monkeypatch.setattr(dp, "_CHAMP_INFO_GATE", FailedLoadGate())
    return target


def _entry(cid, name, tags, attack, magic, defense, difficulty=5):
    return {"id": cid, "name": name, "tags": tags,
            "info": {"attack": attack, "magic": magic, "defense": defense,
                     "difficulty": difficulty}}


def _names(recs):
    return [r["name"] for r in recs]


# ---------------------------------------------------------------- characterization

def test_empty_or_non_list_enemies_is_the_no_data_profile():
    for bad in ([], None, "Zed", {"Zed": 1}):
        prof = dp.compute_threat_profile(bad)
        assert prof["summary"] == "no enemy data"
        assert prof["top_threats"] == []
        assert prof["ad_threat"] == prof["ap_threat"] == 0.0


def test_profile_shape_and_known_burster_on_real_index():
    prof = dp.compute_threat_profile(["Zed", "Lux", "Malphite", "Jinx", "Leona"])
    assert set(prof) == {"ad_threat", "ap_threat", "burst_threat",
                         "tank_pressure", "top_threats", "summary"}
    for k in ("ad_threat", "ap_threat", "burst_threat", "tank_pressure"):
        assert 0.0 <= prof[k] <= 10.0
    assert {t["name"] for t in prof["top_threats"]} >= {"Zed"}
    assert len(prof["top_threats"]) <= 3


def test_recommendations_sorted_capped_and_boots_ceiling():
    recs = dp.recommend_defensive_items(_HIGH_THREAT, top_n=30)
    scores = [r["score"] for r in recs]
    assert scores == sorted(scores, reverse=True)
    boots = [r for r in recs if r["name"] in ("Plated Steelcaps", "Mercury's Treads")]
    assert boots and all(r["score"] <= 6.5 for r in boots)
    assert len(dp.recommend_defensive_items(_HIGH_THREAT, top_n=2)) == 2


def test_owned_item_by_name_is_still_skipped():
    recs = dp.recommend_defensive_items(_HIGH_THREAT, my_owned_items=["guardian angel"],
                                        top_n=30)
    assert "Guardian Angel" not in _names(recs)


def test_enemy_items_is_accepted_but_not_read():
    """F11 (docstring): the old docstring claimed enemy_items adjusted burst /
    AD for lethality and lifesteal stacking; no line ever read it."""
    champs = ["Zed", "Lux", "Malphite"]
    items = [["3142", "6693", "6694"], ["3089"], ["3068"]]
    assert dp.compute_threat_profile(champs, items) == dp.compute_threat_profile(champs)


def test_non_dict_threat_is_empty():
    assert dp.recommend_defensive_items(None) == []
    assert dp.recommend_defensive_items(["x"]) == []


# ---------------------------------------------------------------- F1 owned ids

def test_f1_owned_item_by_id_is_skipped():
    """/api/ds-preview passes item IDS (routes_state.py items = [str(i) ...]);
    the old filter matched NAMES only, so a bought Guardian Angel was still
    recommended and took one of the three strip slots."""
    recs = dp.recommend_defensive_items(_HIGH_THREAT, my_owned_items=["3026", 3157],
                                        top_n=30)
    assert "Guardian Angel" not in _names(recs)
    assert "Zhonya's Hourglass" not in _names(recs)


def test_f1_owned_mode_mirror_id_is_skipped():
    """An ARAM / map-30 mirror id (223026) is the same item as 3026."""
    recs = dp.recommend_defensive_items(_HIGH_THREAT, my_owned_items=["223026"],
                                        top_n=30)
    assert "Guardian Angel" not in _names(recs)


def test_f1_owned_string_is_not_iterated_per_character():
    recs = dp.recommend_defensive_items(_HIGH_THREAT, my_owned_items="3026",
                                        top_n=30)
    assert "Guardian Angel" not in _names(recs)


# ---------------------------------------------------------------- F2 catalog drift

def test_f2_every_catalog_id_is_a_purchasable_sr_item_of_that_name():
    """The curated ids drifted: 3001 is Evenshroud now (Abyssal Mask = 8020),
    and Adaptive Helm, Gargoyle Stoneplate, Silvermere Dawn are not SR
    purchasable - the panel rendered the wrong icon and unbuyable picks.
    The items file is tracked, so its absence is a failure, never a skip."""
    assert _ITEMS_FILE.is_file(), "tracked DDragon items file absent"
    data = json.loads(_ITEMS_FILE.read_text(encoding="utf-8"))
    data = data.get("data", data)
    bad = []
    for item in dp._DEFENSIVE_ITEMS:
        row = data.get(item["id"]) or {}
        ok = (row.get("name") == item["name"]
              and (row.get("maps") or {}).get("11") is True
              and (row.get("gold") or {}).get("purchasable") is not False)
        if not ok:
            bad.append((item["id"], item["name"], row.get("name")))
    assert bad == []


def test_f2_catalog_ids_are_unique_digit_strings():
    ids = [i["id"] for i in dp._DEFENSIVE_ITEMS]
    assert len(ids) == len(set(ids))
    assert all(isinstance(i, str) and i.isdigit() for i in ids)


# ---------------------------------------------------------------- F3 / F4 names

def test_f3_blank_slots_do_not_dilute_the_team_average():
    solo = dp.compute_threat_profile(["Zed"])
    padded = dp.compute_threat_profile(["Zed", "", None, "", "  "])
    for k in ("ad_threat", "ap_threat", "burst_threat", "tank_pressure"):
        assert padded[k] == solo[k], k


def test_f4_non_string_names_are_skipped_not_raised():
    prof = dp.compute_threat_profile(["Zed", {"x": 1}, ["Lux"], 7])
    assert prof == dp.compute_threat_profile(["Zed"])
    assert all(isinstance(t["name"], str) for t in prof["top_threats"])


def test_f4_all_junk_names_is_the_no_data_profile():
    assert dp.compute_threat_profile([None, "", {"a": 1}])["summary"] == "no enemy data"


# ---------------------------------------------------------------- F5 loader

def test_f5_one_malformed_entry_does_not_cost_the_whole_index(fresh_index):
    data = {
        "Zed": _entry("Zed", "Zed", ["Assassin"], 9, 1, 2),
        "Bad1": {"id": "Bad1", "name": "Bad One", "tags": [], "info": "oops"},
        "Bad2": _entry("Bad2", "Bad Two", ["Mage"], "high", 7, 3),
        "Bad3": _entry(5, None, ["Tank"], 5, 5, 5),
        "Bad4": _entry("Bad4", "Bad Four", "Assassin", 5, 5, 5),
        "Bad5": "not a dict",
    }
    fresh_index.write_text(json.dumps({"data": data}), encoding="utf-8")
    idx = dp._load_champ_info()
    assert idx["Zed"]["attack"] == 9
    # junk stat coerces to 0 like a missing one; the other stats survive
    assert idx["Bad Two"]["attack"] == 0 and idx["Bad Two"]["magic"] == 7
    # a string tags field is NOT exploded into characters
    assert idx["Bad Four"]["tags"] == []
    assert "Bad One" in idx and idx["Bad One"]["attack"] == 0


def test_f5_non_finite_and_out_of_range_stats_are_clamped(fresh_index):
    text = json.dumps({"data": {
        "Hi": _entry("Hi", "Hi", [], 99, -4, 5),
        "Fl": _entry("Fl", "Fl", [], 7.9, 2, 5),
    }})
    fresh_index.write_text(text.replace('"attack": 7.9', '"attack": NaN'), encoding="utf-8")
    idx = dp._load_champ_info()
    assert idx["Hi"]["attack"] == 10 and idx["Hi"]["magic"] == 0
    assert idx["Fl"]["attack"] == 0 and idx["Fl"]["magic"] == 2


def test_f5_an_index_with_no_usable_entry_is_a_failure_not_cached(fresh_index):
    fresh_index.write_text(json.dumps({"data": {"x": "junk", "y": 3}}), encoding="utf-8")
    assert dp._load_champ_info() == {}
    assert dp._CHAMP_INFO is None


# ---------------------------------------------------------------- F6 / F7 numbers

def test_f6_junk_threat_values_never_raise_or_emit_non_finite_scores():
    threat = {"ad_threat": "high", "ap_threat": float("nan"),
              "burst_threat": float("inf"), "tank_pressure": [1]}
    recs = dp.recommend_defensive_items(threat, top_n=30)
    assert all(math.isfinite(r["score"]) for r in recs)
    json.dumps(recs, allow_nan=False)


def test_f6_threat_values_are_clamped_to_the_documented_scale():
    big = dp.recommend_defensive_items({"ad_threat": 1e6}, top_n=30)
    ten = dp.recommend_defensive_items({"ad_threat": 10.0}, top_n=30)
    assert big == ten
    neg = dp.recommend_defensive_items({"ad_threat": -50, "ap_threat": 8}, top_n=30)
    assert neg == dp.recommend_defensive_items({"ad_threat": 0, "ap_threat": 8}, top_n=30)


def test_f7_damage_shares_stay_in_unit_interval():
    for threat in ({"ad_threat": -5, "ap_threat": 10},
                   {"ad_threat": float("nan"), "ap_threat": 3},
                   {"ad_threat": float("inf"), "ap_threat": 3},
                   {"ad_threat": "x", "ap_threat": None}):
        ad, ap = dp._threat_to_damage_shares(threat)
        assert 0.0 <= ad <= 1.0 and 0.0 <= ap <= 1.0, threat
        assert ad + ap <= 1.0 + 1e-9


def test_f6_non_finite_threat_reads_as_no_signal_not_max():
    """NaN / inf are junk (0), not the top of the scale: a clamp alone would
    read min(10, nan) as 10 and steer every pick toward that axis."""
    base = {"ap_threat": 3.0}
    for junk in (float("nan"), float("inf")):
        assert (dp.recommend_defensive_items({**base, "ad_threat": junk}, top_n=30)
                == dp.recommend_defensive_items({**base, "ad_threat": 0.0}, top_n=30))
        assert dp._threat_to_damage_shares({**base, "ad_threat": junk}) == (0.0, 1.0)


def test_f7_balanced_when_no_signal():
    assert dp._threat_to_damage_shares({"ad_threat": "x"}) == (0.5, 0.5)
    assert dp._threat_to_damage_shares({}) == (0.5, 0.5)


# ---------------------------------------------------------------- F8 EHP path

class _Row:
    def __init__(self, item_id, delta):
        self.item_id = item_id
        self.delta_ehp = delta


def _fake_ds(monkeypatch, rank_impl, up=True):
    import core.daemon_slayer_client as dsc
    monkeypatch.setattr(dsc, "is_engine_up", lambda *a, **k: up)
    monkeypatch.setattr(dsc, "rank_tank_for", rank_impl)


def test_f8_engine_rows_outside_catalog_fall_back_to_heuristic(monkeypatch):
    _fake_ds(monkeypatch, lambda *a, **k: [_Row("9999", 50.0)])
    recs = dp.recommend_defensive_items_via_ehp(_HIGH_THREAT, my_champion="Ahri")
    assert recs == dp.recommend_defensive_items(_HIGH_THREAT, "Ahri")
    assert recs


def test_f8_engine_raise_falls_back_to_heuristic(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("engine wedged")
    _fake_ds(monkeypatch, boom)
    recs = dp.recommend_defensive_items_via_ehp(_HIGH_THREAT, my_champion="Ahri")
    assert recs == dp.recommend_defensive_items(_HIGH_THREAT, "Ahri")


def test_f8_junk_level_and_owned_ids_reach_the_engine_sanely(monkeypatch):
    seen = {}

    def rank(champ, **kw):
        seen.update(kw)
        return [_Row("3026", 120.04), _Row(3157, 80.0)]
    _fake_ds(monkeypatch, rank)
    recs = dp.recommend_defensive_items_via_ehp(
        _HIGH_THREAT, my_champion="Ahri", my_owned_items=["3111"], my_level="junk")
    assert seen["level"] == 11
    assert "3111" not in seen["only_item_ids"]
    assert _names(recs) == ["Guardian Angel", "Zhonya's Hourglass"]
    assert recs[0]["score"] == 120.0


def test_f8_level_is_clamped(monkeypatch):
    seen = {}

    def rank(champ, **kw):
        seen.update(kw)
        return [_Row("3026", 1.0)]
    _fake_ds(monkeypatch, rank)
    dp.recommend_defensive_items_via_ehp(_HIGH_THREAT, my_champion="Ahri", my_level=99)
    assert seen["level"] == 18


# ---------------------------------------------------------------- F9 top_n

def test_f9_negative_top_n_is_empty_not_all_but_last():
    assert dp.recommend_defensive_items(_HIGH_THREAT, top_n=-1) == []


def test_f9_junk_top_n_uses_the_default():
    assert len(dp.recommend_defensive_items(_HIGH_THREAT, top_n="x")) == 4


# ---------------------------------------------------------------- F10 bursters

def test_f10_known_bursters_match_ddragon_ids_without_an_index(monkeypatch):
    """With the champ index unavailable only the static burster list can
    flag burst; it matched display names exactly, so the DDragon ids the
    planner passes ("Khazix", "Leblanc") were missed."""
    monkeypatch.setattr(dp, "_CHAMP_INFO", {})
    for name in ("Khazix", "Leblanc", "kha'zix"):
        prof = dp.compute_threat_profile([name])
        assert prof["burst_threat"] == 10.0, name
