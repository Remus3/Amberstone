"""Tests for tools/gated_g311_cc_blended_chip.py (G3-11 cc_blended chip grader).

Bundles here are HAND-BUILT (or drawn by the real renderer under node with a
stub element), so a PASS in this file is never evidence for the row
(SUBSTITUTION): only a bundle read in the real dashboard tab counts.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tools import gated_g311_cc_blended_chip as g

ROOT = Path(__file__).resolve().parent.parent
RENDERER = ROOT / "web" / "js" / "panels" / "cc_blended_ehp_threat.js"
CHAMP_SELECT = ROOT / "web" / "js" / "panels" / "champ_select.js"
INDEX_HTML = ROOT / "web" / "index.html"
ROUTE = ROOT / "dashboard" / "routes_cc_blended_ehp_threat.py"
TOOL = ROOT / "tools" / "gated_g311_cc_blended_chip.py"

ROUTE_URL = ("https://127.0.0.1:8888/api/cc-blended-ehp-threat?"
             "ally=Leona%2CJinx&enemy=Morgana&mode=SR")
ROUTE_BODY = {"ok": True, "mode": "SR", "tier": "good", "ratio": 1.2,
              "ally_avg_cc_blended_ehp": 2500.4, "enemy_avg_cc_blended_ehp": 2083.5,
              "ally_total_cc_seconds": 3.2, "enemy_total_cc_seconds": 1.1}


def _bundle(**over) -> dict:
    ev = {
        "tool": "gated_g311_cc_blended_chip",
        "captured_at": "2026-11-08T20:00:00.000Z",
        "href": "https://127.0.0.1:8888/#champ-select",
        "ui_mock": "",
        "page_age_s": 30.0,
        "state_error": None,
        "lcu": {"phase": "ChampSelect", "queue_id": 420, "ally_ids": [89, 222],
                "enemy_ids": [25], "has_champ_select": True},
        "names": {"ally": ["Leona", "Jinx"], "enemy": ["Morgana"]},
        "view_hidden": True,
        "view_box": {"w": 1900.0, "h": 860.0, "visible": True},
        "ta_hidden": False,
        "ta_body_hidden": False,
        "chip_present": True,
        "chip_hidden": False,
        "chip_tier_attr": "good",
        "chip_tier_label": "FAVORABLE",
        "chip_rows": [
            {"label": "Enemy can chain on you", "value": "1.1s",
             "ehp": "(your EHP 2500)"},
            {"label": "You can chain on them", "value": "3.2s",
             "ehp": "(enemy EHP 2084)"},
        ],
        "chip_verdict": "You out-chain them 3.2s vs 1.1s - force fights.",
        "chip_box": {"w": 300.0, "h": 90.0, "visible": True},
        "visibility": "visible",
        "route_url": ROUTE_URL,
        "route_status": 200,
        "route": copy.deepcopy(ROUTE_BODY),
    }
    ev.update(over)
    return ev


def test_pass_on_a_rendered_chip_tied_to_the_route():
    res = g.grade(_bundle())
    assert res["verdict"] == "PASS", res
    assert res["state"] == "RENDERED"
    assert res["checks"]["route_tie"] is True
    assert (res["checks"]["ally_ehp"], res["checks"]["enemy_ehp"]) == (2500, 2084)


@pytest.mark.parametrize("over", [{"route_url": None, "route": None}, {"route": None},
                                  {"route": {"ok": False}}])
def test_pass_needs_the_route_tie(over):
    assert g.grade(_bundle(**over))["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("over", [
    {"route": dict(ROUTE_BODY, ally_avg_cc_blended_ehp=2600.0)},
    {"route": dict(ROUTE_BODY, enemy_total_cc_seconds=1.4)},
    {"route": dict(ROUTE_BODY, tier="warn")},
])
def test_rendered_numbers_off_the_body_are_inconclusive(over):
    res = g.grade(_bundle(**over))
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["checks"]["route_tie"] is False


@pytest.mark.parametrize("over", [
    {"href": "http://127.0.0.1:8888/"},
    {"href": "https://127.0.0.1:9999/"},
    {"href": "file:///tmp/index.html"},
    {"ui_mock": "1"},
    {"lcu": None, "state_error": "HTTP 500"},
])
def test_provenance_misses_are_inconclusive(over):
    res = g.grade(_bundle(**over))
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["provenance"]


def test_blind_select_is_never_a_fail():
    lcu = {"phase": "ChampSelect", "queue_id": 2400, "ally_ids": [89], "enemy_ids": []}
    res = g.grade(_bundle(lcu=lcu, chip_hidden=True, chip_box={"w": 0, "h": 0,
                                                              "visible": False}))
    assert (res["verdict"], res["state"]) == ("INCONCLUSIVE", "BLIND")


@pytest.mark.parametrize("phase", ["InProgress", "Lobby", None])
def test_outside_champ_select_is_inconclusive(phase):
    lcu = dict(_bundle()["lcu"], phase=phase)
    res = g.grade(_bundle(lcu=lcu))
    assert (res["verdict"], res["state"]) == ("INCONCLUSIVE", "NOT_IN_CHAMP_SELECT")


def test_chip_missing_from_the_dom_fails():
    res = g.grade(_bundle(chip_present=False))
    assert (res["verdict"], res["state"]) == ("FAIL", "CHIP_MISSING")


def test_static_default_tier_alone_is_malformed():
    # index.html ships data-cc-tier="warn": a "shown" chip with no rendered content
    res = g.grade(_bundle(chip_tier_attr="warn", chip_tier_label=None, chip_rows=[],
                          chip_verdict=None))
    assert (res["verdict"], res["state"]) == ("FAIL", "MALFORMED")


def test_missing_ehp_caption_is_malformed():
    rows = copy.deepcopy(_bundle()["chip_rows"])
    rows[0]["ehp"] = None
    res = g.grade(_bundle(chip_rows=rows))
    assert (res["verdict"], res["state"]) == ("FAIL", "MALFORMED")


def test_collapsed_drawer_is_inconclusive():
    res = g.grade(_bundle(chip_box={"w": 0, "h": 0, "visible": False},
                          ta_body_hidden=True))
    assert (res["verdict"], res["state"]) == ("INCONCLUSIVE", "COLLAPSED")


def test_populated_chip_with_no_box_and_open_drawer_fails():
    res = g.grade(_bundle(chip_box={"w": 0, "h": 0, "visible": False},
                          ta_body_hidden=False))
    assert res["verdict"] == "FAIL"


def test_hidden_attribute_with_a_box_is_graded_as_shown():
    res = g.grade(_bundle(chip_hidden=True))
    assert res["verdict"] == "PASS"
    assert res["notes"]


_HIDDEN = {"chip_hidden": True, "chip_box": {"w": 0, "h": 0, "visible": False}}


@pytest.mark.parametrize("age", [2.0, 400.0, None])
def test_hidden_chip_outside_the_reload_window_is_inconclusive(age):
    res = g.grade(_bundle(page_age_s=age, **_HIDDEN))
    assert (res["verdict"], res["state"]) == ("INCONCLUSIVE", "HIDDEN")


@pytest.mark.parametrize("over", [
    {"route_url": None},
    {"names": {"ally": ["Leona"], "enemy": ["Morgana"]}},
    {"visibility": "hidden"},
    {"route_status": 500},
    {"route": {"ok": False, "reason": "no_champions"}},
])
def test_hidden_chip_needs_every_precondition_before_a_fail(over):
    assert g.grade(_bundle(**_HIDDEN, **over))["verdict"] == "INCONCLUSIVE"


def test_hidden_chip_on_a_fresh_page_with_an_ok_body_fails():
    res = g.grade(_bundle(**_HIDDEN))
    assert (res["verdict"], res["state"]) == ("FAIL", "HIDDEN")


def test_roster_tie_uses_names_and_mode():
    rn = g.route_names(ROUTE_URL)
    assert rn == {"ally": ["Jinx", "Leona"], "enemy": ["Morgana"], "mode": "SR"}
    names = {"ally": ["Leona", "Jinx"], "enemy": ["Morgana"]}
    assert g.roster_tie(rn, names, 420) is True
    assert g.roster_tie(rn, names, 2400) is False
    assert g.roster_tie(g.route_names(ROUTE_URL.replace("cc-blended-ehp-threat",
                                                        "cc-conditional-pressure")),
                        names, 420) is None


def test_js_round_is_half_up():
    assert [g.js_round(x) for x in (2083.5, 2084.5, 2500.4, -0.5)] == [2084, 2085, 2500, 0]


def test_grade_rejects_a_non_object():
    with pytest.raises(g.InputError):
        g.grade([])


# --- source pins: the traps the grader encodes must still exist -------------------

def test_index_html_nesting_and_static_default():
    html = INDEX_HTML.read_text(encoding="utf-8")
    view = html.index('id="view-champ-select"')
    ta = html.index('id="csv-team-analysis"')
    body = html.index('id="csv-ta-body"')
    chip = html.index(f'id="{g.CHIP_ID}"')
    assert view < ta < body < chip
    tag = html[html.rindex("<div", 0, chip):html.index(">", chip)]
    assert 'data-cc-tier="warn"' in tag
    assert "hidden" in tag
    for elem_id in ("view-champ-select", "csv-team-analysis", "csv-ta-body", g.CHIP_ID):
        assert f'$("{elem_id}")' in g.SNIPPET, elem_id


def test_renderer_labels_classes_and_route():
    src = RENDERER.read_text(encoding="utf-8")
    for s in (g.ENEMY_ROW_LABEL, g.ALLY_ROW_LABEL, "blockEl.dataset.ccTier = tier;",
              "(your EHP ${allyAvg})", "(enemy EHP ${enemyAvg})",
              '"/api/cc-blended-ehp-threat?"'):
        assert s in src, s
    for cls in ("cc-blended-ehp-threat-row", "cc-blended-ehp-threat-row-label",
                "cc-blended-ehp-threat-row-value", "cc-blended-ehp-threat-row-cc",
                "cc-blended-ehp-threat-tier", "cc-blended-ehp-threat-verdict"):
        assert f'class="{cls}"' in src, cls
        assert f'".{cls}"' in g.SNIPPET, cls
    assert '"/api/cc-blended-ehp-threat?"' in g.SNIPPET


def test_route_keys_the_grader_reads():
    src = ROUTE.read_text(encoding="utf-8")
    for key in ("ally_avg_cc_blended_ehp", "enemy_avg_cc_blended_ehp",
                "ally_total_cc_seconds", "enemy_total_cc_seconds", '"tier"'):
        assert key in src, key


def test_champ_select_gate_mode_map_and_drawer_default():
    src = CHAMP_SELECT.read_text(encoding="utf-8")
    gate = src[src.index("function _csvRenderCcBlendedEhpThreat"):]
    gate = gate[:gate.index("\n}\n")]
    assert "cs.their_team" in gate
    assert "block.hidden = true;" in gate
    assert 'if (q === 2400) mode = "KIWI";' in gate
    assert 'q === 1700 || q === 1710 || q === 1750) mode = "ARENA";' in gate
    assert 'q === 420 || q === 400 || q === 430 || q === 700) mode = "SR";' in gate
    assert 'let mode = "ARAM";' in gate
    assert [g.mode_for_queue(q) for q in (2400, 1750, 420, 400, 450, None, 9999)] == [
        "KIWI", "ARENA", "SR", "SR", "ARAM", "ARAM", "ARAM"]
    assert "if (body) body.hidden = !open;" in src


def test_state_payload_still_carries_no_cc_blended_field():
    # the G3-11 premise for the in-game half: /api/state serves no cc_blended value
    for rel in ("dashboard/_state_builder.py", "dashboard/routes_state.py"):
        assert "cc_blended" not in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_snippet_parses_as_javascript(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    p = tmp_path / "snippet.mjs"
    p.write_text("export const f = " + g.SNIPPET + ";\n", encoding="utf-8")
    r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True,
                       timeout=60, check=False)
    assert r.returncode == 0, r.stderr


# --- the real renderer, under node, feeds the grader ------------------------------

NODE_HARNESS = r"""
import { renderCcBlendedEhpThreat } from './ccb.mjs';
const payload = JSON.parse(process.argv[2]);
const el = { id: 'csv-sugg-cc-blended-ehp-threat', hidden: true,
             dataset: { ccTier: 'warn' }, innerHTML: '' };
const out = {};
renderCcBlendedEhpThreat(el, payload);
out.first = { hidden: el.hidden, tier: el.dataset.ccTier, html: el.innerHTML };
el.hidden = true;               // the champ_select.js gate hides it directly
renderCcBlendedEhpThreat(el, payload);
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
    (tmp_path / "ccb.mjs").write_text(src.replace(imp, "const CHAMPS = {};"),
                                      encoding="utf-8")
    (tmp_path / "run.mjs").write_text(NODE_HARNESS, encoding="utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), json.dumps(payload)],
                       capture_output=True, text=True, timeout=60, cwd=tmp_path, check=False)
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
        if cls == "cc-blended-ehp-threat-row":
            self.rows.append({"label": None, "value": None, "ehp": None})

    def handle_endtag(self, tag):
        self.stack.pop()

    def handle_data(self, data):
        cls = self.stack[-1] if self.stack else ""
        if cls == "cc-blended-ehp-threat-tier":
            self.tier_label = data
        elif cls == "cc-blended-ehp-threat-verdict":
            self.verdict = data
        elif cls.startswith("cc-blended-ehp-threat-row-"):
            key = {"label": "label", "value": "value", "cc": "ehp"}[cls.rsplit("-", 1)[1]]
            self.rows[-1][key] = data


@pytest.mark.parametrize("payload", [
    ROUTE_BODY,
    dict(ROUTE_BODY, tier="bad", ally_total_cc_seconds=0.0, enemy_total_cc_seconds=2.25,
         ally_avg_cc_blended_ehp=1999.5),
    {"ok": True, "tier": "warn", "ally_avg_cc_blended_ehp": 3000.0,
     "enemy_avg_cc_blended_ehp": 3000.0, "ally_total_cc_seconds": 0.0,
     "enemy_total_cc_seconds": 0.0, "ratio": 1.0},
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


def test_stale_signature_trap_still_exists(tmp_path):
    # If this fails, the renderer now clears its signature on an external hide: the
    # page-age window in grade() can then be relaxed (and this test with it).
    out = _node_render(tmp_path, ROUTE_BODY)
    assert out["first"]["hidden"] is False
    assert out["after_gate_hide"]["hidden"] is True


# --- CLI ----------------------------------------------------------------------------

def _cli(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True,
                          text=True, timeout=60, cwd=ROOT, check=False)


def test_cli_exit_codes(tmp_path):
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_bundle()), encoding="utf-8")
    blind = tmp_path / "blind.json"
    blind.write_text(json.dumps(_bundle(lcu={"phase": "ChampSelect", "queue_id": 2400,
                                             "ally_ids": [89], "enemy_ids": []})),
                     encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_bundle(chip_present=False)), encoding="utf-8")
    junk = tmp_path / "junk.json"
    junk.write_text("{not json", encoding="utf-8")
    assert _cli("grade", "--evidence", str(ok)).returncode == 0
    assert _cli("grade", "--evidence", str(bad)).returncode == 1
    assert _cli("grade", "--evidence", str(blind)).returncode == 3
    assert _cli("grade", "--evidence", str(junk)).returncode == 2
    r = _cli("snippet")
    assert r.returncode == 0
    assert g.CHIP_ID in r.stdout
