"""Characterization tests for core.aram_item_interaction (RM-111).

Reads NO real rewind_history.db - every test builds an in-memory sqlite corpus,
so the suite stays clean-checkout / CI safe (the db is gitignored;
reference_clean_checkout_probe). Assertions are on computed quantities and on
the pure bucketing functions, not on data-fragile cross-row comparisons
(Testing Discipline).
"""
import sqlite3

import pytest

from core import aram_item_interaction as aii

# Two real ARAM-legal completed legendaries (present in the shipped catalog).
IE = 3031          # Infinity Edge
RABADON = 3089     # Rabadon's Deathcap
COMPONENT = 1038   # B.F. Sword - a component, must never form a cell

FRAME_STEP_MS = 60_000
N_FRAMES = 25      # 24 minutes of frames - covers every purchase window


def _schema(conn):
    conn.execute(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY, map_id INTEGER, "
        "queue_id INTEGER, patch TEXT, has_timeline INTEGER)"
    )
    conn.execute(
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, "
        "team_id INTEGER, champion_id INTEGER, win INTEGER)"
    )
    conn.execute(
        "CREATE TABLE timeline_frames (match_id TEXT, timestamp_ms INTEGER, "
        "participant_id INTEGER, total_gold INTEGER, xp INTEGER)"
    )
    conn.execute(
        "CREATE TABLE timeline_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "match_id TEXT, timestamp_ms INTEGER, event_type TEXT, "
        "participant_id INTEGER, item_id INTEGER)"
    )


def _add_match(conn, match_id, *, blue_champs, red_champs, blue_win,
               purchases, gold_rate=(300, 300)):
    """Seed one ARAM match.

    ``purchases`` is a list of ``(participant_id, item_id, ts_ms)``.
    ``gold_rate`` is (blue, red) gold per frame per participant, so a team's
    gold swing is deterministic and hand-checkable.
    """
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?,?)",
        (match_id, aii.ARAM_MAP_ID, aii.ARAM_QUEUE_ID, "16.14", 1),
    )
    for i, cid in enumerate(blue_champs):
        conn.execute("INSERT INTO participants VALUES (?,?,?,?,?)",
                     (match_id, i + 1, 100, cid, 1 if blue_win else 0))
    for i, cid in enumerate(red_champs):
        conn.execute("INSERT INTO participants VALUES (?,?,?,?,?)",
                     (match_id, i + 6, 200, cid, 0 if blue_win else 1))
    for f in range(N_FRAMES):
        ts = f * FRAME_STEP_MS
        for pid in range(1, 11):
            rate = gold_rate[0] if pid <= 5 else gold_rate[1]
            conn.execute(
                "INSERT INTO timeline_frames VALUES (?,?,?,?,?)",
                (match_id, ts, pid, 500 + rate * f, 100 * f),
            )
    for pid, item_id, ts_ms in purchases:
        conn.execute(
            "INSERT INTO timeline_events "
            "(match_id, timestamp_ms, event_type, participant_id, item_id) "
            "VALUES (?,?,?,?,?)",
            (match_id, ts_ms, "ITEM_PURCHASED", pid, item_id),
        )


# An all-AD, no-frontline red team and an all-AP red team, used to drive two
# distinct enemy comp shapes for the BLUE purchaser.
AD_TEAM = [22, 51, 222, 202, 67]      # Ashe, Caitlyn, Jinx, Jhin, Vayne
AP_TEAM = [103, 99, 1, 61, 134]       # Ahri, Lux, Annie, Orianna, Syndra
BLUE_TEAM = [86, 54, 81, 412, 33]     # Garen, Malphite, Ezreal, Thresh, Rammus


def _corpus(n_matches, *, red=AD_TEAM, item=IE, ts_ms=600_000, wins=None):
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    for i in range(n_matches):
        blue_win = (i < wins) if wins is not None else (i % 2 == 0)
        _add_match(conn, f"NA1_{i}", blue_champs=BLUE_TEAM, red_champs=red,
                   blue_win=blue_win, purchases=[(1, item, ts_ms)])
    conn.commit()
    return conn


# --------------------------------------------------------------------------
# Pure bucketing - no catalog, no db.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ad,ap,fl,expected", [
    (5, 0, 0, "ad_heavy/fl_none"),
    (4, 1, 2, "ad_heavy/fl_light"),
    (0, 5, 3, "ap_heavy/fl_heavy"),
    (0, 4, 5, "ap_heavy/fl_heavy"),
    (3, 2, 1, "mixed/fl_light"),
    (2, 2, 0, "mixed/fl_none"),
])
def test_shape_from_factors_is_a_coarse_nine_way_bucket(ad, ap, fl, expected):
    out = aii.shape_from_factors(
        {"ad_count": ad, "ap_count": ap, "frontline_count": fl}
    )
    assert out == expected


def test_shape_from_factors_never_raises_on_junk():
    assert aii.shape_from_factors({}) == "mixed/fl_none"


def test_timing_buckets_partition_the_game():
    labels = [aii._timing_bucket(t, aii.DEFAULT_TIMING_BUCKETS)
              for t in (0, 479, 480, 899, 900, 5000)]
    assert labels == ["early", "early", "mid", "mid", "late", "late"]


# --------------------------------------------------------------------------
# MIN_BUCKET_N - the load-bearing gate.
# --------------------------------------------------------------------------

def test_cell_below_min_bucket_n_is_dropped_not_shown():
    out = aii.compute_aram_item_interaction(_corpus(aii.MIN_BUCKET_N - 1))
    assert out["ok"] is True
    assert out["cells"] == []
    assert out["cells_dropped_below_min_n"] == 1


def test_cell_at_min_bucket_n_is_emitted():
    out = aii.compute_aram_item_interaction(_corpus(aii.MIN_BUCKET_N))
    assert out["cells_dropped_below_min_n"] == 0
    assert len(out["cells"]) == 1
    cell = out["cells"][0]
    assert cell["n"] == aii.MIN_BUCKET_N
    assert cell["item_id"] == IE
    assert cell["timing"] == "mid"          # 600s falls in the mid band
    assert cell["shape"].count("/") == 1


def test_min_n_is_caller_overridable():
    out = aii.compute_aram_item_interaction(_corpus(3), min_n=3)
    assert len(out["cells"]) == 1
    assert out["cells"][0]["n"] == 3


# --------------------------------------------------------------------------
# Aggregation math.
# --------------------------------------------------------------------------

def test_winrate_and_laplace_smoothing():
    # 12 blue wins out of 20 observations -> raw 0.6, smoothed pulled toward 0.5.
    out = aii.compute_aram_item_interaction(_corpus(20, wins=12), min_n=5)
    cell = out["cells"][0]
    assert cell["n"] == 20
    assert cell["winrate"] == 0.6
    assert cell["winrate_smoothed"] == pytest.approx(13 / 22, abs=1e-4)
    assert 0.5 < cell["winrate_smoothed"] < cell["winrate"]


def test_wpa_is_observed_minus_expected_and_shrunk_toward_zero():
    out = aii.compute_aram_item_interaction(_corpus(20, wins=20), min_n=5)
    cell = out["cells"][0]
    assert cell["wpa"] == pytest.approx(
        cell["winrate"] - cell["expected_winrate"], abs=1e-4)
    assert abs(cell["wpa_shrunk"]) < abs(cell["wpa"])


def test_gold_swing_is_own_minus_enemy_over_the_window():
    # Blue earns 500/frame, red 300/frame; the 120s window spans 2 frames.
    # swing = 5*(500*2) - 5*(300*2) = 5000 - 3000 = 2000.
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    for i in range(20):
        _add_match(conn, f"NA1_{i}", blue_champs=BLUE_TEAM, red_champs=AD_TEAM,
                   blue_win=True, purchases=[(1, IE, 600_000)],
                   gold_rate=(500, 300))
    conn.commit()
    cell = aii.compute_aram_item_interaction(conn, min_n=5)["cells"][0]
    assert cell["gold_swing"] == pytest.approx(2000.0)
    assert cell["n_gold_swing"] == 20


def test_gold_swing_is_none_when_the_window_runs_past_the_last_frame():
    # Purchase at 23:30 with frames ending at 24:00 - the 120s window is not
    # covered, so pressure must be withheld rather than truncated.
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    for i in range(20):
        _add_match(conn, f"NA1_{i}", blue_champs=BLUE_TEAM, red_champs=AD_TEAM,
                   blue_win=True, purchases=[(1, IE, 1_410_000)])
    conn.commit()
    cell = aii.compute_aram_item_interaction(conn, min_n=5)["cells"][0]
    assert cell["gold_swing"] is None
    assert cell["n_gold_swing"] == 0


# --------------------------------------------------------------------------
# Axis behaviour.
# --------------------------------------------------------------------------

def test_enemy_comp_shape_splits_cells():
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    for i in range(10):
        _add_match(conn, f"AD_{i}", blue_champs=BLUE_TEAM, red_champs=AD_TEAM,
                   blue_win=True, purchases=[(1, IE, 600_000)])
    for i in range(10):
        _add_match(conn, f"AP_{i}", blue_champs=BLUE_TEAM, red_champs=AP_TEAM,
                   blue_win=False, purchases=[(1, IE, 600_000)])
    conn.commit()
    out = aii.compute_aram_item_interaction(conn, min_n=5)
    shapes = {c["shape"] for c in out["cells"]}
    assert len(out["cells"]) == 2, out["cells"]
    assert len(shapes) == 2, shapes
    assert all(c["n"] == 10 for c in out["cells"])


def test_purchase_timing_splits_cells():
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    for i in range(10):
        _add_match(conn, f"NA1_{i}", blue_champs=BLUE_TEAM, red_champs=AD_TEAM,
                   blue_win=True,
                   purchases=[(1, IE, 120_000), (1, RABADON, 600_000)])
    conn.commit()
    out = aii.compute_aram_item_interaction(conn, min_n=5)
    by_timing = {c["timing"]: c for c in out["cells"]}
    assert set(by_timing) == {"early", "mid"}
    assert by_timing["early"]["item_id"] == IE
    assert by_timing["mid"]["item_id"] == RABADON


def test_components_are_never_counted():
    out = aii.compute_aram_item_interaction(_corpus(20, item=COMPONENT), min_n=5)
    assert out["cells"] == []
    assert out["cells_dropped_below_min_n"] == 0


def test_champion_id_filter_is_opt_in():
    conn = _corpus(20)
    # Purchaser is participant 1 -> BLUE_TEAM[0].
    on = aii.compute_aram_item_interaction(conn, min_n=5,
                                           champion_id=BLUE_TEAM[0])
    off = aii.compute_aram_item_interaction(conn, min_n=5,
                                            champion_id=BLUE_TEAM[1])
    assert on["cells"] and on["cells"][0]["n"] == 20
    assert off["cells"] == []
    assert on["champion_id"] == BLUE_TEAM[0]


# --------------------------------------------------------------------------
# Fail-soft + firewall.
# --------------------------------------------------------------------------

def test_non_aram_matches_are_excluded():
    conn = _corpus(20)
    conn.execute("UPDATE matches SET map_id = 11")
    conn.commit()
    assert aii.compute_aram_item_interaction(conn, min_n=5)["cells"] == []


def test_matches_without_timeline_are_excluded():
    conn = _corpus(20)
    conn.execute("UPDATE matches SET has_timeline = 0")
    conn.commit()
    assert aii.compute_aram_item_interaction(conn, min_n=5)["cells"] == []


def test_empty_corpus_returns_ok_payload():
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    conn.commit()
    out = aii.compute_aram_item_interaction(conn)
    assert out["ok"] is True
    assert out["cells"] == []
    assert out["matches"] == 0


def test_missing_db_returns_error_payload(tmp_path):
    out = aii.compute_aram_item_interaction_from_db(tmp_path / "nope.db")
    assert out["ok"] is False
    assert "missing" in out["error"]


def test_module_never_imports_daemon_slayer_rank():
    """RM-111 firewall: this surface is DESCRIPTIVE and must not feed DS rank."""
    src = (aii.__file__ or "")
    assert src
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    assert "agents.daemon_slayer" not in text
    assert "from agents" not in text
