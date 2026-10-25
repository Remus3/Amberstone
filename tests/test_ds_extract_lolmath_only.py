"""``tools/daemon_slayer_extract.py --lolmath-only``: refresh lolmath, never Meraki.

lolmath ships on its own cadence (it shipped "26.21" a day after the 16.21.1
extract), but a plain re-run skips an extracted patch and ``--force`` would
re-fetch Meraki, which a Settled rule forbids for a re-extract. The adjudicated
flag re-runs ONLY the lolmath extract against an EXISTING snapshot:

- it refuses ``--force`` and a patch with no ``manifest.json``;
- it fetches nothing from DDragon, Meraki or CDragon - champion ids and the
  version come from the snapshot's own ``champions.json``;
- it may rewrite three files: ``champions.json`` (each champion's ``lolmath``
  sub-object only), ``scenarios.json`` and ``manifest.json`` (lolmath sources,
  counts and a refresh timestamp); every other file in the patch folder and
  ``current.txt`` keep their bytes;
- the RM-805 neutral-table gate is unchanged: a neutral table exits 3 and
  writes nothing. A table that passes the gate WITHOUT an override supersedes
  an adjudicated ``aram_modifiers_carry`` (dropped); with the override the
  carry stays and so do the carried rows.

Built on the RM-805 main() harness (tests/test_ds_extract_aram_neutral_rm805.py).
Every test is synthetic: no network, no live-tree write.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import daemon_slayer_extract as dse  # noqa: E402

PATCH = "99.1.1"

# The 19 files of a real patch folder (data/daemon_slayer/16.21.1/).
ALLOWED = ("champions.json", "scenarios.json", "manifest.json")
OTHERS = (
    "ability_staleness.json",
    "arena_augments.json",
    "build_orders_aram.json",
    "build_orders_arena.json",
    "build_orders_sr.json",
    "cdragon_ability_ratios.json",
    "cdragon_ratio_drift.json",
    "cdragon_spell_stats.json",
    "champion_abilities.json",
    "cherry_augments.json",
    "enchanter_items.json",
    "items_meraki.json",
    "items.json",
    "pickban_targets.json",
    "wiki_ability_stats.json",
    "wiki_stats.json",
)

NEUTRAL = {
    "aramDamageTaken": 1,
    "aramDamageDealt": 1,
    "aramHealing": 1,
    "aramShielding": 1,
    "aramTenacity": 1,
    "aramAbilityHaste": 0,
    "aramAttackSpeed": 1,
}
CARRIED = {**NEUTRAL, "aramDamageDealt": 1.05, "aramDamageTaken": 0.95}
FRESH = {**NEUTRAL, "aramDamageDealt": 1.1, "aramHealing": 0.8}

OLD_SCEN = "https://lolmath.net/_next/static/chunks/old-scen.js"
OLD_DATA = "https://lolmath.net/_next/static/chunks/old-data.js"
NEW_SCEN = "https://lolmath.net/_next/static/chunks/new-scen.js"
NEW_DATA = "https://lolmath.net/_next/static/chunks/new-data.js"


def test_the_fixture_mirrors_a_real_patch_folder():
    assert len(ALLOWED) + len(OTHERS) == 19
    assert not set(ALLOWED) & set(OTHERS)


def _champ(cid: str, key: str) -> dict:
    return {
        "id": cid,
        "key": key,
        "name": cid,
        "title": "the " + cid,
        "tags": ["Fighter"],
        "stats": {"hp": 650, "attackdamage": 60, "attackdamageperlevel": 5},
        "info": {"attack": 8},
        "partype": "Blood Well",
        "lolmath": {
            "cooldowns": {"Q": [14.0, 12.0]},
            "roles": ["FIGHTER"],
            "ratings": {"healing": 1},
            "aram_modifiers": dict(CARRIED),
            "damage_distribution": {"physical": 0.9, "magical": 0.0, "trued": 0.1},
            "skill_order": ["Q", "E", "W"],
        },
    }


def _old_manifest() -> dict:
    return {
        "engine": "daemon_slayer",
        "phase": 1.5,
        "extracted_at": "2026-10-22T20:25:37-0500",
        "ddragon_version": PATCH,
        "ddragon_champion_count": 2,
        "ddragon_item_count": 3,
        "sources": {
            "ddragon_versions": "https://ddragon.leagueoflegends.com/api/versions.json",
            "ddragon_champions": "dd-champ-url",
            "ddragon_items": "dd-item-url",
            "lolmath_scenarios_chunk": OLD_SCEN,
            "lolmath_scenarios_chunk_bytes": 10,
            "lolmath_data_chunk": OLD_DATA,
            "lolmath_data_chunk_bytes": 20,
            "lolmath_data_blocks": {"aram_modifiers": OLD_DATA},
            "lolmath_scenario_pieces": {"cooldowns": OLD_SCEN},
            "meraki_perlevel": "meraki-perlevel-url",
            "meraki_items": "meraki-items-url",
        },
        "lolmath_counts": {
            "cooldowns": 2, "roles": 2, "ratings": 2, "lane_positions": 5,
            "scenarios": 2, "aram_modifiers": 2, "damage_distribution": 2,
            "skill_orders": 2,
        },
        "meraki_perlevel_backfill": {
            "champions_filled": 2, "fields_filled": 2,
            "fields_targeted": ["attackdamageperlevel"],
        },
        "arena_augments": {
            "count": 225, "fetched_at": "2026-10-22T20:25:37-0500",
            "source": "cdragon-arena-url",
        },
        "meraki_items": {
            "count": 320, "fetched_at": "2026-10-22T20:25:37-0500",
            "source": "meraki-items-url", "content_patch": "25.15",
        },
        "outputs": {"champions": "data/daemon_slayer/99.1.1/champions.json"},
        "aram_modifiers_carry": {
            "carried_from": "99.0.1", "rows": 2, "rows_changed_by_carry": 2,
            "reason": "synthetic carry", "ruling": "test", "reverses_if": "test",
        },
    }


def _new_lolmath() -> dse.LolmathExtract:
    return dse.LolmathExtract(
        cooldowns={"Aatrox": {"Q": [13.0, 11.0]}, "Ahri": {"Q": [7.0]}},
        roles={"Aatrox": ["FIGHTER", "TANK"], "Ahri": ["MAGE"]},
        ratings={"Aatrox": {"ratings": {"healing": 2}},
                 "Ahri": {"ratings": {"healing": 0}}},
        lane_positions=["top", "jungle", "middle", "bottom", "support"],
        scenarios={"aatrox": [{"name": "new aatrox"}], "ahri": [{"name": "new ahri"}]},
        chunk_url=NEW_SCEN, chunk_bytes=111,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
        scenario_sources={"cooldowns": NEW_SCEN, "scenarios": [NEW_SCEN]},
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digests(patch_dir: Path, data_root: Path) -> dict[str, str]:
    out = {p.name: _sha(p) for p in patch_dir.iterdir() if p.is_file()}
    out["current.txt"] = _sha(data_root / "current.txt")
    return out


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _no_network(*a, **k):
    raise AssertionError("--lolmath-only must not fetch DDragon / Meraki / CDragon")


def _wire(monkeypatch, tmp_path, aram, argv, *, with_manifest=True):
    """A 19-file patch snapshot under tmp_path; only the lolmath path is stubbed."""
    data_root = tmp_path / "data" / "daemon_slayer"
    patch_dir = data_root / PATCH
    patch_dir.mkdir(parents=True)
    for name in OTHERS:
        dse._atomic_write_json(patch_dir / name, {"file": name, "patch": PATCH})
    champions = {"version": PATCH,
                 "data": {"Aatrox": _champ("Aatrox", "266"), "Ahri": _champ("Ahri", "103")}}
    dse._atomic_write_json(patch_dir / "champions.json", champions)
    dse._atomic_write_json(patch_dir / "scenarios.json", {
        "version": PATCH, "championCount": 2,
        "byDDragonId": {"Aatrox": [{"name": "old"}], "Ahri": [{"name": "old"}]},
        "byLolmathKey": {"aatrox": [{"name": "old"}], "ahri": [{"name": "old"}]},
    })
    if with_manifest:
        dse._atomic_write_json(patch_dir / "manifest.json", _old_manifest())
    dse._atomic_write_text(data_root / "current.txt", PATCH)

    monkeypatch.setattr(dse, "ROOT", tmp_path)
    monkeypatch.setattr(dse, "DATA_ROOT", data_root)
    # Every non-lolmath fetcher, and the raw transport under all of them, raises.
    for name in ("fetch_ddragon", "fetch_meraki_perlevel_overlay",
                 "fetch_arena_augments", "fetch_meraki_items",
                 "_fetch_meraki_bulk", "_fetch_meraki_champion",
                 "_fetch_text", "_fetch_json"):
        monkeypatch.setattr(dse, name, _no_network)
    calls: list[str] = []

    def _discover(*a, **k):
        calls.append("discover")
        return NEW_SCEN, NEW_DATA

    monkeypatch.setattr(dse, "discover_chunks", _discover)
    monkeypatch.setattr(dse, "fetch_chunk", lambda url: "")
    monkeypatch.setattr(dse, "extract_from_bodies", lambda bodies, preferred: _new_lolmath())
    monkeypatch.setattr(dse, "extract_data_blocks", lambda bodies, preferred: {
        "aram_modifiers": aram,
        "damage_distribution": {
            "Aatrox": {"physical": 0.8, "magical": 0.1, "trued": 0.1},
            "Ahri": {"physical": 0.0, "magical": 1.0, "trued": 0.0},
        },
        "skill_orders": {"Aatrox": ["Q", "W", "E"], "Ahri": ["Q", "E", "W"]},
        "data_chunk_url": NEW_DATA,
        "data_chunk_bytes": 222,
        "block_sources": {"aram_modifiers": NEW_DATA, "damage_distribution": NEW_SCEN,
                          "skill_orders": NEW_DATA},
    })
    monkeypatch.setattr(sys, "argv", ["daemon_slayer_extract.py", *argv])
    return data_root, patch_dir, calls


def _strip_lolmath(champions: dict) -> dict:
    out = copy.deepcopy(champions)
    for rec in out["data"].values():
        rec.pop("lolmath", None)
    return out


FRESH_TABLE = {"Aatrox": dict(FRESH), "Ahri": {**NEUTRAL, "aramShielding": 1.2}}
NEUTRAL_TABLE = {"Aatrox": dict(NEUTRAL), "Ahri": dict(NEUTRAL)}


def test_lolmath_only_rewrites_only_the_lolmath_parts(monkeypatch, tmp_path):
    data_root, patch_dir, calls = _wire(
        monkeypatch, tmp_path, FRESH_TABLE, ["--lolmath-only", "--patch", PATCH])
    before = _digests(patch_dir, data_root)
    champs_before = _load(patch_dir / "champions.json")
    manifest_before = _load(patch_dir / "manifest.json")

    assert dse.main() == 0
    assert calls == ["discover"]

    after = _digests(patch_dir, data_root)
    assert set(after) == set(before)
    for name in (*OTHERS, "current.txt"):
        assert after[name] == before[name], name
    assert len(OTHERS) == 16

    # champions.json: byte-for-byte the same outside each lolmath sub-object.
    champs_after = _load(patch_dir / "champions.json")
    assert _strip_lolmath(champs_after) == _strip_lolmath(champs_before)
    assert list(champs_after["data"]) == list(champs_before["data"])
    for cid, rec in champs_after["data"].items():
        assert list(rec) == list(champs_before["data"][cid]), cid
    # ... and the lolmath block is exactly what a full extract would build.
    dd = dse.DDragonSnapshot(version=PATCH, champions=champs_before["data"], items={})
    lm = _new_lolmath()
    lm.aram_modifiers = FRESH_TABLE
    lm.damage_distribution = {
        "Aatrox": {"physical": 0.8, "magical": 0.1, "trued": 0.1},
        "Ahri": {"physical": 0.0, "magical": 1.0, "trued": 0.0},
    }
    lm.skill_orders = {"Aatrox": ["Q", "W", "E"], "Ahri": ["Q", "E", "W"]}
    full = dse.build_champions_payload(lm, dd)
    for cid in ("Aatrox", "Ahri"):
        assert champs_after["data"][cid]["lolmath"] == full["data"][cid]["lolmath"], cid
    assert champs_after["data"]["Aatrox"]["lolmath"]["aram_modifiers"] == FRESH

    scen = _load(patch_dir / "scenarios.json")
    assert scen["version"] == PATCH
    assert scen["byLolmathKey"]["aatrox"] == [{"name": "new aatrox"}]
    assert scen["byDDragonId"]["Ahri"] == [{"name": "new ahri"}]

    # manifest.json: Meraki, arena, DDragon and outputs blocks untouched.
    m = _load(patch_dir / "manifest.json")
    for key in ("engine", "phase", "extracted_at", "ddragon_version",
                "ddragon_champion_count", "ddragon_item_count",
                "meraki_perlevel_backfill", "arena_augments", "meraki_items", "outputs"):
        assert m[key] == manifest_before[key], key
    for key in ("ddragon_versions", "ddragon_champions", "ddragon_items",
                "meraki_perlevel", "meraki_items"):
        assert m["sources"][key] == manifest_before["sources"][key], key
    assert list(m["sources"]) == list(manifest_before["sources"])
    assert m["sources"]["lolmath_scenarios_chunk"] == NEW_SCEN
    assert m["sources"]["lolmath_scenarios_chunk_bytes"] == 111
    assert m["sources"]["lolmath_data_chunk"] == NEW_DATA
    assert m["sources"]["lolmath_data_chunk_bytes"] == 222
    assert m["sources"]["lolmath_data_blocks"]["damage_distribution"] == NEW_SCEN
    assert m["sources"]["lolmath_scenario_pieces"] == {"cooldowns": NEW_SCEN,
                                                       "scenarios": [NEW_SCEN]}
    assert m["lolmath_counts"]["lane_positions"] == 5
    assert m["lolmath_counts"]["aram_modifiers"] == 2
    refresh = m["lolmath_refresh"]
    assert refresh["flag"] == "--lolmath-only"
    assert refresh["refreshed_at"]
    # A table that passes the gate without an override supersedes the carry.
    assert "aram_modifiers_carry" not in m
    assert "aram_modifiers_neutral_override" not in m
    assert set(m) - set(manifest_before) == {"lolmath_refresh"}


def test_lolmath_only_neutral_table_exits_3_and_changes_nothing(monkeypatch, tmp_path):
    data_root, patch_dir, _ = _wire(
        monkeypatch, tmp_path, NEUTRAL_TABLE, ["--lolmath-only", "--patch", PATCH])
    before = _digests(patch_dir, data_root)
    assert len(before) == 20  # 19 patch files + current.txt

    assert dse.main() == dse.EXIT_ARAM_NEUTRAL == 3

    assert _digests(patch_dir, data_root) == before
    assert not list(patch_dir.glob("*.tmp"))


def test_lolmath_only_with_force_is_refused(monkeypatch, tmp_path):
    data_root, patch_dir, calls = _wire(
        monkeypatch, tmp_path, FRESH_TABLE, ["--lolmath-only", "--force", "--patch", PATCH])
    before = _digests(patch_dir, data_root)

    with pytest.raises(SystemExit) as exc:
        dse.main()
    assert exc.value.code == 2
    assert calls == []
    assert _digests(patch_dir, data_root) == before


def test_lolmath_only_needs_an_existing_manifest(monkeypatch, tmp_path):
    data_root, patch_dir, calls = _wire(
        monkeypatch, tmp_path, FRESH_TABLE, ["--lolmath-only", "--patch", PATCH],
        with_manifest=False)
    before = _digests(patch_dir, data_root)

    assert dse.main() == dse.EXIT_LOLMATH_ONLY_NO_SNAPSHOT
    assert dse.EXIT_LOLMATH_ONLY_NO_SNAPSHOT not in (0, dse.EXIT_ARAM_NEUTRAL)
    assert calls == [], "no lolmath fetch before the snapshot check"
    assert _digests(patch_dir, data_root) == before


def test_lolmath_only_defaults_to_the_current_patch(monkeypatch, tmp_path):
    _, patch_dir, calls = _wire(monkeypatch, tmp_path, FRESH_TABLE, ["--lolmath-only"])
    assert dse.main() == 0
    assert calls == ["discover"]
    assert "lolmath_refresh" in _load(patch_dir / "manifest.json")


def test_lolmath_only_override_keeps_the_carry_and_the_carried_rows(monkeypatch, tmp_path):
    reason = "RM-999 adjudication: keep the carry"
    data_root, patch_dir, _ = _wire(
        monkeypatch, tmp_path, NEUTRAL_TABLE,
        ["--lolmath-only", "--patch", PATCH, "--allow-neutral-aram", reason])
    manifest_before = _load(patch_dir / "manifest.json")

    assert dse.main() == 0

    champs = _load(patch_dir / "champions.json")["data"]
    for cid in ("Aatrox", "Ahri"):
        assert champs[cid]["lolmath"]["aram_modifiers"] == CARRIED, cid
    assert champs["Aatrox"]["lolmath"]["skill_order"] == ["Q", "W", "E"]
    m = _load(patch_dir / "manifest.json")
    assert m["aram_modifiers_carry"] == manifest_before["aram_modifiers_carry"]
    rec = m["aram_modifiers_neutral_override"]
    assert rec["reason"] == reason
    assert rec["flag"] == "--allow-neutral-aram"
    assert rec["neutral_rows"] == 2
