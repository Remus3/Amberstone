"""
tests/snapshot_panels/test_session_review_r30.py
R30 page-4 (Session) per-page DESIGN review - regression coverage for the
full-pass slice (2026-06-23, ledger 605).

gemini's view-job for Session: "track daily tilt, fatigue, and cumulative
performance limits; the trap is polluting the daily trend with all-time
averages." The view avoided the trap (every stat is session-scoped) but did
not DO the job - it was a flat summary (Overview / Performance / Champions /
Matches) with no tilt/fatigue signal, plus the Champions list duplicated the
Matches list for varied sessions, and the 2-up grid collided the Modes value
at companion width. This slice:

  A. a session tilt/fatigue verdict + a within-session grade trend strip
     (chronological, oldest->newest), derived from d.matches already in hand
     (grade + timestamp per game) - no backend change. The mock ends on the
     session-worst game (B+ after S-/A-/A/S/A) at 3h27m in, so it reads as a
     declining/fatigue (warn) session.
  B. companion fix - the .session-grid single-columns at <=1200px so the long
     Modes value stops colliding with its label.
  C. de-redundancy - CHAMPIONS THIS SESSION is reframed to REPLAYED CHAMPIONS
     (multi-game champs only; hidden when none), the only rows that are NOT
     already in the Matches list; the duplicated OVERVIEW "Started" row (the
     header sub already shows the start time) is removed.

Drive path: /?ui_mock=1#session -> _sessionFetchAndRender renders the
/data/ui_mock/session.json fixture. Landing signal: #session-games flips
from "-" to the fixture game count.
"""
import pytest
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_session(pw_browser, mock_server, width=1920, height=1080):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    url = mock_server.url + "/?ui_mock=1#session"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.querySelector('#session-games') && "
        "document.querySelector('#session-games').textContent.trim() !== '-' && "
        "document.querySelector('#session-games').textContent.trim() !== ''",
        timeout=10_000,
    )
    return ctx, page, errors


def test_session_trend_renders(mock_server, pw_browser):
    """A: the tilt/fatigue trend renders - a chronological (oldest->newest)
    grade strip + a verdict. The mock ends on the session-worst game so it
    reads as a declining (warn) session."""
    ctx, page, errors = _open_session(pw_browser, mock_server)
    try:
        wrap = page.locator("#session-trend")
        assert wrap.is_visible(), "session trend not visible"
        chips = page.eval_on_selector_all(
            "#session-trend-strip .session-trend-chip", "els => els.map(e => e.textContent.trim())"
        )
        assert len(chips) == 6, f"expected 6 trend chips, got {len(chips)}: {chips}"
        assert chips[0] == "S", f"first (oldest) chip {chips[0]!r} != S"
        assert chips[-1] == "B", f"last (newest) chip {chips[-1]!r} != B"
        text = (page.locator("#session-trend-text").text_content() or "").strip()
        assert text, "trend verdict text empty"
        kind = page.evaluate(
            "() => document.querySelector('#session-trend').dataset.kind"
        )
        assert kind == "warn", f"declining session should read warn, got {kind!r}"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#view-session").screenshot(
            path=str(SCREENSHOTS / "session-review-r30.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_session_champions_multi_game_only(mock_server, pw_browser):
    """C: the Champions card is reframed to REPLAYED CHAMPIONS - only champs
    played 2+ times this session (the rows NOT already in Matches). Jinx (2g)
    stays; the 1-game champs drop."""
    ctx, page, errors = _open_session(pw_browser, mock_server)
    try:
        # head reframed
        heads = page.eval_on_selector_all(
            ".session-card-head", "els => els.map(e => e.textContent.trim())"
        )
        assert any("REPLAYED" in h.upper() for h in heads), (
            f"REPLAYED CHAMPIONS head not found: {heads}"
        )
        champ_text = (
            page.locator("#session-champs").text_content() or ""
        )
        assert "Jinx" in champ_text, "multi-game champ Jinx missing"
        assert "Kai'Sa" not in champ_text, "1-game champ Kai'Sa should be filtered out"
        assert "Tristana" not in champ_text, "1-game champ Tristana should be filtered out"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_session_overview_started_row_removed(mock_server, pw_browser):
    """C: the OVERVIEW 'Started' row is removed - it duplicated the header sub
    ('started 11:42 AM'). The element is gone from the DOM."""
    ctx, page, errors = _open_session(pw_browser, mock_server)
    try:
        n = page.eval_on_selector_all(
            "#session-start", "els => els.length"
        )
        assert n == 0, "OVERVIEW 'Started' row (#session-start) should be removed"
        # the start time is still available in the header sub
        sub = (page.locator("#session-window").text_content() or "").strip()
        assert sub and sub != "-", "session header sub should still carry the window/start"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_session_companion_single_column(mock_server, pw_browser):
    """B: at companion width (923) the .session-grid single-columns so the
    long Modes value stops colliding with its label."""
    ctx, page, errors = _open_session(pw_browser, mock_server, width=923, height=1316)
    try:
        tracks = page.evaluate(
            "() => getComputedStyle(document.querySelector('.session-grid'))"
            ".gridTemplateColumns.trim().split(/\\s+/).length"
        )
        assert tracks == 1, f"session-grid should be single-column at 923, got {tracks} tracks"
        # no horizontal overflow at companion width
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth"
        )
        assert overflow <= 2, f"horizontal overflow at 923: {overflow}px"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
