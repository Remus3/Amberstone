"""
tests/snapshot_panels/test_lobby_find_match_focus.py
RM-1139 - Lobby Find Match / Cancel Queue keep keyboard focus.

THE DEFECT. #lv-find-match and #lv-cancel-match are static buttons in
web/index.html; web/js/main.js drives them two ways:

  1. the Find Match click handler set find.disabled = true for a 1.5 s
     double-fire hold. Disabling the focused button throws keyboard focus
     to <body> at once, so Enter on Find Match left the keyboard nowhere.
     The 2 s lobby refresh also wrote find.disabled = !enabled, which
     re-enabled the button inside the hold.
  2. the lobby refresh disables Find Match while the LCU reports
     Searching and disables Cancel Queue when the search ends. Whichever
     button held focus at that flip lost it to <body>, so a keyboard user
     who started a search could not reach Cancel Queue without re-tabbing
     from the top of the page, and vice versa.

THE FIX. The click hold lives on _LV (clock-based, seq-tokenised, as the
RM-1138 LOCK IN hold) and marks the button aria-disabled="true"
(announced, still focusable) instead of disabled; the click handler
returns while held and the refresh no longer clears it. When the refresh
disables the focused button of the pair and the other one is enabled,
focus moves to the other one: Find -> Cancel when a search starts,
Cancel -> Find when it ends.

Harness: test_lobby_render_stability._open_lobby_stability with the live
polled LCU envelope (ui_mock=False), so search_state drives the render.
POST /api/lcu-cmd is routed and counted and never answered, so the hold
is the only thing between two clicks and two start_matchmaking commands.
"""
import copy
import json
import time
from urllib.parse import urlsplit

from tests.snapshot_panels.test_lobby_render_stability import (
    _POLL_LCU,
    _open_lobby_stability,
)

_ACTIVE_ID = "document.activeElement ? document.activeElement.id : ''"


def _open(pw_browser, mock_server, lcu):
    ctx, page, errors, _hits = _open_lobby_stability(
        pw_browser, mock_server, poll=True, ui_mock=False, lcu=lcu
    )
    page.wait_for_function(
        "(() => { const b = document.getElementById('lv-find-match');"
        "  return b && !b.disabled; })()",
        timeout=15_000,
    )
    return ctx, page, errors


def _count_lcu_posts(ctx):
    posts: list = []

    def _handle(route, request):
        if request.method == "POST":
            try:
                posts.append(json.loads(request.post_data or "{}"))
            except ValueError:
                posts.append({})
        # Never fulfilled: the command stays in flight for the whole test.

    ctx.route(lambda u: urlsplit(u).path == "/api/lcu-cmd", _handle)
    return posts


def test_find_match_hold_keeps_focus_and_blocks_a_second_start(
    mock_server, pw_browser
):
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    posts = _count_lcu_posts(ctx)
    try:
        page.focus("#lv-find-match")
        page.keyboard.press("Enter")
        page.wait_for_timeout(150)
        st = page.evaluate(
            "(() => { const b = document.getElementById('lv-find-match');"
            "  return { active: document.activeElement === b,"
            "    disabled: b.disabled,"
            "    aria: b.getAttribute('aria-disabled') }; })()"
        )
        assert st["active"], (
            f"Enter on Find Match threw keyboard focus away ({st!r}, "
            f"activeElement id {page.evaluate(_ACTIVE_ID)!r})"
        )
        assert st["aria"] == "true" and st["disabled"] is False, (
            f"held Find Match must be aria-disabled, not disabled: {st!r}"
        )
        cmds = [p.get("cmd") for p in posts]
        assert cmds == ["start_matchmaking"], cmds

        # The held button reads like the disabled one: same settled fill
        # and cursor as a transition-free disabled clone (header.css).
        page.wait_for_timeout(300)
        look = page.evaluate(
            "(() => { const b = document.getElementById('lv-find-match');"
            "  const c = b.cloneNode(true); c.id = ''; c.disabled = true;"
            "  c.removeAttribute('aria-disabled');"
            "  c.classList.remove('is-searching');"
            "  c.style.transition = 'none';"
            "  b.parentNode.appendChild(c);"
            "  const hs = getComputedStyle(b), cs = getComputedStyle(c);"
            "  const r = { held: [hs.backgroundColor, hs.cursor],"
            "    disabled: [cs.backgroundColor, cs.cursor] };"
            "  c.remove(); return r; })()"
        )
        assert look["held"] == look["disabled"], (
            f"held Find Match does not read as disabled: {look!r}"
        )

        # A second Enter and a pointer click inside the hold POST nothing.
        # force=True: Playwright's actionability wait treats aria-disabled
        # as disabled and would otherwise sit out the hold, then click.
        page.keyboard.press("Enter")
        page.click("#lv-find-match", force=True)
        page.wait_for_timeout(150)
        assert [p.get("cmd") for p in posts] == ["start_matchmaking"], (
            f"a second activation inside the hold fired again: {posts!r}"
        )

        # The hold releases after its window (a real failure can retry).
        page.wait_for_function(
            "!document.getElementById('lv-find-match')"
            ".hasAttribute('aria-disabled')",
            timeout=5_000,
        )
        page.keyboard.press("Enter")
        page.wait_for_timeout(150)
        assert [p.get("cmd") for p in posts] == [
            "start_matchmaking", "start_matchmaking"
        ], f"the hold never released: {posts!r}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [find hold]: {errors[:3]}"


def _flip_level(page, lcu):
    """Change a rendered party field and wait for the refresh to draw it:
    a real lobby refresh, not a gated no-op."""
    m = lcu["lobby"]["members"][1]
    m["summoner_level"] = 219 if m["summoner_level"] == 218 else 218
    page.wait_for_function(
        "document.querySelector('#lv-members-list')"
        f".textContent.indexOf('LVL {m['summoner_level']}') >= 0",
        timeout=10_000,
    )


def test_hold_survives_a_lobby_refresh(mock_server, pw_browser):
    """The 2 s refresh wrote find.disabled = !enabled and re-enabled a
    held button. Click, let a real refresh land INSIDE the 1.5 s hold, and
    read the hold back. The refresh runs on a 2 s poll, so a click is
    timed off a just-landed refresh and retried until one lands inside."""
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    posts = _count_lcu_posts(ctx)
    try:
        page.wait_for_function(
            "document.querySelector('#lv-members-list')"
            ".textContent.indexOf('LVL 218') >= 0",
            timeout=15_000,
        )
        page.focus("#lv-find-match")
        st = None
        for _ in range(6):
            page.wait_for_function(
                "!document.getElementById('lv-find-match')"
                ".hasAttribute('aria-disabled')",
                timeout=5_000,
            )
            _flip_level(page, lcu)
            # A refresh just landed; the next is up to 2 s out. Click
            # 1 s later so the next refresh can only land in the hold's
            # last 0.5 s or after it.
            page.wait_for_timeout(1000)
            page.keyboard.press("Enter")
            t0 = time.monotonic()
            m = lcu["lobby"]["members"][1]
            m["summoner_level"] = 219 if m["summoner_level"] == 218 else 218
            page.wait_for_function(
                "document.querySelector('#lv-members-list')"
                f".textContent.indexOf('LVL {m['summoner_level']}') >= 0",
                timeout=10_000,
            )
            if time.monotonic() - t0 < 1.3:
                st = page.evaluate(
                    "(() => { const b = document.getElementById("
                    "'lv-find-match');"
                    "  return { aria: b.getAttribute('aria-disabled'),"
                    "    disabled: b.disabled,"
                    "    active: document.activeElement === b }; })()"
                )
                n = len(posts)
                page.keyboard.press("Enter")
                page.wait_for_timeout(100)
                st["refired"] = len(posts) != n
                break
        assert st is not None, "no lobby refresh landed inside a hold window"
        assert st == {
            "aria": "true", "disabled": False, "active": True,
            "refired": False,
        }, f"a lobby refresh inside the hold cleared it or lost focus: {st!r}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [hold refresh]: {errors[:3]}"


def test_focus_moves_between_find_and_cancel_on_search_flips(
    mock_server, pw_browser
):
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    try:
        page.focus("#lv-find-match")
        lcu["lobby"]["search_state"] = "Searching"
        page.wait_for_function(
            "document.getElementById('lv-find-match')"
            ".classList.contains('is-searching')",
            timeout=10_000,
        )
        assert page.evaluate(
            "!document.getElementById('lv-cancel-match').disabled"
        ), "Cancel Queue not enabled while searching"
        active = page.evaluate(_ACTIVE_ID)
        assert active == "lv-cancel-match", (
            "search start disabled the focused Find Match and dropped focus "
            f"to {active or '<body>'!r}, expected Cancel Queue"
        )

        lcu["lobby"]["search_state"] = "Idle"
        page.wait_for_function(
            "document.getElementById('lv-cancel-match').disabled",
            timeout=10_000,
        )
        active = page.evaluate(_ACTIVE_ID)
        assert active == "lv-find-match", (
            "search end disabled the focused Cancel Queue and dropped focus "
            f"to {active or '<body>'!r}, expected Find Match"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [search flip focus]: {errors[:3]}"


def test_search_flip_never_steals_focus_from_elsewhere(
    mock_server, pw_browser
):
    """The move only follows focus that was ON the disabled button: a
    search start while the operator is in another control leaves them
    there."""
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    try:
        page.focus("#lv-mode-trigger")
        lcu["lobby"]["search_state"] = "Searching"
        page.wait_for_function(
            "document.getElementById('lv-find-match')"
            ".classList.contains('is-searching')",
            timeout=10_000,
        )
        assert page.evaluate(_ACTIVE_ID) == "lv-mode-trigger"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [no steal]: {errors[:3]}"


# RM-1208: a queue pop (search_state MatchFound, phase ReadyCheck)
# disabled BOTH buttons of the pair, so the RM-1139 handoff above had no
# enabled partner and focus fell to <body>. During the pop Cancel Queue is
# held aria-disabled (focusable, inert, reads as disabled), never disabled,
# so the focused button keeps focus or hands it to Cancel.

_PAIR_JS = (
    "(() => { const f = document.getElementById('lv-find-match');"
    "  const c = document.getElementById('lv-cancel-match');"
    "  return { active: document.activeElement ? document.activeElement.id"
    "      : '',"
    "    find: [f.disabled, f.getAttribute('aria-disabled')],"
    "    cancel: [c.disabled, c.getAttribute('aria-disabled')] }; })()"
)


def _pop(page, lcu):
    lcu["phase"] = "ReadyCheck"
    lcu["lobby"]["search_state"] = "MatchFound"
    # Waits on "neither button can act", true before and after the fix,
    # so a red run is the focus assertion, not this wait.
    page.wait_for_function(
        "(() => { const f = document.getElementById('lv-find-match');"
        "  const c = document.getElementById('lv-cancel-match');"
        "  return f.disabled && (c.disabled"
        "    || c.getAttribute('aria-disabled') === 'true'); })()",
        timeout=10_000,
    )


def _search(page, lcu, state):
    lcu["phase"] = "Matchmaking" if state == "Searching" else "Lobby"
    lcu["lobby"]["search_state"] = state
    want = "false" if state == "Searching" else "true"
    page.wait_for_function(
        "(() => { const c = document.getElementById('lv-cancel-match');"
        f"  return String(c.disabled) === '{want}'"
        "    && !c.hasAttribute('aria-disabled'); })()",
        timeout=10_000,
    )


def test_queue_pop_keeps_focus_on_cancel_and_cancel_stays_inert(
    mock_server, pw_browser
):
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    posts = _count_lcu_posts(ctx)
    try:
        _search(page, lcu, "Searching")
        page.focus("#lv-cancel-match")
        _pop(page, lcu)
        st = page.evaluate(_PAIR_JS)
        assert st["active"] == "lv-cancel-match", (
            "a queue pop disabled the focused Cancel Queue and dropped "
            f"focus to {st['active'] or '<body>'!r}: {st!r}"
        )
        assert st["cancel"] == [False, "true"], st
        assert st["find"][0] is True, st

        # Inert while held: Enter and a forced click POST nothing.
        page.keyboard.press("Enter")
        page.click("#lv-cancel-match", force=True)
        page.wait_for_timeout(150)
        assert posts == [], f"a held Cancel Queue fired: {posts!r}"

        # Held Cancel reads as disabled: same settled fill, opacity and
        # cursor as a disabled clone, and no hover fill.
        page.hover("#lv-cancel-match", force=True)
        page.wait_for_timeout(250)
        look = page.evaluate(
            "(() => { const b = document.getElementById('lv-cancel-match');"
            "  const c = b.cloneNode(true); c.id = ''; c.disabled = true;"
            "  c.removeAttribute('aria-disabled');"
            "  c.style.transition = 'none';"
            "  b.parentNode.appendChild(c);"
            "  const hs = getComputedStyle(b), cs = getComputedStyle(c);"
            "  const r = { held: [hs.backgroundColor, hs.opacity, hs.cursor],"
            "    disabled: [cs.backgroundColor, cs.opacity, cs.cursor] };"
            "  c.remove(); return r; })()"
        )
        assert look["held"] == look["disabled"], (
            f"held Cancel Queue does not read as disabled: {look!r}"
        )

        # Declined pop -> requeue: Cancel is live again, focus never moved.
        _search(page, lcu, "Searching")
        assert page.evaluate(_ACTIVE_ID) == "lv-cancel-match"
        # Pop again, then the search ends: focus hands to Find Match.
        _pop(page, lcu)
        _search(page, lcu, "Idle")
        active = page.evaluate(_ACTIVE_ID)
        assert active == "lv-find-match", (
            f"pop -> Idle dropped focus to {active or '<body>'!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [pop cancel focus]: {errors[:3]}"


def test_queue_pop_straight_from_idle_hands_focus_to_cancel(
    mock_server, pw_browser
):
    """A fast pop can land between two 2 s polls, so the refresh sees
    Idle -> MatchFound with Find Match focused and never sees Searching."""
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    try:
        page.focus("#lv-find-match")
        _pop(page, lcu)
        st = page.evaluate(_PAIR_JS)
        assert st["active"] == "lv-cancel-match", (
            "an Idle -> MatchFound pop disabled the focused Find Match and "
            f"dropped focus to {st['active'] or '<body>'!r}: {st!r}"
        )
        _search(page, lcu, "Idle")
        assert page.evaluate(_ACTIVE_ID) == "lv-find-match"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [pop find focus]: {errors[:3]}"


def test_queue_pop_never_steals_focus_from_elsewhere(mock_server, pw_browser):
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors = _open(pw_browser, mock_server, lcu)
    try:
        _search(page, lcu, "Searching")
        page.focus("#lv-mode-trigger")
        _pop(page, lcu)
        assert page.evaluate(_ACTIVE_ID) == "lv-mode-trigger"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [pop no steal]: {errors[:3]}"
