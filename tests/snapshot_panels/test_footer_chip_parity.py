"""
tests/snapshot_panels/test_footer_chip_parity.py
RM-1010 (s144 uiux): every visible footer chip - the VOICE button, the
mode pill and the JS-inserted prefs chip - renders at ONE height, so no
footer button stands taller than the footer pills (the 2026-04-29 operator
ask recorded above `footer .footer-btn` in web/css/panels/header.css).

Measured before this slice (headless Chromium, ?ui_mock=1, #home):
- #voice-toggle 25px: `footer .footer-btn` padding 2px, no border, and the
  button keeps the UA `line-height: normal` (21px line box at 16px), while
- #mode-pill 24px: `footer .mode-pill` padding 3px + the base 1px border,
  `line-height: 1` inherited from the footer (16px line box), and
- .prefs-chip 20px: `footer .prefs-chip` in web/css/panels/input_activity.css
  (it loads after header.css, so its padding 2px 8px wins), no border.

The chips are measured by getBoundingClientRect (the visible chip, not the
--hit-min click band the RM-1009 `::after` adds to the button), with the
footer's own height pinned by test_footer_controls_floor.py.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

# 1920x920 = design baseline with Chrome chrome; 923x1280 = companion width.
VIEWPORTS = [(1920, 920), (923, 1280)]

# The prefs chip only exists while a saved pref flag is on; the dev mock
# flag is the one surviving flag (main.js _refreshPrefsChip).
_PREFS_FLAG = "try { localStorage.setItem('rc-ui-mock', '1'); } catch (_) {}"


def _open(pw_browser, mock_server, width, height, prefs_chip):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    if prefs_chip:
        page.add_init_script(_PREFS_FLAG)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1#home",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function("document.body.dataset.view === 'home'", timeout=10_000)
    page.wait_for_selector("footer #voice-toggle", timeout=10_000)
    if prefs_chip:
        page.wait_for_selector("footer .prefs-chip", timeout=10_000)
    # settle the webfonts so the line boxes are the final ones.
    page.evaluate("document.fonts.ready.then(() => true)")
    page.wait_for_timeout(500)
    return ctx, page, errors


_CHIPS = """
() => {
  const f = document.querySelector('footer');
  const fr = f.getBoundingClientRect();
  const sel = ['#voice-toggle', '#mode-pill', '.prefs-chip'];
  const out = {};
  for (const s of sel) {
    const el = f.querySelector(s);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (getComputedStyle(el).display === 'none' || r.width === 0) continue;
    out[s] = {h: r.height, top: r.top, bottom: r.bottom,
              mid: r.top + r.height / 2};
  }
  return {chips: out, footerMid: fr.top + fr.height / 2};
}
"""


@pytest.mark.parametrize("prefs_chip", [False, True], ids=["plain", "prefs-chip"])
@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_footer_chips_share_one_height(
    mock_server, pw_browser, width, height, prefs_chip
):
    ctx, page, errors = _open(pw_browser, mock_server, width, height, prefs_chip)
    try:
        m = page.evaluate(_CHIPS)
    finally:
        page.close()
        ctx.close()
    chips = m["chips"]
    want = {"#voice-toggle", "#mode-pill"} | ({".prefs-chip"} if prefs_chip else set())
    # anchor: an empty or hidden footer must not pass vacuously.
    assert want <= set(chips), f"visible footer chips: {sorted(chips)}"
    heights = {s: c["h"] for s, c in chips.items()}
    assert max(heights.values()) - min(heights.values()) <= 0.5, (
        f"{width}x{height}: footer chips differ in height: {heights}"
    )
    # the button never stands taller than the pills (2026-04-29 ask).
    assert heights["#voice-toggle"] <= heights["#mode-pill"] + 0.5, heights
    # one row: every chip is centred on the bar.
    for s, c in chips.items():
        assert abs(c["mid"] - m["footerMid"]) <= 1, (
            f"{s} centre {c['mid']} off the footer centre {m['footerMid']}"
        )
    assert not errors, f"JS errors: {errors[:3]}"
