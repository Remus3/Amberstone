"""
tests/snapshot_panels/test_history_list_fetch_failure.py
S144-U-211 (s144 uiux): the History view's SESSIONS list says the sessions
did not load when its fetch FAILS, instead of staying on "loading..." or
saying the scope is empty, and the next visit (or scope pick) fetches again.

THE DEFECT. web/js/main.js `_historyFetchAndRender` mapped an HTTP error
reply to `null` and returned on it without painting, and its trailing
`.catch(() => {})` swallowed a rejected fetch (a network error, a body that
is not JSON). MEASURED in headless Chromium at 1920x920, ui_mock and live
/api/history alike: with the reply answered by HTTP 500, or aborted, or a
non-JSON 200 body, the list stays on the page-open "loading..." for good and
the count on "-". A 200 reply with no `sessions` array (the generic
`{"ok": false}` answer) painted "no sessions in scope", a false statement
about the match store. Under ?ui_mock=1 the failed fixture promise was
cached, so leaving the view and coming back never fetched again. And two
replies in flight (a scope tab picked before the first answered) painted in
ARRIVAL order, so an older reply landing last replaced the newer scope's
sessions under the newer scope's tab.

THE FIX. A failed fetch (HTTP error, rejected fetch, unparsable body, a reply
with no `sessions` array) paints "sessions did not load - reopen History to
retry" in the same li.home-empty slot, resets the count and the SEASON STATS
card to "-", and drops the previous scope's sessions and matches; the cached
mock promise is dropped on failure; only the newest request paints. A real
empty scope still reads "no sessions in scope".

WHAT IS MEASURED (rendered text, never a grep), 1920x920 baseline:
  - ui_mock and live: HTTP 500 renders the failure line, count "-";
  - live: an aborted request, a non-JSON body and a reply with no sessions
    array render the failure line;
  - ui_mock and live: a real empty scope still renders "no sessions in scope";
  - ui_mock and live: after a failure, with the reply restored, leaving the
    view and coming back renders the real sessions;
  - live: a scope pick whose fetch fails after a good scope clears the old
    scope's sessions, season stats and match list;
  - live: an older reply landing after a newer scope's reply leaves the
    newer scope's sessions in place.
"""
import json
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MOCK = (Path(__file__).resolve().parents[2]
         / "web" / "data" / "ui_mock" / "history.json")
_LIST = "#history-session-list"
_ROW = "#history-session-list .history-session-row"
_FAIL_LINE = "sessions did not load - reopen History to retry"
_EMPTY_LINE = "no sessions in scope"
_LIVE_RE = re.compile(r"/api/history\?")
_MOCK_GLOB = "**/data/ui_mock/history.json"

_SETTLED = """() => {
  const ul = document.querySelector('#history-session-list');
  if (!ul || !ul.checkVisibility()) return false;
  if (ul.querySelector('.history-session-row')) return true;
  const t = ul.textContent.trim();
  return t && t !== 'loading...';
}"""


def _mock_payload():
    return json.loads(_MOCK.read_text(encoding="utf-8"))


def _scope(scope):
    return _mock_payload()["scopes"][scope]


def _ok_live(route):
    scope = re.search(r"scope=([a-z_0-9]+)", route.request.url)
    slice_ = _scope(scope.group(1) if scope else "14d")
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(slice_))


def _ok_mock(route):
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


def _no_sessions(route):
    route.fulfill(status=200, content_type="application/json",
                  body='{"ok": false}')


def _empty_live(route):
    route.fulfill(status=200, content_type="application/json",
                  body='{"scope": "14d", "sessions": [], "season_stats": {}}')


def _empty_mock(route):
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps({"scopes": {"14d": {
                      "sessions": [], "season_stats": {}}}}))


def _new_page(pw_browser):
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    return ctx, page, errors


def _seq(handlers):
    """Answer the Nth request with handlers[N]; past the end, the last."""
    calls = {"n": 0}

    def _h(route):
        i = min(calls["n"], len(handlers) - 1)
        calls["n"] += 1
        handlers[i](route)
    _h.calls = calls
    return _h


def _goto(page, mock_server, mock):
    q = "/?ui_mock=1#history" if mock else "/#history"
    page.goto(mock_server.url + q, wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_function("document.body.dataset.view === 'history'",
                           timeout=10_000)


def _settled_text(page, timeout=10_000):
    page.wait_for_function(_SETTLED, timeout=timeout)
    return page.inner_text(_LIST).strip()


def _dates(page):
    return page.eval_on_selector_all(
        _ROW, "(rows) => rows.map((r) => r.firstElementChild.textContent)")


def _text(page, sel):
    return (page.text_content(sel) or "").strip()


def _leave_and_return(page):
    page.evaluate("location.hash = '#home'")
    page.wait_for_function("document.body.dataset.view === 'home'",
                           timeout=10_000)
    page.evaluate("location.hash = '#history'")
    page.wait_for_function("document.body.dataset.view === 'history'",
                           timeout=10_000)


def _settle_frames(page, ms=300):
    page.evaluate(
        "(ms) => new Promise((ok) => setTimeout(() =>"
        " requestAnimationFrame(() => requestAnimationFrame(ok)), ms))", ms)


@pytest.mark.parametrize("mock", [True, False], ids=["ui_mock", "live"])
def test_http_error_says_did_not_load(mock, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_MOCK_GLOB if mock else _LIVE_RE, _fail)
        _goto(page, mock_server, mock)
        try:
            text = _settled_text(page, timeout=5_000)
        except Exception:  # noqa: BLE001 - the red state never settles
            text = page.inner_text(_LIST).strip()
        count = _text(page, "#history-session-count")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert text == _FAIL_LINE, (
        f"a 500 history reply left {text!r}, not {_FAIL_LINE!r}")
    assert count == "-", count


@pytest.mark.parametrize("handler", [_abort, _not_json, _no_sessions],
                         ids=["network_error", "not_json", "no_sessions"])
def test_rejected_or_shapeless_reply_says_did_not_load(
        handler, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_LIVE_RE, handler)
        _goto(page, mock_server, False)
        try:
            text = _settled_text(page, timeout=5_000)
        except Exception:  # noqa: BLE001 - the red state never settles
            text = page.inner_text(_LIST).strip()
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert text == _FAIL_LINE, (
        f"a failed history fetch left {text!r}, not {_FAIL_LINE!r}")


@pytest.mark.parametrize("mock", [True, False], ids=["ui_mock", "live"])
def test_real_empty_scope_still_says_empty(mock, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_MOCK_GLOB if mock else _LIVE_RE,
                   _empty_mock if mock else _empty_live)
        _goto(page, mock_server, mock)
        text = _settled_text(page)
        count = _text(page, "#history-session-count")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert text == _EMPTY_LINE, text
    assert count == "0 sessions", count


@pytest.mark.parametrize("mock", [True, False], ids=["ui_mock", "live"])
def test_failure_is_retried_on_the_next_visit(mock, mock_server, pw_browser):
    mock_server._store["data"] = {}
    want = [s["date"] for s in _scope("14d")["sessions"]]
    assert want, "the history fixture's 14d scope carries no sessions"
    ctx, page, errors = _new_page(pw_browser)
    try:
        handler = _seq([_fail, _ok_mock if mock else _ok_live])
        page.route(_MOCK_GLOB if mock else _LIVE_RE, handler)
        _goto(page, mock_server, mock)
        try:
            first = _settled_text(page, timeout=5_000)
        except Exception:  # noqa: BLE001 - the red state never settles
            first = page.inner_text(_LIST).strip()
        _leave_and_return(page)
        page.wait_for_selector(_ROW, timeout=10_000)
        dates = _dates(page)
        calls = handler.calls["n"]
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert first == _FAIL_LINE, first
    assert calls >= 2, f"history was fetched {calls} time(s)"
    assert dates == want, dates


def test_failed_scope_pick_drops_the_previous_scope(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_LIVE_RE, _seq([_ok_live, _fail]))
        _goto(page, mock_server, False)
        page.wait_for_selector(_ROW, timeout=10_000)
        page.click(_ROW)
        page.wait_for_selector("#history-match-list .history-match-row",
                               timeout=10_000)
        page.click("#history-scope-tabs .view-tab[data-scope='season']")
        page.wait_for_function(
            "(t) => document.querySelector('#history-session-list')"
            ".textContent.trim() === t", arg=_FAIL_LINE, timeout=5_000)
        _settle_frames(page)
        dates = _dates(page)
        count = _text(page, "#history-session-count")
        total = _text(page, "#history-season-total")
        wr = _text(page, "#history-season-wr")
        match_rows = page.eval_on_selector_all(
            "#history-match-list .history-match-row", "(r) => r.length")
        head = _text(page, "#history-detail-head")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert dates == [], dates
    assert count == "-", count
    assert (total, wr) == ("-", "-"), (total, wr)
    assert match_rows == 0, f"{match_rows} old-scope match rows still shown"
    assert head == "SELECT A SESSION", head


def test_older_reply_never_replaces_newer_scope(mock_server, pw_browser):
    mock_server._store["data"] = {}
    want = [s["date"] for s in _scope("season")["sessions"]]
    first14 = [s["date"] for s in _scope("14d")["sessions"]]
    assert want and want != first14, "fixture scopes do not differ"
    held: list = []

    def _hold_first_then_ok(route):
        if not held:
            held.append(route)
            return
        _ok_live(route)

    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_LIVE_RE, _hold_first_then_ok)
        _goto(page, mock_server, False)
        for _ in range(100):
            if held:
                break
            page.wait_for_timeout(100)
        assert len(held) == 1, "the first history request was not held"
        page.click("#history-scope-tabs .view-tab[data-scope='season']")
        page.wait_for_selector(_ROW, timeout=10_000)
        # Wait until the held 14d reply has reached the page, so a pass
        # means it was processed and dropped, not merely not yet read.
        with page.expect_event("requestfinished",
                               predicate=lambda r: r == held[0].request,
                               timeout=10_000):
            _ok_live(held[0])
        _settle_frames(page)
        dates = _dates(page)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert dates == want, (
        f"an older 14d reply landing last painted {dates!r} under the"
        f" season tab, not {want!r}")
