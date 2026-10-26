"""RM-914: the lolmath cooldown table must cover the DDragon champion roster.

RM-807 (c) and RM-887 measure every other lolmath block against the cooldown
table, but nothing measured the cooldown table itself against DDragon. If every
lolmath table shrank together (20 clean rows each for a 173-champion DDragon
roster), every gate passed and the other 153 champions got ``None`` in each
``lolmath`` sub-object of ``champions.json``.

The roster is the CANONICAL DDragon champion set (``canonical_champions``: the
throwback rows DDragon 16.15.1 shipped at key + 60000 are not champions). Every
committed snapshot 16.10.1 .. 16.21.1 carries a cooldown row for every
canonical champion (172/172 or 173/173, measured), so a cooldown table under
``LOLMATH_COVERAGE_FLOOR`` of that roster now fails under the RM-807 exit 5
and the ``--allow-degenerate-lolmath REASON`` override, recorded in the
manifest. A champion missing below the floor is named in a WARNING; an id that
DDragon does not list neither counts nor fails. The full extract reads the
roster from ``fetch_ddragon``; ``--lolmath-only`` reads it from the snapshot's
own ``champions.json``.

Every test is synthetic (no network, no live-tree write) except the snapshot
guard, which only reads the committed snapshots.
"""
from __future__ import annotations

import hashlib
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

GOOD_SPLIT = {"physical": 0.8, "magical": 0.1, "trued": 0.1}
GOOD_ORDER = ["Q", "E", "W", "Q", "Q", "R"]
GOOD_CD = {"Q": [14, 12, 10, 8, 6, None], "E": [9, 8, 7, 6, 5, None]}
PATCH = "99.1.1"


def _ids(rows: int) -> list[str]:
    return [f"Champ{i:03d}" for i in range(rows)]


def _tables(rows: int) -> dict[str, dict]:
    """Clean, mutually consistent lolmath tables over the first ``rows`` ids."""
    return {
        "cooldowns": {cid: dict(GOOD_CD) for cid in _ids(rows)},
        "roles": {cid: ["FIGHTER"] for cid in _ids(rows)},
        "damage_distribution": {cid: dict(GOOD_SPLIT) for cid in _ids(rows)},
        "skill_orders": {cid: list(GOOD_ORDER) for cid in _ids(rows)},
    }


def _check(t, ddragon_ids, override_reason=None):
    return dse.check_lolmath_blocks(t["damage_distribution"], t["skill_orders"],
                                    override_reason, cooldowns=t["cooldowns"],
                                    roles=t["roles"], ddragon_ids=ddragon_ids)


# --- the gate ------------------------------------------------------------------

def test_tables_that_shrink_together_raise():
    """The RM-914 shape: every block agrees with a short cooldown table."""
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        _check(_tables(20), _ids(173))
    msg = str(exc.value)
    assert "cooldowns covers 20/173 of the DDragon roster" in msg
    assert "--allow-degenerate-lolmath" in msg


def test_the_same_tables_without_a_roster_still_pass():
    """Pins the gap this closes: the RM-887 measurement alone cannot see it."""
    out = dse.check_lolmath_blocks(*(_tables(20)[k] for k in
                                     ("damage_distribution", "skill_orders")),
                                   cooldowns=_tables(20)["cooldowns"],
                                   roles=_tables(20)["roles"])
    assert "coverage" not in out["cooldowns"]


def test_coverage_just_under_the_floor_raises_and_at_the_floor_passes():
    # 165/173 = 95.4 percent is at the floor; 164/173 = 94.8 percent is under.
    with pytest.raises(dse.DegenerateLolmathBlockError, match="cooldowns covers 164/173"):
        _check(_tables(164), _ids(173))
    out = _check(_tables(165), _ids(173))
    assert out["cooldowns"]["missing_rows"] == 8
    assert out["cooldowns"]["coverage"] == round(165 / 173, 4)


def test_a_missing_champion_below_the_floor_is_named_in_a_warning(caplog):
    # A champion DDragon ships before lolmath lists it is a warning, not a stop.
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = _check(_tables(172), _ids(173))
    assert out["cooldowns"]["missing_rows"] == 1
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "Champ172" in text and "DDragon" in text


def test_full_coverage_passes_without_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = _check(_tables(173), _ids(173))
    assert out["cooldowns"]["missing_rows"] == 0
    assert out["cooldowns"]["coverage"] == 1.0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_ids_outside_the_roster_neither_count_nor_fail():
    t = _tables(20)
    for cid in (f"Extra{i:03d}" for i in range(200)):
        t["cooldowns"][cid] = dict(GOOD_CD)
    with pytest.raises(dse.DegenerateLolmathBlockError, match="cooldowns covers 20/173"):
        _check(t, _ids(173))


@pytest.mark.parametrize("ddragon_ids", [None, [], set()])
def test_without_a_roster_the_measurement_is_unchanged(ddragon_ids):
    t = _tables(173)
    base = dse.check_lolmath_blocks(t["damage_distribution"], t["skill_orders"],
                                    cooldowns=t["cooldowns"], roles=t["roles"])
    assert _check(t, ddragon_ids) == base
    assert "coverage" not in base["cooldowns"]


def test_an_empty_cooldown_table_is_left_to_the_empty_table_failure():
    t = _tables(173)
    t["cooldowns"] = {}
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        _check(t, _ids(173))
    assert "cooldowns empty (0 rows)" in str(exc.value)
    assert "of the DDragon roster" not in str(exc.value)


def test_the_override_accepts_and_records_the_coverage():
    reason = "RM-999 adjudication: lolmath ships a partial roster this patch"
    out = _check(_tables(20), _ids(173), override_reason=reason)
    assert out["override_reason"] == reason
    assert out["cooldowns"]["missing_rows"] == 153
    rec = dse._degenerate_override_record(out)
    assert rec["blocks"]["cooldowns"]["coverage"] == round(20 / 173, 4)


# --- the committed snapshots stay green ----------------------------------------

def _present(lm: dict, field: str) -> dict:
    """The rows champions.json actually carries, as the extract's block shape."""
    return {cid: b[field] for cid, b in lm.items() if b.get(field) is not None}


def test_every_committed_snapshot_covers_the_ddragon_roster():
    snaps = sorted(p for p in (ROOT / "data" / "daemon_slayer").iterdir()
                   if (p / "champions.json").is_file())
    assert len(snaps) >= 5
    for snap in snaps:
        data = json.loads((snap / "champions.json").read_text(encoding="utf-8"))["data"]
        roster = canonical_champions(data)
        assert len(roster) >= 170, snap.name
        lm = {cid: rec.get("lolmath") or {} for cid, rec in data.items()}

        out = dse.check_lolmath_blocks(_present(lm, "damage_distribution"),
                                       _present(lm, "skill_order"),
                                       cooldowns=_present(lm, "cooldowns"),
                                       roles=_present(lm, "roles"), ddragon_ids=roster)
        assert out["cooldowns"]["missing_rows"] == 0, (snap.name, out["cooldowns"])


# --- main(): the full extract reads the roster from DDragon ---------------------

def _ddragon(rows: int, variants: int = 0) -> dict[str, dict]:
    champs = {cid: {"key": str(i + 1), "name": cid, "stats": {}}
              for i, cid in enumerate(_ids(rows))}
    for i in range(variants):
        champs[f"Jade_Champ{i:03d}"] = {"key": str(60001 + i), "name": f"Jade {i}",
                                        "stats": {}}
    return champs


def _wire_main(monkeypatch, tmp_path, t, ddragon, argv, *, network_ok):
    data_root = tmp_path / "data" / "daemon_slayer"
    monkeypatch.setattr(dse, "ROOT", tmp_path)
    monkeypatch.setattr(dse, "DATA_ROOT", data_root)
    # The synthetic DDragon map sits under the RM-910 floors, which
    # tests/test_ds_extract_ddragon_counts.py covers on its own.
    monkeypatch.setattr(dse, "DDRAGON_CHAMPIONS_MIN", 0)
    monkeypatch.setattr(dse, "DDRAGON_ITEMS_MIN", 0)
    monkeypatch.setattr(dse, "fetch_ddragon", lambda: dse.DDragonSnapshot(
        version=PATCH, champions=ddragon, items={}))
    monkeypatch.setattr(dse, "discover_chunks",
                        lambda *a, **k: ("u/scen.js", "u/aram.js"))
    monkeypatch.setattr(dse, "fetch_chunk", lambda url: "")
    monkeypatch.setattr(dse, "extract_from_bodies", lambda bodies, preferred: dse.LolmathExtract(
        cooldowns=t["cooldowns"], roles=t["roles"],
        ratings={cid: {"ratings": {"healing": 2, "shielding": 0}} for cid in t["cooldowns"]},
        lane_positions=["top"], scenarios={"champ000": [{}]},
        chunk_url="u/scen.js", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    ))
    # The ARAM table covers the DDragon roster, so the RM-913 gate stays
    # out of the way and only the RM-807 gate decides.
    monkeypatch.setattr(dse, "extract_data_blocks", lambda bodies, preferred: {
        "aram_modifiers": {cid: {"aramDamageDealt": 1.05} for cid in ddragon},
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
    monkeypatch.setattr(sys, "argv", ["daemon_slayer_extract.py", "--patch", PATCH, *argv])
    return data_root


def test_main_exits_non_zero_and_writes_nothing(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.ERROR, logger="daemon_slayer_extract")
    data_root = _wire_main(monkeypatch, tmp_path, _tables(20), _ddragon(173), [],
                           network_ok=False)
    assert dse.main() == dse.EXIT_LOLMATH_DEGENERATE
    assert not data_root.exists() or not any(data_root.rglob("*"))
    errors = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "RM-807" in errors and "cooldowns covers 20/173 of the DDragon roster" in errors


def test_main_does_not_count_throwback_rows(monkeypatch, tmp_path):
    # 60 variant rows would make 173/233 = 74 percent and stop a clean extract.
    data_root = _wire_main(monkeypatch, tmp_path, _tables(173), _ddragon(173, variants=60),
                           [], network_ok=True)
    assert dse.main() == 0
    assert (data_root / PATCH / "manifest.json").is_file()


def test_main_override_writes_and_records_the_coverage(monkeypatch, tmp_path):
    reason = "RM-999 adjudication: accept the partial lolmath roster"
    data_root = _wire_main(monkeypatch, tmp_path, _tables(20), _ddragon(173),
                           ["--allow-degenerate-lolmath", reason], network_ok=True)
    assert dse.main() == 0
    manifest = json.loads((data_root / PATCH / "manifest.json").read_text(encoding="utf-8"))
    rec = manifest["lolmath_degenerate_override"]
    assert rec["reason"] == reason
    assert rec["blocks"]["cooldowns"]["missing_rows"] == 153


# --- --lolmath-only: the roster is the snapshot's own champions.json ------------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wire_lolmath_only(monkeypatch, tmp_path, t, snapshot_rows, argv):
    data_root = tmp_path / "data" / "daemon_slayer"
    patch_dir = data_root / PATCH
    patch_dir.mkdir(parents=True)
    champs = _ddragon(snapshot_rows)
    for rec in champs.values():
        rec["lolmath"] = {"cooldowns": dict(GOOD_CD)}
    dse._atomic_write_json(patch_dir / "champions.json", {"version": PATCH, "data": champs})
    dse._atomic_write_json(patch_dir / "scenarios.json", {"version": PATCH})
    dse._atomic_write_json(patch_dir / "manifest.json", {
        "ddragon_version": PATCH, "sources": {}, "lolmath_counts": {}})
    dse._atomic_write_text(data_root / "current.txt", PATCH)
    monkeypatch.setattr(dse, "ROOT", tmp_path)
    monkeypatch.setattr(dse, "DATA_ROOT", data_root)

    def _no_network(*a, **k):
        raise AssertionError("--lolmath-only must not fetch DDragon / Meraki / CDragon")

    for name in ("fetch_ddragon", "fetch_meraki_perlevel_overlay",
                 "fetch_arena_augments", "fetch_meraki_items",
                 "_fetch_text", "_fetch_json"):
        monkeypatch.setattr(dse, name, _no_network)
    monkeypatch.setattr(dse, "discover_chunks",
                        lambda *a, **k: ("u/scen.js", "u/aram.js"))
    monkeypatch.setattr(dse, "fetch_chunk", lambda url: "")
    monkeypatch.setattr(dse, "extract_from_bodies", lambda bodies, preferred: dse.LolmathExtract(
        cooldowns=t["cooldowns"], roles=t["roles"],
        ratings={cid: {"ratings": {"healing": 2, "shielding": 0}} for cid in t["cooldowns"]},
        lane_positions=["top"], scenarios={"champ000": [{}]},
        chunk_url="u/scen.js", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    ))
    monkeypatch.setattr(dse, "extract_data_blocks", lambda bodies, preferred: {
        "aram_modifiers": {cid: {"aramDamageDealt": 1.05} for cid in champs},
        "damage_distribution": t["damage_distribution"],
        "skill_orders": t["skill_orders"],
        "data_chunk_url": "u/aram.js",
        "data_chunk_bytes": 1,
        "block_sources": {},
    })
    monkeypatch.setattr(sys, "argv", ["daemon_slayer_extract.py", "--lolmath-only",
                                      "--patch", PATCH, *argv])
    return data_root, patch_dir


def test_lolmath_only_short_roster_exits_5_and_changes_nothing(monkeypatch, tmp_path):
    data_root, patch_dir = _wire_lolmath_only(monkeypatch, tmp_path, _tables(20), 173, [])
    before = {p.name: _sha(p) for p in patch_dir.iterdir()}
    assert dse.main() == dse.EXIT_LOLMATH_DEGENERATE
    assert {p.name: _sha(p) for p in patch_dir.iterdir()} == before


def test_lolmath_only_full_roster_writes(monkeypatch, tmp_path):
    data_root, patch_dir = _wire_lolmath_only(monkeypatch, tmp_path, _tables(173), 173, [])
    assert dse.main() == 0
    champs = json.loads((patch_dir / "champions.json").read_text(encoding="utf-8"))["data"]
    assert champs["Champ172"]["lolmath"]["roles"] == ["FIGHTER"]
