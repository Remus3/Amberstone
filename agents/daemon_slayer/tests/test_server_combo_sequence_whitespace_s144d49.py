"""RM-1240: a blank ``combo_sequence`` string reads as absent, like ``""``.

``_parse_combo_sequence`` in ``agents/daemon_slayer/server.py`` returned
``None`` for ``""`` (so the per-champion registry resolves) but 400'd a
whitespace-only string. Measured on the live server (ENGINE 1.290.0, patch
16.21.1), POST /burst for Zed at level 11:

* ``""`` answered 200 with the registry combo (``combo_sequence_source``
  ``"champion"``);
* ``"   "`` answered 400 ``combo_sequence: empty after parse``.

Policy, chosen to invent nothing: it is ``_opt_str``'s and the RM-1239
``max_priority`` one - a string value is stripped first, and a blank string
reads as absent. Kept tight on purpose: a separator-only string (``"-"``,
``","``) and an explicit empty list (``[]``, ``[" "]``) are still the 400,
because the caller sent a shape with no tokens rather than no value. ASCII
only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.server import _ApiError, _parse_combo_sequence


@pytest.mark.parametrize("raw", ["   ", " ", "\t\n", ""])
def test_blank_string_reads_as_absent(raw) -> None:
    assert _parse_combo_sequence({"combo_sequence": raw}) is None


@pytest.mark.parametrize(
    "body, expected",
    [({}, None), ({"combo_sequence": None}, None),
     ({"combo_sequence": "W-Q-AA-R-AA-AA"},
      ("W", "Q", "AA", "R", "AA", "AA")),
     ({"combo_sequence": " Q-W-E "}, ("Q", "W", "E")),
     ({"combo_sequence": "Q, W ,E"}, ("Q", "W", "E")),
     ({"combo_sequence": ["E", " Q ", "AA"]}, ("E", "Q", "AA"))],
)
def test_existing_forms_are_unchanged(body, expected) -> None:
    assert _parse_combo_sequence(body) == expected


@pytest.mark.parametrize("raw", ["-", ",", " - ", "--", [], [" "], [None]])
def test_tokenless_shape_is_still_a_400(raw) -> None:
    with pytest.raises(_ApiError) as exc:
        _parse_combo_sequence({"combo_sequence": raw})
    assert exc.value.status == 400
    assert exc.value.message == "combo_sequence: empty after parse"
