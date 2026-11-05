"""core/coach_output.py - shared validated structured-output model for coaches.

P2.2 tail (item 314, 2026-06-05). All four live coaches (ARAM/Arena/Brawl via
`coaches/_base_coach.py::parse_fields`, and SR via
`coach_integration/_coach.py::_parse_response`) extract their prose fields with
mode-specific parsers - those legitimately diverge (key remapping, multi-line
accumulation, different markdown-strip, truncation, positional fallback) and
are each pinned by their own golden masters, so they are NOT merged here.

What WAS duplicated verbatim in all four coaches is the native-emit `choices`
JSON-array decode (json.loads -> list, [] on any malformed/non-list input).
This module is the single Pydantic-validated home for that structured-output
parse. `decode_choices` routes a raw field value through the `CoachOutput`
model's validator, reproducing the prior inline behavior for every well-formed
array while giving one validated seam.

The decoded list is otherwise the RAW decoded array (not cleaned) - the
dashboard state builder still runs `core.coach_choices.parse_choices` over it
downstream; this seam only owns the decode, not the per-entry sanitisation.

Trust boundary (s144 true-audit cycle 134): `choices` is model output, and the
coaches write the decoded list into data/*_coaching_data.json with
`json.dumps` at its default allow_nan=True. So the decoded value is made
STRICT-JSON-SAFE here, at the one seam every coach shares:
  * a NaN / Infinity / -Infinity token or an overflowing literal (1e400) is
    None, so the artifact never carries a bare NaN / Infinity token, which is
    not valid JSON for any strict reader;
  * an int over 64 bits is None (no chip reads it, and an int past Python's
    4300-digit limit makes json.dumps raise);
  * an already-decoded list is rebuilt the same way: a tuple is a list, a dict
    keeps only its str keys, and any other value (a set, bytes, an object) is
    None, so one bad leaf can no longer make the artifact's json.dumps raise
    and fail the coach's whole tick write;
  * a container nested deeper than _MAX_DEPTH is None, which also cuts a
    self-referencing list;
  * every container is a fresh copy, never an alias of the caller's.
A well-formed array of strings, finite floats, ints within 64 bits, bools and
nulls, nested no deeper than _MAX_DEPTH, decodes to exactly what json.loads
returns (pinned by tests/test_coach_output_p2_2.py).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# A choices array is list -> dict -> scalar (depth 2); nested lists inside an
# entry add a little. A container deeper than this is no reading (None).
_MAX_DEPTH = 16
# An int wider than this is no reading (None). Mirrors core.coach_choices
# _as_text, which already treats such a number as no chip text downstream.
_MAX_INT_BITS = 64


def _json_safe(value: Any, depth: int) -> Any:
    """`value` as a fresh strict-JSON-safe tree; an unsafe node is None."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value if value.bit_length() <= _MAX_INT_BITS else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if depth >= _MAX_DEPTH:
        return None
    if isinstance(value, (list, tuple)):
        return [_json_safe(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {
            k: _json_safe(v, depth + 1)
            for k, v in value.items()
            if isinstance(k, str)
        }
    return None


class CoachOutput(BaseModel):
    """Validated container for a parsed coach response.

    Holds the optional native-emit `choices` list plus any mode-specific prose
    fields (``extra="allow"`` keeps them verbatim). Constructing the model
    validates: `choices` is decoded from its JSON-array string into a
    strict-JSON-safe list (or [] on empty / None / non-JSON / non-list input);
    all other fields pass through untouched. ``model_dump()`` returns a plain
    dict whose `choices` is strict-JSON-safe; the extras are the caller's own
    values, verbatim (the live coaches read only `.choices`).
    """

    model_config = ConfigDict(extra="allow")

    choices: list = Field(default_factory=list)

    @field_validator("choices", mode="before")
    @classmethod
    def _decode_choices(cls, v: Any) -> list:
        if isinstance(v, list):
            return _json_safe(v, 0)
        if isinstance(v, str):
            s = v.strip()
            if s:
                try:
                    parsed = json.loads(s)
                except (ValueError, RecursionError):
                    # ValueError: malformed / truncated JSON, or an int literal
                    # past Python's digit limit; RecursionError: nesting deeper
                    # than the C scanner allows. Anything else is a real bug
                    # and is left to raise.
                    return []
                if isinstance(parsed, list):
                    return _json_safe(parsed, 0)
        return []

    @classmethod
    def from_fields(cls, fields: "Mapping | None") -> "CoachOutput":
        """Build a validated CoachOutput from a parsed-fields mapping.

        A non-mapping (None, a list of pairs, a str) is no fields, and a
        non-str key is dropped, so a malformed fields value degrades to no
        choices instead of raising TypeError into the coach tick.
        """
        if not isinstance(fields, Mapping):
            return cls()
        return cls(**{k: v for k, v in fields.items() if isinstance(k, str)})

    def to_artifact(self) -> dict:
        """Return the validated fields as a plain dict for the coaching JSON."""
        return self.model_dump()


def decode_choices(raw: Any) -> list:
    """Decode a native-emit `choices` JSON-array string into a list.

    Returns [] on empty / None / non-JSON / non-list input. An already-decoded
    list is rebuilt strict-JSON-safe (equal to the input when it is already
    plain JSON). Equivalent to the prior ``json.loads(raw.strip())`` guard for
    every well-formed array within the bounds in the module docstring; a
    non-finite number, an int over 64 bits or an over-deep container is None.
    """
    return CoachOutput(choices=raw).choices
