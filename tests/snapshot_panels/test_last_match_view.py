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
import json
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"

# LIFT 2a (2026-06-22): fixed /api/post-game-rubric payload for the
# score-decomposition bar test. The mock server returns {} for that
# route, so the test intercepts it (page.route) and fulfills this. The
# saturation per axis = component / (2 * weight), clamped [0,1]:
#   kda    3.0 / (2 * 1.5) = 1.00 -> 100%
#   cs     1.2 / (2 * 1.2) = 0.50 ->  50%
#   obj    0.8 / (2 * 0.8) = 0.50 ->  50%
#   vision 0.5 / (2 * 0.5) = 0.50 ->  50%  (component key vision -> weight vision_score)
#   dpm    2.0 / (2 * 1.0) = 1.00 -> 100%  (component key dpm -> weight damage_per_min)
_RUBRIC_PAYLOAD = {
    "ok": True,
    "match_id": "NA1_TEST",
    "role": "BOTTOM",
    "total_score": 72.0,
    "percentile_grade": "A",
    "components": {
        "kda": 3.0,
        "cs_per_min": 1.2,
        "obj_participation": 0.8,
        "vision": 0.5,
        "dpm": 2.0,
    },
    "weights_used": {
        "kda": 1.5,
        "cs_per_min": 1.2,
        "obj_participation": 0.8,
        "vision_score": 0.5,
        "damage_per_min": 1.0,
    },
}

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


def test_last_match_sr_rubric_decomposition(mock_server, pw_browser):
    """LIFT 2a: the per-role score decomposition renders 5 saturation bars
    from /api/post-game-rubric components{} + weights_used{}. The SR fixture
    carries match.id 9003 so _setHeroRoleGrade fires the fetch; page.route
    intercepts /api/post-game-rubric (mock server returns {}) and fulfills
    _RUBRIC_PAYLOAD. Asserts exactly 5 bars and the known saturations:
    KDA ~100% fill, CS/min ~50% fill (read off the inline width style)."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    # Register the rubric-route interception BEFORE navigation so the
    # _setHeroRoleGrade fetch (fired during the fixture render) hits it.
    page.route(
        "**/api/post-game-rubric**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUBRIC_PAYLOAD),
        ),
    )

    try:
        url = mock_server.url + "/?ui_mock=1&mode=sr#last-match"
        page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        # Landing signal: the fixture render replaces the "-" mode tag.
        page.wait_for_function(
            "document.querySelector('#lm-mode-tag') && "
            "document.querySelector('#lm-mode-tag').textContent.trim() !== '-' && "
            "document.querySelector('#lm-mode-tag').textContent.trim() !== ''",
            timeout=10_000,
        )
        # Wait for the decomposition bars to paint (the rubric fetch is async).
        page.wait_for_selector(
            "#lm-rubric-components .lm-rubric-bar", timeout=10_000
        )

        bars = page.locator("#lm-rubric-components .lm-rubric-bar")
        assert bars.count() == 5, f"expected 5 rubric bars, got {bars.count()}"

        # Read the fill width fraction (fill width / track width) per axis.
        # KDA is the first axis (~100%), CS/min the second (~50%).
        def _fill_frac(idx):
            row = bars.nth(idx)
            track = row.locator(".lm-rubric-bar-track").bounding_box()
            fill = row.locator(".lm-rubric-bar-fill").bounding_box()
            assert track and fill and track["width"] > 0
            return fill["width"] / track["width"]

        kda_frac = _fill_frac(0)
        cs_frac = _fill_frac(1)
        assert kda_frac > 0.9, f"KDA fill {kda_frac:.3f} not ~100%"
        assert 0.4 < cs_frac < 0.6, f"CS/min fill {cs_frac:.3f} not ~50%"

        # Readouts confirm the rounded percentages.
        kda_read = (bars.nth(0).locator(".lm-rubric-bar-readout").text_content()
                    or "").strip()
        cs_read = (bars.nth(1).locator(".lm-rubric-bar-readout").text_content()
                   or "").strip()
        assert kda_read == "100%", f"KDA readout {kda_read!r} != '100%'"
        assert cs_read == "50%", f"CS/min readout {cs_read!r} != '50%'"

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#lm-rubric-components").screenshot(
            path=str(SCREENSHOTS / "pgr_decomposition.png")
        )
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [rubric]: {errors[:3]}"


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
