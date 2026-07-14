"""R126 Slice A TDD RED-first: core.vision_region_atlas OCR region-map atlas.

Characterizes the versioned OCR region-map ATLAS - the persistence + loader
companion to R121's icon dhash atlas (that one catalogs icon hashes; this one
catalogs the pixel rects for the HUD / API-gap OCR fields, keyed by field, at a
1920x1080 baseline, and scales them to a target resolution). BUILD-SUBSTRATE
only: no coach flip, no live wire, ENGINE-IMPACT NONE.

Non-fragile per CLAUDE.md testing discipline: expected values are computed from
the source of truth (data/vision_regions.json + the atlas itself), never from
magic literals. The one deliberate exception is the small CLOSED set of static
API-gap slot names / feeds, which the module DEFINES - so those literals ARE the
source of truth, and pinning them is the point of the test.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import json
from pathlib import Path

import core.vision_region_atlas as vra

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REGIONS_SRC = _REPO_ROOT / "data" / "vision_regions.json"

_API_GAP_SLOTS = ("minimap_fog", "augment_card_1", "augment_card_2", "augment_card_3")
_AUGMENT_CARDS = ("augment_card_1", "augment_card_2", "augment_card_3")


def _source_regions():
    return json.loads(_REGIONS_SRC.read_text(encoding="utf-8"))


def _atlas():
    return vra.build_atlas()


# --------------------------------------------------------------------------- #
# Schema / baseline.
# --------------------------------------------------------------------------- #
def test_schema_version_and_baseline():
    atlas = _atlas()
    assert vra.SCHEMA_VERSION == 1
    assert atlas["schema_version"] == 1
    baseline = atlas["baseline"]
    assert baseline["width"] == 1920
    assert baseline["height"] == 1080


# --------------------------------------------------------------------------- #
# Every calibrated source region survives verbatim.
# --------------------------------------------------------------------------- #
def test_every_source_region_present_and_calibrated():
    atlas = _atlas()
    regions = atlas["regions"]
    src = _source_regions()
    assert src, "source vision_regions.json must be non-empty"
    for name, rect in src.items():
        assert name in regions, name
        r = regions[name]
        assert r["rect"] == rect, name  # EXACT source value, unchanged
        assert r["kind"] == "numeric", name
        assert r["api_gap"] is False, name
        assert r["calibration"] == "calibrated", name
        assert r["feeds"] == name, name


# --------------------------------------------------------------------------- #
# The 4 static API-gap slots (fields Live Client :2999 cannot provide).
# --------------------------------------------------------------------------- #
def test_api_gap_slots_present_with_null_rect():
    regions = _atlas()["regions"]
    for name in _API_GAP_SLOTS:
        assert name in regions, name
        r = regions[name]
        assert r["api_gap"] is True, name
        assert r["rect"] is None, name


def test_minimap_fog_is_dynamic():
    mm = _atlas()["regions"]["minimap_fog"]
    assert mm["calibration"] == "dynamic"
    assert mm["dynamic_source"] == "core.minimap_geometry.compute_minimap_rect"
    assert mm["feeds"] == "enemy_positions"


def test_dynamic_source_resolves_to_real_callable():
    # Ground-truth guard: the dynamic_source string must name a function that
    # actually exists (catches a typo / a future rename of the minimap helper).
    import importlib

    dotted = _atlas()["regions"]["minimap_fog"]["dynamic_source"]
    mod_name, _, attr = dotted.rpartition(".")
    mod = importlib.import_module(mod_name)
    assert callable(getattr(mod, attr))


def test_augment_cards_are_owed():
    regions = _atlas()["regions"]
    for name in _AUGMENT_CARDS:
        r = regions[name]
        assert r["calibration"] == "owed", name
        assert r["feeds"] == "augment_choices", name
        assert r["kind"] == "text", name


# --------------------------------------------------------------------------- #
# Field-set accessors.
# --------------------------------------------------------------------------- #
def test_api_gap_fields():
    atlas = _atlas()
    result = vra.api_gap_fields(atlas)
    assert isinstance(result, frozenset)
    assert result == frozenset({"enemy_positions", "augment_choices"})


def test_owed_fields():
    atlas = _atlas()
    result = vra.owed_fields(atlas)
    assert isinstance(result, frozenset)
    assert result == frozenset({"augment_choices"})


def test_augment_card_names_are_owed_regions():
    atlas = _atlas()
    for name in _AUGMENT_CARDS:
        r = vra.region(name, atlas)
        assert r is not None, name
        assert r["calibration"] == "owed", name


def test_calibrated_fields_match_source_keys():
    atlas = _atlas()
    src = _source_regions()
    result = vra.calibrated_fields(atlas)
    assert isinstance(result, frozenset)
    assert result == frozenset(src.keys())


def test_region_missing_returns_none():
    assert vra.region("does_not_exist", _atlas()) is None


# --------------------------------------------------------------------------- #
# Resolution scaling.
# --------------------------------------------------------------------------- #
def test_scale_region_exactly_doubles_at_4k():
    atlas = _atlas()
    src = _source_regions()
    for name, rect in src.items():
        scaled = vra.scale_region(name, 3840, 2160, atlas)
        assert scaled == tuple(v * 2 for v in rect), name
        assert all(isinstance(v, int) for v in scaled), name


def test_scale_region_none_for_null_rect_and_unknown():
    atlas = _atlas()
    assert vra.scale_region("minimap_fog", 3840, 2160, atlas) is None
    assert vra.scale_region("augment_card_1", 3840, 2160, atlas) is None
    assert vra.scale_region("does_not_exist", 3840, 2160, atlas) is None


# --------------------------------------------------------------------------- #
# Persistence: fail-soft load, atomic write, determinism, staleness guard.
# --------------------------------------------------------------------------- #
def test_load_atlas_missing_path_is_empty():
    assert vra.load_atlas("no/such/path/atlas.json") == {}


def test_write_load_roundtrip(tmp_path):
    atlas = _atlas()
    out = tmp_path / "vision_region_atlas.json"
    written = vra.write_atlas(atlas, out)
    assert written is not None
    assert vra.load_atlas(out) == atlas


def test_write_is_deterministic(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    vra.write_atlas(vra.build_atlas(), a)
    vra.write_atlas(vra.build_atlas(), b)
    assert a.read_bytes() == b.read_bytes()


def test_committed_json_matches_build():
    # Staleness / round-trip guard: the committed JSON on disk must equal a fresh
    # build_atlas() (regenerate via the -c one-liner whenever the source moves).
    committed = json.loads(vra.DEFAULT_ATLAS_PATH.read_text(encoding="utf-8"))
    assert committed == vra.build_atlas()


def test_default_path_accessors_read_committed():
    # Exercise the atlas=None branch (loads DEFAULT_ATLAS_PATH from disk).
    assert vra.api_gap_fields() == frozenset({"enemy_positions", "augment_choices"})
    assert vra.owed_fields() == frozenset({"augment_choices"})


def test_module_and_committed_json_are_ascii():
    mod_bytes = Path(vra.__file__).read_bytes()
    assert all(b < 128 for b in mod_bytes), "module source has non-ASCII bytes"
    json_bytes = vra.DEFAULT_ATLAS_PATH.read_bytes()  # must exist post-generation
    assert all(b < 128 for b in json_bytes), "committed JSON has non-ASCII bytes"
