"""RM-407 - every tracked test tree must be named by a CI pytest invocation.

WHAT WAS MEASURED
-----------------
2026-09-11 at HEAD 591bf1e0d. `.github/workflows/ci.yml` carried exactly two
invocations that name a test TREE rather than individual files, both reading
`pytest tests/ agents/daemon_slayer/tests/`. The repo carries four collection
roots. Two of them - `agents/agent3_testing/suite` and `tools/tests` - were
named by NOTHING, in either job, so their tests had never gated a push, a pull
request or a nightly. They collect (359 and 348 nodeids on that HEAD), they are
tracked, and they were invisible.

That is the same failure class RM-119 closed for the Daemon Slayer tree: a test
that no job runs is not a weak signal, it is zero signal, and nothing about the
repo's surface distinguishes it from a passing one. RM-119 was found by hand.
This guard exists so the next one is not.

WHY THE DISPOSITION TABLE IS THE DATA THE ASSERTIONS ITERATE
------------------------------------------------------------
`_COLLECTION_ROOTS` is joined to the real enumeration and to the real parse of
`ci.yml`, never compared against a restated literal list. A literal checked
against itself proves nothing. Concretely, all four mutations red:

  * delete a row                -> its tree is discovered and unclaimed
  * WIRED -> EXCEPTED, step kept -> the row claims absence, CI still names it
  * EXCEPTED -> WIRED, no step   -> the row claims coverage, CI names nothing
  * a new orphan tree appears    -> discovered and claimed by no row

THE GLOB TRAP THIS GUARD MUST NOT FALL INTO
-------------------------------------------
`git ls-files "*test_*.py"` reports a SIXTEENTH directory, bare `tools`, whose
only match is `tools/pytest_guard.py` - the Claude PostToolUse hook script,
which matches only because "pytest_guard" contains the substring "test_". A
guard built on that pathspec files a phantom orphan tree it can never close.
The discovery predicate here is therefore BASENAME-anchored (`test_*.py` or
`*_test.py` as the file name, via `tests/_repo_walk`'s rglob), and
`test_discovery_predicate_is_basename_anchored` pins that precision so a future
loosening back to a substring match reds this file instead of inventing work.

COVERAGE IS BY PREFIX, NOT BY EXACT STRING
------------------------------------------
`pytest tests/` already collects `tests/phase2_smoke`, `tests/rc2_l3` and nine
other subdirectories transitively. An exact-match model would report all eleven
as orphans. A target covers a tree when it IS that tree or is an ancestor of it.
Targets that name a FILE or a nodeid (`tests/test_drift_guard.py::Foo`, of which
ci.yml has several) deliberately cover no tree at all - running four hand-picked
files is exactly the state RM-119 found insufficient.

WHAT THIS GUARD CANNOT DO
-------------------------
1. It proves a tree is NAMED, not that the job RUNS or that the step passes. A
   step guarded by an `if:` that never fires still reads as coverage here.
2. It reads `.github/workflows/ci.yml` only. A tree wired from a different
   workflow file reads as an orphan.
3. It cannot see an UNTRACKED tree - `tests/_repo_walk` enumerates the git index
   first (ADR-015), so a brand-new test directory is invisible until it is
   staged. That is the right default for a repo guard, but the window between
   writing a tree and staging it is a window this cannot cover.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests import _repo_walk

REPO_ROOT = _repo_walk.REPO_ROOT
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# ---------------------------------------------------------------------------
# THE DISPOSITION TABLE. Columns: collection root, disposition, mechanism.
#
# A WIRED row asserts `ci.yml` names this tree (or an ancestor of it) as a
# pytest target, and carries an EMPTY mechanism. An EXCEPTED row asserts the
# opposite - that CI deliberately does NOT collect it - and must say WHY.
#
# Moving a tree from WIRED to EXCEPTED is a ONE-ROW edit here (flip the
# disposition, fill in the mechanism) plus deleting its step from ci.yml.
# Doing either half alone reds this file, which is the point.
# ---------------------------------------------------------------------------
_WIRED = "WIRED"
_EXCEPTED = "EXCEPTED"

_COLLECTION_ROOTS = (
    ("tests", _WIRED, ""),
    ("agents/daemon_slayer/tests", _WIRED, ""),
    ("agents/agent3_testing/suite", _WIRED, ""),
    ("tools/tests", _WIRED, ""),
)

# The bare `tools` directory the substring pathspec invents, and the single file
# that produces it. Pinned as data so the precision arm names the real offender
# rather than asserting a bare count.
_PHANTOM_TREE = "tools"
_PHANTOM_SOURCE = "tools/pytest_guard.py"

# A floor, not the measured 15. Counts drift with every new subdirectory; what
# must never happen is the enumeration collapsing to a handful and every
# coverage assertion below passing over an empty set.
_MIN_DISCOVERED_TREES = 10

# Trees whose absence means the enumeration broke rather than the repo changed.
_DISCOVERY_ANCHORS = ("tests", "agents/daemon_slayer/tests", "tools/tests")

# Shell variable assignments that may precede the command word, e.g.
# `RC_REQUIRE_HOOK_GATE=1 pytest ...` at ci.yml:421.
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _logical_lines(text: str) -> list[str]:
    """Physical lines joined across trailing-backslash continuations.

    Both tree invocations in ci.yml wrap (`-n auto --dist loadfile` sits on the
    continuation line), and two of the named-file steps put every path on its
    own continuation line, so a per-physical-line parser sees a `pytest` with no
    arguments and silently reports zero targets.

    Comment lines are dropped BEFORE joining, deliberately. ci.yml quotes
    `pytest tests/` inside prose at :93, :181 and :260 and shows a literal
    `pytest test_u2500_candidate_sweep.py ...` at :234; a parser that reads
    those manufactures coverage out of documentation.
    """
    out: list[str] = []
    pending: str | None = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if pending is None:
            if stripped.startswith("#"):
                continue
            pending = stripped
        else:
            pending = pending + " " + stripped
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
        else:
            out.append(pending)
            pending = None
    if pending is not None:
        out.append(pending)
    return out


def _pytest_targets(text: str) -> list[str]:
    """Every path-shaped argument of every `pytest` command in ``text``.

    Takes TEXT rather than a path so the fixture arms can prove this function
    reads its input instead of returning a constant.

    The command word must be exactly `pytest` after any leading env
    assignments, which is what keeps `pip install pytest pytest-asyncio ...`
    (ci.yml:113 and :287) out of the result. An argument counts as a target only
    when it looks like a path, which is what keeps the values of separated
    options - `-n auto`, `--dist loadfile` - out of it.
    """
    found: set[str] = set()
    for line in _logical_lines(text):
        tokens = line.split()
        head = 0
        while head < len(tokens) and _ENV_ASSIGNMENT.match(tokens[head]):
            head += 1
        if head >= len(tokens) or tokens[head] != "pytest":
            continue
        for token in tokens[head + 1:]:
            if token.startswith("-"):
                continue
            if "/" in token or token.endswith(".py"):
                found.add(token.replace("\\", "/").rstrip("/"))
    return sorted(found)


def _covers(target: str, tree: str) -> bool:
    """True when running ``target`` collects everything under ``tree``.

    A target naming a file or a nodeid covers no tree: `tests/test_x.py` is
    neither equal to `tests` nor an ancestor of it.
    """
    return tree == target or tree.startswith(target + "/")


def _is_covered(targets: list[str], tree: str) -> bool:
    return any(_covers(target, tree) for target in targets)


def _discovered_trees() -> list[str]:
    """Every tracked directory holding at least one real test module.

    `tests/_repo_walk` is mandatory here per ADR-015 - the git index is the
    universe and EXCLUDED_DIRS is the backstop - and its rglob patterns are
    matched against the BASENAME, which is what excludes `tools/pytest_guard.py`.
    """
    files = _repo_walk.repo_files(
        REPO_ROOT, patterns=("test_*.py", "*_test.py"), tracked_only=True
    )
    trees = set()
    for path in files:
        rel = _repo_walk.relative_posix(path, REPO_ROOT)
        trees.add(rel.rsplit("/", 1)[0] if "/" in rel else "")
    trees.discard("")
    return sorted(trees)


def _ci_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


# A workflow that wires `tests/` and nothing else - the state this repo was in
# before RM-407. Used to prove the parser answers from its input.
_FIXTURE_TESTS_ONLY = """
jobs:
  check:
    steps:
      - name: suite
        run: |
          # a commented invocation that must NOT count as coverage:
          #   pytest tools/tests -q
          pytest tests/ -q --tb=short --timeout=300 \\
            -n auto --dist loadfile
"""

# The same workflow with one orphan tree wired, so a coverage flip is
# attributable to the text and not to the function.
_FIXTURE_ONE_ORPHAN_WIRED = _FIXTURE_TESTS_ONLY + """
      - name: orphan
        run: |
          pytest tools/tests -q --tb=short --timeout=300
"""


# ---------------------------------------------------------------------------
# Vacuity arms. Every assertion below this point iterates one of three sets;
# an empty set would make all of them pass.
# ---------------------------------------------------------------------------

def test_discovery_is_not_vacuous():
    assert _repo_walk.tracked_relpaths(str(REPO_ROOT)) is not None, (
        "git ls-files did not answer for the repo root, so the enumeration "
        "below fell back to directory skips alone. A guard that reports "
        "'no orphan trees' from an unreadable index is machine-local and "
        "always-green - fix the checkout, do not relax this."
    )
    _repo_walk.self_check(REPO_ROOT)
    trees = _discovered_trees()
    assert len(trees) >= _MIN_DISCOVERED_TREES, (
        f"only {len(trees)} test trees discovered ({trees}); an empty or "
        "collapsed enumeration makes every coverage assertion here pass over "
        "nothing"
    )
    missing = [a for a in _DISCOVERY_ANCHORS if a not in trees]
    assert not missing, f"discovery lost known test trees: {missing}"


def test_discovery_predicate_is_basename_anchored():
    """The `tools` phantom must stay out, and `tools/tests` must stay in.

    Loosening the predicate to a substring match - the shape of
    `git ls-files "*test_*.py"` - files a sixteenth orphan tree that can never
    be closed, because its only member is a hook script.
    """
    tracked = _repo_walk.tracked_relpaths(str(REPO_ROOT))
    assert tracked is not None
    assert _PHANTOM_SOURCE in tracked, (
        f"{_PHANTOM_SOURCE} is no longer tracked, so this arm no longer "
        "exercises the substring trap it exists to pin"
    )
    trees = _discovered_trees()
    assert _PHANTOM_TREE not in trees, (
        f"{_PHANTOM_TREE!r} was discovered as a test tree. Its only "
        f"substring match is {_PHANTOM_SOURCE}, a PostToolUse hook script and "
        "not a test module. The discovery predicate has been loosened off the "
        "file BASENAME."
    )
    assert "tools/tests" in trees, (
        "tools/tests vanished from discovery - the predicate was tightened "
        "past the point of seeing a real tree"
    )


def test_ci_workflow_parse_is_not_vacuous():
    assert CI_WORKFLOW.is_file(), f"{CI_WORKFLOW} is missing"
    text = _ci_text()
    assert len(text) > 1000, "ci.yml is implausibly short; the read failed open"
    targets = _pytest_targets(text)
    assert targets, "parsed zero pytest targets out of ci.yml"
    for anchor in ("tests", "agents/daemon_slayer/tests"):
        assert anchor in targets, (
            f"ci.yml no longer names {anchor!r} as a pytest target. Either the "
            "workflow changed shape or the parser stopped reading it."
        )


def test_parser_answers_from_its_input_not_from_a_constant():
    """Arm (d): a fixture with a known-missing tree must report it uncovered."""
    before = _pytest_targets(_FIXTURE_TESTS_ONLY)
    assert before == ["tests"], (
        f"fixture parse returned {before}; expected exactly ['tests'] - the "
        "commented `pytest tools/tests` line must not be read as coverage"
    )
    assert _is_covered(before, "tests/phase2_smoke"), (
        "prefix coverage broke: `pytest tests/` does collect tests/phase2_smoke"
    )
    assert not _is_covered(before, "tools/tests")
    assert not _is_covered(before, "agents/agent3_testing/suite")

    after = _pytest_targets(_FIXTURE_ONE_ORPHAN_WIRED)
    assert _is_covered(after, "tools/tests"), (
        "adding a real `pytest tools/tests` step to the fixture did not change "
        "the verdict, so the coverage answer does not depend on the text"
    )
    assert not _is_covered(after, "agents/agent3_testing/suite")


def test_a_named_file_target_does_not_cover_its_tree():
    """RM-119's finding, pinned: four hand-picked files are not tree coverage."""
    targets = _pytest_targets(
        "          pytest tests/test_smart_quote_hygiene.py -q\n"
    )
    assert targets == ["tests/test_smart_quote_hygiene.py"]
    assert not _is_covered(targets, "tests")


# ---------------------------------------------------------------------------
# The join. Each arm below iterates the disposition table against ground truth.
# ---------------------------------------------------------------------------

def test_every_discovered_tree_is_claimed_by_a_root_row():
    roots = [row[0] for row in _COLLECTION_ROOTS]
    unclaimed = [
        tree for tree in _discovered_trees()
        if not any(_covers(root, tree) for root in roots)
    ]
    assert not unclaimed, (
        f"test trees claimed by no row in _COLLECTION_ROOTS: {unclaimed}. "
        "Add a WIRED row plus a ci.yml step that runs the tree, or an "
        "EXCEPTED row stating why CI must not collect it."
    )


@pytest.mark.parametrize("root,disposition,mechanism", _COLLECTION_ROOTS)
def test_every_root_row_names_a_tree_that_exists(root, disposition, mechanism):
    trees = _discovered_trees()
    assert any(_covers(root, tree) for tree in trees), (
        f"_COLLECTION_ROOTS row {root!r} matches no tracked test tree. The "
        "directory was renamed, deleted, or emptied - fix the row rather than "
        "leaving CI running a path that collects nothing."
    )


def test_wired_roots_are_named_by_a_ci_tree_invocation():
    """Filtered by a comprehension, never by ``pytest.skip``.

    A per-row parametrization that skips the rows it does not apply to reports
    a SKIP - a green tick - for every row, and the arm is then always-passing
    by construction. `tests/test_skip_condition_hygiene.py` rejects that shape
    repo-wide and rejected the first draft of this file for it.
    """
    targets = _pytest_targets(_ci_text())
    wired = [row[0] for row in _COLLECTION_ROOTS if row[1] == _WIRED]
    assert wired, (
        "_COLLECTION_ROOTS declares no WIRED root at all, so CI runs no test "
        "tree and this arm has nothing to check"
    )
    offenders = [root for root in wired if not _is_covered(targets, root)]
    assert not offenders, (
        f"declared WIRED but named by no pytest invocation in "
        f"{CI_WORKFLOW.name}: {offenders}. Parsed targets: {targets}. Either "
        "restore the step, or flip the row to EXCEPTED with a stated mechanism."
    )


def test_excepted_roots_are_absent_from_ci():
    """The stale-exception arm.

    It genuinely has nothing to iterate while every root is WIRED, which is the
    current state and the desirable one. It is not load-bearing for vacuity -
    `test_every_discovered_tree_is_claimed_by_a_root_row` is - and it exists so
    that flipping a row to EXCEPTED while leaving its step in place reds
    instead of recording a lie.
    """
    targets = _pytest_targets(_ci_text())
    excepted = [row[0] for row in _COLLECTION_ROOTS if row[1] == _EXCEPTED]
    offenders = [root for root in excepted if _is_covered(targets, root)]
    assert not offenders, (
        f"declared EXCEPTED - deliberately not collected - yet named by "
        f"{CI_WORKFLOW.name}: {offenders}. The exception is stale: flip the row "
        "back to WIRED, or delete the step."
    )


@pytest.mark.parametrize("root,disposition,mechanism", _COLLECTION_ROOTS)
def test_disposition_and_mechanism_agree(root, disposition, mechanism):
    assert disposition in (_WIRED, _EXCEPTED), (
        f"{root!r} carries unknown disposition {disposition!r}"
    )
    if disposition == _EXCEPTED:
        assert mechanism.strip(), (
            f"{root!r} is EXCEPTED with no stated mechanism. An exception "
            "nobody can evaluate is indistinguishable from an oversight - say "
            "what prevents CI from collecting this tree."
        )
    else:
        assert not mechanism, (
            f"{root!r} is WIRED but carries mechanism {mechanism!r}. A "
            "mechanism describes why a tree is NOT collected; leaving one on a "
            "WIRED row means a flip was done by halves."
        )


def test_root_rows_are_unique_and_sorted_by_nothing_but_uniqueness():
    roots = [row[0] for row in _COLLECTION_ROOTS]
    assert len(roots) == len(set(roots)), (
        f"duplicate rows in _COLLECTION_ROOTS: {roots}"
    )
    for root in roots:
        assert not root.endswith("/") and "\\" not in root, (
            f"row {root!r} must be a forward-slash repo-relative path with no "
            "trailing separator, or _covers() silently stops matching"
        )
        assert (REPO_ROOT / Path(root)).is_dir(), (
            f"row {root!r} is not a directory in this checkout"
        )
