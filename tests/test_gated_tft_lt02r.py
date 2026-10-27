"""tools/gated_tft_lt02r.py - the LT-02r read-back (s144 lane gated cycle 5).

Read-only plumbing for the LT-02r drain; nothing here ticks a row. All recorder
data below is synthetic (placeholder unit names, no Riot id anywhere); the two
real-tree tests read only tracked files under data/meta and tft/.
"""
from __future__ import annotations

import ast
import json
import types
from pathlib import Path

import pytest

from tft import tft_data
from tools import gated_tft_lt02r as g

ROOT = Path(__file__).resolve().parent.parent


def _module(**over):
    base = dict(CONSTANTS_SET=18, CONSTANTS_SET_VERIFIED=False,
                TIER_ODDS_VERIFIED_LEVELS=frozenset({4, 5}),
                TIER_ODDS={3: {1: 0.75, 2: 0.25, 3: 0.0, 4: 0.0, 5: 0.0},
                           4: {1: 0.55, 2: 0.30, 3: 0.15, 4: 0.0, 5: 0.0},
                           5: {1: 0.45, 2: 0.33, 3: 0.20, 4: 0.02, 5: 0.0},
                           10: {1: 0.05, 2: 0.10, 3: 0.20, 4: 0.40, 5: 0.25}},
                POOL_SIZES={1: 29, 2: 22, 3: 18, 4: 12, 5: 10}, POOL_SIZES_FROM_SET=14,
                UNITS_PER_COST={1: 13, 2: 13, 3: 13, 4: 12, 5: 8})
    base.update(over)
    return types.SimpleNamespace(**base)


def _match(root: Path, name: str, *, labels=None, board=None, frames=0) -> Path:
    d = root / name
    d.mkdir(parents=True)
    rows = [{"t": 1_800_000_000.0 + i, "kind": "vision", "file": f"frames/vision_{i:04d}_gt{i * 20:04d}.jpg",
             "gt": i * 20} for i in range(1, frames + 1)]
    rows.insert(0, {"t": 1_799_999_999.0, "kind": "dash", "file": "frames/dash_0001.jpg"})
    # Real recorder dirs interleave dash / mon2 frames with the game ones up to
    # the very end, so the last-captured rows here are NOT game frames.
    rows += [{"t": 1_900_000_000.0, "kind": "dash", "file": "frames/dash_9998.jpg"},
             {"t": 1_900_000_001.0, "kind": "mon2", "file": "frames/mon2_9999.jpg"}]
    (d / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n",
                                    encoding="utf-8")
    if labels is not None:
        body = ["# synthetic hand labels; no names", "idx,file,frame_ts,gt,stage,level"]
        body += [f"{i},{f},0,{gt},,{'' if lv is None else lv}" for i, (f, gt, lv) in enumerate(labels, 1)]
        (d / "hud_labels_test.csv").write_text("\n".join(body) + "\n", encoding="utf-8")
    if board is not None:
        (d / "eog_raw.json").write_text(json.dumps(
            {"localPlayer": {"boardPieces": [{"level": 1}] * board}}), encoding="utf-8")
    return d


# -- constants -----------------------------------------------------------------

def test_constants_lists_the_levels_outside_the_pinned_set():
    c = g.constants(_module())
    assert c["unpinned_levels"] == [3, 10]
    assert c["unpinned_rows_pct"] == {3: [75, 25, 0, 0, 0], 10: [5, 10, 20, 40, 25]}
    assert c["pool_sizes_from_set"] == 14 and c["constants_set_verified"] is False


def test_constants_on_the_real_module_match_its_own_tables():
    c = g.constants()
    assert set(c["unpinned_levels"]) == set(tft_data.TIER_ODDS) - set(tft_data.TIER_ODDS_VERIFIED_LEVELS)
    assert c["unpinned_levels"], "LT-02r has nothing left to read: retire this tool with the row"
    for lv, row in c["unpinned_rows_pct"].items():
        assert sum(row) == 100, lv
    assert c["pool_sizes"] == tft_data.POOL_SIZES


# -- --check-read ----------------------------------------------------------------

def test_parse_read_accepts_a_level_and_five_percents():
    assert g.parse_read(" 10 = 5/10/20/40/25 ") == (10, [5, 10, 20, 40, 25])


@pytest.mark.parametrize("spec", ["10", "10=5/10/20/40", "x=1/2/3/4/5", "0=100/0/0/0/0",
                                  "3=101/0/0/0/0", "3=-1/0/0/0/0", "3=a/b/c/d/e"])
def test_parse_read_refuses_malformed_specs(spec):
    with pytest.raises(ValueError):
        g.parse_read(spec)


def test_check_read_equal_differs_and_absent():
    odds = _module().TIER_ODDS
    ok = g.check_read(10, [5, 10, 20, 40, 25], odds)
    assert ok["equal"] and ok["sums_to_100"] and ok["diff"] == {}
    bad = g.check_read(3, [70, 30, 0, 0, 0], odds)
    assert not bad["equal"] and bad["diff"] == {1: -5, 2: 5}
    absent = g.check_read(11, [1, 2, 12, 50, 35], odds)
    assert absent["table"] is None and absent["equal"] is False
    assert g.check_read(3, [75, 25, 0, 0, 1], odds)["sums_to_100"] is False


# -- roster ----------------------------------------------------------------------

def test_roster_counts_planner_units_by_game_data_cost():
    extract = {"units": [{"name": "UnitA", "cost": 1}, {"name": "UnitB", "cost": 1},
                         {"name": "UnitC", "cost": 5}, {"name": "UnitC (Variant)", "cost": 5},
                         {"name": "Bad", "cost": "5"}, "junk"]}
    codes = {"UnitA": 1001, "UnitB": 1002, "UnitC": 1003, "Ghost": 1004}
    r = g.roster(extract, codes, {1: 2, 2: 0, 3: 0, 4: 0, 5: 2})
    assert r["units_per_cost_planner"] == {1: 2, 2: 0, 3: 0, 4: 0, 5: 1}
    assert r["differs_at"] == [5]
    assert r["extract_only_units"] == 1 and r["planner_units_without_cost"] == 1


def test_roster_unavailable_on_unreadable_inputs():
    assert g.roster(None, {}, {}) == {"available": False}
    assert g.roster({"units": []}, None, {}) == {"available": False}


def test_roster_on_the_real_set18_files_has_a_cost_for_every_planner_unit():
    r = g.roster(g._read_json(ROOT / g.EXTRACT_REL), g._read_json(ROOT / g.CODES_REL),
                 tft_data.UNITS_PER_COST)
    assert r["available"]
    assert r["planner_units"] > 0 and r["planner_units_without_cost"] == 0
    assert sum(r["units_per_cost_planner"].values()) == r["planner_units"]


# -- recorder index ----------------------------------------------------------------

def test_scan_match_indexes_labelled_levels_and_early_l1_candidates(tmp_path):
    labels = [("frames/v0.jpg", 20, 1), ("frames/v1.jpg", 40, None), ("frames/v2.jpg", 60, None),
              ("frames/v3.jpg", 100, 2), ("frames/v3b.jpg", 100, None), ("frames/v4.jpg", 140, 3),
              ("frames/v5.jpg", 400, None), ("frames/v6.jpg", 900, 9)]
    m = g.scan_match(_match(tmp_path, "m1", labels=labels, board=9, frames=5), [1, 2, 3, 10, 11])
    assert m["labelled_frames"] == 8
    assert m["labelled_by_level"] == {1: ["frames/v0.jpg"], 2: ["frames/v3.jpg"], 3: ["frames/v4.jpg"]}
    # Unread level box strictly before the first L2 frame; a frame already
    # labelled L1 is a labelled frame, not a candidate.
    assert m["l1_candidates"] == ["frames/v1.jpg", "frames/v2.jpg"]
    assert m["eog_board_units"] == 9 and m["l10_hint"] is False and m["l10_candidates"] == []


def test_scan_match_l10_candidates_are_the_last_game_frames_of_a_ten_unit_board(tmp_path):
    m = g.scan_match(_match(tmp_path, "m2", board=10, frames=12), [10])
    assert m["l10_hint"] is True
    assert len(m["l10_candidates"]) == g.LATE_CANDIDATES
    assert m["l10_candidates"][-1].startswith("frames/vision_0012_")
    assert all(f.startswith("frames/vision_") for f in m["l10_candidates"])
    assert m["l1_candidates"] == []


def test_scan_match_without_labels_or_eog_is_empty_not_an_error(tmp_path):
    m = g.scan_match(_match(tmp_path, "m3"), [1, 10])
    assert m == {"match": "m3", "labelled_frames": 0, "labelled_by_level": {}, "l1_candidates": [],
                 "eog_board_units": None, "l10_hint": False, "l10_candidates": []}


def test_match_dirs_need_a_frames_index(tmp_path):
    _match(tmp_path, "b")
    (tmp_path / "a").mkdir()
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    assert [p.name for p in g.match_dirs(tmp_path)] == ["b"]
    assert g.match_dirs(tmp_path / "absent") == []


def test_level_verdicts():
    ms = [{"labelled_by_level": {2: ["f"]}, "l1_candidates": ["e"], "l10_candidates": []},
          {"labelled_by_level": {}, "l1_candidates": [], "l10_candidates": ["z"]}]
    assert g.level_verdicts([1, 2, 3, 10, 11], ms) == {
        1: "on_disk_candidate", 2: "on_disk_labelled", 3: "needs_game",
        10: "on_disk_candidate", 11: "needs_game"}


# -- CLI -------------------------------------------------------------------------

def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in sorted(root.rglob("*"))}


def test_main_report_is_ascii_json_and_writes_nothing(tmp_path, capsys):
    qa = tmp_path / "qa"
    _match(qa, "m1", labels=[("frames/v1.jpg", 40, None), ("frames/v2.jpg", 100, 2)], board=10, frames=3)
    before = _tree(qa)
    assert g.main(["--qa-root", str(qa), "--json"]) == 0
    out = capsys.readouterr().out
    assert out.isascii()
    rep = json.loads(out)
    assert rep["row"] == "LT-02r" and rep["pool_sizes_verdict"] == "no_client_surface"
    assert [m["match"] for m in rep["matches"]] == ["m1"] and rep["checks"] == []
    assert rep["qa_root"] == "<qa-root>/qa"
    assert str(tmp_path) not in out and ":\\\\" not in out
    assert _tree(qa) == before


def test_display_root_of_the_default_root_is_a_placeholder():
    assert g.display_root(g.default_qa_root()) == "<main>/ops/runtime/tft_qa"


def test_main_check_read_exit_codes(tmp_path, capsys):
    qa = tmp_path / "qa"
    qa.mkdir()
    row10 = "/".join(str(v) for v in g._pct(tft_data.TIER_ODDS[10]))
    assert g.main(["--qa-root", str(qa), "--check-read", f"10={row10}"]) == 0
    assert g.main(["--qa-root", str(qa), "--check-read", "10=0/0/0/0/100"]) == 1
    assert g.main(["--qa-root", str(qa), "--check-read", "10=1/2"]) == 2
    text = capsys.readouterr().out
    assert "CHECK L10" in text and "no_client_surface" in text


def test_default_qa_root_is_under_ops_runtime_tft_qa():
    assert g.default_qa_root().parts[-3:] == ("ops", "runtime", "tft_qa")


def test_tool_source_has_no_write_call():
    tree = ast.parse((ROOT / "tools" / "gated_tft_lt02r.py").read_text(encoding="utf-8"))
    banned = {"write_text", "write_bytes", "unlink", "rename", "replace", "rmdir", "mkdir",
              "touch", "remove", "rmtree"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in banned, node.attr
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            raise AssertionError("bare open() call in a read-only tool")
