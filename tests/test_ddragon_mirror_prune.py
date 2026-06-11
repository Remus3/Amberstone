"""Mirror retention: prune_stale_versions keeps current + newest N, deletes the rest.

Deep-audit P1 (item 396): the mirror accreted 5 patch dirs (~1.7 GB, 4 stale
after the JS map-pin fix); the refresh script had no retention mechanism, so
every patch flip leaked ~560 MB forever. Prune only touches semver-named dirs
directly under the web mirror root - bundles under data/meta_build/ (git-tracked
archives) are explicitly out of scope.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ddragon_mirror_refresh import prune_stale_versions


def _mk(web: Path, names):
    for n in names:
        d = web / n
        d.mkdir(parents=True)
        (d / "marker.txt").write_text(n, encoding="utf-8")


def test_prune_keeps_current_plus_newest_retain(tmp_path):
    _mk(tmp_path, ["16.8.1", "16.9.1", "16.10.1", "16.11.1", "16.12.1"])
    removed = prune_stale_versions("16.12.1", retain=2, web_dir=tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["16.11.1", "16.12.1"]
    assert sorted(removed) == ["16.10.1", "16.8.1", "16.9.1"]


def test_prune_never_touches_non_semver_entries(tmp_path):
    _mk(tmp_path, ["16.11.1", "16.12.1", "perk-images"])
    (tmp_path / "_index.json").write_text("{}", encoding="utf-8")
    removed = prune_stale_versions("16.12.1", retain=1, web_dir=tmp_path)
    assert removed == ["16.11.1"]
    assert (tmp_path / "perk-images").is_dir()
    assert (tmp_path / "_index.json").exists()


def test_prune_dry_run_deletes_nothing(tmp_path):
    _mk(tmp_path, ["16.10.1", "16.11.1", "16.12.1"])
    planned = prune_stale_versions("16.12.1", retain=1, web_dir=tmp_path, dry_run=True)
    assert sorted(planned) == ["16.10.1", "16.11.1"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["16.10.1", "16.11.1", "16.12.1"]


def test_prune_current_always_kept_even_when_not_newest(tmp_path):
    # --version pin escape hatch: current may be OLDER than the newest dir.
    _mk(tmp_path, ["16.10.1", "16.11.1", "16.12.1"])
    removed = prune_stale_versions("16.10.1", retain=2, web_dir=tmp_path)
    assert "16.10.1" not in removed
    assert (tmp_path / "16.10.1").is_dir()
    assert (tmp_path / "16.12.1").is_dir()  # newest fills the retain quota
    assert removed == ["16.11.1"]


def test_prune_missing_web_dir_is_noop(tmp_path):
    assert prune_stale_versions("16.12.1", retain=2, web_dir=tmp_path / "absent") == []


def test_prune_unlinks_stale_junction_without_touching_target(tmp_path):
    # Live mirror had 16.9.1 as a Windows junction -> 16.8.1; rmtree refuses
    # reparse points. Prune must unlink the link entry itself and leave the
    # target contents alone.
    import os
    _mk(tmp_path, ["16.12.1", "_store"])
    try:
        os.symlink(tmp_path / "_store", tmp_path / "16.9.1",
                   target_is_directory=True)
    except OSError:
        import pytest
        pytest.skip("symlink creation not permitted")
    removed = prune_stale_versions("16.12.1", retain=1, web_dir=tmp_path)
    assert removed == ["16.9.1"]
    assert not (tmp_path / "16.9.1").exists()
    assert (tmp_path / "_store" / "marker.txt").exists()
