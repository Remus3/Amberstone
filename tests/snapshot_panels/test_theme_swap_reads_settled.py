"""
tests/snapshot_panels/test_theme_swap_reads_settled.py
RM-1132 (s144 uiux): every snapshot test that swaps the theme inside one
page and then reads a computed colour or box-shadow must read the SETTLED
value, never one mid-transition.

Why: a CSS transition on the measured element (or an ancestor whose colour
or background it inherits or composites over) keeps getComputedStyle on the
PREVIOUS theme's value right after the swap. test_tab_bars_selected_state.py
measured exactly that on .bi-tab, .home-mode-tab and the History .view-tab
(every theme read back arcane's --text-dim), and a relative assertion
("selected is brighter", "AA on its own fill") can stay GREEN on the wrong
theme's colours. The same holds for a focus() followed by a box-shadow read
when box-shadow transitions.

Audit (2026-10-30, headless Chromium, document.getAnimations() after each
swap, focus and blur, over the measured elements and all their ancestors):
  - test_tab_bars_selected_state, test_lobby_mains_tabs,
    test_view_menu_items: the Home mode, History scope and Build Insights
    tab bars, the Lobby mains tabs and the view-menu rows DO transition (the
    five Build Insights mode / metric bars do not); settled only because
    their shared _open adds a `transition: none !important` sheet.
  - test_user_builds_rune_tabs, test_user_builds_rune_cells_focus_ring,
    test_user_builds_spell_chooser_keyboard: the rune cells, spell slots and
    spell cells DO transition background and border colours; settled only
    because the shared rune-tabs _open adds the same sheet.
  - test_panel_visibility_tab_selected_state,
    test_settings_checkbox_hit_targets, test_am_call_eyebrow_contrast: no
    sheet, and none needed - nothing they read transitions.
Audit (2026-10-30, s144 L6 merger, the same detector), the six later
s144 uiux modules. Each stamps its theme at BOOT (?theme=) for every theme
it uses and never swaps in-page, so the sweep each depends on is its boot,
plus the focus / blur its ring reads use; the in-page swaps run as well:
  - test_ds_combo_controls_hit_floor, test_ds_knob_inputs_focus_ring,
    test_lm_hero_stats_disclosure, test_ds_matchup_text_contrast,
    test_ds_cards_muted_text_contrast: no sheet, and none needed - nothing
    they read transitions on boot, swap, focus or blur.
  - test_champ_select_lock_button_focus: #csv-lock-btn DOES transition
    box-shadow on focus ("transition: 0.15s", all properties); settled only
    because both of its reads await getAnimations().finished.
Audit (2026-10-31, s145 L7 merger, the same detector), the six s144 uiux
modules landed in L7:
  - test_champ_select_arena_pane_contrast, test_champ_select_enemy_wr_slot_
    contrast, test_champ_select_enemy_wr_slot_stale_cue: boot-stamped
    (?theme=), no sheet, and none needed - nothing they read transitions on
    boot or swap.
  - test_champ_select_arena_augment_options: boot-stamped, never swaps
    in-page (an in-page swap DOES transition the rows' background and
    border); the option rows DO transition box-shadow on focus; settled only
    because its ring read awaits getAnimations().finished.
  - test_home_history_nav_focus_ring, test_lobby_queue_buttons_focus_ring:
    flip data-theme in-page, and the Home tiles, History tabs and Lobby
    queue buttons DO transition their colours, so the ring / surface reads
    straddled the swap; settled now because both openers add the sheet
    (added by the L7 merger with this audit).
Audit (2026-10-31, s144 uiux cycle 95, RM-1314, the same detector):
  - test_match_row_focus_ring: flips data-theme in-page and reads the
    Session / History match rows' focus ring; the rows DO transition
    background and border colour, so its opener adds a transitions-off
    (and animations-off, for the deep-link pulse) sheet.
Audit (2026-11-01, s144 uiux cycle 102, RM-1321, the same detector), the
four s144 uiux modules added since:
  - test_lobby_lane_popup_keyboard, test_view_menu_keyboard: flip data-theme
    in-page and read the focused lane cells and the view trigger's ring; both
    pages add the transitions-off sheet before those reads.
  - test_theme_soft_token_hue, test_theme_signal_prim_hue: flip data-theme
    in-page but read only a bare probe div each read creates, with an explicit
    inline color. No sheet, and none needed: no transition applies to it.
Audit (2026-11-05, s150 landing fix, the same detector, each module's own
opener with and without its sheet), the six s144 uiux modules of RM-1546,
RM-1549, RM-1550, RM-1551, RM-1554 and RM-1555, landed with no row here:
  - test_history_result_marks_contrast, test_match_row_grade_chip_contrast,
    test_history_row_hover_marks_contrast: flip data-theme in-page (the
    hover module with each row under the real mouse) and read the History /
    Session rows, W / L counts, filter toggles and grade chips, which DO
    transition background and border colours on swap and hover; settled
    only because each opener adds a transitions-off (and animations-off)
    sheet.
  - test_home_accent2_focus_ring: flips data-theme in-page and reads the
    Home mode tabs' and champion name's focus ring; the mode tabs DO
    transition colour and border colour; settled only because its opener
    adds the sheet.
  - test_ops_page_state_text_contrast: flips data-theme in-page on
    /ops.html; nothing it reads transitioned with its sheet removed
    (measured once, not pinned: its pin runs with the opener's sheet), so
    the sheet it adds is belt and braces today.
  - test_zone_pill_contrast: boot-stamped (?theme=), never swaps in-page,
    no sheet; it re-classes the zone pill through its four states and reads
    colour and background. No transition runs on a re-class; ENEMY ZONE and
    DEEP ENEMY DO run the zoneWarn animation, on box-shadow only, which no
    read touches, so none is needed.
Audit (2026-11-06, s144 uiux cycle 153, RM-1773, the same detector plus
a no-swap sweep right after a real mouse hover and un-hover), the two s144
uiux hover modules of RM-1763 and RM-1764:
  - test_build_insights_sort_header_hover: boot-stamped (?theme=), never
    swaps in-page, no sheet; it reads the sort header's colour right after
    page.hover() and after the mouse leaves, with no wait. Nothing it reads
    transitions on boot, hover or un-hover, so none is needed.
  - test_last_match_review_nav_hover: boot-stamped, never swaps in-page;
    the Review nav tab and the Graph tab (.lm-tab) DO transition background
    and colour over 0.12s on hover and un-hover. Its reads were settled only
    by a 250 ms sleep; they now await getAnimations().finished on the tab
    (its _SETTLE), and the pin holds the sleep out of the module.
This module pins all thirty-four verdicts at runtime with each test's own opener,
so a new transition on a no-sheet surface, or the sheet dropped from a
shared opener, fails HERE with the element and property named. The fix is
the sheet in that test's opener, not a sleep. The inventory test keeps the
list complete: a new snapshot test that swaps the theme and reads computed
style must be added below.
"""
import copy
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_am_call_eyebrow_contrast import _EXPECT_LINES
from tests.snapshot_panels.test_am_call_eyebrow_contrast import (
    _THEMES as _EYEBROW_THEMES,
)
from tests.snapshot_panels.test_champ_select_arena_augment_options import (
    _OPT as _AUG_OPT,
)
from tests.snapshot_panels.test_champ_select_arena_augment_options import (
    _SILVER as _AUG_SILVER,
)
from tests.snapshot_panels.test_champ_select_arena_augment_options import (
    _fixture as _aug_fixture,
)
from tests.snapshot_panels.test_champ_select_arena_augment_options import (
    _open as _aug_open,
)
from tests.snapshot_panels.test_champ_select_lock_button_focus import (
    _BTN as _LOCK_BTN,
)
from tests.snapshot_panels.test_champ_select_lock_button_focus import (
    _READ_BTN as _LOCK_READ_BTN,
)
from tests.snapshot_panels.test_champ_select_lock_button_focus import (
    _open as _lock_open,
)
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import (
    _open as _cards_open,
)
from tests.snapshot_panels.test_ds_combo_controls_hit_floor import (
    _INPUT as _COMBO_INPUT,
)
from tests.snapshot_panels.test_ds_combo_controls_hit_floor import (
    _SELECT as _COMBO_SELECT,
)
from tests.snapshot_panels.test_ds_combo_controls_hit_floor import (
    _open as _combo_open,
)
from tests.snapshot_panels.test_ds_knob_inputs_focus_ring import _DSK, _DSS
from tests.snapshot_panels.test_ds_knob_inputs_focus_ring import (
    _open as _knob_open,
)
from tests.snapshot_panels.test_home_history_nav_focus_ring import (
    TABS as _HISTORY_TABS,
)
from tests.snapshot_panels.test_home_history_nav_focus_ring import (
    TILES as _HOME_TILES,
)
from tests.snapshot_panels.test_home_history_nav_focus_ring import (
    _open as _nav_open,
)
from tests.snapshot_panels.test_lm_hero_stats_disclosure import _SEL as _LM_SEL
from tests.snapshot_panels.test_lm_hero_stats_disclosure import (
    _open as _lm_open,
)
from tests.snapshot_panels.test_lobby_queue_buttons_focus_ring import (
    _POLL_LCU as _LQ_LCU,
)
from tests.snapshot_panels.test_lobby_queue_buttons_focus_ring import (
    _open as _lq_open,
)
from tests.snapshot_panels.test_match_row_focus_ring import _open as _mr_open
from tests.snapshot_panels.test_settings_checkbox_hit_targets import (
    _open as _settings_open,
)
from tests.snapshot_panels.test_tab_bars_selected_state import (
    _BARS,
    _THEMES,
)
from tests.snapshot_panels.test_tab_bars_selected_state import (
    _open as _bars_open,
)
from tests.snapshot_panels.test_user_builds_rune_tabs import _open as _ub_open

_HERE = Path(__file__).resolve().parent

# The thirty-four modules audited above, keyed by file name.
_COVERED = {
    "test_am_call_eyebrow_contrast.py",
    "test_build_insights_sort_header_hover.py",
    "test_champ_select_arena_augment_options.py",
    "test_champ_select_arena_pane_contrast.py",
    "test_champ_select_enemy_wr_slot_contrast.py",
    "test_champ_select_enemy_wr_slot_stale_cue.py",
    "test_champ_select_lock_button_focus.py",
    "test_ds_cards_muted_text_contrast.py",
    "test_ds_combo_controls_hit_floor.py",
    "test_ds_knob_inputs_focus_ring.py",
    "test_ds_matchup_text_contrast.py",
    "test_history_result_marks_contrast.py",
    "test_history_row_hover_marks_contrast.py",
    "test_home_accent2_focus_ring.py",
    "test_home_history_nav_focus_ring.py",
    "test_last_match_review_nav_hover.py",
    "test_lm_hero_stats_disclosure.py",
    "test_lobby_lane_popup_keyboard.py",
    "test_lobby_mains_tabs.py",
    "test_lobby_queue_buttons_focus_ring.py",
    "test_match_row_focus_ring.py",
    "test_match_row_grade_chip_contrast.py",
    "test_ops_page_state_text_contrast.py",
    "test_panel_visibility_tab_selected_state.py",
    "test_settings_checkbox_hit_targets.py",
    "test_tab_bars_selected_state.py",
    "test_theme_signal_prim_hue.py",
    "test_theme_soft_token_hue.py",
    "test_user_builds_rune_cells_focus_ring.py",
    "test_user_builds_rune_tabs.py",
    "test_user_builds_spell_chooser_keyboard.py",
    "test_view_menu_items.py",
    "test_view_menu_keyboard.py",
    "test_zone_pill_contrast.py",
}

_SHEET = "*, *::before, *::after { transition: none !important; }"

# Swap through every theme; after each swap (and each focus / blur when
# asked) force style on every measured element, then list the transitions
# and animations running on a measured element or any ancestor of one.
_RUNNING = """
([sel, themes, focus]) => {
  const root = document.documentElement;
  const els = Array.from(document.querySelectorAll(sel));
  const watched = new Set();
  for (const el of els) {
    for (let n = el; n; n = n.parentElement) watched.add(n);
  }
  const name = (n) => n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') +
    (typeof n.className === 'string' && n.className.trim()
      ? '.' + n.className.trim().split(/\\s+/).join('.') : '');
  const touch = (el) => {
    const cs = getComputedStyle(el);
    return cs.color + cs.backgroundColor + cs.boxShadow + cs.borderTopColor;
  };
  const running = [];
  const sweep = (t, step) => {
    for (const a of document.getAnimations()) {
      const tg = a.effect && a.effect.target;
      if (!tg || !watched.has(tg)) continue;
      running.push(t + '/' + step + ': ' + name(tg) + ' :: ' +
        (a.transitionProperty || a.animationName || 'animation'));
    }
  };
  if (document.activeElement) document.activeElement.blur();
  sweep('boot', 'load');
  for (const t of themes) {
    if (t === 'hextech') root.removeAttribute('data-theme');
    else root.dataset.theme = t;
    for (const n of watched) touch(n);
    sweep(t, 'swap');
    if (focus) {
      for (const el of els) {
        el.focus(); touch(el); sweep(t, 'focus');
        el.blur(); touch(el); sweep(t, 'blur');
      }
    }
  }
  root.removeAttribute('data-theme');
  return {n: els.length, running: Array.from(new Set(running))};
}
"""


def _check(page, sel, focus, tag, themes=_THEMES):
    got = page.evaluate(_RUNNING, [sel, themes, focus])
    assert got["n"] > 0, f"{tag}: {sel!r} matched nothing"
    assert not got["running"], (
        f"{tag}: a theme-swap read would straddle a transition "
        f"(add the transitions-off sheet to its opener): {got['running'][:6]}"
    )
    return got["n"]


def _close(ctx, page):
    page.close()
    ctx.close()


@pytest.mark.parametrize("bar", _BARS, ids=[b[0] for b in _BARS])
def test_tab_bar_reads_are_settled(mock_server, pw_browser, bar):
    # test_tab_bars_selected_state: one page per bar, as its fixture opens it.
    _name, view, bi_tab, sel, _count = bar
    ctx, page, _errors = _bars_open(pw_browser, mock_server, view, bi_tab, sel)
    try:
        _check(page, sel, False, _name)
    finally:
        _close(ctx, page)


def test_lobby_mains_tab_reads_are_settled(mock_server, pw_browser):
    from tests.snapshot_panels.test_lobby_mains_tabs import _SEL

    ctx, page, _errors = _bars_open(pw_browser, mock_server, "lobby", None, _SEL)
    try:
        # Focus too: its ring test reads box-shadow right after focus().
        _check(page, _SEL, True, "lobby mains tabs")
    finally:
        _close(ctx, page)


def test_view_menu_row_reads_are_settled(mock_server, pw_browser):
    from tests.snapshot_panels.test_view_menu_items import _ALL, _ROWS, _VIEW

    ctx, page, _errors = _bars_open(
        pw_browser, mock_server, _VIEW, None, "#history-scope-tabs .view-tab",
    )
    try:
        page.click("#view-trigger")
        page.wait_for_function(
            f"document.querySelector({_ALL!r}).getBoundingClientRect().width > 0",
            timeout=10_000,
        )
        _check(page, _ROWS, True, "view menu rows")
    finally:
        _close(ctx, page)


def test_settings_reads_are_settled(mock_server, pw_browser):
    # test_panel_visibility_tab_selected_state reads the .pv-tab colours over
    # the card; test_settings_checkbox_hit_targets focuses every checkbox and
    # reads its box-shadow. The settings opener (dev mode on) is a superset
    # of the panel-visibility fixture's page: same view, same card.
    ctx, page, _errors = _settings_open(pw_browser, mock_server, (1920, 920))
    try:
        page.keyboard.press("Tab")  # keyboard modality, as both tests do
        _check(page, "#panel-visibility-card .pv-tab", True, "pv tabs")
        n = _check(page, "#view-settings input[type=checkbox]", True, "checkboxes")
        assert n >= 20, f"only {n} settings checkboxes"
    finally:
        _close(ctx, page)


@pytest.mark.parametrize("theme", _EYEBROW_THEMES)
@pytest.mark.parametrize("mode", sorted(_EXPECT_LINES))
def test_am_call_eyebrow_reads_are_settled(mock_server, pw_browser, mode, theme):
    # test_am_call_eyebrow_contrast stamps the theme at BOOT (?theme=) and
    # boots each of its six themes, so the boot sweep is the one it depends
    # on: every boot theme it uses is booted here too (RM-1135; one boot
    # theme left the other five boot paths unmeasured). The swaps still run.
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode={mode}&theme={theme}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "(n) => document.querySelectorAll("
            "'#am-call-body > div[data-call-line]').length >= n",
            arg=len(_EXPECT_LINES[mode]),
            timeout=10_000,
        )
        # The boot really ran on this theme (a dropped ?theme= would boot
        # the default for all six and still pass the sweep).
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"{mode}: booted on the wrong theme, not {theme}"
        _check(
            page, "#am-call-body > div[data-call-line] > span", False,
            f"{mode}/{theme}",
        )
    finally:
        _close(ctx, page)


_UB_SELS = {
    "rune cells": "#ub-rp-primary-rows .ub-rp-rune, #ub-rp-secondary-rows .ub-rp-rune",
    "rune tabs": "#ub-rp-tabs > button, #ub-rp-sec-trees > button",
    "spell controls": "#ub-sp-slot-d, #ub-sp-slot-f, #ub-sp-grid .ub-sp-cell",
}


@pytest.fixture(scope="module")
def ub_page(mock_server, pw_browser):
    ctx, page, _errors = _ub_open(pw_browser, mock_server)
    try:
        yield page
    finally:
        _close(ctx, page)


@pytest.mark.parametrize("what", sorted(_UB_SELS))
def test_user_builds_reads_are_settled(ub_page, what):
    ub_page.keyboard.press("Shift")
    _check(ub_page, _UB_SELS[what], True, what)


def _matchup_open(mock_server, pw_browser, theme):
    # test_ds_matchup_text_contrast boots inline in its _measure: the same
    # URL, viewport and ready wait, kept in step with it by hand.
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}#active-match",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        "(() => { const g = document.querySelector("
        "'#csv-sugg-ds-matchup .dsm-grid');"
        " return !!g && g.checkVisibility(); })()",
        timeout=10_000,
    )
    return ctx, page, []


def _cs_boot_open(mode, ready):
    # test_champ_select_arena_pane_contrast, test_champ_select_enemy_wr_slot_
    # contrast and test_champ_select_enemy_wr_slot_stale_cue boot inline: the
    # same URL, viewport and ready element, kept in step with them by hand.
    def opener(mock_server, pw_browser, theme):
        mock_server._store["data"] = {}
        ctx = pw_browser.new_context(
            ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
        )
        page = ctx.new_page()
        page.add_init_script(_WS_STUB)
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode={mode}&theme={theme}#champ-select",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(ready, timeout=10_000)
        return ctx, page, []
    return opener


# The boot-theme modules: (opener(mock_server, pw_browser, theme), the
# elements they read, whether they read after focus()).
_BOOT = {
    "arena duo tag and augment title": (
        _cs_boot_open(
            "arena",
            "!!(document.querySelector('#view-champ-select .csv-duo-row')"
            " && document.querySelector("
            "'#view-champ-select .csv-augment-options .csv-augments-title'))",
        ),
        "#view-champ-select .csv-duo-cell-tag,"
        " #view-champ-select .csv-augment-options .csv-augments-title",
        False,
    ),
    "sr enemy win-rate slot": (
        _cs_boot_open(
            "sr",
            "!!document.querySelector("
            "'#view-champ-select #csv-enemies-list .csv-enemy-wr-slot')",
        ),
        "#view-champ-select #csv-enemies-list .csv-enemy-wr-slot", False,
    ),
    "ds combo controls": (
        lambda ms, pw, t: _combo_open(ms, pw, "sr", t),
        f"{_COMBO_INPUT}, {_COMBO_SELECT}", True,
    ),
    "ds knob inputs": (
        lambda ms, pw, t: _knob_open(ms, pw, t), f"{_DSK}, {_DSS}", True,
    ),
    "lm hero stats summary": (
        lambda ms, pw, t: _lm_open(ms, pw, "sr", t), _LM_SEL, True,
    ),
    "ds matchup card": (
        _matchup_open, "#csv-sugg-ds-matchup, #csv-sugg-ds-matchup *", False,
    ),
    "ds relscore and shaper": (
        lambda ms, pw, t: _cards_open(ms, pw, t, {"ok": False})[:3],
        "#csv-ds-relscore, #csv-ds-relscore *,"
        " #view-active-match .bm-shaper, #view-active-match .bm-shaper *",
        False,
    ),
}


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("what", sorted(_BOOT))
def test_boot_theme_reads_are_settled(mock_server, pw_browser, what, theme):
    opener, sel, focus = _BOOT[what]
    ctx, page, _errors = opener(mock_server, pw_browser, theme)
    try:
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"{what}: booted on the wrong theme, not {theme}"
        page.keyboard.press("Shift")  # keyboard modality, as the ring reads do
        # The boot this module depends on, then focus / blur on that theme.
        _check(page, sel, focus, f"{what}/{theme}", themes=[theme])
        # The in-page swaps still run.
        _check(page, sel, False, f"{what}/{theme} swaps")
    finally:
        _close(ctx, page)


@pytest.mark.parametrize("theme", _THEMES)
def test_lock_button_reads_wait_out_its_transition(mock_server, pw_browser, theme):
    # #csv-lock-btn is settled at boot and across swaps, but its box-shadow
    # DOES transition on focus, so its reads must await the transition.
    ctx, page, _errors = _lock_open(mock_server, pw_browser, "sr", theme)
    try:
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        page.keyboard.press("Shift")
        _check(page, _LOCK_BTN, False, f"lock button/{theme}", themes=[theme])
        _check(page, _LOCK_BTN, False, f"lock button/{theme} swaps")
        got = page.evaluate(_RUNNING, [_LOCK_BTN, [theme], True])
    finally:
        _close(ctx, page)
    assert got["n"] == 1, got
    assert any("box-shadow" in r for r in got["running"]), (
        f"{theme}: the LOCK IN focus transition is gone - re-audit "
        f"test_champ_select_lock_button_focus and update the verdict: {got}"
    )
    src = (_HERE / "test_champ_select_lock_button_focus.py").read_text(
        encoding="utf-8"
    )
    assert "await Promise.allSettled(as.map((a) => a.finished));" in src, (
        "the focused-ring read no longer waits out the box-shadow transition"
    )
    assert "await Promise.allSettled(as.map((x) => x.finished));" in (
        _LOCK_READ_BTN
    ), "the pending-lock read no longer waits out the transition"


@pytest.mark.parametrize("theme", _THEMES)
def test_augment_option_reads_wait_out_their_transition(mock_server, pw_browser, theme):
    # The Arena augment option rows are settled at boot and across swaps, but
    # their box-shadow DOES transition on focus, so the focused-ring read in
    # test_champ_select_arena_augment_options must await it.
    ctx, page, _errors = _aug_open(mock_server, pw_browser, _aug_fixture(_AUG_SILVER), theme)
    try:
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        page.keyboard.press("Shift")
        # Only the boot this module depends on: it never swaps in-page (an
        # in-page swap here does transition the rows' background and border).
        _check(page, _AUG_OPT, False, f"augment options/{theme}", themes=[theme])
        got = page.evaluate(_RUNNING, [_AUG_OPT, [theme], True])
    finally:
        _close(ctx, page)
    assert got["n"] >= 1, got
    assert any("box-shadow" in r for r in got["running"]), (
        f"{theme}: the augment option focus transition is gone - re-audit "
        f"test_champ_select_arena_augment_options and update the verdict: {got}"
    )
    src = (_HERE / "test_champ_select_arena_augment_options.py").read_text(
        encoding="utf-8"
    )
    assert "await Promise.allSettled(as.map((a) => a.finished));" in src, (
        "the focused augment option read no longer waits out the box-shadow transition"
    )


@pytest.mark.parametrize("what", ["home tiles", "history tabs", "lobby queue buttons"])
def test_nav_and_queue_ring_reads_are_settled(mock_server, pw_browser, what):
    # test_home_history_nav_focus_ring and test_lobby_queue_buttons_focus_ring
    # flip data-theme in-page and read each control's focus ring after a key
    # press, with each module's own opener.
    if what == "lobby queue buttons":
        ctx, page, _errors = _lq_open(pw_browser, mock_server, copy.deepcopy(_LQ_LCU))
        sel = ".lobby-view-queue-controls .lq-btn"
    else:
        view, sel = (("home", _HOME_TILES) if what == "home tiles"
                     else ("history", _HISTORY_TABS))
        ctx, page, _errors = _nav_open(pw_browser, mock_server, view)
    try:
        page.keyboard.press("Shift")  # keyboard modality, as the ring reads do
        _check(page, sel, True, what)
    finally:
        _close(ctx, page)


@pytest.mark.parametrize("view", ["session", "history"])
def test_match_row_ring_reads_are_settled(mock_server, pw_browser, view):
    # test_match_row_focus_ring flips data-theme in-page and reads each
    # focused Session / History match row's ring, with its own opener.
    ctx, page, _errors, sel, _n = _mr_open(pw_browser, mock_server, view)
    try:
        page.keyboard.press("Shift")  # keyboard modality, as the ring reads do
        _check(page, sel, True, f"{view} match rows")
    finally:
        _close(ctx, page)


def test_view_trigger_ring_reads_are_settled(mock_server, pw_browser):
    # test_view_menu_keyboard flips data-theme in-page and reads the focused
    # trigger's outline over its header, with its own opener.
    from tests.snapshot_panels.test_view_menu_keyboard import _open_view

    ctx, page, _errors = _open_view(pw_browser, mock_server)
    try:
        page.keyboard.press("Shift")  # keyboard modality, as the ring read does
        _check(page, "#view-trigger", True, "view trigger")
    finally:
        _close(ctx, page)


def test_lane_cell_ring_reads_are_settled(mock_server, pw_browser):
    # test_lobby_lane_popup_keyboard adds the sheet in its ring test, not in
    # its opener, so the pin holds the sheet there by source and the verdict
    # with the sheet on.
    from tests.snapshot_panels.test_lobby_lane_popup_keyboard import (
        _CELLS,
        _NO_TRANSITIONS,
        _keyboard_open,
        _open_lobby,
    )

    assert _NO_TRANSITIONS == _SHEET
    src = (_HERE / "test_lobby_lane_popup_keyboard.py").read_text(encoding="utf-8")
    assert "page.add_style_tag(content=_NO_TRANSITIONS)" in src, (
        "the lane cell ring test no longer adds the transitions-off sheet"
    )
    ctx, page, _errors, _posts = _open_lobby(
        pw_browser, mock_server, (1920, 920),
    )
    try:
        page.add_style_tag(content=_SHEET)
        _keyboard_open(page)
        page.keyboard.press("Shift")  # keyboard modality, as the ring read does
        _check(page, _CELLS, True, "lobby lane cells")
    finally:
        _close(ctx, page)


@pytest.mark.parametrize(
    "module", ["test_theme_soft_token_hue.py", "test_theme_signal_prim_hue.py"],
)
def test_token_probe_reads_are_settled(mock_server, pw_browser, module):
    # Both modules read tokens only through a bare div each read creates, so
    # the source pin keeps that shape and the runtime read proves no
    # transition applies to such a div under the same swaps. Both load the
    # same /?ui_mock=1#home page; the signal module opens it inline, so the
    # soft-token module's opener stands in for both.
    from tests.snapshot_panels.test_theme_soft_token_hue import _open as _hue_open

    src = (_HERE / module).read_text(encoding="utf-8")
    assert "const d = document.createElement('div');" in src, module
    assert "return getComputedStyle(d).color;" in src, module
    assert src.count("getComputedStyle") == 1, module
    ctx, page, _errors = _hue_open(pw_browser, mock_server)
    try:
        page.evaluate(
            """() => {
              const d = document.createElement('div');
              d.id = 'probe-u105';
              document.body.appendChild(d);
            }"""
        )
        _check(page, "#probe-u105", False, module)
    finally:
        _close(ctx, page)


def _plain_page(pw_browser, mock_server):
    # The context the History / Session contrast fixtures make for their
    # own _open_view pages.
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    return ctx, page


def test_history_result_mark_reads_are_settled(mock_server, pw_browser):
    # test_history_result_marks_contrast flips data-theme in-page over the
    # match rows (their ::before glyph and tint), the session W / L counts
    # and the filter toggles, with its own opener.
    from tests.snapshot_panels.test_history_result_marks_contrast import (
        _READS,
        _open,
    )

    ctx, page, _errors = _open(pw_browser, mock_server)
    try:
        _check(page, _READS, False, "history result marks")
    finally:
        _close(ctx, page)


@pytest.mark.parametrize("scan", ["session-rows", "history", "session"])
def test_history_row_hover_reads_are_settled(mock_server, pw_browser, scan):
    # test_history_row_hover_marks_contrast reads each row's marks with that
    # row under the real mouse, after each data-theme flip, on its own
    # _open_view page: every row is hovered here, then swept.
    from tests.snapshot_panels.test_history_row_hover_marks_contrast import (
        _SCANS,
        _open_view,
    )

    ctx, page = _plain_page(pw_browser, mock_server)
    try:
        _open_view(page, mock_server, "session" if scan == "session" else "history")
        rows, _grades = _SCANS[scan]
        sel = f"{rows}, {rows} .hs-w, {rows} .hs-l, {rows} > .home-recent-grade"
        n = page.evaluate("(s) => document.querySelectorAll(s).length", rows)
        assert n >= 2, f"{scan}: only {n} rows to hover"
        for i in range(n):
            page.locator(rows).nth(i).hover()
            _check(page, sel, False, f"{scan} row {i} hovered")
    finally:
        _close(ctx, page)


@pytest.mark.parametrize("view", ["history", "session"])
def test_grade_chip_reads_are_settled(mock_server, pw_browser, view):
    # test_match_row_grade_chip_contrast flips data-theme in-page and
    # re-classes each match row's grade chip, on its own _open_view page.
    from tests.snapshot_panels.test_match_row_grade_chip_contrast import (
        _LISTS,
        _open_view,
    )

    ctx, page = _plain_page(pw_browser, mock_server)
    try:
        _open_view(page, mock_server, view)
        lst = _LISTS[view]
        _check(page, f"{lst} > li, {lst} > li > .home-recent-grade", False,
               f"{view} grade chips")
    finally:
        _close(ctx, page)


def test_home_accent_ring_reads_are_settled(mock_server, pw_browser):
    # test_home_accent2_focus_ring flips data-theme in-page and reads each
    # focused mode tab's and the champion name's ring, with its own opener.
    from tests.snapshot_panels.test_home_accent2_focus_ring import (
        CHAMP,
        TABS,
        _open,
    )

    ctx, page, _errors = _open(pw_browser, mock_server)
    try:
        _check(page, f"{TABS}, {CHAMP}", True, "home accent rings")
    finally:
        _close(ctx, page)


def test_ops_page_state_text_reads_are_settled(mock_server, pw_browser):
    # test_ops_page_state_text_contrast flips data-theme in-page on /ops.html
    # and reads every state-coloured text, with its own opener.
    from tests.snapshot_panels.test_ops_page_state_text_contrast import (
        _READS,
        _open,
    )

    ctx, page, _errors = _open(pw_browser, mock_server)
    try:
        _check(page, _READS, False, "ops page state text")
    finally:
        _close(ctx, page)


_ZONE_SEL = "#zone-pill, #zone-label"

# Re-class the zone pill through each state, as test_zone_pill_contrast's
# _MEASURE_JS does, and list every transition / animation then running on
# the pill, its label or an ancestor, with the properties it animates.
_ZONE_RECLASS = """
(labels) => {
  const p = document.getElementById('zone-pill');
  const b = document.getElementById('zone-label');
  const watched = new Set();
  for (const el of [p, b]) {
    for (let n = el; n; n = n.parentElement) watched.add(n);
  }
  const skip = new Set(['offset', 'computedOffset', 'easing', 'composite']);
  const out = {};
  const prev = [p.className, b.textContent];
  for (const [key, [text, cls]] of Object.entries(labels)) {
    p.className = cls;
    b.textContent = text;
    for (const n of watched) {
      const cs = getComputedStyle(n);
      void (cs.color + cs.backgroundColor + cs.boxShadow);
    }
    const rows = [];
    for (const a of document.getAnimations()) {
      const tg = a.effect && a.effect.target;
      if (!tg || !watched.has(tg)) continue;
      const props = new Set();
      for (const kf of a.effect.getKeyframes()) {
        for (const k of Object.keys(kf)) if (!skip.has(k)) props.add(k);
      }
      rows.push({kind: a.transitionProperty ? 'transition' : 'animation',
                 name: a.transitionProperty || a.animationName || '',
                 props: Array.from(props).sort()});
    }
    out[key] = rows;
  }
  // Back to the boot state, so the boot / swap sweeps after this see it.
  [p.className, b.textContent] = prev;
  getComputedStyle(p).backgroundColor;
  return out;
}
"""


@pytest.mark.parametrize("theme", _THEMES)
def test_zone_pill_reads_are_settled(mock_server, pw_browser, theme):
    # test_zone_pill_contrast boots each theme (?theme=), never swaps
    # in-page, and re-classes the pill through its four states, reading the
    # label's colour and the pill's (and ancestors') background.
    from tests.snapshot_panels.test_zone_pill_contrast import _LABELS
    from tests.snapshot_panels.test_zone_pill_contrast import _open as _zone_open

    ctx, page, _errors = _zone_open(pw_browser, mock_server, theme)
    booted = "document.documentElement.dataset.theme || 'hextech'"
    try:
        assert page.evaluate(booted) == theme, (
            f"zone pill: booted on the wrong theme, not {theme}"
        )
        # The re-class first, on the booted theme: _check ends by removing
        # data-theme, so a re-class after it would run on hextech only.
        got = page.evaluate(_ZONE_RECLASS, _LABELS)
        assert page.evaluate(booted) == theme, (
            f"zone pill: the re-class ran off the booted theme {theme}"
        )
        assert sorted(got) == sorted(_LABELS), got
        # No transition on any re-class, and every animation leaves the read
        # properties (colour, background) alone.
        bad = [(k, r) for k, rows in got.items() for r in rows
               if r["kind"] == "transition" or r["props"] != ["boxShadow"]]
        assert not bad, (
            f"{theme}: a zone pill re-class read would straddle a transition"
            f" or a colour animation (add the transitions-off sheet): {bad}"
        )
        # The detector is not blind: the box-shadow pulse it tolerates is seen.
        pulsing = sorted(k for k, rows in got.items()
                         if any(r["name"] == "zoneWarn" for r in rows))
        assert pulsing == ["deep", "enemy"], (
            f"{theme}: the zoneWarn pulse moved - re-audit"
            f" test_zone_pill_contrast and update the verdict: {got}"
        )
        _check(page, _ZONE_SEL, False, f"zone pill/{theme}", themes=[theme])
        _check(page, _ZONE_SEL, False, f"zone pill/{theme} swaps")
    finally:
        _close(ctx, page)


# Force style on every element sel matches and its ancestors, then list the
# transitions / animations running on one of them, with no theme change:
# the read a hover-then-measure module makes right after the mouse moves.
_RUNNING_NOW = """
(sel) => {
  const watched = new Set();
  for (const el of document.querySelectorAll(sel)) {
    for (let n = el; n; n = n.parentElement) watched.add(n);
  }
  for (const n of watched) {
    const cs = getComputedStyle(n);
    void (cs.color + cs.backgroundColor + cs.boxShadow + cs.borderTopColor);
  }
  const out = [];
  for (const a of document.getAnimations()) {
    const tg = a.effect && a.effect.target;
    if (!tg || !watched.has(tg)) continue;
    out.push((tg.id || tg.className) + ' :: ' +
      (a.transitionProperty || a.animationName || 'animation'));
  }
  return out;
}
"""

_BOOTED = "document.documentElement.dataset.theme || 'hextech'"


@pytest.mark.parametrize("theme", _THEMES)
def test_bi_sort_header_hover_reads_are_settled(mock_server, pw_browser, theme):
    # test_build_insights_sort_header_hover boots each theme (?theme=), never
    # swaps in-page, and reads the sort header's colour right after a real
    # mouse hover and un-hover, with no wait. Nothing it reads transitions.
    from tests.snapshot_panels.test_build_insights_sort_header_hover import (
        _EXP,
        _SEL,
    )
    from tests.snapshot_panels.test_build_insights_sort_header_hover import (
        _open as _bi_open,
    )

    ctx, page, _errors = _bi_open(pw_browser, mock_server, theme)
    try:
        assert page.evaluate(_BOOTED) == theme, (
            f"bi sort header: booted on the wrong theme, not {theme}"
        )
        # The hovers first, on the booted theme: _check ends on hextech.
        for sel in (_SEL, _EXP):
            page.hover(sel)
            got = page.evaluate(_RUNNING_NOW, sel)
            assert not got, (
                f"{theme}: a hovered {sel!r} read would straddle a transition"
                f" (settle the read in its module): {got}"
            )
            page.mouse.move(2, 2)
            got = page.evaluate(_RUNNING_NOW, sel)
            assert not got, (
                f"{theme}: an un-hovered {sel!r} read would straddle a"
                f" transition (settle the read in its module): {got}"
            )
        _check(page, f"{_SEL}, {_EXP}", False, f"bi sort header/{theme}",
               themes=[theme])
    finally:
        _close(ctx, page)


@pytest.mark.parametrize("theme", _THEMES)
def test_review_nav_hover_reads_wait_out_their_transition(mock_server, pw_browser, theme):
    # test_last_match_review_nav_hover boots each theme (?theme=) and never
    # swaps in-page (an in-page swap here does transition the tabs' colour),
    # but .lm-tab DOES transition background and colour on hover and
    # un-hover, so its colour reads must await the transition.
    from tests.snapshot_panels import test_last_match_review_nav_hover as lm

    ctx, page, _errors = lm._open(pw_browser, mock_server, theme)
    try:
        assert page.evaluate(_BOOTED) == theme, (
            f"review nav: booted on the wrong theme, not {theme}"
        )
        for sel, own in ((lm._NAV, "lm-go-to-review"), (lm._TAB, "lm-tab")):
            # On the tab itself, not an ancestor: "<id or class> :: color".
            want = f"{own} :: color"
            for step, move in (("hover", lambda s=sel: page.hover(s)),
                               ("un-hover", lambda: page.mouse.move(2, 2))):
                move()
                raw = page.evaluate(_RUNNING_NOW, sel)
                assert want in raw, (
                    f"{theme}: the {sel!r} {step} colour transition is gone -"
                    f" re-audit test_last_match_review_nav_hover and update"
                    f" the verdict: {raw}"
                )
                # The module's own settle leaves nothing running.
                page.evaluate(lm._SETTLE, sel)
                after = page.evaluate(_RUNNING_NOW, sel)
                assert not after, (
                    f"{theme}: {sel!r} still moving after _SETTLE ({step}): {after}"
                )
            lm._hover(page, sel)
            assert not page.evaluate(_RUNNING_NOW, sel), sel
            lm._unhover(page, sel)
            assert not page.evaluate(_RUNNING_NOW, sel), sel
        _check(page, f"{lm._NAV}, {lm._TAB}", False, f"review nav/{theme}",
               themes=[theme])
    finally:
        _close(ctx, page)
    src = (_HERE / "test_last_match_review_nav_hover.py").read_text(encoding="utf-8")
    assert "await Promise.allSettled(as.map((a) => a.finished));" in lm._SETTLE
    assert "wait_for_timeout" not in src, "a fixed sleep stands in for the settle"
    # Every hover and un-hover in the module goes through the settled pair.
    assert src.count("page.hover(") == 1 and src.count("page.mouse.move(2, 2)") == 2, (
        "a hover or un-hover in the module bypasses _hover / _unhover"
    )


def test_positive_control_detects_a_real_transition(mock_server, pw_browser):
    # The detector is not blind: with the opener's sheet removed, the spell
    # cells' background / border transitions are caught after a swap.
    ctx, page, _errors = _ub_open(pw_browser, mock_server)
    try:
        removed = page.evaluate(
            """(sheet) => {
              let k = 0;
              for (const s of document.querySelectorAll('style')) {
                if (s.textContent.trim() === sheet) { s.remove(); k++; }
              }
              return k;
            }""",
            _SHEET,
        )
        assert removed >= 1, "the opener's transitions-off sheet was not found"
        got = page.evaluate(_RUNNING, [_UB_SELS["spell controls"], _THEMES, False])
    finally:
        _close(ctx, page)
    assert got["n"] > 0
    assert any("background-color" in r for r in got["running"]), got


def test_inventory_covers_every_theme_swapping_reader():
    # A module that swaps or resets the theme in-page (dataset.theme =,
    # ?theme=, or a data-theme attribute call after an imported swap such as
    # test_lobby_mains_tabs' shared _MEASURE) and reads getComputedStyle
    # belongs in the audit above.
    swap = re.compile(
        r"dataset\.theme\s*=(?!=)|[?&]theme=|Attribute\(['\"]data-theme"
    )
    found = set()
    for path in sorted(_HERE.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        if swap.search(text) and "getComputedStyle" in text:
            found.add(path.name)
    assert found, "enumeration found no theme-swapping reader at all"
    assert found == _COVERED, (
        f"new: {sorted(found - _COVERED)}; gone: {sorted(_COVERED - found)}"
    )
