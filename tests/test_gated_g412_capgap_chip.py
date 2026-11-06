"""Tests for tools/gated_g412_capgap_chip.py (G4-12 PREP, s144 lane gated c72).

Every game input is hand-built (RM-906: synthetic player names only, no real game,
match or player id). The tool is a read-only grader; these tests pin its verdicts
and the source facts the doc row cites.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from tools import gated_g412_capgap_chip as g

ROOT = Path(__file__).resolve().parent.parent
T0 = 1_000_000.0
ENEMIES = ["Soraka", "Aatrox", "Vladimir", "Sylas", "Warwick"]
ALLIES = ["Jinx", "Leona", "Ahri", "Garen", "Elise"]


def _lc(me: str = "PlayerOne", enemy_team=None, champion: str = "Jinx") -> dict:
    rows = [{"riotIdGameName": f"Ally{i}" if i else "PlayerOne",
             "summonerName": "", "championName": c, "team": "ORDER"}
            for i, c in enumerate(ALLIES)]
    rows += [{"riotIdGameName": f"Foe{i}", "summonerName": "", "championName": c,
              "team": "CHAOS"} for i, c in enumerate(ENEMIES)]
    return {"activePlayer": {"riotIdGameName": me}, "allPlayers": rows,
            "champion": champion, "game_time_s": 412.0,
            "enemy_team": list(ENEMIES) if enemy_team is None else enemy_team}


def _state(lc=None, mode_key: str = "sr", coach_champ: str = "Jinx") -> dict:
    # The real /api/state has no top-level "mode"; the client reads mode_key.
    return {"mode_key": mode_key, "coach": {"champion": coach_champ},
            "liveclient": _lc() if lc is None else lc}


GAP = {"applies": True, "top_gap": "sustain", "verdict": "Enemy heals  a lot.",
       "gaps": [{"axis": "sustain"}, {"axis": "poke"}]}


def _dom(**kw) -> dict:
    d = {"ts": T0 + 1.0, "present": True, "hidden": False, "display": "block",
         "w": 300.0, "h": 40.0, "offset_parent": True, "axis_attr": "sustain",
         "axis_text": "Anti-heal", "verdict_text": "Enemy heals a lot."}
    d.update(kw)
    return d


def _fn(payload: dict):
    seen = []

    def fn(champ, enemies, mode):
        seen.append((champ, list(enemies), mode))
        return payload
    fn.seen = seen
    return fn


# ---- grade verdicts -------------------------------------------------------------

def test_render_match_owes_the_operator_eyeball_and_posts_the_client_roster():
    fn = _fn(GAP)
    r = g.grade(_state(), _dom(), T0, fn)
    assert r["verdict"] == "RENDER_MATCH" and r["operator_eyeball_owed"] is True
    assert fn.seen == [("Jinx", ENEMIES, "SR")]
    assert r["posted_champion"] == "Jinx" and "mode" not in r
    assert r["axis_label"] == "Anti-heal" and r["gaps"] == ["sustain", "poke"]
    assert r["game_time_s"] == 412.0 and g.EXIT[r["verdict"]] == 0


def test_no_game_when_liveclient_empty_or_mode_not_sr():
    assert g.grade(_state(lc={}), _dom(), T0, _fn(GAP))["verdict"] == "NO_GAME"
    assert g.grade(_state(mode_key="client"), _dom(), T0, _fn(GAP))["verdict"] == "NO_GAME"
    assert g.grade(_state(mode_key="aram"), _dom(), T0, _fn(GAP))["verdict"] == "NO_GAME"


def test_non_inprogress_lcu_phase_is_no_game_even_with_a_feed():
    for phase in ("EndOfGame", "PreEndOfGame", "WaitingForStats", "Lobby"):
        st = dict(_state(), lcu={"phase": phase})
        r = g.grade(st, _dom(), T0, _fn(GAP))
        assert r["verdict"] == "NO_GAME" and r["lcu_phase"] == phase, phase
    st = dict(_state(), lcu={"phase": "InProgress"})
    assert g.grade(st, _dom(), T0, _fn(GAP))["verdict"] == "RENDER_MATCH"


def test_stale_dom_when_captures_too_far_apart_or_untimed():
    assert g.grade(_state(), _dom(ts=T0 + 6.0), T0, _fn(GAP))["verdict"] == "STALE_DOM"
    assert g.grade(_state(), _dom(ts=None), T0, _fn(GAP))["verdict"] == "STALE_DOM"
    assert g.grade(_state(), _dom(ts=T0 - 4.9), T0, _fn(GAP))["verdict"] == "RENDER_MATCH"


def test_unresolved_team_is_roster_bad_because_the_client_posts_all_ten():
    fn = _fn(GAP)
    r = g.grade(_state(lc=_lc(me="Nobody")), _dom(), T0, fn)
    assert r["verdict"] == "ROSTER_BAD" and fn.seen == []
    assert len(r["enemies"]) == 10
    assert any("team unresolved" in p for p in r["problems"])
    assert any("enemy count 10" in p for p in r["problems"])


def test_client_and_server_roster_disagreement_is_roster_bad():
    r = g.grade(_state(lc=_lc(enemy_team=ENEMIES[:4] + ["Jinx"])), _dom(), T0, _fn(GAP))
    assert r["verdict"] == "ROSTER_BAD"
    assert r["problems"] == ["client roster != server enemy_team"]
    r = g.grade(_state(lc=_lc(champion="Ahri")), _dom(), T0, _fn(GAP))
    assert r["problems"] == ["client and server disagree on my champion"]


def test_posted_coach_champion_missing_or_wrong_is_roster_bad():
    r = g.grade(_state(coach_champ=""), _dom(), T0, _fn(GAP))
    assert r["verdict"] == "ROSTER_BAD"
    assert r["problems"] == ["no coach champion: the client never fetches the chip"]
    r = g.grade(_state(coach_champ="Ahri"), _dom(), T0, _fn(GAP))
    assert r["problems"] == ["posted coach champion != my roster row champion"]


def test_posted_champion_name_forms_compare_equal_and_are_what_is_posted():
    lc = _lc(champion="Kai'Sa")
    lc["allPlayers"][0]["championName"] = "Kai'Sa"
    lc["enemy_team"] = list(ENEMIES)
    fn = _fn(GAP)
    r = g.grade(_state(lc=lc, coach_champ="Kaisa"), _dom(), T0, fn)
    assert r["verdict"] == "RENDER_MATCH" and fn.seen[0][0] == "Kaisa"


def test_coachless_state_falls_back_to_top_level_champion_like_main_js():
    st = _state()
    del st["coach"]
    st["champion"] = "Jinx"
    assert g.posted_champion(st) == "Jinx"
    assert g.grade(st, _dom(), T0, _fn(GAP))["verdict"] == "RENDER_MATCH"


def test_summoner_name_precedence_matches_resolve_my_team():
    # activePlayer: summonerName wins over riotIdGameName; a row: riotIdGameName
    # wins over summonerName (active_match.js _resolveMyTeam).
    lc = _lc()
    lc["activePlayer"] = {"summonerName": "Foe0", "riotIdGameName": "PlayerOne"}
    assert g.client_roster(lc)["team"] == "CHAOS"
    lc = _lc()
    lc["allPlayers"][0].update(riotIdGameName="Other", summonerName="PlayerOne")
    assert g.client_roster(lc)["team"] is None
    lc["allPlayers"][0].update(riotIdGameName="", summonerName="PlayerOne")
    assert g.client_roster(lc)["team"] == "ORDER"


def test_raw_champion_name_fallback_for_enemies():
    lc = _lc()
    lc["allPlayers"][5].update(championName="", rawChampionName="Soraka")
    assert g.client_roster(lc)["enemies"] == ENEMIES


def test_empty_top_gap_expects_the_none_axis_attribute():
    gap = dict(GAP, top_gap="")
    r = g.grade(_state(), _dom(axis_attr="none", axis_text="Gap"), T0, _fn(gap))
    assert r["verdict"] == "RENDER_MATCH"
    r = g.grade(_state(), _dom(axis_attr="", axis_text="Gap"), T0, _fn(gap))
    assert r["problems"] == ["data-capgap-axis differs"]


def test_riot_id_tagline_still_resolves_my_team():
    r = g.grade(_state(lc=_lc(me="PlayerOne#TAG1")), _dom(), T0, _fn(GAP))
    assert r["verdict"] == "RENDER_MATCH" and r["my_champion"] == "Jinx"


def test_chip_absent_when_mount_missing():
    r = g.grade(_state(), {"ts": T0, "present": False}, T0, _fn(GAP))
    assert r["verdict"] == "CHIP_ABSENT" and g.EXIT["CHIP_ABSENT"] == 3


def test_no_gap_hidden_is_consistent_but_not_a_pass():
    r = g.grade(_state(), _dom(hidden=True), T0, _fn({"applies": False}))
    assert r["verdict"] == "NO_GAP_CONSISTENT" and g.EXIT.get(r["verdict"], 4) == 4


def test_visible_chip_with_no_gap_expected_is_a_mismatch():
    r = g.grade(_state(), _dom(), T0, _fn({"applies": False}))
    assert r["verdict"] == "RENDER_MISMATCH"


def test_each_render_difference_is_named():
    cases = {
        "gap expected but chip not visible": _dom(offset_parent=False),
        "axis label differs": _dom(axis_text="Anti-poke"),
        "data-capgap-axis differs": _dom(axis_attr="poke"),
        "verdict text differs": _dom(verdict_text="Something else."),
    }
    for problem, dom in cases.items():
        r = g.grade(_state(), dom, T0, _fn(GAP))
        assert r["verdict"] == "RENDER_MISMATCH" and r["problems"] == [problem], problem
    for kw in ({"hidden": True}, {"display": "none"}, {"w": 0}, {"h": 0}):
        assert not g.dom_visible(_dom(**kw))


def test_unknown_axis_uses_the_client_fallback_label():
    assert g.axis_label("wave_clear") == "wave clear"
    assert g.axis_label("") == "Gap"


# ---- expected payload sources ---------------------------------------------------

def test_expected_from_preview_reads_capability_gap_or_no_gap():
    assert g.expected_from_preview({"capability_gap": GAP}) is GAP
    assert g.expected_from_preview({"capability_gap": None}) == {"applies": False}
    assert g.expected_from_preview({}) == {"applies": False}


def test_expected_in_process_blank_champion_is_no_gap():
    assert g.expected_in_process("", ENEMIES, "kiwi") == {"applies": False}


ARTILLERY = ["Xerath", "Ziggs", "Vel'Koz", "Lux", "Jayce"]
TANKS = ["Malphite", "Ornn", "Sion", "Cho'Gath", "Zac"]


def test_expected_in_process_canonicalises_like_the_route():
    # The route canonicalises before build_capability_gap; display and
    # canonical forms must grade alike (the verifier measured 11 of 60 raw
    # display-name cases differing before this step existed).
    from core.archetype_picks import canonical_champion_id
    from core.ds_capability_gap import build_capability_gap
    for disp in ("Kog'Maw", "Kai'Sa", "Rek'Sai", "Jarvan IV", "K'Sante"):
        canon = canonical_champion_id(disp)
        assert canon and canon != disp, disp
        for comp in (ARTILLERY, TANKS):
            got = g.expected_in_process(disp, comp, "SR")
            assert got == g.expected_in_process(canon, comp, "SR"), disp
            want = build_capability_gap(canon, comp, "SR")
            assert got == (want if want.get("applies") else {"applies": False}), disp


# ---- CLI -------------------------------------------------------------------------

def test_cli_grade_with_preview_file(tmp_path, capsys):
    st = tmp_path / "state.json"
    st.write_text(json.dumps(_state()), encoding="utf-8")
    dm = tmp_path / "dom.json"
    dm.write_text(json.dumps(_dom()), encoding="utf-8")
    pv = tmp_path / "preview.json"
    pv.write_text(json.dumps({"ok": True, "capability_gap": GAP}), encoding="utf-8")
    rc = g.main(["grade", "--state", str(st), "--dom", str(dm), "--preview", str(pv),
                 "--state-ts", str(T0)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["verdict"] == "RENDER_MATCH"
    assert out["expected_source"] == "preview"
    assert "PlayerOne" not in json.dumps(out)


def test_cli_refuses_a_non_object_file(tmp_path, capsys):
    bad = tmp_path / "state.json"
    bad.write_text("[]", encoding="utf-8")
    assert g.main(["grade", "--state", str(bad), "--dom", str(bad)]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_snippet_reads_the_mount_and_both_text_nodes(capsys):
    assert g.main(["snippet"]) == 0
    js = capsys.readouterr().out
    for needle in (g.MOUNT_ID, ".capability-gap-axis", ".capability-gap-verdict",
                   "offsetParent", "capgapAxis", "Date.now() / 1000"):
        assert needle in js


# ---- source facts the doc row cites ---------------------------------------------

def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_axis_labels_mirror_active_match_js():
    js = _read("web/js/panels/active_match.js")
    block = re.search(r"_AM_CAPGAP_AXIS_LABEL = \{(.*?)\};", js, re.S).group(1)
    pairs = dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", block))
    assert pairs == g.AXIS_LABEL


def test_render_markup_and_client_team_skip_match_the_grader():
    js = _read("web/js/panels/active_match.js")
    assert 'class="capability-gap-axis"' in js and 'class="capability-gap-verdict"' in js
    assert "block.dataset.capgapAxis = axis" in js
    # A null team never skips a row: the fact ROSTER_BAD "team unresolved" rests on.
    assert "if (myTeam && pl.team === myTeam) continue;" in js
    assert "champion: myChamp, enemies: enemyNames, mode, level: 6, items: []" in js
    assert f'id="{g.MOUNT_ID}"' in _read("web/index.html")
    assert 'block.dataset.capgapAxis = axis || "none";' in js
    # What is posted: coach.champion, and the mode_key tag as state.mode.
    main = _read("web/js/main.js")
    assert "const coachPayload = st.coach || st;" in main
    assert "const fileMode = st.mode_key" in main


def test_route_flag_default_on_and_mode_aliases_mirror_routes_state():
    py = _read("dashboard/routes_state.py")
    assert 'os.environ.get("RC_CAPGAP_SURFACE", "1")' in py
    canon = py.index("champion = canonical_champion_id(champion) or champion")
    assert canon < py.index("cg = build_capability_gap(champion, cg_enemies, mode)")
    block = re.search(r"_DS_PREVIEW_MODE_ALIASES = \{(.*?)\}", py, re.S).group(1)
    assert dict(re.findall(r"\"(\w+)\":\s*\"(\w+)\"", block)) == g.MODE_ALIASES
