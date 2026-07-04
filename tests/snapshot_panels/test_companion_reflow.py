"""
tests/snapshot_panels/test_companion_reflow.py
Companion-width responsive-reflow regression for the out-of-game dashboard
views (R29, 2026-06-23).

The rc-shell out-of-game companion (mainWindow, docs/ELECTRON_OVERLAY.md 3.7)
loads the full 1920-authored dashboard in a narrow window (size presets
380-640px; the operator runs it ~920px). Four views' top-level 2-up grids
overflowed / clipped at that width and were given a @media (max-width:1200px)
single-column reflow (settings + lobby + user-builds in header.css; the Post
Game Review .lm-row-half in last_match.css). This guards both directions: each
grid is single-column at the companion width and two-column on the 1920
desktop. The home view has its own guard (test_home_companion_view.py).

R30 page-7 update: .ub-layout is now single-column at BOTH widths AT REST (the
build list takes the full width; the 2-up list|form only appears while the
editor pane is open - covered by test_user_builds_review_r30.py). So
user-builds joins only the companion-single-column guard, not the desktop
two-column one.
"""
import pytest

# (view hash, top-level grid selector that reflows) - 2-up on the 1920
# desktop, single-column at the companion width.
CASES = [
    ("settings", ".settings-body"),
    ("lobby", ".lobby-view-grid"),
    ("last-match", ".lm-row-half"),
]
# user-builds is single-column at rest at both widths (R30 page-7) - it guards
# the companion direction only.
COMPANION_CASES = CASES + [("user-builds", ".ub-layout")]


def _open(pw_browser, mock_server, view, w, h):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(
        mock_server.url + f"/?ui_mock=1#{view}",
        wait_until="domcontentloaded", timeout=15_000,
    )
    return ctx, page, errors


def _track_count(page, sel):
    # The reflowed container must be in the DOM; getComputedStyle
    # grid-template-columns is a space-separated px list (one value == one
    # track). Returns None if the element is absent.
    return page.evaluate(
        """(sel) => {
          const e = document.querySelector(sel);
          if (!e) return null;
          const g = getComputedStyle(e).gridTemplateColumns;
          return (g || '').trim().split(/\\s+/).filter(Boolean).length;
        }""",
        sel,
    )


@pytest.mark.parametrize("view,sel", COMPANION_CASES)
def test_companion_single_column(view, sel, mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, view, 920, 1280)
    try:
        page.wait_for_function(
            "(s) => document.querySelector(s) !== null", arg=sel, timeout=10_000
        )
        tracks = _track_count(page, sel)
        assert tracks == 1, (
            f"{view}: {sel} not single-column at 920px (companion): {tracks} tracks"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{view} companion]: {errors[:3]}"


@pytest.mark.parametrize("view,sel", CASES)
def test_desktop_multi_column(view, sel, mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, view, 1920, 1080)
    try:
        page.wait_for_function(
            "(s) => document.querySelector(s) !== null", arg=sel, timeout=10_000
        )
        tracks = _track_count(page, sel)
        assert tracks == 2, (
            f"{view}: {sel} lost its desktop two-column layout at 1920px: "
            f"{tracks} tracks"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{view} desktop]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text in this test file."""
    from pathlib import Path

    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
