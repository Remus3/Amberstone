"""Tests for tools/gated_g242_zoi_check.py (G2-42 PREP, s144 lane gated c46).

Every input is hand-built (RM-906: no real game, match or player id; the
summoner names below are synthetic). The tool is a read-only grader; these
tests pin its verdicts AND the three source facts its docstring cites (dead
SR fog feed, unwired DMZ, blanked live callouts), so a change that fixes one
of them turns a test red on purpose and the READY block gets re-read.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.minimap_districts import load_grid
from core.vision_tracker import VisionTracker
from core.zoi_influence import compute_zoi
from tools import gated_g242_zoi_check as g242

ROOT = Path(__file__).resolve().parent.parent
SR_IDS = sorted(d.id for d in load_grid("sr").districts)


def _rows(ids):
    return [{"district": i, "ally": 0, "enemy": 0} for i in ids]


def _state(zoi=None, mode="sr", lc=None, callouts=None):
    st = {"mode_key": mode, "liveclient": {"game_time_s": 300.0} if lc is None else lc,
          "callouts": callouts or []}
    if zoi is not None:
        st["zoi"] = zoi
    return st


def _head_zoi(**over):
    zoi = {"bubbles": [{"team": "ally"}, {"team": "enemy"}], "demarcation": {},
           "map_control": {}, "champion_dots": [], "districts": _rows(SR_IDS),
           "districts_fused": _rows(SR_IDS), "mia": {"rings": [], "count": 0}}
    zoi.update(over)
    return zoi


def test_sr_grid_has_thirteen_districts():
    assert len(g242.sr_district_ids()) == 13
    assert g242.sr_district_ids() == frozenset(SR_IDS)


def test_idle_and_non_sr_states_are_not_in_game():
    res = g242.grade_states([_state(mode="client", lc={}), _state(_head_zoi(), mode="aram")])
    assert res["in_game_sr"] == 0
    assert {res[k] for k in ("districts", "bubbles", "mia", "dmz")} == {"NOT_IN_GAME"}


def test_head_shaped_payload_grades_b_ok_and_dmz_not_wired():
    res = g242.grade_states([_state(_head_zoi())])
    assert res["districts"] == "B_OK"
    assert res["bubbles"] == "BUBBLES_PRESENT" and res["bubbles_max"] == 2
    assert res["mia"] == "MIA_EMPTY"
    assert res["dmz"] == "DMZ_NOT_WIRED"


def test_one_missing_district_or_fused_vector_is_b_missing():
    short = _head_zoi(districts=_rows(SR_IDS[1:]))
    assert g242.grade_states([_state(short)])["districts"] == "B_MISSING"
    nofuse = _head_zoi()
    del nofuse["districts_fused"]
    assert g242.grade_states([_state(nofuse)])["districts"] == "B_MISSING"


def test_rings_and_dmz_path_grade_present_and_none_dmz_is_degenerate():
    zoi = _head_zoi(mia={"rings": [{"x": 0.1}, {"x": 0.2}], "count": 2},
                    dmz={"path": [[0.1, 0.9], [0.9, 0.1]], "band_w_frac": 0.02})
    res = g242.grade_states([_state(_head_zoi()), _state(zoi)])
    assert res["mia"] == "MIA_RINGS" and res["mia_rings_max"] == 2
    assert res["dmz"] == "DMZ_PRESENT"
    assert g242.grade_states([_state(_head_zoi(dmz=None))])["dmz"] == "DMZ_DEGENERATE"
    nomia = _head_zoi()
    del nomia["mia"]
    assert g242.grade_states([_state(nomia)])["mia"] == "MIA_ABSENT"


def test_sr_game_without_zoi_is_zoi_absent_not_not_in_game():
    res = g242.grade_states([_state(None, mode="client")])
    assert res["in_game_sr"] == 1
    assert res["districts"] == "ZOI_ABSENT"


def test_served_macro_rows_are_counted():
    st = _state(_head_zoi(), callouts=[{"kind": "macro"}, {"kind": "wave"}])
    assert g242.grade_states([st])["served_macro_rows"] == 1


def _enemy(champ, missing=None, dead=False):
    return {"champion": champ, "summoner_name": "SyntheticName#TAG1", "team": "CHAOS",
            "is_dead": dead, "visible": missing is None, "missing_for_s": missing,
            "last_seen_t": None if missing is None else 100.0, "last_seen_zone": None}


def _vs(enemies, mode="CLASSIC"):
    return {"game_mode": mode, "enemies": enemies}


def test_fog_dead_live_and_empty():
    dead = _vs({c: _enemy(c) for c in ("Ahri", "Garen", "Jinx")})
    assert g242.grade_fog([dead])["verdict"] == "FEED_DEAD"
    live = _vs({"Ahri": _enemy("Ahri", 9.0), "Garen": _enemy("Garen", 12.5),
                "Jinx": _enemy("Jinx", 3.0), "Thresh": _enemy("Thresh", 20.0, dead=True)})
    res = g242.grade_fog([dead, live])
    assert res["verdict"] == "FEED_LIVE"
    assert res["mia_ge_min_max"] == 2
    assert res["champions_mia"] == ["Ahri", "Garen"]
    assert g242.grade_fog([_vs({})])["verdict"] == "NO_ENEMIES"


def test_fog_a_dead_enemy_alone_never_makes_the_feed_live():
    only_dead = _vs({"Ahri": _enemy("Ahri"), "Thresh": _enemy("Thresh", 30.0, dead=True)})
    res = g242.grade_fog([only_dead])
    assert res["verdict"] == "FEED_DEAD" and res["numeric_missing"] == 0


def test_fog_skips_non_sr_copies():
    aram = _vs({"Ahri": _enemy("Ahri", 9.0), "Garen": _enemy("Garen", 9.0)}, mode="ARAM")
    res = g242.grade_fog([aram, {"enemies": {"Ahri": _enemy("Ahri", 9.0)}}])
    assert res["verdict"] == "NOT_SR" and res["sr_files"] == 0
    assert res["skipped_modes"] == ["ARAM", ""]


def test_sr_game_modes_restate_production_gate():
    src = (ROOT / "core" / "sr_aram_worker.py").read_text(encoding="utf-8")
    m = re.search(r"is_sr_mode = gm_upper in \(([^)]*)\)", src)
    assert m, "sr_aram_worker SR gate moved; re-pin SR_GAME_MODES"
    assert g242.SR_GAME_MODES == set(re.findall(r'"([A-Z]+)"', m.group(1)))


def test_fog_output_never_carries_a_summoner_name():
    live = _vs({"Ahri": _enemy("Ahri", 9.0), "Garen": _enemy("Garen", 12.0)})
    assert "SyntheticName" not in json.dumps(g242.grade_fog([live]))


def _players(pos_a, pos_b):
    me = {"championName": "Lux", "team": "ORDER", "summonerName": "Me#TAG1",
          "position": "MIDDLE"}
    return [me,
            {"championName": "Ahri", "team": "CHAOS", "position": pos_a, "isDead": False},
            {"championName": "Garen", "team": "CHAOS", "position": pos_b, "isDead": False}]


def _tracker_rows(seq, mode="CLASSIC"):
    vt = VisionTracker(output_path=Path("unused.json"))
    vt._active_team = "ORDER"
    rows = {}
    for gt, players in seq:
        rows = vt._compute_enemies(players, gt, mode)
    return {"game_mode": mode, "enemies": rows}


def test_aram_dead_enemy_from_the_real_tracker_is_not_read_as_a_live_sr_feed():
    alive = _players("NONE", "NONE")
    dead = [dict(p) for p in alive]
    dead[1]["isDead"] = True
    doc = _tracker_rows([(100.0, alive), (130.0, dead)], mode="ARAM")
    # The tracker does give the dead ARAM enemy a numeric clock ...
    assert doc["enemies"]["Ahri"]["missing_for_s"] is not None
    # ... which the grader skips by mode and would also skip as dead.
    assert g242.grade_fog([doc])["verdict"] == "NOT_SR"
    doc["game_mode"] = "CLASSIC"
    assert g242.grade_fog([doc])["verdict"] == "FEED_DEAD"


def test_source_fact_role_string_position_keeps_the_sr_feed_dead():
    # The client sends position as a ROLE string on SR: the fog clock never starts.
    doc = _tracker_rows([(t, _players("MIDDLE", "TOP")) for t in (100.0, 110.0, 130.0)])
    assert g242.grade_fog([doc])["verdict"] == "FEED_DEAD"


def test_positive_control_coordinate_positions_make_the_feed_live():
    a, b = {"x": 7000.0, "z": 7000.0}, {"x": 2000.0, "z": 12000.0}
    doc = _tracker_rows([(100.0, _players(a, b)), (120.0, _players(a, b))])
    res = g242.grade_fog([doc])
    assert res["verdict"] == "FEED_LIVE" and res["mia_ge_min_max"] == 2


def test_source_fact_state_builder_passes_no_roster_so_no_dmz_key():
    src = (ROOT / "dashboard" / "_state_builder.py").read_text(encoding="utf-8")
    calls = re.findall(r"compute_zoi\((.*?)\)\n", src, flags=re.S)
    assert calls, "compute_zoi call site moved; re-read G2-42 READY"
    assert not any("roster" in c for c in calls)
    dots = [{"team": "blue", "x_frac": 0.3, "y_frac": 0.7, "px": 20, "confidence": 0.9},
            {"team": "red", "x_frac": 0.7, "y_frac": 0.3, "px": 20, "confidence": 0.9}]
    out = compute_zoi(dots, my_level=6, game_time_s=400.0)
    assert out is not None and "dmz" not in out
    # Positive control: the same dots WITH a roster carry the key, so the
    # absence above is the missing roster, not a malformed input.
    wired = compute_zoi(dots, my_level=6, game_time_s=400.0,
                        ally_roster=["Lux"], enemy_roster=["Ahri"])
    assert wired is not None and "dmz" in wired


def test_source_fact_live_envelope_blanks_served_callouts():
    from dashboard import _state_builder as sb
    assert "callouts" in sb.LIVE_SUPPRESSED_ENVELOPE_FIELDS


def _rec(ts, mode="sr", callouts=None, gt=250.0):
    return {"ts": ts, "mode": mode, "game_time_s": gt, "callouts": callouts or []}


def test_shadow_verdicts():
    since = datetime(2026, 1, 2, 18, 0, tzinfo=timezone.utc)
    old = _rec("2026-01-02T17:00:00+00:00", callouts=[{"kind": "macro", "tag": "dragon"}])
    assert g242.grade_shadow([old], since)["verdict"] == "NO_RESULT"
    aram = _rec("2026-01-02T18:05:00+00:00", mode="aram", callouts=[{"kind": "macro"}])
    assert g242.grade_shadow([aram], since)["verdict"] == "NO_RESULT"
    plain = _rec("2026-01-02T18:05:00+00:00", callouts=[{"kind": "wave"}])
    assert g242.grade_shadow([old, plain], since)["verdict"] == "NO_MACRO"
    gank = _rec("2026-01-02T18:05:30+00:00", callouts=[{"kind": "macro", "tag": "macro_gank_warning"}])
    res = g242.grade_shadow([plain, gank], since)
    assert res["verdict"] == "NO_MACRO" and res["other_macro_rows"] == 1
    hit = _rec("2026-01-02T18:06:00+00:00", mode="client",
               callouts=[{"kind": "macro", "tag": g242.OBJECTIVE_TAG, "line": "2 MIA - group"}])
    res = g242.grade_shadow([plain, gank, hit], since)
    assert res["verdict"] == "MACRO_SEEN" and res["macro_rows"] == 1
    assert res["first_macro"]["game_time_s"] == 250.0
    until = datetime(2026, 1, 2, 18, 5, 45, tzinfo=timezone.utc)
    assert g242.grade_shadow([plain, gank, hit], since, until)["verdict"] == "NO_MACRO"


def test_objective_tag_is_what_the_production_tree_emits():
    from core.macro_context import build_macro_context
    from core.macro_decision_tree import evaluate
    fog = {n: {"champion": n, "visible": False, "is_dead": False, "missing_for_s": 20.0,
               "last_seen_zone": "mid_lane"} for n in ("Ahri", "Garen")}
    row = evaluate(build_macro_context("sr", 260.0, enemies=fog, objective_events=[]))
    assert row is not None and row["kind"] == "macro"
    assert row["tag"] == g242.OBJECTIVE_TAG


def test_main_exit_codes(tmp_path, capsys):
    assert g242.main(["state", str(tmp_path / "missing.json")]) == 2
    idle = tmp_path / "idle.json"
    idle.write_text(json.dumps(_state(mode="client", lc={})), encoding="utf-8")
    assert g242.main(["state", str(idle), "--json"]) == 3
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_state(_head_zoi())), encoding="utf-8")
    assert g242.main(["state", str(good)]) == 0
    fog = tmp_path / "vs.json"
    fog.write_text(json.dumps(_vs({"Ahri": _enemy("Ahri", 9.0)})), encoding="utf-8")
    assert g242.main(["fog", str(fog), "--json"]) == 0
    log = tmp_path / "shadow.jsonl"
    log.write_text(json.dumps(_rec("2026-01-02T18:05:00+00:00")) + "\nnot json\n",
                   encoding="utf-8")
    assert g242.main(["shadow", str(log), "--since", "2026-01-02T13:00:00-05:00"]) == 3
    assert g242.main(["shadow", str(log), "--since", "2026-01-02T13:00:00"]) == 2
    capsys.readouterr()


@pytest.mark.parametrize("rel", ["tools/gated_g242_zoi_check.py",
                                 "tests/test_gated_g242_zoi_check.py"])
def test_files_are_ascii_lf(rel):
    data = (ROOT / rel).read_bytes()
    assert b"\r" not in data
    data.decode("ascii")
