"""s172 - no test hands page.wait_for_function an ASYNC predicate.

Playwright's wait_for_function does not await a Promise the predicate returns,
and a Promise is truthy, so an ``async () => ...`` predicate ends the wait at
once (measured 2026-11-26 on Playwright 1.59 and 1.65: ``async () => false``
returned in 0.01 s). Five DS panel tests waited for the champion index that
way and raced its load; test_ds_statcheck_champ_rebind_rm196 lost the race on
the CI runner (ci 45903006209). They now go through
tests/snapshot_panels/_champ_names.py, which imports once and polls a sync
predicate. This AST guard stops the pattern coming back.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check


def _predicate(call: ast.Call) -> ast.expr | None:
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "expression":
            return kw.value
    return None


def _async_text(node: ast.expr | None) -> bool:
    """True for a string literal (or a + concatenation of them) that opens
    with an async function."""
    parts: list[str] = []

    def walk(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            parts.append(n.value)
        elif isinstance(n, ast.JoinedStr):
            for v in n.values:
                walk(v)
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            walk(n.left)
            walk(n.right)

    if node is None:
        return False
    walk(node)
    text = "".join(parts).lstrip().lstrip("(").lstrip()
    return text.startswith("async")


def _offenders(source: str) -> tuple[int, list[int]]:
    calls, bad = 0, []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "wait_for_function"):
            calls += 1
            if _async_text(_predicate(node)):
                bad.append(node.lineno)
    return calls, bad


def test_the_detector_flags_an_async_predicate_and_passes_a_sync_one():
    src = (
        "page.wait_for_function('''async () => { return false; }''')\n"
        "page.wait_for_function(expression='(async () => 1)')\n"
        "page.wait_for_function('() => !!window.x', timeout=5)\n"
        "page.wait_for_function('(ids) => ids.length', arg=[1])\n"
    )
    assert _offenders(src) == (4, [1, 2])


def test_no_test_waits_on_an_async_predicate():
    self_check()
    calls, bad = 0, []
    for path in iter_repo_files(REPO_ROOT / "tests", ("*.py",)):
        n, lines = _offenders(path.read_text(encoding="utf-8"))
        calls += n
        bad += [f"{relative_posix(path)}:{ln}" for ln in lines]
    # The snapshot suite waits on page state in many places; a walk that saw
    # only a handful of calls is not a real scan.
    assert calls >= 50, f"only {calls} wait_for_function calls seen"
    assert not bad, f"async wait_for_function predicates: {bad}"
