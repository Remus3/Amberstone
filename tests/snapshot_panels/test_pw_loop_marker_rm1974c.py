"""
tests/snapshot_panels/test_pw_loop_marker_rm1974c.py
RM-1974c: the snapshot conftest's running-loop marker check.

The hang it bounds: Playwright's sync API keeps its own loop as asyncio's
main-thread running-loop marker between calls, and on Python 3.14 every task
step on that loop checks the marker. agents/agent3_testing/suite/conftest.py
cleared it around each agent3 test, so in an xdist worker that already held
the session browser the next snapshot test's first call never returned
(test_build_insights_sort_header_hover[hextech], killed at 300 s, LEDGER 2064).
The clear is gone and tests/test_asyncio_isolation_guard.py bans it; the
conftest's setup-hook check (RM-2030) turns any later marker change into an immediate,
named failure of the next browser test instead of a hang, and puts
Playwright's loop back so the rest of the worker (and the session teardown's
b.close()) still runs.

These tests pin the check itself (the pure verdict, without touching the real
marker, which would hang this worker) and the one Playwright behaviour it
rests on: after a sync call the marker IS the recorded session loop.
"""
import asyncio
import types

import pytest

from tests.snapshot_panels import conftest as snap


class _Loop:
    def __repr__(self):
        return "<fake loop>"


def test_a_cleared_marker_is_named():
    expected = _Loop()
    problem = snap.pw_loop_marker_problem(None, expected)
    assert problem is not None
    assert "None" in problem and "RM-1974c" in problem, problem


def test_a_swapped_marker_is_named():
    problem = snap.pw_loop_marker_problem(_Loop(), _Loop())
    assert problem is not None and "RM-1974c" in problem, problem


def test_an_intact_or_unarmed_marker_passes():
    loop = _Loop()
    assert snap.pw_loop_marker_problem(loop, loop) is None
    # Before the session browser starts there is nothing to protect.
    assert snap.pw_loop_marker_problem(None, None) is None
    assert snap.pw_loop_marker_problem(loop, None) is None


def test_the_session_browser_arms_the_check(pw_browser):
    """Positive control on the live session: a real round trip completes, the
    check is armed, and the marker is the recorded loop, so a healthy worker
    passes it. If a Playwright upgrade stopped keeping its loop in the marker,
    the check would disarm itself silently; this test reads red instead."""
    ctx = pw_browser.new_context()
    ctx.close()
    recorded = snap._PW_SESSION["loop"]
    assert recorded is not None
    assert recorded.is_running()
    assert asyncio.events._get_running_loop() is recorded
    assert snap.pw_loop_marker_problem(
        asyncio.events._get_running_loop(), recorded) is None


# RM-2030: the check moved from a function-scoped autouse fixture into a
# tryfirst pytest_runtest_setup hook, because pytest sets up module-scoped
# fixtures before function-scoped ones, so a module-scoped fixture that takes
# pw_browser made its Playwright calls before the old check and still hung.
# Measured on a two-module probe (one test clears the marker, the next module
# opens its page in a module-scoped fixture): the old conftest hung to
# --timeout at that fixture; the hook reads one named setup error, and the
# module's next test passes.


def test_the_marker_check_is_a_tryfirst_setup_hook_for_this_folder(request):
    """It must run before ANY fixture of the item, so it is a setup hook that
    pluggy calls ahead of pytest's own (which instantiates the fixtures)."""
    impls = [i for i in request.node.ihook.pytest_runtest_setup.get_hookimpls()
             if i.function is snap.pytest_runtest_setup]
    assert len(impls) == 1, "the snapshot conftest's setup hook is not registered"
    assert impls[0].tryfirst, "the marker check must run before the fixtures"


def test_the_setup_hook_fails_a_browser_item_by_name(monkeypatch):
    """A changed marker fails an item whose closure holds pw_browser, by name.
    The restore it makes writes back the marker this worker already has, so the
    live marker is never changed here."""
    current = asyncio.events._get_running_loop()
    monkeypatch.setitem(snap._PW_SESSION, "loop", current)
    monkeypatch.setattr(snap, "pw_loop_marker_problem",
                        lambda cur, exp: "marker changed (RM-1974c)")
    browser_item = types.SimpleNamespace(fixturenames=["page_mod", "pw_browser"])
    with pytest.raises(pytest.fail.Exception, match="RM-1974c"):
        snap.pytest_runtest_setup(browser_item)
    assert asyncio.events._get_running_loop() is current
    # An item that never reaches the browser is left alone.
    snap.pytest_runtest_setup(types.SimpleNamespace(fixturenames=["tmp_path"]))
    snap.pytest_runtest_setup(object())
