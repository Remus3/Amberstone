"""Item s8 - 6-axis full-roster loadout pollution + length sweep guard.

Operator-set invariants on data/champion_loadouts.json, parametrized
over every champion's collapsed variant (172 champs x sr/aram/arena):

1. LENGTH: every build_path items list and the variant-level ``items``
   mirror carry EXACTLY 7 entries on SR and 6 on ARAM + Arena. The
   length literals are pinned here on purpose - the guard must not
   silently follow a drifted TARGET_LEN constant. (Canonical-count
   finding: the JSON display-name lists are the source of truth;
   coaches.loadout_resolver derives item_ids from them at serve time,
   the /api/loadout/apply LCU item-set push sends the FULL list, and
   champ_select.js's slice(0, 6) caps are render/auto-push trims only.)

2. AXIS RULES: no row carries an item its archetype context forbids,
   per the conservative fact-driven rules in
   tools.champion_loadout_invariants.classify_row (action == "strip"
   only; ambiguous "report" candidates are allowed to exist). The carry
   axis set is additionally literal-pinned below (item-208 lineage + the
   item-s8 Divine Sunderer extension).

3. PINS: operator-pinned hand-curations are exempt (Corki SR "ad"
   Trinity Force + its primary mirror; Pantheon's Sup Roam Umbral Glaive
   is exempt by the range gate itself at 175).

4. MIRROR: the variant-level items list equals its primary build_path's
   items (the resolver + champ-select push read both).

Run ``$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/champion_loadout_sweep_item_s8.py`` if this trips.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOADOUTS_PATH = _ROOT / "data" / "champion_loadouts.json"

from core.daemon_slayer_client import champion_attackrange  # noqa: E402
from tools.champion_loadout_align import _detect_archetype  # noqa: E402
from tools.champion_loadout_invariants import classify_row  # noqa: E402

# Pinned literals on purpose (see module docstring).
TARGET_LEN_PINNED = {"sr": 7, "aram": 6, "arena": 6}
CARRY_FLAGGED_PINNED = frozenset({
    "Trinity Force",
    "Bastionbreaker",
    "Heartsteel",
    "Umbral Glaive",
    "Divine Sunderer",
})
RANGED_FLOOR_PINNED = 350.0

OPERATOR_PINNED_ROWS = frozenset({
    ("Corki", "sr-collapsed", "ad"),
})


def _load() -> dict:
    return json.loads(_LOADOUTS_PATH.read_text(encoding="utf-8"))


_DATA = _load()
_PARAMS = [
    (champ, vk)
    for champ, entry in (_DATA.get("champions") or {}).items()
    for vk, v in (entry.get("variants") or {}).items()
    if isinstance(v, dict) and v.get("_collapsed")
]


def _mode_of(vk: str) -> str:
    for m in ("sr", "aram", "arena"):
        if m in vk:
            return m
    return ""


def _variant(champ: str, vk: str) -> dict:
    return _DATA["champions"][champ]["variants"][vk]


@pytest.mark.parametrize(
    "champ,vk", _PARAMS, ids=[f"{c}-{vk}" for c, vk in _PARAMS]
)
def test_row_lengths_exact(champ: str, vk: str) -> None:
    v = _variant(champ, vk)
    target = TARGET_LEN_PINNED[_mode_of(vk)]
    bad = []
    for p in v.get("build_paths") or []:
        n = len(p.get("items") or [])
        if n != target:
            bad.append(f"{p.get('key')}: {n} items (want {target})")
    n_mirror = len(v.get("items") or [])
    if n_mirror != target:
        bad.append(f"(variant items mirror): {n_mirror} (want {target})")
    assert bad == [], f"{champ}|{vk}: {bad}"


@pytest.mark.parametrize(
    "champ,vk", _PARAMS, ids=[f"{c}-{vk}" for c, vk in _PARAMS]
)
def test_no_offclass_items_per_axis(champ: str, vk: str) -> None:
    v = _variant(champ, vk)
    mode = _mode_of(vk)
    rng = champion_attackrange(champ)
    bad = []
    for p in v.get("build_paths") or []:
        pk = str(p.get("key") or "")
        pinned = (champ, vk, pk) in OPERATOR_PINNED_ROWS
        arch = _detect_archetype(pk, p)
        items = [str(i) for i in (p.get("items") or [])]
        # Literal-pinned carry axis (does not trust production constants).
        if arch == "carry" and rng >= RANGED_FLOOR_PINNED and not pinned:
            for it in items:
                if it in CARRY_FLAGGED_PINNED:
                    bad.append(f"{pk}: carry-axis {it!r}")
        # Fact-driven axes (conservative strip rules only).
        for viol in classify_row(
            champ, mode, arch, items, attackrange=rng, pinned=pinned,
        ):
            if viol.action == "strip":
                bad.append(
                    f"{pk}: {viol.axis}-axis {viol.item!r} ({viol.reason})"
                )
    assert bad == [], f"{champ}|{vk}: {bad}"


@pytest.mark.parametrize(
    "champ,vk", _PARAMS, ids=[f"{c}-{vk}" for c, vk in _PARAMS]
)
def test_variant_items_mirror_primary_path(champ: str, vk: str) -> None:
    v = _variant(champ, vk)
    paths = v.get("build_paths") or []
    assert paths, f"{champ}|{vk}: no build_paths"
    assert list(v.get("items") or []) == list(paths[0].get("items") or []), (
        f"{champ}|{vk}: variant items mirror diverges from primary path"
    )


def test_parametrization_covers_full_roster() -> None:
    # 172 champions x 3 collapsed variants - a collapse-schema change
    # should be a conscious edit here, not a silent shrink of coverage.
    assert len(_PARAMS) == 172 * 3, len(_PARAMS)
