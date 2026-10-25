"""RM-807 (c): an empty or degenerate lolmath cooldown or role table must fail
loudly, the same way as the damage-split and skill-order blocks.

``check_lolmath_coverage`` measures scenario coverage AGAINST the cooldown
roster, so an empty cooldown table made it vacuous: no roster, nothing missing,
pass. Every champion then got ``cooldowns: None`` in ``champions.json``. A
cooldown row with no positive cooldown in any Q / W / E / R slot is the same
silent default one row at a time. Every committed snapshot 16.10.1 .. 16.21.1
carries a cooldown and a role row for every champion, none degenerate.

The cooldown and role tables now go through ``check_lolmath_blocks`` beside the
two data blocks: same 95 percent floor, same ``EXIT_LOLMATH_DEGENERATE``, same
``--allow-degenerate-lolmath REASON`` override, recorded in the manifest.

Every test is synthetic (no network, no live-tree write).
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
# Real rows end in None past the last rank, and some slots carry no cooldown
# at all (16.21.1: 20 such slots, e.g. Ashe Q), so neither is degenerate.
GOOD_CD = {"Q": [14, 12, 10, 8, 6, None], "W": [None] * 6,
           "E": [9, 8, 7, 6, 5, None], "R": [120, 100, 80, None, None, None]}
EMPTY_CD = {"Q": [None] * 6, "W": [None] * 6, "E": [None] * 6, "R": [None] * 6}


def _ids(rows: int) -> list[str]:
    return [f"Champ{i:03d}" for i in range(rows)]


def _damage(rows: int) -> dict[str, dict]:
    return {cid: dict(GOOD_SPLIT) for cid in _ids(rows)}


def _skills(rows: int) -> dict[str, list]:
    return {cid: list(GOOD_ORDER) for cid in _ids(rows)}


def _cooldowns(rows: int, degenerate: int) -> dict[str, dict]:
    return {cid: dict(EMPTY_CD if i < degenerate else GOOD_CD)
            for i, cid in enumerate(_ids(rows))}


def _roles(rows: int, degenerate: int) -> dict[str, list]:
    return {cid: ([] if i < degenerate else ["FIGHTER"])
            for i, cid in enumerate(_ids(rows))}


def _check(cooldowns, roles, override_reason=None, rows=173):
    return dse.check_lolmath_blocks(_damage(rows), _skills(rows), override_reason,
                                    cooldowns=cooldowns, roles=roles)


# --- the gate ------------------------------------------------------------------

@pytest.mark.parametrize("block, cooldowns, roles", [
    ("cooldowns", {}, _roles(173, 0)),
    ("roles", _cooldowns(173, 0), {}),
])
def test_an_empty_cooldown_or_role_table_raises(block, cooldowns, roles):
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        _check(cooldowns, roles)
    msg = str(exc.value)
    assert "RM-807" in msg and f"{block} empty (0 rows)" in msg
    assert "--allow-degenerate-lolmath" in msg


def test_an_all_none_cooldown_table_raises_naming_the_counts():
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        _check(_cooldowns(173, 173), _roles(173, 0))
    msg = str(exc.value)
    assert "cooldowns 173/173" in msg
    assert "roles" not in msg


def test_an_all_empty_role_table_raises():
    with pytest.raises(dse.DegenerateLolmathBlockError, match="roles 173/173"):
        _check(_cooldowns(173, 0), _roles(173, 173))


def test_below_the_floor_the_rows_are_named_in_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = _check(_cooldowns(100, 2), _roles(100, 1), rows=100)
    assert out["cooldowns"] == {"rows": 100, "degenerate_rows": 2,
                                "degenerate_fraction": 0.02}
    assert out["roles"]["degenerate_rows"] == 1
    assert "override_reason" not in out
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "cooldowns" in text and "Champ001" in text and "roles" in text


def test_a_clean_table_passes_without_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = _check(_cooldowns(173, 0), _roles(173, 0))
    assert out["cooldowns"]["degenerate_rows"] == 0
    assert out["roles"]["degenerate_rows"] == 0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_without_the_tables_the_measurement_is_unchanged():
    # The two-block callers keep their exact output shape.
    out = dse.check_lolmath_blocks(_damage(5), _skills(5))
    assert set(out) == {"threshold", "damage_distribution", "skill_orders"}


def test_the_override_accepts_and_is_recorded():
    reason = "RM-999 adjudication: lolmath cooldown table reset"
    out = _check({}, _roles(173, 0), override_reason=reason)
    assert out["override_reason"] == reason
    rec = dse._degenerate_override_record(out)
    assert rec["reason"] == reason
    assert rec["blocks"]["cooldowns"]["rows"] == 0
    assert set(rec["blocks"]) == {"cooldowns", "roles", "damage_distribution",
                                  "skill_orders"}


# --- what "degenerate" means ---------------------------------------------------

@pytest.mark.parametrize("row, degenerate", [
    (dict(GOOD_CD), False),
    ({"R": [0.5]}, False),
    (dict(EMPTY_CD), True),
    ({}, True),
    (None, True),
    ([], True),
    ({"Q": []}, True),
    ({"Q": [0, 0, 0]}, True),
    ({"Q": [-4.0]}, True),
    ({"Q": [float("nan")]}, True),
    ({"Q": [float("inf")]}, True),
    # A bool is not a cooldown (True would otherwise read as 1.0).
    ({"Q": [True]}, True),
    ({"Q": ["14"]}, True),
    ({"Q": 14}, True),
    # Only the four ability slots count.
    ({"P": [10.0]}, True),
])
def test_cooldown_row_degeneracy(row, degenerate):
    assert dse._cooldown_row_is_degenerate(row) is degenerate


@pytest.mark.parametrize("row, degenerate", [
    (["FIGHTER"], False),
    (["MAGE", "SUPPORT"], False),
    ([], True),
    (None, True),
    ({}, True),
    ("FIGHTER", True),
    (["", "   "], True),
    ([None, 1], True),
])
def test_role_row_degeneracy(row, degenerate):
    assert dse._roles_row_is_degenerate(row) is degenerate


def test_every_committed_snapshot_has_full_clean_cooldown_and_role_rows():
    snaps = sorted(p for p in (ROOT / "data" / "daemon_slayer").iterdir()
                   if (p / "champions.json").is_file())
    assert len(snaps) >= 5
    for snap in snaps:
        data = json.loads((snap / "champions.json").read_text(encoding="utf-8"))["data"]
        assert len(data) >= 170, snap.name
        lm = {cid: rec.get("lolmath") or {} for cid, rec in data.items()}
        cooldowns = {cid: b.get("cooldowns") for cid, b in lm.items()}
        roles = {cid: b.get("roles") for cid, b in lm.items()}
        damage = {cid: b.get("damage_distribution") for cid, b in lm.items()}
        skills = {cid: b.get("skill_order") for cid, b in lm.items()}
        out = dse.check_lolmath_blocks(damage, skills, cooldowns=cooldowns, roles=roles)
        assert out["cooldowns"]["degenerate_rows"] == 0, (snap.name, out)
        assert out["roles"]["degenerate_rows"] == 0, (snap.name, out)


# --- main(): the gate fires before any later fetch or write --------------------

def _lolmath(cooldowns, roles):
    return dse.LolmathExtract(
        cooldowns=cooldowns, roles=roles,
        ratings={}, lane_positions=["top"], scenarios={"aatrox": [{}]},
        chunk_url="u/scen.js", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    )


def _wire_main(monkeypatch, tmp_path, cooldowns, roles, argv, *, network_ok):
    data_root = tmp_path / "data" / "daemon_slayer"
    monkeypatch.setattr(dse, "ROOT", tmp_path)
    monkeypatch.setattr(dse, "DATA_ROOT", data_root)
    monkeypatch.setattr(dse, "fetch_ddragon", lambda: dse.DDragonSnapshot(
        version="99.1.1",
        champions={"Aatrox": {"key": "266", "name": "Aatrox", "stats": {}}},
        items={},
    ))
    monkeypatch.setattr(dse, "discover_chunks",
                        lambda *a, **k: ("u/scen.js", "u/aram.js"))
    monkeypatch.setattr(dse, "fetch_chunk", lambda url: "")
    monkeypatch.setattr(dse, "extract_from_bodies",
                        lambda bodies, preferred: _lolmath(cooldowns, roles))
    monkeypatch.setattr(dse, "extract_data_blocks", lambda bodies, preferred: {
        "aram_modifiers": {cid: {"aramDamageDealt": 1.05} for cid in _ids(173)},
        "damage_distribution": _damage(173),
        "skill_orders": _skills(173),
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


@pytest.mark.parametrize("cooldowns, roles, block", [
    ({}, _roles(173, 0), "cooldowns"),
    (_cooldowns(173, 173), _roles(173, 0), "cooldowns"),
    (_cooldowns(173, 0), _roles(173, 173), "roles"),
])
def test_main_exits_non_zero_and_writes_nothing(
        monkeypatch, tmp_path, caplog, cooldowns, roles, block):
    caplog.set_level(logging.ERROR, logger="daemon_slayer_extract")
    data_root = _wire_main(monkeypatch, tmp_path, cooldowns, roles, [], network_ok=False)
    assert dse.main() == dse.EXIT_LOLMATH_DEGENERATE
    assert not data_root.exists() or not any(data_root.rglob("*"))
    errors = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "RM-807" in errors and block in errors


def test_main_override_writes_and_records_the_cooldown_block(monkeypatch, tmp_path):
    reason = "RM-999 adjudication: accept the cooldown reset"
    data_root = _wire_main(monkeypatch, tmp_path, {}, _roles(173, 0),
                           ["--allow-degenerate-lolmath", reason], network_ok=True)
    assert dse.main() == 0
    manifest = json.loads((data_root / "99.1.1" / "manifest.json").read_text(encoding="utf-8"))
    rec = manifest["lolmath_degenerate_override"]
    assert rec["reason"] == reason
    assert rec["blocks"]["cooldowns"]["rows"] == 0
    assert rec["blocks"]["roles"]["degenerate_rows"] == 0
