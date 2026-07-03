"""Deterministic Arena target-priority line (Stage 1, Tier-1, no live wiring).

Pure projection of the Arena coach's documented kill order into one
short string: the prompt's own rule at ``coaches/arena_coach.py:148`` is
carry first (lowest HP, highest threat), CC holder next, tank last. The
frontline/backline CLASSIFICATION needs champion data and therefore
happens in the wiring layer, NOT here - this module only applies the
ordering rule to already-classified names.

Output shapes:
    * first non-frontline opponent (list order preserved) ->
        "Kill {name} first - squishy threat; tanks last"
    * every alive opponent is frontline ->
        "Kill {first} first - no squishy target"
    * nothing usable -> ""

Fail-soft (this function NEVER raises): non-str / blank entries are
skipped, a malformed frontline collection degrades to an empty set, and
the output is clamped to <=12 words so multi-word display names cannot
overflow the overlay line.
"""
from __future__ import annotations


def _clamp_words(text: str, max_words: int) -> str:
    """Trim to at most ``max_words`` whitespace-delimited words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def target_priority(alive_opponents, frontline_names) -> str:
    """Return the kill-order line for the alive opponents, or "".

    ``alive_opponents`` is an ordered list/tuple of opponent display
    names; ``frontline_names`` is any iterable of names already
    classified as frontline. Never raises.
    """
    try:
        # Only a real sequence carries the ordering claim; a bare str
        # would iterate characters, so it is malformed here.
        if not isinstance(alive_opponents, (list, tuple)):
            return ""
        names = [
            n.strip() for n in alive_opponents if isinstance(n, str) and n.strip()
        ]
        if not names:
            return ""
        try:
            frontline = {n for n in frontline_names if isinstance(n, str)}
        except Exception:  # noqa: BLE001 - malformed classification -> none
            frontline = set()
        for name in names:
            if name not in frontline:
                return _clamp_words(
                    f"Kill {name} first - squishy threat; tanks last", 12
                )
        # No squishy alive: still name a target (the first) so the line
        # never goes silent mid-round.
        return _clamp_words(f"Kill {names[0]} first - no squishy target", 12)
    except Exception:  # noqa: BLE001 - hard fail-soft contract
        return ""


__all__ = ["target_priority"]
