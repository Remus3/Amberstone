"""Guards for atlas.html, the public repository map (MAIN 2246 section 6).

History: the page used to carry its dataset as hand-typed JS literals (CATS,
NODES, EDG, DUST and a HUD block) that nothing re-derived. R138 / R195 guarded
their shape and a few anchors, but the content still drifted - measured
2026-10-08, 591 of 926 modules were missing, 14 entries named deleted files
and the HUD commit count was weeks stale. tools/atlas_build.py now generates
every data region of the page from the git index, so these tests pin:

* the build is deterministic - same tree, same bytes, whatever the file order;
* no hand-edited literal remains, every generated region is exactly what the
  generator renders, and the node structure re-derives from the file list;
* the map is fresh - every tracked module is on it and nothing on it is gone
  (fix: ``python tools/atlas_build.py``);
* the order's UX items: no reduced-motion freeze plus a pause control, pulses
  in screen px/s (2); a 14 px font floor (3); full-opacity 18 px+ region
  titles kept under a selection (4); the zoom-performance rules (5); the
  snapshots as files beside the page (7); fleet-kit tokens instead of a
  palette (8); plain drag pans and a zoom cap above 5x (9).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ATLAS = REPO_ROOT / "atlas.html"
BUILDER_PATH = REPO_ROOT / "tools" / "atlas_build.py"
FIXED_STAMP = {"commit": "0000000", "date": "2026-01-01", "commits": 1}


def _load_builder():
    spec = importlib.util.spec_from_file_location("atlas_build_under_test", BUILDER_PATH)
    assert spec and spec.loader, f"cannot load {BUILDER_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ab():
    return _load_builder()


@pytest.fixture(scope="module")
def html() -> str:
    assert ATLAS.is_file(), f"missing {ATLAS}"
    return ATLAS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def model(ab, html) -> dict:
    return ab.parse_data(html)


@pytest.fixture(scope="module")
def app_js(html) -> str:
    """The main (non-data) script block."""
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    apps = [b for b in blocks if "atlas:gen:data" not in b]
    assert len(apps) == 1, f"expected one app script, found {len(apps)}"
    return apps[0]


@pytest.fixture(scope="module")
def page_css(html) -> str:
    """Every <style> block except the inlined @font-face block."""
    blocks = re.findall(r"<style>(.*?)</style>", html, re.S)
    css = [b for b in blocks if "@font-face" not in b]
    assert css, "no page stylesheet found"
    return "\n".join(css)


def _function_body(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    open_at = src.index("{", start)
    depth = 0
    for i in range(open_at, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_at + 1:i]
    raise AssertionError(f"unbalanced body for {name}")


# --------------------------------------------------------------------------
# generated, not authored (item 1)
# --------------------------------------------------------------------------

def test_file_is_pure_ascii() -> None:
    raw = ATLAS.read_bytes()
    offenders = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not offenders[:10], f"non-ascii bytes at {offenders[:10]}"


def test_generator_source_is_pure_ascii() -> None:
    raw = BUILDER_PATH.read_bytes()
    assert all(b < 128 for b in raw), "tools/atlas_build.py carries non-ASCII bytes"


def test_no_hand_edited_literals_remain(html) -> None:
    for name in ("NODES", "DUST", "EDG", "CATS"):
        assert not re.search(rf"\bvar\s+{name}\s*=", html), f"hand-edited {name} literal is back"
    assert "window.ATLAS_SNAPSHOTS" not in html
    assert "window.ATLAS_DATA=" in html


def test_page_equals_generator_render_of_its_embedded_model(ab, html, model) -> None:
    # Every generated region (lede, noscript, summaries, HUD, data) must be
    # byte-identical to what the generator renders from the embedded model,
    # so no region can be edited by hand without this going red.
    assert ab.render_page(html, model) == html


def test_structure_rederives_from_the_embedded_file_list(ab, model) -> None:
    paths = [f[0] for f in model["files"]]
    assert paths == sorted(paths), "file list is not in canonical order"
    node_of = ab.assign_nodes(paths)
    ids = [n["id"] for n in model["nodes"]]
    assert set(ids) == set(node_of.values()), "node set does not re-derive from the files"
    for rel, idx, _desc in model["files"]:
        assert ids[idx] == node_of[rel], f"{rel} hangs off {ids[idx]}, rule says {node_of[rel]}"
    counts = {}
    for rel in paths:
        counts[node_of[rel]] = counts.get(node_of[rel], 0) + 1
    for n in model["nodes"]:
        d = ab._node_dir(n["id"])
        assert n["cat"] == ab.category_of(d), n["id"]
        assert n["files"] == counts[n["id"]], n["id"]
        assert n["w"] == ab._weight(counts[n["id"]]), n["id"]
    assert [c["key"] for c in model["categories"]] == [c[0] for c in ab.CATEGORIES]
    n_nodes = len(model["nodes"])
    for a, b, w in model["edges"]:
        assert 0 <= a < b < n_nodes and w >= 0, (a, b, w)


def test_build_is_deterministic_on_the_real_tree(ab) -> None:
    first = ab.build_model(REPO_ROOT, stamp=FIXED_STAMP, min_modules=ab.MIN_REPO_MODULES)
    second = ab.build_model(REPO_ROOT, stamp=FIXED_STAMP, min_modules=ab.MIN_REPO_MODULES)
    assert ab.render_data(first) == ab.render_data(second)
    assert len(first["files"]) >= ab.MIN_REPO_MODULES


def _git_available() -> bool:
    return shutil.which("git") is not None


def _make_repo(root: Path, files: dict[str, str], order: list[str]) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel in order:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(files[rel], encoding="utf-8", newline="\n")
    subprocess.run(["git", "-C", str(root), "-c", "core.autocrlf=false", "add", "-A"], check=True)


# Built at runtime so this file carries no literal drive path.
_FAKE_DRIVE = "Z" + ":" + chr(92) + "Users" + chr(92) + "someone"

SYNTH = {
    "pkg/__init__.py": '"""Synthetic package for the atlas determinism test."""\n',
    "pkg/alpha.py": '"""Alpha module. Second sentence is dropped."""\nfrom pkg import beta\n',
    "pkg/beta.py": "# arch: beta role text | section=core | frozen=no\nimport os\n",
    "tools/runner.py": ('r"""Runner at ' + _FAKE_DRIVE + ' and 192.0.2.10, loopback 127.0.0.1."""\n'
                        "import helper\nimport pkg.alpha\n"),
    "tools/helper.py": '"""Helper \u2014 with an em dash."""\n',
    "web/js/main.js": "// Entry point.\nimport { n } from './lib/n.js';\n",
    "web/js/lib/n.js": "/** @file Tiny lib. */\nexport const n = 1;\n",
    "tests/test_alpha.py": "def test_x():\n    assert True\n",
    "web/js/main.test.js": "// excluded\n",
    "README.md": "not code\n",
}
for _i in range(26):
    SYNTH[f"big/routes_{_i:02d}.py" if _i < 6 else f"big/misc{_i:02d}.py"] = f'"""Module {_i}."""\n'


@pytest.mark.skipif(not _git_available(), reason="git is not on PATH")
def test_build_is_deterministic_and_order_free_on_a_synthetic_tree(ab) -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_a_") as a, tempfile.TemporaryDirectory(prefix="atlas_b_") as b:
        keys = sorted(SYNTH)
        _make_repo(Path(a), SYNTH, keys)
        _make_repo(Path(b), SYNTH, list(reversed(keys)))
        ma1 = ab.build_model(Path(a), stamp=FIXED_STAMP)
        ma2 = ab.build_model(Path(a), stamp=FIXED_STAMP)
        mb = ab.build_model(Path(b), stamp=FIXED_STAMP)
    assert ab.render_data(ma1) == ab.render_data(ma2) == ab.render_data(mb)
    paths = [f[0] for f in ma1["files"]]
    assert "tests/test_alpha.py" not in paths and "web/js/main.test.js" not in paths
    assert "README.md" not in paths
    ids = {n["id"] for n in ma1["nodes"]}
    assert "big/routes_*" in ids and "big/" in ids, ids
    desc = {f[0]: f[2] for f in ma1["files"]}
    assert desc["pkg/alpha.py"] == "Alpha module."
    assert desc["pkg/beta.py"] == "beta role text"
    assert desc["web/js/lib/n.js"] == "Tiny lib."
    assert "<path>" in desc["tools/runner.py"] and "<ip>" in desc["tools/runner.py"]
    assert "127.0.0.1" in desc["tools/runner.py"] and "Users" not in desc["tools/runner.py"]
    assert desc["tools/helper.py"] == "Helper - with an em dash."
    idx = {n["id"]: i for i, n in enumerate(ma1["nodes"])}
    pairs = {(e[0], e[1]) for e in ma1["edges"] if e[2] > 0}
    assert (min(idx["web/js/"], idx["web/js/lib/"]), max(idx["web/js/"], idx["web/js/lib/"])) in pairs
    assert (min(idx["tools/"], idx["pkg/"]), max(idx["tools/"], idx["pkg/"])) in pairs
    assert all(p != q for p, q in pairs), "a node links to itself"


# --------------------------------------------------------------------------
# freshness: the map covers the tree (adjudicator condition)
# --------------------------------------------------------------------------

def test_every_tracked_module_is_on_the_map(ab, model) -> None:
    tracked = ab.collect_modules(REPO_ROOT, min_modules=ab.MIN_REPO_MODULES)
    mapped = {f[0] for f in model["files"]}
    missing = sorted(set(tracked) - mapped)
    assert not missing, (f"{len(missing)} tracked modules are not on the map, e.g. "
                         f"{missing[:5]} - run: python tools/atlas_build.py")


def test_nothing_on_the_map_is_gone(ab, model) -> None:
    tracked = set(ab.collect_modules(REPO_ROOT, min_modules=ab.MIN_REPO_MODULES))
    gone = sorted({f[0] for f in model["files"]} - tracked)
    assert not gone, (f"{len(gone)} mapped files are no longer tracked modules, e.g. "
                      f"{gone[:5]} - run: python tools/atlas_build.py")


# --------------------------------------------------------------------------
# HUD
# --------------------------------------------------------------------------

def _repo_engine_version() -> str:
    src = (REPO_ROOT / "agents" / "daemon_slayer" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^ENGINE_VERSION\s*=\s*"([^"]+)"', src, re.M)
    assert m, "could not read ENGINE_VERSION"
    return m.group(1)


def _repo_patch() -> str:
    return (REPO_ROOT / "data" / "daemon_slayer" / "current.txt").read_text(encoding="utf-8").strip()


def test_hud_counts_match_the_data(html, model) -> None:
    m = re.search(r"<div[^>]*>nodes:\s*(\d+)</div>", html)
    assert m and int(m.group(1)) == len(model["nodes"])
    m = re.search(r"<div[^>]*>files:\s*(\d+)</div>", html)
    assert m and int(m.group(1)) == len(model["files"])
    m = re.search(r"<div[^>]*>commits:\s*(\d+)</div>", html)
    assert m and int(m.group(1)) == model["stamp"]["commits"]


def test_hud_engine_anchor_matches_repo(html, model) -> None:
    engine, patch = _repo_engine_version(), _repo_patch()
    assert model["facts"] == {"engine": engine, "patch": patch}, (
        "ENGINE_VERSION or the DS patch moved - run: python tools/atlas_build.py")
    m = re.search(r'<div[^>]*\btitle="([^"]*)"[^>]*>engine:\s*DS\s+([\d.]+)\s*/\s*patch\s+([\d.]+)</div>', html)
    assert m, "HUD engine row missing"
    assert (m.group(2), m.group(3)) == (engine, patch)
    assert "Daemon Slayer" in m.group(1) and f"ENGINE_VERSION {engine}" in m.group(1)
    assert "pointer-events:auto" in m.group(0), "title tooltip never fires under pointer-events:none"


def test_scripts_parse_under_node(html) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    for body in re.findall(r"<script>(.*?)</script>", html, re.S):
        fd, path = tempfile.mkstemp(suffix=".js", prefix="atlas_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            proc = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=60)
        finally:
            os.unlink(path)
        assert proc.returncode == 0, proc.stderr or proc.stdout


# --------------------------------------------------------------------------
# the order's UX items
# --------------------------------------------------------------------------

def test_item2_reduced_motion_does_not_freeze_and_pause_exists(html, app_js) -> None:
    assert "rmFrozenT" not in app_js, "the reduced-motion clock freeze is back"
    frame = _function_body(app_js, "frame")
    # under reduced motion the pulses still advance; only Pause stops them
    assert "if(!paused){" in frame and "p.t+=p.spd" in frame
    assert re.search(r'id="atlas-pause"[^>]*aria-pressed=', html), "no pause control"


def test_item2_pulses_move_in_screen_pixels_per_second(app_js) -> None:
    assert re.search(r"var PULSE_PX_S=\d+;", app_js)
    frame = _function_body(app_js, "frame")
    # speed (px/s) * seconds / the link's on-screen length = fraction of the lane
    assert "p.t+=p.spd*k/Math.max(8,p.e.len)" in frame
    assert "pulseZoomMul" not in app_js


def test_item3_font_floor_is_14px(html, page_css, app_js) -> None:
    sizes = [float(s) for s in re.findall(r"font-size:\s*([\d.]+)px", page_css + html.split("</style>")[-1])]
    assert sizes, "no font sizes found"
    small = [s for s in sizes if s < 14]
    assert not small, f"font sizes under the 14 px floor: {small}"
    for px in re.findall(r"labelFont\((\d+)\)", app_js):
        assert int(px) >= 14
    assert "var lfs=zoom>=2.5?16:14;" in app_js


def test_item4_region_titles_full_opacity_18px_kept_under_selection(app_js) -> None:
    render = _function_body(app_js, "render")
    block = render[render.index("// --- category titles"):render.index("// --- node labels")]
    assert "clamp(18*Math.sqrt(zoom),18," in block, "titles must start at 18 px and scale with zoom"
    assert "ctx.globalAlpha=1;" in block
    assert "lockN" not in block and "lockF" not in block, "titles must not hide under a selection"
    assert "if(!locked && !group)" not in app_js


def test_item5_zoom_performance_rules(app_js) -> None:
    render = _function_body(app_js, "render")
    frame = _function_body(app_js, "frame")
    assert not re.search(r"\.shadowBlur\s*=", app_js), "per-pulse (or any) shadowBlur is back"
    assert "DPR=Math.min(window.devicePixelRatio||1,2);" in app_js
    for hot in (render, frame):
        for bad in ("createRadialGradient", "createLinearGradient", ".map(", ".forEach(",
                    ".filter(", ".slice(", "new ", "=[", "={"):
            assert bad not in hot, f"per-frame allocation or gradient in the frame loop: {bad}"
    assert "var CAP=minWH*0.5;" in render and render.count("Math.min(CAP") >= 3
    assert "clipSeg(" in render, "links are not clipped to the viewport"
    assert render.count("onScreen(") >= 3, "frame loop does not cull to the viewport"


def test_item7_snapshots_are_files_beside_the_page(html, model) -> None:
    assert "data:image/" not in html, "an inline base64 image is back in the page"
    snaps = model["snapshots"]
    assert snaps, "no snapshots listed"
    index = json.loads((REPO_ROOT / "atlas" / "snapshots" / "index.json").read_text(encoding="utf-8"))
    assert [s["label"] for s in snaps] == [r["label"] for r in index]
    for s in snaps:
        p = REPO_ROOT / s["src"]
        assert p.is_file(), s["src"]
        head = p.read_bytes()[:12]
        assert head[:4] == b"RIFF" and head[8:12] == b"WEBP", s["src"]


def test_item8_colours_come_from_the_kit_tokens(html, page_css, app_js, model) -> None:
    assert '<link rel="stylesheet" href="ops/fleet_kit/tokens.css">' in html
    tokens = (REPO_ROOT / "ops" / "fleet_kit" / "tokens.css").read_text(encoding="utf-8")
    for c in model["categories"]:
        assert re.search(re.escape(c["token"]) + r"\s*:", tokens), f"{c['token']} is not a kit token"
    palette = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d", page_css)
    assert not palette, f"hard-coded colours in the page CSS: {palette[:5]}"
    js_hex = re.findall(r"['\"]#[0-9a-fA-F]{3,8}['\"]", app_js)
    assert not js_hex, f"hard-coded colours in the app script: {js_hex[:5]}"
    assert "prefers-color-scheme: dark" in app_js and "data-theme" in app_js


def test_item9_plain_drag_pans_and_zoom_cap_above_5x(app_js) -> None:
    assert "mode=(e.shiftKey||e.altKey||e.ctrlKey||e.metaKey)?'tilt':'pan';" in app_js
    m = re.search(r"\bZMAX=(\d+(?:\.\d+)?)", app_js)
    assert m and float(m.group(1)) > 5, "zoom cap must sit above 5x"
