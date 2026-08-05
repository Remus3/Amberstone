"""RM-154: every served agent must be diagnosable and must fail loudly.

The scheduled tasks that run these agents (RC-LCUAgent, RC-LiveClientRelay,
RC-HotkeyListener, the screen-agent pair) launch them under pythonw.exe, which
has NO console. Under pythonw a print() goes nowhere, a stderr-only
StreamHandler drops every record, and an unhandled traceback vanishes - so an
agent that dies or 401s does it in total silence and the only symptom is a
coach that stopped updating.

Two invariants close that hole, and both are asserted here against the REAL
allowlist read off disk (dashboard.routes_static._AGENT_ALLOWED) rather than a
duplicated copy - a contract test that carries its own list stops testing the
contract the moment the list grows.

  1. Every served .py agent configures a file-writing log handler pointed at
     logs/<stem>.log. That is the only channel that survives pythonw.
  2. Every served .py agent that resolves an auth token refuses to start when
     that token is blank: log.error(...) then sys.exit(2). LEDGER 1183 removed
     the dead hardcoded token fallbacks, so a missing config now yields "" -
     without this guard the agent posts an empty token, 401s forever, and the
     scheduled task's Last Result stays a reassuring 0.

tools/hotkey_listener.py resolves no token (it drives local hotkeys and does
not publish), so invariant 2 does not apply to it. The exemption is derived
from the source at collection time rather than skipped inside a test, and it
is itself asserted - an exempt agent must send no X-RC-Token - so it evaporates
the moment that agent grows one.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from dashboard.routes_static import _AGENT_ALLOWED

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

AGENT_PY = sorted(n for n in _AGENT_ALLOWED if n.endswith(".py"))


def _tree(name: str) -> tuple[str, ast.Module]:
    src = (TOOLS / name).read_text(encoding="utf-8")
    return src, ast.parse(src)


def _file_handler_calls(tree: ast.Module) -> list[ast.Call]:
    """Calls to any *FileHandler class (RotatingFileHandler counts)."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        label = func.attr if isinstance(func, ast.Attribute) else getattr(
            func, "id", "")
        if label.endswith("FileHandler"):
            found.append(node)
    return found


def _defines_token_resolver(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.FunctionDef) and n.name == "_resolve_auth_token"
        for n in ast.walk(tree)
    )


def _has_tokenless_exit_guard(tree: ast.Module) -> bool:
    """An `if <...TOKEN...>` whose body both log.error's and sys.exit(2)'s.

    Matching on the shape rather than on text keeps this honest: a guard that
    exits without reporting, or reports without exiting, does not pass.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "TOKEN" not in ast.dump(node.test).upper():
            continue
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if "attr='exit'" in body and "Constant(value=2)" in body and (
                "attr='error'" in body):
            return True
    return False


def test_allowlist_has_python_agents():
    # Guards against the whole file silently passing on an empty parametrize.
    assert len(AGENT_PY) >= 4, AGENT_PY


@pytest.mark.parametrize("name", AGENT_PY)
def test_agent_logs_to_a_file(name):
    src, tree = _tree(name)
    handlers = _file_handler_calls(tree)
    assert handlers, (
        f"tools/{name} configures no FileHandler - under pythonw.exe every "
        "print() and stderr record it emits is discarded. Precedent: "
        "tools/liveclient_relay.py:41-51."
    )
    stem = Path(name).stem
    assert f"{stem}.log" in src, (
        f"tools/{name} has a FileHandler but does not target logs/{stem}.log"
    )


TOKEN_AGENTS = [n for n in AGENT_PY if _defines_token_resolver(_tree(n)[1])]
TOKENLESS_AGENTS = [n for n in AGENT_PY if n not in TOKEN_AGENTS]


@pytest.mark.parametrize("name", TOKENLESS_AGENTS)
def test_tokenless_agent_publishes_nothing(name):
    """The exemption from the guard below has to be EARNED, not assumed.

    Partitioning at collection time rather than skipping inside the test keeps
    this a real assertion: if a currently-tokenless agent ever grows an
    X-RC-Token publish, this fails and it moves into TOKEN_AGENTS.
    """
    src, _tree_ = _tree(name)
    assert "X-RC-Token" not in src, (
        f"tools/{name} sends X-RC-Token but defines no _resolve_auth_token - "
        "give it a resolver so the tokenless-start guard applies to it."
    )


@pytest.mark.parametrize("name", TOKEN_AGENTS)
def test_agent_refuses_to_start_tokenless(name):
    _src, tree = _tree(name)
    assert _has_tokenless_exit_guard(tree), (
        f"tools/{name} resolves an auth token but starts anyway when it is "
        "blank. LEDGER 1183 made the blank case reachable; without a "
        "log.error(...) + sys.exit(2) guard every request 401s silently. "
        "Precedent: tools/liveclient_relay.py:218-224."
    )


@pytest.mark.parametrize("name", AGENT_PY)
def test_agent_does_not_report_through_print(name):
    """print() is the exact channel pythonw discards - no agent may rely on it."""
    _src, tree = _tree(name)
    prints = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "print"
    ]
    assert not prints, (
        f"tools/{name} still has {len(prints)} print() call(s); under "
        "pythonw.exe they go nowhere. Convert them to logger calls."
    )
