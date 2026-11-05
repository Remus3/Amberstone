"""
tests/snapshot_panels/test_view_label_same_view_pick.py
RM-1439 (s144 uiux) - the header's current-view label follows the manual
flag even when the view itself does not change.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1&mode=sr before
the fix. web/js/main.js applyView() returns early when the target is already
the current view, and only the view-change path calls _viewUpdateTitleLabel.
The label (#view-current-label) reads "AUTO <dot> <VIEW>" while no manual
view is saved and "<VIEW>" once one is, so:
- a menu pick of the view already shown saved it as manual but left the
  label reading "AUTO <dot> HOME" - it claimed auto on a manual view;
- "Auto (clear manual)" while the auto view equals the current one cleared
  the manual view but left the label reading "HOME", with no AUTO prefix.

THE FIX. applyView's same-view branch rewrites the label too, and
_viewUpdateTitleLabel leaves the label's nodes alone when its text is already
right, so a re-apply of the same view in the same mode (every resolve on a
state tick) does not rebuild it.

What is checked, at the 1920x920 baseline:
- pick Home from the menu while on auto Home: the label reads "HOME";
- then "Auto (clear manual)": the label reads "AUTO <dot> HOME" again;
- start on a saved manual Home and clear it: the label gains the prefix;
- picking the current view a second time does not touch the label's nodes.
"""
from tests.snapshot_panels.test_focus_ring_token_sites import _new_page

_PREFIX = "AUTO " + chr(0xB7) + " "  # the middle dot, kept ASCII in source
_VP = (1920, 920)

_LABEL = "() => document.getElementById('view-current-label').textContent"


def _open(pw_browser, mock_server, saved_manual=None):
    ctx, page, errors = _new_page(pw_browser, mock_server, _VP)
    route = "#home"
    if saved_manual:
        # The manual view a previous visit saved (web/js/main.js
        # _viewSaveManual writes this key; init reads it back). No hash:
        # ?ui_mock=1 with a #view hash clears this key on load (main.js,
        # the ui_mock IIFE), and with no LCU the auto view is Home.
        page.add_init_script(
            f"try {{ localStorage.setItem('rc-view-manual', {saved_manual!r}); }}"
            " catch (_) {}")
        route = ""
    page.goto(f"{mock_server.url}/?ui_mock=1&mode=sr{route}",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector("#view-trigger", state="visible", timeout=10_000)
    page.wait_for_function(
        "() => document.body.dataset.view === 'home'"
        " && document.getElementById('view-current-label').textContent"
        ".trim().endsWith('HOME')", timeout=10_000)
    page.wait_for_timeout(200)
    return ctx, page, errors


def _pick(page, view):
    page.click("#view-trigger")
    page.click(f".view-menu-item[data-view='{view}']")
    page.wait_for_timeout(150)


def test_a_pick_of_the_shown_view_drops_the_auto_prefix(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server)
    try:
        assert page.evaluate(_LABEL) == _PREFIX + "HOME", (
            f"anchor: Home did not open in auto mode: {page.evaluate(_LABEL)!r}")
        _pick(page, "home")
        manual = page.evaluate("() => localStorage.getItem('rc-view-manual')")
        assert manual == "home", f"anchor: the pick saved no manual view: {manual!r}"
        assert page.evaluate("() => document.body.dataset.view") == "home"
        assert page.evaluate(_LABEL) == "HOME", (
            "a manual pick of the shown view still reads auto: "
            f"{page.evaluate(_LABEL)!r}")
        _pick(page, "auto")
        manual = page.evaluate("() => localStorage.getItem('rc-view-manual')")
        assert manual is None, f"anchor: Auto did not clear the manual view: {manual!r}"
        assert page.evaluate(_LABEL) == _PREFIX + "HOME", (
            "Auto (clear manual) on the shown view left no AUTO prefix: "
            f"{page.evaluate(_LABEL)!r}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_clearing_a_saved_manual_view_restores_the_prefix(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, saved_manual="home")
    try:
        assert page.evaluate(_LABEL) == "HOME", (
            f"anchor: the saved manual Home did not open manual: {page.evaluate(_LABEL)!r}")
        _pick(page, "auto")
        assert page.evaluate("() => document.body.dataset.view") == "home", (
            "anchor: the auto view is not Home, so this is not the same-view path")
        assert page.evaluate(_LABEL) == _PREFIX + "HOME", (
            "clearing the saved manual Home left no AUTO prefix: "
            f"{page.evaluate(_LABEL)!r}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_repeat_pick_does_not_rebuild_the_label(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server)
    try:
        _pick(page, "home")
        assert page.evaluate(_LABEL) == "HOME"
        page.evaluate(
            "() => { const l = document.getElementById('view-current-label');"
            " window.__labelMut = 0;"
            " new MutationObserver((m) => { window.__labelMut += m.length; })"
            ".observe(l, {childList: true, subtree: true, characterData: true}); }")
        _pick(page, "home")
        assert page.evaluate(_LABEL) == "HOME"
        muts = page.evaluate("() => window.__labelMut")
        assert muts == 0, f"a repeat pick of the same view rebuilt the label: {muts} mutations"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
