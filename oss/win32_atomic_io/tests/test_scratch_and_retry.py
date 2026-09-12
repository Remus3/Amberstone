"""Scratch-name and replace-retry tests - the two win32-specific behaviours."""
from __future__ import annotations

from pathlib import Path

import pytest

from win32_atomic_io import _atomic
from win32_atomic_io._atomic import _REPLACE_RETRY_DELAYS_S, _replace_with_retry, _scratch_path


def test_scratch_path_is_distinct_per_call(tmp_path):
    """A name derived from the destination ALONE gives every writer of a file
    the SAME scratch file. Two concurrent writers then interleave: B truncates
    and renames the scratch while A is still filling it, and A's leftover
    bytes land in the published destination."""
    dest = tmp_path / "shared.json"
    names = {_scratch_path(dest).name for _ in range(64)}
    assert len(names) == 64


def test_scratch_path_is_a_sibling_of_the_destination(tmp_path):
    """os.replace is only atomic within one filesystem, so the scratch file
    has to live in the destination's own directory."""
    dest = tmp_path / "sub" / "shared.json"
    scratch = _scratch_path(dest)
    assert scratch.parent == dest.parent
    assert scratch.name != dest.name
    assert scratch.name.startswith(dest.name + ".")
    assert scratch.suffix == ".tmp"


def test_scratch_path_carries_the_process_id(tmp_path):
    """Separate PROCESSES are exactly the case no in-process lock can
    serialize, so the pid is part of the name."""
    import os

    dest = tmp_path / "shared.json"
    assert f".{os.getpid()}." in _scratch_path(dest).name


def test_replace_with_retry_succeeds_on_a_later_attempt(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.write_bytes(b"payload")
    calls = {"n": 0}
    slept = []
    monkeypatch.setattr(_atomic.time, "sleep", lambda s: slept.append(s))
    real_replace = _atomic.os.replace

    def _flaky(a, b):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "Access is denied")
        return real_replace(a, b)

    monkeypatch.setattr(_atomic.os, "replace", _flaky)
    _replace_with_retry(src, dst)

    assert calls["n"] == 3
    assert dst.read_bytes() == b"payload"
    assert not src.exists()
    assert slept == list(_REPLACE_RETRY_DELAYS_S[:2])


def test_replace_with_retry_succeeds_on_the_very_last_attempt(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.write_bytes(b"payload")
    calls = {"n": 0}
    monkeypatch.setattr(_atomic.time, "sleep", lambda _s: None)
    real_replace = _atomic.os.replace
    attempts = len(_REPLACE_RETRY_DELAYS_S)

    def _flaky(a, b):
        calls["n"] += 1
        if calls["n"] <= attempts:
            raise PermissionError(5, "Access is denied")
        return real_replace(a, b)

    monkeypatch.setattr(_atomic.os, "replace", _flaky)
    _replace_with_retry(src, dst)
    assert calls["n"] == attempts + 1
    assert dst.read_bytes() == b"payload"


def test_replace_with_retry_reraises_once_the_delays_are_exhausted(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.write_bytes(b"payload")
    calls = {"n": 0}
    slept = []
    monkeypatch.setattr(_atomic.time, "sleep", lambda s: slept.append(s))

    def _always_denied(a, b):
        calls["n"] += 1
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(_atomic.os, "replace", _always_denied)
    with pytest.raises(PermissionError):
        _replace_with_retry(src, dst)

    assert calls["n"] == len(_REPLACE_RETRY_DELAYS_S) + 1
    assert slept == list(_REPLACE_RETRY_DELAYS_S)
    assert not dst.exists()


def test_replace_with_retry_does_not_swallow_other_oserrors(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    calls = {"n": 0}

    def _enoent(a, b):
        calls["n"] += 1
        raise FileNotFoundError(2, "No such file")

    monkeypatch.setattr(_atomic.os, "replace", _enoent)
    with pytest.raises(FileNotFoundError):
        _replace_with_retry(src, dst)
    assert calls["n"] == 1


def test_retry_delays_are_a_bounded_ascending_tuple():
    assert isinstance(_REPLACE_RETRY_DELAYS_S, tuple)
    assert len(_REPLACE_RETRY_DELAYS_S) >= 1
    assert all(isinstance(d, (int, float)) and d > 0 for d in _REPLACE_RETRY_DELAYS_S)
    assert list(_REPLACE_RETRY_DELAYS_S) == sorted(_REPLACE_RETRY_DELAYS_S)
    assert sum(_REPLACE_RETRY_DELAYS_S) < 1.0


def test_scratch_path_accepts_a_plain_path_object(tmp_path):
    assert isinstance(_scratch_path(Path(tmp_path / "x.json")), Path)
