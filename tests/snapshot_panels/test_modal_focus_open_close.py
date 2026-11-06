"""
tests/snapshot_panels/test_modal_focus_open_close.py
RM-1424 (s144 uiux): an open modal holds the keyboard focus, and closing it
hands focus back.

The two full-window modals, the task detail modal (#task-modal, opened from an
activity row) and the cross-session digest popout (#digest-popout), were each
a position: fixed scrim over the whole page. RM-1427 (s150) retired the digest
popout (its last entry point went in s218), so only the task modal is tested
here; it stays dormant behind the hidden #activity-strip, ready for that
strip's documented restore.
Measured in headless Chromium at 1920x920 under ?ui_mock=1 before the fix:
opening either left focus where it was (on the control behind the scrim, or on
the body), so the next Tab walked the page the operator cannot see; neither
was aria-modal (the task modal had no dialog role at all); Escape closed the
modal with focus left on the body, so the keyboard position was lost; and both
close buttons sat under the --hit-min floor (28x28 and 36x36).

Ruling, the RM-1312 / RM-1321 menu rules applied to a modal:
- Opening moves focus to the modal's close button and remembers the control
  that had focus (the opener), unless focus was already inside the modal.
- While the modal is the TOPMOST open layer (escape_layers paint order), Tab
  and Shift+Tab cycle its own controls; from the body the next Tab enters it.
  A menu or another layer painted over the modal is not trapped by it.
- A keyboard close (Escape, or Enter / Space on the close button) hands focus
  back to the opener when it is still rendered; otherwise focus inside the
  modal is dropped. A pointer close (a click on the close button or on the
  scrim) never parks focus on the opener, so the next Space on Replay is not
  taken by it.
- The modal is role="dialog" aria-modal="true" with a labelled title, and its
  close button meets --hit-min with a focus ring.

The task modal opens through its real path, a click on an activity row
rendered from a routed /api/activity response. A scripted click moves no
focus, so the opener is the control the test focused first, as a keyboard
activation would leave it. The layer painted over the modal is the view menu,
opened by an activation as the keyboard opens it (the modal's scrim takes the
mouse), the test_escape_one_action RM-1070 pattern.
"""
import json

import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import (
    VIEWPORTS,
    _assert_rings,
    _new_page,
    _rings,
)

VP = VIEWPORTS[0]
OPENER = "#view-trigger"

_MODALS = {
    "task": ("#task-modal", "#task-modal-close", "#task-modal-title"),
}

_ACTIVITY = {
    "events": [
        {
            "ts": "2026-11-04T20:15:07",
            "event": "completed",
            "op": "audit.note",
            "task_id": "t-synthetic-0001",
            "owner_agent": 7,
        }
    ],
    "snapshot": {"total": 1, "by_status": {"completed": 1}},
}
_TASK = {
    "id": "t-synthetic-0001",
    "op": "audit.note",
    "owner_agent": 7,
    "status": "completed",
    "priority": 3,
    "created_at": "2026-11-04T20:15:00",
    "events": [{"ts": "2026-11-04T20:15:07", "event": "completed", "status": "completed"}],
}


def _route_api(page):
    page.route(
        "**/api/activity*",
        lambda r: r.fulfill(status=200, content_type="application/json",
                            body=json.dumps(_ACTIVITY)),
    )
    page.route(
        "**/api/task/*",
        lambda r: r.fulfill(status=200, content_type="application/json",
                            body=json.dumps(_TASK)),
    )


def _open_view(pw_browser, mock_server, view="settings"):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    _route_api(page)
    page.goto(mock_server.url + f"/?ui_mock=1#{view}",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "(v) => document.body.dataset.view === v", arg=view, timeout=10_000
    )
    page.wait_for_function(
        "() => !!document.querySelector('#activity-line .activity-event')",
        timeout=10_000,
    )
    return ctx, page, errors


def _active(page):
    return page.evaluate(
        "() => { const a = document.activeElement;"
        " return a === document.body ? 'BODY' : (a && a.id ? '#' + a.id : String(a && a.tagName)); }"
    )


def _is_open(page, modal):
    return page.evaluate(
        "(s) => { const m = document.querySelector(s);"
        " return !m.classList.contains('hidden') && m.getClientRects().length > 0; }",
        _MODALS[modal][0],
    )


def _focus_opener(page):
    # One Tab sets keyboard modality, then the opener takes focus.
    page.keyboard.press("Tab")
    page.focus(OPENER)
    assert _active(page) == OPENER


def _open(page, modal):
    assert modal == "task", modal
    page.evaluate("() => document.querySelector('#activity-line .activity-event').click()")
    page.wait_for_function(
        "(s) => !document.querySelector(s).classList.contains('hidden')",
        arg=_MODALS[modal][0], timeout=5_000,
    )
    assert _is_open(page, modal), f"{modal} is not rendered; the fixture is wrong"


def _inside(page, modal):
    return page.evaluate(
        "(s) => document.querySelector(s).contains(document.activeElement)",
        _MODALS[modal][0],
    )


@pytest.mark.parametrize("modal", list(_MODALS))
def test_opening_a_modal_moves_focus_to_its_close_button(mock_server, pw_browser, modal):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _focus_opener(page)
        _open(page, modal)
        assert _active(page) == _MODALS[modal][1]
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key", ["Tab", "Shift+Tab"])
@pytest.mark.parametrize("modal", list(_MODALS))
def test_tab_never_leaves_the_open_modal(mock_server, pw_browser, modal, key):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _focus_opener(page)
        _open(page, modal)
        for i in range(4):
            page.keyboard.press(key)
            assert _inside(page, modal), f"{key} #{i + 1} left the modal: {_active(page)}"
        # From the body (a click on the modal's text drops focus there), the
        # next Tab enters the modal instead of walking the page behind it.
        page.evaluate("() => document.activeElement.blur()")
        assert _active(page) == "BODY"
        page.keyboard.press(key)
        assert _inside(page, modal), f"{key} from the body went to {_active(page)}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("modal", list(_MODALS))
def test_tab_walks_the_page_again_once_the_modal_is_closed(mock_server, pw_browser, modal):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _focus_opener(page)
        _open(page, modal)
        page.keyboard.press("Escape")
        assert not _is_open(page, modal)
        page.keyboard.press("Tab")
        assert _active(page) not in (OPENER, _MODALS[modal][1]), "Tab is still held"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("how", ["Escape", "Enter", "Space"])
@pytest.mark.parametrize("modal", list(_MODALS))
def test_a_keyboard_close_hands_focus_back_to_the_opener(mock_server, pw_browser, modal, how):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _focus_opener(page)
        _open(page, modal)
        assert _active(page) == _MODALS[modal][1]
        page.keyboard.press(how)
        assert not _is_open(page, modal), f"{how} left the modal open"
        assert _active(page) == OPENER, f"after {how} focus is on {_active(page)}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("modal", list(_MODALS))
def test_escape_from_the_body_still_hands_focus_back(mock_server, pw_browser, modal):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _focus_opener(page)
        _open(page, modal)
        page.evaluate("() => document.activeElement.blur()")
        page.keyboard.press("Escape")
        assert not _is_open(page, modal)
        assert _active(page) == OPENER
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("where", ["close", "scrim"])
@pytest.mark.parametrize("modal", list(_MODALS))
def test_a_pointer_close_never_parks_focus_on_the_opener(mock_server, pw_browser, modal, where):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _focus_opener(page)
        _open(page, modal)
        sel, close_btn, _title = _MODALS[modal]
        if where == "close":
            page.click(close_btn)
        else:
            page.mouse.click(5, VP[1] - 5)
        assert not _is_open(page, modal), f"a click on the {where} left it open"
        assert _active(page) == "BODY", f"after a {where} click focus is on {_active(page)}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("modal", list(_MODALS))
def test_an_opener_that_lost_its_box_takes_no_focus(mock_server, pw_browser, modal):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _focus_opener(page)
        _open(page, modal)
        page.evaluate("(s) => { document.querySelector(s).style.display = 'none'; }", OPENER)
        page.keyboard.press("Escape")
        assert not _is_open(page, modal)
        assert _active(page) == "BODY"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_MENU = """() => {
  const m = document.getElementById('view-menu');
  return {
    open: !m.classList.contains('hidden') && m.getClientRects().length > 0,
    focusIn: m.contains(document.activeElement),
    z: [m, document.getElementById('task-modal')]
      .map((e) => +getComputedStyle(e).zIndex),
  };
}"""


def test_a_layer_painted_over_the_modal_is_not_held_by_it(mock_server, pw_browser):
    # The view menu (z 9100, a non-modal role="menu" layer) opened over the
    # task modal (z 200), on Home, where the menu's active row is its first.
    # Measured (s150): Tab stays in the menu, the modal's trap stands down; the
    # first Escape closes only the menu and leaves the modal open; the next
    # Tab is the modal's again; the second Escape closes the modal and hands
    # focus back to the original opener. (The menu returns focus to its own
    # trigger, behind the scrim, and a Tab past the menu's last row on Settings
    # lands behind it too; both are filed under RM-1427, not pinned here.)
    ctx, page, errors = _open_view(pw_browser, mock_server, "home")
    try:
        _focus_opener(page)
        _open(page, "task")
        page.evaluate("() => document.getElementById('view-trigger').click()")
        menu = page.evaluate(_MENU)
        assert menu["open"] and _is_open(page, "task"), menu
        assert menu["z"][0] > menu["z"][1], f"the menu is not painted over the modal: {menu}"
        assert menu["focusIn"], f"opening the menu left focus on {_active(page)}"
        page.keyboard.press("Tab")
        assert page.evaluate(_MENU)["focusIn"] and not _inside(page, "task"), (
            f"the modal under the menu took the Tab: {_active(page)}")
        page.keyboard.press("Escape")
        assert not page.evaluate(_MENU)["open"], "the first Escape left the menu open"
        assert _is_open(page, "task"), "the first Escape closed the modal under the menu"
        page.keyboard.press("Tab")
        assert _inside(page, "task"), f"with the menu shut Tab went to {_active(page)}"
        page.keyboard.press("Escape")
        assert not _is_open(page, "task")
        assert _active(page) == OPENER
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("modal", list(_MODALS))
def test_each_modal_is_a_labelled_aria_modal_dialog(mock_server, pw_browser, modal):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        sel, close_btn, title = _MODALS[modal]
        got = page.evaluate(
            """([s, c]) => {
              const m = document.querySelector(s);
              const t = document.getElementById(m.getAttribute('aria-labelledby') || '');
              const b = document.querySelector(c);
              return {
                role: m.getAttribute('role'),
                modal: m.getAttribute('aria-modal'),
                title: t ? '#' + t.id : null,
                titleText: t ? t.textContent.trim() : '',
                closeName: (b.getAttribute('aria-label') || '').trim(),
              };
            }""",
            [sel, close_btn],
        )
        assert got["role"] == "dialog", got
        assert got["modal"] == "true", got
        assert got["title"] == title and got["titleText"], got
        assert got["closeName"].lower() == "close", got
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("modal", list(_MODALS))
def test_each_close_button_meets_the_hit_floor_and_paints_a_ring(mock_server, pw_browser, modal):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _open(page, modal)
        close_btn = _MODALS[modal][1]
        box = page.evaluate(
            """(c) => {
              const r = document.querySelector(c).getBoundingClientRect();
              const hit = parseFloat(getComputedStyle(document.documentElement)
                .getPropertyValue('--hit-min'));
              return { w: r.width, h: r.height, hit };
            }""",
            close_btn,
        )
        assert box["hit"] >= 42, box
        assert box["w"] >= box["hit"] and box["h"] >= box["hit"], box
        page.keyboard.press("Tab")
        _assert_rings(_rings(page, close_btn), close_btn, 1)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
