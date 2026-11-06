"""
tests/snapshot_panels/test_tft_board_more_cue.py
The TFT Active Match BOARD says how many units sit below its fixed box
(s144 lane uiux, RM-1771).

The board wrapper (web/js/panels/active_match.js _amTftBoardNode,
web/css/panels/active_match.css .am-tft-board-wrap) is a fixed eyebrow + two
chip-row box, so a round landing never reflows the pane grid. Since
RM-1766 a narrower window drops a column instead of cutting a name, so the
seven-unit tft_round board needs a third row once the window is under about
1150 px (three columns), and that row sat below the box with nothing on
screen saying so. Measured on this fixture: 1 unit hidden at 1100 / 1024 /
the 923x1280 companion size, 3 at 800-640, 5 at 560 and under, while the
eyebrow read "7 UNITS - as of 17:27" (RM-1766 verifier SHOULD-FIX, filed
FUTURE).

Contract pinned here:
  - the eyebrow row carries a cue, "+N BELOW", whose N is the number of chips
    not wholly inside the visible box; it shows only when N > 0 (short on
    purpose: the eyebrow already says UNITS, and the cue must stay whole in a
    150 px board where the eyebrow text ellipsises first);
  - at the 1920x920 baseline (two rows fit) the cue is hidden and the eyebrow
    text is unchanged (control);
  - the cue is one line, whole, inside the board, beside (not over) the
    eyebrow text, at the eyebrow's type and colour, and the eyebrow row keeps
    its one-line height, so the wrapper stays the fixed 132 px box (and the
    board eyebrow itself is one line with its whole text as the title, the
    RM-1767 verifier SHOULD-FIX);
  - the eyebrow row is pinned (sticky, the pane colour behind it), so the
    cue stays on screen while units remain below (verifier SHOULD-FIX);
  - it follows the box: scrolled to the bottom it hides, and a window resized
    from the baseline to 1024 px shows it without a new round (no poll);
  - it is aria-hidden: the list already gives assistive tech every unit.

Those counts are the two-column layout. Since RM-1772 the panes stack in
one full-width column at 720 px and under, so the board there is wider
(four columns at 640, three at 480) and fewer units are hidden. The size
sweep computes its count from the measured column count; the pinned and
scrolled-to-bottom cases use 760 and 800, which are still two columns.

Drive path: /?ui_mock=1&mode=tft_round#active-match (web/data/ui_mock/
active_match_tft_round.json, a recorded S134 round row: seven units).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_SETTLE = r"""
async () => {
  await document.fonts.ready;
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));
}
"""

_MEASURE = r"""
() => {
  const wrap = document.querySelector('#am-build-body .am-tft-board-wrap');
  const wr = wrap.getBoundingClientRect();
  const visBottom = wr.top + wrap.clientTop + wrap.clientHeight;
  const below = Array.from(wrap.querySelectorAll('.am-tft-unit'))
    .filter(u => u.getBoundingClientRect().bottom > visBottom + 0.5).length;
  const sec = wrap.querySelector('.am-tft-sec');
  const cue = wrap.querySelector('.am-tft-more');
  const box = el => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {left: r.left, right: r.right, top: r.top, bottom: r.bottom,
            height: r.height, text: el.textContent,
            scroll: el.scrollWidth, client: el.clientWidth,
            display: cs.display, visibility: cs.visibility,
            fontSize: cs.fontSize, fontWeight: cs.fontWeight,
            color: cs.color, lineHeight: cs.lineHeight,
            hidden: el.hidden, ariaHidden: el.getAttribute('aria-hidden'),
            title: el.title, whiteSpace: cs.whiteSpace};
  };
  const head = sec ? sec.parentElement : null;
  const cols = getComputedStyle(wrap.querySelector('.am-tft-board'))
    .gridTemplateColumns.trim().split(/\s+/).length;
  // The first opaque colour behind the wrapper: a pinned head must paint it.
  const rgba = c => { const cv = document.createElement('canvas');
    cv.width = cv.height = 1; const x = cv.getContext('2d');
    x.fillStyle = c; x.fillRect(0, 0, 1, 1);
    return Array.from(x.getImageData(0, 0, 1, 1).data).join(','); };
  let el = wrap, behind = null;
  while (el && !behind) {
    const b = getComputedStyle(el).backgroundColor;
    if (rgba(b).endsWith(',255')) behind = rgba(b);
    el = el.parentElement;
  }
  let onTop = null;
  if (cue && !cue.hidden) {
    const c = cue.getBoundingClientRect();
    const hit = document.elementFromPoint((c.left + c.right) / 2,
                                          (c.top + c.bottom) / 2);
    onTop = !!hit && (hit === cue || cue.contains(hit));
  }
  return {below, cols, wrapH: wrap.clientHeight, wrapScroll: wrap.scrollHeight,
          wrapTop: wr.top + wrap.clientTop, wrapLeft: wr.left, wrapRight: wr.right,
          scrollTop: wrap.scrollTop,
          sec: box(sec), cue: box(cue), head: box(head),
          headBg: head ? rgba(getComputedStyle(head).backgroundColor) : null,
          headPos: head ? getComputedStyle(head).position : null,
          behind, cueOnTop: onTop,
          headIsWrapChild: head ? head.parentElement === wrap : false};
}
"""

_SIZES = [(1920, 920), (1440, 900), (1199, 920), (1100, 900), (1024, 768),
          (923, 1280), (768, 1024), (640, 900), (480, 800)]


def _open(pw_browser, mock_server, w: int, h: int):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=tft_round#active-match",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "document.querySelectorAll('#am-build-body .am-tft-unit').length > 0",
        timeout=10_000,
    )
    page.evaluate(_SETTLE)
    return ctx, page, errors


def _shown(c: dict | None) -> bool:
    return bool(c) and not c["hidden"] and c["display"] != "none" \
        and c["visibility"] != "hidden" and c["height"] > 0


def _units_word(n: int) -> str:
    return f"+{n} BELOW"


def test_baseline_has_no_cue_and_keeps_the_eyebrow(mock_server, pw_browser):
    # Control: two rows fit at 1920x920, so nothing is below and the cue is
    # hidden; the eyebrow text and the 132 px wrapper are unchanged.
    ctx, page, errors = _open(pw_browser, mock_server, 1920, 920)
    try:
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert m["below"] == 0, m
    assert m["wrapH"] == 132 and m["wrapScroll"] <= m["wrapH"], m
    assert m["sec"]["text"] == "7 UNITS - as of 17:27", m["sec"]
    assert m["cue"] is not None, "no .am-tft-more cue element in the board"
    assert not _shown(m["cue"]), m["cue"]


@pytest.mark.parametrize("w,h", _SIZES)
def test_cue_counts_the_units_below_the_box(w, h, mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, w, h)
    try:
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert m["wrapH"] == 132, m["wrapH"]
    cue, sec, head = m["cue"], m["sec"], m["head"]
    assert cue is not None, "no .am-tft-more cue element in the board"
    assert cue["ariaHidden"] == "true", cue
    # The board eyebrow is one line at every width, its whole text in the
    # title (the RM-1767 verifier SHOULD-FIX: pinned for the lobby only).
    one_line = float(sec["lineHeight"].rstrip("px")) + 0.5
    assert sec["whiteSpace"] == "nowrap" and sec["height"] <= one_line, sec
    assert sec["title"] == sec["text"] and sec["text"].startswith("7 UNITS"), sec
    assert m["headIsWrapChild"], "eyebrow row is not a direct wrapper child"
    # One text line plus the eyebrow's own 6 px gap (padding on the pinned
    # row), so the 132 px box is unchanged.
    assert head["height"] <= one_line + 6.5, head
    # Independent of the code's counting method: seven units in `cols`
    # columns, two chip rows visible in the fixed box.
    assert m["below"] == max(0, 7 - 2 * m["cols"]), (w, h, m["cols"], m["below"])
    if m["below"] == 0:
        assert not _shown(cue), f"{w}x{h}: cue shown with nothing below: {cue}"
        return
    assert _shown(cue), (
        f"{w}x{h}: {m['below']} unit(s) below the box and no visible cue")
    assert cue["text"] == _units_word(m["below"]), (w, h, cue["text"])
    # One line, whole, inside the board, beside the eyebrow text.
    assert cue["scroll"] <= cue["client"], f"{w}x{h}: cue text cut: {cue}"
    assert cue["height"] <= one_line, cue
    assert m["cueOnTop"], f"{w}x{h}: cue is covered at its own centre"
    assert cue["left"] >= m["wrapLeft"] - 0.5, (w, h, cue)
    assert cue["right"] <= m["wrapRight"] + 0.5, (w, h, cue)
    assert cue["left"] >= sec["right"] - 0.5, (
        f"{w}x{h}: cue overlaps the eyebrow text ({cue['left']:.1f} < "
        f"{sec['right']:.1f})")
    # The eyebrow's own type and colour (--fs-xs, --text-dim), not sub-floor.
    assert cue["fontSize"] == sec["fontSize"] == "16px", (cue, sec)
    assert cue["color"] == sec["color"], (cue["color"], sec["color"])
    assert cue["fontWeight"] == sec["fontWeight"], (cue, sec)


def test_companion_size_shows_the_hidden_row(mock_server, pw_browser):
    # The RM-1766 FUTURE case itself, at the 923x1280 companion size:
    # three columns, so the seventh unit is a third row below the box.
    ctx, page, errors = _open(pw_browser, mock_server, 923, 1280)
    try:
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert m["below"] == 1, f"fixture no longer overflows by one row: {m}"
    assert _shown(m["cue"]), m["cue"]
    assert m["cue"]["text"] == "+1 BELOW", m["cue"]


_BOX_JS = r"""
() => {
  const w = document.querySelector('#am-build-body .am-tft-board-wrap');
  return {scrollW: w.scrollWidth, clientW: w.clientWidth};
}
"""


@pytest.mark.parametrize("w,h", [(360, 800), (320, 700)])
def test_cue_never_spills_a_board_narrower_than_itself(
        w, h, mock_server, pw_browser):
    # Before RM-1772 the board at 320 px was 78 px, narrower than
    # "+5 BELOW", and the cue ellipsised inside the box. Since the panes
    # stack at 720 and under, the board takes the full column, so these
    # widths now pin only that the cue never spills the box sideways; the
    # max-width rule stays for a board narrower than its cue.
    ctx, page, errors = _open(pw_browser, mock_server, w, h)
    try:
        m = page.evaluate(_MEASURE)
        box = page.evaluate(_BOX_JS)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert m["below"] >= 1 and _shown(m["cue"]), m
    assert m["cue"]["right"] <= m["wrapRight"] + 0.5, (w, m["cue"], m["wrapRight"])
    assert box["scrollW"] <= box["clientW"], (w, box)
    assert m["wrapH"] == 132, m["wrapH"]


def test_cue_stays_pinned_while_units_remain_below(mock_server, pw_browser):
    # The RM-1771 verifier SHOULD-FIX: at 760 px (two columns, the last
    # two-column width band since RM-1772 stacks the panes at 720 and
    # under) three units are below; scrolling one chip row must not scroll
    # the cue away with the eyebrow. The pinned row paints the pane colour,
    # so no chip shows through it.
    ctx, page, errors = _open(pw_browser, mock_server, 760, 900)
    try:
        before = page.evaluate(_MEASURE)
        page.evaluate(
            "() => { document.querySelector("
            "'#am-build-body .am-tft-board-wrap').scrollTop = 60; }")
        page.evaluate(_SETTLE)
        after = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert before["below"] == 3, before
    assert after["scrollTop"] == 60, after["scrollTop"]
    assert 1 <= after["below"] < 3, after
    assert _shown(after["cue"]), after["cue"]
    assert after["cue"]["text"] == _units_word(after["below"]), after["cue"]
    assert after["headPos"] == "sticky", after["headPos"]
    assert after["cue"]["top"] >= after["wrapTop"] - 0.5, (
        after["cue"], after["wrapTop"])
    assert after["cueOnTop"], "a scrolled chip covers the cue"
    assert after["headBg"] == after["behind"], (after["headBg"], after["behind"])


def test_cue_hides_when_scrolled_to_the_bottom(mock_server, pw_browser):
    # 800 px: two columns, three units below (640 was used before
    # RM-1772; the stacked single column there now fits four columns).
    ctx, page, errors = _open(pw_browser, mock_server, 800, 900)
    try:
        before = page.evaluate(_MEASURE)
        page.evaluate(
            "() => { const w = document.querySelector("
            "'#am-build-body .am-tft-board-wrap'); w.scrollTop = w.scrollHeight; }")
        page.evaluate(_SETTLE)
        after = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert before["below"] == 3 and _shown(before["cue"]), before
    assert after["below"] == 0, after
    assert not _shown(after["cue"]), after["cue"]


def test_cue_follows_a_window_resize(mock_server, pw_browser):
    # No new round and no poll: narrowing the window alone must show it.
    ctx, page, errors = _open(pw_browser, mock_server, 1920, 920)
    try:
        wide = page.evaluate(_MEASURE)
        page.set_viewport_size({"width": 1024, "height": 920})
        page.evaluate(_SETTLE)
        page.evaluate(_SETTLE)
        narrow = page.evaluate(_MEASURE)
        page.set_viewport_size({"width": 1920, "height": 920})
        page.evaluate(_SETTLE)
        page.evaluate(_SETTLE)
        wide_again = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert wide["below"] == 0 and not _shown(wide["cue"]), wide
    assert narrow["below"] >= 1, narrow
    assert _shown(narrow["cue"]), narrow["cue"]
    assert narrow["cue"]["text"] == _units_word(narrow["below"]), narrow["cue"]
    assert wide_again["below"] == 0 and not _shown(wide_again["cue"]), wide_again
