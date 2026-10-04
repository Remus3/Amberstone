# arch: regression - RM-117 retention decision: git-tracked patch generations are not retention targets | section=core | frozen=no
"""RM-117 retention decision (2026-10-03). Tier 1 / tier 2 backups were
measured ABSENT; tier 3 (superseded patch generations) is all git-tracked,
so tracked generations are repository content and drop out of
SUPERSEDED_PATCH. Untracked generations keep the old behaviour.
"""

import subprocess
from pathlib import Path

import core.data_retention as dr

ROOT = Path(__file__).resolve().parent.parent


def _gens(tmp_path, names=("16.10.1", "16.11.1", "16.12.1")):
    base = tmp_path / "daemon_slayer"
    for n in names:
        (base / n).mkdir(parents=True)
        (base / n / "items.json").write_text("{}", encoding="utf-8")
    return base


def _superseded(cands):
    return sorted(c.path.name for c in cands
                  if c.klass == dr.CLASS_SUPERSEDED_PATCH)


def test_untracked_superseded_generation_still_reported(tmp_path):
    _gens(tmp_path)
    assert _superseded(dr.scan(tmp_path, tracked=frozenset())) == ["16.10.1"]


def test_tracked_superseded_generation_is_not_a_candidate(tmp_path):
    _gens(tmp_path)
    tracked = frozenset({"daemon_slayer/16.10.1/items.json"})
    cands = dr.scan(tmp_path, tracked=tracked)
    assert _superseded(cands) == []
    # Its files are still classified (RETAIN), not silently dropped.
    assert any(c.path.parent.name == "16.10.1" and c.klass == dr.CLASS_RETAIN
               for c in cands)
    plan = dr.plan(tmp_path, tracked=tracked)
    assert plan.counts_by_class[dr.CLASS_SUPERSEDED_PATCH] == 0


def test_git_tracked_files_fail_soft_outside_a_repo(tmp_path):
    assert dr._git_tracked_files(tmp_path) == frozenset()


def test_real_repo_patch_dirs_are_seen_as_tracked():
    """Against the real checkout: a generation git tracks (the DS patch
    dir the RM-236 boot test reads) is never offered for deletion."""
    data = ROOT / "data"
    tracked = dr._git_tracked_files(data)
    if not tracked:
        import pytest
        pytest.skip("git unavailable")
    probe = data / "daemon_slayer" / "16.15.1"
    if not probe.is_dir():
        import pytest
        pytest.skip("16.15.1 not present")
    assert dr._is_tracked_dir(data, probe, tracked)
    ls = subprocess.run(["git", "-C", str(data), "ls-files",
                         "daemon_slayer/16.15.1"], capture_output=True)
    assert ls.stdout.strip(), "premise: 16.15.1 is tracked"
