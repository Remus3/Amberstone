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
Audit (2026-11-07, s144 uiux cycle 186, S144-U-196, the same detector at
each read moment), the s144 uiux module of S144-U-194, landed on lane/uiux
with no row here:
  - test_lobby_mains_recent_cell: boot-stamped (?theme=), never swaps
    in-page, no sheet; it clicks a MAINS tab and reads the RECENT result
    word and the OVERALL W / L colours of the freshly rendered rows. Nothing
    it reads, nor any ancestor, transitions at that moment, so none is
    needed.
Audit (2026-11-08, s144 uiux cycle 207, S144-U-214, a document-wide
detector: every transition or animation running anywhere in the page at
each getComputedStyle read the module's own _measure makes, with its fixed
sleeps taken out and no sheet), the nine s144 uiux contrast modules of
S144-U-199..U-209, landed on lane/uiux with no row here. All nine stamp
the theme at BOOT (?theme=) and never swap in-page:
  - test_footer_mode_pill_contrast, test_home_muted_text_contrast,
    test_lobby_text_contrast, test_session_text_contrast: no sheet, and
    none needed - nothing runs at their reads. The footer and Lobby reads
    re-class the mode pill and the Accept / Party toggles inside one
    evaluate: nothing on the pill transitions on a re-class, and the
    toggles DO transition their four border colours, which no read touches
    (each reads colour and the background under it), so none is needed;
    the pin holds those transitions to the border colours.
  - test_historical_pgr_text_contrast: its archive read is settled without
    its 400 ms sleep (nothing runs at it), so the sleep goes and no sheet
    is needed; its state-marks read keeps a sheet, now this full
    transitions-off sheet in place of a bare `*` rule plus a 200 ms sleep.
  - test_build_insights_chart_text_contrast, test_pgr_text_contrast,
    test_home_pick_name_contrast, test_user_builds_text_contrast: the
    Build Insights tabs and Clear button, the PGR tabs, the Tonight's Pick
    name and the User Builds champion input, Delete and Add buttons DO
    transition at their reads (tab click, hover, fill, click); they were
    settled only by 400 / 400 / 300 / 250 ms sleeps. Each opener now adds
    the sheet and the sleeps are gone. Measured on the way: the Build
    Insights sleep was also the only wait for the Skills / Runes / Spells
    / Bench async paint (without it a read saw 14 rows ending in
    "loading..." instead of 83), now a wait for each tab's own content;
    and the User Builds "+ Add build" read straddled its background
    transition with every sleep in place (no sleep sat before it), so it
    measured a mid-transition fill (hextech 201,172,115 for the settled
    205,181,132) until the sheet.
Audit (2026-11-08, s144 uiux cycle 208, S144-U-215, the same
document-wide detector at each getComputedStyle read its own _measure
makes), the s144 uiux module of S144-U-215:
  - test_ui_mock_active_match_complete: boot-stamped (?theme=), never
    swaps in-page, no sheet and no sleep; it waits for the BUILD module to
    land and reads the Daemon Slayer row's "All six item slots full" line
    and the pane surface under it. Nothing runs anywhere in the page at
    that read, so none is needed.
Audit (2026-11-08, s144 uiux cycle 216, S144-U-223, the same
document-wide detector at each getComputedStyle read its own _measure
makes), the s144 uiux module of S144-U-223:
  - test_am_map_roster_state_contrast: boot-stamped (?theme=), never swaps
    in-page, no sheet and no sleep; it reads the MAP roster's state words
    and the row under them on a live feed, then again after the page clock
    runs the feed past its stale cut and the rows re-class to "no feed".
    Nothing runs anywhere in the page at either read, so none is needed.
Audit (2026-11-08, s144 uiux cycle 235, S144-U-240, the same
document-wide detector at each getComputedStyle read its own _measure
makes), the s144 uiux module of S144-U-240:
  - test_header_placeholder_pill_contrast: boot-stamped (?theme=), never
    swaps in-page; it waits for the zone and CS placeholders, adds the
    transitions-off sheet, then reads the Active Match header's text and
    re-classes the hidden zone pill through its stale zone classes inside
    the same evaluate. The sheet covers the zone pill's colour and the
    hidden rule drops its pulse, so nothing runs at that read.
Audit (2026-11-08, s144 uiux cycle 236, S144-U-241, the same
document-wide detector at each getComputedStyle read its own _measure
makes), the seven s144 uiux modules of S144-U-233..239, landed on
lane/uiux with no row here:
  - test_champ_select_ban_phase_over_head_contrast,
    test_champ_select_personal_build_contrast: flip dataset.theme in-page
    on the booted champ-select page and read at once. In five of six
    themes (all but arcane) the swap left transitions running at the read
    (the view trigger's colours, the heartbeat and title caret colour, the
    rune-save button, build-path rows and items, bench cells): 10 of 12
    runs straddled. Settled now because both openers add the sheet before
    the swap; every contrast verdict in both modules still holds.
  - test_last_match_build_wpa_contrast,
    test_lobby_mains_placeholder_contrast,
    test_lobby_roster_row_dimming_contrast,
    test_session_hygiene_inert_contrast: boot-stamped (?theme=), never
    swap in-page; each opener adds the sheet before its read (the roster
    module reads again after a real mouse hover, the Lobby mains one after
    a tab click), and nothing runs at their reads with it.
  - test_ui_mock_active_match_build_eyebrows: boot-stamped, never swaps
    in-page, no sheet and no sleep; nothing runs anywhere in the page at
    its read. Its reader is now _measure(mock_server, pw_browser, theme,
    surface) so the pin drives it with its first surface.
Audit (2026-11-09, s144 uiux cycle 237, S144-U-242, the same
document-wide detector at each getComputedStyle read its own _measure
makes), the s144 uiux module of S144-U-242:
  - test_replay_match_row_text_contrast: boot-stamped (?theme=), never
    swaps in-page; it waits for the four RECENT MATCHES rows, adds the
    transitions-off sheet, then reads them at rest, under a real mouse
    hover on each row and after a click picks each row. The rows DO
    transition their background (120ms) on hover and pick, so the sheet is
    what settles those reads.
Audit (2026-11-09, s144 uiux cycle 238, S144-U-243, the same
document-wide detector at each getComputedStyle read its own _measure
makes), the s144 uiux module of S144-U-243:
  - test_am_empty_line_contrast: boot-stamped (?theme=), never swaps
    in-page; it waits for the mode's Active Match empty lines (the spike
    curve's and, outside aram, the ward heat strip's), adds the
    transitions-off sheet, then reads them in one evaluate. Nothing it
    reads transitions, so the sheet is belt and braces, not a fix.
Audit (2026-11-09, s144 uiux cycle 240, S144-U-245, the same
document-wide detector at each getComputedStyle read its own _measure
makes), the s144 uiux module of S144-U-245:
  - test_zoi_debug_readout: boot-stamped (?theme=), never swaps in-page;
    it adds the transitions-off sheet, drives map_state.js
    renderMinimapCanvases() with a deep-enemy call (no style read), then
    reads the ?debug=1 readout under the Active Match map in one
    evaluate. Nothing it reads transitions, so the sheet is belt and
    braces, not a fix.
Audit (2026-11-09, s144 uiux cycle 245, S144-U-250, the same
detector), the s144 uiux module of S144-U-250:
  - test_lobby_queue_fill_text_contrast: flips data-theme in-page on the
    polled Lobby page and reads the live Find Match / Cancel Queue labels
    at rest and under a real mouse hover. The queue buttons DO transition
    background and border colour on a swap and a hover, so its opener adds
    the transitions-off sheet before the flip, and emulates reduced motion
    so the searching Find Match pulse (an animation) is a static ring. It
    joins the contrast pin below on its Searching state.
Audit (2026-11-09, s144 uiux cycle 246, S144-U-251, the same
detector), the s144 uiux module of S144-U-251:
  - test_lobby_mode_menu_current_contrast: boots the ui_mock Lobby in the
    theme (?theme=), opens the Change Lobby Mode menu and the lane popup
    and reads their labels at rest and under a real mouse hover. The menu
    items DO transition background and border colour on a hover, so its
    opener adds the transitions-off sheet before the first click. It joins
    the contrast pin below.
Audit (2026-11-09, s144 uiux cycle 248, S144-U-253, the same
detector), the s144 uiux module of S144-U-253:
  - test_home_find_match_picker_contrast: boots the ui_mock Home in the
    theme (?theme=), opens the Find Match picker from the hero CTA and
    reads its labels at rest, under a real mouse hover and on the item a
    keyboard Tab focuses. The queue items DO transition background and
    border colour on a hover, so its opener adds the transitions-off sheet
    before the first click. It joins the contrast pin below.
Audit (2026-11-09, s144 uiux cycle 250, S144-U-255, the same
detector), the s144 uiux module of S144-U-255:
  - test_item_value_bar_relocated: boot-stamped (?theme=), never swaps
    in-page; it adds the transitions-off sheet, then drives map_state.js
    renderItemValueDiff() under the Active Match map and reads the label
    and the signed number in the same evaluate. The bar's fill DOES
    transition left / right / background-color on a render, but no read
    is on the fill or an ancestor of it, and the sheet is on before the
    first render. It joins the contrast pin below.
Audit (2026-11-09, s144 uiux cycle 263, S144-U-269, the same
detector), the s144 uiux module of S144-U-269:
  - test_coach_decisions_banner_contrast: boots the ui_mock Active Match
    in the theme (?theme=) with a routed /api/decisions, emulates reduced
    motion, adds the transitions-off sheet and waits out the row's
    slide-in animation, then reads the coach decisions banner at rest,
    under a real mouse hover and on each keyboard-focused button. The
    buttons carry no transition; the sheet and the animation wait are on
    before the first read. It joins the contrast pin below.
Audit (2026-11-09, s144 uiux cycle 266, S144-U-272, the same
detector), the s144 uiux module of S144-U-272:
  - test_overlay_empty_caption_contrast: boot-stamped (?theme=), never
    swaps in-page; it waits for the overlay fight-model pane's caption and
    empty line (?overlay=1&ui_mock=1) or for the Active Match .am-empty
    placeholders (no mock, dashboard and ?overlay=1), adds the
    transitions-off sheet, then reads them in one evaluate. Nothing it
    reads transitions, so the sheet is belt and braces, not a fix. It joins
    the contrast pin below.
Audit (2026-11-09, s144 uiux cycle 269, S144-U-275, the same
detector), the s144 uiux module of S144-U-275:
  - test_overlay_call_glyph_contrast: boot-stamped (?theme=), never
    swaps in-page; it waits for the w-call ACTION row's band glyph
    (?overlay=1&ui_mock=1), adds the transitions-off sheet, then reads the
    glyph and bar per band and the widget's live and idle opacity in one
    evaluate (the widget's own opacity transition is also switched off
    inline for that read). It joins the contrast pin below.
Audit (2026-11-09, s144 uiux cycle 270, S144-U-277, the same
detector), the s144 uiux module of S144-U-277:
  - test_overlay_lead_bar_contrast: boot-stamped (?theme=), never swaps
    in-page; it waits for the #rn-lead widget mount (?overlay=1&ui_mock=1),
    adds the transitions-off sheet, then renders the pill per state through
    callouts.js renderLead and reads the bar, the pill's backing and the
    widget's live and idle opacity in one evaluate (the widget's own
    opacity transition is also switched off inline for that read). It
    joins the contrast pin below.
This module pins all sixty-five verdicts at runtime with each test's own opener,
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

# The sixty-five modules audited above, keyed by file name.
_COVERED = {
    "test_am_call_eyebrow_contrast.py",
    "test_am_empty_line_contrast.py",
    "test_am_map_roster_state_contrast.py",
    "test_build_insights_chart_text_contrast.py",
    "test_build_insights_sort_header_hover.py",
    "test_champ_select_arena_augment_options.py",
    "test_champ_select_arena_pane_contrast.py",
    "test_champ_select_ban_phase_over_head_contrast.py",
    "test_champ_select_enemy_wr_slot_contrast.py",
    "test_champ_select_enemy_wr_slot_stale_cue.py",
    "test_champ_select_lock_button_focus.py",
    "test_champ_select_personal_build_contrast.py",
    "test_coach_decisions_banner_contrast.py",
    "test_ds_cards_muted_text_contrast.py",
    "test_ds_combo_controls_hit_floor.py",
    "test_ds_knob_inputs_focus_ring.py",
    "test_ds_matchup_text_contrast.py",
    "test_footer_mode_pill_contrast.py",
    "test_header_placeholder_pill_contrast.py",
    "test_historical_pgr_text_contrast.py",
    "test_history_result_marks_contrast.py",
    "test_history_row_hover_marks_contrast.py",
    "test_home_accent2_focus_ring.py",
    "test_home_find_match_picker_contrast.py",
    "test_home_history_nav_focus_ring.py",
    "test_home_muted_text_contrast.py",
    "test_home_pick_name_contrast.py",
    "test_item_value_bar_relocated.py",
    "test_last_match_build_wpa_contrast.py",
    "test_last_match_review_nav_hover.py",
    "test_lm_hero_stats_disclosure.py",
    "test_lobby_lane_popup_keyboard.py",
    "test_lobby_mains_placeholder_contrast.py",
    "test_lobby_mains_recent_cell.py",
    "test_lobby_mains_tabs.py",
    "test_lobby_mode_menu_current_contrast.py",
    "test_lobby_queue_buttons_focus_ring.py",
    "test_lobby_queue_fill_text_contrast.py",
    "test_lobby_roster_row_dimming_contrast.py",
    "test_lobby_text_contrast.py",
    "test_match_row_focus_ring.py",
    "test_match_row_grade_chip_contrast.py",
    "test_ops_page_state_text_contrast.py",
    "test_overlay_call_glyph_contrast.py",
    "test_overlay_empty_caption_contrast.py",
    "test_overlay_lead_bar_contrast.py",
    "test_panel_visibility_tab_selected_state.py",
    "test_pgr_text_contrast.py",
    "test_replay_match_row_text_contrast.py",
    "test_session_hygiene_inert_contrast.py",
    "test_session_text_contrast.py",
    "test_settings_checkbox_hit_targets.py",
    "test_tab_bars_selected_state.py",
    "test_theme_signal_prim_hue.py",
    "test_theme_soft_token_hue.py",
    "test_ui_mock_active_match_build_eyebrows.py",
    "test_ui_mock_active_match_complete.py",
    "test_user_builds_rune_cells_focus_ring.py",
    "test_user_builds_rune_tabs.py",
    "test_user_builds_spell_chooser_keyboard.py",
    "test_user_builds_text_contrast.py",
    "test_view_menu_items.py",
    "test_view_menu_keyboard.py",
    "test_zone_pill_contrast.py",
    "test_zoi_debug_readout.py",
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
        # Anchor against an empty read. S144-U-263 cut the PANEL VISIBILITY
        # card to the eight panels a view can show, which left the view
        # with 18 checkboxes; the old ">= 20" predated that cut.
        assert n >= 18, f"only {n} settings checkboxes"
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


@pytest.mark.parametrize("tab", ("you", "party"))
@pytest.mark.parametrize("theme", _THEMES)
def test_lobby_mains_recent_cell_reads_are_settled(
    mock_server, pw_browser, theme, tab
):
    # test_lobby_mains_recent_cell boots each theme (?theme=), never swaps
    # in-page, clicks a MAINS tab and reads the rows it renders. Replays its
    # read path and lists what runs on the read elements at that moment.
    from tests.snapshot_panels import test_lobby_mains_recent_cell as rc

    mock_server._store["data"] = rc._STATE
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": rc._SIZES[0][0], "height": rc._SIZES[0][1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&theme={theme}#lobby",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.body.dataset.view === 'lobby'"
            " && !!document.getElementById('lv-mc-tab-party')",
            timeout=10_000,
        )
        page.click(f"#lv-mc-tab-{tab}")
        page.wait_for_function(
            "(tab) => { const l = document.getElementById("
            "'lv-mainchamps-list'); return !!l && l.dataset.tab === tab"
            " && l.querySelectorAll('.lv-mc-result').length >= 3; }",
            arg=tab, timeout=10_000,
        )
        page.evaluate(rc._SETTLE)
        booted = page.evaluate(_BOOTED)
        running = page.evaluate(
            _RUNNING_NOW,
            "#lv-mainchamps-list .lv-mc-result, "
            "#lv-mainchamps-list .lv-mc-wl .lv-mc-w, "
            "#lv-mainchamps-list .lv-mc-wl .lv-mc-l",
        )
    finally:
        ctx.close()
        mock_server._store["data"] = {}
    assert booted == theme, (theme, booted)
    assert running == [], f"{theme} {tab}: {running}"


# The thirty contrast modules (S144-U-214, U-215, U-223, U-240, U-241,
# U-242, U-243, U-245, U-250, U-251, U-253, U-255, U-269, U-272, U-275,
# U-277):
# each one's _measure extra arguments after (mock_server, pw_browser, theme),
# taken from its own constants (its first viewport, its first mode, the TFT
# footer state, the mixed Session scenario, its first surface).
_CONTRAST = {
    "test_am_empty_line_contrast": ("mode", "vp"),
    "test_am_map_roster_state_contrast": (),
    "test_build_insights_chart_text_contrast": ("vp",),
    "test_champ_select_ban_phase_over_head_contrast": (),
    "test_champ_select_personal_build_contrast": (),
    "test_coach_decisions_banner_contrast": (),
    "test_footer_mode_pill_contrast": ("fixture",),
    "test_header_placeholder_pill_contrast": ("vp",),
    "test_historical_pgr_text_contrast": ("mode", "vp"),
    "test_home_find_match_picker_contrast": (),
    "test_home_muted_text_contrast": ("vp",),
    "test_home_pick_name_contrast": ("vp",),
    "test_item_value_bar_relocated": ("vp",),
    "test_last_match_build_wpa_contrast": (),
    "test_lobby_mains_placeholder_contrast": (),
    "test_lobby_mode_menu_current_contrast": (),
    "test_lobby_queue_fill_text_contrast": (),
    "test_lobby_roster_row_dimming_contrast": (),
    "test_lobby_text_contrast": ("vp",),
    "test_overlay_call_glyph_contrast": (),
    "test_overlay_empty_caption_contrast": ("surface",),
    "test_overlay_lead_bar_contrast": (),
    "test_pgr_text_contrast": ("mode", "vp"),
    "test_replay_match_row_text_contrast": (),
    "test_session_hygiene_inert_contrast": ("vp", "scenario"),
    "test_session_text_contrast": ("vp",),
    "test_ui_mock_active_match_build_eyebrows": ("surface",),
    "test_ui_mock_active_match_complete": (),
    "test_user_builds_text_contrast": ("vp",),
    "test_zoi_debug_readout": ("vp",),
}
# The twenty-two whose opener adds the sheet before its first interaction.
_CONTRAST_SHEETED = (
    "test_am_empty_line_contrast",
    "test_build_insights_chart_text_contrast",
    "test_champ_select_ban_phase_over_head_contrast",
    "test_champ_select_personal_build_contrast",
    "test_coach_decisions_banner_contrast",
    "test_header_placeholder_pill_contrast",
    "test_home_find_match_picker_contrast",
    "test_home_pick_name_contrast",
    "test_item_value_bar_relocated",
    "test_last_match_build_wpa_contrast",
    "test_lobby_mains_placeholder_contrast",
    "test_lobby_mode_menu_current_contrast",
    "test_lobby_queue_fill_text_contrast",
    "test_lobby_roster_row_dimming_contrast",
    "test_overlay_call_glyph_contrast",
    "test_overlay_empty_caption_contrast",
    "test_overlay_lead_bar_contrast",
    "test_pgr_text_contrast",
    "test_replay_match_row_text_contrast",
    "test_session_hygiene_inert_contrast",
    "test_user_builds_text_contrast",
    "test_zoi_debug_readout",
)

# Force style on every element, then list every transition / animation
# running anywhere in the page: what the module's next colour read would see.
_RUNNING_PAGE = """() => {
  void document.documentElement.offsetHeight;
  for (const n of document.querySelectorAll('*')) {
    const cs = getComputedStyle(n);
    void (cs.color + cs.backgroundColor + cs.boxShadow + cs.borderTopColor);
  }
  return document.getAnimations().map((a) => {
    const tg = a.effect && a.effect.target;
    return (tg ? (tg.id || tg.className || tg.tagName) : '?') + ' :: ' +
      (a.transitionProperty || a.animationName || 'animation');
  });
}"""

# Re-class each [id, classes] element through its classes, as the footer and
# Lobby reads do inside their evaluate, and list what runs on it, its
# children or an ancestor after each re-class; the class is put back after
# and what the re-class started is finished, so the module reads as before.
_RECLASS_RUNNING = """(specs) => {
  const out = [];
  let n = 0;
  for (const [id, classes] of specs) {
    const el = document.getElementById(id);
    if (!el) { out.push('missing #' + id); continue; }
    const watched = new Set([el, ...el.querySelectorAll('*')]);
    for (let p = el.parentElement; p; p = p.parentElement) watched.add(p);
    n += 1;
    const keep = el.className;
    for (const cls of classes) {
      el.classList.remove(...classes);
      el.classList.add(cls);
      for (const w of watched) {
        const cs = getComputedStyle(w);
        void (cs.color + cs.backgroundColor + cs.boxShadow + cs.borderTopColor);
      }
      for (const a of document.getAnimations()) {
        const tg = a.effect && a.effect.target;
        if (!tg || !watched.has(tg)) continue;
        out.push(id + '.' + cls + ': ' + (tg.id || tg.className) + ' :: ' +
          (a.transitionProperty || a.animationName || 'animation'));
      }
    }
    el.className = keep;
    void getComputedStyle(el).color;
    for (const a of document.getAnimations()) {
      const tg = a.effect && a.effect.target;
      if (tg && watched.has(tg) && a.transitionProperty) a.finish();
    }
  }
  return {n, running: out};
}"""


# What a module's re-class may transition: properties its read never touches.
_BORDERS = tuple(f"border-{s}-color" for s in ("top", "right", "bottom", "left"))
_RECLASS_TOLERATED = {"test_lobby_text_contrast": _BORDERS}


def _reclass_specs(mod):
    if mod.__name__.endswith("test_footer_mode_pill_contrast"):
        return [["mode-pill", list(mod._TAGS)]]
    if mod.__name__.endswith("test_lobby_text_contrast"):
        return [[k, [c for c, _t in v]] for k, v in mod._TOGGLES.items()]
    return None


class _ProbePage:
    """A module's own page, with a probe before each colour read: every
    evaluate whose script calls getComputedStyle first lists what runs."""

    def __init__(self, page, rec):
        self._page, self._rec = page, rec

    def evaluate(self, expr, *args, **kw):
        if "getComputedStyle" in expr:
            self._rec["reads"] += 1
            self._rec["running"] += self._page.evaluate(_RUNNING_PAGE)
            if self._rec["reclass"] and expr == self._rec["measure"]:
                got = self._page.evaluate(_RECLASS_RUNNING, self._rec["reclass"])
                self._rec["reclassed"] += got["n"]
                self._rec["reclass_running"] += got["running"]
        return self._page.evaluate(expr, *args, **kw)

    def add_style_tag(self, **kw):
        if self._rec.get("drop_sheet") and kw.get("content") == _SHEET:
            self._rec["dropped"] += 1
            return None
        return self._page.add_style_tag(**kw)

    def __getattr__(self, name):
        return getattr(self._page, name)


class _ProbeContext:
    def __init__(self, ctx, rec):
        self._ctx, self._rec = ctx, rec

    def new_page(self):
        page = self._ctx.new_page()
        for css in self._rec.get("inject", ()):
            page.add_init_script(
                "document.addEventListener('DOMContentLoaded', () => {"
                " const s = document.createElement('style');"
                f" s.textContent = {css!r}; document.head.appendChild(s); }});"
            )
        return _ProbePage(page, self._rec)

    def __getattr__(self, name):
        return getattr(self._ctx, name)


class _ProbeBrowser:
    def __init__(self, browser, rec):
        self._browser, self._rec = browser, rec

    def new_context(self, **kw):
        return _ProbeContext(self._browser.new_context(**kw), self._rec)


def _contrast_run(mock_server, pw_browser, name, theme, **opts):
    import importlib

    mod = importlib.import_module(f"tests.snapshot_panels.{name}")
    pick = {"vp": lambda: mod._VIEWPORTS[0], "mode": lambda: mod._MODES[0],
            "fixture": lambda: "tft", "scenario": lambda: "mixed",
            "surface": lambda: sorted(mod._SURFACES)[0]}
    extra = [pick[axis]() for axis in _CONTRAST[name]]
    rec = {"reads": 0, "running": [], "reclass_running": [], "reclassed": 0,
           "dropped": 0,
           "measure": getattr(mod, "_MEASURE", None),
           "reclass": _reclass_specs(mod), **opts}
    try:
        mod._measure(mock_server, _ProbeBrowser(pw_browser, rec), theme, *extra)
    finally:
        mock_server._store["data"] = {}
    return rec


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("name", sorted(_CONTRAST))
def test_contrast_module_reads_are_settled(mock_server, pw_browser, name, theme):
    # Each module's own _measure, run through a probe that lists everything
    # running in the page at each of its colour reads (and, for the footer
    # and Lobby, after each re-class their read makes).
    rec = _contrast_run(mock_server, pw_browser, name, theme)
    assert rec["reads"] >= 1, f"{name}: the probe saw no colour read"
    assert not rec["running"], (
        f"{name}/{theme}: a read would straddle a transition (add the"
        f" transitions-off sheet to its opener): {sorted(set(rec['running']))[:8]}"
    )
    if not rec["reclass"]:
        return
    assert rec["reclassed"] == len(rec["reclass"]), (
        f"{name}: the re-class probe did not reach every element: {rec}"
    )
    ok = _RECLASS_TOLERATED.get(name, ())
    bad = [r for r in rec["reclass_running"] if r.rsplit(" :: ", 1)[1] not in ok]
    assert not bad, (
        f"{name}/{theme}: a re-class read would straddle a transition on a"
        f" property it reads (add the transitions-off sheet): {sorted(set(bad))[:8]}"
    )
    # The detector is not blind: the border transitions it tolerates are seen.
    seen = {r.rsplit(" :: ", 1)[1] for r in rec["reclass_running"]}
    assert seen == set(ok), (
        f"{name}/{theme}: the re-class transitions moved - re-audit {name}"
        f" and update the verdict: {sorted(seen)}"
    )


def test_contrast_modules_hold_their_sheet_and_no_sleep():
    # A fixed sleep in place of the sheet (or of a content wait) comes back
    # here, and each sheeted opener adds this module's exact sheet.
    import importlib

    for name in sorted(_CONTRAST):
        src = (_HERE / f"{name}.py").read_text(encoding="utf-8")
        assert "wait_for_timeout" not in src, f"{name}: a fixed sleep is back"
    for name in (*_CONTRAST_SHEETED, "test_historical_pgr_text_contrast"):
        mod = importlib.import_module(f"tests.snapshot_panels.{name}")
        src = (_HERE / f"{name}.py").read_text(encoding="utf-8")
        assert mod._SHEET == _SHEET, name
        assert "add_style_tag(content=_SHEET)" in src, name


def test_contrast_probe_sees_a_dropped_sheet(mock_server, pw_browser):
    # The page probe is not blind: with its sheet dropped, the Tonight's
    # Pick name's hover colour transition is caught at the hover read.
    rec = _contrast_run(mock_server, pw_browser,
                        "test_home_pick_name_contrast", "hextech",
                        drop_sheet=True)
    assert rec["dropped"] == 1, rec
    assert any(r.startswith("home-coach-pick-champ") and r.endswith(":: color")
               for r in rec["running"]), rec["running"]


def test_contrast_reclass_probe_sees_a_transition(mock_server, pw_browser):
    # The re-class probe is not blind: given a colour transition on the
    # footer pill, it is caught on the pill's re-class.
    rec = _contrast_run(
        mock_server, pw_browser, "test_footer_mode_pill_contrast", "hextech",
        inject=("#mode-pill { transition: color 2s linear !important; }",),
    )
    assert rec["reclassed"] == 1, rec
    assert any(r.startswith("mode-pill.") and r.endswith(":: color")
               for r in rec["reclass_running"]), rec["reclass_running"]

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
