# Split plan for the two oversize panel stylesheets

Status: PLAN ONLY. No slice has landed. Row: RM-726 (c), filed 2026-10-09 by
the repo review: "no panel CSS over 60 KB". Written 2026-10-31 by the s144
queue lane, measured at local main `fc123ec87`. This plan is the honest
first half of that row. The row closes when the last slice below lands and
no file under `web/css/panels/` is over 60 KB (61,440 bytes).

Guard: `tests/test_web_css_split_plan_rm726.py`. It parses the slice blocks
below and checks, on the live files:

- each Start line is a whole-rule cut at brace depth 0, once, in plan order;
- each anchor class occurs only inside its slice's range (after landing:
  only in the target, so a copied range goes red);
- every piece the cut produces is at most 61,440 bytes;
- `web/css/dashboard.css` imports the source and its landed targets on
  consecutive lines, in plan order;
- the coupled files still name the code, and the views are real view ids.

When a slice lands, mark its heading `(LANDED <sha>)` and keep the block: the
guard then checks the target instead of the source range, and it fails when
a target exists without the mark or the mark exists without the target. The
guard cannot check that nothing was left behind or edited: the joined-bytes
check in rule 2 is the slice's own landing check, run by its verifier.

## Why split, and what it does not buy

Measured at `fc123ec87`:

- `web/css/panels/header.css`: 150,410 bytes, 3,763 lines. The filed size
  was 135 KB.
- `web/css/panels/champ_select_view.css`: 94,487 bytes, 2,778 lines.
- Every other file under `web/css/panels/` is under 60 KB.

The split is for review and ownership, the same reason as the script split
in `docs/WEB_JS_SPLIT_PLAN.md`. `header.css` is not only the header: it holds
the header bar, the view shell, and the whole Lobby, Session, History, User
Builds and Settings views, so every lane's fix to any of those views lands in
one 3,700-line file.

The split does NOT make the page faster. Every panel stylesheet is already a
separate `@import` from `web/css/dashboard.css`, served by the local
dashboard. The split adds nine more local requests. ADR-008's asset hash
already covers new files: `dashboard/_static.py` `asset_fileset` walks
`web/css/**/*.css`, so no hash list needs an edit.

## Rules for every slice

1. CONTIGUOUS CUT, VERBATIM. CSS has no symbols to move. A slice cuts one
   contiguous run of whole top-level rules, from its Start line up to the
   next slice's Start line (or the end of the file), into the target file,
   byte for byte. No rule is edited, merged or reordered in the same commit.
   A cleanup is its own row, before or after.
2. CASCADE ORDER IS IMPORT ORDER. The target is imported in
   `web/css/dashboard.css` on the line right after the source (or after the
   previous slice's target), never anywhere else. Then the browser reads the
   same rules in the same order, so every specificity tie resolves as before.
   The landing check for that: the source plus its targets, joined in import
   order, equal the old source bytes.
3. CUT AT DEPTH 0. A Start line must sit outside every `{}` block, so no
   `@media`, `@supports` or `@keyframes` block is split. The guard checks it.
   `@keyframes` names and custom properties are global, so a rule in one piece
   may use a name defined in another. That is fine and needs no change.
4. ONE SLICE PER COMMIT, one commit per cycle (the queue lane's one-row rule).
   A slice that turns out to be two is shipped as two.
5. READERS FIRST (prep commit, before the first slice of each file). Many
   Python tests read these files as SOURCE TEXT. After a move they read a
   file that no longer holds the rule. A presence check then fails with a
   misleading message. An ABSENCE check keeps passing while it checks
   nothing: `tests/test_mode_flap_deferral_dom.py` asserts the retired row-2
   pill classes are not in `header.css` only, so after a split a resurrected
   rule in a new piece would pass. `tests/test_mission_control_server.py`
   (the no-Mission-Control-residue check) reads `header.css` plus three other
   files and has the same blind spot. (A guard that walks every web/ source,
   like `tests/test_view_section_btn_selector_removed.py`'s absence half, is
   not affected; its `header.css` reads are presence checks.) So the first commit adds one test helper that returns a
   source plus its landed targets, joined in `dashboard.css` import order. It
   re-points every reader to that helper. After that, a slice touches the
   source, the target, `dashboard.css`, the per-file ledgers and guarded
   citations (rule 6), its coupled tests where they read the source, and its
   own plan block. Readers measured at `fc123ec87` (files that open the
   path):
   - `header.css`: `tests/test_ascii_source_sweep.py`,
     `tests/test_build_insights_panel_dom.py`,
     `tests/test_dark_values_ratchet_oq6.py`,
     `tests/test_history_session_wl_oq8.py`,
     `tests/test_mission_control_server.py`,
     `tests/test_mode_flap_deferral_dom.py`,
     `tests/test_motion_reduce_sweep_oq4.py`,
     `tests/test_settings_force_scan_dom.py`,
     `tests/test_view_section_btn_selector_removed.py`.
   - `champ_select_view.css`:
     `tests/snapshot_panels/test_champ_select_archetype_chip.py`,
     `tests/snapshot_panels/test_champ_select_view.py`,
     `tests/test_aram_comp_verdict_bench_ui.py`,
     `tests/test_ban_reason_labels_oq9.py`,
     `tests/test_champ_select_e4_counters.py`,
     `tests/test_champ_select_rune_follows_build.py`,
     `tests/test_champ_select_sr_ui_audit.py`,
     `tests/test_csv_build_chooser_part3_item240.py`,
     `tests/test_csv_topleft_picks_layout.py`,
     `tests/test_csv_typography_v21_floor.py`,
     `tests/test_dark_values_ratchet_oq6.py`,
     `tests/test_personal_record_dom.py`.
   Re-measure this list when the prep commit is cut. Each slice's Coupled
   line below was measured by co-mention: the file names the source and one
   of the slice's anchors. That is a superset of the readers. Most are
   browser snapshot tests that only cite the file in a docstring, and those
   need no change.
6. PER-FILE LEDGERS MOVE WITH THE BYTES. Some guards key a count or an
   allow-list by file path. A slice splits the entry between the source and
   the target, in the same commit, without raising the total:
   `tests/test_dark_values_ratchet_oq6.py` (dark-value counts: `header.css` 5,
   `champ_select_view.css` 42), `tests/test_ascii_source_sweep.py` (allowed
   glyphs for `header.css`), `tests/test_motion_reduce_sweep_oq4.py`
   (`panels/header.css` list) and `tests/test_web_ascii_sweep.py` (the
   live-half digest is re-captured and attributed, as its own notes say).
   `tests/test_overlay_slider_hit_target.py` cites a `header.css` line number
   in its docstring and a message; re-point the cite.
   GUARDED LINE CITATIONS. `tests/test_citation_drift_guard_rm171.py` (over
   `tools/citation_audit.py`) fails when a living doc gains a new broken
   `path:<N>` citation. Living docs cite these two files by line number, so
   a slice that shortens a source breaks every cite into the moved range or
   past the new end of file. Measured at writing with
   `tools/citation_audit.py --json`: 21 guarded cites into the two files,
   and 14 of them point past the new end of file once every slice lands
   (the rest sit in the heads that stay, and still resolve). Those 14 are
   in `BACKLOG.md`, `docs/UI_SCALE_SPEC_V2.md`, the
   glyph adjudication doc, the lobby QA and design-system-map docs under
   `docs/qa/`, a LEAP spec and a superpowers plan. Each slice runs
   `tools/citation_audit.py` before and after the cut. In the same commit it
   re-points each newly broken cite to the target file (or to the source's
   new line), or it adds a baseline entry with a reason. This plan cites no
   line numbers on purpose.
7. TIER: Tier-1 web. Before the commit: the slice's coupled tests, the
   readers and ledgers above, `tests/test_web_css_split_plan_rm726.py`, and
   the 5-phase UI audit below.
8. THE 5-PHASE UI AUDIT runs on a HEADLESS render (the `tests/snapshot_panels`
   harness, `?ui_mock=1#<view>`), by an agent that did not write the slice,
   on every view on the slice's Views line, at 1920x920 and 923x1280. The five
   phases are STRUCTURE, TYPOGRAPHY, HIT-TARGETS, ASCII and HIERARCHY, as
   defined in `tools/headless-uiux.md` section 5. A pure move must change zero
   computed styles and zero box geometry. So the strongest check is a before
   and after diff of computed styles and boxes for every element on those
   views. Any difference is a MUST-FIX, and the slice is not a pure move until
   it is gone.
9. OWNERSHIP. Before a slice starts, check that no lane branch has unlanded
   edits to the source (`git log main..lane/<x> -- <file>` for every lane).
   If one does, wait for it to land. Measured at writing: `lane/uiux` carries
   unlanded commits to `champ_select_view.css` (RM-1197, U-77, U-80 and
   U-82), so the CV
   slices wait for that landing. Their Start lines, anchors and piece sizes
   were re-checked on the `lane/uiux` copy (through RM-1202) and hold
   there too (pieces 34,141 / 31,975 / 30,405 bytes).

## Order

The prep commit (rule 5) for each file goes first. Then the header slices run
from the tail of the file towards the head or in any order: the guard
recomputes each range from the Start lines that have not landed, and the
import-order check keeps plan order. The plan numbers them in file order.

What stays in `header.css` at the end (32,398 bytes at writing) is the voice
controls, the header bar and its row, the footer and prefs chip, the static
widths and heights of the header pills, the title dropdown, the view menu,
the view banner and view shell, the view tabs, and the
`body[data-view=...]` show and hide rules. It also keeps a few early lobby
title and member-color rules (the `s162 v5` panel-title block): they sit
between view-shell rules, and a contiguous cut cannot take them without also
taking the view shell. A later non-move row may relocate them.

What stays in `champ_select_view.css` at the end (33,024 bytes) is the
champ-select grid, the MY PICK card, the team columns and their threat and
status rules.

## web/css/panels/header.css slices

### HS-1 - Lobby queue strip
- File: `web/css/panels/header.css`
- Target: `lobby_queue.css`
- Start: `/* Lobby view layout (2026-04-26 v2): replaces the post-match-duped`
- Anchors: `lobby-view-card`, `lq-btn`, `lq-lane-pref`, `lq-find`, `lq-auto-accept`, `lq-party-toggle`, `lq-cancel`, `lq-mode-trigger`
- Coupled: `tests/snapshot_panels/test_lobby_card_containment.py`, `tests/snapshot_panels/test_lobby_view.py`, `tests/test_motion_reduce_sweep_oq4.py`
- Views: `lobby`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the queue card, the lane pair, Find Match / Cancel and the mode dropdown (HIT-TARGETS keeps --hit-min and :focus-visible), and the Find Match pulse under prefers-reduced-motion.
- Notes: 14,426 bytes at writing. Runs from the lobby grid to the end of the mode dropdown popover.

### HS-2 - Lobby panels
- File: `web/css/panels/header.css`
- Target: `lobby_panels.css`
- Start: `/* ---- s162 v4: Friends / Recently Played panel ---- */`
- Anchors: `lv-fr-row`, `lv-top8-list`, `lv-top8-name`, `lv-top8-tag`, `lv-top8-reorder-btn`, `lv-top8-search-input`, `lv-member-action`, `lv-mainchamps-tabs`, `lv-mc-tab`, `lv-duosyn-row`
- Coupled: `tests/snapshot_panels/test_lobby_hit_targets.py`, `tests/snapshot_panels/test_lobby_mains_tabs.py`, `tests/snapshot_panels/test_lobby_render_stability.py`, `tests/snapshot_panels/test_lobby_top8_search_input.py`, `tests/snapshot_panels/test_lobby_top8_tag_control.py`, `tests/snapshot_panels/test_user_builds_row_actions_hit.py`, `tests/test_web_ascii_sweep.py`
- Views: `lobby`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the Friends, My Top 8, Party and Mains cards at both widths (STRUCTURE, no reflow), the Top 8 reorder and tag controls and the party member actions (HIT-TARGETS), and the rank and KP color bands (HIERARCHY).
- Notes: the largest piece, 37,208 bytes at writing. It runs to the end of the lobby tips and recent list, just before the Session view block.

### HS-3 - Session view
- File: `web/css/panels/header.css`
- Target: `session_view.css`
- Start: `/* Session view layout - v2.1 UI scale (docs/UI_SCALE_SPEC_V2.md page #5,`
- Anchors: `session-grid`, `session-card`, `session-row`, `session-trend`, `session-trend-chip`, `session-champ-list`, `session-match-list`
- Coupled: `tests/snapshot_panels/test_session_view.py`
- Views: `session`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the session cards and the trend strip (STRUCTURE), the empty-list placeholder glyph (ASCII: it is a CSS escape, keep it one), and the row floor (HIT-TARGETS).
- Notes: 7,137 bytes at writing.

### HS-4 - History view
- File: `web/css/panels/header.css`
- Target: `history_view.css`
- Start: `/* History view layout - v2.1 UI scale (docs/UI_SCALE_SPEC_V2.md page #4,`
- Anchors: `history-card`, `history-session-list`, `history-match-list`, `history-session-row`, `history-match-row`, `history-filter-rbtn`, `history-formstrip`, `hs-wl`
- Coupled: `tests/snapshot_panels/test_history_view.py`, `tests/snapshot_panels/test_session_view.py`, `tests/snapshot_panels/test_user_builds_row_actions_hit.py`, `tests/test_history_session_wl_oq8.py`
- Views: `history`, `session`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the filter toolbar, its select and the radio buttons (HIT-TARGETS and their :focus-visible outlines), the per-session W-L chip (HIERARCHY), and the match rows the Session view reuses.
- Notes: 10,207 bytes at writing. The Session view reuses `history-match-row`, so it is audited too.

### HS-5 - User Builds view
- File: `web/css/panels/header.css`
- Target: `user_builds_view.css`
- Start: `/* User Builds view (Phase 8 step 6 - 2026-05-04, UI scale v2.1 page #2`
- Anchors: `ub-list-pane`, `ub-form-pane`, `ub-build-list`, `ub-build-row`, `ub-count`, `ub-field`, `ub-btn`, `ub-btn-tiny`, `ub-rp-rune`
- Coupled: `tests/snapshot_panels/test_user_builds_fit.py`, `tests/snapshot_panels/test_user_builds_row_actions_hit.py`, `tests/snapshot_panels/test_user_builds_rune_cells_focus_ring.py`, `tests/snapshot_panels/test_user_builds_view.py`, `tests/test_web_ascii_sweep.py`
- Views: `user-builds`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the list and form panes fit (STRUCTURE at both widths), the row Edit / Delete (the RM-1007 ring and --hit-min floor) and the spell and rune cells (HIT-TARGETS and the RM-1133 / RM-1084 / RM-1087 keyboard paths and focus rings).
- Notes: 19,857 bytes at writing.

### HS-6 - Settings view
- File: `web/css/panels/header.css`
- Target: `settings_view.css`
- Start: `/* Settings view layout (UI scale v2.1, 2026-05-23 - worked-example`
- Anchors: `settings-body`, `settings-card`, `settings-row`, `settings-filter-input`, `set-action-btn`, `spend-gate-row`
- Coupled: `tests/snapshot_panels/test_companion_reflow.py`, `tests/snapshot_panels/test_settings_checkbox_hit_targets.py`, `tests/snapshot_panels/test_settings_view.py`, `tests/snapshot_panels/test_user_builds_row_actions_hit.py`, `tests/test_overlay_slider_hit_target.py`, `tests/test_settings_force_scan_dom.py`, `tests/test_web_ascii_sweep.py`
- Views: `settings`, `lobby`, `user-builds`, `history`, `active-match`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the checkbox wrappers and sliders (HIT-TARGETS, the RM-1061 ring), the coaching-action buttons and spend gates, and the companion single-column reflow (STRUCTURE at 923x1280).
- Notes: 10,761 bytes at writing. The range carries the shared `@media (max-width: 1200px)` block. It also collapses the lobby grid, the User Builds layout, the History grid, the header row and the heartbeat. So the audit covers those views at 923x1280 too.

### HS-7 - Header chips, toasts and digest
- File: `web/css/panels/header.css`
- Target: `header_chips.css`
- Start: `.mode-pill {`
- Anchors: `self-spell`, `kda-burst`, `keybinds-toast`, `advisory-toast`, `rebuild-toast`, `digest-popout`, `digest-insights`
- Coupled: `tests/snapshot_panels/test_escape_one_action.py`
- Views: `all`, `active-match`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the header bar pills in game (mode, champion, spells, KDA, CS, level, vision, ult, zone, win), the toasts and the digest popout (Escape still closes it, the z-index stack is unchanged), and the pulse keyframes under prefers-reduced-motion.
- Notes: 18,416 bytes at writing. The Start line has no comment banner: it is the first rule after the Settings block. The static widths of the same pills stay in the head (rule 1 forbids merging them in a move).

## web/css/panels/champ_select_view.css slices

### CV-1 - Pick and ban recommendations, mode layouts, bench, suggestions
- File: `web/css/panels/champ_select_view.css`
- Target: `champ_select_recs.css`
- Start: `/* -- Pick & Ban Recommendations panel ----------------------------- */`
- Anchors: `csv-pickban-body`, `csv-pb168-cell`, `csv-pb168-pick`, `csv-pb168-ban`, `csv-pb168-bans`, `csv-pb-pick-header`, `csv-bench-cell`, `csv-counter-pick`, `csv-sugg-team-damage`
- Coupled: `tests/snapshot_panels/test_champ_select_review_r30.py`, `tests/snapshot_panels/test_champ_select_view.py`, `tests/test_aram_comp_verdict_bench_ui.py`, `tests/test_ban_reason_labels_oq9.py`, `tests/test_champ_select_e4_counters.py`, `tests/test_champ_select_sr_ui_audit.py`, `tests/test_csv_topleft_picks_layout.py`, `tests/test_csv_typography_v21_floor.py`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the pick and ban grid in SR, ARAM and Arena mocks (STRUCTURE for each mode-conditional layout), the why-banned sub-labels (TYPOGRAPHY floor), the ARAM bench verdicts and the counter-pick list (HIERARCHY), and the companion reflow at 923x1280.
- Notes: 31,975 bytes at writing. The mode-conditional layouts (s165) and the R30 companion reflow are in this range and override the head's grid. Rule 2 keeps them after it.

### CV-2 - Build chooser, Arena, team analysis
- File: `web/css/panels/champ_select_view.css`
- Target: `champ_select_builds.css`
- Start: `/* -- Build chooser rows (SR / ARAM / Arena) ------------------------- */`
- Anchors: `csv-builds-row`, `csv-build-row`, `csv-build-spell`, `csv-build-badge`, `csv-rune-side`, `csv-duo-cell`, `csv-augment-slot`, `csv-arena-cell`, `csv-ta-head`
- Coupled: `tests/snapshot_panels/test_champ_select_archetype_chip.py`, `tests/snapshot_panels/test_champ_select_faint_text_contrast.py`, `tests/snapshot_panels/test_champ_select_review_r30.py`, `tests/snapshot_panels/test_champ_select_view.py`, `tests/test_champ_select_rune_follows_build.py`, `tests/test_champ_select_sr_ui_audit.py`, `tests/test_csv_typography_v21_floor.py`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the build chooser rows and the rune side picker (HIT-TARGETS and the RM-971 focus parity), the Arena duo, augment slots and enemy cards (STRUCTURE in the Arena mock), the LOCK IN button edge (RM-1137), and the TEAM ANALYSIS label contrast (HIERARCHY).
- Notes: 29,488 bytes at writing. Waits for the `lane/uiux` landing (rule 9); three of its four hunks fall in this range and one in the head.
