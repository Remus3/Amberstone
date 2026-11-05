"""tools/gated_g5_focus_layout.py - the G5-11 read-back (s144 lane gated cycle 11).

Read-only plumbing for the next real Arena game; nothing here ticks a row. The
subteam truth is fed through the real producer (``lcu/champ_select_shape.py``
``arena_teams``) and the roster through the adapter under test
(``core/focus_board_live.py`` ``roster_from_lc``), so a shape change in either
breaks a test here. All data is synthetic: champion ids are placeholders with
made-up DDragon keys and no Riot id appears anywhere.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from lcu.champ_select_shape import arena_teams
from tools import gated_g5_focus_layout as g

ROOT = Path(__file__).resolve().parent.parent
CUT = datetime(2026, 10, 27, 13, 0, 0, tzinfo=timezone.utc)

CHAMPS = {
    "ChampA": {"key": "901", "name": "Champ A"},
    "ChampB": {"key": "902", "name": "Champ B"},
    "ChampC": {"key": "903", "name": "Champ C"},
    "ChampD": {"key": "904", "name": "Champ D"},
    "ChampE": {"key": "905", "name": "Champ E"},
    "ChampF": {"key": "906", "name": "Champ F"},
    "ChampG": {"key": "907", "name": "Champ G"},
}
KEY = {cid: int(rec["key"]) for cid, rec in CHAMPS.items()}


def _session(groups: list[list[str]], me_cell: int = 0) -> dict:
    """An LCU champ-select session with one subteam per group; cell ids count up."""
    cell = 0
    sub = []
    for i, grp in enumerate(groups, start=1):
        members = []
        for cid in grp:
            members.append({"cellId": cell, "championId": KEY[cid] if cid else 0})
            cell += 1
        sub.append({"subteamId": i, "name": f"Team {i}", "members": members})
    return {"localPlayerCellId": me_cell, "additionalSubteamData": sub}


def _cs(groups: list[list[str]], me_cell: int = 0) -> dict:
    """An /api/state capture carrying the real ``arena_teams`` distil."""
    return {"lcu": {"champ_select": {"arena_teams": arena_teams(_session(groups, me_cell))}}}


def _lc(players: list[tuple[str, str]], me: str = "Player0") -> dict:
    """A relay capture: ``(champion id, team value)`` per player, me first."""
    allp = [{"riotIdGameName": f"Player{i}", "championName": CHAMPS[c]["name"],
             "rawChampionName": f"game_character_displayname_{c}", "team": t,
             "level": 3, "items": []}
            for i, (c, t) in enumerate(players)]
    return {"ts": 1.0, "data": {"activePlayer": {"riotIdGameName": me, "level": 3},
                                "allPlayers": allp}}


DUO_GROUPS = [["ChampA", "ChampB"], ["ChampC", "ChampD"], ["ChampE", "ChampF"]]
DUO_LC = [("ChampA", "T1"), ("ChampB", "T1"), ("ChampC", "T2"), ("ChampD", "T2"),
          ("ChampE", "T3"), ("ChampF", "T3")]


def _fb(status="ok", allies=("ChampB",), kill=("ChampC", "ChampD")) -> dict:
    return {"status": status, "allies": list(allies), "kill_order": list(kill)}


def _row(ts="2026-10-27T13:05:00+00:00", fb=None, **extra) -> dict:
    rec = {"ts": ts, "mode": "arena", "champ": "Champ A", "round": "~3"}
    if fb is not None:
        rec["focus_board"] = fb
    rec.update(extra)
    return rec


def _rep(cs=None, lc=None, rows=(), cutoff=CUT) -> dict:
    return g.report(cs, lc, list(rows), cutoff, CHAMPS)


# -- the roster check (the adapter's own mapping against the subteam truth) ----

def test_duo_layout_with_per_subteam_team_values_passes():
    rep = _rep(_cs(DUO_GROUPS), _lc(DUO_LC), [_row(fb=_fb())])
    assert rep["checks"]["subteams"]["partners"] == ["ChampB"]
    assert rep["checks"]["roster"]["status"] == "PASS"
    assert rep["checks"]["roster"]["team_values"] == {"T1": 2, "T2": 2, "T3": 2}
    assert rep["verdict"] == "PASS"


def test_two_sided_team_values_fail_the_one_partner_premise():
    """If Riot spelled Arena as two big sides, the adapter calls 2 of the 5
    others allies; the subteam truth says one partner."""
    lc = _lc([(c, "ORDER" if i < 3 else "CHAOS") for i, (c, _t) in enumerate(DUO_LC)])
    rep = _rep(_cs(DUO_GROUPS), lc)
    assert rep["checks"]["roster"]["status"] == "FAIL"
    assert "allies" in rep["checks"]["roster"]["why"]
    assert rep["verdict"] == "FAIL"


def test_trio_subteams_with_matching_team_values_pass():
    groups = [["ChampA", "ChampB", "ChampC"], ["ChampD", "ChampE", "ChampF"]]
    lc = _lc([(c, "T1" if i < 3 else "T2") for i, c in enumerate(c for g in groups for c in g)])
    rep = _rep(_cs(groups), lc)
    assert rep["checks"]["subteams"]["sizes"] == [3, 3]
    assert rep["checks"]["subteams"]["partners"] == ["ChampB", "ChampC"]
    assert rep["checks"]["roster"]["status"] == "PASS"


def test_round_subset_roster_still_passes():
    """The Live Client may list only part of the lobby; the enemies need only be
    a sub-multiset of the other subteams."""
    rep = _rep(_cs(DUO_GROUPS), _lc(DUO_LC[:4]))
    assert rep["checks"]["roster"]["status"] == "PASS"
    assert rep["checks"]["roster"]["enemies"] == 2


def test_partner_listed_on_an_enemy_team_value_fails():
    lc = _lc([("ChampA", "T1"), ("ChampB", "T2")] + DUO_LC[2:])
    rep = _rep(_cs(DUO_GROUPS), lc)
    assert rep["checks"]["roster"]["status"] == "FAIL"
    assert "wrong side" in rep["checks"]["roster"]["why"]
    assert rep["verdict"] == "FAIL"


def test_live_roster_bigger_than_the_subteams_is_no_result():
    """An incomplete champ-select capture is not a layout fault (verifier s144g011)."""
    groups = [["ChampA", "ChampB"], ["ChampC", "ChampD"]]
    rep = _rep(_cs(groups), _lc(DUO_LC))
    assert rep["checks"]["roster"]["status"] == "NO_RESULT"
    assert "the subteams hold 4" in rep["checks"]["roster"]["why"]


def test_only_my_subteam_revealed_is_no_result():
    rep = _rep(_cs([["ChampA", "ChampB"]]), _lc(DUO_LC))
    assert rep["checks"]["subteams"]["status"] == "NO_RESULT"
    assert "not revealed" in rep["checks"]["subteams"]["why"]
    assert rep["verdict"] == "INCOMPLETE"


def test_empty_enemy_subteam_is_no_result():
    teams = arena_teams(_session(DUO_GROUPS))
    teams[1]["cells"] = []
    rep = _rep({"arena_teams": teams}, _lc(DUO_LC))
    assert rep["checks"]["subteams"]["status"] == "NO_RESULT"
    assert "empty" in rep["checks"]["subteams"]["why"]


def test_my_own_champion_as_ally_is_wrong_side():
    sub = g.check_subteams(arena_teams(_session(DUO_GROUPS)), "ChampA", CHAMPS)
    assert g.layout(["ChampA"], ["ChampC"], sub, CHAMPS)[0] == "FAIL"
    assert g.layout(["ChampB"], ["ChampA"], sub, CHAMPS)[0] == "FAIL"


def test_unresolved_champion_is_no_result_not_fail():
    lc = _lc(DUO_LC)
    lc["data"]["allPlayers"][1].update(championName="Nobody", rawChampionName="Nobody")
    rep = _rep(_cs(DUO_GROUPS), lc)
    assert rep["checks"]["roster"]["status"] == "NO_RESULT"
    assert "unresolved" in rep["checks"]["roster"]["why"]


def test_mirror_champion_on_an_enemy_subteam_is_not_a_leak():
    groups = [["ChampA", "ChampB"], ["ChampA", "ChampC"]]
    lc = _lc([("ChampA", "T1"), ("ChampB", "T1"), ("ChampA", "T2"), ("ChampC", "T2")])
    rep = _rep(_cs(groups), lc, [_row(fb=_fb(kill=("ChampA", "ChampC")))])
    assert rep["checks"]["subteams"]["partners"] == ["ChampB"]
    assert rep["checks"]["roster"]["status"] == "PASS"
    assert rep["checks"]["shadow"]["status"] == "PASS"


# -- NO_RESULT paths -------------------------------------------------------------

def test_missing_captures_are_incomplete_not_pass():
    rep = _rep(None, None, [_row(fb=_fb())])
    assert rep["checks"]["subteams"]["status"] == "NO_RESULT"
    assert rep["checks"]["roster"]["status"] == "NO_RESULT"
    assert rep["checks"]["shadow"]["status"] == "NO_RESULT"
    assert rep["verdict"] == "INCOMPLETE"


def test_unlocked_cell_is_no_result():
    rep = _rep(_cs([["ChampA", ""], ["ChampC", "ChampD"]]), _lc(DUO_LC[:4]))
    assert rep["checks"]["subteams"]["status"] == "NO_RESULT"
    assert "locked" in rep["checks"]["subteams"]["why"]


def test_captures_from_two_games_are_no_result():
    rep = _rep(_cs([["ChampC", "ChampD"], ["ChampE", "ChampF"]]), _lc(DUO_LC))
    assert rep["checks"]["subteams"]["status"] == "NO_RESULT"
    assert "two games" in rep["checks"]["subteams"]["why"]
    assert rep["verdict"] == "INCOMPLETE"


# -- the shadow check -------------------------------------------------------------

def test_partner_in_kill_order_fails_the_shadow():
    rows = [_row(fb=_fb()), _row(fb=_fb(allies=(), kill=("ChampB", "ChampC")))]
    rep = _rep(_cs(DUO_GROUPS), _lc(DUO_LC), rows)
    sh = rep["checks"]["shadow"]
    assert sh["status"] == "FAIL"
    assert sh["ok_columns"] == 2
    assert "1 ok column" in sh["why"]


def test_only_transient_columns_are_no_result_and_counted():
    rows = [_row(fb=_fb(status="pending", allies=(), kill=())),
            _row(fb=_fb(status="warming", allies=(), kill=())),
            _row(), _row(fb=_fb(), focus_board_relog=True,
                         ts="2026-10-27T12:59:59+00:00")]
    rep = _rep(_cs(DUO_GROUPS), _lc(DUO_LC), rows)
    sh = rep["checks"]["shadow"]
    assert sh["status"] == "NO_RESULT"
    assert sh["rows"] == 3 and sh["columns"] == 2
    assert sh["column_status"] == {"pending": 1, "warming": 1}
    assert sh["relogs"] == 0


def test_shadow_window_and_champion_filter_drop_other_games():
    """A failing column from another champion or after --until is not read
    (verifier s144g011: the cutoff alone admitted another Arena game)."""
    bad = _fb(allies=(), kill=("ChampB",))
    rows = [_row(fb=_fb()), _row(fb=bad, champ="Champ C"),
            _row(ts="2026-10-27T14:00:00+00:00", fb=bad)]
    until = datetime(2026, 10, 27, 13, 30, 0, tzinfo=timezone.utc)
    rep = g.report(_cs(DUO_GROUPS), _lc(DUO_LC), rows, CUT, CHAMPS, until=until)
    assert rep["checks"]["shadow"]["rows"] == 1
    assert rep["checks"]["shadow"]["status"] == "PASS"
    assert rep["until_utc"] == until.isoformat()
    assert _rep(_cs(DUO_GROUPS), _lc(DUO_LC), rows)["checks"]["shadow"]["status"] == "FAIL"


def test_column_naming_a_champion_in_no_subteam_is_no_result():
    rows = [_row(fb=_fb(kill=("ChampG", "ChampC")))]
    sh = _rep(_cs(DUO_GROUPS), _lc(DUO_LC), rows)["checks"]["shadow"]
    assert sh["status"] == "NO_RESULT"
    assert sh["outcomes"] == {"NO_RESULT": 1}
    assert "another game" in sh["why"]


def test_ally_skipped_by_the_board_is_no_result_not_fail():
    rows = [_row(fb=_fb(allies=(), kill=("ChampC", "ChampD")))]
    sh = _rep(_cs(DUO_GROUPS), _lc(DUO_LC), rows)["checks"]["shadow"]
    assert sh["status"] == "NO_RESULT"
    assert "missing from allies" in sh["why"]


def test_no_cutoff_reads_no_shadow_rows():
    rep = _rep(_cs(DUO_GROUPS), _lc(DUO_LC), [_row(fb=_fb())], cutoff=None)
    assert rep["checks"]["shadow"]["status"] == "NO_RESULT"
    assert rep["cutoff_utc"] is None


# -- capture shapes, CLI and read-only --------------------------------------------

def test_bare_shapes_are_accepted():
    teams = arena_teams(_session(DUO_GROUPS))
    assert g.arena_teams_of(teams) == teams
    assert g.arena_teams_of({"champ_select": {"arena_teams": teams}}) == teams
    assert g.arena_teams_of({"arena_teams": teams}) == teams
    data = _lc(DUO_LC)["data"]
    assert g.liveclient_of(data) is data
    assert g.liveclient_of({"liveclient": data}) is data
    assert g.liveclient_of({"error": "no_liveclient_yet"}) == {}


def test_pinned_ddragon_champions_load_with_numeric_keys():
    champs = g.load_champions(ROOT)
    assert champs, "data/daemon_slayer/<current>/champions.json did not load"
    assert g._key_index(champs)[int(champs["Aatrox"]["key"])] == "Aatrox"


def test_main_exit_codes_and_read_only(tmp_path, capsys, monkeypatch):
    shadow = tmp_path / g.SHADOW_REL
    shadow.parent.mkdir(parents=True)
    shadow.write_text(json.dumps(_row(fb=_fb())) + "\n", encoding="utf-8")
    before = hashlib.sha256(shadow.read_bytes()).hexdigest()
    cs = tmp_path / "cs.json"
    lc = tmp_path / "lc.json"
    cs.write_text(json.dumps(_cs(DUO_GROUPS)), encoding="utf-8")
    lc.write_text(json.dumps(_lc(DUO_LC)), encoding="utf-8")
    monkeypatch.setattr(g, "load_champions", lambda root: CHAMPS)
    args = ["--data-root", str(tmp_path), "--since", "2026-10-27T08:00:00-05:00"]
    assert g.main(args + ["--cs", str(cs), "--lc", str(lc)]) == 0
    assert "G5-11 focus-board layout: PASS" in capsys.readouterr().out
    assert g.main(args + ["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["verdict"] == "INCOMPLETE"
    assert hashlib.sha256(shadow.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == [
        "arena_coach_shadow.jsonl", "cs.json", "lc.json"]
