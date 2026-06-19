"""D1: the pre-commit Share sync is gated on staged mirrored-source.

The local pre-commit hook used to run `tools/ds_share_sync.py` on EVERY commit,
which re-stamped Share/MANIFEST.md (a timestamp) every time and fired the
external gist upload even for commits that could not change the mirror. The
`--precommit` mode skips the sync when no mirrored DS source is staged, removing
that churn. These tests pin the pure `_should_sync` predicate (no git needed).
"""
from __future__ import annotations

from tools.ds_share_sync import _DS_TOOLS, _should_sync


def test_engine_package_path_triggers_sync():
    assert _should_sync(["agents/daemon_slayer/rank.py"]) is True


def test_data_snapshot_path_triggers_sync():
    assert _should_sync(["data/daemon_slayer/16.12.1/items.json"]) is True


def test_share_package_path_triggers_sync():
    assert _should_sync(["Share/README.md"]) is True


def test_curated_ds_tool_triggers_sync():
    # Every curated DS tool that is mirrored into Share/src must trigger.
    for name in _DS_TOOLS:
        assert _should_sync([f"tools/{name}"]) is True, name


def test_share_sync_tool_itself_does_not_trigger():
    # ds_share_sync.py is intentionally NOT mirrored, so editing it must not
    # trigger a sync (it cannot change Share/src content).
    assert _should_sync(["tools/ds_share_sync.py"]) is False


def test_non_ds_commit_does_not_trigger():
    # The wave-1 shape: web / dashboard / core / coach / tests only.
    staged = [
        "core/op_score_curve.py",
        "dashboard/routes_op_score.py",
        "coaches/aram_coach.py",
        "web/index.html",
        "tests/test_op_score_curve.py",
    ]
    assert _should_sync(staged) is False


def test_empty_staged_does_not_trigger():
    assert _should_sync([]) is False


def test_mixed_commit_triggers_when_any_mirrored():
    # A commit that touches both non-DS and one mirrored file must sync.
    staged = ["web/index.html", "agents/daemon_slayer/__init__.py"]
    assert _should_sync(staged) is True
