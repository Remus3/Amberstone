"""Guard: no live file cites a dated competitor-lift doc at a dead path (RM-1115).

The dated ``COMPETITOR_LIFT_<date>.md`` docs moved from ``docs/`` to
``docs/_archive/`` (the mdclean C7 sweep). The DS-package half of RM-1115
(``tests/test_ds_lift_doc_paths_w_s144d35.py``) re-pointed
``agents/daemon_slayer``. This guard covers the rest of the live tree:
``core/``, ``dashboard/``, ``web/``, ``tests/``, ``ops/`` and ``tools/``.

A cite must name a path that resolves on disk, so a ``docs/COMPETITOR_LIFT_
2026-05-30.md`` cite (a path that no longer exists) fails and
``docs/_archive/COMPETITOR_LIFT_2026-05-30.md`` passes. Templates with a
``<date>`` placeholder are not dated cites and are not matched. Three files
quote a dead path on purpose (a guard docstring explaining the move, a
budget comment about a deleted doc) and are the only exemptions.

The universe is the TRACKED files under those roots, read through
``tests/_repo_walk`` (ADR-015), never a fresh ``rglob``. ``ops/`` holds two
gitignored trees that are not live files: ``ops/runtime/responder_export/<sha>/``
(a full snapshot COPY of an older repo, written by the inbox responder) and
``ops/loop/control/`` (lane prompts and reports). An ``rglob`` read both, so
this guard was red on every checkout that carries them and green in CI and in
clean worktrees. The ROOTS filter is this guard's own scope choice, applied on
top of the shared walker. Empty is never clean: ``_walk()`` asserts every
``EXPECTED`` file, this guard itself and every root are reached.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests._repo_walk import iter_repo_files, relative_posix, tracked_relpaths

REPO = Path(__file__).resolve().parent.parent
ROOTS = ("core", "dashboard", "web", "tests", "ops", "tools")
SUFFIXES = {".py", ".js", ".css", ".md", ".html", ".mjs", ".ps1"}
_SELF = "tests/test_lift_doc_paths_live_files_rm1115_s144d80.py"
# Files that quote a dead path as the subject of the text (history of the move).
QUOTES_DEAD_PATH = {
    "tests/test_ds_file_line_cites_v_s144d33.py",
    "tests/test_ds_lift_doc_paths_w_s144d35.py",
    "tests/test_citation_drift_guard_rm171.py",
    "tests/test_lift_doc_paths_live_files_rm1115_s144d80.py",
}
_DATED = re.compile(
    r"docs/(?:[\w.-]+/)*COMPETITOR_LIFT_\d{4}-\d{2}-\d{2}[\w-]*?\.md")
# Files that carry a cite and the archived doc each must name.
EXPECTED = {
    "core/carry_share.py": "COMPETITOR_LIFT_2026-06-18_R2.md",
    "core/item_wpa.py": "COMPETITOR_LIFT_2026-06-02.md",
    "core/skill_wpa.py": "COMPETITOR_LIFT_2026-06-02.md",
    "core/personal_build_wr.py": "COMPETITOR_LIFT_2026-06-16.md",
    "core/player_gpi.py": "COMPETITOR_LIFT_2026-06-16.md",
    "dashboard/routes_ds_combo.py": "COMPETITOR_LIFT_2026-05-30.md",
    "dashboard/routes_ds_knobs.py": "COMPETITOR_LIFT_2026-05-30.md",
    "dashboard/routes_ds_relscore.py": "COMPETITOR_LIFT_2026-05-30.md",
    "dashboard/routes_ds_sweep.py": "COMPETITOR_LIFT_2026-05-30.md",
    "dashboard/routes_personal_build.py": "COMPETITOR_LIFT_2026-06-16.md",
    "dashboard/routes_spike_markers.py": "COMPETITOR_LIFT_2026-05-30.md",
    "web/js/panels/ds_combo.js": "COMPETITOR_LIFT_2026-05-30.md",
    "web/css/panels/ds_combo.css": "COMPETITOR_LIFT_2026-05-30.md",
    "tests/test_routes_ds_combo_ttk_t2f3.py": "COMPETITOR_LIFT_2026-06-08.md",
}


_WRAPPED = re.compile(r"COMPETITOR_LIFT_[ \t]*\r?\n[ \t#*/]*\d{4}-\d{2}")


def _live_files(repo: Path | None = None):
    """Tracked files under ROOTS with a scanned suffix, via tests/_repo_walk."""
    repo = repo or REPO
    patterns = tuple(f"*{suffix}" for suffix in sorted(SUFFIXES))
    for path in sorted(iter_repo_files(repo, patterns)):
        rel = relative_posix(path, repo)
        if rel.split("/", 1)[0] in ROOTS and path.suffix in SUFFIXES:
            yield path


def _dead_cites(files, repo: Path) -> list[str]:
    missing = []
    for path in files:
        rel = relative_posix(path, repo)
        if rel in QUOTES_DEAD_PATH:
            continue
        for m in _DATED.finditer(_flat(path)):
            if not (repo / m.group(0)).is_file():
                missing.append(f"{rel}: {m.group(0)}")
    return sorted(set(missing))


def _wrapped_cites(files, repo: Path) -> list[str]:
    return [relative_posix(path, repo) for path in files
            if relative_posix(path, repo) not in QUOTES_DEAD_PATH
            and _WRAPPED.search(path.read_text(encoding="utf-8"))]


def _walk() -> list[Path]:
    """``_live_files()`` as a list, refusing to be vacuous.

    Both sweeps below assert an EMPTY offender list, which an empty walk
    satisfies, so each one goes through this anchor first.
    """
    files = list(_live_files())
    rels = {relative_posix(p, REPO) for p in files}
    absent = sorted((set(EXPECTED) | {_SELF}) - rels)
    assert not absent, f"walk misses known tracked file(s): {absent}"
    empty_roots = [r for r in ROOTS if not any(x.startswith(f"{r}/") for x in rels)]
    assert not empty_roots, f"walk reached nothing under: {empty_roots}"
    assert len(files) > 500, len(files)
    return files


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_pattern_shapes():
    assert _DATED.search("docs/COMPETITOR_LIFT_2026-06-18_R2.md")
    assert _DATED.search("docs/_archive/COMPETITOR_LIFT_2026-05-30.md")
    assert not _DATED.search("docs/COMPETITOR_LIFT_<YYYY-MM-DD>.md")


def test_walk_is_not_empty():
    files = _walk()
    hits = [p for p in files if _DATED.search(_flat(p))]
    assert len(hits) >= len(EXPECTED)


def test_walk_skips_untracked_trees():
    """The universe is the git index: no gitignored runtime tree is read.

    The repo-copy export is excluded by segment on every path; with a readable
    index every walked file must also be IN it, which is what keeps the
    gitignored lane reports under ops/loop/control/ out.
    """
    rels = [relative_posix(p, REPO) for p in _walk()]
    assert not [r for r in rels if "responder_export" in r.split("/")]
    tracked = tracked_relpaths(str(REPO))
    if tracked is not None:
        assert not [r for r in rels if r not in tracked]


def test_scan_skips_a_gitignored_copy_but_not_a_tracked_cite(tmp_path):
    """Both sweeps read the git index, so a gitignored tree under ops/ is not
    the repo - and a tracked live file is still caught.

    The planted copy dir is deliberately NOT named ``responder_export``, so
    this proves the git-index half of tests/_repo_walk (ADR-015), not the
    EXCLUDED_DIRS name backstop. The tracked offenders prove each sweep still
    discriminates rather than skips.
    """
    base = tmp_path.resolve()
    dead = "see docs/COMPETITOR_LIFT_2026-05-30.md\n"
    cut = "see docs/COMPETITOR_LIFT_\n# 2026-06-16.md\n"
    files = {
        ".gitignore": "ops/runtime/\nops/loop/control/\n",
        "core/clean.py": "x = 1\n",
        "core/dead.py": dead,
        "tools/cut.md": cut,
        "ops/runtime/copy_0dcd/core/dead.py": dead,
        "ops/runtime/copy_0dcd/tools/cut.md": cut,
        "ops/loop/control/lane_prompts/s144_reports/r.md": dead + cut,
    }
    for rel, text in files.items():
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    for argv in (["git", "init", "-q"], ["git", "add", "-A"]):
        subprocess.run(argv, cwd=str(base), check=True, capture_output=True)
    scanned = list(_live_files(base))
    assert sorted(relative_posix(p, base) for p in scanned) == [
        "core/clean.py", "core/dead.py", "tools/cut.md"]
    assert _dead_cites(scanned, base) == [
        "core/dead.py: docs/COMPETITOR_LIFT_2026-05-30.md"]
    assert _wrapped_cites(scanned, base) == ["tools/cut.md"]


def test_every_dated_lift_cite_resolves():
    missing = _dead_cites(_walk(), REPO)
    assert not missing, "lift doc path does not resolve:\n" + "\n".join(missing)


def test_no_cite_is_wrapped_mid_name():
    """A name cut across two lines evades the one-line regex above."""
    assert _WRAPPED.search("docs/COMPETITOR_LIFT_\n2026-06-16.md")
    assert _WRAPPED.search("docs/COMPETITOR_LIFT_\n * 2026-06-16.md")
    bad = _wrapped_cites(_walk(), REPO)
    assert not bad, bad


def test_expected_files_name_the_archived_doc():
    bad = []
    for rel, doc in sorted(EXPECTED.items()):
        flat = _flat(REPO / rel)
        if f"docs/_archive/{doc}" not in flat:
            bad.append(rel)
        elif not (REPO / "docs" / "_archive" / doc).is_file():
            bad.append(f"{rel} (archived doc missing)")
    assert not bad, bad


def test_ttk_cite_names_the_section_not_lines():
    for rel in ("dashboard/routes_ds_combo.py", "web/js/panels/ds_combo.js",
                "tests/test_routes_ds_combo_ttk_t2f3.py",
                "tests/test_ds_combo_ttk_panel_t2f3.py"):
        flat = _flat(REPO / rel)
        assert "lines 114-121" not in flat, rel
        assert "T2-F3" in flat, rel
    heading = [
        line for line in (REPO / "docs" / "_archive"
                          / "COMPETITOR_LIFT_2026-06-08.md"
                          ).read_text(encoding="utf-8").splitlines()
        if line.startswith("#### T2-F3 - ")]
    assert len(heading) == 1 and "time-to-kill" in heading[0]
