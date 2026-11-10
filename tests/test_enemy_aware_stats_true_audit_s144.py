"""s144 true-audit (lane 8) - core/enemy_aware_stats.py.

One test per confirmed finding, each written RED against the pre-audit module:

* F1 The champion base layer was keyed by DDragon ``id`` only, but the Live
  Client ``championName`` the dashboard passes is the DISPLAY name ("Kai'Sa",
  "Lee Sin", "Wukong", "Nunu & Willump"). Those enemies silently got ZERO base
  armor / MR / HP - the P1-L4 understatement the layer exists to fix.
* F2 One malformed catalog row (non-dict entry, non-dict ``stats``, a
  non-numeric stat) aborted the WHOLE index load, disabling enemy-aware stats.
* F3 A non-finite stat (JSON ``NaN`` / ``Infinity``, which ``json.loads``
  accepts) passed ``float()`` and poisoned every ``target_*`` with nan / inf.
* F4 A junk ``level`` (``"abc"``, nan, inf) raised out of
  ``compute_target_stats_from_items`` when champions were supplied; a ``bool``
  level was taken as level 1; a ``str`` champion list was split into letters.
* F5 ``enemy_items_from_liveclient`` raised ``OverflowError`` on an
  ``itemID`` of Infinity, took ``True`` as item 1 and truncated 3047.5 to 3047.
* F6 ``active_player_team`` returned the FIRST game-name match, so a same
  game name on the other team (different tag) gave the wrong team, and a
  non-string ``team`` was returned as-is.
* F7 The loaders caught every ``Exception``; an unexpected one is now raised
  (and not cached) instead of silently disabling the module.
"""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from core import enemy_aware_stats as eas


def _champ(cid: str, name: str, armor: float = 30.0) -> dict:
    return {"id": cid, "name": name,
            "stats": {"armor": armor, "armorperlevel": 4.0,
                      "spellblock": 32.0, "spellblockperlevel": 2.0,
                      "hp": 600.0, "hpperlevel": 100.0}}


@pytest.fixture
def catalogs(tmp_path, monkeypatch):
    """Point both loaders at tmp files; reset caches and gates around the test."""
    champs = tmp_path / "ddragon_champions.json"
    items = tmp_path / "ddragon_items.json"
    monkeypatch.setattr(eas, "_CHAMPS_PATH", champs)
    monkeypatch.setattr(eas, "_ITEMS_PATH", items)

    def _reset() -> None:
        eas._CHAMP_INDEX = None
        eas._STAT_INDEX = None
        eas._CHAMP_GATE.reset()
        eas._STAT_GATE.reset()

    _reset()

    def write(champ_rows=None, item_rows=None, *, champ_text=None, item_text=None):
        if champ_text is None:
            champ_text = json.dumps({"data": champ_rows or {}})
        if item_text is None:
            item_text = json.dumps({"data": item_rows or {}})
        champs.write_text(champ_text, encoding="utf-8")
        items.write_text(item_text, encoding="utf-8")
        _reset()

    yield write
    _reset()


_THORNMAIL = {"3075": {"stats": {"FlatArmorMod": 75, "FlatHPPoolMod": 150}}}


# --- F1: display names resolve to the DDragon id's base stats ---------------

@pytest.mark.parametrize("display,cid", [
    ("Kai'Sa", "Kaisa"), ("Lee Sin", "LeeSin"), ("Wukong", "MonkeyKing"),
    ("Nunu & Willump", "Nunu"), ("Dr. Mundo", "DrMundo"),
])
def test_display_name_gets_the_champion_base(catalogs, display, cid):
    catalogs({cid: _champ(cid, display, armor=40.0)}, _THORNMAIL)
    by_id = eas._champ_base_by_level(cid, 11)
    by_display = eas._champ_base_by_level(display, 11)
    assert by_id[0] > 40.0
    assert by_display == by_id


@pytest.mark.parametrize("variant", ["kai'sa", "KAI'SA", "KaiSa", "kaisa"])
def test_case_and_punctuation_variants_resolve(catalogs, variant):
    catalogs({"Kaisa": _champ("Kaisa", "Kai'Sa", armor=25.0)}, _THORNMAIL)
    assert eas._champ_base_by_level(variant, 11) == eas._champ_base_by_level("Kaisa", 11)
    assert eas._champ_base_by_level(variant, 11)[0] > 25.0


def test_display_name_reaches_the_target_end_to_end(catalogs):
    catalogs({"Kaisa": _champ("Kaisa", "Kai'Sa", armor=25.0)}, _THORNMAIL)
    res = eas.compute_target_stats_from_items(
        [["3075"]], enemy_champions=["Kai'Sa"], level=1)
    assert res["source"] == "live-items+base"
    assert res["target_armor"] == 100.0  # 75 item + 25 base at level 1
    assert res["target_max_hp"] == 750.0


def test_unknown_champion_still_contributes_zero(catalogs):
    catalogs({"Garen": _champ("Garen", "Garen")}, _THORNMAIL)
    assert eas._champ_base_by_level("NotAChampion", 11) == (0.0, 0.0, 0.0, 0.0)
    assert eas._champ_base_by_level("", 11) == (0.0, 0.0, 0.0, 0.0)


def test_every_real_ddragon_display_name_resolves_to_its_id():
    """Against the shipped catalog: name and id give the same base for all."""
    eas._CHAMP_INDEX = None
    eas._CHAMP_GATE.reset()
    raw = json.loads(eas._CHAMPS_PATH.read_text(encoding="utf-8"))
    rows = raw.get("data", raw)
    assert len(rows) > 150
    differ = 0
    for cid, entry in rows.items():
        name = entry["name"]
        assert eas._champ_base_by_level(name, 9) == eas._champ_base_by_level(cid, 9), name
        assert eas._champ_base_by_level(cid, 9)[0] > 0.0, cid
        differ += name != cid
    assert differ >= 15  # the class this fix exists for is real in the data
    eas._CHAMP_INDEX = None


# --- F2: one bad row never disables the index ------------------------------

def test_bad_item_rows_are_skipped_not_fatal(catalogs):
    catalogs({}, {
        "1": "junk",
        "2": {"stats": "junk"},
        "3": {"stats": {"FlatArmorMod": "abc"}},
        "4": {"stats": {"FlatArmorMod": [5]}},
        **_THORNMAIL,
    })
    idx = eas._load_stat_index()
    assert idx.get("3075") == {"armor": 75.0, "mr": 0.0, "hp": 150.0}
    assert "1" not in idx and "2" not in idx
    assert eas._STAT_INDEX is idx  # a good load is cached


def test_bad_champion_rows_are_skipped_not_fatal(catalogs):
    catalogs({
        "Bad1": "junk",
        "Bad2": {"id": "Bad2", "stats": "junk"},
        "Bad3": {"id": "Bad3", "stats": {"armor": "abc", "hp": 500}},
        "Garen": _champ("Garen", "Garen", armor=36.0),
    }, _THORNMAIL)
    assert eas._champ_base_by_level("Garen", 1)[0] == 36.0
    assert eas._champ_base_by_level("Bad3", 1) == (0.0, 0.0, 500.0, 0.0)


@pytest.mark.parametrize("text", ["[1, 2]", '{"data": [1, 2]}', '"x"'],
                         ids=["list", "data-list", "string"])
def test_wrong_top_level_shape_is_a_failure_not_cached(catalogs, text):
    catalogs(champ_text=text, item_text=text)
    assert eas._load_stat_index() == {}
    assert eas._load_champ_index() == {}
    assert eas._STAT_INDEX is None and eas._CHAMP_INDEX is None


# --- F3: non-finite stats never reach the target ---------------------------

def test_non_finite_item_stats_are_dropped(catalogs):
    catalogs({}, item_text=(
        '{"data": {"1": {"stats": {"FlatArmorMod": NaN}},'
        ' "2": {"stats": {"FlatSpellBlockMod": Infinity, "FlatHPPoolMod": 200}},'
        ' "3": {"stats": {"FlatHPPoolMod": "-Infinity"}}}}'))
    res = eas.compute_target_stats_from_items([["1", "2", "3"]])
    for key in ("target_armor", "target_mr", "target_max_hp", "target_bonus_hp"):
        assert math.isfinite(res[key]), key
    assert res["target_max_hp"] == 200.0
    assert res["target_mr"] == 0.0


def test_non_finite_champion_stats_are_dropped(catalogs):
    catalogs(champ_text=(
        '{"data": {"Garen": {"id": "Garen", "name": "Garen", "stats":'
        ' {"armor": NaN, "armorperlevel": Infinity, "spellblock": 30,'
        ' "hp": 600, "hpperlevel": 100}}}}'),
        item_text=json.dumps({"data": _THORNMAIL}))
    res = eas.compute_target_stats_from_items(
        [["3075"]], enemy_champions=["Garen"], level=11)
    for key in ("target_armor", "target_mr", "target_max_hp", "target_bonus_hp"):
        assert math.isfinite(res[key]), key
    assert res["target_armor"] == 75.0


# --- F4: junk level / champion list never raises ---------------------------

@pytest.mark.parametrize("level", ["abc", float("nan"), float("inf"), True, [11], {}],
                         ids=["str", "nan", "inf", "bool", "list", "dict"])
def test_junk_level_degrades_to_items_only(catalogs, level):
    catalogs({"Garen": _champ("Garen", "Garen")}, _THORNMAIL)
    res = eas.compute_target_stats_from_items(
        [["3075"]], enemy_champions=["Garen"], level=level)
    assert res["source"] == "live-items"
    assert res["target_armor"] == 75.0


def test_numeric_string_level_is_accepted(catalogs):
    catalogs({"Garen": _champ("Garen", "Garen", armor=30.0)}, _THORNMAIL)
    res = eas.compute_target_stats_from_items(
        [["3075"]], enemy_champions=["Garen"], level="1")
    assert res["source"] == "live-items+base"
    assert res["target_armor"] == 105.0


@pytest.mark.parametrize("champs", ["Garen", {"Garen": 1}, 5],
                         ids=["str", "dict", "int"])
def test_non_sequence_champion_list_is_ignored(catalogs, champs):
    catalogs({"Garen": _champ("Garen", "Garen")}, _THORNMAIL)
    res = eas.compute_target_stats_from_items(
        [["3075"]], enemy_champions=champs, level=11)
    assert res["source"] == "live-items"
    assert res["target_armor"] == 75.0


def test_float_and_int_item_ids_hit_the_catalog(catalogs):
    catalogs({}, _THORNMAIL)
    res = eas.compute_target_stats_from_items([[3075.0], [3075], ["3075"]])
    assert res["target_armor"] == 75.0
    assert res["n_enemies"] == 3


# --- F5: item ids from the live client -------------------------------------

@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), True,
                                 3047.5, -3047, "abc", "3047.5", [3047]],
                         ids=["inf", "-inf", "nan", "bool", "frac", "neg", "abc",
                              "fracstr", "list"])
def test_junk_item_id_is_skipped_never_raised(bad):
    data = {"allPlayers": [{"team": "CHAOS", "items": [
        {"itemID": bad, "slot": 0}, {"itemID": 3075, "slot": 1}]}]}
    assert eas.enemy_items_from_liveclient(data) == [[3075]]


def test_integral_float_and_string_item_ids_are_kept():
    data = {"allPlayers": [{"team": "CHAOS", "items": [
        {"itemID": 3047.0, "slot": 0}, {"itemID": " 3075 ", "slot": 1},
        {"itemId": 3065, "slot": 2}]}]}
    assert eas.enemy_items_from_liveclient(data) == [[3047, 3075, 3065]]


# --- F6: the active player's team ------------------------------------------

def test_same_game_name_on_both_teams_resolves_by_full_riot_id():
    data = {
        "activePlayer": {"summonerName": "Bob#EUW", "riotId": "Bob#EUW",
                         "riotIdGameName": "Bob"},
        "allPlayers": [
            {"riotIdGameName": "Bob", "riotId": "Bob#NA1",
             "summonerName": "Bob#NA1", "team": "ORDER"},
            {"riotIdGameName": "Bob", "riotId": "Bob#EUW",
             "summonerName": "Bob#EUW", "team": "CHAOS"},
        ],
    }
    assert eas.active_player_team(data) == "CHAOS"


def test_game_name_ambiguous_across_teams_is_none_not_a_guess():
    data = {
        "activePlayer": {"summonerName": "Bob"},
        "allPlayers": [{"riotIdGameName": "Bob", "team": "ORDER"},
                       {"riotIdGameName": "Bob", "team": "CHAOS"}],
    }
    assert eas.active_player_team(data) is None


@pytest.mark.parametrize("bad", [5, True, ["ORDER"], {"t": 1}, ""],
                         ids=["int", "bool", "list", "dict", "empty"])
def test_non_string_team_is_none(bad):
    data = {"activePlayer": {"summonerName": "Me#EUW"},
            "allPlayers": [{"riotIdGameName": "Me", "team": bad}]}
    assert eas.active_player_team(data) is None


def test_legacy_summoner_name_frame_still_resolves():
    data = {"activePlayer": {"summonerName": "Me"},
            "allPlayers": [{"summonerName": "Other", "team": "ORDER"},
                           {"summonerName": "Me", "team": "CHAOS"}]}
    assert eas.active_player_team(data) == "CHAOS"


# --- F8 (verifier find): a JSON integer too big for a float ----------------

_HUGE = "9" * 400  # valid JSON; float() of the parsed int raises OverflowError


def test_huge_integer_stat_reads_zero_not_raised(catalogs):
    catalogs(
        champ_text=('{"data": {"Garen": {"id": "Garen", "name": "Garen",'
                    ' "stats": {"armor": ' + _HUGE + ', "hp": 600}}}}'),
        item_text=('{"data": {"1": {"stats": {"FlatArmorMod": ' + _HUGE + '}},'
                   ' "3075": {"stats": {"FlatArmorMod": 75}}}}'))
    assert eas._load_stat_index().get("3075") == {"armor": 75.0, "mr": 0.0, "hp": 0.0}
    assert "1" not in eas._load_stat_index()
    assert eas._champ_base_by_level("Garen", 1) == (0.0, 0.0, 600.0, 0.0)


def test_huge_integer_level_degrades_to_items_only(catalogs):
    catalogs({"Garen": _champ("Garen", "Garen")}, _THORNMAIL)
    res = eas.compute_target_stats_from_items(
        [["3075"]], enemy_champions=["Garen"], level=int(_HUGE))
    assert res["source"] == "live-items"
    assert res["target_armor"] == 75.0


def test_huge_integer_slot_is_unknown_not_raised():
    data = {"allPlayers": [{"team": "CHAOS",
                            "items": [{"itemID": 3075, "slot": int(_HUGE)}]}]}
    assert eas.enemy_items_from_liveclient(data) == [[3075]]


def test_overlong_digit_item_id_is_skipped_not_raised(catalogs):
    """int() refuses a digit string past 4300 digits with ValueError."""
    catalogs({}, _THORNMAIL)
    long_id = "1" * 4400
    data = {"allPlayers": [{"team": "CHAOS", "items": [
        {"itemID": long_id, "slot": 0}, {"itemID": 3075, "slot": 1}]}]}
    assert eas.enemy_items_from_liveclient(data) == [[3075]]
    res = eas.compute_target_stats_from_items([[long_id, "3075"]])
    assert res["target_armor"] == 75.0


@pytest.mark.parametrize("bad", [5, 1.5, True, "3075", {"a": [3075]}],
                         ids=["int", "float", "bool", "str", "dict"])
def test_non_list_items_by_player_is_empty_not_raised(catalogs, bad):
    catalogs({}, _THORNMAIL)
    assert eas.compute_target_stats_from_items(bad) == eas._empty_stats()


def test_overflowing_stat_sum_is_empty_not_inf(catalogs):
    catalogs({}, {"1": {"stats": {"FlatArmorMod": 1e308}},
                  "2": {"stats": {"FlatArmorMod": 1e308}}})
    for agg in ("avg", "max", "top1"):
        res = eas.compute_target_stats_from_items([["1", "2"]], aggregator=agg)
        assert res == eas._empty_stats(), agg


# --- F7: the loaders no longer swallow an unexpected exception -------------

def test_unexpected_loader_error_surfaces_and_is_not_cached(catalogs, monkeypatch):
    catalogs({}, _THORNMAIL)

    def boom(*_a, **_k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(eas, "json", SimpleNamespace(loads=boom))
    with pytest.raises(RuntimeError):
        eas._load_stat_index()
    assert eas._STAT_INDEX is None
