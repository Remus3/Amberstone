"""Lane 8 true-audit of ``core/liveclient_coerce.py`` (s144, RM-1042).

The module's contract is that ``as_list`` never raises and reads anything
that is not a list or a cleanly integer-keyed dict as ``[]``. Three ways the
foreign ``:2999`` payload broke that contract, each pinned here:

* a dict key of more than 4300 ASCII digits made ``int(k)`` raise
  ``ValueError`` (the interpreter's int-string limit), which escaped into
  ``game_reader/snapshot_normalizer.py`` ``_process_game`` and voided the
  whole tick;
* two keys naming the SAME index (``"1"`` and ``"01"``, ``"0"`` and ``"-0"``)
  were both kept, so the "list" carried a phantom extra row in an order
  taken from the wire's insertion order;
* a non-empty value of the wrong shape (a string, a number, a dict with a
  non-integer key) was dropped to ``[]`` with nothing logged, so a renamed or
  re-nested upstream field went dark silently.
"""
from __future__ import annotations

import logging

import pytest

from core import liveclient_coerce as lc


@pytest.fixture(autouse=True)
def _fresh_warn_state():
    lc._reset_warned_for_tests()
    yield
    lc._reset_warned_for_tests()


def _hits(caplog, needle):
    return [r for r in caplog.records
            if r.name == lc._log.name and needle in r.getMessage()]


# -- F1: a key past the int-string limit -------------------------------------

def test_huge_digit_key_reads_as_empty_instead_of_raising():
    assert lc.as_list({"1" * 5000: "x"}, "Events") == []


def test_huge_digit_key_beside_a_good_key_refuses_the_whole_dict():
    assert lc.as_list({"0": "a", "9" * 5000: "b"}, "Events") == []


def test_huge_negative_digit_key_reads_as_empty():
    assert lc.as_list({"-" + "7" * 4400: "x"}, "items") == []


# -- F2: two keys naming one index -------------------------------------------

@pytest.mark.parametrize("src", [
    {"1": "a", "01": "b"},
    {"0": "a", "-0": "b"},
    {1: "a", "1": "b"},
    {"0": "z", "2": "a", "002": "b"},
])
def test_duplicate_index_keys_are_refused(src):
    assert lc.as_list(src, "Events") == []


def test_distinct_index_keys_with_leading_zero_still_coerce():
    # A leading zero alone is still integer-like (module docstring); only a
    # COLLISION is refused.
    assert lc.as_list({"01": "b", "0": "a"}, "Events") == ["a", "b"]


# -- F3: an unusable non-empty shape is warned, once per field ---------------

@pytest.mark.parametrize("bad", ["abc", 7, 1.5, True, {"a": 1},
                                 {"0": 1, "x": 2}, {"1": 1, "01": 2},
                                 {"1" * 5000: 1}])
def test_unusable_shape_warns_once_per_field(bad, caplog):
    caplog.set_level(logging.WARNING, logger=lc._log.name)
    assert lc.as_list(bad, "allPlayers") == []
    assert lc.as_list(bad, "allPlayers") == []
    hits = _hits(caplog, "allPlayers")
    assert len(hits) == 1
    assert "unusable" in hits[0].getMessage()


def test_unusable_warning_never_carries_the_value(caplog):
    caplog.set_level(logging.WARNING, logger=lc._log.name)
    lc.as_list("SECRET-LOOKING-PAYLOAD", "items")
    lc.as_list({"PAYLOAD-KEY": 1}, "Events")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "SECRET-LOOKING-PAYLOAD" not in text
    assert "PAYLOAD-KEY" not in text


def test_absent_or_empty_values_stay_silent(caplog):
    caplog.set_level(logging.WARNING, logger=lc._log.name)
    for v in (None, {}, [], ""):
        assert lc.as_list(v, "Events") == []
    assert _hits(caplog, "Events") == []


def test_coerce_and_refuse_warnings_are_independent(caplog):
    caplog.set_level(logging.WARNING, logger=lc._log.name)
    lc.as_list({"0": 1}, "Events")
    lc.as_list({"a": 1}, "Events")
    msgs = [r.getMessage() for r in _hits(caplog, "Events")]
    assert len(msgs) == 2
    assert any("object-shaped" in m for m in msgs)
    assert any("unusable" in m for m in msgs)


# -- the field label is never a crash path ------------------------------------

@pytest.mark.parametrize("label", [["Events"], {"k": 1}, 5, ""])
def test_non_str_or_empty_field_label_does_not_raise(label, caplog):
    caplog.set_level(logging.WARNING, logger=lc._log.name)
    assert lc.as_list({"1": "b", "0": "a"}, label) == ["a", "b"]
    assert lc.as_list("junk", label) == []
    assert _hits(caplog, "<unnamed>")


# -- as_bool: the default is returned as given --------------------------------

def test_as_bool_returns_a_non_bool_default_unchanged():
    # core/live_event_deriver.py reads isDead with default None, so a
    # missing flag stays "unknown" rather than "alive".
    assert lc.as_bool(None, None) is None
    assert lc.as_bool("maybe", None) is None
    assert lc.as_bool("TRUE", None) is True
