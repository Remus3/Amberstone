"""RM-433 - every reader of the gitignored per-host sync config finds it from a
LINKED WORKTREE.

`ops/moon_sync_repos.json` is gitignored, so it exists only in the MAIN working
tree. A reader that resolves it against its OWN tree silently degrades in every
lane worktree: the tools see zero sibling roots and zero participants, and the
test-side readers see an empty carrier set, which turns a mirror arm into an
empty parametrisation or a skip that reads as green.

The fixture is a REAL `git worktree add` inside tmp_path, so the resolver is
exercised through the same `git rev-parse --git-common-dir` it uses on the box.
Nothing here names a real sibling: every root is a tmp directory.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tests.test_channel_doc_rc_gate as channel_gate  # noqa: E402
import tests.test_loop_concurrency as loop_conc  # noqa: E402
import tests.test_outbound_reciprocity_check as orc_tests  # noqa: E402
import tools.inbox_responder_runner as runner  # noqa: E402
from tools import moon_sync_poller as poller  # noqa: E402
from tools import outbound_reciprocity_check as orc  # noqa: E402
from tools import sibling_name_sweep as sweep  # noqa: E402

CONFIG_REL = Path("ops") / "moon_sync_repos.json"
CODES = ("ZZ", "QQ")

# Git variables that would redirect `git -C <dir>` away from the fixture repo
# when this suite itself runs under a git hook.
_GIT_REDIRECT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                     "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")


def _git(cwd: Path, *args: str) -> None:
    hooks = cwd.parent / "_no_hooks"
    hooks.mkdir(exist_ok=True)
    subprocess.run(
        ["git", "-c", f"core.hooksPath={hooks}", "-c", "user.name=rm433-test",
         "-c", "user.email=rm433-test@example.invalid", "-c", "commit.gpgsign=false",
         *args],
        cwd=str(cwd), capture_output=True, text=True, check=True, timeout=120,
    )


@pytest.fixture()
def layout(tmp_path: Path, monkeypatch):
    """A main checkout carrying the config, plus a linked worktree carrying none."""
    for name in (*_GIT_REDIRECT_ENV, orc.REPOS_ENV):
        monkeypatch.delenv(name, raising=False)
    base = tmp_path.resolve()
    main = base / "mainrepo"
    main.mkdir()
    _git(main, "init", "-q")
    (main / "README.txt").write_text("fixture\n", encoding="ascii")
    _git(main, "add", "README.txt")
    _git(main, "commit", "-q", "--no-verify", "-m", "fixture")
    sibs = []
    for code in CODES:
        sib = base / f"sib-{code.lower()}"
        (sib / "moon_sync_inbox").mkdir(parents=True)
        sibs.append(sib)
    (main / "ops").mkdir()
    (main / CONFIG_REL).write_text(
        json.dumps({"repos": [str(s) for s in sibs],
                    "participants": {c: str(s) for c, s in zip(CODES, sibs)}}),
        encoding="ascii")
    wt = base / "linkedwt"
    _git(main, "worktree", "add", "-q", "--detach", str(wt))
    assert not (wt / CONFIG_REL).exists(), "the worktree must carry no config of its own"
    return main, wt, sibs


# --------------------------------------------------------------- the resolver


def test_resolver_finds_the_main_tree_config_from_a_worktree(layout):
    main, wt, _ = layout
    assert sweep.resolve_config_path(wt) == main / CONFIG_REL


def test_resolver_creates_no_process(layout, monkeypatch):
    """The responder runner resolves participants BEFORE its real-spawn guard,
    which promises no subprocess, and the poller resolves at import on a hook
    path where a console child flashes. So the resolver reads git's own worktree
    link files instead of running git."""
    main, wt, _ = layout

    def tripwire(*a, **kw):
        raise AssertionError(f"a process was created: {a[:1]}")

    monkeypatch.setattr(subprocess, "Popen", tripwire)
    assert sweep.resolve_config_path(wt) == main / CONFIG_REL


def test_resolver_follows_a_relative_gitdir_link(layout):
    """`git worktree add --relative-paths` (git 2.48+) writes the link relative
    to the worktree; the resolver must not read that as relative to the cwd."""
    main, wt, _ = layout
    link = wt / ".git"
    absolute = link.read_text(encoding="utf-8").strip()[len("gitdir:"):].strip()
    relative = Path("..") / Path(absolute).relative_to(wt.parent)
    # Git for Windows marks `.git` HIDDEN, and truncate-create on a hidden file
    # is refused there, so rewrite it in place instead of via write_text.
    with link.open("r+b") as fh:
        fh.write(f"gitdir: {relative.as_posix()}\n".encode("ascii"))
        fh.truncate()
    assert sweep.resolve_config_path(wt) == main / CONFIG_REL


def test_a_non_toplevel_subdirectory_of_a_worktree_does_not_borrow(layout):
    """Only a checkout ROOT resolves to the main tree; a directory inside one
    keeps its own (absent) answer."""
    _main, wt, _ = layout
    sub = wt / "nested"
    sub.mkdir()
    assert sweep.resolve_config_path(sub) == sub / CONFIG_REL


def test_a_submodule_style_gitfile_without_commondir_does_not_borrow(tmp_path):
    """A `.git` FILE is not proof of a linked worktree: a submodule's points at a
    modules dir with no `commondir`, and must not resolve to its superproject."""
    base = tmp_path.resolve()
    sup = base / "super"
    (sup / ".git" / "modules" / "child").mkdir(parents=True)
    (sup / "ops").mkdir()
    (sup / CONFIG_REL).write_text("{}", encoding="ascii")
    child = sup / "child"
    child.mkdir()
    (child / ".git").write_text(f"gitdir: {sup / '.git' / 'modules' / 'child'}\n",
                                encoding="ascii")
    assert sweep.resolve_config_path(child) == child / CONFIG_REL


def test_resolver_prefers_a_worktree_local_config(layout):
    _main, wt, _ = layout
    (wt / "ops").mkdir(exist_ok=True)
    (wt / CONFIG_REL).write_text("{}", encoding="ascii")
    assert sweep.resolve_config_path(wt) == wt / CONFIG_REL


def test_resolver_returns_the_local_path_when_no_tree_has_one(layout):
    main, wt, _ = layout
    (main / CONFIG_REL).unlink()
    got = sweep.resolve_config_path(wt)
    assert got == wt / CONFIG_REL and not got.exists()


def test_sweep_load_config_still_arms_through_the_shared_resolver(layout):
    main, wt, _ = layout
    cfg = sweep.load_config(root=wt, env={})
    assert cfg.mode == sweep.MODE_ARMED, (cfg.mode, cfg.detail)
    assert cfg.source == str(main / CONFIG_REL)


# ---------------------------------------------------------------- tool readers


def test_poller_repo_roots_come_from_the_main_tree(layout, monkeypatch):
    _main, wt, sibs = layout
    monkeypatch.setattr(poller, "_SELF_REPO", str(wt))
    roots = poller._load_repo_roots()
    assert roots[0] == str(wt)
    assert [str(s) for s in sibs] == list(roots[1:])


def test_poller_participants_come_from_the_main_tree(layout, monkeypatch):
    _main, wt, sibs = layout
    monkeypatch.setattr(poller, "_SELF_REPO", str(wt))
    got = poller._load_participants()
    for code, sib in zip(CODES, sibs):
        assert got[poller._norm_root(str(sib))] == code


def test_poller_env_override_still_wins_in_a_worktree(layout, monkeypatch, tmp_path):
    _main, wt, _ = layout
    monkeypatch.setattr(poller, "_SELF_REPO", str(wt))
    only = str(tmp_path / "override-only")
    monkeypatch.setenv(orc.REPOS_ENV, only)
    assert poller._load_repo_roots() == (str(wt), only)


def test_reciprocity_sibling_roots_come_from_the_main_tree(layout):
    _main, wt, sibs = layout
    assert orc.load_sibling_roots(wt, env={}) == sibs


def test_reciprocity_env_override_still_wins_in_a_worktree(layout, tmp_path):
    _main, wt, _ = layout
    only = tmp_path / "override-only"
    assert orc.load_sibling_roots(wt, env={orc.REPOS_ENV: str(only)}) == [only]


def test_responder_participants_come_from_the_main_tree(layout):
    _main, wt, sibs = layout
    keep, detail = runner.load_participants(wt)
    assert keep == {c: s / "moon_sync_inbox" for c, s in zip(CODES, sibs)}
    assert detail == ""


# ---------------------------------------------------------------- test readers


@pytest.mark.parametrize("module,attr", [(loop_conc, "ROOT"), (channel_gate, "REPO_ROOT")],
                         ids=["loop_concurrency", "channel_doc_rc_gate"])
def test_test_side_sibling_roots_come_from_the_main_tree(layout, monkeypatch, module, attr):
    _main, wt, sibs = layout
    monkeypatch.setattr(module, attr, wt)
    assert module._sibling_roots() == sibs


@pytest.mark.parametrize("module,attr", [(loop_conc, "ROOT"), (channel_gate, "REPO_ROOT")],
                         ids=["loop_concurrency", "channel_doc_rc_gate"])
def test_test_side_reader_refuses_an_empty_carrier_set_when_the_config_exists(
        layout, monkeypatch, module, attr):
    """An empty enumeration must not pass: the config EXISTS, so zero carriers is
    a broken config, never a machine without siblings."""
    main, wt, _ = layout
    (main / CONFIG_REL).write_text(json.dumps({"repos": []}), encoding="ascii")
    monkeypatch.setattr(module, attr, wt)
    with pytest.raises(AssertionError):
        module._sibling_roots()


@pytest.mark.parametrize("module,attr", [(loop_conc, "ROOT"), (channel_gate, "REPO_ROOT")],
                         ids=["loop_concurrency", "channel_doc_rc_gate"])
def test_test_side_reader_with_no_config_anywhere_is_empty_not_an_error(
        layout, monkeypatch, module, attr):
    """Control arm: a fresh clone or CI has no config at all, and that stays the
    honest empty answer the callers turn into a named skip."""
    main, wt, _ = layout
    (main / CONFIG_REL).unlink()
    monkeypatch.setattr(module, attr, wt)
    assert module._sibling_roots() == []


def test_reciprocity_literal_guard_reads_the_main_tree_config(layout, monkeypatch):
    main, wt, _ = layout
    monkeypatch.setattr(orc_tests, "REPO_ROOT", wt)
    assert orc_tests._per_host_config_path() == main / CONFIG_REL
