"""Tests for tools/gated_g101_cs_cards.py (G1-01 locked-own-champ card grader).

Bundles here are HAND-BUILT (or drawn by the real renderers under node with a
stub element), so a PASS in this file is never evidence for the row
(SUBSTITUTION): only a bundle captured in the real dashboard tab is.
"""
from __future__ import annotations

import copy
import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import gated_g101_cs_cards as g

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
CS_JS = WEB / "js" / "panels" / "champ_select.js"
DSSO_JS = WEB / "js" / "panels" / "ds_skill_order.js"
PBW_JS = WEB / "js" / "panels" / "personal_build.js"
BO_JS = WEB / "js" / "panels" / "build_order.js"

BOX = {"w": 540.0, "h": 92.0, "visible": True, "in_viewport": True}
NOBOX = {"w": 0, "h": 0, "visible": False, "in_viewport": False}
DSSO_PAYLOAD = {"ok": True, "reason": None, "champion": "Jinx",
                "max_order": ["Q", "W", "E"], "max_order_str": "Q > W > E",
                "ult_levels": [6, 11, 16]}
BASE = {
    "tool": "gated_g101_cs_cards",
    "captured_at": "2026-10-30T12:00:00.000Z",
    "href": "https://127.0.0.1:8888/",
    "ui_mock": "",
    "page_age_s": 30.0,
    "visibility": "visible",
    "state_error": None,
    "lcu": {"phase": "ChampSelect", "queue_id": 420, "is_aram": False,
            "my_champion": 222, "my_champion_locked": 222, "my_completed": True,
            "has_champ_select": True},
    "slug": "Jinx",
    "pbw_mode": "sr",
    "cache_error": None,
    "dom_after_cache": True,
    "view_box": BOX,
    "host_box": BOX,
    "dsso": {"present": True, "hidden": False, "box": BOX, "title": "Skill order",
             "sub": "Jinx", "max": "Max: Q > W > E", "ult": "Ult: 6/11/16",
             "payload": DSSO_PAYLOAD,
             "fetch": {"since_s": 25.0, "status": 200, "count": 1}},
    "pbw": {"present": True, "hidden": False, "box": BOX, "title": "Your best build",
            "sub": "Jinx: items you win with (baseline 60% / 60g)", "rows": 6,
            "payload": {"champion": "Jinx", "confidence": "ok", "n_items": 6},
            "fetch": {"since_s": 25.0, "status": 200, "count": 1}},
    "seq": {"builds_present": True, "builds_champion": "Jinx", "builds_mode": "sr",
            "present": True, "state": "ready", "box": BOX, "tag": "ORDERED SEQUENCE",
            "chips": 6, "fetch": {"since_s": 25.0, "status": 200, "count": 1}},
}


def _bundle(**over):
    """BASE with dotted-path overrides, e.g. _bundle(**{"dsso.box": NOBOX})."""
    ev = copy.deepcopy(BASE)
    for path, val in over.items():
        cur = ev
        keys = path.split(".")
        for k in keys[:-1]:
            cur = cur[k]
        cur[keys[-1]] = val
    return ev


def _card(ev, name):
    return g.grade(ev)["cards"][name]["verdict"]


# --- overall gates -----------------------------------------------------------------

def test_baseline_passes():
    res = g.grade(_bundle())
    assert res["verdict"] == "PASS"
    assert {c["verdict"] for c in res["cards"].values()} == {"PASS"}


@pytest.mark.parametrize("over,state", [
    ({"href": "https://127.0.0.1:8889/"}, "UNGRADED"),
    ({"href": "http://127.0.0.1:8888/"}, "UNGRADED"),
    ({"ui_mock": "1"}, "UNGRADED"),
    ({"href": "https://127.0.0.1:8888/?ui_mock=1&mode=sr#champ-select"}, "UNGRADED"),
    ({"lcu": None}, "UNGRADED"),
    ({"lcu.phase": "InProgress"}, "NOT_IN_CHAMP_SELECT"),
    ({"lcu.my_completed": False}, "NOT_LOCKED"),
    ({"lcu.my_completed": None}, "NOT_LOCKED"),
    ({"lcu.my_champion_locked": 0}, "NOT_LOCKED"),
    ({"lcu.my_champion": 0}, "NOT_LOCKED"),
    ({"lcu.queue_id": 450}, "NOT_SR"),
    ({"lcu.queue_id": 2400}, "NOT_SR"),
    ({"lcu.queue_id": 1750}, "NOT_SR"),
    ({"lcu.is_aram": True}, "NOT_SR"),
    ({"view_box": NOBOX}, "VIEW_NOT_SHOWN"),
])
def test_gates_are_inconclusive(over, state):
    res = g.grade(_bundle(**over))
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["state"] == state
    assert res["cards"] == {}


@pytest.mark.parametrize("over", [
    {"slug": None}, {"slug": ""}, {"page_age_s": 9.9}, {"page_age_s": None},
    {"visibility": "hidden"}, {"host_box": NOBOX}, {"host_box": None},
])
def test_capture_gaps_are_inconclusive(over):
    res = g.grade(_bundle(**over))
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["cards"] == {}


def test_locked_id_absent_from_older_agent_shape_still_locks():
    assert g.grade(_bundle(**{"lcu.my_champion_locked": None}))["verdict"] == "PASS"


# --- DS skill order -------------------------------------------------------------------

@pytest.mark.parametrize("over,verdict", [
    ({"dsso.present": False}, "FAIL"),
    ({"dsso.title": "Skill"}, "FAIL"),
    ({"dsso.max": "Max: "}, "FAIL"),
    ({"dsso.max": "Max: Q -> W -> E"}, "FAIL"),
    ({"dsso.ult": "Ult: "}, "FAIL"),
    ({"dsso.box": None}, "INCONCLUSIVE"),
    ({"dsso.sub": "Vayne"}, "INCONCLUSIVE"),
    ({"dsso.max": "Max: Q > E > W"}, "INCONCLUSIVE"),
    ({"dsso.ult": "Ult: 6/11"}, "INCONCLUSIVE"),
    ({"dsso.payload": None}, "INCONCLUSIVE"),
    ({"dsso.payload.ok": False}, "INCONCLUSIVE"),
])
def test_dsso_shown_paths(over, verdict):
    assert _card(_bundle(**over), "ds_skill_order") == verdict


def test_dsso_hidden_attribute_with_a_box_is_graded_as_shown():
    assert _card(_bundle(**{"dsso.hidden": True}), "ds_skill_order") == "PASS"


@pytest.mark.parametrize("over,verdict", [
    ({}, "FAIL"),                                                   # stale-signature hide
    ({"dsso.payload": None}, "INCONCLUSIVE"),                       # nothing cached yet
    ({"dsso.payload.ok": False}, "INCONCLUSIVE"),                   # hidden by design
    ({"dsso.payload.max_order": []}, "INCONCLUSIVE"),
    ({"dom_after_cache": False, "dsso.fetch.since_s": 2.0}, "INCONCLUSIVE"),
    ({"dom_after_cache": False, "dsso.fetch": None}, "INCONCLUSIVE"),
    ({"dom_after_cache": False, "dsso.fetch.since_s": 6.0}, "FAIL"),
    ({"cache_error": "TypeError", "dsso.fetch.since_s": 2.0}, "INCONCLUSIVE"),
    ({"dsso.fetch.status": 500}, "INCONCLUSIVE"),
    ({"dsso.fetch.status": None}, "FAIL"),
])
def test_dsso_hidden_paths(over, verdict):
    res = g.grade(_bundle(**{"dsso.box": NOBOX, "dsso.hidden": True, **over}))
    assert res["cards"]["ds_skill_order"]["verdict"] == verdict
    assert res["verdict"] == ("FAIL" if verdict == "FAIL" else "INCONCLUSIVE")
    if verdict == "FAIL":
        assert any("RM-1162" in n for n in res["notes"])


# --- personal build -----------------------------------------------------------------

@pytest.mark.parametrize("over,verdict", [
    ({"pbw.present": False}, "FAIL"),
    ({"pbw.title": "Best build"}, "FAIL"),
    ({"pbw.sub": "Jinx"}, "FAIL"),
    ({"pbw.rows": 0}, "FAIL"),
    ({"pbw.rows": None}, "FAIL"),
    ({"pbw.rows": 5}, "INCONCLUSIVE"),
    ({"pbw.sub": "Vayne: items you win with (baseline 50% / 9g)"}, "INCONCLUSIVE"),
    ({"pbw.payload": None}, "INCONCLUSIVE"),
    ({"pbw.payload.n_items": 0}, "INCONCLUSIVE"),
])
def test_pbw_shown_paths(over, verdict):
    assert _card(_bundle(**over), "personal_build") == verdict


@pytest.mark.parametrize("over,verdict", [
    ({}, "FAIL"),
    ({"pbw.payload.n_items": 0, "pbw.payload.confidence": "insufficient"}, "INCONCLUSIVE"),
    ({"pbw.payload": None}, "INCONCLUSIVE"),
    ({"dom_after_cache": False, "pbw.fetch.since_s": 1.0}, "INCONCLUSIVE"),
])
def test_pbw_hidden_paths(over, verdict):
    ev = _bundle(**{"pbw.box": NOBOX, "pbw.hidden": True, **over})
    assert _card(ev, "personal_build") == verdict


@pytest.mark.parametrize("builds_champion", ["-", "Vayne", None])
def test_hidden_card_on_a_page_still_drawing_another_pick_is_not_a_fail(builds_champion):
    # verifier c37 blocker: hover B, hover C, lock B, capture inside the ~2 s state
    # push - the page still draws C while B's payload is cached. State lag, not RM-1162.
    ev = _bundle(**{"dsso.box": NOBOX, "dsso.hidden": True, "pbw.box": NOBOX,
                    "pbw.hidden": True, "seq.builds_champion": builds_champion})
    res = g.grade(ev)
    assert res["cards"]["ds_skill_order"]["verdict"] == "INCONCLUSIVE"
    assert res["cards"]["personal_build"]["verdict"] == "INCONCLUSIVE"
    assert res["verdict"] == "INCONCLUSIVE"
    assert not any("RM-1162" in n for n in res["notes"])


def test_below_the_fold_card_passes_with_a_note():
    low = dict(BOX, in_viewport=False)
    res = g.grade(_bundle(**{"pbw.box": low}))
    assert res["verdict"] == "PASS"
    assert any("below the fold" in n for n in res["notes"])


def test_pbw_below_threshold_names_the_confidence():
    ev = _bundle(**{"pbw.box": NOBOX, "pbw.payload.n_items": 0,
                    "pbw.payload.confidence": "insufficient"})
    assert any("insufficient" in n for n in g.grade(ev)["notes"])


# --- ordered sequence strip ---------------------------------------------------------

@pytest.mark.parametrize("over,verdict", [
    ({"seq.builds_present": False}, "FAIL"),
    ({"seq.builds_champion": "Vayne"}, "INCONCLUSIVE"),
    ({"seq.builds_mode": "aram"}, "INCONCLUSIVE"),
    ({"seq.present": False}, "FAIL"),
    ({"seq.state": "loading"}, "INCONCLUSIVE"),
    ({"seq.state": "empty"}, "INCONCLUSIVE"),
    ({"seq.state": "bogus"}, "FAIL"),
    ({"seq.chips": 0}, "FAIL"),
    ({"seq.chips": 8}, "FAIL"),
    ({"seq.tag": "SEQUENCE"}, "FAIL"),
    ({"seq.box": NOBOX}, "FAIL"),
    ({"seq.box": None}, "INCONCLUSIVE"),
])
def test_seq_paths(over, verdict):
    assert _card(_bundle(**over), "build_seq") == verdict


def test_one_fail_fails_the_row_and_mixed_is_inconclusive():
    assert g.grade(_bundle(**{"seq.present": False, "dsso.payload": None}))["verdict"] == "FAIL"
    assert g.grade(_bundle(**{"seq.state": "loading"}))["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("bad", [
    [], "x", {"dsso": "x"}, {"dsso.box": "x"}, {"dsso.payload": "x"}, {"pbw.payload": 3},
])
def test_bad_shapes_raise_input_error(bad):
    if isinstance(bad, dict):
        key, val = next(iter(bad.items()))
        ev = _bundle(**{key: val})
        with pytest.raises(g.InputError):
            g.grade(ev)
    else:
        with pytest.raises(g.InputError):
            g.grade(bad)


# --- CLI ------------------------------------------------------------------------------

def _run(tmp_path, ev, *extra) -> int:
    p = tmp_path / "ev.json"
    p.write_text(ev if isinstance(ev, str) else json.dumps(ev), encoding="utf-8")
    return g.main(["grade", "--evidence", str(p), *extra])


def test_cli_exit_codes(tmp_path, capsys):
    assert _run(tmp_path, _bundle()) == 0
    assert _run(tmp_path, _bundle(**{"seq.present": False})) == 1
    assert _run(tmp_path, _bundle(ui_mock="1")) == 3
    assert _run(tmp_path, "{not json") == 2
    assert _run(tmp_path, "[]") == 2
    assert _run(tmp_path, _bundle(**{"dsso.box": "x"})) == 2
    assert _run(tmp_path, _bundle(), "--json") == 0
    assert g.main(["snippet"]) == 0


def test_cli_human_output_prints_no_champion_id(tmp_path, capsys):
    capsys.readouterr()
    assert _run(tmp_path, _bundle(**{"lcu.my_champion": 777, "lcu.my_champion_locked": 777})) == 0
    out = capsys.readouterr().out
    assert "777" not in out and "Jinx" not in out and "PASS" in out


# --- source pins: the grader's assumptions about the page -------------------------

def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_mounts_and_markup_the_grader_reads_exist():
    idx = _src(WEB / "index.html")
    assert 'id="csv-sugg-ds-skill-order"' in idx and 'id="csv-personal-build"' in idx
    dsso = _src(DSSO_JS)
    for s in ('"dsso-head-title">Skill order<', "dsso-head-sub", '"dsso-max">Max: ',
              '"dsso-ult">Ult: '):
        assert s in dsso, s
    pbw = _src(PBW_JS)
    for s in ('"pbw-head-title">Your best build<', "pbw-head-sub", ": items you win with",
              'class="pbw-row"'):
        assert s in pbw, s
    cs = _src(CS_JS)
    for s in ('id="csv-builds-seq" data-bo-state="loading"', 'data-bo-state="empty"',
              'data-bo-state="ready"', "ORDERED SEQUENCE", 'class="csv-boseq-chip',
              '<div class="csv-builds" data-champion="${myName || ""}" data-mode="${mode || "sr"}">'):
        assert s in cs, s
    assert "const BO_SLOTS = 7;" in _src(BO_JS)


def test_pbw_mode_map_matches_the_page():
    m = re.search(r"const _PBW_MODE_MAP = \{(.*?)\};", _src(PBW_JS), re.S)
    pairs = {int(k): v for k, v in re.findall(r"(\d+):\s*\"(\w+)\"", m.group(1))}
    assert pairs == g.PBW_MODE_MAP
    # the snippet's own non-sr subset agrees with the page map
    snip = {int(k): v for k, v in re.findall(r"(\d+): \"(\w+)\"", g.SNIPPET)}
    assert snip == {k: v for k, v in pairs.items() if v != "sr"}


def test_detect_mode_mirrors_csv_detect_mode():
    body = re.search(r"function _csvDetectMode\(cs\) \{(.*?)\n\}", _src(CS_JS), re.S).group(1)
    assert 'q === 1700 || q === 1710 || q === 1750) return "arena"' in body
    assert 'cs.is_aram || q === 450 || q === 920 || q === 2400) return "aram"' in body
    assert [g.detect_mode(q, a) for q, a in ((420, False), (450, False), (1750, True),
                                             (400, True), (None, None))] == \
        ["sr", "aram", "arena", "aram", "sr"]


def test_cards_render_only_on_the_sr_path():
    cs = _src(CS_JS)
    assert re.search(r'if \(mode === "sr"\) \{\s*_csvRenderSuggestions\(cs, myCid, myName, mode\);'
                     r'\s*\} else \{\s*_csvRenderSuggestionsNonSr\(cs\);', cs)
    nonsr = re.search(r"function _csvRenderSuggestionsNonSr\(cs\) \{(.*?)\n\}", cs, re.S).group(1)
    assert "PersonalBuild" not in nonsr and "SkillOrder" not in nonsr


def test_snippet_reads_the_pages_own_module_instances():
    # main.js loads with a ?v= query but imports panels by RELATIVE specifier, so
    # /js/panels/<m>.js (no query) is the page's instance, not a second copy.
    assert re.search(r'<script type="module" src="/js/main\.js\?v=', _src(WEB / "index.html"))
    assert "from './panels/champ_select.js'" in _src(WEB / "js" / "main.js")
    assert "from './ds_skill_order.js'" in _src(CS_JS)
    assert "from './personal_build.js'" in _src(CS_JS)
    assert 'import("/js/panels/ds_skill_order.js")' in g.SNIPPET
    assert 'import("/js/panels/personal_build.js")' in g.SNIPPET
    assert "export function getCachedDsSkillOrder(champion, mode)" in _src(DSSO_JS)
    assert "export function getCachedPersonalBuild(" in _src(PBW_JS)
    assert 'getCachedDsSkillOrder(slug, "SR")' in g.SNIPPET  # renderDsSkillOrderForChampSelect: mode "SR"
    assert 'const mode = "SR";' in _src(DSSO_JS)


def test_render_gate_is_not_the_cause_scheduled_renders_clear_the_sig():
    # the docstring rules the _csvComputeSig gate OUT; pin the reason
    body = re.search(r"function _csvScheduleRender\(\) \{(.*?)\n\}", _src(CS_JS), re.S).group(1)
    assert 'sec.dataset.csvSig = ""' in body


def test_strip_empty_state_unreachable_trap_still_exists():
    # RM-1163: build_order.js caches ONLY an ok, non-empty order, so the strip's
    # "no ordered build" branch never draws; a no-order route leaves "computing...".
    # When this goes red the strip can reach "empty": revisit grade_seq.
    bo = _src(BO_JS)
    assert bo.count("_BO_CACHE[key] = data") == 1
    assert "if (data && data.ok && Array.isArray(data.order) && data.order.length) {" in bo


def test_stale_signature_gate_hides_without_clearing_the_signature():
    # RM-1162 source half: both champ-select gates hide the card DIRECTLY on
    # "no champion yet", leaving the renderer's signature stamp in place.
    dsso = re.search(r"export function renderDsSkillOrderForChampSelect\(cs, blockId\) \{(.*?)\n\}",
                     _src(DSSO_JS), re.S).group(1)
    assert "if (myId <= 0) {\n    block.hidden = true;\n    return;" in dsso
    assert "_DSSO_SIG" not in dsso
    pbw = re.search(r"function _csvRenderPersonalBuild\(cs\) \{(.*?)\n\}", _src(CS_JS), re.S).group(1)
    assert "if (myId <= 0) {\n    block.hidden = true;\n    return;" in pbw
    assert "_PBW_SIG" not in _src(CS_JS)


# --- node: the snippet parses; the real renderers feed the grader ---------------------

def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    return node


def test_snippet_parses_as_javascript(tmp_path):
    p = tmp_path / "snippet.mjs"
    p.write_text("export default " + g.SNIPPET + ";\n", encoding="utf-8")
    r = subprocess.run([_node(), "--check", str(p)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


NODE_HARNESS = r"""
import * as dsso from "./dsso.mjs";
import * as pbw from "./pbw.mjs";
const [mode] = process.argv.slice(2);
const P = %s;
const Q = %s;
const el = (id) => ({ id, hidden: true, innerHTML: "" });
if (mode === "render") {
  const a = el("csv-sugg-ds-skill-order"), b = el("csv-personal-build");
  dsso.renderDsSkillOrder(a, P); pbw.renderPersonalBuild(b, Q);
  console.log(JSON.stringify({ dsso: a, pbw: b }));
} else {
  // RM-1162 through the real entry point: lock, new select with no pick, lock again
  const a = el("csv-sugg-ds-skill-order");
  globalThis.document = { getElementById: () => a };
  globalThis.fetch = async () => ({ ok: true, json: async () => P });
  const seen = [];
  dsso.renderDsSkillOrderForChampSelect({ my_champion: 222 });
  await new Promise((r) => setTimeout(r, 20));
  dsso.renderDsSkillOrderForChampSelect({ my_champion: 222 }); seen.push(a.hidden);
  dsso.renderDsSkillOrderForChampSelect({ my_champion: 0 }); seen.push(a.hidden);
  dsso.renderDsSkillOrderForChampSelect({ my_champion: 222 }); seen.push(a.hidden);
  const b = el("csv-personal-build");
  pbw.renderPersonalBuild(b, Q); seen.push(b.hidden);
  b.hidden = true;                       // what _csvRenderPersonalBuild does on no pick
  pbw.renderPersonalBuild(b, Q); seen.push(b.hidden);
  console.log(JSON.stringify(seen));
}
"""

PBW_PAYLOAD = {"champion": "Jinx", "champion_id": None, "mode": "sr", "games": 60,
               "win_rate": 0.6, "baseline_win_rate": 0.6, "confidence": "ok",
               "items": [{"item_id": 3031, "name": "Infinity Edge", "games": 30, "wins": 20,
                          "win_rate": 0.66, "adj_win_rate": 0.64, "lift": 0.04,
                          "is_boots": False},
                         {"item_id": 3006, "name": "Berserker's Greaves", "games": 40,
                          "wins": 24, "win_rate": 0.6, "adj_win_rate": 0.6, "lift": 0.0,
                          "is_boots": True}],
               "most_common_build": [3006, 3031]}


def _node_run(tmp_path, mode):
    node = _node()
    src = _src(DSSO_JS)
    imp = "import { resolveChampNames } from './cc_conditional_pressure.js';"
    assert imp in src
    stub = "const resolveChampNames = (ids) => ids.filter((x) => (x | 0) > 0).map(() => 'Jinx');"
    (tmp_path / "dsso.mjs").write_text(src.replace(imp, stub), encoding="utf-8")
    (tmp_path / "pbw.mjs").write_text(_src(PBW_JS), encoding="utf-8")
    (tmp_path / "run.mjs").write_text(
        NODE_HARNESS % (json.dumps(DSSO_PAYLOAD), json.dumps(PBW_PAYLOAD)), encoding="utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), mode], capture_output=True,
                       text=True, timeout=60, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _text(markup: str, cls: str):
    pat = r'<(span|div) class="' + re.escape(cls) + r'"[^>]*>(.*?)</\1>'
    m = re.search(pat, markup, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(2))) if m else None


def test_real_renderer_markup_grades_pass(tmp_path):
    out = _node_run(tmp_path, "render")
    a, b = out["dsso"]["innerHTML"], out["pbw"]["innerHTML"]
    assert out["dsso"]["hidden"] is False and out["pbw"]["hidden"] is False
    ev = _bundle(**{
        "dsso.title": _text(a, "dsso-head-title"), "dsso.sub": _text(a, "dsso-head-sub"),
        "dsso.max": _text(a, "dsso-max"), "dsso.ult": _text(a, "dsso-ult"),
        "pbw.title": _text(b, "pbw-head-title"), "pbw.sub": _text(b, "pbw-head-sub"),
        "pbw.rows": b.count('class="pbw-row"'), "pbw.payload.n_items": 2,
    })
    res = g.grade(ev)
    assert res["cards"]["ds_skill_order"]["verdict"] == "PASS", res
    assert res["cards"]["personal_build"]["verdict"] == "PASS", res


def test_stale_signature_trap_still_exists(tmp_path):
    # RM-1162. When the fix lands this goes red ON PURPOSE: the hidden-with-data
    # FAIL in the grader then stops naming RM-1162 as the measured cause.
    seen = _node_run(tmp_path, "stale")
    assert seen == [False, True, True, False, True]
