# arch: ward-readiness extractor over the active player's Live Client items | section=core | frozen=no
"""core/ward_cue.py - derive the overlay ward-ready glyph cue from inventory.

QA1 (RC2 overlay): a single-pulse glyph that catches the eye the moment a
warding trinket comes off cooldown or the operator is holding a control ward
to place. No competitor surfaces this, and it is the one warding signal we can
read live WITHOUT the (non-existent) ward-placement event stream.

Live Client realities (the same ones core/ward_producer.py is built on):
  * The Live Client API emits NO ward / trinket cast events - the canonical
    event set is ChampionKill / DragonKill / BaronKill / TurretKilled /
    InhibKilled / ... only (dashboard/_state_cooldowns.py documents this). So a
    precise trinket cooldown timer is impossible. What IS exposed is the
    per-item ``canUse`` boolean on ``allPlayers[i].items[]``: for a ward
    trinket, canUse True == off cooldown / ready to place (ward_producer.py
    reads the True->False edge to infer a placement; we read the True state
    itself for the ready cue).
  * Control Ward (2055) is a stackable consumable. "Ready" means you are
    holding one (count >= 1) - there is no cooldown, you place it when you have
    it, so presence is the honest signal.

This module is the PURE extractor (no I/O, no DOM): dashboard/_liveclient.py
calls it with the active player's ``items`` list and ships the result as
``/api/state.liveclient.ward_cue``. The overlay (web/js/panels/ward_cue.js)
owns the not-ready -> ready edge detection + the one-shot pulse.
"""

from __future__ import annotations

from typing import Any

# Placeable ward trinkets. 3340 = Stealth Ward (yellow warding totem),
# 3363 = Farsight Alteration (blue). 3364 = Oracle Lens (sweeper) is
# deliberately EXCLUDED: it reveals/clears, it does not place a ward, so it
# does not belong in a "ward is ready" cue (ward_producer.py skips it too).
WARD_TRINKET_IDS = frozenset({3340, 3363})

# Control Ward (stackable consumable).
CONTROL_WARD_ID = 2055


def _coerce_int(value: Any) -> int | None:
    """Best-effort int coercion. Live Client itemID is numeric, but JSON can
    surface either an int or a stringy id depending on the relay path; a value
    that will not coerce is treated as absent (the entry is skipped)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compute_ward_cue(items: Any) -> dict[str, Any]:
    """Extract the ward-ready cue from the active player's Live Client items.

    ``items`` is ``allPlayers[i].items`` for the operator - a list of dicts of
    shape ``{itemID, slot, count, canUse, consumable, displayName}``. Any other
    input (None, non-list, malformed entries) degrades to the safe all-off
    default rather than raising, since this rides the per-tick /api/state build.

    Returns a flat dict the overlay reads directly::

        {"trinket_ready": bool,    # a ward trinket is off cooldown right now
         "trinket_id": int|None,   # which ward trinket the operator carries
         "control_ward": bool,     # holding at least one control ward
         "control_ward_count": int}
    """
    out: dict[str, Any] = {
        "trinket_ready": False,
        "trinket_id": None,
        "control_ward": False,
        "control_ward_count": 0,
    }
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = _coerce_int(it.get("itemID"))
        if iid is None:
            continue
        if iid in WARD_TRINKET_IDS:
            out["trinket_id"] = iid
            # Strict True only: the Live Client field is a real bool. A truthy
            # non-True value must not flash a false "ready" pulse.
            if it.get("canUse") is True:
                out["trinket_ready"] = True
        elif iid == CONTROL_WARD_ID:
            cnt = _coerce_int(it.get("count"))
            cnt = cnt if cnt is not None else 0
            if cnt > 0:
                out["control_ward"] = True
                out["control_ward_count"] = cnt
    return out


__all__ = ["compute_ward_cue", "WARD_TRINKET_IDS", "CONTROL_WARD_ID"]
