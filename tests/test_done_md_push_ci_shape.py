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

import pytest

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
_REQUIRE_FLAG = re.compile(r"\b(RC_REQUIRE_[A-Z_]+)=1\b")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PYTHON = re.compile(r"^python3?$")
# Shell chain operators. A single `&` (bash background, spaced or not;
# RM-1105) chains too, and so `|&` splits as `|` then `&`; an `&` touching a
# redirection (`2>&1`, `&>`, `>&`) does not. Same `&` predicate as
# tools/stop_claim_gate.py _STATEMENT_BREAK.
_CHAIN = re.compile(r"&&|\|\||;|\||(?<![<>&])&(?![>&])")
_NOT_A_PATH = ("-", '"', "'", "@", "$")


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


def _commands(lines: list[str]) -> list[list[str]]:
    """Each shell command as tokens (RM-817): trailing-backslash continuations
    joined, `&&` / `||` / `;` / `|` / `|&` / single `&` chains split
    (RM-1105), a YAML `- run:` prefix and leading env assignments dropped.
    Naive whitespace split: a quoted argument holding a space is several
    tokens, so a pytest path token carrying a quote character is dropped
    (`-k 'a or b/c'` is no tree), and an `&` or `|` inside quotes still
    splits."""
    logical: list[str] = []
    pending = ""
    for ln in lines:
        pending = f"{pending} {ln.strip()}" if pending else ln.strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical.append(pending)
        pending = ""
    if pending:
        logical.append(pending)
    out = []
    for line in logical:
        for part in _CHAIN.split(line):
            tokens = part.split()
            while tokens and tokens[0] in ("-", "run:"):
                tokens = tokens[1:]
            while tokens and _ENV_ASSIGNMENT.match(tokens[0]):
                tokens = tokens[1:]
            if tokens:
                out.append(tokens)
    return out


def _pytest_args(tokens: list[str]) -> list[str] | None:
    if tokens[0] == "pytest":
        return tokens[1:]
    if _PYTHON.match(tokens[0]) and tokens[1:3] == ["-m", "pytest"]:
        return tokens[3:]
    return None


def _check_script(tokens: list[str]) -> str | None:
    """`tools/x.py` for `python[3] tools/x.py ... --check` or
    `python[3] -m tools.x ... --check`; None for any other command."""
    if not _PYTHON.match(tokens[0]) or len(tokens) < 2:
        return None
    if tokens[1] == "-m" and len(tokens) > 2 and tokens[2] != "pytest":
        script, args = tokens[2].replace(".", "/") + ".py", tokens[3:]
    elif tokens[1].endswith(".py") and not tokens[1].startswith(_NOT_A_PATH):
        script, args = tokens[1], tokens[2:]
    else:
        return None
    return script if "--check" in args else None


def _check_job_non_suite_steps(ci: str) -> dict[str, set[str]]:
    lines = _check_job_run_lines(ci)
    roots, scripts = set(), set()
    for tokens in _commands(lines):
        script = _check_script(tokens)
        if script:
            scripts.add(script)
        for arg in _pytest_args(tokens) or ():
            if (arg.startswith(_NOT_A_PATH) or "'" in arg or '"' in arg
                    or not ("/" in arg or arg.endswith(".py"))):
                continue
            root = arg.rstrip("/")
            if not any(root == r or root.startswith(r + "/") for r in DUAL_SUITE_ROOTS):
                roots.add(root)
    return {
        "sync_checks": scripts,
        "require_flags": set(_REQUIRE_FLAG.findall("\n".join(lines))),
        "orphan_trees": roots,
    }


def _names_check(table: str, script: str) -> bool:
    """A table line names the script (path or dotted module), then `--check`."""
    spellings = (script, script[:-3].replace("/", "."))
    for line in table.split("\n"):
        for name in spellings:
            at = line.find(name)
            if at >= 0 and "--check" in line[at + len(name):]:
                return True
    return False


def test_check_job_derivation_is_not_vacuous():
    found = _check_job_non_suite_steps(_read(CI))
    assert "tools/ds_feed_index.py" in found["sync_checks"], found
    assert found["require_flags"], found
    assert "tools/tests" in found["orphan_trees"], found


def _unnamed_steps(table: str, ci: str) -> list[str]:
    found = _check_job_non_suite_steps(ci)
    return sorted(
        [f"python {p} --check" for p in found["sync_checks"]
         if not _names_check(table, p)]
        + [flag for flag in found["require_flags"] if flag not in table]
        + [f"`{tree}`" for tree in found["orphan_trees"] if f"`{tree}`" not in table]
    )


def test_tier_table_names_every_check_job_step_the_suite_skips():
    missing = _unnamed_steps(_tier_table(_read(DONE)), _read(CI))
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
    assert "data/daemon_slayer/ds_feed_index.json" in table, "say what to commit with the data"


# --------------------------------------------------------------------------- #
# RM-817: the derivation above read only `pytest <tree>` as the first word and
# only `python tools/x.py --check` with `--check` right after the script, so a
# check job gaining `python -m pytest newtree/tests`, `python3 ...`,
# `python tools/x.py --base a --check` or `python -m tools.x --check` stayed
# green while the TIER TABLE named none of them (found s128 by the S-J
# verifier). Each shape is planted in a fixture ci.yml and must redden the
# guard; the real table is the one checked, so a fixture red is the guard's.
# --------------------------------------------------------------------------- #
_FIXTURE_CI = """name: ci
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: index
        run: |
          # a commented step is documentation, never a derived step:
          #   python -m pytest commented/tests
          #   python tools/commented_sync.py --check
          python tools/ds_feed_index.py --check
      - name: suite
        run: |
          pytest tests/ agents/daemon_slayer/tests/ -q --timeout=300 \\
            -n auto --dist loadfile
{planted}
  nightly:
    runs-on: ubuntu-latest
    steps:
      - run: python -m pytest nightly_only/tests --check
"""

PLANTED = {
    "python -m pytest": (
        "          python -m pytest newtree/tests -q", "`newtree/tests`"),
    "python3 -m pytest": (
        "          python3 -m pytest newtree/tests -q", "`newtree/tests`"),
    "inline run: python -m pytest": (
        "      - run: python -m pytest newtree/tests -q", "`newtree/tests`"),
    "second tree on a continuation line": (
        "          pytest tests/ \\\n            newtree/tests -q",
        "`newtree/tests`"),
    "--check after other arguments": (
        "          python tools/new_sync.py --base a --check",
        "python tools/new_sync.py --check"),
    "python3 script --check": (
        "          python3 tools/new_sync.py --check",
        "python tools/new_sync.py --check"),
    "python -m tools.x --check": (
        "          python -m tools.new_sync --check",
        "python tools/new_sync.py --check"),
    "--check behind a chained command": (
        "          python tools/ds_feed_index.py --write && "
        "python tools/new_sync.py --check",
        "python tools/new_sync.py --check"),
    # RM-1105: bash `a & b` backgrounds a and runs b, so b is its own command;
    # `a |& b` pipes stdout and stderr into b.
    "--check behind a backgrounded command": (
        "          python tools/ds_feed_index.py --write & "
        "python tools/new_sync.py --check",
        "python tools/new_sync.py --check"),
    "pytest behind a backgrounded command": (
        "          python tools/ds_feed_index.py --write & "
        "python -m pytest newtree/tests -q",
        "`newtree/tests`"),
    "--check behind a |& pipe": (
        "          python tools/ds_feed_index.py --write |& "
        "python tools/new_sync.py --check",
        "python tools/new_sync.py --check"),
}


def _fixture(planted: str = "") -> str:
    return _FIXTURE_CI.replace("{planted}", planted)


def test_fixture_ci_is_green_against_the_real_table():
    """The control arm: without a planted step the real table names it all."""
    table = _tier_table(_read(DONE))
    assert _unnamed_steps(table, _fixture()) == []
    found = _check_job_non_suite_steps(_fixture())
    assert found["sync_checks"] == {"tools/ds_feed_index.py"}, found
    assert found["orphan_trees"] == set(), found


@pytest.mark.parametrize("shape", sorted(PLANTED))
def test_each_planted_shape_reddens_the_guard(shape):
    planted, expected = PLANTED[shape]
    table = _tier_table(_read(DONE))
    assert _unnamed_steps(table, _fixture(planted)) == [expected], shape


def test_shapes_the_guard_must_not_read_as_steps():
    """Near misses: none is a check-job step the table owes a name."""
    near_misses = (
        "          python tools/new_sync.py --checker",
        "          python tools/new_sync.py --write",
        "          python -c \"import sys; print('--check')\"",
        "          pip install pytest newtree-plugin",
        "          python -m pytest \"@$RUNNER_TEMP/impact_tests.txt\" -q",
        "          python -m pytest --check",
        "          pytest tests/ -k 'a or b/c'",
        # RM-1105: an `&` inside a redirection chains nothing.
        "          python tools/new_sync.py --write 2>&1",
        "          python tools/new_sync.py --write &> sync.log",
        "          python tools/new_sync.py --write >& sync.log",
    )
    table = _tier_table(_read(DONE))
    for line in near_misses:
        assert _unnamed_steps(table, _fixture(line)) == [], line


def test_a_table_naming_the_step_clears_it():
    """The other direction: the guard reads the table, not a constant."""
    planted, expected = PLANTED["--check after other arguments"]
    table = _tier_table(_read(DONE))
    assert _unnamed_steps(table + "\n> - `" + expected + "`", _fixture(planted)) == []
    module_named = table + "\n> - `python -m tools.new_sync --check`"
    assert _unnamed_steps(module_named, _fixture(planted)) == []
    reversed_order = table + "\n> - `--check` then tools/new_sync.py"
    assert _unnamed_steps(reversed_order, _fixture(planted)) == [expected]


def test_single_ampersand_splits_but_redirections_do_not():
    """RM-1105: the splitter itself, so a shape is pinned even where the
    derivation downstream would happen to tolerate a missed split."""
    assert _commands(["a x & b y"]) == [["a", "x"], ["b", "y"]]
    assert _commands(["a x |& b y"]) == [["a", "x"], ["b", "y"]]
    assert _commands(["a x &"]) == [["a", "x"]]
    assert _commands(["a x& b y"]) == [["a", "x"], ["b", "y"]]
    assert _commands(["a x &b y"]) == [["a", "x"], ["b", "y"]]
    assert _commands(["a x && b y || c ; d | e"]) == [
        ["a", "x"], ["b", "y"], ["c"], ["d"], ["e"]]
    for line in ("a 2>&1", "a &> f", "a >& f", "a 1>&2 f"):
        assert _commands([line]) == [line.split()], line
