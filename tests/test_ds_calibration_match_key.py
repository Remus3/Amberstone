"""D-01b: ARAM / Arena DS-calibration rows must carry a joinable match key.

WHY
    ``data/ds_calibration.jsonl`` carries 5257 ARAM and 710 Arena rows with an
    EMPTY ``game_id``, so 100 percent of them are permanently unjoinable to an
    outcome. The cause is structural, not a forgotten kwarg: the Live Client
    ``/allgamedata`` payload never surfaces a game_id for those modes (see the
    ``core/live_metrics.py`` module note) and ``AramCoach._blank_artifact_data``
    hardcodes ``"game_id": ""``.

WHAT IS PINNED HERE
    1. ``core.ds_calibration.log_ds_run`` accepts a ``match_key`` kwarg and
       writes it into the record ADDITIVELY (``game_id`` is untouched).
    2. ``core.live_metrics.match_key`` is the ONE minting seam - a public
       wrapper over the existing ``_resolve_match_id`` - so no second minting
       implementation exists.
    3. Two ticks of the same game share the key; a game-clock reset larger than
       ``_NEW_GAME_CLOCK_DROP_S`` mints a new one.
    4. A real game_id still wins (SR is unchanged in shape).
    5. All four ``log_ds_run`` call sites actually pass the key.
    6. BACKWARD COMPATIBILITY: legacy rows with no ``match_key`` (and no
       ``game_id``) still parse and still aggregate without raising.

The autouse ``redirect_prod_write_paths_to_tmp`` fixture in ``tests/conftest.py``
redirects ``core.ds_calibration._LOG_PATH`` to a tmp dir, so every write below
is hermetic and the real on-disk log is never touched.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from core import ds_calibration, live_metrics
from core.ds_calibration_agreement import (
    compute_ds_calibration_agreement,
    load_records,
)

_ROOT = Path(__file__).resolve().parent.parent


class _Holder:
    """Stand-in for a coach instance (the per-match session lives on it)."""


def _read_entries() -> list[dict]:
    path = Path(ds_calibration._LOG_PATH)
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# --------------------------------------------------------------------------
# 1 + 2: the producer records the key, minted by the shared seam.
# --------------------------------------------------------------------------

def test_live_metrics_exposes_a_public_match_key_wrapper():
    assert hasattr(live_metrics, "match_key"), (
        "core.live_metrics must expose a PUBLIC match_key() wrapper; the "
        "calibration logger may not duplicate the minting logic")


def test_aram_record_carries_a_non_empty_match_key():
    holder = _Holder()
    state = {"champion": "Ahri", "game_seconds": 300}
    key = live_metrics.match_key(holder, {"champion": "Ahri"}, state, "ARAM")
    assert key, "ARAM must mint a synthetic key when no game_id exists"
    assert key.startswith("sess_ARAM_Ahri_")

    ds_calibration.log_ds_run(
        champion="Ahri", mode="ARAM", level=9, owned_items=[3157],
        ds_picks=[{"item_id": 3089, "delta_dps": 1.0}], match_key=key)

    entries = _read_entries()
    assert len(entries) == 1
    rec = entries[0]
    assert rec["match_key"] == key
    # ADDITIVE: game_id survives untouched for backward compatibility.
    assert rec["game_id"] == ""
    assert rec["champion"] == "Ahri"


def test_arena_record_carries_a_non_empty_match_key():
    holder = _Holder()
    state = {"champion": "Pyke", "game_seconds": 120}
    key = live_metrics.match_key(holder, {"champion": "Pyke"}, state, "ARENA")
    assert key.startswith("sess_ARENA_Pyke_")

    ds_calibration.log_ds_run(
        champion="Pyke", mode="ARENA", level=7, owned_items=[],
        ds_picks=[{"item_id": 6673, "delta_dps": 2.0}], match_key=key)

    assert _read_entries()[0]["match_key"] == key


# --------------------------------------------------------------------------
# 3: stability across ticks + a new key on a clock reset.
# --------------------------------------------------------------------------

def test_two_ticks_of_one_game_share_the_key_and_a_reset_mints_a_new_one():
    holder = _Holder()
    champ = {"champion": "Ahri"}

    k1 = live_metrics.match_key(holder, champ, {"game_seconds": 300}, "ARAM")
    k2 = live_metrics.match_key(holder, champ, {"game_seconds": 330}, "ARAM")
    assert k1 == k2, "two ticks of the same game must share the match key"

    # Clock resets past the drop threshold -> a genuinely new game.
    drop = live_metrics._NEW_GAME_CLOCK_DROP_S
    k3 = live_metrics.match_key(
        holder, champ, {"game_seconds": 330 - drop - 1.0}, "ARAM")
    assert k3 != k1, "a game-clock reset must mint a NEW match key"

    for k, gt in ((k1, 300), (k2, 330), (k3, 0)):
        ds_calibration.log_ds_run(
            champion="Ahri", mode="ARAM", level=1 + int(gt // 100),
            owned_items=[], ds_picks=[{"item_id": 3089}], match_key=k)
    keys = [r["match_key"] for r in _read_entries()]
    assert keys[0] == keys[1] != keys[2]


def test_a_real_game_id_still_wins():
    holder = _Holder()
    key = live_metrics.match_key(
        holder, {"champion": "Jinx"},
        {"game_id": "5557010443", "game_seconds": 600}, "SR")
    assert key == "live_5557010443"

    ds_calibration.log_ds_run(
        champion="Jinx", mode="SR", level=13, owned_items=[],
        ds_picks=[{"item_id": 3031}], game_id="5557010443", match_key=key)
    rec = _read_entries()[0]
    assert rec["game_id"] == "5557010443"
    assert rec["match_key"] == "live_5557010443"


def test_match_key_never_raises_on_a_hostile_holder():
    """Calibration logging is best-effort; the seam must fail soft."""
    class _Slotted:
        __slots__ = ()

    assert live_metrics.match_key(_Slotted(), {}, {}, "ARAM") == ""
    assert live_metrics.match_key(None, None, None, "ARAM") == ""


def test_match_key_falls_back_to_game_id_when_not_supplied():
    ds_calibration.log_ds_run(
        champion="Jinx", mode="SR", level=13, owned_items=[],
        ds_picks=[{"item_id": 3031}], game_id="5557010443")
    assert _read_entries()[0]["match_key"] == "5557010443"


# --------------------------------------------------------------------------
# 5: every call site actually passes the key.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "coaches/aram_coach.py",
    "coaches/arena_coach.py",
    "coaches/brawl_coach.py",
    "coach_integration/_coach.py",
])
def test_every_log_ds_run_call_site_passes_a_match_key(rel):
    src = (_ROOT / rel).read_text(encoding="utf-8")
    assert "log_ds_run" in src, f"{rel} no longer calls log_ds_run"
    assert "match_key=" in src, (
        f"{rel} calls log_ds_run without passing match_key - its rows would "
        "stay unjoinable")
    assert "live_metrics.match_key(" in src, (
        f"{rel} must mint via the shared core.live_metrics seam")


# --------------------------------------------------------------------------
# 6: backward compatibility with the legacy keyless corpus.
# --------------------------------------------------------------------------

def test_legacy_keyless_rows_still_parse_and_aggregate(tmp_path):
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(
        # A pre-D-01b ARAM row: no match_key key at all, empty game_id.
        json.dumps({"ts": 1.0, "champion": "Ahri", "mode": "ARAM", "level": 9,
                    "owned_items": ["3157"], "ds_picks": [], "game_id": ""})
        + "\n"
        # A pre-scorer SR row.
        + json.dumps({"ts": 2.0, "champion": "Jinx", "mode": "SR", "level": 13,
                      "owned_items": [], "ds_picks": [{"item_id": 3031}],
                      "game_id": "5557010443"})
        + "\n"
        # A new-shape row carrying the additive field.
        + json.dumps({"ts": 3.0, "champion": "Ahri", "mode": "ARAM", "level": 9,
                      "owned_items": [], "ds_picks": [], "game_id": "",
                      "match_key": "sess_ARAM_Ahri_1"})
        + "\n",
        encoding="utf-8")

    records = load_records(legacy)
    assert len(records) == 3
    assert records[0].get("match_key") is None  # legacy row untouched
    assert records[2]["match_key"] == "sess_ARAM_Ahri_1"

    conn = sqlite3.connect(":memory:")
    try:
        out = compute_ds_calibration_agreement(conn, records)
    finally:
        conn.close()
    assert out["ok"] is True
    assert out["ticks"] == 3
    # Two keyless rows are still counted as such - the consumer's game_id
    # bucketing is deliberately unchanged by this slice.
    assert out["coverage"]["records_without_game_id"] == 2
