"""s144 true-audit of core/edge_watcher.py (RM-1041).

Findings pinned here (the P2-4 contract itself stays in
tests/test_edge_watcher_p24.py):

  1. A broken probe was silent. A probe that raises logged at DEBUG only, and
     a probe that returns a non-ProbeState (or no probe at all) logged
     nothing, so a target that could never be read stayed UNREACHABLE - and
     never fired - with nothing at the default log level. Now: one WARNING
     per failure streak per target; any ProbeState return ends the streak.
  2. ``on_appear`` raising an exception whose ``__str__`` itself raises
     escaped ``poll`` / ``observe`` through the record's error string, and
     the on_appear WARNING carried no traceback.
  3. A non-callable ``probe`` or ``on_appear`` was accepted at construction
     and only failed later (the probe silently, as UNREACHABLE forever).
     Now a TypeError at construction.
  4. An unhashable target made ``poll`` raise a bare dict TypeError AFTER
     running the probe, while the docstring said ``poll`` never raises. Now
     a clear TypeError before the probe runs, and the docstring says so.
"""
from __future__ import annotations

import json
import logging

import pytest

from core.edge_watcher import ABSENT, PRESENT, UNREACHABLE, EdgeWatcher

_LOGGER = "rc.edge_watcher"


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == _LOGGER and r.levelno == logging.WARNING]


class _Seq:
    """Probe replaying a list of states or exceptions, counting its calls."""

    def __init__(self, items):
        self.items = list(items)
        self.calls = 0

    def __call__(self, target):
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


# -- finding 1: a broken probe is warned once per streak ----------------------

def test_probe_raising_warns_once_per_streak(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    probe = _Seq([RuntimeError("relay down")] * 3 + [ABSENT]
                 + [RuntimeError("relay down again")] * 2)
    w = EdgeWatcher(probe, None)
    for _ in range(3):
        assert w.poll("g") is None
    assert len(_warnings(caplog)) == 1
    first = _warnings(caplog)[0]
    assert "RuntimeError" in first.getMessage()
    # exc_info=False leaves False on the record, so check the type itself
    assert first.exc_info and first.exc_info[0] is RuntimeError
    w.poll("g")  # a good read ends the streak
    w.poll("g")
    w.poll("g")
    assert len(_warnings(caplog)) == 2
    assert "relay down again" in _warnings(caplog)[1].getMessage()


def test_probe_returning_garbage_warns_once_naming_the_type(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    w = EdgeWatcher(_Seq(["yes", "yes", 1]), None)
    for _ in range(3):
        assert w.poll("g") is None
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "returned str" in warns[0].getMessage()


def test_poll_without_a_probe_warns_once(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    w = EdgeWatcher(None, None)
    for _ in range(4):
        assert w.poll("g") is None
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "no probe" in warns[0].getMessage()


def test_explicit_unreachable_from_probe_is_not_a_failure(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    probe = _Seq([UNREACHABLE] * 3 + [RuntimeError("x"), UNREACHABLE,
                                      RuntimeError("y")])
    w = EdgeWatcher(probe, None)
    for _ in range(3):
        w.poll("g")
    assert _warnings(caplog) == []
    for _ in range(3):
        w.poll("g")
    # the explicit UNREACHABLE between the two raises ended the first streak
    assert len(_warnings(caplog)) == 2


def test_failure_streaks_are_per_target(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)

    def probe(_t):
        raise OSError("down")

    w = EdgeWatcher(probe, None)
    for _ in range(2):
        w.poll("a")
        w.poll("b")
    warns = _warnings(caplog)
    assert len(warns) == 2
    text = " ".join(r.getMessage() for r in warns)
    assert "'a'" in text and "'b'" in text


def test_direct_observe_unreachable_never_warns(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    w = EdgeWatcher(None, None)
    for _ in range(3):
        w.observe("g", UNREACHABLE)
    assert _warnings(caplog) == []


def test_probe_failure_still_unprimes_and_never_fires():
    fired = []
    probe = _Seq([ABSENT, RuntimeError("x"), PRESENT, ABSENT, PRESENT])
    w = EdgeWatcher(probe, fired.append)
    for _ in range(5):
        w.poll("g")
    assert fired == ["g"]  # only the final ABSENT -> PRESENT edge


# -- finding 2: on_appear failure never escapes, and is logged with a trace ---

class _BadStr(Exception):
    def __str__(self):
        raise ValueError("no str for you")


def test_on_appear_exception_with_raising_str_does_not_escape(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)

    def boom(_t):
        raise _BadStr

    w = EdgeWatcher(_Seq([ABSENT, PRESENT]), boom)
    w.poll("g")
    rec = w.poll("g")
    assert rec is not None and rec["action"] == "fire"
    assert rec["error"].startswith("_BadStr")
    json.dumps(rec)


def test_on_appear_warning_carries_the_traceback(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)

    def boom(_t):
        raise RuntimeError("action failed")

    w = EdgeWatcher(None, boom)
    w.observe("g", ABSENT)
    w.observe("g", PRESENT)
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "action failed" in warns[0].getMessage()
    assert warns[0].exc_info and warns[0].exc_info[0] is RuntimeError


# -- finding 3: callables are checked at construction -------------------------

@pytest.mark.parametrize("probe,on_appear", [
    ("not callable", None),
    (None, 5),
    (ABSENT, None),
    (None, ["x"]),
])
def test_non_callable_probe_or_action_is_refused(probe, on_appear):
    with pytest.raises(TypeError):
        EdgeWatcher(probe, on_appear)


def test_none_and_callables_are_accepted():
    EdgeWatcher(None, None)
    EdgeWatcher(lambda t: ABSENT, lambda t: None, dry_run=True)


# -- finding 4: an unhashable target is a clear caller error -------------------

def test_unhashable_target_raises_before_the_probe_runs():
    probe = _Seq([ABSENT])
    w = EdgeWatcher(probe, None)
    with pytest.raises(TypeError, match="target must be hashable"):
        w.poll(["live_game"])
    assert probe.calls == 0


def test_observe_unhashable_target_raises_clear_type_error():
    w = EdgeWatcher(None, None)
    with pytest.raises(TypeError, match="target must be hashable"):
        w.observe({"t": 1}, ABSENT)


def test_direct_reachable_observe_ends_a_poll_failure_streak(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    w = EdgeWatcher(None, None)
    w.poll("g")
    w.poll("g")
    assert len(_warnings(caplog)) == 1
    w.observe("g", ABSENT)  # the caller read it some other way: reachable
    w.poll("g")
    assert len(_warnings(caplog)) == 2


def test_poll_docstring_states_the_caller_error():
    doc = EdgeWatcher.poll.__doc__ or ""
    assert "TypeError" in doc
