"""
tests/snapshot_panels/test_settings_client_reorg.py
Overlay item 4 - out-of-game Settings menu reorg (Sections A + B).

Spec: docs/specs/2026-07-11-overlay-item4-client-settings-reorg-design.md.
This slice reworks the #settings-body card grid (web/index.html):

  A. Rename the CHAMP SELECT card to CLIENT SETTINGS and consolidate the
     Champ Select / Pre-Game Lobby / Post Game Review / Voice groups into it,
     each as its own labelled sub-group (.settings-subhead). PGR sub-renames:
     "Rank-tier comparison" -> "Rank-Tier"; "Baseline window (prior games)"
     -> "Baseline Games".
  B. Remove the COACHING ACTIONS, HEADLESS LOOP and DATA / METRICS cards from
     the Settings view (their dev.js wiring is null-guarded, so dropping the
     markup is safe).
  C. API SPEND GATES + DISPLAY stay.

Headless DOM structural coverage through the same mock-server + Playwright
harness as test_settings_view.py (the reproducible stand-in for the live
self-signed-HTTPS :8888 check). The 5-phase visual fixture audit is deferred
to the interactive audit session (this run is headless-only); these tests pin
the STRUCTURE the audit will style.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"

# Element ids that MUST still resolve after the consolidation (dev.js /
# main.js wire these by id; a rename/move that dropped one silently breaks a
# control). Grouped by the sub-section they move into.
_MOVED_CONTROL_IDS = [
    "set-force-flash-snowball", "set-push-runes", "set-push-spells", "set-push-build",
    "set-lobby-auto-accept", "set-lobby-party-default",
    "set-pgr-rank-tier", "set-pgr-baseline", "set-pgr-baseline-val",
    "set-voice-on", "set-voice-name",
]

# Card heads that must NOT appear in the settings view any more (Section B).
_REMOVED_HEADS = ["COACHING ACTIONS", "HEADLESS LOOP", "DATA / METRICS"]


def _open_settings(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    url = mock_server.url + "/?ui_mock=1#settings"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.body.dataset.view === 'settings' && "
        "document.querySelector('#view-settings .settings-card') !== null",
        timeout=10_000,
    )
    return ctx, page, errors


def _card_heads(page):
    return page.evaluate(
        "Array.from(document.querySelectorAll("
        "'#settings-body .settings-card > .settings-card-head'))"
        ".map(function(e){return (e.textContent||'').trim();})"
    )


def test_client_settings_card_present(mock_server, pw_browser):
    """The renamed CLIENT SETTINGS card exists and is the first static card."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        heads = _card_heads(page)
        assert "CLIENT SETTINGS" in heads, f"CLIENT SETTINGS head missing; heads={heads}"
        assert "CHAMP SELECT" not in heads, (
            f"stale CHAMP SELECT card head still present; heads={heads}"
        )
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#view-settings").screenshot(
            path=str(SCREENSHOTS / "settings_client_reorg.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [client reorg]: {errors[:3]}"


def test_client_settings_subgroups(mock_server, pw_browser):
    """The four moved-in groups render as labelled sub-heads inside the one
    CLIENT SETTINGS card (Section A consolidation)."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        subheads = page.evaluate(
            "Array.from(document.querySelectorAll("
            "'#settings-body .settings-card .settings-subhead'))"
            ".map(function(e){return (e.textContent||'').trim();})"
        )
        for want in ["Champ Select", "Pre-Game Lobby", "Post Game Review", "Voice"]:
            assert want in subheads, f"sub-head {want!r} missing; subheads={subheads}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [subgroups]: {errors[:3]}"


def test_removed_cards_absent(mock_server, pw_browser):
    """Section B: Coaching actions / Headless loop / Data-Metrics cards gone."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        heads = _card_heads(page)
        for gone in _REMOVED_HEADS:
            assert gone not in heads, f"removed card {gone!r} still present; heads={heads}"
        # API Spend Gates + Display are retained.
        assert "API SPEND GATES" in heads, f"API SPEND GATES dropped; heads={heads}"
        assert "DISPLAY" in heads, f"DISPLAY dropped; heads={heads}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [removed cards]: {errors[:3]}"


def test_pgr_sub_renames(mock_server, pw_browser):
    """PGR label renames land and the old phrasings are gone."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        txt = page.evaluate(
            "document.querySelector('#settings-body').textContent || ''"
        )
        assert "Rank-Tier" in txt, "renamed 'Rank-Tier' label missing"
        assert "Baseline Games" in txt, "renamed 'Baseline Games' label missing"
        assert "Rank-tier comparison" not in txt, "stale 'Rank-tier comparison' present"
        assert "Baseline window" not in txt, "stale 'Baseline window' present"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [pgr renames]: {errors[:3]}"


def test_moved_controls_still_resolve(mock_server, pw_browser):
    """Every relocated control id still resolves inside the settings view, so
    the dev.js / main.js wiring keyed on those ids is intact."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        missing = page.evaluate(
            "(ids) => ids.filter(function(id){"
            "return document.querySelector('#view-settings #'+id) === null;})",
            _MOVED_CONTROL_IDS,
        )
        assert not missing, f"control ids no longer resolve in settings: {missing}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [moved controls]: {errors[:3]}"


def test_no_non_ascii_bytes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in this file."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s) in {__file__}: {offenders[:5]}"
