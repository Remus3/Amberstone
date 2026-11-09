"""
tests/snapshot_panels/test_replay_pick_reveals_main.py
At 720 px and under the Replay panes stack (RM-1785): the match list sits
above the main pane, and the view section scrolls them as one page. A pick
loaded the match below the list and left the view where it was, so the
match it loaded was out of sight (s144 lane uiux, S144-U-182; the U-175
FUTURE row "picking a row at 720 and under does not bring the main pane
into view").

Measured before the fix (headless Chromium, the ui_mock replay padded to 12
matches, the third row picked; "view" = the view section's visible box):
  - 640x307 (300% zoom of the 1920x920 baseline): view 99-265, main pane
    from 318 down, so the meta line and the scrubber were both below it;
  - 480x230 (400%): view 99-188, main pane from 280;
  - 320x256: view 99-214, main pane from 245;
  - 320x640: view 99-598, meta row 584-696 (14 px of it showing) and the
    scrubber 714-758, below the view;
  - 640x900: everything showed already (meta 538-589, scrubber 607-651).
The PGR "Review ->" arrival (sessionStorage rc-replay-focus-match) scrolled
only the picked row into view, so the main pane stayed below it too.

Contract pinned here (padded ui_mock replay, stacked layout):
  - after a click, an Enter or Space on a focused row, or a PGR arrival,
    once the match has loaded, the main pane's head (its top edge through
    the bottom of the scrubber #replay-slider) lies inside the view's
    visible box;
    where that head is taller than the view, the main pane's top edge sits
    at the view's top (the meta line leads), at 640x307, 480x230, 320x256
    and 320x640;
  - focus stays on the picked row (a pick never moves focus);
  - where the head already shows (640x900) the view does not move;
  - side by side (722x400 and the 1920x920 baseline) a pick moves neither
    the view nor the main pane's own scroll.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_replay_narrow_reflow import _padded_mock

_ROWS = "#replay-match-list .replay-match-row"
_SHORT = ((640, 307), (480, 230), (320, 256), (320, 640))
_SHORT_IDS = [f"{w}x{h}" for w, h in _SHORT]
_SIDE = ((722, 400), (1920, 920))
_SIDE_IDS = [f"{w}x{h}" for w, h in _SIDE]

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)
_LOADED = (
    "(id) => {"
    " const m = document.getElementById('replay-meta').textContent;"
    " return m.startsWith(id + ' - ') && / - patch /.test(m); }"
)

_READ = """() => {
  const sec = document.getElementById("view-replay");
  const sr = sec.getBoundingClientRect();
  const vTop = Math.max(0, sr.top + sec.clientTop);
  const vBot = Math.min(window.innerHeight,
                        sr.top + sec.clientTop + sec.clientHeight);
  const box = (e) => { const r = e.getBoundingClientRect();
    return {t: r.top, b: r.bottom}; };
  const list = box(sec.querySelector(".replay-list-pane"));
  const mainEl = sec.querySelector(".replay-main-pane");
  const active = document.activeElement;
  return {vTop, vBot, scrollTop: sec.scrollTop,
    mainScroll: mainEl.scrollTop, winY: window.scrollY,
    list, main: box(mainEl),
    meta: box(sec.querySelector(".replay-meta-row")),
    slider: box(document.getElementById("replay-slider")),
    activeId: active && active.dataset ? active.dataset.matchId || "" : "",
    activeIsRow: !!(active && active.classList
                    && active.classList.contains("replay-match-row"))};
}"""


def _open(pw_browser, url, size, focus_id=None):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    if focus_id:
        page.add_init_script(
            "try { sessionStorage.setItem('rc-replay-focus-match', "
            + json.dumps(focus_id) + "); } catch (_) {}")
    body = json.dumps(_padded_mock())
    page.route("**/data/ui_mock/replay.json", lambda route: route.fulfill(
        status=200, content_type="application/json", body=body))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(url + "/?ui_mock=1#replay", wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_selector(_ROWS, timeout=10_000)
    return ctx, page, errors


def _pick(pw_browser, url, size, how="click", nth=2):
    ctx, page, errors = _open(pw_browser, url, size)
    try:
        row = page.locator(_ROWS).nth(nth)
        mid = row.get_attribute("data-match-id")
        # The user brings the row into sight before picking it.
        row.scroll_into_view_if_needed()
        page.evaluate(_SETTLE)
        before = page.evaluate(_READ)
        if how == "click":
            row.click()
        else:
            row.focus()
            page.evaluate(_SETTLE)
            before = page.evaluate(_READ)
            page.keyboard.press(how)
        page.wait_for_function(_LOADED, arg=mid, timeout=10_000)
        page.evaluate(_SETTLE)
        after = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size}: {errors[:3]}"
    return mid, before, after


def _assert_head_shown(where, r):
    assert r["main"]["t"] >= r["list"]["b"] - 1, (
        f"{where}: the panes are not stacked: {r}")
    head = r["slider"]["b"] - r["main"]["t"]
    view = r["vBot"] - r["vTop"]
    if head <= view:
        assert r["main"]["t"] >= r["vTop"] - 1, (
            f"{where}: the main pane top {r['main']['t']:.0f} is above the"
            f" view top {r['vTop']:.0f}")
        assert r["slider"]["b"] <= r["vBot"] + 1, (
            f"{where}: the scrubber bottom {r['slider']['b']:.0f} is below"
            f" the view bottom {r['vBot']:.0f} (meta {r['meta']})")
    else:
        assert abs(r["main"]["t"] - r["vTop"]) <= 1, (
            f"{where}: the head ({head:.0f} px) is taller than the view"
            f" ({view:.0f} px) but the main pane top {r['main']['t']:.0f}"
            f" is not at the view top {r['vTop']:.0f}")


@pytest.mark.parametrize("size", _SHORT, ids=_SHORT_IDS)
def test_a_click_brings_the_loaded_match_into_view(mock_server, pw_browser,
                                                    size):
    mock_server._store["data"] = {}
    mid, before, after = _pick(pw_browser, mock_server.url, size, "click")
    _assert_head_shown(f"click {size}", after)
    assert after["activeIsRow"] and after["activeId"] == mid, (
        f"focus left the picked row at {size}: {after}")


@pytest.mark.parametrize("key", ("Enter", "Space"))
@pytest.mark.parametrize("size", ((640, 307), (320, 640)),
                         ids=["640x307", "320x640"])
def test_a_key_pick_brings_the_loaded_match_into_view(mock_server,
                                                      pw_browser, size, key):
    mock_server._store["data"] = {}
    mid, before, after = _pick(pw_browser, mock_server.url, size, key)
    _assert_head_shown(f"{key} {size}", after)
    assert after["activeIsRow"] and after["activeId"] == mid, (
        f"focus left the picked row at {size}: {after}")


@pytest.mark.parametrize("size", ((640, 307), (320, 256)),
                         ids=["640x307", "320x256"])
def test_a_pgr_arrival_brings_the_loaded_match_into_view(mock_server,
                                                          pw_browser, size):
    mock_server._store["data"] = {}
    mid = "MOCK_PAD_08"
    ctx, page, errors = _open(pw_browser, mock_server.url, size, focus_id=mid)
    try:
        page.wait_for_function(_LOADED, arg=mid, timeout=10_000)
        page.evaluate(_SETTLE)
        after = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size}: {errors[:3]}"
    _assert_head_shown(f"pgr {size}", after)


def test_a_pick_that_already_shows_does_not_move_the_view(mock_server,
                                                          pw_browser):
    mock_server._store["data"] = {}
    _mid, before, after = _pick(pw_browser, mock_server.url, (640, 900))
    _assert_head_shown("click (640, 900)", after)
    assert after["scrollTop"] == before["scrollTop"], (before, after)
    assert after["winY"] == before["winY"], (before, after)


@pytest.mark.parametrize("size", _SIDE, ids=_SIDE_IDS)
def test_side_by_side_a_pick_moves_nothing(mock_server, pw_browser, size):
    mock_server._store["data"] = {}
    _mid, before, after = _pick(pw_browser, mock_server.url, size)
    assert after["main"]["t"] < after["list"]["b"], (
        f"expected side-by-side panes at {size}: {after}")
    assert after["scrollTop"] == before["scrollTop"], (size, before, after)
    assert after["mainScroll"] == before["mainScroll"], (size, before, after)
    assert after["winY"] == before["winY"], (size, before, after)
