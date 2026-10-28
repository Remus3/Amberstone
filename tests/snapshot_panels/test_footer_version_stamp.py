"""
tests/snapshot_panels/test_footer_version_stamp.py
RM-1012 (s144 uiux): the footer build stamp `footer .ui-version` (created
by web/js/main.js autoReload `stampFooter`) paints only when it carries a
stamp, and when it does it renders at the footer chip height.

Measured before this slice (headless Chromium, ?ui_mock=1, #home, 1920x920):
- empty stamp (no `rc_version` in /api/health and no `v` in
  /api/ui-version - the mock-server case) rendered as a 16x4px --surface
  speck: `footer .ui-version` in web/css/panels/input_activity.css keeps
  padding 2px 8px and its background on an empty span;
- a real stamp ("RC <ver> . ui <hash>", the live case) rendered 20px tall
  next to the 24px #mode-pill / #voice-toggle chips RM-1010 aligned (that
  slice measured the mock, where the stamp is empty, so it never saw it).

The stamped case fulfils /api/health and /api/ui-version per page through
Playwright routing with synthetic values; the mock server is untouched.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

# 1920x920 = design baseline with Chrome chrome; 923x1280 = companion width.
VIEWPORTS = [(1920, 920), (923, 1280)]

_RC_VERSION = "9.8.7"
_UI_HASH = "0a1b2c3d"


def _json_route(payload):
    body = json.dumps(payload)
    return lambda route: route.fulfill(
        status=200, content_type="application/json", body=body
    )


def _open(pw_browser, mock_server, width, height, stamped):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    if stamped:
        page.route("**/api/ui-version", _json_route({"v": _UI_HASH}))
        page.route(
            "**/api/health",
            _json_route({"alive": True, "rc_version": _RC_VERSION}),
        )
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1#home",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function("document.body.dataset.view === 'home'", timeout=10_000)
    # stampFooter creates the span on the first /api/ui-version answer.
    page.wait_for_selector("footer .ui-version", state="attached", timeout=10_000)
    page.evaluate("document.fonts.ready.then(() => true)")
    page.wait_for_timeout(500)
    return ctx, page, errors


_STAMP = """
() => {
  const f = document.querySelector('footer');
  const fr = f.getBoundingClientRect();
  const el = f.querySelector('.ui-version');
  const r = el.getBoundingClientRect();
  const pill = f.querySelector('#mode-pill').getBoundingClientRect();
  return {text: el.textContent, display: getComputedStyle(el).display,
          w: r.width, h: r.height, mid: r.top + r.height / 2,
          pillH: pill.height, footerMid: fr.top + fr.height / 2};
}
"""


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_empty_stamp_paints_nothing(mock_server, pw_browser, width, height):
    ctx, page, errors = _open(pw_browser, mock_server, width, height, False)
    try:
        m = page.evaluate(_STAMP)
    finally:
        page.close()
        ctx.close()
    # anchor: this case really is the empty stamp the mock produces.
    assert m["text"] == "", m
    assert m["display"] == "none" or (m["w"] == 0 and m["h"] == 0), (
        f"{width}x{height}: empty footer stamp still paints: {m}"
    )
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_stamp_renders_at_footer_chip_height(mock_server, pw_browser, width, height):
    ctx, page, errors = _open(pw_browser, mock_server, width, height, True)
    try:
        m = page.evaluate(_STAMP)
    finally:
        page.close()
        ctx.close()
    # anchor: both halves of the stamp reached the span.
    assert f"RC {_RC_VERSION}" in m["text"] and f"ui {_UI_HASH}" in m["text"], m
    assert m["display"] != "none" and m["w"] > 0, m
    assert abs(m["h"] - m["pillH"]) <= 0.5, (
        f"{width}x{height}: stamp {m['h']}px vs mode pill {m['pillH']}px"
    )
    assert abs(m["mid"] - m["footerMid"]) <= 1, (
        f"stamp centre {m['mid']} off the footer centre {m['footerMid']}"
    )
    assert not errors, f"JS errors: {errors[:3]}"
