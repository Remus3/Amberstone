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
import shlex
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
# Since the 2026-10-05 supply-chain order, CI installs from HASH-PINNED files
# (`pip install --require-hashes -r .github/ci/requirements-*.txt`), so pyyaml
# no longer appears on the install line itself. "Installs pyyaml" therefore
# means: a `pip install` line (shell comment stripped - a comment that says
# pyyaml installs nothing) either names pyyaml as an argument, or names a
# `-r` file, resolved from the repo root like the runner's checkout, that pins
# `pyyaml==` (following nested `-r` lines relative to their own file, as pip
# does). The twin of this helper lives in
# tests/test_ci_job_timeout_headroom_rm156.py, deliberately not shared: each
# guard must stand on its own.
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
        # The shape CI uses now: hashed file that pins pyyaml.
        ("pip install --require-hashes -r ci/req.txt", "pyyaml==6.0.3 \\\n    --hash=sha256:00\n", True),
        # NEGATIVE CONTROL: a hashed file WITHOUT pyyaml installs no pyyaml.
        ("pip install --require-hashes -r ci/req.txt", "pytest==9.1.1 \\\n    --hash=sha256:00\n", False),
        # NEGATIVE CONTROL: a trailing comment naming pyyaml installs nothing.
        ("pip install --require-hashes -r ci/req.txt  # pyyaml", "pytest==9.1.1\n", False),
        # A commented-out pin in the file is not a pin.
        ("pip install -r ci/req.txt", "# pyyaml==6.0.3\npytest==9.1.1\n", False),
        # A -r file that does not exist installs nothing.
        ("pip install -r ci/missing.txt", "pyyaml==6.0.3\n", False),
        # Nested -r, resolved relative to the including file, as pip does.
        ("pip install -r ci/outer.txt", "pyyaml==6.0.3\n", True),
        # The pre-hash shape still counts: pyyaml named on the line itself.
        ("pip install pytest pytest-timeout pyyaml", "", True),
        ("python -m pip install --requirement=ci/req.txt", "PyYAML==6.0.3\n", True),
    ],
)
def test_pyyaml_install_probe_reads_the_requirements_file(tmp_path, install_line, req_body, expected):
    """Negative controls first: the probe must not be satisfied by a comment or
    by a hashed file that lacks pyyaml, or the guard below is decoration."""
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "req.txt").write_text(req_body, encoding="utf-8")
    (tmp_path / "ci" / "outer.txt").write_text("-r req.txt\n", encoding="utf-8")
    run = f"set -e\n{install_line}\npython -c \"import yaml\"\n"
    assert _run_text_installs_pyyaml(run, tmp_path) is expected


def test_ci_installs_the_yaml_parser_it_needs():
    """Runs with no yaml at all - so it still fires when the yaml tests skip.

    Text-level on purpose: parsing the workflow to learn whether the workflow
    installs the parser is circular. Any workflow step that invokes THIS module
    must have a pyyaml install somewhere in its job - on the install line, or
    pinned in the `-r` requirements file that line installs.
    """
    me = _HERE.name
    offenders = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        if me not in text:
            continue
        if not _run_text_installs_pyyaml(text, _REPO):
            offenders.append(path.name)
    assert not offenders, (
        f"{offenders} run {me} but install no pyyaml - neither on a "
        "`pip install` line nor pinned (`pyyaml==`) in the `-r` file it "
        "installs. Without it the YAML assertions in this module degrade to "
        "skips, and a skipped test is a green tick."
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


# --------------------------------------------------------------------------- #
# 5. the docs-guards install set is a DECISION about every runtime package
# --------------------------------------------------------------------------- #
# MEASURED 2026-10-31, docs-guards run 41216101159: 8 failed. The workflow's
# install set was sized on a 2026-07-27 premise - "not one of the 48 selected
# modules imports the runtime stack" - that nothing guarded. The s144 widening
# of the selector (RM-1107 / RM-1145..RM-1147, index-walk readers) took the
# selection to 184 modules, and four of them hold NON-md tests that execute
# runtime packages the job never installed: json5 (tools/daemon_slayer_extract.py,
# loaded by agents/daemon_slayer/tests/test_artifact_patch_marker_guard.py and
# tests/test_tracked_json_producers_emit_lf_bytes.py), anthropic
# (tft/tft_coach_engine.py, imported by tests/test_tft_meta_provenance_rm846.py)
# and portalocker (core/decision_detector.py, imported lazily by the dashboard's
# POST dispatch inside the in-process server that
# tests/test_dead_endpoint_cleanup_item186.py starts on 127.0.0.1 - the handler
# thread died on the import, so the CLIENT saw RemoteDisconnected; no network).
#
# Dropping those modules from the selection would trade a red job for a blind
# one: the same modules hold md-fragile tests (test_no_import_of_deleted_handler
# reads every tracked file, `.md` included). So the job installs what its
# selection executes, and every OTHER package pinned in requirements.in is
# declared NOT installed, with a reason, in requirements-docs-guards.in:
#
#     # docs-guards-not-installed: <name> - <reason>
#
# The universe is requirements.in (the producing side), not a list here, so a
# new runtime dependency fails this guard until someone classifies it. Static
# import tracing was measured and rejected as the mechanism: over the live
# selection it flagged 26 modules (try/except-guarded and never-called imports)
# and still missed the portalocker path, which only a POST reaches.
_CI_DIR = _REPO / ".github" / "ci"
_RUNTIME_IN = _REPO / "requirements.in"
_DOCS_GUARDS_IN = _CI_DIR / "requirements-docs-guards.in"
_DOCS_GUARDS_TXT = _CI_DIR / "requirements-docs-guards.txt"
# Same pin shape as ci.yml's "hashed CI install sets agree with requirements.in".
_PIN_LINE = re.compile(r"([A-Za-z0-9_.-]+)==([^\s;\\]+)")
_NOT_INSTALLED_LINE = re.compile(
    r"^#\s*docs-guards-not-installed:\s*(?P<name>[A-Za-z0-9_.-]+)\s+-\s+(?P<why>\S.*)$"
)
# The regression floor for 41216101159: what the selection was MEASURED to
# execute. A declaration cannot excuse these, because the job is red without them.
# Reverses if: no selected module reaches the named loader any more (re-measure
# with an import-blocked run of the selection, then drop the entry).
_MEASURED_SELECTION_NEEDS = {
    "json5": "tools/daemon_slayer_extract.py (2 selected modules load it)",
    "anthropic": "tft/tft_coach_engine.py (tests/test_tft_meta_provenance_rm846.py)",
    "portalocker": "core/decision_detector.py (the dashboard POST dispatch)",
}


def _norm_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pinned_dists(path: Path) -> set:
    """Distribution names pinned `name==ver` at line start; a comment pins nothing."""
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _PIN_LINE.match(line)
        if m:
            out.add(_norm_dist(m.group(1)))
    return out


def _declared_not_installed(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _NOT_INSTALLED_LINE.match(line.strip())
        if m:
            out[_norm_dist(m.group("name"))] = m.group("why").strip()
    return out


def _runtime_classification_gaps(runtime_in: Path, guards_in: Path, guards_txt: Path,
                                 floor=()) -> list:
    runtime = _pinned_dists(runtime_in)
    if not runtime:
        # The anchor: an empty universe would make every check below vacuous.
        return [f"{runtime_in.name} yielded no `name==ver` pins - the parser is wrong, not the file"]
    installed = _pinned_dists(guards_txt)
    declared = _declared_not_installed(guards_in)
    gaps = []
    for name in sorted(runtime):
        if name in installed and name in declared:
            gaps.append(f"{name}: installed by {guards_txt.name} AND declared not installed "
                        f"in {guards_in.name} - drop the stale declaration")
        elif name not in installed and name not in declared:
            gaps.append(f"{name}: pinned in {runtime_in.name} but neither installed by "
                        f"{guards_txt.name} nor declared `# docs-guards-not-installed: "
                        f"{name} - <reason>` in {guards_in.name}")
    for name in sorted(set(declared) - runtime):
        gaps.append(f"{name}: declared not installed in {guards_in.name} but "
                    f"{runtime_in.name} pins no such package - drop the dead declaration")
    for name in sorted(floor):
        if _norm_dist(name) not in installed:
            gaps.append(f"{name}: the selection executes it (docs-guards 41216101159) but "
                        f"{guards_txt.name} does not install it")
    return gaps


_HASHED = " \\\n    --hash=sha256:00\n"


@pytest.mark.parametrize(
    ("runtime", "guards_in", "guards_txt", "floor", "expected_names"),
    [
        # Every runtime package classified, one each way: clean.
        ("a==1\nb==2\n", "# docs-guards-not-installed: b - heavy\n", "a==1" + _HASHED, (), []),
        # NEGATIVE CONTROL: an unclassified runtime package is a gap.
        ("a==1\nb==2\n", "", "a==1" + _HASHED, (), ["b"]),
        # A commented-out pin installs nothing.
        ("a==1\n", "", "# a==1\n", (), ["a"]),
        # A declaration with no reason is not a declaration.
        ("a==1\n", "# docs-guards-not-installed: a\n", "", (), ["a"]),
        # Installed AND declared: the declaration is stale.
        ("a==1\n", "# docs-guards-not-installed: a - heavy\n", "a==1" + _HASHED, (), ["a"]),
        # Declared for a package requirements.in does not pin: dead.
        ("a==1\n", "# docs-guards-not-installed: zz - gone\n", "a==1" + _HASHED, (), ["zz"]),
        # Names compare as pip normalizes them.
        ("Pillow==1\nopencv_python==2\n",
         "# docs-guards-not-installed: pillow - x\n# docs-guards-not-installed: opencv-python - y\n",
         "", (), []),
        # The floor: a measured need cannot be declared away.
        ("a==1\n", "# docs-guards-not-installed: a - heavy\n", "", ("a",), ["a"]),
        # ANCHOR: an empty universe is a failure, never a vacuous pass.
        ("", "", "", (), ["requirements.in"]),
    ],
    ids=["clean", "unclassified", "commented-pin", "no-reason", "stale-declaration",
         "dead-declaration", "normalized-names", "floor-not-declarable", "empty-universe"],
)
def test_runtime_classification_probe_has_teeth(tmp_path, runtime, guards_in, guards_txt,
                                                floor, expected_names):
    r = tmp_path / "requirements.in"
    gi = tmp_path / "requirements-docs-guards.in"
    gt = tmp_path / "requirements-docs-guards.txt"
    r.write_text(runtime, encoding="utf-8")
    gi.write_text(guards_in, encoding="utf-8")
    gt.write_text(guards_txt, encoding="utf-8")
    gaps = _runtime_classification_gaps(r, gi, gt, floor)
    assert len(gaps) == len(expected_names), gaps
    for gap, name in zip(gaps, expected_names):
        assert gap.startswith(name), (gap, name)


def test_docs_guards_install_set_classifies_every_runtime_package():
    """Each package requirements.in pins is installed by the docs-guards job or
    declared not installed with a reason, and the measured needs of the
    selection are installed. Text-level, no yaml: it runs in both jobs."""
    for path in (_RUNTIME_IN, _DOCS_GUARDS_IN, _DOCS_GUARDS_TXT):
        assert path.is_file(), f"{path.relative_to(_REPO)} is missing"
    gaps = _runtime_classification_gaps(_RUNTIME_IN, _DOCS_GUARDS_IN, _DOCS_GUARDS_TXT,
                                        floor=tuple(_MEASURED_SELECTION_NEEDS))
    assert not gaps, (
        "docs-guards.yml installs .github/ci/requirements-docs-guards.txt and runs "
        "every module tools/md_guard_selector.py picks; a runtime package it "
        "neither installs nor deliberately declines is the 41216101159 failure "
        "waiting for its module. Classify it in the .in, then regenerate the "
        "hashed .txt with the command in its header:\n  " + "\n  ".join(gaps)
    )
