"""P6 lolmath parity - regenerated build_orders carry the kit damage axis.

End-to-end guard over the HZ-B1 ``build_orders_sr.json`` ``mixed`` cell (the
variant the lolmath-vs-DS sweep flagged): each champion the axis correction
re-based must now build a dominant item axis that matches its kit's
``lolmath.damage_distribution``. Item axis is read from items.json stats
(``FlatMagicDamageMod`` -> AP, ``FlatPhysicalDamageMod`` -> AD); hybrid / neither
items (boots, crit-only, on-hit) are neutral and do not vote.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import archetype_picks as ap
from core import build_order_precompute as bop

# The shipped-table gate lives in the HZ-B1 suite (one implementation, not
# seven copies). Importing the FUNCTION by name binds only that name, so the
# sibling module's TestCase classes are not collected a second time here.
from tests.test_build_order_precompute import load_shipped_table

_ROOT = Path(__file__).resolve().parent.parent

# Every champion the kit-axis correction re-based (see test_archetype_axis_correction).
# Listed by DDragon DISPLAY name for readability; the build_orders tables are
# canonical-keyed (the HZ canonical-keyspace fix), so the table lookup below
# canonicalizes the name first. kit_damage_axis accepts either form.
FLIPPED = [
    "Gwen", "Teemo", "Rumble", "Diana", "Mordekaiser", "Kog'Maw", "Nidalee",
    "Elise", "Gragas", "Lillia", "Akali", "Ekko", "Evelynn", "Fizz",
    "Kassadin", "Katarina", "LeBlanc", "Pyke",
]


def _item_axes() -> dict[str, str]:
    path = _ROOT / "data" / "daemon_slayer" / bop.resolve_patch() / "items.json"
    data = json.loads(path.read_text(encoding="utf-8")).get("data", {})
    out: dict[str, str] = {}
    for iid, entry in data.items():
        stats = (entry or {}).get("stats") or {}
        is_ap = "FlatMagicDamageMod" in stats
        is_ad = "FlatPhysicalDamageMod" in stats
        if is_ap and not is_ad:
            out[str(iid)] = "ap"
        elif is_ad and not is_ap:
            out[str(iid)] = "ad"
    return out


def _dominant_axis(order: list, axes: dict[str, str]) -> str | None:
    ad = sum(1 for i in order if axes.get(str(i)) == "ad")
    ap_ = sum(1 for i in order if axes.get(str(i)) == "ap")
    if ap_ > ad:
        return "ap"
    if ad > ap_:
        return "ad"
    return None


@pytest.fixture(scope="module")
def table() -> dict:
    # MEASURED 2026-07-26 (skip audit): this fixture used to call the fail-soft
    # production loader and `pytest.skip` on a falsey return, which silently
    # turned all 18 axis-parity assertions off whenever the SR table was absent
    # OR corrupt - the same empty dict for both. The axis correction this file
    # guards is re-applied at every patch regeneration, so the guard went quiet
    # in the one window it exists for. Absence may still skip; a table that is
    # on disk is now always read and always asserted.
    payload = load_shipped_table(
        bop._db_path("sr", bop.resolve_patch()), "HZ-B1 build_orders/sr",
    )
    assert payload.get("build_orders"), "HZ-B1 build_orders SR table has no rows"
    return payload


@pytest.fixture(scope="module")
def axes() -> dict[str, str]:
    return _item_axes()


@pytest.mark.parametrize("champ", FLIPPED)
def test_mixed_build_axis_matches_kit(champ, table, axes):
    ap._invalidate_axis_cache()
    # LEDGER 823: the operator archetype-pick UI was removed and
    # data/cs_archetype_picks.json cleared, so every champion now resolves to
    # its kit-axis default and this guard runs unconditionally. It doubles as a
    # pollution tripwire - a re-introduced user_cs pick that flips a champ off
    # its kit axis (e.g. Katarina->bruiser) would fail here. (The daafdd93
    # source != "default" skip is gone.)
    champ_id = ap.canonical_champion_id(champ)
    order = (bop.lookup(table, champ_id, "mixed") or {}).get("order") or []
    assert order, f"{champ}: mixed build order is empty"
    built = _dominant_axis(order, axes)
    kit = ap.kit_damage_axis(champ)
    assert built == kit, (
        f"{champ}: built {built}-dominant but kit axis is {kit} (order={order})"
    )
