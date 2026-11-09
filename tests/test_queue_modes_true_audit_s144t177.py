"""Lane 8 true-audit s144t177: core/queue_modes.py input hardening.

Each test below was RED against the module as it stood before this cycle:

* F1 - ``int(float("inf"))`` raises OverflowError, which the resolver did not
  catch, so ``is_tft_context`` broke its own "Never raises" docstring. Python's
  ``json.loads`` turns ``1e400`` and ``Infinity`` into ``inf``, so any JSON
  feed (LCU, the file-ingest mirror) can deliver one.
* F2 - a non-integral float was truncated: ``450.5`` resolved to "aram" and
  ``map_id=22.9`` to the TFT board. A malformed id must be unmapped.
* F3 - ``int()``'s string grammar accepts ``"4_50"`` and non-ASCII digits, and
  ``int()`` accepts ``bytes``; none is a queue id an LCU payload carries.
* F4 - ``QUEUE_ID_TO_MODE_KEY`` was a plain dict every importer shared, so one
  stray write re-routed every caller's pre-game flip. It is read-only now.
* F5 - the module docstring listed the return keys without "jade" and called
  the Brawl backend deadcode, which the CLAUDE.md Settled line forbids
  (brawl_coach.py is live-reachable: "unexercised, not unreachable").
"""
from __future__ import annotations

import enum
import json
import numbers

import pytest

from core import queue_modes as qm


# ----------------------------------------------------------------- F1 inf

@pytest.mark.parametrize("value", [
    float("inf"), float("-inf"), json.loads("1e400"), json.loads("Infinity"),
])
def test_infinite_queue_id_is_unmapped_not_an_overflow(value):
    assert qm.mode_key_from_queue_id(value) is None
    assert qm.is_tft_queue(value) is False
    assert qm.is_tft_context(queue_id=value) is False


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_is_tft_context_never_raises_on_a_non_finite_map_id(value):
    assert qm.is_tft_context(map_id=value) is False


def test_non_finite_map_id_does_not_hide_a_real_tft_signal():
    assert qm.is_tft_context(queue_id=1100, map_id=float("inf")) is True
    assert qm.is_tft_context(game_mode="TFT", map_id=float("inf")) is True


# --------------------------------------------------- F2 fractional floats

@pytest.mark.parametrize("value", [450.5, 1750.9, 420.000001, 1100.5])
def test_non_integral_float_queue_id_is_unmapped(value):
    assert qm.mode_key_from_queue_id(value) is None
    assert qm.is_tft_queue(value) is False


def test_non_integral_float_map_id_is_not_the_tft_board():
    assert qm.is_tft_context(map_id=22.9) is False
    assert qm.is_tft_context(map_id=21.5) is False


def test_integral_float_still_resolves():
    # JSON round-trips can turn 450 into 450.0; that is still queue 450.
    assert qm.mode_key_from_queue_id(450.0) == "aram"
    assert qm.is_tft_context(map_id=22.0) is True


# ------------------------------------------------- F3 string / bytes grammar

@pytest.mark.parametrize("value", [
    "4_50", "1_100",
    chr(0x0664) + chr(0x0665) + chr(0x0660),  # Arabic-Indic 450
    chr(0xFF14) + chr(0xFF15) + chr(0xFF10),  # fullwidth 450
    "450.0", "",
    "   ", "0x1c2",
])
def test_non_decimal_ascii_strings_are_unmapped(value):
    assert qm.mode_key_from_queue_id(value) is None


def test_overlong_digit_string_is_unmapped_not_a_value_error():
    # int() refuses strings past the 4300-digit limit with ValueError; the
    # pre-audit try/except caught it, so the stricter grammar must too.
    assert qm.mode_key_from_queue_id("1" * 5000) is None
    assert qm.is_tft_queue("9" * 4301) is False
    assert qm.is_tft_context(map_id="9" * 4301) is False


def test_underscore_string_map_id_is_not_the_tft_board():
    assert qm.is_tft_context(map_id="2_2") is False


@pytest.mark.parametrize("value", [b"450", bytearray(b"1100"), memoryview(b"1750")])
def test_bytes_like_queue_id_is_unmapped(value):
    assert qm.mode_key_from_queue_id(value) is None


def test_plain_decimal_strings_still_coerce():
    assert qm.mode_key_from_queue_id(" 450 ") == "aram"
    assert qm.mode_key_from_queue_id("+1750") == "arena"
    assert qm.mode_key_from_queue_id("1100\n") == "tft"
    assert qm.is_tft_context(map_id="22") is True


def test_int_subclasses_still_resolve():
    class Q(enum.IntEnum):
        ARAM = 450

    assert qm.mode_key_from_queue_id(Q.ARAM) == "aram"


@pytest.mark.parametrize("value", [object(), [450], {"id": 450}, (1100,)])
def test_unrelated_types_are_unmapped(value):
    assert qm.mode_key_from_queue_id(value) is None
    assert qm.is_tft_context(queue_id=value, map_id=value) is False


# ------------------------------------ F6 subclass overrides are never run

class _RaisingStr(str):
    __slots__ = ()

    def strip(self, *a):
        raise RuntimeError("strip")

    def upper(self):
        raise RuntimeError("upper")


class _RaisingFloat(float):
    def is_integer(self):
        raise RuntimeError("is_integer")

    def __int__(self):
        raise RuntimeError("__int__")


class _RaisingInt(int):
    def __int__(self):
        raise RuntimeError("__int__")


@pytest.mark.parametrize("value, expected", [
    (_RaisingStr("450"), "aram"),
    (_RaisingFloat(450.0), "aram"),
    (_RaisingFloat(450.5), None),
    (_RaisingInt(1100), "tft"),
])
def test_builtin_subclass_overrides_never_escape(value, expected):
    assert qm.mode_key_from_queue_id(value) == expected
    assert qm.is_tft_context(map_id=value) is False


class _NumpyLikeInt:
    """A non-int Integral (the numpy integer shape), registered below."""

    def __init__(self, value, exc=None):
        self.value, self.exc = value, exc

    def __int__(self):
        if self.exc is not None:
            raise self.exc
        return self.value


numbers.Integral.register(_NumpyLikeInt)


def test_registered_integral_resolves_and_its_expected_failures_are_caught():
    assert qm.mode_key_from_queue_id(_NumpyLikeInt(1750)) == "arena"
    assert qm.is_tft_context(map_id=_NumpyLikeInt(22)) is True
    for exc in (TypeError("t"), ValueError("v"), OverflowError("o")):
        assert qm.mode_key_from_queue_id(_NumpyLikeInt(450, exc)) is None


def test_tft_game_mode_str_subclass_is_read_through_base_methods():
    assert qm.is_tft_game_mode(_RaisingStr(" tft ")) is True
    assert qm.is_tft_context(game_mode=_RaisingStr("CLASSIC")) is False


class _RaisingBool:
    def __bool__(self):
        raise RuntimeError("__bool__")

    def __str__(self):
        raise RuntimeError("__str__")


@pytest.mark.parametrize("value", [_RaisingBool(), 10 ** 5000, b"TFT", 0, None],
                         ids=["raising-dunders", "5001-digit-int", "bytes", "zero", "none"])
def test_non_str_game_mode_is_not_tft_and_never_raises(value):
    assert qm.is_tft_game_mode(value) is False
    assert qm.is_tft_context(game_mode=value) is False


# ----------------------------------------------------------- F4 read-only

def test_queue_map_is_read_only():
    with pytest.raises(TypeError):
        qm.QUEUE_ID_TO_MODE_KEY[1] = "sr"  # type: ignore[index]
    assert 1 not in qm.QUEUE_ID_TO_MODE_KEY
    assert qm.QUEUE_ID_TO_MODE_KEY.get(450) == "aram"
    assert dict(qm.QUEUE_ID_TO_MODE_KEY)[1100] == "tft"


# ------------------------------------------------------------- F5 docstring

def test_module_docstring_names_every_mode_key_the_map_returns():
    doc = qm.__doc__ or ""
    for mode_key in sorted(set(qm.QUEUE_ID_TO_MODE_KEY.values())):
        assert f"`{mode_key}`" in doc, mode_key


def test_module_docstring_does_not_call_the_brawl_backend_dead():
    assert "deadcode" not in (qm.__doc__ or "").lower()
