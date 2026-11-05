"""Tests for tools/gated_g232_layout_diff.py (G2-32 PREP, s144 lane gated c70).

Every layout here is hand-built; the tool reads one JSON state file and the widget
registry. These tests pin its classes, its verdicts, its mirror of the shell's
sanitizer and the source facts the doc row cites.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools import gated_g232_layout_diff as g232

ROOT = Path(__file__).resolve().parent.parent
LAYOUT_JS = ROOT / "web" / "js" / "lib" / "overlay_layout.js"

REG = {"w-build": "league", "w-call": "league", "w-tft-hud": "tft", "w-launcher": "*"}


def _state(layout: dict) -> dict:
    return {"x": 1, "overlay": {"panelSet": "build", "widgetLayout": layout}}


# ---- registry ---------------------------------------------------------------

def test_registry_reads_the_live_source():
    reg = g232.registry(LAYOUT_JS.read_text(encoding="utf-8"))
    assert reg["w-build"] == "league"
    assert reg["w-tft-hud"] == "tft"
    assert reg["w-launcher"] == "*"
    # The doc-comment template entry is not a widget.
    assert not any("." in k for k in reg)
    assert len(reg) >= 10


def test_registry_scopes_from_text():
    js = ('const WIDGETS = [\n  { id: "w-a", sel: "#a", x: 1, y: 2 },\n'
          '  { id: "w-b", sel: "#b", x: 1, y: 2, game: "tft" },\n];\n'
          '// { id: "w-...", sel, x, y }\n')
    assert g232.registry(js) == {"w-a": "league", "w-b": "tft"}


# ---- product name / default path --------------------------------------------

def test_product_name_from_package_and_fallback():
    assert g232.product_name('{"name": "x", "productName": "Some Shell"}') == "Some Shell"
    assert g232.product_name('{"name": "x"}') == g232.FALLBACK_PRODUCT
    assert g232.product_name("not json") == g232.FALLBACK_PRODUCT
    assert g232.product_name(None) == g232.FALLBACK_PRODUCT


def test_live_package_product_name_matches_fallback():
    pkg = (ROOT / "rc-shell" / "package.json").read_text(encoding="utf-8")
    assert g232.product_name(pkg) == json.loads(pkg)["productName"] == g232.FALLBACK_PRODUCT


def test_default_state_path_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = g232.default_state_path()
    assert p is not None and p.name == "rc-shell-state.json" and p.parent.parent == tmp_path
    monkeypatch.delenv("APPDATA")
    assert g232.default_state_path() is None


# ---- sanitizer mirror -------------------------------------------------------

def test_layout_from_state_mirrors_sanitizer():
    st = _state({"w-build": {"x": 70.6, "y": 470.2, "hidden": False, "scale": 0.9, "junk": 1},
                 "w-call": "bad", "w-lead": {"x": True, "y": "3"}})
    assert g232.layout_from_state(st) == {"w-build": {"x": 71, "y": 470, "hidden": False,
                                                      "scale": 0.9}, "w-lead": {}}
    assert g232.layout_from_state([]) == {}
    assert g232.layout_from_state({"overlay": []}) == {}
    assert g232.layout_from_state({"overlay": {"widgetLayout": None}}) == {}


# ---- classify ---------------------------------------------------------------

@pytest.mark.parametrize("before,after,tags", [
    ({"x": 1, "y": 2}, {"x": 1, "y": 2}, ["UNMOVED"]),
    ({"x": 1, "y": 2}, {"x": 5, "y": 2}, ["MOVED"]),
    ({"x": 1, "y": 2}, {"x": 1, "y": 2, "hidden": True}, ["HIDDEN_CHANGED"]),
    ({"x": 1, "y": 2, "scale": 1}, {"x": 1, "y": 2, "scale": 0.8}, ["SCALE_CHANGED"]),
    (None, {"x": 3, "y": 4}, ["NEW_ENTRY", "MOVED"]),
    (None, {"hidden": True}, ["NEW_ENTRY"]),
    (None, None, ["NOT_STORED"]),
    ({"x": 1, "y": 2}, None, ["NOT_STORED", "ENTRY_DROPPED"]),
])
def test_classify(before, after, tags):
    assert g232.classify(before, after) == tags


# ---- clamp ------------------------------------------------------------------

def test_clamp_lower_bound_always_checked():
    assert g232.clamp_problem({"x": -1, "y": 5}, None, None) == "below 0"
    assert g232.clamp_problem({"x": 0, "y": 0}, None, None) is None
    assert g232.clamp_problem({"hidden": True}, None, None) is None


def test_clamp_upper_bound_only_with_dims():
    e = {"x": 1873, "y": 10}
    assert g232.clamp_problem(e, None, None) is None
    assert g232.clamp_problem(e, 1920, 1080) == "past 1920x1080 minus 48"
    assert g232.clamp_problem({"x": 1872, "y": 1032}, 1920, 1080) is None


def test_min_visible_matches_source():
    js = LAYOUT_JS.read_text(encoding="utf-8")
    m = re.search(r"const MIN_VISIBLE = (\d+);", js)
    assert m and int(m.group(1)) == g232.MIN_VISIBLE


# ---- diff verdicts ----------------------------------------------------------

def test_diff_persisted():
    b = {"w-build": {"x": 70, "y": 470}, "w-call": {"x": 180, "y": 130}}
    a = {"w-build": {"x": 300, "y": 400}, "w-call": {"x": 180, "y": 130}, "w-spike": {"x": 1}}
    res = g232.diff(b, a, REG, "league")
    assert res["verdict"] == "PERSISTED" and res["moved"] == ["w-build"]
    row = next(r for r in res["rows"] if r["id"] == "w-build")
    assert (row["dx"], row["dy"], row["after"]) == (230, -70, [300, 400])
    assert res["stale_ids"] == ["w-spike"]
    assert {r["id"] for r in res["rows"]} == {"w-build", "w-call", "w-launcher"}
    assert res["upper_bound_checked"] is False


def test_diff_no_evidence_and_scope():
    lay = {"w-build": {"x": 70, "y": 470}}
    res = g232.diff(lay, dict(lay), REG, "league")
    assert res["verdict"] == "NO_EVIDENCE" and res["moved"] == []
    tft = g232.diff({}, {"w-tft-hud": {"x": 5, "y": 5}}, REG, "tft")
    assert tft["verdict"] == "PERSISTED" and {r["id"] for r in tft["rows"]} == {"w-tft-hud",
                                                                              "w-launcher"}
    assert len(g232.diff({}, {}, REG, "all")["rows"]) == 4


def test_diff_clamp_breach_wins():
    res = g232.diff({}, {"w-build": {"x": 10, "y": 10}, "w-call": {"x": 1900, "y": 5}},
                    REG, "league", 1920, 1080)
    assert res["verdict"] == "CLAMP_BREACH" and res["breaches"] == ["w-call"]
    assert res["upper_bound_checked"] is True


def test_diff_upper_bound_skips_undragged_but_lower_bound_does_not():
    lay = {"w-build": {"x": 1900, "y": 10}, "w-call": {"x": -2, "y": 10}}
    res = g232.diff(lay, dict(lay), REG, "league", 1920, 1080)
    assert res["breaches"] == ["w-call"] and res["verdict"] == "CLAMP_BREACH"


def test_diff_moved_without_full_coords_has_no_delta():
    res = g232.diff({"w-build": {"x": 70}}, {"w-build": {"x": 90}}, REG, "league")
    row = next(r for r in res["rows"] if r["id"] == "w-build")
    assert row["tags"] == ["MOVED"] and "dx" not in row and row["after"] == [90, None]


# ---- CLI --------------------------------------------------------------------

def _write(p: Path, obj) -> Path:
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_cli_snap_then_diff(tmp_path, capsys):
    st = _write(tmp_path / "state.json", _state({"w-build": {"x": 70, "y": 470}}))
    assert g232.main(["snap", "--state", str(st)]) == 0
    snap = json.loads(capsys.readouterr().out)
    assert snap["widgetLayout"] == {"w-build": {"x": 70, "y": 470}}
    assert {"read_at", "state_mtime"} <= set(snap)
    before = _write(tmp_path / "before.json", snap)
    assert g232.main(["diff", str(before), "--state", str(st)]) == 4
    capsys.readouterr()
    _write(st, _state({"w-build": {"x": 90, "y": 400}}))
    assert g232.main(["diff", str(before), "--state", str(st), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "PERSISTED" and out["moved"] == ["w-build"]
    _write(st, _state({"w-build": {"x": -4, "y": 400}}))
    assert g232.main(["diff", str(before), "--state", str(st)]) == 3
    text = capsys.readouterr().out
    assert "CLAMP_BREACH" in text and "below 0" in text


def test_cli_bad_input(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert g232.main(["snap", "--state", str(missing)]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert g232.main(["snap", "--state", str(bad)]) == 2
    st = _write(tmp_path / "state.json", _state({}))
    assert g232.main(["diff", str(bad), "--state", str(st)]) == 2
    assert g232.main(["diff", str(_write(tmp_path / "b.json", {"x": 1})),
                      "--state", str(st)]) == 2
    assert g232.main(["diff", str(_write(tmp_path / "c.json", {"widgetLayout": {}})),
                      "--state", str(missing)]) == 2


# ---- source facts the doc row cites -------------------------------------------

def test_source_facts_still_hold():
    js = LAYOUT_JS.read_text(encoding="utf-8")
    assert "function _effectiveXY(" in js and "function _clampXY(" in js
    # The drag law lives in _installDrag's begin and _makeHandle's body bind.
    drag = js[js.index("function _installDrag("):js.index("function _makeHandle(")]
    begin = drag[drag.index("const begin = (e) => {"):]
    assert "_effectiveXY(w.id" in begin
    assert '_winOn("pointermove", onMove)' in begin
    assert 'el.setAttribute("data-rc-zone", "")' in begin
    handle = js[js.index("function _makeHandle("):js.index("function _makeHotkeyHint(")]
    # Edge press (target is the widget element itself) is handle-only in ACTIVE.
    assert "if (t === el) return;" in handle
    assert "}, 400);" in js  # _persist debounce
    main_js = (ROOT / "rc-shell" / "src" / "main.js").read_text(encoding="utf-8")
    assert '"rc-shell:overlay-layout:set"' in main_js
    assert '"rc-shell-state.json"' in main_js
