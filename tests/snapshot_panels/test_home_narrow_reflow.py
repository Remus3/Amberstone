"""
tests/snapshot_panels/test_home_narrow_reflow.py
RM-1431 (s144 uiux) - the Home view reflows inside its own panel at narrow
widths and zoom (WCAG 1.4.10 reflow, 320 CSS px wide).

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#home before the
fix, picker closed. The document ran 22 px sideways at 640x307 (300% zoom of
the 1920x920 baseline), 182 px at 480x230 (400%) and 342 px at 320x256: its
scrollWidth was 662 at all three. Inside #home-overlay the RECENT cards and
the THIS WEEK rows kept their fixed desktop columns (6px 44px 1fr 200px
116px 44px and 100px+ 72px 150px 150px 44px), so .home-body could not shrink
below 613 px; at 320 the launcher rail (3 columns) needed 426 px of 222, and
the hero's two columns squeezed the greeting and the Find Match column to
13 px wide while their content ran across the stat chips.

THE FIX (web/css/panels/home.css, one @media (max-width: 720px) block, below
the 1200px companion block, so 1920x920 and 923x1280 are untouched): the
overlay's side margin / padding step down, the hero stacks to one column, a
RECENT card folds to two rows (portrait | name | grade, then items | KDA), a
THIS WEEK row wraps its cells, and the launcher tiles auto-fit 3 / 2 / 1
across. A second block under 440px gives the KDA its own row: the 5-phase
audit measured the champion name at 66 px beside a 90 px KDA at 320.

What is checked, at 768x368, 640x307, 480x230 and 320x256:
- no Home element with visible overflow is wider inside than its own box
  (scrollWidth vs clientWidth), the overlay included, so nothing runs out of
  its card or out of the view;
- every RECENT card shows its portrait, items, KDA and grade whole inside the
  card (the card clips, so an overflow there would hide them, not scroll),
  no two of them overlap, and the champion name is never narrower than the
  KDA;
- the launcher tiles keep the 44 px floor.
The document itself has no sideways scroll at 768 and 640; at 480 and 320 the
shared header / footer chrome still runs wider (filed separately, RM-1432),
so there the check is the view's own panel. At 1920x920 and 923x1280 the
authored layout is pinned by its computed values.
"""
import sys

import pytest

from tests.snapshot_panels.test_home_find_match_picker_focus import _open_home

_PROBE = """
() => {
  const de = document.documentElement;
  const ov = document.getElementById('home-overlay');
  const r0 = ov.getBoundingClientRect();
  const wide = [];
  for (const el of [ov, ...ov.querySelectorAll('*')]) {
    if (!el.getClientRects().length) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'inline' || cs.overflowX !== 'visible') continue;
    if (el instanceof SVGElement) continue;
    if (el.scrollWidth > el.clientWidth + 1) {
      wide.push({tag: el.tagName, id: el.id, cls: String(el.className).slice(0, 48),
                 sw: el.scrollWidth, cw: el.clientWidth});
    }
  }
  const cut = [];
  for (const card of ov.querySelectorAll('.home-recent-card')) {
    const c = card.getBoundingClientRect();
    const parts = card.querySelectorAll(
      '.home-recent-img, .home-recent-main, .home-recent-item-slot:not(.empty),'
      + ' .home-recent-kda, .home-recent-grade-badge');
    for (const p of parts) {
      const b = p.getBoundingClientRect();
      if (b.left < c.left - 0.5 || b.right > c.right + 0.5
          || b.top < c.top - 0.5 || b.bottom > c.bottom + 0.5) {
        cut.push({cls: String(p.className).slice(0, 40), l: b.left, r: b.right,
                  t: b.top, b: b.bottom, card: [c.left, c.right, c.top, c.bottom]});
      }
    }
  }
  // Hierarchy: in each RECENT card the champion name column is never
  // narrower than the KDA pill beside or under it.
  const champVsKda = Array.from(ov.querySelectorAll('.home-recent-card')).map((card) => [
    Math.round(card.querySelector('.home-recent-champ').getBoundingClientRect().width),
    Math.round(card.querySelector('.home-recent-kda').getBoundingClientRect().width)]);
  const overlap = [];
  for (const card of ov.querySelectorAll('.home-recent-card')) {
    const kids = Array.from(card.children).filter((k) => k.getClientRects().length
      && !k.classList.contains('home-recent-stripe'));
    for (let i = 0; i < kids.length; i++) {
      for (let j = i + 1; j < kids.length; j++) {
        const a = kids[i].getBoundingClientRect(), b = kids[j].getBoundingClientRect();
        if (a.width && b.width && a.left < b.right - 0.5 && b.left < a.right - 0.5
            && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5) {
          overlap.push([String(kids[i].className), String(kids[j].className)]);
        }
      }
    }
  }
  const tiles = Array.from(ov.querySelectorAll('.home-action-tile'))
    .filter((t) => t.getClientRects().length)
    .map((t) => Math.round(t.getBoundingClientRect().height));
  return {vw: de.clientWidth, docOverflow: de.scrollWidth - de.clientWidth,
          ov: {left: r0.left, right: r0.right}, wide, cut, tiles, champVsKda, overlap,
          nCards: ov.querySelectorAll('.home-recent-card').length,
          nWeek: ov.querySelectorAll('.home-week-bar-row').length};
}
"""

_NARROW = [(768, 368), (640, 307), (480, 230), (320, 256)]
# Widths where the shared header / footer already fit, so the whole document
# must not scroll sideways once Home folds.
_DOC_CLEAN = {768, 640}


def _settle(page):
    page.wait_for_function(
        "() => document.querySelectorAll('#home-overlay .home-recent-card').length > 0"
        " && document.querySelectorAll('#home-overlay .home-week-bar-row').length > 0",
        timeout=10_000)


@pytest.mark.parametrize("vp", _NARROW, ids=lambda v: f"{v[0]}x{v[1]}")
def test_home_fits_inside_its_own_panel(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _settle(page)
        st = page.evaluate(_PROBE)
        assert st["nCards"] == 3 and st["nWeek"] == 3, f"anchor: fixture rows: {st}"
        assert st["ov"]["right"] <= st["vw"] + 0.5, (
            f"{vp}: the Home panel runs past the window: {st['ov']} vw {st['vw']}")
        assert not st["wide"], (
            f"{vp}: {len(st['wide'])} Home boxes are wider inside than their own"
            f" box: {st['wide'][:6]}")
        assert not st["cut"], (
            f"{vp}: a RECENT card clips its own content: {st['cut'][:4]}")
        assert not st["overlap"], (
            f"{vp}: parts of a RECENT card overlap: {st['overlap'][:4]}")
        small = [p for p in st["champVsKda"] if p[0] < p[1]]
        assert not small, (
            f"{vp}: the champion name is narrower than the KDA (name, kda): {small}")
        assert st["tiles"] and min(st["tiles"]) >= 44, (
            f"{vp}: a launcher tile fell under the 44 px floor: {st['tiles']}")
        if vp[0] in _DOC_CLEAN:
            assert st["docOverflow"] <= 0, (
                f"{vp}: the document scrolls sideways by {st['docOverflow']} px")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_AUTHORED_JS = """
() => {
  const q = (s) => document.querySelector(s);
  const cs = (s) => getComputedStyle(q(s));
  const ov = cs('#home-overlay');
  // Track lists rounded to whole px, so sub-pixel font metrics cannot flake.
  const cols = (s) => cs(s).gridTemplateColumns.split(' ')
    .map((v) => Math.round(parseFloat(v))).join(' ');
  return {
    ovMargin: [ov.marginLeft, ov.marginRight], ovPad: [ov.paddingLeft, ov.paddingRight],
    hero: cols('.home-hero'),
    body: cols('.home-body'),
    recent: cols('.home-recent-card'),
    week: cols('.home-week-bar-row'),
    weekDisplay: cs('.home-week-bar-row').display,
    actions: cols('.home-actions'),
    cardH: Math.round(q('.home-recent-card').getBoundingClientRect().height),
    weekH: Math.round(q('.home-week-bar-row').getBoundingClientRect().height),
  };
}
"""

# Computed at HEAD before the fix (RM-1431); the narrow block must not
# reach these sizes.
_AUTHORED = {
    (1920, 920): {
        "ovMargin": ["24px", "24px"], "ovPad": ["24px", "24px"],
        "hero": "526 1052 155", "body": "1114 696",
        "recent": "6 44 600 200 116 44", "week": "183 72 150 150 44",
        "weekDisplay": "grid", "actions": "297 297 297 297 297 297",
        "cardH": 63, "weekH": 39,
    },
    (923, 1280): {
        "ovMargin": ["24px", "24px"], "ovPad": ["24px", "24px"],
        "hero": "616 155", "body": "825",
        "recent": "6 44 311 200 116 44", "week": "312 72 150 150 44",
        "weekDisplay": "grid", "actions": "270 270 270",
        "cardH": 63, "weekH": 39,
    },
}


def _comparable(st: dict) -> dict:
    """RM-1657: the hero row follows its text's height, so the fallback font decides
    it: the Linux CI runner read "525 1050 157" and "614 157" where Windows read
    "526 1052 155" and "616 155" (run 42003344193). Only Windows pins that field;
    every other value is the same on both."""
    if sys.platform == "win32":
        return st
    return {k: v for k, v in st.items() if k != "hero"}


@pytest.mark.parametrize("vp", list(_AUTHORED), ids=lambda v: f"{v[0]}x{v[1]}")
def test_the_authored_layout_is_unchanged(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _settle(page)
        st = page.evaluate(_AUTHORED_JS)
        assert _comparable(st) == _comparable(_AUTHORED[vp]), (
            f"{vp}: the authored Home layout moved: {st}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
