"""MAIN ORDER 2026-10-26 0315 item 1: CodeQL alert 66 (py/bind-socket-all-network-interfaces).

The alert's code flow (read from the python analysis SARIF on b0c755499)
starts at the empty-string literal inside ``vision_server._bind_host`` -
``(os.environ.get("RC_VISION_BIND") or "").strip() or "127.0.0.1"`` - and
runs through ``core.port_handoff.await_port`` / ``can_bind`` into
``socket.bind``. The ``require_loopback`` refusal stops it at run time, but
the source is the literal, not the refusal test, so the earlier dismissal
misread it. ``_bind_host`` is rewritten with no wildcard literal; behaviour
is unchanged: unset or blank still means 127.0.0.1.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import vision_server

REPO = Path(__file__).resolve().parents[1]

# CodeQL's vulnerableHostname() set for this query: the literals it treats as
# "bind to every interface".
_WILDCARDS = {"", "0.0.0.0", "::", "::0"}


def _bind_host_def() -> ast.FunctionDef:
    src = (REPO / "vision_server" / "__init__.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "_bind_host":
            return node
    raise AssertionError("vision_server._bind_host not found")


def test_bind_host_holds_no_wildcard_literal():
    fn = _bind_host_def()
    body = fn.body[1:] if ast.get_docstring(fn) is not None else fn.body
    found = [(n.lineno, n.value) for stmt in body for n in ast.walk(stmt)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and n.value in _WILDCARDS]
    assert not found, f"wildcard literal back in _bind_host: {found}"


def test_unset_means_loopback(monkeypatch):
    monkeypatch.delenv("RC_VISION_BIND", raising=False)
    assert vision_server._bind_host() == "127.0.0.1"


@pytest.mark.parametrize("blank", ["", " ", "\t", " \n "])
def test_empty_or_blank_means_loopback(monkeypatch, blank):
    monkeypatch.setenv("RC_VISION_BIND", blank)
    assert vision_server._bind_host() == "127.0.0.1"


@pytest.mark.parametrize("raw, want", [("127.0.0.2", "127.0.0.2"),
                                       ("  ::1  ", "::1"),
                                       ("localhost\n", "localhost")])
def test_set_value_is_stripped_and_used(monkeypatch, raw, want):
    monkeypatch.setenv("RC_VISION_BIND", raw)
    assert vision_server._bind_host() == want
