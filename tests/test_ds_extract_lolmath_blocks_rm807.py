"""RM-807 (a) + (b): the extractor must fail loudly on a degenerate lolmath
damage-split or skill-order block.

RM-805 closed the silent accept of an all-neutral ARAM table. Its sibling sweep
found the other two lolmath data blocks have the same silent-default shape:
an all-zero ``damage_distribution`` row (or an empty block) and an empty
``skill_orders`` list are written into ``champions.json`` exactly like real
data, and the engine reads a zero split as "no damage axis". Every committed
snapshot 16.10.1 .. 16.21.1 carries 0 degenerate rows in either block, so a
block that comes back >= 95 percent degenerate is an upstream reset or parser
drift, not a balance patch.

``main()`` now exits ``EXIT_LOLMATH_DEGENERATE`` with a named reason before any
later fetch and before any file is written. The one way past it is the explicit
``--allow-degenerate-lolmath REASON`` flag, which logs a WARNING and records the
override (reason and per-block counts) in the manifest. Below the floor a
degenerate row is still named in a WARNING, never accepted silently.

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
ZERO_SPLIT = {"physical": 0, "magical": 0, "trued": 0}
GOOD_ORDER = ["Q", "E", "W", "Q", "Q", "R"]


def _damage(rows: int, degenerate: int) -> dict[str, dict]:
    return {f"Champ{i:03d}": dict(ZERO_SPLIT if i < degenerate else GOOD_SPLIT)
            for i in range(rows)}


def _skills(rows: int, degenerate: int) -> dict[str, list]:
    return {f"Champ{i:03d}": ([] if i < degenerate else list(GOOD_ORDER))
            for i in range(rows)}


# --- the threshold -------------------------------------------------------------

def test_threshold_and_exit_code():
    assert dse.LOLMATH_BLOCK_FAIL_FRACTION == 0.95
    # Distinct from RM-805's exit 3 and --lolmath-only's exit 4.
    assert dse.EXIT_LOLMATH_DEGENERATE not in (0, dse.EXIT_ARAM_NEUTRAL,
                                               dse.EXIT_LOLMATH_ONLY_NO_SNAPSHOT)


def test_an_all_zero_damage_block_raises_naming_the_block_and_counts():
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        dse.check_lolmath_blocks(_damage(173, 173), _skills(173, 0))
    msg = str(exc.value)
    assert "RM-807" in msg
    assert "damage_distribution" in msg
    assert "173/173" in msg
    assert "--allow-degenerate-lolmath" in msg
    assert "skill_orders" not in msg


def test_an_all_empty_skill_block_raises_naming_the_block():
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        dse.check_lolmath_blocks(_damage(173, 0), _skills(173, 173))
    msg = str(exc.value)
    assert "skill_orders" in msg and "173/173" in msg
    assert "damage_distribution" not in msg


def test_both_blocks_degenerate_are_both_named():
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        dse.check_lolmath_blocks(_damage(10, 10), _skills(10, 10))
    msg = str(exc.value)
    assert "damage_distribution" in msg and "skill_orders" in msg


@pytest.mark.parametrize("which", ["damage", "skills"])
def test_an_empty_block_raises(which):
    damage = {} if which == "damage" else _damage(5, 0)
    skills = {} if which == "skills" else _skills(5, 0)
    with pytest.raises(dse.DegenerateLolmathBlockError, match="0 rows"):
        dse.check_lolmath_blocks(damage, skills)


def test_exactly_95_percent_degenerate_raises():
    with pytest.raises(dse.DegenerateLolmathBlockError, match="95/100"):
        dse.check_lolmath_blocks(_damage(100, 95), _skills(100, 0))


def test_94_percent_degenerate_passes_and_names_the_rows(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = dse.check_lolmath_blocks(_damage(100, 94), _skills(100, 2))
    assert out["threshold"] == 0.95
    assert out["damage_distribution"]["rows"] == 100
    assert out["damage_distribution"]["degenerate_rows"] == 94
    assert out["damage_distribution"]["degenerate_fraction"] == pytest.approx(0.94)
    assert out["skill_orders"]["degenerate_rows"] == 2
    assert "override_reason" not in out
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    # A degenerate row below the floor is named, never accepted silently.
    assert "Champ000" in text and "Champ001" in text
    assert "skill_orders" in text


def test_a_clean_table_passes_without_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = dse.check_lolmath_blocks(_damage(173, 0), _skills(173, 0))
    assert out["damage_distribution"]["degenerate_rows"] == 0
    assert out["skill_orders"]["degenerate_rows"] == 0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# --- what "degenerate" means ---------------------------------------------------

@pytest.mark.parametrize("row, degenerate", [
    (dict(GOOD_SPLIT), False),
    ({"physical": 0.0, "magical": 1.0, "trued": 0.0}, False),
    ({"physical": 0, "magical": 0, "trued": 0.42}, False),
    (dict(ZERO_SPLIT), True),
    ({}, True),
    (None, True),
    ([], True),
    # A non-numeric or non-finite value carries no information.
    ({"physical": "0.8", "magical": None, "trued": 0}, True),
    ({"physical": float("nan"), "magical": 0, "trued": 0}, True),
    ({"physical": float("inf"), "magical": 0, "trued": 0}, True),
    # A bool is not a share (True would otherwise read as 1.0).
    ({"physical": True, "magical": 0, "trued": 0}, True),
    # A negative share is not a damage axis.
    ({"physical": -0.5, "magical": 0, "trued": 0}, True),
    # Only the three consumed fields count.
    ({"physical": 0, "magical": 0, "trued": 0, "other": 1.0}, True),
])
def test_damage_row_degeneracy(row, degenerate):
    assert dse._damage_row_is_degenerate(row) is degenerate


@pytest.mark.parametrize("row, degenerate", [
    (list(GOOD_ORDER), False),
    # Real orders carry a None slot at some levels (measured in 16.x snapshots).
    (["Q", None, "E", "W"], False),
    ([], True),
    (None, True),
    ({}, True),
    ("QEW", True),
    ([None, None], True),
    (["", "x", 1], True),
])
def test_skill_row_degeneracy(row, degenerate):
    assert dse._skill_order_is_degenerate(row) is degenerate


def test_every_committed_snapshot_has_zero_degenerate_rows():
    # The floor must never fire on real data, and the measured baseline is
    # zero, so a single degenerate row in a committed snapshot is a regression.
    snaps = sorted(p for p in (ROOT / "data" / "daemon_slayer").iterdir()
                   if (p / "champions.json").is_file())
    assert len(snaps) >= 5
    for snap in snaps:
        data = json.loads((snap / "champions.json").read_text(encoding="utf-8"))["data"]
        assert len(data) >= 170, snap.name
        damage = {cid: (rec.get("lolmath") or {}).get("damage_distribution")
                  for cid, rec in data.items()}
        skills = {cid: (rec.get("lolmath") or {}).get("skill_order")
                  for cid, rec in data.items()}
        out = dse.check_lolmath_blocks(damage, skills)
        assert out["damage_distribution"]["degenerate_rows"] == 0, (snap.name, out)
        assert out["skill_orders"]["degenerate_rows"] == 0, (snap.name, out)


# --- the explicit override -----------------------------------------------------

def test_the_override_accepts_and_logs_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    reason = "RM-999 adjudication: lolmath outage, carry 16.20.1"
    out = dse.check_lolmath_blocks(_damage(173, 173), _skills(173, 0),
                                   override_reason=reason)
    assert out["override_reason"] == reason
    assert out["damage_distribution"]["degenerate_rows"] == 173
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "RM-807" in text and "173/173" in text and reason in text


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_blank_override_reason_does_not_override(reason):
    with pytest.raises(dse.DegenerateLolmathBlockError):
        dse.check_lolmath_blocks(_damage(173, 173), _skills(173, 0),
                                 override_reason=reason)


def test_an_unneeded_override_is_not_recorded():
    out = dse.check_lolmath_blocks(_damage(173, 0), _skills(173, 0),
                                   override_reason="not needed")
    assert "override_reason" not in out


# --- main(): the gate is wired before any later fetch or write ------------------

NEUTRAL_OK_ARAM = {f"Champ{i:03d}": {"aramDamageDealt": 1.05} for i in range(173)}


def _lolmath():
    return dse.LolmathExtract(
        cooldowns={"Aatrox": {"Q": [4.0]}}, roles={"Aatrox": ["FIGHTER"]},
        ratings={}, lane_positions=["top"], scenarios={"aatrox": [{}]},
        chunk_url="u/scen.js", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    )


def _wire_main(monkeypatch, tmp_path, damage, skills, argv, *, network_ok):
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
        "aram_modifiers": NEUTRAL_OK_ARAM,
        "damage_distribution": damage,
        "skill_orders": skills,
        "data_chunk_url": "u/aram.js",
        "data_chunk_bytes": 1,
        "block_sources": {"aram_modifiers": "u/aram.js"},
    })

    def _no_network(*a, **k):
        raise AssertionError("network fetch after the RM-807 gate")

    if network_ok:
        monkeypatch.setattr(dse, "fetch_meraki_perlevel_overlay", lambda ids: {})
        # Full-size payloads, so the RM-807 (d) upstream floor stays out of the way.
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


@pytest.mark.parametrize("damage, skills, block", [
    (_damage(173, 173), _skills(173, 0), "damage_distribution"),
    (_damage(173, 0), _skills(173, 173), "skill_orders"),
    ({}, _skills(173, 0), "damage_distribution"),
])
def test_main_exits_non_zero_and_writes_nothing_on_a_degenerate_block(
        monkeypatch, tmp_path, caplog, damage, skills, block):
    caplog.set_level(logging.ERROR, logger="daemon_slayer_extract")
    data_root = _wire_main(monkeypatch, tmp_path, damage, skills, [], network_ok=False)
    rc = dse.main()
    assert rc == dse.EXIT_LOLMATH_DEGENERATE
    assert not data_root.exists() or not any(data_root.rglob("*"))
    errors = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "RM-807" in errors and block in errors


def test_main_override_writes_and_records_the_override(monkeypatch, tmp_path):
    reason = "RM-999 adjudication: accept the reset"
    data_root = _wire_main(
        monkeypatch, tmp_path, _damage(173, 173), _skills(173, 0),
        ["--allow-degenerate-lolmath", reason], network_ok=True,
    )
    assert dse.main() == 0
    manifest = json.loads((data_root / "99.1.1" / "manifest.json").read_text(encoding="utf-8"))
    rec = manifest["lolmath_degenerate_override"]
    assert rec["flag"] == "--allow-degenerate-lolmath"
    assert rec["reason"] == reason
    assert rec["threshold"] == 0.95
    assert rec["blocks"]["damage_distribution"]["degenerate_rows"] == 173
    assert rec["blocks"]["skill_orders"]["degenerate_rows"] == 0


def test_main_clean_blocks_record_no_override(monkeypatch, tmp_path):
    data_root = _wire_main(monkeypatch, tmp_path, _damage(173, 0), _skills(173, 0), [],
                           network_ok=True)
    assert dse.main() == 0
    manifest = json.loads((data_root / "99.1.1" / "manifest.json").read_text(encoding="utf-8"))
    assert "lolmath_degenerate_override" not in manifest


# --- refresh_manifest_lolmath (--lolmath-only) ----------------------------------

def test_refresh_records_an_override_and_drops_a_stale_one():
    lolmath = _lolmath()
    aram_check = {"rows": 1, "neutral_rows": 0, "neutral_fraction": 0.0, "threshold": 0.95}
    stale = {"lolmath_degenerate_override": {"reason": "old"}, "sources": {}}
    block_check = dse.check_lolmath_blocks(_damage(5, 5), _skills(5, 0),
                                           override_reason="new adjudication")
    out = dse.refresh_manifest_lolmath(stale, lolmath, aram_check, keep_carry=False,
                                       block_check=block_check)
    assert out["lolmath_degenerate_override"]["reason"] == "new adjudication"
    clean = dse.check_lolmath_blocks(_damage(5, 0), _skills(5, 0))
    out = dse.refresh_manifest_lolmath(stale, lolmath, aram_check, keep_carry=False,
                                       block_check=clean)
    assert "lolmath_degenerate_override" not in out
