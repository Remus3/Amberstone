"""RM-763: a leading `./` is a PREFIX, never a character set.

`str.lstrip("./")` drops every leading `.` and `/` CHARACTER, so the dot that
belongs to a name goes too: `.github/CONTRIBUTING.md` became
`github/CONTRIBUTING.md`, which is not a segment-boundary suffix of the
tracked path, so `tools/md_guard_selector.py` (`_hits`) never resolved a
`.github/` literal. Four tracked `.md` files live under `.github/`.

The sibling sweep found the same expression in `tools/ci_watchdog.py`
(`touches_frozen`) and `tools/stop_claim_gate.py` (`_same_file`); both are
pinned here too. The fix strips leading `./`, `../` and `/` SEGMENTS
(repeated `removeprefix`), so every shape the character-set strip resolved
on purpose still resolves - only a dot that starts a NAME survives now.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools import ci_watchdog as cw
from tools import md_guard_selector as mgs
from tools import stop_claim_gate as scg

REPO_ROOT = Path(__file__).resolve().parent.parent

_TRACKED_MD = [
    ".github/CONTRIBUTING.md",
    ".github/SECURITY.md",
    "docs/LEDGER.md",
    "ROADMAP.md",
]


def _hits(literal: str) -> bool:
    return mgs._hits(literal, mgs._md_suffix_index(_TRACKED_MD), _TRACKED_MD)


# --------------------------------------------------------------------------- #
# tools/md_guard_selector.py `_hits`
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("literal", [
    ".github/CONTRIBUTING.md",
    "./.github/CONTRIBUTING.md",
    ".github\\SECURITY.md",
])
def test_selector_resolves_a_dot_directory_literal(literal):
    """The defect: the leading dot of `.github` was stripped."""
    assert _hits(literal), f"{literal!r} names a tracked .md but does not select"


@pytest.mark.parametrize("literal", [
    "./docs/LEDGER.md",
    "./././docs/LEDGER.md",
    ".\\docs\\LEDGER.md",
    "../docs/LEDGER.md",
    "/docs/LEDGER.md",
    ".//ROADMAP.md",
    "docs/LEDGER.md",
    "LEDGER.md",
])
def test_selector_still_strips_leading_dot_segments(literal):
    """Every prefix shape the character-set strip resolved still resolves; a
    false negative is the costly direction for this selector."""
    assert _hits(literal), f"{literal!r} no longer selects"


@pytest.mark.parametrize("literal", [
    ".docs/LEDGER.md",
    "..ROADMAP.md",
    "github/CONTRIBUTING.md",
])
def test_selector_keeps_a_dot_that_starts_a_name(literal):
    """`.docs/` is a different directory from `docs/`: the character-set strip
    resolved it to the tracked path, which is a different file."""
    assert not _hits(literal), f"{literal!r} resolved to a path it does not name"


def test_live_selector_reports_the_dot_github_literal():
    """End to end on the real tree: `tests/phase7_polish/test_commit_msg_check.py`
    carries the literal `.github/CONTRIBUTING.md`, and the explain map must
    credit that literal, not only the bare basename."""
    module = "tests/phase7_polish/test_commit_msg_check.py"
    literal = ".github/CONTRIBUTING.md"
    source = (REPO_ROOT / module).read_text(encoding="utf-8")
    assert f'"{literal}"' in source, f"{module} no longer carries {literal!r}"
    detail = mgs.select_md_guard_modules(REPO_ROOT, explain=True)
    assert literal in detail.get(module, []), (
        f"{module} selected by {detail.get(module)!r}, not by {literal!r}"
    )


# --------------------------------------------------------------------------- #
# sibling: tools/ci_watchdog.py `touches_frozen`
# --------------------------------------------------------------------------- #
def test_touches_frozen_keeps_a_dot_that_starts_a_name():
    """`.app/__init__.py` is not the frozen `app/__init__.py`."""
    assert cw.touches_frozen([".app/__init__.py", ".main.py"]) == []


@pytest.mark.parametrize("path", ["./main.py", "../main.py", "/main.py", ".\\main.py"])
def test_touches_frozen_still_strips_leading_dot_segments(path):
    assert cw.touches_frozen([path]) == ["main.py"]


# --------------------------------------------------------------------------- #
# sibling: tools/stop_claim_gate.py `_same_file`
# --------------------------------------------------------------------------- #
def test_same_file_keeps_the_dot_of_a_dot_directory_claim():
    """A claim about `.github/workflows/ci.yml` is not backed by an edit of
    some other `github/workflows/ci.yml`."""
    assert not scg._same_file(".github/workflows/ci.yml", ["docs/github/workflows/ci.yml"])
    assert scg._same_file(".github/workflows/ci.yml", [".github/workflows/ci.yml"])


@pytest.mark.parametrize("claim", ["./tools/x.py", "../tools/x.py", "/tools/x.py", ".\\tools\\x.py"])
def test_same_file_still_strips_leading_dot_segments(claim):
    assert scg._same_file(claim, ["tools/x.py"])
