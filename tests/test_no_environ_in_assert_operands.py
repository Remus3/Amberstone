"""Guard: no assertion may render the whole process environment on failure.

Why
---
A failing ``assert FLAG not in os.environ`` (pytest assertion rewriting) or
``self.assertNotIn(FLAG, os.environ)`` (unittest) renders the operand in the
failure message. For ``os.environ`` that is every key AND every value of the
process environment - API keys and tokens included - written into the terminal,
the pytest result file and the CI log.

MEASURED 2026-09-21 (pytest 9.0.3, Python 3.14), and it is wider than the
obvious case: pytest's rewriter explains the ATTRIBUTE a called method hangs
off, so a failing ``assert os.environ.get(FLAG) is None`` prints

    where 'value' = get('FLAG')
      where get = environ({... the whole environment ...}).get

``assert os.getenv(FLAG) is None`` does not (``os.getenv`` renders as a
function), a subscript ``os.environ[FLAG]`` renders only its value, and a
comprehension renders as an opaque ``<generator object ...>``.

Safe forms
----------
* plain assert: read the one value to a local first -
  ``v = os.environ.get(FLAG)`` then ``assert v is None`` - or use
  ``os.getenv(FLAG)`` / ``os.environ[FLAG]``.
* unittest: ``self.assertIsNone(os.environ.get(FLAG))`` or
  ``self.assertFalse(FLAG in os.environ, msg="FLAG set")`` - unittest only ever
  sees the argument VALUE, so a ``.get()`` result or a bool is safe there.

What is flagged (AST, not grep)
-------------------------------
1. A plain ``assert`` whose test expression, walked the way pytest's rewriter
   explains it, reaches an environ expression anywhere (as a comparison operand,
   or as the object a method is called on). Comprehension and lambda bodies and
   subscript bases are not walked - pytest renders those opaquely.
2. A plain ``assert`` message, or any argument of an ``assert*`` call
   (``self.assertIn``, ``assertDictEqual``, ``mock.assert_called_with`` ...),
   whose VALUE is an environ expression or is a string built from one.

An "environ expression" is ``os.environ`` / ``os.environb`` (or any
``<x>.environ``), a name imported via ``from os import environ``, a
``dict()`` / ``set()`` / ``list()`` / ``sorted()`` / ``frozenset()`` /
``tuple()`` of one, a ``.copy()`` / ``.keys()`` / ``.items()`` / ``.values()``
of one, a comprehension iterating one, or a name assigned from any of those
anywhere in the same file (so ``env = os.environ`` is caught).

There is NO exemption list. Fix the call site instead.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = (
    REPO_ROOT / "tests",
    REPO_ROOT / "agents" / "daemon_slayer" / "tests",
)
# tests/ alone holds well over a thousand modules; a floor far below that still
# fails a vacuous (empty or mis-rooted) walk instead of reading it as clean.
MIN_FILES_SCANNED = 500

_ENVIRON_ATTRS = {"environ", "environb"}
_WRAPPERS = {"dict", "set", "list", "sorted", "frozenset", "tuple"}
_VIEW_METHODS = {"copy", "keys", "items", "values"}
_COMPREHENSIONS = (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)
_STR_BUILDERS = {"str", "repr", "format", "pformat", "pprint"}


def _is_environ_expr(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Attribute) and node.attr in _ENVIRON_ATTRS:
        return True
    if isinstance(node, ast.Name) and node.id in aliases:
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in _WRAPPERS and node.args:
            return _is_environ_expr(node.args[0], aliases)
        if isinstance(func, ast.Attribute) and func.attr in _VIEW_METHODS:
            return _is_environ_expr(func.value, aliases)
    if isinstance(node, _COMPREHENSIONS):
        return any(_is_environ_expr(g.iter, aliases) for g in node.generators)
    return False


def _collect_aliases(tree: ast.AST) -> set[str]:
    """Names bound (anywhere in the file) to an environ expression.

    Seeded from ``from os import environ [as x]``, then iterated to a fixed
    point so ``a = os.environ; b = dict(a)`` marks both.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for a in node.names:
                if a.name in _ENVIRON_ATTRS:
                    aliases.add(a.asname or a.name)
    while True:
        before = len(aliases)
        for node in ast.walk(tree):
            targets: list[ast.AST] = []
            value = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None or not _is_environ_expr(value, aliases):
                continue
            for t in targets:
                if isinstance(t, ast.Name):
                    aliases.add(t.id)
        if len(aliases) == before:
            return aliases


def _rewriter_reaches_environ(node: ast.AST, aliases: set[str]) -> bool:
    """Would pytest's assertion explanation render an environ mapping?"""
    if _is_environ_expr(node, aliases):
        return True
    if isinstance(node, (*_COMPREHENSIONS, ast.Lambda)):
        return False
    if isinstance(node, ast.Subscript):
        return _rewriter_reaches_environ(node.slice, aliases)
    return any(_rewriter_reaches_environ(c, aliases) for c in ast.iter_child_nodes(node))


def _value_renders_environ(node: ast.AST, aliases: set[str]) -> bool:
    """Is this VALUE (a unittest arg or an assert msg) an environ mapping or a
    string built from one?"""
    if _is_environ_expr(node, aliases):
        return True
    if isinstance(node, ast.JoinedStr):
        return any(_value_renders_environ(v.value, aliases)
                   for v in node.values if isinstance(v, ast.FormattedValue))
    if isinstance(node, ast.BinOp):
        return (_value_renders_environ(node.left, aliases)
                or _value_renders_environ(node.right, aliases))
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_value_renders_environ(e, aliases) for e in node.elts)
    if isinstance(node, ast.Dict):
        return any(_value_renders_environ(v, aliases) for v in node.values)
    if isinstance(node, ast.Call):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name in _STR_BUILDERS or name == "join":
            args = [*node.args, *(k.value for k in node.keywords)]
            return any(_value_renders_environ(a, aliases) for a in args)
    return False


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def find_environ_assert_operands(source: str, filename: str = "<string>") -> list[str]:
    """Return ``file:line: description`` for every leaking assertion in ``source``."""
    tree = ast.parse(source, filename=filename)
    aliases = _collect_aliases(tree)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            if _rewriter_reaches_environ(node.test, aliases):
                hits.append(f"{filename}:{node.lineno}: assert expression explains an environ mapping")
            if node.msg is not None and _value_renders_environ(node.msg, aliases):
                hits.append(f"{filename}:{node.lineno}: assert message renders an environ mapping")
        elif isinstance(node, ast.Call) and _call_name(node.func).startswith("assert"):
            args = [*node.args, *(k.value for k in node.keywords)]
            if any(_value_renders_environ(a, aliases) for a in args):
                hits.append(
                    f"{filename}:{node.lineno}: {_call_name(node.func)}() takes an environ mapping")
    return hits


def _iter_test_sources():
    for base in SCAN_DIRS:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(".py"):
                    yield Path(dirpath) / fn


# ---- positive controls: the checker must SEE each bad shape ----------------

def _one_hit(body: str) -> None:
    src = "import os\nfrom os import environ\ndef test_x(self, m):\n" + body
    hits = find_environ_assert_operands(src)
    assert len(hits) == 1, (body, hits)


def test_checker_flags_bare_assert_membership():
    _one_hit("    assert 'FLAG' not in os.environ\n")


def test_checker_flags_assert_on_environ_get_because_pytest_explains_the_mapping():
    _one_hit("    assert os.environ.get('FLAG') is None\n")
    _one_hit("    assert os.environ.get('FLAG'), 'unset'\n")


def test_checker_flags_unittest_membership():
    _one_hit("    self.assertNotIn('FLAG', os.environ)\n")


def test_checker_flags_aliases_wrappers_and_from_import():
    _one_hit("    env = os.environ\n    assert 'A' in env\n")
    _one_hit("    snap = dict(os.environ)\n    assert snap == {}\n")
    _one_hit("    snap = {k: v for k, v in os.environ.items()}\n    self.assertEqual(snap, {})\n")
    _one_hit("    assert 'C' in environ\n")
    _one_hit("    self.assertIn('D', set(os.environ))\n")
    _one_hit("    self.assertDictEqual(os.environ.copy(), {})\n")
    _one_hit("    m.assert_called_with(env=os.environ)\n")
    _one_hit("    assert x, f'env was {os.environ}'\n")


def test_checker_passes_the_safe_forms():
    src = (
        "import os\n"
        "def test_x(self, environ):\n"
        "    v = os.environ.get('FLAG')\n"
        "    assert v is None\n"
        "    assert os.getenv('FLAG') is None\n"
        "    assert os.environ['FLAG'] == '1'\n"
        "    assert all(k not in os.environ for k in ('A', 'B'))\n"
        "    self.assertIsNone(os.environ.get('FLAG'))\n"
        "    self.assertFalse('FLAG' in os.environ, msg='FLAG set')\n"
        "    self.assertEqual(os.environ.get('FLAG'), '1')\n"
        "    assert 'X' not in environ\n"  # a local parameter, not os.environ
        "    if 'X' in os.environ:\n"
        "        pass\n"
    )
    assert find_environ_assert_operands(src) == []


# ---- the sweep ---------------------------------------------------------------

def test_no_test_asserts_against_the_whole_environment():
    files = list(_iter_test_sources())
    assert len(files) >= MIN_FILES_SCANNED, (
        f"only {len(files)} test files enumerated under {[str(d) for d in SCAN_DIRS]}; "
        f"an empty or mis-rooted walk must not read as clean")
    assert Path(__file__).resolve() in {f.resolve() for f in files}, "walk missed this file"
    hits: list[str] = []
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        hits.extend(find_environ_assert_operands(path.read_text(encoding="utf-8"), rel))
    assert not hits, (
        "assertions that would render the whole process environment (secrets "
        "included) into a failure message - read the one value to a local "
        "first:\n" + "\n".join(hits))
