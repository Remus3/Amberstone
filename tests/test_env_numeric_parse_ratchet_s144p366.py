"""S144-P-366 - no module-level ``int(os.environ...)`` / ``float(os.environ...)`` that can raise at import.

``int("abc")`` and ``float("abc")`` raise ``ValueError``; an environment variable is operator-typed text, so a typo in
``RC_*`` turns a plain import into a crash of the whole tool (or, for a library module, of every importer: the
lane-8 cycle 39 ``RC_RUNEWRITER_POLL_SEC`` incident in ``lcu/lcu_rune_writer.py`` took four route modules with it).
``float("nan")`` and ``float("-1")`` parse fine and then misbehave as a timeout. The repo's convention is a small
named reader that falls back to the default (``agents/_supervisor_common.py::_env_port``,
``dashboard/routes_state.py::_state_cadence_s``).

Measured 2026-11-08 with an AST walk over every tracked ``*.py`` outside the test trees: THREE call sites, one already
guarded (``dashboard/routes_state.py``) and two bare - ``tools/ds_matchdb_mcp_server.py`` (``DISPATCH_TIMEOUT_S``) and
``tools/keybind_listener.py`` (``LEGION_PORT``). Both now read through a named fallback reader and the baseline is
EMPTY on purpose: a bare call anywhere in scope fails ``test_no_bare_env_numeric_parse``.

Shapes read: ``int(...)`` / ``float(...)`` whose FIRST argument is ``os.environ.get(...)``, ``environ.get(...)``,
``os.getenv(...)`` or ``os.environ[...]``, and that is not inside the ``body`` of a ``try`` with a handler for
``ValueError`` / ``TypeError`` / ``Exception`` (or a bare ``except``). Named blind spots, as every AST ratchet here: a
value first bound to a variable (``raw = os.environ.get(..); int(raw)``), a wrapper such as ``int(x or 5)``, and a
parse in a helper that receives the raw string - those are reviewed by hand.
"""
from __future__ import annotations

import ast


from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "docs/")
_CATCHES = {"ValueError", "TypeError", "Exception", "BaseException"}

# rel path -> bare call count. EMPTY: only shrinks, and it is already at the floor.
_BASELINE: dict[str, int] = {}


def _is_env_read(node: ast.AST) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        f = node.func
        if f.attr == "getenv" and isinstance(f.value, ast.Name) and f.value.id == "os":
            return True
        if f.attr == "get":
            v = f.value
            return (isinstance(v, ast.Attribute) and v.attr == "environ") or (
                isinstance(v, ast.Name) and v.id == "environ")
    if isinstance(node, ast.Subscript):
        v = node.value
        return (isinstance(v, ast.Attribute) and v.attr == "environ") or (
            isinstance(v, ast.Name) and v.id == "environ")
    return False


def _handler_catches(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(n, ast.Name) and n.id in _CATCHES for n in names)


def scan_source(src: str) -> list[int]:
    """Line of every unguarded ``int|float(<env read>)`` call in ``src``."""
    tree = ast.parse(src)
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    hits: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("int", "float") and node.args and _is_env_read(node.args[0])):
            continue
        guarded, cur = False, node
        while cur in parent:
            up = parent[cur]
            if isinstance(up, ast.Try) and cur in up.body and any(_handler_catches(h) for h in up.handlers):
                guarded = True
                break
            cur = up
        if not guarded:
            hits.append(node.lineno)
    return sorted(hits)


def test_scanner_is_live():
    """Each unsafe shape is reported and each safe spelling is quiet (an empty scan proves nothing alone)."""
    bare = (
        "import os\nA = int(os.environ.get('X', '1'))\n",
        "import os\nA = float(os.getenv('X', '1'))\n",
        "import os\nA = int(os.environ['X'])\n",
        "from os import environ\nA = int(environ.get('X', '1'))\n",
        "import os\ndef f():\n    try:\n        pass\n    except KeyError:\n        pass\n    return int(os.environ.get('X', '1'))\n",
        "import os\ntry:\n    pass\nexcept ValueError:\n    A = int(os.environ.get('X', '1'))\n",
    )
    for src in bare:
        assert scan_source(src), src
    safe = (
        "import os\ntry:\n    A = int(os.environ.get('X', '1'))\nexcept ValueError:\n    A = 1\n",
        "import os\ntry:\n    A = float(os.getenv('X'))\nexcept (TypeError, ValueError):\n    A = 1.0\n",
        "import os\ntry:\n    A = int(os.environ['X'])\nexcept Exception:\n    A = 1\n",
        "import os\ntry:\n    A = int(os.environ['X'])\nexcept:\n    A = 1\n",
        "import os\nA = os.environ.get('X', '1')\n",
        "A = int('5')\n",
        "import os\ndef _reader():\n    return 1\nA = int(_reader())\n",
    )
    for src in safe:
        assert scan_source(src) == [], src


def _tree_hits() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in repo_files():
        rel = relative_posix(path)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            lines = scan_source(src)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        if lines:
            out[rel] = len(lines)
    return out


def test_no_bare_env_numeric_parse():
    hits = _tree_hits()
    new = {rel: n for rel, n in hits.items() if n > _BASELINE.get(rel, 0)}
    assert not new, (
        f"int()/float() of an environment variable with no ValueError fallback (a typo crashes the import): {new}")


def test_baseline_is_exact():
    hits = _tree_hits()
    stale = {rel: n for rel, n in _BASELINE.items() if hits.get(rel, 0) < n}
    assert not stale, f"baseline rows that no longer offend, drop them: {stale}"


def test_scan_covers_the_known_readers():
    """The walk must reach the three measured files, or an empty result would be a scan that saw nothing."""
    seen = {relative_posix(p) for p in repo_files()}
    for rel in ("dashboard/routes_state.py", "tools/ds_matchdb_mcp_server.py", "tools/keybind_listener.py"):
        assert rel in seen, rel


# --- behaviour of the two readers this slice added -------------------------------------------------------------


def test_dispatch_timeout_reader_falls_back_on_bad_values():
    from tools import ds_matchdb_mcp_server as mod

    read = mod._dispatch_timeout_from_env
    assert read("60") == 60.0
    assert read("0.5") == 0.5
    for bad in ("45s", "", "abc", "nan", "inf", "-inf", "0", "-3"):
        assert read(bad) == 45.0, bad


def test_dispatch_timeout_reader_reads_the_environment(monkeypatch):
    from tools import ds_matchdb_mcp_server as mod

    monkeypatch.setenv("RC_MCP_DISPATCH_TIMEOUT_S", "oops")
    assert mod._dispatch_timeout_from_env() == 45.0
    monkeypatch.setenv("RC_MCP_DISPATCH_TIMEOUT_S", "12")
    assert mod._dispatch_timeout_from_env() == 12.0
    monkeypatch.delenv("RC_MCP_DISPATCH_TIMEOUT_S")
    assert mod._dispatch_timeout_from_env() == 45.0


def test_legion_port_reader_falls_back_on_bad_values(monkeypatch):
    from tools import keybind_listener as mod

    read = mod._legion_port_from_env
    assert read("9000") == 9000
    assert read("65535") == 65535
    for bad in ("abc", "", "88.88", "0", "-1", "65536", "x"):
        assert read(bad) == 8888, bad
    monkeypatch.setenv("RC_LEGION_PORT", "nope")
    assert read() == 8888
    monkeypatch.setenv("RC_LEGION_PORT", "9001")
    assert read() == 9001
