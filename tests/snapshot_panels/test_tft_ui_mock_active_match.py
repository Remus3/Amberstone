"""
tests/snapshot_panels/test_tft_ui_mock_active_match.py
The out-of-game ?ui_mock=1 audit path for a TFT Active Match (session 134,
lane uiux, RM-895).

main.js _amMockUrl mapped sr / aram / arena / mayhem / complete only, so a
UI audit of the TFT Active Match needed a live TFT game. Two fixtures now
cover it, both rooted in the session 134 TFT QA recorder capture of a live
Normal TFT game (queue 1090):
  - ?ui_mock=1&mode=tft       web/data/ui_mock/active_match_tft.json - the
                              coach payload RC really served (every TFT field
                              empty, SR leftovers risk / fight_rule riding
                              along, liveclient {}): the "Unavailable" state.
  - ?ui_mock=1&mode=tft_live  web/data/ui_mock/active_match_tft_live.json -
                              the tft_coaching_data.json key set
                              (tft/tft_coach_engine.py output) filled with the
                              HUD values the QA report read at 4-2 (level 8,
                              gold 57, HP 100): the populated state.

The page contract is the S134 T1 no-feed fallback in
web/js/panels/active_match.js (amLiveFallbackModel); test_tft_active_match_view
pins it through /api/state, this file pins that the mock path reaches it and
that both states keep one geometry (no reflow when the feed lands).

Drive path: /?ui_mock=1&mode=<tft|tft_live>#active-match with an empty /api/state
(auto-derive lands on home, the hash wins). The view-change kick runs
_amMockLoad; the landed render stamps "phase InProgress" into #am-sub.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_FALLBACK_HEAD = "#am-call-body [data-am-fallback]"

# League-only pane text, plus the SR leftovers the real TFT payload carries
# (coach.risk MEDIUM, coach.fight_rule FAIR FIGHT ...). None may render.
_LOL_ONLY = (
    "DS engine ranks",
    "WARDS",
    "MIA",
    "waiting for live data",
    "Static mode map",
    "FAIR FIGHT",
)

_EXPECT = {
    "tft": {
        "sub": "TFT - phase InProgress - live data unavailable",
        "status": "Unavailable - no live feed from the TFT client yet.",
        "cells": [
            ["STAGE", "-", True], ["LEVEL", "-", True],
            ["HP", "-", True], ["GOLD", "-", True],
        ],
    },
    "tft_live": {
        "sub": "TFT - stage 4-2 - phase InProgress",
        "status": "Live",
        "cells": [
            ["STAGE", "4-2", False], ["LEVEL", "8", False],
            ["HP", "100", False], ["GOLD", "57", False],
        ],
    },
}


def _open(pw_browser, mock_server, mode: str):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode={mode}#active-match",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "(document.getElementById('am-sub')?.textContent || '')"
        ".indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    return ctx, page, errors


def _text(page, el_id: str) -> str:
    return page.evaluate(
        "(id) => document.getElementById(id).innerText", el_id
    )


def _stat_cells(page) -> list[list]:
    return page.evaluate(
        "() => Array.from(document.querySelectorAll("
        "'#am-call-body .am-tft-stat')).map(c => ["
        "c.querySelector('.am-tft-stat-label').textContent,"
        "c.querySelector('.am-tft-stat-value').textContent,"
        "c.classList.contains('is-empty')])"
    )


def _stat_rects(page) -> list[list]:
    # Measure after the web fonts settle: the first context of a run can read
    # the strip before a font swap moves it, which looks like a reflow.
    return page.evaluate(
        "async () => { await document.fonts.ready;"
        " await new Promise(r => requestAnimationFrame(() => r()));"
        " return Array.from(document.querySelectorAll("
        "'#am-call-body .am-tft-stat')).map(c => {"
        " const r = c.getBoundingClientRect();"
        " return [Math.round(r.x), Math.round(r.y),"
        " Math.round(r.width), Math.round(r.height)]; }); }"
    )


@pytest.mark.parametrize("mode", ["tft", "tft_live"])
def test_tft_ui_mock_renders_the_tft_fallback(mode, mock_server, pw_browser):
    want = _EXPECT[mode]
    ctx, page, errors = _open(pw_browser, mock_server, mode)
    try:
        assert page.evaluate("document.body.dataset.uiMock") == "1"
        assert page.locator("#view-active-match").is_visible()
        assert _text(page, "am-sub") == want["sub"]
        head = page.locator(_FALLBACK_HEAD)
        assert head.get_attribute("data-am-fallback") == "tft"
        assert head.get_attribute("role") == "status"
        head_text = head.inner_text()
        assert "TFT LIVE DATA" in head_text
        assert want["status"] in head_text
        assert _stat_cells(page) == want["cells"]
        assert _text(page, "am-build-body").strip() == (
            "UNITS\nUnits appear after the TFT client writes its first round."
        )
        assert _text(page, "am-map-body").strip() == (
            "LOBBY\nLobby placements and HP appear after the first round."
        )
        view = _text(page, "view-active-match")
        for needle in _LOL_ONLY:
            assert needle not in view, f"League text {needle!r} in TFT mock ({mode})"
        # No horizontal overflow at the 1920-wide baseline.
        assert page.evaluate(
            "document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth"
        ), f"horizontal overflow in TFT mock ({mode})"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


def test_tft_ui_mock_states_share_one_geometry(mock_server, pw_browser):
    """The stat strip keeps its four slots in the same place whether the feed
    is absent or present - the feed landing changes text, never layout."""
    rects = {}
    for mode in ("tft", "tft_live"):
        ctx, page, errors = _open(pw_browser, mock_server, mode)
        try:
            rects[mode] = _stat_rects(page)
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [{mode}]: {errors[:3]}"
    assert len(rects["tft"]) == 4
    assert all(r[2] > 0 and r[3] > 0 for r in rects["tft"]), rects["tft"]
    assert rects["tft"] == rects["tft_live"], json.dumps(rects)
