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
V26_MANIFEST_SHA256 = "45b5088e202a0c0c453fb1dc4ca8969783563d60d3b7b02e8d2c5c547fe4edae"
V26_COMMON_BLOCK_SHA256 = "cacc3ca30125d184e07612d232c2ba3f76338d5ea987d23e7e2addcb74e77dd0"
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
                          encoding="utf-8", errors="replace", timeout=60)


# ---------------------------------------------------------------- step 1

def test_the_vendored_kit_is_the_v26_order_bytes_and_conforms():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V26_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 26 and len(man["files"]) == 24
    assert "fleet_hook.sh" in man["files"]
    assert man["common_block_sha256"] == V26_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (26, 0)
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
