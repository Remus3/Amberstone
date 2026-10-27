"""
tests/snapshot_panels/test_champ_select_build_chooser_keyboard.py
The Champ Select build chooser is keyboard-usable (session 144, lane uiux,
RM-971).

Measured headless before the fix, on the ?ui_mock=1 sr / aram / arena pages:
every clickable in .csv-builds (the legacy .csv-build-row and the collapsed
variant's .csv-build-path-row) had tabIndex -1, no key handler and no
:focus-visible rule, so a build could be picked only with the mouse. A
path-row click also re-renders the central pane through innerHTML
(_csvScheduleRender -> _csvRenderCentralPane), which destroys the focused
node and throws focus to <body> (lane doc section 6, trap 2).

Contract pinned here:
- every chooser click target is in the tab order (tabindex 0, role button,
  aria-pressed mirroring its selected state); the collapsed OUTER row, whose
  click is a no-op, stays out of the tab order;
- Tab moves from one path row to the next;
- Enter and Space activate a row like a click;
- focus survives the central-pane rebuild (re-found by data-variant +
  data-path-key), and a rebuild never STEALS focus that was elsewhere;
- a keyboard-focused row shows a focus ring (computed box-shadow).

Drive path: /?ui_mock=1&mode=<m>#champ-select with an empty /api/state
(the same path as test_champ_select_view.py). sr + arena render a collapsed
variant with path rows; aram renders one legacy row.
"""
import pytest

from tests.snapshot_panels.test_champ_select_view import _open_champ_select

_CLICKABLE = (
    "#view-champ-select .csv-builds .csv-build-row:not(.csv-build-row-collapsed),"
    " #view-champ-select .csv-builds .csv-build-path-row"
)

_ACTIVE_DESC_JS = """() => {
  const a = document.activeElement;
  if (!a || a === document.body) return null;
  return {
    cls: a.className || "",
    variant: a.dataset ? (a.dataset.variant || "") : "",
    path: a.dataset ? (a.dataset.pathKey || "") : "",
    inBuilds: !!a.closest(".csv-builds"),
  };
}"""


def _wait_rows(page) -> None:
    page.wait_for_function(
        "(s) => document.querySelectorAll(s).length > 0",
        arg=_CLICKABLE,
        timeout=10_000,
    )


def _path_keys(page) -> list:
    return page.evaluate(
        "() => Array.from(document.querySelectorAll("
        "'#view-champ-select .csv-builds .csv-build-path-row'))"
        ".map(r => r.dataset.pathKey)"
    )


def _focus_path(page, key: str) -> None:
    # Focus by keyboard semantics: a programmatic focus followed by a real
    # key press, so :focus-visible matches as it would after Tab.
    page.evaluate(
        "(k) => document.querySelector('#view-champ-select .csv-builds"
        " .csv-build-path-row[data-path-key=\"' + k + '\"]').focus()",
        key,
    )


def _active_path(page) -> str:
    return page.evaluate(
        "() => { const r = document.querySelector('#view-champ-select"
        " .csv-builds .csv-build-path-row.is-active'); return r ?"
        " r.dataset.pathKey : ''; }"
    )


def _wait_rebuilt(page) -> None:
    # The pre-rebuild nodes carry a JS marker; the rebuild replaces them.
    page.wait_for_function(
        "() => { const r = document.querySelector('#view-champ-select"
        " .csv-builds .csv-build-path-row, #view-champ-select .csv-builds"
        " .csv-build-row'); return !!r && !r.__s144u03; }",
        timeout=10_000,
    )


def _mark_nodes(page) -> None:
    page.evaluate(
        "() => document.querySelectorAll('#view-champ-select .csv-builds"
        " .csv-build-path-row, #view-champ-select .csv-builds .csv-build-row')"
        ".forEach(r => { r.__s144u03 = 1; })"
    )


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_every_chooser_target_is_in_the_tab_order(mode, mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        _wait_rows(page)
        rows = page.evaluate(
            "(s) => Array.from(document.querySelectorAll(s)).map(r => ({"
            " tab: r.tabIndex, role: r.getAttribute('role'),"
            " pressed: r.getAttribute('aria-pressed'),"
            " on: r.classList.contains('selected')"
            " || r.classList.contains('is-active') }))",
            _CLICKABLE,
        )
        assert rows, mode
        for r in rows:
            assert r["tab"] == 0, (mode, r)
            assert r["role"] == "button", (mode, r)
            assert r["pressed"] == ("true" if r["on"] else "false"), (mode, r)
        outer = page.evaluate(
            "() => Array.from(document.querySelectorAll('#view-champ-select"
            " .csv-builds .csv-build-row-collapsed')).map(r => r.tabIndex)"
        )
        assert all(t == -1 for t in outer), (mode, outer)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


@pytest.mark.parametrize("mode,key", [("sr", "Enter"), ("arena", " ")])
def test_keyboard_picks_a_path_and_focus_survives_the_rebuild(
    mode, key, mock_server, pw_browser
):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        _wait_rows(page)
        keys = _path_keys(page)
        assert len(keys) >= 2, (mode, keys)
        before = _active_path(page)
        target = next(k for k in keys if k != before)
        first = keys[0]
        # Tab reachability: Tab from the first path row lands on the second.
        _focus_path(page, first)
        page.keyboard.press("Tab")
        got = page.evaluate(_ACTIVE_DESC_JS)
        assert got and got["path"] == keys[1], (mode, got)
        _focus_path(page, target)
        page.keyboard.press("Shift")
        ring = page.evaluate(
            "() => getComputedStyle(document.activeElement).boxShadow"
        )
        assert ring and ring != "none", (mode, ring)
        _mark_nodes(page)
        page.keyboard.press(key)
        _wait_rebuilt(page)
        assert _active_path(page) == target, mode
        got = page.evaluate(_ACTIVE_DESC_JS)
        assert got and got["inBuilds"] and got["path"] == target, (mode, got)
        pressed = page.evaluate(
            "(k) => document.querySelector('#view-champ-select .csv-builds"
            " .csv-build-path-row[data-path-key=\"' + k + '\"]')"
            ".getAttribute('aria-pressed')",
            target,
        )
        assert pressed == "true", (mode, pressed)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


def test_keyboard_activates_the_legacy_row(mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "aram")
    try:
        _wait_rows(page)
        sel = "#view-champ-select .csv-builds .csv-build-row:not(.csv-build-row-collapsed)"
        # One row on the aram page: clear its selection, then Enter must
        # re-select it exactly as a click does.
        page.evaluate(
            "(s) => { const r = document.querySelector(s);"
            " r.classList.remove('selected'); r.focus(); }",
            sel,
        )
        page.keyboard.press("Enter")
        state = page.evaluate(
            "(s) => { const r = document.querySelector(s); return"
            " [r.classList.contains('selected'), r.getAttribute('aria-pressed'),"
            " document.activeElement === r]; }",
            sel,
        )
        assert state == [True, "true", True], state
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [aram]: {errors[:3]}"


def test_a_rebuild_never_steals_focus(mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "sr")
    try:
        _wait_rows(page)
        page.evaluate(
            "() => { if (document.activeElement) document.activeElement.blur(); }"
        )
        _mark_nodes(page)
        page.evaluate(
            "() => document.dispatchEvent(new Event('rc:lol-descriptions-ready'))"
        )
        _wait_rebuilt(page)
        assert page.evaluate(_ACTIVE_DESC_JS) is None
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr]: {errors[:3]}"
