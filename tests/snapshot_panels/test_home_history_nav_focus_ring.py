"""
tests/snapshot_panels/test_home_history_nav_focus_ring.py
RM-1210 (s144 uiux) - the Home launcher tiles and the History scope tabs
draw a token focus ring.

THE DEFECT. The six .home-action-tile buttons (web/index.html: Post Game
Review / Session / History / Replay / Builds / Settings - the Home launcher,
the first thing a keyboard user tabs into) and the four History scope tabs
(.view-tab: 14 Days / Whole Season / Prior Season / Whole DB) carried no
:focus-visible rule (web/css/panels/home.css, web/css/panels/header.css),
so a keyboard-focused one fell back to the user-agent ring. MEASURED in
headless Chromium under /?ui_mock=1 before the fix (default theme arcane):
every one computed `outline-style: auto`, 1px, rgb(16,16,16), 1.08:1
against the surface the ring is painted on - effectively no ring. Found by
a focus-ring sweep over every visible focusable control on all eleven
views (the RM-1209 measurement generalised).

THE FIX. `outline: 2px solid var(--accent)`, the Lobby precedent
(.lq-btn, .lv-top8-tag). An OUTLINE, not the --focus-ring box-shadow: the
arcane theme draws the selected scope tab's cyan underline as an inset
box-shadow (themes.css `:root[data-theme="arcane"] .view-tab.active`, a
more specific selector), so a shadow ring would either lose to it or wipe
it. Offsets: 2px on the tiles (8px grid gap), 1px on the tabs (4px flex
gap), so neither ring reaches a neighbouring control.

WHAT IS MEASURED (headless Chromium, computed values, never a grep):
  - every rendered, enabled control, focused with keyboard modality,
    matches :focus-visible and computes a solid outline >= 2px whose
    colour is the resolved --accent (not the UA `auto` ring);
  - that ring colour against the nearest opaque ancestor background is
    >= 3:1, the WCAG 1.4.11 non-text floor, stating the PAIR;
  - no overflow-clipping ancestor cuts the ring, and the ring's reach
    (offset + width) stays inside the gap to the nearest sibling control;
  - the focused ACTIVE scope tab keeps the arcane cyan underline;
  - the ring holds in every :root[data-theme] block of themes.css.
"""
import re
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent

TILES = ".home-actions .home-action-tile"
TABS = "#view-history .view-section-tabs .view-tab"
N_TILES = 6
N_TABS = 4

_RING_JS = r"""
(sel) => {
  const cv = document.createElement('canvas');
  cv.width = 1; cv.height = 1;
  const c2 = cv.getContext('2d', { willReadFrequently: true });
  // Resolve any CSS colour syntax (oklch included) to sRGB bytes.
  const rgba = (col) => {
    c2.clearRect(0, 0, 1, 1);
    c2.fillStyle = '#000';
    c2.fillStyle = col;
    c2.fillRect(0, 0, 1, 1);
    const d = c2.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3]];
  };
  const lum = (p) => {
    const ch = p.slice(0, 3).map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  const ratio = (a, b) => {
    const la = lum(a), lb = lum(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  const accent = rgba(getComputedStyle(document.documentElement)
    .getPropertyValue('--accent').trim());
  const all = Array.from(document.querySelectorAll(sel)).filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width && r.height && !el.disabled;
  });
  const out = [];
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (document.activeElement && document.activeElement.blur) {
      document.activeElement.blur();
    }
    el.focus();
    const cs = getComputedStyle(el);
    const ring = rgba(cs.outlineColor);
    // The offset ring sits outside the border box: it is painted on the
    // first ancestor with an opaque background colour.
    let surface = null, surfaceOf = '';
    for (let a = el.parentElement; a; a = a.parentElement) {
      const bg = rgba(getComputedStyle(a).backgroundColor);
      if (bg[3] === 255) {
        surface = bg; surfaceOf = a.id || String(a.className); break;
      }
    }
    if (!surface) surface = [0, 0, 0, 255];
    const reach = parseFloat(cs.outlineOffset) + parseFloat(cs.outlineWidth);
    const clippedBy = [];
    for (let a = el.parentElement; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.overflowX === 'visible' && s.overflowY === 'visible') continue;
      const ar = a.getBoundingClientRect();
      if (r.left - reach < ar.left - 0.5 || r.right + reach > ar.right + 0.5
          || r.top - reach < ar.top - 0.5
          || r.bottom + reach > ar.bottom + 0.5) {
        clippedBy.push(a.id || String(a.className));
      }
    }
    // Smallest edge-to-edge gap to another matched control (rows or
    // columns), so the ring may not paint over a neighbour.
    let gap = Infinity;
    for (const o of all) {
      if (o === el) continue;
      const q = o.getBoundingClientRect();
      const dx = Math.max(q.left - r.right, r.left - q.right, 0);
      const dy = Math.max(q.top - r.bottom, r.top - q.bottom, 0);
      gap = Math.min(gap, Math.max(dx, dy));
    }
    out.push({
      key: el.id || el.dataset.target || el.dataset.scope || '',
      active: el.classList.contains('active'),
      focused: document.activeElement === el,
      fv: el.matches(':focus-visible'),
      style: cs.outlineStyle,
      width: parseFloat(cs.outlineWidth),
      offset: parseFloat(cs.outlineOffset),
      reach,
      gap: gap === Infinity ? -1 : Math.round(gap * 100) / 100,
      ring: ring.join(','),
      accent: accent.join(','),
      shadow: cs.boxShadow,
      surfaceOf,
      contrast: Math.round(ratio(ring, surface) * 100) / 100,
      clippedBy,
    });
  }
  return out;
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
        mock_server.url + "/?ui_mock=1#home",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function("document.body.dataset.view === 'home'", timeout=10_000)
    if view != "home":
        page.evaluate(f"location.hash = '#{view}'")
        page.wait_for_function(
            f"document.body.dataset.view === '{view}'", timeout=10_000
        )
    page.evaluate("document.fonts.ready.then(() => true)")
    page.wait_for_timeout(300)
    page.keyboard.press("Shift")  # keyboard modality for :focus-visible
    return ctx, page, errors


def _assert_rings(rows, n, what):
    assert len(rows) == n, f"{what}: expected {n} rendered controls, got {rows}"
    bad = [
        r for r in rows
        if not (r["focused"] and r["fv"] and r["style"] == "solid"
                and r["width"] >= 2 and r["ring"] == r["accent"])
    ]
    assert not bad, f"{what} without the --accent 2px ring: {bad}"
    low = [r for r in rows if r["contrast"] < 3.0]
    assert not low, f"{what} ring below 3:1 on its surface: {low}"
    clipped = [r for r in rows if r["clippedBy"]]
    assert not clipped, f"{what} ring clipped by an overflow box: {clipped}"
    crowd = [r for r in rows if r["gap"] >= 0 and r["reach"] >= r["gap"]]
    assert not crowd, f"{what} ring reaches a neighbouring control: {crowd}"


def test_home_launcher_tiles_paint_the_accent_ring(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, "home")
    try:
        rows = page.evaluate(_RING_JS, TILES)
        _assert_rings(rows, N_TILES, "Home tile")
        assert {r["key"] for r in rows} == {
            "last-match", "session", "history", "replay", "user-builds",
            "settings",
        }, rows
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_history_scope_tabs_paint_the_accent_ring(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, "history")
    try:
        rows = page.evaluate(_RING_JS, TABS)
        _assert_rings(rows, N_TABS, "History scope tab")
        assert {r["key"] for r in rows} == {
            "14d", "season", "prior_season", "all",
        }, rows
        # The arcane theme's selected-scope underline is an inset
        # box-shadow; a focused active tab must keep it beside the ring.
        active = [r for r in rows if r["active"]]
        assert len(active) == 1, rows
        assert "inset" in active[0]["shadow"], active
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _themes():
    text = (ROOT / "web" / "css" / "themes.css").read_text(encoding="utf-8")
    return sorted(set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text)))


def test_ring_holds_in_every_theme(mock_server, pw_browser):
    """The ring colour is each theme's own --accent: under every
    :root[data-theme] block in web/css/themes.css both control sets stay
    on the token and above 3:1 on their surface."""
    themes = _themes()
    assert len(themes) >= 5, f"theme scan anchor: {themes}"
    failures, accents, seen = [], set(), 0
    for view, sel in (("home", TILES), ("history", TABS)):
        ctx, page, errors = _open(pw_browser, mock_server, view)
        try:
            for t in themes:
                page.evaluate(
                    "(t) => document.documentElement"
                    ".setAttribute('data-theme', t)",
                    t,
                )
                page.keyboard.press("Shift")
                rows = page.evaluate(_RING_JS, sel)
                assert rows, f"{t} #{view}: no control rendered"
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
    # Anchors: both views measured in every theme, and the attribute flip
    # really re-themed the page.
    assert seen == len(themes) * (N_TILES + N_TABS), seen
    assert len(accents) >= 3, f"theme flip inert: {accents}"
    assert not failures, f"theme ring failures: {failures[:4]}"
