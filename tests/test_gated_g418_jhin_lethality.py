"""Tests for tools/gated_g418_jhin_lethality.py (G4-18 READY, s144 gated c75).

The grader is PREP only: it never ticks G4-18. These tests pin (a) the source
facts the READY block states (Jhin's fight_length, the carry branch serving
scorer dps, the default primary, the engine lethality field, the named core,
the Swiftness override, the shared G4-17 row reader), and (b) every verdict.
Synthetic names only (RM-906): no real player, game or player id. ASCII only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import gated_g417_onhit_render as g417
from tools import gated_g418_jhin_lethality as g

ROOT = Path(__file__).resolve().parent.parent
CLIENT = (ROOT / "core/daemon_slayer_client.py").read_text(encoding="utf-8")
FL_SRC = (ROOT / "core/ds_champion_fight_length.py").read_text(encoding="utf-8")
BO_SRC = (ROOT / "core/build_order.py").read_text(encoding="utf-8")

TS = 1_800_000_000.0
FOES = ["Garen", "Ahri", "Jinx", "Leona", "Vi"]
# Synthetic lethality catalog for the verdict tests (ids as the engine keys them).
LETH = {"6697": "Hubris", "6676": "The Collector", "3142": "Youmuu's Ghostblade",
        "6696": "Axiom Arc", "226676": "The Collector"}
# preview: IE, Hubris, Collector, BT, Youmuu's, LDR, Axiom Arc, Runaan's
LIVE = ["3031", "6697", "6676", "3072", "3142", "3036", "6696", "3085"]
LIVE_LETH = ["6697", "6676", "3142", "6696"]


def _pl(name, team, champ, items=()):
    return {"riotIdGameName": name, "summonerName": name, "team": team,
            "championName": champ,
            "items": [{"itemID": int(i), "slot": n} for n, i in enumerate(items)]}


def _state(champ="Jhin", owned=("1055",), phase="InProgress", mode="sr",
           coach_champ=None, level=9):
    allies = [_pl("PlayerA", "ORDER", champ, owned)] + [
        _pl(f"Ally{n}", "ORDER", c) for n, c in enumerate(["Malphite", "Lux", "Ezreal", "Nami"])]
    foes = [_pl(f"Foe{n}", "CHAOS", c) for n, c in enumerate(FOES)]
    lc = {"allPlayers": allies + foes,
          "activePlayer": {"summonerName": "PlayerA", "riotIdGameName": "PlayerA"},
          "owned_item_ids": list(owned), "game_time_s": 900.0}
    return {"mode_key": mode, "mode": mode, "lcu": {"phase": phase},
            "coach": {"champion": champ if coach_champ is None else coach_champ,
                      "level": level},
            "liveclient": lc}


def _preview(ids=LIVE, scorer="dps", **over):
    rows = [{"item_id": i, "item_name": f"Item{i}", "delta_dps": 10.0,
             "scorer": scorer, "unique_passive_key": "", "family": ""} for i in ids]
    body = {"ok": True, "ranked": rows, "scorer": scorer, "archetype": "carry"}
    body.update(over)
    return body


def _order(ids, scorer="dps"):
    return {"ok": True, "scorer": scorer,
            "order": [{"item_id": i, "item_name": f"Item{i}", "locked_family": ""}
                      for i in ids]}


def _item(i, **over):
    it = {"id": i, "name": LETH.get(i, f"Item{i}"), "owned": False,
          "visible": True, "clipped": False}
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


def _grade(state=None, dom=None, preview=None, order=None, ult=None, ts=TS,
           fl=0.5):
    return g.grade(state or _state(), dom or _dom(), ts,
                   preview if preview is not None else _preview(), order, ult,
                   leth=LETH, fl=fl)


# --- (a) source facts --------------------------------------------------------

def test_jhin_fight_length_is_mapped_and_resolved_by_the_tool():
    assert '"jhin": 0.5,' in FL_SRC
    assert g.fight_length("Jhin") == 0.5


def test_carry_branch_applies_fight_length_and_serves_scorer_dps():
    assert "_carry_fight_length = champion_fight_length(champion)" in CLIENT
    tail = CLIENT[CLIENT.index("_carry_fight_length = champion_fight_length(champion)"):]
    assert '"scorer":    "dps",' in tail
    assert g.SCORER == "dps"


def test_jhin_default_primary_is_carry():
    from core.archetype_picks import default_for_champion
    assert default_for_champion("Jhin")[0] == "carry"


def test_engine_lethality_field_classifies_the_core():
    leth = g.lethality_ids()
    for iid in ("6697", "6676", "3142", "6696"):
        assert iid in leth, iid
    # IE, Serylda's and Runaan's carry no lethality: context only, never graded.
    for iid in ("3031", "6694", "3085"):
        assert iid not in leth, iid


def test_named_core_matches_the_shipped_claim():
    for name in ("Hubris", "The Collector", "Youmuu's", "Serylda's", "IE the retained"):
        assert name in FL_SRC, name
    assert set(g.NAMED_CORE) == {"3031", "6694", "6676", "6697", "6696", "3142"}


def test_swiftness_override_still_set_for_jhin():
    assert '"Jhin": "3009",' in BO_SRC
    assert g.SWIFTNESS_ID == "3009"


def test_row_reader_is_the_g417_one():
    assert g.DOM_SNIPPET is g417.DOM_SNIPPET
    assert g.expected_live is g417.expected_live
    assert g.client_bodies is g417.client_bodies
    assert g.ROWS == ("bm-live", "bm-meta", "bm-ult") and g.SLOT_CAP == 7


# --- (b) verdicts --------------------------------------------------------------

def test_render_match_is_not_a_tick():
    r = _grade(order=_order(["3009", "6697", "6676"]), ult=_order(["6697", "3009"]),
               dom=_dom(meta=["3009", "6697", "6676"], ult=["6697", "3009"]))
    assert r["verdict"] == "RENDER_MATCH" and r["operator_eyeball_owed"] is True
    assert r["lethality_expected"]["bm-live"] == ["6697", "6676", "3142", "6696"]
    assert set(r["rows_with_lethality"]) == {"bm-live", "bm-meta", "bm-ult"}
    assert r["swiftness_rows"] == ["bm-meta", "bm-ult"]
    assert "Hubris" in r["named_core_painted"] and "Infinity Edge" in r["named_core_painted"]
    assert r["advisory"] == [] and r["fight_length"] == 0.5


@pytest.mark.parametrize("kw,verdict", [
    ({"state": _state(phase="ChampSelect")}, "NO_GAME"),
    ({"state": _state(mode="arena")}, "NO_GAME"),
    ({"ts": TS + 6}, "STALE_DOM"),
    ({"state": _state(champ="Jinx")}, "NOT_JHIN"),
    ({"state": _state(coach_champ="")}, "ROSTER_BAD"),
    ({"state": _state(coach_champ="Caitlyn")}, "ROSTER_BAD"),
    ({"fl": None}, "UNMAPPED"),
    ({"dom": {"ts": TS, "present": False}}, "PANE_ABSENT"),
    ({"preview": {"ok": False}}, "PLAN_ERROR"),
    ({"preview": _preview(reason="build_complete", ranked=[])}, "FULL_BUILD"),
    ({"preview": _preview(scorer="ability")}, "SCORER_DRIFT"),
    ({"order": _order(["6697"], scorer="burst")}, "SCORER_DRIFT"),
    ({"dom": _dom(live=[], meta=[], ult=[])}, "EMPTY_ROWS"),
])
def test_refusals(kw, verdict):
    assert _grade(**kw)["verdict"] == verdict


def test_aram_is_a_live_mode():
    assert _grade(state=_state(mode="aram"))["verdict"] == "RENDER_MATCH"


def test_live_row_missing_a_ranked_lethality_item_is_a_mismatch():
    r = _grade(dom=_dom(live=["3031", "6697", "6676", "3072", "3036", "6696"]))
    assert r["verdict"] == "RENDER_MISMATCH"
    assert "3142" in r["problems"][0]


def test_live_row_painting_lethality_beyond_the_preview_is_a_mismatch():
    # Edge of Night (3814) painted in the Daemon Slayer row, preview never ranks it.
    r = g.grade(_state(), _dom(live=LIVE[:6] + ["3814"]), TS, _preview(),
                leth=dict(LETH, **{"3814": "Edge of Night"}), fl=0.5)
    assert r["verdict"] == "RENDER_MISMATCH"


def test_owned_lethality_tile_in_live_row_is_not_a_mismatch():
    dom = _dom()
    dom["rows"][0]["items"].insert(0, _item("6676", owned=True))
    assert _grade(dom=dom)["verdict"] == "RENDER_MATCH"


def test_hidden_or_clipped_lethality_is_a_mismatch():
    for over in ({"visible": False}, {"clipped": True}):
        dom = _dom()
        dom["rows"][0]["items"][1] = _item("6697", **over)
        r = _grade(dom=dom)
        assert r["verdict"] == "RENDER_MISMATCH", over
        assert "6697" in r["problems"][0]


def test_fallback_tile_resolves_by_name_to_the_sr_id():
    dom = _dom()
    dom["rows"][0]["items"][2] = _item("", name="The Collector")
    r = _grade(dom=dom)
    assert r["verdict"] == "RENDER_MATCH"
    assert "6676" in r["lethality_painted"]["bm-live"]


def test_meta_and_ultimate_disagreement_is_advisory_only():
    r = _grade(order=_order(["6697", "6676"]), dom=_dom(meta=["6697"]))
    assert r["verdict"] == "RENDER_MATCH"
    assert any(a.startswith("bm-meta:") for a in r["advisory"])


def test_runaans_above_the_core_is_advisory():
    r = _grade(preview=_preview(["3085"] + LIVE[:7]), dom=_dom(live=["3085"] + LIVE[:6]))
    assert r["verdict"] == "RENDER_MATCH"
    assert any("Runaan's" in a for a in r["advisory"])


def test_no_lethality_anywhere_is_a_plan_question():
    ids = ["3031", "3072", "3036", "3085", "3046", "3094", "3033"]
    r = _grade(preview=_preview(ids), dom=_dom(live=ids))
    assert r["verdict"] == "PLAN_NO_LETHALITY"


def test_ranked_but_unpainted_is_dark():
    ids = ["3031", "3072", "3036", "3085", "3046", "3094", "3033"]
    r = _grade(dom=_dom(live=ids))
    assert r["verdict"] == "LETHALITY_DARK"


def test_cli_grade_and_bodies(tmp_path, capsys):
    files = {"state": _state(), "dom": _dom(), "preview": _preview()}
    for k, v in files.items():
        (tmp_path / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")
    rc = g.main(["bodies", "--state", str(tmp_path / "state.json")])
    body = json.loads(capsys.readouterr().out)
    assert rc == 0 and body["ds_preview"]["champion"] == "Jhin"
    assert body["ultimate"] == {"champion": "Jhin", "mode": "SR", "level": 18,
                                "items": [], "archetype": ""}
    rc = g.main(["grade", "--state", str(tmp_path / "state.json"), "--dom",
                 str(tmp_path / "dom.json"), "--preview", str(tmp_path / "preview.json"),
                 "--state-ts", str(TS)])
    out = json.loads(capsys.readouterr().out)
    # the real engine catalog grades the synthetic preview: Hubris et al. are lethality
    assert rc == 0 and out["verdict"] == "RENDER_MATCH"
    (tmp_path / "bad.json").write_text("[]", encoding="utf-8")
    assert g.main(["grade", "--state", str(tmp_path / "bad.json"), "--dom",
                   str(tmp_path / "dom.json"), "--preview",
                   str(tmp_path / "preview.json")]) == 2


def test_tool_prints_no_player_name():
    r = _grade()
    assert "PlayerA" not in json.dumps(r)


def test_module_runs_as_script():
    res = subprocess.run([sys.executable, str(ROOT / "tools/gated_g418_jhin_lethality.py"),
                          "snippet"], capture_output=True, text=True, timeout=60,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert res.returncode == 0 and "am-build-body" in res.stdout
