"""A/B tutoring-style coach choices.

Goal: the coach output today is free prose (action / immediate / objective /
next). For tutoring value the operator wants the option to surface 2-3
discrete micro-decisions per tick with explicit A / B (sometimes C)
options, each carrying a confidence band + source tag. The user sees the
choices; the dashboard logs which choice was visible at decision time so
the post-game review can replay the timeline with the coaching context.

This module is the SHAPE + (eventually) a synthesizer:

- ``CoachChoice`` dataclass = the on-the-wire shape.
- ``parse_choices(coach: dict) -> list[CoachChoice]`` = extracts a valid
  list from a coach JSON dict; tolerates missing field, bad shape, and
  out-of-range confidence values.
- ``synthesize_simple_choices(coach: dict) -> list[CoachChoice]`` = a
  conservative fallback that derives a single A/B from the existing
  action + fight_rule + immediate fields when the coach has not yet been
  prompt-tuned to emit native choices. Returns an empty list when no
  meaningful A/B can be derived (no synthetic noise).

Cost gate: no extra LLM calls. The native-emission path piggybacks on the
existing per-tick coach call (the prompt asks the model to return the
choices array alongside the prose). The synthesizer is a pure-Python
fallback.

Logging the user's selection lives in ``core.decision_detector.record_coach_choice``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable


VALID_CONFIDENCE_BANDS = ("low", "mid", "high")
_MAX_CHOICES = 3
_MAX_LABEL_LEN = 80
_MAX_OUTCOME_LEN = 160


@dataclass(frozen=True)
class CoachChoice:
    """One A/B/C choice surfaced by the coach for this tick."""

    key: str
    label: str
    expected_outcome: str = ""
    confidence: str = "mid"
    source_tag: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _coerce_str(v: object, limit: int) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if len(s) > limit:
        s = s[:limit].rstrip() + "..."
    return s


def _coerce_band(v: object) -> str:
    s = _coerce_str(v, 8).lower()
    if s in VALID_CONFIDENCE_BANDS:
        return s
    return "mid"


def _coerce_key(v: object, fallback: str) -> str:
    s = _coerce_str(v, 4).upper()
    if not s:
        return fallback
    return s[:1]


def parse_choices(coach: dict | None) -> list[CoachChoice]:
    """Pull a clean list of choices out of a coach JSON dict.

    Returns an empty list on any of: coach is None, ``choices`` absent,
    ``choices`` not a list, or all entries malformed. Truncates to
    ``_MAX_CHOICES``. Each entry is sanitized: label/outcome are
    string-coerced + length-limited, key is one upper-case letter,
    confidence falls back to ``mid`` when out-of-range.
    """

    if not isinstance(coach, dict):
        return []
    raw = coach.get("choices")
    if not isinstance(raw, list):
        return []
    out: list[CoachChoice] = []
    for idx, entry in enumerate(raw[:_MAX_CHOICES]):
        if not isinstance(entry, dict):
            continue
        fallback_key = chr(ord("A") + idx)
        label = _coerce_str(entry.get("label"), _MAX_LABEL_LEN)
        if not label:
            continue
        out.append(
            CoachChoice(
                key=_coerce_key(entry.get("key"), fallback_key),
                label=label,
                expected_outcome=_coerce_str(entry.get("expected_outcome"), _MAX_OUTCOME_LEN),
                confidence=_coerce_band(entry.get("confidence")),
                source_tag=_coerce_str(entry.get("source_tag"), 32),
            )
        )
    return out


def _action_choice(action: str) -> tuple[str, str] | None:
    """Return (a_label, b_label) if the action prose contains a recognizable
    binary verb pair. Returns None when no A/B can be derived."""

    a = action.lower()
    pairs: list[tuple[tuple[str, ...], str, str]] = [
        (("contest", "fight for", "take the"), "Contest", "Concede"),
        (("engage", "all-in", "pick"), "Engage", "Disengage"),
        (("push",), "Push", "Freeze"),
        (("freeze",), "Freeze", "Push"),
        (("recall", "back", "reset"), "Recall", "Stay"),
        (("ward", "vision"), "Ward", "Skip vision"),
        (("rotate", "swap"), "Rotate", "Hold"),
        (("siege",), "Siege", "Disengage"),
    ]
    for triggers, a_lbl, b_lbl in pairs:
        if any(t in a for t in triggers):
            return a_lbl, b_lbl
    return None


def synthesize_simple_choices(coach: dict | None) -> list[CoachChoice]:
    """Derive a conservative single A/B from existing coach prose fields.

    Returns ``[]`` when no obvious binary verb is present. Used until the
    coach LLM is prompt-tuned to emit native ``choices`` arrays; the
    synthesized output carries source_tag=``synth`` so the frontend can
    visually distinguish.
    """

    if not isinstance(coach, dict):
        return []
    action = _coerce_str(coach.get("action"), 200)
    if not action:
        return []
    pair = _action_choice(action)
    if pair is None:
        return []
    a_lbl, b_lbl = pair
    immediate = _coerce_str(coach.get("immediate"), _MAX_OUTCOME_LEN)
    fight_rule = _coerce_str(coach.get("fight_rule"), _MAX_OUTCOME_LEN)
    expected_a = immediate or "follow the coach call"
    expected_b = fight_rule or "play safe; reassess next tick"
    return [
        CoachChoice(key="A", label=a_lbl, expected_outcome=expected_a,
                    confidence="mid", source_tag="synth"),
        CoachChoice(key="B", label=b_lbl, expected_outcome=expected_b,
                    confidence="mid", source_tag="synth"),
    ]


def to_jsonable(choices: Iterable[CoachChoice]) -> list[dict]:
    """Serialize a sequence of CoachChoice to plain dicts for JSON."""

    return [c.to_dict() for c in choices]
