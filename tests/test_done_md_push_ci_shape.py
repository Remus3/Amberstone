"""tools/done.md must describe the push path ci.yml really runs (c1b3 ruling,
session 126). For nine sessions after W-A (LEDGER 1706) made a push run an
impact slice, the SHAPE block and section 2c still said the push fires the
full dual suite. Pinned both ways: the stale claims are gone, the one
conditional dispatch is written once, and the ci.yml matrix the text depends
on still holds - if ci.yml changes, this fails and section 2c must be
re-ruled rather than left stale.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DONE = ROOT / "tools" / "done.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"

STALE = (
    "FIRES the full suite",
    "The push IS the full suite",
    "has already fired the full dual suite",
    "the push CI run covers that",
    "The repo is PRIVATE",
)
FULL_STEP_IF = "if: github.event_name != 'push' || steps.impact.outputs.mode == 'full'"


def _read(p: Path) -> str:
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_done_md_drops_the_push_runs_the_full_suite_claims():
    done = _read(DONE)
    hits = [s for s in STALE if s in done]
    assert not hits, hits


def test_done_md_names_the_slice_and_one_conditional_dispatch():
    done = _read(DONE)
    assert "impact slice" in done
    assert done.count("gh workflow run ci.yml --ref main") == 1
    sec = done[done.index("### 2c."):done.index("### 3.")]
    assert "':(exclude)*.md'" in sec
    assert "RC-NEXT-SESSION.txt" in sec


def test_the_ci_matrix_the_doc_describes_still_holds():
    ci = _read(CI)
    assert FULL_STEP_IF in ci, (
        "ci.yml's full-suite gate changed - re-rule tools/done.md SHAPE and 2c")
    assert "workflow_dispatch:" in ci
    assert "'**/*.md'" in ci
