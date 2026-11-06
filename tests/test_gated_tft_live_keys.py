"""tools/gated_tft_live_keys.py - the RM-292 (c) read-back (s144 lane gated cycle 4).

The tool is read-only plumbing for a live TFT drain; nothing here ticks a row.
Source pins first (the seed / live-write discriminator rests on them), then the
census classifier, the live-file snapshots and the verdict. All data is
synthetic: unit names are placeholders, no Riot id appears anywhere.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from tools import gated_tft_live_keys as g

ROOT = Path(__file__).resolve().parent.parent
T0 = 1_800_000_000.0


def _live(path: Path, mtime: float, **over) -> Path:
    data = {"mode": "tft_live", "stage_round": "3-2", "level": 6, "hp": 70,
            "board_units": ["UnitA"], "bench_units": ["UnitB", "empty", ""],
            "shop_units": ["UnitC", "unknown", "empty"], "traits_active": [],
            "augments": [], "last_round_result": None, "augment_select": False,
            "comp": "", "build": "", "buy": "", "sell": "", "keep": "",
            "augment_play": "", "loss": "", "unit_placement": "", "unit_swap": "swap x",
            "degraded": False, "degraded_message": ""}
    data.update(over)
    for k in [k for k, v in over.items() if v is _DROP]:
        del data[k]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


_DROP = object()


# -- source pins ---------------------------------------------------------------

def test_head_writer_literal_carries_the_three_keys_and_the_discriminator():
    keys = g.writer_keys((ROOT / g.WRITER_REL).read_text(encoding="utf-8"))
    assert set(g.KEYS) <= keys
    assert {"degraded", "degraded_message", "last_round_result", "mode"} <= keys


def test_degraded_republish_sets_degraded_true():
    src = (ROOT / g.WRITER_REL).read_text(encoding="utf-8")
    assert '"degraded":True' in src and 'out["degraded"]=False' in src


def _dicts_with(path: Path, key: str) -> list[set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            ks = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            if key in ks:
                out.append(ks)
    return out


@pytest.mark.parametrize("rel", ["coaches/tft_coach.py", "core/feature_policy.py"])
def test_seeds_never_carry_the_degraded_key(rel):
    seeds = _dicts_with(ROOT / rel, "bench_units")
    assert seeds, f"{rel}: the tft_live seed literal moved"
    for ks in seeds:
        assert "degraded" not in ks and set(g.KEYS) <= ks


def test_policy_placeholder_classifies_as_seed():
    from core.feature_policy import _TFT_LIVE_DISABLED_PAYLOAD
    assert g.classify(dict(_TFT_LIVE_DISABLED_PAYLOAD)) == "seed"


# -- writer_keys / classify ----------------------------------------------------

def test_writer_keys_reads_dict_and_subscript_stores_only_in_write():
    src = (
        "class A:\n"
        "    def _write(self, vs, f, cs):\n"
        "        out = {'a': 1, 'b': 2}\n"
        "        out['c'] = 3\n"
        "        other = {'z': 1}\n"
        "    def _other(self):\n"
        "        out = {'q': 1}\n"
        "def _write(path, data):\n"
        "    out = {'module': 1}\n"
    )
    assert g.writer_keys(src) == {"a", "b", "c"}
    assert g.writer_keys("x = 1\n") == set()


@pytest.mark.parametrize("data,kind", [
    ({"mode": "tft_live", "bench_units": []}, "seed"),
    ({"degraded": False}, "live_write"),
    ({"degraded": True}, "live_degraded"),
    ({"degraded": "yes"}, "live_write"),
    ([1, 2], "unreadable"),
    (None, "unreadable"),
])
def test_classify(data, kind):
    assert g.classify(data) == kind


# -- snapshot / collect --------------------------------------------------------

def test_snapshot_absent_and_unreadable(tmp_path):
    assert g.snapshot(tmp_path / "nope.json", set())["kind"] == "absent"
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert g.snapshot(bad, set())["kind"] == "unreadable"


def test_snapshot_live_write_counts_filled_entries_not_names(tmp_path):
    p = _live(tmp_path / "f.json", T0)
    s = g.snapshot(p, {"degraded", "bench_units"})
    assert s["kind"] == "live_write" and s["mtime"] == T0
    assert s["keys_present"] == dict.fromkeys(g.KEYS, True)
    assert s["filled"] == {"bench_units": 1, "shop_units": 2, "unit_swap": 6}
    assert s["missing_head_keys"] == []
    assert "UnitB" not in json.dumps(s)


def test_snapshot_reports_missing_keys_and_bad_shapes(tmp_path):
    p = _live(tmp_path / "f.json", T0, unit_swap=_DROP, bench_units="x", shop_units=None)
    s = g.snapshot(p, {"unit_swap", "mode"})
    assert s["keys_present"]["unit_swap"] is False
    assert s["filled"] == {"bench_units": None, "shop_units": None, "unit_swap": None}
    assert s["missing_head_keys"] == ["unit_swap"]


def test_collect_dedupes_by_mtime(tmp_path):
    p = _live(tmp_path / "f.json", T0)
    stamps = iter([T0 + 60, T0 + 60, T0 + 120])

    def fake_sleep(_s):
        _live(p, next(stamps))

    snaps = g.collect(p, set(), 4, 15.0, sleep=fake_sleep)
    assert [s["mtime"] for s in snaps] == [T0, T0 + 60, T0 + 120]
    assert len(g.collect(p, set(), 3, 0.0, sleep=lambda _s: None)) == 1
    assert len(g.collect(p, set(), 0, 0.0, sleep=lambda _s: None)) == 1


# -- census ----------------------------------------------------------------------

def _tree(tmp_path: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return list(files)


def test_census_classes_python_roles(tmp_path):
    files = _tree(tmp_path, {
        "a/get.py": "def f(d):\n    return d.get('bench_units')\n",
        "a/sub.py": "def f(d):\n    return d['shop_units']\n",
        "a/store.py": "def f(d):\n    d['unit_swap'] = 1\n",
        "a/seed.py": "S = {'bench_units': [], 'shop_units': []}\n",
        "a/seq.py": "F = ('bench_units', 'x')\n",
        "a/doc.py": "'''bench_units'''\nX = 1\n",
        "a/cmp.py": "def f(k):\n    return k == 'unit_swap'\n",
        "a/pop.py": "def f(d):\n    d.pop('unit_swap', None)\n",
        "a/broken.py": "def f(:\n    'bench_units'\n",
    })
    cen = g.census(tmp_path, files)
    roles = {(h["file"], h["role"]) for h in cen["hits"]}
    assert ("a/get.py", "read") in roles and ("a/sub.py", "read") in roles
    assert ("a/store.py", "write") in roles and ("a/seed.py", "dict_key") in roles
    assert ("a/seq.py", "sequence") in roles and ("a/cmp.py", "other") in roles
    assert ("a/pop.py", "read") in roles and ("a/broken.py", "other") in roles
    assert not any(h["file"] == "a/doc.py" for h in cen["hits"])
    assert {h["file"] for h in cen["readers"]} == {
        "a/get.py", "a/sub.py", "a/cmp.py", "a/pop.py", "a/broken.py"}
    assert [h["file"] for h in cen["sequence"]] == ["a/seq.py"]


def test_census_js_mentions_are_readers_and_writer_upstream_are_not(tmp_path):
    files = _tree(tmp_path, {
        "web/js/p.js": "const s = p.shop_units;\nconst b = p['bench_units_x'];\n",
        g.WRITER_REL: "def f(vs):\n    return vs.get('bench_units')\n",
        "tft/tft_vision_reader.py": "def f(d):\n    return d.get('shop_units')\n",
        "web/x.html": '<div data-k="unit_swap"></div>\n',
        "web/y.tsx": "\nexport const s = (p) => p.bench_units;\n",
    })
    cen = g.census(tmp_path, files)
    assert {(h["file"], h["line"]) for h in cen["readers"]} == {
        ("web/js/p.js", 1), ("web/x.html", 1), ("web/y.tsx", 2)}
    assert cen["writer_hits"] == 1
    assert any(h["scope"] == "upstream" for h in cen["hits"])


@pytest.mark.parametrize("rel,is_test", [
    ("tests/test_x.py", True), ("agents/daemon_slayer/tests/helper.py", True),
    ("tools/test_thing.py", True), ("web/js/panels/a.test.mjs", True),
    ("conftest.py", True), ("tools/x_test.py", True),
    ("tft/tft_live_analysis.py", False), ("web/js/main.js", False),
])
def test_is_test_path(rel, is_test):
    assert g.is_test_path(rel) is is_test


@pytest.mark.parametrize("rel,scanned", [
    ("a/b.py", True), ("a/b.js", True), ("a/b.mjs", True), ("a/b.cjs", True),
    ("a/b.ts", True), ("a/b.jsx", True), ("a/b.tsx", True), ("a/b.vue", True),
    ("a/b.html", True), ("a/b.md", False), ("a/b.json", False), ("docs/x.py", False),
    ("tests/x.py", False), ("web/js/a.test.mjs", False),
])
def test_is_scanned(rel, scanned):
    assert g.is_scanned(rel) is scanned


def test_tracked_sources_real_tree():
    rels = g.tracked_sources(ROOT)
    assert g.WRITER_REL in rels and "web/js/main.js" in rels
    assert not any(r.startswith(("tests/", "docs/")) for r in rels)
    assert not any(r.endswith(".md") for r in rels)


def test_census_real_tree_positive_control():
    cen = g.census(ROOT)
    assert cen["files_scanned"] > 100 and cen["writer_hits"] >= 3
    seeds = {h["file"] for h in cen["hits"] if h["role"] == "dict_key" and h["scope"] == "elsewhere"}
    assert {"coaches/tft_coach.py", "core/feature_policy.py"} <= seeds


# -- verdict ---------------------------------------------------------------------

CLEAN = {"readers": [], "hits": [], "sequence": [], "writer_hits": 0, "files_scanned": 1}


def _snaps(tmp_path: Path, n: int, start: float = T0, same_round: bool = False,
           **over) -> list[dict]:
    out = []
    for i in range(n):
        sr = "3-2" if same_round else f"3-{i + 1}"
        p = _live(tmp_path / f"s{i}.json", start + 60 * i, **{"stage_round": sr, **over})
        out.append(g.snapshot(p, set(g.KEYS) | {"degraded"}))
    return out


def test_verdict_pass_needs_enough_stage_rounds(tmp_path):
    v, why = g.verdict(_snaps(tmp_path, 3), CLEAN, 3, None)
    assert v == "PASS" and "3 stage rounds" in why
    v, why = g.verdict(_snaps(tmp_path / "b", 2), CLEAN, 3, None)
    assert v == "INCOMPLETE" and "2 of 3" in why


def test_rewrites_inside_one_round_count_once(tmp_path):
    assert g.verdict(_snaps(tmp_path, 3, same_round=True), CLEAN, 3, None)[0] == "INCOMPLETE"
    assert g.verdict(_snaps(tmp_path / "b", 3, stage_round=""), CLEAN, 1, None)[0] == "INCOMPLETE"


def test_augment_select_merges_never_count(tmp_path):
    merged = _snaps(tmp_path, 3, augment_select=True)
    assert all(s["kind"] == "live_write" for s in merged)
    assert g.verdict(merged, CLEAN, 1, None)[0] == "INCOMPLETE"


def test_verdict_fail_on_reader_beats_everything(tmp_path):
    cen = dict(CLEAN, readers=[{"file": "x.py", "line": 3, "key": "shop_units", "role": "read"}])
    v, why = g.verdict(_snaps(tmp_path, 3), cen, 3, None)
    assert v == "FAIL" and "x.py:3" in why


def test_verdict_fail_when_a_live_write_lacks_a_key(tmp_path):
    snaps = _snaps(tmp_path, 3) + _snaps(tmp_path / "b", 1, shop_units=_DROP)
    v, why = g.verdict(snaps, CLEAN, 3, None)
    assert v == "FAIL" and "shop_units" in why


def test_verdict_degraded_never_counts_and_never_fails(tmp_path):
    # _publish_degraded copies whatever the file held: over an absent or
    # corrupt file (_load -> {"mode": "tft_live"}) HEAD itself writes a
    # degraded state without the three keys, so that is not a FAIL.
    deg = _snaps(tmp_path, 3, degraded=True)
    assert g.verdict(deg, CLEAN, 1, None)[0] == "INCOMPLETE"
    assert g.verdict(_snaps(tmp_path / "b", 1, degraded=True, unit_swap=_DROP),
                     CLEAN, 1, None)[0] == "INCOMPLETE"


def test_verdict_since_and_seed_and_head_gap(tmp_path):
    old = _snaps(tmp_path, 3)
    assert g.verdict(old, CLEAN, 3, T0 + 61)[0] == "INCOMPLETE"
    assert g.verdict(old, CLEAN, 3, T0)[0] == "PASS"
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"mode": "tft_live", "bench_units": []}), encoding="utf-8")
    v, why = g.verdict([g.snapshot(seed, set())], CLEAN, 1, None)
    assert v == "INCOMPLETE" and "no live write" in why
    gap = [g.snapshot(_live(tmp_path / "g.json", T0), {"degraded", "brand_new_key"})]
    assert g.verdict(gap, CLEAN, 1, None)[0] == "INCOMPLETE"


# -- main ------------------------------------------------------------------------

def test_main_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(g, "census", lambda root, files=None: dict(CLEAN))
    _live(tmp_path / "data" / "tft_live_data.json", T0)
    assert g.main(["--data-root", str(tmp_path), "--json"]) == 1
    rep = json.loads(capsys.readouterr().out)
    assert rep["verdict"] == "INCOMPLETE" and rep["live_writes"] == 1
    assert rep["degraded_states"] == 0
    assert rep["populated_writes"] == {"bench_units": 1, "shop_units": 1, "unit_swap": 1}
    deg = tmp_path / "deg"
    _live(deg / "data" / "tft_live_data.json", T0, degraded=True)
    assert g.main(["--data-root", str(deg), "--json"]) == 1
    rep = json.loads(capsys.readouterr().out)
    assert rep["live_writes"] == 0 and rep["degraded_states"] == 1
    assert rep["populated_writes"] == {"bench_units": 0, "shop_units": 0, "unit_swap": 0}
    assert g.main(["--data-root", str(tmp_path), "--need", "1"]) == 0
    assert capsys.readouterr().out.startswith("RM-292 (c) verdict: PASS")
    assert g.main(["--data-root", str(tmp_path), "--need", "1",
                   "--since", "2030-01-01T00:00"]) == 1
    monkeypatch.setattr(g, "census", lambda root, files=None: dict(
        CLEAN, readers=[{"file": "y.js", "line": 1, "key": "unit_swap", "role": "read",
                         "scope": "elsewhere"}]))
    assert g.main(["--data-root", str(tmp_path)]) == 2
    assert "y.js:1" in capsys.readouterr().out
