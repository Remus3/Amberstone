"""
tests/snapshot_panels/test_pgr_review_r30.py
R30 page-3 (Post Game Review) per-page DESIGN review - regression coverage
for the full-pass slice (2026-06-23, ledger 604).

The slow per-page design review found the PGR inverted its own job: gemini's
view-job is "autopsy the win/loss via turning points + anomalies", yet the
view opened on the Build tab (the ally/enemy scoreboard = gemini's NAMED
trap) with the actual autopsy buried in the 3rd tab, three "bad-game"
verdicts (grade / lobby-score / role-grade) read as redundant stamps with no
frame labels, and the tier-compare grid sat empty-by-default eating ~40% of
the hero. This slice:

  A. default landing tab -> AI Analysis (autopsy-first, not the scoreboard)
     + a one-line takeaway headline above the hero (the most actionable
     quick_review signal: my_chronic > a real wrong_team > a real right).
  B. frame captions disambiguating the verdicts (grade "Overall" / score
     "Lobby"; role-grade keeps its role label) - pure-CSS ::before.
  C. rank-compare collapses to the selector + a compact prompt when no tier
     is chosen (was an 8-cell dashes grid); the cells return once a rank is
     picked.
  D. the deferred token fold-in - PGR card radius --radius-sm -> --panel-radius
     (18px) on the focal cards (.lm-hero / .lm-section); chips/pills + the raw
     3px/4px literals -> --panel-radius-sm (10px). Operator-locked sub-floors
     (font/color at last_match.css :160/862/883/1138/1159/1225/1266) untouched.

Drive path mirrors test_last_match_view.py: /?ui_mock=1&mode=sr#last-match.
The SR fixture (web/data/ui_mock/last_match_sr.json) carries a populated
quick_review (my_chronic[0] = "Ahri R often held too long pre-6 spikes") and
NO enriched roster, so the takeaway + collapsed rank-compare + default-tab +
card-radius assertions all stand on authored, deterministic data.
"""
import pytest
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

_CHRONIC_TEXT = "Ahri R often held too long pre-6 spikes"


def _open_pgr(pw_browser, mock_server, mode="sr", width=1920, height=1080):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    url = mock_server.url + f"/?ui_mock=1&mode={mode}#last-match"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # mode tag flips from "-" to the fixture mode once renderLastMatch lands.
    page.wait_for_function(
        "document.querySelector('#lm-mode-tag') && "
        "document.querySelector('#lm-mode-tag').textContent.trim() !== '-' && "
        "document.querySelector('#lm-mode-tag').textContent.trim() !== ''",
        timeout=10_000,
    )
    return ctx, page, errors


def test_pgr_default_tab_is_ai_analysis(mock_server, pw_browser):
    """A1: fresh load (empty localStorage) opens on AI Analysis (the autopsy),
    NOT Build (the scoreboard = gemini's named trap)."""
    ctx, page, errors = _open_pgr(pw_browser, mock_server)
    try:
        ai_active = page.evaluate(
            "() => { const b = document.querySelector("
            "'#lm-tabbed-section .lm-tab[data-tab=\"ai-analysis\"]');"
            " return b ? b.classList.contains('is-active') : null; }"
        )
        assert ai_active is True, "AI Analysis tab not default-active"
        ai_panel_vis = page.evaluate(
            "() => { const p = document.querySelector("
            "'.lm-tab-panel[data-tab-panel=\"ai-analysis\"]');"
            " return p ? (!p.hasAttribute('hidden') && "
            "getComputedStyle(p).display !== 'none') : null; }"
        )
        assert ai_panel_vis is True, "AI Analysis panel not visible by default"
        build_hidden = page.evaluate(
            "() => { const p = document.querySelector("
            "'.lm-tab-panel[data-tab-panel=\"build\"]');"
            " return p ? (p.hasAttribute('hidden') || "
            "getComputedStyle(p).display === 'none') : null; }"
        )
        assert build_hidden is True, "Build (scoreboard) panel not hidden by default"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pgr_takeaway_headline(mock_server, pw_browser):
    """A2: the takeaway headline is visible + carries the most actionable
    quick_review signal (my_chronic first) with the 'Fix next game' label."""
    ctx, page, errors = _open_pgr(pw_browser, mock_server)
    try:
        wrap = page.locator("#lm-takeaway")
        assert wrap.is_visible(), "takeaway headline not visible"
        text = (page.locator("#lm-takeaway-text").text_content() or "").strip()
        assert text == _CHRONIC_TEXT, f"takeaway text {text!r} != chronic"
        label = (page.locator("#lm-takeaway-label").text_content() or "").strip()
        assert label.lower() == "fix next game", f"takeaway label {label!r}"
        kind = page.evaluate(
            "() => document.querySelector('#lm-takeaway').dataset.kind"
        )
        assert kind == "warn", f"takeaway kind {kind!r} != warn"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pgr_verdict_frame_captions(mock_server, pw_browser):
    """B: the grade + score verdict blocks carry a frame caption (::before)
    naming their reference frame (Overall / Lobby) so the three verdicts no
    longer read as redundant 'bad game' stamps."""
    ctx, page, errors = _open_pgr(pw_browser, mock_server)
    try:
        grade_before = page.evaluate(
            "() => getComputedStyle("
            "document.querySelector('#lm-grade-badge'), '::before').content"
        )
        assert "overall" in (grade_before or "").lower(), (
            f"grade frame caption missing: {grade_before!r}"
        )
        # The score is hidden in the no-roster fixture; un-hide it to read the
        # declared ::before so the CSS rule is asserted deterministically.
        page.eval_on_selector("#lm-hero-score", "el => el.hidden = false")
        score_before = page.evaluate(
            "() => getComputedStyle("
            "document.querySelector('#lm-hero-score'), '::before').content"
        )
        assert "lobby" in (score_before or "").lower(), (
            f"score frame caption missing: {score_before!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pgr_rank_compare_collapsed_when_empty(mock_server, pw_browser):
    """C: with no tier selected the rank-compare collapses - cells hidden,
    is-empty class set, selector + prompt still present (the affordance)."""
    ctx, page, errors = _open_pgr(pw_browser, mock_server)
    try:
        is_empty = page.evaluate(
            "() => document.querySelector('.lm-hero-rank-compare')"
            ".classList.contains('is-empty')"
        )
        assert is_empty is True, "rank-compare not collapsed when no tier"
        cell_hidden = page.evaluate(
            "() => { const c = document.querySelector("
            "'.lm-hero-rank-compare .lm-rank-cell');"
            " return c ? getComputedStyle(c).display === 'none' : null; }"
        )
        assert cell_hidden is True, "rank-compare cells not hidden when empty"
        sel_vis = page.locator("#lm-rank-select").is_visible()
        assert sel_vis, "rank selector (the affordance) not visible"
        prompt_vis = page.locator("#lm-rank-empty").is_visible()
        assert prompt_vis, "rank-empty prompt not visible when collapsed"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pgr_card_radius_tokens(mock_server, pw_browser):
    """D: the focal PGR cards (.lm-hero / .lm-section) carry --panel-radius
    (18px); the verdict chips carry --panel-radius-sm (10px). The deferred
    --radius-sm (8px) -> v2 token migration."""
    ctx, page, errors = _open_pgr(pw_browser, mock_server)
    try:
        hero_r = page.evaluate(
            "() => getComputedStyle(document.querySelector('.lm-hero'))"
            ".borderTopLeftRadius"
        )
        assert hero_r == "18px", f"hero card radius {hero_r!r} != 18px (--panel-radius)"
        section_r = page.evaluate(
            "() => { const s = document.querySelector('.lm-section');"
            " return s ? getComputedStyle(s).borderTopLeftRadius : null; }"
        )
        assert section_r == "18px", f"section card radius {section_r!r} != 18px"
        grade_r = page.evaluate(
            "() => getComputedStyle(document.querySelector('#lm-grade-badge'))"
            ".borderTopLeftRadius"
        )
        assert grade_r == "10px", f"grade chip radius {grade_r!r} != 10px (--panel-radius-sm)"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#view-last-match").screenshot(
            path=str(SCREENSHOTS / "pgr-review-r30_sr.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pgr_no_raw_radius_literals():
    """D guard: no raw px border-radius literals remain in last_match.css
    except the intentional 50% circles (portraits). Everything else routes
    through a --panel-radius* token."""
    css = (
        Path(__file__).resolve().parent.parent.parent
        / "web" / "css" / "panels" / "last_match.css"
    ).read_text(encoding="utf-8")
    import re

    offenders = []
    for m in re.finditer(r"border(?:-[a-z]+)*-radius\s*:\s*([^;]+);", css):
        val = m.group(1).strip()
        if "var(" in val or val == "50%":
            continue
        offenders.append(val)
    assert not offenders, f"raw radius literals remain: {offenders}"
