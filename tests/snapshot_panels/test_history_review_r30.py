"""
tests/snapshot_panels/test_history_review_r30.py
R30 page-5 (History) per-page DESIGN review - regression coverage for the
full-pass slice (2026-06-23, ledger 606).

gemini's view-job for History: "filterable macro-trend analysis across the
2800-game database; the trap is weak filters killing specific matchup
queries." The filters were already strong + GLOBAL (champion/mode/result/
grade across the scope), so the trap was avoided - but a filter produced a
match LIST with no AGGREGATE: SEASON STATS stayed whole-scope, so "all my
Ahri games" never answered "how do I perform on Ahri." This slice:

  A. filtered aggregate - while any filter is active, SEASON STATS shows the
     filtered subset's total / win-rate / avg-KDA / most-played + a filtered
     header; it restores the whole-scope stats when filters clear. Turns the
     filter into the matchup-trend analysis the view is for.
  B. discoverability - the empty state advertises that the filters query
     globally (across all N matches), not only within a clicked session.
  C. companion - the 3-col .history-grid single-columns at <=1200px so the
     SESSIONS dates stop wrapping mid-date.

Drive path: /?ui_mock=1#history -> _historyFetchAndRender renders the 14d
scope of /data/ui_mock/history.json. The 14d scope has 14 matches; Jinx is
3 games (2W/1L -> 66.7% WR, avg KDA 4.78), so filtering champion=Jinx gives
deterministic filtered-aggregate values.
"""
import pytest
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_history(pw_browser, mock_server, width=1920, height=1080):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    url = mock_server.url + "/?ui_mock=1#history"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.querySelector('#history-season-total') && "
        "document.querySelector('#history-season-total').textContent.trim() === '14'",
        timeout=10_000,
    )
    return ctx, page, errors


def test_history_filtered_aggregate_updates_season_stats(mock_server, pw_browser):
    """A: filtering champion=Jinx makes SEASON STATS reflect the filtered
    subset (3 games, 66.7% WR, Jinx most-played, 4.78 avg KDA) + a filtered
    header."""
    ctx, page, errors = _open_history(pw_browser, mock_server)
    try:
        page.select_option("#history-filter-champion", label="Jinx")
        # the head retitles when filtered
        page.wait_for_function(
            "document.querySelector('#history-season-total').textContent.trim() === '3'",
            timeout=5_000,
        )
        head = (page.locator("#history-season-head").text_content() or "").strip()
        assert "JINX" in head.upper() or "FILTER" in head.upper(), f"head not filtered: {head!r}"
        wr = (page.locator("#history-season-wr").text_content() or "").strip()
        assert wr == "66.7%", f"filtered win-rate {wr!r} != 66.7%"
        fav = (page.locator("#history-season-fav").text_content() or "").strip()
        assert fav == "Jinx", f"filtered most-played {fav!r} != Jinx"
        kda = (page.locator("#history-season-kda").text_content() or "").strip()
        assert kda == "4.78", f"filtered avg KDA {kda!r} != 4.78"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#view-history").screenshot(
            path=str(SCREENSHOTS / "history-review-r30.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_history_filter_clear_restores_season_stats(mock_server, pw_browser):
    """A: clearing the champion filter restores the whole-scope SEASON STATS
    (14 games, 64.3% WR) and the 'SEASON STATS' header."""
    ctx, page, errors = _open_history(pw_browser, mock_server)
    try:
        page.select_option("#history-filter-champion", label="Jinx")
        page.wait_for_function(
            "document.querySelector('#history-season-total').textContent.trim() === '3'",
            timeout=5_000,
        )
        # clear back to All champions (value "")
        page.select_option("#history-filter-champion", value="")
        page.wait_for_function(
            "document.querySelector('#history-season-total').textContent.trim() === '14'",
            timeout=5_000,
        )
        head = (page.locator("#history-season-head").text_content() or "").strip()
        assert head.upper() == "SEASON STATS", f"head not restored: {head!r}"
        wr = (page.locator("#history-season-wr").text_content() or "").strip()
        assert wr == "64.3%", f"restored win-rate {wr!r} != 64.3%"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_history_empty_state_advertises_filtering(mock_server, pw_browser):
    """B: the default empty state advertises that filters query globally
    (mentions filtering + the total match count) rather than only telling the
    user to click a session."""
    ctx, page, errors = _open_history(pw_browser, mock_server)
    try:
        empty = (page.locator("#history-match-list").text_content() or "").strip().lower()
        assert "filter" in empty, f"empty state should advertise filtering: {empty!r}"
        assert "14" in empty, f"empty state should mention the match count: {empty!r}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_history_companion_single_column(mock_server, pw_browser):
    """C: at companion width (923) the 3-col .history-grid single-columns so
    the SESSIONS dates stop wrapping mid-date."""
    ctx, page, errors = _open_history(pw_browser, mock_server, width=923, height=1316)
    try:
        tracks = page.evaluate(
            "() => getComputedStyle(document.querySelector('.history-grid'))"
            ".gridTemplateColumns.trim().split(/\\s+/).length"
        )
        assert tracks == 1, f"history-grid should be single-column at 923, got {tracks} tracks"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
