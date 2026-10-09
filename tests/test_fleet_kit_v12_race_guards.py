"""FLEET-KIT v12 RACE GUARDS (FLEET-COMMON item 16; MAIN 2026-10-08 2031 ORDER
section 3): the tree-side half of the adoption.

The kit files themselves are pinned by tests/test_fleet_kit_conformance.py and
tests/test_lane_progress_v7.py. This file pins what RC wires around them:
  * tests/conftest.py installs ops/fleet_kit/fleet_test_guard.py (step 6), with
    the env roots and the extra live-tick ignores in tests/_fleet_guard_config.py;
  * .gitignore names the five v12 runtime paths (step 4);
  * every slash-command doc carries the RACE GUARDS block, and /done routes its
    commit and push through fleet_gitlock.py and any whole suite through
    fleet_suite_gate.py (step 5);
  * Python code that pushes takes the kit's git_lock() (step 5: the CI watchdog);
  * the Claude-side precommit gate still sees a commit run through the git lock;
  * CLAUDE.md names the claims hook wiring.
The hooks themselves live in the gitignored project .claude/settings.json (RC's
v11 decision: tracking it would publish host paths from a public repo), so no
test here can read them; the adoption read-back is recorded in docs/LEDGER.md.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _fleet_guard_config as cfg

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"

V12_NEW = ("fleet_claims.py", "fleet_gitlock.py", "fleet_suite_gate.py",
           "fleet_test_guard.py")

# The 23 slash-command docs (same anchored set as tests/test_skill_dispatch_v10.py).
COMMANDS = (
    "RC2-Continue.md", "directed-headless-upgrade.md", "done.md",
    "game-monitor.md", "headless-ds.md", "headless-gated.md",
    "headless-queue.md", "headless-repo.md", "headless-research.md",
    "headless-true-audit.md", "headless-uiux.md", "headless-upgrade.md",
    "live-gated-drain.md", "orchestrated-run.md", "overlay-build-continue.md",
    "repo-insights.md", "root-cause-fix.md", "section-j-dispatch.md",
    "ship-batch.md", "sync-all-md.md", "test-driven-development.md",
    "test-first-autopilot.md", "weekly-hygiene.md",
)

RACE_GUARDS_BLOCK = "\n".join((
    "> **RACE GUARDS (FLEET-KIT v12, FLEET-COMMON item 16; MAIN 2026-10-08 2031 "
    "ORDER step 5).** Enforced by the kit hook `ops/fleet_kit/fleet_claims.py` "
    "(PreToolUse + SubagentStop in the project settings), not by this text.",
    "> 1. Every `git commit` / `git push` runs through the tree's git lock: "
    "`python ops/fleet_kit/fleet_gitlock.py run --owner <id> -- git commit -F <tmpfile>` "
    "(same shape for `git push ...`). Python code uses `fleet_gitlock.git_lock(dir, owner)`. "
    "A bare commit or push is denied.",
    "> 2. A WHOLE suite (pytest naming no test file) runs through the machine-wide gate: "
    "`python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- <suite cmd>`. "
    "A slice that names its test files needs no gate.",
    "> 3. `<id>` is your own claims owner id, `<session_id>.<agent_id>` (`.main` in a "
    "main thread); a deny reason names it. The hook also denies an edit, a redirect or "
    "a `git add` of a file another live agent holds - leave that file to its agent.",
))

# Lane / drain prompts fed to headless runs that are not slash commands.
LOOP_PROMPTS = (
    "ops/loop/prompts/drain_w23_common.md", "ops/loop/prompts/drain_w23_merger.md",
    "ops/loop/prompts/lane_research_prompt.md", "ops/loop/prompts/lane_ui_prompt.md",
)


def _load(name):
    spec = importlib.util.spec_from_file_location("rc_v12_" + name, KIT / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("utf-8")


# ---------------------------------------------------------------- kit set

def test_v12_kit_ships_the_four_race_guard_files():
    man = json.loads((KIT / "MANIFEST.json").read_text(encoding="ascii"))
    assert man["version"] == 12
    for name in V12_NEW:
        assert name in man["files"], name
        assert (KIT / name).is_file(), name


# ---------------------------------------------------------------- step 6

def test_conftest_installs_the_kit_test_guard(request):
    names = set(request.fixturenames)
    assert "_fleet_live_state_guard" in names
    assert "_fleet_runtime_roots" in names
    src = _text("tests/conftest.py")
    assert "fleet_test_guard.install(" in src
    assert "env_roots=_fleet_guard_config.ENV_ROOTS" in src


def test_every_declared_env_root_points_into_tmp_path(tmp_path):
    assert cfg.ENV_ROOTS, "an empty env_roots would pass vacuously"
    for var, sub in cfg.ENV_ROOTS.items():
        value = os.environ.get(var)
        assert value == str(tmp_path / sub), var


def test_env_roots_are_vars_rc_code_actually_reads():
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "grep", "-l", "-e", "RC_", "--", "*.py",
         ":!tests", ":!docs", ":!ops/fleet_kit"],
        capture_output=True, text=True, check=True).stdout.split()
    blob = "\n".join(_text(p) for p in tracked)
    for var in cfg.ENV_ROOTS:
        assert f'"{var}"' in blob, f"{var} is read by no RC module"


def test_the_guard_ignores_extend_the_kit_defaults():
    guard = _load("fleet_test_guard")
    src = _text("tests/conftest.py")
    assert "ignore=fleet_test_guard.IGNORE + _fleet_guard_config.EXTRA_IGNORE" in src
    assert "ops/loop/control/inbox_tick_last.json" in cfg.EXTRA_IGNORE
    assert not set(cfg.EXTRA_IGNORE) & set(guard.IGNORE)
    for glob in cfg.EXTRA_IGNORE:
        assert glob.startswith("ops/loop/control/"), glob


# ---------------------------------------------------------------- step 4

@pytest.mark.parametrize("rel", [
    "ops/loop/control/claims/x.json", "ops/loop/control/locks/git.lock",
    "ops/loop/control/claims.jsonl", "ops/loop/control/claims.mode",
    "ops/loop/control/gitlock.jsonl"])
def test_gitignore_names_the_v12_runtime_paths(rel):
    gi = _text(".gitignore").splitlines()
    named = {"ops/loop/control/claims/x.json": "ops/loop/control/claims/",
             "ops/loop/control/locks/git.lock": "ops/loop/control/locks/"}.get(rel, rel)
    assert named in gi, f"{named} not named in .gitignore"
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", rel])
    assert r.returncode == 0, rel


# ---------------------------------------------------------------- step 5

@pytest.mark.parametrize("name", COMMANDS)
def test_every_command_doc_carries_the_race_guards_block(name):
    assert RACE_GUARDS_BLOCK in _text("tools/" + name)
    mirror = ROOT / ".claude" / "commands" / name
    if mirror.is_file():
        assert RACE_GUARDS_BLOCK in mirror.read_bytes().decode("utf-8")


@pytest.mark.parametrize("rel", LOOP_PROMPTS)
def test_loop_prompts_carry_the_race_guards_block(rel):
    assert RACE_GUARDS_BLOCK in _text(rel)


def test_done_commits_and_pushes_through_the_git_lock():
    done = _text("tools/done.md")
    gl = 'python "C:/Riot Commander/ops/fleet_kit/fleet_gitlock.py" run --owner <id> -- '
    assert gl + 'git -C "C:/Riot Commander" commit -F <tmpfile>' in done
    assert gl + 'git -C "C:/Riot Commander" push origin <branch>' in done
    assert "- Otherwise: `git -C \"C:/Riot Commander\" push origin <branch>`" not in done
    assert ('python "C:/Riot Commander/ops/fleet_kit/fleet_suite_gate.py" run '
            '--owner <id> -- ') in done


def test_ci_watchdog_push_runs_inside_the_git_lock(monkeypatch, tmp_path):
    from tools import ci_watchdog as cw
    events = []

    class _Lock:
        def __init__(self, where, owner, verb):
            events.append(("lock", str(where), owner, verb))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            events.append(("unlock",))
            return False

    monkeypatch.setattr(cw, "_git_lock", lambda where, owner, verb: _Lock(where, owner, verb))

    def fake_run(cmd, cwd=None, timeout=120, **kw):
        events.append(("run", tuple(cmd[:4])))
        if "diff" in cmd and "--name-only" in cmd:
            return 0, "tools/x.py\n"
        return 0, ""

    monkeypatch.setattr(cw, "_run", fake_run)
    monkeypatch.setattr(cw, "_claude_fix_via_kit", lambda cmd, wt, t: (0, "fixed"))
    monkeypatch.setattr(cw, "_gh", lambda: "gh")
    cw.execute_dispatch(1, "a" * 40, arm=True, worktree=tmp_path / "wt")
    push_at = next(i for i, e in enumerate(events) if e[0] == "run" and "push" in e[1])
    assert events[push_at - 1][0] == "lock"
    assert events[push_at - 1][2] == "ci-watchdog" and events[push_at - 1][3] == "push"
    assert events[push_at + 1] == ("unlock",)
    locks = [e for e in events if e[0] == "lock"]
    assert len(locks) == 1, "only the push takes the git lock"


def test_ci_watchdog_git_lock_is_the_kit_lock(tmp_path):
    from tools import ci_watchdog as cw
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    lock = repo / "ops" / "loop" / "control" / "locks" / "git.lock"
    with cw._git_lock(str(repo), "ci-watchdog", "push") as held:
        assert Path(held) == lock and lock.is_file()
        rec = json.loads(lock.read_text(encoding="ascii"))
        assert rec["owner"] == "ci-watchdog" and rec["verb"] == "push"
    assert not lock.exists(), "the lock is released after the push"
    assert Path(sys.modules["fleet_kit_fleet_gitlock"].__file__).resolve() == \
        (KIT / "fleet_gitlock.py").resolve()


# ---------------------------------------------------------------- defence in depth

def test_precommit_gate_sees_a_commit_run_through_the_git_lock():
    from tools import precommit_gate as pg
    assert pg._is_commit(
        "python ops/fleet_kit/fleet_gitlock.py run --owner s.a -- git commit -F m.txt")
    assert pg._is_commit(
        'python "E:/x/ops/fleet_kit/fleet_gitlock.py" run --owner s.a -- '
        'git -C "E:/x" commit -F m.txt')
    assert not pg._is_commit(
        "python ops/fleet_kit/fleet_gitlock.py run --owner s.a -- git push origin main")
    assert not pg._is_commit("python ops/fleet_kit/fleet_gitlock.py status")


# ---------------------------------------------------------------- CLAUDE.md

def test_claude_md_names_the_claims_hook_wiring():
    text = _text("CLAUDE.md")
    assert 'python "$CLAUDE_PROJECT_DIR/ops/fleet_kit/fleet_claims.py" hook' in text
    assert 'python "$CLAUDE_PROJECT_DIR/ops/fleet_kit/fleet_claims.py" release-hook' in text
