"""FLEET-KIT v24 (MAIN 2026-10-26 0315 ORDER to all seven, cumulative v21-v24:
lanes loader race, claims effective cwd, sidecar root spelling, VW chart slot,
FLEET-COMMON 19): the tree-side half of the adoption.

The kit bytes are pinned by tests/test_fleet_kit_conformance.py and
tests/test_fleet_kit_v15.py (manifest sha + common block). This file pins
what the ORDER's sections 3-5 ask RC to do around them:
  * step 1: the vendored kit is v24, patch 0, 23 files + MANIFEST, manifest
    sha from the ORDER's section 1;
  * step 2: the FLEET-COMMON block carries the new item 19 (no width-dependent
    layout in chat) after item 18, and conformance() == [];
  * step 3 (section 4): the behaviours the section-4 bullets name - chart
    palette 9 slots with VW last, _lanes() publishes only after exec_module
    (a failed load publishes nothing; a concurrent caller never sees a
    half-loaded module), shell_targets resolves against the EFFECTIVE cwd
    and a relative Edit with no tool cwd claims nothing;
  * step 4 (RC + CS): no kit line spells the default sidecar root
    drive-rooted, so RC's sweep drops its v23 "Sidecars" allow segment and
    still reads every kit file clean;
  * CLAUDE.md carries the RC "KIT v24" rules line naming this guard.
RC was on v23 (MAIN drift 2026-10-25 22:43), so section 2 owes nothing.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
V24_MANIFEST_SHA256 = "a41ff08e4c2ace7f48119f9ffec051ce18458184c2417d6806be39f3c8804a7d"
V24_COMMON_BLOCK_SHA256 = "886c5f8b1a86928f91412d2800e9dfef3dd8e5b9158d14a06e65d06c22964800"
BEGIN, END = "<!-- FLEET-COMMON BEGIN -->\n", "<!-- FLEET-COMMON END -->"
# A drive-rooted spelling of the default sidecar root (any drive, either slash).
DRIVE_ROOTED_SIDECAR = re.compile(r"[A-Za-z]:[\\/]+Sidecars", re.I)
GATE = "rc_v24_lanes_gate"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v24_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _block():
    text = _text("CLAUDE.md")
    return text[text.index(BEGIN) + len(BEGIN):text.index(END)]


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

def test_the_common_block_carries_item_19_after_item_18_and_conforms():
    block = _block()
    assert hashlib.sha256(block.encode("ascii")).hexdigest() == V24_COMMON_BLOCK_SHA256
    assert block.encode("ascii") == (KIT / "FLEET-COMMON.md").read_bytes()
    i18 = block.index("\n18. STATUS BOARD (kit v23")
    i19 = block.index("\n19. NO WIDTH-DEPENDENT LAYOUT IN CHAT (kit v24; operator order 2026-10-25).")
    assert i18 < i19 and "\n20. " not in block
    item19 = block[i19:]
    assert "tables, box-drawing frames, ASCII art or space-aligned columns in chat" in item19
    assert "in a file and chat gets one line pointing at it." in item19
    assert _load("fleet_headless").conformance(ROOT) == []


# ---------------------------------------------------------------- step 3

def test_the_chart_palette_has_nine_slots_with_vw_last():
    tok = json.loads((KIT / "tokens.json").read_text(encoding="ascii"))
    order = tok["chart_order"]
    assert len(order) == 9 and len(set(order)) == 9 and order[-1] == "VW"
    for mode in ("light", "dark"):
        assert len(tok["chart"][mode]) == len(order), mode
    assert (tok["chart"]["light"][8], tok["chart"]["dark"][8]) == ("#0497ae", "#14a1b7")
    css = (KIT / "tokens.css").read_text(encoding="ascii")
    assert css.count("--fk-chart-9:") == 3
    assert "--fk-chart-9: #0497ae;" in css and "--fk-chart-9: #14a1b7;" in css


def _lanes_probe(tmp_path, monkeypatch, body):
    """fleet_headless with __file__ moved beside a stub fleet_lanes.py (its
    source = body(module name)), and the kit's sys.modules slot for it
    emptied (restored at teardown)."""
    fh = _load("fleet_headless")
    name = f"fleet_kit_lanes_v{fh.KIT_VERSION}"
    (tmp_path / "fleet_lanes.py").write_text(body(name), encoding="ascii")
    monkeypatch.setattr(fh, "__file__", str(tmp_path / "fleet_headless.py"))
    monkeypatch.setitem(sys.modules, name, None)
    del sys.modules[name]
    return fh, name


def test_lanes_publishes_the_module_only_after_exec_module(tmp_path, monkeypatch):
    fh, name = _lanes_probe(tmp_path, monkeypatch, lambda name: (
        "import sys\n"
        f"REGISTERED_DURING_EXEC = {name!r} in sys.modules\n"
        "PRIORITIES = ('probe',)\n"))
    mod = fh._lanes()
    assert mod.REGISTERED_DURING_EXEC is False
    assert sys.modules[name] is mod and fh._lanes() is mod


def test_a_failed_lanes_load_publishes_nothing(tmp_path, monkeypatch):
    fh, name = _lanes_probe(tmp_path, monkeypatch, lambda _n: "raise RuntimeError('rc v24 probe')\n")
    try:
        fh._lanes()
    except RuntimeError:
        pass
    else:
        raise AssertionError("the stub's import error was swallowed")
    assert name not in sys.modules


def test_a_concurrent_lanes_caller_never_sees_a_half_loaded_module(tmp_path, monkeypatch):
    # The 10-25 21:00 rollout refusal: thread B read fleet_lanes while thread A
    # was still inside exec_module and hit "has no attribute PRIORITIES".
    gate = types.SimpleNamespace(entered=threading.Event(), release=threading.Event(), execs=[])
    monkeypatch.setitem(sys.modules, GATE, gate)
    fh, _name = _lanes_probe(tmp_path, monkeypatch, lambda _n: (
        "import sys\n"
        f"_g = sys.modules[{GATE!r}]\n"
        "_g.execs.append(1)\n"
        "_g.entered.set()\n"
        "_g.release.wait(10)\n"
        "PRIORITIES = ('probe',)\n"))
    seen = {}

    def call(tag):
        seen[tag] = hasattr(fh._lanes(), "PRIORITIES")

    a = threading.Thread(target=call, args=("a",))
    a.start()
    assert gate.entered.wait(10), "thread A never reached exec_module"
    b = threading.Thread(target=call, args=("b",))
    b.start()
    time.sleep(0.3)  # B is either blocked on the loader lock or already returned
    gate.release.set()
    a.join(10)
    b.join(10)
    assert seen == {"a": True, "b": True}
    assert gate.execs == [1], "fleet_lanes was executed more than once"


def test_shell_targets_resolve_against_the_effective_cwd(tmp_path):
    claims = _load("fleet_claims")
    proj = tmp_path / "proj"
    files, specs = claims.shell_targets("cd sub && echo hi > out.txt", str(proj))
    assert files == [proj / "sub" / "out.txt"] and specs == []
    other = tmp_path / "other"
    files, _ = claims.shell_targets(f'cd "{other.as_posix()}" && git add a.py', str(proj))
    assert files == [other / "a.py"]
    files, _ = claims.shell_targets("echo hi > top.txt", str(proj))
    assert files == [proj / "top.txt"]
    assert all(p.is_absolute() for p in files)


def test_a_relative_edit_with_no_tool_cwd_claims_nothing(tmp_path, monkeypatch):
    claims = _load("fleet_claims")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)  # the hook process's own dir must never be guessed
    monkeypatch.setattr(claims, "index_add", lambda *a, **k: None)
    monkeypatch.setattr(claims, "session_process", lambda *a, **k: None)
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "rel.txt"}}
    assert claims.decide_edit(payload, "s.a", time.time(), 3600) == ("allow", "")
    assert not claims.claims_dir(repo).exists()
    # positive control: the same edit WITH a tool cwd claims inside that tree
    payload["cwd"] = str(repo)
    assert claims.decide_edit(payload, "s.a", time.time(), 3600) == ("allow", "")
    assert (claims.claims_dir(repo) / "s.a.json").is_file()


# ---------------------------------------------------------------- step 4

def test_no_kit_line_spells_the_sidecar_root_drive_rooted():
    man = json.loads((KIT / "MANIFEST.json").read_text(encoding="ascii"))
    hits = [
        (name, n)
        for name in (*man["files"], "MANIFEST.json")
        for n, line in enumerate(_text(f"ops/fleet_kit/{name}").split("\n"), 1)
        if DRIVE_ROOTED_SIDECAR.search(line)
    ]
    assert hits == []
    # KIT-SIDECAR-PATH: built from parts, the value is unchanged.
    lanes = _load("fleet_lanes")
    assert lanes.SIDECAR_DEFAULT == ("E:" + os.sep + "Sidecars" if os.name == "nt" else "")


def test_rc_sweep_dropped_the_sidecars_allow_segment_and_reads_the_kit_clean():
    from tools import sibling_name_sweep as sweep

    assert "sidecars" not in sweep._ALLOW_SEGMENTS
    man = json.loads((KIT / "MANIFEST.json").read_text(encoding="ascii"))
    for name in (*man["files"], "MANIFEST.json"):
        rel = f"ops/fleet_kit/{name}"
        hits = sweep.structural_findings(_text(rel), path=rel, source="TREE", status="T")
        assert not hits, [(h.path, h.line) for h in hits]
    # positive control: with the row dropped, the old spelling is a live hit again
    probe = "root " + "E:" + "/" + "Sidecars" + " when unset\n"
    assert sweep.structural_findings(probe, path="probe.txt", source="TREE", status="T")


# ---------------------------------------------------------------- CLAUDE.md

def test_claude_md_carries_the_kit_v24_rules_line():
    text = _text("CLAUDE.md")
    rc = text[text.index(END):]
    line = next(ln for ln in rc.split("\n") if ln.startswith("**KIT v24 (MAIN 2026-10-26 0315"))
    for needle in ("FLEET-COMMON item 19", "Guard `tests/test_fleet_kit_v24.py`", "Sidecars"):
        assert needle in line, needle
    assert (ROOT / "CLAUDE.md").stat().st_size <= 60 * 1024
