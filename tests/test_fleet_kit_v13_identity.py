"""FLEET-KIT v13 (MAIN 2026-10-08 2246 ORDER section 1; FLEET-COMMON 17, NO AI OR
BOT ATTRIBUTION): the tree-side wiring RC owns.

The kit bytes are pinned by tests/test_fleet_kit_conformance.py and
tests/test_lane_progress_v7.py. This file pins:
  * both identity hooks, wired with the kit's own strings in the tracked
    .githooks (step 4) - the pre-push identity gate runs BEFORE the sibling
    sweep, the credential scan and the LFS upload, and is fed the captured refs;
  * the commit-msg hook strips through the kit AFTER RC's own Co-Authored-By
    strip and BEFORE the message validators;
  * .gitignore names ops/loop/control/identity.jsonl (step 5);
  * the kit's commit-msg strip really removes an AI trailer and keeps the rest
    (end to end through the vendored file, on a tmp message);
  * CLAUDE.md names the identity wiring and that fleet.operatorIdent is LOCAL
    git config only (step 6 - its values are never in a tracked file).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"

COMMIT_MSG_LINE = 'python "ops/fleet_kit/fleet_identity.py" commit-msg "$1" || true'
PRE_PUSH_LINE = 'python "ops/fleet_kit/fleet_identity.py" pre-push "$@" || exit 1'


def _text(rel):
    return (ROOT / rel).read_bytes().decode("ascii").replace("\r\n", "\n")


def test_v13_kit_ships_identity_and_rewrite():
    man = json.loads((KIT / "MANIFEST.json").read_text(encoding="ascii"))
    assert man["version"] == 13
    for name in ("fleet_identity.py", "fleet_rewrite.py"):
        assert name in man["files"] and (KIT / name).is_file(), name


def test_commit_msg_hook_strips_through_the_kit_after_rc_strip():
    hook = _text(".githooks/commit-msg")
    assert hook.count(COMMIT_MSG_LINE) == 1
    at = hook.index(COMMIT_MSG_LINE)
    assert hook.index("grep -v -i '^Co-Authored-By: Claude'") < at
    assert at < hook.index("--message-file")


def test_pre_push_identity_gate_runs_first_on_the_captured_refs():
    hook = _text(".githooks/pre-push")
    line = "printf '%s\\n' \"$REFS\" | " + PRE_PUSH_LINE
    assert hook.count(line) == 1
    at = hook.index(line)
    assert hook.index('REFS="$(cat)"') < at
    assert at < hook.index("sibling_name_sweep.py\" --pre-push")
    assert at < hook.index("credential_history_scan.py\" --pre-push")
    assert at < hook.index('git lfs pre-push "$@"')
    # LFS stays the LAST command (its exit status is the hook's on a clean path).
    assert hook.rstrip().endswith('git lfs pre-push "$@"')


def test_gitignore_names_the_identity_log():
    assert "ops/loop/control/identity.jsonl" in _text(".gitignore").splitlines()
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q",
                        "ops/loop/control/identity.jsonl"])
    assert r.returncode == 0


def test_kit_commit_msg_strip_end_to_end(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_bytes(b"fix: a thing\n\nbody line\n\nClaude-Session: x\n"
                    b"Co-Authored-By: Claude <noreply@anthropic.com>\n")
    r = subprocess.run([sys.executable, str(KIT / "fleet_identity.py"), "commit-msg",
                        str(msg)], cwd=str(tmp_path), capture_output=True)
    assert r.returncode == 0
    assert msg.read_bytes() == b"fix: a thing\n\nbody line\n"


def test_claude_md_names_the_identity_wiring():
    text = _text("CLAUDE.md")
    assert COMMIT_MSG_LINE in text
    assert PRE_PUSH_LINE in text
    assert "fleet.operatorIdent" in text and "LOCAL git config" in text
