"""RM-1241: a whitespace-only string in a numeric key or ``only`` reads as absent.

The scalar helpers in ``agents/daemon_slayer/server.py`` read ``""`` as
"absent" (the default answers) but a whitespace-only string took a different
road. Measured on the live server (ENGINE 1.290.0, patch 16.21.1):

* POST /stats, Zed: ``level: ""`` -> 200 at level 1 (the default);
  ``level: "   "`` -> 400 "level: expected integer, got '   '";
  ``level: " 11 "`` -> 200 at level 11 (already stripped by ``int``).
* POST /dps, Jinx: ``target_armor: ""`` -> 200 at 0.0;
  ``target_armor: "   "`` -> 400 "target_armor: expected number, got '   '".
* POST /rank, Jinx L11 ``items: ["3031"]``: ``only: ""`` -> 107 candidates
  (no filter); ``only: "   "`` -> 0 candidates, an empty 200 - the caller
  sent no value and silently got an empty whitelist.

Policy, chosen to invent nothing: it is ``_opt_str``'s and the RM-1239 /
RM-1240 one - a blank string reads as absent. Kept tight on purpose: an
explicit empty list ``only: []`` stays an empty whitelist, a separator-only
``only: " , "`` is unchanged, and a non-blank junk string (``"abc"``) stays
the 400. ASCII only.
"""
from __future__ import annotations

import inspect

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import (
    _ApiError,
    _opt_float,
    _opt_int,
    _opt_only,
    _opt_targets_override,
    _opt_weight,
)

BLANKS = ["   ", " ", "\t\n", ""]


@pytest.mark.parametrize("raw", BLANKS)
def test_opt_int_blank_is_the_default(raw) -> None:
    assert _opt_int({"level": raw}, "level", 7) == 7


@pytest.mark.parametrize("raw", BLANKS)
def test_opt_float_blank_is_the_default(raw) -> None:
    assert _opt_float({"target_armor": raw}, "target_armor", 42.5) == 42.5


@pytest.mark.parametrize("raw", BLANKS)
def test_opt_weight_blank_is_absent(raw) -> None:
    assert _opt_weight({"alpha": raw}, "alpha") is None


@pytest.mark.parametrize("raw", BLANKS)
def test_opt_targets_override_blank_is_absent(raw) -> None:
    assert _opt_targets_override({"targets_per_proc_override": raw}) is None


@pytest.mark.parametrize("raw", BLANKS + [None])
def test_opt_only_blank_is_no_filter(raw) -> None:
    assert _opt_only({"only": raw}) is None


def test_opt_only_absent_is_no_filter() -> None:
    assert _opt_only({}) is None


@pytest.mark.parametrize(
    "raw, expected",
    [([], []), (" , ", []), ("3031, 3094", ["3031", "3094"]),
     (["3031", " 3094 "], ["3031", "3094"]), ([3031.0], ["3031"])],
)
def test_opt_only_existing_forms_are_unchanged(raw, expected) -> None:
    assert _opt_only({"only": raw}) == expected


def test_opt_only_keeps_the_element_400() -> None:
    with pytest.raises(_ApiError) as exc:
        _opt_only({"only": [True]})
    assert exc.value.status == 400
    assert exc.value.message.startswith("only[0]:")


@pytest.mark.parametrize(
    "fn, body, key",
    [(_opt_int, {"level": "abc"}, "level"),
     (_opt_float, {"target_armor": "abc"}, "target_armor"),
     (_opt_weight, {"alpha": "abc"}, "alpha")],
)
def test_non_blank_junk_is_still_a_400(fn, body, key) -> None:
    with pytest.raises(_ApiError) as exc:
        fn(body, key)
    assert exc.value.status == 400
    assert repr("abc") in exc.value.message


@pytest.mark.parametrize(
    "fn, body, expected",
    [(lambda b: _opt_int(b, "level", 1), {"level": " 11 "}, 11),
     (lambda b: _opt_float(b, "target_armor"), {"target_armor": " 100 "},
      100.0),
     (lambda b: _opt_weight(b, "alpha"), {"alpha": " 0.5 "}, 0.5)],
)
def test_padded_numbers_still_parse(fn, body, expected) -> None:
    assert fn(body) == expected


def test_every_route_reads_only_through_the_helper() -> None:
    """No route keeps the old ``not in (None, "")`` form, which let a blank
    string through to an empty whitelist; eight routes read ``only``."""
    src = inspect.getsource(server)
    assert 'body["only"] not in (None, "")' not in src
    assert src.count("only_ids = _opt_only(body)") == 8
