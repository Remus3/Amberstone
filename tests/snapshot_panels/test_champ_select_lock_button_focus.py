"""
tests/snapshot_panels/test_champ_select_lock_button_focus.py
RM-1137 (s144 uiux): the Champ Select LOCK IN button (#csv-lock-btn,
rendered by web/js/panels/champ_select.js _csvRenderCentralPane, styled by
web/css/panels/champ_select_view.css .csv-lock-btn) is the page's primary
action, and nothing pinned its keyboard contract.

MEASURED under /?ui_mock=1&mode=<sr|aram>#champ-select at 1920x1080 before
the fix:
- a keyboard-focused LOCK IN drew only the UA outline (auto 3px), and the
  button sits flush against the overflow-x: hidden .csv-card-body.csv-mypick
  (button left/right == container left/right), so the outer outline is cut
  off both side edges - the RM-972 build-row clip, on the primary action;
- the central pane rebuilds through innerHTML on every async land (DS, ban
  suggestions, lol-descriptions ...), and the RM-971 focus carry only knew
  the build chooser rows, so a rebuild threw a focused LOCK IN to <body>
  (lane doc section 6, trap 2).

Contract pinned here: the focused button draws the one system ring INSET
(inset var(--focus-ring), outline none) on all six themes; focus survives a
central-pane rebuild; a rebuild never STEALS focus that was elsewhere. The
32px min-height stays the documented UIX1 operator exception
(tests/test_champ_select_sr_ui_audit.py _MINH_EXCEPTIONS), so the hit floor
is not asserted. Arena renders no LOCK IN button (its duo pane), so it is
not driven.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_champ_select_view import _MODE_CONTENT

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_BTN = "#csv-lock-btn"

_INSET_RING = """() => {
  const probe = document.createElement('div');
  probe.style.boxShadow = 'inset var(--focus-ring)';
  document.body.appendChild(probe);
  const ring = getComputedStyle(probe).boxShadow;
  probe.remove();
  return ring;
}"""

# Mark the live node, fire a real re-render trigger (the lol-descriptions
# cache land, which clears the section sig and schedules one rAF render),
# then wait until the button is a NEW node, i.e. the pane really rebuilt.
_REBUILD = """async (sel) => {
  const old = document.querySelector(sel);
  old.dataset.preRebuild = '1';
  document.dispatchEvent(new Event('rc:lol-descriptions-ready'));
  const t0 = performance.now();
  while (performance.now() - t0 < 5000) {
    await new Promise((r) => requestAnimationFrame(r));
    const now = document.querySelector(sel);
    if (now && now !== old && !now.dataset.preRebuild) {
      const a = document.activeElement;
      return {rebuilt: true, active: a ? (a.id || a.tagName) : null};
    }
  }
  return {rebuilt: false, active: null};
}"""


def _open(mock_server, pw_browser, mode, theme="hextech"):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode={mode}&theme={theme}#champ-select",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        f"document.querySelectorAll('{_MODE_CONTENT[mode]}').length > 0",
        timeout=10_000,
    )
    page.wait_for_selector(_BTN, state="visible", timeout=10_000)
    return ctx, page, errors


def _focus_by_keyboard(page) -> None:
    # A real key press first, so a programmatic focus matches :focus-visible
    # the way it does after Tab.
    page.keyboard.press("Shift")
    page.evaluate("(s) => document.querySelector(s).focus()", _BTN)


@pytest.mark.parametrize("theme", _THEMES)
def test_lock_button_draws_the_inset_system_ring(mock_server, pw_browser, theme):
    ctx, page, errors = _open(mock_server, pw_browser, "sr", theme)
    try:
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        ring = page.evaluate(_INSET_RING)
        _focus_by_keyboard(page)
        # .csv-lock-btn carries "transition: 0.15s" (all properties), so
        # the ring fades in: read the SETTLED value, after its transitions.
        got = page.evaluate(
            "async (sel) => { const el = document.querySelector(sel);"
            " await Promise.all(el.getAnimations().map((a) => a.finished));"
            " const cs = getComputedStyle(el);"
            " return {text: el.textContent.trim(),"
            " focused: document.activeElement === el,"
            " visible: el.matches(':focus-visible'),"
            " outline: cs.outlineStyle, shadow: cs.boxShadow}; }",
            _BTN,
        )
    finally:
        page.close()
        ctx.close()
    assert ring.startswith("inset") or ring.endswith("inset"), (
        f"inset --focus-ring resolved {ring!r}"
    )
    assert got["text"].startswith("LOCK IN "), got
    assert got["focused"] and got["visible"], got
    assert got["shadow"] == ring, (
        f"{theme}: focused LOCK IN box-shadow {got['shadow']!r}, ring {ring!r}"
    )
    assert got["outline"] == "none", (
        f"{theme}: focused LOCK IN still draws the UA outline ({got['outline']})"
    )
    assert not errors, errors[:3]


@pytest.mark.parametrize("mode", ["sr", "aram"])
def test_lock_button_sits_flush_in_a_clipping_card(mock_server, pw_browser, mode):
    # Why the ring is INSET: the button spans its overflow-x: hidden card
    # edge to edge, so any OUTER ring or outline is clipped at both sides.
    # If the layout ever gains side room this test says so, and an outer
    # ring becomes an option again.
    ctx, page, errors = _open(mock_server, pw_browser, mode)
    try:
        geo = page.evaluate(
            "(sel) => { const el = document.querySelector(sel);"
            " const card = el.closest('.csv-card-body.csv-mypick');"
            " const r = el.getBoundingClientRect();"
            " const c = card.getBoundingClientRect();"
            " return {ox: getComputedStyle(card).overflowX,"
            " left: r.left - c.left, right: c.right - r.right}; }",
            _BTN,
        )
    finally:
        page.close()
        ctx.close()
    assert geo["ox"] != "visible", geo
    assert geo["left"] < 2 and geo["right"] < 2, geo
    assert not errors, errors[:3]


@pytest.mark.parametrize("mode", ["sr", "aram"])
def test_focus_survives_a_central_pane_rebuild(mock_server, pw_browser, mode):
    ctx, page, errors = _open(mock_server, pw_browser, mode)
    try:
        _focus_by_keyboard(page)
        out = page.evaluate(_REBUILD, _BTN)
    finally:
        page.close()
        ctx.close()
    assert out["rebuilt"], f"{mode}: the central pane never rebuilt"
    assert out["active"] == "csv-lock-btn", (
        f"{mode}: a rebuild threw LOCK IN focus to {out['active']}"
    )
    assert not errors, errors[:3]


def test_a_rebuild_never_steals_focus(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, "sr")
    try:
        page.evaluate(
            "() => { if (document.activeElement) document.activeElement.blur(); }"
        )
        out = page.evaluate(_REBUILD, _BTN)
    finally:
        page.close()
        ctx.close()
    assert out["rebuilt"], "the central pane never rebuilt"
    assert out["active"] != "csv-lock-btn", (
        "a rebuild moved focus onto LOCK IN when it was not there"
    )
    assert not errors, errors[:3]


# RM-1138: a click on LOCK IN holds the lock for 1.5s so a second click
# cannot fire a second lock_pick. MEASURED before the fix (sr and aram, the
# lock_pick POST stubbed to never answer): the hold lived only on the
# clicked node as btn.disabled, so a central-pane rebuild inside the window
# rendered a fresh ENABLED button and a second click POSTed a second
# lock_pick (2 POSTs); and disabling the focused button threw keyboard focus
# to <body> at once, before any rebuild. Contract pinned here: the hold
# survives a rebuild, is announced (aria-disabled="true"), keeps keyboard
# focus on the button, and releases after the window.
_STUB_LOCK_POST = """() => {
  window.__lockPosts = 0;
  const orig = window.fetch;
  window.fetch = (u, o) => {
    if (String(u).includes('/api/lcu-cmd') && !String(u).includes('result')) {
      window.__lockPosts += 1;
      return new Promise(() => {});
    }
    return orig(u, o);
  };
}"""

# Opacity is read SETTLED: .csv-lock-btn carries "transition: 0.15s".
_READ_BTN = """async (sel) => {
  const b = document.querySelector(sel);
  await Promise.all(b.getAnimations().map((x) => x.finished));
  const a = document.activeElement;
  return {aria: b.getAttribute('aria-disabled'), disabled: b.disabled,
    opacity: getComputedStyle(b).opacity,
    active: a ? (a.id || a.tagName) : null, posts: window.__lockPosts};
}"""


@pytest.mark.parametrize("mode", ["sr", "aram"])
def test_a_pending_lock_survives_a_rebuild(mock_server, pw_browser, mode):
    ctx, page, errors = _open(mock_server, pw_browser, mode)
    try:
        page.evaluate(_STUB_LOCK_POST)
        _focus_by_keyboard(page)
        page.keyboard.press("Enter")
        held = page.evaluate(_READ_BTN, _BTN)
        out = page.evaluate(_REBUILD, _BTN)
        rebuilt = page.evaluate(_READ_BTN, _BTN)
        # Both a keyboard and a pointer-style activation of the NEW node.
        page.keyboard.press("Enter")
        page.evaluate("(s) => document.querySelector(s).click()", _BTN)
        posts = page.evaluate("() => window.__lockPosts")
    finally:
        page.close()
        ctx.close()
    assert held["posts"] == 1, held
    assert held["aria"] == "true", f"{mode}: the held button is not announced: {held}"
    assert held["active"] == "csv-lock-btn", (
        f"{mode}: activating LOCK IN threw focus to {held['active']}"
    )
    assert out["rebuilt"], f"{mode}: the central pane never rebuilt"
    assert rebuilt["aria"] == "true", (
        f"{mode}: a rebuild inside the hold rendered a live button: {rebuilt}"
    )
    assert rebuilt["active"] == "csv-lock-btn", rebuilt
    # The held state still LOOKS held (the dimmed [disabled] treatment).
    assert held["opacity"] == "0.5" and rebuilt["opacity"] == "0.5", (
        f"{mode}: the held button is not dimmed: {held} / {rebuilt}"
    )
    assert posts == 1, f"{mode}: a click after the rebuild fired lock_pick #{posts}"
    assert not errors, errors[:3]


def test_the_lock_hold_releases_after_its_window(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, "sr")
    try:
        page.evaluate(_STUB_LOCK_POST)
        page.evaluate("(s) => document.querySelector(s).click()", _BTN)
        page.evaluate(_REBUILD, _BTN)
        page.wait_for_function(
            "(s) => document.querySelector(s).getAttribute('aria-disabled')"
            " !== 'true'",
            arg=_BTN, timeout=5_000,
        )
        page.evaluate("(s) => document.querySelector(s).click()", _BTN)
        posts = page.evaluate("() => window.__lockPosts")
    finally:
        page.close()
        ctx.close()
    assert posts == 2, f"the released button did not fire a retry ({posts} POSTs)"
    assert not errors, errors[:3]
