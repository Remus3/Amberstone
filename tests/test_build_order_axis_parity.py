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
    payload = bop.load_build_order_precompute("sr")
    if not payload.get("build_orders"):
        pytest.skip("HZ-B1 build_orders SR table absent (run build_order_precompute)")
    return payload


@pytest.fixture(scope="module")
def axes() -> dict[str, str]:
    return _item_axes()


@pytest.mark.parametrize("champ", FLIPPED)
def test_mixed_build_axis_matches_kit(champ, table, axes):
    ap._invalidate_axis_cache()
    # An operator user_cs pick deliberately re-tags a champion's archetype (e.g.
    # bruiser Katarina), so the committed precompute build legitimately follows
    # the picked archetype's axis, not the kit axis. This guard protects the
    # DEFAULT kit-axis builds; skip champs the operator overrode. The separate
    # bruiser-scorer-is-not-axis-aware-for-AP-kits case is tracked in BACKLOG.
    if ap.get_archetype_for(champ).get("source") != "default":
        pytest.skip(f"{champ} has an operator archetype pick; kit-axis guard is default-only")
    champ_id = ap.canonical_champion_id(champ)
    order = (bop.lookup(table, champ_id, "mixed") or {}).get("order") or []
    assert order, f"{champ}: mixed build order is empty"
    built = _dominant_axis(order, axes)
    kit = ap.kit_damage_axis(champ)
    assert built == kit, (
        f"{champ}: built {built}-dominant but kit axis is {kit} (order={order})"
    )
