"""MAIN ORDER 2026-10-26 0300 (U5) item 1: every wall-clock UPPER bound in an
assertion under tests/ goes through the kit's ``fleet_test_guard.budget()``.

Why: a raw ``assert elapsed < 2.0`` is written for an idle box. While other
trees' suites hold suite-gate slots the same code runs slower and the bound
reds with no defect (kit v16 KIT-16). ``budget(seconds)`` multiplies the
idle-box seconds by the live slot-holder count, so the bound widens only
while the box is shared. Lower bounds stay raw: a slow box never makes a
real lower bound fail.

What the scan flags (AST, every ``*.py`` under tests/): inside an ``assert``
statement or a ``self.assertLess`` / ``assertLessEqual`` /
``assertGreater`` / ``assertGreaterEqual`` / ``assertTrue`` call, a
comparison whose SMALLER side is a timing value and whose LARGER side
holds no ``budget(...)`` call (directly, or through a name assigned from
one in the same file). A timing value is a clock difference
(``time.monotonic() / perf_counter() / time.time() - x``), a name or key
spelled with ``elapsed`` or ``waited``, or a name assigned from a clock difference in the
same function. A bare clock read compared with a deadline counts when the
deadline name was assigned from a clock read plus seconds with no budget().

Not flagged on purpose: ``while`` / ``if`` waits (they are polls, not
assertions), timestamps compared with timestamps (``t0 <= ts <= t1``),
``abs(x - y) < eps`` value checks, and an assertion on a VIRTUAL clock that
carries ``# timing-budget: exempt (<reason>)`` on one of its lines.

Where the unfixed code takes a finite time a widened bound would admit, the
bound is capped below it, ``min(fleet_test_guard.budget(x), cap)``, so the
test keeps telling fixed from broken on a loaded box.

Read-back for MAIN: this test green = no raw elapsed / perf_counter /
monotonic upper bound left in tests/ outside budget(). The non-vacuity tests
below prove the detector still fires on each shape it claims.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

_CLOCK_ATTRS = {"monotonic", "perf_counter", "monotonic_ns", "perf_counter_ns"}
_TIME_ATTRS = {"time", "time_ns"}
_ASSERT_CALLS = {"assertLess", "assertLessEqual", "assertGreater",
                 "assertGreaterEqual", "assertTrue"}


def _is_clock_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or node.args or node.keywords:
        return False
    f = node.func
    if isinstance(f, ast.Attribute):
        if f.attr in _CLOCK_ATTRS:
            return True
        return (f.attr in _TIME_ATTRS and isinstance(f.value, ast.Name)
                and f.value.id in {"time", "_time"})
    return isinstance(f, ast.Name) and f.id in _CLOCK_ATTRS


def _is_constant_expr(node: ast.AST) -> bool:
    return all(isinstance(n, (ast.Constant, ast.BinOp, ast.UnaryOp, ast.operator,
                              ast.unaryop)) for n in ast.walk(node))


def _is_clock_diff(node: ast.AST) -> bool:
    """`clock() - start`; `time.time() - 3600` is a past TIMESTAMP, not a span."""
    return (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)
            and _is_clock_call(node.left) and not _is_constant_expr(node.right))


def _has_budget(node: ast.AST, budget_names: set) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "budget":
                return True
        if isinstance(sub, ast.Name) and sub.id in budget_names:
            return True
    return False


# Spellings of a measured span: `elapsed`, `fast_elapsed`, `result["elapsed_s"]`,
# `h.waited_s` (core.port_handoff's wait record).
_SPAN_WORDS = ("elapsed", "waited")


def _spells_span(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in _SPAN_WORDS)


def _mentions_elapsed(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return _spells_span(node.id)
    if isinstance(node, ast.Attribute):
        return _spells_span(node.attr) or _mentions_elapsed(node.value)
    if isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            if _spells_span(key.value):
                return True
        return _mentions_elapsed(node.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args:
        key = node.args[0]
        if isinstance(key, ast.Constant) and isinstance(key.value, str) \
                and _spells_span(key.value):
            return True
        # `elapsed.get("a", 99.0)`: the span word is on the mapping, not the key.
        return _mentions_elapsed(node.func.value)
    return False


def _assigned_names(scope: ast.AST, pred, top_only: bool = False) -> set:
    out = set()
    nodes = getattr(scope, "body", []) if top_only else ast.walk(scope)
    for sub in nodes:
        if isinstance(sub, (ast.Assign, ast.AnnAssign)) and sub.value is not None:
            targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
            if pred(sub.value):
                out.update(t.id for t in targets if isinstance(t, ast.Name))
    return out


def _is_raw_deadline(value: ast.AST) -> bool:
    """`deadline = time.monotonic() + 5.0` (a clock read plus seconds)."""
    return (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add)
            and (_is_clock_call(value.left) or _is_clock_call(value.right)))


class _Scanner(ast.NodeVisitor):
    def __init__(self, tree: ast.AST):
        self.hits: list[int] = []
        self.budget_names = _assigned_names(tree, lambda v: _has_budget(v, set()))
        self.deadlines = _assigned_names(
            tree, lambda v: _is_raw_deadline(v) and not _has_budget(v, set()))
        self.scope_timing: list[set] = [_assigned_names(tree, _is_clock_diff, top_only=True)]

    def visit_FunctionDef(self, node):
        self.scope_timing.append(_assigned_names(node, _is_clock_diff))
        self.generic_visit(node)
        self.scope_timing.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _timing(self, node: ast.AST) -> bool:
        if _is_clock_diff(node) or _mentions_elapsed(node):
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            return self._timing(node.left) or self._timing(node.right)
        return isinstance(node, ast.Name) and node.id in self.scope_timing[-1]

    def _upper(self, small: ast.AST, big: ast.AST) -> bool:
        if _has_budget(big, self.budget_names):
            return False
        if self._timing(small):
            return True
        return (_is_clock_call(small) and isinstance(big, ast.Name)
                and big.id in self.deadlines)

    def _hit(self, stmt: ast.AST) -> None:
        self.hits.append((stmt.lineno, getattr(stmt, "end_lineno", None) or stmt.lineno))

    def _compare(self, node: ast.AST, stmt: ast.AST) -> None:
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Compare):
                continue
            items = [sub.left, *sub.comparators]
            for (a, b), op in zip(zip(items, items[1:]), sub.ops):
                if isinstance(op, (ast.Lt, ast.LtE)) and self._upper(a, b):
                    self._hit(stmt)
                elif isinstance(op, (ast.Gt, ast.GtE)) and self._upper(b, a):
                    self._hit(stmt)

    def visit_Assert(self, node):
        self._compare(node.test, node)
        self.generic_visit(node)

    def visit_Call(self, node):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else ""
        if name in {"assertLess", "assertLessEqual"} and len(node.args) >= 2:
            if self._upper(node.args[0], node.args[1]):
                self._hit(node)
        elif name in {"assertGreater", "assertGreaterEqual"} and len(node.args) >= 2:
            if self._upper(node.args[1], node.args[0]):
                self._hit(node)
        elif name == "assertTrue" and node.args:
            self._compare(node.args[0], node)
        self.generic_visit(node)


# A bound on a VIRTUAL clock (a fake the test advances itself) is exact, and
# scaling it by box load would only weaken it. Such an assertion carries this
# pragma, with the reason in parentheses, on one of its own lines.
EXEMPT_PRAGMA = "# timing-budget: exempt ("


def raw_upper_bounds(source: str) -> list[int]:
    """Line numbers of raw wall-clock upper bounds in one module's source."""
    tree = ast.parse(source)
    scanner = _Scanner(tree)
    scanner.visit(tree)
    lines = source.splitlines()
    out = set()
    for start, end in scanner.hits:
        span = lines[start - 1:end]
        if not any(EXEMPT_PRAGMA in ln and not ln.rstrip().endswith("(") for ln in span):
            out.add(start)
    return sorted(out)


def _test_files() -> list[Path]:
    return sorted(p for p in TESTS_DIR.rglob("*.py") if "__pycache__" not in p.parts)


# Every shape the scan flags needs one of these spellings in the file, so a
# file without any is skipped unparsed (the AST pass is the cost of this test).
_TRIGGER = re.compile(r"elapsed|waited|monotonic|perf_counter|time\(", re.IGNORECASE)


def test_no_raw_wall_clock_upper_bound_left_in_tests():
    files = _test_files()
    assert len(files) > 500, f"scan reached only {len(files)} files under tests/"
    offenders = []
    parsed = 0
    for path in files:
        src = path.read_text(encoding="utf-8")
        if not _TRIGGER.search(src):
            continue
        parsed += 1
        for line in raw_upper_bounds(src):
            offenders.append(f"{path.relative_to(TESTS_DIR).as_posix()}:{line}")
    assert parsed > 50, f"only {parsed} files carried a timing spelling - trigger broken?"
    assert not offenders, (
        "raw wall-clock upper bound(s) - wrap the idle-box seconds as "
        "`elapsed < fleet_test_guard.budget(<seconds>)` (tests/_timing_budget.py): "
        + ", ".join(offenders))


# ---------------------------------------------------------------- non-vacuity

_FLAGGED = {
    "elapsed_name": "def t():\n    assert elapsed < 2.0\n",
    "clock_diff_inline": "import time\ndef t():\n    assert time.monotonic() - t0 < 1.0\n",
    "perf_counter": "import time\ndef t():\n    assert time.perf_counter() - t0 < 1.0\n",
    "wall_time": "import time\ndef t():\n    assert time.time() - t0 < 45\n",
    "chained_lower_kept_upper_flagged": "def t():\n    assert 0.5 <= elapsed < 3.5\n",
    "assert_less": "def t(self):\n    self.assertLess(elapsed, 3.0)\n",
    "assert_less_get": "def t(self):\n    self.assertLess(r.get('elapsed_s', 1e9), 3.0)\n",
    "get_on_elapsed_mapping": "def t(self):\n    self.assertLess(elapsed.get('a', 99.0), 1.0)\n",
    "subscript_key": "def t():\n    assert result['elapsed'] < 1.0\n",
    "assigned_diff": "import time\ndef t():\n    dt = time.monotonic() - t0\n    assert dt < 1.0\n",
    "reversed_gt": "def t():\n    assert 2.0 > elapsed\n",
    "assert_greater": "def t(self):\n    self.assertGreater(2.0, elapsed)\n",
    "assert_true": "def t(self):\n    self.assertTrue(elapsed < 2.0)\n",
    "raw_deadline": ("import time\ndef t():\n    deadline = time.monotonic() + 5.0\n"
                     "    assert time.monotonic() < deadline\n"),
    "constant_bound": "def t():\n    assert elapsed < _HOOK_BUDGET_S\n",
    "ms_scaled": "import time\ndef t():\n    assert (time.perf_counter() - t0) * 1000 < 50\n",
    "pragma_without_reason": "def t():\n    assert elapsed < 2.0  # timing-budget: exempt (\n",
    "plain_variable_named_budget": "def t():\n    budget = 2.0\n    assert elapsed < budget\n",
    "waited_attribute": "def t():\n    assert 0.3 <= h.waited_s < 5.0\n",
}

_CLEAN = {
    "budget_inline": "def t():\n    assert elapsed < fleet_test_guard.budget(2.0)\n",
    "budget_bare": "def t():\n    assert elapsed < budget(2.0)\n",
    "budget_chained": "def t():\n    assert 0.5 <= elapsed < fleet_test_guard.budget(3.5)\n",
    "budget_name": ("def t():\n    limit = fleet_test_guard.budget(2.0)\n"
                    "    assert elapsed < limit\n"),
    "budget_deadline": ("import time\ndef t():\n"
                        "    deadline = time.monotonic() + fleet_test_guard.budget(5.0)\n"
                        "    assert time.monotonic() < deadline\n"),
    "lower_bound_only": "def t():\n    assert elapsed >= 0.5\n",
    "poll_loop": ("import time\ndef t():\n    while time.monotonic() - t0 < 5.0:\n"
                  "        pass\n"),
    "if_branch": "def t():\n    if elapsed < 2.0:\n        pass\n",
    "timestamp_window": "def t():\n    assert t0 <= got['ingested_at'] <= t1\n",
    "abs_value_check": "def t():\n    assert abs(inf['elapsed_s'] - 120.0) < 0.01\n",
    "past_timestamp": "import time\ndef t():\n    assert started < time.time() + 1.0\n",
    "assert_less_budget": "def t(self):\n    self.assertLess(elapsed, budget(3.0))\n",
    "past_timestamp_name": ("import time\ndef t():\n    old = time.time() - 3600\n"
                            "    assert old < newest\n"),
    "capped_budget": ("def t():\n    assert elapsed < min(fleet_test_guard.budget(0.9), 0.95)\n"),
    "virtual_clock_pragma": ("def t(self):\n    self.assertLess(\n"
                             "        elapsed, LIMIT)  # timing-budget: exempt (virtual clock)\n"),
}


def test_detector_fires_on_every_claimed_shape():
    missed = [name for name, src in _FLAGGED.items() if not raw_upper_bounds(src)]
    assert not missed, f"detector blind to: {missed}"
    untriggered = [name for name, src in _FLAGGED.items() if not _TRIGGER.search(src)]
    assert not untriggered, f"the file pre-filter would skip: {untriggered}"


def test_detector_passes_budget_forms_and_non_bounds():
    wrong = {name: raw_upper_bounds(src) for name, src in _CLEAN.items()
             if raw_upper_bounds(src)}
    assert not wrong, f"false positives: {wrong}"


def test_timing_budget_helper_is_the_kit_budget():
    from tests import _timing_budget

    assert _timing_budget.fleet_test_guard.budget.__module__ == "fleet_test_guard"
    assert _timing_budget.fleet_test_guard.budget(2.0) >= 2.0
