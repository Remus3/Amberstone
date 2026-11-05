"""wiki_ability_stats apiname alias (RM-1341).

The sidecar keys each record by the wiki Template:Data TITLE ("Vel'Koz/Void
Rift"); callers pass the DDragon id ("Velkoz"). ``DataSnapshot`` now resolves a
record by title first and by ``"<apiname>/<ability>"`` second, so the 22
champions whose wiki name differs from their id are reachable. Derived from the
committed sidecar - no hand-kept champion list. ASCII only.
"""
from __future__ import annotations

import json
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot

_DATA = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"


def _records() -> dict:
    patch = (_DATA / "current.txt").read_text(encoding="utf-8").strip()
    doc = json.loads((_DATA / patch / "wiki_ability_stats.json").read_text(encoding="utf-8"))
    return doc["abilities"]


def _mismatched() -> list[tuple[str, str, str, dict]]:
    out = []
    for key, rec in _records().items():
        prefix, ability = key.split("/", 1)
        api = rec.get("apiname")
        if api and api != prefix:
            out.append((prefix, api, ability, rec))
    return out


def test_every_mismatched_record_is_reachable_by_apiname() -> None:
    snap = DataSnapshot.load()
    pairs = _mismatched()
    assert pairs, "no mismatched prefix: the sidecar changed shape, re-derive this guard"
    for prefix, api, ability, _rec in pairs:
        assert snap.ability_static_cd(api, ability) == snap.ability_static_cd(prefix, ability), (api, ability)
        assert snap.ability_recharge(api, ability) == snap.ability_recharge(prefix, ability), (api, ability)


def test_velkoz_w_recharge_and_leblanc_p_static_are_reachable() -> None:
    snap = DataSnapshot.load()
    assert snap.ability_recharge("Velkoz", "Void Rift") == [19.0, 18.0, 17.0, 16.0, 15.0]
    assert snap.ability_static_cd("Leblanc", "Mirror Image") == "60"


def test_title_key_still_wins_and_unknown_is_none() -> None:
    snap = DataSnapshot.load()
    assert snap.ability_recharge("Vel'Koz", "Void Rift") == [19.0, 18.0, 17.0, 16.0, 15.0]
    assert snap.ability_recharge("NoSuchChamp", "Void Rift") is None
    assert snap.ability_static_cd("Velkoz", "No Such Ability") is None


def test_stub_snapshot_built_directly_gets_the_alias_too() -> None:
    real = DataSnapshot.load()
    stub = DataSnapshot(
        patch=real.patch,
        manifest=real.manifest,
        champions={},
        items={},
        scenarios_by_id={},
        scenarios_by_lolmath={},
        arena_augments_by_id={},
        arena_augments_by_api={},
        data_root=real.data_root,
        wiki_ability_stats={"Vel'Koz/Void Rift": {"apiname": "Velkoz", "static": "2"}},
    )
    assert stub.ability_static_cd("Velkoz", "Void Rift") == "2"
    assert stub.ability_static_cd("Vel'Koz", "Void Rift") == "2"


def test_alias_never_shadows_a_title_keyed_record() -> None:
    real = DataSnapshot.load()
    stub = DataSnapshot(
        patch=real.patch,
        manifest=real.manifest,
        champions={},
        items={},
        scenarios_by_id={},
        scenarios_by_lolmath={},
        arena_augments_by_id={},
        arena_augments_by_api={},
        data_root=real.data_root,
        wiki_ability_stats={
            "A/Q": {"apiname": "B", "static": "1"},
            "B/Q": {"apiname": "B", "static": "9"},
        },
    )
    assert stub.ability_static_cd("B", "Q") == "9"
