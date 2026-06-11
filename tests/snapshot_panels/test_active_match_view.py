"""
tests/snapshot_panels/test_active_match_view.py
Active Match VIEW snapshot coverage - SR + ARAM + Arena (C2, 2026-06-06).

Renders the full-page active-match view (#view-active-match) for SR, ARAM,
and Arena against the ui_mock fixtures through the headless mock-server +
Playwright harness. Reproducible stand-in for the live self-signed-HTTPS
:8888 visual check: Claude_Preview cannot attach the self-signed cert and
Game-PC :8892 MCP is down (project_gamepc_mcp_boot_gap), so the C-phase
visual validation runs here in CI instead of as a one-off screenshot.
Mirrors test_champ_select_view.py (C1).

Drive path: /?ui_mock=1&mode=<mode>#active-match. main.js boot flips
body.dataset.uiMock; with an empty SSE state the auto-derive lands on
"home" (no live mode -> not an in-game surface) so the #active-match hash
wins the view router. The view-change branch (main.js:630) kicks
_amMockLoad, which fetches /data/ui_mock/active_match_<mode>.json and
re-fires renderActiveMatch(coach, {mode, lcuPhase: phase, liveclient,
cooldowns}). phase=InProgress -> the isLive render fills the CALL pane and
stamps "phase InProgress" into #am-sub. We wait on that text because the
pre-fetch placeholder render carries an empty phase, so the signal only
fires once the fixture's coach data has actually rendered.

Asserts per mode: the view mounts, the live coach line renders in the CALL
pane, the mode's static map mounts with the right alt (#am-map-img
alt="<mode> map"), the Draft Elo chip is enabled for SR/ARAM and hidden in
Arena (the _renderDraftEloFromCtx 5v5-only gate - the per-mode structural
differentiator, mirroring C1's SR-only Pick & Ban hidden check), and no
unhandled JS errors fire. Screenshots the view for the audit trail.
"""
import json

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_active_match(pw_browser, mock_server, mode):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home"/"client"
    # (no live mode), so the #active-match hash is honored by the view
    # router instead of being overridden by a derived in-game surface.
    mock_server._store["data"] = {}

    # Render at the spec's 1920x1080 design baseline (docs/UI_SCALE_SPEC_V2.md)
    # so the capture + no-scroll hierarchy assertions match the operator's
    # actual monitor instead of Playwright's default 1280-wide viewport.
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    url = mock_server.url + f"/?ui_mock=1&mode={mode}#active-match"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render to land the live coach payload: the
    # isLive branch stamps "phase InProgress" into #am-sub (the pre-fetch
    # placeholder render carries an empty phase, so this only fires once
    # the fixture's coach data has rendered).
    page.wait_for_function(
        "document.querySelector('#am-sub') && "
        "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    return ctx, page, errors


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_active_match_view_renders(mode, mock_server, pw_browser):
    ctx, page, errors = _open_active_match(pw_browser, mock_server, mode)
    try:
        view = page.locator("#view-active-match")
        assert view.is_visible(), f"#view-active-match not visible (mode={mode})"

        # Live coach RIGHT NOW / ACTION line rendered in the CALL pane.
        call = page.locator("#am-call-body")
        assert call.locator("div").count() > 0, f"CALL pane empty (mode={mode})"

        # The mode's static map mounted with the right per-mode alt.
        img = page.locator("#am-map-img")
        assert img.count() > 0, f"#am-map-img missing (mode={mode})"
        assert img.get_attribute("alt") == f"{mode} map", (
            f"map alt != {mode!r} map (mode={mode})"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / f"active-match_{mode}.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


@pytest.mark.parametrize(
    "mode,expect_hidden",
    [("sr", False), ("aram", False), ("arena", True)],
)
def test_active_match_draft_elo_mode_gate(mode, expect_hidden, mock_server, pw_browser):
    """Draft Elo chip is a 5v5-only surface: enabled for SR/ARAM, hidden in
    Arena (_renderDraftEloFromCtx). The per-mode structural differentiator."""
    ctx, page, errors = _open_active_match(pw_browser, mock_server, mode)
    try:
        display = page.eval_on_selector(
            "#am-draft-elo", "el => getComputedStyle(el).display"
        )
        if expect_hidden:
            assert display == "none", (
                f"draft-elo should be hidden in {mode} (display={display})"
            )
        else:
            assert display != "none", (
                f"draft-elo should be enabled in {mode} (display={display})"
            )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode} draft-elo]: {errors[:3]}"


# Operator fix 2026-06-10: ARAM/Mayhem emit no champion coordinates
# (Live Client position "NONE"), so the map pane's live signal is the
# text layers - a ticking clock in the status line plus a per-enemy
# roster (zone label / respawn countdown / MIA age / level). Shaped
# like the real 2026-06-10 game's /api/vision-state (game_mode KIWI,
# last_seen_zone on_bridge, last_seen_pos null).
_VS_FIXTURE = {
    "t_now": 0,
    "game_time": 754.2,
    "game_mode": "KIWI",
    "active_team": "ORDER",
    "enemies": {
        "Viktor": {
            "champion": "Viktor", "summoner_name": "x", "team": "CHAOS",
            "level": 14, "is_dead": False, "respawn_in_s": None,
            "visible": True, "missing_for_s": None, "last_seen_pos": None,
            "last_seen_t": 754.0, "last_seen_zone": "on_bridge",
        },
        "Jinx": {
            "champion": "Jinx", "summoner_name": "y", "team": "CHAOS",
            "level": 13, "is_dead": True, "respawn_in_s": 21.4,
            "visible": False, "missing_for_s": None, "last_seen_pos": None,
            "last_seen_t": 700.0, "last_seen_zone": "on_bridge",
        },
    },
    "summary": {"visible_count": 1, "missing_count": 0, "dead_count": 1,
                "total": 2},
}


def test_active_match_map_text_ticks_from_vision_state(mock_server, pw_browser):
    """The map pane's status + roster must render from /api/vision-state
    alone - WITHOUT the base image (this worktree-style env has no local
    ddragon mirror, which is exactly the no-image fallback path that used
    to freeze the panel on 'loading vision...')."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/vision-state*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_VS_FIXTURE)))
    page.goto(mock_server.url + "/?ui_mock=1&mode=aram#active-match",
              wait_until="domcontentloaded", timeout=15_000)
    try:
        page.wait_for_function(
            "document.querySelector('#am-map-status') && "
            "document.querySelector('#am-map-status')"
            ".textContent.indexOf('on bridge') >= 0",
            timeout=10_000,
        )
        status = page.locator("#am-map-status").text_content()
        assert "12:34" in status, f"clock missing from status: {status!r}"
        assert "1 on bridge - 1 dead" in status, status
        rows = page.locator("#am-map-roster .am-mr-row")
        assert rows.count() == 2, "one roster row per enemy"
        dead = page.locator('#am-map-roster .am-mr-row[data-state="dead"]')
        assert dead.count() == 1
        assert "DEAD 22s" in dead.text_content(), (
            "dead enemy must carry the ceil(respawn_in_s) countdown")
        alive = page.locator('#am-map-roster .am-mr-row[data-state="ok"]')
        assert alive.count() == 1
        assert "on bridge" in alive.text_content(), (
            "alive enemy must carry the zone label")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [map text]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "active_match_sr.json",
        ROOT / "web" / "data" / "ui_mock" / "active_match_aram.json",
        ROOT / "web" / "data" / "ui_mock" / "active_match_arena.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
