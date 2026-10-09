"""Workflow shape of MAIN's PERF-AUDIT (2026-10-08) items 1 and 8 in ci.yml.

Item 1 (HIGH): push CI ran the full dual suite (~38.5k tests, 22-45 min) on
every non-.md push, and 119 of 265 push runs (45 pct) were cancelled by a newer
push. Fix: keep the fast guards on every push, run the full dual suite on PR,
on the merge/batch cadence (workflow_dispatch) and nightly, and give a push an
impact-selected slice (tools/ci_impact_selector.py).

Item 8 (MED): the nightly job's `if:` also admitted workflow_dispatch, so one
dispatch ran TWO full suites, and the nightly had no Playwright browser cache.
Fix: schedule only, plus the cache step.

The `if:` conditions are EVALUATED here, not string-matched: a tiny evaluator
covers exactly the `==` / `!=` / `&&` / `||` forms these jobs use and fails on
anything else, so a reworded condition that changes behaviour reds this module
and one that keeps behaviour stays green.
"""
from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_CI = _REPO / ".github" / "workflows" / "ci.yml"
_RC_TREE = "tests/"
_DS_TREE = "agents/daemon_slayer/tests/"
_SELECTOR = "tools/ci_impact_selector.py"
_EVENTS = ("push", "pull_request", "workflow_dispatch", "schedule")
_MODES = ("slice", "full", "none")
# Same floor as tests/test_ci_job_timeout_headroom_rm156.py (worst observed
# Playwright cache miss, 10m33s, bills against the job ceiling).
_SETUP_HEADROOM_MIN = 12


def _doc():
    yaml = pytest.importorskip("yaml", reason="PyYAML absent - CI pins it in requirements-ci.txt")
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _jobs():
    return _doc()["jobs"]


_ATOM = re.compile(r"^\s*([A-Za-z_][\w.\-]*)\s*(==|!=)\s*'([^']*)'\s*$")
_CONTEXT_KEYS = ("github.event_name", "steps.impact.outputs.mode")


def _eval_if(expr, *, event, mode=""):
    """Evaluate a GitHub `if:` built only of `X == 'v'` / `X != 'v'` atoms
    joined by `&&` / `||` (no parentheses). `&&` binds tighter, as in GitHub.
    A step output that was never set reads as the empty string, as in GitHub."""
    if expr is None:
        return True
    text = str(expr).strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2]
    assert "(" not in text and ")" not in text, f"unsupported `if:` shape: {expr!r}"
    values = {"github.event_name": event, "steps.impact.outputs.mode": mode}
    any_true = False
    for disjunct in text.split("||"):
        all_true = True
        for atom in disjunct.split("&&"):
            m = _ATOM.match(atom)
            assert m, f"unsupported `if:` atom {atom!r} in {expr!r}"
            key, op, literal = m.groups()
            assert key in _CONTEXT_KEYS, f"unmodelled context {key!r} in {expr!r}"
            hit = values[key] == literal
            all_true = all_true and (hit if op == "==" else not hit)
        any_true = any_true or all_true
    return any_true


def _is_dual_suite_step(step):
    run = step.get("run") if isinstance(step, dict) else None
    if not isinstance(run, str):
        return False
    return bool(re.search(r"(?m)^\s*pytest\b", run)) and _RC_TREE in run and _DS_TREE in run


def _dual_suite_runs(event, mode):
    """(job, step name) of every dual-suite step that RUNS for this event."""
    ran = []
    for job_name, job in _jobs().items():
        if not _eval_if(job.get("if"), event=event):
            continue
        for step in job.get("steps") or []:
            if _is_dual_suite_step(step) and _eval_if(step.get("if"), event=event, mode=mode):
                ran.append((job_name, step.get("name")))
    return ran


def _check_steps():
    return _jobs()["check"]["steps"]


def _step_by_id(step_id):
    for step in _check_steps():
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"no step with id {step_id!r} in the check job")


def _is_slice_step(step):
    run = step.get("run") if isinstance(step, dict) else None
    return isinstance(run, str) and "pytest" in run and "@" in run and "impact" in run


def _slice_step():
    found = [s for s in _check_steps() if _is_slice_step(s)]
    assert len(found) == 1, f"expected ONE impact-slice pytest step, found {len(found)}"
    return found[0]


def test_the_evaluator_is_not_vacuous():
    assert _eval_if("github.event_name == 'push'", event="push") is True
    assert _eval_if("github.event_name == 'push'", event="schedule") is False
    assert _eval_if("github.event_name != 'push' || steps.impact.outputs.mode == 'full'",
                    event="push", mode="full") is True
    assert _eval_if("github.event_name == 'push' && steps.impact.outputs.mode == 'slice'",
                    event="push", mode="none") is False
    with pytest.raises(AssertionError):
        _eval_if("contains(github.ref, 'main')", event="push")


# ---- item 8: the nightly ----------------------------------------------------

@pytest.mark.parametrize("event", _EVENTS)
def test_nightly_runs_on_schedule_only(event):
    job = _jobs()["nightly-full-suite"]
    assert _eval_if(job.get("if"), event=event) is (event == "schedule"), job.get("if")


def test_nightly_caches_playwright_browsers_before_installing_them():
    steps = _jobs()["nightly-full-suite"]["steps"]
    cache = [i for i, s in enumerate(steps)
             if str(s.get("uses", "")).startswith("actions/cache@")
             and "ms-playwright" in str((s.get("with") or {}).get("path", ""))]
    install = [i for i, s in enumerate(steps)
               if "playwright install" in str(s.get("run", ""))]
    assert cache, "nightly-full-suite has no Playwright browser cache step"
    assert install, "nightly-full-suite no longer installs Chromium"
    assert cache[0] < install[0], "the cache must be restored BEFORE the install"


def test_both_playwright_caches_use_one_pinned_action_and_one_key():
    caches = []
    for job_name in ("check", "nightly-full-suite"):
        for s in _jobs()[job_name]["steps"]:
            if str(s.get("uses", "")).startswith("actions/cache@"):
                caches.append((s["uses"], (s.get("with") or {}).get("key")))
    assert len(caches) == 2, caches
    assert caches[0] == caches[1], caches
    assert re.fullmatch(r"actions/cache@[0-9a-f]{40}", caches[0][0]), "pin to a full commit SHA"


# ---- item 1: how many full suites each event runs ----------------------------

@pytest.mark.parametrize("event", ("pull_request", "workflow_dispatch", "schedule"))
def test_non_push_events_run_the_full_dual_suite_exactly_once(event):
    ran = _dual_suite_runs(event, mode="")
    assert len(ran) == 1, (event, ran)


@pytest.mark.parametrize("mode", ("slice", "none"))
def test_an_ordinary_push_runs_no_full_dual_suite(mode):
    assert _dual_suite_runs("push", mode) == []


def test_a_push_the_selector_escalates_runs_the_full_dual_suite_once():
    assert _dual_suite_runs("push", "full") == [
        ("check", next(s["name"] for s in _check_steps() if _is_dual_suite_step(s)))]


def test_the_full_step_keeps_the_name_the_queue_driver_reads():
    """ops/loop/queue_loop.py grades the `check` job's step whose name contains
    CI_STEP. Renaming it away would turn every graded cycle `unavailable`."""
    qloop = importlib.import_module("ops.loop.queue_loop")
    full = [s for s in _check_steps() if _is_dual_suite_step(s)]
    assert len(full) == 1
    assert qloop.CI_JOB == "check"
    assert qloop.CI_STEP in full[0]["name"]


# ---- the selector and slice steps -------------------------------------------

def test_the_selector_step_runs_on_push_only():
    step = _step_by_id("impact")
    for event in _EVENTS:
        assert _eval_if(step.get("if"), event=event) is (event == "push"), event
    assert _SELECTOR in step["run"]


def test_the_selector_gets_the_push_base_through_env_not_inline():
    """No `${{ }}` inside a run body: an expression expanded into shell text is
    the injection shape; an env binding is data."""
    step = _step_by_id("impact")
    assert "${{" not in step["run"]
    env = step.get("env") or {}
    bound = [k for k, v in env.items() if "github.event.before" in str(v)]
    assert bound, "the push base (github.event.before) is not bound in the step env"
    assert f"--base \"${bound[0]}\"" in step["run"]
    assert '--head "$GITHUB_SHA"' in step["run"]
    assert '--github-output "$GITHUB_OUTPUT"' in step["run"]


def test_the_slice_step_runs_only_for_a_push_slice():
    step = _slice_step()
    for event in _EVENTS:
        for mode in _MODES:
            want = event == "push" and mode == "slice"
            assert _eval_if(step.get("if"), event=event, mode=mode) is want, (event, mode)


def test_the_slice_reads_the_argfile_the_selector_writes():
    out = re.search(r'--out\s+"([^"]+)"', _step_by_id("impact")["run"])
    assert out, "the selector step names no --out file"
    run = _slice_step()["run"]
    assert f'"@{out.group(1)}"' in run, "pytest must read the selector's --out file as an @argfile"
    assert "-n auto" in run and "--dist loadfile" in run and "--timeout=" in run


def test_the_slice_step_fires_its_own_timeout_before_the_job_ceiling():
    step = _slice_step()
    job_ceiling = _jobs()["check"]["timeout-minutes"]
    assert step.get("timeout-minutes"), "the slice step needs a step-level timeout"
    assert job_ceiling >= step["timeout-minutes"] + _SETUP_HEADROOM_MIN


def test_the_selector_step_precedes_the_steps_that_read_it():
    names = [s.get("id") or s.get("name") for s in _check_steps()]
    impact = names.index("impact")
    slice_at = _check_steps().index(_slice_step())
    full_at = next(i for i, s in enumerate(_check_steps()) if _is_dual_suite_step(s))
    assert impact < slice_at and impact < full_at


def test_the_selector_mode_words_match_the_workflow():
    spec = importlib.util.spec_from_file_location("ci_impact_selector", _REPO / _SELECTOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, mod)
    spec.loader.exec_module(mod)
    assert (mod.MODE_SLICE, mod.MODE_FULL, mod.MODE_NONE) == _MODES


# ---- the fast guards stay on every push ---------------------------------------

def test_every_other_check_step_runs_on_every_check_event():
    """Only the selector, the slice and the full suite are event-gated. The
    fast guards (py_compile, ruff, ASCII hygiene, docs-guard wiring, the git
    hook gate, the build-order tables, the orphan trees, the DS feed index)
    run on every push - that is half of item 1's acceptance."""
    def gated_by_design(step):
        return step.get("id") == "impact" or _is_slice_step(step) or _is_dual_suite_step(step)

    steps = _check_steps()
    assert sum(1 for s in steps if gated_by_design(s)) == 3, "selector, slice, full suite"
    offenders = [s.get("name") or s.get("uses") for s in steps
                 if s.get("if") is not None and not gated_by_design(s)]
    assert offenders == [], offenders


@pytest.mark.parametrize("must_run", [
    "py_compile sweep", "ruff lint", "authored-source hygiene",
    "docs-guard complement is wired", "git hook gate armed and firing",
])
def test_named_fast_guards_are_still_in_the_check_job(must_run):
    assert must_run in [s.get("name") for s in _check_steps()]


@pytest.mark.parametrize("event", ("push", "pull_request", "workflow_dispatch"))
def test_check_runs_on_every_event_but_the_schedule(event):
    assert _eval_if(_jobs()["check"].get("if"), event=event) is True
    assert _eval_if(_jobs()["check"].get("if"), event="schedule") is False
