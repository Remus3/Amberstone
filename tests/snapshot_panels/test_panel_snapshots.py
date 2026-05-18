"""
tests/snapshot_panels/test_panel_snapshots.py
Phase 3.3: Playwright panel snapshot tests.

6 fixture states × 4 game panels = 24 screenshots per run.
Screenshots written to tests/snapshot_panels/screenshots/ (gitignored).
Tests pass when:
  - All 4 panels are visible in the DOM.
  - Game-mode fixtures produce non-placeholder #rn-action text.
  - No unhandled JS errors.

Adversarial fixtures (`adv_*`) probe degraded-input handling:
the panels must still mount and the page must not throw, even when
`coach` is missing entirely, all fields are null, or values are
out of range.

Run locally:
    pytest tests/snapshot_panels/ -v
Regenerate screenshots:
    pytest tests/snapshot_panels/ -v  (screenshots overwrite automatically)
"""
import pytest
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"
FIXTURES = ["lobby", "sr", "aram", "arena", "brawl", "tft"]
ADV_FIXTURES = [
    "adv_no_coach",
    "adv_null_fields",
    "adv_empty_strings",
    "adv_out_of_range",
]
GAME_PANELS = ["right-now", "next", "item-build", "minimap"]


@pytest.mark.parametrize("fixture_name", FIXTURES)
def test_panels(fixture_name, mock_server, pw_browser):
    """Load dashboard with a fixture state; screenshot every game panel."""
    mock_server.set_fixture(fixture_name)

    from tests.snapshot_panels.conftest import _WS_STUB
    ctx = pw_browser.new_context(ignore_https_errors=True)
    page = ctx.new_page()
    # Prevent the dashboard WS from connecting to the real supervisor on :8891.
    # Live WS messages override the fixture and cause non-deterministic failures.
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    try:
        # /#last-match forces the view router to show the game panels at boot
        # (without it, the router starts in "home" view → main hidden).
        # domcontentloaded fires after all ES modules execute, so the view
        # router has already applied by the time Playwright resumes.
        #
        # s219 NOTE: `last-match` is now the Post Game Review view, which
        # hides `main` via CSS. To keep this test's legacy "show main
        # panels" contract working, we inject a stylesheet override below
        # that nullifies the s219 hide rule for this URL only. This test
        # is specifically scoped to the legacy in-game panels (#right-now,
        # #next, #item-build, #minimap) which live in main - the new
        # Post Game Review section has its own panel-snapshot coverage in
        # a separate test if needed.
        url = mock_server.url + "/#last-match"
        page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        page.add_style_tag(content="""
          body[data-view="last-match"] main { display: block !important; }
          body[data-view="last-match"] #view-last-match { display: none !important; }
        """)

        # For game fixtures, wait until #rn-action shows coaching text (not "-").
        # SSE delivers health+state immediately; typical latency < 200 ms.
        # For lobby the action stays "-"; just let the event loop settle.
        if fixture_name != "lobby":
            page.wait_for_function(
                "(document.querySelector('#rn-action')?.textContent?.trim() || '') !== '-'",
                timeout=8_000,
            )
        else:
            page.wait_for_timeout(800)

        SCREENSHOTS.mkdir(exist_ok=True)
        for panel_id in GAME_PANELS:
            el = page.locator(f"#{panel_id}")
            assert el.is_visible(), (
                f"#{panel_id} not visible (fixture={fixture_name})"
            )
            el.screenshot(path=str(SCREENSHOTS / f"{panel_id}_{fixture_name}.png"))

        # Game fixtures: verify meaningful coaching content rendered.
        if fixture_name != "lobby":
            action = page.locator("#rn-action").inner_text()
            assert action.strip() and action.strip() != "-", (
                f"#rn-action placeholder not replaced (fixture={fixture_name})"
            )

    finally:
        page.close()
        ctx.close()

    # Surface unhandled JS errors (first 3 for brevity).
    assert not errors, f"JS errors [{fixture_name}]: {errors[:3]}"


@pytest.mark.parametrize("fixture_name", ADV_FIXTURES)
def test_adversarial(fixture_name, mock_server, pw_browser):
    """Degraded-input fixtures: renderer must mount panels and not throw.

    These fixtures intentionally violate the happy-path contract:
      - `adv_no_coach`: coach field absent (state.coach is undefined)
      - `adv_null_fields`: coach exists but every field is null
      - `adv_empty_strings`: every string is ""
      - `adv_out_of_range`: negative gold/cs/game_time_s, hp_pct=250,
        level=99, malformed kda

    We do NOT wait for #rn-action to leave the placeholder - by design
    these fixtures may never produce coaching text. We only assert
    that the four panel DOM nodes exist and no unhandled JS errors fire.
    """
    mock_server.set_fixture(fixture_name)

    from tests.snapshot_panels.conftest import _WS_STUB
    ctx = pw_browser.new_context(ignore_https_errors=True)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    try:
        url = mock_server.url + "/#last-match"
        page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        # s219: same override as test_panels - `last-match` is now Post
        # Game Review; the legacy "show main panels" contract this test
        # relies on requires nullifying the s219 hide rules.
        page.add_style_tag(content="""
          body[data-view="last-match"] main { display: block !important; }
          body[data-view="last-match"] #view-last-match { display: none !important; }
        """)
        # Give SSE + initial render a moment to settle. No content guarantee.
        page.wait_for_timeout(1500)

        for panel_id in GAME_PANELS:
            el = page.locator(f"#{panel_id}")
            assert el.count() > 0, (
                f"#{panel_id} missing from DOM (fixture={fixture_name})"
            )
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [{fixture_name}]: {errors[:3]}"


def test_mode_transition(mock_server, pw_browser):
    """Hot-swap the SSE fixture across modes; renderer must not leak DOM state.

    Sequence: lobby → sr → aram → tft → lobby.
    Each step reloads the page so the fresh fixture is fetched. We assert
    `body[data-mode]` matches the new mode_key on each step, and no JS
    errors fire during any transition.
    """
    from tests.snapshot_panels.conftest import _WS_STUB
    ctx = pw_browser.new_context(ignore_https_errors=True)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    sequence = ["lobby", "sr", "aram", "tft", "lobby"]
    # main.js initializes state.mode = "client" (web/js/lib/state.js:5) and
    # setMode early-returns when tag === state.mode. So for a fixture whose
    # mode_key is "client" loaded on a fresh page, body[data-mode] never gets
    # stamped - it's either None (initial) or whatever the prior step left.
    # Game modes always stamp a definite attribute value.
    game_modes = {"sr", "aram", "tft"}

    try:
        for step, fixture_name in enumerate(sequence):
            mock_server.set_fixture(fixture_name)
            url = mock_server.url + "/#last-match"
            if step == 0:
                page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            else:
                page.reload(wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_timeout(1000)

            actual = page.evaluate(
                "() => document.body.getAttribute('data-mode')"
            )
            if fixture_name in game_modes:
                assert actual == fixture_name, (
                    f"step {step} fixture={fixture_name}: "
                    f"body[data-mode]={actual!r} expected {fixture_name!r}"
                )
            else:
                # Lobby - main.js state.mode default is already "client"
                # so setMode("client") short-circuits and the attribute may
                # be None (fresh load) or stale from a prior step. Both OK.
                assert actual in (None, "client"), (
                    f"step {step} fixture={fixture_name}: "
                    f"body[data-mode]={actual!r} expected None or 'client'"
                )
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors during transition: {errors[:3]}"
