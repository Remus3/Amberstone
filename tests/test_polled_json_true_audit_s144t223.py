"""Lane 8 (true-audit) s144 cycle 223 - core/polled_json.py read and write
contracts, mirrored in oss/win32_atomic_io (the drift guard
tests/test_oss_win32_atomic_io_drift.py pins the two copies together).

  S144-T223-A  read_json_dict caught only JSONDecodeError around json.loads.
               The stdlib decoder also raises RecursionError (nesting past the
               interpreter stack) and a plain ValueError (an integer literal
               past sys.get_int_max_str_digits()), so a polled file of either
               shape crashed the caller instead of yielding the default the
               docstring promises.
  S144-T223-B  atomic_write_json encoded an ensure_ascii=False dump as UTF-8,
               which raises UnicodeEncodeError on a lone surrogate - exactly
               what json.loads yields for an escaped "\\ud800" - so a
               read-modify-write of such a file crashed the writer. The
               fallback re-serializes with ensure_ascii=True (valid, lossless,
               pure ASCII); every payload that encoded before writes the same
               bytes as before.
"""
from __future__ import annotations

import json

import pytest

from core import polled_json
from core.polled_json import atomic_write_json, read_json_dict


def test_nesting_too_deep_for_the_decoder_returns_default(tmp_path, caplog):
    target = tmp_path / "deep.json"
    depth = 200_000
    target.write_bytes(('{"a": ' + "[" * depth + "]" * depth + "}").encode("ascii"))
    with caplog.at_level("WARNING", logger="rc.polled_json"):
        assert read_json_dict(target, {"d": 1}) == {"d": 1}
    assert "decode failed" in caplog.text


def test_integer_literal_past_the_digit_limit_returns_default(tmp_path, caplog):
    target = tmp_path / "bigint.json"
    target.write_bytes(('{"a": 1' + "0" * 5000 + "}").encode("ascii"))
    with caplog.at_level("WARNING", logger="rc.polled_json"):
        assert read_json_dict(target, {"d": 1}) == {"d": 1}
    assert "decode failed" in caplog.text


def test_a_reader_error_that_is_not_a_parse_failure_still_raises(tmp_path, monkeypatch):
    target = tmp_path / "ok.json"
    target.write_bytes(b'{"a": 1}')

    def _boom(_raw):
        raise KeyError("not a parse failure")

    monkeypatch.setattr(polled_json.json, "loads", _boom)
    with pytest.raises(KeyError):
        read_json_dict(target, {"d": 1})


def test_read_modify_write_of_an_escaped_lone_surrogate_round_trips(tmp_path):
    target = tmp_path / "surrogate.json"
    target.write_bytes(b'{"name": "a\\ud800b"}')
    data = read_json_dict(target)
    assert data == {"name": "a\ud800b"}
    data["n"] = 1
    atomic_write_json(target, data)
    raw = target.read_bytes()
    raw.decode("ascii")
    assert read_json_dict(target) == {"name": "a\ud800b", "n": 1}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["surrogate.json"]


def test_encodable_payload_bytes_are_unchanged(tmp_path):
    target = tmp_path / "accent.json"
    payload = {"name": "caf\u00e9", "list": [1, 2]}
    atomic_write_json(target, payload)
    assert target.read_bytes() == json.dumps(
        payload, indent=2, ensure_ascii=False
    ).encode("utf-8")


def test_surrogate_fallback_honours_indent(tmp_path):
    target = tmp_path / "surrogate_indent.json"
    payload = {"a": "\ud800", "b": [1]}
    atomic_write_json(target, payload, indent=4)
    assert target.read_bytes() == json.dumps(
        payload, indent=4, ensure_ascii=True
    ).encode("ascii")
