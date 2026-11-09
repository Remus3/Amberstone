"""Hardening regressions for core.minimap_presence (lane 8 true-audit, S144-T-581).

Each test pins one measured weakness of the per-district presence tracker
(``MinimapPresenceTracker`` / ``current_presence``) or its serving copy
(``presence_payload``), the /api/state ``zoi["districts"]`` splice in
dashboard/_state_builder.py. Grep-confirmed surfaces:
- ``MinimapPresenceTracker.update(dots, mode, game_time_s, flip=False)``
- ``presence_payload(rows)`` and the ``_reset_tracker`` test seam
- ``district_of`` CLAMPS out-of-box coordinates into an edge district
  (core/minimap_districts.py ``district_of``), so the tracker must refuse
  them itself
- dashboard/server.py serves /api/state from a ``ThreadingHTTPServer``, so
  the module singleton can be updated from two request threads at once

Synthetic fixtures only - deterministic, no live frame.
"""
import json
import threading

from core import minimap_presence as mp
from core.minimap_districts import load_grid
from core.minimap_presence import MinimapPresenceTracker, presence_payload


def _dot(team, x, y):
    return {"team": team, "x_frac": x, "y_frac": y, "px": 30, "confidence": 0.5}


def _by_id(rows):
    return {r["district"]: r for r in rows}


def _sr_ids():
    return [d.id for d in load_grid("sr").districts]


def _total(rows, side):
    return sum(r[side] for r in rows)


# --- F1: an overflowing integer game time voids the whole tick ----------------

def test_overflowing_int_time_keeps_full_label_set():
    tr = MinimapPresenceTracker()
    rows = tr.update([_dot("blue", 0.30, 0.70)], "sr", 10**400)
    # contract: a non-finite / unusable clock emits a live snapshot, never []
    assert [r["district"] for r in rows] == _sr_ids()
    assert _by_id(rows)["dragon_pit"]["ally"] == 1


# --- F2: a bool game time is read as 1.0 and wipes the live match -------------

def test_bool_time_is_not_a_clock_and_never_wipes():
    tr = MinimapPresenceTracker()
    tr.update([_dot("blue", 0.30, 0.70)], "sr", 100.0)
    tr.update([], "sr", True)  # True would read as t=1.0 = a 99 s regression
    r = _by_id(tr.update([], "sr", 104.0))["dragon_pit"]
    assert r["last_seen_t"]["ally"] == 100.0
    assert r["ally_missing_since_s"] == 4.0


# --- F3: a NaN clock on a MODE CHANGE shows the previous match's sightings ----

def test_nan_time_mode_change_does_not_leak_previous_match():
    tr = MinimapPresenceTracker()
    tr.update([_dot("blue", 0.08, 0.92)], "sr", 100.0)  # blue_base sighting
    rows = tr.update([], "aram", float("nan"))
    aram_ids = [d.id for d in load_grid("aram").districts]
    assert [r["district"] for r in rows] == aram_ids
    for r in rows:
        assert r["last_seen_t"] == {"ally": None, "enemy": None}, r
    # and the SR state is gone for good, not just hidden for one tick
    r = _by_id(tr.update([], "aram", 101.0))["blue_base"]
    assert r["last_seen_t"] == {"ally": None, "enemy": None}


# --- F4: off-map and bool coordinates are counted as presence -----------------

def test_out_of_box_and_bool_coordinates_are_skipped():
    tr = MinimapPresenceTracker()
    rows = tr.update(
        [
            _dot("blue", 5.0, -3.0),      # far outside the minimap crop
            _dot("blue", -0.01, 0.5),
            _dot("red", 0.5, 1.5),
            _dot("red", True, 0.5),       # bool is not a coordinate
            _dot("blue", 0.5, False),
        ],
        "sr",
        10.0,
    )
    assert _total(rows, "ally") == 0
    assert _total(rows, "enemy") == 0
    # the inclusive box edges are still real coordinates
    rows = tr.update([_dot("blue", 0.0, 1.0), _dot("red", 1.0, 0.0)], "sr", 11.0)
    assert _total(rows, "ally") == 1
    assert _total(rows, "enemy") == 1


# --- F5: flip="false" mirrors the map ----------------------------------------

def test_string_false_flip_does_not_mirror():
    tr = MinimapPresenceTracker()
    rows = _by_id(tr.update([_dot("blue", 0.92, 0.92)], "sr", 10.0, flip="false"))
    assert rows["blue_base"]["ally"] == 0
    for junk in ("0", "no", "", None, 0, [], "off"):
        rows = _by_id(tr.update([_dot("blue", 0.92, 0.92)], "sr", 11.0, flip=junk))
        assert rows["blue_base"]["ally"] == 0, junk
    for real in (True, 1, "true", "TRUE", " yes ", "on", "1"):
        rows = _by_id(tr.update([_dot("blue", 0.92, 0.92)], "sr", 12.0, flip=real))
        assert rows["blue_base"]["ally"] == 1, real


# --- F6: one overflowing row voids the whole payload --------------------------

def test_payload_one_bad_row_drops_alone():
    payload = presence_payload(
        [
            {"district": "a", "ally": 1, "ally_missing_since_s": 10**400},
            {"district": "b", "ally": 2},
        ]
    )
    assert [r["district"] for r in payload] == ["a", "b"]
    assert payload[0]["ally_missing_since_s"] is None
    assert payload[1]["ally"] == 2
    json.dumps(payload, allow_nan=False)

    class RaisingRow(dict):
        def get(self, *a, **kw):
            raise RuntimeError("boom")

    payload = presence_payload([RaisingRow(district="a"), {"district": "b", "ally": 2}])
    assert [r["district"] for r in payload] == ["b"]


def test_payload_rejects_bool_negative_and_absurd_values():
    payload = presence_payload(
        [
            {
                "district": "a",
                "ally": True,
                "enemy": 1e300,
                "ally_missing_since_s": True,
                "enemy_missing_since_s": -4.0,
                "last_seen_t": {"ally": False, "enemy": 12.345},
            }
        ]
    )
    row = payload[0]
    assert row["ally"] == 0
    assert row["enemy"] == mp._MAX_DOTS
    assert row["ally_missing_since_s"] is None
    assert row["enemy_missing_since_s"] is None
    assert row["last_seen_t"] == {"ally": None, "enemy": 12.35}
    assert len(json.dumps(payload)) < 400
    huge = presence_payload([{"district": "a", "ally": 10**400, "enemy": -(10**400)}])
    assert (huge[0]["ally"], huge[0]["enemy"]) == (mp._MAX_DOTS, 0)


def test_payload_district_must_be_a_string_id():
    class Evil(str):
        def __str__(self):
            raise RuntimeError("boom")

    payload = presence_payload(
        [
            {"district": ["x"], "ally": 1},
            {"district": 5, "ally": 1},
            {"district": None, "ally": 1},
            {"district": "", "ally": 1},
            {"district": Evil("mid"), "ally": 1},
            {"district": "top", "ally": 1},
        ]
    )
    assert [r["district"] for r in payload] == ["mid", "top"]
    assert all(type(r["district"]) is str for r in payload)


# --- F7: dot ingest is unbounded ----------------------------------------------

def test_dot_ingest_is_bounded():
    tr = MinimapPresenceTracker()
    rows = tr.update([_dot("blue", 0.30, 0.70)] * 10000, "sr", 10.0)
    assert _total(rows, "ally") == mp._MAX_DOTS


def test_mapping_dot_is_read():
    from types import MappingProxyType

    tr = MinimapPresenceTracker()
    rows = tr.update([MappingProxyType(_dot("blue", 0.30, 0.70))], "sr", 10.0)
    assert _by_id(rows)["dragon_pit"]["ally"] == 1


# --- F8: the singleton is updated from concurrent request threads ------------

def test_update_and_reset_are_serialized(monkeypatch):
    tr = MinimapPresenceTracker()
    entered = threading.Event()
    release = threading.Event()
    real_bucket = mp._bucket

    def slow_bucket(*a, **kw):
        entered.set()
        release.wait(5)
        return real_bucket(*a, **kw)

    monkeypatch.setattr(mp, "_bucket", slow_bucket)
    worker = threading.Thread(
        target=tr.update, args=([_dot("blue", 0.30, 0.70)], "sr", 100.0)
    )
    worker.start()
    assert entered.wait(5)
    resetter = threading.Thread(target=tr.reset)
    resetter.start()
    resetter.join(0.3)
    # reset must wait for the in-flight update, never interleave with it
    assert resetter.is_alive()
    release.set()
    worker.join(5)
    resetter.join(5)
    assert not resetter.is_alive()
    monkeypatch.setattr(mp, "_bucket", real_bucket)
    # the reset ran AFTER the update, so nothing survives it
    r = _by_id(tr.update([], "sr", 101.0))["dragon_pit"]
    assert r["last_seen_t"] == {"ally": None, "enemy": None}
