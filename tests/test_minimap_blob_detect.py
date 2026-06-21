"""Tests for core.minimap_blob_detect - pure-numpy team-color blob detection on
a minimap crop (item 567 slice 2). Synthetic fixtures only (deterministic, no
live frame needed) so they run on a clean checkout / CI."""
import numpy as np
import pytest

from core.minimap_blob_detect import crop_minimap, detect_team_dots

RED = (200, 40, 40)      # vivid enemy red
BLUE = (40, 120, 220)    # vivid ally blue


def _blank(h=60, w=60):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _square(img, r0, r1, c0, c1, color):
    img[r0:r1, c0:c1] = color
    return img


def test_empty_crop_no_dots():
    assert detect_team_dots(_blank()) == []


def test_single_red_blob_centroid_and_team():
    img = _square(_blank(), 20, 30, 36, 46, RED)  # center ~ (row 25, col 41)
    dots = detect_team_dots(img)
    assert len(dots) == 1
    d = dots[0]
    assert d["team"] == "red"
    assert abs(d["x_frac"] - 41 / 60) < 0.05
    assert abs(d["y_frac"] - 25 / 60) < 0.05
    assert d["px"] >= 5


def test_single_blue_blob():
    img = _square(_blank(), 10, 20, 10, 20, BLUE)
    dots = detect_team_dots(img)
    assert len(dots) == 1 and dots[0]["team"] == "blue"


def test_red_and_blue_both_detected():
    img = _blank()
    _square(img, 5, 15, 5, 15, BLUE)
    _square(img, 40, 50, 40, 50, RED)
    dots = detect_team_dots(img)
    teams = sorted(d["team"] for d in dots)
    assert teams == ["blue", "red"], f"expected one of each, got {dots}"


def test_low_saturation_terrain_ignored():
    """A muted blue/red TERRAIN wash (low saturation) must not register as a dot -
    this is the icon-vs-terrain discriminator that the raw-RGB threshold missed."""
    img = _blank()
    img[:, :] = (80, 95, 110)   # bluish but sat ~0.27 < 0.45
    assert detect_team_dots(img) == []


def test_tiny_speckle_rejected():
    img = _blank()
    img[30, 30] = RED           # 1 px, below min_px
    img[31, 31] = RED           # diagonally adjacent -> 2 px component
    assert detect_team_dots(img) == []


def test_huge_wash_bails_to_empty():
    """If a whole crop is vivid (loading screen / garbage), bail rather than emit
    a wall of noise."""
    img = _blank(120, 120)
    img[:, :] = RED
    assert detect_team_dots(img) == []


def test_confidence_sorted_descending():
    img = _blank()
    _square(img, 5, 8, 5, 8, RED)        # small (~9 px)
    _square(img, 30, 45, 30, 45, BLUE)   # large (~225 px -> capped, may exceed max_px)
    _square(img, 30, 40, 50, 58, RED)    # medium
    dots = detect_team_dots(img)
    confs = [d["confidence"] for d in dots]
    assert confs == sorted(confs, reverse=True)
    assert all(0.0 <= c <= 1.0 for c in confs)


def test_crop_minimap_maps_design_rect_by_fraction():
    """minimap_rect is design 1920x1080 px; on a 1280x720 frame it must apply as a
    FRACTION, yielding the bottom-right minimap sub-array."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    # paint the expected minimap region so we can confirm the crop lands on it
    frame[507:715, 1067:1275] = RED
    rect = {"x": 1600, "y": 761, "w": 312, "h": 312}
    sub = crop_minimap(frame, rect)
    assert sub is not None
    assert abs(sub.shape[0] - 208) <= 2 and abs(sub.shape[1] - 208) <= 2
    # the crop should be (mostly) the red region we painted
    assert (sub[..., 0] > 150).mean() > 0.9


def test_crop_minimap_bad_input_none():
    assert crop_minimap(np.zeros((10, 10, 3)), None) is None
    assert crop_minimap("not an array", {"x": 0, "y": 0, "w": 1, "h": 1}) is None


def test_detect_handles_bad_shapes():
    assert detect_team_dots(np.zeros((2, 2))) == []        # not 3-channel
    assert detect_team_dots("nope") == []
