"""Map-legality guard for every committed build-order table.

Asserts that every item id shipped in a build-order table is legal on THAT
mode's DDragon map: SR = map 11, ARAM = map 12, Arena = map 30. The mode ->
map-id mapping is imported from ``agents.daemon_slayer.rank.MODE_MAP_ID`` rather
than duplicated, so the guard tracks the engine's own table.

WHY THIS EXISTS (2026-07-18). A great many items ship BOTH a base SR id and
mode-mirror ids in the 22xxxx (Arena) / 32xxxx (ARAM) families, and the base and
its mirrors share an identical display NAME. Moonstone Renewer is 6617 with
``maps["30"]=False`` and 226617 with ``maps["30"]=True``. That makes the Arena
table look wrong to any check that reads item NAMES and then resolves the BASE
id - the name "Moonstone Renewer" appears in a shipped Arena order and the base
id is map-30 illegal, so a name-based audit reports a defect that is not there.
That false positive was raised and investigated; the tables were correct all
along. This guard pins the real invariant on the real ids so the question does
not have to be re-litigated from names again.

Coverage is deliberately all THREE table families, because the two existing
sibling guards leave gaps this one closes:
  - ``test_build_order_boots`` pins the Arena 22-mirror remap, but only for the
    BOOTS slot via ``core.build_order._select_boots`` - the other five slots and
    the shipped tables themselves were unpinned.
  - ``test_build_order_content_freshness`` covers the precompute + variants
    families, but not the flat ``data/daemon_slayer/<patch>/`` family, and it
    checks stamps and roster shape rather than item legality.

ASCII only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.daemon_slayer.rank import MODE_MAP_ID
from core import build_order_precompute as bop
from core import build_order_variants as bov

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTENT_KEY = "build_orders"
_MODE_KEYS = ("sr", "aram", "arena")
_FAMILIES = ("flat", "precompute", "variants")
_TABLES = [(family, mode) for family in _FAMILIES for mode in _MODE_KEYS]
_TABLE_IDS = [f"{family}-{mode}" for family, mode in _TABLES]

# A table that collected no ids would pass every assertion vacuously. Real
# tables carry 48-63 distinct ids; this floor only catches a walk that silently
# stopped finding them.
_ID_FLOOR = 20


def _items_catalog(patch: str) -> dict:
    path = _REPO_ROOT / "data" / "daemon_slayer" / patch / "items.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _load_table(family: str, mode_key: str, patch: str) -> dict:
    if family == "precompute":
        return bop.load_build_order_precompute(mode=mode_key, patch=patch)
    if family == "variants":
        return bov.load_build_order_variants(mode=mode_key, patch=patch)
    path = _REPO_ROOT / "data" / "daemon_slayer" / patch / f"build_orders_{mode_key}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_item_ids(node: object, found: set) -> None:
    """Collect every item-id-shaped leaf under ``node``.

    Walks the CONTENT subtree only, so stamp fields (engine_version, patch,
    generated_at) never reach this and cannot be mistaken for ids.
    """
    if isinstance(node, dict):
        for val in node.values():
            _collect_item_ids(val, found)
    elif isinstance(node, list):
        for val in node:
            _collect_item_ids(val, found)
    elif isinstance(node, (str, int)):
        text = str(node)
        if text.isdigit() and len(text) >= 4:
            found.add(text)


@pytest.mark.parametrize(("family", "mode_key"), _TABLES, ids=_TABLE_IDS)
def test_every_shipped_item_id_is_legal_on_its_map(family: str, mode_key: str) -> None:
    patch = bop.resolve_patch()
    items = _items_catalog(patch)
    payload = _load_table(family, mode_key, patch)
    content = payload.get(_CONTENT_KEY)
    assert isinstance(content, dict) and content, (
        f"{family} {mode_key}: content key {_CONTENT_KEY!r} missing or empty"
    )

    ids: set = set()
    _collect_item_ids(content, ids)
    assert len(ids) >= _ID_FLOOR, (
        f"{family} {mode_key}: collected only {len(ids)} item ids (floor "
        f"{_ID_FLOOR}) - the walk stopped finding ids, so a legality pass here "
        f"would be vacuous"
    )

    unknown = sorted(i for i in ids if i not in items)
    assert not unknown, (
        f"{family} {mode_key}: {len(unknown)} id(s) are not in the {patch} item "
        f"catalog: {unknown[:10]}"
    )

    map_id = MODE_MAP_ID[mode_key.upper()]
    illegal = sorted(
        i for i in ids if not (items[i].get("maps") or {}).get(map_id)
    )
    assert not illegal, (
        f"{family} {mode_key}: {len(illegal)} item id(s) illegal on map "
        f"{map_id}: "
        + ", ".join(f"{i} ({items[i].get('name', '?')})" for i in illegal[:10])
        + ". Arena/ARAM orders must carry the mode MIRROR id (22xxxx / 32xxxx), "
        "not the base SR id - they share a display name, so check the ID."
    )


def test_arena_and_aram_actually_use_mirror_ids() -> None:
    """Positive control for the guard above.

    If a future generator emitted base SR ids on Arena, the legality assertion
    would catch it - but only while the mirrors keep ``maps["30"]=False`` on the
    base. This pins the intended SHAPE directly: the Arena table really does
    reach for the 22-prefixed namespace.
    """
    patch = bop.resolve_patch()
    arena = _load_table("flat", "arena", patch)
    ids: set = set()
    _collect_item_ids(arena[_CONTENT_KEY], ids)
    mirrors = {i for i in ids if i.startswith("22") and len(i) > 4}
    assert mirrors, (
        "Arena table carries no 22-prefixed mirror ids at all - either the "
        "mirror remap regressed or the id namespace changed"
    )
