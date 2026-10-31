"""RM-1239: ``max_priority`` strips its string form like every string key.

``_parse_max_priority`` in ``agents/daemon_slayer/server.py`` tested the
compact form (``"QWE"``) on the RAW string, before any strip. Measured on the
live server (ENGINE 1.290.0, patch 16.21.1), POST /ability-dps for Cassiopeia
at level 11:

* ``"QWE"`` and ``"E,W,Q"`` answered 200;
* ``" QWE"`` and ``"QWE "`` answered 400 ``max_priority: expected 3 keys,
  got ['QWE']`` - the message blames the caller for sending the one valid
  priority it quotes back;
* ``"   "`` (three spaces) passed the ``len == 3`` test, became the tuple
  ``(" ", " ", " ")`` and reached the engine as an opaque 422.

Policy, chosen to invent nothing: it is ``_opt_str``'s - a string value is
stripped first, and a blank string reads as absent (``None``, so the
per-champion registry resolves), the same as ``""`` already did. A
non-permutation (``"QQE"``) is still the engine's 422 (``test_burst``
pins it), and list forms are untouched (``_coerce_str_list`` already strips
each element). ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.server import _ApiError, _parse_max_priority


@pytest.mark.parametrize(
    "raw, expected",
    [(" QWE", ("Q", "W", "E")), ("QWE ", ("Q", "W", "E")),
     ("  ewq  ", ("E", "W", "Q")), ("\tQEW\n", ("Q", "E", "W"))],
)
def test_padded_compact_form_parses(raw, expected) -> None:
    assert _parse_max_priority({"max_priority": raw}) == expected


@pytest.mark.parametrize("raw", ["   ", " ", "\t\n", ""])
def test_blank_string_reads_as_absent(raw) -> None:
    assert _parse_max_priority({"max_priority": raw}) is None


@pytest.mark.parametrize(
    "body, expected",
    [({}, None), ({"max_priority": None}, None),
     ({"max_priority": "QWE"}, ("Q", "W", "E")),
     ({"max_priority": "qwe"}, ("Q", "W", "E")),
     ({"max_priority": "E,W,Q"}, ("E", "W", "Q")),
     ({"max_priority": " E , W , Q "}, ("E", "W", "Q")),
     ({"max_priority": ["q", " w ", "e"]}, ("Q", "W", "E"))],
)
def test_existing_forms_are_unchanged(body, expected) -> None:
    assert _parse_max_priority(body) == expected


@pytest.mark.parametrize("raw", ["Q-W-E", "QW", "Q,W", ["Q", "W"], "Q W E"])
def test_wrong_key_count_is_still_a_400(raw) -> None:
    with pytest.raises(_ApiError) as exc:
        _parse_max_priority({"max_priority": raw})
    assert exc.value.status == 400
    assert exc.value.message.startswith("max_priority: expected 3 keys")


def test_non_permutation_still_reaches_the_engine() -> None:
    # The engine's permutation check owns this (422, test_burst pins it);
    # the parser must not start rejecting or rewriting it.
    assert _parse_max_priority({"max_priority": " QQE "}) == ("Q", "Q", "E")
