"""Tests for core.minimap_districts - the pure per-mode district substrate
(ZOI plan Wave 1, agent-districts / spec A).

Grep-confirmed API surfaces used here:
- core/zoi_influence.py:177 `_action_quadrant(cx, cy)` (9-label prototype)
- core/zoi_influence.py:206-216 `_QUADRANT_READABLE` (label -> readable)
- flip semantics: core/minimap_geometry.py:104-108 (flip anchors the rect
  left, i.e. a flipped frame mirrors on X; district_of de-flips x -> 1-x)

Synthetic fixtures only (deterministic, no live frame), mirrors the
conventions of tests/test_zoi_influence.py so they run on a clean checkout.
"""
import json
import math

from core.minimap_districts import (
    FALLBACK_DISTRICT_ID,
    GridConfig,
    district_bbox_frac,
    district_of,
    load_grid,
    neighbors,
    reachable,
)
from core.zoi_influence import _QUADRANT_READABLE, _action_quadrant

ALL_MODES = ("sr", "aram", "arena", "brawl", "tft")

# Representative centroid per legacy 9-cell label. Each point is self-checked
# against `_action_quadrant` below so the oracle cannot silently drift.
_LEGACY_REPRESENTATIVES = {
    "top_left": (0.15, 0.15),
    "top_right": (0.88, 0.40),
    "bot_left": (0.12, 0.60),
    "bot_right": (0.85, 0.85),
    "mid": (0.40, 0.40),
    "top_river": (0.65, 0.35),
    "bot_river": (0.35, 0.65),
    "ally_base": (0.08, 0.92),
    "enemy_base": (0.92, 0.08),
}


def _valid_ids(mode):
    grid = load_grid(mode)
    if grid is None or not grid.districts:
        return {FALLBACK_DISTRICT_ID}
    return {d.id for d in grid.districts}


def _district_by_id(mode, district_id):
    grid = load_grid(mode)
    if grid is None:
        return None
    for d in grid.districts:
        if d.id == district_id:
            return d
    return None


# --- a. TOTALITY SWEEP -----------------------------------------------------

def test_totality_sweep_all_modes():
    """20x20 grid x flip in {False, True} x 5 modes = 4000 lookups; every one
    returns a valid district id present in that mode's grid (or the stub
    fallback for grid-less modes)."""
    lookups = 0
    for mode in ALL_MODES:
        valid = _valid_ids(mode)
        for flip in (False, True):
            for i in range(20):
                for j in range(20):
                    x = i / 19.0
                    y = j / 19.0
                    did = district_of(x, y, mode, flip=flip)
                    lookups += 1
                    assert isinstance(did, str) and did, (
                        f"non-string id for {mode!r} at ({x!r}, {y!r}) flip={flip!r}"
                    )
                    assert did in valid, (
                        f"{did!r} not a district of {mode!r} at ({x!r}, {y!r}) flip={flip!r}"
                    )
    assert lookups == 4000


# --- b. SR LEGACY PARITY ORACLE ---------------------------------------------

def test_sr_legacy_parity_oracle():
    """For each of the 9 legacy cells, the representative centroid maps to a
    district whose legacy_label matches the legacy readable label."""
    assert set(_LEGACY_REPRESENTATIVES) == set(_QUADRANT_READABLE)
    for key, (cx, cy) in _LEGACY_REPRESENTATIVES.items():
        # self-check: the representative really is in that legacy cell
        assert _action_quadrant(cx, cy) == key, (
            f"representative ({cx!r}, {cy!r}) no longer maps to legacy {key!r}"
        )
        did = district_of(cx, cy, "sr")
        dist = _district_by_id("sr", did)
        assert dist is not None, f"district {did!r} missing from sr grid"
        assert dist.legacy_label == _QUADRANT_READABLE[key], (
            f"district {did!r} legacy_label {dist.legacy_label!r} != "
            f"{_QUADRANT_READABLE[key]!r} for legacy cell {key!r}"
        )


def test_sr_every_legacy_label_covered():
    """Every one of the 9 readable legacy labels appears on at least one SR
    district."""
    grid = load_grid("sr")
    seen = {d.legacy_label for d in grid.districts if d.legacy_label}
    assert seen == set(_QUADRANT_READABLE.values())


# --- c. FLIP MIRROR ----------------------------------------------------------

def test_flip_mirrors_x():
    for mode in ALL_MODES:
        for i in range(11):
            for j in range(11):
                x = i / 10.0
                y = j / 10.0
                assert district_of(x, y, mode, flip=True) == district_of(
                    1.0 - x, y, mode, flip=False
                ), f"flip mismatch mode={mode!r} at ({x!r}, {y!r})"


# --- d. CONFIG REFERENCE-INTEGRITY -------------------------------------------

def test_config_reference_integrity():
    for mode in ALL_MODES:
        grid = load_grid(mode)
        if grid is None:  # tft: no grid, by design
            assert mode == "tft"
            continue
        assert isinstance(grid, GridConfig)
        ids = {d.id for d in grid.districts}
        assert ids, f"mode {mode!r} loaded an empty grid"
        for d in grid.districts:
            for ref in list(d.adjacent) + list(d.shortcuts):
                assert ref in ids, (
                    f"{d.id!r} references unknown district {ref!r} in {mode!r}"
                )
            assert len(d.poly) >= 3, f"{d.id!r} poly < 3 verts in {mode!r}"
            for (px, py) in d.poly:
                assert 0.0 <= px <= 1.0 and 0.0 <= py <= 1.0, (
                    f"{d.id!r} vert ({px!r}, {py!r}) out of [0,1] in {mode!r}"
                )


# --- e. FAIL-SOFT -------------------------------------------------------------

def test_failsoft_garbage_numeric_inputs():
    for bad_x, bad_y in (
        (float("nan"), 0.5),
        (0.5, float("inf")),
        (float("-inf"), float("nan")),
        (None, None),
        ("abc", 0.5),
        (0.5, [1, 2]),
        ({}, ()),
    ):
        for mode in ALL_MODES:
            did = district_of(bad_x, bad_y, mode)
            assert isinstance(did, str) and did
            assert did in _valid_ids(mode) or did == FALLBACK_DISTRICT_ID


def test_failsoft_unknown_mode():
    assert load_grid("nonsense_mode") is None
    assert load_grid(None) is None
    assert load_grid(123) is None
    assert district_of(0.5, 0.5, "nonsense_mode") == FALLBACK_DISTRICT_ID
    assert district_of(0.5, 0.5, None) == FALLBACK_DISTRICT_ID
    assert neighbors("mid_lane", "nonsense_mode") == []
    assert reachable("mid_lane", "nonsense_mode") == set()
    assert district_bbox_frac("mid_lane", "nonsense_mode") is None


def test_failsoft_corrupt_json_falls_back_embedded(tmp_path):
    (tmp_path / "sr.json").write_text("{ this is not json", encoding="utf-8")
    grid = load_grid("sr", config_dir=tmp_path)
    assert isinstance(grid, GridConfig)
    assert len(grid.districts) >= 1  # embedded minimal fallback


def test_failsoft_missing_file_falls_back_embedded(tmp_path):
    grid = load_grid("aram", config_dir=tmp_path)  # empty dir, no aram.json
    assert isinstance(grid, GridConfig)
    assert len(grid.districts) >= 1


def test_failsoft_wrong_shape_json_falls_back_embedded(tmp_path):
    (tmp_path / "brawl.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    grid = load_grid("brawl", config_dir=tmp_path)
    assert isinstance(grid, GridConfig)
    assert len(grid.districts) >= 1


# --- graph helpers ------------------------------------------------------------

def test_neighbors_includes_shortcuts():
    nbrs = neighbors("mid_lane", "sr")
    assert "top_river" in nbrs and "bot_river" in nbrs  # adjacency
    assert "baron_pit" in nbrs and "dragon_pit" in nbrs  # river-gank shortcuts
    assert neighbors("no_such_district", "sr") == []


def test_reachable_hops():
    r0 = reachable("blue_base", "sr", hops=0)
    assert r0 == {"blue_base"}
    r1 = reachable("blue_base", "sr", hops=1)
    assert "bot_river" in r1 and "blue_base" in r1
    r2 = reachable("blue_base", "sr", hops=2)
    assert r1 <= r2
    assert "dragon_pit" in r2  # blue_base -> bot_river -> dragon_pit
    # generous hop count converges on the whole connected grid
    r_all = reachable("blue_base", "sr", hops=99)
    assert r_all == _valid_ids("sr")
    assert reachable("no_such_district", "sr", hops=3) == set()


def test_district_bbox_frac():
    bbox = district_bbox_frac("blue_base", "sr")
    assert bbox is not None
    x0, y0, x1, y1 = bbox
    assert math.isclose(x0, 0.0) and math.isclose(x1, 0.18)
    assert math.isclose(y0, 0.82) and math.isclose(y1, 1.0)
    assert district_bbox_frac("no_such_district", "sr") is None


# --- per-mode shape ------------------------------------------------------------

def test_sr_pits_and_rivers():
    assert district_of(0.70, 0.30, "sr") == "baron_pit"
    assert district_of(0.30, 0.70, "sr") == "dragon_pit"
    assert district_of(0.65, 0.35, "sr") == "top_river"
    assert district_of(0.35, 0.65, "sr") == "bot_river"


def test_aram_single_lane_invariant():
    grid = load_grid("aram")
    assert grid is not None
    for d in grid.districts:
        assert d.shortcuts == (), (
            f"aram {d.id!r} must not declare shortcuts (single-lane invariant)"
        )
    assert district_of(0.5, 0.5, "aram") == "aram_bridge"
    assert district_of(0.05, 0.95, "aram") == "blue_base"
    assert district_of(0.95, 0.05, "aram") == "red_base"


def test_arena_grid_hint_cells():
    grid = load_grid("arena")
    assert grid is not None
    assert grid.grid_hint == {"cols": 3, "rows": 3}
    ids = {d.id for d in grid.districts}
    assert len(ids) == 9
    assert district_of(0.05, 0.05, "arena") == "cell_0_0"
    assert district_of(0.95, 0.95, "arena") == "cell_2_2"
    assert district_of(0.5, 0.5, "arena") == "cell_1_1"
    center = _district_by_id("arena", "cell_1_1")
    assert center.label == "center"


def test_tft_none_grid_still_total():
    assert load_grid("tft") is None
    assert district_of(0.5, 0.5, "tft") == FALLBACK_DISTRICT_ID
    assert district_of(float("nan"), None, "tft") == FALLBACK_DISTRICT_ID
