"""Tests for core.ds_calibration_agreement (RM-32 / D-01).

Every test drives an INJECTED in-memory sqlite corpus + an injected record
list, never the gitignored data/rewind_history.db, so a clean checkout passes.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import ds_calibration_agreement as dca  # noqa: E402

# --------------------------------------------------------------------------
# Fixture corpus.
# --------------------------------------------------------------------------

_GCT_MS = 1778377395498  # game_creation_ts, ms epoch
_GCT_S = _GCT_MS / 1000.0


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER, "
        "map_id INTEGER, game_creation_ts INTEGER, game_duration_s INTEGER, "
        "tracked_champion_id INTEGER, tracked_team_id INTEGER, "
        "tracked_win INTEGER, has_timeline INTEGER)"
    )
    conn.execute(
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, "
        "team_id INTEGER, champion_id INTEGER, item0 INTEGER, item1 INTEGER, "
        "item2 INTEGER, item3 INTEGER, item4 INTEGER, item5 INTEGER, "
        "item6 INTEGER)"
    )
    conn.execute(
        "CREATE TABLE timeline_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "match_id TEXT, timestamp_ms INTEGER, event_type TEXT, "
        "participant_id INTEGER, item_id INTEGER)"
    )


def _add_match(conn, game_id, *, win=1, champ_id=222, purchases=(),
               final_items=(0, 0, 0, 0, 0, 0, 0), has_timeline=1,
               gct_ms=_GCT_MS):
    mid = f"NA1_{game_id}"
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?)",
        (mid, 420, 11, gct_ms, 1800, champ_id, 100, int(win), has_timeline),
    )
    conn.execute(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (mid, 4, 100, champ_id, *final_items),
    )
    # A second, non-tracked participant with a different champion.
    conn.execute(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (mid, 5, 200, champ_id + 1, 0, 0, 0, 0, 0, 0, 0),
    )
    for ts_ms, item_id, pid in purchases:
        conn.execute(
            "INSERT INTO timeline_events (match_id, timestamp_ms, event_type, "
            "participant_id, item_id) VALUES (?,?,?,?,?)",
            (mid, ts_ms, "ITEM_PURCHASED", pid, item_id),
        )
    return mid


def _rec(game_id, offset_s, *, mode="SR", champion="Vayne", level=9,
         owned=(), picks=()):
    return {
        "ts": _GCT_S + offset_s,
        "champion": champion,
        "mode": mode,
        "level": level,
        "owned_items": [str(i) for i in owned],
        "ds_picks": [
            {"item_id": str(i), "item_name": f"item{i}", "delta_dps": 10.0,
             "gold": 3000, "scorer": s}
            for (i, s) in picks
        ],
        "game_id": str(game_id),
    }


def _conn():
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    return conn


# --------------------------------------------------------------------------
# Record loading.
# --------------------------------------------------------------------------

def test_load_records_skips_malformed_lines(tmp_path):
    p = tmp_path / "cal.jsonl"
    good = json.dumps(_rec("111", 30, picks=[(3036, "dps")]))
    p.write_text(good + "\n{ not json\n\n" + good + "\n", encoding="utf-8")
    assert len(dca.load_records(p)) == 2


def test_load_records_missing_file_is_empty(tmp_path):
    assert dca.load_records(tmp_path / "nope.jsonl") == []


def test_game_key_strips_platform_prefix():
    assert dca._game_key("NA1_5557010443") == "5557010443"
    assert dca._game_key("5557010443") == "5557010443"


# --------------------------------------------------------------------------
# Core agreement math.
# --------------------------------------------------------------------------

def test_followed_pick_is_counted_when_purchased_after_the_tick():
    conn = _conn()
    _add_match(conn, "1", win=1,
               purchases=[(600_000, 3036, 4)])  # 600s in, tracked participant
    conn.commit()
    recs = [_rec("1", 120, picks=[(3036, "dps")])]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    cells = {(c["mode"], c["scorer"]): c for c in out["cells"]}
    assert cells[("SR", "dps")]["n"] == 1
    assert cells[("SR", "dps")]["followed"] == 1


def test_purchase_before_the_recommendation_does_not_count_as_followed():
    conn = _conn()
    _add_match(conn, "1", purchases=[(60_000, 3036, 4)])  # bought at 60s
    conn.commit()
    recs = [_rec("1", 600, picks=[(3036, "dps")])]  # recommended at 600s
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    cell = out["cells"][0]
    assert cell["n"] == 1
    assert cell["followed"] == 0


def test_purchase_by_another_participant_does_not_count():
    conn = _conn()
    _add_match(conn, "1", purchases=[(600_000, 3036, 5)])  # enemy bought it
    conn.commit()
    recs = [_rec("1", 120, picks=[(3036, "dps")])]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    assert out["cells"][0]["followed"] == 0


def test_repeat_ticks_collapse_to_one_observation():
    """~30 ticks per game recommend the same item - that is one observation."""
    conn = _conn()
    _add_match(conn, "1", purchases=[(600_000, 3036, 4)])
    conn.commit()
    recs = [_rec("1", 60 + i * 30, picks=[(3036, "dps")]) for i in range(10)]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    assert out["cells"][0]["n"] == 1
    assert out["ticks"] == 10


def test_already_owned_pick_is_not_an_observation():
    conn = _conn()
    _add_match(conn, "1", purchases=[(600_000, 3036, 4)])
    conn.commit()
    recs = [_rec("1", 120, owned=[3036], picks=[(3036, "dps")])]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    assert out["cells"] == []
    assert out["observations"] == 0


def test_missing_scorer_falls_into_the_unknown_bucket():
    conn = _conn()
    _add_match(conn, "1")
    conn.commit()
    rec = _rec("1", 120)
    rec["ds_picks"] = [{"item_id": "3036", "item_name": "x", "delta_dps": 1.0,
                        "gold": 3000}]
    out = dca.compute_ds_calibration_agreement(conn, [rec], min_n=1)
    assert out["cells"][0]["scorer"] == dca.UNKNOWN_SCORER


def test_mode_and_scorer_split_into_separate_cells():
    conn = _conn()
    _add_match(conn, "1")
    _add_match(conn, "2")
    conn.commit()
    recs = [
        _rec("1", 120, mode="SR", picks=[(3036, "dps")]),
        _rec("2", 120, mode="ARAM", picks=[(3036, "ehp")]),
    ]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    assert {(c["mode"], c["scorer"]) for c in out["cells"]} == {
        ("SR", "dps"), ("ARAM", "ehp")}


# --------------------------------------------------------------------------
# Statistical discipline: Laplace shrink + hard MIN_BUCKET_N gate.
# --------------------------------------------------------------------------

def test_rates_go_through_laplace_shrink():
    from core.smoothed_rates import laplace_rate
    conn = _conn()
    for i in range(4):
        _add_match(conn, str(i), purchases=[(600_000, 3036, 4)])
    conn.commit()
    recs = [_rec(str(i), 120, picks=[(3036, "dps")]) for i in range(4)]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    cell = out["cells"][0]
    assert cell["follow_rate"] == 1.0
    assert cell["follow_rate_smoothed"] == pytest.approx(
        round(laplace_rate(4, 4), 4))
    assert cell["follow_rate_smoothed"] < 1.0


def test_cells_below_min_bucket_n_are_dropped_and_counted():
    conn = _conn()
    _add_match(conn, "1")
    conn.commit()
    recs = [_rec("1", 120, picks=[(3036, "dps")])]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=5)
    assert out["cells"] == []
    assert out["cells_dropped_below_min_n"] == 1


def test_min_bucket_n_default_is_a_hard_positive_gate():
    assert dca.MIN_BUCKET_N >= 5


# --------------------------------------------------------------------------
# Outcome correlation.
# --------------------------------------------------------------------------

def test_outcome_split_reports_followed_and_unfollowed_winrates():
    conn = _conn()
    # Two won games where the pick was followed, two lost where it was not.
    _add_match(conn, "1", win=1, purchases=[(600_000, 3036, 4)])
    _add_match(conn, "2", win=1, purchases=[(600_000, 3036, 4)])
    _add_match(conn, "3", win=0)
    _add_match(conn, "4", win=0)
    conn.commit()
    recs = [_rec(str(i), 120, picks=[(3036, "dps")]) for i in (1, 2, 3, 4)]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    cell = out["cells"][0]
    assert cell["n_followed"] == 2
    assert cell["n_unfollowed"] == 2
    assert cell["winrate_followed"] == 1.0
    assert cell["winrate_unfollowed"] == 0.0
    # Smoothed + shrunk delta must be strictly inside the raw 1.0 gap.
    assert 0.0 < cell["winrate_delta_shrunk"] < 1.0


def test_game_level_follow_rate_split_by_outcome():
    conn = _conn()
    _add_match(conn, "1", win=1, purchases=[(600_000, 3036, 4)])
    _add_match(conn, "2", win=0)
    conn.commit()
    recs = [_rec(str(i), 120, picks=[(3036, "dps")]) for i in (1, 2)]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    g = out["games"]
    assert g["joined"] == 2
    assert g["wins"] == 1
    assert g["mean_follow_rate_win"] == 1.0
    assert g["mean_follow_rate_loss"] == 0.0


# --------------------------------------------------------------------------
# Coverage / join accounting.
# --------------------------------------------------------------------------

def test_records_without_game_id_are_counted_but_unjoinable():
    conn = _conn()
    conn.commit()
    rec = _rec("1", 120, picks=[(3036, "dps")])
    rec["game_id"] = ""
    out = dca.compute_ds_calibration_agreement(conn, [rec], min_n=1)
    assert out["coverage"]["records"] == 1
    assert out["coverage"]["records_without_game_id"] == 1
    assert out["cells"] == []


def test_unjoined_game_ids_are_reported():
    conn = _conn()
    _add_match(conn, "1")
    conn.commit()
    recs = [_rec("1", 120, picks=[(3036, "dps")]),
            _rec("999", 120, picks=[(3036, "dps")])]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    assert out["coverage"]["games_in_log"] == 2
    assert out["coverage"]["games_joined"] == 1
    assert out["coverage"]["games_unjoined"] == 1


def test_inventory_fallback_when_no_timeline_purchases():
    conn = _conn()
    _add_match(conn, "1", purchases=(), final_items=(3036, 0, 0, 0, 0, 0, 0))
    conn.commit()
    recs = [_rec("1", 120, picks=[(3036, "dps")])]
    out = dca.compute_ds_calibration_agreement(conn, recs, min_n=1)
    assert out["cells"][0]["followed"] == 1
    assert out["coverage"]["games_inventory_fallback"] == 1


# --------------------------------------------------------------------------
# Fail-soft.
# --------------------------------------------------------------------------

def test_empty_inputs_return_ok_payload():
    conn = _conn()
    conn.commit()
    out = dca.compute_ds_calibration_agreement(conn, [], min_n=1)
    assert out["ok"] is True
    assert out["cells"] == []
    assert out["observations"] == 0


def test_missing_tables_do_not_raise():
    conn = sqlite3.connect(":memory:")  # no schema at all
    out = dca.compute_ds_calibration_agreement(
        conn, [_rec("1", 120, picks=[(3036, "dps")])], min_n=1)
    assert out["ok"] is True
    assert out["cells"] == []


def test_from_db_missing_file_returns_not_ok(tmp_path):
    out = dca.compute_ds_calibration_agreement_from_db(
        db_path=tmp_path / "nope.db", log_path=tmp_path / "nope.jsonl")
    assert out["ok"] is False
    assert "rewind_history.db" in str(out.get("error"))


# --------------------------------------------------------------------------
# HARD FIREWALL - descriptive only, never an input to DS rank.
# --------------------------------------------------------------------------

def test_module_never_imports_daemon_slayer():
    """RM-32 firewall: this surface is DESCRIPTIVE and must not feed DS rank."""
    src = dca.__file__ or ""
    assert src
    text = Path(src).read_text(encoding="utf-8")
    assert "agents.daemon_slayer" not in text
    assert "from agents" not in text
    assert "import agents" not in text


def test_module_never_writes_to_the_database():
    src = Path(dca.__file__ or "").read_text(encoding="utf-8").upper()
    for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ", "CREATE "):
        assert verb not in src, f"write verb {verb!r} present"


def test_daemon_slayer_never_imports_this_module():
    """Reverse direction of the firewall: DS must not consume the analysis."""
    ds_dir = _ROOT / "agents" / "daemon_slayer"
    # The DS package is TRACKED, so it is in every checkout. Skipping on its
    # absence would silently disarm the firewall guard exactly when the tree is
    # broken.
    assert ds_dir.is_dir(), f"tracked DS package missing at {ds_dir}"
    for py in ds_dir.rglob("*.py"):
        assert "ds_calibration_agreement" not in py.read_text(
            encoding="utf-8", errors="ignore"), f"{py} references the analysis"
