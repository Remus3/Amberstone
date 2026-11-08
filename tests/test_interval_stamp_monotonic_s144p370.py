"""S144-P-370 - an in-process interval stamp held on ``self`` is taken and aged on ``time.monotonic()``.

``coach_integration/_coach.py`` ``CoachIntegration`` keeps ``self._last_coach_time = time.time()`` and
``_should_coach`` decides the 3 s debounce and the 2 s kill-window gap from ``time.time() - self._last_coach_time``.
The stamp never leaves the process (no reader outside the class, nothing persisted or shown), so a system clock
step (NTP, manual change, VM resume) only corrupts it: a forward step lets a coach call through inside the
debounce (a burst of paid calls), a backward step suppresses coaching until the clock catches up.
``time.monotonic()`` cannot step. (S144-P-363 / S144-P-364 / S144-P-368 made the same change for wait loops and
TTL caches.)

Part 1 is behavioural: the clock is stepped under the live ``_should_coach``. The "never coached" sentinel is
``-inf``, not ``0.0``: a monotonic clock may read a few seconds right after boot, and ``now - 0.0`` would then
debounce the very first call.

Part 2 is a census: an AST walk over every tracked non-test ``*.py`` for a class that assigns
``self.<attr> = time.time()`` (or ``time.time() +/- x``) and whose every read of ``self.<attr>`` is an operand of
a subtraction, the shape of an interval stamp. Measured 2026-11-08: ONE such stamp (the coach one, converted
here), so the named-row table is empty. A stamp that is read by ``getattr`` or returned, stored, compared or
persisted is wall time by design and is excluded by that shape (``PostgameCollector._trigger_at`` is the
measured example); a write-only stamp (``TftVisionReader._last_capture``, ``DecisionCache._last_fetch_ok``)
has no age computation to corrupt and is not reported. Stated limits: a reader in ANOTHER file, a stamp bound
to a local variable first and a module-level stamp are not seen.
"""
from __future__ import annotations

import ast
import time

import pytest

from coach_integration._coach import CoachIntegration
from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "ops/launcher/", "agents/agent3_testing/suite/", "docs/_archive/")

# (file, class, attribute) -> why a wall-clock interval stamp is the design. Empty: the one site was converted.
_ROWS: dict[tuple[str, str, str], str] = {}


@pytest.fixture
def coach(monkeypatch):
    inst = CoachIntegration.__new__(CoachIntegration)
    inst._debounce_s = 3.0
    inst._client = object()
    inst._last_state = {}
    inst.reset_state()
    monkeypatch.setattr(CoachIntegration, "_run_safe", lambda self, state: None)
    return inst


def _joined(coach_inst):
    return coach_inst._should_coach({"dead_count": 0, "hp_pct": 50, "gold": 0})


def test_a_never_coached_instance_coaches_even_right_after_boot(coach, monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 0.5)
    assert coach._should_coach({}) is True


def test_a_forward_wall_clock_step_does_not_lift_the_debounce(coach, monkeypatch):
    coach.request_now({"champion": "x"})
    assert _joined(coach) is False
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 3600.0)
    assert _joined(coach) is False


def test_a_backward_wall_clock_step_does_not_extend_the_debounce(coach, monkeypatch):
    coach.request_now({"champion": "x"})
    real_mono, real_wall = time.monotonic, time.time
    monkeypatch.setattr(time, "monotonic", lambda: real_mono() + coach._debounce_s + 1.0)
    monkeypatch.setattr(time, "time", lambda: real_wall() - 3600.0)
    assert coach._should_coach({}) is True


def test_a_kill_window_gap_is_measured_on_the_monotonic_clock(coach, monkeypatch):
    coach.request_now({"champion": "x"})
    real_mono, real_wall = time.monotonic, time.time
    monkeypatch.setattr(time, "monotonic", lambda: real_mono() + 2.5)
    monkeypatch.setattr(time, "time", lambda: real_wall() - 3600.0)
    assert coach._should_coach({"kill_window": True}) is True


def test_the_stamp_is_monotonic(coach):
    before = time.monotonic()
    coach.request_now({"champion": "x"})
    assert before <= coach._last_coach_time <= time.monotonic()


def test_a_timeout_retry_backdates_the_stamp_on_the_monotonic_clock(coach):
    """The timeout path sets the stamp so the next trigger may fire 2 s on; it must use the same clock."""
    coach._last_coach_time = time.monotonic() - coach._debounce_s + 2.0
    assert coach._should_coach({}) is False
    coach._last_coach_time -= 2.5
    assert coach._should_coach({}) is True


def _is_time_time(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "time"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "time")


def _wall_stamp_value(node: ast.AST) -> bool:
    """``time.time()`` itself or an arithmetic expression with a direct ``time.time()`` operand."""
    if _is_time_time(node):
        return True
    return isinstance(node, ast.BinOp) and (_wall_stamp_value(node.left) or _wall_stamp_value(node.right))


def _is_self_attr(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"


def scan_source(src: str) -> list[tuple[int, str, str]]:
    """``(line, class, attr)`` of every ``self.attr = <wall time>`` whose reads are all subtraction operands."""
    tree = ast.parse(src)
    out: list[tuple[int, str, str]] = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        parent: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(cls):
            for child in ast.iter_child_nodes(node):
                parent[child] = node
        getattr_names = {n.args[1].value for n in ast.walk(cls)
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "getattr"
                         and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)
                         and isinstance(n.args[1].value, str)}
        stamps: dict[str, int] = {}
        for node in ast.walk(cls):
            if isinstance(node, ast.Assign) and _wall_stamp_value(node.value):
                for target in node.targets:
                    if _is_self_attr(target):
                        stamps.setdefault(target.attr, node.lineno)
        for attr, line in stamps.items():
            if attr in getattr_names:
                continue
            loads = [n for n in ast.walk(cls) if _is_self_attr(n) and n.attr == attr and isinstance(n.ctx, ast.Load)]
            if loads and all(isinstance(parent.get(n), ast.BinOp) and isinstance(parent[n].op, ast.Sub)
                             for n in loads):
                out.append((line, cls.name, attr))
    return sorted(out)


def test_scanner_is_live():
    """The interval-stamp shape is reported and each neighbouring safe shape stays quiet."""
    hit = ("import time\nclass C:\n    def go(self):\n        self._t = time.time()\n"
           "    def due(self):\n        return time.time() - self._t > 3\n")
    assert scan_source(hit) == [(4, "C", "_t")]
    shifted = ("import time\nclass C:\n    def back(self):\n        self._t = time.time() - 2.0\n"
               "    def due(self):\n        return time.time() - self._t > 3\n")
    assert scan_source(shifted) == [(4, "C", "_t")]
    quiet = (
        # monotonic is the fix
        "import time\nclass C:\n    def go(self):\n        self._t = time.monotonic()\n"
        "    def due(self):\n        return time.monotonic() - self._t > 3\n",
        # a read that escapes (returned) is a wall time that leaves the process
        "import time\nclass C:\n    def go(self):\n        self._t = time.time()\n"
        "    def when(self):\n        return self._t\n",
        # a read through getattr is invisible to the AST walk, so the attribute is skipped
        "import time\nclass C:\n    def go(self):\n        self._t = time.time()\n"
        "    def due(self):\n        return time.time() - getattr(self, '_t', 0) > 3\n",
        # write-only: nothing ages it
        "import time\nclass C:\n    def go(self):\n        self._t = time.time()\n",
        # one subtraction read plus one escaping read
        "import time\nclass C:\n    def go(self):\n        self._t = time.time()\n"
        "    def due(self):\n        return time.time() - self._t > 3\n"
        "    def when(self):\n        return {'at': self._t}\n",
    )
    for src in quiet:
        assert scan_source(src) == [], src


def _tree_hits() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in repo_files():
        rel = relative_posix(path)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel or not rel.endswith(".py"):
            continue
        try:
            hits = scan_source((REPO_ROOT / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        found.update((rel, cls, attr) for _line, cls, attr in hits)
    return found


def test_no_in_process_interval_stamp_on_the_wall_clock():
    new = _tree_hits() - set(_ROWS)
    assert not new, f"interval stamps taken with time.time() (use time.monotonic()): {sorted(new)}"


def test_rows_are_exact():
    stale = set(_ROWS) - _tree_hits()
    assert not stale, f"rows that no longer offend, drop them: {sorted(stale)}"


def test_scan_reaches_the_converted_file():
    assert "coach_integration/_coach.py" in {relative_posix(p) for p in repo_files()}
