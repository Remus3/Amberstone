"""RM-887: a lolmath role, damage-split or skill-order block that is clean
but covers only part of the cooldown roster must fail loudly.

RM-807 counts degenerate rows INSIDE each block, so a block of 20 clean rows
passed even when the roster holds 173 champions; the other 153 got ``None`` in
``champions.json`` (``_lolmath_block`` reads every block by DDragon id). The
roster is the cooldown table, the same one ``check_lolmath_coverage`` measures
scenarios against. Every committed snapshot 16.10.1 .. 16.21.1 carries a role,
damage-split and skill-order row for every cooldown-roster champion (172/172 or
173/173, measured), so a block under 95 percent of the roster now fails under
the RM-807 floor: same ``EXIT_LOLMATH_DEGENERATE``, same
``--allow-degenerate-lolmath REASON`` override, recorded in the manifest. A
champion missing below the floor is named in a WARNING.

Every test is synthetic (no network, no live-tree write) except the snapshot
guard, which only reads the committed snapshots.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import daemon_slayer_extract as dse  # noqa: E402

GOOD_SPLIT = {"physical": 0.8, "magical": 0.1, "trued": 0.1}
GOOD_ORDER = ["Q", "E", "W", "Q", "Q", "R"]
GOOD_CD = {"Q": [14, 12, 10, 8, 6, None], "E": [9, 8, 7, 6, 5, None]}
BLOCKS = ("roles", "damage_distribution", "skill_orders")


def _ids(rows: int) -> list[str]:
    return [f"Champ{i:03d}" for i in range(rows)]


def _tables(roster: int, *, roles: int | None = None, damage: int | None = None,
            skills: int | None = None) -> dict[str, dict]:
    """Clean tables; a block given a count covers only the first N roster ids."""
    def n(val):
        return roster if val is None else val
    return {
        "cooldowns": {cid: dict(GOOD_CD) for cid in _ids(roster)},
        "roles": {cid: ["FIGHTER"] for cid in _ids(n(roles))},
        "damage_distribution": {cid: dict(GOOD_SPLIT) for cid in _ids(n(damage))},
        "skill_orders": {cid: list(GOOD_ORDER) for cid in _ids(n(skills))},
    }


def _check(t, override_reason=None):
    return dse.check_lolmath_blocks(t["damage_distribution"], t["skill_orders"],
                                    override_reason, cooldowns=t["cooldowns"],
                                    roles=t["roles"])


# --- the gate ------------------------------------------------------------------

@pytest.mark.parametrize("block", BLOCKS)
def test_a_clean_block_covering_a_fraction_of_the_roster_raises(block):
    key = {"roles": "roles", "damage_distribution": "damage",
           "skill_orders": "skills"}[block]
    t = _tables(173, **{key: 20})
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        _check(t)
    msg = str(exc.value)
    assert "RM-807" in msg and "--allow-degenerate-lolmath" in msg
    assert f"{block} covers 20/173 of the cooldown roster" in msg
    for other in set(BLOCKS) - {block}:
        assert other not in msg


def test_coverage_just_under_the_floor_raises_and_at_the_floor_passes():
    # 95/100 = exactly the floor passes; 94/100 is under it.
    with pytest.raises(dse.DegenerateLolmathBlockError, match="covers 94/100"):
        _check(_tables(100, damage=94))
    out = _check(_tables(100, damage=95))
    assert out["damage_distribution"]["missing_rows"] == 5
    assert out["damage_distribution"]["coverage"] == pytest.approx(0.95)


def test_a_missing_champion_below_the_floor_is_named_in_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = _check(_tables(173, skills=172))
    assert out["skill_orders"]["missing_rows"] == 1
    assert "override_reason" not in out
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "skill_orders" in text and "Champ172" in text


def test_full_coverage_passes_without_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = _check(_tables(173))
    for block in BLOCKS:
        assert out[block]["missing_rows"] == 0
        assert out[block]["coverage"] == 1.0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_rows_outside_the_roster_neither_count_nor_fail():
    # A lolmath-only champion is warned about by build_champions_payload; it
    # does not stand in for a roster champion that has no row.
    t = _tables(100, damage=90)
    t["damage_distribution"].update(
        {f"Extra{i}": dict(GOOD_SPLIT) for i in range(10)})
    with pytest.raises(dse.DegenerateLolmathBlockError, match="covers 90/100"):
        _check(t)


def test_the_cooldown_table_is_the_roster_not_a_covered_block():
    out = _check(_tables(173))
    assert out["cooldowns"] == {"rows": 173, "degenerate_rows": 0,
                                "degenerate_fraction": 0.0}


def test_an_empty_roster_leaves_coverage_to_the_empty_cooldown_failure():
    t = _tables(173)
    t["cooldowns"] = {}
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        _check(t)
    msg = str(exc.value)
    assert "cooldowns empty (0 rows)" in msg
    assert "covers" not in msg


def test_without_a_roster_the_measurement_is_unchanged():
    out = dse.check_lolmath_blocks({"A": dict(GOOD_SPLIT)}, {"A": list(GOOD_ORDER)})
    assert out["damage_distribution"] == {"rows": 1, "degenerate_rows": 0,
                                          "degenerate_fraction": 0.0}


def test_the_override_accepts_and_records_the_coverage():
    reason = "RM-999 adjudication: lolmath dropped the skill-order rows"
    out = _check(_tables(173, skills=20), override_reason=reason)
    assert out["override_reason"] == reason
    rec = dse._degenerate_override_record(out)
    assert rec["blocks"]["skill_orders"]["coverage"] == pytest.approx(20 / 173, abs=1e-4)
    assert rec["blocks"]["skill_orders"]["missing_rows"] == 153


# --- the committed snapshots are fully covered ---------------------------------

def _present(lm: dict[str, dict], field: str) -> dict:
    """The rows champions.json actually carries, as the extract's block shape."""
    return {cid: b[field] for cid, b in lm.items() if b.get(field) is not None}


def test_every_committed_snapshot_covers_the_cooldown_roster():
    snaps = sorted(p for p in (ROOT / "data" / "daemon_slayer").iterdir()
                   if (p / "champions.json").is_file())
    assert len(snaps) >= 5
    for snap in snaps:
        data = json.loads((snap / "champions.json").read_text(encoding="utf-8"))["data"]
        assert len(data) >= 170, snap.name
        lm = {cid: rec.get("lolmath") or {} for cid, rec in data.items()}
        cooldowns = _present(lm, "cooldowns")
        assert len(cooldowns) == len(data), snap.name
        out = dse.check_lolmath_blocks(_present(lm, "damage_distribution"),
                                       _present(lm, "skill_order"),
                                       cooldowns=cooldowns, roles=_present(lm, "roles"))
        for block in BLOCKS:
            assert out[block]["missing_rows"] == 0, (snap.name, block, out[block])


# --- main(): the gate fires before any later fetch or write --------------------

def _wire_main(monkeypatch, tmp_path, t, argv, *, network_ok):
    data_root = tmp_path / "data" / "daemon_slayer"
    monkeypatch.setattr(dse, "ROOT", tmp_path)
    monkeypatch.setattr(dse, "DATA_ROOT", data_root)
    monkeypatch.setattr(dse, "fetch_ddragon", lambda: dse.DDragonSnapshot(
        version="99.1.1",
        champions={"Champ000": {"key": "1", "name": "Champ000", "stats": {}}},
        items={},
    ))
    monkeypatch.setattr(dse, "discover_chunks",
                        lambda *a, **k: ("u/scen.js", "u/aram.js"))
    monkeypatch.setattr(dse, "fetch_chunk", lambda url: "")
    monkeypatch.setattr(dse, "extract_from_bodies", lambda bodies, preferred: dse.LolmathExtract(
        cooldowns=t["cooldowns"], roles=t["roles"],
        ratings={}, lane_positions=["top"], scenarios={"champ000": [{}]},
        chunk_url="u/scen.js", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    ))
    monkeypatch.setattr(dse, "extract_data_blocks", lambda bodies, preferred: {
        "aram_modifiers": {cid: {"aramDamageDealt": 1.05} for cid in _ids(173)},
        "damage_distribution": t["damage_distribution"],
        "skill_orders": t["skill_orders"],
        "data_chunk_url": "u/aram.js",
        "data_chunk_bytes": 1,
        "block_sources": {"aram_modifiers": "u/aram.js"},
    })

    def _no_network(*a, **k):
        raise AssertionError("network fetch after the RM-807 gate")

    if network_ok:
        monkeypatch.setattr(dse, "fetch_meraki_perlevel_overlay", lambda ids: {})
        monkeypatch.setattr(dse, "fetch_arena_augments", lambda: {
            "count": 225, "augments": [{"id": i} for i in range(225)]})
        monkeypatch.setattr(dse, "fetch_meraki_items", lambda: {
            "count": 320, "items": {str(i): {} for i in range(320)}})
    else:
        monkeypatch.setattr(dse, "fetch_meraki_perlevel_overlay", _no_network)
        monkeypatch.setattr(dse, "fetch_arena_augments", _no_network)
        monkeypatch.setattr(dse, "fetch_meraki_items", _no_network)
    monkeypatch.setattr(sys, "argv", ["daemon_slayer_extract.py", "--patch", "99.1.1", *argv])
    return data_root


@pytest.mark.parametrize("key, block", [
    ("roles", "roles"), ("damage", "damage_distribution"), ("skills", "skill_orders"),
])
def test_main_exits_non_zero_and_writes_nothing(
        monkeypatch, tmp_path, caplog, key, block):
    caplog.set_level(logging.ERROR, logger="daemon_slayer_extract")
    data_root = _wire_main(monkeypatch, tmp_path, _tables(173, **{key: 20}), [],
                           network_ok=False)
    assert dse.main() == dse.EXIT_LOLMATH_DEGENERATE
    assert not data_root.exists() or not any(data_root.rglob("*"))
    errors = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "RM-807" in errors and f"{block} covers 20/173" in errors


def test_main_override_writes_and_records_the_coverage(monkeypatch, tmp_path):
    reason = "RM-999 adjudication: accept the partial damage block"
    data_root = _wire_main(monkeypatch, tmp_path, _tables(173, damage=20),
                           ["--allow-degenerate-lolmath", reason], network_ok=True)
    assert dse.main() == 0
    manifest = json.loads((data_root / "99.1.1" / "manifest.json").read_text(encoding="utf-8"))
    rec = manifest["lolmath_degenerate_override"]
    assert rec["reason"] == reason
    assert rec["blocks"]["damage_distribution"]["missing_rows"] == 153
