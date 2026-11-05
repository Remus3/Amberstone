"""
tests/snapshot_panels/test_home_accent2_focus_ring.py
RM-1546 (s144 uiux) - the Home mode tabs and the Tonight's Pick
champion name draw their keyboard focus ring in --accent, not --accent-2.

THE DEFECT. Two :focus-visible rules in web/css/panels/home.css drew
`outline: 2px solid var(--accent-2)`: .home-mode-tab (All / SR / ARAM /
Arena, offset 0) and .home-coach-pick-champ (offset 2px). --accent-2 is the
red pop in the ember and bloodmoon themes and a mid purple in arcane, so
the ring barely separates from the dark red / purple surfaces it sits on.
MEASURED in headless Chromium under /?ui_mock=1#home at 1920x920, computed
colours resolved to sRGB, WCAG 1.4.11 non-text floor 3:1:
  - focused ACTIVE mode tab, ring vs the tab's own --surface-3 fill (the
    ring abuts it, offset 0): bloodmoon 2.56, ember 2.60, arcane 2.77 -
    BELOW 3:1; vs the #home-overlay surface outside it: 3.39 / 3.46 / 3.75;
  - focused champion name, ring vs the card --surface-2 (offset 2px):
    bloodmoon 3.00, ember 3.05, arcane 3.28 - on the floor, no headroom.
  (hextech, moonlit and terminal were 7.8 to 10.6.)

THE FIX. Both rings take --accent, the Home / Lobby ring convention
(.home-action-tile and .view-tab, RM-1210; .lq-btn, .lv-top8-tag). Measured
after: >= 5.17:1 on every adjacent computed background colour in every
theme (the lowest pair is arcane --accent on the active tab's --surface-3
fill). The Tonight's Pick card also paints a gradient over its --surface-2,
which this file does not sample: the painted pixel beside the arcane ring
measured 4.44:1 in the slice audit. --accent-2 stays
the champion name's TEXT colour and the tab / card tint; only the ring
moves.

WHAT IS MEASURED (headless Chromium, computed values, never a grep):
  - in every :root[data-theme] block of web/css/themes.css plus the
    attribute-less hextech base, each mode tab and the champion name,
    focused with keyboard modality, matches :focus-visible and paints a
    solid outline >= 2px whose colour is the resolved --accent;
  - that ring is >= 4.5:1 (the 3:1 floor plus headroom) against the first
    opaque ancestor background AND, where the ring abuts the control
    (offset < 1px), against the control's own opaque fill - the PAIR is
    named in every failure;
  - no CSS rule under web/css draws an outline in --accent-2 (scanner
    anchored on a real outline declaration count).
"""
import re
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent
CSS_DIR = ROOT / "web" / "css"

TABS = "#home-mode-tabs .home-mode-tab"
CHAMP = "#home-coach-pick-champ"
N_TABS = 4
FLOOR = 4.5

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_OUTLINE_DECL = re.compile(r"(?:^|[;{\s])(outline(?:-[a-z]+)?)\s*:\s*([^;}]*)")

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
    const r = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    return Math.round(r * 100) / 100;
  };
  const accent = rgba(getComputedStyle(document.documentElement)
    .getPropertyValue('--accent').trim());
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r0 = el.getBoundingClientRect();
    if (!r0.width || !r0.height) continue;
    if (document.activeElement && document.activeElement.blur) {
      document.activeElement.blur();
    }
    el.focus();
    const cs = getComputedStyle(el);
    const ring = rgba(cs.outlineColor);
    let surface = null, surfaceOf = '';
    for (let a = el.parentElement; a; a = a.parentElement) {
      const bg = rgba(getComputedStyle(a).backgroundColor);
      if (bg[3] === 255) {
        surface = bg; surfaceOf = a.id || String(a.className); break;
      }
    }
    if (!surface) { surface = [0, 0, 0, 255]; surfaceOf = '(none)'; }
    const own = rgba(cs.backgroundColor);
    const offset = parseFloat(cs.outlineOffset);
    out.push({
      key: el.dataset.mode || el.id || el.textContent.trim(),
      active: el.classList.contains('active'),
      focused: document.activeElement === el,
      fv: el.matches(':focus-visible'),
      style: cs.outlineStyle,
      width: parseFloat(cs.outlineWidth),
      offset,
      ring: ring.join(','),
      accent: accent.join(','),
      surfaceOf,
      vsSurface: ratio(ring, surface),
      // The ring abuts the control only when it is not pushed off it.
      vsOwn: (offset < 1 && own[3] === 255) ? ratio(ring, own) : null,
    });
  }
  return out;
}
"""


def _themes():
    text = (CSS_DIR / "themes.css").read_text(encoding="utf-8")
    return sorted(set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text)))


def _open(pw_browser, mock_server):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/?ui_mock=1#home",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function("document.body.dataset.view === 'home'", timeout=10_000)
    page.wait_for_function(
        "(() => { const e = document.getElementById('home-coach-pick-champ');"
        " return e && e.textContent.trim() !== '-'"
        " && e.getBoundingClientRect().width > 0; })()",
        timeout=10_000,
    )
    # Theme flips below must not straddle a colour transition (RM-1132).
    page.add_style_tag(
        content="*, *::before, *::after { transition: none !important; }"
    )
    page.keyboard.press("Shift")  # keyboard modality for :focus-visible
    return ctx, page, errors


def _set_theme(page, theme):
    # hextech is the base palette: web/index.html sets no attribute for it.
    page.evaluate(
        "(t) => t === 'hextech'"
        " ? document.documentElement.removeAttribute('data-theme')"
        " : document.documentElement.setAttribute('data-theme', t)",
        theme,
    )
    page.keyboard.press("Shift")


def _bad(theme, rows):
    out = []
    for r in rows:
        why = []
        if not (r["focused"] and r["fv"]):
            why.append("not :focus-visible")
        if r["style"] != "solid" or r["width"] < 2:
            why.append(f"outline {r['style']} {r['width']}px")
        if r["ring"] != r["accent"]:
            why.append(f"ring {r['ring']} is not --accent {r['accent']}")
        if r["vsSurface"] < FLOOR:
            why.append(f"ring vs {r['surfaceOf']} {r['vsSurface']}:1")
        if r["vsOwn"] is not None and r["vsOwn"] < FLOOR:
            why.append(f"ring vs its own fill {r['vsOwn']}:1")
        if why:
            out.append((theme, r["key"], "active" if r["active"] else "", why))
    return out


def test_home_rings_are_accent_with_headroom_in_every_theme(mock_server, pw_browser):
    themes = _themes()
    assert len(themes) >= 5, f"theme scan anchor: {themes}"
    themes.append("hextech")
    ctx, page, errors = _open(pw_browser, mock_server)
    failures, accents, seen_tabs, seen_champ, abutting = [], set(), 0, 0, 0
    try:
        for t in themes:
            _set_theme(page, t)
            tabs = page.evaluate(_RING_JS, TABS)
            champ = page.evaluate(_RING_JS, CHAMP)
            assert len(tabs) == N_TABS, f"{t}: tabs rendered {tabs}"
            assert len(champ) == 1, f"{t}: champion name rendered {champ}"
            assert sum(1 for r in tabs if r["active"]) == 1, tabs
            seen_tabs += len(tabs)
            seen_champ += len(champ)
            abutting += sum(1 for r in tabs if r["vsOwn"] is not None)
            accents.update(r["accent"] for r in tabs + champ)
            failures += _bad(t, tabs) + _bad(t, champ)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    # Anchors: every theme measured, the flip really re-themed the page, and
    # the own-fill pair was actually read for the offset-0 tab rings.
    assert seen_tabs == N_TABS * len(themes), seen_tabs
    assert seen_champ == len(themes), seen_champ
    assert len(accents) >= 3, f"theme flip inert: {accents}"
    assert abutting >= len(themes), f"own-fill pair never read: {abutting}"
    assert not failures, f"focus ring failures: {failures[:6]}"


def _outline_decls():
    for css in sorted(CSS_DIR.rglob("*.css")):
        text = _COMMENT.sub(" ", css.read_text(encoding="utf-8"))
        for m in _OUTLINE_DECL.finditer(text):
            yield css.relative_to(ROOT).as_posix(), m.group(1), m.group(2).strip()


def test_no_css_rule_draws_an_outline_in_accent_2():
    decls = list(_outline_decls())
    assert len(decls) >= 20, f"outline scanner matched only {len(decls)}"
    hits = [d for d in decls if "--accent-2" in d[2]]
    assert not hits, (
        "--accent-2 is the red pop in ember / bloodmoon and sits at or under "
        f"3:1 on their surfaces; draw focus rings in --accent: {hits}"
    )
