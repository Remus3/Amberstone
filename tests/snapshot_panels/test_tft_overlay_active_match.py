"""
tests/snapshot_panels/test_tft_overlay_active_match.py
The in-game overlay (?overlay=1) half of the TFT Active Match audit path
(session 134, lane uiux, RM-897).

test_tft_ui_mock_active_match.py pins the ?ui_mock=1&mode=tft|tft_live page at
the 1920 dashboard width. The overlay renders the same CALL pane inside the
~210px w-call widget (web/css/overlay.css, the S134 T1 TFT block): the stat
strip folds to 2x2 and the status row reserves two lines, so the card keeps
its height when the feed lands. Nothing pinned that contract under ?overlay=1.

Measured on the first headless render (2026-10-25): the ?ui_mock=1&mode=tft
overlay painted the BUILD widget that a live TFT overlay hides, because
body[data-mode] stayed unset - setMode() runs only from the /api/state and
health envelopes, and the mock path carries neither. Every
body[data-mode="tft"] rule (overlay.css BUILD hide, header.css SR-pill
collapse) was therefore unreachable on the audit path. main.js now stamps the
TFT fixture's mode through setMode() when the mock lands.

Drive path: /?ui_mock=1&mode=<tft|tft_live>&overlay=1 with an empty
/api/state, at the 1080p design viewport and at 2560x1440 with ovscale=1.333
(the pseudo-screen scale, docs/UI_CAPTURE_RECIPES.md).
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_CALL = "#view-active-match .am-pane-call"
_STATUS = "#am-call-body > div[data-am-fallback] > span:last-child"

# League-only text, plus the SR leftovers the real TFT payload carries.
_LOL_ONLY = (
    "DS engine ranks",
    "WARDS",
    "MIA",
    "waiting for live data",
    "FAIR FIGHT",
)

_EXPECT = {
    "tft": {
        "status": "Unavailable - no live feed from the TFT client yet.",
        "cells": [
            ["STAGE", "-", True], ["LEVEL", "-", True],
            ["HP", "-", True], ["GOLD", "-", True],
        ],
    },
    "tft_live": {
        "status": "Live",
        "cells": [
            ["STAGE", "4-2", False], ["LEVEL", "8", False],
            ["HP", "100", False], ["GOLD", "57", False],
        ],
    },
}

# (viewport, extra query) - the 1080p design field and the 1440p pseudo-screen.
_SCALES = {
    "1080p": ({"width": 1920, "height": 1080}, ""),
    "1440p": ({"width": 2560, "height": 1440}, "&ovscale=1.333"),
}

_GEOMETRY = """async ([callSel, statusSel]) => {
  await document.fonts.ready;
  await new Promise(r => requestAnimationFrame(() => r()));
  const rect = el => { const r = el.getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y),
            Math.round(r.width), Math.round(r.height)]; };
  return {
    call: rect(document.querySelector(callSel)),
    status: rect(document.querySelector(statusSel)),
    stats: Array.from(document.querySelectorAll(
      '#am-call-body .am-tft-stat')).map(rect),
  };
}"""


def _open(pw_browser, mock_server, mode: str, scale: str = "1080p",
          health: list | None = None):
    viewport, extra = _SCALES[scale]
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport=viewport)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    if health is not None:
        # A no-game box's health.json: mode client, no mode flags. Carrying
        # rc_version makes the footer version check (main.js fetchRcVersion)
        # fetch it once only, so every later /api/health is the HTTP
        # fallback poll's, the one that hands it to onHealth.
        def _health(route):
            health.append(route.request.url)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"rc_version": "test", "mode": "client",
                                 "alive": True, "has_game": False}),
            )
        page.route("**/api/health", _health)
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode={mode}&overlay=1{extra}",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "(document.getElementById('am-sub')?.textContent || '')"
        ".indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    return ctx, page, errors


def _display(page, selector: str) -> str:
    return page.eval_on_selector(selector, "e => getComputedStyle(e).display")


@pytest.mark.parametrize("mode", ["tft", "tft_live"])
def test_tft_overlay_mock_reaches_the_tft_overlay_contract(
    mode, mock_server, pw_browser
):
    want = _EXPECT[mode]
    ctx, page, errors = _open(pw_browser, mock_server, mode)
    try:
        assert page.evaluate("document.body.dataset.shell") == "overlay"
        assert page.evaluate("document.body.dataset.view") == "active-match"
        # The audit path stamps the mode a live TFT game stamps, so the
        # body[data-mode="tft"] overlay rules are reachable here.
        assert page.evaluate("document.body.dataset.mode") == "tft"
        # TFT has no League item build: the BUILD widget is gone.
        assert _display(page, "#view-active-match .am-pane-build") == "none"
        # The CALL widget is in the field and carries the honest TFT state.
        assert page.eval_on_selector(_CALL, "e => e.dataset.ovxId") == "w-call"
        assert page.eval_on_selector(
            _CALL, "e => getComputedStyle(e).position"
        ) == "fixed"
        assert page.locator(_CALL).is_visible()
        head = page.locator("#am-call-body [data-am-fallback]")
        assert head.get_attribute("data-am-fallback") == "tft"
        assert head.get_attribute("role") == "status"
        assert page.locator(_STATUS).inner_text() == want["status"]
        cells = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'#am-call-body .am-tft-stat')).map(c => ["
            "c.querySelector('.am-tft-stat-label').textContent,"
            "c.querySelector('.am-tft-stat-value').textContent,"
            "c.classList.contains('is-empty')])"
        )
        assert cells == want["cells"]
        # 2x2 strip: two grid columns, and no cell clips its text.
        cols = page.eval_on_selector(
            "#am-call-body > div.am-tft-stats",
            "e => getComputedStyle(e).gridTemplateColumns.split(' ').length",
        )
        assert cols == 2
        clipped = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'#am-call-body .am-tft-stat, #am-call-body .am-tft-stat *'))"
            ".filter(e => e.scrollWidth > e.clientWidth + 1)"
            ".map(e => e.className)"
        )
        assert clipped == [], f"clipped stat text ({mode}): {clipped}"
        call_text = page.locator(_CALL).inner_text()
        for needle in _LOL_ONLY:
            assert needle not in call_text, (
                f"League text {needle!r} in the TFT overlay CALL ({mode})"
            )
        assert page.evaluate(
            "document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth"
        ), f"horizontal overflow in the TFT overlay ({mode})"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


@pytest.mark.parametrize("scale", sorted(_SCALES))
def test_tft_overlay_states_share_one_geometry(scale, mock_server, pw_browser):
    """The w-call card, its status row and the four stat slots sit in the same
    place whether the feed is absent or present: the two-line reserve holds
    the wrapped unavailable sentence, so the feed landing changes text only."""
    geo = {}
    for mode in ("tft", "tft_live"):
        ctx, page, errors = _open(pw_browser, mock_server, mode, scale)
        try:
            geo[mode] = page.evaluate(_GEOMETRY, [_CALL, _STATUS])
            if mode == "tft":
                # The wrapped sentence fits inside the reserved rows.
                fits = page.eval_on_selector(
                    _STATUS, "e => e.scrollHeight <= e.clientHeight + 1"
                )
                assert fits, f"status row overflows its reserve ({scale})"
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [{mode} {scale}]: {errors[:3]}"
    assert len(geo["tft"]["stats"]) == 4
    assert all(r[2] > 0 and r[3] > 0 for r in geo["tft"]["stats"]), geo
    assert geo["tft"] == geo["tft_live"], json.dumps(geo)


def test_tft_overlay_mock_mode_survives_the_health_downgrade(
    mock_server, pw_browser
):
    """The audit page has no game behind it, so the HTTP fallback poll's
    /api/health envelope reports "client" a few seconds after load. Without
    the onHealth hold that downgrade undid the fixture's tft stamp and the
    BUILD widget painted again (verifier, measured at ~6 s). Wait until the
    poll has served a health envelope after the fixture, then re-assert."""
    health: list[str] = []
    ctx, page, errors = _open(pw_browser, mock_server, "tft", health=health)
    try:
        assert page.evaluate("document.body.dataset.mode") == "tft"
        # One /api/health is the version check's; any second one is the
        # fallback poll's, and the fixture had already landed by then.
        for _ in range(80):
            if len(health) >= 2:
                break
            page.wait_for_timeout(250)
        assert len(health) >= 2, f"no fallback /api/health poll: {health}"
        # onHealth runs after the response body is parsed; let it settle.
        page.wait_for_timeout(500)
        assert page.evaluate("document.body.dataset.mode") == "tft"
        assert _display(page, "#view-active-match .am-pane-build") == "none"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
