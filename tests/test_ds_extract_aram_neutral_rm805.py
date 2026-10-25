"""RM-805: the extractor must fail loudly on a (near) all-neutral ARAM table.

The DS 16.20.1 -> 16.21.1 refresh (RM-766, 2026-10-22) pulled a lolmath ARAM
modifier table that was neutral for 173/173 champions - a shape no committed
snapshot ever showed (16.10.1 .. 16.20.1: 21-24 percent of rows neutral).
``tools/daemon_slayer_extract.py`` accepted it silently and wrote it into
``champions.json``; only a later adjudication noticed and carried the
16.20.1 block forward (manifest ``aram_modifiers_carry``).

The extractor now refuses a table that is >= 95 percent neutral: ``main()``
exits non-zero with a named reason BEFORE any network fetch after the lolmath
parse and BEFORE any file is written. The one way past it is the explicit
``--allow-neutral-aram REASON`` flag, which logs a WARNING and records the
override (reason and counts) in the manifest, so accepting or carrying a
neutral table is always a deliberate, recorded act.

"Neutral" follows core/aram_balance_context.py: the six multipliers are
neutral at 1.0, aramAbilityHaste (additive flat) is neutral at 0, and a
missing or non-numeric field carries no information (neutral).

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

NEUTRAL = {
    "aramDamageTaken": 1,
    "aramDamageDealt": 1,
    "aramHealing": 1,
    "aramShielding": 1,
    "aramTenacity": 1,
    "aramAbilityHaste": 0,
    "aramAttackSpeed": 1,
}


def _table(rows: int, neutral: int) -> dict[str, dict]:
    """``rows`` champions, the first ``neutral`` of them fully neutral."""
    out = {}
    for i in range(rows):
        row = dict(NEUTRAL)
        if i >= neutral:
            row["aramDamageDealt"] = 1.05
        out[f"Champ{i:03d}"] = row
    return out


# --- the threshold -------------------------------------------------------------

def test_threshold_is_95_percent():
    assert dse.ARAM_NEUTRAL_FAIL_FRACTION == 0.95


def test_an_all_neutral_173_row_table_raises_naming_the_counts():
    with pytest.raises(dse.NeutralAramTableError) as exc:
        dse.check_aram_neutrality(_table(173, 173))
    msg = str(exc.value)
    assert "173/173" in msg
    assert "RM-805" in msg
    assert "--allow-neutral-aram" in msg


def test_a_table_at_exactly_95_percent_neutral_raises():
    with pytest.raises(dse.NeutralAramTableError, match="95/100"):
        dse.check_aram_neutrality(_table(100, 95))


def test_a_table_above_95_percent_neutral_raises():
    with pytest.raises(dse.NeutralAramTableError, match="170/173"):
        dse.check_aram_neutrality(_table(173, 170))


def test_a_94_percent_neutral_table_passes():
    out = dse.check_aram_neutrality(_table(100, 94))
    assert out["rows"] == 100
    assert out["neutral_rows"] == 94
    assert out["neutral_fraction"] == pytest.approx(0.94)
    assert out["threshold"] == 0.95
    assert "override_reason" not in out


def test_a_normal_table_passes():
    # The committed snapshots carry 37-41 neutral rows of 172-173.
    out = dse.check_aram_neutrality(_table(173, 41))
    assert out["neutral_rows"] == 41


def test_an_empty_table_raises():
    # An empty block leaves every champion with no modifiers at all, the same
    # silent-default shape as an all-neutral one.
    with pytest.raises(dse.NeutralAramTableError, match="0 rows"):
        dse.check_aram_neutrality({})


# --- what "neutral" means ------------------------------------------------------

@pytest.mark.parametrize("row, neutral", [
    (dict(NEUTRAL), True),
    ({}, True),
    (None, True),
    ({**NEUTRAL, "aramDamageDealt": 1.05}, False),
    ({**NEUTRAL, "aramHealing": 0.9}, False),
    ({**NEUTRAL, "aramAttackSpeed": 1.025}, False),
    ({**NEUTRAL, "aramAbilityHaste": -10}, False),
    ({**NEUTRAL, "aramAbilityHaste": 0.0, "aramTenacity": 1.0}, True),
    # A non-numeric value carries no information.
    ({**NEUTRAL, "aramDamageDealt": None, "aramAbilityHaste": "x"}, True),
    # A bool is not a magnitude (True would otherwise read as AH 1).
    ({**NEUTRAL, "aramAbilityHaste": True}, True),
    # Only the seven consumed fields count.
    ({**NEUTRAL, "aramEnergyRegen": 1.2}, True),
])
def test_row_neutrality(row, neutral):
    assert dse._aram_row_is_neutral(row) is neutral


def test_neutral_field_sets_match_the_runtime_consumer():
    # core/aram_balance_context.py defines neutral for the dashboard grid; the
    # extractor gate must judge the same fields the same way.
    from core import aram_balance_context as abc

    assert set(dse._ARAM_MULT_FIELDS) == set(abc._GRID_MULT_FIELDS)
    assert set(dse._ARAM_FLAT_FIELDS) == set(abc._GRID_FLAT_FIELDS)


def test_every_committed_snapshot_passes_the_gate():
    # The floor must never fire on real data: every snapshot on disk (the
    # 16.21.1 one carries the adjudicated 16.20.1 block) is far below it.
    snaps = sorted(p for p in (ROOT / "data" / "daemon_slayer").iterdir()
                   if (p / "champions.json").is_file())
    assert len(snaps) >= 5
    for snap in snaps:
        data = json.loads((snap / "champions.json").read_text(encoding="utf-8"))["data"]
        table = {cid: (rec.get("lolmath") or {}).get("aram_modifiers")
                 for cid, rec in data.items()}
        out = dse.check_aram_neutrality(table)
        assert out["neutral_fraction"] < 0.5, (snap.name, out)


# --- the explicit override -----------------------------------------------------

def test_the_override_accepts_and_logs_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = dse.check_aram_neutrality(
        _table(173, 173), override_reason="RM-999 adjudication: carry 16.20.1",
    )
    assert out["neutral_rows"] == 173
    assert out["override_reason"] == "RM-999 adjudication: carry 16.20.1"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "the override must log a WARNING"
    text = " ".join(r.getMessage() for r in warnings)
    assert "RM-805" in text
    assert "173/173" in text
    assert "RM-999 adjudication: carry 16.20.1" in text


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_blank_override_reason_does_not_override(reason):
    with pytest.raises(dse.NeutralAramTableError):
        dse.check_aram_neutrality(_table(173, 173), override_reason=reason)


def test_an_unneeded_override_is_not_recorded():
    out = dse.check_aram_neutrality(_table(173, 41), override_reason="not needed")
    assert "override_reason" not in out


# --- main(): the gate is wired before any write ---------------------------------

def _lolmath():
    return dse.LolmathExtract(
        cooldowns={"Aatrox": {"Q": [4.0]}}, roles={"Aatrox": ["FIGHTER"]},
        ratings={}, lane_positions=["top"], scenarios={"aatrox": [{}]},
        chunk_url="u/scen.js", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    )


def _wire_main(monkeypatch, tmp_path, aram, argv, *, network_ok):
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
                        lambda bodies, preferred: _lolmath())
    monkeypatch.setattr(dse, "extract_data_blocks", lambda bodies, preferred: {
        "aram_modifiers": aram,
        # Clean blocks, so only the RM-805 gate decides (RM-807 gates these two).
        "damage_distribution": {"Aatrox": {"physical": 0.9, "magical": 0.0, "trued": 0.1}},
        "skill_orders": {"Aatrox": ["Q", "E", "W"]},
        "data_chunk_url": "u/aram.js",
        "data_chunk_bytes": 1,
        "block_sources": {"aram_modifiers": "u/aram.js"},
    })

    def _no_network(*a, **k):
        raise AssertionError("network fetch after the RM-805 gate")

    if network_ok:
        monkeypatch.setattr(dse, "fetch_meraki_perlevel_overlay", lambda ids: {})
        monkeypatch.setattr(dse, "fetch_arena_augments", lambda: {"count": 0})
        monkeypatch.setattr(dse, "fetch_meraki_items", lambda: {"count": 0})
    else:
        monkeypatch.setattr(dse, "fetch_meraki_perlevel_overlay", _no_network)
        monkeypatch.setattr(dse, "fetch_arena_augments", _no_network)
        monkeypatch.setattr(dse, "fetch_meraki_items", _no_network)
    monkeypatch.setattr(sys, "argv", ["daemon_slayer_extract.py", "--patch", "99.1.1", *argv])
    return data_root


def test_main_exits_non_zero_and_writes_nothing_on_a_neutral_table(
        monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.ERROR, logger="daemon_slayer_extract")
    data_root = _wire_main(monkeypatch, tmp_path, _table(173, 173), [], network_ok=False)
    rc = dse.main()
    assert rc == dse.EXIT_ARAM_NEUTRAL
    assert rc != 0
    assert not data_root.exists() or not any(data_root.rglob("*"))
    errors = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "RM-805" in errors and "173/173" in errors


def test_main_override_writes_and_records_the_override(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    reason = "RM-999 adjudication: carry 16.20.1 forward"
    data_root = _wire_main(
        monkeypatch, tmp_path, _table(173, 173),
        ["--allow-neutral-aram", reason], network_ok=True,
    )
    assert dse.main() == 0
    manifest = json.loads((data_root / "99.1.1" / "manifest.json").read_text(encoding="utf-8"))
    rec = manifest["aram_modifiers_neutral_override"]
    assert rec["reason"] == reason
    assert rec["rows"] == 173
    assert rec["neutral_rows"] == 173
    assert rec["threshold"] == 0.95
    assert rec["flag"] == "--allow-neutral-aram"
    assert any(reason in r.getMessage() for r in caplog.records
               if r.levelno == logging.WARNING)


def test_main_normal_table_records_no_override(monkeypatch, tmp_path):
    data_root = _wire_main(monkeypatch, tmp_path, _table(173, 41), [], network_ok=True)
    assert dse.main() == 0
    manifest = json.loads((data_root / "99.1.1" / "manifest.json").read_text(encoding="utf-8"))
    assert "aram_modifiers_neutral_override" not in manifest
