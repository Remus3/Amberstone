"""
tests/snapshot_panels/test_panel_snapshots.py
Phase 3.3: Playwright panel snapshot tests.

6 fixture states × 4 game panels = 24 screenshots per run.
Screenshots written to tests/snapshot_panels/screenshots/ (gitignored).
Tests pass when:
  - All 4 panels are visible in the DOM.
  - Game-mode fixtures produce non-placeholder #rn-action text.
  - No unhandled JS errors.

Run locally:
    pytest tests/snapshot_panels/ -v
Regenerate screenshots:
    pytest tests/snapshot_panels/ -v  (screenshots overwrite automatically)
"""
import pytest
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"
FIXTURES = ["lobby", "sr", "aram", "arena", "brawl", "tft"]
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
        url = mock_server.url + "/#last-match"
        page.goto(url, wait_until="domcontentloaded", timeout=15_000)

        # For game fixtures, wait until #rn-action shows coaching text (not "—").
        # SSE delivers health+state immediately; typical latency < 200 ms.
        # For lobby the action stays "—"; just let the event loop settle.
        if fixture_name != "lobby":
            page.wait_for_function(
                "(document.querySelector('#rn-action')?.textContent?.trim() || '') !== '—'",
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
            assert action.strip() and action.strip() != "—", (
                f"#rn-action placeholder not replaced (fixture={fixture_name})"
            )

    finally:
        page.close()
        ctx.close()

    # Surface unhandled JS errors (first 3 for brevity).
    assert not errors, f"JS errors [{fixture_name}]: {errors[:3]}"
