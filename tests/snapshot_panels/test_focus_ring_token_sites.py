"""
tests/snapshot_panels/test_focus_ring_token_sites.py
RM-1017 (s144 uiux): `--focus-ring` (web/css/tokens.css, re-declared per
theme in web/css/themes.css) is a BOX-SHADOW value, "0 0 0 2px <color>".
Six :focus-visible rules fed it to `outline:` instead:

- web/css/panels/build_insights.css  .bi-tab, #bi-min-n, th.bi-sortable
  (since RM-1762 the ring is on the .bi-sort-btn inside that cell)
- web/css/panels/duration_winrate.css  .dw-champ-input, .dw-champ-clear
- web/css/panels/replay_events.css  .replay-events-row

"0 0 0 2px <color>" is not a valid outline, so the declaration is invalid at
computed-value time and every outline longhand falls back to its initial
value: outline-style none. Measured in headless Chromium under /?ui_mock=1
before the fix: a keyboard-focused Replay timeline row computed
`outline: none 3px ... ; box-shadow: none`, i.e. no ring at all, and the
source grep for the token name reads clean (headless-uiux.md section 6,
trap 1). The fix draws the token as a box-shadow, the way every other
--focus-ring site does (panel_visibility.css, player_gpi.css,
champ_select_view.css); the two sites that asked for an inside ring
(outline-offset -2px) use `inset var(--focus-ring)`, the RM-972 pattern.

The same slice gives the three Replay Timeline filter checkboxes
(#replay-evt-items / -skills / -wards) a :focus-visible ring: they had no
rule and fell back to the UA outline, unlike every Settings checkbox.

This file fails if any CSS rule feeds --focus-ring to an outline again, if
any of those controls stops painting a 2px ring under keyboard focus, or if
an outer ring is clipped by an overflow ancestor (an outer ring on a
timeline row would be: #replay-events-list scrolls).
"""
import re
from pathlib import Path

import pytest

from tests.snapshot_panels._webfont_stub import route_offline_webfont
from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent
CSS_DIR = ROOT / "web" / "css"
VIEWPORTS = [(1920, 920), (923, 1280)]

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_OUTLINE_DECL = re.compile(r"(?:^|[;{\s])(outline(?:-[a-z]+)?)\s*:\s*([^;}]*)")

# Focus each matched control (keyboard modality is set by one Tab press
# first, so .focus() matches :focus-visible the way Tab traversal does) and
# report whether focus ADDS a 2px ring, by box-shadow or by a real (not UA
# `auto`) outline. The unfocused shadow is read first so a resting shadow
# (e.g. a won / lost inset stripe) cannot pass for a ring.
_RINGS = """
(sel) => {
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (document.activeElement && document.activeElement.blur) {
      document.activeElement.blur();
    }
    const rest = getComputedStyle(el).boxShadow;
    el.focus();
    const cs = getComputedStyle(el);
    const shadowRing = cs.boxShadow !== rest
      && cs.boxShadow.includes('0px 0px 0px 2px');
    const outlineRing = cs.outlineStyle !== 'none'
      && cs.outlineStyle !== 'auto' && parseFloat(cs.outlineWidth) >= 2;
    // An outer 2px ring must fit inside every overflow-clipping ancestor
    // (an inset ring cannot be clipped by them). The box is re-read after
    // focus, which scrolls a row below the list's fold into view.
    const f = el.getBoundingClientRect();
    const pad = cs.boxShadow.includes('inset') ? 0 : 2;
    const clippedBy = [];
    for (let a = el.parentElement; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.overflowX === 'visible' && s.overflowY === 'visible') continue;
      const ar = a.getBoundingClientRect();
      if (f.left - pad < ar.left - 0.5 || f.right + pad > ar.right + 0.5
          || f.top - pad < ar.top - 0.5 || f.bottom + pad > ar.bottom + 0.5) {
        clippedBy.push(a.id || String(a.className));
      }
    }
    out.push({
      sel, id: el.id || el.dataset.biTab || el.className,
      focused: document.activeElement === el,
      fv: el.matches(':focus-visible'),
      rest, shadow: cs.boxShadow,
      outline: cs.outlineStyle + ' ' + cs.outlineWidth,
      ring: shadowRing || outlineRing,
      clippedBy,
    });
  }
  return out;
}
"""


def _decls_feeding_focus_ring_to_outline():
    hits = []
    for css in sorted(CSS_DIR.rglob("*.css")):
        text = _COMMENT.sub(" ", css.read_text(encoding="utf-8"))
        for m in _OUTLINE_DECL.finditer(text):
            if "--focus-ring" in m.group(2):
                rel = css.relative_to(ROOT).as_posix()
                hits.append(f"{rel}: {m.group(1)}: {m.group(2).strip()}")
    return hits


def test_focus_ring_token_is_a_box_shadow_value():
    """The premise: the token is a shadow list, so it can never be an
    outline. If tokens.css ever changes its shape, revisit this file."""
    tokens = (CSS_DIR / "tokens.css").read_text(encoding="utf-8")
    m = re.search(r"--focus-ring\s*:\s*([^;]+);", tokens)
    assert m, "--focus-ring not declared in web/css/tokens.css"
    assert re.match(r"0 0 0 2px\s", m.group(1).strip()), m.group(1)


def test_no_css_rule_feeds_the_focus_ring_token_to_outline():
    hits = _decls_feeding_focus_ring_to_outline()
    assert not hits, (
        "--focus-ring is a box-shadow value; as an outline it is invalid at "
        f"computed-value time and paints nothing: {hits}"
    )


def test_outline_scan_sees_a_real_declaration():
    """Anchor: the scanner must read outline declarations at all, or an
    empty result above would pass for the wrong reason."""
    seen = 0
    for css in CSS_DIR.rglob("*.css"):
        text = _COMMENT.sub(" ", css.read_text(encoding="utf-8"))
        seen += len(_OUTLINE_DECL.findall(text))
    assert seen >= 20, f"outline scanner matched only {seen} declarations"


def _new_page(pw_browser, mock_server, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    # RM-1079: the webfont comes from the local stub, never the network.
    route_offline_webfont(ctx)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    return ctx, page, errors


def _rings(page, sel):
    return page.evaluate(_RINGS, sel)


def _assert_rings(rows, sel, at_least):
    assert len(rows) >= at_least, f"{sel}: only {len(rows)} rendered"
    bad = [r for r in rows if not (r["focused"] and r["fv"] and r["ring"])]
    assert not bad, f"{sel}: focused without a 2px ring: {bad[:3]}"
    clipped = [r for r in rows if r["clippedBy"]]
    assert not clipped, f"{sel}: focus ring clipped by an overflow box: {clipped[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_build_insights_controls_paint_a_focus_ring(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        page.goto(mock_server.url + "/?ui_mock=1#build-insights",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#bi-table-mount table.bi-table "
            "th.bi-sortable') !== null",
            timeout=10_000,
        )
        page.keyboard.press("Tab")
        _assert_rings(_rings(page, "#view-build-insights .bi-tab"), ".bi-tab", 9)
        _assert_rings(_rings(page, "#bi-min-n"), "#bi-min-n", 1)
        _assert_rings(
            _rings(page, "#bi-table-mount th.bi-sortable .bi-sort-btn"),
            ".bi-sort-btn", 2
        )
        # Game Length tab mounts the duration panel's champion picker.
        page.click(".bi-tab[data-bi-tab='duration']")
        page.wait_for_selector("#bi-duration-mount .dw-champ-clear", timeout=10_000)
        page.keyboard.press("Tab")
        _assert_rings(
            _rings(page, "#bi-duration-mount .dw-champ-input"), ".dw-champ-input", 1
        )
        _assert_rings(
            _rings(page, "#bi-duration-mount .dw-champ-clear"), ".dw-champ-clear", 1
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_replay_timeline_controls_paint_a_focus_ring(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        page.goto(mock_server.url + "/?ui_mock=1#replay",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_selector(".replay-match-row", timeout=10_000)
        page.click(".replay-match-row")
        page.wait_for_function(
            "() => document.querySelectorAll('.replay-events-row').length > 0",
            timeout=10_000,
        )
        page.keyboard.press("Tab")
        _assert_rings(
            _rings(page, "#replay-events-list .replay-events-row"),
            ".replay-events-row", 3,
        )
        _assert_rings(
            _rings(page, ".replay-events-filter input[type=checkbox]"),
            "replay filter checkbox", 3,
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
