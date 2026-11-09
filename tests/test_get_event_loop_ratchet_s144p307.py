"""S144-P-307 - ``asyncio.get_event_loop()`` is held at zero in the tracked tree.

Python 3.12 deprecated the implicit-loop behaviour of ``asyncio.get_event_loop()`` and 3.14 removed it: with no
running loop and none set on the thread the call raises ``RuntimeError`` (3.14.4 measured 2026-11-06). The one site,
``agents/supervisor.py`` ``Supervisor._on_mode_transition``, read
``asyncio.get_running_loop() if asyncio.get_event_loop().is_running() else None`` and then logged "no running loop -
skipping auto-analyze schedule" on the ``None`` branch. That branch was unreachable: outside a running loop the
``get_event_loop()`` in the condition raised first, so the documented skip became an exception that surfaced in the
caller (``FileIngest`` swallows it as a ``warning``, which is how it stayed unseen). The fix asks the one question
that never raises for the wrong reason: ``get_running_loop()`` inside ``try / except RuntimeError``.

The ratchet is an AST walk over every tracked ``.py`` (a name in a string or comment does not count), baseline empty.
It matches any attribute / name / import reference, not only a call (S144-P-308: a test mock still configured
``_aio.get_event_loop.return_value`` after the production code stopped reading it).
``ops/fleet_kit/`` is vendored byte-for-byte and is skipped; it has no site today.
"""
from __future__ import annotations

import ast
import asyncio
from unittest.mock import patch

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP = ("ops/fleet_kit/",)


def _sites(source: str) -> list[int]:
    """Every reference to the name, not only a call: ``mock.get_event_loop.return_value`` configures a seam
    nothing reads any more (S144-P-308), and ``from asyncio import get_event_loop`` is the call in waiting."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Attribute) and node.attr == "get_event_loop") or (
            isinstance(node, ast.Name) and node.id == "get_event_loop"
        ):
            out.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            out.extend(node.lineno for a in node.names if a.name == "get_event_loop")
    return sorted(set(out))


def test_no_get_event_loop_in_the_tracked_tree():
    files = repo_files(REPO_ROOT, ("*.py",))
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    hits = []
    for p in files:
        rel = relative_posix(p)
        if rel.startswith(_SKIP):
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            lines = _sites(src)
        except SyntaxError:
            continue
        hits.extend(f"{rel}:{n}" for n in lines)
    assert not hits, f"asyncio.get_event_loop() (RuntimeError with no loop on 3.14): {hits}"


def test_the_detector_sees_both_call_shapes():
    """Positive control: a clean tree must not be a detector that stopped matching."""
    assert _sites("import asyncio\nasyncio.get_event_loop()\n") == [2]
    assert _sites("from asyncio import get_event_loop\nget_event_loop().run_forever()\n") == [1, 2]
    assert _sites("import asyncio\nasyncio.get_running_loop()\nx = 'get_event_loop()'\n") == []


def test_mode_transition_outside_a_loop_skips_instead_of_raising():
    """The behaviour fix: game -> client with no running loop logs the skip and returns."""
    from agents.supervisor import Supervisor

    sup = Supervisor()
    with pytest.raises(RuntimeError):
        asyncio.get_running_loop()  # precondition: this test runs outside any loop
    with patch("agents.supervisor.log") as log:
        sup._on_mode_transition("game", "client")  # must not raise
    assert not getattr(sup, "_auto_analyze_task", None)
    assert any("no running loop" in c.args[0] for c in log.debug.call_args_list)
