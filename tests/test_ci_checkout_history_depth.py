"""A CI job that runs a git-history guard must check out git history.

`actions/checkout` defaults to `fetch-depth: 1` - a SHALLOW clone holding
exactly one commit. Git does not error on a history question asked of a
shallow clone; it answers "no such object" / "never deleted", which is a WRONG
answer rather than an absent one. So a guard built on `git cat-file -e
<rev>^:<path>` or `git log --all --diff-filter=DR` does not error out on CI -
it asserts the wrong thing and goes red, and it does so ONLY on CI, because
every developer clone on this box is full.

MEASURED 2026-08-07 by cloning this repo at `--depth 1` and running the
affected modules inside the clone:

    git log --all --diff-filter=DR --name-status
        shallow: 0 lines        full: 1344 lines
    pytest tests/test_u2500_candidate_sweep.py tests/test_rc2_p73_quarantine.py
           tests/test_skip_condition_hygiene.py
           tests/test_cost_health_watchdog_glob_rm165.py
        shallow clone: 12 failed, 73 passed
        full clone:     0 failed, 85 passed

Those 12 were 12 of the 13 failures that held `ci` red from run 31136741053
through 31156390386, all of them invisible to the local dual suite.

The remedy chosen was `fetch-depth: 0` on the two `ci.yml` checkouts, NOT a
`skipif` on a shallow clone. That choice is what this module defends, and the
reasoning is worth keeping next to the assertion: every CI run is a shallow
clone and no local run is, so a shallow-clone skip fires on 100 percent of CI
runs and 0 percent of local ones - the guard would report green in the one
place it is the only thing watching. `tests/test_u2500_candidate_sweep.py` and
`tests/test_rc2_p73_quarantine.py` are in their current form precisely because
f2f6a0e3 made them skip and cc5525d8 found they had been asserting nothing for
months.

Deliberately NOT asserted here: that every checkout in the repo is deep.
`docs-guards.yml` is explicitly `fetch-depth: 1` and correct to be - it runs a
selected set of .md-reading modules, none of which asks git for history. The
rule is scoped to jobs that actually run a history-reading guard, and both
routes to running one (naming the whole `tests/` tree, and naming the module)
are covered.
"""
from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

# The whole-tree pytest arguments. A job naming either of these runs every
# module in that tree, history-reading ones included.
_WHOLE_TREE_ARGS = {"tests", "tests/", "agents/daemon_slayer/tests",
                    "agents/daemon_slayer/tests/"}

# Command fragments that only make sense against real history. `cat-file -e
# <rev>^:<path>` and `log --diff-filter=DR` are the two in use today;
# `rev-list` is included because it is the obvious third way to ask the same
# question and should not be able to arrive ungated.
_HISTORY_MARKERS = ("cat-file", "--diff-filter", "rev-list")


def _yaml():
    """PyYAML, or skip.

    Same rationale as tests/test_ci_job_timeout_headroom_rm156.py: its
    `test_every_job_running_this_module_installs_pyyaml` already asserts that
    any job pytest-running the `tests/` tree installs pyyaml, and this module
    lives in that tree, so the skip cannot silently take hold on the runner.
    """
    return pytest.importorskip(
        "yaml", reason="PyYAML absent - CI installs it, see the pyyaml pin in "
                       "tests/test_ci_job_timeout_headroom_rm156.py")


def _workflow_files() -> list[Path]:
    """Both extensions - GitHub honours `.yaml` exactly as it honours `.yml`."""
    return sorted(
        p for ext in ("*.yml", "*.yaml") for p in _WORKFLOW_DIR.glob(ext)
    )


def _jobs(doc) -> dict:
    if not isinstance(doc, dict):
        return {}
    jobs = doc.get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def _run_bodies(job) -> list[str]:
    if not isinstance(job, dict):
        return []
    return [s["run"] for s in (job.get("steps") or [])
            if isinstance(s, dict) and isinstance(s.get("run"), str)]


def _pytest_arg_sets(run: str) -> list[list[str]]:
    """Arguments of every real `pytest` invocation in a shell `run:` body.

    Line-anchored on purpose: these `run:` blocks carry long `#` comment
    prose that quotes pytest command lines verbatim, and a substring match
    would read those as invocations. Continuation lines ending in `\\` are
    joined so a multi-line command is seen whole.
    """
    joined = re.sub(r"\\\n\s*", " ", run)
    out = []
    for line in joined.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        m = re.match(r"^(?:python\s+-m\s+)?pytest\b(.*)$", stripped)
        if not m:
            continue
        try:
            out.append(shlex.split(m.group(1)))
        except ValueError:
            out.append(m.group(1).split())
    return out


def _history_reading_modules() -> list[str]:
    """Repo-relative `tests/` modules that shell out to git HISTORY.

    Derived by scanning, not listed by hand: a new guard that asks git a
    history question must be covered by this rule the day it lands, without
    anyone remembering to add it here.
    """
    found = []
    for p in sorted((_REPO_ROOT / "tests").glob("test_*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if any(m in text for m in _HISTORY_MARKERS):
            found.append(f"tests/{p.name}")
    return found


def _checkout_fetch_depth(job):
    """`fetch-depth` of the job's `actions/checkout` step, or a marker.

    Returns `None` when the job has no checkout at all, and the string
    `"<default>"` when it checks out without declaring a depth - which is the
    shallow default and the whole bug, so it must not read as "unset, probably
    fine".
    """
    if not isinstance(job, dict):
        return None
    for step in job.get("steps") or []:
        if not isinstance(step, dict):
            continue
        uses = step.get("uses")
        if not isinstance(uses, str) or not uses.startswith("actions/checkout"):
            continue
        with_ = step.get("with")
        if not isinstance(with_, dict) or "fetch-depth" not in with_:
            return "<default>"
        return with_["fetch-depth"]
    return None


# --------------------------------------------------------------------------- #
# Non-vacuity: the rule below is only worth anything if such guards exist
# --------------------------------------------------------------------------- #

def test_history_reading_guards_exist_and_are_found_by_the_scan():
    """If this ever empties, the rule below silently stops protecting anything.

    The three named modules are the ones that were measured red on a shallow
    clone. They are asserted by NAME as well as by count, because a scan that
    drifts into matching nothing and a scan that matches everything both look
    like a passing test from a bare `len(...) > 0`.
    """
    found = _history_reading_modules()
    for expected in ("tests/test_u2500_candidate_sweep.py",
                     "tests/test_rc2_p73_quarantine.py",
                     "tests/test_skip_condition_hygiene.py"):
        assert expected in found, (
            f"{expected} no longer looks like a git-history guard to this "
            f"scan (markers: {_HISTORY_MARKERS}). Either it stopped asking "
            "git for history - in which case drop it from this assertion - or "
            "the scan has rotted and the fetch-depth rule below is now blind."
        )
    assert len(found) < 40, (
        f"{len(found)} of the tests/ modules matched {_HISTORY_MARKERS}; that "
        "is broad enough that the markers are probably matching prose rather "
        "than git invocations, which would make the rule below fire on jobs "
        "that need nothing."
    )


def test_a_shallow_clone_really_would_answer_wrongly():
    """The premise, checked against THIS checkout rather than asserted.

    `git log --all --diff-filter=DR` is the oracle behind the ROTTED verdict in
    tests/test_skip_condition_hygiene.py. On a full clone it returns hundreds
    of paths; on a shallow one it returns nothing and every rotted premise
    reads as a clean capability skip. This asserts the full-clone half - the
    half a developer box and a `fetch-depth: 0` runner both have - so that a
    future checkout regression shows up here as well as in the guards
    themselves.
    """
    if not (_REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout - no history to interrogate")
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=60)
    assert shallow.returncode == 0, f"git failed: {shallow.stderr}"
    assert shallow.stdout.strip() == "false", (
        "this checkout is SHALLOW. Every guard listed by "
        "_history_reading_modules() is asserting against a git that answers "
        "'never tracked' for everything - see this module's docstring for the "
        "measured 12-failure blast radius."
    )
    deleted = subprocess.run(
        ["git", "log", "--all", "--diff-filter=DR", "--name-status",
         "--format="],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=300)
    assert deleted.returncode == 0, f"git failed: {deleted.stderr}"
    lines = [ln for ln in deleted.stdout.splitlines() if ln.strip()]
    assert len(lines) > 100, (
        f"only {len(lines)} deleted/renamed paths in all of history - this "
        "repo has thousands of commits and hundreds of removals, so a number "
        "this small means history is truncated and the ROTTED oracle in "
        "tests/test_skip_condition_hygiene.py is blind here"
    )


# --------------------------------------------------------------------------- #
# The rule
# --------------------------------------------------------------------------- #

def test_jobs_running_the_whole_tests_tree_check_out_full_history():
    """`fetch-depth: 0`, per JOB, derived from what the job actually runs.

    Per-job and not per-file: a workflow can hold one job that needs history
    and one that does not, and `ci.yml` holds exactly that shape today
    (`check` and `nightly-full-suite` both run the tree; a future lint-only
    job would not).
    """
    yaml = _yaml()
    offenders = []
    checked = []
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in _jobs(doc).items():
            runs_tree = any(
                set(args) & _WHOLE_TREE_ARGS
                for run in _run_bodies(job)
                for args in _pytest_arg_sets(run)
            )
            if not runs_tree:
                continue
            checked.append(f"{path.name}:{job_name}")
            if _checkout_fetch_depth(job) != 0:
                offenders.append(
                    f"{path.name}:{job_name} "
                    f"(fetch-depth={_checkout_fetch_depth(job)!r})")
    assert checked, (
        "no job in .github/workflows/ runs the whole tests/ tree, so this "
        "rule asserted nothing. Either the workflows stopped gating the tree "
        "- a much larger problem than fetch-depth - or _pytest_arg_sets no "
        "longer recognises the invocation."
    )
    assert not offenders, (
        f"job(s) {sorted(offenders)} run the whole tests/ tree, which "
        f"contains {len(_history_reading_modules())} git-history guards, on a "
        "SHALLOW checkout. `actions/checkout` defaults to fetch-depth 1 and "
        "git then answers history questions wrongly rather than failing, so "
        "those guards go red on CI and only on CI. Add:\n"
        "    - uses: actions/checkout@v6\n"
        "        with:\n"
        "          fetch-depth: 0"
    )


def test_jobs_naming_a_history_guard_directly_check_out_full_history():
    """The second route in: a job that names the module rather than the tree.

    `docs-guards.yml` names `tests/test_ci_docs_guard_coverage.py` explicitly,
    so the shape is live in this repo and a history guard could arrive the
    same way. Whole-tree detection would not see it.
    """
    yaml = _yaml()
    history = set(_history_reading_modules())
    offenders = []
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in _jobs(doc).items():
            named = {a for run in _run_bodies(job)
                     for args in _pytest_arg_sets(run)
                     for a in args
                     if a.split("::")[0].replace("\\", "/") in history}
            if not named:
                continue
            if _checkout_fetch_depth(job) != 0:
                offenders.append(
                    f"{path.name}:{job_name} names {sorted(named)} at "
                    f"fetch-depth={_checkout_fetch_depth(job)!r}")
    assert not offenders, (
        "job(s) run a named git-history guard on a SHALLOW checkout: "
        f"{sorted(offenders)}. Set `fetch-depth: 0` on that job's "
        "actions/checkout step."
    )


def test_docs_guard_selector_picks_no_history_reading_module():
    """The DYNAMIC route, which no YAML scan can see.

    `docs-guards.yml` runs `xargs -a /tmp/md_guard_modules.txt python -m
    pytest`, so its module list is computed at run time by
    tools/md_guard_selector.py and is invisible to the two static rules above.
    That job checks out at `fetch-depth: 1` on purpose - it reads .md, not
    history - which is correct exactly as long as the selector never picks a
    history guard. Measured 2026-08-07: it picks none. This is the assertion
    that keeps that true.
    """
    selector = _REPO_ROOT / "tools" / "md_guard_selector.py"
    assert selector.is_file(), f"{selector} missing - docs-guards.yml runs it"
    proc = subprocess.run(
        [sys.executable, str(selector)],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, (
        f"md_guard_selector.py failed ({proc.returncode}): {proc.stderr[-800:]}"
    )
    selected = {ln.strip().replace("\\", "/")
                for ln in proc.stdout.splitlines() if ln.strip()}
    assert selected, "the selector chose nothing - it exits 1 on empty, so " \
                     "this should be unreachable"
    overlap = sorted(selected & set(_history_reading_modules()))
    assert not overlap, (
        f"tools/md_guard_selector.py now selects {overlap}, which ask git for "
        "history, but docs-guards.yml checks out at fetch-depth: 1. Either "
        "raise that job to fetch-depth: 0 or keep the guard out of the "
        "selector's reach."
    )
