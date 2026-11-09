"""S144-P-314 - no tracked ``.py`` calls a stdlib API that is deprecated or removed on the interpreter RC runs on, held at zero.

RC runs Python 3.14 (``ruff.toml`` still says ``target-version = "py39"``, so none of ruff's rules knows which
stdlib names the running interpreter has dropped or warns on). Measured 2026-11-07 on 3.14.4 with
``-W error``: ``datetime.datetime.utcnow()`` and ``asyncio.iscoroutinefunction`` and
``asyncio.get_event_loop_policy`` and ``locale.getdefaultlocale`` raise ``DeprecationWarning`` (a future removal),
and ``pkgutil.find_loader`` and ``ast.Str`` / ``Num`` / ``Bytes`` / ``NameConstant`` / ``Ellipsis`` no longer exist
(``AttributeError``). The tree is clean today (zero hits), so this pins that: a new call fails here instead of at the
first live run on the next interpreter.

Detector (AST over every tracked ``.py``, so a name in a string, comment or docstring never counts):
- a call or reference ``<anything>.utcnow`` / ``<anything>.utcfromtimestamp`` (a datetime classmethod; the repo's own
  ``_utcnow`` helpers are a different name and are not matched);
- ``<module>.<name>`` for the table below, where ``<module>`` is the module name or an ``import ... as`` alias of it;
- ``from <module> import <name>`` for the same table, and ``import imp`` / ``from imp import``.

The fix for each is the replacement named in ``_REPLACEMENT``. The baseline is empty.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_ANY_RECEIVER = {"utcnow", "utcfromtimestamp"}

_MODULE_ATTRS = {
    "asyncio": {"iscoroutinefunction", "coroutine", "get_event_loop_policy", "set_event_loop_policy",
                "AbstractEventLoopPolicy", "DefaultEventLoopPolicy", "WindowsSelectorEventLoopPolicy",
                "WindowsProactorEventLoopPolicy"},
    "pkgutil": {"find_loader", "get_loader"},
    "locale": {"getdefaultlocale"},
    "ast": {"Str", "Num", "Bytes", "NameConstant", "Ellipsis"},
    "inspect": {"getargspec"},
}

_REMOVED_MODULES = {"imp"}

_REPLACEMENT = {
    "utcnow": "datetime.now(timezone.utc)",
    "utcfromtimestamp": "datetime.fromtimestamp(ts, timezone.utc)",
    "iscoroutinefunction": "inspect.iscoroutinefunction",
    "coroutine": "async def",
    "get_event_loop_policy": "asyncio.Runner / loop_factory",
    "set_event_loop_policy": "asyncio.Runner / loop_factory",
    "getdefaultlocale": "locale.getlocale / locale.setlocale",
    "find_loader": "importlib.util.find_spec",
    "get_loader": "importlib.util.find_spec",
    "getargspec": "inspect.signature",
    "imp": "importlib",
}


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> tracked module, for ``import asyncio`` and ``import asyncio as aio``."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in _MODULE_ATTRS:
                    out[a.asname or a.name] = a.name
    return out


def _scan(source: str) -> list[tuple[int, str]]:
    """``(lineno, dotted name)`` for each use of a deprecated or removed stdlib API."""
    tree = ast.parse(source)
    alias = _aliases(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in _ANY_RECEIVER:
                out.append((node.lineno, f".{node.attr}"))
            elif isinstance(node.value, ast.Name) and node.value.id in alias:
                mod = alias[node.value.id]
                if node.attr in _MODULE_ATTRS[mod]:
                    out.append((node.lineno, f"{mod}.{node.attr}"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            root = node.module.split(".")[0]
            if root in _REMOVED_MODULES:
                out.append((node.lineno, f"from {node.module} import ..."))
            elif node.module in _MODULE_ATTRS:
                out.extend((node.lineno, f"{node.module}.{a.name}")
                           for a in node.names if a.name in _MODULE_ATTRS[node.module])
        elif isinstance(node, ast.Import):
            out.extend((node.lineno, f"import {a.name}")
                       for a in node.names if a.name.split(".")[0] in _REMOVED_MODULES)
    return out


def test_no_tracked_py_uses_a_deprecated_or_removed_stdlib_api():
    files = repo_files(REPO_ROOT, ("*.py",))
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    hits: list[str] = []
    seen = 0
    for p in files:
        try:
            found = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        seen += 1
        hits.extend(f"{relative_posix(p)}:{n} {name}" for n, name in found)
    assert seen > 100, "the parse walk returned almost nothing"
    assert not hits, f"deprecated / removed stdlib API in use (see _REPLACEMENT): {hits}"


def test_the_detector_sees_each_spelling():
    cases = {
        "import datetime\nx = datetime.datetime.utcnow()\n": [(2, ".utcnow")],
        "from datetime import datetime as D\nx = D.utcfromtimestamp(1)\n": [(2, ".utcfromtimestamp")],
        "import asyncio\nasyncio.iscoroutinefunction(f)\n": [(2, "asyncio.iscoroutinefunction")],
        "import asyncio as aio\naio.set_event_loop_policy(p)\n": [(2, "asyncio.set_event_loop_policy")],
        "from asyncio import get_event_loop_policy\n": [(1, "asyncio.get_event_loop_policy")],
        "import asyncio\nasyncio.WindowsSelectorEventLoopPolicy()\n": [(2, "asyncio.WindowsSelectorEventLoopPolicy")],
        "import pkgutil\npkgutil.find_loader('x')\n": [(2, "pkgutil.find_loader")],
        "import locale\nlocale.getdefaultlocale()\n": [(2, "locale.getdefaultlocale")],
        "import ast\nisinstance(n, ast.Str)\n": [(2, "ast.Str")],
        "import inspect\ninspect.getargspec(f)\n": [(2, "inspect.getargspec")],
        "import imp\n": [(1, "import imp")],
        "from imp import reload\n": [(1, "from imp import ...")],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_a_modern_spelling_a_string_and_a_local_helper_are_not_flagged():
    clean = (
        "import asyncio, inspect, ast\n"
        "from datetime import datetime, timezone\n"
        "datetime.now(timezone.utc)\n"
        "inspect.iscoroutinefunction(f)\n"
        "isinstance(n, ast.Constant)\n"
        "asyncio.run(main())\n"
        "S._utcnow = lambda: 1\n"
        "monkeypatch.setattr(P, '_utcnow', f)\n"
        "doc = 'datetime.utcnow() and asyncio.iscoroutinefunction'\n"
        "# datetime.utcnow()\n"
        "import importlib\n"
    )
    assert _scan(clean) == []
    shadow = "class asyncio:\n    iscoroutinefunction = 1\nasyncio.iscoroutinefunction\n"
    assert _scan(shadow) == []
    assert set(_REPLACEMENT) >= _ANY_RECEIVER | {"iscoroutinefunction", "getargspec", "imp"}
