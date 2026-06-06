"""Champ-select brief generator (deterministic; Haiku eliminated).

Haiku-elimination program (items 273/276/280/283, flipped 2026-06-06).
`brief_via_coach()` previously asked Claude Haiku for the unified champ-select
brief (build + runes + ally notes) and shadow-logged a deterministic candidate
alongside for operator validation. The deterministic substrate
(`_champ_select_deterministic.brief_deterministic`) was validated against that
shadow log, so this surface now serves it DIRECTLY with ZERO Anthropic call.

The public name + signature are unchanged so the web_dashboard re-export and
any in-process caller keep working. Returns the {build, runes, ally_notes}
shape, and the empty {"build": [], "runes": {}, "ally_notes": ""} shape on any
error (the deterministic substrate is itself fail-soft).
"""
from __future__ import annotations

from dashboard._champ_select_deterministic import brief_deterministic


def brief_via_coach(champ: str, enemies: list, allies: list,
                    role: str, mode: str) -> dict:
    """Return the deterministic champ-select brief: build + runes + ally notes.
    No Anthropic call - delegates to
    `_champ_select_deterministic.brief_deterministic`, which mirrors this shape
    and fails soft to the empty brief on any error."""
    return brief_deterministic(champ, enemies, allies, role, mode)
