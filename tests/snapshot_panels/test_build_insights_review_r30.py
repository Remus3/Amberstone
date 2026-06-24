"""
tests/snapshot_panels/test_build_insights_review_r30.py
R30 page-8 (Build Insights) per-page DESIGN review - regression coverage
for the full-pass slice (2026-06-23).

gemini's view-job: "contextual efficacy of item paths against specific
comps; the trap is generic global pick rates instead of situational win
deltas." The four WPA tables already avoid that trap (personal
selection-bias-corrected residuals, not global pickrates), so the operator
picked the "full pass" enhancements:

  1+2. A confidence-weighted TAKEAWAY rail beside each WPA table - it names
       the strongest + weakest mover ranked by wpa_shrunk (the
       shrink-adjusted residual), so the most TRUSTWORTHY signal wins, not
       the noisiest raw number. Fills the ~650px desktop dead zone; stacks
       above the table at the companion width (headline-first). Answers the
       view's job question: "what do I build more / cut?".
  3.   The Min-N control relabels per active tab (Min buys / games / picks)
       and HIDES on the four chart tabs (which never read min_n).

Drive path: /?ui_mock=1#build-insights -> the Items table mounts from the
build_insights fixture; #bi-summary-items carries the takeaway.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _open_bi(pw_browser, mock_server, width=1920, height=1080):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    url = mock_server.url + "/?ui_mock=1#build-insights"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.querySelector('#bi-table-mount table.bi-table') !== null",
        timeout=10_000,
    )
    return ctx, page, errors


def test_bi_takeaway_strongest_weakest(mock_server, pw_browser):
    """1+2: the Items takeaway names the shrunk-best + shrunk-worst mover."""
    ctx, page, errors = _open_bi(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "() => { const s = document.querySelector('#bi-summary-items');"
            " return s && s.textContent.trim().length > 0; }",
            timeout=10_000,
        )
        txt = page.inner_text("#bi-summary-items")
        up = txt.upper()
        assert "STRONGEST" in up, f"no STRONGEST block: {txt!r}"
        assert "WEAKEST" in up, f"no WEAKEST block: {txt!r}"
        # wpa_shrunk ranking: Experimental Hexplate best, Edge of Night worst.
        assert "Experimental Hexplate" in txt, f"strongest item missing: {txt!r}"
        assert "Edge of Night" in txt, f"weakest item missing: {txt!r}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_bi_takeaway_confidence_weighted(mock_server, pw_browser):
    """1+2: the WEAKEST is chosen by wpa_shrunk, not raw wpa. On the Skills
    fixture the raw-worst is Corki (-0.1362, n=25) but the shrink-adjusted
    worst is Kog'Maw (-0.1167, n=39) - the rail must surface the trustworthy
    one (Kog'Maw), proving the confidence weighting is live."""
    ctx, page, errors = _open_bi(pw_browser, mock_server)
    try:
        page.click("#bi-tabs .bi-tab[data-bi-tab='skills']")
        page.wait_for_function(
            "() => { const s = document.querySelector('#bi-summary-skills');"
            " return s && s.textContent.trim().length > 0; }",
            timeout=10_000,
        )
        txt = page.inner_text("#bi-summary-skills")
        assert "Renata Glasc" in txt, f"shrunk-strongest skill missing: {txt!r}"
        assert "Kog'Maw" in txt, (
            f"expected shrunk-worst Kog'Maw (not raw-worst Corki): {txt!r}"
        )
        assert "Corki" not in txt, (
            f"raw-worst Corki must NOT be the weakest by wpa_shrunk: {txt!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_bi_min_n_label_per_tab(mock_server, pw_browser):
    """3: the Min-N control relabels per tab + hides on a chart tab."""
    ctx, page, errors = _open_bi(pw_browser, mock_server)
    try:
        lbl = page.locator(".bi-controls label")
        assert lbl.inner_text().strip().lower() == "min buys", (
            f"items label should read 'Min buys', got {lbl.inner_text()!r}"
        )
        # Skills -> the unit is games.
        page.click("#bi-tabs .bi-tab[data-bi-tab='skills']")
        page.wait_for_function(
            "() => document.querySelector('.bi-controls label')"
            ".textContent.trim().toLowerCase() === 'min games'",
            timeout=5_000,
        )
        # Game Length is a chart tab -> the control hides (no min_n consumer).
        page.click("#bi-tabs .bi-tab[data-bi-tab='duration']")
        page.wait_for_function(
            "() => { const c = document.querySelector('.bi-controls');"
            " return c && (c.hidden || getComputedStyle(c).display === 'none'); }",
            timeout=5_000,
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text in this slice's test file."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
