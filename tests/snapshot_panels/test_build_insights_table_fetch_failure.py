"""
tests/snapshot_panels/test_build_insights_table_fetch_failure.py
S144-U-209 (s144 uiux): a Build Insights table tab whose fetch FAILS says
its stats are unavailable, instead of telling the player to go play games,
and the next visit to the tab fetches again.

THE DEFECT. web/js/panels/build_insights.js `_fetch` ran one `finish(data)`
for every outcome: an HTTP error, a network error and an `ok: false` reply
all reached it as `null`, became `st.items = []` and `st.loaded = true`, and
`_render` painted the EMPTY-CORPUS line. MEASURED in headless Chromium under
/?ui_mock=1 with each table fixture answered by HTTP 500: Items read "No
item data yet - play a few games (need at least 20 buys per item).", and
Skills / Runes / Spells the same with their own unit. That is a false
instruction (the corpus may be full; the server failed), while the five
chart tabs on the same view already say "<Thing> stats unavailable." for a
failure and keep "Not enough ..." for a real empty corpus. And because
`loaded` was set, the failure stuck: switching tabs and back never fetched
again (the ui_mock path also cached the failed promise), until the Min
filter changed.

THE FIX. A failed fetch sets `st.failed`, leaves `loaded` false and drops
the cached mock promise; `_render` paints the tab's `failMsg` ("Item stats
unavailable." and so on, the chart tabs' wording). The next activation of
the tab fetches again. An empty `items` array still paints the empty line.

WHAT IS MEASURED (rendered text, never a grep), at the 1920x920 baseline:
  - each of the four table tabs, fixture answered by HTTP 500, renders its
    own unavailable line and NOT the "play a few games" line;
  - the same tab answered by a real empty reply (`items: []`) still renders
    the "No <x> data yet" line (failure and empty are told apart);
  - after a failure, with the fixture restored, leaving the tab and coming
    back renders the real table (the failure is not cached).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

# tab key -> (ui_mock fixture stem, unavailable line, empty-line prefix)
_TABLE_TABS = {
    "items": ("build_insights", "Item stats unavailable.",
              "No item data yet"),
    "skills": ("build_insights_skill", "Skill stats unavailable.",
               "No skill data yet"),
    "runes": ("rune_wpa", "Rune stats unavailable.", "No rune data yet"),
    "spells": ("summspell_wpa", "Spell stats unavailable.",
               "No spell data yet"),
}
_MOUNTS = {
    "items": "#bi-table-mount",
    "skills": "#bi-skill-table-mount",
    "runes": "#bi-rune-table-mount",
    "spells": "#bi-spell-table-mount",
}


def _open(pw_browser, mock_server, routes):
    """Open Build Insights under ?ui_mock=1 with `routes` (stem -> handler)
    installed BEFORE the first fetch."""
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    for stem, handler in routes.items():
        page.route(f"**/data/ui_mock/{stem}.json", handler)
    page.goto(mock_server.url + "/?ui_mock=1#build-insights",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.body.dataset.view === 'build-insights'", timeout=10_000)
    return ctx, page, errors


def _show(page, tab):
    page.click(f"#bi-tabs .bi-tab[data-bi-tab='{tab}']")
    page.wait_for_function(
        """(sel) => {
          const m = document.querySelector(sel);
          if (!m || !m.checkVisibility()) return false;
          const t = m.textContent.trim();
          return t && t !== 'loading...';
        }""", arg=_MOUNTS[tab], timeout=10_000)
    return page.inner_text(_MOUNTS[tab]).strip()


def _fail(route):
    route.fulfill(status=500, body="server error")


def _empty(route):
    route.fulfill(status=200, content_type="application/json",
                  body='{"ok": true, "items": []}')


def _mounts_exist(page):
    return page.evaluate(
        "(sels) => sels.filter((s) => !document.querySelector(s))",
        list(_MOUNTS.values()))


@pytest.mark.parametrize("tab", list(_TABLE_TABS))
def test_failed_fetch_says_unavailable_not_play_games(
        tab, mock_server, pw_browser):
    stem, unavailable, empty_prefix = _TABLE_TABS[tab]
    ctx, page, errors = _open(pw_browser, mock_server, {stem: _fail})
    try:
        assert not _mounts_exist(page), _mounts_exist(page)
        text = _show(page, tab)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert text == unavailable, (
        f"{tab}: a failed fetch rendered {text!r}, not {unavailable!r}")
    assert "play a few games" not in text, text
    assert not text.startswith(empty_prefix), text


@pytest.mark.parametrize("tab", list(_TABLE_TABS))
def test_empty_reply_keeps_the_empty_corpus_line(
        tab, mock_server, pw_browser):
    stem, unavailable, empty_prefix = _TABLE_TABS[tab]
    ctx, page, errors = _open(pw_browser, mock_server, {stem: _empty})
    try:
        text = _show(page, tab)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert text.startswith(empty_prefix), (
        f"{tab}: an empty reply rendered {text!r}")
    assert "play a few games" in text, text
    assert unavailable not in text, text


@pytest.mark.parametrize("tab", list(_TABLE_TABS))
def test_failure_is_not_cached_and_the_next_visit_fetches_again(
        tab, mock_server, pw_browser):
    stem, unavailable, _ = _TABLE_TABS[tab]
    state = {"fail": True, "hits": 0}

    def flaky(route):
        state["hits"] += 1
        if state["fail"]:
            _fail(route)
        else:
            route.continue_()

    ctx, page, errors = _open(pw_browser, mock_server, {stem: flaky})
    try:
        first = _show(page, tab)
        hits_after_fail = state["hits"]
        state["fail"] = False
        # Leave the tab for a chart tab, then come back.
        page.click("#bi-tabs .bi-tab[data-bi-tab='snowball']")
        page.wait_for_timeout(300)
        page.click(f"#bi-tabs .bi-tab[data-bi-tab='{tab}']")
        page.wait_for_selector(
            f"{_MOUNTS[tab]} table.bi-table", timeout=10_000)
        rows = page.locator(f"{_MOUNTS[tab]} table.bi-table tbody tr").count()
        second = page.inner_text(_MOUNTS[tab])
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert first == unavailable, first
    assert hits_after_fail >= 1, state
    assert state["hits"] > hits_after_fail, (
        f"{tab}: coming back to the tab did not fetch again: {state}")
    assert rows >= 1, f"{tab}: the retried fetch painted no table rows"
    assert unavailable not in second, second
