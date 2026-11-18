# arch: tests for the lane worktree base resolution in ops/loop/lane_launcher.py | section=tests | frozen=no
"""MAIN 2026-10-08 2246 ORDER section 5 (SIDECAR-1): the lane worktree base
moves off the old drive-root folder into this tree's folder under the shared
sidecar root. The new base is a machine path, so it lives in a per-host
GITIGNORED config (`ops/lane_worktrees.json`, template
`ops/lane_worktrees.example.json`), never as a literal in a tracked file: the
sibling-name sweep's structural arm halts a push carrying an undeclared
drive-rooted path, and README-AUDIT section 3 finding 2 wants absolute machine
paths out of the tree.

Resolution order: env RC_LANE_WORKTREE_BASE, then the per-host config's
`base`, then the kit's sidecar `RC/Worktree` folder, then `<repo
parent>/rc-worktrees` (the historical layout, relative to the checkout - no
machine literal), which since MAIN ORDER 2026-11-16 2145 raises instead when
that parent is a drive root.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

launcher = importlib.import_module("ops.loop.lane_launcher")

REPO = Path(launcher.REPO_ROOT)


def test_env_wins_over_config(tmp_path):
    cfg = tmp_path / "lane_worktrees.json"
    cfg.write_text(json.dumps({"base": str(tmp_path / "from_cfg")}), encoding="ascii")
    got = launcher.resolve_worktree_base(
        env={"RC_LANE_WORKTREE_BASE": str(tmp_path / "from_env")}, config=cfg, repo_root=REPO)
    assert got == tmp_path / "from_env"


def test_config_used_when_env_unset(tmp_path):
    cfg = tmp_path / "lane_worktrees.json"
    cfg.write_text(json.dumps({"base": str(tmp_path / "from_cfg")}), encoding="ascii")
    got = launcher.resolve_worktree_base(env={}, config=cfg, repo_root=REPO)
    assert got == tmp_path / "from_cfg"


def test_fallback_is_relative_to_the_checkout(tmp_path):
    # MAIN ORDER 2026-11-16 2145 (E-ROOT): `<repo parent>/rc-worktrees` is kept
    # only for a checkout whose parent is NOT a drive root; a drive-root parent
    # (RC's own layout) now raises. The sidecar is pinned off so the kit's
    # sidecar step cannot answer first.
    no_sidecar = {"FLEET_SIDECAR_ROOT": ""}
    nested = tmp_path / "x" / "repo"
    for cfg in (tmp_path / "absent.json", tmp_path / "bad.json", tmp_path / "empty.json"):
        if cfg.name == "bad.json":
            cfg.write_text("{not json", encoding="ascii")
        if cfg.name == "empty.json":
            cfg.write_text(json.dumps({"base": ""}), encoding="ascii")
        got = launcher.resolve_worktree_base(env=no_sidecar, config=cfg, repo_root=nested)
        assert got == nested.parent / "rc-worktrees", cfg.name
        if REPO.parent == Path(REPO.parent.anchor):
            with pytest.raises(RuntimeError):
                launcher.resolve_worktree_base(env=no_sidecar, config=cfg, repo_root=REPO)
        else:
            got = launcher.resolve_worktree_base(env=no_sidecar, config=cfg, repo_root=REPO)
            assert got == REPO.parent / "rc-worktrees", cfg.name


def test_sidecar_worktree_folder_before_the_parent_fallback(tmp_path):
    sc = tmp_path / "sc"
    (sc / "RC").mkdir(parents=True)
    got = launcher.resolve_worktree_base(
        env={"FLEET_SIDECAR_ROOT": str(sc)}, config=tmp_path / "absent.json", repo_root=REPO)
    assert got == sc / "RC" / "Worktree"


def test_unresolved_base_refuses_at_use(monkeypatch):
    monkeypatch.setattr(launcher, "WORKTREE_BASE", None)
    with pytest.raises(launcher.LaneLaunchError):
        launcher.worktree_path("upgrade")


def test_blank_env_does_not_override(tmp_path):
    cfg = tmp_path / "lane_worktrees.json"
    cfg.write_text(json.dumps({"base": str(tmp_path / "from_cfg")}), encoding="ascii")
    got = launcher.resolve_worktree_base(
        env={"RC_LANE_WORKTREE_BASE": "  "}, config=cfg, repo_root=REPO)
    assert got == tmp_path / "from_cfg"


def test_default_config_path_is_the_gitignored_per_host_file():
    assert launcher.WORKTREE_CONFIG == REPO / "ops" / "lane_worktrees.json"
    example = REPO / "ops" / "lane_worktrees.example.json"
    assert example.is_file()
    assert json.loads(example.read_text(encoding="ascii"))["base"] == ""
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "ops/lane_worktrees.json" in [ln.strip() for ln in ignored]


def test_no_drive_rooted_literal_in_the_launcher():
    """The order's live site carries no machine path literal any more.

    The order had two sites; the other, the 2026-07-16 one-shot spawner, was
    archived to docs/_archive/2026-07/ by RM-721 (c) and is pinned there by
    tests/test_orphan_ops_loop_spawn_lanes_rm721.py.
    """
    rel = "ops/loop/lane_launcher.py"
    text = (REPO / rel).read_text(encoding="ascii")
    assert r"C:\rc-worktrees" not in text, rel
    assert "Sidecars" not in text, rel
