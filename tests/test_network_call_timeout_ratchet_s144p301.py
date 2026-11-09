"""S144-P-301 - every tracked network open names a timeout.

``urllib.request.urlopen``, ``socket.create_connection`` / ``websocket.create_connection``,
``http.client.HTTPConnection`` / ``HTTPSConnection`` and the module-level ``requests`` / ``httpx``
verbs all default to NO timeout: a peer that accepts the connection and then goes quiet parks the
caller forever. In a ``pythonw.exe`` agent or a CI step that is a silent hang, not an error.

Measured 2026-11-06 over every tracked ``.py`` (AST, not grep): 4 unbounded calls in 3 files and
none anywhere else - ``tools/overlay_live_frame_probe.py`` (``urlopen`` + ``websocket.create_connection``),
one ``urlopen`` in ``agents/daemon_slayer/tests/test_server.py`` and one ``HTTPConnection`` that never
opens a socket in ``tests/test_vision_token_header_safe_rm241.py``. All four are bounded now. The
baseline is empty on purpose: a new unbounded open fails, there is nothing to shrink.

A call is bounded when it passes ``timeout=`` (any value but a literal ``None``), fills the
positional timeout slot, or splats ``**kwargs`` (the timeout may ride in it - the guard cannot see
inside, so it does not guess).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

# callee final name -> index of the positional ``timeout`` parameter.
_OPENERS = {
    "urlopen": 2,            # urlopen(url, data=None, timeout=...)
    "create_connection": 1,  # socket.create_connection(address, timeout) / websocket.create_connection(url, timeout)
    "HTTPConnection": 2,     # HTTPConnection(host, port=None, timeout=...)
    "HTTPSConnection": 2,
}
_REQUESTS_VERBS = frozenset({"get", "post", "put", "delete", "head", "patch", "request"})
_REQUESTS_MODULES = frozenset({"requests", "httpx"})


def _callee(node: ast.Call) -> tuple[str | None, str | None]:
    """(final name, owning module name when it is ``<name>.<attr>``)."""
    fn = node.func
    if isinstance(fn, ast.Attribute):
        owner = fn.value.id if isinstance(fn.value, ast.Name) else None
        return fn.attr, owner
    if isinstance(fn, ast.Name):
        return fn.id, None
    return None, None


def _timeout_slot(name: str | None, owner: str | None) -> int | None:
    """Positional index of the timeout parameter, ``-1`` for keyword-only, None if not an opener."""
    if name in _OPENERS:
        return _OPENERS[name]
    if name in _REQUESTS_VERBS and owner in _REQUESTS_MODULES:
        return -1
    return None


def unbounded_calls(source: str) -> list[tuple[int, str]]:
    """(line, callee) of every network open in ``source`` that names no timeout."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name, owner = _callee(node)
        slot = _timeout_slot(name, owner)
        if slot is None:
            continue
        if any(k.arg is None for k in node.keywords):
            continue  # **kwargs may carry it
        explicit = [k for k in node.keywords if k.arg == "timeout"]
        if explicit:
            value = explicit[0].value
            if isinstance(value, ast.Constant) and value.value is None:
                out.append((node.lineno, f"{name}(timeout=None)"))
            continue
        if slot >= 0 and len(node.args) > slot:
            continue
        if any(isinstance(a, ast.Starred) for a in node.args):
            continue
        out.append((node.lineno, name or "?"))
    return out


def test_every_tracked_network_open_names_a_timeout():
    offenders: list[str] = []
    scanned = 0
    for path in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if rel == "tests/test_network_call_timeout_ratchet_s144p301.py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
            hits = unbounded_calls(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        scanned += 1
        offenders.extend(f"{rel}:{line} {callee}" for line, callee in hits)
    assert scanned > 500, f"enumeration collapsed: only {scanned} files scanned"
    assert not offenders, (
        "network open with no timeout (hangs forever on a peer that goes quiet); add timeout=...:\n  "
        + "\n  ".join(offenders)
    )


def test_detector_flags_the_unbounded_forms_and_passes_the_bounded_ones():
    flagged = unbounded_calls(
        "import urllib.request as u, socket, http.client as h, requests, websocket\n"
        "u.urlopen('http://x')\n"
        "u.urlopen('http://x', None)\n"
        "socket.create_connection(('h', 1))\n"
        "websocket.create_connection('ws://x', origin='o')\n"
        "h.HTTPSConnection('h')\n"
        "requests.get('http://x')\n"
        "u.urlopen('http://x', timeout=None)\n"
    )
    assert [line for line, _ in flagged] == [2, 3, 4, 5, 6, 7, 8]
    assert unbounded_calls(
        "import urllib.request as u, socket, http.client as h, requests\n"
        "u.urlopen('http://x', timeout=5)\n"
        "u.urlopen('http://x', None, 5)\n"
        "socket.create_connection(('h', 1), 2.0)\n"
        "h.HTTPConnection('h', 80, 3)\n"
        "requests.post('http://x', timeout=(3, 9))\n"
        "u.urlopen('http://x', **kw)\n"
        "session.get('http://x')\n"          # not the module-level verb: out of scope
        "d.get('key')\n"                     # a dict read is not a network call
    ) == []
