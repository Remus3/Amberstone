"""Tests for tools/gated_g103_cc_pressure.py (G1-03 champ-select CC chip grader).

Bundles here are HAND-BUILT (or drawn by the real renderer under node with a
stub element), so a PASS in this file is never evidence for the row
(SUBSTITUTION): only a bundle read in the real dashboard tab counts.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tools import gated_g103_cc_pressure as g

ROOT = Path(__file__).resolve().parent.parent
RENDERER = ROOT / "web" / "js" / "panels" / "cc_conditional_pressure.js"
CHAMP_SELECT = ROOT / "web" / "js" / "panels" / "champ_select.js"
INDEX_HTML = ROOT / "web" / "index.html"
TOOL = ROOT / "tools" / "gated_g103_cc_pressure.py"

ROUTE_URL = ("https://127.0.0.1:8888/api/cc-conditional-pressure?"
             "ally=Leona%2CJinx&enemy=Morgana&mode=SR")


def _bundle(**over) -> dict:
    ev = {
        "tool": "gated_g103_cc_pressure",
        "captured_at": "2026-11-02T20:00:00.000Z",
        "href": "https://127.0.0.1:8888/#champ-select",
        "ui_mock": "",
        "page_age_s": 30.0,
        "state_error": None,
        "lcu": {"phase": "ChampSelect", "queue_id": 420, "ally_ids": [89, 222],
                "enemy_ids": [25], "has_champ_select": True},
        "names": {"ally": ["Leona", "Jinx"], "enemy": ["Morgana"]},
        "view_hidden": True,  # measured: the SHOWN view keeps [hidden]
        "view_box": {"w": 1900.0, "h": 860.0, "visible": True},
        "ta_hidden": False,
        "ta_body_hidden": False,
        "chip_present": True,
        "chip_hidden": False,
        "chip_tier_attr": "good",
        "chip_tier_label": "FAVORABLE",
        "chip_rows": [
            {"label": "Enemy can chain on one target", "value": "1.1s"},
            {"label": "You can chain on one target", "value": "3.2s"},
        ],
        "chip_verdict": "You out-chain them 3.2s vs 1.1s - set up your conditional CC.",
        "chip_box": {"w": 300.0, "h": 80.0, "visible": True},
        "visibility": "visible",
        "route_url": ROUTE_URL,
        "route_status": 200,
        "route": {"ok": True, "tier": "good", "ally_total_cc_seconds": 3.2,
                  "enemy_total_cc_seconds": 1.1, "ratio": 2.9},
    }
    ev.update(over)
    return ev


def test_pass_on_a_rendered_chip_tied_to_the_route():
    res = g.grade(_bundle())
    assert res["verdict"] == "PASS", res
    assert res["state"] == "RENDERED"
    assert res["checks"]["route_tie"] is True


@pytest.mark.parametrize("over", [{"route_url": None, "route": None}, {"route": None},
                                  {"route": {"ok": False}}])
def test_pass_needs_the_route_tie(over):
    # verifier pass 3: a captured URL without a body (or no URL) must not PASS
    res = g.grade(_bundle(**over))
    assert res["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("over, reason", [
    ({"href": "http://127.0.0.1:8888/"}, "https"),
    ({"href": "https://127.0.0.1:9999/"}, "https"),
    ({"href": "file:///tmp/index.html"}, "https"),
    ({"ui_mock": "1"}, "ui_mock"),
    ({"lcu": None, "state_error": "HTTP 500"}, "/api/state"),
])
def test_provenance_misses_are_inconclusive(over, reason):
    res = g.grade(_bundle(**over))
    assert res["verdict"] == "INCONCLUSIVE"
    assert any(reason in p for p in res["provenance"])


def test_not_in_champ_select_is_inconclusive():
    ev = _bundle()
    ev["lcu"]["phase"] = "InProgress"
    res = g.grade(ev)
    assert (res["verdict"], res["state"]) == ("INCONCLUSIVE", "NOT_IN_CHAMP_SELECT")


def test_blind_select_is_inconclusive_never_fail():
    ev = _bundle(chip_hidden=True, chip_box=GONE)
    ev["lcu"]["enemy_ids"] = []
    ev["lcu"]["queue_id"] = 2400
    res = g.grade(ev)
    assert (res["verdict"], res["state"]) == ("INCONCLUSIVE", "BLIND")


def test_zero_ids_are_not_committed():
    ev = _bundle()
    ev["lcu"]["enemy_ids"] = [0, 0]
    assert g.grade(ev)["state"] == "BLIND"
    ev = _bundle()
    ev["lcu"]["ally_ids"] = [0]
    assert g.grade(ev)["state"] == "NO_ALLY"


def test_bad_id_shapes_are_gaps():
    ev = _bundle()
    ev["lcu"]["ally_ids"] = ["89"]
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"
    ev = _bundle()
    ev["lcu"]["enemy_ids"] = [True]
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"


def test_view_not_shown_is_inconclusive():
    gone = {"w": 0, "h": 0, "visible": False}
    assert g.grade(_bundle(view_box=gone))["state"] == "VIEW_NOT_SHOWN"
    flat = {"w": 0, "h": 0, "visible": True}
    assert g.grade(_bundle(view_box=flat))["state"] == "VIEW_NOT_SHOWN"
    assert g.grade(_bundle(view_box=None))["verdict"] == "INCONCLUSIVE"


def test_view_hidden_attribute_is_not_the_truth():
    # measured 2026-10-30: the shown champ-select view keeps [hidden], display block
    assert g.grade(_bundle(view_hidden=True))["verdict"] == "PASS"
    gone = {"w": 0, "h": 0, "visible": False}
    assert g.grade(_bundle(view_hidden=False, view_box=gone))["verdict"] == "INCONCLUSIVE"


def test_missing_chip_is_fail():
    res = g.grade(_bundle(chip_present=False))
    assert (res["verdict"], res["state"]) == ("FAIL", "CHIP_MISSING")


@pytest.mark.parametrize("key", ["chip_present", "chip_hidden", "chip_tier_attr",
                                 "chip_tier_label", "chip_rows", "chip_verdict",
                                 "chip_box"])
def test_a_field_never_captured_is_inconclusive_not_fail(key):
    # verifier pass 4 blocker 1: a missing key is no proof of an absent element
    ev = _bundle()
    del ev[key]
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"
    assert g.grade(_bundle(chip_present=None))["verdict"] == "INCONCLUSIVE"


def test_null_fields_on_a_shown_chip_are_malformed():
    # the snippet returns null for an element it did not find: that IS captured
    ev = _bundle(chip_tier_label=None, chip_rows=[], chip_verdict=None)
    assert g.grade(ev)["verdict"] == "FAIL"


def test_hidden_attribute_with_a_rendered_box_is_graded_as_shown():
    # verifier pass 4 blocker 2: the box wins over the attribute
    res = g.grade(_bundle(chip_hidden=True))
    assert res["verdict"] == "PASS"
    assert any("[hidden]" in n for n in res["notes"])


def test_static_default_tier_alone_is_not_a_render():
    # index.html ships data-cc-cond-tier="warn": an un-rendered chip whose hidden
    # flag was cleared still carries it, so tier alone must not pass
    res = g.grade(_bundle(chip_tier_attr="warn", chip_tier_label=None, chip_rows=[],
                          chip_verdict=None))
    assert (res["verdict"], res["state"]) == ("FAIL", "MALFORMED")


@pytest.mark.parametrize("over", [
    {"chip_tier_attr": "great"},
    {"chip_tier_label": "EVEN"},
    {"chip_rows": [{"label": "Enemy can chain on one target", "value": "1.1"},
                   {"label": "You can chain on one target", "value": "3.2s"}]},
    {"chip_rows": [{"label": "You can chain on one target", "value": "3.2s"}]},
    {"chip_rows": "junk"},
    {"chip_rows": [{"label": "Enemy can chain on one target", "value": chr(0x661) + ".1s"},
                   {"label": "You can chain on one target", "value": "3.2s"}]},
    {"chip_verdict": "   "},
])
def test_malformed_content_is_fail(over):
    assert g.grade(_bundle(**over))["verdict"] == "FAIL"


def test_collapsed_drawer_is_inconclusive():
    res = g.grade(_bundle(ta_body_hidden=True, chip_box={"w": 0, "h": 0, "visible": False}))
    assert (res["verdict"], res["state"]) == ("INCONCLUSIVE", "COLLAPSED")


def test_hidden_cluster_with_a_populated_chip_is_fail():
    res = g.grade(_bundle(ta_hidden=True, chip_box={"w": 0, "h": 0, "visible": False}))
    assert res["verdict"] == "FAIL"
    assert "cluster hidden" in res["fails"][0]


@pytest.mark.parametrize("drawer", [None, "false", 0])
def test_no_box_with_the_drawer_state_unknown_is_inconclusive(drawer):
    # verifier pass 2 blocker 2: a no-box FAIL needs the drawer proven open
    ev = _bundle(ta_body_hidden=drawer, chip_box={"w": 0, "h": 0, "visible": False})
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"


def test_rendered_box_wins_over_attributes():
    assert g.grade(_bundle(ta_hidden=True, ta_body_hidden=True))["verdict"] == "PASS"


def test_open_drawer_with_no_box_is_fail():
    res = g.grade(_bundle(chip_box={"w": 0.0, "h": 0.0, "visible": False}))
    assert res["verdict"] == "FAIL"


@pytest.mark.parametrize("bad_box", [None, {}, {"w": 1, "h": 1}, {"w": "1", "h": 1, "visible": True},
                                     {"w": float("nan"), "h": 1, "visible": True}])
def test_box_not_captured_is_inconclusive(bad_box):
    assert g.grade(_bundle(chip_box=bad_box))["verdict"] == "INCONCLUSIVE"


GONE = {"w": 0, "h": 0, "visible": False}


def test_hidden_on_a_fresh_page_is_fail():
    res = g.grade(_bundle(chip_hidden=True, chip_box=GONE))
    assert (res["verdict"], res["state"]) == ("FAIL", "HIDDEN")


def test_hidden_with_a_non_ok_route_is_a_compute_question():
    res = g.grade(_bundle(chip_hidden=True, chip_box=GONE, route={"ok": False, "reason": "no_champions"}))
    assert res["verdict"] == "INCONCLUSIVE"
    assert "against the route" in res["gaps"][0]


@pytest.mark.parametrize("status", [500, 503, 404, "500", False, 0])
def test_hidden_after_the_pages_fetch_failed_is_inconclusive(status):
    assert g.grade(_bundle(chip_hidden=True, chip_box=GONE, route_status=status))["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("vis", ["hidden", None, True])
def test_hidden_in_a_background_tab_is_inconclusive(vis):
    assert g.grade(_bundle(chip_hidden=True, chip_box=GONE, visibility=vis))["verdict"] == "INCONCLUSIVE"


def test_hidden_with_an_unknown_fetch_status_still_fails():
    # responseStatus is absent on older browsers; the ok re-fetch body still ties it
    assert g.grade(_bundle(chip_hidden=True, chip_box=GONE, route_status=None))["verdict"] == "FAIL"


@pytest.mark.parametrize("age", [0.5, 9.9, 90.1, 3600.0, None, "30", True])
def test_hidden_outside_the_fresh_window_is_inconclusive(age):
    res = g.grade(_bundle(chip_hidden=True, chip_box=GONE, page_age_s=age))
    assert res["verdict"] == "INCONCLUSIVE"


def test_hidden_with_no_route_fetch_seen_is_inconclusive():
    # verifier pass 1 blocker: an in-flight request is not in resource timing yet
    res = g.grade(_bundle(chip_hidden=True, chip_box=GONE, route_url=None, route=None))
    assert res["verdict"] == "INCONCLUSIVE"
    assert "no route fetch seen" in res["gaps"][0]


def test_hidden_with_a_failed_refetch_is_inconclusive():
    res = g.grade(_bundle(chip_hidden=True, chip_box=GONE, route=None))
    assert res["verdict"] == "INCONCLUSIVE"
    assert "re-fetch" in res["gaps"][0]


def test_hidden_after_a_same_count_hover_change_is_inconclusive():
    # verifier pass 2 blocker 1: championId carries hovers, so a hover change keeps
    # the count while the page's last FINISHED fetch is for the old roster
    ev = _bundle(chip_hidden=True, chip_box=GONE)
    ev["lcu"]["ally_ids"] = [89, 51]
    ev["names"] = {"ally": ["Leona", "Caitlyn"], "enemy": ["Morgana"]}
    res = g.grade(ev)
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["checks"]["roster_tie"] is False


@pytest.mark.parametrize("names", [None, {}, {"ally": ["Leona"], "enemy": None},
                                   {"ally": [1], "enemy": ["Morgana"]}])
def test_hidden_without_resolved_names_is_inconclusive(names):
    ev = _bundle(chip_hidden=True, chip_box=GONE, names=names)
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"


def test_hidden_with_a_mode_mismatch_is_inconclusive():
    ev = _bundle(chip_hidden=True, chip_box=GONE, route_url=ROUTE_URL.replace("mode=SR", "mode=ARAM"))
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("over", [
    {"names": None},
    {"route_url": ROUTE_URL.replace("mode=SR", "mode=ARAM")},
    {"route_url": ROUTE_URL.replace("Morgana", "Annie")},
])
def test_rendered_without_a_roster_tie_is_inconclusive(over):
    res = g.grade(_bundle(**over))
    assert res["verdict"] == "INCONCLUSIVE"
    assert any("roster tie" in x for x in res["gaps"])


def test_hidden_while_the_page_lags_the_rosters_is_inconclusive():
    ev = _bundle(chip_hidden=True, chip_box=GONE)
    ev["lcu"]["enemy_ids"] = [25, 12]
    ev["names"]["enemy"] = ["Morgana", "Alistar"]
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"


def test_rendered_but_lagging_rosters_is_inconclusive():
    ev = _bundle()
    ev["lcu"]["ally_ids"] = [89]
    ev["names"]["ally"] = ["Leona"]
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"


def test_route_tie_mismatch_is_inconclusive():
    ev = _bundle()
    ev["route"]["enemy_total_cc_seconds"] = 2.4
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"
    ev = _bundle()
    ev["route"]["tier"] = "bad"
    assert g.grade(ev)["verdict"] == "INCONCLUSIVE"


def test_route_tie_tolerates_half_way_rounding():
    # JS (1.25).toFixed(1) is "1.3"; Python formats 1.25 as "1.2"
    ev = _bundle(chip_rows=[{"label": "Enemy can chain on one target", "value": "1.3s"},
                            {"label": "You can chain on one target", "value": "3.2s"}])
    ev["route"]["enemy_total_cc_seconds"] = 1.25
    assert g.grade(ev)["verdict"] == "PASS"


def test_route_fallback_fields_mirror_the_renderer():
    assert g.expected_from_route({"ok": True, "ally_conditional_cc_s": 2.0}) == {
        "tier": "warn", "enemy_s": 0.0, "ally_s": 2.0}
    assert g.expected_from_route({"ok": False}) is None
    assert g.expected_from_route({"ok": True, "ally_total_cc_seconds": "x"}) is None


def test_route_names_lists():
    assert g.route_names(ROUTE_URL) == {"ally": ["Jinx", "Leona"], "enemy": ["Morgana"],
                                        "mode": "SR"}
    assert g.route_names("https://127.0.0.1:8888/api/state") is None
    assert g.route_names(None) is None


def test_grade_rejects_a_non_object():
    with pytest.raises(g.InputError):
        g.grade([1, 2])


# --- CLI -----------------------------------------------------------------------


def _run(tmp_path, ev, *extra) -> int:
    p = tmp_path / "ev.json"
    p.write_text(json.dumps(ev) if not isinstance(ev, str) else ev, encoding="utf-8")
    return g.main(["grade", "--evidence", str(p), *extra])


def test_cli_exit_codes(tmp_path, capsys):
    assert _run(tmp_path, _bundle()) == 0
    assert _run(tmp_path, _bundle(chip_present=False)) == 1
    assert _run(tmp_path, _bundle(ui_mock="1")) == 3
    assert _run(tmp_path, "{not json") == 2
    assert _run(tmp_path, "[]") == 2
    assert _run(tmp_path, _bundle(), "--json") == 0
    out = capsys.readouterr().out
    assert '"verdict": "PASS"' in out


def test_cli_snippet_prints_and_never_reads_a_puuid(capsys):
    assert g.main(["snippet"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == g.SNIPPET.strip()
    assert "puuid" not in g.SNIPPET
    assert "summonerName" not in g.SNIPPET and "gameName" not in g.SNIPPET


def test_cli_human_output_names_no_ids(tmp_path, capsys):
    assert _run(tmp_path, _bundle()) == 0
    out = capsys.readouterr().out
    assert "G1-03 verdict PASS (RENDERED)" in out
    assert "89" not in out and "222" not in out


def test_tool_is_read_only_and_offline():
    src = TOOL.read_text(encoding="utf-8")
    for banned in ("urllib.request", "requests", "http.client", "socket",
                   "write_text", "write_bytes", ".unlink(", "open("):
        assert banned not in src, banned


# --- pins against the shipped dashboard ------------------------------------------


def test_tier_labels_match_the_renderer():
    src = RENDERER.read_text(encoding="utf-8")
    body = src[src.index("function _tierLabel"):src.index("function _conditionalVerdict")]
    assert 'tier === "good") return "FAVORABLE"' in body
    assert 'tier === "bad")  return "AT RISK"' in body
    assert 'return "EVEN"' in body
    assert g.TIER_LABELS == {"good": "FAVORABLE", "warn": "EVEN", "bad": "AT RISK"}


def test_renderer_markup_matches_the_snippet_selectors():
    src = RENDERER.read_text(encoding="utf-8")
    for cls in ("cc-conditional-pressure-tier", "cc-conditional-pressure-row",
                "cc-conditional-pressure-row-label", "cc-conditional-pressure-row-value",
                "cc-conditional-pressure-verdict"):
        assert f'class="{cls}"' in src, cls
        assert f".{cls}" in g.SNIPPET, cls
    assert g.ENEMY_ROW_LABEL in src and g.ALLY_ROW_LABEL in src
    assert "blockEl.dataset.ccCondTier = tier;" in src


def test_index_html_nesting_and_static_default():
    html = INDEX_HTML.read_text(encoding="utf-8")
    view = html.index('id="view-champ-select"')
    ta = html.index('id="csv-team-analysis"')
    body = html.index('id="csv-ta-body"')
    chip = html.index('id="csv-sugg-cc-conditional-pressure"')
    assert view < ta < body < chip
    tag = html[html.rindex("<div", 0, chip):html.index(">", chip)]
    # the trap the grader encodes: the static chip already carries tier "warn"
    assert 'data-cc-cond-tier="warn"' in tag and "hidden" in tag
    assert "view_box: box(view)" in g.SNIPPET
    for elem_id in ("view-champ-select", "csv-team-analysis", "csv-ta-body",
                    "csv-sugg-cc-conditional-pressure"):
        assert f'$("{elem_id}")' in g.SNIPPET, elem_id


def test_champ_select_gate_and_drawer_default():
    src = CHAMP_SELECT.read_text(encoding="utf-8")
    gate = src[src.index("function _csvRenderCcConditionalPressure"):]
    gate = gate[:gate.index("\n}\n")]
    assert "cs.their_team" in gate and "block.hidden = true;" in gate
    assert '"/api/' not in gate  # the fetch lives in the renderer module
    assert 'sessionStorage.getItem(_CSV_TA_STORE_KEY) === "1"' in src
    assert "if (body) body.hidden = !open;" in src


def test_mode_map_matches_the_page_gate():
    src = CHAMP_SELECT.read_text(encoding="utf-8")
    gate = src[src.index("function _csvRenderCcConditionalPressure"):]
    gate = gate[:gate.index(chr(10) + "}" + chr(10))]
    assert 'if (q === 2400) mode = "KIWI";' in gate
    assert 'q === 1700 || q === 1710 || q === 1750) mode = "ARENA";' in gate
    assert 'q === 420 || q === 400 || q === 430 || q === 700) mode = "SR";' in gate
    assert 'let mode = "ARAM";' in gate
    assert [g.mode_for_queue(q) for q in (2400, 1750, 420, 400, 450, None, 9999)] == [
        "KIWI", "ARENA", "SR", "SR", "ARAM", "ARAM", "ARAM"]


def test_snippet_resolves_names_from_the_page_s_own_index():
    items_index = (ROOT / "web" / "js" / "lib" / "items_index.js").read_text(encoding="utf-8")
    assert 'fetch("/data/champions_index.json' in items_index
    assert "CHAMPS.byId = j.byId || {};" in items_index
    assert 'fetch("/data/champions_index.json"' in g.SNIPPET
    assert "byId[String(id)]" in g.SNIPPET
    src = RENDERER.read_text(encoding="utf-8")
    assert "const slug = byId[String(id)];" in src


def test_snippet_parses_as_javascript(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    p = tmp_path / "snippet.mjs"
    p.write_text("export const f = " + g.SNIPPET + ";\n", encoding="utf-8")
    r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr


# --- the real renderer, under node, feeds the grader ------------------------------

NODE_HARNESS = r"""
import { renderCcConditionalPressure } from './ccp.mjs';
const payload = JSON.parse(process.argv[2]);
const el = { id: 'csv-sugg-cc-conditional-pressure', hidden: true,
             dataset: { ccCondTier: 'warn' }, innerHTML: '' };
const out = {};
renderCcConditionalPressure(el, payload);
out.first = { hidden: el.hidden, tier: el.dataset.ccCondTier, html: el.innerHTML };
el.hidden = true;               // the champ_select.js gate hides it directly
renderCcConditionalPressure(el, payload);
out.after_gate_hide = { hidden: el.hidden };
process.stdout.write(JSON.stringify(out));
"""


def _node_render(tmp_path, payload) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    src = RENDERER.read_text(encoding="utf-8")
    imp = "import { CHAMPS } from '../lib/items_index.js';"
    assert imp in src
    (tmp_path / "ccp.mjs").write_text(src.replace(imp, "const CHAMPS = {};"),
                                      encoding="utf-8")
    (tmp_path / "run.mjs").write_text(NODE_HARNESS, encoding="utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), json.dumps(payload)],
                       capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


class _ChipParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.tier_label = None
        self.verdict = None
        self.rows: list[dict] = []

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        self.stack.append(cls)
        if cls == "cc-conditional-pressure-row":
            self.rows.append({"label": None, "value": None})

    def handle_endtag(self, tag):
        self.stack.pop()

    def handle_data(self, data):
        cls = self.stack[-1] if self.stack else ""
        if cls == "cc-conditional-pressure-tier":
            self.tier_label = data
        elif cls == "cc-conditional-pressure-verdict":
            self.verdict = data
        elif cls == "cc-conditional-pressure-row-label":
            self.rows[-1]["label"] = data
        elif cls == "cc-conditional-pressure-row-value":
            self.rows[-1]["value"] = data


@pytest.mark.parametrize("payload", [
    {"ok": True, "tier": "good", "ally_total_cc_seconds": 3.2,
     "enemy_total_cc_seconds": 1.1, "ratio": 2.9},
    {"ok": True, "tier": "bad", "ally_total_cc_seconds": 0.0,
     "enemy_total_cc_seconds": 1.25, "ratio": 0.0},
    {"ok": True, "ally_conditional_cc_s": 0.4, "enemy_conditional_cc_s": 0.4},
])
def test_real_renderer_output_grades_pass(tmp_path, payload):
    out = _node_render(tmp_path, payload)
    first = out["first"]
    assert first["hidden"] is False
    p = _ChipParser()
    p.feed(first["html"])
    ev = _bundle(chip_tier_attr=first["tier"], chip_tier_label=p.tier_label,
                 chip_rows=p.rows, chip_verdict=p.verdict, route=copy.deepcopy(payload))
    res = g.grade(ev)
    assert res["verdict"] == "PASS", res
    assert re.match(r"^\d+\.\ds$", p.rows[0]["value"])


def test_stale_signature_trap_still_exists(tmp_path):
    # If this starts failing, the renderer now clears its signature on an external
    # hide: the page-age window in grade() can then be relaxed (and this test with it).
    out = _node_render(tmp_path, {"ok": True, "tier": "good", "ally_total_cc_seconds": 3.2,
                                  "enemy_total_cc_seconds": 1.1, "ratio": 2.9})
    assert out["first"]["hidden"] is False
    assert out["after_gate_hide"]["hidden"] is True
