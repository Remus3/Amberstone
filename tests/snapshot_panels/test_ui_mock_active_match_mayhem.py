"""
tests/snapshot_panels/test_ui_mock_active_match_mayhem.py
The ?ui_mock=1&mode=mayhem Active Match audit page, and the MAP pane's status
line when the vision feed knows no enemies (session 144, lane uiux,
S144-U-220).

1. Mayhem pin. web/data/ui_mock/active_match_aram_mayhem.json had no test that
   rendered it (it only appeared in the capability-gap parametrize, which
   reads the chip and nothing else). ARAM Mayhem is queue 2400 / gameMode
   KIWI, which RC maps to MODE_ARAM, so the page is the ARAM render: the
   header reads ARAM, the per-lane ward strip is hidden, the DS matchup grid
   and the THREATS strip list the five CHAOS champions and never the
   operator's ORDER side.

2. Map status. With /api/vision-state answering {} (what
   dashboard/routes_diag.py _serve_vision_state sends when no vision state
   exists, and what every ui_mock audit page got), the status line read
   "0 VISIBLE - 0 MIA - 0 DEAD": a count of five enemies that the feed did not
   know. It now reads "no enemy vision yet". A poll that fails before any
   answer said "loading vision..." for good; it now reads "vision feed did
   not load". A feed that does know the enemies still paints its counts.

Drive path: /?ui_mock=1&mode=mayhem#active-match with an empty /api/state;
the landed render stamps "phase InProgress" into #am-sub.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_ENEMIES = ["Sett", "Jinx", "Brand", "Malphite", "Lux"]
_ALLIES = ["Ziggs", "Braum", "Kayle", "Nami"]

# A Mayhem /api/vision-state at the fixture's 9:47, shaped like
# core/vision_tracker.py state(): KIWI, no positions, one enemy dead.
_VS_KIWI = {
    "t_now": 0, "game_time": 587.0, "game_mode": "KIWI",
    "active_team": "ORDER",
    "enemies": {
        name: {"champion": name, "team": "CHAOS", "level": 12,
               "is_dead": name == "Lux",
               "respawn_in_s": 18.0 if name == "Lux" else None,
               "visible": name != "Lux", "missing_for_s": None,
               "last_seen_pos": None, "last_seen_t": 587.0,
               "last_seen_zone": "on_bridge"}
        for name in _ENEMIES
    },
    "summary": {"visible_count": 4, "missing_count": 0, "dead_count": 1,
                "total": 5},
}

_STATUS_JS = (
    "() => (document.getElementById('am-map-status') || {}).textContent || ''"
)


def _open(pw_browser, mock_server, vision):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    if vision == "empty":
        body, status = "{}", 200
    elif vision == "failed":
        body, status = "{}", 503
    else:
        body, status = json.dumps(_VS_KIWI), 200
    page.route("**/api/vision-state*", lambda r: r.fulfill(
        status=status, content_type="application/json", body=body))
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=mayhem#active-match",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "(document.getElementById('am-sub')?.textContent || '')"
        ".indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    # The first vision poll fires on the map build; wait until it has
    # replaced the placeholder.
    page.wait_for_function(
        f"({_STATUS_JS})() !== '' && ({_STATUS_JS})() !== 'loading vision...'",
        timeout=10_000,
    )
    return ctx, page, errors


def test_mayhem_ui_mock_renders_the_aram_view_of_the_fixture(
    mock_server, pw_browser
):
    ctx, page, errors = _open(pw_browser, mock_server, "kiwi")
    try:
        assert page.evaluate("document.body.dataset.uiMock") == "1"
        assert page.locator("#view-active-match").is_visible()
        assert page.evaluate(
            "document.getElementById('am-sub').textContent"
        ) == "ARAM - Ziggs - 09:47 - phase InProgress"
        call = page.evaluate(
            "document.getElementById('am-call-body').innerText"
        )
        assert "RIGHT NOW" in call
        assert "Hold W knockback for the Sett all-in" in call
        assert "Mayhem tempo - shove and poke the choke" in call
        # ARAM is one bridge: the per-lane ward strip is hidden.
        assert page.evaluate(
            "() => { const w = document.getElementById('am-ward-heat');"
            " return !w || getComputedStyle(w).display === 'none'"
            " || w.offsetHeight === 0; }"
        ), "the TOP/JG/MID/BOT ward strip paints in a Mayhem game"
        grid = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'#view-active-match .dsm-grid-champ')).map(e => e.textContent)"
        )
        assert grid == _ENEMIES, grid
        threats = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'#view-active-match .threat-strip .threat-portrait'))"
            ".map(e => e.alt)"
        )
        assert threats == _ENEMIES, threats
        for ally in _ALLIES:
            assert ally not in threats and ally not in grid, ally
        assert page.evaluate(
            "document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth"
        ), "horizontal overflow in the Mayhem mock"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [mayhem]: {errors[:3]}"


def test_map_status_paints_the_feed_counts_when_it_knows_the_enemies(
    mock_server, pw_browser
):
    """Positive control for the two cases below: a KIWI feed that knows the
    five enemies paints its clock, counts and one roster row per enemy."""
    ctx, page, errors = _open(pw_browser, mock_server, "kiwi")
    try:
        page.wait_for_function(
            "document.querySelectorAll('#am-map-roster .am-mr-row').length"
            " === 5", timeout=10_000,
        )
        assert page.evaluate(_STATUS_JS) == "9:47 - 4 on bridge - 1 dead"
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


@pytest.mark.parametrize("vision,want", [
    ("empty", "no enemy vision yet"),
    ("failed", "vision feed did not load"),
])
def test_map_status_never_counts_enemies_the_feed_does_not_know(
    vision, want, mock_server, pw_browser
):
    ctx, page, errors = _open(pw_browser, mock_server, vision)
    try:
        # Let a few 500 ms polls land: the line must hold, not flip back.
        page.wait_for_timeout(1200)
        got = page.evaluate(_STATUS_JS)
        assert got == want, (vision, got)
        assert "0 visible" not in got and "MIA" not in got, got
        assert page.evaluate(
            "document.querySelectorAll('#am-map-roster .am-mr-row').length"
        ) == 0
        # The status line is drawn, not collapsed.
        assert page.evaluate(
            "document.getElementById('am-map-status').offsetHeight > 0"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
