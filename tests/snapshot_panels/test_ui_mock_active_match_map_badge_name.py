"""
tests/snapshot_panels/test_ui_mock_active_match_map_badge_name.py
The SR MAP canvas's red MIA badge names the whole enemy (session 144, lane
uiux, S144-U-231).

web/js/panels/active_match.js cut every badge name to its first 6
characters (`name.slice(0, 6)`): Nidalee 25 s gone read "Nidale 25s", and a
two-word Live Client display name (the /api/vision-state `enemies` keys,
core/vision_tracker.py) lost its second word - "Tahm K 25s". The gank band
under the map already printed the whole name, so the two marks about the
same enemy disagreed. The badge now draws the whole name and only cuts it,
ending in "...", when the tag would be wider than the canvas.

Drive path: /?ui_mock=1&mode=sr#active-match with an empty /api/state and a
live /api/vision-state stand-in (the S144-U-228 harness, reused through the
S144-U-229 text-floor module's _open, which records every fillText).
"""
from tests.snapshot_panels.test_ui_mock_active_match_map_stall import (
    _Feed,
    _vs_sr,
)
from tests.snapshot_panels.test_ui_mock_active_match_map_text_floor import (
    _BADGE_BOX_JS,
    _open,
)


def _vs_tahm_corner(t_now):
    """The S144-U-228 SR state with Nidalee swapped for Tahm Kench, 25 s
    gone at the top-right corner of the map, where the longer badge must
    still clamp inside the canvas."""
    vs = _vs_sr(t_now)
    del vs["enemies"]["Nidalee"]
    vs["enemies"]["Tahm Kench"] = {
        "champion": "Tahm Kench", "team": "CHAOS", "level": 8,
        "is_dead": False, "respawn_in_s": None, "visible": False,
        "missing_for_s": 25.0, "last_seen_pos": {"x": 14700, "z": 14700},
        "last_seen_t": 562.0, "last_seen_zone": "RIVER",
    }
    return vs


def _badge_tags(page):
    return [t for t, _f in page.evaluate("window.__amCanvasText")
            if t.endswith(" 25s")]


def test_sr_mia_badge_names_the_whole_enemy(mock_server, pw_browser):
    """Nidalee 25 s gone: the badge reads "Nidalee 25s", the same name the
    gank band prints, not "Nidale 25s"."""
    ctx, page, errors = _open(pw_browser, mock_server, _Feed("live", _vs_sr))
    try:
        tags = _badge_tags(page)
        assert tags, page.evaluate("window.__amCanvasText")[:5]
        assert set(tags) == {"Nidalee 25s"}, tags
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_sr_mia_badge_keeps_a_two_word_name_inside_the_canvas(
    mock_server, pw_browser
):
    """Tahm Kench at the top-right corner: both words are drawn, and the
    wider red box is still clamped clear of every canvas edge."""
    ctx, page, errors = _open(pw_browser, mock_server,
                              _Feed("live", _vs_tahm_corner))
    try:
        tags = _badge_tags(page)
        assert tags and set(tags) == {"Tahm Kench 25s"}, tags
        box = page.evaluate(_BADGE_BOX_JS)
        assert box["x0"] >= 1 and box["y0"] >= 1, box
        assert box["x1"] <= box["w"] - 2, box
        assert box["y1"] <= box["h"] - 2, box
        assert box["white"] > 20, box
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
