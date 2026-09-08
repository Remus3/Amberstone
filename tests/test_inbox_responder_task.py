"""RC-InboxResponder scheduled-task registration arms (spec sections 11, 12, 14).

WHY THIS EXISTS. The runner is registered under a scheduled task with a hard
ExecutionTimeLimit. If the worst-case cycle can outlast that limit, the Task
Scheduler kills `pythonw` mid-cycle and the failure presents as a silently
missing tick rather than an error - there is nothing to see in the log because
the process never got to write the END row. So the bound has to be proven from
the constants, statically, in CI, and it has to be proven against the constant
NAMES rather than against numbers copied out of the spec: a number copied here
goes stale the moment somebody edits the runner, and a stale copy passes.

The constants span TWO files on purpose. The per-call timeouts live in
`tools/inbox_responder_runner.py`; the tree-kill costs live in
`tools/inbox_responder_procs.py`, which owns the only literal `subprocess`
calls in the responder. The census below asserts each name is assigned exactly
once at module level in its OWN file, because that is the property the sum
depends on - a second assignment anywhere would make "the value of
SPAWN_TIMEOUT_S" ambiguous and the derived bound meaningless.

READ THE SOURCE, DO NOT IMPORT IT. Every value here is parsed out of the file
text with `ast`. Importing the module and reading attributes would tell us the
final value of a name but not how many times it was assigned, which is half of
what this test is for.

THE KILL ALLOWANCE IS LOAD-BEARING, and the third arm proves it. Section 11
records a REFUTED sum: if every timed-out call received the full tree-kill
sequence, the worst-case cycle would carry 14 kill terms and reach 1160 s,
which BLOWS the 600 s limit. It comes back under the limit only because
`procs.KillBudget` grants the full kill sequence to the FIRST timeout of a
cycle and gives every later one a bare `proc.kill()` at zero cost. So the arm
asserts the refuted expression EXCEEDS the ETL. If someone deletes the budget
and this file stays green, the green is a lie - hence the assertion in the
failing direction.

NO ACCOUNT NAME LIVES HERE. The ps1 resolves its principal from
`$env:USERNAME` at install time. This test pins the literal token and asserts
that no `-UserId` value is a bare word, which is the property that keeps a
machine account out of the tree; it never writes an account name of its own.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

RUNNER = ROOT / "tools" / "inbox_responder_runner.py"
PROCS = ROOT / "tools" / "inbox_responder_procs.py"
PS1 = ROOT / "ops" / "install_RC_InboxResponder.ps1"

# The nine timing constants that live in the runner.
RUNNER_NAMES = (
    "SLOT_TIMEOUT_S",
    "EXPORT_TIMEOUT_S",
    "SPAWN_TIMEOUT_S",
    "MEASURE_TIMEOUT_S",
    "PRECHECK_TIMEOUT_S",
    "PRECHECK_CALLS_PER_MEASURE",
    "MAX_MEASURES",
    "SLACK_S",
    "TASK_ETL_S",
)

# The three tree-kill constants, which live in procs and NOWHERE else.
PROCS_NAMES = (
    "KILL_CMD_TIMEOUT_S",
    "KILL_WAIT_S",
    "KILL_ALLOWANCE_PER_CYCLE",
)

# Modules that must reach a child process only through procs. The console-flash
# guard covers procs by name; these three are covered by having no spawn at all.
FUNNELLED_MODULES = (
    "tools/inbox_responder_spawn.py",
    "tools/inbox_responder_exec.py",
    "tools/inbox_responder_export.py",
)


# ---------------------------------------------------------------------------
# Source parsing helpers. Every one of these takes SOURCE TEXT, not a path, so
# the mutation probes at the bottom of the file can feed them a doctored copy
# in memory and prove the arms actually fail when the constants go bad.
# ---------------------------------------------------------------------------


def _module_level_assign_counts(src: str, name: str) -> int:
    """How many times `name` is bound by a top-level assignment statement."""
    tree = ast.parse(src)
    count = 0
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                count += 1
    return count


def _any_rebind_count(src: str, name: str) -> int:
    """How many times `name` is bound ANYWHERE (incl. inside a function)."""
    tree = ast.parse(src)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                count += 1
    return count


def _module_level_value(src: str, name: str) -> int:
    """The int bound to `name` by its single top-level assignment."""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                literal = ast.literal_eval(value)
                assert isinstance(literal, int), f"{name} is not an int: {literal!r}"
                return literal
    raise AssertionError(f"{name} has no module-level assignment")


def _constants(runner_src: str, procs_src: str) -> dict:
    values = {n: _module_level_value(runner_src, n) for n in RUNNER_NAMES}
    values.update({n: _module_level_value(procs_src, n) for n in PROCS_NAMES})
    return values


def _base_terms(c: dict) -> int:
    """Everything except the kill allowance: the per-call timeouts plus slack."""
    return (
        c["SLOT_TIMEOUT_S"]
        + c["EXPORT_TIMEOUT_S"]
        + c["SPAWN_TIMEOUT_S"]
        + c["MAX_MEASURES"] * (
            c["MEASURE_TIMEOUT_S"]
            + c["PRECHECK_CALLS_PER_MEASURE"] * c["PRECHECK_TIMEOUT_S"]
        )
        + c["SLACK_S"]
    )


def _kill_term(c: dict) -> int:
    return c["KILL_CMD_TIMEOUT_S"] + c["KILL_WAIT_S"]


def _worst_case_cycle_s(c: dict) -> int:
    """Section 11 formula. Spec works this out as 380."""
    return _base_terms(c) + c["KILL_ALLOWANCE_PER_CYCLE"] * _kill_term(c)


def _two_process_export_cycle_s(c: dict) -> int:
    """ensure_export issues TWO git processes on a cache miss. Spec: 440."""
    return _worst_case_cycle_s(c) + c["EXPORT_TIMEOUT_S"]


def _refuted_per_call_kill_cycle_s(c: dict) -> int:
    """The REFUTED shape: a full tree-kill per timed-out call. Spec: 1160."""
    kill_terms = 2 + c["MAX_MEASURES"] * (1 + c["PRECHECK_CALLS_PER_MEASURE"])
    return _base_terms(c) + kill_terms * _kill_term(c)


def _refuted_kill_term_count(c: dict) -> int:
    return 2 + c["MAX_MEASURES"] * (1 + c["PRECHECK_CALLS_PER_MEASURE"])


def _ps1_single(pattern: str, text: str, label: str) -> re.Match:
    """Match `pattern` and assert it matches EXACTLY once (vacuity control).

    A zero-match regex passes any `not in` style assertion silently, and a
    two-match regex means the ps1 carries a second, possibly contradicting,
    spelling. Both are failures, so every ps1 regex in this file goes through
    here rather than being used directly.
    """
    matches = list(re.finditer(pattern, text))
    assert len(matches) == 1, (
        f"{label}: expected exactly 1 match for {pattern!r} in "
        f"{PS1.name}, found {len(matches)}"
    )
    return matches[0]


def _read(path: Path) -> str:
    assert path.exists(), f"{path} is missing"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def runner_src() -> str:
    return _read(RUNNER)


@pytest.fixture(scope="module")
def procs_src() -> str:
    return _read(PROCS)


@pytest.fixture(scope="module")
def ps1_text() -> str:
    return _read(PS1)


@pytest.fixture(scope="module")
def consts(runner_src: str, procs_src: str) -> dict:
    return _constants(runner_src, procs_src)


# ---------------------------------------------------------------------------
# Census: each name assigned exactly once, at module level, in its own file.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", RUNNER_NAMES)
def test_runner_constant_assigned_exactly_once_at_module_level(
    name: str, runner_src: str
) -> None:
    count = _module_level_assign_counts(runner_src, name)
    assert count == 1, (
        f"{name} has {count} module-level assignments in {RUNNER.name}; "
        "the derived cycle bound is only meaningful when it has exactly one"
    )
    assert _any_rebind_count(runner_src, name) == 1, (
        f"{name} is rebound somewhere else in {RUNNER.name}"
    )


@pytest.mark.parametrize("name", PROCS_NAMES)
def test_procs_constant_assigned_exactly_once_at_module_level(
    name: str, procs_src: str
) -> None:
    count = _module_level_assign_counts(procs_src, name)
    assert count == 1, (
        f"{name} has {count} module-level assignments in {PROCS.name}; "
        "the derived cycle bound is only meaningful when it has exactly one"
    )
    assert _any_rebind_count(procs_src, name) == 1, (
        f"{name} is rebound somewhere else in {PROCS.name}"
    )


@pytest.mark.parametrize("name", PROCS_NAMES)
def test_kill_constants_live_in_procs_only(name: str, runner_src: str) -> None:
    """A private runner copy of a kill constant would let the two drift apart."""
    assert _any_rebind_count(runner_src, name) == 0, (
        f"{name} is assigned in {RUNNER.name} as well as {PROCS.name}; "
        "procs owns the tree-kill costs and must be the only owner"
    )


@pytest.mark.parametrize("name", RUNNER_NAMES)
def test_runner_timing_constants_are_not_shadowed_in_procs(
    name: str, procs_src: str
) -> None:
    assert _any_rebind_count(procs_src, name) == 0, (
        f"{name} is assigned in {PROCS.name}; the runner owns it"
    )


# ---------------------------------------------------------------------------
# The bound. Section 12 row `timeouts-below-ETL`.
# ---------------------------------------------------------------------------


def test_worst_case_cycle_is_below_the_task_execution_time_limit(
    consts: dict,
) -> None:
    total = _worst_case_cycle_s(consts)
    etl = consts["TASK_ETL_S"]
    assert total < etl, (
        f"worst-case cycle {total}s is not under the {etl}s ExecutionTimeLimit "
        f"(constants: {consts})"
    )


def test_two_process_export_worst_case_is_below_the_limit(consts: dict) -> None:
    """Cache miss: `rev-parse origin/main` returns late, then `archive` times out."""
    total = _two_process_export_cycle_s(consts)
    etl = consts["TASK_ETL_S"]
    assert total < etl, (
        f"two-process-export worst case {total}s is not under the {etl}s "
        f"ExecutionTimeLimit (constants: {consts})"
    )
    assert total == _worst_case_cycle_s(consts) + consts["EXPORT_TIMEOUT_S"]


def test_kill_allowance_is_load_bearing_not_decorative(consts: dict) -> None:
    """The REFUTED per-call-kill sum must EXCEED the ETL.

    This is the arm that stops the budget from being deleted as dead weight.
    If a full tree-kill per timed-out call fitted under the limit, the budget
    would be optional; it does not, so it is not.
    """
    refuted = _refuted_per_call_kill_cycle_s(consts)
    etl = consts["TASK_ETL_S"]
    assert refuted > etl, (
        f"the per-call-kill sum is {refuted}s, which FITS under the {etl}s "
        f"limit - the kill allowance would then be decorative and this arm no "
        f"longer proves anything (constants: {consts})"
    )
    assert refuted > _worst_case_cycle_s(consts)
    assert consts["KILL_ALLOWANCE_PER_CYCLE"] < _refuted_kill_term_count(consts), (
        "the allowance is not actually narrowing the number of full kills"
    )


def test_recorded_spec_figures_still_hold(consts: dict) -> None:
    """Cross-check against the worked numbers in spec section 11.

    Deliberately SECOND to the name-derived arms above: if a constant changes
    on purpose, the arms above stay green and only this one goes red, which is
    the signal to update the spec prose rather than to relax the bound.
    """
    assert _worst_case_cycle_s(consts) == 380
    assert _two_process_export_cycle_s(consts) == 440
    assert _refuted_per_call_kill_cycle_s(consts) == 1160
    assert _refuted_kill_term_count(consts) == 14
    assert consts["TASK_ETL_S"] == 600


# ---------------------------------------------------------------------------
# The ps1. Each regex carries a count == 1 vacuity control via _ps1_single.
# ---------------------------------------------------------------------------


def test_execution_time_limit_matches_task_etl_constant(
    ps1_text: str, consts: dict
) -> None:
    match = _ps1_single(
        r"-ExecutionTimeLimit\s*\(New-TimeSpan\s+-Minutes\s+(\d+)\)",
        ps1_text,
        "ExecutionTimeLimit",
    )
    minutes = int(match.group(1))
    assert minutes * 60 == consts["TASK_ETL_S"], (
        f"ps1 registers a {minutes}-minute ExecutionTimeLimit "
        f"({minutes * 60}s) but TASK_ETL_S is {consts['TASK_ETL_S']}s"
    )


def test_repetition_interval_is_shorter_than_the_execution_time_limit(
    ps1_text: str, consts: dict
) -> None:
    """A 10-minute ETL under a 5-minute repeat skips at most one tick."""
    match = _ps1_single(
        r"-RepetitionInterval\s*\(New-TimeSpan\s+-Minutes\s+(\d+)\)",
        ps1_text,
        "RepetitionInterval",
    )
    interval_s = int(match.group(1)) * 60
    assert 0 < interval_s < consts["TASK_ETL_S"]


def test_principal_is_s4u(ps1_text: str) -> None:
    _ps1_single(r"-LogonType\s+S4U", ps1_text, "LogonType S4U")


def test_multiple_instances_is_ignorenew(ps1_text: str) -> None:
    """Pinned in the SHIPPED spelling: the property assignment.

    The ps1 carries the parameter spelling `-MultipleInstances IgnoreNew` in a
    COMMENT explaining why it is not used (the parameter was reported missing
    on Windows PowerShell 5.1), so pinning that spelling would pin a comment.
    Assert the property assignment instead, and assert it is on a live line.
    """
    match = _ps1_single(
        r"\$settings\.MultipleInstances\s*=\s*\"IgnoreNew\"",
        ps1_text,
        "MultipleInstances property assignment",
    )
    line = ps1_text[: match.start()].rsplit("\n", 1)[-1]
    assert not line.lstrip().startswith("#"), (
        "the only IgnoreNew assignment in the ps1 is inside a comment"
    )


def test_action_runs_pythonw_not_python(ps1_text: str) -> None:
    """pythonw.exe or the scheduled tick flashes a console every 5 minutes."""
    match = _ps1_single(
        r"\$Python\s*=\s*\"[^\"]*pythonw\.exe\"", ps1_text, "pythonw path"
    )
    assert "python.exe" not in match.group(0)


def test_working_directory_is_passed_to_the_action(ps1_text: str) -> None:
    _ps1_single(r"-WorkingDirectory\s+\$Root", ps1_text, "WorkingDirectory")


def test_userid_is_the_env_token_and_never_a_bare_account_name(
    ps1_text: str,
) -> None:
    """The principal resolves at INSTALL time; no account name is in the tree."""
    match = _ps1_single(r"-UserId\s+(\S+)", ps1_text, "UserId")
    value = match.group(1)
    assert value == "$env:USERNAME", (
        f"-UserId is {value!r}; it must be the literal $env:USERNAME token so "
        "the installing account is resolved from the shell, never written down"
    )
    assert value.startswith("$"), "a bare word -UserId value is an account name"


def test_no_account_name_appears_anywhere_in_the_ps1(ps1_text: str) -> None:
    """Probe with the CURRENT account rather than hardcoding one.

    Writing a name here to search for would itself put an account name in the
    tree, which is the thing being prevented. So take the installing account
    from the environment at test time and assert its absence.
    """
    account = os.environ.get("USERNAME") or os.environ.get("USER")
    if not account or len(account) < 3:
        pytest.skip("no usable account name in the environment to probe with")
    assert account.lower() not in ps1_text.lower(), (
        f"the installing account name appears in {PS1.name}; the ps1 must "
        "resolve its principal from $env:USERNAME instead"
    )


# ---------------------------------------------------------------------------
# console-flash cross-check (section 12 row `console-flash`).
# ---------------------------------------------------------------------------


def test_procs_is_listed_in_the_console_flash_guard() -> None:
    """procs owns the responder's only spawns, so the guard must cover it."""
    guard = ROOT / "tests" / "test_no_console_flash_scheduled_tools.py"
    src = _read(guard)
    tree = ast.parse(src)
    listed = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "SCHEDULED_SPAWNERS":
                listed = ast.literal_eval(node.value)
    assert listed is not None, "SCHEDULED_SPAWNERS not found in the guard"
    assert "tools/inbox_responder_procs.py" in listed, (
        "RC-InboxResponder runs unattended under pythonw every 5 minutes and "
        "procs carries its literal subprocess calls, so it must be guarded"
    )


@pytest.mark.parametrize("rel", FUNNELLED_MODULES)
def test_funnelled_modules_carry_no_literal_subprocess_call(rel: str) -> None:
    """One process seam. A spawn added here would bypass the flash guard."""
    src = _read(ROOT / rel)
    tree = ast.parse(src)
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "subprocess"
    ]
    assert not offenders, (
        f"{rel} references subprocess directly at line(s) {offenders}; every "
        "responder child process must go through inbox_responder_procs.py, "
        "which is the module the console-flash guard covers"
    )


# ---------------------------------------------------------------------------
# Mutation probes. These prove the arms above are not vacuous by feeding the
# same helpers a DOCTORED in-memory copy of the source and asserting the
# derived bound actually breaks. Nothing on disk is touched.
# ---------------------------------------------------------------------------


def _mutated(src: str, name: str, new_value: int) -> str:
    pattern = rf"(?m)^{re.escape(name)} = \d+$"
    mutated, count = re.subn(pattern, f"{name} = {new_value}", src)
    assert count == 1, f"mutation of {name} matched {count} lines, expected 1"
    return mutated


def test_mutation_spawn_timeout_breaks_the_bound(
    runner_src: str, procs_src: str
) -> None:
    consts = _constants(_mutated(runner_src, "SPAWN_TIMEOUT_S", 400), procs_src)
    assert _worst_case_cycle_s(consts) >= consts["TASK_ETL_S"]


def test_mutation_precheck_calls_breaks_the_bound(
    runner_src: str, procs_src: str
) -> None:
    consts = _constants(
        _mutated(runner_src, "PRECHECK_CALLS_PER_MEASURE", 30), procs_src
    )
    assert _worst_case_cycle_s(consts) >= consts["TASK_ETL_S"]


def test_mutation_kill_allowance_in_procs_breaks_the_bound(
    runner_src: str, procs_src: str
) -> None:
    consts = _constants(
        runner_src, _mutated(procs_src, "KILL_ALLOWANCE_PER_CYCLE", 6)
    )
    assert _worst_case_cycle_s(consts) >= consts["TASK_ETL_S"]


def test_mutation_duplicate_assignment_breaks_the_census(runner_src: str) -> None:
    doctored = runner_src + "\nSLACK_S = 999\n"
    assert _module_level_assign_counts(doctored, "SLACK_S") == 2


def test_mutation_etl_regex_is_not_vacuous(ps1_text: str) -> None:
    """A renamed parameter must fail loudly rather than match zero times."""
    doctored = ps1_text.replace("-ExecutionTimeLimit", "-ExecutionTimeLimitX")
    with pytest.raises(AssertionError):
        _ps1_single(
            r"-ExecutionTimeLimit\s*\(New-TimeSpan\s+-Minutes\s+(\d+)\)",
            doctored,
            "ExecutionTimeLimit",
        )
