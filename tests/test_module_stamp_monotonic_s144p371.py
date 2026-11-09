"""S144-P-371 - a module-level interval stamp is taken and aged on ``time.monotonic()``.

S144-P-370 held the ``self.<attr> = time.time()`` shape at zero; this is its module-global sibling. A name
bound to ``time.time()`` (directly, or through a local in a function that declares it ``global``) and read
only as a subtraction operand is an in-process interval stamp: nothing persists it, nothing shows it. A
system clock step (NTP, manual change, VM resume) corrupts it - and in ``dashboard/routes_state.py`` that
meant the ``/api/state`` payload cache: after a backward step of N seconds ``now - _STATE_CACHE_TS`` stayed
negative, so the cached payload was served for N seconds and the dashboard froze on a stale state. The
same file's capability-gap log throttle and client-console 10 Hz throttle, ``coaches/voice_coach.py``'s
min-interval gate and the two ``uptime_s`` stamps (``tools/ds_matchdb_mcp_server.py``,
``vision_server/_config.py``) had the same shape.

Part 1 is behavioural (the clock is stepped under the live code). The "never stamped" sentinel is
``-inf``, not ``0.0``: a monotonic clock may read a few seconds right after boot, and ``now - 0.0`` would
then throttle the very first event.

Part 2 is a census over every tracked non-test ``*.py``: a module-level name bound to wall time whose every
read is a subtraction operand. Measured 2026-11-08: SIX such stamps (all converted here; the census sees five,
the sixth - ``_START_TIME`` - is read in two OTHER files and is pinned by the per-file check), so the named-row
table is empty. ``dashboard/routes_team_context.py`` ``_CACHE_TS`` is read as a plain value (it is shown to
the client) and is excluded by that shape; the measured example of a wall stamp that is wall time by design.
Stated limits: a reader in ANOTHER file, a stamp held in a dict or attribute of another object and a mode
read through ``globals()`` are not seen.
"""
from __future__ import annotations

import ast
import json
import time
from unittest import mock

import pytest

from tests._module_view import bind_subprocess
from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "ops/launcher/", "agents/agent3_testing/suite/", "docs/_archive/")

# (file, name) -> why a wall-clock module stamp is the design. Empty: every site was converted.
_ROWS: dict[tuple[str, str], str] = {}


# ---------------------------------------------------------------- behaviour


@pytest.fixture
def rs():
    from dashboard import routes_state
    saved = (routes_state._STATE_CACHE_PAYLOAD, routes_state._STATE_CACHE_TS)
    routes_state._STATE_CACHE_PAYLOAD = None
    routes_state._STATE_CACHE_TS = 0.0
    yield routes_state
    routes_state._STATE_CACHE_PAYLOAD, routes_state._STATE_CACHE_TS = saved


def test_a_backward_wall_clock_step_does_not_freeze_the_state_cache(rs, monkeypatch):
    builds = []
    with mock.patch.object(rs, "_timed_build_state", side_effect=lambda: builds.append(1) or {"n": len(builds)}):
        first = rs._state_payload_cached()
        real_mono, real_wall = time.monotonic, time.time
        monkeypatch.setattr(time, "monotonic", lambda: real_mono() + rs._STATE_CADENCE_S + 1.0)
        monkeypatch.setattr(time, "time", lambda: real_wall() - 3600.0)
        second = rs._state_payload_cached()
    assert len(builds) == 2
    assert json.loads(first) != json.loads(second)


def test_a_forward_wall_clock_step_does_not_expire_a_fresh_state_cache(rs, monkeypatch):
    builds = []
    with mock.patch.object(rs, "_timed_build_state", side_effect=lambda: builds.append(1) or {"n": len(builds)}):
        rs._state_payload_cached()
        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() + 3600.0)
        rs._state_payload_cached()
    assert len(builds) == 1


def test_the_capgap_throttle_survives_a_backward_wall_clock_step(rs, monkeypatch):
    monkeypatch.setenv("RC_CAPGAP_SHADOW", "1")
    monkeypatch.setattr(rs, "_capgap_last_log", time.monotonic())
    real_mono, real_wall = time.monotonic, time.time
    monkeypatch.setattr(time, "monotonic", lambda: real_mono() + rs._CAPGAP_THROTTLE_S + 1.0)
    monkeypatch.setattr(time, "time", lambda: real_wall() - 3600.0)
    reads = []
    monkeypatch.setattr("core.liveclient_cache.get", lambda: reads.append(1) or mock.Mock(data=None, age_s=0.0))
    rs._capgap_shadow_log()
    assert reads, "the throttle window elapsed on the monotonic clock, so the cache must be read"


@pytest.mark.parametrize("rel, name", [
    ("dashboard/routes_state.py", "_capgap_last_log"),
    ("dashboard/routes_state.py", "_CE_LAST_TS"),
    ("coaches/voice_coach.py", "_LAST_TS"),
])
def test_a_never_stamped_throttle_starts_at_minus_infinity(rel, name):
    """``now - 0.0`` on a monotonic clock that reads 0.5 s after boot would throttle the first event."""
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    values = [ast.unparse(n.value) for n in tree.body
              if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None
              and any(isinstance(t, ast.Name) and t.id == name
                      for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))]
    assert values == ["float('-inf')"], values


def test_voice_coach_min_interval_is_aged_on_the_monotonic_clock(monkeypatch):
    from coaches import voice_coach
    from core import live_game_gate

    class _Popen:
        calls = 0

        def __init__(self, *a, **k):
            type(self).calls += 1

    monkeypatch.setattr(live_game_gate, "live_game_now", lambda: False)
    bind_subprocess(monkeypatch, voice_coach, Popen=_Popen)
    monkeypatch.setattr(voice_coach, "_LAST_TS", float("-inf"))
    monkeypatch.setattr(voice_coach, "_LAST_TEXT", "")
    assert voice_coach.speak("first line") is True
    real_mono, real_wall = time.monotonic, time.time
    # backward wall step: the old wall-clock gate saw a negative interval and stayed shut for an hour
    monkeypatch.setattr(time, "monotonic", lambda: real_mono() + voice_coach._MIN_INTERVAL_S + 1.0)
    monkeypatch.setattr(time, "time", lambda: real_wall() - 3600.0)
    assert voice_coach.speak("second line") is True
    assert _Popen.calls == 2


@pytest.mark.parametrize("rel, name", [
    ("dashboard/routes_state.py", "_STATE_CACHE_TS"),
    ("dashboard/routes_state.py", "_capgap_last_log"),
    ("dashboard/routes_state.py", "_CE_LAST_TS"),
    ("coaches/voice_coach.py", "_LAST_TS"),
    ("tools/ds_matchdb_mcp_server.py", "_START"),
    ("vision_server/_config.py", "_START_TIME"),
])
def test_each_converted_stamp_is_off_the_wall_clock(rel, name):
    assert (rel, name) not in _tree_hits() | _loose_hits()


# ------------------------------------------------------------------- census


def _is_time_time(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "time"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "time")


def _wall(node: ast.AST, local_names: set[str]) -> bool:
    """``time.time()``, a local bound to it, or arithmetic with one of those as a direct operand."""
    if _is_time_time(node):
        return True
    if isinstance(node, ast.Name) and node.id in local_names:
        return True
    return isinstance(node, ast.BinOp) and (_wall(node.left, local_names) or _wall(node.right, local_names))


def _stamp_names(tree: ast.Module) -> dict[str, int]:
    """Module-level names bound to wall time, at module level or in a function that declares them ``global``."""
    stamps: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and _wall(node.value, set()):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    stamps.setdefault(target.id, node.lineno)
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        declared = {name for g in ast.walk(fn) if isinstance(g, ast.Global) for name in g.names}
        if not declared:
            continue
        local_names: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and _wall(node.value, local_names):
                local_names.update(t.id for t in node.targets
                                   if isinstance(t, ast.Name) and t.id not in declared)
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and _wall(node.value, local_names):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in declared:
                        stamps.setdefault(target.id, node.lineno)
    return stamps


def scan_source(src: str) -> list[tuple[int, str]]:
    """``(line, name)`` of every module stamp bound to wall time whose reads are all subtraction operands."""
    tree = ast.parse(src)
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    out = []
    for name, line in _stamp_names(tree).items():
        loads = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)]
        if loads and all(isinstance(parent.get(n), ast.BinOp) and isinstance(parent[n].op, ast.Sub)
                         for n in loads):
            out.append((line, name))
    return sorted(out)


def test_scanner_is_live():
    hit = "import time\n_T = time.time()\ndef up():\n    return time.time() - _T\n"
    assert scan_source(hit) == [(2, "_T")]
    via_local = ("import time\n_T = 0.0\ndef go():\n    global _T\n    now = time.time()\n    _T = now\n"
                 "def due():\n    return time.time() - _T > 3\n")
    assert scan_source(via_local) == [(6, "_T")]
    shifted = ("import time\n_T = 0.0\ndef go():\n    global _T\n    _T = time.time() + 5\n"
               "def due():\n    return time.time() - _T > 3\n")
    assert scan_source(shifted) == [(5, "_T")]
    quiet = (
        # monotonic is the fix
        "import time\n_T = time.monotonic()\ndef up():\n    return time.monotonic() - _T\n",
        # a read that escapes (shown to a client) is a wall time by design
        "import time\n_T = 0.0\ndef go():\n    global _T\n    _T = time.time()\ndef when():\n    return {'at': _T}\n",
        # write-only: nothing ages it
        "import time\n_T = time.time()\n",
        # one subtraction read plus one escaping read
        "import time\n_T = time.time()\ndef up():\n    return time.time() - _T\ndef when():\n    return _T\n",
        # a local that is never a global declaration is not a module stamp
        "import time\ndef go():\n    t = time.time()\n    return time.time() - t\n",
    )
    for src in quiet:
        assert scan_source(src) == [], src


def _tree_hits() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in repo_files():
        rel = relative_posix(path)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel or not rel.endswith(".py"):
            continue
        try:
            hits = scan_source((REPO_ROOT / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        found.update((rel, name) for _line, name in hits)
    return found


def _loose_hits() -> set[tuple[str, str]]:
    """Stamps in the converted files that are still bound to wall time, whatever their reads look like."""
    found: set[tuple[str, str]] = set()
    for rel in ("dashboard/routes_state.py", "coaches/voice_coach.py", "tools/ds_matchdb_mcp_server.py",
                "vision_server/_config.py"):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        found.update((rel, name) for name in _stamp_names(tree))
    return found


def test_no_module_interval_stamp_on_the_wall_clock():
    new = _tree_hits() - set(_ROWS)
    assert not new, f"module interval stamps taken with time.time() (use time.monotonic()): {sorted(new)}"


def test_rows_are_exact():
    stale = set(_ROWS) - _tree_hits()
    assert not stale, f"rows that no longer offend, drop them: {sorted(stale)}"


def test_scan_reaches_the_converted_files():
    walked = {relative_posix(p) for p in repo_files()}
    for rel in ("dashboard/routes_state.py", "coaches/voice_coach.py", "tools/ds_matchdb_mcp_server.py",
                "vision_server/_config.py"):
        assert rel in walked
