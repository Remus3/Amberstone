"""Guard: the per-item Ability-Haste registry stays in lock-step with live DDragon.

The hand-pinned ``_item_ability_haste._ITEM_ABILITY_HASTE`` (220 items) has no
committed regen tool, so a patch that re-values an item's AH silently drifts the
registry - and every existing test asserts HARDCODED values, so nothing catches
it. Exactly that happened: at 16.13.1 Riot re-valued Eclipse's Arena mirror
226692 (10 -> 15, matching base 6692) and the pin + the value-assertion tests
both missed it, uncaught until the 16.14.1 refresh audit.

These two guards make the drift class fail LOUDLY at CI time going forward:

  1. ``test_registry_matches_live_ddragon`` re-derives the AH dict from the
     CURRENT-patch DDragon item.json (via the drift-check tool's canonical
     parse) and asserts zero add/remove/value drift vs the pin. Any future AH
     re-value fails here until the registry is re-pinned in the same commit.
  2. ``test_drift_check_default_tracks_current_patch`` pins the fix to the
     drift-check TOOL: its no-arg default must resolve the LIVE patch
     (current.txt), not a hardcoded stale catalog (the original bug: the tool
     hardcoded 16.12.1 and false-reported IN SYNC).

Repo-level (not agents/daemon_slayer/tests/) on purpose: it imports the
ops/audit drift-check tool, which sits outside the engine package and which
the engine suite must stay able to run without.
ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

from pathlib import Path

import ops.audit.item_ah_drift_check as ahc
from agents.daemon_slayer._item_ability_haste import _ITEM_ABILITY_HASTE

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CURRENT = _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"


def _current_patch() -> str:
    return _CURRENT.read_text(encoding="utf-8").strip()


def test_registry_matches_live_ddragon() -> None:
    patch = _current_patch()
    item_json = _REPO_ROOT / "data" / "meta_build" / "ddragon" / patch / "item.json"
    assert item_json.exists(), f"no DDragon item.json for live patch {patch}"

    derived = ahc.derive_from_ddragon(item_json)
    pinned = _ITEM_ABILITY_HASTE

    changed = {
        i: (pinned[i], derived[i])
        for i in set(pinned) & set(derived)
        if pinned[i] != derived[i]
    }
    added = sorted(set(derived) - set(pinned), key=int)     # DDragon has AH, pin missing
    removed = sorted(set(pinned) - set(derived), key=int)   # pin has AH, DDragon dropped

    assert not changed, (
        f"item-AH pin value drift vs DDragon {patch}: {changed}. Re-pin "
        "agents/daemon_slayer/_item_ability_haste.py in this commit."
    )
    assert not added and not removed, (
        f"item-AH id-set drift vs DDragon {patch}: added={added} removed={removed}. "
        "Re-pin the registry in this commit."
    )


def test_drift_check_default_tracks_current_patch() -> None:
    # The tool's no-arg default catalog must follow the live patch, else it is a
    # blind guard (the original bug hardcoded 16.12.1 and false-cleaned).
    resolved = ahc._default_item_json()
    patch = _current_patch()
    assert patch in str(resolved), (
        f"drift-check default {resolved} does not track current.txt patch {patch}"
    )
    assert resolved.exists(), f"resolved default item.json missing: {resolved}"
