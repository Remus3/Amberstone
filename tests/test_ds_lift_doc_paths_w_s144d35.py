"""Guard: every competitor-lift doc cited in the DS package resolves (w).

Measured 2026-10-30 at ENGINE 1.290.0 (RM-1115, DS-package half). The
dated lift docs moved from ``docs/`` to ``docs/_archive/``, but
``combo.py``, ``dps_sweep.py``, ``spike_markers.py`` and the two tests
``test_combo_2026_05_30.py`` / ``test_spike_markers_2026_05_30.py`` still
cited ``docs/COMPETITOR_LIFT_2026-05-30.md``, a path that no longer
exists. The cites now name the archived copy and keep their section id
("Lift 2" / "Lift 3" / "Lift 4"), which still heads the matching section
there.

The tests below fail on any lift-doc path in the DS package that does not
resolve on disk, and pin each section id to the subject its module
implements.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
LIFT = "COMPETITOR_LIFT_2026-05-30.md"
ARCHIVED = REPO / "docs" / "_archive" / LIFT
_LIFT_PATH = re.compile(r"docs/(?:[\w.-]+/)*COMPETITOR_LIFT_[\w.-]+?\.md")

# file -> (section id, a word its archived section heading must carry)
TARGETS = {
    "combo.py": ("Lift 2", "combo"),
    "dps_sweep.py": ("Lift 3", "stat-sweep"),
    "spike_markers.py": ("Lift 4", "power-spike"),
    "tests/test_combo_2026_05_30.py": ("Lift 2", "combo"),
    "tests/test_spike_markers_2026_05_30.py": ("Lift 4", "power-spike"),
}


def _ds_files():
    return sorted(p for p in DS.rglob("*.py")
                  if "__pycache__" not in p.parts)


def test_pattern_matches_both_shapes():
    for sample in (
        f"``docs/{LIFT}`` \"Lift 2\"",
        f"spec: docs/_archive/{LIFT} \"Lift 3\".",
        "(docs/_archive/COMPETITOR_LIFT_2026-06-08.md T1-F3)",
    ):
        assert _LIFT_PATH.search(sample), sample
    assert _LIFT_PATH.search(f"docs/{LIFT}").group(0) == f"docs/{LIFT}"


def test_walk_is_not_empty():
    files = _ds_files()
    assert len(files) > 100
    hits = [p for p in files
            if _LIFT_PATH.search(p.read_text(encoding="utf-8"))]
    assert len(hits) >= len(TARGETS)


def test_every_cited_lift_doc_resolves():
    missing = []
    for path in _ds_files():
        text = path.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            for m in _LIFT_PATH.finditer(line):
                if not (REPO / m.group(0)).is_file():
                    rel = path.relative_to(REPO).as_posix()
                    missing.append(f"{rel}:{n}: {m.group(0)}")
    assert not missing, "lift doc path does not resolve:\n" + "\n".join(
        missing)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_cites_the_archived_section(name):
    section, _ = TARGETS[name]
    flat = " ".join((DS / name).read_text(encoding="utf-8").split())
    assert f"docs/_archive/{LIFT}" in flat, name
    assert f'"{section}"' in flat, name
    assert f"docs/{LIFT}" not in flat, name


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_section_heads_the_subject(name):
    section, word = TARGETS[name]
    headings = [line for line in
                ARCHIVED.read_text(encoding="utf-8").splitlines()
                if line.startswith(f"## {section} - ")]
    assert len(headings) == 1, (section, headings)
    assert word in headings[0], (name, headings[0])
