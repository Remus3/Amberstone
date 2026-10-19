"""FLEET-KIT v19 (MAIN 2026-10-18 1235 ORDER; STATUS BOARD, FLEET-COMMON item
18, stop sentinels refuse spawn, pre-push scans a new ref against ls-remote):
the tree-side half of the adoption.

The kit bytes are pinned by tests/test_fleet_kit_conformance.py and
tests/test_fleet_kit_v15.py (manifest sha + common block). This file pins
what the ORDER's section 4 asks RC to do around them:
  * step 1: the vendored kit is v19 and carries the new fleet_board.py;
  * step 2: the FLEET-COMMON block carries item 18 and conformance() == [];
  * step 3: ops/status_board.json is tracked config (ASCII, LF, code RC,
    dataset_version 2, the RC board url) and the board state dir is ignored;
  * step 4: /done pushes the board once with --final after the hand-off
    read-back and before the done marker; the session-start DIRECTIVE wires
    the start / reprint pushes; a headless render pushes nothing;
  * step 5: RC declares no stop sentinels (decision recorded in CLAUDE.md);
  * step 6: .githooks/pre-push still runs identity FIRST, with the remote
    arguments the kit needs for its ls-remote scan.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
RC_BOARD_URL = "https://claude.ai/artifact/7ofQL8BtTQfzjLPbfyi6aJ"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v19_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    # done.md carries one pre-existing non-ASCII glyph; .gitignore checks out
    # CRLF under core.autocrlf. Neither is this file's concern.
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_the_vendored_kit_is_v19_with_the_board_helper():
    man = json.loads(_text("ops/fleet_kit/MANIFEST.json"))
    # Kit v20 (MAIN 2026-10-18 1812) superseded v19; the board helper stays.
    assert man["version"] >= 19
    assert "fleet_board.py" in man["files"]
    assert _load("fleet_headless").KIT_VERSION == man["version"]


def test_the_common_block_carries_item_18_and_conforms():
    text = _text("CLAUDE.md")
    block = text[text.index("<!-- FLEET-COMMON BEGIN -->"):text.index("<!-- FLEET-COMMON END -->")]
    assert "18. STATUS BOARD (kit v19" in block
    assert _load("fleet_headless").conformance(ROOT) == []


def test_status_board_config_is_tracked_ascii_lf_and_names_rc():
    raw = (ROOT / "ops" / "status_board.json").read_bytes()
    raw.decode("ascii")
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    assert json.loads(raw) == {"code": "RC", "dataset_version": 2, "url": RC_BOARD_URL}
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "ops/status_board.json"],
                             cwd=ROOT, capture_output=True)
    assert tracked.returncode == 0


def test_board_state_dir_is_gitignored():
    assert "ops/loop/control/board/" in _text(".gitignore").split("\n")
    ignored = subprocess.run(["git", "check-ignore", "-q", "ops/loop/control/board/state.json"],
                             cwd=ROOT, capture_output=True)
    assert ignored.returncode == 0


def test_done_pushes_the_board_once_between_handoff_readback_and_marker():
    done = _text("tools/done.md")
    sec9 = done[done.index("### 9. Final output"):done.index("### 10. Next-session prompt")]
    board = sec9.index("fleet_board.py calls --final --session <n>")
    marker = sec9.index("fleet_done.py mark --session <n> --status done")
    assert board < marker
    assert done.count("fleet_board.py calls --final") == 1
    assert "never a ritual failure" in sec9


def test_session_start_directive_wires_the_start_and_reprint_push():
    spec = importlib.util.spec_from_file_location("rc_v19_sc", ROOT / "tools" / "session_checklist.py")
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    assert "fleet_board.py calls --session <n>" in sc.DIRECTIVE
    assert "--final" not in sc.DIRECTIVE
    assert "reprint" in sc.DIRECTIVE


def test_a_headless_render_pushes_nothing(tmp_path):
    board = _load("fleet_board")
    env = {"FLEET_SUBAGENT_FIRST": "off"}
    assert board.render(tmp_path, 1, [], environ=env) == {"push": False, "reason": "headless"}
    assert not (tmp_path / "ops" / "loop" / "control" / "board").exists()


def test_rc_declares_no_stop_sentinels():
    assert not (ROOT / "ops" / "stop_sentinels.json").exists()
    assert _load("fleet_headless").stop_sentinel_hit(ROOT) is None


def test_pre_push_runs_identity_first_with_the_remote_args():
    lines = [ln for ln in _text(".githooks/pre-push").split("\n")
             if "python" in ln.lower() and ".py" in ln and not ln.lstrip().startswith("#")]
    assert lines, "pre-push runs no python step"
    assert "fleet_identity.py\" pre-push \"$@\"" in lines[0]
