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
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOTS = ("core", "dashboard", "web", "tests", "ops", "tools")
SUFFIXES = {".py", ".js", ".css", ".md", ".html", ".mjs", ".ps1"}
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


def _live_files():
    for root in ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            if (path.suffix in SUFFIXES and path.is_file()
                    and "__pycache__" not in path.parts
                    and "node_modules" not in path.parts):
                yield path


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_pattern_shapes():
    assert _DATED.search("docs/COMPETITOR_LIFT_2026-06-18_R2.md")
    assert _DATED.search("docs/_archive/COMPETITOR_LIFT_2026-05-30.md")
    assert not _DATED.search("docs/COMPETITOR_LIFT_<YYYY-MM-DD>.md")


def test_walk_is_not_empty():
    files = list(_live_files())
    assert len(files) > 500
    hits = [p for p in files if _DATED.search(_flat(p))]
    assert len(hits) >= len(EXPECTED)


def test_every_dated_lift_cite_resolves():
    missing = []
    for path in _live_files():
        rel = path.relative_to(REPO).as_posix()
        if rel in QUOTES_DEAD_PATH:
            continue
        for m in _DATED.finditer(_flat(path)):
            if not (REPO / m.group(0)).is_file():
                missing.append(f"{rel}: {m.group(0)}")
    assert not missing, "lift doc path does not resolve:\n" + "\n".join(
        sorted(set(missing)))


def test_no_cite_is_wrapped_mid_name():
    """A name cut across two lines evades the one-line regex above."""
    wrapped = re.compile(r"COMPETITOR_LIFT_[ \t]*\r?\n[ \t#*/]*\d{4}-\d{2}")
    assert wrapped.search("docs/COMPETITOR_LIFT_\n2026-06-16.md")
    assert wrapped.search("docs/COMPETITOR_LIFT_\n * 2026-06-16.md")
    bad = [path.relative_to(REPO).as_posix() for path in _live_files()
           if path.relative_to(REPO).as_posix() not in QUOTES_DEAD_PATH
           and wrapped.search(path.read_text(encoding="utf-8"))]
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
