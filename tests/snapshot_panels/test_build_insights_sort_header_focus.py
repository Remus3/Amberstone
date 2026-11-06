"""
tests/snapshot_panels/test_build_insights_sort_header_focus.py
RM-1761 (s144 uiux): a Build Insights sort header keeps keyboard focus
across the re-sort, and a held key is one sort.

`web/js/panels/build_insights.js` `_render` rebuilds the whole table with
`innerHTML` on every sort. Measured in headless Chromium before the fix
(`?ui_mock=1#build-insights`, 1920x920 and 923x1280): Enter or Space on a
focused `th.bi-sortable` sorted the table and threw focus to `<body>`, so a
second press did nothing and the next Tab started over from the top of the
page. A keyboard user could sort once per Tab walk (lane doc trap 2, the
innerHTML repaint). With focus kept, a held Enter would re-sort on every
autorepeat and flip the order back and forth (RM-1758 (a)); RM-1322 rule:
a held key is one press.

Positive controls: a mouse click still sorts; a click elsewhere in the page
(focus outside the table) is not stolen by a later re-render.

RM-1762 moved the tab stop from the `<th>` to a `<button class=
"bi-sort-btn">` inside it (the APG sortable table, aria-sort on the cell;
test_build_insights_sort_header_aria.py), so focus is read off the button
and its header cell's data-sort key.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

_READY = (
    "document.querySelector('#bi-table-mount table.bi-table "
    "th.bi-sortable') !== null"
)

_STATE = """
() => {
  const a = document.activeElement;
  const ths = Array.from(
    document.querySelectorAll('#bi-table-mount th.bi-sortable'));
  return {
    focusTag: a ? a.tagName : null,
    focusSort: (a && a.closest('th.bi-sortable'))
      ? a.closest('th.bi-sortable').getAttribute('data-sort') : null,
    focusInMount: !!(a && document.getElementById('bi-table-mount').contains(a)),
    focusVisible: !!(a && a.matches(':focus-visible')),
    focusH: a ? Math.round(a.getBoundingClientRect().height) : 0,
    scrollX: document.documentElement.scrollWidth > window.innerWidth,
    heads: ths.map((t) => t.textContent.trim()),
  };
}
"""


def _open(pw_browser, mock_server, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + "/?ui_mock=1#build-insights",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(_READY, timeout=10_000)
    page.keyboard.press("Tab")  # keyboard modality
    return ctx, page, errors


def _focus_head(page, key):
    page.focus(f"#bi-table-mount th.bi-sortable[data-sort='{key}'] .bi-sort-btn")


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
@pytest.mark.parametrize("key", ["Enter", " "], ids=["enter", "space"])
def test_keyboard_sort_keeps_focus_on_the_header(mock_server, pw_browser, vp, key):
    ctx, page, errors = _open(pw_browser, mock_server, vp)
    try:
        _focus_head(page, "n")
        page.keyboard.press(key)
        s1 = page.evaluate(_STATE)
        # heads = [WPA, <tab's n label>, Win Rate]; the n column sorts desc.
        assert s1["heads"][1].endswith("v"), s1
        assert s1["focusTag"] == "BUTTON" and s1["focusSort"] == "n", (
            f"focus left the sorted header after one press: {s1}")
        # The kept focus still paints the keyboard ring (test_focus_ring_
        # token_sites.py pins its 2px shape).
        assert s1["focusVisible"], s1
        # The second press must reach the same header and flip the order.
        page.keyboard.press(key)
        s2 = page.evaluate(_STATE)
        assert s2["focusSort"] == "n", s2
        assert s2["heads"][1].endswith("^"), (
            f"second keyboard press did not flip the sort: {s1['heads']} -> "
            f"{s2['heads']}")
        # Tab continues from the sorted header, not from the top of the page.
        page.keyboard.press("Tab")
        assert page.evaluate(_STATE)["focusSort"] == "observed_winrate"
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_held_enter_is_one_sort(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, vp)
    try:
        _focus_head(page, "observed_winrate")
        page.keyboard.down("Enter")
        s1 = page.evaluate(_STATE)
        # Three autorepeat keydowns on whatever holds focus now.
        for _ in range(3):
            page.evaluate(
                "() => document.activeElement.dispatchEvent(new KeyboardEvent("
                "'keydown', {key: 'Enter', repeat: true, bubbles: true, "
                "cancelable: true}))")
        page.keyboard.up("Enter")
        s2 = page.evaluate(_STATE)
        assert s1["focusSort"] == "observed_winrate", s1
        assert s2["heads"] == s1["heads"], (
            f"an autorepeat re-sorted: {s1['heads']} -> {s2['heads']}")
        assert s2["heads"][-1].endswith("v"), s2
        assert not errors, errors
    finally:
        ctx.close()


def test_control_mouse_click_still_sorts(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0])
    try:
        before = page.evaluate(_STATE)["heads"]
        page.click("#bi-table-mount th.bi-sortable[data-sort='n']")
        after = page.evaluate(_STATE)["heads"]
        assert after != before and after[1].endswith("v"), (before, after)
        page.click("#bi-table-mount th.bi-sortable[data-sort='n']")
        again = page.evaluate(_STATE)["heads"]
        assert again[1].endswith("^"), again
        assert not errors, errors
    finally:
        ctx.close()


def test_control_rerender_never_steals_focus_from_outside(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.focus("#bi-min-n")
        # A re-render with focus outside the table (the data path runs the
        # same _render) must leave focus where it is.
        page.evaluate(
            "() => document.querySelector("
            "\"#bi-table-mount th.bi-sortable[data-sort='n'] .bi-sort-btn\")"
            ".click()")
        s = page.evaluate(_STATE)
        assert s["focusInMount"] is False, s
        assert page.evaluate("document.activeElement.id") == "bi-min-n"
        assert not errors, errors
    finally:
        ctx.close()
