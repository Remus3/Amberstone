"""Tests for tools/gated_g416_counter_chips.py (G4-16 READY, s144 gated c73).

The grader is PREP only: it never ticks G4-16. These tests pin (a) the source
facts the READY block states (chip classes, pane id, thresholds, the client's
ally-items rule that includes my own row), (b) that the in-process expected
hint list equals the full POST /api/build-plan route's counter_hints, and (c)
every verdict. Synthetic names only (RM-906): no real player, game or player id.
ASCII only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dashboard import routes_build_plan
from tests.test_build_plan_contract import _fake_seed_fn
from tools import gated_g416_counter_chips as g

ROOT = Path(__file__).resolve().parent.parent
AM_JS = (ROOT / "web/js/panels/active_match.js").read_text(encoding="utf-8")
SITU = (ROOT / "core/build_planner/situational.py").read_text(encoding="utf-8")

TS = 1_800_000_000.0
SUSTAIN = ["Soraka", "Aatrox", "Zed", "Lux", "Garen"]
PEN = ["Zed", "Talon", "Jhin", "Lux", "Garen"]


def _pl(name, team, champ, items=(), kills=0, deaths=0, level=6):
    return {"riotIdGameName": name, "summonerName": name, "team": team,
            "championName": champ, "level": level,
            "scores": {"kills": kills, "deaths": deaths, "assists": 0},
            "items": [{"itemID": int(i), "slot": n} for n, i in enumerate(items)]}


def _state(enemies, enemy_items=None, my_items=("3047",), ally_items=(),
           phase="InProgress", mode="sr", me="PlayerA", served=True):
    enemy_items = enemy_items or [[] for _ in enemies]
    allies = [_pl("PlayerA", "ORDER", "Malphite", my_items),
              _pl("PlayerB", "ORDER", "Ahri", ally_items),
              _pl("PlayerC", "ORDER", "Jinx"), _pl("PlayerD", "ORDER", "Leona"),
              _pl("PlayerE", "ORDER", "Vi")]
    foes = [_pl(f"Foe{n}", "CHAOS", c, enemy_items[n]) for n, c in enumerate(enemies)]
    lc = {"allPlayers": allies + foes,
          "activePlayer": {"summonerName": me, "riotIdGameName": me},
          "owned_item_ids": list(my_items), "game_time_s": 900.0}
    if served:
        lc["enemy_team"] = list(enemies)
    return {"mode_key": mode, "mode": mode, "lcu": {"phase": phase},
            "coach": {"champion": "Malphite", "level": 11}, "liveclient": lc}


def _dom(hints, ts=TS, **over):
    chips = [{"label": h["label"], "detail": h["detail"], "ok": h["satisfied"],
              "high": h["severity"] == "high", "visible": True} for h in hints]
    dom = {"ts": ts, "present": True, "strip": bool(chips),
           "strip_visible": bool(chips), "chips": chips}
    dom.update(over)
    return dom


def _route_hints(body):
    orig = routes_build_plan._seed_fn_factory
    routes_build_plan._seed_fn_factory = lambda **kw: _fake_seed_fn
    try:
        class H:
            body = b""

            def _send(self, status, body, ctype):
                self.body = body
        h = H()
        routes_build_plan._serve_build_plan(h, body)
        reply = json.loads(h.body.decode("utf-8"))
    finally:
        routes_build_plan._seed_fn_factory = orig
    assert reply["ok"] is True
    return reply["counter_hints"]


def _grade(state, dom=None, ts=TS):
    body = g.client_body(state)["body"]
    hints = g.expected_in_process(body)
    return g.grade(state, _dom(hints) if dom is None else dom, ts,
                   g.expected_in_process), hints


# --- source pins: the READY block's facts ---------------------------------

def test_dom_snippet_names_the_painted_classes():
    for cls in ("counter-strip", "counter-chip-label", "counter-chip-detail",
                "counter-chip--ok", "counter-chip--high"):
        assert cls in g.DOM_SNIPPET
        assert f'"{cls}' in AM_JS or f" {cls}" in AM_JS or f'"{cls}"' in AM_JS
    assert 'getElementById("am-build-body")' in AM_JS
    assert g.PANE_ID == "am-build-body"


def test_thresholds_the_block_states():
    assert re.search(r"^HEAL_THRESHOLD = 2$", SITU, re.M)
    assert re.search(r"^PEN_HINT_CUT = 0\.5\b", SITU, re.M)
    assert re.search(r"^HP_HINT_FLOOR = 300\.0\b", SITU, re.M)
    assert "const _BUILD_PLAN_COOLDOWN_MS = 4000;" in AM_JS


def test_client_ally_items_include_my_own_row():
    # _extractBpAllyItems keeps every row ON my team - me included - so my
    # own Grievous item suppresses the C2 chip (the dedup), never paints --ok.
    m = re.search(r"export function _extractBpAllyItems\(allPlayers, myTeam\) \{(.*?)\n\}",
                  AM_JS, re.S)
    assert m and "pl.team !== myTeam) continue" in m.group(1)


def test_not_live_render_returns_before_the_build_pane():
    body = AM_JS[AM_JS.index("export function renderActiveMatch"):]
    gate = body.index("if (!isLive) {")
    assert body.index("return;", gate) < body.index("_AM.buildBody()", gate)


# --- in-process expected == the route -------------------------------------

@pytest.mark.parametrize("state", [
    _state(SUSTAIN),
    _state(SUSTAIN, ally_items=("3075",)),
    _state(PEN, [["3036"], ["6694"], ["3142"], [], []]),
    _state(["Garen", "Lux", "Jinx", "Ahri", "Annie"], my_items=()),
])
def test_in_process_equals_route(state):
    body = g.client_body(state)["body"]
    assert g.expected_in_process(body) == _route_hints(body)


def test_no_champion_is_no_hints():
    assert g.expected_in_process({"champion": "", "enemies": SUSTAIN}) == []


# --- client body ---------------------------------------------------------

def test_body_resolved_team_posts_five_enemies_and_my_items_as_ally():
    posted = g.client_body(_state(SUSTAIN, my_items=("3033",)))
    assert posted["team"] == "ORDER"
    assert posted["body"]["enemies"] == SUSTAIN
    assert "3033" in posted["body"]["ally_items"]
    assert posted["body"]["items"] == ["3033"]


def test_body_unresolved_team_posts_everyone():
    posted = g.client_body(_state(SUSTAIN, me="Nobody"))
    assert posted["team"] is None
    assert len(posted["body"]["enemies"]) == 10
    assert posted["body"]["ally_items"] == []


def test_owned_falls_back_to_my_row_below_slot_6():
    st = _state(SUSTAIN, my_items=("3047", "1001", "2003", "1036", "1037", "1038", "3340"))
    st["liveclient"]["owned_item_ids"] = [None, ""]
    assert g.client_body(st)["body"]["items"] == ["3047", "1001", "2003", "1036",
                                                  "1037", "1038"]


# --- verdicts ---------------------------------------------------------------

def test_c2_lit_is_render_match():
    res, hints = _grade(_state(SUSTAIN))
    assert "antiheal" in [h["criterion"] for h in hints]
    assert res["verdict"] == "RENDER_MATCH"
    assert "antiheal" in res["owed_cases"]
    assert res["inputs"]["heal_sources"] >= 2
    assert res["operator_eyeball_owed"] is True


def test_c2_ally_grievous_is_the_dedup_case():
    res, hints = _grade(_state(SUSTAIN, ally_items=("3075",)))
    assert [h["criterion"] for h in hints] == ["resist"]
    assert res["verdict"] == "RENDER_MATCH"
    assert res["owed_cases"] == ["antiheal_dedup"]
    assert res["inputs"]["ally_has_antiheal"] is True


def test_my_own_grievous_suppresses_c2_never_ok():
    body = g.client_body(_state(SUSTAIN, my_items=("3047", "3033")))["body"]
    hints = g.expected_in_process(body)
    assert not [h for h in hints if h["criterion"] == "antiheal"]


def test_unresolved_team_reaches_ok_and_is_refused():
    # Verifier c73: with the team unresolved ally_items is empty while items
    # still holds my Grievous item, so C2 computes satisfied (--ok); the grader
    # refuses that state before it grades a chip.
    st = _state(SUSTAIN, my_items=("3047", "3033"), me="Nobody")
    body = g.client_body(st)["body"]
    assert body["ally_items"] == []
    c2 = [h for h in g.expected_in_process(body) if h["criterion"] == "antiheal"]
    assert c2 and c2[0]["satisfied"] is True
    res = g.grade(st, _dom([]), TS, g.expected_in_process)
    assert res["verdict"] == "ROSTER_BAD"


def test_detail_only_difference_is_detail_lag():
    st = _state(SUSTAIN)
    hints = g.expected_in_process(g.client_body(st)["body"])
    dom = _dom(hints)
    for c in dom["chips"]:
        if c["label"] == "ANTIHEAL":
            c["detail"] = "1 enemy heal sources"
    res = g.grade(st, dom, TS, g.expected_in_process)
    assert res["verdict"] == "DETAIL_LAG"
    assert g.EXIT["DETAIL_LAG"] == 3


def test_repaint_signature_ignores_hint_detail():
    sig = AM_JS[AM_JS.index("const sig = JSON.stringify({"):]
    sig = sig[:sig.index("});")]
    assert "h.criterion" in sig and "h.satisfied" in sig and "h.detail" not in sig


def test_retain_guard_returns_before_the_counter_row():
    body = AM_JS[AM_JS.index("export function _renderAmBuildBody"):]
    assert body.index("if (_shouldRetainBuild(") < body.index('_line("COUNTER"')
    # Only a FILLED row strip carries data-rc-zone; the reserve strip is bare.
    assert 'strip.setAttribute("data-rc-zone", "");' in body
    assert "bm-strip[data-rc-zone]" in g.DOM_SNIPPET


def test_empty_build_rows_with_hints_and_no_row_is_retained():
    st = _state(SUSTAIN)
    res = g.grade(st, _dom([], build_items=0), TS, g.expected_in_process)
    assert res["verdict"] == "RETAINED"
    assert g.EXIT.get("RETAINED", 4) == 4
    res = g.grade(st, _dom([], build_items=3), TS, g.expected_in_process)
    assert res["verdict"] == "RENDER_MISMATCH"


def test_empty_coach_object_is_what_the_client_posts():
    st = _state(SUSTAIN)
    st["coach"] = {}
    st["champion"] = "Malphite"
    assert g.client_body(st)["body"]["champion"] == ""


def test_c4_lit_is_render_match():
    res, hints = _grade(_state(PEN, [["3036"], ["6694"], ["3142"], [], []]))
    assert "hp_vs_pen" in [h["criterion"] for h in hints]
    assert res["verdict"] == "RENDER_MATCH"
    assert "hp_vs_pen" in res["owed_cases"]
    assert res["inputs"]["my_has_resist"] is True
    assert len(res["inputs"]["enemy_pen_item_ids"]) == 3


def test_c4_needs_my_resist():
    body = g.client_body(_state(PEN, [["3036"], ["6694"], [], [], []], my_items=()))["body"]
    assert "hp_vs_pen" not in [h["criterion"] for h in g.expected_in_process(body)]


def test_missing_chip_is_render_mismatch():
    st = _state(SUSTAIN)
    hints = g.expected_in_process(g.client_body(st)["body"])
    dom = _dom(hints)
    dom["chips"] = [c for c in dom["chips"] if c["label"] != "ANTIHEAL"]
    res = g.grade(st, dom, TS, g.expected_in_process)
    assert res["verdict"] == "RENDER_MISMATCH"


def test_flipped_ok_state_is_render_mismatch():
    st = _state(SUSTAIN)
    hints = g.expected_in_process(g.client_body(st)["body"])
    dom = _dom(hints)
    dom["chips"][0]["ok"] = not dom["chips"][0]["ok"]
    assert g.grade(st, dom, TS, g.expected_in_process)["verdict"] == "RENDER_MISMATCH"


def test_hidden_chip_is_render_mismatch():
    st = _state(SUSTAIN)
    hints = g.expected_in_process(g.client_body(st)["body"])
    dom = _dom(hints)
    dom["chips"][0]["visible"] = False
    res = g.grade(st, dom, TS, g.expected_in_process)
    assert res["verdict"] == "RENDER_MISMATCH"


def test_no_hint_and_no_row_is_consistent_and_a_row_is_a_mismatch():
    st = _state(SUSTAIN)
    res = g.grade(st, _dom([]), TS, lambda b: [])
    assert res["verdict"] == "NO_HINT_CONSISTENT"
    res = g.grade(st, _dom([], strip=True), TS, lambda b: [])
    assert res["verdict"] == "RENDER_MISMATCH"


def test_no_owed_chip():
    hint = {"criterion": "tenacity", "satisfied": False, "severity": "med",
            "label": "TENACITY", "detail": "enemy CC 6/10", "suggest_class": "tenacity"}
    st = _state(["Garen", "Lux", "Jinx", "Ahri", "Annie"])
    res = g.grade(st, _dom([hint]), TS, lambda b: [hint])
    assert res["verdict"] == "NO_OWED_CHIP"


@pytest.mark.parametrize("over", [
    {"phase": "EndOfGame"}, {"phase": ""}, {"phase": None}, {"mode": "arena"},
    {"mode": "client"}])
def test_no_game(over):
    res, _ = _grade(_state(SUSTAIN, **over))
    assert res["verdict"] == "NO_GAME"


def test_empty_liveclient_is_no_game():
    st = _state(SUSTAIN)
    st["liveclient"] = {}
    assert g.grade(st, _dom([]), TS, g.expected_in_process)["verdict"] == "NO_GAME"


def test_stale_dom():
    st = _state(SUSTAIN)
    res = g.grade(st, _dom([], ts=TS + 6), TS, g.expected_in_process)
    assert res["verdict"] == "STALE_DOM"


@pytest.mark.parametrize("mut, needle", [
    (lambda s: s["liveclient"]["activePlayer"].update(summonerName="Nobody",
                                                      riotIdGameName="Nobody"),
     "team unresolved"),
    (lambda s: s["liveclient"].update(enemy_team=["Zed"]), "enemy_team"),
    (lambda s: s["coach"].update(champion=""), "no coach champion"),
    (lambda s: s["coach"].update(champion="Ahri"), "!= my roster row"),
])
def test_roster_bad(mut, needle):
    st = _state(SUSTAIN)
    mut(st)
    res = g.grade(st, _dom([]), TS, g.expected_in_process)
    assert res["verdict"] == "ROSTER_BAD"
    assert any(needle in p for p in res["problems"])


def test_pane_absent():
    st = _state(SUSTAIN)
    res = g.grade(st, {"ts": TS, "present": False}, TS, g.expected_in_process)
    assert res["verdict"] == "PANE_ABSENT"


def test_output_carries_no_player_name():
    res, _ = _grade(_state(SUSTAIN))
    text = json.dumps(res)
    assert "Player" not in text and "Foe" not in text


# --- CLI ------------------------------------------------------------------

def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_cli_snippet_body_and_grade(tmp_path, capsys):
    st = _state(SUSTAIN)
    hints = g.expected_in_process(g.client_body(st)["body"])
    sp = _write(tmp_path, "s.json", st)
    dp = _write(tmp_path, "d.json", _dom(hints))
    assert g.main(["snippet"]) == 0
    assert g.PANE_ID in capsys.readouterr().out
    assert g.main(["body", "--state", sp]) == 0
    assert json.loads(capsys.readouterr().out)["enemies"] == SUSTAIN
    assert g.main(["grade", "--state", sp, "--dom", dp, "--state-ts", str(TS)]) == 0
    assert json.loads(capsys.readouterr().out)["expected_source"] == "in_process"
    pp = _write(tmp_path, "p.json", {"ok": True, "counter_hints": hints})
    assert g.main(["grade", "--state", sp, "--dom", dp, "--plan", pp,
                   "--state-ts", str(TS)]) == 0
    assert json.loads(capsys.readouterr().out)["expected_source"] == "plan"
    bad = _write(tmp_path, "bad.json", {"ok": False, "counter_hints": []})
    assert g.main(["grade", "--state", sp, "--dom", dp, "--plan", bad,
                   "--state-ts", str(TS)]) == 3
    assert json.loads(capsys.readouterr().out)["verdict"] == "PLAN_ERROR"


def test_cli_refuses_a_non_object(tmp_path, capsys):
    sp = _write(tmp_path, "s.json", [1, 2])
    assert g.main(["grade", "--state", sp, "--dom", sp]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_comp_inputs_keeps_exactly_the_penetration_item_ids(monkeypatch):
    """S144-P-270 pin: comp_inputs' enemy_pen_item_ids is every enemy item classified lethality, percent armor pen
    or percent magic pen, in order, and nothing else (the inline lambda it replaced was behaviour-equal)."""
    from types import SimpleNamespace

    from core.build_planner import situational

    def props(**kw):
        base = dict(is_lethality=False, is_percent_armor_pen=False, is_percent_magic_pen=False,
                    is_armor=False, is_magic_resist=False, hp=0.0)
        return SimpleNamespace(**{**base, **kw})

    table = {"1": props(is_lethality=True), "2": props(), "3": props(is_percent_armor_pen=True),
             "4": props(is_percent_magic_pen=True), "5": props(is_armor=True, hp=300.0)}
    calls: list[str] = []

    def classify(i):
        calls.append(str(i))
        return table[str(i)]

    monkeypatch.setattr(situational, "classify_item", classify)
    out = g.comp_inputs({"enemy_items": [["1", "2"], ["3", "4"], [5]], "items": ["5"]})
    assert out["enemy_pen_item_ids"] == ["1", "3", "4"]
    assert calls[:5] == ["1", "2", "3", "4", "5"], "classify_item runs once per enemy item, in order"
    assert out["my_has_resist"] is True
    assert out["my_item_hp"] == 300.0
