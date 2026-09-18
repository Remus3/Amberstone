"""Drift guard: oss/win32_atomic_io must not diverge from core/polled_json.py.

`oss/win32_atomic_io/` is an EXTRACTED, shareable copy of the atomic-write /
tolerant-read primitives that live in `core/polled_json.py`. RC has 20-plus
importers of the original, so the extraction deliberately did NOT replace it -
the package is a sibling copy. Two copies of the same logic are exactly the
shape that rots, so this guard pins them together.

It pins the EXECUTABLE LOGIC, not bytes. A byte pin would be wrong here on
purpose: the shipped docstrings and comments were deliberately rewritten to
drop RC-specific prose (file paths, task ids, memory keys) that means nothing
outside this repo. So both sides are parsed with `ast`, docstrings are
stripped, comments never reach the tree at all, and the normalized function
bodies are compared symbol by symbol.

ONE normalization is allowed, and it is declared rather than implied: the log
MESSAGE PREFIX differs ("polled_json" vs "win32_atomic_io"), because the
package must not advertise RC's module name. That substitution is canonicalized
on BOTH sides and the guard asserts it actually fired on both, so it cannot
quietly widen into a blanket allowance for changed string literals.

Anything else - a changed constant, a reordered statement, a different
exception clause, a dropped cleanup - fails, naming the symbol.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent
_RC_SOURCE = _REPO_ROOT / "core" / "polled_json.py"
_PKG_ROOT = _REPO_ROOT / "oss" / "win32_atomic_io"
_PKG_SOURCE = _PKG_ROOT / "src" / "win32_atomic_io" / "_atomic.py"

# Function symbols whose executable body must stay identical in both copies.
_PINNED_FUNCTIONS = (
    "_replace_with_retry",
    "_scratch_path",
    "_write_then_replace",
    "atomic_write_json",
    "atomic_write_bytes",
    "atomic_write_text",
    "read_json_dict",
)

# Module-level assignments whose value must stay identical in both copies.
_PINNED_ASSIGNMENTS = ("_REPLACE_RETRY_DELAYS_S",)

# The ONLY tolerated textual difference. Each side's log-message prefix is
# rewritten to a neutral token before comparison. Both aliases must be
# observed, and the counts must match, or the guard fails - see
# test_the_declared_log_prefix_allowance_is_exercised_on_both_sides.
_LOG_PREFIX_ALIASES = ("polled_json:", "win32_atomic_io:")
_LOG_PREFIX_CANON = "<logprefix>:"

# Prose that must never reach the shipped package: RC paths, task ids, memory
# keys, scheduled-task names, and RC runtime filenames.
_RC_PROSE_TOKENS = (
    "data/force_scan.json",
    "core/hotkeys.py",
    "dashboard/_writers.py",
    "coaches/arena_coach.py",
    "tools/lcu_agent.py",
    "app/__init__.py",
    "coach_integration/_coach.py",
    "coaches/sr_user_builds.py",
    "core/cost_tracker.py",
    "coaches/_base_coach.py",
    "RC-HotkeyListener",
    "RC-LCUAgent",
    "test_polled_json_lane8_cycle24",
    "LANE 8 CYCLE",
    "RM-261",
    "RM-264",
    "AUDIT 2026-04-28",
    "reference_os_replace_winerror5",
    "reference_windows_write_text_crlf_byte_count",
    "feedback_resolver_fix_is_not_a_consumer_fix",
    "restart_trigger.txt",
    "coaching_data.json",
    "ops/rc_supervisor",
    "rc.polled_json",
    "PolledJsonFile",
    "Riot Commander",
)

# Every RC package the extracted copy must not depend on.
_RC_IMPORT_ROOTS = (
    "core",
    "app",
    "ops",
    "coaches",
    "dashboard",
    "lcu",
    "tools",
    "agents",
    "modes",
    "modules",
    "tft",
    "ui",
    "coach_integration",
    "vision_server",
)


def _package_py_files() -> list[Path]:
    return [p for p in _package_all_files() if p.suffix == ".py"]


# Generated / gitignored artifacts that are not part of the shipped package.
# They are excluded by DIRECTORY NAME rather than by a gitignore consultation
# so the guard keeps working in a tree with no git available.
_GENERATED_DIRS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "build", "dist", ".eggs"})


def _is_generated(path: Path) -> bool:
    return any(part in _GENERATED_DIRS or part.endswith(".egg-info") for part in path.parts)


def _package_all_files() -> list[Path]:
    return sorted(p for p in _PKG_ROOT.rglob("*") if p.is_file() and not _is_generated(p.relative_to(_PKG_ROOT)))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_bytes().decode("utf-8"), filename=str(path))


def _strip_docstring(node: ast.AST) -> None:
    body = getattr(node, "body", None)
    if not body:
        return
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        del body[0]


class _Normalizer(ast.NodeTransformer):
    """Strip docstrings and canonicalize the one declared log-prefix alias."""

    def __init__(self) -> None:
        self.substitutions = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # noqa: N802
        self.generic_visit(node)
        _strip_docstring(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:  # noqa: N802
        self.generic_visit(node)
        _strip_docstring(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:  # noqa: N802
        self.generic_visit(node)
        _strip_docstring(node)
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # noqa: N802
        if isinstance(node.value, str):
            for alias in _LOG_PREFIX_ALIASES:
                if node.value.startswith(alias):
                    node.value = _LOG_PREFIX_CANON + node.value[len(alias):]
                    self.substitutions += 1
                    break
        return node


def _normalized(node: ast.AST) -> tuple:
    """Return (structural dump, count of declared log-prefix substitutions).

    The node is round-tripped through unparse/parse first so that source
    positions and formatting cannot leak into the comparison - only the tree
    shape survives.
    """
    norm = _Normalizer()
    canonical = norm.visit(ast.parse(ast.unparse(node)))
    return ast.dump(canonical, annotate_fields=True, include_attributes=False), norm.substitutions


def _functions(tree: ast.Module) -> dict:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _assignments(tree: ast.Module) -> dict:
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for tgt in n.targets:
                if isinstance(tgt, ast.Name):
                    out[tgt.id] = n
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out[n.target.id] = n
    return out


@pytest.fixture(scope="module")
def rc_tree() -> ast.Module:
    assert _RC_SOURCE.is_file(), f"missing RC source: {_RC_SOURCE}"
    return _parse(_RC_SOURCE)


@pytest.fixture(scope="module")
def pkg_tree() -> ast.Module:
    assert _PKG_SOURCE.is_file(), f"missing extracted copy: {_PKG_SOURCE}"
    return _parse(_PKG_SOURCE)


@pytest.mark.parametrize("symbol", _PINNED_FUNCTIONS)
def test_pinned_function_logic_is_identical_in_both_copies(symbol, rc_tree, pkg_tree):
    rc_funcs = _functions(rc_tree)
    pkg_funcs = _functions(pkg_tree)
    assert symbol in rc_funcs, f"{symbol} vanished from {_RC_SOURCE.name} - re-point or retire this guard"
    assert symbol in pkg_funcs, f"{symbol} is missing from the extracted copy {_PKG_SOURCE}"

    rc_dump, _ = _normalized(rc_funcs[symbol])
    pkg_dump, _ = _normalized(pkg_funcs[symbol])
    assert rc_dump == pkg_dump, (
        f"DRIFT in {symbol}: core/polled_json.py and oss/win32_atomic_io have diverged in "
        f"EXECUTABLE LOGIC (docstrings and comments are already ignored). Apply the change to "
        f"BOTH copies, or retire the extracted package."
    )


@pytest.mark.parametrize("symbol", _PINNED_FUNCTIONS)
def test_pinned_function_signature_is_identical_in_both_copies(symbol, rc_tree, pkg_tree):
    rc_sig = ast.dump(_functions(rc_tree)[symbol].args, include_attributes=False)
    pkg_sig = ast.dump(_functions(pkg_tree)[symbol].args, include_attributes=False)
    assert rc_sig == pkg_sig, f"DRIFT in {symbol}: the signatures differ between the two copies"


@pytest.mark.parametrize("symbol", _PINNED_ASSIGNMENTS)
def test_pinned_module_constant_is_identical_in_both_copies(symbol, rc_tree, pkg_tree):
    rc_assigns = _assignments(rc_tree)
    pkg_assigns = _assignments(pkg_tree)
    assert symbol in rc_assigns, f"{symbol} vanished from {_RC_SOURCE.name}"
    assert symbol in pkg_assigns, f"{symbol} is missing from the extracted copy"
    rc_dump, _ = _normalized(rc_assigns[symbol])
    pkg_dump, _ = _normalized(pkg_assigns[symbol])
    assert rc_dump == pkg_dump, f"DRIFT in {symbol}: the constant differs between the two copies"


def test_the_declared_log_prefix_allowance_is_exercised_on_both_sides(rc_tree, pkg_tree):
    """The one tolerated difference must actually be in use on both sides and
    in equal measure. If it ever reads zero the allowance has become dead
    permission that silently forgives some future literal change instead."""
    rc_funcs = _functions(rc_tree)
    pkg_funcs = _functions(pkg_tree)
    rc_hits = sum(_normalized(rc_funcs[s])[1] for s in _PINNED_FUNCTIONS)
    pkg_hits = sum(_normalized(pkg_funcs[s])[1] for s in _PINNED_FUNCTIONS)
    assert rc_hits > 0, "the log-prefix allowance no longer matches anything in core/polled_json.py"
    assert rc_hits == pkg_hits, (
        f"the log-prefix allowance fired {rc_hits} times in core/polled_json.py but {pkg_hits} "
        f"times in the extracted copy - one side gained or lost a log line"
    )


def test_the_unadopted_wrapper_class_is_not_shipped(pkg_tree):
    """PolledJsonFile is deliberately EXCLUDED from the extraction: it has zero
    production instantiations in RC and the adopt-or-remove decision is still
    open, so shipping it would publish an unadopted surface."""
    classes = [n.name for n in pkg_tree.body if isinstance(n, ast.ClassDef)]
    assert classes == [], f"the extracted package should ship no classes, found {classes}"


def test_the_extracted_package_imports_stdlib_only():
    offenders = []
    for py in _package_py_files():
        tree = _parse(py)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                roots = [(node.module or "").split(".")[0]]
            else:
                continue
            for root in roots:
                if root in _RC_IMPORT_ROOTS:
                    offenders.append(f"{py.relative_to(_REPO_ROOT)}: {root}")
    assert offenders == [], f"the extracted package must not import RC code: {offenders}"


def test_the_logger_name_is_not_rcs():
    src = _PKG_SOURCE.read_bytes().decode("utf-8")
    assert 'logging.getLogger("win32_atomic_io")' in src
    assert "rc.polled_json" not in src


@pytest.mark.parametrize("token", _RC_PROSE_TOKENS)
def test_rc_specific_prose_is_absent_from_every_shipped_file(token):
    offenders = []
    for path in _package_all_files():
        if token in path.read_bytes().decode("utf-8", errors="replace"):
            offenders.append(str(path.relative_to(_REPO_ROOT)))
    assert offenders == [], f"RC-specific token {token!r} leaked into the shipped package: {offenders}"


def test_every_shipped_file_is_ascii_with_lf_endings():
    # The breadth of this file set is LOAD-BEARING beyond hygiene: it is what
    # catches a CRLF-drifted shipped LICENSE, which the license compare below
    # deliberately cannot see. Narrowing it is guarded - see
    # test_the_ascii_lf_guard_still_enumerates_every_shipped_file.
    problems = []
    for path in _package_all_files():
        raw = path.read_bytes()
        cr_count = raw.count(b"\r")
        if cr_count:
            problems.append(f"{path.name}: {cr_count} CR bytes")
        non_ascii = sum(1 for b in raw if b > 127)
        if non_ascii:
            problems.append(f"{path.name}: {non_ascii} non-ASCII bytes")
    assert problems == [], f"ASCII / LF hygiene failed: {problems}"


def _called_names(func: ast.FunctionDef) -> set:
    """Every bare-name function called anywhere inside `func`."""
    return {
        n.func.id for n in ast.walk(func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def test_the_ascii_lf_guard_still_enumerates_every_shipped_file():
    """Make the LICENSE's dependence on the ASCII/LF guard EXPLICIT (RM-474).

    WHY this exists, measured 2026-09-18 by performing the edit rather than
    arguing about it: RM-471 replaced the LICENSE byte compare with a
    line-ending-NORMALIZED content compare, which is correct and is not in
    question - but it cost a CRLF-drifted SHIPPED LICENSE its second
    independent guard. Only `test_every_shipped_file_is_ascii_with_lf_endings`
    still catches that, and it did not know it was load-bearing.

    Observed at this HEAD: CRLF-drift the shipped LICENSE and that one test is
    the ONLY failure (51 passed, 1 failed). Then narrow its file set from
    `_package_all_files()` to `_package_py_files()` - a ONE-TOKEN edit, and
    `_package_py_files()` already sits in this module as a ready-made
    alternative - and the fully CRLF-drifted LICENSE goes green again (52
    passed, 0 failed). Nothing in the suite objected. This test is what
    objects.

    WHY this SHAPE rather than moving the CR check into the compare test: the
    row permitted either, but only this one fails on the NARROWING ITSELF,
    with no drift needed. Moving the check would merely make the narrowing
    harmless and silent, and a future reader would still have no way to learn
    that the breadth was ever deliberate. Both are wanted, so the independent
    CR pin is ALSO restored, next to the compare test that needs it.

    A rewrite of the guard that enumerates the shipped files some other legal
    way will trip this too. That is intended: it is a LOUD stop, not a silent
    downgrade, and the fix is to re-point this assertion on purpose.
    """
    survivor_name = "test_every_shipped_file_is_ascii_with_lf_endings"
    tree = ast.parse(_THIS_FILE.read_bytes().decode("utf-8"))
    survivor = _functions(tree).get(survivor_name)
    assert survivor is not None, (
        f"{survivor_name} was renamed or removed. It is the only test that catches a "
        f"CRLF-drifted shipped LICENSE; re-point this guard at its replacement."
    )

    called = _called_names(survivor)
    assert "_package_all_files" in called, (
        f"{survivor_name} no longer enumerates _package_all_files(), so it no longer "
        f"covers the shipped LICENSE - and the license compare normalizes line endings "
        f"away on purpose, so nothing else would catch a CRLF-drifted LICENSE. It calls "
        f"{sorted(called)} instead."
    )
    assert "_package_py_files" not in called, (
        f"{survivor_name} was narrowed to the .py files only. That is exactly the "
        f"one-token regression this guard exists to stop: it leaves a CRLF-drifted "
        f"shipped LICENSE fully green."
    )

    pkg_license = _PKG_ROOT / "LICENSE"
    assert pkg_license in _package_all_files(), (
        "the shipped LICENSE is not in _package_all_files(), so the ASCII/LF guard does "
        "not actually reach it however it is spelled"
    )


def _license_content(raw: bytes) -> bytes:
    """Return the LICENSE's CONTENT, with the line-ending REPRESENTATION removed.

    WHY the comparison is normalized rather than the attribute being fixed
    (RM-471, measured 2026-09-18):

    The two LICENSE paths are the SAME git blob - `git rev-parse HEAD:LICENSE`
    and `git rev-parse HEAD:oss/win32_atomic_io/LICENSE` both return
    ed51d99f7579c6d7f692320d6fd8412ef1f9a7b3 - yet a raw byte compare of the
    WORKING-TREE copies passed in the primary checkout and FAILED in a fresh
    worktree of the same commit. Nothing had drifted. The divergence was
    line-ending ATTRIBUTE RESOLUTION:

      - the root `.gitattributes` pins `eol=lf` BY EXTENSION, and `LICENSE` is
        EXTENSIONLESS, so the root copy resolves NO text and NO eol attribute
        (`git check-attr -a -- LICENSE` prints nothing) and falls through to
        `core.autocrlf`, measured `true` on this machine - it materializes CRLF;
      - the package copy is covered by `oss/win32_atomic_io/.gitattributes`
        catch-all `text=auto eol=lf`, so it ALWAYS materializes LF.

    So the raw compare's verdict depended on WHEN and WHERE the tree was
    checked out, which is exactly what a drift guard must not do.

    Fixing the ATTRIBUTE instead was considered and rejected: a
    `.gitattributes` change only takes effect on RE-CHECKOUT, so every tree
    already materialized - including the one running this test - would keep
    failing until someone re-checked the file out, and the guard's verdict
    would still be a function of checkout history. It would also leave the
    verdict dependent on the git attribute pipeline, which a plain `cp -r` or a
    zip export of the package does not honour at all.

    Normalizing here loses nothing the guard is FOR. Its subject is whether the
    shipped copy is a DIFFERENT OR NARROWER GRANT, and CRLF-vs-LF is never that.
    The shipped copy's own line endings are still pinned, separately and
    strictly, by `test_every_shipped_file_is_ascii_with_lf_endings`, which
    fails on a single CR byte anywhere in the package - so this normalization
    cannot hide a CRLF regression in the file that actually ships. Only the
    ROOT copy's representation is left unpinned, deliberately: it is a checkout
    artifact of the consuming machine, not repository content.

    The normalization is deliberately the narrowest one that does the job:
    CRLF and lone CR are mapped to LF, and NOTHING else is touched - no
    whitespace stripping, no case folding, no blank-line collapsing. Widening
    it would start hiding real differences. `test_license_content_normalizes_only_line_endings`
    is the positive control that pins it to exactly that.
    """
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def test_license_content_normalizes_only_line_endings():
    """Positive control for `_license_content`. A normalizer that quietly
    widened into stripping or folding would make the LICENSE compare above
    pass over real content drift, and nothing else would notice."""
    assert _license_content(b"a\r\nb\rc\n") == b"a\nb\nc\n"
    # Texts that differ in CONTENT must stay different after normalization.
    assert _license_content(b"Copyright (c) Moon\n") != _license_content(b"Copyright (c) Other\r\n")
    assert _license_content(b"Apache License\n") != _license_content(b"apache license\n")
    assert _license_content(b" leading\n") != _license_content(b"leading\n")
    assert _license_content(b"trailing \n") != _license_content(b"trailing\n")
    assert _license_content(b"a\n\nb\n") != _license_content(b"a\nb\n")


def test_the_package_ships_the_repository_license_byte_for_byte():
    """The package sits inside an Apache-2.0 repository, so it IS Apache-2.0.
    The copy exists so a `cp -r` of this directory alone carries its grant; a
    copy that has DRIFTED from the root is worse than no copy, because it reads
    as a separate and possibly narrower grant.

    The compare is over line-ending-normalized CONTENT, not raw bytes, so the
    verdict is the same in every checkout - see `_license_content` for the
    measurement and for why the attribute was not the thing fixed."""
    pkg_license = _PKG_ROOT / "LICENSE"
    assert pkg_license.is_file(), "the package must ship its own copy of the repository LICENSE"
    root_bytes = (_REPO_ROOT / "LICENSE").read_bytes()
    assert _license_content(pkg_license.read_bytes()) == _license_content(root_bytes), (
        "oss/win32_atomic_io/LICENSE has drifted from the root LICENSE in CONTENT "
        "(the compare already ignores line endings, so this is real drift); "
        "re-copy it at byte level (text-mode writes rewrite LF as CRLF on Windows)"
    )
    # The grant must name a grantor. An unrendered template is a grant with
    # nobody granting it, and it passes a naive SPDX grep.
    text = _license_content(root_bytes).decode("utf-8")
    assert "Apache License" in text and "Version 2.0" in text
    assert "{{" not in text and "[name of copyright owner]" not in text, (
        "the LICENSE carries an unfilled copyright placeholder - a grant with no grantor"
    )


def test_the_shipped_license_line_endings_are_pinned_independently():
    """The SECOND independent guard on the shipped LICENSE's representation,
    restored next to the compare that stopped providing it (RM-474).

    The compare above normalizes CRLF away deliberately, for the reasons
    recorded on `_license_content`, and that is not being re-litigated here -
    this is NOT a byte compare and re-introducing one would undo RM-471. It
    asserts one narrower thing the normalized compare cannot: that the copy
    which actually SHIPS is LF, read straight off disk with no file-set helper
    in the path. So this survives any rewrite or narrowing of
    `test_every_shipped_file_is_ascii_with_lf_endings`, while that test in turn
    catches the same drift in every OTHER shipped file. Two independent guards
    again, which is the state RM-471 cost and this restores.

    Scope is deliberately CR ONLY. Non-ASCII drift in this file is already
    caught by the CONTENT compare above (a changed byte is a changed byte once
    line endings are normalized); CR is the single thing that normalization is
    blind to by design.
    """
    raw = (_PKG_ROOT / "LICENSE").read_bytes()
    cr_count = raw.count(b"\r")
    assert cr_count == 0, (
        f"the shipped oss/win32_atomic_io/LICENSE carries {cr_count} CR bytes. The "
        f"package's own .gitattributes pins it to LF, so a CRLF copy means it was "
        f"re-copied with a text-mode write (write_text rewrites LF as CRLF on Windows) "
        f"or checked out around that pin. Re-copy it at BYTE level."
    )


def test_the_readme_makes_no_contradictory_license_claim():
    """A directory inside an Apache-2.0 repository that tells the reader it is
    all-rights-reserved is a self-contradiction that ships. Guard the wording
    in both directions: the truthful claim must be present, and each of the
    old false ones must be absent."""
    readme = (_PKG_ROOT / "README.md").read_bytes().decode("utf-8")
    assert "## License" in readme
    lowered = readme.lower()
    assert "apache" in lowered, "the README must state the license it is actually under"

    forbidden = (
        "not yet distributable",
        "no license has been granted",
        "all-rights-reserved",
        "all rights reserved",
        "no redistribution",
        "internal use only",
        "awaiting the license decision",
        "there is deliberately no `license` file",
    )
    offenders = [phrase for phrase in forbidden if phrase in lowered]
    assert offenders == [], (
        f"the README contradicts the Apache-2.0 grant it ships under: {offenders}"
    )


def test_the_pyproject_license_metadata_matches_the_shipped_license():
    """Two declarations that can disagree are two chances to be wrong. A tool
    reading only the classifier must reach the same answer as one reading only
    the `license` field."""
    pyproject = (_PKG_ROOT / "pyproject.toml").read_bytes().decode("utf-8")
    assert 'license = "Apache-2.0"' in pyproject, "the SPDX license declaration is missing"
    assert "License :: OSI Approved :: Apache Software License" in pyproject, (
        "the OSI license classifier is missing"
    )
    assert "not distributable yet" not in pyproject, (
        "pyproject still carries the superseded no-license note"
    )


def test_the_expected_package_layout_is_present():
    expected = [
        _PKG_ROOT / "README.md",
        _PKG_ROOT / "LICENSE",
        _PKG_ROOT / "pyproject.toml",
        _PKG_SOURCE,
        _PKG_ROOT / "src" / "win32_atomic_io" / "__init__.py",
        _PKG_ROOT / "tests" / "test_atomic_write.py",
        _PKG_ROOT / "tests" / "test_read_json_dict.py",
        _PKG_ROOT / "tests" / "test_scratch_and_retry.py",
    ]
    missing = [str(p.relative_to(_REPO_ROOT)) for p in expected if not p.is_file()]
    assert missing == [], f"missing from the extracted package: {missing}"


def test_core_polled_json_still_keeps_its_wrapper_class(rc_tree):
    """The extraction did NOT modify core/polled_json.py - RC has many
    importers and the blast radius of this slice is zero. If this ever fails,
    someone edited the original; re-read the exclusion rationale above."""
    classes = [n.name for n in rc_tree.body if isinstance(n, ast.ClassDef)]
    assert classes == ["PolledJsonFile"]
