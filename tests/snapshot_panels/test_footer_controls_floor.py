"""
tests/snapshot_panels/test_footer_controls_floor.py
RM-1009 (s144 uiux): the dashboard footer bar keeps its height on every
view, its text sits on the --fs-xs floor, and its buttons are clickable over
a full --hit-min band with a visible focus ring.

Measured before this slice (headless Chromium, ?ui_mock=1):
- `footer` (web/css/panels/input_activity.css) set `height: 36px` but no
  `flex-shrink: 0`, unlike `header`. In the body flex column it SHRANK on
  the tall views: 20px on #settings and #session, 31px on #champ-select,
  so the bar's height depended on which view was open.
- Every footer control rendered at 12px (`footer .footer-btn`,
  `footer .voice-picker`, `footer .mode-pill` in web/css/panels/header.css)
  and the bar text at 15px, below `--fs-xs` (16px), which
  docs/UI_SCALE_SPEC_V2.md names as the footer's tier.
- #voice-toggle, the only visible footer button, was a 20px-tall target
  under the 42px `--hit-min`, and no footer rule declared a
  `:focus-visible` style.

The 2026-04-29 operator ask that footer buttons not stand taller than the
footer pills is kept: the button's visible chip stays compact and its hit
band is widened to --hit-min by a transparent pseudo-element, so the click
target is asserted with elementFromPoint, not with the chip's box.

Every value is read COMPUTED in real headless Chromium; --hit-min, --fs-xs
and --accent resolve through the live cascade, never hard-coded here.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

# 1920x920 = the design baseline viewport with Chrome chrome (CLAUDE.md);
# 923x1280 = the companion width the lobby / reflow tests also use.
VIEWPORTS = [(1920, 920), (923, 1280)]
# home fits its viewport; settings and session are the tall scrolling views
# the footer used to shrink on.
VIEWS = ["home", "settings", "session"]


def _open(pw_browser, mock_server, view, width, height):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1#" + view,
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    # the router writes body[data-view] once the hash view wins.
    page.wait_for_function(
        f"document.body.dataset.view === {view!r}", timeout=10_000
    )
    page.wait_for_selector("footer #voice-toggle", timeout=10_000)
    # let the view's mock fetch land so its content height is final.
    page.wait_for_timeout(1500)
    return ctx, page, errors


_TOKENS = """
() => {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute;visibility:hidden;'
    + 'height:var(--hit-min);font-size:var(--fs-xs);color:var(--accent)';
  document.body.appendChild(probe);
  const cs = getComputedStyle(probe);
  const t = {hit: parseFloat(cs.height), fsXs: parseFloat(cs.fontSize),
             accent: cs.color};
  probe.remove();
  return t;
}
"""

_MEASURE = """
() => {
  const f = document.querySelector('footer');
  const fr = f.getBoundingClientRect();
  // Show the voice picker the way the toggle does when voice is on, so its
  // box is measured too (it is display:none while voice is off).
  const picker = document.getElementById('voice-picker');
  if (picker) picker.style.display = '';
  const texts = [];
  const walker = document.createTreeWalker(f, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!n.textContent.trim() || !el) continue;
    const r = el.getBoundingClientRect();
    if (getComputedStyle(el).display === 'none' || r.width === 0) continue;
    texts.push({id: el.id, cls: String(el.className), txt: n.textContent.trim().slice(0, 24),
                fs: parseFloat(getComputedStyle(el).fontSize)});
  }
  const ctrls = [];
  for (const el of f.querySelectorAll('button, select')) {
    const r = el.getBoundingClientRect();
    if (getComputedStyle(el).display === 'none' || r.width === 0) continue;
    const cx = r.left + r.width / 2;
    const hitAt = y => {
      const hit = document.elementFromPoint(cx, y);
      return !!(hit && (hit === el || el.contains(hit)));
    };
    ctrls.push({id: el.id, tag: el.tagName, w: r.width, h: r.height,
                fs: parseFloat(getComputedStyle(el).fontSize),
                inBar: r.top >= fr.top - 0.5 && r.bottom <= fr.bottom + 0.5,
                hitTop: hitAt(fr.top + 1), hitBottom: hitAt(fr.bottom - 1)});
  }
  if (picker) picker.style.display = 'none';
  return {
    footerH: fr.height, footerBottom: fr.bottom,
    vh: document.documentElement.clientHeight,
    overflowX: f.scrollWidth - f.clientWidth,
    texts, ctrls,
  };
}
"""


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize("view", VIEWS)
def test_footer_keeps_hit_min_height_on_every_view(
    mock_server, pw_browser, view, width, height
):
    ctx, page, errors = _open(pw_browser, mock_server, view, width, height)
    try:
        tok = page.evaluate(_TOKENS)
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert tok["hit"] >= 42, f"--hit-min resolved to {tok['hit']}px"
    assert m["footerH"] >= tok["hit"] - 0.5, (
        f"#{view} at {width}x{height}: footer is {m['footerH']}px tall, "
        f"under --hit-min {tok['hit']}px (it shrinks when not flex-shrink:0)"
    )
    assert abs(m["footerBottom"] - m["vh"]) <= 0.5, (
        f"#{view}: footer bottom {m['footerBottom']} is off the viewport "
        f"bottom {m['vh']}"
    )
    assert m["overflowX"] <= 0, f"#{view}: footer overflows by {m['overflowX']}px"
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_footer_text_and_controls_meet_floors(mock_server, pw_browser, width, height):
    ctx, page, errors = _open(pw_browser, mock_server, "home", width, height)
    try:
        tok = page.evaluate(_TOKENS)
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert tok["fsXs"] >= 16, f"--fs-xs resolved to {tok['fsXs']}px"
    ids = {t["id"] for t in m["texts"]}
    # the bar label, the voice toggle and the mode pill all render text.
    assert {"voice-toggle", "mode-pill", "ws-url"} <= ids, sorted(ids)
    for t in m["texts"]:
        assert t["fs"] >= tok["fsXs"], (
            f"footer text {t['txt']!r} (#{t['id']} .{t['cls']}) is "
            f"{t['fs']}px < --fs-xs {tok['fsXs']}px"
        )
    by_id = {c["id"]: c for c in m["ctrls"]}
    assert {"voice-toggle", "voice-picker"} <= set(by_id), sorted(by_id)
    for c in m["ctrls"]:
        assert c["inBar"], f"#{c['id']} spills out of the footer bar"
        assert c["fs"] >= tok["fsXs"], f"#{c['id']} font {c['fs']}px < --fs-xs"
        assert c["w"] >= tok["hit"] - 0.5, f"#{c['id']} {c['w']}px wide < --hit-min"
        # the click target spans the whole bar height (>= --hit-min, pinned
        # by the test above): a click at the bar's top and bottom edge lands
        # on the control.
        assert c["hitTop"] and c["hitBottom"], (
            f"#{c['id']} ({c['h']}px chip) is not clickable across the full "
            f"footer band: top={c['hitTop']} bottom={c['hitBottom']}"
        )
    assert not errors, f"JS errors: {errors[:3]}"


def test_footer_button_shows_accent_focus_ring(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, "home", 1920, 920)
    try:
        tok = page.evaluate(_TOKENS)
        # A keyboard press first so programmatic focus is keyboard-modality
        # and :focus-visible matches.
        page.keyboard.press("Shift")
        ring = page.evaluate(
            """() => {
              const b = document.getElementById('voice-toggle');
              b.focus();
              const cs = getComputedStyle(b);
              const out = {focused: document.activeElement === b,
                           visible: b.matches(':focus-visible'),
                           style: cs.outlineStyle,
                           width: parseFloat(cs.outlineWidth),
                           color: cs.outlineColor};
              b.blur();
              return out;
            }"""
        )
    finally:
        page.close()
        ctx.close()
    assert ring["focused"] and ring["visible"], ring
    assert ring["style"] == "solid", f"focus outline style {ring['style']!r}"
    assert ring["width"] >= 2, f"focus outline {ring['width']}px"
    assert ring["color"] == tok["accent"], (
        f"focus ring {ring['color']} is not --accent {tok['accent']}"
    )
    assert not errors, f"JS errors: {errors[:3]}"


# RM-1547: the voice picker is the footer's one other keyboard stop. It
# carried its own `.voice-picker:focus` rule (web/css/panels/header.css): a
# 1px --info outline at offset 1px, unlike the 2px --accent :focus-visible
# convention every other footer control uses. Its box is --hit-min tall in a
# --hit-min footer that sits on the viewport bottom, so an outline drawn
# OUTSIDE the box loses its bottom edge off-screen: the ring has to sit inside
# the box to show all four sides.
_PICKER_RING = """
() => {
  const p = document.getElementById('voice-picker');
  p.style.display = '';
  p.focus();
  const cs = getComputedStyle(p);
  const r = p.getBoundingClientRect();
  const fr = document.querySelector('footer').getBoundingClientRect();
  const w = parseFloat(cs.outlineWidth);
  const off = parseFloat(cs.outlineOffset);
  // the outline's outer edge sits (offset + width) beyond the border box.
  const reach = off + w;
  const out = {focused: document.activeElement === p,
               visible: p.matches(':focus-visible'),
               style: cs.outlineStyle, width: w, offset: off,
               color: cs.outlineColor,
               ringTop: r.top - reach, ringBottom: r.bottom + reach,
               ringLeft: r.left - reach, ringRight: r.right + reach,
               footTop: fr.top, footBottom: fr.bottom,
               vw: document.documentElement.clientWidth,
               vh: document.documentElement.clientHeight};
  p.blur();
  p.style.display = 'none';
  return out;
}
"""


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_voice_picker_shows_whole_accent_focus_ring(
    mock_server, pw_browser, width, height
):
    ctx, page, errors = _open(pw_browser, mock_server, "home", width, height)
    try:
        tok = page.evaluate(_TOKENS)
        page.keyboard.press("Shift")
        ring = page.evaluate(_PICKER_RING)
    finally:
        page.close()
        ctx.close()
    assert ring["focused"] and ring["visible"], ring
    assert ring["style"] == "solid", f"picker focus outline style {ring['style']!r}"
    assert ring["width"] >= 2, f"picker focus outline {ring['width']}px"
    assert ring["color"] == tok["accent"], (
        f"picker focus ring {ring['color']} is not --accent {tok['accent']}"
    )
    # all four sides of the ring are painted inside the footer bar and the
    # viewport, so none of it is cut off at the window bottom.
    assert ring["ringTop"] >= ring["footTop"] - 0.5, ring
    assert ring["ringBottom"] <= ring["footBottom"] + 0.5, ring
    assert ring["ringBottom"] <= ring["vh"] + 0.5, ring
    assert ring["ringLeft"] >= -0.5 and ring["ringRight"] <= ring["vw"] + 0.5, ring
    assert not errors, f"JS errors: {errors[:3]}"
