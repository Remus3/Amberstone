"""
tests/snapshot_panels/test_route_matcher_no_wide_interception_rm1506.py
RM-1506: a callable Playwright route matcher sends EVERY request of its context
through the Python process, so a snapshot context's route must be a string glob
or a compiled regex.

playwright._impl._helper.RouteHandler.prepare_interception_patterns cannot hand a
function to the driver, so one callable matcher widens the whole context's
interception to the glob **/*. RM-1080 installed two of them on every snapshot
context, and a dashboard page load makes about 225 requests. Measured 2026-11-05
on a plain page-load loop: 5950 KB of Python memory and 26400 objects stayed
reachable per page after ctx.close() and gc.collect() (Route, Task, frame,
inspect.FrameInfo), against 381 KB and 811 with a regex; workers reached 1.5 GB on
this directory alone, and the collector's pause grew with that heap while holding
the GIL the mock server and the Playwright dispatcher both need.

test_a_page_load_sends_only_the_font_requests_to_python pins the behaviour on a
real browser, the pattern test pins Playwright's own decision, and the AST guard
stops a new callable matcher before it reaches a browser.
"""
import ast
import re
from urllib.parse import urlsplit

import pytest
from playwright._impl._helper import RouteHandler

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check
from tests.snapshot_panels import _route_match, _webfont_stub
from tests.snapshot_panels.conftest import _WS_STUB

_WIDE = {"glob": "**/*"}


def _font_host(url):
    return (_webfont_stub.url_has_host(url, _webfont_stub.CSS_HOST)
            or _webfont_stub.url_has_host(url, _webfont_stub.FACE_HOST))


def test_a_fixture_context_never_asks_for_wide_interception(pw_browser):
    ctx = pw_browser.new_context()
    try:
        routes = ctx._impl_obj._routes
        assert len(routes) == 2, "premise: both font routes are installed"
        patterns = RouteHandler.prepare_interception_patterns(routes)
    finally:
        ctx.close()
    assert len(patterns) == 2, patterns
    assert _WIDE not in patterns, patterns


def test_a_stub_page_route_never_asks_for_wide_interception(pw_browser):
    ctx = pw_browser.new_context()
    page = ctx.new_page()
    try:
        _webfont_stub.route_stub_webfont(page, lambda route: None)
        patterns = RouteHandler.prepare_interception_patterns(page._impl_obj._routes)
    finally:
        page.close()
        ctx.close()
    assert len(patterns) == 2, patterns
    assert _WIDE not in patterns, patterns


def test_a_page_load_sends_only_the_font_requests_to_python(mock_server, pw_browser):
    """The driver decides by the pattern, so a local request that reaches the
    context's Python route dispatcher means interception is wide again."""
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    impl = ctx._impl_obj
    original = impl._on_route
    reached_python = []

    async def spy(route):
        reached_python.append(route.request.url)
        return await original(route)

    impl._on_route = spy
    requested = []
    ctx.on("request", lambda r: requested.append(r.url))
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    try:
        page.goto(mock_server.url + "/?ui_mock=1", wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function("document.fonts.status === 'loaded'", timeout=10_000)
    finally:
        page.close()
        ctx.close()
    local = [u for u in requested if not _font_host(u)]
    # Anchor: an empty page would pass the assertion below with nothing routed.
    assert len(local) >= 20, f"premise: the dashboard boots its module graph: {len(local)}"
    assert any(_font_host(u) for u in requested), "premise: the Lato @import fired"
    stray = [u for u in reached_python if not _font_host(u)]
    assert not stray, f"{len(stray)} of {len(local)} local requests reached Python: {stray[:3]}"
    assert reached_python, "the font routes never fired, so nothing was measured"


# --- the matchers themselves, no browser --------------------------------------

_PATH_CORPUS = (
    "http://127.0.0.1:51234/api/state",
    "http://127.0.0.1:51234/api/state?x=1",
    "http://127.0.0.1:51234/api/state#frag",
    "http://localhost/api/state",
    "http://127.0.0.1:51234/api/state/",
    "http://127.0.0.1:51234/api/states",
    "http://127.0.0.1:51234/x/api/state",
    "http://127.0.0.1:51234/?next=/api/state",
    "http://127.0.0.1:51234/#/api/state",
    "http://127.0.0.1:51234/api/state2?x=/api/state",
    "https://example.test/api/state",
    "https://example.test/api%2Fstate",
    "http://127.0.0.1:51234/API/STATE",
)


@pytest.mark.parametrize("url", _PATH_CORPUS)
def test_on_path_answers_what_the_lambda_it_replaced_answered(url):
    """A differential on the corpus: each site used
    `lambda u: urlsplit(u).path == P`, so a regex that drifts from it would
    change which request a stub answers."""
    assert bool(_route_match.on_path("/api/state").search(url)) == (urlsplit(url).path == "/api/state")


def test_on_host_differs_from_the_callable_on_userinfo():
    """The known divergence _route_match.on_host records, kept on purpose: if
    this flips, its comment is wrong."""
    url = "https://user@fonts.gstatic.com/s/x.woff2"
    assert _webfont_stub.url_has_host(url, _webfont_stub.FACE_HOST)
    assert not _route_match.on_host(_webfont_stub.FACE_HOST).search(url)


def test_on_path_takes_a_literal_path():
    assert _route_match.on_path("/api/a.b").search("http://h/api/a.b")
    assert not _route_match.on_path("/api/a.b").search("http://h/api/axb")


# --- the AST guard ------------------------------------------------------------

_ALLOWED_CALLS = {"on_host", "on_path", "compile"}
_ROUTE_CALL = re.compile(r"\.(?:un)?route\s*\(")


def _matcher_of(call):
    """The matcher a .route / .unroute call passes: its first positional
    argument, else its `url=` keyword (Playwright's name for it), else a `**`
    splat. None when the call passes none of them."""
    if call.args:
        return call.args[0]
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    return keywords.get("url", keywords.get(None))


def _callable_matchers(source):
    """(line, matcher text) of every .route / .unroute whose matcher is not a
    string or a regex, positional or `url=`. A bare name and a `**` splat are
    refused too: they cannot be read here.

    NOT COMPLETE: this reads the syntax of a call on an attribute named route
    or unroute, so it cannot see an alias (`r = ctx.route; r(lambda u: True, h)`),
    `getattr(ctx, "route")(...)`, or `on_host` rebound to something that returns
    a function. Those stay uncaught here; the behaviour tests above would only
    see one on the contexts they build themselves."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("route", "unroute")):
            continue
        matcher = _matcher_of(node)
        if matcher is None:
            continue
        if isinstance(matcher, (ast.JoinedStr, ast.BinOp)):
            continue
        if isinstance(matcher, ast.Constant) and isinstance(matcher.value, str):
            continue
        if isinstance(matcher, ast.Call):
            name = matcher.func.attr if isinstance(matcher.func, ast.Attribute) else getattr(matcher.func, "id", "")
            if name in _ALLOWED_CALLS:
                continue
        found.append((node.lineno, ast.unparse(matcher)))
    return found


def test_the_guard_sees_each_callable_shape():
    bad = ("ctx.route(lambda u: True, h)\n"
           "page.route(is_mine, h)\n"
           "page.route(make_matcher(), h)\n"
           "page.unroute(lambda u: True)\n")
    assert [line for line, _ in _callable_matchers(bad)] == [1, 2, 3, 4]
    good = ("ctx.route('**/api/x', h)\n"
            "ctx.route(f'**/{name}', h)\n"
            "ctx.route('**/' + name, h)\n"
            "ctx.route(re.compile('x'), h)\n"
            "ctx.route(on_host('x'), h)\n"
            "ctx.route(_route_match.on_path('/x'), h)\n")
    assert _callable_matchers(good) == []


def test_the_guard_reads_a_url_keyword(tmp_path):
    """Playwright names the argument `url`, so the keyword form widens the
    context exactly as the positional form does and has to fail the same way."""
    site = tmp_path / "keyword_site.py"
    site.write_text("ctx.route(url=lambda u: True, handler=h)\n"
                    "page.route(handler=h, url=is_mine)\n"
                    "page.route(url=make_matcher(), handler=h)\n"
                    "page.unroute(url=lambda u: True)\n"
                    "page.route(**options)\n", encoding="utf-8")
    found = _callable_matchers(site.read_text(encoding="utf-8"))
    assert [line for line, _ in found] == [1, 2, 3, 4, 5], found
    good = ("ctx.route(url='**/api/x', handler=h)\n"
            "ctx.route(handler=h, url=re.compile('x'))\n"
            "ctx.route(url=_route_match.on_path('/x'), handler=h)\n"
            "router.route()\n"
            "router.route(mode='aram')\n")
    assert _callable_matchers(good) == []


def _scan(paths, root=REPO_ROOT):
    """(files that call .route or .unroute, the callable matchers in them)."""
    sites = 0
    findings = []
    for path in paths:
        source = path.read_text(encoding="utf-8", errors="replace")
        if not _ROUTE_CALL.search(source):
            continue
        sites += 1
        findings += [f"{relative_posix(path, root)}:{line}: {text}" for line, text in _callable_matchers(source)]
    return sites, findings


def _audit(paths):
    sites, findings = _scan(paths)
    # Anchor: an empty enumeration would pass the assertion below.
    assert sites >= 40, f"premise: the snapshot directory routes: {sites} files"
    assert not findings, findings


def test_the_scan_reports_a_keyword_site_in_a_file(tmp_path):
    (tmp_path / "keyword_site.py").write_text(
        "ctx.route (url=lambda u: True, handler=h)\n", encoding="utf-8")
    assert _scan(tmp_path.glob("*.py"), tmp_path) == (
        1, ["keyword_site.py:1: lambda u: True"])


def test_the_audit_does_not_pass_on_an_empty_enumeration():
    with pytest.raises(AssertionError, match="premise"):
        _audit([])


def test_no_tracked_python_routes_with_a_callable_matcher():
    self_check()
    _audit(iter_repo_files())
