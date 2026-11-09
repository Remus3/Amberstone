"""s156 S3 (C4): champion archetype groupings held to the tracked DDragon roster.

core/archetype_picks.py maps DDragon class tags to the scorer archetypes and
layers curated rosters on top (AP burst assassins, on-hit AP, support routes,
the default-OFF ARAM win-axis override table). A new champion or a retag in
a DDragon bump must never land on the unknown-tag fallback silently, and a
curated roster must never name a champion DDragon does not ship.

Audit at 16.22.1 (2026-11-08): 173 champions, tag universe {Assassin,
Fighter, Mage, Marksman, Support, Tank} all mapped; Locke (new since 16.12.1)
resolves mage/assassin on an AP axis; Zaahen retag (Fighter+Assassin ->
Fighter) changes only its alt-view. Three ARAM override rows were written
against a default that has since moved (KNOWN_STALE_ARAM_OVERRIDES below);
the seam is default-OFF with no production consumer, so they are recorded,
not rewritten.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import archetype_picks as ap

_REPO = Path(__file__).resolve().parent.parent
_ROUTABLE = set(ap.IMPLEMENTED_SCORERS) | {"onhit"}

# Rows of core/aram_archetype_override.json whose recorded default_primary no
# longer matches today's default (Kayle / KogMaw moved to onhit with the
# on-hit-AP roster; Taric moved to tank with the support-route roster, which
# makes his row a no-op). Shrink-only: a NEW stale row fails the test.
KNOWN_STALE_ARAM_OVERRIDES = frozenset({"Kayle", "KogMaw", "Taric"})


def _champs() -> dict:
    raw = json.loads((_REPO / "data" / "meta" / "ddragon_champions.json")
                     .read_text(encoding="utf-8"))
    return raw.get("data", raw)


def test_every_ddragon_tag_has_an_archetype():
    tags = {t for c in _champs().values() for t in c.get("tags", [])}
    assert tags, "empty roster would pass vacuously"
    unmapped = sorted(t for t in tags if t.lower() not in ap._TAG_TO_ARCHETYPE)
    assert not unmapped, unmapped


def test_every_champion_is_tagged_and_routes_to_a_scorer():
    champs = _champs()
    assert len(champs) >= 170
    bad = {}
    for cid, c in champs.items():
        if not c.get("tags"):
            bad[cid] = "untagged"
            continue
        primary, secondary = ap.default_for_champion(cid)
        if primary not in _ROUTABLE or secondary not in _ROUTABLE:
            bad[cid] = (primary, secondary)
        # The display name must resolve to the same default as the id.
        if ap.default_for_champion(c["name"]) != (primary, secondary):
            bad[cid] = ("name/id disagree", c["name"])
    assert not bad, bad


@pytest.mark.parametrize("roster_name,roster", [
    ("_AP_ASSASSIN_IDS", lambda: ap._AP_ASSASSIN_IDS),
    ("onhit_ap_roster", lambda: set(ap.load_onhit_ap_roster())),
    ("support_route_overrides", lambda: set(ap.load_support_route_overrides())),
])
def test_curated_rosters_name_real_champions(roster_name, roster):
    champs = _champs()
    names = {c["name"] for c in champs.values()}
    members = set(roster())
    assert members, f"{roster_name} is empty"
    ghosts = sorted(m for m in members if m not in champs and m not in names)
    assert not ghosts, (roster_name, ghosts)


def test_aram_override_rows_name_real_champions_and_routable_archetypes():
    doc = json.loads((_REPO / "core" / "aram_archetype_override.json")
                     .read_text(encoding="utf-8"))
    champs = _champs()
    for name, row in doc["champions"].items():
        assert name in champs, name
        assert row["override"] in ap.ARCHETYPE_SET, name


def test_stale_aram_override_rows_do_not_grow():
    doc = json.loads((_REPO / "core" / "aram_archetype_override.json")
                     .read_text(encoding="utf-8"))
    stale = {name for name, row in doc["champions"].items()
             if ap.default_for_champion(name)[0] != row["default_primary"]}
    assert stale <= KNOWN_STALE_ARAM_OVERRIDES, sorted(stale - KNOWN_STALE_ARAM_OVERRIDES)
