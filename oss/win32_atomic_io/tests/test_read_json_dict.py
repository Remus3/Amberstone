"""read_json_dict tests: every degraded input yields the default, and the
default is handed back as a fresh DEEP copy."""
from __future__ import annotations

import threading

import pytest

from win32_atomic_io import atomic_write_json, read_json_dict


def test_missing_file_returns_default(tmp_path):
    assert read_json_dict(tmp_path / "nope.json", {"d": 1}) == {"d": 1}


def test_missing_file_with_no_default_returns_empty_dict(tmp_path):
    assert read_json_dict(tmp_path / "nope.json") == {}


def test_a_directory_returns_default(tmp_path):
    a_dir = tmp_path / "as_dir.json"
    a_dir.mkdir()
    assert read_json_dict(a_dir, {"d": 1}) == {"d": 1}


def test_non_utf8_bytes_return_default(tmp_path):
    """UnicodeDecodeError is a ValueError, NOT an OSError, so it needs its own
    handler - without one a corrupt file crashes the caller instead of
    yielding the default the contract promises."""
    target = tmp_path / "latin.json"
    target.write_bytes(b'{"k": "\xff\xfe not utf-8"}')
    assert read_json_dict(target, {"d": 1}) == {"d": 1}


def test_invalid_json_returns_default(tmp_path):
    target = tmp_path / "broken.json"
    target.write_bytes(b'{"half": ')
    assert read_json_dict(target, {"d": 1}) == {"d": 1}


def test_empty_file_returns_default(tmp_path):
    target = tmp_path / "empty.json"
    target.write_bytes(b"")
    assert read_json_dict(target, {"d": 1}) == {"d": 1}


@pytest.mark.parametrize(
    "body",
    [b"[1, 2, 3]", b'"a string"', b"42", b"3.5", b"null", b"true"],
    ids=["list", "string", "int", "float", "null", "bool"],
)
def test_valid_json_that_is_not_a_dict_returns_default(tmp_path, body):
    target = tmp_path / "notadict.json"
    target.write_bytes(body)
    assert read_json_dict(target, {"d": 1}) == {"d": 1}


def test_a_real_dict_is_returned_verbatim(tmp_path):
    target = tmp_path / "good.json"
    atomic_write_json(target, {"mode": "a", "n": [1, 2]})
    assert read_json_dict(target, {"d": 1}) == {"mode": "a", "n": [1, 2]}


def test_returned_default_is_a_deep_copy_not_an_alias(tmp_path):
    """A shallow dict(default) shares every nested mutable with the caller's
    own object AND with every later call, so appending to a returned
    {"log": []} silently poisons every subsequent read."""
    default = {"log": []}
    missing = tmp_path / "nope.json"

    first = read_json_dict(missing, default)
    first["log"].append("poison")

    second = read_json_dict(missing, default)
    assert second == {"log": []}
    assert default == {"log": []}
    assert first["log"] is not second["log"]
    assert first["log"] is not default["log"]


def test_deep_copy_reaches_nested_containers(tmp_path):
    default = {"a": {"b": {"c": [1]}}}
    got = read_json_dict(tmp_path / "nope.json", default)
    got["a"]["b"]["c"].append(2)
    assert default == {"a": {"b": {"c": [1]}}}


def test_uncopyable_default_raises_type_error(tmp_path):
    """Deliberate: deepcopy refuses a lock or a socket where the old shallow
    copy silently succeeded. This is a JSON module - such a default is a
    programming error, and surfacing it beats copying a live handle into what
    callers treat as inert data."""
    with pytest.raises(TypeError):
        read_json_dict(tmp_path / "nope.json", {"lock": threading.Lock()})


def test_uncopyable_default_raises_even_when_the_file_is_fine(tmp_path):
    """The copy happens before the read, so the error does not depend on the
    file being absent."""
    target = tmp_path / "good.json"
    atomic_write_json(target, {"ok": True})
    with pytest.raises(TypeError):
        read_json_dict(target, {"lock": threading.Lock()})


def test_empty_default_is_falsy_and_yields_a_fresh_dict(tmp_path):
    missing = tmp_path / "nope.json"
    a = read_json_dict(missing, {})
    b = read_json_dict(missing, {})
    a["x"] = 1
    assert b == {}
