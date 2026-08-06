"""Starter-tier floor guard for every committed Lane B build-order table.

WHY THIS EXISTS (measured 2026-08-06)
-------------------------------------
Lane B wants the build half of coaching to be a LOOKUP into a precomputed
Daemon Slayer table instead of a live Haiku call. Coverage is already saturated
and machine-guarded (tests/test_build_order_coverage_guard.py, floor 1.0) and
map legality is pinned (tests/test_build_order_map_legality.py). The remaining
way for these tables to be WRONG rather than MISSING is item TIER: a shipped
6-slot order that contains a 400-950g STARTER item instead of a legendary.

Nothing prevented that, and nothing detected it. STARTER items pass every
filter in the engine's candidate pool - ``agents/daemon_slayer/rank.py:747``
``_eligible_items`` denies already-equipped / non-coachable / off-map /
non-terminal / over-budget ids, and a starter is none of those. Doran's Helm
(1120, 450g), Doran's Bow (1086, 400g), Cull (1083, 450g) and Guardian's Blade
(3177, 950g) are purchasable, terminal (``into`` empty) and map-legal, so they
sit in the pool of every scorer in every mode right now.

Today's tables are clean only as an ACCIDENT of the ordering metric. The order
is planned by ``core/build_order.py`` ``plan_build_order`` with
``sort_by="delta"`` (absolute gain), and a 450g starter never wins an absolute-
gain comparison against a 3000g legendary. Flip that one already-transported
flag to the engine's other shipped ordering metric - ``sort_by="efficiency"``
(gain per gold, implemented on all 7 scorers, transported as body key ``sort``
through ``core/daemon_slayer_client.py`` to ``agents/daemon_slayer/server.py``)
- and starters immediately win, because stat-per-gold is exactly what a starter
maximizes. MEASURED over a 15-champion x 4-comp-archetype static sweep: 52 of
60 cells changed, and the efficiency orders pulled Doran's Helm, Doran's Bow
and Guardian's Blade into slots 3-5 of the final build.

So the invariant this guard pins is a real one that is one flag away from being
violated across all 2076 comp-archetype cells at once, and a wrong precompute
is worse than the Haiku call it is meant to replace.

THE RULE, DERIVED FROM THE ITEM DATA (not assumed)
--------------------------------------------------
``core.build_order_precompute.is_starter_tier`` classifies on the Meraki /
DDragon bulk that is already the source of truth for item metrics: the ``Lane``
tag plus a gold ceiling. Measured over the whole 16.15.1 registry, 78 items
carry ``Lane``:

  * 76 of them cost under 1000g and are ALL genuinely starter tier - the
    Doran's line, Cull, Dark Seal, the Guardian's line, the support-quest
    starters, potions, trinkets and the zero-gold quest markers.
  * exactly 2 cost 1000g or more: Atma's Reckoning (223039 / 663039, 2500g),
    a real legendary that happens to carry the tag.

The threshold therefore sits in a genuine empty band - the dearest starter is
950g, the cheapest ``Lane``-tagged legendary is 2500g - rather than splitting a
continuum. It is NOT a depth test: the mode-mirror namespaces (22xxxx Arena /
44xxxx / 66xxxx) ship ``depth: None`` with a flattened 2500-2750g price, so
``depth >= 2`` would flag 71 of the 138 currently-shipped ids, including every
Arena mirror legendary and every upgraded boot.

COVERAGE - all THREE table families x all three modes, the same universe the
sibling map-legality guard walks:
  * flat       data/daemon_slayer/<patch>/build_orders_<mode>.json (damage axis)
  * precompute data/daemon_slayer/build_orders/<patch>/build_orders_<mode>.json
  * variants   data/daemon_slayer/build_orders/<patch>/build_order_variants_<mode>.json

ASCII only.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core import build_order_precompute as bop
from core import build_order_variants as bov

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTENT_KEY = "build_orders"
_MODE_KEYS = ("sr", "aram", "arena")
_FAMILIES = ("flat", "precompute", "variants")
_TABLES = [(family, mode) for family in _FAMILIES for mode in _MODE_KEYS]
_TABLE_IDS = [f"{family}-{mode}" for family, mode in _TABLES]

# A walk that collected no slots would pass the starter assertion vacuously.
# Every real table carries thousands of slots (173 champions x 2-4 axis classes
# x 6 slots); this floor only catches a traversal that silently found nothing.
# Mirrors the _ID_FLOOR rationale in tests/test_build_order_map_legality.py.
_SLOT_FLOOR = 500

# Ids used as fixed reference points for the classifier. Each is asserted
# against the SHIPPED catalog record, never against a hardcoded gold value, so
# a patch that re-prices an item re-derives the expectation instead of going
# stale. Chosen as the boundary cases the measurement above turned up.
_KNOWN_STARTERS = ("1120", "1086", "1083", "3177", "1082", "2003")
_KNOWN_NON_STARTERS = (
    "3089",    # Rabadon's Deathcap - plain legendary, no Lane tag
    "3006",    # Berserker's Greaves - upgraded boots, a legal order slot
    "223039",  # Atma's Reckoning - Lane-tagged but 2500g, above the ceiling
    "223089",  # Arena mirror legendary - depth None, must not be misread
)


def _items_catalog(patch: str) -> dict:
    path = _REPO_ROOT / "data" / "daemon_slayer" / patch / "items.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _load_table(family: str, mode_key: str, patch: str) -> dict:
    if family == "precompute":
        return bop.load_build_order_precompute(mode=mode_key, patch=patch)
    if family == "variants":
        return bov.load_build_order_variants(mode=mode_key, patch=patch)
    path = (
        _REPO_ROOT / "data" / "daemon_slayer" / patch
        / f"build_orders_{mode_key}.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _starter_slots(payload: dict, items: dict) -> list[tuple[str, str, str]]:
    """Return ``[(champion, axis_class, item_id), ...]`` for every ORDER slot
    holding a starter-tier item. Shared by the guard and its positive control so
    both exercise one detector."""
    hits: list[tuple[str, str, str]] = []
    for champ, axis, item_id in bop.iter_order_item_ids(payload):
        if bop.is_starter_tier(items.get(item_id)):
            hits.append((champ, axis, item_id))
    return hits


@pytest.mark.parametrize(("family", "mode_key"), _TABLES, ids=_TABLE_IDS)
def test_no_shipped_order_slot_is_starter_tier(family: str, mode_key: str) -> None:
    """No committed build-order slot may hold a starter-tier item."""
    patch = bop.resolve_patch()
    items = _items_catalog(patch)
    payload = _load_table(family, mode_key, patch)
    content = payload.get(_CONTENT_KEY)
    assert isinstance(content, dict) and content, (
        f"{family} {mode_key}: content key {_CONTENT_KEY!r} missing or empty"
    )

    slots = list(bop.iter_order_item_ids(payload))
    assert len(slots) >= _SLOT_FLOOR, (
        f"{family} {mode_key}: walked only {len(slots)} order slots (floor "
        f"{_SLOT_FLOOR}) - the traversal stopped finding orders, so a "
        f"starter-tier pass here would be vacuous"
    )

    hits = _starter_slots(payload, items)
    assert not hits, (
        f"{family} {mode_key}: {len(hits)} order slot(s) hold a starter-tier "
        "item. A full build must not contain a starter: "
        + ", ".join(
            f"{champ}/{axis} -> {iid} "
            f"({(items.get(iid) or {}).get('name', '?')})"
            for champ, axis, iid in hits[:8]
        )
        + ". Most likely cause: the ordering metric was changed off "
        "sort_by='delta' (gain per gold ranks a 450g starter above a "
        "legendary). Regen with the delta metric, or exclude starter-tier ids "
        "from the pool before shipping another metric."
    )


@pytest.mark.parametrize("mode_key", _MODE_KEYS)
def test_guard_fires_on_a_planted_starter(mode_key: str) -> None:
    """Positive control - the guard above must not be vacuous.

    Plants a known starter into one order of a real shipped payload and asserts
    the SAME detector reports exactly that slot. Without this, a detector that
    silently found nothing would keep the guard green forever.
    """
    patch = bop.resolve_patch()
    items = _items_catalog(patch)
    payload = copy.deepcopy(_load_table("precompute", mode_key, patch))
    assert not _starter_slots(payload, items), "fixture payload is already dirty"

    champ = sorted(payload[_CONTENT_KEY])[0]
    axis = sorted(payload[_CONTENT_KEY][champ])[0]
    cell = payload[_CONTENT_KEY][champ][axis]
    planted = "1120"  # Doran's Helm - terminal, purchasable, map-legal, 450g
    cell["order"] = list(cell["order"])[:-1] + [planted]

    hits = _starter_slots(payload, items)
    assert hits == [(champ, axis, planted)], (
        f"{mode_key}: planted starter {planted} in {champ}/{axis} but the "
        f"detector reported {hits!r}"
    )


@pytest.mark.parametrize("item_id", _KNOWN_STARTERS)
def test_known_starter_is_classified_starter_tier(item_id: str) -> None:
    """Every reference starter classifies as starter tier, and the SHIPPED
    catalog record still satisfies both halves of the documented rule (Lane tag
    AND gold below the ceiling) - so a re-priced patch fails here loudly instead
    of quietly weakening the guard above."""
    items = _items_catalog(bop.resolve_patch())
    rec = items.get(item_id)
    assert rec is not None, f"{item_id} is absent from the item catalog"
    tags = rec.get("tags") or []
    gold = int((rec.get("gold") or {}).get("total") or 0)
    assert bop.STARTER_TIER_TAG in tags, (
        f"{item_id} ({rec.get('name')}) no longer carries the "
        f"{bop.STARTER_TIER_TAG!r} tag: {tags}"
    )
    assert gold < bop.STARTER_TIER_GOLD_CEILING, (
        f"{item_id} ({rec.get('name')}) costs {gold}g, at or above the "
        f"{bop.STARTER_TIER_GOLD_CEILING}g starter ceiling"
    )
    assert bop.is_starter_tier(rec) is True


@pytest.mark.parametrize("item_id", _KNOWN_NON_STARTERS)
def test_known_legendary_is_not_classified_starter_tier(item_id: str) -> None:
    """Legendaries, upgraded boots and the Lane-tagged 2500g outlier must all
    stay OUT of the starter class - the guard is worthless if it flags the items
    a build order is supposed to contain."""
    items = _items_catalog(bop.resolve_patch())
    rec = items.get(item_id)
    assert rec is not None, f"{item_id} is absent from the item catalog"
    assert bop.is_starter_tier(rec) is False, (
        f"{item_id} ({rec.get('name')}) was misclassified as starter tier"
    )


def test_starter_ceiling_sits_in_an_empty_price_band() -> None:
    """The ceiling must not split a continuum.

    Re-derives the measurement the rule was built on: partition every
    ``Lane``-tagged item in the shipped catalog by the ceiling and assert a real
    GAP separates the two groups. If a patch ever prices a starter at 1100g or a
    Lane-tagged legendary at 900g, the threshold has stopped being a clean
    separator and this fails rather than silently misclassifying.
    """
    items = _items_catalog(bop.resolve_patch())
    below: list[int] = []
    above: list[int] = []
    for rec in items.values():
        if not isinstance(rec, dict):
            continue
        if bop.STARTER_TIER_TAG not in (rec.get("tags") or []):
            continue
        gold = int((rec.get("gold") or {}).get("total") or 0)
        (below if gold < bop.STARTER_TIER_GOLD_CEILING else above).append(gold)

    assert below and above, (
        f"Lane-tagged partition is degenerate: {len(below)} below / "
        f"{len(above)} above the {bop.STARTER_TIER_GOLD_CEILING}g ceiling - "
        "one side is empty, so the ceiling is untested by real data"
    )
    assert max(below) < min(above), (
        f"the {bop.STARTER_TIER_GOLD_CEILING}g ceiling no longer separates a "
        f"gap: dearest sub-ceiling Lane item is {max(below)}g, cheapest "
        f"at-or-above is {min(above)}g"
    )


def test_iter_order_item_ids_handles_both_leaf_shapes() -> None:
    """The two committed leaf shapes must both be walked.

    The flat damage-axis family stores a bare LIST of ids per axis class while
    the precompute and variants families store ``{"order": [...]}``. A walker
    that understood only one shape would silently skip a whole family and take
    the guard above with it.
    """
    bare = {"build_orders": {"Ahri": {"balanced": ["3089", "3111"]}}}
    wrapped = {"build_orders": {"Ahri": {"mixed": {"order": ["3089", "3111"]}}}}
    assert list(bop.iter_order_item_ids(bare)) == [
        ("Ahri", "balanced", "3089"), ("Ahri", "balanced", "3111"),
    ]
    assert list(bop.iter_order_item_ids(wrapped)) == [
        ("Ahri", "mixed", "3089"), ("Ahri", "mixed", "3111"),
    ]


@pytest.mark.parametrize("payload", [
    {}, None, {"build_orders": None}, {"build_orders": {"Ahri": None}},
    {"build_orders": {"Ahri": {"mixed": None}}},
    {"build_orders": {"Ahri": {"mixed": {"order": None}}}},
    {"build_orders": {"Ahri": {"mixed": {"order": [None, ""]}}}},
])
def test_iter_order_item_ids_is_total_on_malformed_payloads(payload) -> None:
    """A malformed table yields nothing rather than raising - the walker is used
    by producers on the read side, where every Lane B surface fails soft."""
    assert list(bop.iter_order_item_ids(payload)) == []


@pytest.mark.parametrize("record", [
    None, {}, "3089", 3089, [], {"tags": "Lane"},
    {"tags": ["Lane"]}, {"tags": ["Lane"], "gold": None},
    {"tags": ["Lane"], "gold": {}}, {"tags": ["Lane"], "gold": {"total": None}},
    {"tags": ["Lane"], "gold": {"total": "cheap"}},
])
def test_is_starter_tier_is_total_on_malformed_records(record) -> None:
    """An unparseable record is NOT classified as starter tier - unknown never
    becomes a positive, so a data glitch cannot redden the guard by itself."""
    assert bop.is_starter_tier(record) is False
