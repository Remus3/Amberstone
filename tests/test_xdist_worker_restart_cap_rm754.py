"""Every xdist suite run caps worker restarts with `--max-worker-restart=0` (RM-754).

MEASURED (s133 research lane cycle 7, a throwaway project, pytest 9.0.3 /
pytest-xdist 3.8.0 / pytest-timeout 2.4.0; BACKLOG RM-754 REFRESHED): with
`-n 2 --dist loadfile --timeout=5` and one test sleeping past the timeout, the
controller handed the SAME crashed test to every replacement worker - 9
"crashed while running" failures (1 + the default restart budget of 4 x n),
47-49 s wall, identical with and without a child process that outlives it.
`--max-worker-restart=0`: 1 crash, 5 s. At `-n 8 --timeout=300` the default
budget is 32 restarts, so one hung test can hold a worker for hours while the
rest sit idle - the filed "every worker idle, no summary line" wedge. A crash
run is also short: a test defined after the crashed one in the same FILE never
ran and was never reported.

Decision (RM-754 step 2, recorded in BACKLOG): the flag on every xdist command.
Alternatives rejected there: `--dist load` loses the per-file locality the suite
relies on; a conftest process-tree killer does not stop the re-run; an outer
wall cap only bounds it.

Pinned here (the local command-doc half is
tests/test_command_docs_suite_gate.py `test_every_gated_pytest_call_runs_in_parallel`):

  * every pytest step in every workflow that runs xdist (`-n <x>`) carries the
    flag (CI runners get 2-4 workers, a default budget of 8-16 re-runs of a
    300 s timeout, so a hung test burns the step's whole timeout instead of
    failing in five minutes);
  * the flag is NOT in pytest.ini `addopts`: measured, `python -m pytest -p
    no:xdist --max-worker-restart=0 --collect-only -q <file>` exits 4 (usage
    error), so a plugin-less run would break - the flag stays per command;
  * the TIER TABLE says a crash run is red and undercounts the crashed file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_WORKFLOWS = _REPO / ".github" / "workflows"
_PYTEST_INI = _REPO / "pytest.ini"
_DONE = _REPO / "tools" / "done.md"
FLAG = "--max-worker-restart=0"
# `-n auto` / `-n 8` / `-n=4` / `-n8` / `--numprocesses 2` as a whole token.
_XDIST = re.compile(r"(?:^|\s)(?:(?:-n|--numprocesses)(?:\s+|=)\S|-n\d)")


def _yaml():
    # PyYAML is pinned in requirements-ci.txt and installed locally; a missing
    # module must FAIL this guard, never skip it into a blind green.
    import yaml
    return yaml


def _pytest_steps(doc: dict):
    for job_id, job in (doc.get("jobs") or {}).items():
        for i, step in enumerate(job.get("steps") or []):
            run = step.get("run")
            if isinstance(run, str) and "pytest" in run:
                yield job_id, step.get("name") or f"step {i}", run


def _offenders(doc: dict) -> tuple[int, list[str]]:
    seen, bad = 0, []
    for job_id, name, run in _pytest_steps(doc):
        # A shell line continuation splits one command over two lines.
        cmd = run.replace("\\\n", " ")
        if not _XDIST.search(cmd):
            continue
        seen += 1
        if FLAG not in cmd.split():
            bad.append(f"{job_id} / {name}")
    return seen, bad


def test_every_workflow_xdist_pytest_step_caps_worker_restarts():
    yaml = _yaml()
    files = sorted(_WORKFLOWS.glob("*.yml"))
    assert files, "no workflow files found - the sweep went blind"
    total, bad = 0, []
    for path in files:
        seen, off = _offenders(yaml.safe_load(path.read_text(encoding="utf-8")))
        total += seen
        bad += [f"{path.name}: {o}" for o in off]
    # ci.yml runs xdist in nightly-full-suite, the push impact slice and the
    # check job's full dual suite (BACKLOG RM-754 s144 re-probe): >= 3.
    assert total >= 3, f"only {total} xdist pytest steps found - the sweep went blind"
    assert not bad, f"xdist pytest steps without {FLAG}:\n" + "\n".join(bad)


def test_the_detector_flags_a_step_without_the_cap():
    # Positive and negative controls on the predicate, so an always-green
    # sweep fails here.
    no_cap = {"jobs": {"j": {"steps": [
        {"name": "s", "run": "pytest tests/ -q --timeout=300 \\\n  -n auto --dist loadfile\n"}]}}}
    capped = {"jobs": {"j": {"steps": [
        {"name": "s", "run": f"pytest tests/ -q -n auto --dist loadfile {FLAG}\n"}]}}}
    serial = {"jobs": {"j": {"steps": [
        {"name": "s", "run": "pytest tests/test_x.py -q --nightly-only\n"}]}}}
    assert _offenders(no_cap) == (1, ["j / s"])
    assert _offenders(capped) == (1, [])
    assert _offenders(serial) == (0, [])
    # A different restart budget is not the cap.
    other = {"jobs": {"j": {"steps": [
        {"name": "s", "run": "pytest tests/ -n 4 --max-worker-restart=1\n"}]}}}
    assert _offenders(other) == (1, ["j / s"])
    # RM-1104 (c) sibling: pytest parses `-n8` as `-n 8`.
    glued = {"jobs": {"j": {"steps": [{"name": "s", "run": "pytest tests/ -n8\n"}]}}}
    assert _offenders(glued) == (1, ["j / s"])


def test_the_cap_is_not_in_pytest_ini_addopts():
    text = _PYTEST_INI.read_bytes().decode("utf-8")
    addopts = [ln for ln in text.splitlines() if ln.strip().startswith("addopts")]
    assert addopts, "pytest.ini has no addopts line - the guard went blind"
    assert not any("max-worker-restart" in ln for ln in addopts), (
        "the flag in addopts breaks every `-p no:xdist` run (usage error, exit 4); "
        "keep it on each xdist command")


@pytest.mark.parametrize("needle", [FLAG, "crashed while running", "undercount"])
def test_the_tier_table_explains_a_crash_run(needle):
    done = _DONE.read_bytes().decode("utf-8")
    start = done.index("**TIER TABLE")
    table = done[start:done.index("\n\n", start)]
    assert needle in table, needle
