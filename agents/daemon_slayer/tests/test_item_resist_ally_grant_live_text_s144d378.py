"""S144-D-378..379 - the DS item resist-grant and item ally-grant registries match the live text they cite.

WHY. ``_item_resist_grants`` (R106 / R124 / R133 / R67 tail) and
``_item_ally_grant`` (Term A / R144) document their ids, maps, sources and
divergence evidence from the patch they were written at (16.13.1 / 16.14.1).
Their credit and mirror guards pin the VALUES; nothing pinned the prose to the
live snapshot, and each had drifted.

* S144-D-378 ``_item_resist_grants``: it put Terminus 3302 on maps
  "11 / 12 / 21 / 35" (live since 16.18.1: 11, 12 and 453) in a "706 items"
  index (live: 699). It called Shield of Molten Stone 443058 and Cloak of
  Starry Night 443059 "Meraki-absent"; Meraki carries both rows in every
  vendored dir 16.10.1..16.22.1, with the same 20% and a magnitude for the
  uncredited Block Chance / non-AA DR halves. It said "Meraki carries no mirror
  rows"; Meraki carries some 22xxxx rows, just none of the four mirrors here.
* S144-D-379 ``_item_ally_grant``: it quoted Knight's Vow 3109 as redirecting
  12% (Meraki's frozen 25.15 wording; live DDragon has said 14% since 16.11.1).
  It listed "Redemption amp 12% vs 10%" as Arena divergence evidence; the Arena
  223107 line reads 10%, equal to the base, since 16.18.1 (the curated
  ``enchanter_items.json`` already tracks that). It said ``name_to_id("Echoes of
  Helia", mode="sr")`` returns 326620; under the resolver's
  lowest-numeric-id-wins rule it returns the bare 6620 today.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Docstring
and comment fixes only; no registry value or code path changes, so scorer
output is byte-identical.
"""

from __future__ import annotations

import inspect
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _item_ally_grant as ally_mod
from agents.daemon_slayer import _item_resist_grants as resist_mod
from agents.daemon_slayer._item_resist_grants import _ITEM_RESIST_GRANTS

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"


def _patch() -> str:
    return (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _items() -> dict[str, Any]:
    raw = json.loads(
        (_DATA / _patch() / "items.json").read_text(encoding="utf-8")
    )
    return raw["data"]


@cache
def _meraki_body(patch: str) -> dict[str, Any]:
    raw = json.loads(
        (_DATA / patch / "items_meraki.json").read_text(encoding="utf-8")
    )
    return raw["items"]


@cache
def _enchanter() -> dict[str, Any]:
    raw = json.loads(
        (_DATA / _patch() / "enchanter_items.json").read_text(encoding="utf-8")
    )
    return raw["items"]


def _meraki_dirs() -> list[str]:
    return sorted(
        d.name for d in _DATA.iterdir() if (d / "items_meraki.json").is_file()
    )


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _desc(iid: str) -> str:
    return _plain(_items()[iid].get("description", ""))


def _maps(iid: str) -> list[str]:
    return sorted(
        (m for m, on in _items()[iid].get("maps", {}).items() if on), key=int
    )


def _hp(iid: str) -> float:
    return float(_items()[iid].get("stats", {}).get("FlatHPPoolMod", 0))


def _flat(text: str) -> str:
    return " ".join(text.split())


def _meraki_text(patch: str, iid: str, name: str) -> str:
    row = _meraki_body(patch)[iid]
    for block in list(row.get("passives") or []) + list(row.get("active") or []):
        if block.get("name") == name:
            return block.get("effects") or ""
    raise AssertionError(f"Meraki {patch} {iid} carries no {name!r} passive")


_RESIST_DOC = _flat(resist_mod.__doc__ or "")
_RESIST_SRC = _flat(inspect.getsource(resist_mod))
_ALLY_DOC = _flat(ally_mod.__doc__ or "")
_ALLY_SRC = _flat(inspect.getsource(ally_mod))


@pytest.mark.parametrize("doc", [_RESIST_DOC, _ALLY_DOC])
def test_docstring_cites_no_snapshot_line_numbers(doc: str) -> None:
    assert not re.search(r"items(?:_meraki)?\.json:\d", doc)


# --------------------------------------------------------------------------
# S144-D-378 - _item_resist_grants
# --------------------------------------------------------------------------


def test_resist_terminus_maps_match_live() -> None:
    assert _maps("3302") == ["11", "12", "453"]
    assert _maps("223302") == ["30"]
    assert "(maps 11 / 12 / 453)" in _RESIST_DOC
    assert "11 / 12 / 21 / 35" not in _RESIST_DOC
    assert "Nexus Blitz" not in _RESIST_DOC


def test_resist_index_size_matches_live() -> None:
    assert f"{len(_items())} items" in _RESIST_DOC
    assert "706 items" not in _RESIST_DOC


def test_resist_terminus_suffix_family_is_two_ids() -> None:
    assert {k for k in _items() if k.endswith("3302")} == {"3302", "223302"}
    assert {k for k in _meraki_body(_patch()) if k.endswith("3302")} == {"3302"}


@pytest.mark.parametrize("patch", _meraki_dirs())
@pytest.mark.parametrize(
    ("iid", "name"),
    [("443058", "Immovable as the Earth"), ("443059", "Limitless as the Stars")],
)
def test_resist_prismatic_rows_are_in_every_vendored_meraki(
    patch: str, iid: str, name: str
) -> None:
    assert "by {{as|20%|" in _meraki_text(patch, iid, name)


def test_resist_no_meraki_absent_claim_remains() -> None:
    assert "Meraki-absent" not in _RESIST_SRC
    assert "Meraki carries both rows" in _RESIST_SRC


def test_resist_meraki_prints_the_uncredited_secondary_magnitudes() -> None:
    p = _patch()
    stone = _meraki_text(p, "443058", "Immovable as the Earth")
    cloak = _meraki_text(p, "443059", "Limitless as the Stars")
    assert "5% per {{as|200 '''total''' armor}}" in stone
    assert "maximum of 50% chance" in stone
    assert "5% per {{as|200 '''total''' magic resistance}}" in cloak
    assert "maximum of 50% damage reduction" in cloak
    assert "5% per 200 total armor, up to 50%" in _RESIST_SRC
    assert "5% per 200 total MR, up to 50%" in _RESIST_SRC
    # DDragon still prints neither magnitude, so the rows stay uncredited.
    assert "200" not in _desc("443058")
    assert "Block Chance based on your Armor" in _desc("443058")


def test_resist_mirror_rows_are_not_in_meraki() -> None:
    body = _meraki_body(_patch())
    for iid in ("226665", "224401", "663058", "663059", "223302"):
        assert iid not in body
    assert any(k.startswith("22") for k in body)
    assert "Meraki carries no mirror rows" not in _RESIST_DOC
    assert "Meraki carries none of these four mirror rows" in _RESIST_DOC


@pytest.mark.parametrize(
    ("iid", "needle", "field", "value"),
    [
        ("6665", "Magic Resist by 30% until end of combat", "armor_pct", 30.0),
        ("226665", "Magic Resist by 40% until end of combat", "armor_pct", 40.0),
        ("4401", "Gain 70 Magic Resist", "mr", 70.0),
        ("224401", "gain 50 Magic Resist", "mr", 50.0),
        ("443058", "Increase your armor by 20%", "armor_pct", 20.0),
        ("663058", "Increase your armor by 20%", "armor_pct", 20.0),
        ("443059", "Increase your Magic Resist by 20%", "mr_pct", 20.0),
        ("663059", "Increase your Magic Resist by 10%", "mr_pct", 10.0),
    ],
)
def test_resist_registry_magnitudes_match_live_text(
    iid: str, needle: str, field: str, value: float
) -> None:
    assert needle in _desc(iid)
    assert getattr(_ITEM_RESIST_GRANTS[iid], field) == value


def test_resist_mirror_values_cite_the_live_patch() -> None:
    assert "and still at 16.22.1" in _RESIST_DOC


# --------------------------------------------------------------------------
# S144-D-379 - _item_ally_grant
# --------------------------------------------------------------------------


def test_ally_knights_vow_live_percent() -> None:
    assert "take 14% of the damage they receive" in _desc("3109")
    assert "take 14% of the damage they receive" in _desc("323109")
    assert "take 12% of the damage they receive" in _desc("223109")
    # Meraki (frozen at content patch 25.15) still prints the old 12%.
    assert "redirect 12% of the" in _meraki_text(_patch(), "3109", "Sacrifice")
    assert "redirect 12% of the pre-mitigation damage they take" not in _ALLY_DOC
    assert '"take 14% of the damage they receive"' in _ALLY_DOC


def test_ally_redemption_arena_amp_no_longer_diverges() -> None:
    assert "10% Heal and Shield Power" in _desc("223107")
    assert "10% Heal and Shield Power" in _desc("3107")
    assert _enchanter()["223107"]["heal_shield_amp_pct"] == 0.1
    assert _enchanter()["3107"]["heal_shield_amp_pct"] == 0.1
    assert "Redemption amp 12% vs 10%" not in _ALLY_DOC
    assert "Redemption's Arena amp" in _ALLY_DOC


@pytest.mark.parametrize(
    ("arena", "base", "arena_hp", "base_hp"),
    [("223190", "3190", 400.0, 200.0), ("223222", "3222", 400.0, 250.0),
     ("226620", "6620", 300.0, 200.0)],
)
def test_ally_held_divergence_evidence_still_live(
    arena: str, base: str, arena_hp: float, base_hp: float
) -> None:
    assert (_hp(arena), _hp(base)) == (arena_hp, base_hp)
    assert _maps(arena) == ["30"]


def test_ally_held_arena_rows_state_no_magnitude() -> None:
    for iid in ("223107", "223190", "223222", "226620"):
        assert not re.search(r"\d+ - \d+", _desc(iid)), iid


def test_ally_mikaels_amp_split_matches_live() -> None:
    assert "12% Heal and Shield Power" in _desc("3222")
    assert "15% Heal and Shield Power" in _desc("323222")
    assert "12% Heal and Shield Power" in _desc("223222")


def test_ally_resolver_hands_sr_the_bare_helia() -> None:
    from core.daemon_slayer_resolver import name_to_id

    assert name_to_id("Echoes of Helia", mode="sr") == "6620"
    assert _maps("326620") == ["11"]
    assert "lowest-numeric-id-wins" in _ALLY_DOC
    assert "now returns the bare ``6620``" in _ALLY_DOC


@pytest.mark.parametrize(
    ("mirror", "needle"),
    [
        ("323107", "Restore 150 - 350 Health to allied units"),
        ("323190", "290 - 360 Shield that decays over 2.5 seconds"),
        ("323222", "restore 100 - 250 Health"),
        ("326620", "Healing or Shielding an ally consumes all Soul Charges"),
    ],
)
def test_ally_mirror_sources_still_quote_live(mirror: str, needle: str) -> None:
    source = ally_mod._ALLY_GRANT_MIRROR_SOURCE[mirror]
    assert needle in _desc(mirror)
    assert needle in _desc(source)


def test_ally_exclusion_families_match_live_catalog() -> None:
    for suffix, expected in (
        ("3109", {"3109", "223109", "323109"}),
        ("3050", {"3050", "223050", "323050"}),
        ("2524", {"2524", "222524"}),
        ("3876", {"3876"}),
    ):
        got = {k for k in _items() if k.endswith(suffix) and len(k) in (4, 6)}
        assert got == expected, suffix
        assert expected <= ally_mod._ALLY_GRANT_EXCLUDED_ITEM_IDS
    assert "16.14.1 and still at 16.22.1" in _ALLY_DOC
