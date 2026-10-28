"""
tests/snapshot_panels/test_snapshot_webfont_offline.py
RM-1079 (s144 uiux): a page made by the shared snapshot helper
(test_focus_ring_token_sites._new_page, used by the Replay, Escape and
font-swap snapshot files) renders the same on every host, network or not.

web/css/dashboard.css @imports the Lato CSS from fonts.googleapis.com
(display=swap), which fetches the face from fonts.gstatic.com. Before this
slice only test_replay_filter_hit_targets' late-swap test routed those
requests to the local stub (RM-1078); every other page from _new_page
reached Google Fonts, so its _settle_layout wait, and the face its text was
measured in, depended on the network (the flake source before RM-1071).

_new_page now answers both hosts at the CONTEXT level with the stub
(_webfont_stub.route_offline_webfont). A test that wants other behaviour
routes at the PAGE level, which Playwright checks first: the font-swap
files abort the webfonts to force their faces, and the late-swap test holds
the face. This file pins all three halves: the default page is answered by
the stub and draws 'Lato' with it, nothing fails or leaves for Google
Fonts, and a page-level route still wins.

RM-1080: the rest of the snapshot directory (its own _new_page helpers
and about a hundred direct pw_browser.new_context calls) still reached
Google Fonts. The session pw_browser fixture now yields
OfflineWebfontBrowser, whose new_context and new_page install the stub on
every context they make, so no call site changes. The tests at the end pin
that a context made straight from the fixture, with no helper, is answered
by the stub, and that the wrapper still passes the rest of the Browser API
through (test_replay_pane_corner_brackets launches its second browser from
pw_browser.browser_type).
"""
import pytest

from tests.snapshot_panels._webfont_stub import (
    STUB_APPLIED,
    STUB_CSS,
    STUB_FONT_URL,
    OfflineWebfontBrowser,
)
from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_replay_timeline_rows_and_grid_reach import (
    _load_first_match,
)

_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")


def _is_font_host(url):
    return any(h in url for h in _HOSTS)


def _watch_font_traffic(ctx):
    """Record every webfont request, response body kind and failure."""
    seen = {"requests": [], "css": [], "faces": [], "failed": []}

    def on_response(resp):
        url = resp.url
        if "fonts.googleapis.com" in url:
            seen["css"].append(resp.text() == STUB_CSS)
        elif "fonts.gstatic.com" in url:
            seen["faces"].append(url)

    ctx.on("request", lambda r: _is_font_host(r.url)
           and seen["requests"].append(r.url))
    ctx.on("response", lambda r: _is_font_host(r.url) and on_response(r))
    ctx.on("requestfailed", lambda r: _is_font_host(r.url)
           and seen["failed"].append(r.url))
    return seen


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_default_page_serves_the_webfont_from_the_stub(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    seen = _watch_font_traffic(ctx)
    try:
        _load_first_match(page, mock_server)
        status = page.evaluate("document.fonts.status")
        applied = page.evaluate(STUB_APPLIED)
    finally:
        page.close()
        ctx.close()
    # Anchor: the page asked for the webfont at all, or an empty list below
    # would pass on a dashboard that dropped the @import.
    assert seen["requests"], "premise: the dashboard.css Lato @import fired"
    assert seen["css"] and all(seen["css"]), (
        f"a Google Fonts CSS response was not the stub CSS: {seen}"
    )
    assert seen["faces"] and set(seen["faces"]) == {STUB_FONT_URL}, (
        f"a face came from somewhere other than the stub: {seen}"
    )
    assert not seen["failed"], f"webfont requests failed: {seen['failed']}"
    assert status == "loaded", f"fonts settled as {status!r}"
    assert applied, "the stub face, not a fallback, draws 'Lato' text"
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_page_level_route_still_overrides_the_stub(mock_server, pw_browser):
    """The font-swap files abort the webfonts at the page level to force
    their faces; that must beat the context-level stub."""
    ctx, page, errors = _new_page(pw_browser, mock_server, VIEWPORTS[0])
    seen = _watch_font_traffic(ctx)
    page.route("**/fonts.googleapis.com/**", lambda route: route.abort())
    page.route("**/fonts.gstatic.com/**", lambda route: route.abort())
    try:
        _load_first_match(page, mock_server)
        applied = page.evaluate(STUB_APPLIED)
    finally:
        page.close()
        ctx.close()
    assert seen["failed"], "premise: the page-level abort saw the @import"
    assert not seen["css"], f"the stub answered past a page route: {seen}"
    assert not applied, "the stub face drew text past a page-level abort"
    assert not errors, f"JS errors: {errors[:3]}"


def test_the_fixture_browser_is_the_wrapper_and_passes_through(pw_browser):
    """RM-1080: every snapshot file gets the wrapper from the fixture,
    and the Browser API it does not override still answers."""
    assert isinstance(pw_browser, OfflineWebfontBrowser), type(pw_browser)
    assert pw_browser.browser_type.name == "chromium"
    assert pw_browser.is_connected()


@pytest.mark.parametrize("via", ["new_context", "new_page"])
def test_a_bare_fixture_context_serves_the_webfont_from_the_stub(
        mock_server, pw_browser, via):
    """RM-1080: a context made straight from the fixture, the way most
    snapshot files make theirs, installs no route itself and is still
    answered by the stub."""
    mock_server._store["data"] = {}
    opts = {"ignore_https_errors": True,
            "viewport": {"width": VIEWPORTS[0][0], "height": VIEWPORTS[0][1]}}
    if via == "new_context":
        ctx = pw_browser.new_context(**opts)
        page = ctx.new_page()
    else:
        page = pw_browser.new_page(**opts)
        ctx = page.context
    seen = _watch_font_traffic(ctx)
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        _load_first_match(page, mock_server)
        status = page.evaluate("document.fonts.status")
        applied = page.evaluate(STUB_APPLIED)
    finally:
        page.close()
        if via == "new_context":
            ctx.close()
    assert seen["requests"], "premise: the dashboard.css Lato @import fired"
    assert seen["css"] and all(seen["css"]), (
        f"a Google Fonts CSS response was not the stub CSS: {seen}"
    )
    assert seen["faces"] and set(seen["faces"]) == {STUB_FONT_URL}, (
        f"a face came from somewhere other than the stub: {seen}"
    )
    assert not seen["failed"], f"webfont requests failed: {seen['failed']}"
    assert status == "loaded", f"fonts settled as {status!r}"
    assert applied, "the stub face, not a fallback, draws 'Lato' text"
    assert not errors, f"JS errors: {errors[:3]}"
