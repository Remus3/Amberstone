"""
tests/snapshot_panels/test_lobby_mode_menu_fits_at_open.py
RM-1429 (s144 uiux) - the Lobby mode menu is whole inside the view at open.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#lobby before the
fix. The mode menu (#lv-mode-menu) is position:absolute under its trigger
(top: calc(100% + 4px)) inside #view-lobby, which scrolls (overflow-y auto)
when the view is shorter than its content. At 1280x720 the view's padding
box ends at y 677 (200 px of scroll) while the menu opened at y 411.3 to
705.4: its bottom 28.4 px were cut off, the SR column's lowest item (Ranked
Flex) among them, until the operator scrolled; nothing scrolled it in. The
overflow is BELOW the view, inside its scroll range, so a scroll could reach
it; the open never made that scroll. 1920x920, 1366x768, 923x1280, 1024x600
and 800x600 already fit at open.

THE FIX (web/js/main.js, the #lv-mode-trigger click handler): after the menu
is shown, the menu is scrolled into view (block / inline nearest), BEFORE the
RM-1422 scroll-away arm, so the open's own scroll is part of the open and
never a scroll away from it. Nearest moves the view only as far as the menu
needs; a menu that already fits moves nothing.

The rect checks clip against #view-lobby's padding box and the window, the
same clip rects escape_layers.js visibleArea uses. /api/lcu-cmd is
intercepted at the page, so nothing but the local mock is reached.
"""
import pytest

from tests.snapshot_panels.test_lobby_popup_closes_on_scroll import _open_lobby

_GEO = """
() => {
  const box = (el) => { const b = el.getBoundingClientRect();
    return {top: b.top, bottom: b.bottom, left: b.left, right: b.right}; };
  const v = document.getElementById('view-lobby');
  const m = document.getElementById('lv-mode-menu');
  const t = document.getElementById('lv-mode-trigger');
  const vr = v.getBoundingClientRect();
  const clip = {top: Math.max(0, vr.top + v.clientTop),
                left: Math.max(0, vr.left + v.clientLeft)};
  clip.bottom = Math.min(innerHeight, vr.top + v.clientTop + v.clientHeight);
  clip.right = Math.min(innerWidth, vr.left + v.clientLeft + v.clientWidth);
  const items = Array.from(m.querySelectorAll('.lq-mode-item'));
  const ae = document.activeElement;
  return {
    open: !m.classList.contains('hidden'),
    aria: m.getAttribute('aria-hidden'),
    expanded: t.getAttribute('aria-expanded'),
    menu: box(m),
    trigger: box(t),
    // The LOWEST item, not the last in DOM order: the 4-column grid puts
    // the SR column's 5th item (Ranked Flex) lowest, below TFT's last.
    last: items.length ? box(items.reduce((a, b) =>
      b.getBoundingClientRect().bottom > a.getBoundingClientRect().bottom ? b : a)) : null,
    nItems: items.length,
    clip,
    scroll: v.scrollTop,
    maxScroll: v.scrollHeight - v.clientHeight,
    focus: !ae ? null : (ae.id || ae.tagName),
  };
}
"""

_SLACK = 0.5


def _inside(r, c):
    return (r["top"] >= c["top"] - _SLACK and r["bottom"] <= c["bottom"] + _SLACK
            and r["left"] >= c["left"] - _SLACK and r["right"] <= c["right"] + _SLACK)


def _open(page, how):
    if how == "pointer":
        page.click("#lv-mode-trigger")
    else:
        page.focus("#lv-mode-trigger")
        page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    st = page.evaluate(_GEO)
    assert st["open"] and st["aria"] == "false" and st["expanded"] == "true", st
    assert st["focus"] == "lv-mode-trigger", st
    assert st["nItems"] >= 10, f"anchor: the menu lost its items: {st}"
    return st


def _assert_fits(st, label):
    assert _inside(st["menu"], st["clip"]), (
        f"{label}: the mode menu is cut off by the view at open: {st}")
    assert _inside(st["last"], st["clip"]), f"{label}: lowest item cut off: {st}"
    # The trigger it hangs from stays in sight too (both fit at every
    # viewport below), so the open never strands the operator's anchor.
    assert _inside(st["trigger"], st["clip"]), (
        f"{label}: the open scrolled the trigger out of sight: {st}")


_VPS = [(1920, 920), (1280, 720), (1366, 768), (923, 1280), (1024, 600), (800, 600)]


@pytest.mark.parametrize("vp", _VPS, ids=lambda v: f"{v[0]}x{v[1]}")
@pytest.mark.parametrize("how", ["pointer", "keyboard"])
def test_the_mode_menu_is_whole_inside_the_view_at_open(
        mock_server, pw_browser, vp, how):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        st = _open(page, how)
        _assert_fits(st, f"{vp} {how}")
        # The open's own scroll is not a scroll away (RM-1422 arm order).
        page.wait_for_timeout(300)
        assert page.evaluate(_GEO)["open"], "the open's own scroll closed it"
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", _VPS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_opening_from_a_view_scrolled_to_its_end_fits(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        page.evaluate("() => { const v = document.getElementById('view-lobby');"
                      " v.scrollTop = v.scrollHeight; }")
        page.wait_for_timeout(200)
        st = _open(page, "keyboard")
        _assert_fits(st, f"{vp} scrolled")
        page.wait_for_timeout(300)
        assert page.evaluate(_GEO)["open"], "the open's own scroll closed it"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_menu_that_already_fits_moves_nothing(mock_server, pw_browser):
    """Control: at the 1920x920 baseline the view does not scroll and the
    menu fits as authored, so the open leaves scrollTop at 0."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, (1920, 920))
    try:
        st = _open(page, "pointer")
        assert st["maxScroll"] == 0 and st["scroll"] == 0, st
        _assert_fits(st, "1920x920")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_the_open_scrolls_only_as_far_as_the_menu_needs(mock_server, pw_browser):
    """At 1280x720 the menu's bottom was cut off at open. Nearest scrolls
    the view just far enough that the menu's bottom meets the view's bottom
    edge, never to the end of the view and never past the menu."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, (1280, 720))
    try:
        st = _open(page, "pointer")
        assert st["scroll"] > 0, f"anchor: the menu did not need a scroll: {st}"
        assert abs(st["menu"]["bottom"] - st["clip"]["bottom"]) <= 1.0, st
        assert st["scroll"] <= st["maxScroll"], st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
