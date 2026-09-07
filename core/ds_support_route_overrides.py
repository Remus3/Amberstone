# arch: Slice C support-tag route-override loader (RM-84) | section=core | frozen=no
"""Slice C (2026-07-18, RM-84) - Support-tag archetype ROUTE corrections.

WHY: ``core.archetype_picks.tag_to_archetype("Support") == "enchanter"``, so all
18 champions whose FIRST DDragon tag is ``Support`` route to the ``ds.hps``
scorer. ``axis_correct_archetype`` rescues the AD ones (Pyke -> assassin, Senna
-> carry) because it resolves an AD-vs-AP conflict, but it is structurally blind
to an AP-vs-AP misroute (Morgana: enchanter and mage are both AP) and to an
axis-neutral one (Thresh / Rakan / Taric / Bard).

The consequence is an engine-anchor violation, not a preference: every champion
routed to ``ds.hps`` gets the SAME byte-identical top-6 (Echoes of Helia >
Ardent Censer > Staff of Flowing Water > Locket > Knight's Vow > Redemption),
and for the overridden champions the top 3 of that list have a ~0% real pick
rate at every build depth in every role.

WHY NOT ``data/cs_archetype_picks.json``: that file is GITIGNORED runtime
operator state (``.gitignore:77``). An override written there would not reach
CI or any other machine, and it would re-create exactly the
committed-precompute pollution vector whose UI was removed in LEDGER 824. This
roster is git-tracked and kit-derived, mirroring the Slice A (``_AP_ASSASSIN_IDS``)
and Slice B (``core/ds_onhit_ap_roster.py``) precedents.

Cached per process (module-level dict + ``threading.Lock`` - same pattern as
``ds_onhit_ap_roster`` / ``archetype_picks._ID_CACHE``). Fail-soft: a missing,
unreadable or malformed file returns ``{}`` so every champion falls back to the
tag-derived route, never raises - a roster problem must never crash coaching.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

_ROSTER_PATH = Path(__file__).resolve().parent / "ds_support_route_overrides.json"

# Kept in sync with ``archetype_picks.VALID_ARCHETYPES``; duplicated rather than
# imported to avoid a circular import (archetype_picks imports THIS module).
_VALID_ARCHETYPES = frozenset(
    {"carry", "bruiser", "tank", "mage", "assassin", "enchanter", "onhit"}
)

_ROSTER_LOCK = threading.Lock()
_ROSTER_CACHE: Optional[dict[str, tuple[str, str]]] = None


def _flatten(raw) -> dict[str, tuple[str, str]]:
    """``{"champions": {champ: {"primary": p, "secondary": s}}}`` -> ``{champ: (p, s)}``.

    Skips (does not raise on) any entry that is not a dict, is missing
    ``primary``, or names an archetype outside ``_VALID_ARCHETYPES`` - one bad
    hand-edit degrades to "that champion keeps its tag route" rather than
    nuking the whole roster. ``secondary`` defaults to ``"enchanter"`` so the
    demoted route stays available as the operator's one-tap alt-view.
    """
    if not isinstance(raw, dict):
        return {}
    champs = raw.get("champions")
    if not isinstance(champs, dict):
        return {}
    out: dict[str, tuple[str, str]] = {}
    for champ, entry in champs.items():
        if not isinstance(entry, dict):
            continue
        primary = entry.get("primary")
        if not isinstance(primary, str) or primary not in _VALID_ARCHETYPES:
            continue
        secondary = entry.get("secondary")
        if not isinstance(secondary, str) or secondary not in _VALID_ARCHETYPES:
            secondary = "enchanter"
        out[champ] = (primary, secondary)
    return out


def load_support_route_overrides() -> dict[str, tuple[str, str]]:
    """Return ``{champion: (primary, secondary)}``; ``{}`` when unavailable."""
    global _ROSTER_CACHE
    with _ROSTER_LOCK:
        if _ROSTER_CACHE is not None:
            return _ROSTER_CACHE
        out: dict[str, tuple[str, str]] = {}
        try:
            out = _flatten(json.loads(_ROSTER_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            _log.warning(
                "ds_support_route_overrides: roster load failed (%s); "
                "every champion keeps its DDragon-tag route",
                exc,
            )
        _ROSTER_CACHE = out
        return _ROSTER_CACHE


def reset_support_route_override_cache() -> None:
    """Drop the per-process cache (tests + a hand-edit during a live session)."""
    global _ROSTER_CACHE
    with _ROSTER_LOCK:
        _ROSTER_CACHE = None
