"""FLEET-KIT v26 (MAIN 2026-10-31 2200 ORDER to all seven, cumulative: per-tree
run cap, headless route = ordered list of 1-3 accounts, nonce-checked
deny-hook launcher, board fixes, RC 2128 kit fixes, gate tree median): the
tree-side half of the adoption.

The ORDER's section 5 asks RC to:
  * step 1: vendor all 24 files + MANIFEST byte-for-byte (manifest sha from
    the ORDER's section 1), re-embed the FLEET-COMMON block (item 10 changed)
    and confirm conformance() == [];
  * step 2: run the two PreToolUse kit hooks through
    `bash "$CLAUDE_PROJECT_DIR/ops/fleet_kit/fleet_hook.sh" <script> ...`,
    timeout 15, no ` || true`, matchers unchanged, the SubagentStop
    release-hook unchanged; `{}` piped into each reads exit 0, empty stdout.
    RC keeps its live settings gitignored, so the tracked half is
    ops/claude_settings.example.json and the live file is checked when present;
  * step 5: the run budget is reset only through the kit's `budget reset`.
CLAUDE.md carries the RC "KIT v26" rules line naming this guard.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
TEMPLATE = ROOT / "ops" / "claude_settings.example.json"
# Kit v27 (MAIN 2026-10-31 2347 ORDER, cumulative) superseded v26 (manifest
# 45b5088e...6fe4edae, 24 files); the pins below now hold the v27 bytes (24 files).
# Kit v28 (MAIN 2026-11-01 0825 ORDER, cumulative) superseded v27 (manifest
# 0a90af35...68e949c1, 24 files); the pins below now hold the v28 bytes (24 files).
# Kit v30 (MAIN 2026-11-12 0345 ORDER, cumulative v29 + v30) superseded v28
# (manifest 34347174...b9e52a6d93, block cacc3ca3...4e77dd0); the pins below now
# hold the v30 bytes (24 files).
# Kit v31 (MAIN 2026-11-14 0936 ORDER, cumulative) superseded v30
# (manifest d2ac4025...5714d07ea2, block unchanged); the pins below now
# hold the v31 bytes (24 files).
# Kit v32 (MAIN 2026-11-16 1947 ORDER, cumulative) superseded v31
# (manifest 6359f695...899a3829d, block 6205943c...bedea5ee); the pins below
# now hold the v32 bytes (25 files, FLEET-COMMON items 17 and 18 changed).
V26_MANIFEST_SHA256 = "cede0b7c8a80ca6ece410c07b572e4ac9dabe0bf7769d9c82d692bb1858c757d"
V26_COMMON_BLOCK_SHA256 = "0dbee15df74d42c2b50747c8194c9afd0d09c8ac7e03659515b9b3df7eca40a1"
END = "<!-- FLEET-COMMON END -->"

LAUNCHER = '"$CLAUDE_PROJECT_DIR/ops/fleet_kit/fleet_hook.sh"'
WANT_PRE = {
    "Bash|PowerShell|Read|Edit|Write|Grep|Glob|NotebookEdit|MultiEdit":
        f"bash {LAUNCHER} fleet_subagent_first.py",
    "Edit|Write|NotebookEdit|MultiEdit|Bash|PowerShell":
        f"bash {LAUNCHER} fleet_claims.py hook",
}
RELEASE = 'python "$CLAUDE_PROJECT_DIR/ops/fleet_kit/fleet_claims.py" release-hook || true'


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v26_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _kit_hooks(blob):
    """(event, matcher, timeout, command) for every fleet-kit hook line."""
    out = []
    for event, groups in (blob.get("hooks") or {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                cmd = hook.get("command", "")
                if "ops/fleet_kit/fleet_" in cmd and "fleet_done.py" not in cmd:
                    out.append((event, group.get("matcher"), hook.get("timeout"), cmd))
    return out


def _git_bash():
    """Git Bash (never System32's WSL bash.exe), as Claude Code runs hooks."""
    if os.name != "nt":
        return shutil.which("bash")
    override = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH", "").strip()
    if override and Path(override).is_file():
        return override
    git = shutil.which("git")
    if not git:
        return None
    for parent in list(Path(git).resolve().parents)[:3]:
        for rel in ("bin/bash.exe", "usr/bin/bash.exe"):
            if (parent / rel).is_file():
                return str(parent / rel)
    return None


def _launch(args, tmp_path, env_over=None):
    bash = _git_bash()
    if bash is None:
        pytest.skip("no Git Bash to run the hook launcher in")
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path).replace("\\", "/")
    env["FLEET_HOOK_PYTHON"] = sys.executable.replace("\\", "/")
    env.update(env_over or {})
    return subprocess.run([bash, (KIT / "fleet_hook.sh").as_posix(), *args], input="{}",
                          cwd=tmp_path, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60, check=False)


# ---------------------------------------------------------------- step 1

def test_the_vendored_kit_is_the_v26_order_bytes_and_conforms():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V26_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 32 and len(man["files"]) == 25
    assert "fleet_hook.sh" in man["files"]
    assert man["common_block_sha256"] == V26_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (32, 0)
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name
    assert fh.conformance(ROOT) == []


def test_the_launcher_is_ascii_lf():
    raw = (KIT / "fleet_hook.sh").read_bytes()
    assert raw.isascii() and b"\r" not in raw


def test_claude_md_carries_the_new_fleet_common_item_10():
    text = _text("CLAUDE.md")
    block = text[:text.index(END)]
    assert "an ordered list of 1 to 3 accounts" in block
    assert "per tree (a higher cap, at most 500" in block


# ---------------------------------------------------------------- step 2

def _assert_v26_wiring(blob):
    hooks = _kit_hooks(blob)
    pre = {m: (t, c) for e, m, t, c in hooks if e == "PreToolUse"}
    assert pre == {m: (15, c) for m, c in WANT_PRE.items()}
    for _, cmd in pre.values():
        assert "|| true" not in cmd and not cmd.startswith("python ")
    stop = [(t, c) for e, _, t, c in hooks if e == "SubagentStop"]
    assert stop == [(10, RELEASE)]


def test_the_tracked_template_wires_the_v26_launcher():
    _assert_v26_wiring(json.loads(TEMPLATE.read_text(encoding="ascii")))


def test_the_live_settings_wire_the_v26_launcher():
    if (ROOT / ".git").is_file():
        pytest.skip("linked worktree: its .claude/ copy is a creation-time snapshot")
    live = ROOT / ".claude" / "settings.json"
    if not live.is_file():
        pytest.skip(".claude/settings.json is gitignored and absent in this checkout")
    _assert_v26_wiring(json.loads(live.read_text(encoding="utf-8")))


def test_empty_input_through_the_launcher_is_a_silent_allow(tmp_path):
    proc = _launch(["fleet_subagent_first.py"], tmp_path)
    assert (proc.returncode, proc.stdout) == (0, ""), proc.stderr
    assert "FLEET-NONCE" not in proc.stdout


@pytest.mark.parametrize("stub", ["true", "no-such-python-interpreter"])
def test_a_stub_or_missing_interpreter_fails_closed(stub, tmp_path):
    proc = _launch(["fleet_subagent_first.py"], tmp_path, {"FLEET_HOOK_PYTHON": stub})
    assert proc.returncode == 2 and proc.stdout == ""
    assert "fleet hook: interpreter check failed (fleet_subagent_first.py)" in proc.stderr


def test_a_script_outside_the_kit_is_refused(tmp_path):
    proc = _launch(["../tools/rc_facts.py"], tmp_path)
    assert proc.returncode == 2 and proc.stdout == ""


# ---------------------------------------------------------------- step 5 + CLAUDE.md

def test_the_kit_owns_the_budget_reset_verb():
    fh = _load("fleet_headless")
    assert callable(fh.budget_reset)
    assert fh.RUNS_CAP_MAX == 500
    lanes = _load("fleet_lanes")
    assert lanes.runs_cap("RC", {}) == lanes.RUNS_CAP_DEFAULT == 120
    assert lanes.runs_cap("RC", {"runs_cap": {"RC": 501}}) == 120


def test_claude_md_carries_the_kit_v26_rules_line():
    text = _text("CLAUDE.md")
    rc = text[text.index(END):]
    line = next(ln for ln in rc.split("\n") if ln.startswith("**KIT v26 (MAIN 2026-10-31 2200"))
    for needle in ("budget reset --code RC", "fleet_hook.sh", "timeout 15",
                   "Guard `tests/test_fleet_kit_v26.py`"):
        assert needle in line, needle
    assert f"`bash {LAUNCHER} fleet_subagent_first.py`" in rc
    assert f"`bash {LAUNCHER} fleet_claims.py hook`" in rc
    assert (ROOT / "CLAUDE.md").stat().st_size <= 60 * 1024
