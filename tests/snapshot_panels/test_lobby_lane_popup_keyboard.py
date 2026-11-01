"""
tests/snapshot_panels/test_lobby_lane_popup_keyboard.py
RM-1320 (s144 uiux) - the Lobby lane-preference popup (#lv-lane-popup,
opened by #lv-lane-primary / #lv-lane-secondary) from the keyboard.

THE DEFECTS. MEASURED in headless Chromium under /?ui_mock=1#lobby at
1920x920 before the fix (the mock self row prefers MIDDLE then BOTTOM):

1. Enter on #lv-lane-primary opened the popup but left focus on the
   trigger. The popup sits BEFORE the triggers in DOM order, so the next Tab
   went to #lv-lane-secondary and skipped all six lane cells; only
   Shift+Tab reached them, and it landed on the last one (FILL).
2. A focused lane cell painted only the UA `auto` ring, measured
   `auto 1px rgb(16, 16, 16)`: near-black on the dark popup surface.
3. Escape did nothing: the popup was the one transient layer not
   registered with the Escape dispatcher (web/js/lib/escape_layers.js), so
   it stayed open with focus inside it.
4. Picking a cell with Enter closed the popup and dropped focus to <body>
   (the focused cell went display:none with the popup).
5. Tab past the last cell moved focus to #lv-lane-primary but left the
   popup open over the page.
6. Neither trigger carried aria-haspopup / aria-expanded, and the cells of
   the role="menu" popup carried no menuitem role.
7. The popup's lane label (#lv-lane-popup-label) followed the pointer only
   (mouseenter / mouseleave), never keyboard focus.

THE FIX follows the Lobby mode menu (RM-1249..1253) and the Home Find Match
picker (RM-1312 / U-97): opening moves focus to the slot's current lane
cell (the first cell when the slot has none) and remembers the opener;
Escape closes through the one dispatcher and returns focus to that trigger;
a pick returns focus to it too (no ring after a pointer pick); focus leaving
the popup closes it without moving focus; the triggers carry
aria-haspopup="menu" and an aria-expanded that tracks the popup; the cells
are role="menuitem"; .lobby-lane-popup-cell:focus-visible draws the 2px
--accent outline (offset 1px) used by .lq-mode-item; focusing a cell names
its lane in the popup label.

/api/lcu-cmd is intercepted at the page, so nothing but the local mock is
reached.
"""
import json

import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_home_history_nav_focus_ring import (
    _RING_JS,
    _assert_rings,
    _themes,
)

_CELLS = "#lv-lane-popup .lobby-lane-popup-cell"
_N_CELLS = 6
_CELL = _CELLS + '[data-pref="{pref}"]'
_NO_TRANSITIONS = "*, *::before, *::after { transition: none !important; }"

_STATE = """
() => {
  const p = document.getElementById('lv-lane-popup');
  const pri = document.getElementById('lv-lane-primary');
  const sec = document.getElementById('lv-lane-secondary');
  const ae = document.activeElement;
  return {
    open: !p.classList.contains('hidden'),
    ariaHidden: p.getAttribute('aria-hidden'),
    priExpanded: pri.getAttribute('aria-expanded'),
    secExpanded: sec.getAttribute('aria-expanded'),
    priHas: pri.getAttribute('aria-haspopup'),
    secHas: sec.getAttribute('aria-haspopup'),
    focus: !ae ? null : (ae.id || (p.contains(ae) && ae.dataset.pref
                                    ? 'cell:' + ae.dataset.pref : ae.tagName)),
    ring: !!ae && ae.matches(':focus-visible'),
    label: document.getElementById('lv-lane-popup-label').textContent.trim(),
    roles: Array.from(p.querySelectorAll('.lobby-lane-popup-cell'))
      .map((c) => c.getAttribute('role')),
  };
}
"""


def _open_lobby(pw_browser, mock_server, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    posts: list[dict] = []

    def _lcu(route):
        try:
            posts.append(json.loads(route.request.post_data or "{}"))
        except ValueError:
            posts.append({})
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/lcu-cmd", _lcu)
    page.goto(mock_server.url + "/?ui_mock=1#lobby",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                           timeout=10_000)
    page.wait_for_selector("#lv-lane-primary", state="visible", timeout=10_000)
    # The mock self row's prefs are applied by the lobby render.
    page.wait_for_function(
        "() => document.getElementById('lv-lane-primary').dataset.pref"
        " === 'MIDDLE'", timeout=10_000)
    return ctx, page, errors, posts


def _keyboard_open(page, trigger="lv-lane-primary"):
    page.focus("#" + trigger)
    page.keyboard.press("Enter")
    st = page.evaluate(_STATE)
    assert st["open"] and st["ariaHidden"] == "false", st
    return st


def _assert_closed(st):
    assert not st["open"], f"lane popup stayed open: {st}"
    assert st["ariaHidden"] == "true", st
    assert st["priExpanded"] == "false" and st["secExpanded"] == "false", st


def test_triggers_and_cells_carry_the_menu_roles(mock_server, pw_browser):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        st = page.evaluate(_STATE)
        assert st["priHas"] == "menu" and st["secHas"] == "menu", st
        assert st["priExpanded"] == "false" and st["secExpanded"] == "false", st
        assert st["roles"] == ["menuitem"] * _N_CELLS, st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_keyboard_open_moves_focus_to_the_current_lane(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        st = _keyboard_open(page)
        assert st["focus"] == "cell:MIDDLE", (
            f"opening the lane popup left focus outside it: {st}")
        assert st["ring"], st
        assert st["priExpanded"] == "true" and st["secExpanded"] == "false", st
        assert st["label"] == "MIDDLE", f"label does not name the focused lane: {st}"
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_secondary_trigger_opens_on_its_own_lane(mock_server, pw_browser):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        st = _keyboard_open(page, "lv-lane-secondary")
        assert st["focus"] == "cell:BOTTOM", st
        assert st["secExpanded"] == "true" and st["priExpanded"] == "false", st
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        _assert_closed(st)
        assert st["focus"] == "lv-lane-secondary", st
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_and_returns_focus_to_the_trigger(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.focus(_CELL.format(pref="TOP"))
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        _assert_closed(st)
        assert st["focus"] == "lv-lane-primary" and st["ring"], st
        assert posts == [], f"Escape fired an LCU command: {posts}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_keyboard_pick_returns_focus_to_the_trigger(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.focus(_CELL.format(pref="JUNGLE"))
        page.keyboard.press("Enter")
        st = page.evaluate(_STATE)
        _assert_closed(st)
        assert st["focus"] == "lv-lane-primary", (
            f"a keyboard pick dropped focus: {st}")
        assert st["ring"], st
        for _ in range(40):
            if posts:
                break
            page.wait_for_timeout(50)
        assert {"cmd": "lobby.set_position_prefs", "primary": "JUNGLE",
                "secondary": "BOTTOM"} in posts, posts
        # The lobby refresh must not throw focus away again.
        page.wait_for_timeout(1500)
        assert page.evaluate(_STATE)["focus"] == "lv-lane-primary"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pointer_open_and_pick_move_focus_without_a_ring(mock_server, pw_browser):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.click("#lv-lane-primary")
        st = page.evaluate(_STATE)
        assert st["open"] and st["focus"] == "cell:MIDDLE", st
        assert st["ring"] is False, "a pointer open painted the keyboard ring"
        page.click(_CELL.format(pref="TOP"))
        st = page.evaluate(_STATE)
        _assert_closed(st)
        assert st["focus"] == "lv-lane-primary" and st["ring"] is False, st
        assert any(p.get("primary") == "TOP" for p in posts), posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_outside_click_closes_without_moving_focus(mock_server, pw_browser):
    """Control: the document click closer still closes the popup, and focus
    is not pulled back to the trigger by it."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        _keyboard_open(page)
        page.mouse.click(5, 900)
        st = page.evaluate(_STATE)
        _assert_closed(st)
        assert st["focus"] != "lv-lane-primary", st
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_tab_past_the_last_cell_closes_the_popup(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        seen = []
        for _ in range(_N_CELLS + 2):
            st = page.evaluate(_STATE)
            seen.append(st["focus"])
            assert st["open"], f"moving between cells closed the popup: {st}"
            if st["focus"] == "cell:FILL":
                break
            page.keyboard.press("Tab")
            assert page.evaluate(_STATE)["label"] != "", seen
        assert seen == ["cell:MIDDLE", "cell:BOTTOM", "cell:UTILITY",
                        "cell:FILL"], seen
        page.keyboard.press("Tab")
        st = page.evaluate(_STATE)
        assert not st["focus"].startswith("cell:"), st
        _assert_closed(st)
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_shift_tab_off_the_first_cell_closes_the_popup(mock_server, pw_browser):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        _keyboard_open(page)
        page.focus(_CELL.format(pref="TOP"))
        assert page.evaluate(_STATE)["open"]
        page.keyboard.press("Shift+Tab")
        st = page.evaluate(_STATE)
        assert not st["focus"].startswith("cell:"), st
        _assert_closed(st)
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_focused_cell_names_its_lane(mock_server, pw_browser):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        _keyboard_open(page)
        labels = {}
        for pref in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY", "FILL"):
            page.focus(_CELL.format(pref=pref))
            labels[pref] = page.evaluate(_STATE)["label"]
        assert labels == {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MIDDLE",
                          "BOTTOM": "BOTTOM", "UTILITY": "SUPPORT",
                          "FILL": "FILL"}, labels
        # The label sat at a hardcoded 13px, below the v2.1 --fs-xs floor.
        # By COMPUTED value: it is the resolved --fs-xs, it stays on one
        # line, and it fits inside the popup (measured on SUPPORT, the
        # longest lane name).
        page.focus(_CELL.format(pref="UTILITY"))
        geo = page.evaluate("""() => {
          const d = document.createElement('span');
          d.style.fontSize = 'var(--fs-xs)';
          document.body.appendChild(d);
          const xs = parseFloat(getComputedStyle(d).fontSize);
          d.remove();
          const l = document.getElementById('lv-lane-popup-label');
          const p = document.getElementById('lv-lane-popup');
          const lr = l.getBoundingClientRect(), pr = p.getBoundingClientRect();
          const lh = parseFloat(getComputedStyle(l).lineHeight)
            || parseFloat(getComputedStyle(l).fontSize) * 1.3;
          return {xs, fs: parseFloat(getComputedStyle(l).fontSize),
                  h: lr.height, lh, sw: l.scrollWidth, cw: l.clientWidth,
                  inside: lr.left >= pr.left && lr.right <= pr.right};
        }""")
        assert geo["xs"] == 16 and geo["fs"] == geo["xs"], geo
        assert geo["h"] < 2 * geo["lh"] and geo["sw"] <= geo["cw"], geo
        assert geo["inside"], geo
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_lane_cells_paint_the_accent_ring_in_every_theme(mock_server, pw_browser):
    themes = _themes()
    assert len(themes) >= 5, f"theme scan anchor: {themes}"
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.add_style_tag(content=_NO_TRANSITIONS)
        _keyboard_open(page)
        accents = set()
        for t in [None] + themes:
            if t:
                page.evaluate(
                    "(t) => document.documentElement"
                    ".setAttribute('data-theme', t)", t)
            page.keyboard.press("Shift")
            rows = page.evaluate(_RING_JS, _CELLS)
            _assert_rings(rows, _N_CELLS, f"Lobby lane cell [{t}]")
            accents.add(rows[0]["accent"])
            assert page.evaluate(_STATE)["open"], f"ring probe closed it [{t}]"
        assert len(accents) >= 3, f"theme flip inert: {accents}"
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
