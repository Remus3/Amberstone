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
`base`, then `<repo parent>/rc-worktrees` (the historical layout, relative to
the checkout - no machine literal).
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

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
    for cfg in (tmp_path / "absent.json", tmp_path / "bad.json", tmp_path / "empty.json"):
        if cfg.name == "bad.json":
            cfg.write_text("{not json", encoding="ascii")
        if cfg.name == "empty.json":
            cfg.write_text(json.dumps({"base": ""}), encoding="ascii")
        got = launcher.resolve_worktree_base(env={}, config=cfg, repo_root=REPO)
        assert got == REPO.parent / "rc-worktrees", cfg.name


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


def test_no_drive_rooted_literal_in_the_two_sites():
    """The order's two sites carry no machine path literal any more."""
    for rel in ("ops/loop/lane_launcher.py", "ops/loop/spawn_lanes.ps1"):
        text = (REPO / rel).read_text(encoding="ascii")
        assert r"C:\rc-worktrees" not in text, rel
        assert "Sidecars" not in text, rel
