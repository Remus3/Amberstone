"""
tests/snapshot_panels/test_build_insights_sort_header_aria.py
RM-1762 (s144 uiux): a Build Insights sort header exposes its sort state
to assistive tech, the APG sortable-table shape.

Measured in headless Chromium before the fix (`?ui_mock=1#build-insights`,
1920x920 and 923x1280): each sortable header was `<th role="button"
tabindex="0">`. The role override took the cell out of the column-header
role, so `aria-sort` could not apply, and no header carried it. The only
sort cue was the letter " v" or " ^" appended to the text, so the button's
accessible name read "WPA v" (a stray letter, no direction). The WAI-ARIA
APG sortable table puts a real `<button>` inside a `<th aria-sort>`: the
cell stays a column header, `aria-sort` sits on the sorted column only, and
the visible arrow is aria-hidden.

Positive control: the non-sortable "Expected WP" header is a plain column
header with no button and no aria-sort, before and after.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

_READY = (
    "document.querySelector('#bi-table-mount table.bi-table "
    "th.bi-sortable') !== null"
)

# Per header cell: role override, aria-sort, the inner button (if any) with
# its type, text and box, and the cell box (the button must fill it, so the
# whole header stays the hit target it was).
_HEADS = """
(mount) => Array.from(
  document.querySelectorAll('#' + (mount || 'bi-table-mount')
    + ' table.bi-table thead th')
).map((th) => {
  const b = th.querySelector('button');
  const tr = th.getBoundingClientRect();
  const br = b ? b.getBoundingClientRect() : null;
  return {
    cls: th.className,
    sort: th.getAttribute('data-sort'),
    role: th.getAttribute('role'),
    thTab: th.getAttribute('tabindex'),
    ariaSort: th.getAttribute('aria-sort'),
    btn: !!b,
    btnType: b ? b.getAttribute('type') : null,
    btnW: br ? Math.round(br.width) : 0,
    btnH: br ? Math.round(br.height) : 0,
    thW: Math.round(tr.width),
    thH: Math.round(tr.height),
    text: th.textContent.trim(),
  };
})
"""


def _open(pw_browser, mock_server, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + "/?ui_mock=1#build-insights",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(_READY, timeout=10_000)
    page.keyboard.press("Tab")  # keyboard modality
    return ctx, page, errors


def _by_sort(heads):
    return {h["sort"]: h for h in heads if h["sort"]}


def _sorted_cols(heads):
    return {h["sort"]: h["ariaSort"] for h in heads if h["ariaSort"]}


def _table(page):
    return page.locator("#bi-table-mount table.bi-table")


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_sort_headers_are_column_headers_holding_a_button(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, vp)
    try:
        heads = page.evaluate(_HEADS)
        sortable = [h for h in heads if h["sort"]]
        assert len(sortable) == 3, heads
        for h in sortable:
            assert h["role"] is None and h["thTab"] is None, (
                f"the cell overrides its column-header role or is itself a "
                f"tab stop: {h}")
            assert h["btn"] and h["btnType"] == "button", h
            # The button fills the cell, so the whole header is still the
            # click / hit target (--hit-min 42).
            assert h["btnH"] >= 42, h
            assert abs(h["btnW"] - h["thW"]) <= 1, h
            assert abs(h["btnH"] - h["thH"]) <= 1, h
        # Accessibility tree: three column headers that each hold a button
        # named by the column alone (the arrow is aria-hidden).
        tbl = _table(page)
        for name in ("WPA", "Win Rate"):
            assert tbl.get_by_role("columnheader", name=name, exact=True).count() == 1
            assert tbl.get_by_role("button", name=name, exact=True).count() == 1
        assert tbl.get_by_role("button").count() == 3
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_aria_sort_follows_the_keyboard_sort(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, vp)
    try:
        # Default state: WPA descending, and only WPA carries aria-sort.
        assert _sorted_cols(page.evaluate(_HEADS)) == {"wpa": "descending"}
        page.focus("#bi-table-mount th.bi-sortable[data-sort='n'] button")
        page.keyboard.press("Enter")
        h1 = page.evaluate(_HEADS)
        assert _sorted_cols(h1) == {"n": "descending"}, h1
        assert _by_sort(h1)["n"]["text"].endswith("v"), h1
        page.keyboard.press(" ")
        h2 = page.evaluate(_HEADS)
        assert _sorted_cols(h2) == {"n": "ascending"}, h2
        assert _by_sort(h2)["n"]["text"].endswith("^"), h2
        # The sorted column's header is reachable by its state in the tree.
        n_name = _by_sort(h2)["n"]["text"][:-2]
        assert _table(page).get_by_role(
            "button", name=n_name, exact=True).count() == 1, n_name
        assert not errors, errors
    finally:
        ctx.close()


def test_aria_sort_on_another_tab(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.click(".bi-tab[data-bi-tab='runes']")
        page.wait_for_function(
            "document.querySelector('#bi-rune-table-mount th.bi-sortable"
            "[data-sort=\"n\"]') !== null", timeout=10_000)
        page.click(
            "#bi-rune-table-mount th.bi-sortable[data-sort='observed_winrate']")
        heads = page.evaluate(_HEADS, "bi-rune-table-mount")
        assert _sorted_cols(heads) == {"observed_winrate": "descending"}, heads
        assert all(h["btn"] for h in heads if h["sort"]), heads
        assert _by_sort(heads)["n"]["text"].startswith("Picks"), heads
        assert not errors, errors
    finally:
        ctx.close()


def test_control_unsortable_header_stays_plain(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0])
    try:
        exp = [h for h in page.evaluate(_HEADS) if "bi-c-exp" in h["cls"]]
        assert len(exp) == 1, exp
        assert exp[0]["btn"] is False and exp[0]["ariaSort"] is None, exp
        assert exp[0]["role"] is None, exp
        assert _table(page).get_by_role(
            "columnheader", name="Expected WP", exact=True).count() == 1
        assert not errors, errors
    finally:
        ctx.close()
