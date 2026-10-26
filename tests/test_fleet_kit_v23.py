"""FLEET-KIT v23 (MAIN 2026-10-25 1926 ORDER, cumulative: v21 + v22 + v23;
STATUS BOARD LOCAL ONLY): the tree-side half of the adoption.

The kit bytes are pinned by tests/test_fleet_kit_conformance.py and
tests/test_fleet_kit_v15.py (manifest sha + common block). This file pins
what the ORDER's section 5 asks RC to do around them:
  * step 1: the vendored kit is v23, patch 0, 23 files + MANIFEST, manifest
    sha from the ORDER's section 1;
  * step 2: the FLEET-COMMON block carries the v23 item 18 (LOCAL ONLY) and
    conformance() == [];
  * step 3 (section 4): the board files ride the kit IGNORE, not RC's
    EXTRA_IGNORE; render returns {"rendered", "html"}; a headless render
    writes nothing;
  * step 4: no RC session pushes the board - /done renders it once with
    --final between the hand-off read-back and the done marker, the
    session-start DIRECTIVE renders at start and reprint, and no Artifact /
    ArtifactData / `fleet_board.py calls|pushed|account` step remains;
  * step 5: /done section 1 runs `fleet_done.py reap --apply` before its
    commit.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
# Kit v24 (MAIN 2026-10-26 0315 ORDER) superseded the v23 bytes (manifest
# f5d82861...11ba527c, block 5e8fa06f...bbc663); step 1 now pins the v24
# bytes and tests/test_fleet_kit_v24.py pins what v24 adds.
V23_MANIFEST_SHA256 = "a41ff08e4c2ace7f48119f9ffec051ce18458184c2417d6806be39f3c8804a7d"
V23_COMMON_BLOCK_SHA256 = "886c5f8b1a86928f91412d2800e9dfef3dd8e5b9158d14a06e65d06c22964800"
BOARD_FILES = ("ops/loop/control/board/status.json", "ops/loop/control/board/state.json",
               "ops/loop/control/board/board.html")
# Every RC surface that once told a session to push the board.
BOARD_SITES = ("tools/done.md", "tools/session_checklist.py", "tools/rc_facts.py", "CLAUDE.md")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v23_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    # done.md carries one pre-existing non-ASCII glyph; not this file's concern.
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _block():
    text = _text("CLAUDE.md")
    return text[text.index("<!-- FLEET-COMMON BEGIN -->"):text.index("<!-- FLEET-COMMON END -->")]


# ---------------------------------------------------------------- step 1

def test_the_vendored_kit_is_the_v23_order_bytes():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V23_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 24 and len(man["files"]) == 23
    assert man["common_block_sha256"] == V23_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (24, 0)
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name


# ---------------------------------------------------------------- step 2

def test_the_common_block_carries_item_18_local_only_and_conforms():
    block = _block()
    assert "18. STATUS BOARD (kit v23" in block
    assert "LOCAL ONLY" in block and "Headless runs never render." in block
    assert "Headless runs never push" not in block
    assert "ops/status_board.json" not in block
    assert _load("fleet_headless").conformance(ROOT) == []


# ---------------------------------------------------------------- step 3

def test_the_board_files_ride_the_kit_ignore_not_rc_extra_ignore(tmp_path):
    from tests import _fleet_guard_config as cfg

    board, guard = _load("fleet_board"), _load("fleet_test_guard")
    for rel in BOARD_FILES:
        assert rel in guard.IGNORE, rel
        assert rel not in cfg.EXTRA_IGNORE, f"{rel} is in the kit IGNORE since v21/v23"
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "status_board.json").write_text('{"code": "RC"}\n', encoding="ascii")
    plan = board.render(tmp_path, 1, [], environ={})
    assert plan["rendered"] is True and plan["html"].endswith("board.html")
    assert "push" not in plan
    for rel in BOARD_FILES:
        os.utime(tmp_path / rel, ns=(10**18, 10**18))
    raw = guard.snapshot(tmp_path, ignore=())
    eff = guard.snapshot(tmp_path, ignore=tuple(guard.IGNORE))
    board.render(tmp_path, 2, [], environ={})
    changed = guard.compare(raw, guard.snapshot(tmp_path, ignore=()))[0]
    assert set(BOARD_FILES) <= set(changed), "positive control: the render touched nothing"
    assert guard.verdict(*guard.compare(eff, guard.snapshot(tmp_path, ignore=tuple(guard.IGNORE)))) == ""


def test_a_headless_render_writes_nothing(tmp_path):
    board = _load("fleet_board")
    plan = board.render(tmp_path, 1, [], environ={"FLEET_SUBAGENT_FIRST": "off"})
    assert plan == {"rendered": False, "reason": "headless"}
    assert board.calls_text(plan) == "board not rendered: headless\n"
    assert not (tmp_path / "ops" / "loop" / "control" / "board").exists()


def test_the_retired_push_api_is_gone():
    board = _load("fleet_board")
    for name in ("tool_calls", "dataset_update", "set_account_board", "account_label",
                 "boards_of", "board_for", "page", "URL_PLACEHOLDER"):
        assert not hasattr(board, name), name


# ---------------------------------------------------------------- step 4

def test_done_renders_the_board_once_between_handoff_readback_and_marker():
    done = _text("tools/done.md")
    sec9 = done[done.index("### 9. Final output"):done.index("### 10. Next-session prompt")]
    board = sec9.index("fleet_board.py render --final --session <n>")
    marker = sec9.index("fleet_done.py mark --session <n> --status done")
    assert board < marker
    assert done.count("fleet_board.py render --final") == 1
    assert "never a ritual failure" in sec9


def test_the_session_start_directive_renders_locally():
    spec = importlib.util.spec_from_file_location("rc_v23_sc", ROOT / "tools" / "session_checklist.py")
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    assert "fleet_board.py render --session <n>" in sc.DIRECTIVE
    assert "reprint" in sc.DIRECTIVE and "--final" not in sc.DIRECTIVE
    assert "tool calls" not in sc.DIRECTIVE


def test_no_rc_surface_still_pushes_the_board():
    for rel in BOARD_SITES:
        text = _text(rel)
        for retired in ("fleet_board.py calls", "fleet_board.py pushed", "fleet_board.py account",
                        "datasets/board", "Board push failed"):
            assert retired not in text, f"{rel} still carries {retired!r}"


def test_the_installed_done_command_matches_tools_done():
    installed = ROOT / ".claude" / "commands" / "done.md"
    if installed.is_file():  # gitignored copy; absent in a fresh clone / CI
        assert installed.read_bytes() == (ROOT / "tools" / "done.md").read_bytes()


# ---------------------------------------------------------------- step 5

def test_done_reaps_worktrees_before_the_section_1_commit():
    done = _text("tools/done.md")
    sec1 = done[done.index("### 1. Auto-commit any pending changes"):done.index("### 2. Push")]
    reap = sec1.index("python ops/fleet_kit/fleet_done.py reap --apply")
    assert reap < sec1.index("fleet_gitlock.py\" run --owner")
    assert "never --force" in sec1
    assert done.count("fleet_done.py reap --apply") == 1
