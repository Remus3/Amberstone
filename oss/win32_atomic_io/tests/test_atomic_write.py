"""Writer tests: round-trip, parent creation, exact byte counts, no litter."""
from __future__ import annotations

import json
import os

import pytest

from win32_atomic_io import atomic_write_bytes, atomic_write_json, atomic_write_text
from win32_atomic_io import _atomic


def _names_in(directory):
    return sorted(p.name for p in directory.iterdir())


def test_atomic_write_json_round_trip(tmp_path):
    target = tmp_path / "payload.json"
    payload = {"mode": "a", "n": 3, "nested": {"list": [1, 2, 3]}}
    atomic_write_json(target, payload)
    assert json.loads(target.read_bytes().decode("utf-8")) == payload


def test_atomic_write_json_creates_parent_dirs(tmp_path):
    target = tmp_path / "deep" / "deeper" / "payload.json"
    atomic_write_json(target, {"ok": True})
    assert target.is_file()
    assert json.loads(target.read_bytes().decode("utf-8")) == {"ok": True}


def test_atomic_write_bytes_round_trip_and_parents(tmp_path):
    target = tmp_path / "made" / "blob.bin"
    data = b"\x00\x01\x02binary\xffpayload"
    atomic_write_bytes(target, data)
    assert target.read_bytes() == data


def test_atomic_write_text_round_trip_and_parents(tmp_path):
    target = tmp_path / "made" / "note.txt"
    atomic_write_text(target, "hello\nworld\n")
    assert target.read_bytes() == b"hello\nworld\n"


def test_atomic_write_text_byte_count_is_exact_with_newlines(tmp_path):
    """The CRLF trap: Path.write_text rewrites LF as CRLF on Windows, so the
    on-disk byte count diverges from what the caller serialized. Assert on
    BYTES, never on the round-tripped text - read_text hides the difference.
    """
    target = tmp_path / "lines.txt"
    content = "one\ntwo\nthree\n"
    atomic_write_text(target, content)
    raw = target.read_bytes()
    assert raw == content.encode("utf-8")
    assert len(raw) == len(content.encode("utf-8")) == 14
    assert raw.count(b"\r") == 0


def test_atomic_write_json_byte_count_is_exact_with_newlines(tmp_path):
    """An indented payload is full of newlines, so the same trap applies."""
    target = tmp_path / "indented.json"
    payload = {"a": 1, "b": [1, 2], "c": {"d": "e"}}
    atomic_write_json(target, payload)
    expected = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    raw = target.read_bytes()
    assert raw == expected
    assert len(raw) == len(expected)
    assert raw.count(b"\r") == 0


def test_atomic_write_json_honours_indent_kwarg(tmp_path):
    target = tmp_path / "flat.json"
    payload = {"a": 1}
    atomic_write_json(target, payload, indent=None)
    assert target.read_bytes() == json.dumps(payload, indent=None, ensure_ascii=False).encode("utf-8")


def test_overwrite_replaces_previous_content_entirely(tmp_path):
    target = tmp_path / "p.json"
    atomic_write_json(target, {"long": "x" * 500})
    atomic_write_json(target, {"short": 1})
    assert json.loads(target.read_bytes().decode("utf-8")) == {"short": 1}


def test_scratch_file_is_not_left_behind_when_the_write_raises(tmp_path, monkeypatch):
    """Exhausting the replace retries must re-raise AND remove the scratch
    file. A per-writer scratch name is never reused, so an orphan would be
    unbounded litter rather than a file the next write overwrites.
    """
    target = tmp_path / "victim.json"
    target.write_bytes(b"{}")
    monkeypatch.setattr(_atomic.time, "sleep", lambda _s: None)

    def _always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(_atomic.os, "replace", _always_denied)
    with pytest.raises(PermissionError):
        atomic_write_json(target, {"new": True})

    assert _names_in(tmp_path) == ["victim.json"]
    assert not any(p.suffix == ".tmp" for p in tmp_path.iterdir())
    assert target.read_bytes() == b"{}"


def test_scratch_file_is_not_left_behind_when_the_encode_write_raises(tmp_path, monkeypatch):
    target = tmp_path / "victim.bin"
    real_replace = os.replace

    def _boom(self, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(_atomic.Path, "write_bytes", _boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"data")
    assert list(tmp_path.iterdir()) == []
    assert os.replace is real_replace


def test_scratch_file_is_not_left_behind_on_keyboard_interrupt(tmp_path, monkeypatch):
    """BaseException, not Exception - a Ctrl-C mid-write must not litter."""
    target = tmp_path / "victim.bin"

    def _interrupt(src, dst):
        raise KeyboardInterrupt

    monkeypatch.setattr(_atomic.os, "replace", _interrupt)
    with pytest.raises(KeyboardInterrupt):
        atomic_write_bytes(target, b"data")
    assert list(tmp_path.iterdir()) == []
