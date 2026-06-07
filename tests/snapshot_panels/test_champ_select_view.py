"""
tests/snapshot_panels/test_champ_select_view.py
Champ-select VIEW snapshot coverage - ARAM + Arena (C1, 2026-06-06).

Renders the full-page champ-select view (#view-champ-select) for ARAM and
Arena against the ui_mock fixtures through the headless mock-server +
Playwright harness. This is the reproducible stand-in for the live
self-signed-HTTPS :8888 visual check: Claude_Preview cannot attach the
self-signed cert and Game-PC :8892 MCP is down (project_gamepc_mcp_boot_gap),
so the C-phase visual validation runs here in CI instead of as a one-off
screenshot. Mirrors test_panel_snapshots.py.

Drive path: /?ui_mock=1&mode=<mode>#champ-select. main.js boot flips
body.dataset.uiMock and clears the manual-view sticky; with an empty SSE
state the auto-derive lands on "home" (not a mid-flight game surface) so the
#champ-select hash wins. renderChampSelectView calls _csResolveLcu ->
_csMockLoad, which fetches /data/ui_mock/champ_select_<mode>.json and
re-renders, stamping #view-champ-select[data-cs-mode].

Asserts per mode: the view mounts with the right data-cs-mode, the mode-
specific structure renders (ARAM = bench-swap strip; Arena = duo row +
augment slots), the SR-only Pick & Ban card is hidden, and no unhandled JS
errors fire. Screenshots the view for the audit trail.
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"

# (mode, the selector that only appears once the mock fixture has rendered
#  that mode's central pane - proves the async _csMockLoad render landed).
_MODE_CONTENT = {
    "aram": "#view-champ-select .csv-bench-cell",
    "arena": "#view-champ-select .csv-duo-cell",
}


def _open_champ_select(pw_browser, mock_server, mode):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home", so the
    # #champ-select hash is NOT treated as a stale game-state surface and
    # wins the view router (see main.js _viewResolveAndApply).
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

    url = mock_server.url + f"/?ui_mock=1&mode={mode}#champ-select"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render to land its mode-specific content.
    page.wait_for_function(
        f"document.querySelectorAll('{_MODE_CONTENT[mode]}').length > 0",
        timeout=10_000,
    )
    return ctx, page, errors


@pytest.mark.parametrize("mode", ["aram", "arena"])
def test_champ_select_view_renders(mode, mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        view = page.locator("#view-champ-select")
        assert view.is_visible(), f"#view-champ-select not visible (mode={mode})"
        assert view.get_attribute("data-cs-mode") == mode, (
            f"data-cs-mode != {mode!r} (mode={mode})"
        )

        # SR-only Pick & Ban card must be hidden in ARAM/Arena.
        assert not page.locator(".csv-card-pickban").is_visible(), (
            f"Pick & Ban card should be hidden in {mode}"
        )

        # Mode-specific structure landed.
        assert page.locator(_MODE_CONTENT[mode]).count() > 0, (
            f"mode-specific content missing (mode={mode})"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / f"champ-select_{mode}.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


def test_champ_select_aram_bench_strip(mock_server, pw_browser):
    """ARAM ships a 10-champion bench-swap strip from the fixture bench[]."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "aram")
    try:
        cells = page.locator("#view-champ-select .csv-bench-cell")
        assert cells.count() == 10, (
            f"expected 10 bench cells, got {cells.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [aram bench]: {errors[:3]}"


def test_champ_select_arena_augments(mock_server, pw_browser):
    """Arena central pane renders the augment slot scaffold (3 slots)."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "arena")
    try:
        slots = page.locator("#view-champ-select .csv-augment-slot")
        assert slots.count() >= 1, "expected at least one augment slot"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [arena augments]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "champ_select_aram.json",
        ROOT / "web" / "data" / "ui_mock" / "champ_select_arena.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
