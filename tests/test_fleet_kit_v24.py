"""FLEET-KIT v24 (MAIN 2026-10-26 0315 ORDER, cumulative through v23): the
tree-side half of the adoption.

The kit bytes are pinned by tests/test_fleet_kit_conformance.py and
tests/test_fleet_kit_v15.py (manifest sha + common block). This file pins
what the ORDER's section 5 asks RC to do around them:
  * step 1: the vendored kit is v24, patch 0, 23 files + MANIFEST, manifest
    sha from the ORDER's section 1;
  * step 2: the FLEET-COMMON block carries the new item 19 (no
    width-dependent layout in chat) after item 18, and conformance() == [];
  * step 3 (section 4): chart_order carries 9 codes with VW last; a
    `cd X && ...` shell target resolves under X; _lanes() publishes the
    module only after exec_module;
  * step 4: RC's "Sidecars" allow segment is dropped from
    tools/sibling_name_sweep.py and the sweep still reads the kit clean
    (no kit line spells the sidecar root drive-rooted any more).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
V24_MANIFEST_SHA256 = "a41ff08e4c2ace7f48119f9ffec051ce18458184c2417d6806be39f3c8804a7d"
V24_COMMON_BLOCK_SHA256 = "886c5f8b1a86928f91412d2800e9dfef3dd8e5b9158d14a06e65d06c22964800"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v24_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _block():
    text = _text("CLAUDE.md")
    return text[text.index("<!-- FLEET-COMMON BEGIN -->"):text.index("<!-- FLEET-COMMON END -->")]


# ---------------------------------------------------------------- step 1

def test_the_vendored_kit_is_the_v24_order_bytes():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V24_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 24 and len(man["files"]) == 23
    assert man["common_block_sha256"] == V24_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (24, 0)
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name


# ---------------------------------------------------------------- step 2

def test_the_common_block_carries_item_19_after_18_and_conforms():
    block = _block()
    i18 = block.index("18. STATUS BOARD (kit v23")
    i19 = block.index("19. NO WIDTH-DEPENDENT LAYOUT IN CHAT (kit v24")
    assert i18 < i19
    assert "No markdown\n    tables" in block
    assert "20. " not in block[i19:]
    assert _load("fleet_headless").conformance(ROOT) == []


# ---------------------------------------------------------------- step 3

def test_chart_order_has_nine_codes_with_vw_last():
    tokens = json.loads((KIT / "tokens.json").read_text(encoding="ascii"))
    order = tokens["chart_order"]
    assert len(order) == 9 and order[-1] == "VW"
    assert tokens["chart"]["light"][8] == "#0497ae"
    assert tokens["chart"]["dark"][8] == "#14a1b7"
    assert len(tokens["chart"]["light"]) == len(tokens["chart"]["dark"]) == len(order)
    assert "--fk-chart-9:" in (KIT / "tokens.css").read_text(encoding="ascii")


def test_shell_targets_resolve_against_the_effective_cwd(tmp_path):
    claims = _load("fleet_claims")
    sub = tmp_path / "other"
    sub.mkdir()
    files, _ = claims.shell_targets(f'cd "{sub}" && echo hi > out.txt', str(tmp_path))
    assert [Path(f) for f in files] == [sub / "out.txt"]
    files, _ = claims.shell_targets("echo hi > out.txt", str(tmp_path))
    assert [Path(f) for f in files] == [tmp_path / "out.txt"]
    assert all(Path(f).is_absolute() for f in files)


def test_lanes_loader_publishes_only_after_exec_module():
    fh = _load("fleet_headless")
    src = (KIT / "fleet_headless.py").read_text(encoding="ascii")
    body = src[src.index("def _lanes():"):src.index("def _governor(")]
    assert body.index("spec.loader.exec_module(mod)") < body.index("sys.modules[name] = mod")
    assert "_LANES_LOCK" in body and hasattr(fh, "_LANES_LOCK")
    mod = fh._lanes()
    assert hasattr(mod, "PRIORITIES")
    assert fh._lanes() is mod


# ---------------------------------------------------------------- step 4

def test_the_sidecars_allow_segment_is_dropped_and_the_kit_reads_clean():
    sweep_src = _text("tools/sibling_name_sweep.py")
    assert '"Sidecars"' not in sweep_src
    drive_rooted = re.compile(r"[A-Za-z]:[\\/]+Sidecars", re.IGNORECASE)
    for f in sorted(KIT.iterdir()):
        if f.is_file() and f.suffix in (".py", ".js", ".md", ".json", ".css"):
            assert not drive_rooted.search(f.read_text(encoding="utf-8")), f.name
