"""RM-1246 - the loop's grounding-guard rationale cites by rule and symbol.

The executor's directive grounding guard (ops/loop/executor.py), the
directive-chain metadata comment in ops/loop/loop_controller.py and the tests
that pin both (tests/test_loop_executor.py, tests/test_loop_director_continuity.py)
cited ops/loop/director_prompt.md by line: `:14-18`, `:16-18` and `:18`. At the
2026-07-27 commits that wrote them (f63dcee0f, 050e6928d) lines 14-18 were the
GROUNDING PREFIX rule and line 18 its PREMISE-CHECK field line. At HEAD
(lane/repo, 2026-10-31) lines 14-18 are the CONTEXT DISCIPLINE rule: the cites
send a reader to the wrong rule.

The same rationale cited the executor by line. The self-cites `(:188, :213,
:478, :558)` in executor.py, repeated as `executor.py:188, ...` in the test,
meant ParallelPlan's docstring, parallel_plan's docstring, the unreadable-HEAD
branch of grounding_findings and _git_out's docstring; at HEAD those lines are
other code. `executor.py:528` (the exact kind buckets) meant
reground_directive, and `loop_controller.py:577` (the `=== LAST claude.done
===` section) meant build_director_context.

Each cite now names its rule or symbol. This guard pins three things:

(a) no tracked .py under ops/ or tests/ cites director_prompt.md by line;
(b) executor.py and tests/test_loop_executor.py carry no executor /
    loop_controller line cite and no bare `:<line>` continuation cite;
(c) every rule and symbol the rationale now names still exists and still says
    what the rationale quotes it as saying. A rename or a reword names the
    stale sentence.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests._repo_walk import repo_files

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

PROMPT = "ops/loop/director_prompt.md"
EXECUTOR = "ops/loop/executor.py"
CONTROLLER = "ops/loop/loop_controller.py"
EXEC_TEST = "tests/test_loop_executor.py"
CONT_TEST = "tests/test_loop_director_continuity.py"

CITERS = (EXECUTOR, CONTROLLER, EXEC_TEST, CONT_TEST)

_PROMPT_LINE_CITE = re.compile(r"director_prompt\.md:\d+")
_LOOP_PY_LINE_CITE = re.compile(r"(?:executor|loop_controller)\.py:\d+")
# A bare `:NNN` or `:NNN-MMM` continuation cite (the RM-1196 pattern).
_BARE_LINE_CITE = re.compile(r"(?<![\w.:/\[])`?:\d{2,4}(?:-\d+)?\b(?![/\d])")

# The prompt's own PREMISE-CHECK placeholder line, which the executor rejects
# as template text and which tests/test_loop_executor.py quotes as a fixture.
PLACEHOLDER = ("PREMISE-CHECK: <each factual claim you rely on, tagged "
               "[from-digest] or [UNVERIFIED]>")

# (citer, module, qualified symbol, regex that must match the symbol's source)
CLAIMS = (
    (EXECUTOR, EXECUTOR, "ParallelPlan",
     r"deliberately four-valued, not a bool\. \"unverified\""),
    (EXECUTOR, EXECUTOR, "parallel_plan",
     r"Any doubt at any step lands in \"unverified\""),
    (EXECUTOR, EXECUTOR, "grounding_findings",
     r"an unreadable HEAD is an unknown, never a pass"),
    (EXECUTOR, EXECUTOR, "_git_out",
     r"empty answer lands in the unverified branch"),
    (EXECUTOR, CONTROLLER, "build_director_context",
     r"=== LAST claude\.done ===\\n\{json\.dumps\(last_done\)\}"),
    (EXEC_TEST, EXECUTOR, "ParallelPlan",
     r"deliberately four-valued, not a bool\. \"unverified\""),
    (EXEC_TEST, EXECUTOR, "parallel_plan",
     r"Any doubt at any step lands in \"unverified\""),
    (EXEC_TEST, EXECUTOR, "grounding_findings",
     r"an unreadable HEAD is an unknown, never a pass"),
    (EXEC_TEST, EXECUTOR, "_git_out",
     r"empty answer lands in the unverified branch"),
    (EXEC_TEST, EXECUTOR, "reground_directive",
     r"f\.kind in \(\"stale-head\", \"unverified\"\)"),
    (EXEC_TEST, EXECUTOR, "reground_directive",
     r"f\.kind == \"unverified-premise\""),
    (EXEC_TEST, CONTROLLER, "build_director_context",
     r"=== LAST claude\.done ===\\n\{json\.dumps\(last_done\)\}"),
)

# Every citer names the director_prompt rule it means by its heading.
RULE_NAME = "GROUNDING PREFIX"
RULE_CITERS = (EXECUTOR, CONTROLLER, EXEC_TEST, CONT_TEST)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _symbol_source(module: str, qualname: str) -> str | None:
    """Source of `qualname` in `module`: a def / class, or an assignment
    target in a module or class body. None when the symbol is gone."""
    text = _read(module)
    body = ast.parse(text).body
    parts = qualname.split(".")
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        found = None
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and node.name == part:
                found = node
                break
            if last and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                if any(isinstance(t, ast.Name) and t.id == part
                       for t in targets):
                    found = node
                    break
        if found is None:
            return None
        if last:
            return ast.get_source_segment(text, found)
        body = getattr(found, "body", [])
    return None


def _scanned_py() -> list[Path]:
    # TRACKED .py under ops/ and tests/ only (ADR-015, tests/_repo_walk). A raw
    # rglob also walked the gitignored ops/runtime/responder_export/<sha>/ repo
    # copies in a main checkout, whose stale executor.py still carries the old
    # cites, so the guard went red there and green in every worktree and on CI.
    files = [p for p in repo_files(ROOT, ("*.py",))
             if p.relative_to(ROOT).parts[0] in ("ops", "tests")]
    return [p for p in files if p.resolve() != SELF]


def test_citers_present():
    for rel in CITERS + (PROMPT,):
        assert (ROOT / rel).is_file(), f"{rel} missing"
    assert {c[0] for c in CLAIMS} == {EXECUTOR, EXEC_TEST}
    scanned = _scanned_py()
    assert len(scanned) > 100, "the ops/ + tests/ walk found too few files"
    assert ROOT / EXECUTOR in scanned and ROOT / EXEC_TEST in scanned


def test_no_director_prompt_line_cite_under_ops_or_tests():
    hits = []
    scanned = _scanned_py()
    assert len(scanned) > 100, "the ops/ + tests/ walk found too few files"
    for path in scanned:
        for n, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace")
                .splitlines(), 1):
            for m in _PROMPT_LINE_CITE.finditer(line):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{n}: "
                            f"{m.group(0)}")
    assert not hits, (
        "director_prompt.md is cited by line again; name the rule (for "
        f"example its GROUNDING PREFIX rule) instead (RM-1246): {hits}"
    )


@pytest.mark.parametrize("rel", (EXECUTOR, EXEC_TEST))
def test_no_executor_line_cite(rel):
    text = _read(rel)
    hits = _LOOP_PY_LINE_CITE.findall(text)
    hits += [m.group(0) for m in _BARE_LINE_CITE.finditer(text)]
    assert not hits, (
        f"{rel} cites loop code by line again: {hits}. Name the symbol "
        "instead (RM-1246)."
    )


def _prompt_fields() -> list[str]:
    text = _read(PROMPT)
    rule = text.index(f"- {RULE_NAME} (the directive's FIRST 3 lines")
    section = text[rule:text.index("\n- ", rule + 1)]
    # The field lines are the 4-space-indented emit block; the rule's own
    # 2-space prose (NEWEST-WINS) is not a field.
    return re.findall(r"^ {4}([A-Z-]+):", section, re.MULTILINE)


def test_director_prompt_grounding_prefix_rule_holds_its_three_fields():
    fields = _prompt_fields()
    assert fields == ["GROUNDED-AGAINST", "NOT-A-DUPLICATE-OF",
                      "PREMISE-CHECK"], fields
    assert "    " + PLACEHOLDER + "\n" in _read(PROMPT)


def test_controller_metadata_prefixes_open_with_the_rule_fields():
    """loop_controller's comment says the GROUNDING PREFIX rule mandates the
    first three DIRECTIVE_METADATA_PREFIXES entries and the ENGINE-IMPACT rule
    the fourth."""
    src = _symbol_source(CONTROLLER, "DIRECTIVE_METADATA_PREFIXES")
    assert src is not None, "loop_controller lost DIRECTIVE_METADATA_PREFIXES"
    prefixes = re.findall(r'"([A-Z-]+):"', src)
    assert prefixes[:3] == _prompt_fields(), prefixes
    assert "ENGINE-IMPACT" in prefixes
    assert "- ENGINE-IMPACT (a mandatory line in the directive body)" in _read(
        PROMPT)


@pytest.mark.parametrize("rel", RULE_CITERS)
def test_citer_names_the_grounding_prefix_rule(rel):
    assert f"director_prompt.md's {RULE_NAME} rule" in _read(rel).replace(
        "\n# ", " ").replace("\n", " "), (
        f"{rel} no longer names director_prompt.md's {RULE_NAME} rule"
    )


def test_placeholder_fixture_quotes_the_prompt_verbatim():
    assert PLACEHOLDER in _read(PROMPT)
    flat = re.sub(r'"\s*\n\s*"', "", _read(EXEC_TEST))
    assert "    " + PLACEHOLDER + "\\n" in flat, (
        "the placeholder fixture no longer quotes director_prompt.md verbatim"
    )


@pytest.mark.parametrize(
    "citer,module,qualname,pattern", CLAIMS,
    ids=[f"{c[0].rsplit('/', 1)[-1]}->{c[1].rsplit('/', 1)[-1]}:{c[2]}:{i}"
         for i, c in enumerate(CLAIMS)],
)
def test_named_symbol_holds_the_quoted_text(citer, module, qualname, pattern):
    text = _read(citer)
    if citer == module:
        # The definition itself would satisfy a whole-file search, so a
        # self-citer must name the symbol in a comment.
        text = "\n".join(line for line in text.splitlines()
                         if line.lstrip().startswith("#"))
    assert qualname in text, (
        f"{citer} no longer names {qualname} (RM-1246)"
    )
    src = _symbol_source(module, qualname)
    assert src is not None, (
        f"{module} has no {qualname}; {citer} names it (RM-1246)"
    )
    assert re.search(pattern, src), (
        f"{module} {qualname} no longer matches {pattern!r}; the sentence "
        f"in {citer} that names it is stale (RM-1246)"
    )


def test_pattern_catches_the_old_forms():
    for old in ("director_prompt.md:14-18", "ops/loop/director_prompt.md:18"):
        assert _PROMPT_LINE_CITE.search(old), old
    for old in ("executor.py:528", "loop_controller.py:577"):
        assert _LOOP_PY_LINE_CITE.search(old), old
    for old in ("(:188, :213, :478, :558)", "(:478, an unknown"):
        assert _BARE_LINE_CITE.search(old), old
    for fine in ("director_prompt.md GROUNDING PREFIX", "127.0.0.1:8888",
                 "raw[:200]", "HEAD=9d836162"):
        assert not _PROMPT_LINE_CITE.search(fine), fine
        assert not _BARE_LINE_CITE.search(fine), fine
