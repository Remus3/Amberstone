"""Tests for tools/gated_g505_mode_mods.py (G5-05 CHECK A stat half + CHECK B coach half).

Every capture and row here is hand-written and synthetic (RM-906): no real
Riot id, game id or match key.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from tools import gated_g505_mode_mods as g

ME = "Synthetic#0001"
CHAMPS = {"Vayne": {"name": "Vayne", "key": "67"}, "Quinn": {"name": "Quinn", "key": "133"}}
# Vayne level 9 ARENA, no items (measured in-process at DS 1.290.0, G5-05 row).
VAYNE_OFF = {"hp": 1240.52, "ad": 75.839}
VAYNE_ON = {"hp": 1173.12, "ad": 73.143}
CUT = datetime(2026, 10, 27, tzinfo=timezone.utc)
AFTER = CUT.timestamp() + 60


def capture(level=9, hp=1173.12, ad=73.143, items=(), wrap="data"):
    lc = {
        "activePlayer": {"riotId": ME, "level": level,
                         "championStats": {"maxHealth": hp, "attackDamage": ad}},
        "allPlayers": [
            {"riotId": "Synthetic#0002", "championName": "Quinn",
             "rawChampionName": "game_character_displayname_Quinn", "items": []},
            {"riotId": ME, "championName": "Vayne",
             "rawChampionName": "game_character_displayname_Vayne",
             "items": [{"itemID": i} for i in items]},
        ],
        "gameData": {"gameTime": 612.5, "gameMode": "CHERRY"},
    }
    return {wrap: lc} if wrap else lc


def fake_compute(champ, level, items, augments, flag):
    if "999999" in items:
        raise KeyError("999999")
    return dict(VAYNE_ON if flag else VAYNE_OFF)


def addends(champ):
    return {"hp": {"per": -10.0}, "ad": {"per": -0.4}, "as": {"per": -0.3}} if champ == "Vayne" else None


def stat(doc, clean=True, augments=()):
    return g.check_stat(doc, list(augments), clean, CHAMPS, fake_compute, addends)


# -- CHECK A -------------------------------------------------------------------

def test_stat_pass_when_live_sits_on_the_on_line():
    rep = stat(capture())
    assert rep["status"] == "PASS"
    assert rep["addend_axes"] == ["hp", "ad"]
    assert rep["sample"]["champion"] == "Vayne"


def test_stat_fail_when_live_sits_on_the_off_line():
    rep = stat(capture(hp=1240.52, ad=75.839))
    assert rep["status"] == "FAIL"


def test_stat_fail_on_one_axis_beats_a_pass_on_the_other():
    rep = stat(capture(hp=1173.12, ad=75.839))
    assert rep["status"] == "FAIL"


def test_stat_midpoint_is_no_result():
    rep = stat(capture(hp=(1173.12 + 1240.52) / 2, ad=(73.143 + 75.839) / 2))
    assert rep["status"] == "NO_RESULT"
    assert "neither" in rep["why"]


def test_stat_pass_is_capped_until_clean_is_asserted():
    rep = stat(capture(), clean=False)
    assert rep["status"] == "INCOMPLETE"
    assert rep["would_be"] == "PASS"


def test_stat_fail_is_capped_until_clean_is_asserted():
    rep = stat(capture(hp=1240.52, ad=75.839), clean=False)
    assert rep["status"] == "INCOMPLETE"
    assert rep["would_be"] == "FAIL"


def test_stat_below_level_six_is_no_result():
    rep = stat(capture(level=5))
    assert rep["status"] == "NO_RESULT"
    assert "level" in rep["why"]


def test_stat_unknown_item_is_no_result():
    rep = stat(capture(items=(999999,)))
    assert rep["status"] == "NO_RESULT"
    assert "unknown id" in rep["why"]


def test_stat_champion_without_ar_block_is_no_result():
    doc = capture()
    lc = doc["data"]
    lc["activePlayer"]["riotId"] = "Synthetic#0002"
    rep = stat(doc)
    assert rep["status"] == "NO_RESULT"
    assert "no ar block" in rep["why"]


def test_stat_small_gap_axis_is_dropped():
    rows = g.grade_axes({"hp": 1173.12, "ad": 73.143}, {"hp": 1173.12, "ad": 73.143},
                        {"hp": 1240.52, "ad": 74.0}, ["hp", "ad"])
    assert rows["axes"]["ad"]["dropped"].startswith("gap under")
    assert rows["status"] == "PASS"


def test_stat_every_axis_dropped_is_no_result():
    rows = g.grade_axes({"hp": 1000.0}, {"hp": 1000.0}, {"hp": 1005.0}, ["hp"])
    assert rows["status"] == "NO_RESULT"
    assert rows["why"] == "no axis left"


def test_stat_no_own_row_is_no_result():
    doc = capture()
    doc["data"]["activePlayer"]["riotId"] = "Synthetic#0009"
    rep = stat(doc)
    assert rep["status"] == "NO_RESULT"


@pytest.mark.parametrize("wrap", ["data", "liveclient", None])
def test_stat_reads_every_capture_shape(wrap):
    assert stat(capture(wrap=wrap))["status"] == "PASS"


def test_stat_resolves_display_name_when_raw_name_is_absent():
    doc = capture()
    for p in doc["data"]["allPlayers"]:
        p.pop("rawChampionName")
    assert stat(doc)["sample"]["champion"] == "Vayne"


def test_stat_real_engine_vayne_compute_half():
    # In-process DS (no network): the ON / OFF lines the predicate brackets.
    compute, addends_of = g._ds_compute()
    assert set(addends_of("Vayne")) >= {"hp", "ad"}
    on = compute("Vayne", 9, [], [], True)
    off = compute("Vayne", 9, [], [], False)
    assert on["hp"] < off["hp"] and on["ad"] < off["ad"]
    assert addends_of("Tristana") is None


# -- CHECK B -------------------------------------------------------------------

def row(flag="absent", ts=AFTER, mode="ARENA", champ="Vayne", picks=("1", "2", "3"),
        engine="1.290.0"):
    r = {"ts": ts, "champion": champ, "mode": mode, "level": 9, "owned_items": ["1055"],
         "ds_picks": [{"item_id": p} for p in picks], "match_key": "synthetic-key"}
    if flag != "absent":
        r.update({"apply_mode_modifiers": flag, "engine_version": engine,
                  "enemy_stats": {"armor": 80.0, "mr": 60.0, "max_hp": 2500.0,
                                  "bonus_hp": 0.0, "ad_share": 0.5, "ap_share": 0.5},
                  "augments": []})
    return r


def rerun_with(on, off):
    calls = []

    def rerun(r, flag):
        calls.append(flag)
        return list(on if flag else off)
    return rerun, calls


def test_coach_pass_when_row_matches_on_order():
    rerun, calls = rerun_with(("1", "2", "3"), ("2", "1", "3"))
    rep = g.check_coach([row(flag=True)], CUT, None, "1.290.0", rerun)
    assert rep["status"] == "PASS"
    assert calls == [True, False]


def test_coach_fail_when_row_matches_off_order():
    rerun, _ = rerun_with(("2", "1", "3"), ("1", "2", "3"))
    assert g.check_coach([row(flag=True)], CUT, None, "1.290.0", rerun)["status"] == "FAIL"


def test_coach_on_off_agree_is_no_result():
    rerun, _ = rerun_with(("1", "2", "3"), ("1", "2", "3"))
    rep = g.check_coach([row(flag=True)], CUT, None, "1.290.0", rerun)
    assert rep["status"] == "NO_RESULT"
    assert rep["graded"][0]["why"] == "ON and OFF agree"


def test_coach_matches_neither_is_no_result():
    rerun, _ = rerun_with(("4", "5", "6"), ("6", "5", "4"))
    rep = g.check_coach([row(flag=True)], CUT, None, "1.290.0", rerun)
    assert rep["status"] == "NO_RESULT"


def test_coach_empty_rerun_is_no_result():
    rep = g.check_coach([row(flag=True)], CUT, None, "1.290.0", lambda r, f: None)
    assert rep["graded"][0]["why"] == "a re-run returned nothing"


def test_coach_keyless_row_is_never_rerun():
    rerun, calls = rerun_with(("1", "2", "3"), ("2", "1", "3"))
    rep = g.check_coach([row()], CUT, None, "1.290.0", rerun)
    assert rep["status"] == "NO_RESULT"
    assert rep["vintage"]["pre_rm875"] == 1
    assert "predate RM-875" in rep["why"]
    assert calls == []


def test_coach_flag_off_row_is_never_rerun():
    rerun, calls = rerun_with(("1", "2", "3"), ("2", "1", "3"))
    rep = g.check_coach([row(flag=False)], CUT, None, "1.290.0", rerun)
    assert rep["vintage"]["flag_off"] == 1
    assert "flag OFF" in rep["why"]
    assert calls == []


def test_coach_engine_version_mismatch_is_no_result():
    rerun, calls = rerun_with(("1", "2", "3"), ("2", "1", "3"))
    rep = g.check_coach([row(flag=True, engine="1.289.0")], CUT, None, "1.290.0", rerun)
    assert rep["graded"][0]["why"] == "engine_version differs"
    assert calls == []


def test_coach_without_rerun_owes_it():
    rep = g.check_coach([row(flag=True)], CUT, None, "1.290.0", None)
    assert rep["status"] == "NO_RESULT"
    assert "re-run owed" in rep["graded"][0]["why"]


def test_coach_one_fail_beats_a_pass():
    rows = [row(flag=True), row(flag=True, picks=("2", "1", "3"))]
    rerun, _ = rerun_with(("1", "2", "3"), ("2", "1", "3"))
    assert g.check_coach(rows, CUT, None, "1.290.0", rerun)["status"] == "FAIL"


def test_coach_window_mode_and_champion_filters():
    rows = [row(flag=True, ts=CUT.timestamp() - 60), row(flag=True, mode="ARAM"),
            row(flag=True, champ="Quinn"), row(flag=True, champ="vayne")]
    rerun, _ = rerun_with(("1", "2", "3"), ("2", "1", "3"))
    rep = g.check_coach(rows, CUT, "Vayne", "1.290.0", rerun)
    assert rep["rows"] == 1
    assert rep["status"] == "PASS"


def test_coach_no_cutoff_is_no_result():
    assert g.check_coach([row(flag=True)], None, None, "1.290.0")["status"] == "NO_RESULT"


def test_row_time_reads_epoch_and_iso():
    assert g.row_time({"ts": AFTER}) > CUT
    assert g.row_time({"ts": "2026-10-27T01:00:00Z"}) > CUT
    assert g.row_time({"ts": "nonsense"}) is None


def test_graded_rows_carry_no_match_key():
    rerun, _ = rerun_with(("1", "2", "3"), ("2", "1", "3"))
    rep = g.check_coach([row(flag=True)], CUT, None, "1.290.0", rerun)
    assert "synthetic-key" not in json.dumps(rep)


# -- CLI -----------------------------------------------------------------------

def test_cli_coach_reads_data_root_and_exits_incomplete(tmp_path, capsys):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ds_calibration.jsonl").write_text(
        json.dumps(row()) + "\n" + "not json\n", encoding="utf-8")
    rc = g.main(["coach", "--since", "2026-10-27T00:00:00Z", "--data-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "G5-05 coach: INCOMPLETE" in out
    assert "pre_rm875': 1" in out


def test_cli_stat_missing_capture_exits_incomplete(tmp_path, capsys):
    rc = g.main(["stat", "--lc", str(tmp_path / "absent.json"), "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert rep["status"] == "NO_RESULT"
