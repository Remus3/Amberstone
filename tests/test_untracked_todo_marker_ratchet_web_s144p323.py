"""S144-P-323 - a TODO / FIXME / HACK marker in a tracked web / script comment names where it is tracked.

Companion of S144-P-322 (which covers production .py): a bare `TODO: later` in a
`//` or `/* */` comment (.js / .mjs / .css / .html) or a `#` comment (.ps1) is a
promise with no owner. Measured 2026-11-07 over every tracked file of those
types outside `docs/_archive`: two markers. `web/js/main.js` already carries a
parenthesised tag; `web/js/panels/item_build.js` was bare (owned sub-item
values) and now cites `WP-B3`, the plan row in docs/OVERLAY_BUILD_MASTER_PLAN.md
that tracks it. The baseline is therefore empty and only a regression can fill it.

The marker and tracker grammar is imported from the P-322 guard so the two rules
cannot drift apart. Test code, `docs/_archive` and the vendored `ops/fleet_kit`
are out of scope.
"""
from __future__ import annotations

import re

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check
from tests.test_untracked_todo_marker_ratchet_s144p322 import MARKER, TRACKER

PATTERNS = ("*.js", "*.mjs", "*.css", "*.html", "*.ps1")
# Wider than P-322's tracker: `WP-B3` style work-package ids are this tree's
# overlay-plan tracker token.
WP_TRACKER = re.compile(r"\bWP-[A-Z]\d+\b")
COMMENT_START = re.compile(r"//|/\*|<!--|#|^\s*\*")

# Only shrinks (an entry that stops offending must be dropped).
BASELINE: dict[str, int] = {}


def _out_of_scope(rel: str) -> bool:
    return (
        rel.startswith(("tests/", "docs/_archive/", "ops/fleet_kit/"))
        or "/tests/" in rel
        or "/test/" in rel
        or ".test." in rel
    )


def bare_markers(src: str) -> list[tuple[int, str]]:
    """(line, text) of every untracked marker in the comment part of a line."""
    out = []
    for lineno, line in enumerate(src.split("\n"), 1):
        m = COMMENT_START.search(line)
        if not m:
            continue
        text = line[m.start():]
        for hit in MARKER.finditer(text):
            if text[hit.end():hit.end() + 1] == "(" or TRACKER.search(text) or WP_TRACKER.search(text):
                continue
            out.append((lineno, text.strip()))
    return sorted(set(out))


def _census() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in iter_repo_files(REPO_ROOT, PATTERNS):
        rel = relative_posix(path)
        if _out_of_scope(rel):
            continue
        hits = bare_markers(path.read_bytes().decode("utf-8", errors="replace"))
        if hits:
            found[rel] = len(hits)
    return found


def test_walker_reaches_the_tree():
    self_check()
    rels = {relative_posix(p) for p in iter_repo_files(REPO_ROOT, PATTERNS)}
    assert "web/js/panels/item_build.js" in rels
    assert "web/js/main.js" in rels


def test_no_new_untracked_marker():
    census = _census()
    new = {f: n for f, n in census.items() if n > BASELINE.get(f, 0)}
    assert not new, new


def test_baseline_is_exact():
    census = _census()
    stale = {f: n for f, n in BASELINE.items() if census.get(f, 0) != n}
    assert not stale, stale


@pytest.mark.parametrize("src", [
    "  // TODO: later\n",
    "/* FIXME handle the empty case */\n",
    "/*\n * HACK: swap this out.\n */\n",
    "<!-- TODO: remove -->\n",
    "# TODO: later\n",
])
def test_rule_bites_a_bare_marker(src):
    assert len(bare_markers(src)) == 1


@pytest.mark.parametrize("src", [
    "// TODO(s218-dummy-data): wire when ingest ships\n",
    "// TODO RM-123 wire the thing\n",
    "// TODO: WP-B3 owns the recipe data\n",
    "// the MASTODON and TODOS words are not markers\n",
    "const label = 'TODO: a string value is data, not a comment';\n",
])
def test_rule_spares_tracked_and_non_markers(src):
    assert bare_markers(src) == []
