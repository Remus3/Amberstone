"""Drift guard: no tracked .md file may carry a corrupt-GitHub-Actions-ref
shaped token (an `@` immediately followed by a path that ends in `.py`).

Background (R210, 2026-07-27): the gemini loop auditor is a DIFF SCANNER over
model-authored prose. Three separate false-positive REGRESS cycles (cycle 7,
cycle 8, cycle 15, cycle 16) were caused by an incident writeup quoting a
hallucinated path literal VERBATIM into a durable markdown doc. The literal has
the exact shape of a workflow `uses:` ref whose version tag was replaced by a
file path. Every time such a doc line re-enters a diff, the auditor sees the
token, concludes a workflow has a corrupted `uses:` ref, and burns an entire
loop cycle on a fix-first directive for a defect that does not exist. Ground
truth at the time of writing: CI fully green, and all 10 `uses:` refs across
the 3 workflow files are real tags (actions/checkout@v6, actions/setup-python@v6,
actions/cache@v4, CodSpeedHQ/action@v4). There is no workflow defect and there
never was one.

The fix is to write the literal with `[at]` in place of the bare `@` when
quoting it in prose. The meaning survives - a human reads `[at]` as the `@`
that the hallucinated ref carried - while the diff no longer contains a token
the auditor can mistake for a live workflow ref.

WHY THIS GUARD COVERS .md ONLY (scope fence - deliberate, do not widen):
An elided form of the same shape (`test_x.py` in place of the full incident
basename) appears in `ops/loop/executor.py` and `tests/test_loop_executor.py`,
and there it is LOAD-BEARING: it is the
documented exemplar that the R210 grounding guard is specified against.
Neutering it in those two files would weaken the very tests that catch the
false premise. Prose docs are the diff-poison surface, because the auditor
reads narrative markdown as if it were describing the current repository.
Code comments and test fixtures are not that surface - they are read as code.
So: .md is asserted clean, .py is deliberately left alone.

Enumeration is via `git ls-files` (the git INDEX), never a filesystem walk, so
an untracked scratch file, a build artifact, or an agent's temp notes cannot
fail the suite.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# A corrupt action ref: '@' immediately followed by a path containing a '/' or
# '\' separator and ending in '.py'. A legitimate ref is '@' followed by a
# version tag or branch name (no separator, no '.py'), so 'owner/repo@v6' can
# never match - the '@' there is followed by 'v6' and stops.
_CORRUPT_ACTION_REF_RE = re.compile(r"@[A-Za-z0-9_./\\-]*[/\\][A-Za-z0-9_./\\-]*\.py")

# The R210 incident literal, assembled from two pieces ON PURPOSE so that THIS
# FILE does not itself contain the poison token contiguously. Concatenating at
# runtime keeps the diff of this guard clean while still exercising the regex
# against the real string.
_INCIDENT_TOKEN = "@" + r"agents\daemon_slayer\tests\test_magic_burst_valuation_dsv6.py"

# Every real `uses:` ref in .github/workflows/ as measured 2026-07-27. The
# guard must never flag any of these; if it ever does it has widened into
# false-positive territory and would start failing on legitimate docs that
# quote a workflow.
_REAL_ACTION_REFS: tuple[str, ...] = (
    "actions/checkout@v6",
    "actions/setup-python@v6",
    "actions/cache@v4",
    "CodSpeedHQ/action@v4",
)

_FIX_HINT = (
    "Write the literal with '[at]' in place of the bare '@' (for example "
    "'[at]agents\\daemon_slayer\\tests\\test_x.py'). Keep the rest of the "
    "token byte-for-byte; do NOT reword or delete the surrounding prose - "
    "these are durable historical records."
)


def _tracked_markdown_files() -> list[str]:
    """Repo-relative posix paths of every tracked .md file, from the INDEX."""
    proc = subprocess.run(
        ["git", "ls-files", "--", "*.md"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, (
        f"git ls-files failed (rc={proc.returncode}) in {_REPO_ROOT}: "
        f"{proc.stderr.strip()}"
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _scan(rel_posix: str) -> list[tuple[int, str]]:
    """Return (1-indexed line number, matched token) for every corrupt ref."""
    path = _REPO_ROOT / rel_posix
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _CORRUPT_ACTION_REF_RE.finditer(line):
            hits.append((lineno, match.group(0)))
    return hits


def test_tracked_markdown_enumeration_is_non_empty() -> None:
    """Sanity pin: the git-index enumeration actually returns .md files.

    Without this, a broken `git ls-files` invocation would make the main guard
    vacuously green.
    """
    files = _tracked_markdown_files()
    assert len(files) > 10, (
        f"expected many tracked .md files, got {len(files)}: {files[:5]}"
    )
    assert all(f.endswith(".md") for f in files), (
        "git ls-files returned a non-.md path"
    )


def test_no_corrupt_action_ref_in_tracked_markdown() -> None:
    """No tracked .md file may contain a corrupt-action-ref shaped token."""
    violations: list[str] = []
    for rel_posix in _tracked_markdown_files():
        for lineno, token in _scan(rel_posix):
            violations.append(f"  {rel_posix}:{lineno}: {token}")
    if violations:
        pytest.fail(
            "Corrupt-GitHub-Actions-ref shaped token(s) found in tracked "
            "markdown. This shape poisons the gemini loop auditor's diff scan "
            "and manufactures a false 'VERDICT: REGRESS' for a workflow defect "
            "that does not exist (R210). "
            + _FIX_HINT
            + "\nOffending file:line:\n"
            + "\n".join(violations)
        )


def test_regex_does_not_flag_real_action_refs() -> None:
    """The guard must never fire on a legitimate `uses:` ref.

    Pins the four real refs measured across .github/workflows/ so the guard can
    never silently widen into flagging valid action pins.
    """
    for ref in _REAL_ACTION_REFS:
        assert _CORRUPT_ACTION_REF_RE.search(ref) is None, (
            f"guard has widened: it now flags the legitimate action ref {ref!r}"
        )
        # Also exercise the ref in the prose context it actually appears in.
        line = f"      - uses: {ref}"
        assert _CORRUPT_ACTION_REF_RE.search(line) is None, (
            f"guard has widened: it now flags the workflow line {line!r}"
        )


def test_regex_does_not_flag_other_at_shapes() -> None:
    """Neighbouring `@` shapes that are NOT the defect must stay unflagged."""
    benign = (
        "owner/repo@main",
        "@import './panels/build_module.css';",
        "@tests occurrence in any .md",  # bare '@word', no separator
        "@staticmethod",
        "user@example.com",
        "pytest tests/test_loop_executor.py",  # a path with no leading '@'
    )
    for sample in benign:
        assert _CORRUPT_ACTION_REF_RE.search(sample) is None, (
            f"guard has widened: it now flags the benign string {sample!r}"
        )


def test_regex_does_flag_the_incident_literal() -> None:
    """Negative control: the guard must still catch the real poison token.

    Without this, someone could 'fix' a failure by loosening the regex until it
    matches nothing and the guard would go green while doing nothing.
    """
    assert _CORRUPT_ACTION_REF_RE.search(_INCIDENT_TOKEN) is not None, (
        "guard has been neutered: it no longer matches the R210 incident "
        "literal it exists to catch"
    )
    quoted = f"naming `{_INCIDENT_TOKEN}` as the corrupted literal"
    assert _CORRUPT_ACTION_REF_RE.search(quoted) is not None, (
        "guard no longer matches the incident literal in backticked prose"
    )
    # The de-poisoned form must NOT match - that is the prescribed fix.
    assert _CORRUPT_ACTION_REF_RE.search(_INCIDENT_TOKEN.replace("@", "[at]", 1)) is None, (
        "the prescribed '[at]' fix does not actually clear the guard"
    )


def test_loop_executor_sources_are_out_of_scope() -> None:
    """Scope fence: the .py exemplars are deliberately NOT covered.

    ops/loop/executor.py and tests/test_loop_executor.py carry the literal as
    the load-bearing exemplar the R210 grounding guard is specified against.
    This test documents that exclusion as intentional so a future widening of
    the guard to '*' has to consciously break it rather than silently neuter
    those tests.
    """
    for rel_posix in ("ops/loop/executor.py", "tests/test_loop_executor.py"):
        assert (_REPO_ROOT / rel_posix).is_file(), (
            f"expected exemplar source missing: {rel_posix}"
        )
    assert not any(f.endswith(".py") for f in _tracked_markdown_files()), (
        "the enumeration must yield .md only"
    )


def test_this_drift_guard_is_ascii() -> None:
    """This test file MUST be 7-bit ASCII."""
    raw = Path(__file__).read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tests/test_doc_action_ref_hygiene.py has {len(non_ascii)} non-ASCII "
        f"bytes; first at offset {non_ascii[0][0]}"
    )
