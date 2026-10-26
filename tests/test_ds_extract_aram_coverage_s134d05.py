"""RM-913: the lolmath ARAM modifier table must cover the DDragon roster.

RM-805 ``check_aram_neutrality`` measures only the rows the table carries, so
20 clean, non-neutral rows for a 173-champion roster passed, and the other 153
champions got ``aram_modifiers: None`` in ``champions.json``. Counting the
missing rows as neutral would not catch it either (153/173 = 88 percent, under
the 95 percent neutral floor).

Design call (recorded): the coverage floor lives in the RM-805 gate, under
exit 3 (``EXIT_ARAM_NEUTRAL``) and the ``--allow-neutral-aram REASON``
override, not under RM-807 exit 5. Putting it under exit 5 would make an
adjudicated ``--allow-neutral-aram`` empty table (an RM-805 carry-forward)
trip a second gate it was never meant to meet. The roster is the CANONICAL
DDragon champion set, the one RM-914 measures the cooldown table against;
every committed snapshot 16.10.1 .. 16.21.1 carries an ARAM row for every
canonical champion (172/172 or 173/173, measured), so the floor is
``LOLMATH_COVERAGE_FLOOR`` (95 percent). An empty table is left to the
existing empty-table failure, so its override still exits 0. An id DDragon
does not list neither counts nor fails; a missing champion above the floor is
named in a WARNING.

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
from agents.daemon_slayer.mode_variants import canonical_champions  # noqa: E402

CLEAN = {"aramDamageDealt": 1.05, "aramDamageTaken": 0.95}
GOOD_SPLIT = {"physical": 0.8, "magical": 0.1, "trued": 0.1}
GOOD_ORDER = ["Q", "E", "W", "Q", "Q", "R"]
GOOD_CD = {"Q": [14, 12, 10, 8, 6, None]}
PATCH = "99.1.1"


def _ids(rows: int) -> list[str]:
    return [f"Champ{i:03d}" for i in range(rows)]


def _aram(rows: int) -> dict[str, dict]:
    return {cid: dict(CLEAN) for cid in _ids(rows)}


# --- the gate ------------------------------------------------------------------

def test_a_short_clean_table_raises_naming_the_coverage():
    """The RM-913 shape: 20 clean rows for a 173-champion roster."""
    with pytest.raises(dse.NeutralAramTableError) as exc:
        dse.check_aram_neutrality(_aram(20), roster=_ids(173))
    msg = str(exc.value)
    assert "covers 20/173 of the DDragon roster" in msg
    assert "RM-913" in msg
    assert "--allow-neutral-aram" in msg


def test_the_same_table_without_a_roster_still_passes():
    """Pins the gap this closes: the RM-805 measurement alone cannot see it."""
    out = dse.check_aram_neutrality(_aram(20))
    assert out["neutral_rows"] == 0
    assert "coverage" not in out


def test_coverage_just_under_the_floor_raises_and_at_the_floor_passes():
    # 165/173 = 95.4 percent is at the floor; 164/173 = 94.8 percent is under.
    with pytest.raises(dse.NeutralAramTableError, match="covers 164/173"):
        dse.check_aram_neutrality(_aram(164), roster=_ids(173))
    out = dse.check_aram_neutrality(_aram(165), roster=_ids(173))
    assert out["missing_rows"] == 8
    assert out["coverage"] == round(165 / 173, 4)


def test_a_missing_champion_above_the_floor_is_named_in_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = dse.check_aram_neutrality(_aram(172), roster=_ids(173))
    assert out["missing_rows"] == 1
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "Champ172" in text and "DDragon" in text


def test_full_coverage_passes_without_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = dse.check_aram_neutrality(_aram(173), roster=_ids(173))
    assert out["missing_rows"] == 0
    assert out["coverage"] == 1.0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_ids_outside_the_roster_neither_count_nor_fail():
    table = _aram(20)
    for i in range(200):
        table[f"Extra{i:03d}"] = dict(CLEAN)
    with pytest.raises(dse.NeutralAramTableError, match="covers 20/173"):
        dse.check_aram_neutrality(table, roster=_ids(173))


@pytest.mark.parametrize("roster", [None, [], set()])
def test_without_a_roster_the_measurement_is_unchanged(roster):
    base = dse.check_aram_neutrality(_aram(173))
    assert dse.check_aram_neutrality(_aram(173), roster=roster) == base


def test_an_empty_table_is_left_to_the_empty_table_failure():
    with pytest.raises(dse.NeutralAramTableError) as exc:
        dse.check_aram_neutrality({}, roster=_ids(173))
    assert "empty (0 rows)" in str(exc.value)
    assert "of the DDragon roster" not in str(exc.value)


def test_an_overridden_empty_table_still_passes():
    """The acceptance the design call protects: an RM-805 carry stays exit 0."""
    reason = "RM-999 adjudication: carry the previous ARAM block forward"
    out = dse.check_aram_neutrality({}, override_reason=reason, roster=_ids(173))
    assert out["override_reason"] == reason
    assert "coverage" not in out


def test_both_failures_are_named_together():
    table = {cid: {} for cid in _ids(20)}
    with pytest.raises(dse.NeutralAramTableError) as exc:
        dse.check_aram_neutrality(table, roster=_ids(173))
    msg = str(exc.value)
    assert "20/20 neutral" in msg and "covers 20/173" in msg


def test_the_override_accepts_and_records_the_coverage(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    reason = "RM-999 adjudication: lolmath ships a partial ARAM table"
    out = dse.check_aram_neutrality(_aram(20), override_reason=reason, roster=_ids(173))
    assert out["override_reason"] == reason
    assert out["missing_rows"] == 153
    rec = dse._neutral_override_record(out)
    assert rec["coverage"] == round(20 / 173, 4)
    assert rec["missing_rows"] == 153
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert reason in text and "covers 20/173" in text


def test_an_override_record_without_a_roster_keeps_its_shape():
    out = dse.check_aram_neutrality({}, override_reason="carry")
    assert set(dse._neutral_override_record(out)) == {
        "flag", "reason", "rows", "neutral_rows", "neutral_fraction", "threshold"}


# --- the committed snapshots stay green ----------------------------------------

def test_every_committed_snapshot_covers_the_ddragon_roster():
    snaps = sorted(p for p in (ROOT / "data" / "daemon_slayer").iterdir()
                   if (p / "champions.json").is_file())
    assert len(snaps) >= 5
    for snap in snaps:
        data = json.loads((snap / "champions.json").read_text(encoding="utf-8"))["data"]
        roster = canonical_champions(data)
        assert len(roster) >= 170, snap.name
        table = {cid: aram for cid, rec in data.items()
                 if (aram := (rec.get("lolmath") or {}).get("aram_modifiers")) is not None}
        out = dse.check_aram_neutrality(table, roster=roster)
        assert out["missing_rows"] == 0, (snap.name, out)


# --- main(): both entry points measure against the DDragon roster ---------------

def _ddragon(rows: int) -> dict[str, dict]:
    return {cid: {"key": str(i + 1), "name": cid, "stats": {}}
            for i, cid in enumerate(_ids(rows))}


def _wire_lolmath(monkeypatch, aram, roster_rows=173):
    """Clean RM-807 blocks over the whole roster, so only the ARAM gate decides."""
    ids = _ids(roster_rows)
    monkeypatch.setattr(dse, "discover_chunks",
                        lambda *a, **k: ("u/scen.js", "u/aram.js"))
    monkeypatch.setattr(dse, "fetch_chunk", lambda url: "")
    monkeypatch.setattr(dse, "extract_from_bodies", lambda bodies, preferred: dse.LolmathExtract(
        cooldowns={cid: dict(GOOD_CD) for cid in ids},
        roles={cid: ["FIGHTER"] for cid in ids},
        ratings={cid: {"ratings": {"healing": 2, "shielding": 0}} for cid in ids},
        lane_positions=["top"], scenarios={"champ000": [{}]},
        chunk_url="u/scen.js", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    ))
    monkeypatch.setattr(dse, "extract_data_blocks", lambda bodies, preferred: {
        "aram_modifiers": aram,
        "damage_distribution": {cid: dict(GOOD_SPLIT) for cid in ids},
        "skill_orders": {cid: list(GOOD_ORDER) for cid in ids},
        "data_chunk_url": "u/aram.js",
        "data_chunk_bytes": 1,
        "block_sources": {"aram_modifiers": "u/aram.js"},
    })


def _wire_main(monkeypatch, tmp_path, aram, argv, *, network_ok):
    data_root = tmp_path / "data" / "daemon_slayer"
    monkeypatch.setattr(dse, "ROOT", tmp_path)
    monkeypatch.setattr(dse, "DATA_ROOT", data_root)
    # The synthetic DDragon map sits under the RM-910 floors, which
    # tests/test_ds_extract_ddragon_counts.py covers on its own.
    monkeypatch.setattr(dse, "DDRAGON_CHAMPIONS_MIN", 0)
    monkeypatch.setattr(dse, "DDRAGON_ITEMS_MIN", 0)
    monkeypatch.setattr(dse, "fetch_ddragon", lambda: dse.DDragonSnapshot(
        version=PATCH, champions=_ddragon(173), items={}))
    _wire_lolmath(monkeypatch, aram)

    def _no_network(*a, **k):
        raise AssertionError("network fetch after the RM-805 gate")

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
    monkeypatch.setattr(sys, "argv", ["daemon_slayer_extract.py", "--patch", PATCH, *argv])
    return data_root


def test_main_exits_non_zero_and_writes_nothing(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.ERROR, logger="daemon_slayer_extract")
    data_root = _wire_main(monkeypatch, tmp_path, _aram(20), [], network_ok=False)
    assert dse.main() == dse.EXIT_ARAM_NEUTRAL
    assert not data_root.exists() or not any(data_root.rglob("*"))
    errors = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "covers 20/173 of the DDragon roster" in errors


def test_main_full_table_writes_without_an_override(monkeypatch, tmp_path):
    data_root = _wire_main(monkeypatch, tmp_path, _aram(173), [], network_ok=True)
    assert dse.main() == 0
    manifest = json.loads((data_root / PATCH / "manifest.json").read_text(encoding="utf-8"))
    assert "aram_modifiers_neutral_override" not in manifest


def test_main_override_writes_and_records_the_coverage(monkeypatch, tmp_path):
    reason = "RM-999 adjudication: accept the partial ARAM table"
    data_root = _wire_main(monkeypatch, tmp_path, _aram(20),
                           ["--allow-neutral-aram", reason], network_ok=True)
    assert dse.main() == 0
    manifest = json.loads((data_root / PATCH / "manifest.json").read_text(encoding="utf-8"))
    rec = manifest["aram_modifiers_neutral_override"]
    assert rec["reason"] == reason
    assert rec["missing_rows"] == 153


def test_main_overridden_empty_table_still_exits_zero(monkeypatch, tmp_path):
    data_root = _wire_main(monkeypatch, tmp_path, {},
                           ["--allow-neutral-aram", "RM-999 carry"], network_ok=True)
    assert dse.main() == 0
    manifest = json.loads((data_root / PATCH / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["aram_modifiers_neutral_override"]["rows"] == 0


def test_lolmath_only_measures_against_the_snapshot_roster(monkeypatch):
    """``--lolmath-only`` shares ``_extract_lolmath``; its roster is champions.json."""
    _wire_lolmath(monkeypatch, _aram(20))
    args = dse.argparse.Namespace(chunk_url=None, data_chunk_url=None,
                                  allow_neutral_aram=None, allow_degenerate_lolmath=None)
    with pytest.raises(dse.NeutralAramTableError, match="covers 20/173"):
        dse._extract_lolmath(args, _ddragon(173))
