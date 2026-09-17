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
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

__all__ = ["ReplaceFaults", "replace_fails", "scoped_fs_fault", "scoped_path_fault"]

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


# --------------------------------------------------------------------------- #
# RM-411: a ROOT-scoped injector with a control inside the armed window
# --------------------------------------------------------------------------- #
# ``monkeypatch.setattr(mod.os, "replace", ...)`` READS like containment and is
# not: ``mod.os`` is the one stdlib ``os`` module every importer in the process
# shares, so an unconditional shim breaks ``os.replace`` for every other caller
# in the process while it is armed - background threads above all. (The -n 8
# xdist reason once given for this is REFUTED: workers are separate processes.)
#
# ``scoped_fs_fault`` runs ``action`` only for a destination at or under
# ``root`` and delegates everything else to the real callable captured before
# patching. The scoping is PROVEN, not assumed: on entry, inside the armed
# window, a CONTROL call through the patched name moves a file in a fresh
# directory outside ``root`` and must succeed. Make the shim unconditional and
# that control is what fails first.

# RM-464 round 2 adds "open": os.open(path, flags, ...) is scoped on its PATH
# argument (the first positional), where replace / rename are scoped on dst.
_SCOPED_NAMES = ("replace", "rename", "open")


def _at_or_under(root: Path, dst) -> bool:
    try:
        resolved = Path(os.fspath(dst)).resolve()
    except TypeError:  # an fd or similar - never ours
        return False
    return resolved == root or root in resolved.parents


def _fs_in_scope(root: Path, dst) -> bool:
    # The SHIM's scope seam, separate from the control-dir check (RM-464), so a
    # mutation that widens the shim leaves the control's own check honest.
    return _at_or_under(root, dst)


def _assert_open_control_delegates(root: Path, control: Path) -> None:
    p = control / "control.open"
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, b"rm464-control")
        finally:
            os.close(fd)
        with open(p, "rb") as fh:
            ok = fh.read() == b"rm464-control"
    except Exception as exc:
        raise AssertionError(
            f"os.open outside {root} did not delegate to the real call: {exc!r}"
        ) from exc
    if not ok:
        raise AssertionError(f"os.open outside {root} did not delegate to the real call")


def _assert_control_delegates(name: str, root: Path) -> None:
    control = Path(tempfile.mkdtemp(prefix="rm411_control_"))
    try:
        if _at_or_under(root, control):
            raise AssertionError(f"control dir {control} is under {root}; it proves nothing")
        if name == "open":
            _assert_open_control_delegates(root, control)
            return
        src, dst = control / "control.src", control / "control.dst"
        src.write_bytes(b"rm411-control")
        getattr(os, name)(src, dst)
        if src.exists() or dst.read_bytes() != b"rm411-control":
            raise AssertionError(f"os.{name} outside {root} did not delegate to the real call")
    finally:
        shutil.rmtree(control, ignore_errors=True)


@contextmanager
def scoped_fs_fault(name: str, root, action, *, expect_fire: bool = True):
    """Patch ``os.<name>`` so ``action(real, *args, **kw)`` runs only when the
    scoped path resolves at or under ``root``; every other call is delegated.

    ``name`` is ``"replace"`` / ``"rename"`` (scoped on ``dst``, the action is
    called as ``action(real, src, dst, *a, **kw)``) or ``"open"`` (scoped on
    ``path``, called as ``action(real, path, flags, *a, **kw)``). Yields a
    :class:`ReplaceFaults` whose ``attempts`` counts the in-scope calls
    (``failures`` is left to the action). Asserts the control delegation on
    entry and, on a clean exit, that at least one in-scope call happened - a
    mistyped root would otherwise leave a green test that injected nothing -
    unless ``expect_fire=False`` is passed for a spy that may see none.
    """
    if name not in _SCOPED_NAMES:
        raise ValueError(f"scoped_fs_fault supports {_SCOPED_NAMES}, not {name!r}")
    root = Path(root).resolve()
    real = getattr(os, name)
    rec = ReplaceFaults()
    scoped_index, scoped_kw = (0, "path") if name == "open" else (1, "dst")

    def _scoped(*args, **kw):
        scoped = args[scoped_index] if len(args) > scoped_index else kw.get(scoped_kw)
        if scoped is not None and _fs_in_scope(root, scoped):
            rec.attempts += 1
            return action(real, *args, **kw)
        return real(*args, **kw)

    setattr(os, name, _scoped)
    try:
        _assert_control_delegates(name, root)
        yield rec
    finally:
        setattr(os, name, real)

    if expect_fire and rec.attempts == 0:
        raise AssertionError(f"scoped_fs_fault(os.{name}, {root}) never saw an in-scope call - the test proved nothing")


# --------------------------------------------------------------------------- #
# RM-464: the pathlib sibling - a ROOT-scoped Path method fault
# --------------------------------------------------------------------------- #
# ``monkeypatch.setattr(Path, "unlink", boom)`` patches the CLASS, so every Path
# instance in the process hits ``boom`` while it is armed - the same blast
# radius as the ``os.replace`` patches RM-411 scoped, one layer up. A test
# that keys its fault on a NAME (``self.name.endswith(".tmp")``) is not scoped
# either: every atomic writer in the tree writes a ``*.tmp`` scratch.
#
# ``scoped_path_fault`` scopes on a PATH. For ``replace`` / ``rename`` the
# scoped path is the DESTINATION (matching ``scoped_fs_fault``); for every other
# method it is the path the method is called on. The control on entry runs the
# method through the patched class attribute on a fresh directory outside
# ``root`` and must see the real effect on disk; any exception there is turned
# into an AssertionError naming the delegation failure.

_PATH_NAMES = ("unlink", "replace", "rename", "mkdir", "write_bytes", "write_text")
_PATH_DEST_ARG = ("replace", "rename")
_CONTROL_PAYLOAD = b"rm464-control"


def _path_in_scope(root: Path, path) -> bool:
    # A separate seam from _at_or_under, so a mutation of the SHIM's scoping
    # leaves the control's own "is my directory outside root" check honest.
    return _at_or_under(root, path)


def _raw_write(p: Path, data: bytes) -> None:
    with open(p, "wb") as fh:  # builtins.open, never a Path method under test
        fh.write(data)


def _raw_read(p: Path) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def _assert_path_control_delegates(name: str, root: Path) -> None:
    control = Path(tempfile.mkdtemp(prefix="rm464_control_"))
    try:
        if _at_or_under(root, control):
            raise AssertionError(f"control dir {control} is under {root}; it proves nothing")
        method = getattr(Path, name)
        try:
            if name == "unlink":
                p = control / "control.del"
                _raw_write(p, _CONTROL_PAYLOAD)
                method(p)
                ok = not os.path.lexists(p)
            elif name in _PATH_DEST_ARG:
                src, dst = control / "control.src", control / "control.dst"
                _raw_write(src, _CONTROL_PAYLOAD)
                method(src, dst)
                ok = not os.path.lexists(src) and _raw_read(dst) == _CONTROL_PAYLOAD
            elif name == "mkdir":
                p = control / "control.dir"
                method(p)
                ok = os.path.isdir(p)
            elif name == "write_bytes":
                p = control / "control.bin"
                method(p, _CONTROL_PAYLOAD)
                ok = _raw_read(p) == _CONTROL_PAYLOAD
            else:  # write_text
                p = control / "control.txt"
                method(p, _CONTROL_PAYLOAD.decode("ascii"), encoding="ascii")
                ok = _raw_read(p) == _CONTROL_PAYLOAD
        except Exception as exc:
            raise AssertionError(
                f"Path.{name} outside {root} did not delegate to the real method: {exc!r}"
            ) from exc
        if not ok:
            raise AssertionError(f"Path.{name} outside {root} did not delegate to the real method")
    finally:
        shutil.rmtree(control, ignore_errors=True)


@contextmanager
def scoped_path_fault(name: str, root, action, *, expect_fire: bool = True):
    """Patch ``pathlib.Path.<name>`` so ``action(real, self, *a, **kw)`` runs
    only when the scoped path resolves at or under ``root``; every other call
    is delegated to the real method captured before patching.

    The scoped path is the destination for ``replace`` / ``rename`` and
    ``self`` otherwise. Yields a :class:`ReplaceFaults` whose ``attempts``
    counts in-scope calls. Asserts the control delegation on entry and, on a
    clean exit, that at least one in-scope call happened - unless
    ``expect_fire=False`` is passed for a spy that may legitimately see none.
    """
    if name not in _PATH_NAMES:
        raise ValueError(f"scoped_path_fault supports {_PATH_NAMES}, not {name!r}")
    root = Path(root).resolve()
    real = Path.__dict__[name]
    rec = ReplaceFaults()

    def _scoped(self, *a, **kw):
        if name in _PATH_DEST_ARG:
            scoped = a[0] if a else kw.get("target")
        else:
            scoped = self
        if scoped is not None and _path_in_scope(root, scoped):
            rec.attempts += 1
            return action(real, self, *a, **kw)
        return real(self, *a, **kw)

    setattr(Path, name, _scoped)
    try:
        _assert_path_control_delegates(name, root)
        yield rec
    finally:
        setattr(Path, name, real)

    if expect_fire and rec.attempts == 0:
        raise AssertionError(
            f"scoped_path_fault(Path.{name}, {root}) never saw an in-scope call - the test proved nothing"
        )
