"""s144 true-audit - hardening of agents/_minimap_bbox.py.

Each test names the weakness it pins. The resolver backs the live
/api/minimap-crop route (agents/_supervisor_http.py `_handle_minimap_crop`),
which the dashboard polls every ~2 s through the :8888 proxy, so a raise
escapes the route's try blocks and a per-call warning floods the log.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from agents import _minimap_bbox as mb  # noqa: E402

_FALLBACK = (1565, 735, 1905, 1075)


@pytest.fixture
def regions(tmp_path, monkeypatch):
    path = tmp_path / "vision_regions.json"
    monkeypatch.setattr(mb, "_REGIONS_FILE", path)
    mb._reset_warnings()
    yield path
    mb._reset_warnings()


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


# -- load_persisted: entries Python's json accepts but int() cannot ---------

@pytest.mark.parametrize("token", ["Infinity", "-Infinity", "NaN"])
def test_non_finite_entry_falls_back_instead_of_raising(regions, token):
    # json.loads accepts Infinity / NaN; int(inf) raised OverflowError, which
    # the old (TypeError, ValueError) catch missed - the raise escaped
    # resolve() and the route, which calls it outside any try.
    _write(regions, '{"_minimap_sr": [0, 0, ' + token + ', 100]}')
    assert mb.load_persisted("sr") is None
    assert mb.resolve("sr") == _FALLBACK


# -- load_persisted: the [0, 10000] range the HTTP override enforces --------

@pytest.mark.parametrize("entry", [
    [0, 0, 100000, 100000],     # PIL would allocate a 10^10-pixel crop
    [-50, 0, 100, 100],         # negative coord
    [0, 0, 10001, 100],         # one over the limit
])
def test_out_of_range_persisted_entry_falls_back(regions, entry):
    _write(regions, json.dumps({"_minimap_sr": entry}))
    assert mb.load_persisted("sr") is None
    assert mb.resolve("sr") == _FALLBACK


def test_persisted_entry_at_range_limits_is_kept(regions):
    _write(regions, json.dumps({"_minimap_sr": [0, 0, 10000, 10000]}))
    assert mb.load_persisted("sr") == (0, 0, 10000, 10000)


# -- load_persisted: values int() silently mangled ---------------------------

def test_bool_entry_is_rejected(regions):
    # bool is an int subclass: [false, false, true, true] became (0, 0, 1, 1).
    _write(regions, '{"_minimap_sr": [false, false, true, true]}')
    assert mb.load_persisted("sr") is None


def test_fractional_float_entry_is_rejected_not_truncated(regions):
    # int(1565.9) == 1565 silently moved the box.
    _write(regions, json.dumps({"_minimap_sr": [10.5, 20, 30, 40]}))
    assert mb.load_persisted("sr") is None


def test_integral_float_entry_is_kept(regions):
    _write(regions, json.dumps({"_minimap_sr": [10.0, 20.0, 30.0, 40.0]}))
    result = mb.load_persisted("sr")
    assert result == (10, 20, 30, 40)
    assert all(type(v) is int for v in result)


@pytest.mark.parametrize("bad", ["1_0", " 10", "+10", "\u0661\u0660", "1e1"])
def test_non_plain_digit_string_entry_is_rejected(regions, bad):
    _write(regions, json.dumps({"_minimap_sr": [bad, 20, 30, 40]}))
    assert mb.load_persisted("sr") is None


# -- load_persisted: file encodings and read errors -------------------------

def test_utf8_bom_file_is_read(regions):
    # A file saved by PowerShell 5.1 `Set-Content -Encoding UTF8` (or an
    # editor) carries a BOM; json.loads raised on it and the calibration was
    # silently ignored.
    regions.write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"_minimap_sr": [10, 20, 30, 40]}).encode()
    )
    assert mb.load_persisted("sr") == (10, 20, 30, 40)


def test_regions_path_is_a_directory_falls_back(regions):
    regions.mkdir()
    assert mb.load_persisted("sr") is None
    assert mb.resolve("sr") == _FALLBACK


def test_deeply_nested_json_falls_back(regions):
    _write(regions, "[" * 200000 + "]" * 200000)
    assert mb.load_persisted("sr") is None


def test_unexpected_exception_type_is_not_swallowed(regions, monkeypatch):
    # The read guard catches the read / decode / parse errors it expects; a
    # caller bug (here a stand-in TypeError from the parser) must surface,
    # not be logged as "read failed" and served as the fallback.
    _write(regions, "{}")

    def boom(*_a, **_k):
        raise TypeError("caller bug")

    monkeypatch.setattr(mb.json, "loads", boom)
    with pytest.raises(TypeError):
        mb.load_persisted("sr")


# -- warnings are deduplicated (the route is polled every ~2 s) -------------

def test_malformed_file_warning_logged_once_per_distinct_message(regions, caplog):
    _write(regions, "{not json")
    with caplog.at_level(logging.WARNING, logger="rc.minimap_bbox"):
        for _ in range(5):
            assert mb.resolve("sr") == _FALLBACK
    assert len([r for r in caplog.records if r.name == "rc.minimap_bbox"]) == 1


def test_bad_entry_warning_logged_once(regions, caplog):
    _write(regions, json.dumps({"_minimap_sr": [50, 0, 10, 100]}))
    with caplog.at_level(logging.WARNING, logger="rc.minimap_bbox"):
        for _ in range(5):
            mb.resolve("sr")
    assert len([r for r in caplog.records if r.name == "rc.minimap_bbox"]) == 1


def test_non_object_top_level_warning_logged_once(regions, caplog):
    # Verifier catch: the file slot was cleared just before the non-object
    # check re-armed it, so this case logged on every poll.
    _write(regions, "[1, 2]")
    with caplog.at_level(logging.WARNING, logger="rc.minimap_bbox"):
        for _ in range(5):
            assert mb.resolve("sr") == _FALLBACK
    assert len([r for r in caplog.records if r.name == "rc.minimap_bbox"]) == 1


def test_warning_relogged_after_a_good_read(regions, caplog):
    with caplog.at_level(logging.WARNING, logger="rc.minimap_bbox"):
        _write(regions, "{not json")
        mb.resolve("sr")
        _write(regions, json.dumps({"_minimap_sr": [10, 20, 30, 40]}))
        assert mb.resolve("sr") == (10, 20, 30, 40)
        _write(regions, "{not json")
        mb.resolve("sr")
    assert len([r for r in caplog.records if r.name == "rc.minimap_bbox"]) == 2


def test_bad_entry_warning_is_bounded(regions, caplog):
    _write(regions, json.dumps({"_minimap_sr": ["x" * 50000, 0, 10, 10]}))
    with caplog.at_level(logging.WARNING, logger="rc.minimap_bbox"):
        assert mb.load_persisted("sr") is None
    msgs = [r.getMessage() for r in caplog.records if r.name == "rc.minimap_bbox"]
    assert msgs and all(len(m) < 400 for m in msgs)


@pytest.mark.parametrize("big", [10 ** 200, 10 ** 4000])
def test_out_of_range_huge_int_warning_is_bounded(regions, caplog, big):
    # Verifier catch: the range error carried the whole coerced tuple, and
    # JSON lets an int run to thousands of digits.
    _write(regions, json.dumps({"_minimap_sr": [0, 0, big, big]}))
    with caplog.at_level(logging.WARNING, logger="rc.minimap_bbox"):
        assert mb.load_persisted("sr") is None
    msgs = [r.getMessage() for r in caplog.records if r.name == "rc.minimap_bbox"]
    assert msgs and all(len(m) < 400 for m in msgs)


# -- resolve: junk mode values ----------------------------------------------

@pytest.mark.parametrize("mode", [5, 1.0, ["sr"], {"sr": 1}, b"sr"])
def test_non_str_mode_returns_none(regions, mode):
    assert mb.resolve(mode) is None


def test_mode_surrounding_whitespace_is_ignored(regions):
    assert mb.resolve(" sr ") == _FALLBACK


# -- parse_http_override: strict, bounded parse -----------------------------

@pytest.mark.parametrize("raw", [
    "1_0,0,100,100",            # int() accepted the underscore form
    "+1,0,100,100",             # and a sign
    "\u0661,0,100,100",         # and non-ASCII digits
    "1,2,3",                    # too few
    "",                         # empty
    ",,,",                      # empty parts
])
def test_http_override_rejects_non_plain_digits(raw):
    with pytest.raises(ValueError):
        mb.parse_http_override(raw)


def test_http_override_checks_arity_before_converting(monkeypatch):
    # A query string of tens of thousands of parts was converted part by part
    # before the length check; the arity check now runs first.
    calls = []
    real_int = int

    def counting_int(v, *a):
        calls.append(v)
        return real_int(v, *a)

    monkeypatch.setattr(mb, "int", counting_int, raising=False)
    with pytest.raises(ValueError):
        mb.parse_http_override(",".join(["1"] * 20000))
    assert len(calls) == 0


@pytest.mark.parametrize("raw", [None, 5, b"0,0,1,1", ["0", "0", "1", "1"]])
def test_http_override_non_str_raises_value_error(raw):
    # The route maps ValueError to a 400; any other type escaped as a 500.
    with pytest.raises(ValueError):
        mb.parse_http_override(raw)


def test_http_override_tolerates_space_after_comma():
    assert mb.parse_http_override("10, 20, 30, 40") == (10, 20, 30, 40)
