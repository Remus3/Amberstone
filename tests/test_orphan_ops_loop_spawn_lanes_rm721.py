"""RM-721 (c) dead-launcher drift guard: ops/loop/spawn_lanes.ps1 stays archived.

ops/loop/spawn_lanes.ps1 was the 2026-07-16 night-run one-shot (2b8dee205):
it created two DATED worktrees (research-20260716 on docs/research-20260716,
ui-20260716 on ui/overlay-item4-item8-20260716) and detached one hidden
ops/loop/run_lane.ps1 worker per lane. It was archived to
docs/_archive/2026-07/ in session 144 (repo lane, git mv, history kept) because
it was dead on two independent facts:

  1. ZERO callers. No tracked .py / .ps1 / .bat / .cmd / .json / .yml / .js /
     .html / .xml (UTF-16 task XMLs decoded) file runs it; outside dated
     history (docs/LEDGER.md, docs/audits/, docs/specs/, BACKLOG.md) the only
     mentions were prose: the ops/loop/lane_launcher.py docstring, the
     ops/lane_worktrees.example.json _doc line, the two 2026-07-16 lane
     prompts, and tests/test_lane_worktree_base_v13.py, which read it as a
     path-literal site.
  2. Its job is spent. Its branch names and worktree folders are dated to
     one night, and the live lane path is ops/loop/lane_launcher.py
     (launch_lane -> ensure_worktree -> ops/loop/run_lane.ps1), which takes a
     lane name and builds lane/<x> worktrees itself.

ops/loop/run_lane.ps1 is NOT dead: lane_launcher.py still starts it, and
tests/test_headless_env.py pins it as a kit-routed runner.

If you find yourself restoring the spawner, first confirm a real caller
exists; the archived copy is the reference.
"""
from __future__ import annotations

import subprocess

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix

_DELETED = "ops/loop/spawn_lanes.ps1"
_ARCHIVED = "docs/_archive/2026-07/spawn_lanes.ps1"


def _tracked(rel: str) -> bool:
    out = subprocess.run(
        ["git", "ls-files", "--", rel], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout
    return out.strip() == rel


def test_spawn_lanes_one_shot_stays_out_of_ops_loop() -> None:
    assert not (REPO_ROOT / _DELETED).exists(), (
        f"{_DELETED} reappeared. It is the spent 2026-07-16 night-run spawner; "
        "the live lane path is ops/loop/lane_launcher.py. Confirm a real "
        "caller before restoring it."
    )
    assert not _tracked(_DELETED)


def test_spawn_lanes_archive_copy_is_tracked() -> None:
    # Archived with git mv, so the copy stays tracked even though .gitignore
    # ignores the _archive/ path (a cp + git add would have been refused).
    assert (REPO_ROOT / _ARCHIVED).is_file()
    assert _tracked(_ARCHIVED), f"{_ARCHIVED} is not in the git index"


def test_live_runner_the_spawner_used_is_still_present() -> None:
    # Anchor: the absence check above must not pass under a wrong root, and
    # the runner the spawner detached is still live.
    assert (REPO_ROOT / "ops" / "loop" / "lane_launcher.py").is_file()
    assert (REPO_ROOT / "ops" / "loop" / "run_lane.ps1").is_file()


def test_no_live_tracked_text_names_the_spawner() -> None:
    """No runnable or config file, and no live lane prompt, names it.

    Dated history (docs/, BACKLOG.md and other *.md outside ops/) and tests/
    (this guard names the file) are out of scope; data/ and web/data/ are
    bulk game data. ops/**/*.md IS in scope: the lane prompts are fed to
    headless runs, so a stale "the repo root spawn_lanes.ps1 resolves" there
    is an instruction, not history. *.xml covers the tracked task XMLs.
    """
    patterns = ("*.py", "*.ps1", "*.bat", "*.cmd", "*.json", "*.yml",
                "*.yaml", "*.js", "*.mjs", "*.html", "*.xml", "*.md")
    skip = ("tests/", "docs/", "data/", "web/data/")
    scanned = 0
    offenders = []
    for path in iter_repo_files(REPO_ROOT, patterns):
        rel = relative_posix(path)
        if rel.startswith(skip) or "/tests/" in rel:
            continue
        if rel.endswith(".md") and not rel.startswith("ops/"):
            continue
        scanned += 1
        raw = path.read_bytes()
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
        if "spawn_lanes" in text:
            offenders.append(rel)
    # An empty walk would pass vacuously; the tree holds thousands of these.
    assert scanned > 500, f"walk saw only {scanned} files - the scan is broken"
    assert offenders == [], f"live references to the archived spawner: {offenders}"
