"""
tests/snapshot_panels/test_replay_review_r30.py
R30 page-6 (Replay) per-page DESIGN review - regression coverage for the
"+ reorder timeline" full slice (2026-06-23).

gemini's view-job: "timestamped index of critical decision errors + objective
fights; the trap is trying to be a video player instead of an actionable event
timeline." The view shipped as a manual frame-scrubber + scoreboard grid with a
PASSIVE event ribbon below it - the named trap. This slice:

  1. Makes each timeline event CLICKABLE -> seeks the scrubber to the event's
     timestamp (nearest snapshot) + re-renders the grid at that frame.
     Converts the passive log into navigation (an "actionable event timeline").
  2. Hoists the timeline ABOVE the scoreboard grid so the event index reads as
     the hero (event-index-first), not the scrubber.
  3. ASCII hard-rule cleanup (the "<-" arrow + a box-drawing comment rule).

Drive path: /?ui_mock=1#replay -> click a match row -> the timeline populates
under #replay-events-section; clicking a row drives #replay-slider via the
dev.js scrubber.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
# ui_mock fixture snapshot minutes (web/data/ui_mock/replay.json).
_SNAP_MINUTES = [0, 10, 20, 30]


def _nearest_idx(clock_s):
    target_min = (clock_s or 0) / 60.0
    best_i, best_d = 0, 1e9
    for i, mn in enumerate(_SNAP_MINUTES):
        d = abs(mn - target_min)
        if d < best_d:
            best_d, best_i = d, i
    return best_i


def _open_replay(pw_browser, mock_server, width=1920, height=1080):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    url = mock_server.url + "/?ui_mock=1#replay"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector(".replay-match-row", timeout=10_000)
    return ctx, page, errors


def _select_first_match(page):
    page.click(".replay-match-row")
    page.wait_for_function(
        "() => document.querySelectorAll('.replay-events-row').length > 0",
        timeout=10_000,
    )


def test_replay_timeline_seeks_scrubber(mock_server, pw_browser):
    """1: clicking a timeline event seeks #replay-slider to the nearest
    snapshot index for that event's clock_s (the actionable-timeline fix)."""
    ctx, page, errors = _open_replay(pw_browser, mock_server)
    try:
        _select_first_match(page)
        # the scrubber starts at frame 0
        assert page.eval_on_selector("#replay-slider", "el => el.value") == "0"
        # pick the LATEST event (max data-clock) so the seek lands off frame 0
        clock = page.evaluate(
            "() => Math.max(...[...document.querySelectorAll("
            "'.replay-events-row')].map(r => Number(r.dataset.clock) || 0))"
        )
        expected = _nearest_idx(clock)
        assert expected > 0, f"fixture sanity: latest-event idx {expected} (clock {clock})"
        # click the row carrying that max clock (delegated handler -> seek)
        page.eval_on_selector(
            ".replay-events-list",
            "(list) => { const rows = [...list.querySelectorAll('.replay-events-row')];"
            " const row = rows.reduce((a, b) => (Number(b.dataset.clock) || 0) >"
            " (Number(a.dataset.clock) || 0) ? b : a); row.click(); }",
        )
        page.wait_for_function(
            f"() => document.querySelector('#replay-slider').value === '{expected}'",
            timeout=5_000,
        )
        val = page.eval_on_selector("#replay-slider", "el => el.value")
        assert val == str(expected), f"slider {val!r} != expected {expected}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_replay_timeline_above_grid(mock_server, pw_browser):
    """2: the timeline section precedes the scoreboard grid in DOM order
    (event-index-first hierarchy)."""
    ctx, page, errors = _open_replay(pw_browser, mock_server)
    try:
        _select_first_match(page)
        # DOCUMENT_POSITION_FOLLOWING (4): grid follows events => events first.
        order = page.evaluate(
            "() => { const ev = document.getElementById('replay-events-section');"
            " const grid = document.querySelector('.replay-grid-wrap');"
            " return ev.compareDocumentPosition(grid)"
            " & Node.DOCUMENT_POSITION_FOLLOWING; }"
        )
        assert order, "timeline section should precede the grid in DOM order"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """3: ASCII-only authored text in this slice's test file."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
