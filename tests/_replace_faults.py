"""tests/_replace_faults.py - a PORTABLE fault injector for the atomic-write
retry path in core/polled_json.

LANE 8 CYCLE 26. Why this module exists:

Every writer in the tree funnels through ``core.polled_json._write_then_replace``
-> ``_replace_with_retry`` -> ``os.replace``. The retry loop exists because on
Windows ``os.replace`` raises ``PermissionError`` (WinError 5) while a reader
holds the destination open, and RC's polled files are read by other processes by
design.

The lane-8 regression corpus reproduced that condition by simply opening the
target file and relying on the OPERATING SYSTEM to produce the fault:

    with open(target, encoding="utf-8"):
        with self.assertRaises(PermissionError):
            some_writer(target, payload)

That idiom is not portable, and the failure is asymmetric in the worst way:

  * On win32 it works, so the tests are green on the machine that authors them.
  * On POSIX an open handle does NOT block a rename, so the write SUCCEEDS.
    A test asserting the failure goes RED (measured: 9 red tests on the Linux
    CI runner for run 33332566593), and - more insidiously - a test asserting
    only the CLEANUP after a failure goes vacuously GREEN, because no fault
    ever occurred and there was nothing to clean up.

The consequence is that the exhaustion branch of ``_replace_with_retry`` (the
bare ``raise`` after the last backoff) has NEVER been executed on Linux. The
most safety-critical primitive in the tree had its failure path covered only by
an accident of Windows file-locking semantics.

The fix is to inject the fault at the ``os.replace`` boundary instead of asking
the OS for it. The retry loop, the backoff, the scratch-file cleanup and the
re-raise then run identically on every platform, and the Windows-only question
that remains - "does the real OS still produce this condition?" - is a separate,
much smaller, platform-gated assertion living beside each converted test.

Vacuity is designed out rather than documented away. ``replace_fails`` asserts
on exit that it actually fired at least once, so a wrong path, a writer that
never reached ``os.replace``, or a future refactor that routes around the
primitive fails the test LOUDLY instead of passing it silently. That is the
direct lesson of feedback_mutation_that_fails_to_apply_looks_green: a mutation
that fails to apply looks exactly like a mutation the guard caught.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

__all__ = ["ReplaceFaults", "replace_fails"]

# NOTE on the companion real-OS tests: they gate with a literal
# `sys.platform != "win32"` at the decorator rather than importing a named
# constant from here. That is not a style preference - tests/
# test_skip_condition_hygiene.py resolves a skip only when the condition names
# sys.platform / os.name / platform.system DOTTED at the site (its
# _PLATFORM_DOTTED set), and an imported boolean reads to it as UNRESOLVED,
# which it treats as an always-passing guard. A named constant here would have
# been more readable and less checkable.


class ReplaceFaults:
    """Call record for an active ``replace_fails`` block."""

    __slots__ = ("attempts", "failures")

    def __init__(self) -> None:
        self.attempts = 0
        self.failures = 0

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return (f"<ReplaceFaults attempts={self.attempts} "
                f"failures={self.failures}>")


@contextmanager
def replace_fails(target, times: int | None = None, *, expect_fire: bool = True):
    """Make ``os.replace`` raise PermissionError for ``target`` only.

    ``times=None`` fails every attempt, which drives ``_replace_with_retry``
    through its full backoff and out the re-raise: the PERMANENT-contention
    case. ``times=n`` fails the first n attempts and then lets the real replace
    through: the TRANSIENT case the retry loop was written for.

    Only the named destination is faulted; every other replace in the process
    is delegated untouched, so an autouse fixture or a temp-dir helper writing
    an unrelated file is not collaterally broken.

    Yields a :class:`ReplaceFaults` recording attempts and failures. On exit it
    asserts the injector actually fired, unless ``expect_fire=False`` is passed
    for the deliberate no-fault control case. Without that assertion a mistyped
    path would silently disable the fault and leave a green test proving
    nothing.
    """
    target = Path(target)
    real_replace = os.replace
    rec = ReplaceFaults()

    def _fake_replace(src, dst, *a, **kw):
        try:
            same = Path(dst) == target
        except TypeError:  # dst was an int fd or similar - not our target
            same = False
        if same:
            rec.attempts += 1
            if times is None or rec.attempts <= times:
                rec.failures += 1
                raise PermissionError(
                    13, "simulated share-lock on the destination", str(dst))
        return real_replace(src, dst, *a, **kw)

    os.replace = _fake_replace
    try:
        yield rec
    finally:
        os.replace = real_replace

    if expect_fire and rec.failures == 0:
        raise AssertionError(
            f"replace_fails({target}) never fired: os.replace was not called "
            f"with that destination ({rec.attempts} matching attempts). The "
            f"test proved nothing - check the path, and check that the writer "
            f"still routes through core.polled_json."
        )
