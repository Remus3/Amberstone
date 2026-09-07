"""Make the xdist-only ``subTest`` serialization defect fail everywhere.

MEASURED 2026-07-26 and fixed in ``cd0f115d``: pytest 9's
``_pytest/unittest.py:436`` addSubTest stuffs the RAW ``subTest`` kwargs
into ``SubtestContext(msg=..., kwargs=dict(test.params))`` and emits a
report for EVERY subtest, passing ones included. Under xdist that report
crosses the execnet channel (``xdist/remote.py:289``), and execnet
serializes only builtin primitives - so a bare ``object()`` raises
``execnet.gateway_base.DumpError`` from inside ``subTest.__exit__`` and
fails the PARENT test. Serially there is no channel, so the identical
matrix passes.

``cd0f115d`` fixed the five known instances and swept the rest BY EYE,
recording the result as prose in its commit body. That sweep is a claim
about a moment, not a gate: this repo has 461 ``self.subTest(`` call
sites and the next hostile-input matrix is one non-primitive kwarg away
from re-introducing an ``-n``-only failure that a serial run cannot see.

This module closes that. It validates each ``subTest`` kwarg against
execnet's OWN serializer at call time, so the defect fails identically
in a serial run and under ``-n 8`` - and it fails pointing at the kwarg
rather than at ``subTest.__exit__``.

The fix at a call site is never to drop the hostile input: label by
``repr(value)`` and keep the value itself byte-identical.

Measured serializer behaviour (execnet 2.x, probed 2026-07-28) - the
container types recurse, so a list of ``object()`` fails too:

    OK    None int float complex str bytes list tuple dict set frozenset
    FAIL  object() [object()]

Note ``set()`` DOES serialize; an earlier docstring claimed otherwise.

KNOWN REACH LIMIT, deliberate: a rootdir ``conftest.py`` is only loaded
when pytest is invoked from the repo root, so running the DS suite from
inside ``agents/daemon_slayer/`` bypasses this guard. That invocation is
already ruled out for an unrelated reason (it produces 13 CWD failures -
memory ``reference_ds_suite_run_from_repo_root``) and CI runs from the
root, so the gap is fenced rather than open. It is NOT closed with a
second conftest under ``agents/daemon_slayer/tests/``: a conftest there
importing ``tests._subtest_channel_guard`` would couple the engine suite to
the RC ``tests/`` tree, which it deliberately does not depend on so that it
can run standalone. (That tree is NOT stdlib-only - an earlier version of
this docstring said so and it is false: 32 of its 438 modules import
``core.*`` at module scope. The coupling argument does not rest on the
stronger claim, so only the claim was withdrawn.)
"""
from __future__ import annotations

import unittest
from contextlib import contextmanager

_ORIGINAL_SUBTEST = unittest.TestCase.subTest

# Fallback whitelist for the case where execnet is not installed (the
# suite still runs, just without xdist). Deliberately narrower than
# execnet's real grammar - a false positive here is a loud test failure,
# never a silent pass.
_FALLBACK_SAFE = (type(None), bool, int, float, complex, str, bytes)


def is_channel_safe(value: object) -> bool:
    """True when execnet can put ``value`` on the worker->master channel."""
    try:
        from execnet.gateway_base import dumps
    except Exception:  # noqa: BLE001 - execnet absent; use the whitelist
        if isinstance(value, _FALLBACK_SAFE):
            return True
        if isinstance(value, (list, tuple, set, frozenset)):
            return all(is_channel_safe(v) for v in value)
        if isinstance(value, dict):
            return all(is_channel_safe(k) and is_channel_safe(v)
                       for k, v in value.items())
        return False
    try:
        dumps(value)
    except Exception:  # noqa: BLE001 - DumpError and anything it wraps
        return False
    return True


def offending_params(msg: object, params: dict) -> list[str]:
    """Names of the subTest arguments execnet would refuse to serialize."""
    bad = []
    if msg is not unittest.case._subtest_msg_sentinel and not is_channel_safe(msg):
        bad.append("msg")
    bad.extend(key for key, value in params.items() if not is_channel_safe(value))
    return bad


@contextmanager
def _guarded_subtest(self, msg=unittest.case._subtest_msg_sentinel, **params):
    bad = offending_params(msg, params)
    if bad:
        raise TypeError(
            "subTest argument(s) {} cannot cross the execnet channel, so this "
            "test passes serially and fails under `pytest -n`. Keep the value "
            "under test byte-identical and label the subTest by repr() "
            "instead: self.subTest({}=repr(value)). See "
            "tests/_subtest_channel_guard.py.".format(
                ", ".join(repr(b) for b in bad), bad[0])
        )
    with _ORIGINAL_SUBTEST(self, msg, **params):
        yield


def install() -> None:
    """Idempotently swap the guard in for ``unittest.TestCase.subTest``."""
    if getattr(unittest.TestCase.subTest, "_rc_channel_guard", False):
        return
    _guarded_subtest._rc_channel_guard = True
    unittest.TestCase.subTest = _guarded_subtest
