"""
tests/snapshot_panels/test_settings_review_r30.py
R30 page-9 (Settings) per-page DESIGN review - regression coverage for the
full-pass slice (2026-06-23, ledger 608).

gemini's view-job: "predictable, centralized control for thresholds and
connections; the trap is scattering feature flags across active views." The
panel already met that (9 domain-grouped cards, scattering avoided), so the
operator picked the two enhancements:

  B. density/compaction - tighter card gap + head margin so the sparse
     single-toggle cards (CHAMP SELECT / DISPLAY) waste less vertical space.
     (Cosmetic - verified by the recon + 5-phase audit, not asserted here.)
  C. quick-filter - a search box above the card grid that shows only the
     cards matching the typed keyword (head or any row text); empty shows all.
     Makes any setting findable instantly and scales as the panel grows.

Drive path: /?ui_mock=1#settings -> the static settings cards render under
#settings-body; #settings-filter-input drives _settingsApplyFilter.
"""
import pytest


def _open_settings(pw_browser, mock_server, width=1920, height=1080):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    url = mock_server.url + "/?ui_mock=1#settings"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector("#settings-filter-input", timeout=10_000)
    return ctx, page, errors


# Overlay item 4A consolidated the VOICE / CHAMP SELECT / PRE-GAME LOBBY /
# POST GAME REVIEW cards into one CLIENT SETTINGS card (each a sub-group), so
# the card-level filter now matches on CLIENT SETTINGS (it carries the Voice
# text) and DISPLAY is the non-matching card that hides.
_CARD_STATE_JS = """() => {
  const cards = [...document.querySelectorAll('#settings-body .settings-card')];
  const find = (t) => cards.find(c => {
    const h = c.querySelector('.settings-card-head');
    return h && h.textContent.trim().toUpperCase() === t;
  });
  const vis = (c) => c ? (!c.hidden && getComputedStyle(c).display !== 'none') : null;
  return {
    client: vis(find('CLIENT SETTINGS')),
    display: vis(find('DISPLAY')),
    total: cards.length,
    shown: cards.filter(vis).length,
  };
}"""


def test_settings_filter_hides_nonmatching(mock_server, pw_browser):
    """C: typing a keyword shows only the matching cards."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        page.fill("#settings-filter-input", "voice")
        page.wait_for_function(
            "() => { const cards = [...document.querySelectorAll("
            "'#settings-body .settings-card')];"
            " return cards.some(c => c.hidden); }",
            timeout=5_000,
        )
        st = page.evaluate(_CARD_STATE_JS)
        assert st["client"] is True, "CLIENT SETTINGS card should match 'voice' (Voice group)"
        assert st["display"] is False, "DISPLAY should be hidden by 'voice' filter"
        assert st["shown"] < st["total"], "filter did not hide any cards"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_settings_filter_clear_shows_all(mock_server, pw_browser):
    """C: clearing the filter restores every card."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        page.fill("#settings-filter-input", "voice")
        page.wait_for_function(
            "() => [...document.querySelectorAll("
            "'#settings-body .settings-card')].some(c => c.hidden)",
            timeout=5_000,
        )
        page.fill("#settings-filter-input", "")
        page.wait_for_function(
            "() => [...document.querySelectorAll("
            "'#settings-body .settings-card')].every(c => !c.hidden)",
            timeout=5_000,
        )
        st = page.evaluate(_CARD_STATE_JS)
        assert st["shown"] == st["total"], "clearing filter should show all cards"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
