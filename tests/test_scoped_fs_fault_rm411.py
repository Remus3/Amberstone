"""RM-411: tests/_replace_faults.scoped_fs_fault must hand back the REAL
os.replace / os.rename - the identical object - on a clean exit AND when the
body raises. A helper that leaks its shim turns a scoped fault into the very
process-wide patch it exists to prevent, for every later test in the process.

Each arm restores the real callable in its own ``finally`` BEFORE asserting,
so a leaking helper fails this test without corrupting the rest of the run.
"""

from __future__ import annotations

import os

import pytest

from tests._replace_faults import scoped_fs_fault


def _delegate(real, src, dst, *a, **kw):
    return real(src, dst, *a, **kw)


@pytest.mark.parametrize("name", ["replace", "rename"])
def test_real_callable_is_restored_after_a_clean_exit(tmp_path, name):
    real = getattr(os, name)
    try:
        with scoped_fs_fault(name, tmp_path, _delegate) as rec:
            assert getattr(os, name) is not real, "the shim was never installed"
            src, dst = tmp_path / "a.src", tmp_path / "a.dst"
            src.write_bytes(b"x")
            getattr(os, name)(src, dst)
        assert rec.attempts == 1
        after = getattr(os, name)
    finally:
        setattr(os, name, real)
    assert after is real


@pytest.mark.parametrize("name", ["replace", "rename"])
def test_real_callable_is_restored_after_the_body_raises(tmp_path, name):
    real = getattr(os, name)
    try:
        with pytest.raises(RuntimeError, match="body failed"):
            with scoped_fs_fault(name, tmp_path, _delegate):
                assert getattr(os, name) is not real, "the shim was never installed"
                raise RuntimeError("body failed")
        after = getattr(os, name)
    finally:
        setattr(os, name, real)
    assert after is real
