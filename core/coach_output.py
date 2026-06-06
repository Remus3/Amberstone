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
model's validator, reproducing the prior inline behavior byte-for-byte while
giving one validated seam.

The decoded list is intentionally the RAW decoded array (not cleaned) - the
dashboard state builder still runs `core.coach_choices.parse_choices` over it
downstream; this seam only owns the decode, not the per-entry sanitisation.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CoachOutput(BaseModel):
    """Validated container for a parsed coach response.

    Holds the optional native-emit `choices` list plus any mode-specific prose
    fields (``extra="allow"`` keeps them verbatim). Constructing the model
    validates: `choices` is decoded from its JSON-array string into a list (or
    [] on empty / None / non-JSON / non-list input); all other fields pass
    through untouched. ``model_dump()`` returns a plain JSON-safe artifact dict.
    """

    model_config = ConfigDict(extra="allow")

    choices: list = Field(default_factory=list)

    @field_validator("choices", mode="before")
    @classmethod
    def _decode_choices(cls, v: Any) -> list:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            s = v.strip()
            if s:
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
        return []

    @classmethod
    def from_fields(cls, fields: "dict | None") -> "CoachOutput":
        """Build a validated CoachOutput from a parsed-fields dict."""
        return cls(**(fields or {}))

    def to_artifact(self) -> dict:
        """Return the validated fields as a plain dict for the coaching JSON."""
        return self.model_dump()


def decode_choices(raw: Any) -> list:
    """Decode a native-emit `choices` JSON-array string into a list.

    Returns [] on empty / None / non-JSON / non-list input. An already-decoded
    list passes through unchanged. This is the shared replacement for the
    decode block that was duplicated inline in all four coaches; it is
    byte-for-byte equivalent to the prior
    ``json.loads(raw.strip())`` guard.
    """
    return CoachOutput(choices=raw).choices
