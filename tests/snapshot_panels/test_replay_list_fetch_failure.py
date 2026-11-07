"""
tests/snapshot_panels/test_replay_list_fetch_failure.py
S144-U-210 (s144 uiux): the Replay view's RECENT MATCHES list says the
matches did not load when its fetch FAILS, instead of saying the match store
is empty, and the next visit to the view fetches again.

THE DEFECT. web/js/panels/dev.js `_replayViewRefresh` mapped an HTTP error
reply to `null`, and `null` reached the same branch as a real empty list:
the list read "no matches in rewind_history.db". MEASURED in headless
Chromium, ui_mock and live /api paths alike, with the list reply answered by
HTTP 500: "no matches in rewind_history.db" - a false statement (the store
may hold hundreds of matches; the server failed). A reply that rejects (a
network error, or a body that is not JSON) only logged a warning, so the
list stayed on the page-open "loading..." for good. Under ?ui_mock=1 the
failed fixture promise was also cached, so leaving the view and coming back
never fetched again. And two list replies in flight (the view left and
re-entered before the first answered) painted in ARRIVAL order, so an older
failed reply landing last replaced the newer list.

THE FIX. A failed list fetch (HTTP error, rejected fetch, unparsable body,
a reply with no `matches` array) paints "matches did not load - reopen
Replay to retry"; the cached mock promise is dropped on failure; only the
newest list request paints. A real empty list still reads "no matches in
rewind_history.db".

WHAT IS MEASURED (rendered text, never a grep), 1920x920 baseline:
  - ui_mock and live: the list reply answered by HTTP 500 renders the
    failure line, not the empty-store line;
  - live: a network error (aborted request) and a non-JSON 200 body render
    the failure line, not "loading...";
  - ui_mock and live: a real empty reply (`matches: []`) still renders the
    empty-store line (failure and empty are told apart);
  - ui_mock and live: after a failure, with the reply restored, leaving the
    view and coming back renders the real rows (the failure is not cached);
  - live: an older failed reply that lands after a newer good one leaves the
    newer rows in place.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MOCK = (Path(__file__).resolve().parents[2]
         / "web" / "data" / "ui_mock" / "replay.json")
_LIST = "#replay-match-list"
_FAIL_LINE = "matches did not load - reopen Replay to retry"
_EMPTY_LINE = "no matches in rewind_history.db"
_LIVE_GLOB = "**/api/replay/matches*"
_MOCK_GLOB = "**/data/ui_mock/replay.json"

_SETTLED = """() => {
  const ul = document.querySelector('#replay-match-list');
  if (!ul || !ul.checkVisibility()) return false;
  if (ul.querySelector('.replay-match-row')) return true;
  const t = ul.textContent.trim();
  return t && t !== 'loading...';
}"""


def _fixture_matches():
    return json.loads(_MOCK.read_text(encoding="utf-8"))["matches"]


def _ok_live(route):
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps({"matches": _fixture_matches()}))


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


def _empty(route):
    route.fulfill(status=200, content_type="application/json",
                  body='{"matches": []}')


def _new_page(pw_browser):
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    return ctx, page, errors


def _seq(handlers):
    """A route handler that answers its Nth request with handlers[N]; past
    the end, the last handler keeps answering."""
    calls = {"n": 0}

    def _h(route):
        i = min(calls["n"], len(handlers) - 1)
        calls["n"] += 1
        handlers[i](route)
    _h.calls = calls
    return _h


def _goto(page, mock_server, mock):
    q = "/?ui_mock=1#replay" if mock else "/#replay"
    page.goto(mock_server.url + q, wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_function("document.body.dataset.view === 'replay'",
                           timeout=10_000)


def _settled_text(page):
    page.wait_for_function(_SETTLED, timeout=10_000)
    return page.inner_text(_LIST).strip()


def _row_ids(page):
    return page.eval_on_selector_all(
        "#replay-match-list .replay-match-row",
        "(rows) => rows.map((r) => r.dataset.matchId)")


def _leave_and_return(page):
    page.evaluate("location.hash = '#home'")
    page.wait_for_function("document.body.dataset.view === 'home'",
                           timeout=10_000)
    page.evaluate("location.hash = '#replay'")
    page.wait_for_function("document.body.dataset.view === 'replay'",
                           timeout=10_000)


@pytest.mark.parametrize("mock", [True, False], ids=["ui_mock", "live"])
def test_http_error_says_did_not_load_not_empty_store(
        mock, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_MOCK_GLOB if mock else _LIVE_GLOB, _fail)
        _goto(page, mock_server, mock)
        text = _settled_text(page)
        rows = _row_ids(page)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert rows == [], rows
    assert text == _FAIL_LINE, (
        f"a 500 list reply rendered {text!r}, not {_FAIL_LINE!r}")
    assert _EMPTY_LINE not in text, text


@pytest.mark.parametrize("handler", [_abort, _not_json],
                         ids=["network_error", "not_json"])
def test_rejected_fetch_says_did_not_load_not_loading(
        handler, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_LIVE_GLOB, handler)
        _goto(page, mock_server, False)
        try:
            page.wait_for_function(_SETTLED, timeout=5_000)
        except Exception:  # noqa: BLE001 - the red state never settles
            pass
        text = page.inner_text(_LIST).strip()
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert text == _FAIL_LINE, (
        f"a rejected list fetch left {text!r}, not {_FAIL_LINE!r}")


@pytest.mark.parametrize("mock", [True, False], ids=["ui_mock", "live"])
def test_real_empty_list_still_says_empty_store(
        mock, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_MOCK_GLOB if mock else _LIVE_GLOB, _empty)
        _goto(page, mock_server, mock)
        text = _settled_text(page)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert text == _EMPTY_LINE, text


@pytest.mark.parametrize("mock", [True, False], ids=["ui_mock", "live"])
def test_failure_is_retried_on_the_next_visit(mock, mock_server, pw_browser):
    mock_server._store["data"] = {}
    want = [m["match_id"] for m in _fixture_matches()]
    assert want, "the replay fixture carries no matches"
    ctx, page, errors = _new_page(pw_browser)
    try:
        handler = _seq([_fail, _ok_mock if mock else _ok_live])
        page.route(_MOCK_GLOB if mock else _LIVE_GLOB, handler)
        _goto(page, mock_server, mock)
        first = _settled_text(page)
        _leave_and_return(page)
        page.wait_for_selector("#replay-match-list .replay-match-row",
                               timeout=10_000)
        rows = _row_ids(page)
        calls = handler.calls["n"]
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert first == _FAIL_LINE, first
    assert calls >= 2, f"the list was fetched {calls} time(s)"
    assert rows == want, rows


def test_older_failed_reply_never_replaces_newer_rows(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    want = [m["match_id"] for m in _fixture_matches()]
    held: list = []

    def _hold_first_then_ok(route):
        if not held:
            held.append(route)
            return
        _ok_live(route)

    ctx, page, errors = _new_page(pw_browser)
    try:
        page.route(_LIVE_GLOB, _hold_first_then_ok)
        _goto(page, mock_server, False)
        for _ in range(100):
            if held:
                break
            page.wait_for_timeout(100)
        assert len(held) == 1, "the first list request was not held"
        _leave_and_return(page)
        page.wait_for_selector("#replay-match-list .replay-match-row",
                               timeout=10_000)
        _fail(held[0])
        page.evaluate(
            "() => new Promise((ok) => setTimeout(() =>"
            " requestAnimationFrame(() => requestAnimationFrame(ok)), 300))")
        rows = _row_ids(page)
        text = page.inner_text(_LIST).strip()
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert rows == want, (rows, text)
    assert _FAIL_LINE not in text, text
