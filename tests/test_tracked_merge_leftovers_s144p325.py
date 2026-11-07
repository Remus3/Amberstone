"""S144-P-325 - no merge-conflict marker and no merge / editor leftover file in the tracked tree, held at zero.

A conflict that was committed half-resolved is the quietest merge failure: ``<<<<<<< HEAD`` inside a ``.py`` is a
SyntaxError that the lane notices, but inside a ``.json`` data file, a ``.md`` doc, a ``.css`` rule or a ``.yml`` workflow
it is only a parse error at the one consumer, and most readers in this repo catch it and fall back to defaults. Three
shapes are checked over EVERY path in the git index (``docs/_archive`` and the other dated trees included: a conflict
marker is never part of a verbatim record), measured 2026-11-07 at zero:

- a line that STARTS with seven ``<`` or seven ``>`` followed by a space or the end of the line (the ``<<<<<<< HEAD`` /
  ``>>>>>>> branch`` pair git writes), in any text file;
- a line that is exactly seven ``=`` in a code or data file (``.py`` / ``.js`` / ``.json`` / ``.yml`` ...), which is the
  separator half of the same hunk. Markdown, text and rst are skipped for this one shape only, because a seven-``=``
  setext underline is legitimate there.
- a tracked path that is a merge or editor leftover: ``*.orig`` / ``*.rej`` / ``*.bak`` / ``*.swp`` / ``*.swo``, a
  trailing-``~`` backup, ``.DS_Store``, ``Thumbs.db`` or ``desktop.ini``.

Each shape has a positive control below, so a rule that stopped detecting fails loudly instead of passing for nothing.
Nothing is grandfathered: resolve the hunk or delete the file, never widen this test.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, tracked_relpaths

_TEXT_SUFFIXES = (
    ".py", ".md", ".js", ".mjs", ".css", ".html", ".json", ".yml", ".yaml", ".toml",
    ".ps1", ".bat", ".sh", ".txt", ".ahk", ".vbs", ".cfg", ".ini", ".jsonl", ".csv",
)
# The `=======` separator is ambiguous in prose (a setext underline), so it is only a marker in these.
_PROSE_SUFFIXES = (".md", ".txt", ".rst")

_HUNK_EDGE = re.compile(rb"^(?:<{7}|>{7})(?: |\r?$)", re.MULTILINE)
_HUNK_SEPARATOR = re.compile(rb"^={7}\r?$", re.MULTILINE)
_LEFTOVER_PATH = re.compile(
    r"(?:\.(?:orig|rej|bak|swp|swo)|~)$|(?:^|/)(?:\.DS_Store|Thumbs\.db|desktop\.ini)$",
    re.IGNORECASE,
)


def _marker_problem(rel: str, raw: bytes) -> str:
    """The first conflict-marker problem in ``raw`` (a file named ``rel``), or an empty string."""
    if _HUNK_EDGE.search(raw):
        return "has a <<<<<<< / >>>>>>> conflict marker line"
    if not rel.lower().endswith(_PROSE_SUFFIXES) and _HUNK_SEPARATOR.search(raw):
        return "has a bare ======= conflict separator line"
    return ""


def _tracked_paths() -> list[str]:
    tracked = tracked_relpaths(str(REPO_ROOT))
    assert tracked is not None, "git index unreadable: a guard must not pass on an unreadable index"
    return sorted(tracked)


def test_enumeration_is_not_vacuous():
    paths = _tracked_paths()
    assert len(paths) > 2000
    assert sum(1 for p in paths if p.lower().endswith(_TEXT_SUFFIXES)) > 1500


def test_no_tracked_text_file_carries_a_conflict_marker():
    offenders = []
    for rel in _tracked_paths():
        if not rel.lower().endswith(_TEXT_SUFFIXES):
            continue
        path = Path(REPO_ROOT) / rel
        if not path.is_file():
            continue
        problem = _marker_problem(rel, path.read_bytes())
        if problem:
            offenders.append(f"{relative_posix(path)}: {problem}")
    assert offenders == []


def test_no_tracked_path_is_a_merge_or_editor_leftover():
    assert [rel for rel in _tracked_paths() if _LEFTOVER_PATH.search(rel)] == []


@pytest.mark.parametrize(
    ("rel", "raw"),
    [
        ("a.py", b"x = 1\n<<<<<<< HEAD\nx = 2\n"),
        ("a.json", b'{"a": 1}\n>>>>>>> lane/repo\n'),
        ("a.md", b"text\n<<<<<<<\nmore\n"),
        ("a.css", b"a {}\r\n<<<<<<< HEAD\r\n"),
        ("a.py", b"x = 1\n=======\nx = 2\n"),
        ("a.yml", b"a: 1\n=======\r\nb: 2\n"),
    ],
)
def test_marker_checker_flags_each_shape(rel, raw):
    assert _marker_problem(rel, raw) != ""


@pytest.mark.parametrize(
    ("rel", "raw"),
    [
        ("a.md", b"Title\n=======\ntext\n"),
        ("a.txt", b"=======\n"),
        ("a.py", b"# ======= banner\nx = '<<<<<<< not at line start'\n"),
        ("a.py", b"x = 1\n<<<<<<<<  eight\n"),
        ("a.py", b"x = 1\n==== short\n========\n"),
        ("a.md", b"```\n  <<<<<<< indented in a fence\n```\n"),
    ],
)
def test_marker_checker_passes_lookalikes(rel, raw):
    assert _marker_problem(rel, raw) == ""


@pytest.mark.parametrize(
    "rel",
    ["a.orig", "dir/b.rej", "c.BAK", "d.swp", "e.swo", "notes.txt~", ".DS_Store", "x/Thumbs.db", "desktop.ini"],
)
def test_leftover_path_checker_flags_each_shape(rel):
    assert _LEFTOVER_PATH.search(rel)


@pytest.mark.parametrize("rel", ["a.py", "backup.md", "orig.txt", "docs/bakery.md", "x/thumbs_db.py"])
def test_leftover_path_checker_passes_lookalikes(rel):
    assert not _LEFTOVER_PATH.search(rel)
