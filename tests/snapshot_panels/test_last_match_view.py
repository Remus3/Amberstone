"""
tests/snapshot_panels/test_last_match_view.py
Post Game Review (Last Match) VIEW snapshot coverage - SR + ARAM + Arena
(C3, 2026-06-06).

Renders the full-page Post Game Review view (#view-last-match) for SR, ARAM,
and Arena against the ui_mock fixtures through the headless mock-server +
Playwright harness. Reproducible stand-in for the live self-signed-HTTPS
:8888 visual check: Claude_Preview cannot attach the self-signed cert and
1-PC (ADR-011) has no separate-machine MCP visual path, so the C-phase
visual validation runs here in CI. Mirrors test_champ_select_view.py (C1)
and test_active_match_view.py (C2).

Drive path: /?ui_mock=1&mode=<mode>#last-match. main.js boot flips
body.dataset.uiMock; the #last-match hash routes to the PGR view and its
activate hook calls fetchAndRenderLastMatch (last_match.js). With the dev
mock toggle on AND ?mode=sr|aram|arena, _lmMockUrl resolves
/data/ui_mock/last_match_<mode>.json and renderLastMatch paints the
fixture instead of the live /api/last-match feed. The SR fixture +
_lmMockUrl sr branch are new this session so SR (#14) has the same
CI-durable coverage as ARAM (#15) / Arena (#16).

_setHero stamps #lm-mode-tag from the fixture mode ("Ranked Solo" / "ARAM"
/ "ARENA") - it starts as "-", so waiting for it to change is the
landing signal AND the per-mode differentiator (mirroring C1's data-cs-mode
and C2's draft-elo gate). Asserts per mode: the view mounts, the hero
champion name + grade render, the mode tag matches, and no unhandled JS
errors fire. Arena shows the neutral ARENA result pill (CHERRY subteam
mode); SR shows VICTORY (win, non-arena). Screenshots each for the trail.
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"

# The fixture mode string _setHero stamps into #lm-mode-tag (the per-mode
# differentiator + the async-render landing signal; #lm-mode-tag starts "-").
_MODE_TAG = {"sr": "Ranked Solo", "aram": "ARAM", "arena": "ARENA"}


def _open_last_match(pw_browser, mock_server, mode):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> no live game overrides the fixture render; the
    # #last-match hash routes the PGR view and its activate hook fires
    # fetchAndRenderLastMatch against the mock fixture.
    mock_server._store["data"] = {}

    # Spec 1920x1080 design baseline (docs/UI_SCALE_SPEC_V2.md) so the
    # capture + no-scroll hierarchy assertions match the operator monitor.
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    url = mock_server.url + f"/?ui_mock=1&mode={mode}#last-match"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for renderLastMatch -> _setHero to replace the placeholder "-"
    # mode tag with the fixture's mode (proves the async fixture render
    # landed; the pre-render placeholder is "-").
    page.wait_for_function(
        "document.querySelector('#lm-mode-tag') && "
        "document.querySelector('#lm-mode-tag').textContent.trim() !== '-' && "
        "document.querySelector('#lm-mode-tag').textContent.trim() !== ''",
        timeout=10_000,
    )
    return ctx, page, errors


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_last_match_view_renders(mode, mock_server, pw_browser):
    ctx, page, errors = _open_last_match(pw_browser, mock_server, mode)
    try:
        view = page.locator("#view-last-match")
        assert view.is_visible(), f"#view-last-match not visible (mode={mode})"

        # Hero rendered from the fixture: champion name populated.
        champ = (page.locator("#lm-champion-name").text_content() or "").strip()
        assert champ and champ != "-", f"hero champion not rendered (mode={mode})"

        # Mode tag is the per-mode differentiator (fixture-controlled).
        tag = (page.locator("#lm-mode-tag").text_content() or "").strip()
        assert tag == _MODE_TAG[mode], (
            f"mode tag {tag!r} != {_MODE_TAG[mode]!r} (mode={mode})"
        )

        # Grade badge rendered.
        grade = (page.locator("#lm-grade-badge").text_content() or "").strip()
        assert grade and grade != "-", f"grade badge empty (mode={mode})"

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / f"last-match_{mode}.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


def test_last_match_arena_result_pill(mock_server, pw_browser):
    """Arena (CHERRY subteam mode, queue 1750) shows the neutral ARENA
    result pill, not VICTORY/DEFEAT (the _setHero isArenaSubteamMode path)."""
    ctx, page, errors = _open_last_match(pw_browser, mock_server, "arena")
    try:
        badge = (page.locator("#lm-result-badge").text_content() or "").strip()
        assert badge == "ARENA", f"arena result pill {badge!r} != 'ARENA'"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [arena pill]: {errors[:3]}"


def test_last_match_sr_victory_pill(mock_server, pw_browser):
    """SR (win, non-arena) shows the VICTORY result pill - distinguishes the
    win/loss path from Arena's neutral pill."""
    ctx, page, errors = _open_last_match(pw_browser, mock_server, "sr")
    try:
        badge = (page.locator("#lm-result-badge").text_content() or "").strip()
        assert badge.startswith("VICTORY"), f"sr result pill {badge!r} not VICTORY"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr pill]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in the new
    test + the 3 PGR fixtures it drives."""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "last_match_sr.json",
        ROOT / "web" / "data" / "ui_mock" / "last_match_aram.json",
        ROOT / "web" / "data" / "ui_mock" / "last_match_arena.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
