"""A CI timeout must fail LOUDLY, and must sit above ordinary runner variance.

RM-156, MEASURED 2026-08-04 against the live GitHub Actions API.

Push run `30866367283` was killed by GitHub at 40m16s of job wall clock, with
`.github/workflows/ci.yml`'s `check` job carrying `timeout-minutes: 40`. Two
separate defects were behind that, and only the first one was filed:

1. THE CEILING WAS TOO THIN. The filing quoted a "22-27 minute norm", which was
   read off the runs immediately surrounding the failure. Over the last 40 runs
   the `check` job's successful wall clock is min 22m17s, median about 27m, and
   **max 36m49s** (run `30820229244`) - so the real headroom was about 3
   minutes, not 13. The 36m49s outlier is not suite variance at all: its
   `Install Playwright Chromium` step took **10m33s** against 27s on the runs
   either side of it, i.e. a cache miss on a step the job ceiling also has to
   cover. A single job-level ceiling is therefore the wrong instrument on its
   own - it is one number spanning two independent tails, setup and suite.

2. THE FAILURE MODE WAS SILENT. A job killed by `timeout-minutes` reports
   conclusion `cancelled`, which is the SAME conclusion GitHub reports for a run
   superseded by the `cancel-in-progress` concurrency group. Run `30863180947`
   (5m19s, superseded) and run `30866367283` (40m16s, timed out) are
   indistinguishable by conclusion alone. `cancelled` reads as neither pass nor
   fail, so a branch whose CI never actually ran the suite skims as green.

The fix pinned here is the step-level ceiling. GitHub kills a step that exceeds
its own `timeout-minutes` and marks that STEP failed, so the job concludes
`failure` - red, not `cancelled`. That makes the loud-fail property structural
rather than a convention someone has to remember.

SOURCING THAT PREMISE HONESTLY, because the whole fix rests on it and the
obvious citation does not exist. GitHub's workflow-syntax reference documents
only half of it: the job-level knob is described as "the maximum number of
minutes to let a job run before GitHub automatically CANCELS it", while the
step-level knob is described as "the maximum number of minutes to run the step
before killing the process" and never names the resulting conclusion. The
step-marked-FAILED half comes from the runner implementation instead -
`actions/runner`, `src/Runner.Worker/StepsRunner.cs`, which on a step timeout
sets `TaskResult.Failed` when the job token is NOT cancelled, and
`TaskResult.Canceled` in the job-cancel branch. That is authoritative but it is
source, not documentation, and it can change under us without a docs diff. If
this behaviour is ever seen to differ in a real run, this module is the place
that has to be re-measured first.

The invariant that makes it work is the ORDERING: the step ceiling must be
reached strictly BEFORE the job ceiling. If the job ceiling is the lower of the
two, the job dies first and the conclusion is `cancelled` again - the exact bug
this module exists to prevent, silently restored by a one-line edit. Hence
`_SETUP_HEADROOM_MIN`, which is sized from the measured 10m33s Playwright cache
miss, not guessed.

Contract style follows `tests/test_ci_docs_guard_coverage.py`: the workflow YAML
is parsed off disk and the long step is DERIVED from what it actually runs, not
matched by name. Renaming a step, or adding a third job that runs the dual
suite, must not slip past this (memory
`feedback_contract_test_must_read_the_contract_from_disk`).
"""
# NOTE ON THE PYYAML SKIP, corrected after an independent verifier caught the
# first version of this module asserting something false about itself. The
# original docstring claimed `test_ci_installs_the_yaml_parser_it_needs` in
# tests/test_ci_docs_guard_coverage.py covered this file's dependency. It does
# not: that test keys on its OWN filename (`me = _HERE.name`) and searches for a
# pyyaml install anywhere in a workflow's TEXT, so it is blind both to this
# module and to WHICH job installs the parser. Measured 2026-08-04: `check`
# installs pyyaml and `nightly-full-suite` does not, so every assertion here
# skipped in the nightly job while reporting a green tick - the exact
# skip-is-green class the 2026-07-27 audit was opened for. The fix is on the
# workflow side (pyyaml added to the nightly pip line), and
# `test_every_job_running_this_module_installs_pyyaml` below now asserts it
# per-JOB rather than per-file so it cannot regress silently again.
from __future__ import annotations

import re
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_REPO = _HERE.parent.parent
_WORKFLOW_DIR = _REPO / ".github" / "workflows"

# Both halves of the tree. A step running BOTH is the ~25 minute one.
_RC_TREE = "tests/"
_DS_TREE = "agents/daemon_slayer/tests/"

# MEASURED 2026-08-04 over the last 40 ci.yml runs (GitHub Actions API), then
# CORRECTED by an independent verifier - the first pass of this block read its
# maxima off an aggregate and understated both by about two minutes:
#   check `full dual suite` step, complete runs:   20m47s .. 27m40s
#                                                  (max: run 30847651957)
#   nightly `Full Dual Suite` step, complete runs: 23m20s .. 27m14s
#                                                  (max: run 30762978964)
#   check `full dual suite` step, TRUNCATED by the job ceiling: 38m41s
# The truncation is a lower bound - the suite wanted more than 38m41s that run
# and we will never know how much more. A ceiling has to sit above the tail of
# ordinary variance or it manufactures fake reds, so this floor sits about 12
# minutes above the 27m40s worst COMPLETE observation rather than hugging it.
# 2026-09-01 UPDATE: landing the 61-commit lane 8 true-audit branch grew the dual
# suite from ~45min to ~57min on CI (run 33470194278 timed out at the old 55m step
# ceiling while 99 pct passing - a green-but-slow suite, no test failure). Active
# ceilings raised in ci.yml: step 55 -> 75, job 75 -> 95. The floor below stays
# conservative on purpose - it guards against an absurdly-LOW ceiling, not the
# suite's actual size; the real headroom lives in the 75m step ceiling.
_MIN_SUITE_STEP_CEILING_MIN = 40

# MEASURED 2026-08-04: `Install Playwright Chromium` took 10m33s on run
# 30820229244 (cache miss) against 27s on the runs either side. Everything a job
# does outside the suite step still bills against the JOB ceiling, so the job
# ceiling has to clear the step ceiling by at least that worst-observed setup.
_SETUP_HEADROOM_MIN = 12


def _yaml():
    """PyYAML, or skip - same rationale as tests/test_ci_docs_guard_coverage.py,
    whose `test_ci_installs_the_yaml_parser_it_needs` asserts CI installs it, so
    these assertions cannot silently degrade to green ticks on the runner."""
    return pytest.importorskip("yaml", reason="PyYAML absent - see pyyaml in CI installs")


def _workflow_files():
    """Both extensions. GitHub honours `.yaml` exactly as it honours `.yml`, so
    globbing only one leaves a workflow that this module cannot see - which is
    the hole `test_every_ci_job_declares_a_job_timeout` exists to close. Moot
    today (all three workflows are `.yml`) and deliberately not left to luck."""
    return sorted(
        p for ext in ("*.yml", "*.yaml") for p in _WORKFLOW_DIR.glob(ext)
    )


def _load_workflows():
    yaml = _yaml()
    return {
        p.name: yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in _workflow_files()
    }


def _jobs(doc):
    if not isinstance(doc, dict):
        return {}
    jobs = doc.get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def _dual_suite_steps(doc):
    """Every step that pytest-runs BOTH trees, derived from its `run:` body.

    Deliberately not matched on step name: the two steps that do this today are
    called "full dual suite (RM-119 ...)" and "Full Dual Suite", and a third
    could be added under any name at all.
    """
    found = []
    for job_name, job in _jobs(doc).items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if not isinstance(run, str):
                continue
            if not re.search(r"(?m)^\s*pytest\b", run):
                continue
            if _RC_TREE in run and _DS_TREE in run:
                found.append((job_name, job, step))
    return found


def test_every_job_running_this_module_installs_pyyaml():
    """This module's own dependency must not disarm it in a job that runs it.

    Text-level and per-JOB on purpose. The sibling in
    tests/test_ci_docs_guard_coverage.py does this per-FILE, which is what let
    the gap through: it finds a pyyaml install anywhere in the workflow text and
    is satisfied, even when the job actually running the tests installs none.
    Here a job counts as running this module if it pytest-runs a tree that
    contains it, and such a job must install pyyaml in one of its own steps.
    """
    import yaml as _yaml_mod  # noqa: F401  - this test is meaningless without it
    yaml = _yaml()
    me_rel = f"tests/{_HERE.name}"
    offenders = []
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in _jobs(doc).items():
            if not isinstance(job, dict):
                continue
            runs = [
                s["run"] for s in (job.get("steps") or [])
                if isinstance(s, dict) and isinstance(s.get("run"), str)
            ]
            selects_me = any(
                (me_rel in r) or (re.search(r"(?m)^\s*pytest\b", r) and _RC_TREE in r)
                for r in runs
            )
            if not selects_me:
                continue
            if not any(re.search(r"(?im)^\s*pip install\b.*\bpyyaml\b", r) for r in runs):
                offenders.append(f"{path.name}:{job_name}")
    assert not offenders, (
        f"job(s) {sorted(offenders)} run {me_rel} but install no pyyaml, so "
        "every assertion in this module degrades to a SKIP there - and a "
        "skipped test is a green tick. Add pyyaml to that job's pip install."
    )


def test_every_ci_job_declares_a_job_timeout():
    """An unbounded job runs to GitHub's 6-hour default before anyone hears."""
    missing = []
    for name, doc in _load_workflows().items():
        for job_name, job in _jobs(doc).items():
            if isinstance(job, dict) and job.get("timeout-minutes") is None:
                missing.append(f"{name}:{job_name}")
    assert not missing, (
        f"job(s) with no `timeout-minutes`: {sorted(missing)}. Without one a "
        "hung job burns the GitHub default (6 hours) before reporting."
    )


def test_the_dual_suite_step_is_found_at_all():
    """Guards the two tests below from passing vacuously.

    If the derivation stops matching - the suite is split across jobs, the
    invocation stops naming both trees, pytest is called through a wrapper -
    these assertions would find nothing to check and report green. That is the
    vacuous-guard failure class, so the universe being non-empty is its own
    assertion rather than an assumption of the others.
    """
    steps = _dual_suite_steps(_load_workflows()["ci.yml"])
    assert steps, (
        "no step in ci.yml pytest-runs both "
        f"{_RC_TREE!r} and {_DS_TREE!r}. If the dual suite was deliberately "
        "split into separate jobs, this module's derivation must be updated in "
        "the same commit - do not leave it matching nothing, which is green."
    )


def test_dual_suite_steps_carry_their_own_step_timeout():
    """The loud-fail mechanism itself.

    A step that exceeds its own `timeout-minutes` is marked FAILED and the job
    concludes `failure`. A job that exceeds the job ceiling concludes
    `cancelled`, which is indistinguishable from a concurrency supersede.
    """
    offenders = []
    for job_name, _job, step in _dual_suite_steps(_load_workflows()["ci.yml"]):
        ceiling = step.get("timeout-minutes")
        if ceiling is None:
            offenders.append(f"{job_name}: no step-level timeout-minutes")
        elif ceiling < _MIN_SUITE_STEP_CEILING_MIN:
            offenders.append(
                f"{job_name}: step ceiling {ceiling}m is under the measured "
                f"floor of {_MIN_SUITE_STEP_CEILING_MIN}m"
            )
    assert not offenders, (
        f"{offenders}\n"
        "The dual-suite step needs a step-level `timeout-minutes`. Relying on "
        "the job ceiling alone makes an overrun report `cancelled` (run "
        "30866367283, 40m16s), which is the same conclusion a superseded run "
        "gets (run 30863180947, 5m19s) - neither pass nor fail, and easy to "
        "skim past as green."
    )


def test_step_ceiling_is_reached_before_the_job_ceiling():
    """The ordering invariant. Without it the step timeout is decorative.

    If job <= step, the job ceiling always wins and every overrun is `cancelled`
    again. The margin is sized from the measured 10m33s Playwright cache miss,
    because setup bills against the job ceiling and not the step ceiling.
    """
    offenders = []
    for job_name, job, step in _dual_suite_steps(_load_workflows()["ci.yml"]):
        step_ceiling = step.get("timeout-minutes")
        job_ceiling = job.get("timeout-minutes")
        if step_ceiling is None or job_ceiling is None:
            continue  # reported by the sibling tests
        if job_ceiling < step_ceiling + _SETUP_HEADROOM_MIN:
            offenders.append(
                f"{job_name}: job {job_ceiling}m vs step {step_ceiling}m - "
                f"needs at least step + {_SETUP_HEADROOM_MIN}m"
            )
    assert not offenders, (
        f"{offenders}\n"
        "The JOB ceiling must clear the STEP ceiling by the worst observed "
        "setup cost (10m33s Playwright cache miss, run 30820229244), or the job "
        "dies first and the conclusion is `cancelled` rather than `failure` - "
        "restoring exactly the defect RM-156 fixed."
    )
