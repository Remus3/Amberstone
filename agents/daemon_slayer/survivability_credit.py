"""RF1 generic-bruiser-template survivability item-credit table loader (seam input).

Reads ``survivability_item_credit.json`` (built offline by
``ops/audit/ds_perm_swarm/build_survivability_item_credit.py`` from the DSP10
consolidated buried-winner report, hybrid/bruiser scorer lane + rewind WIN data)
and exposes the per-champion set of TERMINAL survivability / sustain items the
hybrid/bruiser scorer buries but the player base wins on. Consumed by the
DEFAULT-OFF ``prefer_survivability_by_win`` seam in
``hybrid.rank_items_by_hybrid`` to float those items above the generic AD-DPS
template.

ROOT-CAUSE distinction from the sibling DPS/burst kit-axis seam (DSP11
``kit_axis_credit``): the DSP11 float is GATED ON ``delta_dps > 0`` because its
items (IE / Manamune / Trinity) genuinely add DPS, just buried. Survivability
items add EHP / sustain, NOT DPS, so their hybrid delta is ~0 - they are floated
here BY WIN-TABLE MEMBERSHIP, not by the scorer delta. That membership IS the
win evidence the damage-biased hybrid sort is blind to.

Fail-soft: a missing / unreadable / malformed table yields an empty map so the
seam degrades to a byte-identical no-op rather than raising. The live default-ON
flip is EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_TABLE_PATH = Path(__file__).resolve().parent / "survivability_item_credit.json"
# RF2 enchanter/hps-lane table (separate file + cache). The hps scorer's
# enchanter_only pool EXCLUDES HP/tank items entirely (zero HPS throughput), so the
# RF2 seam INJECTS these tabled ids into the pool before floating - see
# ``hps.rank_items_by_hps``. The hybrid table above only needs floating (RF1).
_ENCHANTER_TABLE_PATH = (
    Path(__file__).resolve().parent / "survivability_item_credit_enchanter.json"
)

# champion key (DDragon id / display name) -> frozenset of terminal item ids.
_CACHE: Optional[dict[str, frozenset[str]]] = None
_CACHE_ENCHANTER: Optional[dict[str, frozenset[str]]] = None


def _parse_table(path: Path) -> dict[str, frozenset[str]]:
    """Parse a survivability-credit table file into champ -> item-id frozensets.

    Fail-soft: a missing / unreadable / malformed table yields an empty map so the
    seam degrades to a byte-identical no-op rather than raising.
    """
    out: dict[str, frozenset[str]] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for champ, entry in (raw.get("champions") or {}).items():
            items = (entry or {}).get("items") or []
            ids = frozenset(
                str(i["id"]) for i in items if isinstance(i, dict) and i.get("id")
            )
            if ids:
                out[str(champ)] = ids
    except Exception:  # noqa: BLE001 - fail-soft, empty map -> seam is a no-op
        out = {}
    return out


def _load() -> dict[str, frozenset[str]]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _parse_table(_TABLE_PATH)
    return _CACHE


def _load_enchanter() -> dict[str, frozenset[str]]:
    global _CACHE_ENCHANTER
    if _CACHE_ENCHANTER is None:
        _CACHE_ENCHANTER = _parse_table(_ENCHANTER_TABLE_PATH)
    return _CACHE_ENCHANTER


def reset_cache() -> None:
    """Drop both cached tables so the next read re-pulls. Used by tests."""
    global _CACHE, _CACHE_ENCHANTER
    _CACHE = None
    _CACHE_ENCHANTER = None


def survivability_item_ids(champion_id: str, champ_rec: Optional[dict] = None) -> frozenset[str]:
    """WIN-anchored survivability item ids for ``champion_id`` (empty if none).

    RF1 hybrid/bruiser lane (``hybrid.rank_items_by_hybrid``).
    """
    if not champion_id:
        return frozenset()
    tbl = _load()
    hit = tbl.get(str(champion_id))
    if hit:
        return hit
    name = (champ_rec or {}).get("name") if isinstance(champ_rec, dict) else None
    if name:
        return tbl.get(str(name), frozenset())
    return frozenset()


def survivability_item_ids_enchanter(
    champion_id: str, champ_rec: Optional[dict] = None
) -> frozenset[str]:
    """RF2 enchanter/hps-lane WIN-anchored survivability item ids (empty if none).

    Consumed by the DEFAULT-OFF ``prefer_survivability_by_win`` seam in
    ``hps.rank_items_by_hps``. UNLIKE the RF1 hybrid lane, the hps scorer's
    ``enchanter_only`` pool EXCLUDES these HP/tank items (zero HPS throughput), so the
    seam must INJECT these ids into the candidate pool before floating them.
    """
    if not champion_id:
        return frozenset()
    tbl = _load_enchanter()
    hit = tbl.get(str(champion_id))
    if hit:
        return hit
    name = (champ_rec or {}).get("name") if isinstance(champ_rec, dict) else None
    if name:
        return tbl.get(str(name), frozenset())
    return frozenset()
