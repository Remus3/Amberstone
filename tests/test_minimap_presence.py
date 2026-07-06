"""Tests for core.minimap_presence (ZOI plan Wave 2, agent-presence / spec B).

Grep-confirmed API surfaces used here (cite file:line):
- dot shape {team, x_frac, y_frac, px, confidence}: core/minimap_blob_detect.py:109-115
- blue = ally / red = enemy convention: core/zoi_influence.py:263
- district_of(x_frac, y_frac, mode, flip=False) TOTAL lookup: core/minimap_districts.py:312
- load_grid(mode, config_dir=None) -> GridConfig|None: core/minimap_districts.py:225
- SR 13-district grid ids: config/minimap_grids/sr.json
- arena grid_hint 3x3 materialized cells: core/minimap_districts.py:155-194

Synthetic fixtures only - deterministic, no live frame, clean-checkout safe.
"""
import json
import math

from core.minimap_districts import district_of, load_grid
from core.minimap_presence import (
    MinimapPresenceTracker,
    _reset_tracker,
    current_presence,
    presence_payload,
)

ROW_KEYS = {
    "district",
    "ally",
    "enemy",
    "ally_missing_since_s",
    "enemy_missing_since_s",
    "last_seen_t",
}


def _dot(team, x, y, px=30, confidence=0.5):
    """One synthetic blob dot in the current_minimap_dots shape."""
    return {"team": team, "x_frac": x, "y_frac": y, "px": px, "confidence": confidence}


def _by_id(rows):
    return {r["district"]: r for r in rows}


def _sr_ids():
    grid = load_grid("sr")
    assert grid is not None
    return [d.id for d in grid.districts]


# --- 1. full-label-set invariant (no reflow on data absence) -----------------

def test_full_label_set_every_tick():
    tr = MinimapPresenceTracker()
    sr_ids = _sr_ids()
    assert len(sr_ids) == 13

    # tick 1: zero dots - EVERY district still emitted, stable key set
    rows = tr.update([], "sr", 10.0)
    assert [r["district"] for r in rows] == sr_ids
    for r in rows:
        assert set(r.keys()) == ROW_KEYS
        assert r["ally"] == 0 and r["enemy"] == 0
        assert r["ally_missing_since_s"] is None  # never seen this match
        assert r["last_seen_t"] == {"ally": None, "enemy": None}

    # tick 2: one dot - STILL the full label set, same keys every row
    rows = tr.update([_dot("blue", 0.08, 0.92)], "sr", 12.0)
    assert [r["district"] for r in rows] == sr_ids
    for r in rows:
        assert set(r.keys()) == ROW_KEYS


# --- 2. bucketing correctness on known centroids -----------------------------

def test_bucketing_known_centroids():
    # self-check the oracle so the fixture cannot silently drift
    assert district_of(0.08, 0.92, "sr") == "blue_base"
    assert district_of(0.92, 0.08, "sr") == "red_base"
    assert district_of(0.30, 0.70, "sr") == "dragon_pit"

    tr = MinimapPresenceTracker()
    rows = _by_id(
        tr.update(
            [
                _dot("blue", 0.08, 0.92),
                _dot("blue", 0.30, 0.70),
                _dot("red", 0.30, 0.70),
                _dot("red", 0.92, 0.08),
            ],
            "sr",
            60.0,
        )
    )
    assert rows["blue_base"]["ally"] == 1
    assert rows["blue_base"]["enemy"] == 0
    assert rows["red_base"]["enemy"] == 1
    assert rows["red_base"]["ally"] == 0
    assert rows["dragon_pit"]["ally"] == 1
    assert rows["dragon_pit"]["enemy"] == 1
    # a district nobody is in stays all-zero
    assert rows["baron_pit"]["ally"] == 0 and rows["baron_pit"]["enemy"] == 0


# --- 3. missing_since accumulation + reset -----------------------------------

def test_missing_since_accumulates_and_resets():
    tr = MinimapPresenceTracker()
    dot = _dot("blue", 0.30, 0.70)  # dragon_pit

    r = _by_id(tr.update([dot], "sr", 100.0))["dragon_pit"]
    assert r["ally"] == 1
    assert r["ally_missing_since_s"] == 0.0
    assert r["last_seen_t"]["ally"] == 100.0

    r = _by_id(tr.update([], "sr", 110.0))["dragon_pit"]
    assert r["ally"] == 0
    assert r["ally_missing_since_s"] == 10.0
    assert r["last_seen_t"]["ally"] == 100.0

    r = _by_id(tr.update([], "sr", 120.0))["dragon_pit"]
    assert r["ally_missing_since_s"] == 20.0

    # presence returning (count 0 -> >0) resets the missing timer
    r = _by_id(tr.update([dot], "sr", 125.0))["dragon_pit"]
    assert r["ally"] == 1
    assert r["ally_missing_since_s"] == 0.0
    assert r["last_seen_t"]["ally"] == 125.0
    # enemy side never seen: stays None throughout
    assert r["enemy_missing_since_s"] is None
    assert r["last_seen_t"]["enemy"] is None


# --- 4. new-game wipe (game_time_s regression) --------------------------------

def test_new_game_wipe_on_time_regression():
    tr = MinimapPresenceTracker()
    tr.update([_dot("blue", 0.30, 0.70)], "sr", 600.0)

    # a fresh match starts near 0 - a big regression must wipe all counters
    r = _by_id(tr.update([], "sr", 3.0))["dragon_pit"]
    assert r["ally"] == 0
    assert r["ally_missing_since_s"] is None
    assert r["last_seen_t"] == {"ally": None, "enemy": None}


def test_small_time_regression_is_tolerated():
    tr = MinimapPresenceTracker()
    tr.update([_dot("blue", 0.30, 0.70)], "sr", 100.0)

    # a couple seconds of jitter is NOT a new game - state survives,
    # missing clamps at 0.0 rather than going negative
    r = _by_id(tr.update([], "sr", 98.0))["dragon_pit"]
    assert r["last_seen_t"]["ally"] == 100.0
    assert r["ally_missing_since_s"] == 0.0


# --- 5. mode-change wipe -------------------------------------------------------

def test_mode_change_wipe():
    tr = MinimapPresenceTracker()
    tr.update([_dot("blue", 0.30, 0.70)], "sr", 100.0)

    aram_grid = load_grid("aram")
    rows = tr.update([], "aram", 110.0)
    assert [r["district"] for r in rows] == [d.id for d in aram_grid.districts]
    for r in rows:
        assert r["last_seen_t"] == {"ally": None, "enemy": None}
        assert r["ally_missing_since_s"] is None

    # switching BACK to sr is also fresh - nothing carried across matches
    r = _by_id(tr.update([], "sr", 120.0))["dragon_pit"]
    assert r["last_seen_t"] == {"ally": None, "enemy": None}


# --- 6. stale-gap wipe ---------------------------------------------------------

def test_stale_gap_wipe():
    tr = MinimapPresenceTracker()
    tr.update([_dot("blue", 0.30, 0.70)], "sr", 100.0)

    # > ~30s of game time with no update = stale - counters must not resume
    r = _by_id(tr.update([], "sr", 140.0))["dragon_pit"]
    assert r["ally_missing_since_s"] is None
    assert r["last_seen_t"] == {"ally": None, "enemy": None}


# --- 7. flip handling ----------------------------------------------------------

def test_flip_mirrors_x():
    # self-check: de-flipped (1 - 0.92, 0.92) lands in blue_base
    assert district_of(0.92, 0.92, "sr", flip=True) == "blue_base"

    tr = MinimapPresenceTracker()
    rows = _by_id(tr.update([_dot("blue", 0.92, 0.92)], "sr", 50.0, flip=True))
    assert rows["blue_base"]["ally"] == 1


# --- 8. fail-soft garbage ------------------------------------------------------

def test_fail_soft_garbage_dots_and_modes():
    tr = MinimapPresenceTracker()
    sr_ids = _sr_ids()

    # None / non-list dots degrade to zero counts, full label set kept
    assert [r["district"] for r in tr.update(None, "sr", 10.0)] == sr_ids
    assert [r["district"] for r in tr.update("garbage", "sr", 11.0)] == sr_ids

    # malformed dot entries are skipped, valid ones still bucket
    rows = _by_id(
        tr.update(
            [
                42,
                None,
                {"team": "green", "x_frac": 0.5, "y_frac": 0.5},
                {"team": "blue"},
                {"team": "blue", "x_frac": "x", "y_frac": 0.5},
                {"team": "blue", "x_frac": float("nan"), "y_frac": 0.5},
                _dot("red", 0.92, 0.08),
            ],
            "sr",
            12.0,
        )
    )
    assert rows["red_base"]["enemy"] == 1
    assert sum(r["ally"] for r in rows.values()) == 0

    # grid-less / unknown modes emit [] (tft has no spatial grid by design)
    assert tr.update([], "tft", 13.0) == []
    assert tr.update([], "definitely_not_a_mode", 14.0) == []
    assert tr.update([], None, 15.0) == []


def test_fail_soft_nan_time_never_mutates_state():
    tr = MinimapPresenceTracker()
    tr.update([_dot("blue", 0.30, 0.70)], "sr", 100.0)

    # NaN / None / garbage times: rows still emitted (full label set,
    # counts live), but stored state is untouched
    for bad_t in (float("nan"), None, "soon", float("inf")):
        rows = tr.update([_dot("red", 0.92, 0.08)], "sr", bad_t)
        assert [r["district"] for r in rows] == _sr_ids()
        assert _by_id(rows)["red_base"]["enemy"] == 1

    # next VALID tick continues from t=100 as if the garbage never happened
    r = _by_id(tr.update([], "sr", 105.0))["dragon_pit"]
    assert r["last_seen_t"]["ally"] == 100.0
    assert r["ally_missing_since_s"] == 5.0
    # the NaN-tick red dot was never committed to last_seen state
    assert _by_id(tr.update([], "sr", 106.0))["red_base"]["last_seen_t"]["enemy"] is None


# --- 9. arena grid_hint cells --------------------------------------------------

def test_arena_cells_full_set_and_center_bucket():
    assert district_of(0.5, 0.5, "arena") == "cell_1_1"

    tr = MinimapPresenceTracker()
    rows = tr.update([_dot("blue", 0.5, 0.5)], "arena", 30.0)
    assert len(rows) == 9  # 3x3 grid_hint materialized cells
    assert _by_id(rows)["cell_1_1"]["ally"] == 1


# --- 10. payload helper + module singleton -------------------------------------

def test_presence_payload_json_safe():
    tr = MinimapPresenceTracker()
    rows = tr.update([_dot("blue", 0.30, 0.70)], "sr", 100.0)
    payload = presence_payload(rows)
    assert [r["district"] for r in payload] == _sr_ids()

    # strictly JSON round-trippable (flat rows, no NaN, stable keys)
    encoded = json.dumps(payload, allow_nan=False)
    assert json.loads(encoded) == payload

    # garbage in -> [] out, malformed rows dropped or sanitized, never raises
    assert presence_payload(None) == []
    assert presence_payload("nope") == []
    sanitized = presence_payload(
        [{"district": "x", "ally": "3", "enemy": None, "last_seen_t": "bad"}, 7]
    )
    assert len(sanitized) == 1
    assert sanitized[0]["ally"] == 3
    assert sanitized[0]["enemy"] == 0
    assert sanitized[0]["last_seen_t"] == {"ally": None, "enemy": None}
    assert not math.isnan(
        presence_payload([{"district": "x", "ally": float("nan")}])[0]["ally"]
    )


def test_module_singleton_current_presence():
    _reset_tracker()
    rows = current_presence([_dot("blue", 0.30, 0.70)], "sr", 100.0)
    assert _by_id(rows)["dragon_pit"]["ally"] == 1

    rows = current_presence([], "sr", 104.0)
    assert _by_id(rows)["dragon_pit"]["ally_missing_since_s"] == 4.0

    _reset_tracker()
    rows = current_presence([], "sr", 108.0)
    assert _by_id(rows)["dragon_pit"]["last_seen_t"] == {"ally": None, "enemy": None}
