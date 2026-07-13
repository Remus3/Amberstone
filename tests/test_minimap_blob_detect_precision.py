"""Precision regression for core.minimap_blob_detect on the saved SR corpus
frames (Z2 in docs/LIVE_GAME_GATED_SYNC.md).

Root cause pinned by this suite: the raw blob detector counted EVERY saturated
team-colored 8-connected blob as a champion dot, so minions / wards / structures
/ base + merged lane clusters inflated the count to 62-74 dots per SR frame. The
fix raises a champion-icon size floor (detect_team_dots(champ_min_px=...)) and
caps the survivors to the top-N confidence per team (max_per_team), so the live
caller emits at most 10 dots (<=5 per team).

Fixtures are the offline live-grab SR minimap frames under
data/vision_calib_reference/. They are gitignored-but-present on Legion (the
whole point of Z2 is to un-block headless validation without a live game). When
run from a git worktree the gitignored corpus lives only in the primary
checkout, so _refdirs() also looks there. If a frame is genuinely absent the
case SKIPS with a clear message - it never fake-passes.

The crop rect comes from core.minimap_geometry.compute_minimap_rect(1.62, False,
2560, 1440) -> MinimapRect(x=2134, y=1014, w=416, h=416); the frames are native
2560x1440 so the rect is a direct pixel slice.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import os

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

import core.minimap_blob_detect as mbd
from core.minimap_geometry import compute_minimap_rect

_BASE = ("2560x1440_GlobalScale_0.0000_ShowTeamFramesOnLeft_0"
         "_MirroredScoreboard_0_FlipMiniMap_0_MinimapScale_1.6200")
_FRAMES = [_BASE + ".jpg", _BASE + "__enemy_dead.jpg", _BASE + "__self_dead.jpg"]


def _refdirs():
    """Candidate corpus directories. The repo-relative dir first; when this is a
    git worktree (.claude/worktrees/<name>) the gitignored corpus is only in the
    primary checkout, so add that too."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    dirs = [os.path.join(root, "data", "vision_calib_reference")]
    key = os.sep + os.path.join(".claude", "worktrees") + os.sep
    if key in root + os.sep:
        primary = (root + os.sep).split(key)[0]
        dirs.append(os.path.join(primary, "data", "vision_calib_reference"))
    return dirs


def _load_crop(fname):
    """Load an SR corpus frame and slice out the minimap rect, or None if the
    frame is on no candidate path (headless CI without the live-grab corpus)."""
    for d in _refdirs():
        path = os.path.join(d, fname)
        if os.path.isfile(path):
            im = np.asarray(Image.open(path).convert("RGB"))
            rect = compute_minimap_rect(1.62, False, 2560, 1440)
            assert rect is not None and rect.w == 416 and rect.h == 416, rect
            return im[rect.y:rect.y + rect.h, rect.x:rect.x + rect.w]
    return None


def _detect_live(crop):
    """Run the detector exactly as the live caller does: scaled size bounds +
    the champion floor + the per-team cap."""
    minpx, maxpx = mbd._scaled_size_bounds(crop.shape[1])
    return mbd.detect_team_dots(
        crop, min_px=minpx, max_px=maxpx,
        champ_min_px=mbd._champ_floor_px(crop.shape[1]),
        max_per_team=mbd._MAX_PER_TEAM,
    )


@pytest.mark.parametrize("fname", _FRAMES)
def test_sr_frame_dot_count_capped(fname):
    """Each SR corpus frame must emit <=10 dots (<=5 per team) through the live
    detect path - the Z2 acceptance bar (was 62-74 raw)."""
    crop = _load_crop(fname)
    if crop is None:
        pytest.skip(f"corpus frame absent: {fname}")
    dots = _detect_live(crop)
    red = [d for d in dots if d["team"] == "red"]
    blue = [d for d in dots if d["team"] == "blue"]
    assert len(dots) <= 10, f"{fname}: {len(dots)} dots (want <=10): {[d['px'] for d in dots]}"
    assert len(red) <= 5, f"{fname}: {len(red)} red dots (want <=5)"
    assert len(blue) <= 5, f"{fname}: {len(blue)} blue dots (want <=5)"


@pytest.mark.parametrize("fname", _FRAMES)
def test_sr_frame_raw_detector_overcounts(fname):
    """Characterize the pre-fix behavior: the RAW detector (no floor, no cap,
    just the scaled bounds) still over-counts on these frames. This documents
    the root cause and proves the fix (not the fixture) is what caps the count.
    """
    crop = _load_crop(fname)
    if crop is None:
        pytest.skip(f"corpus frame absent: {fname}")
    minpx, maxpx = mbd._scaled_size_bounds(crop.shape[1])
    raw = mbd.detect_team_dots(crop, min_px=minpx, max_px=maxpx)
    assert len(raw) > 10, (
        f"{fname}: raw detector emitted {len(raw)} dots - expected the "
        "pre-fix over-count (>10); fixture may have changed")


def test_champ_floor_scales_and_never_below_baseline():
    """The champion floor scales linearly with crop width (like _scaled_size_
    bounds) and never drops below the 208px baseline for smaller crops."""
    assert mbd._champ_floor_px(208) == mbd._CHAMP_MIN_PX
    assert mbd._champ_floor_px(416) == mbd._CHAMP_MIN_PX * 2
    # crops smaller than the baseline do not shrink the floor below _CHAMP_MIN_PX
    assert mbd._champ_floor_px(60) == mbd._CHAMP_MIN_PX
    # garbage input degrades to the baseline, never raises
    assert mbd._champ_floor_px(None) == mbd._CHAMP_MIN_PX
    # the floor must stay at/under a champion-sized blob so the 208px fallback
    # crop's champion (25px) is never rejected
    assert mbd._CHAMP_MIN_PX <= 25


def test_max_per_team_caps_and_keeps_top_confidence():
    """detect_team_dots(max_per_team=N) keeps the N highest-confidence dots per
    team and drops the rest; default None is uncapped."""
    img = np.zeros((80, 80, 3), dtype=np.uint8)
    # six red blobs of descending height (px), all above the default floor
    spans = [(2, 12), (14, 23), (26, 34), (38, 45), (50, 56), (62, 67)]
    for i, (a, b) in enumerate(spans):
        img[2:2 + (10 - i), a:b] = (200, 40, 40)
    uncapped = mbd.detect_team_dots(img)
    assert len(uncapped) == 6
    capped = mbd.detect_team_dots(img, max_per_team=3)
    assert len(capped) == 3
    # survivors are the top-3 by confidence, still globally conf-sorted
    confs = [d["confidence"] for d in capped]
    assert confs == sorted(confs, reverse=True)
    assert confs == [d["confidence"] for d in uncapped[:3]]


def test_champ_min_px_is_reject_only_conf_unchanged():
    """champ_min_px must NOT change the confidence value of surviving dots - it
    is a reject filter, conf stays keyed to min_px (byte-identical guarantee for
    the identity byte-identical tests)."""
    img = np.zeros((60, 60, 3), dtype=np.uint8)
    img[20:28, 30:38] = (200, 40, 40)  # 64px blob (the identity fixture shape)
    base = mbd.detect_team_dots(img, min_px=5, max_px=220)
    floored = mbd.detect_team_dots(img, min_px=5, max_px=220, champ_min_px=20)
    assert base == floored  # 64px survives floor 20, conf identical (keyed to 5)


def test_default_signature_byte_identical():
    """The no-new-kwargs call path is unchanged: champ_min_px/max_per_team
    default None and do not alter output."""
    img = np.zeros((60, 60, 3), dtype=np.uint8)
    img[10:20, 10:20] = (40, 120, 220)
    a = mbd.detect_team_dots(img)
    b = mbd.detect_team_dots(img, champ_min_px=None, max_per_team=None)
    assert a == b
