"""
tests/snapshot_panels/test_home_summary_fetch_failure.py
S144-U-212 (s144 uiux): the Home view says its summary did not load when the
/api/home/summary fetch FAILS, instead of staying on "loading..." under a hero
that reads "no games yet today", and a failed mode-tab switch no longer leaves
the previous tab's matches, pick and chips under the new tab.

THE DEFECT. web/js/main.js `_homeFetchAndRender` mapped an HTTP error reply to
`null` and returned on it without painting, and its trailing catch swallowed a
rejected fetch (a network error, a body that is not JSON). MEASURED in headless
Chromium at 1920x920, ui_mock and live alike: with the reply answered by HTTP
500, aborted, or a non-JSON 200 body, RECENT 3 and THIS WEEK stay on the
page-open "loading..." and the hero sub-line on its authored "no games yet
today", a false statement about the match store. A 200 reply with no `recent`
array (the generic `{"ok": false}` answer) painted "no matches yet" and "no
games this week", false too: `dashboard/builders_home.py` `_build_home_summary`
always ships `recent` and `this_week`. Under ?ui_mock=1 the failed fixture
promise was cached, so the 20 s poll and every later visit re-read the cached
failure and never fetched again. A mode tab picked while the summary fetch
fails left the previous tab's match cards, Tonight's Pick and chip values in
place under the newly active tab.

THE FIX. A failed fetch (HTTP error, rejected fetch, unparsable body, a reply
with no `recent` array) paints "summary did not load - retrying" on the hero
sub-line, "matches did not load - retrying" in RECENT 3 and "week did not load
- retrying" in THIS WEEK, resets the KDA / CS chips to "-" and clears their
sparklines, hides Tonight's Pick, and keeps the W/L strip's empty-tab rule -
UNLESS the active tab already painted from a good reply, in which case a
failed poll keeps that paint (same scope, last good read). The cached mock
promise is dropped on failure, so the next poll or visit fetches again. A real
empty store still reads "no matches yet" / "no games this week".

WHAT IS MEASURED (rendered text, never a grep), 1920x920 baseline:
  - ui_mock and live: HTTP 500 renders the three failure lines and "-" chips;
  - live: an aborted request, a non-JSON body and a reply with no `recent`
    array render the failure lines;
  - live: a real empty store still renders "no matches yet" and "no games
    this week";
  - ui_mock and live: after a failure, with the reply restored, leaving the
    view and coming back renders the real match cards;
  - live: a mode tab whose fetch fails after a good ALL paint clears the old
    tab's cards, pick and chip values;
  - live: a failed refetch of the SAME tab after a good paint keeps the cards.
"""
import json
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MOCK = (Path(__file__).resolve().parents[2]
         / "web" / "data" / "ui_mock" / "home.json")
_RECENT = "#home-recent-list"
_WEEK = "#home-week-list"
_CARD = "#home-recent-list .home-recent-card"
_SUB_FAIL = "summary did not load - retrying"
_RECENT_FAIL = "matches did not load - retrying"
_WEEK_FAIL = "week did not load - retrying"
_LIVE_RE = re.compile(r"/api/home/summary")
_MOCK_GLOB = "**/data/ui_mock/home.json"

_SETTLED = """() => {
  const ul = document.querySelector('#home-recent-list');
  if (!ul) return false;
  if (ul.querySelector('.home-recent-card')) return true;
  const t = ul.textContent.trim();
  return !!t && t !== 'loading...';
}"""


def _ok(route):
    route.fulfill(status=200, content_type="application/json",
                  body=_MOCK.read_text(encoding="utf-8"))


def _fail(route):
    route.fulfill(status=500, content_type="application/json",
                  body='{"error": "internal"}')


def _abort(route):
    route.abort()


def _not_json(route):
    route.fulfill(status=200, content_type="application/json",
                  body="<html>proxy error</html>")


def _no_recent(route):
    route.fulfill(status=200, content_type="application/json",
                  body='{"ok": false}')


def _empty_live(route):
    # The builder's own empty shape: dashboard/builders_home.py
    # _build_home_summary starts from {"today": {}, "recent": [],
    # "this_week": []}.
    route.fulfill(status=200, content_type="application/json",
                  body='{"today": {}, "recent": [], "this_week": []}')


class _Switch:
    """A route handler whose behaviour the test swaps mid-run."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = 0

    def __call__(self, route):
        self.calls += 1
        self.handler(route)


def _new_page(pw_browser):
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    return ctx, page, errors


def _goto(page, mock_server, mock):
    q = "/?ui_mock=1#home" if mock else "/#home"
    page.goto(mock_server.url + q, wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_function("document.body.dataset.view === 'home'",
                           timeout=10_000)


def _settle(page, timeout=10_000):
    try:
        page.wait_for_function(_SETTLED, timeout=timeout)
    except Exception:  # noqa: BLE001 - the red state never settles
        pass


def _settle_frames(page, ms=400):
    page.evaluate(
        "(ms) => new Promise((ok) => setTimeout(() =>"
        " requestAnimationFrame(() => requestAnimationFrame(ok)), ms))", ms)


def _text(page, sel):
    return (page.text_content(sel) or "").strip()


def _read(page):
    return {
        "sub": _text(page, "#home-hero-sub"),
        "recent": _text(page, _RECENT),
        "week": _text(page, _WEEK),
        "kda": _text(page, "#home-hero-kda"),
        "cs": _text(page, "#home-hero-cs"),
        "cards": page.locator(_CARD).count(),
        "combo_hidden": page.evaluate(
            "document.getElementById('home-combo').hidden"),
        "sparks": page.evaluate(
            "document.querySelectorAll('.home-hero-spark *').length"),
    }


def _assert_failed(got):
    assert got["recent"] == _RECENT_FAIL, got
    assert got["week"] == _WEEK_FAIL, got
    assert got["sub"] == _SUB_FAIL, got
    assert got["kda"] == "-" and got["cs"] == "-", got
    assert got["cards"] == 0, got
    assert got["combo_hidden"] is True, got
    assert got["sparks"] == 0, got


def _leave_and_return(page):
    page.evaluate("location.hash = '#history'")
    page.wait_for_function("document.body.dataset.view === 'history'",
                           timeout=10_000)
    page.evaluate("location.hash = '#home'")
    page.wait_for_function("document.body.dataset.view === 'home'",
                           timeout=10_000)


@pytest.mark.parametrize("mock", [True, False], ids=["ui_mock", "live"])
def test_http_error_says_did_not_load(mock, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_MOCK_GLOB if mock else _LIVE_RE, _fail)
        _goto(page, mock_server, mock)
        _settle(page, timeout=5_000)
        got = _read(page)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    _assert_failed(got)


@pytest.mark.parametrize("handler", [_abort, _not_json, _no_recent],
                         ids=["network_error", "not_json", "no_recent"])
def test_rejected_or_shapeless_reply_says_did_not_load(
        handler, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_LIVE_RE, handler)
        _goto(page, mock_server, False)
        _settle(page, timeout=5_000)
        got = _read(page)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    _assert_failed(got)


def test_real_empty_store_still_says_empty(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_LIVE_RE, _empty_live)
        _goto(page, mock_server, False)
        _settle(page)
        got = _read(page)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["recent"] == "no matches yet", got
    assert got["week"] == "no games this week", got
    assert got["sub"] == "no games yet today", got


@pytest.mark.parametrize("mock", [True, False], ids=["ui_mock", "live"])
def test_next_visit_fetches_again_after_a_failure(mock, mock_server,
                                                  pw_browser):
    mock_server._store["data"] = {}
    want = len(json.loads(_MOCK.read_text(encoding="utf-8"))["recent"][:3])
    ctx, page, errors = _new_page(pw_browser)
    sw = _Switch(_fail)
    try:
        page.route(_MOCK_GLOB if mock else _LIVE_RE, sw)
        _goto(page, mock_server, mock)
        _settle(page, timeout=5_000)
        first = _text(page, _RECENT)
        sw.handler = _ok
        _leave_and_return(page)
        page.wait_for_function(
            f"document.querySelectorAll('{_CARD}').length === {want}",
            timeout=10_000)
        got = _read(page)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert first == _RECENT_FAIL, first
    assert got["cards"] == want, got
    assert got["sub"] != _SUB_FAIL, got


def test_failed_tab_switch_drops_the_previous_tab(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    sw = _Switch(_ok)
    try:
        page.route(_LIVE_RE, sw)
        _goto(page, mock_server, False)
        page.wait_for_function(
            f"document.querySelectorAll('{_CARD}').length > 0",
            timeout=10_000)
        before = _read(page)
        sw.handler = _fail
        n = sw.calls
        page.evaluate(
            "document.querySelector(\".home-mode-tab[data-hmode='SR']\")"
            ".click()")
        page.wait_for_function(
            f"document.querySelector('{_RECENT}').textContent.trim()"
            f" === '{_RECENT_FAIL}'", timeout=5_000)
        _settle_frames(page)
        got = _read(page)
        calls = sw.calls
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert before["cards"] > 0 and before["combo_hidden"] is False, before
    assert before["kda"] != "-", before
    assert calls > n, "the SR tab never fetched"
    _assert_failed(got)


def test_failed_refetch_of_the_same_tab_keeps_the_paint(mock_server,
                                                        pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    sw = _Switch(_ok)
    try:
        page.route(_LIVE_RE, sw)
        _goto(page, mock_server, False)
        page.wait_for_function(
            f"document.querySelectorAll('{_CARD}').length > 0",
            timeout=10_000)
        before = _read(page)
        sw.handler = _fail
        n = sw.calls
        _leave_and_return(page)
        deadline = 50
        while sw.calls <= n and deadline:
            page.wait_for_timeout(100)
            deadline -= 1
        _settle_frames(page)
        got = _read(page)
        calls = sw.calls
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert calls > n, "the return visit never refetched"
    assert got == before, (before, got)
