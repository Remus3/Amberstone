"""
tests/snapshot_panels/test_tft_overlay_active_match.py
The in-game overlay (?overlay=1) half of the TFT Active Match audit path
(session 134, lane uiux, RM-897; re-pinned to the S134 N9 field, RM-941).

test_tft_ui_mock_active_match.py pins the ?ui_mock=1&mode=tft|tft_live page at
the 1920 dashboard width. This file pins what the same audit page paints under
?overlay=1, which must be the field a LIVE TFT overlay shows.

History:
- RM-897 (first headless render, 2026-10-25): the overlay mock painted the
  BUILD widget that a live TFT overlay hides, because body[data-mode] stayed
  unset. main.js now stamps the fixture's mode through setMode() and onHealth
  holds it against the no-game "client" downgrade.
- RM-941 (2026-10-25): S134 N9 (web/js/lib/overlay_tft.js +
  overlay_layout.js) then made a TFT match show ONLY the TFT widget set
  (w-tft-hud / w-tft-board / w-tft-lobby + the launcher), keyed on
  body[data-ovx-game], which renderTftOverlay stamps from /api/state.mode_key.
  The audit page's /api/state is empty, so it stamped "lol" over the tft
  data-mode and the audit painted the League field instead: the 210x713 DS
  fight-model pane w-ovds and the League CALL card w-call, and no TFT widget
  at all - a field no live TFT overlay ever shows (measured on a headless
  render of both fixtures). main.js now feeds renderTftOverlay a state built
  from the TFT fixture (mode_key "tft" + the fixture's coach / liveclient) on
  landing, and on every state tick while the mock is up.

Drive path: /?ui_mock=1&mode=<tft|tft_live>&overlay=1 with an empty
/api/state, at the 1080p design viewport and at 2560x1440 with ovscale=1.333
(the pseudo-screen scale, docs/UI_CAPTURE_RECIPES.md). The live-payload half
of the N9 contract is test_overlay_tft_view.py.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_overlay_tft_view import _VISIBLE_WIDGETS_JS

# The field a live TFT overlay shows with no opponent rows (the lobby widget
# is data-gated), per test_overlay_tft_view.py.
_TFT_FIELD = {"w-launcher", "w-tft-hud", "w-tft-board"}

# League panes the TFT field must not paint.
_LEAGUE_PANES = (
    "#am-pane-ovds",
    "#view-active-match .am-pane-call",
    "#view-active-match .am-pane-build",
)

# League-only text, plus the SR leftovers the real TFT payload carries.
_LOL_ONLY = (
    "DS engine ranks",
    "WARDS",
    "MIA",
    "waiting for live data",
    "FAIR FIGHT",
)

# Vitals cell text per fixture. tft = the no-feed placeholder (empty coach);
# tft_live = the HUD read at round 4-2 (active_match_tft_live.json note). The
# fixture carries no standing / players_alive, so PLACE and ALIVE stay "-".
_VITALS = {
    "tft": {"hp": "-", "place": "-", "alive": "-",
            "stage": "-", "level": "-", "gold": "-"},
    "tft_live": {"hp": "100", "place": "-", "alive": "-",
                 "stage": "4-2", "level": "8", "gold": "57"},
}

# (viewport, extra query) - the 1080p design field and the 1440p pseudo-screen.
_SCALES = {
    "1080p": ({"width": 1920, "height": 1080}, ""),
    "1440p": ({"width": 2560, "height": 1440}, "&ovscale=1.333"),
}

_WAIT_TFT_FIELD = (
    "() => { const h = document.getElementById('ovt-hud');"
    " return !!h && !h.hidden && h.classList.contains('ovx-widget')"
    " && document.body.classList.contains('ovx-ready')"
    " && document.body.dataset.ovxGame === 'tft'; }"
)

_VITALS_JS = """() => Object.fromEntries(Array.from(
  document.querySelectorAll('#ovt-hud .ovt-cell[data-k]')).map(c =>
  [c.dataset.k, c.querySelector('.ovt-val').textContent]))"""


def _open(pw_browser, mock_server, mode: str, scale: str = "1080p",
          health: list | None = None, states: list | None = None):
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
    if states is not None:
        # The empty no-game /api/state, counted: each one reaches
        # renderTftOverlay through the HTTP fallback site in main.js.
        def _state(route):
            states.append(route.request.url)
            route.fulfill(status=200, content_type="application/json",
                          body="{}")
        page.route("**/api/state", _state)
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
    page.wait_for_function(_WAIT_TFT_FIELD, timeout=10_000)
    page.evaluate("() => document.fonts.ready.then(() => true)")
    return ctx, page, errors


def _league_panes_painted(page) -> list[str]:
    return [sel for sel in _LEAGUE_PANES if page.locator(sel).is_visible()]


@pytest.mark.parametrize("mode", ["tft", "tft_live"])
def test_tft_overlay_mock_paints_the_live_tft_field(
    mode, mock_server, pw_browser
):
    """STRUCTURE + ASCII: the audit page paints the TFT widget set a live TFT
    overlay shows, with the fixture's vitals, and none of the League panes."""
    ctx, page, errors = _open(pw_browser, mock_server, mode)
    try:
        assert page.evaluate("document.body.dataset.shell") == "overlay"
        assert page.evaluate("document.body.dataset.view") == "active-match"
        assert page.evaluate("document.body.dataset.mode") == "tft"
        assert page.evaluate("document.body.dataset.ovxGame") == "tft"
        visible = page.evaluate(_VISIBLE_WIDGETS_JS)
        assert set(visible) == _TFT_FIELD, sorted(visible)
        assert _league_panes_painted(page) == []
        assert page.evaluate(_VITALS_JS) == _VITALS[mode]
        assert page.eval_on_selector("#ovt-lobby", "e => e.hidden"), (
            "lobby is data-gated and the fixture has no opponent rows"
        )
        assert page.eval_on_selector(
            "#ovt-hud", "e => getComputedStyle(e).position") == "fixed"
        painted = page.evaluate(
            "() => ['ovt-hud', 'ovt-board'].map(i =>"
            " document.getElementById(i).innerText).join(' ')"
        )
        assert all(ord(c) < 128 for c in painted), painted
        for needle in _LOL_ONLY:
            assert needle not in painted, (
                f"League text {needle!r} on the TFT overlay field ({mode})"
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
def test_tft_overlay_mock_states_share_one_geometry(
    scale, mock_server, pw_browser
):
    """NO-REFLOW: the TFT widgets sit in the same boxes whether the feed is
    absent (tft) or present (tft_live), so the feed landing changes text only."""
    boxes = {}
    for mode in ("tft", "tft_live"):
        ctx, page, errors = _open(pw_browser, mock_server, mode, scale)
        try:
            boxes[mode] = {k: [round(v) for v in r] for k, r in
                           page.evaluate(_VISIBLE_WIDGETS_JS).items()}
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [{mode} {scale}]: {errors[:3]}"
    assert set(boxes["tft"]) == _TFT_FIELD, boxes
    assert all(r[2] > r[0] and r[3] > r[1] for r in boxes["tft"].values())
    assert boxes["tft"] == boxes["tft_live"], json.dumps(boxes)


def test_tft_overlay_round_feed_paints_the_lobby_widget(mock_server, pw_browser):
    """RM-944: ?mode=tft_round (a verbatim recorded row of the S134
    standalone-client shape) is the one fixture with opponent rows, so it is
    the only audit path that shows the data-gated lobby widget and a filled
    board. The served coach advice strings must not reach the field (B4)."""
    ctx, page, errors = _open(pw_browser, mock_server, "tft_round")
    try:
        page.wait_for_function(
            "() => { const l = document.getElementById('ovt-lobby');"
            " return !!l && !l.hidden; }",
            timeout=10_000,
        )
        visible = page.evaluate(_VISIBLE_WIDGETS_JS)
        assert set(visible) == _TFT_FIELD | {"w-tft-lobby"}, sorted(visible)
        assert _league_panes_painted(page) == []
        assert page.evaluate(_VITALS_JS) == {
            "hp": "78", "place": "#5", "alive": "8",
            "stage": "3-5", "level": "7", "gold": "21",
        }
        painted = page.evaluate(
            "() => ['ovt-hud', 'ovt-board', 'ovt-lobby'].map(i =>"
            " document.getElementById(i).innerText).join(' ')"
        )
        assert all(ord(c) < 128 for c in painted), painted
        for unit in ("Yunara", "Rakan", "Fiddlesticks"):
            assert unit in painted, f"board unit {unit!r} missing"
        for needle in _LOL_ONLY + ("roll 50g", "Tanks wide", "Void Staff",
                                   "Rakan2 A1", "pivot to"):
            assert needle not in painted, (
                f"{needle!r} on the TFT overlay field (tft_round)"
            )
        assert page.evaluate(
            "document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth"
        ), "horizontal overflow in the TFT overlay (tft_round)"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [tft_round]: {errors[:3]}"


def test_tft_overlay_mock_field_survives_health_and_state_polls(
    mock_server, pw_browser
):
    """The audit page has no game behind it: the HTTP fallback poll's
    /api/health reports "client" (the RM-897 downgrade, held by onHealth) and
    its /api/state carries no mode_key, which re-stamped data-ovx-game "lol"
    on every tick before RM-941. Wait until both polls have run after the
    fixture landed, then re-assert the TFT field."""
    health: list[str] = []
    states: list[str] = []
    ctx, page, errors = _open(pw_browser, mock_server, "tft_live",
                              health=health, states=states)
    try:
        landed_states = len(states)
        # One /api/health is the version check's; any second one is the
        # fallback poll's, and the fixture had already landed by then.
        for _ in range(80):
            if len(health) >= 2 and len(states) > landed_states:
                break
            page.wait_for_timeout(250)
        assert len(health) >= 2, f"no fallback /api/health poll: {health}"
        assert len(states) > landed_states, f"no later /api/state: {states}"
        # Both handlers run after the response body is parsed; let them settle.
        page.wait_for_timeout(500)
        assert page.evaluate("document.body.dataset.mode") == "tft"
        assert page.evaluate("document.body.dataset.ovxGame") == "tft"
        assert set(page.evaluate(_VISIBLE_WIDGETS_JS)) == _TFT_FIELD
        assert _league_panes_painted(page) == []
        assert page.evaluate(_VITALS_JS) == _VITALS["tft_live"]
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
