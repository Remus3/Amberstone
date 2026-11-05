"""
tests/snapshot_panels/test_view_label_text_floor.py
RM-1553 (s144 uiux) - the header's current-view label and the trigger's
caret read at the 16 px text floor.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1&mode=sr at
1920x920 before the fix: the label (#view-current-label, .title-current,
web/css/panels/header.css) computed font-size 13px and the caret
(.title-caret) 14px, both under --fs-xs (16px, docs/UI_SCALE_SPEC_V2.md).
The label is on screen on every view: it is the one place the dashboard
names the view the operator is looking at. It was pinned to 230 px (s218:
the trigger keeps one width on every view) with overflow hidden and no
ellipsis, so the archive label "AUTO - POST GAME REVIEW (ARCHIVE)" (an F5
on #historical-pgr) scrolled 286 px in that box and was cut mid-word,
silently.

THE FIX (web/css/panels/header.css).
- .title-current: font-size var(--fs-xs), letter-spacing 0.08em (was
  0.16em), width 290px. 290 holds the widest manual label, "POST GAME
  REVIEW (ARCHIVE)", and every "AUTO - <VIEW>" label, in Segoe UI bold
  (the fallback when the Lato webfont is unreachable; Lato is no wider).
- The RM-1436 wrap (the whole AUTO prefix wraps away before the name is
  cut) moves from the max-width 720px block to the base rule, so the one
  label still wider than 290 px drops its prefix instead of its name.
- .title-caret: font-size var(--fs-xs).

What is checked, on every view the menu offers, at the 1920x920 baseline
and at 1280x720:
- the label and the caret compute at least 16 px;
- the trigger has one width on every view (s218) and keeps its 43 px height;
- the view name is never cut, and the prefix is shown whole or not at all;
- on #historical-pgr in auto mode the prefix gives way to the whole name;
- where the Segoe UI fallback is installed, every label set in it fits.
"""
import sys

import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import _new_page

_VIEWS = {
    "home": "HOME",
    "lobby": "PRE-GAME LOBBY",
    "champ-select": "CHAMP SELECT",
    "active-match": "ACTIVE MATCH",
    "last-match": "POST GAME REVIEW",
    "session": "SESSION",
    "history": "HISTORY",
    "historical-pgr": "POST GAME REVIEW (ARCHIVE)",
    "replay": "REPLAY",
    "user-builds": "USER BUILDS",
    "build-insights": "BUILD INSIGHTS",
    "settings": "SETTINGS",
}
_PREFIX = "AUTO " + chr(0xB7) + " "  # the middle dot, kept ASCII in source
_VPS = [(1920, 920), (1280, 720)]

_PROBE = """
() => {
  const l = document.getElementById('view-current-label');
  const L = l.getBoundingClientRect();
  const t = document.getElementById('view-trigger').getBoundingClientRect();
  const caret = document.querySelector('#view-trigger .title-caret');
  const nameEl = l.querySelector('.title-current-name');
  const autoEl = l.querySelector('.title-current-auto');
  const inside = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cy = (r.top + r.bottom) / 2;
    return r.width > 0 && r.left >= L.left - 0.5 && r.right <= L.right + 0.5
      && cy >= L.top && cy <= L.bottom;
  };
  return {
    text: l.textContent,
    labelFs: parseFloat(getComputedStyle(l).fontSize),
    caretFs: parseFloat(getComputedStyle(caret).fontSize),
    labelH: Math.round(L.height),
    triggerW: Math.round(t.width), triggerH: Math.round(t.height),
    nameWhole: !!nameEl && inside(nameEl)
      && nameEl.scrollWidth <= nameEl.clientWidth + 1,
    autoShown: autoEl ? inside(autoEl) : false,
    hasAuto: !!autoEl,
  };
}
"""

# Lays every label out in Segoe UI bold inside a clone of the real label
# (same class, so the same width, padding and tracking) and returns the ones
# whose name would be cut. null when Segoe UI is not installed (a family
# that is absent measures the same as the generic it falls back to).
_SEGOE = """
(labels) => {
  const probe = (fam) => {
    const s = document.createElement('span');
    s.style.cssText = 'position:absolute;visibility:hidden;font:700 40px ' + fam;
    s.textContent = 'POST GAME REVIEW (ARCHIVE) wmWM';
    document.body.appendChild(s);
    const w = s.getBoundingClientRect().width;
    s.remove();
    return w;
  };
  if (probe('"Segoe UI", monospace') === probe('monospace')
      && probe('"Segoe UI", serif') === probe('serif')) return null;
  const src = document.getElementById('view-current-label');
  const host = src.parentElement;
  const cut = [];
  for (const [pre, name] of labels) {
    const c = src.cloneNode(false);
    c.removeAttribute('id');
    c.style.fontFamily = '"Segoe UI"';
    c.style.visibility = 'hidden';
    const n = document.createElement('span');
    n.className = 'title-current-name';
    n.textContent = name;
    if (pre) {
      const a = document.createElement('span');
      a.className = 'title-current-auto';
      a.textContent = pre;
      c.append(a, n);
    } else {
      c.append(n);
    }
    host.appendChild(c);
    const C = c.getBoundingClientRect();
    const A = pre ? c.firstChild.getBoundingClientRect() : null;
    const aShown = A ? (A.top + A.bottom) / 2 <= C.bottom : false;
    if (n.scrollWidth > n.clientWidth + 1 || (pre && !aShown)) {
      cut.push([pre, name, n.scrollWidth, n.clientWidth, aShown]);
    }
    c.remove();
  }
  return cut;
}
"""


def _open(pw_browser, mock_server, vp, view):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(f"{mock_server.url}/?ui_mock=1&mode=sr#{view}",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector("#view-trigger", state="visible", timeout=10_000)
    page.wait_for_function(
        "(want) => document.getElementById('view-current-label').textContent"
        ".trim().endsWith(want)", arg=_VIEWS[view], timeout=10_000)
    page.wait_for_timeout(200)
    return ctx, page, errors


@pytest.mark.parametrize("vp", _VPS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_label_and_caret_read_at_the_floor_on_every_view(mock_server, pw_browser, vp):
    widths = {}
    for view, name in _VIEWS.items():
        ctx, page, errors = _open(pw_browser, mock_server, vp, view)
        try:
            st = page.evaluate(_PROBE)
        finally:
            page.close()
            ctx.close()
        label = f"{view} {vp}"
        assert not errors, f"{label}: JS errors: {errors[:3]}"
        assert st["text"] in (name, _PREFIX + name), f"anchor: {label}: {st}"
        assert st["labelFs"] >= 16, f"{label}: the view label is under 16px: {st}"
        assert st["caretFs"] >= 16, f"{label}: the caret is under 16px: {st}"
        assert st["nameWhole"], f"{label}: the view name is cut: {st}"
        if st["hasAuto"] and view != "historical-pgr":
            assert st["autoShown"], f"{label}: the AUTO prefix is not shown: {st}"
        assert st["labelH"] <= 20, f"{label}: the label is not one line: {st}"
        assert st["triggerH"] == 43, f"{label}: the trigger height moved: {st}"
        widths[view] = st["triggerW"]
    assert len(set(widths.values())) == 1, (
        f"{vp}: the trigger changes width between views: {widths}")


def test_archive_label_drops_the_prefix_not_the_name(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, (1920, 920), "historical-pgr")
    try:
        st = page.evaluate(_PROBE)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    assert st["text"] == _PREFIX + _VIEWS["historical-pgr"], f"anchor: {st}"
    assert st["nameWhole"], f"the archive view name is cut: {st}"
    assert st["hasAuto"] and not st["autoShown"], (
        f"the AUTO prefix should give way to the archive name: {st}")


@pytest.mark.skipif(sys.platform != "win32", reason="Segoe UI ships with Windows only")
def test_every_label_fits_in_the_segoe_ui_fallback(mock_server, pw_browser):
    labels = []
    for name in _VIEWS.values():
        labels.append(["", name])
        if name != _VIEWS["historical-pgr"]:
            labels.append([_PREFIX, name])
    ctx, page, errors = _open(pw_browser, mock_server, (1920, 920), "home")
    try:
        cut = page.evaluate(_SEGOE, labels)
    finally:
        page.close()
        ctx.close()
    assert cut is not None, "Segoe UI is missing on a Windows host"
    assert not errors, f"JS errors: {errors[:3]}"
    assert cut == [], f"labels cut in Segoe UI bold at the pinned width: {cut}"
