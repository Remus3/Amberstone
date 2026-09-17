"""Scoped fault injection for this package's own tests. Stdlib only.

WHY THE INJECTORS HAVE TO BE SCOPED. ``monkeypatch.setattr(_atomic.os,
"replace", boom)`` READS like containment and is not: ``_atomic.os`` is a
reference to the ONE stdlib ``os`` module object every importer in the process
shares, so ``setattr`` on it is identical in blast radius to patching ``os``
itself. While the patch is armed, every other caller in the process hits
``boom`` - a background thread above all. The same holds one layer up for
``_atomic.Path.write_bytes`` (a CLASS attribute, so every ``Path`` instance in
the process) and for ``_atomic.time.sleep`` (a fake that returns instantly
turns another thread's sleep into a busy-spin).

WHY THIS FILE IS LOCAL RATHER THAN AN IMPORT. The surrounding repository has an
equivalent helper under its own top-level ``tests/`` package. This package is
deliberately self-contained - its own LICENSE, its own pyproject, no
dependencies, runnable from a copy of THIS DIRECTORY ALONE - and an import
reaching up out of the package tree would quietly break that property: a
consumer who vendors the directory would get a test suite that cannot import.
So it grows its own small, stdlib-only version. It is an independent
implementation, not a mirror, and nothing pins the two to each other; do not
add such a pin, and do not "fix" a divergence in only one of them.

Every injector here does two things a hand-rolled shim does not:

  * it SCOPES on a path, delegating every out-of-scope call to the real
    callable captured before patching, and PROVES that delegation with a
    control call in a fresh directory outside the scope, run from INSIDE the
    armed window - make the shim unconditional and the control fails first;
  * it asserts on clean exit that at least one in-scope call happened, so a
    mistyped root cannot leave a green test that injected nothing.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

__all__ = ["FaultRecord", "record_sleeps", "scoped_os_fault", "scoped_path_fault"]

_CONTROL_PAYLOAD = b"scoped-fault-control"


class FaultRecord:
    """Call record for an armed injector: in-scope calls seen."""

    __slots__ = ("attempts",)

    def __init__(self) -> None:
        self.attempts = 0

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"<FaultRecord attempts={self.attempts}>"


def _under(root: Path, candidate) -> bool:
    try:
        resolved = Path(os.fspath(candidate)).resolve()
    except TypeError:  # an fd or similar - never ours
        return False
    return resolved == root or root in resolved.parents


def _raw_write(p: Path, data: bytes) -> None:
    with open(p, "wb") as fh:  # builtins.open, never a Path method under test
        fh.write(data)


def _raw_read(p: Path) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


@contextmanager
def _control_dir(root: Path, prefix: str):
    control = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        if _under(root, control):
            raise AssertionError(
                f"control dir {control} is under {root}; it proves nothing")
        yield control
    finally:
        shutil.rmtree(control, ignore_errors=True)


@contextmanager
def scoped_os_fault(os_mod, name, root, action, *, expect_fire=True):
    """Patch ``os_mod.<name>`` so ``action(real, src, dst, ...)`` runs only when
    the DESTINATION resolves at or under ``root``; delegate everything else.

    ``name`` is ``"replace"`` or ``"rename"``. Yields a :class:`FaultRecord`
    counting in-scope calls.
    """
    if name not in ("replace", "rename"):
        raise ValueError(f"scoped_os_fault supports replace / rename, not {name!r}")
    root = Path(root).resolve()
    real = getattr(os_mod, name)
    rec = FaultRecord()

    def _scoped(src, dst, *a, **kw):
        if _under(root, dst):
            rec.attempts += 1
            return action(real, src, dst, *a, **kw)
        return real(src, dst, *a, **kw)

    setattr(os_mod, name, _scoped)
    try:
        with _control_dir(root, "scoped_os_control_") as control:
            src, dst = control / "control.src", control / "control.dst"
            _raw_write(src, _CONTROL_PAYLOAD)
            try:
                getattr(os_mod, name)(src, dst)  # through the PATCHED name
                ok = not os.path.lexists(src) and _raw_read(dst) == _CONTROL_PAYLOAD
            except Exception as exc:
                raise AssertionError(
                    f"os.{name} outside {root} did not delegate to the real "
                    f"call: {exc!r}") from exc
            if not ok:
                raise AssertionError(
                    f"os.{name} outside {root} did not delegate to the real call")
        yield rec
    finally:
        setattr(os_mod, name, real)

    if expect_fire and rec.attempts == 0:
        raise AssertionError(
            f"scoped_os_fault(os.{name}, {root}) never saw an in-scope call - "
            f"the test proved nothing")


@contextmanager
def scoped_path_fault(path_cls, name, root, action, *, expect_fire=True):
    """Patch ``Path.<name>`` so ``action(real, self, *a, **kw)`` runs only when
    ``self`` resolves at or under ``root``; delegate everything else.

    ``name`` is ``"write_bytes"`` or ``"write_text"``. Yields a
    :class:`FaultRecord` counting in-scope calls.
    """
    if name not in ("write_bytes", "write_text"):
        raise ValueError(
            f"scoped_path_fault supports write_bytes / write_text, not {name!r}")
    root = Path(root).resolve()
    real = path_cls.__dict__[name]
    rec = FaultRecord()

    def _scoped(self, *a, **kw):
        if _under(root, self):
            rec.attempts += 1
            return action(real, self, *a, **kw)
        return real(self, *a, **kw)

    setattr(path_cls, name, _scoped)
    try:
        with _control_dir(root, "scoped_path_control_") as control:
            try:
                if name == "write_bytes":
                    p = control / "control.bin"
                    p.write_bytes(_CONTROL_PAYLOAD)  # through the PATCHED name
                else:
                    p = control / "control.txt"
                    p.write_text(_CONTROL_PAYLOAD.decode("ascii"), encoding="ascii")
                ok = _raw_read(p) == _CONTROL_PAYLOAD
            except Exception as exc:
                raise AssertionError(
                    f"Path.{name} outside {root} did not delegate to the real "
                    f"method: {exc!r}") from exc
            if not ok:
                raise AssertionError(
                    f"Path.{name} outside {root} did not delegate to the real method")
        yield rec
    finally:
        setattr(path_cls, name, real)

    if expect_fire and rec.attempts == 0:
        raise AssertionError(
            f"scoped_path_fault(Path.{name}, {root}) never saw an in-scope call "
            f"- the test proved nothing")


@contextmanager
def record_sleeps(time_mod):
    """Record ``time_mod.sleep`` durations from the CALLING thread only.

    ``time_mod`` is the one global ``time`` module however it is spelled, so
    the patch cannot be narrowed - but it CAN be made honest. Calls from the
    thread that opened the context are recorded and return immediately (the
    test stays fast); calls from any other thread pass through to the real
    ``time.sleep``, so their timing is undisturbed and they never enter the
    recorded list.

    Prefer asserting the recorded VALUES over a bare count - it pins the
    backoff schedule as well as the retry count, at no cost.
    """
    recorded: list = []
    owner = threading.get_ident()
    real = time_mod.sleep

    def probe(seconds=0.0):
        if threading.get_ident() == owner:
            recorded.append(seconds)
            return None
        return real(seconds)

    time_mod.sleep = probe
    try:
        yield recorded
    finally:
        time_mod.sleep = real
