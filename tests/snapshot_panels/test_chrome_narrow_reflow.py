"""
tests/snapshot_panels/test_chrome_narrow_reflow.py
RM-1432 (s144 uiux) - the shared page header and footer fit a narrow
window (WCAG 1.4.10 reflow, 320 CSS px wide; 300% zoom of the 1920x920
baseline is 640 wide, 400% is 480).

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#home before the
fix. The header and footer are chrome on every view, and at 480x230 and
320x256 they ran the document 48 / 208 px sideways:
- the view trigger (#view-trigger) is 403 px wide at every width, because
  its current-view label (.title-current) is pinned to 230 px so the trigger
  never changes size between views (s218). At 320 the header row is 288 px,
  so the trigger ran 131 px past it and its caret sat outside the window;
- the footer holds ONE row (RM-1013, nowrap) with 22 px side padding and
  18 px gaps, and nothing in it could give way but the build stamp: the
  "RC | <ws url>" label kept its full 250 px, so at 480 the CLIENT mode pill
  and the health dot ran past the right edge (footer scrollWidth 528), and at
  320 the VOICE toggle did too.

THE FIX.
- web/css/panels/header.css, @media (max-width: 720px): the trigger may
  shrink to its row (flex 0 1 auto, min-width 0) and only the current-view
  label gives way (it keeps width 230px, with min-width 0 and an ellipsis).
  The shrink is content-blind (the trigger's own size stays 403 px), so
  within one window size the trigger is still the same width on every
  view; where it fits its row nothing moves.
- web/css/panels/input_activity.css: the footer connection label
  (.footer-conn, web/index.html) gives way like the stamp (block, min-width
  0, ellipsis, at a lower shrink weight than the stamp so the stamp still
  goes first); the voice picker may shrink; and under 720 px the footer
  side padding steps 22 -> 12 px and the gap 18 -> 10 px. web/js/main.js
  copies "RC | <ws url>" into the label's title, so a cut label keeps its
  whole text on hover.

What is checked, on Home and on the SR Active Match view (the header row
with every in-game pill), at 768x368, 640x307, 480x230 and 320x256:
- the document has no sideways scroll;
- every rendered header and footer element lies whole inside the window;
- the footer stays one --hit-min row, every footer item on that row;
- the trigger keeps the 42 px floor, and its brand label and caret stay
  whole inside it;
- a cut connection label carries its whole text in its title.
The same with the voice picker shown (voice on, a long voice name): at HEAD
it ran the document 90 / 250 / 410 px sideways at 640 / 480 / 320
(768 fit). At 1920x920 and
923x1280 the authored chrome is pinned by its computed values.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import _new_page

_VIEWS = {
    "home": "/?ui_mock=1#home",
    "active-match": "/?ui_mock=1&mode=sr#active-match",
}
_NARROW = [(768, 368), (640, 307), (480, 230), (320, 256)]

_PROBE = """
() => {
  const de = document.documentElement;
  const vw = de.clientWidth;
  const out = [];
  const seen = (el) => el.getClientRects().length > 0;
  for (const root of [document.querySelector('header'), document.querySelector('footer')]) {
    for (const el of [root, ...root.querySelectorAll('*')]) {
      if (!seen(el) || el instanceof SVGElement && el.tagName !== 'svg') continue;
      const b = el.getBoundingClientRect();
      if (!b.width && !b.height) continue;
      if (b.left < -0.5 || b.right > vw + 0.5) {
        out.push({tag: el.tagName, id: el.id, cls: String(el.className).slice(0, 40),
                  l: Math.round(b.left), r: Math.round(b.right)});
      }
    }
  }
  const ft = document.querySelector('footer');
  const fr = ft.getBoundingClientRect();
  const foot = Array.from(ft.children).filter((k) => seen(k)
    && !k.classList.contains('spacer')).map((k) => {
      const b = k.getBoundingClientRect();
      return {id: k.id || String(k.className).slice(0, 30), t: b.top, b: b.bottom,
              w: Math.round(b.width)};
    });
  const off = foot.filter((k) => k.t < fr.top - 0.5 || k.b > fr.bottom + 0.5);
  const tr = document.getElementById('view-trigger');
  const t = tr.getBoundingClientRect();
  const inside = (sel) => {
    const b = tr.querySelector(sel).getBoundingClientRect();
    return b.left >= t.left - 0.5 && b.right <= t.right + 0.5;
  };
  const conn = ft.querySelector('.footer-conn');
  return {
    vw, docOverflow: de.scrollWidth - vw, out, off,
    footH: Math.round(fr.height), footSW: ft.scrollWidth, footCW: ft.clientWidth,
    hitMin: Math.round(parseFloat(getComputedStyle(de).getPropertyValue('--hit-min'))),
    trigger: {w: Math.round(t.width), h: Math.round(t.height),
              label: inside('.title-label'), caret: inside('.title-caret')},
    conn: conn ? {cut: conn.scrollWidth > conn.clientWidth + 1, title: conn.title,
                  text: conn.textContent.trim()} : null,
    picker: (() => { const p = document.getElementById('voice-picker');
                     return seen(p) ? Math.round(p.getBoundingClientRect().width) : 0; })(),
  };
}
"""

_SHOW_PICKER = """
() => {
  const p = document.getElementById('voice-picker');
  p.innerHTML = '';
  const o = document.createElement('option');
  o.value = 'v';
  o.textContent = 'Microsoft Zira - English (United States) - en-US';
  p.appendChild(o);
  p.style.display = '';
}
"""


def _open(pw_browser, mock_server, vp, view):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + _VIEWS[view], wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_selector("#view-trigger", state="visible", timeout=10_000)
    page.wait_for_function(
        "() => document.getElementById('view-current-label').textContent.trim()"
        " && document.getElementById('ws-url').textContent.trim() !== '-'",
        timeout=10_000)
    page.wait_for_timeout(300)
    return ctx, page, errors


def _check(st, label):
    assert st["docOverflow"] <= 0, (
        f"{label}: the document scrolls sideways by {st['docOverflow']} px")
    assert not st["out"], (
        f"{label}: {len(st['out'])} header / footer elements run past the"
        f" window ({st['vw']} px): {st['out'][:6]}")
    assert st["footSW"] <= st["footCW"] + 1, (
        f"{label}: the footer is wider inside than itself: {st['footSW']}"
        f" > {st['footCW']}")
    assert st["footH"] == st["hitMin"], (
        f"{label}: the footer is not one {st['hitMin']} px row: {st['footH']}")
    assert not st["off"], f"{label}: a footer item left the footer row: {st['off']}"
    tr = st["trigger"]
    assert tr["h"] >= 42 and tr["label"] and tr["caret"], (
        f"{label}: the view trigger lost its floor or cut its brand / caret: {tr}")
    conn = st["conn"]
    assert conn is not None, f"{label}: no footer connection label"
    if conn["cut"]:
        assert conn["title"] == conn["text"] and "ws" in conn["title"], (
            f"{label}: the cut connection label has no whole-text title: {conn}")


@pytest.mark.parametrize("view", list(_VIEWS))
@pytest.mark.parametrize("vp", _NARROW, ids=lambda v: f"{v[0]}x{v[1]}")
def test_chrome_fits_a_narrow_window(mock_server, pw_browser, vp, view):
    ctx, page, errors = _open(pw_browser, mock_server, vp, view)
    try:
        _check(page.evaluate(_PROBE), f"{view} {vp}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", _NARROW, ids=lambda v: f"{v[0]}x{v[1]}")
def test_footer_fits_with_the_voice_picker_shown(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, vp, "home")
    try:
        page.evaluate(_SHOW_PICKER)
        st = page.evaluate(_PROBE)
        assert st["picker"] > 0, f"anchor: the voice picker is not shown: {st}"
        _check(st, f"voice on {vp}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", _NARROW, ids=lambda v: f"{v[0]}x{v[1]}")
def test_trigger_is_one_width_on_every_view(mock_server, pw_browser, vp):
    # s218 static rule: at one window size the trigger does not change width
    # between views, whatever its current-view label says. A first cut of
    # this fix sized the label from its text and broke this (274 px on Home
    # vs 342 px on Active Match at 640).
    widths = {}
    for view in _VIEWS:
        ctx, page, errors = _open(pw_browser, mock_server, vp, view)
        try:
            widths[view] = page.evaluate(
                "() => [document.getElementById('view-current-label').textContent,"
                " document.getElementById('view-trigger').getBoundingClientRect().width]")
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    labels = {w[0] for w in widths.values()}
    assert len(labels) == len(_VIEWS), f"anchor: the views share a label: {widths}"
    sizes = {round(w[1], 1) for w in widths.values()}
    assert len(sizes) == 1, f"{vp}: the trigger changes width between views: {widths}"


_AUTHORED_JS = """
() => {
  const cs = (s) => getComputedStyle(document.querySelector(s));
  const w = (s) => Math.round(document.querySelector(s).getBoundingClientRect().width);
  const f = cs('footer');
  return {
    trigger: w('#view-trigger'), current: w('#view-current-label'),
    footPad: [f.paddingLeft, f.paddingRight], footGap: f.columnGap,
    footH: Math.round(document.querySelector('footer').getBoundingClientRect().height),
    connCut: (() => { const c = document.querySelector('footer .footer-conn');
                      return c.scrollWidth > c.clientWidth + 1; })(),
  };
}
"""

# Trigger, label and footer values computed at HEAD before the fix
# (RM-1432); connCut is new with .footer-conn. The narrow rules must not
# reach these sizes.
_AUTHORED = {
    (1920, 920): {"trigger": 403, "current": 230, "footPad": ["22px", "22px"],
                  "footGap": "18px", "footH": 42, "connCut": False},
    (923, 1280): {"trigger": 403, "current": 230, "footPad": ["22px", "22px"],
                  "footGap": "18px", "footH": 42, "connCut": False},
}


@pytest.mark.parametrize("view", list(_VIEWS))
@pytest.mark.parametrize("vp", list(_AUTHORED), ids=lambda v: f"{v[0]}x{v[1]}")
def test_the_authored_chrome_is_unchanged(mock_server, pw_browser, vp, view):
    ctx, page, errors = _open(pw_browser, mock_server, vp, view)
    try:
        st = page.evaluate(_AUTHORED_JS)
        assert st == _AUTHORED[vp], f"{view} {vp}: the authored chrome moved: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
