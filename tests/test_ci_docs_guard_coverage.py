"""CI must run the guards that read docs, on the pushes that change docs.

MEASURED 2026-07-27. `.github/workflows/ci.yml` carries, on BOTH `push` and
`pull_request`, the 2026-06-30 MINUTE SAVER::

    paths-ignore:
      - '**/*.md'

and until 2026-09-06 `.github/workflows/codspeed.yml` carried the same; that
workflow has since been deleted (docs/OPERATIONS.md "Why CodSpeed was dropped"),
which changes the count and not the contract. A docs-only commit therefore
triggers NO workflow at all. But dozens of test modules read tracked
`.md` files off disk and assert on their CONTENT, so a `.md`-only commit can
turn a `.py` guard RED with nothing watching. It happened twice in a row:

* `b412c2d8` (docs-only) pushed the newest ``| R<n> |`` row of
  `docs/ORCHESTRATION_PLAN.md` past the 16000-byte director-context tail and
  turned `tests/test_loop_director_context_caps.py` RED. CI did not run.
* `ae829bb2`, the docs-only FIX for that, also ran no CI - so the fix's own
  green was never machine-confirmed.

This is the R207 class: a guard exempted from the very thing it guards.

The contract pinned here is the COMPLEMENT, not the removal of the minute
saver. Docs-only commits are ~55% of history and a pure prose edit that no
guard reads still must not pay for the full suite. So: whenever a workflow
declines `**/*.md`, some other workflow must ACCEPT `**/*.md` and run the
md-reading guards.

Two design constraints, both from scars in this repo:

1. The selected universe is DERIVED, never listed. A hand-maintained list in
   YAML would be green over every module added after it was written - the
   `SCHEDULED_SPAWNERS` failure (memory
   `reference_guard_derives_universe_from_wrong_side`). So the workflow calls
   `tools/md_guard_selector.py`, and this module re-derives the universe by an
   INDEPENDENT AST pass and asserts the selector's LIVE output covers it.
2. The contract is read off disk, not hardcoded. A pinned expected string is a
   substring pin, not a contract test (memory
   `feedback_contract_test_must_read_the_contract_from_disk`). So the real
   workflow YAML is parsed and its real steps are inspected.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_REPO = _HERE.parent.parent
_WORKFLOW_DIR = _REPO / ".github" / "workflows"
_SELECTOR_REL = "tools/md_guard_selector.py"
_SELECTOR = _REPO / "tools" / "md_guard_selector.py"

# The module that actually went RED under a docs-only push. It reads
# docs/ORCHESTRATION_PLAN.md, docs/LEDGER.md and ROADMAP.md off disk.
_SCAR_MODULE = "tests/test_loop_director_context_caps.py"

_MD_GLOB_PATTERNS = ("**/*.md", "*.md", "**/*.MD", "**.md")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _yaml():
    """PyYAML, or skip.

    An optional third-party import is the one skip reason the 2026-07-27 skip
    audit left standing, because it is a genuine ENVIRONMENT capability. It
    cannot hide the defect in CI: `test_ci_installs_the_yaml_parser_it_needs`
    below runs with no yaml at all and asserts every workflow step that invokes
    this module also installs pyyaml, so a CI run that would have skipped these
    assertions fails on that one instead.
    """
    return pytest.importorskip("yaml", reason="PyYAML absent - see pyyaml in CI installs")


def _workflow_files():
    return sorted(p for p in _WORKFLOW_DIR.glob("*.yml"))


def _load_workflows():
    yaml = _yaml()
    out = {}
    for p in _workflow_files():
        out[p.name] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return out


def _push_trigger(doc):
    """The `on: push:` mapping, tolerating YAML 1.1 turning `on` into True."""
    if not isinstance(doc, dict):
        return None
    on = doc.get("on", doc.get(True))
    if not isinstance(on, dict):
        return None
    push = on.get("push")
    return push if isinstance(push, dict) else None


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _run_steps(doc):
    """Every `run:` string in every job of a workflow document."""
    steps = []
    if not isinstance(doc, dict):
        return steps
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                steps.append(step["run"])
    return steps


def _git_tracked():
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(_REPO), capture_output=True, text=True, timeout=180, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def _selector_live_output():
    """Exactly what the workflow gets - the CLI, not the importable function."""
    proc = subprocess.run(
        [sys.executable, str(_SELECTOR)],
        cwd=str(_REPO), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, (
        f"{_SELECTOR_REL} exited {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _independently_derived_md_readers():
    """A DELIBERATELY different derivation from the selector's.

    The selector resolves every path-like `.md` literal against a
    segment-boundary suffix index of `git ls-files`. This one matches on
    BASENAME only. Same intent, different mechanics - so a bug in the
    selector's index construction shows up as a gap here rather than being
    reproduced identically on both sides.
    """
    tracked = _git_tracked()
    md_basenames = {p.rsplit("/", 1)[-1] for p in tracked if p.lower().endswith(".md")}
    modules = set()
    for rel in tracked:
        if not rel.endswith(".py"):
            continue
        if not (rel.startswith("tests/") or rel.startswith("agents/daemon_slayer/tests/")):
            continue
        try:
            tree = ast.parse((_REPO / rel).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            text = node.value
            if len(text.splitlines()) != 1 or " " in text or "\t" in text:
                continue
            if not text.lower().endswith(".md"):
                continue
            if text.replace("\\", "/").rsplit("/", 1)[-1] in md_basenames:
                modules.add(rel)
                break
    return modules


# --------------------------------------------------------------------------- #
# 1. some workflow fires on a .md push
# --------------------------------------------------------------------------- #
def test_some_workflow_fires_on_a_markdown_push():
    """The hole itself. Every workflow ignoring `**/*.md` needs a complement."""
    docs = _load_workflows()

    ignoring = []
    accepting = []
    for name, doc in docs.items():
        push = _push_trigger(doc)
        if push is None:
            continue
        ignored = _as_list(push.get("paths-ignore"))
        accepted = _as_list(push.get("paths"))
        if any(pat in _MD_GLOB_PATTERNS for pat in ignored):
            ignoring.append(name)
        if any(pat in _MD_GLOB_PATTERNS for pat in accepted):
            accepting.append(name)

    assert ignoring, (
        "no workflow declines '**/*.md' any more - if the MINUTE SAVER was "
        "deliberately removed, delete this assertion with a measurement; "
        f"scanned {sorted(docs)}"
    )
    assert accepting, (
        "these workflows skip a docs-only push: "
        f"{sorted(ignoring)} - and NOTHING fires on '**/*.md'. Test modules "
        "read tracked .md off disk and assert on their content, so a docs-only "
        "commit can turn a .py guard RED with no CI run at all (b412c2d8, "
        "ae829bb2). Add a workflow whose push trigger accepts '**/*.md'."
    )


# --------------------------------------------------------------------------- #
# 2. that workflow actually invokes the selector
# --------------------------------------------------------------------------- #
def test_markdown_workflow_invokes_the_selector():
    """Firing is not enough - it has to run the DERIVED module set."""
    docs = _load_workflows()

    firing = {
        name: doc for name, doc in docs.items()
        if any(pat in _MD_GLOB_PATTERNS
               for pat in _as_list((_push_trigger(doc) or {}).get("paths")))
    }
    assert firing, "no workflow accepts '**/*.md' on push - see the sibling test"

    invoking = [
        name for name, doc in firing.items()
        if any(_SELECTOR_REL in run for run in _run_steps(doc))
    ]
    assert invoking, (
        f"workflow(s) {sorted(firing)} fire on a .md push but no `run:` step "
        f"invokes {_SELECTOR_REL}. A hand-written module list in YAML is the "
        "SCHEDULED_SPAWNERS failure - it stays green over every module added "
        "after it was written. The set must be derived at CI time."
    )


def test_selector_exists_and_is_executable_as_a_cli():
    assert _SELECTOR.exists(), f"{_SELECTOR_REL} missing from the checkout"
    assert _SELECTOR_REL in set(_git_tracked()), (
        f"{_SELECTOR_REL} is untracked - CI checks out git, not this disk"
    )
    selected = _selector_live_output()
    assert selected, "the selector emitted nothing - CI would run zero guards"


# --------------------------------------------------------------------------- #
# 3. the selector's live output covers an independent re-derivation
# --------------------------------------------------------------------------- #
def test_selector_covers_every_module_that_names_a_tracked_md():
    selected = set(_selector_live_output())
    derived = _independently_derived_md_readers()
    missing = sorted(derived - selected)
    assert not missing, (
        f"{len(missing)} test module(s) reference a tracked .md but are NOT "
        f"selected, so a docs-only push would not run them: {missing}"
    )


def test_known_scar_module_is_selected():
    """`tests/test_loop_director_context_caps.py` is the module that actually
    broke under b412c2d8. Named explicitly so a future refactor of the
    selector cannot quietly drop the one case that proved the defect."""
    assert (_REPO / _SCAR_MODULE).exists(), f"{_SCAR_MODULE} vanished"
    selected = _selector_live_output()
    assert _SCAR_MODULE in selected, (
        f"{_SCAR_MODULE} reads docs/ORCHESTRATION_PLAN.md off disk and went "
        "RED under the docs-only push b412c2d8, but the selector does not "
        f"pick it. Selected {len(selected)} module(s)."
    )


# --------------------------------------------------------------------------- #
# 4. this module's own dependency cannot silently disarm it in CI
# --------------------------------------------------------------------------- #
def test_ci_installs_the_yaml_parser_it_needs():
    """Runs with no yaml at all - so it still fires when the yaml tests skip.

    Text-level on purpose: parsing the workflow to learn whether the workflow
    installs the parser is circular. Any workflow step that invokes THIS module
    must have a pyyaml install somewhere in its job.
    """
    me = _HERE.name
    offenders = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        if me not in text:
            continue
        if not re.search(r"(?im)^\s*pip install\b.*\bpyyaml\b", text):
            offenders.append(path.name)
    assert not offenders, (
        f"{offenders} run {me} but never `pip install pyyaml`. Without it the "
        "YAML assertions in this module degrade to skips, and a skipped test "
        "is a green tick."
    )


def test_minute_saver_is_still_in_place():
    """Guards the fix from over-correcting. Deleting ci.yml's paths-ignore
    would also close the hole - by making every prose edit pay for the full
    suite, which the 2026-06-30 measurement (55% docs-only) rejected."""
    text = (_WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")
    assert "paths-ignore" in text and "**/*.md" in text, (
        "ci.yml no longer skips docs-only pushes. If that was deliberate, it "
        "needs its own measurement - do not delete the minute saver to make "
        "the docs-guard workflow easier."
    )
