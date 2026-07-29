"""Backfill - strip the ranged-only Runaan's Hurricane from MELEE champions'
static loadouts (data/champion_loadouts.json), data-only + atomic + idempotent.

Root cause + carry
------------------
The live DS scorer gained a melee ranged-only purchasability gate on 2026-07-02
(agents/daemon_slayer/rank.py RANGED_ONLY_ITEM_IDS, applied in
_filter_candidates). The parallel STATIC-loadout serve path
(coaches/loadout_resolver.py) got the symmetric serve-time gate on 2026-07-12,
which fixes the champ-select chooser + the item-1 LCU item-set push at runtime.
This tool completes the fix per the CLAUDE.md "Data Fixes" rule: the corrupted
rows at rest (74 melee served-builds across ~50 champions carrying Runaan's
Hurricane, an item melee cannot buy) are backfilled so the source data is
honest and a raw-data CI guard can catch any future re-pollution. Operator
observed the bug live 2026-07-11 (Xin Zhao; the report named "Terminus", a
conflation with the Runaan's Hurricane + Yun Tal Wildarrows actually carried in
Xin Zhao's sr jg-bruiser build).

Constraints honored (all enforced by existing guards - see
tests/test_loadout_sweep_guard_item_s8.py + test_champion_loadouts_no_unique_
clash.py):
  * LENGTH: replace Runaan's 1:1 (never drop) so SR stays 7 items, ARAM/Arena 6.
  * MIRROR: variant-level items are resynced to the primary build_path.
  * AXIS: replacement is archetype-aware (assassin/lethality -> a lethality
    item; bruiser/carry/on-hit -> an on-hit / attack-speed item) and never a
    heal/shield item, so classify_row (the s8 axis guard) is satisfied.
  * NO CLASH: every candidate is outside the 7 unique-passive families, so
    the no-unique-clash guard cannot trip.
  * NO DUP: the first candidate not already in the row is used.

Idempotent: a second run finds no Runaan's on any melee row and is a no-op.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.daemon_slayer._melee_ranged import (  # noqa: E402
    MELEE_RANGED_ATTACKRANGE_SPLIT,
    attackrange_is_ranged,
)
from core.daemon_slayer_client import champion_attackrange  # noqa: E402
from tools.champion_loadout_align import _detect_archetype  # noqa: E402

_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Runaan's Hurricane display name(s) as they appear in the loadout lists.
_RUNAAN = "Runaan's Hurricane"

# Melee = base attackrange BELOW the shared canonical split (350, RM-123 -
# mirrors rank.MELEE_ATTACKRANGE_CEILING + loadout_resolver + _melee_ranged).
_MELEE_CEILING = MELEE_RANGED_ATTACKRANGE_SPLIT

# Archetype-aware, melee-legal replacement chains. Every entry is outside the 7
# unique-passive families and is NOT a heal/shield item, so the axis + clash
# guards pass for every polluted archetype (bruiser / assassin / carry). The
# first candidate not already present in the row is used (avoids a duplicate).
_ONHIT_CHAIN = [
    "Kraken Slayer", "Wit's End", "Guinsoo's Rageblade",
    "Phantom Dancer", "Terminus", "Blade of The Ruined King",
]
_LETHALITY_CHAIN = [
    "The Collector", "Axiom Arc", "Serylda's Grudge",
    "Youmuu's Ghostblade", "Edge of Night", "Opportunity",
]


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _is_melee(champ: str) -> bool:
    try:
        return not attackrange_is_ranged(float(champion_attackrange(champ)))
    except (TypeError, ValueError):
        return False


def _pick_replacement(path_key: str, path: dict, items: list[str]) -> str:
    arch = _detect_archetype(str(path_key or ""), path)
    chain = _LETHALITY_CHAIN if arch == "assassin" else _ONHIT_CHAIN
    present = {_norm(x) for x in items}
    for cand in chain:
        if _norm(cand) not in present:
            return cand
    raise RuntimeError(
        f"no free replacement for {path_key!r} (all candidates present): {items}"
    )


def _fix_items(path_key: str, path: dict, items: list[str]) -> list[str]:
    """Replace every Runaan's occurrence in a single item list 1:1."""
    if not any(_norm(x) == _norm(_RUNAAN) for x in items):
        return list(items)
    out = list(items)
    for i, it in enumerate(out):
        if _norm(it) == _norm(_RUNAAN):
            out[i] = _pick_replacement(path_key, path, out)
    return out


def apply(data: dict) -> int:
    champs = data.get("champions") or {}
    touched = 0
    for champ, cd in champs.items():
        if not _is_melee(champ):
            continue
        for _vk, var in (cd.get("variants") or {}).items():
            changed = False
            for p in var.get("build_paths") or []:
                if not isinstance(p, dict):
                    continue
                new_items = _fix_items(p.get("key"), p, list(p.get("items") or []))
                if new_items != list(p.get("items") or []):
                    p["items"] = new_items
                    changed = True
                    touched += 1
            # Resync the variant-level items mirror to the primary path (the
            # s8 mirror guard requires variant.items == primary path items).
            paths = var.get("build_paths") or []
            if paths:
                prim = next(
                    (p for p in paths if p.get("_is_primary")), paths[0]
                )
                if list(var.get("items") or []) != list(prim.get("items") or []):
                    var["items"] = list(prim.get("items") or [])
                    changed = True
            elif any(_norm(x) == _norm(_RUNAAN) for x in (var.get("items") or [])):
                # Pathless variant: fix the mirror list directly.
                var["items"] = _fix_items(
                    "", var, list(var.get("items") or [])
                )
                touched += 1
                changed = True
            if changed:
                pass
    return touched


def main() -> None:
    data = json.loads(_LOADOUTS.read_text(encoding="utf-8"))
    n = apply(data)
    tmp = _LOADOUTS.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp, _LOADOUTS)
    print(f"ranged-only melee backfill applied: {n} item list(s) fixed")


if __name__ == "__main__":
    main()
