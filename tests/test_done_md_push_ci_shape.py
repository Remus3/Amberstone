"""tools/done.md must describe the push path ci.yml really runs (c1b3 ruling,
session 126). For nine sessions after W-A (LEDGER 1706) made a push run an
impact slice, the SHAPE block and section 2c still said the push fires the
full dual suite. Pinned both ways: the stale claims are gone, the one
conditional dispatch is written once, and the ci.yml matrix the text depends
on still holds - if ci.yml changes, this fails and section 2c must be
re-ruled rather than left stale.
"""
from __future__ import annotations

import re
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


# --------------------------------------------------------------------------- #
# RM-790: the TIER TABLE names CI's check-job steps the gated suite never runs.
# Session 126: c6bbd1577 went RED at `tools/ds_feed_index.py --check` after a
# DS data change whose local Tier-2 run was green; fixed forward in 376443c8a.
# The step universe is derived from ci.yml (the producing side), never listed.
# --------------------------------------------------------------------------- #
TIER_TABLE_HEAD = "**TIER TABLE"
DUAL_SUITE_ROOTS = ("tests", "agents/daemon_slayer/tests")
_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.M)
_SYNC_CHECK = re.compile(r"\bpython (tools/[\w/.-]+\.py) --check\b")
_REQUIRE_FLAG = re.compile(r"\b(RC_REQUIRE_[A-Z_]+)=1\b")
_PYTEST_ROOT = re.compile(r"^\s*(?:[A-Z_]+=\S+\s+)*pytest\s+([^\s\\-][^\s\\]*)")


def _tier_table(done: str) -> str:
    start = done.index(TIER_TABLE_HEAD)
    return done[start:done.index("\n\n", start)]


def _check_job_run_lines(ci: str) -> list[str]:
    """Non-comment lines of the `check` job, the job a push is graded on."""
    jobs = [(m.group(1), m.start()) for m in _JOB.finditer(ci)]
    names = [name for name, _ in jobs]
    assert "check" in names, "ci.yml has no `check` job - re-rule RM-790"
    i = names.index("check")
    end = jobs[i + 1][1] if i + 1 < len(jobs) else len(ci)
    body = ci[jobs[i][1]:end]
    return [ln for ln in body.split("\n") if not ln.lstrip().startswith("#")]


def _check_job_non_suite_steps(ci: str) -> dict[str, set[str]]:
    lines = _check_job_run_lines(ci)
    text = "\n".join(lines)
    roots = set()
    for ln in lines:
        m = _PYTEST_ROOT.match(ln)
        if m and not m.group(1).startswith(('"', "'", "@")):
            root = m.group(1).rstrip("/")
            if not any(root == r or root.startswith(r + "/") for r in DUAL_SUITE_ROOTS):
                roots.add(root)
    return {
        "sync_checks": set(_SYNC_CHECK.findall(text)),
        "require_flags": set(_REQUIRE_FLAG.findall(text)),
        "orphan_trees": roots,
    }


def test_check_job_derivation_is_not_vacuous():
    found = _check_job_non_suite_steps(_read(CI))
    assert "tools/ds_feed_index.py" in found["sync_checks"], found
    assert found["require_flags"], found
    assert "tools/tests" in found["orphan_trees"], found


def test_tier_table_names_every_check_job_step_the_suite_skips():
    table = _tier_table(_read(DONE))
    found = _check_job_non_suite_steps(_read(CI))
    missing = sorted(
        [f"python {p} --check" for p in found["sync_checks"]
         if f"python {p} --check" not in table]
        + [flag for flag in found["require_flags"] if flag not in table]
        + [tree for tree in found["orphan_trees"] if f"`{tree}`" not in table]
    )
    assert not missing, (
        "ci.yml's check job runs these outside the gated dual suite, but the "
        f"tools/done.md TIER TABLE does not name them: {missing}")


def test_tier_table_orders_the_ds_feed_index_write_before_check():
    table = _tier_table(_read(DONE))
    write = "python tools/ds_feed_index.py --write"
    check = "python tools/ds_feed_index.py --check"
    assert write in table and check in table, "RM-790: name both DS index steps"
    assert table.index(write) < table.index(check)
    assert "data/daemon_slayer/" in table, "say WHICH change needs the DS index steps"
    assert "tools/ds_feed_index.json" in table, "say what to commit with the data"
