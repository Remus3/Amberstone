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

CodeQL py/incomplete-url-substring (alerts 78-83): every webfont host test
here and in _webfont_stub was a substring test, so a look-alike URL
(`https://x.example/?q=fonts.googleapis.com`,
`https://fonts.googleapis.com.evil.example/`) counted as Google Fonts. They
all go through _webfont_stub.url_has_host, an exact hostname match; the
browser-free tests at the end pin it on the helper, on the routes the stub
installs and on _watch_font_traffic.
"""
import pytest

from tests.snapshot_panels import _webfont_stub
from tests.snapshot_panels._webfont_stub import (
    CSS_HOST,
    FACE_HOST,
    STUB_APPLIED,
    STUB_CSS,
    STUB_FONT_URL,
    OfflineWebfontBrowser,
    url_has_host,
)
from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_replay_timeline_rows_and_grid_reach import (
    _load_first_match,
)

_HOSTS = (CSS_HOST, FACE_HOST)


def _is_font_host(url):
    return any(url_has_host(url, h) for h in _HOSTS)


def _watch_font_traffic(ctx):
    """Record every webfont request, response body kind and failure."""
    seen = {"requests": [], "css": [], "faces": [], "failed": []}

    def on_response(resp):
        url = resp.url
        if url_has_host(url, CSS_HOST):
            seen["css"].append(resp.text() == STUB_CSS)
        elif url_has_host(url, FACE_HOST):
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


# --- exact host matching, no browser (CodeQL alerts 78-83) -------------------

_CSS_URL = ("https://fonts.googleapis.com/css2"
            "?family=Lato:wght@100;300;400;700;900&display=swap")
_REAL_URLS = {"fonts.googleapis.com": _CSS_URL,
              "fonts.gstatic.com": STUB_FONT_URL}
# Each shape carries a font host as a SUBSTRING by construction (so the old
# `host in url` test matched it) while its hostname is some other host.
_LOOKALIKE_SHAPES = (
    "https://x.example/?q={h}",
    "https://{h}.evil.example/s/rc-stub/lato-stub.ttf",
    "https://evil.example/{h}/css2?family=Lato",
    "https://not{h}/css2",
    "https://{h}@evil.example/css2",
    "https://x.example/#{h}",
)
_LOOKALIKES = tuple(s.format(h=h) for h in _HOSTS for s in _LOOKALIKE_SHAPES)


def test_url_has_host_matches_the_exact_hostname_only():
    assert len(_LOOKALIKES) == 2 * len(_LOOKALIKE_SHAPES) == 12
    for host, url in _REAL_URLS.items():
        assert _webfont_stub.url_has_host(url, host), url
        assert _webfont_stub.url_has_host(url.replace(host, host.upper()), host)
    # Each real URL names one host, never the other.
    assert not _webfont_stub.url_has_host(_CSS_URL, "fonts.gstatic.com")
    assert not _webfont_stub.url_has_host(STUB_FONT_URL, "fonts.googleapis.com")
    for url in _LOOKALIKES:
        for host in _HOSTS:
            assert not _webfont_stub.url_has_host(url, host), (url, host)
    # A URL urlsplit cannot parse is no host, not a crash in a route.
    assert not _webfont_stub.url_has_host("https://[fonts.gstatic.com/x", "fonts.gstatic.com")


class _RouteRecorder:
    """Stands in for a Playwright Page or BrowserContext: records route()."""

    def __init__(self):
        self.routes = []

    def route(self, matcher, handler):
        self.routes.append((matcher, handler))


def _assert_css_then_face(routes):
    assert len(routes) == 2, routes
    (css, _), (face, _) = routes
    assert css(_CSS_URL) and not css(STUB_FONT_URL)
    assert face(STUB_FONT_URL) and not face(_CSS_URL)
    for url in _LOOKALIKES:
        assert not css(url), url
        assert not face(url), url


def test_the_stub_routes_match_the_font_hosts_exactly():
    page = _RouteRecorder()
    _webfont_stub.route_stub_webfont(page, lambda route: None)
    _assert_css_then_face(page.routes)

    ctx = _RouteRecorder()
    _webfont_stub.route_offline_webfont(ctx)
    _assert_css_then_face(ctx.routes)


class _EventRecorder:
    """Stands in for a BrowserContext: records on(event, callback)."""

    def __init__(self):
        self.handlers = {}

    def on(self, event, callback):
        self.handlers.setdefault(event, []).append(callback)

    def fire(self, event, obj):
        for cb in self.handlers.get(event, []):
            cb(obj)


class _Msg:
    def __init__(self, url, body=""):
        self.url = url
        self._body = body

    def text(self):
        return self._body


def test_watch_font_traffic_counts_the_font_hosts_exactly():
    ctx = _EventRecorder()
    seen = _watch_font_traffic(ctx)
    assert set(ctx.handlers) == {"request", "response", "requestfailed"}
    for url in _LOOKALIKES:
        for event in ctx.handlers:
            ctx.fire(event, _Msg(url, STUB_CSS))
    assert seen == {"requests": [], "css": [], "faces": [], "failed": []}, seen

    for event in ctx.handlers:
        ctx.fire(event, _Msg(_CSS_URL, STUB_CSS))
        ctx.fire(event, _Msg(STUB_FONT_URL))
    assert seen == {"requests": [_CSS_URL, STUB_FONT_URL], "css": [True],
                    "faces": [STUB_FONT_URL],
                    "failed": [_CSS_URL, STUB_FONT_URL]}, seen
