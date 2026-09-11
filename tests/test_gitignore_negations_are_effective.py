"""Every `!` line in `.gitignore` must actually re-include its path.

MEASURED 2026-09-10: `!agents/state/resolved_decisions.json` was INERT. Git
cannot re-include a file whose PARENT DIRECTORY is excluded, and the rule above
it was a bare `agents/state/`. The `!` line was present, read as protection,
and did nothing - the file survived only because it was already tracked.

The failure this guards is silent in the worst way: `git add` on a re-added
copy REFUSES, exits 0, and stages nothing.

THREE DISPOSITIONS, kept apart on purpose. Parsing `.gitignore` needs no git,
so the census arm runs unconditionally and CHECKED-AND-FOUND-NOTHING is
distinguishable from COULD-NOT-CHECK. Only the effectiveness arm shells out,
and it SKIPS with a reason when git is absent rather than erroring - an
ungated `subprocess.run(..., check=True)` here would turn a missing git into a
false RED, which is the conflation this repo audited in others.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = REPO_ROOT / ".gitignore"

_GIT = shutil.which("git")


def _negations() -> list[tuple[int, str]]:
    """Return (1-indexed line number, path) for every negation line."""
    out: list[tuple[int, str]] = []
    text = GITIGNORE.read_text(encoding="utf-8")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line.startswith("!") and len(line) > 1:
            out.append((lineno, line[1:]))
    return out


def test_the_census_selects_a_real_corpus() -> None:
    """Anti-vacuous control: an empty parse must not pass the arm below.

    Deliberately git-free, so a missing git cannot convert this guard against a
    false GREEN into a false RED.
    """
    assert GITIGNORE.is_file(), f"{GITIGNORE} is missing"
    found = _negations()
    assert found, "parsed zero negation lines - the parser, not the file, is wrong"


@pytest.mark.skipif(_GIT is None, reason="git not on PATH - ignore status is unresolvable without it")
def test_every_gitignore_negation_actually_re_includes_its_path() -> None:
    inert: list[str] = []
    for lineno, path in _negations():
        # No check=True: exit 1 is the PASSING answer here (not ignored), and
        # exit 0 means the negation lost to an earlier rule.
        proc = subprocess.run(
            [_GIT, "check-ignore", "-q", "--no-index", "--", path],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if proc.returncode not in (0, 1):
            pytest.skip(f"git check-ignore returned {proc.returncode} - could not check")
        if proc.returncode == 0:
            inert.append(f".gitignore:{lineno} !{path}")

    assert not inert, (
        "these negations are INERT - the path is still ignored despite the `!`. "
        "Most likely a PARENT DIRECTORY is excluded (`dir/` rather than `dir/*`), "
        "which git cannot re-include from: " + "; ".join(inert)
    )
