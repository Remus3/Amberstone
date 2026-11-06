"""RM-915: the lolmath ratings table goes through the RM-807 block gate.

Nothing measured the ratings dict (``{Aatrox: {ratings: {healing, shielding}}}``).
``_lolmath_block`` writes ``ratings: None`` for every champion it does not name,
and ``core/build_planner/champ_kit_data.py`` reads that score to tell an
enchanter support (``max(healing, shielding) >= 4``) from any other support,
so a short, empty or zeroed table silently re-classifies champions.

Measured at authoring: every committed snapshot 16.10.1 .. 16.21.1 carries a
ratings row with integer healing and shielding for every champion; scores run
0 .. 10 and 42 of 173 champions score 0 / 0 at 16.21.1, so zero is a real
score. The table is now gated like the cooldown, role and data blocks: same 95
percent degenerate floor, same coverage floor against the cooldown roster, and
a table at that floor scoring 0 / 0 everywhere fails too. Same
``EXIT_LOLMATH_DEGENERATE``, same ``--allow-degenerate-lolmath REASON``.

Every test is synthetic except the committed-snapshot read (no network, no
live-tree write).
"""
from __future__ import annotations

import argparse
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
GOOD_CD = {"Q": [4.0]}


def _ids(rows: int) -> list[str]:
    return [f"Champ{i:03d}" for i in range(rows)]


def _rating(healing, shielding=0) -> dict:
    return {"ratings": {"healing": healing, "shielding": shielding}}


def _ratings(rows: int, *, degenerate: int = 0, zero: int = 0) -> dict[str, dict]:
    out = {}
    for i, cid in enumerate(_ids(rows)):
        if i < degenerate:
            out[cid] = {"ratings": {}}
        elif i < degenerate + zero:
            out[cid] = _rating(0, 0)
        else:
            out[cid] = _rating(4, 2)
    return out


def _check(ratings, override_reason=None, roster=173):
    ids = _ids(roster)
    return dse.check_lolmath_blocks(
        {cid: dict(GOOD_SPLIT) for cid in ids},
        {cid: list(GOOD_ORDER) for cid in ids},
        override_reason,
        cooldowns={cid: dict(GOOD_CD) for cid in ids},
        roles={cid: ["SUPPORT"] for cid in ids},
        ratings=ratings,
    )


# --- the gate ------------------------------------------------------------------

def test_an_empty_ratings_table_raises():
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        _check({})
    msg = str(exc.value)
    assert "RM-807" in msg and "ratings empty (0 rows)" in msg
    assert "--allow-degenerate-lolmath" in msg


def test_a_short_ratings_table_raises_against_the_cooldown_roster():
    # The filing's shape: 20 clean rows for a 173-champion cooldown roster.
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        _check(_ratings(20))
    msg = str(exc.value)
    assert "ratings covers 20/173 of the cooldown roster" in msg
    for name in ("cooldowns", "roles", "damage_distribution", "skill_orders"):
        assert f"{name} " not in msg


def test_an_all_degenerate_ratings_table_raises():
    with pytest.raises(dse.DegenerateLolmathBlockError, match="ratings 173/173 degenerate"):
        _check(_ratings(173, degenerate=173))


def test_an_all_zero_ratings_table_raises():
    # Every row is well-formed, so only the block view sees the reset.
    with pytest.raises(dse.DegenerateLolmathBlockError) as exc:
        _check(_ratings(173, zero=173))
    assert "ratings 173/173 score 0 healing and 0 shielding" in str(exc.value)


def test_the_committed_zero_share_passes_without_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = _check(_ratings(173, zero=42))
    assert out["ratings"] == {"rows": 173, "degenerate_rows": 0,
                              "degenerate_fraction": 0.0, "zero_rows": 42,
                              "missing_rows": 0, "coverage": 1.0}
    assert "override_reason" not in out
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_below_the_floors_the_rows_are_named_in_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    ratings = _ratings(173, degenerate=1)
    del ratings["Champ172"]
    out = _check(ratings)
    assert out["ratings"]["degenerate_rows"] == 1
    assert out["ratings"]["missing_rows"] == 1
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "ratings" in text and "Champ000" in text and "Champ172" in text


def test_without_the_ratings_table_the_measurement_is_unchanged():
    ids = _ids(5)
    out = dse.check_lolmath_blocks(
        {cid: dict(GOOD_SPLIT) for cid in ids}, {cid: list(GOOD_ORDER) for cid in ids},
        cooldowns={cid: dict(GOOD_CD) for cid in ids}, roles={cid: ["MAGE"] for cid in ids},
    )
    assert set(out) == {"threshold", "cooldowns", "roles", "damage_distribution",
                        "skill_orders"}


def test_the_override_accepts_and_is_recorded():
    reason = "RM-915 adjudication: lolmath ratings table reset"
    out = _check(_ratings(20), override_reason=reason)
    assert out["override_reason"] == reason
    rec = dse._degenerate_override_record(out)
    assert rec["reason"] == reason
    assert rec["blocks"]["ratings"]["missing_rows"] == 153
    assert set(rec["blocks"]) == {"cooldowns", "roles", "ratings",
                                  "damage_distribution", "skill_orders"}


# --- what "degenerate" means ---------------------------------------------------

@pytest.mark.parametrize("row, degenerate", [
    (_rating(10, 0), False),
    (_rating(0, 0), False),
    ({"ratings": {"healing": 2}}, False),
    ({"ratings": {"shielding": 0.5}}, False),
    ({"ratings": {}}, True),
    ({"ratings": None}, True),
    ({}, True),
    (None, True),
    ([], True),
    ({"healing": 4, "shielding": 2}, True),
    ({"ratings": {"healing": -1}}, True),
    ({"ratings": {"healing": float("nan")}}, True),
    ({"ratings": {"healing": float("inf")}}, True),
    # A bool is not a score (True would otherwise read as 1).
    ({"ratings": {"healing": True}}, True),
    ({"ratings": {"healing": "4"}}, True),
    # Only the two score fields count.
    ({"ratings": {"damage": 9}}, True),
])
def test_rating_row_degeneracy(row, degenerate):
    assert dse._rating_row_is_degenerate(row) is degenerate


# --- the committed data passes the gate it now meets ----------------------------

def _snapshots() -> list[Path]:
    return sorted(p for p in (ROOT / "data" / "daemon_slayer").glob("16.*")
                  if (p / "champions.json").is_file())


def test_every_committed_snapshot_passes_the_ratings_gate():
    snaps = _snapshots()
    assert len(snaps) >= 10, [p.name for p in snaps]
    for snap in snaps:
        data = json.loads((snap / "champions.json").read_text(encoding="utf-8"))["data"]
        ratings = {cid: {"ratings": c["lolmath"]["ratings"]} for cid, c in data.items()}
        cooldowns = {cid: c["lolmath"]["cooldowns"] for cid, c in data.items()}
        out = dse.check_lolmath_blocks(
            {cid: dict(GOOD_SPLIT) for cid in data}, {cid: list(GOOD_ORDER) for cid in data},
            cooldowns=cooldowns, ratings=ratings,
        )
        assert out["ratings"]["degenerate_rows"] == 0, snap.name
        assert out["ratings"]["coverage"] == 1.0, snap.name
        assert out["ratings"]["zero_rows"] < len(data) // 2, snap.name


# --- _extract_lolmath wires the table in ----------------------------------------

def _wire(monkeypatch, ratings):
    ids = _ids(173)
    monkeypatch.setattr(dse, "discover_chunks", lambda *a, **k: ("u/scen.js", "u/aram.js"))
    monkeypatch.setattr(dse, "fetch_chunk", lambda url: "")
    monkeypatch.setattr(dse, "extract_from_bodies", lambda bodies, preferred: dse.LolmathExtract(
        cooldowns={cid: dict(GOOD_CD) for cid in ids}, roles={cid: ["FIGHTER"] for cid in ids},
        ratings=ratings, lane_positions=["top"], scenarios={"champ000": [{}]},
        chunk_url="u/scen.js", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    ))
    monkeypatch.setattr(dse, "extract_data_blocks", lambda bodies, preferred: {
        "aram_modifiers": {cid: {"aramDamageDealt": 1.05} for cid in ids},
        "damage_distribution": {cid: dict(GOOD_SPLIT) for cid in ids},
        "skill_orders": {cid: list(GOOD_ORDER) for cid in ids},
        "data_chunk_url": "u/aram.js",
        "data_chunk_bytes": 1,
        "block_sources": {"aram_modifiers": "u/aram.js"},
    })
    return {cid: {"key": str(i + 1), "name": cid, "stats": {}}
            for i, cid in enumerate(ids)}


def _args(allow=None) -> argparse.Namespace:
    return argparse.Namespace(chunk_url=None, data_chunk_url=None,
                              allow_neutral_aram=None, allow_degenerate_lolmath=allow)


def test_extract_lolmath_stops_on_a_short_ratings_table(monkeypatch):
    champions = _wire(monkeypatch, _ratings(20))
    with pytest.raises(dse.DegenerateLolmathBlockError,
                       match="ratings covers 20/173 of the cooldown roster"):
        dse._extract_lolmath(_args(), champions)


def test_extract_lolmath_records_a_clean_ratings_table(monkeypatch):
    champions = _wire(monkeypatch, _ratings(173, zero=42))
    _, _, block_check = dse._extract_lolmath(_args(), champions)
    assert block_check["ratings"]["coverage"] == 1.0
    assert block_check["ratings"]["zero_rows"] == 42
