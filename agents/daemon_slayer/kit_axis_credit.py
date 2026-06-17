"""DSP11 Cluster-B2 kit-axis item-credit table loader (DEFAULT-OFF seam input).

Reads ``kit_axis_item_credit.json`` (built offline by
``ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py`` from the DSP10
consolidated buried-winner report + rewind WIN data) and exposes the per-champion
set of TERMINAL kit-axis items the dps/burst scorers bury but the player base
wins on. Consumed by the DEFAULT-OFF ``prefer_kit_axis_by_win`` seam in
``rank.py`` (DPS) + ``burst.py`` (burst) to:

  1. un-strip those items from the ranged-marksman off-class deny set
     (caster-ADCs whose Trinity Force is hard-excluded today), and
  2. float them above the generic AD template in the ranking.

Fail-soft: a missing / unreadable / malformed table yields an empty map so the
seam degrades to a byte-identical no-op rather than raising. The live default-ON
flip is EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_TABLE_PATH = Path(__file__).resolve().parent / "kit_axis_item_credit.json"

# champion key (DDragon id / display name) -> (frozenset ids, frozenset names).
_CACHE: Optional[dict[str, tuple[frozenset[str], frozenset[str]]]] = None


def _load() -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    out: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    try:
        raw = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
        for champ, entry in (raw.get("champions") or {}).items():
            items = (entry or {}).get("items") or []
            ids = frozenset(
                str(i["id"]) for i in items if isinstance(i, dict) and i.get("id")
            )
            names = frozenset(
                str(i["name"]) for i in items if isinstance(i, dict) and i.get("name")
            )
            if ids or names:
                out[str(champ)] = (ids, names)
    except Exception:  # noqa: BLE001 - fail-soft, empty map -> seam is a no-op
        out = {}
    _CACHE = out
    return out


def reset_cache() -> None:
    """Drop the cached table so the next read re-pulls. Used by tests."""
    global _CACHE
    _CACHE = None


def _resolve(champion_id: str, champ_rec: Optional[dict]) -> tuple[frozenset[str], frozenset[str]]:
    tbl = _load()
    hit = tbl.get(str(champion_id))
    if hit:
        return hit
    name = (champ_rec or {}).get("name") if isinstance(champ_rec, dict) else None
    if name:
        return tbl.get(str(name), (frozenset(), frozenset()))
    return (frozenset(), frozenset())


def kit_axis_item_ids(champion_id: str, champ_rec: Optional[dict] = None) -> frozenset[str]:
    """WIN-anchored kit-axis item ids for ``champion_id`` (empty if none)."""
    if not champion_id:
        return frozenset()
    return _resolve(str(champion_id), champ_rec)[0]


def kit_axis_item_names(champion_id: str, champ_rec: Optional[dict] = None) -> frozenset[str]:
    """WIN-anchored kit-axis item NAMES for ``champion_id`` (empty if none).

    Used to un-strip these items from the name-keyed off-class marksman deny set.
    """
    if not champion_id:
        return frozenset()
    return _resolve(str(champion_id), champ_rec)[1]
