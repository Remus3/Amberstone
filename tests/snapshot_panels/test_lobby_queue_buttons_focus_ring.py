"""
tests/snapshot_panels/test_lobby_queue_buttons_focus_ring.py
RM-1209 (s144 uiux) - the Lobby queue strip draws a token focus ring.

THE DEFECT. The six .lq-btn controls in .lobby-view-queue-controls
(web/index.html: Accept, Party, the Primary / Secondary lane pair, Cancel
Queue, Find Match) carried no :focus-visible rule in
web/css/panels/header.css, so a keyboard-focused queue button fell back to
the user-agent ring (Chromium: `outline-style: auto`, a thin system
colour). Every other Lobby control draws the lobby precedent instead
(.lv-top8-tag / .lv-top8-search-input: a solid 2px --accent outline), and
the Find / Cancel pair is exactly where RM-1139 and RM-1208 move focus
programmatically, so the ring is how a keyboard user sees where focus
went.

THE FIX. `.lq-btn:focus-visible { outline: 2px solid
var(--accent); outline-offset: 2px; }`. An OUTLINE, not the --focus-ring
box-shadow: .lq-find.is-searching animates box-shadow (lq-find-pulse) and
.lq-btn transitions it, so a shadow ring would be overwritten by the
pulse. The 2px offset puts the ring on the strip surface rather than on
the button's own fill, so it reads on the green Find and red Cancel fills
as well as on the --surface-alt buttons; the strip's 8px gap leaves room
for 2px offset + 2px width without touching a neighbour. A second rule,
`.lq-lane-pref.is-conflict:focus-visible`, restores the ring over the
conflict outline.

MEASURED BEFORE THE FIX (default theme arcane): every queue button
computed `outline-style: auto`, 1px, rgb(16,16,16) on the
.lobby-view-card-queue surface - 1.08:1, effectively no ring. After: the
--accent ring at 6.99:1 (arcane) to 10.12:1 (moonlit) on that surface.

WHAT IS MEASURED (headless Chromium, computed values, never a grep):
  - every rendered, enabled .lq-btn, focused with keyboard modality,
    matches :focus-visible and computes a solid outline >= 2px whose
    colour is the resolved --accent (not the UA `auto` ring);
  - that ring colour against the nearest opaque ancestor background
    (the surface the offset ring is painted on) is >= 3:1, the WCAG
    1.4.11 non-text floor, stating the PAIR;
  - no overflow-clipping ancestor cuts the ring (offset + width = 4px);
  - the Idle state covers Accept / Party / both lanes / Find, the
    Searching state covers Cancel (Find is disabled while searching);
  - a CONFLICTED Primary lane button (.lq-lane-pref.is-conflict, whose
    1px --bad outline has the same specificity and comes later) still
    draws the ring, and keeps its --bad border;
  - the ring holds in every :root[data-theme] block of themes.css.

Harness: test_lobby_render_stability._open_lobby_stability with the
polled LCU envelope (ui_mock=False), as test_lobby_find_match_focus.py.
"""
import copy
import re
from pathlib import Path

from tests.snapshot_panels.test_lobby_render_stability import (
    _POLL_LCU,
    _open_lobby_stability,
)

ROOT = Path(__file__).resolve().parent.parent.parent

_RING_JS = r"""
() => {
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
  const out = [];
  const btns = document.querySelectorAll(
    '.lobby-view-queue-controls .lq-btn');
  for (const el of btns) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.disabled) continue;
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
    out.push({
      id: el.id,
      focused: document.activeElement === el,
      fv: el.matches(':focus-visible'),
      style: cs.outlineStyle,
      width: parseFloat(cs.outlineWidth),
      offset: parseFloat(cs.outlineOffset),
      ring: ring.join(','),
      accent: accent.join(','),
      surfaceOf,
      contrast: Math.round(ratio(ring, surface) * 100) / 100,
      clippedBy,
    });
  }
  return out;
}
"""


def _open(pw_browser, mock_server, lcu):
    ctx, page, errors, _hits = _open_lobby_stability(
        pw_browser, mock_server, poll=True, ui_mock=False, lcu=lcu
    )
    page.wait_for_function(
        "(() => { const b = document.getElementById('lv-find-match');"
        "  return b && !b.disabled; })()",
        timeout=15_000,
    )
    # The queue buttons transition their colours, so an in-page theme flip
    # followed by a ring / surface read would straddle it (RM-1132 audit,
    # tests/snapshot_panels/test_theme_swap_reads_settled.py).
    page.add_style_tag(
        content="*, *::before, *::after { transition: none !important; }"
    )
    return ctx, page, errors


def _assert_rings(rows, want_ids):
    got = {r["id"] for r in rows}
    missing = set(want_ids) - got
    assert not missing, f"queue buttons not rendered/enabled: {missing}; {rows}"
    bad = [
        r for r in rows
        if not (r["focused"] and r["fv"] and r["style"] == "solid"
                and r["width"] >= 2 and r["ring"] == r["accent"])
    ]
    assert not bad, f"queue button without the --accent 2px ring: {bad}"
    low = [r for r in rows if r["contrast"] < 3.0]
    assert not low, f"ring below 3:1 on its surface: {low}"
    clipped = [r for r in rows if r["clippedBy"]]
    assert not clipped, f"ring clipped by an overflow box: {clipped}"


def test_idle_queue_buttons_paint_the_accent_ring(mock_server, pw_browser):
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    try:
        page.keyboard.press("Tab")  # keyboard modality for :focus-visible
        rows = page.evaluate(_RING_JS)
        _assert_rings(rows, {
            "lv-auto-accept", "lv-party-toggle", "lv-lane-primary",
            "lv-lane-secondary", "lv-find-match",
        })
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_searching_cancel_queue_paints_the_accent_ring(
    mock_server, pw_browser
):
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    try:
        lcu["lobby"]["search_state"] = "Searching"
        page.wait_for_function(
            "(() => { const b = document.getElementById('lv-cancel-match');"
            "  return b && !b.disabled && b.getBoundingClientRect().width; })()",
            timeout=15_000,
        )
        page.keyboard.press("Tab")
        rows = page.evaluate(_RING_JS)
        _assert_rings(rows, {"lv-cancel-match"})
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_conflicted_primary_lane_keeps_the_ring(mock_server, pw_browser):
    """.lq-lane-pref.is-conflict sets `outline: 1px solid var(--bad)` at
    the same specificity as .lq-btn:focus-visible and LATER in the file,
    so without its own :focus-visible rule a focused conflicted Primary
    shows only the 1px red outline pushed out by the offset. The conflict
    is driven for real through the polled envelope: self and a party
    member share a non-FILL primary, and main.js's lobby conflict probe
    toggles is-conflict on #lv-lane-primary. The red border still carries the conflict."""
    lcu = copy.deepcopy(_POLL_LCU)
    # Self's primary comes from lobby.local_member (main.js the lane-pref
    # seed); the other member's from its own position_preferences.first.
    lcu["lobby"]["local_member"] = {"position_preferences": {
        "first_preference": "MIDDLE", "second_preference": "TOP"}}
    lcu["lobby"]["members"][1]["position_preferences"] = {
        "first": "MIDDLE", "second": "TOP"}
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    try:
        page.wait_for_function(
            "document.getElementById('lv-lane-primary')"
            ".classList.contains('is-conflict')",
            timeout=15_000,
        )
        page.keyboard.press("Tab")
        rows = [r for r in page.evaluate(_RING_JS)
                if r["id"] == "lv-lane-primary"]
        _assert_rings(rows, {"lv-lane-primary"})
        border = page.evaluate(
            "(() => { const cv = document.createElement('canvas');"
            "  const c = cv.getContext('2d');"
            "  const px = (col) => { c.clearRect(0, 0, 1, 1);"
            "    c.fillStyle = col; c.fillRect(0, 0, 1, 1);"
            "    return Array.from(c.getImageData(0, 0, 1, 1).data).join(','); };"
            "  const el = document.getElementById('lv-lane-primary');"
            "  return [px(getComputedStyle(el).borderTopColor),"
            "    px(getComputedStyle(document.documentElement)"
            "      .getPropertyValue('--bad').trim())]; })()"
        )
        assert border[0] == border[1], f"conflict border lost: {border}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _themes():
    text = (ROOT / "web" / "css" / "themes.css").read_text(encoding="utf-8")
    return sorted(set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text)))


def test_ring_holds_in_every_theme(mock_server, pw_browser):
    """The ring colour is each theme's own --accent: under every
    :root[data-theme] block in web/css/themes.css the ring stays on the
    token and above 3:1 on the strip surface."""
    themes = _themes()
    assert len(themes) >= 5, f"theme scan anchor: {themes}"
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    try:
        failures, accents = [], set()
        for t in themes:
            page.evaluate(
                "(t) => document.documentElement.setAttribute('data-theme', t)",
                t,
            )
            page.keyboard.press("Tab")
            rows = page.evaluate(_RING_JS)
            assert rows, f"{t}: no queue button rendered"
            for r in rows:
                accents.add(r["accent"])
                if not (r["style"] == "solid" and r["width"] >= 2
                        and r["ring"] == r["accent"]
                        and r["contrast"] >= 3.0):
                    failures.append((t, r))
        # Anchor: the attribute flip really re-themed the page.
        assert len(accents) >= 3, f"theme flip inert: {accents}"
        assert not failures, f"theme ring failures: {failures[:4]}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
