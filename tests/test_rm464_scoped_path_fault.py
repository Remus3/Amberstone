"""RM-464: tests/_replace_faults.scoped_path_fault - the pathlib sibling of
RM-411's scoped_fs_fault.

``monkeypatch.setattr(Path, "unlink", boom)`` patches the CLASS, so every
``Path`` instance in the process - every thread, every library - hits the
fault while it is armed. ``scoped_path_fault`` runs the action only for a path
at or under ``root`` and delegates everything else, and proves that on entry
with a CONTROL call outside ``root`` inside the armed window.

These tests pin: the fault bites in scope, the real method runs out of scope,
the real method object is restored on a clean exit and on a raising body, the
control is armed (an unconditional shim fails on entry), and a helper that
never saw an in-scope call fails loudly unless ``expect_fire=False``.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

import tests._replace_faults as rf
from tests._replace_faults import scoped_path_fault

_NAMES = ["unlink", "replace", "rename", "mkdir", "write_bytes", "write_text"]


def _deny(real, path, *a, **kw):
    raise PermissionError(13, "injected", str(path))


def _exercise(name: str, base: Path) -> Path:
    """Perform one ``name`` operation whose SCOPED path lies in ``base``."""
    if name == "unlink":
        p = base / "victim"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(b"x")
        p.unlink()
        return p
    if name in ("replace", "rename"):
        # The source sits beside the destination: scope is decided by the
        # DESTINATION alone, and a same-directory move is portable.
        src = base / "src"
        base.mkdir(parents=True, exist_ok=True)
        with open(src, "wb") as fh:
            fh.write(b"x")
        dst = base / "moved"
        getattr(src, name)(dst)
        return dst
    if name == "mkdir":
        p = base / "newdir"
        p.mkdir()
        return p
    if name == "write_bytes":
        p = base / "b.bin"
        p.write_bytes(b"x")
        return p
    p = base / "t.txt"
    p.write_text("x", encoding="utf-8")
    return p


@pytest.mark.parametrize("name", _NAMES)
def test_fault_bites_in_scope_and_delegates_outside(tmp_path, name):
    real = getattr(Path, name)
    outside = Path(tempfile.mkdtemp(prefix="rm464_outside_"))
    try:
        with scoped_path_fault(name, tmp_path, _deny) as rec:
            assert getattr(Path, name) is not real, "the shim was never installed"
            with pytest.raises(PermissionError, match="injected"):
                _exercise(name, tmp_path)
            assert rec.attempts == 1
            done = _exercise(name, outside)  # must NOT raise: out of scope
            assert rec.attempts == 1, "an out-of-scope call was counted as in scope"
            if name == "unlink":
                assert not done.exists(), "the out-of-scope unlink did not really run"
            else:
                assert done.exists(), f"the out-of-scope {name} did not really run"
        after = getattr(Path, name)
    finally:
        setattr(Path, name, real)
        shutil.rmtree(outside, ignore_errors=True)
    assert after is real


@pytest.mark.parametrize("name", _NAMES)
def test_real_method_is_restored_after_the_body_raises(tmp_path, name):
    real = getattr(Path, name)
    try:
        with pytest.raises(RuntimeError, match="body failed"):
            with scoped_path_fault(name, tmp_path, _deny):
                raise RuntimeError("body failed")
        after = getattr(Path, name)
    finally:
        setattr(Path, name, real)
    assert after is real


@pytest.mark.parametrize("name", _NAMES)
def test_control_is_armed_against_an_unconditional_shim(tmp_path, name, monkeypatch):
    """Mutation arm: make every call look in scope and the entry control must
    fail - that is the only thing standing between this helper and the
    process-wide patch it replaces."""
    real = getattr(Path, name)
    monkeypatch.setattr(rf, "_path_in_scope", lambda root, p: True)
    try:
        with pytest.raises(AssertionError, match="did not delegate"):
            with scoped_path_fault(name, tmp_path, _deny):
                pass
        after = getattr(Path, name)
    finally:
        setattr(Path, name, real)
    assert after is real


def test_never_fired_is_loud_by_default(tmp_path):
    with pytest.raises(AssertionError, match="never saw an in-scope call"):
        with scoped_path_fault("unlink", tmp_path, _deny):
            pass


def test_expect_fire_false_allows_zero_in_scope_calls(tmp_path):
    with scoped_path_fault("unlink", tmp_path, _deny, expect_fire=False) as rec:
        pass
    assert rec.attempts == 0


def test_unknown_name_is_refused(tmp_path):
    with pytest.raises(ValueError):
        with scoped_path_fault("chmod", tmp_path, _deny):
            pass
