"""Tests for tools/gated_g417_onhit_render.py (G4-17 READY, s144 gated c74).

The grader is PREP only: it never ticks G4-17. These tests pin (a) the source
facts the READY block states (which route feeds which build row, the 7 cap, the
MUTE drop, the scorer resolution, item 3115 = Nashor's Tooth, the onhit roster),
(b) the client-body and Daemon Slayer row derivations, and (c) every verdict.
Synthetic names only (RM-906): no real player, game or player id. ASCII only.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import gated_g417_onhit_render as g

ROOT = Path(__file__).resolve().parent.parent
AM_JS = (ROOT / "web/js/panels/active_match.js").read_text(encoding="utf-8")
ROUTES = (ROOT / "dashboard/routes_state.py").read_text(encoding="utf-8")
PICKS = (ROOT / "core/archetype_picks.py").read_text(encoding="utf-8")

TS = 1_800_000_000.0
ROSTER = {"Gwen": 1.0, "Kayle": 0.3, "KogMaw": 0.6}
FOES = ["Garen", "Ahri", "Jinx", "Leona", "Vi"]


def _pl(name, team, champ, items=()):
    return {"riotIdGameName": name, "summonerName": name, "team": team,
            "championName": champ,
            "items": [{"itemID": int(i), "slot": n} for n, i in enumerate(items)]}


def _state(champ="Gwen", owned=("1056",), phase="InProgress", mode="sr",
           coach_champ=None, level=7):
    allies = [_pl("PlayerA", "ORDER", champ, owned)] + [
        _pl(f"Ally{n}", "ORDER", c) for n, c in enumerate(["Malphite", "Lux", "Ezreal", "Nami"])]
    foes = [_pl(f"Foe{n}", "CHAOS", c) for n, c in enumerate(FOES)]
    lc = {"allPlayers": allies + foes,
          "activePlayer": {"summonerName": "PlayerA", "riotIdGameName": "PlayerA"},
          "owned_item_ids": list(owned), "game_time_s": 600.0}
    return {"mode_key": mode, "mode": mode, "lcu": {"phase": phase},
            "coach": {"champion": champ if coach_champ is None else coach_champ,
                      "level": level},
            "liveclient": lc}


LIVE = ["3153", "3124", "4645", "3089", "3115", "3091", "6653", "3135"]


def _preview(ids=LIVE, scorer="onhit", **over):
    rows = [{"item_id": i, "item_name": f"Item{i}", "delta_dps": 10.0,
             "scorer": scorer, "unique_passive_key": "", "family": ""} for i in ids]
    body = {"ok": True, "ranked": rows, "scorer": scorer, "archetype": "onhit"}
    body.update(over)
    return body


def _order(ids, scorer="onhit"):
    return {"ok": True, "scorer": scorer,
            "order": [{"item_id": i, "item_name": f"Item{i}", "locked_family": ""}
                      for i in ids]}


def _item(i, **over):
    it = {"id": i, "name": "Nashor's Tooth" if i == "3115" else f"Item{i}",
          "owned": False, "visible": True, "clipped": False}
    it.update(over)
    return it


def _dom(live=LIVE[:7], meta=(), ult=(), ts=TS, **over):
    rows = [{"variant": v, "label": lab, "visible": True,
             "items": [_item(i) for i in ids]}
            for v, lab, ids in (("bm-live", "Daemon Slayer", live),
                                ("bm-meta", "Meta Build", meta),
                                ("bm-ult", "Ultimate Build", ult))]
    dom = {"ts": ts, "present": True, "rows": rows}
    dom.update(over)
    return dom


def _grade(state=None, dom=None, preview=None, order=None, ult=None, ts=TS):
    return g.grade(state or _state(), dom or _dom(), ts,
                   preview if preview is not None else _preview(), order, ult,
                   roster=ROSTER)


# --- (a) source facts --------------------------------------------------------

def test_daemon_slayer_row_is_fed_by_ds_preview_not_build_plan():
    assert 'fetch("/api/ds-preview", {' in AM_JS
    assert "const picks = (livePicks && livePicks.length) ? livePicks : coachPicks;" in AM_JS
    assert '{ label: "Daemon Slayer", items: cap(live) },' in AM_JS
    assert "live: dedupedPicks," in AM_JS
    assert 'fetch("/api/build-order", {' in AM_JS
    # /api/build-plan only feeds the badges + counter chips.
    assert 'const planState = isLive ? (planStates[String(id)] || "") : "";' in AM_JS


def test_row_classes_cap_and_mute_drop_are_as_stated():
    for frag in ('"Daemon Slayer":  "bm-live",', '"Meta Build":     "bm-meta",',
                 '"Ultimate Build": "bm-ult",', "const _BM_SLOT_CAP = 7;",
                 "filterSilenced(applyItemOverrides(rowDef.items))",
                 "img.src = `/data/ddragon/${ver}/img/item/${id}.png`;",
                 'row.className = `bm-row ${variant}`;', 's.className = "bm-strip";',
                 'if (opts.bm && owned) wrap.classList.add("bm-owned");'):
        assert frag in AM_JS, frag
    assert g.SLOT_CAP == 7 and g.ROWS == ("bm-live", "bm-meta", "bm-ult")


def test_ultimate_request_is_level_18_no_items_and_requests_echo_incumbent():
    ult = AM_JS[AM_JS.index("function _maybeRefreshUltimateOrder"):]
    ult = ult[:ult.index("\n}\n")]
    assert "level:     18," in ult and "items:     []," in ult
    assert "_ultBody.incumbent = _ultInc;" in ult
    assert "_boBody.incumbent = _inc;" in AM_JS


def test_routes_resolve_scorer_from_archetype_and_preview_tops_8():
    assert ROUTES.count('archetype = (get_archetype_for(champion).get("primary") or "carry").lower()') >= 2
    assert '"top": 8' in ROUTES
    assert '"reason": "build_complete",' in ROUTES
    # an operator pick wins over the default
    body = PICKS[PICKS.index("def get_archetype_for"):]
    assert body.index("picks = _load_picks()") < body.index("default_for_champion(champion)")


def test_default_scorer_is_onhit_for_the_roster():
    from core.archetype_picks import default_for_champion
    for champ in ("Gwen", "Kayle", "KogMaw"):
        assert default_for_champion(champ)[0] == "onhit", champ


def test_3115_is_nashors_tooth_and_roster_holds_the_three():
    haste = (ROOT / "agents/daemon_slayer/_item_ability_haste.py").read_text(encoding="utf-8")
    assert '"3115":  15.0,  # Nashor\'s Tooth' in haste
    assert g.NASHOR_ID == "3115"
    assert {"Gwen", "Kayle", "KogMaw"} <= set(g.onhit_roster())
    assert g.canonical("Kog'Maw") == "KogMaw"


def test_snippet_is_valid_js_and_reads_the_rows():
    s = g.DOM_SNIPPET
    for frag in ("getElementById('am-build-body')", ".bm-module > .bm-row",
                 "bm-shaper", ".bm-strip", "bm-owned", "/\\/item\\/(\\d+)\\.png/"):
        assert frag in s, frag
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    res = subprocess.run([node, "-e", "new Function('return ' + process.argv[1]);",
                          s], capture_output=True, text=True, timeout=60,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert res.returncode == 0, res.stderr


# --- (b) derivations -------------------------------------------------------

def test_client_bodies_mirror_the_three_fetchers():
    b = g.client_bodies(_state(owned=("1056", "3006")))
    assert b["ds_preview"] == {"champion": "Gwen", "mode": "SR", "level": 7,
                               "items": ["1056", "3006"]}
    assert b["build_order"]["archetype"] == "" and b["build_order"]["level"] == 7
    assert b["ultimate"] == {"champion": "Gwen", "mode": "SR", "level": 18,
                             "items": [], "archetype": ""}
    st = _state()
    st["liveclient"]["owned_item_ids"] = []
    assert g.client_bodies(st)["ds_preview"]["items"] == ["1056"]
    st["mode"] = ""
    st["mode_key"] = ""
    assert g.client_bodies(st)["ds_preview"]["mode"] == "SR"


def test_expected_live_family_dedupes_then_caps_7():
    p = _preview(LIVE)
    p["ranked"][1]["family"] = "fam"
    p["ranked"][2]["family"] = "fam"
    assert g.expected_live(p, None, None) == [LIVE[0], LIVE[1]] + LIVE[3:8]
    assert g.expected_live(_preview(LIVE), None, None) == LIVE[:7]
    # a Meta-row locked_family feeds the dedupe map too
    order = {"order": [{"item_id": LIVE[0], "locked_family": "x"},
                       {"item_id": LIVE[4], "locked_family": "x"}]}
    assert LIVE[4] not in g.expected_live(_preview(LIVE), order, None)


# --- (c) verdicts ------------------------------------------------------------

def test_render_match_is_not_a_tick():
    r = _grade()
    assert r["verdict"] == "RENDER_MATCH" and r["operator_eyeball_owed"] is True
    assert r["rows_with_nashor"] == ["bm-live"] and r["coherence"] == 1.0
    assert g.EXIT["RENDER_MATCH"] == 0


@pytest.mark.parametrize("kw,verdict", [
    ({"state": _state(phase="ChampSelect")}, "NO_GAME"),
    ({"state": _state(mode="arena")}, "NO_GAME"),
    ({"ts": TS + 6}, "STALE_DOM"),
    ({"state": _state(coach_champ="")}, "ROSTER_BAD"),
    ({"state": _state(coach_champ="Kayle")}, "ROSTER_BAD"),
    ({"state": _state(champ="Syndra")}, "NOT_ONHIT_CHAMP"),
    ({"dom": {"ts": TS, "present": False}}, "PANE_ABSENT"),
    ({"preview": {"ok": False}}, "PLAN_ERROR"),
    ({"preview": _preview([], scorer="dps", reason="build_complete")}, "FULL_BUILD"),
    ({"preview": _preview(scorer="mage")}, "SCORER_DRIFT"),
    ({"order": _order(LIVE, scorer="dps")}, "SCORER_DRIFT"),
    ({"dom": _dom(live=())}, "EMPTY_ROWS"),
])
def test_refusals(kw, verdict):
    assert _grade(**kw)["verdict"] == verdict


def test_kogmaw_display_name_is_accepted():
    st = _state(champ="Kog'Maw")
    assert _grade(state=st)["verdict"] == "RENDER_MATCH"


def test_live_row_omits_nashor_the_preview_ranks_is_a_mismatch():
    dom = _dom(live=[i for i in LIVE[:7] if i != "3115"], meta=["3115"])
    r = _grade(dom=dom)
    assert r["verdict"] == "RENDER_MISMATCH"
    assert "Daemon Slayer row" in r["problems"][0]


def test_live_row_paints_nashor_beyond_the_preview_is_a_mismatch():
    pre = _preview([i for i in LIVE if i != "3115"])
    r = _grade(preview=pre, dom=_dom(live=["3153", "3115"]))
    assert r["verdict"] == "RENDER_MISMATCH"


def test_hidden_or_clipped_nashor_is_a_mismatch():
    for flag in ({"visible": False}, {"clipped": True}):
        dom = _dom()
        for it in dom["rows"][0]["items"]:
            if it["id"] == "3115":
                it.update(flag)
        assert _grade(dom=dom)["verdict"] == "RENDER_MISMATCH", flag


def test_fallback_tile_matches_by_name():
    dom = _dom()
    for it in dom["rows"][0]["items"]:
        if it["id"] == "3115":
            it["id"] = ""
    assert _grade(dom=dom)["verdict"] == "RENDER_MATCH"


def test_meta_and_ultimate_disagreement_is_advisory_only():
    r = _grade(order=_order(["3115", "3153"]), ult=_order(["3153"]),
               dom=_dom(meta=["3153"], ult=["3153", "3115"]))
    assert r["verdict"] == "RENDER_MATCH"
    assert len(r["advisory"]) == 2


def test_no_nashor_anywhere():
    pre = _preview([i for i in LIVE if i != "3115"])
    dom = _dom(live=[i for i in LIVE[:7] if i != "3115"])
    assert _grade(preview=pre, dom=dom)["verdict"] == "PLAN_NO_NASHOR"
    assert _grade(preview=pre, dom=dom, ult=_order(["3115"]))["verdict"] == "NASHOR_DARK"
    st = _state(owned=("1056", "3115"))
    assert _grade(state=st, preview=pre, dom=dom)["verdict"] == "NASHOR_OWNED"


def test_cli_grade_and_bodies(tmp_path, capsys):
    st, dm, pv = tmp_path / "s.json", tmp_path / "d.json", tmp_path / "p.json"
    st.write_text(json.dumps(_state()), encoding="utf-8")
    dm.write_text(json.dumps(_dom()), encoding="utf-8")
    pv.write_text(json.dumps(_preview()), encoding="utf-8")
    rc = g.main(["grade", "--state", str(st), "--dom", str(dm), "--preview", str(pv),
                 "--state-ts", str(TS)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["verdict"] == "RENDER_MATCH"
    assert g.main(["bodies", "--state", str(st)]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {"ds_preview", "build_order", "ultimate"}
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert g.main(["grade", "--state", str(bad), "--dom", str(dm),
                   "--preview", str(pv)]) == 2


def test_tool_prints_no_player_name():
    r = _grade()
    assert "PlayerA" not in json.dumps(r) and "Foe0" not in json.dumps(r)


def test_module_runs_as_script():
    res = subprocess.run([sys.executable, str(ROOT / "tools/gated_g417_onhit_render.py"),
                          "snippet"], capture_output=True, text=True, timeout=60,
                         cwd=str(ROOT),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert res.returncode == 0 and "am-build-body" in res.stdout
