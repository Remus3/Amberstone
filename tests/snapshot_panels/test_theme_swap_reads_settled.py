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
This module pins all twenty-one verdicts at runtime with each test's own opener,
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

# The twenty-one modules audited above, keyed by file name.
_COVERED = {
    "test_am_call_eyebrow_contrast.py",
    "test_champ_select_arena_augment_options.py",
    "test_champ_select_arena_pane_contrast.py",
    "test_champ_select_enemy_wr_slot_contrast.py",
    "test_champ_select_enemy_wr_slot_stale_cue.py",
    "test_champ_select_lock_button_focus.py",
    "test_ds_cards_muted_text_contrast.py",
    "test_ds_combo_controls_hit_floor.py",
    "test_ds_knob_inputs_focus_ring.py",
    "test_ds_matchup_text_contrast.py",
    "test_home_history_nav_focus_ring.py",
    "test_lm_hero_stats_disclosure.py",
    "test_lobby_mains_tabs.py",
    "test_lobby_queue_buttons_focus_ring.py",
    "test_panel_visibility_tab_selected_state.py",
    "test_settings_checkbox_hit_targets.py",
    "test_tab_bars_selected_state.py",
    "test_user_builds_rune_cells_focus_ring.py",
    "test_user_builds_rune_tabs.py",
    "test_user_builds_spell_chooser_keyboard.py",
    "test_view_menu_items.py",
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
    assert "await Promise.all(el.getAnimations().map((a) => a.finished));" in src, (
        "the focused-ring read no longer waits out the box-shadow transition"
    )
    assert "await Promise.all(b.getAnimations().map((x) => x.finished));" in (
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
    assert "await Promise.all(el.getAnimations().map((a) => a.finished));" in src, (
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
