"""RM-489: nine tracked DDragon patch dirs versus a "current + previous"
retention claim.

Decision (self-adjudicated 2026-10-03): the two are DIFFERENT stores and both
are correct. `tools/ddragon_mirror_refresh.py` RETAIN_VERSIONS=2 governs the
gitignored `web/data/ddragon/<semver>/` MIRROR only. The TRACKED bundle
archives under `data/meta_build/ddragon/<semver>/` are retained WITHOUT a
count bound, because DS modules and tests cite specific archived patches as
verbatim ground truth (e.g. 16.11.1 rune_procs, 16.12.1 enemy_runes, 16.14.1
rune shield/heal grants) and some tests glob every archived
runesReforged.json. Pruning them would orphan those citations. Measured cost:
~22 MB for 9 patches. Alternative rejected: prune the archive to the cited set
(saves little, and the next citation of an uncited patch would need a
re-fetch of a patch Riot may no longer serve identically).

These guards make the decision checkable: a cited archive must exist, and the
mirror pruner must not be able to reach the archive.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tools import ddragon_mirror_refresh as dmr

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "data" / "meta_build" / "ddragon"
CITE = re.compile(r"data/meta_build/ddragon/(\d+\.\d+\.\d+)/")


def _tracked(*patterns: str) -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", *patterns],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def test_every_cited_archive_patch_is_tracked():
    files = _tracked("*.py")
    assert len(files) > 100, "vacuous enumeration"
    cited: set[str] = set()
    for rel in files:
        try:
            cited |= set(CITE.findall((ROOT / rel).read_text(encoding="utf-8",
                                                             errors="replace")))
        except OSError:
            continue
    assert cited, "no archive citations found - the pattern or the tree moved"
    archived = {Path(p).parts[3] for p in _tracked("data/meta_build/ddragon")}
    missing = sorted(cited - archived)
    assert not missing, f"cited DDragon archive patches not tracked: {missing}"


def test_mirror_pruner_cannot_reach_the_tracked_archive():
    assert ARCHIVE.resolve() != Path(dmr.WEB_DIR).resolve()
    assert ARCHIVE.resolve() not in Path(dmr.WEB_DIR).resolve().parents
    assert dmr.RETAIN_VERSIONS == 2


def test_mirror_prune_dry_run_on_the_archive_layout_only_lists(tmp_path):
    """Even pointed at an archive-shaped dir, dry_run deletes nothing."""
    for v in ("16.17.1", "16.18.1", "16.19.1"):
        (tmp_path / v).mkdir()
    removed = dmr.prune_stale_versions("16.19.1", web_dir=tmp_path, dry_run=True)
    assert removed == ["16.17.1"]
    assert all((tmp_path / v).is_dir() for v in ("16.17.1", "16.18.1", "16.19.1"))
