"""RM-1399 - core/ward_cue.py names only files that exist.

Measured 2026-11-04 by resolving every repo-relative path named in a tracked
non-test .py comment or docstring against the git index: core/ward_cue.py (and
the comment block of tests/test_ward_cue.py) pointed at two files that are
gone.

- dashboard/_state_cooldowns.py was removed in the 2026-08-11 Riot compliance
  change (dashboard/_state_builder.py records the removal); it was cited as
  the place the "no ward / trinket cast events" fact is documented.
- web/js/panels/ward_cue.js was deleted as a frontend orphan (the backend was
  kept on purpose); it was cited as the owner of the edge detection and pulse,
  which made the module read as live-consumed when nothing in web/ reads
  `ward_cue` today.

The module now says the panel is gone, that the backend was kept, and where
the teardown decision lives. This pins (a) every repo path the two files name
resolves in the index, (b) the module still carries the no-consumer note, (c)
the claim stays true: no tracked web/ file reads `ward_cue`, and the
liveclient builder still ships the field (if either flips, the note must be
rewritten, not the guard loosened), (d) the path pattern bites a dead path and
spares a live one.
"""
from __future__ import annotations

import re

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

FILES = ("core/ward_cue.py", "tests/test_ward_cue.py")

_PATH = re.compile(
    r"(?<![\w/.\-])((?:core|dashboard|web|tools|ops|docs|lib|agents)"
    r"/[\w./\-]+\.(?:py|md|js|css|json|ps1))\b")


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_bytes().decode("utf-8")


_PATTERNS = ("*.py", "*.md", "*.js", "*.mjs", "*.css", "*.json", "*.ps1",
             "*.html")


def _tracked() -> set[str]:
    return {relative_posix(p) for p in repo_files(REPO_ROOT, _PATTERNS)}


def _dead_paths(text: str, tracked: set[str]) -> list[str]:
    return sorted({m.group(1) for m in _PATH.finditer(text)
                   if m.group(1) not in tracked})


@pytest.mark.parametrize("rel", FILES)
def test_every_named_repo_path_exists(rel):
    tracked = _tracked()
    assert "core/ward_producer.py" in tracked  # an empty walk cannot pass
    assert _dead_paths(_read(rel), tracked) == [], rel


def test_the_module_carries_the_no_consumer_note():
    text = _read("core/ward_cue.py")
    assert "nothing in web/ reads the field today" in text
    assert "docs/LIVE_GAME_GATED_SYNC.md" in text
    assert "dashboard/_state_cooldowns.py" not in text
    assert "web/js/panels/ward_cue.js" not in text


def test_the_note_is_still_true():
    web = [rel for rel in (relative_posix(p)
                for p in repo_files(REPO_ROOT, _PATTERNS))
           if rel.startswith("web/") and rel.endswith((".js", ".mjs", ".html"))]
    assert "web/js/panels/objective_chips.js" in web  # walk is not empty
    readers = [rel for rel in web if "ward_cue" in _read(rel)
               and not rel.endswith(("objective_chips.js",
                                     "objective_gauges.js"))]
    assert readers == [], readers
    assert "compute_ward_cue" in _read("dashboard/_liveclient.py")


def test_the_pattern_bites_dead_and_spares_live():
    tracked = {"core/ward_producer.py"}
    assert _dead_paths("see dashboard/_state_cooldowns.py now", tracked) == [
        "dashboard/_state_cooldowns.py"]
    assert _dead_paths("see core/ward_producer.py now", tracked) == []
