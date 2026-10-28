"""
tests/snapshot_panels/test_replay_row_list_semantics.py
RM-1066 (s144 uiux, residue of RM-1062 item 2): both Replay row lists
lost their list semantics. web/js/panels/dev.js `_replayViewRefresh` built
each RECENT MATCHES row as `li.replay-match-row` with `role="button"`
(RM-1018), and web/js/panels/replay_events.js `_eventRowHtml` /
`_flagRowHtml` did the same for every timeline row (R30 page 6, RM-638).
An explicit role REPLACES the implicit one, so neither `ul` nor `ol` had a
single listitem left: a screen reader announced a run of buttons with no
"list, N items" and no position in it. Measured in headless Chromium under
/?ui_mock=1#replay before the fix: role=listitem 0 of 4 match rows and
0 of 15 timeline rows.

The fix: each row is a plain `li` (implicit listitem) holding one real
`<button type="button">` that carries the row class, the data attributes,
the result stripe, the focus ring and (match rows) aria-current. The
button fills its li, so the click target and the painted row are the same
box; its UA chrome (font, color, border, background, centred text) is
reset so the row renders as before. Enter / Space / Ctrl+Space and the
focus rings stay pinned by test_replay_match_row_keyboard.py,
test_replay_space_single_action.py and test_focus_ring_token_sites.py.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import (
    VIEWPORTS,
    _new_page,
)

_LISTS = (
    # (list id, row class, rows in web/data/ui_mock/replay.json match 1)
    ("replay-match-list", "replay-match-row", 4),
    ("replay-events-list", "replay-events-row", 15),
)

# Structure of one list: every direct child, its role attribute, and what
# it holds. A row button must fill its li (same box) so a click anywhere on
# the painted row lands on the control.
_STRUCTURE = """
(id) => [...document.getElementById(id).children].map(li => {
  const kids = [...li.children];
  const b = kids[0];
  const lr = li.getBoundingClientRect();
  const br = b ? b.getBoundingClientRect() : null;
  const cs = b ? getComputedStyle(b) : null;
  const list = getComputedStyle(document.getElementById(id));
  return {
    tag: li.tagName, role: li.getAttribute('role'),
    tabIndex: li.getAttribute('tabindex'), kids: kids.length,
    btnTag: b ? b.tagName : null, btnType: b ? b.getAttribute('type') : null,
    btnRole: b ? b.getAttribute('role') : null,
    btnClass: b ? b.className : null,
    fill: br ? [br.x - lr.x, br.y - lr.y, br.width - lr.width,
                br.height - lr.height].every(d => Math.abs(d) < 0.5) : false,
    h: br ? br.height : 0,
    fontFamily: cs ? cs.fontFamily === list.fontFamily : false,
    color: cs ? cs.color === list.color : false,
    textAlign: cs ? cs.textAlign : null,
    blocky: b ? [...b.querySelectorAll('*')].map(e => e.tagName)
      .filter(t => t === 'DIV' || t === 'P' || t === 'UL') : [],
  };
})
"""


def _load_match(page, mock_server):
    page.goto(mock_server.url + "/?ui_mock=1#replay",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector("#replay-match-list .replay-match-row",
                           timeout=10_000)
    page.click("#replay-match-list .replay-match-row")
    page.wait_for_function(
        "() => document.querySelectorAll('.replay-events-row').length > 0",
        timeout=10_000,
    )


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_rows_are_listitems_holding_one_real_button(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _load_match(page, mock_server)
        for list_id, row_cls, n in _LISTS:
            lst = page.locator("#" + list_id)
            # Accessible roles, as Playwright computes them (implicit + explicit).
            assert lst.get_by_role("listitem").count() == n, list_id
            assert lst.get_by_role("button").count() == n, list_id
            rows = page.evaluate(_STRUCTURE, list_id)
            assert len(rows) == n, (list_id, len(rows))
            bad = [r for r in rows if not (
                r["tag"] == "LI" and r["role"] is None and r["tabIndex"] is None
                and r["kids"] == 1 and r["btnTag"] == "BUTTON"
                and r["btnType"] == "button" and r["btnRole"] is None
                and row_cls in r["btnClass"].split()
                # Button content is phrasing content only (HTML content model).
                and not r["blocky"]
            )]
            assert not bad, f"{list_id}: rows are not li > button: {bad[:2]}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_row_button_fills_its_row_and_drops_the_ua_chrome(
    mock_server, pw_browser, vp
):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _load_match(page, mock_server)
        for list_id, _row_cls, _n in _LISTS:
            rows = page.evaluate(_STRUCTURE, list_id)
            bad = [r for r in rows if not (
                r["fill"] and r["h"] >= 42 and r["fontFamily"] and r["color"]
                and r["textAlign"] in ("left", "start")
            )]
            assert not bad, f"{list_id}: row button box / chrome wrong: {bad[:2]}"
        # The match row keeps no UA button background or border at rest.
        rest = page.evaluate(
            """() => { const b = document.querySelector(
                 '#replay-match-list .replay-match-row:not(.active)');
               const cs = getComputedStyle(b);
               return { bg: cs.backgroundColor, top: cs.borderTopWidth,
                        left: cs.borderLeftWidth, bottom: cs.borderBottomWidth }; }"""
        )
        assert rest == {"bg": "rgba(0, 0, 0, 0)", "top": "0px",
                        "left": "0px", "bottom": "1px"}, rest
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_aria_current_sits_on_the_loaded_rows_button(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _load_match(page, mock_server)
        cur = page.evaluate(
            """() => [...document.querySelectorAll('#replay-match-list [aria-current]')]
                 .map(e => ({ tag: e.tagName, val: e.getAttribute('aria-current'),
                              active: e.classList.contains('active') }))"""
        )
        assert cur == [{"tag": "BUTTON", "val": "true", "active": True}], cur
        # Activating another row moves it; the li never carries it.
        page.locator("#replay-match-list .replay-match-row").nth(2).click()
        cur = page.evaluate(
            """() => [...document.querySelectorAll('#replay-match-list [aria-current]')]
                 .map(e => ({ tag: e.tagName,
                   idx: [...document.querySelectorAll(
                     '#replay-match-list .replay-match-row')].indexOf(e) }))"""
        )
        assert cur == [{"tag": "BUTTON", "idx": 2}], cur
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
