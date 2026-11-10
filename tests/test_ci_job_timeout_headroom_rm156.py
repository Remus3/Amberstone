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
import shlex
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
# 2026-10-31 UPDATE (s146 C3), which RETIRES the "floor stays conservative"
# policy just above: a 40m floor let the live ceiling go stale with every guard
# green. Dispatch run 41231173460 was killed by the 75m `full dual suite` step
# ceiling with no hang - the suite grew about 18 percent (42.9k -> 54.4k tests,
# 2026-10-25 .. 10-31) and hosted-runner speed varies about 1.5x on ONE sha
# (a5c8d94ff: 55.1m dispatch vs 36.7m nightly), so a 52.5m full run x 1.5 is
# about 79m, over 75 before any further growth. Both dual-suite steps (`check`
# and `nightly-full-suite`) were raised 75 -> 110 and both jobs 95 -> 125. The
# floor now pins that decision, so a regression to 75 is red here rather than
# a killed run on the next dispatch. Re-measure before LOWERING it.
# 2026-11-07 UPDATE (RM-2036, s153). Push run 42383196203 on `e37f0d1b4` was
# killed by the 110m step ceiling at 95 percent of its progress stream with no
# pytest summary, so its ~72 failures went unnamed (RM-2037). Suite-step minutes
# over the 11 newest hosted full runs (BACKLOG RM-2036): 62.1 .. 106.6 complete,
# and 110.2 killed at 95 percent, which projects to 110.2 / 0.95 = 116.0 min.
# The pytest stop (`--session-timeout`, below) is the number a slow run must
# clear, so it is sized first: 116.0 / 0.85 = 136.5 min is the RM-2036 15
# percent headroom floor today, and the suite grew 64.3k -> 69.5k outcomes
# (+8 percent) in the 1.6 days 52266153f..e37f0d1b4, so 150 min keeps 15
# percent headroom through about +10 percent more growth (127.5 min of tail)
# and stops only past +29 percent. Step = 150 + 10 = 160 (see
# _SUMMARY_SLACK_MIN); job = 160 + 15 = 175 (guard floor 172).
_MIN_SUITE_STEP_CEILING_MIN = 160

# RM-2036: pytest itself must stop BEFORE the step ceiling, or a slow run is
# killed mid-stream and prints no failure summary. pytest-timeout's
# `--session-timeout=<seconds>` (2.3.0+, pinned 2.4.0 in
# .github/ci/requirements-ci.txt) is checked by EACH xdist worker after each
# test; a worker past it sets `session.shouldfail`, xdist's controller turns
# that into `Interrupted` and pytest prints FAILURES, the short test summary
# and the stats line, exit code 2 (a red step). MEASURED 2026-11-07 on a
# scratch project, pytest-xdist 3.8.0 / pytest-timeout 2.4.0, `-n 2 --dist
# loadfile --max-worker-restart=0 --session-timeout=4`: rc 2 in 5 s, every
# FAILED nodeid listed, then `xdist.dsession.Interrupted: session-timeout: 4.0
# sec exceeded`. A worker checks only BETWEEN tests, so the stop can land one
# per-test `--timeout` late; the step ceiling must clear the session timeout by
# that plus _SUMMARY_SLACK_MIN for fixture teardown, xdist node teardown and
# printing the failure list. Not a `timeout -s INT` wrapper: every ci.yml guard
# derives the suite step from a line that STARTS with `pytest`.
_MIN_SESSION_TIMEOUT_MIN = 150
_SUMMARY_SLACK_MIN = 5

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
    """The module's own dependency must not disarm it in a job that runs it.

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
            if not any(_run_text_installs_pyyaml(r, _REPO) for r in runs):
                offenders.append(f"{path.name}:{job_name}")
    assert not offenders, (
        f"job(s) {sorted(offenders)} run {me_rel} but install no pyyaml - "
        "neither on a `pip install` line nor pinned (`pyyaml==`) in the `-r` "
        "file it installs - so every assertion in this module degrades to a "
        "SKIP there, and a skipped test is a green tick. Pin pyyaml in that "
        "job's hashed requirements file (or name it on its pip install line)."
    )


# Since the 2026-10-05 supply-chain order CI installs from HASH-PINNED files
# (`pip install --require-hashes -r .github/ci/requirements-*.txt`), so pyyaml
# is no longer on the install line itself. "Installs pyyaml" means: a
# `pip install` line (shell comment stripped - a comment naming pyyaml installs
# nothing) names pyyaml as an argument, or names a `-r` file - resolved from the
# repo root, like the runner's checkout - that pins `pyyaml==`, following nested
# `-r` lines relative to their own file as pip does. Twin of the helper in
# tests/test_ci_docs_guard_coverage.py, deliberately NOT shared: this module's
# docstring above is the record of why each guard must stand on its own.
_PIP_INSTALL = re.compile(r"\bpip3?\s+install\b(?P<args>.*)$")
_SHELL_COMMENT = re.compile(r"(?:^|\s)#.*$")
_PYYAML_EXACT_PIN = re.compile(r"(?i)^pyyaml\s*===?\s*\S")


def _requirements_file_pins_pyyaml(path: Path, _seen: set | None = None) -> bool:
    seen = set() if _seen is None else _seen
    try:
        path = path.resolve()
    except OSError:
        return False
    if path in seen or not path.is_file():
        return False
    seen.add(path)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = _SHELL_COMMENT.sub("", raw).strip()
        if _PYYAML_EXACT_PIN.match(line):
            return True
        nested = re.match(r"(?:-r|--requirement)(?:\s*=\s*|\s+)?(\S+)$", line)
        if nested and _requirements_file_pins_pyyaml(path.parent / nested.group(1), seen):
            return True
    return False


def _run_text_installs_pyyaml(text: str, root: Path) -> bool:
    text = re.sub(r"\\\r?\n", " ", text)
    for raw in text.splitlines():
        m = _PIP_INSTALL.search(_SHELL_COMMENT.sub("", raw))
        if not m:
            continue
        try:
            tokens = shlex.split(m.group("args"))
        except ValueError:
            tokens = m.group("args").split()
        i = 0
        while i < len(tokens):
            tok, ref = tokens[i], None
            if tok in ("-r", "--requirement") and i + 1 < len(tokens):
                ref, i = tokens[i + 1], i + 1
            elif tok.startswith("--requirement="):
                ref = tok.split("=", 1)[1]
            elif tok.startswith("-r") and len(tok) > 2:
                ref = tok[2:]
            elif not tok.startswith("-") and re.split(r"[\[=<>~!;]", tok, maxsplit=1)[0].lower() == "pyyaml":
                return True
            if ref is not None and _requirements_file_pins_pyyaml(root / ref):
                return True
            i += 1
    return False


@pytest.mark.parametrize(
    ("install_line", "req_body", "expected"),
    [
        ("pip install --require-hashes -r ci/req.txt", "pyyaml==6.0.3 \\\n    --hash=sha256:00\n", True),
        # NEGATIVE CONTROLS: a hashed file without pyyaml, and a trailing
        # comment naming it, both install nothing.
        ("pip install --require-hashes -r ci/req.txt", "pytest==9.1.1 \\\n    --hash=sha256:00\n", False),
        ("pip install --require-hashes -r ci/req.txt  # pyyaml", "pytest==9.1.1\n", False),
        ("pip install -r ci/req.txt", "# pyyaml==6.0.3\npytest==9.1.1\n", False),
        ("pip install -r ci/missing.txt", "pyyaml==6.0.3\n", False),
        ("pip install -r ci/outer.txt", "pyyaml==6.0.3\n", True),
        ("pip install pytest pytest-timeout pyyaml", "", True),
    ],
)
def test_pyyaml_install_probe_reads_the_requirements_file(tmp_path, install_line, req_body, expected):
    """The probe must not be satisfied by a comment or by a hashed file that
    lacks pyyaml, or the per-job guard above is decoration."""
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "req.txt").write_text(req_body, encoding="utf-8")
    (tmp_path / "ci" / "outer.txt").write_text("-r req.txt\n", encoding="utf-8")
    run = f'set -e\n{install_line}\npython -c "import yaml"\n'
    assert _run_text_installs_pyyaml(run, tmp_path) is expected


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


def _pytest_command_lines(run: str) -> list[str]:
    """The logical `pytest ...` lines of a `run:` body: continuations joined,
    whole-line and trailing shell comments dropped, so an option that appears
    only in prose cannot satisfy the guard."""
    joined = re.sub(r"\\\r?\n", " ", run)
    out = []
    for raw in joined.splitlines():
        line = _SHELL_COMMENT.sub("", raw).strip()
        if re.match(r"pytest\b", line):
            out.append(line)
    return out


def _option_seconds(line: str, name: str) -> float | None:
    """`--name=N` or `--name N` on one pytest line, as seconds; None if absent."""
    try:
        tokens = shlex.split(line)
    except ValueError:
        tokens = line.split()
    for i, tok in enumerate(tokens):
        value = None
        if tok.startswith(f"--{name}="):
            value = tok.split("=", 1)[1]
        elif tok == f"--{name}" and i + 1 < len(tokens):
            value = tokens[i + 1]
        if value is not None:
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _pytest_stop_problems(step: dict) -> list[str]:
    """Why this step's pytest would NOT stop and print its summary before the
    step ceiling kills it (RM-2036); empty when it would."""
    ceiling = step.get("timeout-minutes")
    lines = _pytest_command_lines(step.get("run") or "")
    if not lines:
        return ["no pytest command line in the step"]
    problems = []
    for line in lines:
        session_s = _option_seconds(line, "session-timeout")
        per_test_s = _option_seconds(line, "timeout")
        if session_s is None:
            problems.append(
                "no `--session-timeout=<seconds>` on the pytest line, so a slow "
                "run is killed by the step ceiling with no failure summary"
            )
            continue
        if per_test_s is None:
            problems.append(
                "no per-test `--timeout=<seconds>`, so one hung test can hold "
                "a worker past the session timeout without bound"
            )
            continue
        if session_s < _MIN_SESSION_TIMEOUT_MIN * 60:
            problems.append(
                f"--session-timeout={session_s:g}s is under the RM-2036 floor "
                f"of {_MIN_SESSION_TIMEOUT_MIN * 60}s, so it would interrupt "
                "an ordinary slow-but-green run"
            )
        if isinstance(ceiling, (int, float)):
            need_s = session_s + per_test_s + _SUMMARY_SLACK_MIN * 60
            if ceiling * 60 < need_s:
                problems.append(
                    f"step ceiling {ceiling}m = {ceiling * 60}s is under "
                    f"session {session_s:g}s + one per-test timeout "
                    f"{per_test_s:g}s + {_SUMMARY_SLACK_MIN}m summary slack "
                    f"= {need_s:g}s, so the step can die before pytest prints"
                )
    return problems


def test_dual_suite_steps_stop_pytest_before_their_step_ceiling():
    """RM-2036: run 42383196203 hit the step ceiling at 95 percent and printed
    no summary, so ~72 failures went unnamed. pytest must end itself first."""
    offenders = []
    for job_name, _job, step in _dual_suite_steps(_load_workflows()["ci.yml"]):
        for problem in _pytest_stop_problems(step):
            offenders.append(f"{job_name}: {problem}")
    assert not offenders, "\n".join(offenders)


_GOOD_RUN = (
    "# a comment naming --session-timeout=1 must not count\n"
    "pytest tests/ agents/daemon_slayer/tests/ -q --tb=short --timeout=300 \\\n"
    "  -n auto --dist loadfile --max-worker-restart=0 --session-timeout=9000\n"
)


@pytest.mark.parametrize(
    ("step", "expect_ok"),
    [
        ({"timeout-minutes": 160, "run": _GOOD_RUN}, True),
        # NEGATIVE CONTROLS: the shape this module must reject.
        ({"timeout-minutes": 160, "run": _GOOD_RUN.replace(" --session-timeout=9000", "")}, False),
        (
            {"timeout-minutes": 160, "run": _GOOD_RUN.replace(" --session-timeout=9000", "  # --session-timeout=9000")},
            False,
        ),
        ({"timeout-minutes": 159, "run": _GOOD_RUN}, False),
        ({"timeout-minutes": 160, "run": _GOOD_RUN.replace("--timeout=300", "--timeout=600")}, False),
        ({"timeout-minutes": 160, "run": _GOOD_RUN.replace("9000", "3000")}, False),
        ({"timeout-minutes": 160, "run": _GOOD_RUN.replace(" --timeout=300", "")}, False),
        ({"timeout-minutes": 160, "run": _GOOD_RUN.replace("--session-timeout=9000", "--session-timeout 9000")}, True),
    ],
)
def test_pytest_stop_probe_rejects_a_missing_or_late_stop(step, expect_ok):
    """The probe above is not decoration: each control flips it."""
    assert (not _pytest_stop_problems(step)) is expect_ok, _pytest_stop_problems(step)
