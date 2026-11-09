"""S144-P-322 - a TODO / FIXME / HACK marker in production .py names where it is tracked.

A bare `TODO: do X later` in a comment or docstring is a promise with no owner:
nothing reads it, so nothing ever closes it. Measured 2026-11-07 over every
tracked production .py (comments via tokenize, module / class / function
docstrings via ast): six markers. Two carry a tracker already (a parenthesised
tag, or a roadmap item number); one was bare in `core/post_game_score.py`
(`TODO: retrain on N>=20 timelines`), which the gated-sync doc already tracks as
G7-07, so the docstring now cites it; three are the DS engine's own
`ability_dps.py` module-level TODO, which names its follow-up in prose and
belongs to the DS lane, so it is a named baseline entry, not a fix here.

A marker is "tracked" when its text carries a tracker token (`TRACKER`) or the
marker is followed straight away by `(`. The baseline only shrinks: an entry
that stops offending fails `test_baseline_is_exact` until it is dropped. Test
code, `docs/_archive` and the vendored `ops/fleet_kit` are out of scope.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check

MARKER = re.compile(r"(?<![A-Za-z_\-])(TODO|FIXME|HACK)(?![A-Za-z_\-])")
TRACKER = re.compile(r"RM-\d+|\bS\d+-[A-Z]+-\d+|\bG\d+-\d+\b|\bitem \d+\b|\bROADMAP\b|\bBACKLOG\b")

# DS-lane file: the module-level TODO names its follow-up in prose. Only shrinks.
BASELINE = {
    "agents/daemon_slayer/ability_dps.py": 3,
}


def _out_of_scope(rel: str) -> bool:
    return (
        rel.startswith(("tests/", "docs/_archive/", "ops/fleet_kit/"))
        or "/tests/" in rel
    )


def bare_markers(src: str) -> list[tuple[int, str]]:
    """(line, text) of every untracked marker in comments and docstrings."""
    texts: list[tuple[int, str]] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            texts.append((tok.start[0], tok.string))
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            doc = body[0].value
            for i, line in enumerate(doc.value.split("\n")):
                texts.append((doc.lineno + i, line))
    out = []
    for lineno, text in texts:
        for m in MARKER.finditer(text):
            if text[m.end():m.end() + 1] == "(" or TRACKER.search(text):
                continue
            out.append((lineno, text.strip()))
    return sorted(set(out))


def _census() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in iter_repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if _out_of_scope(rel):
            continue
        hits = bare_markers(path.read_bytes().decode("utf-8"))
        if hits:
            found[rel] = len(hits)
    return found


def test_walker_reaches_the_tree():
    self_check()
    assert any(relative_posix(p) == "core/post_game_score.py"
               for p in iter_repo_files(REPO_ROOT, ("*.py",)))


def test_no_new_untracked_marker():
    census = _census()
    new = {f: n for f, n in census.items() if n > BASELINE.get(f, 0)}
    assert not new, new


def test_baseline_is_exact():
    census = _census()
    stale = {f: n for f, n in BASELINE.items() if census.get(f, 0) != n}
    assert not stale, stale


@pytest.mark.parametrize("src", [
    "# TODO: later\n",
    "# FIXME handle the empty case\n",
    "def f():\n    '''Doc.\n\n    HACK: swap this out.\n    '''\n",
])
def test_rule_bites_a_bare_marker(src):
    assert len(bare_markers(src)) == 1


@pytest.mark.parametrize("src", [
    "# TODO(s218-dummy-data): wire when ingest ships\n",
    "# TODO RM-123 wire the thing\n",
    "# TODO: see G7-07\n",
    "# TODO item 77 follows\n",
    "# the MASTODON and TODOS words are not markers\n",
    "x = 'TODO: a string value is data, not a comment'\n",
])
def test_rule_spares_tracked_and_non_markers(src):
    assert bare_markers(src) == []
