"""
tests/snapshot_panels/test_footer_status_items.py
RM-1014 (s144 uiux): the four footer status items - #input-latency-footer
(.latency-stat), #analyze-footer (.analyze-stat), #analyze-now and
#frame-count - against the one-row footer contract RM-1013 set.

Probed before this slice: web/css/panels/map_state.css hides all four with
an unconditional `display: none` (operator request 2026-04-29), and no JS in
web/js toggles their display (main.js only writes their text, class and the
button's disabled state), so they are hidden on EVERY view, not only on
#home under ?ui_mock=1 as the row was filed. The same CSS block says
"Restore by removing rules". This file pins both halves:
- they stay hidden on every view, so the RM-1013 one-row measurement
  covers every footer item that can paint;
- the documented restore (those four rules deleted from the live CSSOM)
  keeps the footer ONE row with no horizontal overflow at the design
  baseline and at companion width, with a long build stamp and the longest
  latency text main.js writes, and the restored items sit on --fs-xs.

Measured before the fix (restore applied, headless Chromium): .latency-stat
and .analyze-stat rendered at 12px, below the --fs-xs (16px) floor, at both
widths; at 923x1280 the restored row overflowed the footer by 340px (376px
with the 60-character stamp: analyze, ANALYZE NOW and #frame-count pushed
past the edge; independent verifier measurement). Now the three status
text items take the RM-1013 stamp treatment (min-width 0, ellipsis) and
the font token, and the stamp gives way first (flex-shrink), since it keeps
its full text in its title and they do not. At 923 they are squeezed to a
few characters each (filed for a companion-width priority call); at 1920
every one shows whole beside the 60-character stamp.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

VIEWPORTS = [(1920, 920), (923, 1280)]

VIEWS = [
    "home", "lobby", "champ-select", "active-match", "last-match", "session",
    "history", "replay", "user-builds", "build-insights", "settings",
]

STATUS_IDS = ["input-latency-footer", "analyze-footer", "analyze-now", "frame-count"]

# Synthetic stamp (as test_footer_version_stamp RM-1013) and the longest
# latency line main.js `LAT.footer.textContent` writes (5-digit ms, n in 3
# digits); written ASCII-escaped, main.js joins the parts with U+00B7.
_LONG_RC_VERSION = "9.8.7-rc.12+build.20261027.0123456789abcdef"
_LATENCY_TEXT = "latency avg 12345ms \u00b7 p95 23456ms \u00b7 n=999"


def _json_route(payload):
    body = json.dumps(payload)
    return lambda route: route.fulfill(
        status=200, content_type="application/json", body=body
    )


def _open(pw_browser, mock_server, width, height, stamped=False):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    if stamped:
        page.route("**/api/ui-version", _json_route({"v": "0a1b2c3d"}))
        page.route(
            "**/api/health",
            _json_route({"alive": True, "rc_version": _LONG_RC_VERSION}),
        )
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1#home",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function("document.body.dataset.view === 'home'", timeout=10_000)
    if stamped:
        page.wait_for_selector("footer .ui-version", state="attached", timeout=10_000)
    page.evaluate("document.fonts.ready.then(() => true)")
    page.wait_for_timeout(400)
    return ctx, page, errors


_DISPLAYS = """
(ids) => ids.map(id => {
  const el = document.getElementById(id);
  return {id, inFooter: !!(el && el.closest('footer')),
          display: el ? getComputedStyle(el).display : null};
})
"""


def test_status_items_stay_hidden_on_every_view(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, 1920, 920)
    seen = {}
    try:
        for view in VIEWS:
            page.evaluate(f"location.hash = '#{view}'")
            page.wait_for_function(
                f"document.body.dataset.view === '{view}'", timeout=10_000
            )
            seen[view] = page.evaluate(_DISPLAYS, STATUS_IDS)
    finally:
        page.close()
        ctx.close()
    # anchor: every view was reached and every item exists in the footer.
    assert sorted(seen) == sorted(VIEWS), seen
    for view, rows in seen.items():
        assert all(r["inFooter"] for r in rows), (view, rows)
        shown = [r for r in rows if r["display"] != "none"]
        assert not shown, f"#{view}: footer status items paint: {shown}"
    assert not errors, f"JS errors: {errors[:3]}"


# Delete the four map_state.css hide rules from the CSSOM - the restore the
# CSS comment documents - then fill the items with their longest real text.
_RESTORE = """
([ids, latency]) => {
  const sels = new Set(ids.map(id => '#' + id));
  let removed = 0;
  // map_state.css reaches the page through dashboard.css @import, so walk
  // imported sheets too.
  const walk = (sheet) => {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { return; }
    for (let i = rules.length - 1; i >= 0; i--) {
      const r = rules[i];
      if (r.styleSheet) { walk(r.styleSheet); continue; }
      if (r.selectorText && sels.has(r.selectorText.trim())
          && r.style && r.style.display === 'none') {
        sheet.deleteRule(i);
        removed++;
      }
    }
  };
  for (const sheet of document.styleSheets) walk(sheet);
  document.getElementById('input-latency-footer').textContent = latency;
  document.getElementById('analyze-footer').textContent = 'analyze running';
  document.getElementById('frame-count').textContent = '123456 frames';
  return removed;
}
"""

_ROW = """
(ids) => {
  const f = document.querySelector('footer');
  const fr = f.getBoundingClientRect();
  const pillH = f.querySelector('#mode-pill').getBoundingClientRect().height;
  const items = ids.map(id => {
    const el = document.getElementById(id);
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return {id, display: cs.display, fontSize: parseFloat(cs.fontSize),
            ws: cs.whiteSpace, w: r.width, h: r.height,
            clipped: el.scrollWidth > el.clientWidth,
            left: r.left, right: r.right, top: r.top, bottom: r.bottom};
  });
  const fsXs = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--fs-xs'));
  return {items, pillH, fsXs, footerH: fr.height, footerTop: fr.top,
          footerBottom: fr.bottom, footerLeft: fr.left, footerRight: fr.right,
          footerOverflow: f.scrollWidth - f.clientWidth,
          docOverflow: document.documentElement.scrollWidth
            - document.documentElement.clientWidth};
}
"""


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_restored_status_items_keep_the_footer_one_row(
    mock_server, pw_browser, width, height
):
    ctx, page, errors = _open(pw_browser, mock_server, width, height, stamped=True)
    try:
        removed = page.evaluate(_RESTORE, [STATUS_IDS, _LATENCY_TEXT])
        page.wait_for_timeout(100)
        m = page.evaluate(_ROW, STATUS_IDS)
    finally:
        page.close()
        ctx.close()
    # anchor: exactly the four documented hide rules were removed and every
    # status item now paints.
    assert removed == 4, removed
    assert all(i["display"] != "none" and i["w"] > 0 for i in m["items"]), m["items"]
    assert m["fsXs"] >= 16, m["fsXs"]
    for i in m["items"]:
        assert i["fontSize"] >= m["fsXs"], f"{width}x{height}: {i['id']} at {i['fontSize']}px"
        assert i["ws"] == "nowrap", i
        assert i["h"] <= m["pillH"] + 0.5, (
            f"{width}x{height}: {i['id']} wrapped to {i['h']}px (pill {m['pillH']}px)"
        )
        assert m["footerTop"] <= i["top"] and i["bottom"] <= m["footerBottom"], (
            f"{width}x{height}: {i['id']} leaves the footer band: {i}"
        )
        assert i["left"] >= m["footerLeft"] and i["right"] <= m["footerRight"] + 0.5, (
            f"{width}x{height}: {i['id']} runs past the footer edge: {i}"
        )
    # at the design baseline the row has room: the restored text shows whole.
    if width >= 1920:
        clipped = [i["id"] for i in m["items"] if i["clipped"]]
        assert not clipped, f"{width}x{height}: status text truncated: {clipped}"
    assert m["footerOverflow"] <= 0, f"{width}x{height}: footer overflows by {m['footerOverflow']}px"
    assert m["docOverflow"] <= 0, f"{width}x{height}: page overflows by {m['docOverflow']}px"
    assert not errors, f"JS errors: {errors[:3]}"
