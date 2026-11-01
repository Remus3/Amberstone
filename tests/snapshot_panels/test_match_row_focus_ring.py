"""
tests/snapshot_panels/test_match_row_focus_ring.py
RM-1314 (s144 uiux) - a keyboard-focused Session / History match row
draws the token focus ring and keeps its own W/L result encoding.

THE DEFECT. web/js/main.js `_wireMatchRowToHistoricalPgr` makes every
populated .history-match-row a keyboard control (role=button, tabindex=0,
Enter / Space open the detached historical PGR). Its only focus style was
the shared HIST1 rule in web/css/panels/home.css
(`.history-match-row-clickable:hover, .history-match-row-clickable:focus-visible`),
which set `outline: none` and swapped in the hover tint. MEASURED in
headless Chromium under /?ui_mock=1 at 1920x920 before the fix (default
theme arcane):
  - #session, all 6 rows: focused + :focus-visible, yet outline-style
    none and box-shadow none - the only cue was a 0.18-alpha --info tint,
    identical to hover, no ring at all;
  - #history, the 4 rows of a selected session (2 win, 2 loss): focusing
    a row REPLACED its --good / --bad result rail and result tint with the
    --info ones, so the W/L hue of the very row the keyboard user is on
    disappeared (the CSS-escape triangle glyph was the only survivor);
  - the swap also moved padding-left 10px -> 8px, shifting the row's text
    2px on every focus.
Found by a focus sweep over every visible focusable control on ten
?ui_mock=1 views: these rows were the only focused controls with neither an
outline nor a box-shadow.

THE FIX. :focus-visible gets its own rule: `outline: 2px solid
var(--accent)` with a 1px offset - the RM-1210 / Lobby precedent
(.home-action-tile, .view-tab, .lq-btn). The rows sit in a 4px-gap flex
column, so the ring's 3px reach stays clear of the neighbouring row. The
HIST1 hover tint stays a pointer affordance on :hover only.

WHAT IS MEASURED (headless Chromium, computed values, never a grep):
  - every rendered row, focused with keyboard modality, matches
    :focus-visible and computes a solid >= 2px outline in the resolved
    --accent, >= 3:1 against the opaque surface it is painted on (the
    PAIR is the ring colour vs that ancestor background), unclipped by
    an overflow box, and its reach stays inside the gap to the next row;
  - focusing a win / loss row leaves its background, its left rail
    colour and its padding-left exactly as they were unfocused;
  - pointer hover still paints the HIST1 tint;
  - the ring holds in every :root[data-theme] block of web/css/themes.css.
"""
import re
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_home_history_nav_focus_ring import (
    _RING_JS,
    _assert_rings,
)

ROOT = Path(__file__).resolve().parent.parent.parent

SESSION_ROWS = "#session-matches .history-match-row-clickable"
HISTORY_ROWS = "#history-match-list .history-match-row-clickable"
N_SESSION = 6   # web/data/ui_mock/session.json matches
N_HISTORY = 4   # first session of the history fixture's "14d" scope

_STATE_JS = r"""
(sel) => {
  const pick = (el) => {
    const cs = getComputedStyle(el);
    return [cs.backgroundColor, cs.borderLeftColor, cs.borderLeftWidth,
            cs.paddingLeft].join(' | ');
  };
  return Array.from(document.querySelectorAll(sel))
    .filter((el) => el.getBoundingClientRect().height)
    .map((el) => {
      if (document.activeElement && document.activeElement.blur) {
        document.activeElement.blur();
      }
      const before = pick(el);
      el.focus();
      const after = pick(el);
      return { result: el.dataset.result || '', before, after,
               fv: el.matches(':focus-visible') };
    });
}
"""


def _open(pw_browser, mock_server, view):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1#{view}",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        f"document.body.dataset.view === '{view}'", timeout=10_000
    )
    if view == "session":
        sel, n = SESSION_ROWS, N_SESSION
    else:
        # The History match list paints once a session row is chosen.
        page.wait_for_selector(
            "#history-session-list .history-session-row", timeout=10_000
        )
        page.click("#history-session-list .history-session-row")
        sel, n = HISTORY_ROWS, N_HISTORY
    page.wait_for_function(
        f"document.querySelectorAll('{sel}').length === {n}", timeout=10_000
    )
    page.evaluate("document.fonts.ready.then(() => true)")
    # Rows transition background / border and the deep-link pulse animates,
    # so a read right after focus or a theme flip would straddle it.
    page.add_style_tag(
        content="*, *::before, *::after { transition: none !important;"
        " animation: none !important; }"
    )
    page.mouse.move(0, 0)
    page.keyboard.press("Shift")  # keyboard modality for :focus-visible
    return ctx, page, errors, sel, n


def test_session_match_rows_paint_the_accent_ring(mock_server, pw_browser):
    ctx, page, errors, sel, n = _open(pw_browser, mock_server, "session")
    try:
        rows = page.evaluate(_RING_JS, sel)
        _assert_rings(rows, n, "Session match row")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_history_match_rows_paint_the_accent_ring(mock_server, pw_browser):
    ctx, page, errors, sel, n = _open(pw_browser, mock_server, "history")
    try:
        rows = page.evaluate(_RING_JS, sel)
        _assert_rings(rows, n, "History match row")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_focus_keeps_the_rows_result_encoding(mock_server, pw_browser):
    """Focus adds a ring; it never repaints the row. The --good / --bad
    rail and tint of a win / loss row, and its padding, read the same
    focused as unfocused."""
    ctx, page, errors, sel, n = _open(pw_browser, mock_server, "history")
    try:
        rows = page.evaluate(_STATE_JS, sel)
        assert len(rows) == n, rows
        results = sorted(r["result"] for r in rows)
        # Anchor: the fixture really carries both result rails.
        assert "win" in results and "loss" in results, results
        assert all(r["fv"] for r in rows), rows
        changed = [r for r in rows if r["before"] != r["after"]]
        assert not changed, f"focus repainted the row: {changed}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pointer_hover_keeps_the_hist1_tint(mock_server, pw_browser):
    ctx, page, errors, sel, n = _open(pw_browser, mock_server, "session")
    try:
        first = page.locator(sel).first
        rest = first.evaluate("(el) => getComputedStyle(el).backgroundColor")
        first.hover()
        hov = first.evaluate("(el) => getComputedStyle(el).backgroundColor")
        info_soft = page.evaluate(
            "() => { const d = document.createElement('div');"
            " d.style.background = 'var(--info-soft)';"
            " document.body.appendChild(d);"
            " const c = getComputedStyle(d).backgroundColor;"
            " d.remove(); return c; }"
        )
        assert hov != rest, (rest, hov)
        assert hov == info_soft, (hov, info_soft)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _themes():
    text = (ROOT / "web" / "css" / "themes.css").read_text(encoding="utf-8")
    return sorted(set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text)))


def test_ring_holds_in_every_theme(mock_server, pw_browser):
    themes = _themes()
    assert len(themes) >= 5, f"theme scan anchor: {themes}"
    failures, accents, seen = [], set(), 0
    for view in ("session", "history"):
        ctx, page, errors, sel, n = _open(pw_browser, mock_server, view)
        try:
            for t in themes:
                page.evaluate(
                    "(t) => document.documentElement"
                    ".setAttribute('data-theme', t)",
                    t,
                )
                page.keyboard.press("Shift")
                rows = page.evaluate(_RING_JS, sel)
                assert rows, f"{t} #{view}: no row rendered"
                seen += len(rows)
                for r in rows:
                    accents.add(r["accent"])
                    if not (r["style"] == "solid" and r["width"] >= 2
                            and r["ring"] == r["accent"]
                            and r["contrast"] >= 3.0):
                        failures.append((t, view, r))
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    assert seen == len(themes) * (N_SESSION + N_HISTORY), seen
    assert len(accents) >= 3, f"theme flip inert: {accents}"
    assert not failures, f"theme ring failures: {failures[:4]}"


# --- RM-1315: pointer hover and the deep-link .is-focused glow ---------
#
# THE DEFECT. Two more HIST1-era rules in web/css/panels/home.css repainted
# a result row the same way focus used to: `.history-match-row-clickable:hover`
# and the Recent-5 deep-link `.history-match-row.is-focused` both set
# `border-left: 3px solid var(--info)`, the --info-soft tint and
# `padding-left: 8px`. MEASURED in headless Chromium under /?ui_mock=1 at
# 1920x920 (default theme arcane), #history with its first session chosen
# (2 win, 2 loss rows): hovering or deep-linking a win / loss row replaced
# its --good / --bad rail and result tint with the --info ones and moved
# padding-left 10px -> 8px, so the row the pointer is on (or the one the
# operator just jumped to) lost its W/L hue and shifted its text 2px.
#
# THE FIX. The --info tint + rail stay the cue for a NEUTRAL row (no known
# result) only, with no padding change. A win / loss row keeps its own rail
# and tint: on hover its other three borders turn --accent (the shared
# .history-match-row:hover rule in header.css), and a deep-linked row of
# any kind draws a 2px --info outline at a 1px offset.

_PAINT_JS = r"""
(el) => {
  const cs = getComputedStyle(el);
  return { bg: cs.backgroundColor, rail: cs.borderLeftColor,
           railW: cs.borderLeftWidth, pad: cs.paddingLeft,
           top: cs.borderTopColor, oStyle: cs.outlineStyle,
           oWidth: parseFloat(cs.outlineWidth) || 0, oColor: cs.outlineColor,
           result: el.dataset.result || '' };
}
"""

_TOKEN_JS = r"""
(name) => {
  const d = document.createElement('div');
  d.style.color = `var(${name})`;
  document.body.appendChild(d);
  const c = getComputedStyle(d).color;
  d.remove();
  return c;
}
"""

_RING_CONTRAST_JS = r"""
(el) => {
  // Resolve any CSS colour syntax (oklch included) to sRGB bytes through a
  // 1x1 canvas, as the shared _RING_JS helper does.
  const cv = document.createElement('canvas');
  cv.width = 1; cv.height = 1;
  const c2 = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (col) => {
    c2.clearRect(0, 0, 1, 1);
    c2.fillStyle = '#000';
    c2.fillStyle = col;
    c2.fillRect(0, 0, 1, 1);
    return Array.from(c2.getImageData(0, 0, 1, 1).data);
  };
  const lum = (p) => {
    const ch = p.slice(0, 3).map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  // The offset ring paints on the first ancestor with an opaque background.
  let surface = [0, 0, 0, 255], surfaceOf = '';
  for (let a = el.parentElement; a; a = a.parentElement) {
    const bg = rgba(getComputedStyle(a).backgroundColor);
    if (bg[3] === 255) { surface = bg; surfaceOf = a.id || String(a.className); break; }
  }
  const ring = rgba(getComputedStyle(el).outlineColor);
  const la = lum(ring), lb = lum(surface);
  return { ratio: (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05),
           ring, surface, surfaceOf };
}
"""


def _rest(page, loc):
    page.mouse.move(0, 0)
    page.wait_for_function("() => !document.querySelector('.history-match-row:hover')")
    return loc.evaluate(_PAINT_JS)


def test_hover_keeps_a_result_rows_rail_tint_and_padding(mock_server, pw_browser):
    ctx, page, errors, sel, n = _open(pw_browser, mock_server, "history")
    try:
        rows = page.locator(sel)
        assert rows.count() == n
        seen, bad = [], []
        for i in range(n):
            loc = rows.nth(i)
            before = _rest(page, loc)
            loc.hover()
            after = loc.evaluate(_PAINT_JS)
            seen.append(before["result"])
            keep = ("bg", "rail", "railW", "pad")
            if any(before[k] != after[k] for k in keep):
                bad.append((i, before, after))
            elif before["top"] == after["top"]:
                bad.append((i, "hover changed nothing", before, after))
        assert "win" in seen and "loss" in seen, seen
        assert not bad, f"hover repainted a result row: {bad}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_hover_on_a_neutral_row_does_not_shift_its_padding(mock_server, pw_browser):
    ctx, page, errors, sel, n = _open(pw_browser, mock_server, "session")
    try:
        rows = page.locator(sel)
        info = page.evaluate(_TOKEN_JS, "--info")
        bad = []
        for i in range(n):
            loc = rows.nth(i)
            before = _rest(page, loc)
            assert before["result"] not in ("win", "loss"), before
            loc.hover()
            after = loc.evaluate(_PAINT_JS)
            if after["pad"] != before["pad"] or after["rail"] != info:
                bad.append((i, before, after))
        assert not bad, f"neutral hover: {bad}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_deep_link_glow_keeps_a_result_rows_rail_and_draws_a_ring(
    mock_server, pw_browser
):
    ctx, page, errors, sel, n = _open(pw_browser, mock_server, "history")
    try:
        rows = page.locator(sel)
        info = page.evaluate(_TOKEN_JS, "--info")
        seen, bad = [], []
        for i in range(n):
            loc = rows.nth(i)
            before = _rest(page, loc)
            loc.evaluate("(el) => el.classList.add('is-focused')")
            after = loc.evaluate(_PAINT_JS)
            pair = loc.evaluate(_RING_CONTRAST_JS)
            loc.evaluate("(el) => el.classList.remove('is-focused')")
            seen.append(before["result"])
            if any(before[k] != after[k] for k in ("bg", "rail", "railW", "pad")):
                bad.append((i, "repainted", before, after))
            if not (after["oStyle"] == "solid" and after["oWidth"] >= 2
                    and after["oColor"] == info):
                bad.append((i, "no --info ring", after))
            elif pair["ratio"] < 3.0:
                bad.append((i, "ring below 3:1", pair))
        assert "win" in seen and "loss" in seen, seen
        assert not bad, f"deep-link glow: {bad}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_deep_link_glow_on_a_neutral_row_keeps_the_info_tint(
    mock_server, pw_browser
):
    ctx, page, errors, sel, n = _open(pw_browser, mock_server, "session")
    try:
        loc = page.locator(sel).first
        info = page.evaluate(_TOKEN_JS, "--info")
        info_soft = page.evaluate(
            "() => { const d = document.createElement('div');"
            " d.style.background = 'var(--info-soft)';"
            " document.body.appendChild(d);"
            " const c = getComputedStyle(d).backgroundColor;"
            " d.remove(); return c; }"
        )
        before = _rest(page, loc)
        loc.evaluate("(el) => el.classList.add('is-focused')")
        after = loc.evaluate(_PAINT_JS)
        assert after["bg"] == info_soft, (before, after)
        assert after["rail"] == info, (before, after)
        assert after["pad"] == before["pad"], (before, after)
        assert after["oStyle"] == "solid" and after["oColor"] == info, after
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_deep_link_ring_holds_in_every_theme(mock_server, pw_browser):
    """The --info deep-link ring is >= 3:1 on the surface it paints on
    (PAIR: resolved --info vs the first opaque ancestor) in every
    :root[data-theme] block, and a win / loss row keeps its rail there."""
    themes = _themes()
    assert len(themes) >= 5, f"theme scan anchor: {themes}"
    ctx, page, errors, sel, n = _open(pw_browser, mock_server, "history")
    failures, rings, seen = [], set(), 0
    try:
        rows = page.locator(sel)
        for t in themes:
            page.evaluate(
                "(t) => document.documentElement.setAttribute('data-theme', t)",
                t,
            )
            for i in range(n):
                loc = rows.nth(i)
                before = _rest(page, loc)
                loc.evaluate("(el) => el.classList.add('is-focused')")
                after = loc.evaluate(_PAINT_JS)
                pair = loc.evaluate(_RING_CONTRAST_JS)
                loc.evaluate("(el) => el.classList.remove('is-focused')")
                seen += 1
                rings.add(tuple(pair["ring"]))
                if before["rail"] != after["rail"] or pair["ratio"] < 3.0:
                    failures.append((t, i, before["result"], pair))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    assert seen == len(themes) * n, seen
    assert len(rings) >= 3, f"theme flip inert: {rings}"
    assert not failures, f"deep-link ring theme failures: {failures[:4]}"
