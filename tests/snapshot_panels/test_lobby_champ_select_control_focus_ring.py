"""
tests/snapshot_panels/test_lobby_champ_select_control_focus_ring.py
RM-1249 (s144 uiux) - the Lobby mode switcher, the Lobby party / Top 8
action buttons and the champ-select "Save as default" rune button draw a
token focus ring.

THE DEFECT. Four control sets carried no :focus-visible rule, so a
keyboard-focused one fell back to the user-agent ring. MEASURED in headless
Chromium under /?ui_mock=1 before the fix (default theme arcane), every one
computed `outline-style: auto`, 1px, rgb(16,16,16):
  - #lv-mode-trigger "Change Lobby Mode" (.lq-mode-trigger,
    web/css/panels/header.css): 1.08:1 on .lobby-view-card;
  - the seven party-row .lv-member-action buttons (copy / promote / kick,
    web/js/main.js renderLobbyMembers): 1.46:1 on .lobby-member-row;
  - #lv-top8-search-add (also .lv-member-action, web/index.html):
    1.24:1 on .lv-top8-search;
  - .csv-rune-save-default (web/js/panels/champ_select.js rune side head,
    web/css/panels/champ_select_view.css): 1.46:1 on .csv-rune-side.
Found by the RM-1210 focus-ring sweep over every visible focusable control
on all eleven ?ui_mock=1 views (the Home / History half shipped as
RM-1210; this is its filed residue).

THE FIX. `outline: 2px solid var(--accent)`, the Lobby precedent (.lq-btn,
.lv-top8-tag) and the RM-1210 shape. Offsets are chosen to fit each gap:
1px on the action buttons (4px flex gap in .lobby-member-actions, so the
3px reach never paints over the next button) and on the mode trigger (its
menu opens 4px below it); 2px on the lone rune button.

WHAT IS MEASURED (headless Chromium, computed values, never a grep), with
the probe and the gates of test_home_history_nav_focus_ring.py:
  - every rendered, enabled control, focused with keyboard modality,
    matches :focus-visible and computes a solid outline >= 2px whose
    colour is the resolved --accent (not the UA `auto` ring);
  - that ring colour against the nearest opaque ancestor background is
    >= 3:1, the WCAG 1.4.11 non-text floor, stating the PAIR;
  - no overflow-clipping ancestor cuts the ring, and the ring's reach
    (offset + width) stays inside the gap to the nearest sibling control;
  - the ring holds in every :root[data-theme] block of themes.css.
"""
from collections import Counter

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_home_history_nav_focus_ring import (
    _RING_JS,
    _assert_rings,
    _themes,
)

MODE_TRIGGER = "#view-lobby #lv-mode-trigger"
# Party-row actions and the Top 8 search "add" button share the class; the
# crown <span> also carries it but is not a button.
MEMBER_ACTIONS = "#view-lobby button.lv-member-action"
RUNE_SAVE = "#view-champ-select .csv-rune-save-default"

# ?ui_mock=1 lobby fixture: self (copy) + two members (copy, promote, kick).
PARTY_ACTIONS = Counter({"copy": 3, "promote": 2, "kick": 2})
N_MEMBER_BUTTONS = sum(PARTY_ACTIONS.values()) + 1  # + #lv-top8-search-add

_ACTIONS_JS = r"""
(sel) => Array.from(document.querySelectorAll(sel))
  .filter((el) => el.getBoundingClientRect().width && !el.disabled)
  .map((el) => el.id || el.dataset.action || '')
"""


def _open(pw_browser, mock_server, url, view, ready):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + url, wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_function(
        f"document.body.dataset.view === '{view}'", timeout=10_000
    )
    page.wait_for_selector(ready, state="visible", timeout=10_000)
    page.evaluate("document.fonts.ready.then(() => true)")
    page.wait_for_timeout(300)
    # These controls transition their colours, so an in-page theme flip
    # followed by a ring / surface read would straddle it (RM-1132 audit,
    # tests/snapshot_panels/test_theme_swap_reads_settled.py).
    page.add_style_tag(
        content="*, *::before, *::after { transition: none !important; }"
    )
    page.keyboard.press("Shift")  # keyboard modality for :focus-visible
    return ctx, page, errors


def _lobby(pw_browser, mock_server):
    return _open(pw_browser, mock_server, "/?ui_mock=1#lobby", "lobby",
                 MEMBER_ACTIONS)


def _champ_select(pw_browser, mock_server, mode):
    return _open(pw_browser, mock_server,
                 f"/?ui_mock=1&mode={mode}#champ-select", "champ-select",
                 RUNE_SAVE)


def test_lobby_mode_trigger_paints_the_accent_ring(mock_server, pw_browser):
    ctx, page, errors = _lobby(pw_browser, mock_server)
    try:
        rows = page.evaluate(_RING_JS, MODE_TRIGGER)
        _assert_rings(rows, 1, "Lobby mode trigger")
        assert rows[0]["key"] == "lv-mode-trigger", rows
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_lobby_member_actions_paint_the_accent_ring(mock_server, pw_browser):
    ctx, page, errors = _lobby(pw_browser, mock_server)
    try:
        keys = page.evaluate(_ACTIONS_JS, MEMBER_ACTIONS)
        assert Counter(k for k in keys if k != "lv-top8-search-add") \
            == PARTY_ACTIONS, keys
        assert "lv-top8-search-add" in keys, keys
        rows = page.evaluate(_RING_JS, MEMBER_ACTIONS)
        _assert_rings(rows, N_MEMBER_BUTTONS, "Lobby member action")
        # The ring is painted on the row / search strip the button sits in.
        surfaces = {r["surfaceOf"].split()[0] for r in rows}
        assert surfaces == {"lobby-member-row", "lv-top8-search"}, rows
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_champ_select_rune_save_default_paints_the_accent_ring(
        mock_server, pw_browser):
    for mode in ("sr", "aram"):
        ctx, page, errors = _champ_select(pw_browser, mock_server, mode)
        try:
            rows = page.evaluate(_RING_JS, RUNE_SAVE)
            _assert_rings(rows, 1, f"{mode} rune Save as default")
            assert rows[0]["key"] == "csv-rune-save-default", rows
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [{mode}]: {errors[:3]}"


def test_ring_holds_in_every_theme(mock_server, pw_browser):
    """The ring colour is each theme's own --accent: under every
    :root[data-theme] block in web/css/themes.css all three control sets
    stay on the token and above 3:1 on their surface."""
    themes = _themes()
    assert len(themes) >= 5, f"theme scan anchor: {themes}"
    failures, accents, seen = [], set(), 0
    for opener, sels in (
        (lambda: _lobby(pw_browser, mock_server),
         (MODE_TRIGGER, MEMBER_ACTIONS)),
        (lambda: _champ_select(pw_browser, mock_server, "sr"),
         (RUNE_SAVE,)),
    ):
        ctx, page, errors = opener()
        try:
            for t in themes:
                page.evaluate(
                    "(t) => document.documentElement"
                    ".setAttribute('data-theme', t)",
                    t,
                )
                page.keyboard.press("Shift")
                for sel in sels:
                    rows = page.evaluate(_RING_JS, sel)
                    assert rows, f"{t} {sel}: no control rendered"
                    seen += len(rows)
                    for r in rows:
                        accents.add(r["accent"])
                        if not (r["style"] == "solid" and r["width"] >= 2
                                and r["ring"] == r["accent"]
                                and r["contrast"] >= 3.0
                                and not r["clippedBy"]):
                            failures.append((t, sel, r))
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    # Anchors: every set measured in every theme, and the attribute flip
    # really re-themed the page.
    assert seen == len(themes) * (1 + N_MEMBER_BUTTONS + 1), seen
    assert len(accents) >= 3, f"theme flip inert: {accents}"
    assert not failures, f"theme ring failures: {failures[:4]}"
