# UI/UX PROGRAM - master QA ledger (operator-present, started 2026-07-22)

Method: memory `feedback_operator_ui_qa_method` - MAP (read-only fan-out) -> ADVOCATE ROUNDS
(batched Qs, each with a keep/move/remove/fix rec AND a counter-argument) -> ACT (worktree
slices, verifier gate, 5-phase fixture audit before commit). Every ruling recorded here.

Source brief: `docs/qa/UI_UX_QUEUE_2026-07-21.md`. Treats the E11 sweep as INCOMPLETE.

## Operator's four asks (do not narrow)

1. Colour is optically off + panels do not cohere - explore a THEME SWAP, not cell patches.
   (NOT the old bare-hex compliance hunt - that comes back empty.)
2. 2-3 LAYOUT ALTERNATIVES per page to choose between, not one proposal to approve.
3. Content audit: some daily-read data points redundant, others missing.
4. Earlier per-page reviews never finished; E11 sweep INCOMPLETE.

## Session framing rulings (2026-07-22, round 0)

| # | Question | Ruling |
|---|----------|--------|
| F1 | When to build the 2560x1440 overlay pseudo-screen | **Build now, in infra phase** - overlay is half the colour complaint, can't theme-swap it without a headless render target |
| F2 | Scheduling the .rofl q2400 backfill (Home/PGR Unknown 0-0-0) | **Parallel track now** - independent of UI, unblocks Home/PGR/Session content rulings |
| F3 | Theme-swap ambition | **2-3 alternative candidate themes** to pick between, then refine one |
| F4 | First per-page slice after design-system | **Home first** |

## Phase plan

- PHASE 0 (infra, parallel): (0a) overlay pseudo-screen @ 2560x1440 headless; (0b) mock
  completeness check for out-of-game pages; (0c PARALLEL) .rofl Layer-1 backfill for q2400.
- PHASE 1 (design-system MAP): cross-page palette/contrast/panel-chrome/overlay inventory ->
  2-3 theme candidates rendered on the mock pages.
- PHASE 2 (advocate rounds): design-system first, then Home, then remaining pages.
- PHASE 3 (ACT): slices behind verifier gate + 5-phase fixture audit, commit, CI green.

## Known defects to route (from queue section B)

Home: Unknown/0-0-0 rows (->0c), stray no-data dot on 14D CS/MIN, bare `.` on TONIGHT'S PICK
good/bad, nav grid omits Champ Select/Active Match/Pre-Game Lobby/Build Insights, panels stuck
on "loading..." forever after one transient fetch fail (no retry/error state).
PGR: `-`/"No grade yet" AND `OVERALL D` together, phantom v2 Refresh-from-Riot button, reference
block reads as own stats (provenance not unmissable).
Replay: right pane clips header ("GOL"), dead slider.
Settings: voice picker empty option list.
Global: footer says "Legion-PC" (retired), large dead space below fold on Home/PGR/Session,
`performance_tracker.py:39` grade labels carry a  -  escape rendering an em-dash in-UI + written
into data/ratings/last_sr.json + last_arena.json (repo-wide scope unmeasured).
Overlay: THREATS row empty placeholder circles (5 SR/12 Arena), dead DMG/SURV/UTIL steppers
(RM-05 ruled DEAD, removal never landed), complete-build renders bare DAEMON SLAYER/META BUILD
headers with nothing under, R40 draft-elo chip mounted inside hidden `.am-pane-head`
(overlay.css:482) so it can never paint, low-contrast enemy-spell chip labels, unlabeled minimap
ZOI number (no legend), `health.overlay_visible` FALSE while visibly rendering, ARAM balance grid
-> its own draggable widget (verify it landed), G2-35 stats panel needs pace-projected baseline,
G2-34 objective gauges collapse horizontally.

## Verified defects (confirmed live against source, not trusting the queue)

- Footer `Legion-PC`: `web/index.html:2251` (`<span>Legion-PC ... </span>`). One-liner but the
  replacement text is an operator-read UI string -> defer wording to advocate round.
- Em-dash escapes: `performance_tracker.py:37-39` - ` - ` in ALL SIX `GRADE_LABEL` entries
  (queue logged only line 39). Renders em-dash in-UI + serializes into `data/ratings/last_sr.json`
  + `last_arena.json`. Fix needs the Data-Fixes backfill tail (recover already-written rows),
  not just the source edit. Repo-wide ` - `/` - ` escape scope still to be swept.

## Rulings ledger

### Design-system round 1 (2026-07-22) - theme direction

| # | Question | Ruling |
|---|----------|--------|
| DS1 | 3 competing chrome systems (gold-hairline / no-border / white-glass) | **Collapse to ONE chrome** - every panel adopts a single border/backing/radius; kill the white-glass hairline |
| DS2 | Which candidate themes to render | **Hextech-Unified + Deep Terminal** (2, not 3; Warm Editorial + Slate Cool dropped) |
| DS3 | Overlay theme target | **Share the chosen palette, keep a documented in-game legibility variant** (stronger border/backing over game pixels) |
| DS4 | Off-theme orphans champ_select + ds_statcheck | **Fold ds_statcheck into the theme pass now; champ_select converts in its own champ-select slice** |

Findings backing these: `docs/qa/DESIGN_SYSTEM_MAP_2026-07-22.md`. Real fault set = structural chrome
split + palette fragmentation + `--faint #5C6E88` AA contrast fail (~3.4:1). NOT a hue-compliance
issue (old pass was right to come back empty on that question).

### SPATIAL BRAND round (2026-07-22) - operator pivoted to define the envelope FIRST

Full detail: `docs/qa/SPATIAL_BRAND_SPEC_2026-07-22.md`. Measured desktop (2560x1440, work area
2560x1400, client 1280x720 centered) + swept 6 competitors live (Overlay App E/Aggregator A/Coaching App Z7/Overlay App F/
Aggregator C/Aggregator B/Overlay App Z5) + web research.

| # | Ruling |
|---|--------|
| SP1 | Out-of-game = ONE **full floating landscape hub** (~1400-1600 wide), overlaps client when open. Retires the 920x1280 portrait + the "live in the empty gutter" premise (no competitor does it; it caused the overflow pain) |
| SP2 | Sizing = **resolution-adaptive auto-fit + manual scale % + remembered position** (Aggregator A model) - the overflow cure |
| SP3 | Overlay stays a separate surface; overlay-settings target = layout Type + Size% + Transparency% + drag Position (+Reset) |
| SP4 | Hextech-Unified theme validated as genre-native; the Hextech-vs-Terminal palette pick resumes against the landscape hub |

### PARKED WORK (built this session, UNMERGED in worktrees)
- Theme candidates (Hextech-Unified + Deep Terminal, unified chrome, ds_statcheck fix, ?theme seam,
  4 comparison renders). Palette PICK deferred (operator pivoted before choosing).
- Overlay pseudo-screen (tools/pseudo_screen_overlay.py + fixtures + main.js seam). Decided infra.
- .rofl q2400 backfill (core/rofl_stats_backfill.py + CLI + 7 tests). Live --commit pending post-merge.
All await: verifier gate + git show --stat check + merge. Competitor apps left installed/logged-in on
Legion (operator's to keep or remove via Revo).

## Build tracks status (2026-07-22) - all in worktrees, UNMERGED (holding until theme agent done)

- **Overlay pseudo-screen: BUILT + rendered.** `tools/pseudo_screen_overlay.py` (committed harness,
  modes sr/aram/mayhem/complete), fixtures `active_match_aram_mayhem.json` +
  `active_match_complete.json`, `main.js` `_amMockUrl` 2-line seam. SR HUD rendered 7 widgets @
  2560x1440. Finding: `aram_balance.js:46` `_AB_ARAM_MODES={"aram","kiwi"}` already covers Mayhem
  (mode "aram") - no panel edit. Defect B#3: the finished-build state shows a "will render mid-game"
  PLACEHOLDER (not literally bare headers) - that placeholder is the real UX bug. Caveat: live :8888
  serves MAIN, so new fixtures render only post-merge.
- **.rofl q2400 backfill: BUILT (code+tests, live DB untouched).** `core/rofl_stats_backfill.py`
  +`backfill_tracked_summary` (UPDATE tracked_* where NULL, Riot-ID join, never puuid, never touches
  queue_id) + closed net-new tracked_* hole; `tools/rofl_tracked_backfill.py` CLI (--commit gated,
  dry-run default); 7 new hermetic TDD tests PASS. Agent claims the other 13 fails are a 0-byte-DB
  worktree artifact that pass on Legion main - VERIFY at merge, do not trust. Live --commit backfill
  runs AFTER merge (recovers ~15 of 120 NULL-tracked rows that have an archived .rofl).
- **Theme candidates: IN FLIGHT** (Hextech-Unified + Deep Terminal, unified chrome, ds_statcheck fix,
  ?theme swap seam, comparison renders of Home+Session under both).

Merge order when theme lands: verify each with `git show --stat` (staged-deletion guard), verifier
gate, then merge overlay + rofl (disjoint) + theme; run live --commit rofl backfill; render faithful
comparison for the operator's palette pick.

--------------------------------------------------------------------------------
## 2026-09-01 - lane 4 headless, ELECTRON OVERLAY only (LEDGER 1315)

Operator scoped the run to the Electron overlay (rc-shell + the in-game dock) and split the
mandate: SHIP the text-verifiable, PREPARE anything ending in a rendered-pixel judgement.
All figures below were measured in real headless Chromium, not read off source.

### RULINGS

| # | Ruling |
|---|--------|
| OV-R1 | **B-OVL-4 CLOSED.** The draft-elo chip is re-parented out of `.am-pane-head` into a new `.am-pane-chips` row, a DIRECT child of `.am-pane-build`. The queue fence ("re-parent, not a CSS exception") holds: the pane-head hide rule is untouched. It is deliberately NOT in `#am-build-body`, which `active_match.js:859` wipes on every build-signature change. |
| OV-R2 | **A repainting host in the overlay MUST preserve `document.activeElement`.** Now enforced for the layout menu by `_captureMenuFocus` / `_restoreMenuFocus` in `web/js/lib/overlay_layout.js`, keyed on a stable `data-ovx-ctl` because node identity dies with the rebuild. Guard: `tests/snapshot_panels/test_overlay_launcher_menu.py`. |
| OV-R3 | **An AMBIENT-tier widget may not paint the reserved lethal red.** `OVERLAY_DOCTRINE.md` rule 4 + section 5 reserve red for the Emergency winner. The draft-elo bad band and low-sample pill are re-mapped to neutral ink in the overlay shell ONLY; the dashboard keeps its colours. Ordinal meaning survives via luminance plus the printed percentage and signed score. |
| OV-R4 | **A newly-PAINTING element inherits the overlay's rules, not its origin surface's.** The re-parent moved a dashboard-scoped chip onto the HUD and it arrived carrying a dashboard red and a dashboard type scale. Any future "make X visible in the overlay" slice re-audits X against the doctrine before it ships, not after. |
| OV-R5 | **The lane doctrine's own citations are auditable artifacts.** `tools/headless-uiux.md` trap 2 cited a focus-preservation pattern in `dev.js` that does not exist. Corrected and pinned by `tests/test_uiux_lane_doc_focus_citation.py`. A doctrine doc that tells the next agent to copy absent code costs a whole slice. |

### FUTURE (measured, grounded, NOT actioned this run)

- **F-OV-1 PREPARED, operator-gated.** `#view-active-match .am-pane` (specificity 1,1,0) in `web/css/panels/active_match.css:92-100` BEATS `body[data-shell="overlay"] .ovx-widget.am-pane` (0,3,1) in `web/css/overlay.css`, so `w-call` / `w-build` / `w-ovds` paint OPAQUE `oklch(0.27 0.06 302)` in-game instead of the intended `rgba(22,32,46,0.58)`. The PRIMARY widget is not see-through. Diagnosis is text-verifiable; the fix flips it translucent over live gameplay, so it rides DS3. Repair specified in all three variants in `OVERLAY_LEGIBILITY_VARIANTS_2026-09-01.md`.
- **F-OV-2.** `#w-launcher` is a `<div>`, `tabIndex -1`, no `role`. The layout menu is now keyboard-USABLE once open but still cannot be OPENED from the keyboard.
- **F-OV-3.** Same focus-destruction class, unfixed: `coach_choices.js:223` (rebuilds the A/B chips), `overlay_ds_controls.js:535` and `:556` (wipes the four `#ovds-*` number inputs mid-typing when a champion drops out of a tick), and `web/js/panels/dev.js:369` on the dashboard (was `:510` until RM-339 deleted the dead diagnostics block above it on 2026-09-04; same statement, same finding).
- **F-OV-4.** CI runs NO `.mjs` node tests (no `node --test` in `.github/workflows/`), so `web/js/lib/*.test.mjs` is an unrun gate. One test sat red there from 2026-08-11 until this run.
- **F-OV-5.** The draft-elo chip exposes dashboard-scoped type to the overlay: `.de-sample` computes 9px (12.0px effective at ovscale 1.333), below the overlay's own smallest sanctioned token `--fs-ov-head` (11px, 14.7px effective).
- **F-OV-6.** `w-build` computes `overflow:hidden` with a max-height, so overflow is CLIPPED not scrollable; the new chips row costs 14-30px of clipped content.
- **F-OV-7.** `_menuRangeBusy` guards a path no caller reaches (`_setOpacity` / `_setScale` do not re-render), but the flag can stick and its `blur` rescue is untested - deleting it would convert the guard into a silent menu freeze.
- **F-OV-8.** `.draft-elo-contributions` still uses `#ff8080`. Left deliberately: it is `display:none` at rest, hover-only, `pointer-events:none`, and the overlay is click-through, so it paints no red on the HUD at rest; and its ally-green / enemy-red / matchup-amber triad is a CATEGORY encoding, not magnitude. Flagged for an operator ruling rather than neutralised blind.
- **F-OV-9 citation drift found while triaging** - `UI_UX_QUEUE_2026-07-21.md:78` and `LIVE_GAME_GATED_SYNC.md:98` cite `overlay.css:482`; the rule is now at `:506`. `LIVE_GAME_GATED_SYNC.md:500` cites `overlay_layout.js:67` for `w-stats`; it is `:83`. `UI_UX_PROGRAM_QA:106` cites `aram_balance.js:46` in `web/js/lib/`; it is `web/js/panels/aram_balance.js:55`. This file's `:57` cites the footer at `web/index.html:2251`, which is now the draft-elo chip.
- **F-OV-10 dead gated rows.** `LIVE_GAME_GATED_SYNC.md` G2-26 and G2-33 point at `web/js/panels/enemy_spells.js`, deleted by `1a401b4b` (2026-08-11, LEDGER 1238). Kill them, do not drain. Same for queue row B-OVL-5.
- **F-OV-11.** `health.overlay_visible` has ZERO writers - exactly two references repo-wide, the read at `app/_health_monitor.py:82` and the initializer at `app/__init__.py:132` - so it is hardcoded false by construction and can never be true. Both files are CLAUDE.md frozen, so it needs an adjudicating agent's approval; not actioned in an overlay-scoped run. (= queue B-OVL-7.)

### CONTRADICTION TO RECONCILE BEFORE ANYONE ACTS ON THE QUEUE
Queue lines 86-88 record G2-34 and G2-35 as "RULED", while `LIVE_GAME_GATED_SYNC.md:538-541` still
carries both as OPEN live-gated DECISIONS the operator makes after seeing them in-game. The gated
doc is the later, narrower authority; treat both as NOT closable headless.

## 2026-11-04 - lane 4 headless, s144 cycle 106 (RM-1365)

### RULING
- **Escape belongs to what the operator can see.** The one Escape dispatcher (`web/js/lib/escape_layers.js`) skips an open layer whose element has no box (`getClientRects()` empty), the same rendered test `main.js` `_letterShortcutsYield` and `review_player.js` `_menuOpen` already apply to a menu left open by a view change. Measured before the fix, headless Chromium 1920x920: the Lobby mode menu or lane popup opened from the keyboard and stranded by a hash change or Back took the first Escape on Replay unseen, so zen stayed on. Guard: `tests/snapshot_panels/test_escape_unrendered_layer.py`, plus `openEntries` in `escape_layers.test.mjs`.
- A visibility:hidden or opacity 0 layer still has a box and still takes the press; a grep of `web/css` finds no layer hidden that way (not measured in a browser).
- The stranded layer keeps its open class; what it shows when the operator returns to Lobby is a separate row.

## 2026-11-04 - lane 4 headless, s144 cycle 107 (RM-1367)

### RULING
- **A view change never leaves the keyboard on a control nobody can see.** `applyView` (`web/js/main.js`) blurs focus that the change left on an element with no box (`getClientRects()` empty), in the same task as the change. It only blurs and never moves focus anywhere, so a rendered control keeps it (the header view trigger after a keyboard pick from the view menu), and activation code that focuses a control on the new view (the Home Find Match pick to `#lv-mode-trigger`) still runs after it. Guard: `tests/snapshot_panels/test_view_change_stranded_focus.py`.
- Measured before the fix, headless Chromium 1920x920 under `?ui_mock=1`: Chromium's own focus fixup does drop the hidden focus, but only at the next rendering frame. A `setTimeout` 0 after the hash change still read `lv-mode-trigger` with 0 rects; one `requestAnimationFrame` later it read `BODY`. Inside that window an Enter clicked the hidden Lobby trigger once and opened its mode menu on Replay. The row's first report (focus "stays" on the trigger) was a read taken inside that window; a two-frame read passes on the unfixed code, so the guard reads focus inside the hashchange dispatch itself.
- The Enter consequence test rides the frame race (red in 2 of 3 runs on the unfixed code); the hashchange-dispatch read is the deterministic pin.

## 2026-11-04 - lane 4 headless, s144 cycle 108 (RM-1368)

### RULING
- **A view change closes every transient layer it leaves with no box.** `applyView` (`web/js/main.js`) calls `dismissStrandedLayers()` (`web/js/lib/escape_layers.js`) in the same task as the `body[data-view]` flip, before the RM-1367 focus drop. It dismisses each Escape-registered layer that is open and whose element has no box (`getClientRects()` empty), through the layer's optional `dismiss()` (a closer that never moves focus), else its `close()`. A layer still rendered after the change (the header view menu, the task modal) is left alone, and so is a layer whose `el()` gives no element. Guard: `tests/snapshot_panels/test_view_change_closes_layers.py`, plus `strandedLayers` in `escape_layers.test.mjs`.
- Measured before the fix, headless Chromium 1920x920 under `?ui_mock=1`, each layer opened and its view left by a hash change: the Home Find Match picker (inside `#home-overlay`) kept its open state with 0 rects on Replay, but its scrim `#home-find-match-backdrop` (created on `<body>`, position:fixed, z 9100) stayed over the whole Replay view: `elementFromPoint` at the centre read the backdrop, a click on the rendered `#view-trigger` timed out behind it, and Escape could not clear it (an unrendered layer takes no press, RM-1365). Back on Home the picker was still open. The Lobby mode menu and lane popup kept their open class and `aria-expanded="true"` on Replay and were still open on return to Lobby. This settles the s144 u106 verifier dispute: the picker has no box, its scrim does.
- The RM-1365 dispatcher filter and the RM-1323 letter-shortcut yield stay: they are still the rule for any other way a layer loses its box. Their guards (`test_escape_unrendered_layer.py`, `test_hotkey_letter_owners.py`) built the stranded state from the view change; they now assert the change closed the layer, then put the open class back on the unrendered layer so both filters stay pinned end to end.

## 2026-11-04 - lane 4 headless, s144 cycle 109 (RM-1366)

### RULING
- **The open menu owns a plain Space on every view, not only on Replay.** `web/js/main.js` `_spaceHeldBehindMenu` prevents a plain or Shift+Space when a `role="menu"` is rendered (`getClientRects()` non-empty, the RM-1323 test) and focus is on nothing a Space activates or types into, and does nothing else with it: the menu stays open, Escape or a click closes it as before. It reuses `isTypingTarget` / `isSpaceActivated` from `review_player_model.js`, so the page hold and the player's RM-1324 hold read focus the same way. Ctrl / Alt / Meta + Space pass (the player's play chord). Guard: `tests/snapshot_panels/test_space_behind_a_menu_any_view.py`.
- Measured before the fix, headless Chromium 1920x920 under `?ui_mock=1`: view menu open, right-click a bare spot of the view (no click fires, so the menu stays open, focus on the body), then Space scrolled the scroller under that spot, unprevented, on six views: Settings 718 px, Session 716, Replay with a match loaded and no recording 253, Champ Select 139, Historical PGR 55 to 65, Build Insights 31. Home, Lobby, Active Match, Post Game Review, History and User Builds had no scroller to move under `ui_mock`. The row (filed as Replay-only, the player stands down with no recording) was one layer too narrow: the player is not on this route at all.
- Alternative not taken: close the menu on a right-click outside it. It changes the pointer contract of four menus to fix a key, and the RM-1323 / RM-1324 rulings already say keys behind an open menu stand down; the hold keeps one rule.
- Each scroll test has a control that serves `main.js` without the hold and must see the same route scroll; the RM-1324 control in `test_replay_keys_behind_menu.py` now strips both holds.

## 2026-11-04 - lane 4 headless, s144 cycle 110 (RM-1364)

### RULING
- **An open, rendered modal owns the page's shortcuts, as a menu does.** The two full-page scrims, the task detail modal (`#task-modal`) and the cross-session digest popout (`#digest-popout`), now register with `modal: true` in `web/js/lib/escape_layers.js`; `modalLayerRendered()` answers whether such a layer is open with a box (the RM-1365 `openEntries` rule). `web/js/main.js` `_letterShortcutsYield` (A, F, Z, H, ?, Shift+R) and the Replay player's `hotkeyAction` (`modalOpen`: ], [, d, D, Space) both read it.
- Measured before the fix, headless Chromium 1920x920 under `?ui_mock=1`, focus on the body, on Home, Settings, Replay, Lobby and Session: A clicked ANALYZE NOW and Z flipped zen behind either modal; Shift+R wiped preferences and reloaded the page out from under the modal; on Replay `]` seeked a showing recording 20 -> 30 behind the task modal.
- Space behind a modal is NOT held, unlike behind a menu: with focus on the body it scrolled nothing on those five views, and a click inside the modal may want Space to scroll the modal's own content. It no longer plays. A menu painted over a modal is checked first, so its hold still applies.
- Kept: Ctrl / Alt + Space still plays behind a modal (the play-from-anywhere chord, above the check as RM-1324 kept it for a menu); Escape still closes the modal through the dispatcher; a modal open by class with no box (the overlay shell's `display: none !important`) kills no key.
- Not changed, unmeasured: Ctrl+K (focus the prompt) behind a modal; under `?ui_mock=1` it moved focus to nothing measurable. Filed as a follow-up, not ruled.
- Guard: `tests/snapshot_panels/test_shortcuts_behind_a_modal.py` (red 33 failed / 15 passed, green 48 passed), `modalShowing` in `escape_layers.test.mjs`, the `modalOpen` case in `review_player_model.test.mjs`.

## 2026-11-04 - lane 4 headless, s144 cycle 111 (RM-1424)

### RULING
- **An open modal holds the keyboard focus, and closing it hands focus back** (the RM-1312 / RM-1321 menu rules applied to a modal). `web/js/lib/escape_layers.js` `modalOpened(root, initial)` runs right after a modal is shown: it remembers the control that had focus (the opener; not when focus is already inside, so a re-open keeps the first opener) and focuses the close button. `modalClosing(root, refocus)` runs before it is hidden: with refocus, focus inside the modal or on the body goes back to the opener when it is still connected and rendered; otherwise focus inside the modal is dropped. Both `#task-modal` (`web/js/main.js` `openTaskModal` / `closeTaskModal`) and `#digest-popout` (`web/js/panels/right_now.js`) use them.
- Keyboard close = refocus: Escape (the dispatcher's `close`) and Enter / Space on the close button (a click with `detail === 0`). Pointer close = no refocus: a mouse click on the close button or on the scrim never parks focus on the opener, so the next Space on Replay is not taken by it (the RM-1321 reasoning).
- **Tab is held by the TOPMOST open layer only when it is `modal: true`.** A capture keydown listener in `escape_layers.js` cycles the modal's own rendered tabbables (`trapIndex`, wrapping both ways); from outside it (the body, after a click on the modal's text) the next Tab enters it. A layer painted over the modal (the digest popout at z 9500 over the task modal at z 200) holds Tab itself, and each Escape closes one layer and hands focus back one step.
- Both modals are now `role="dialog" aria-modal="true"` with `aria-labelledby` on their title (the task modal had no dialog role); `aria-modal` is only claimed because the focus is now actually held. `#task-modal-close` gained `aria-label="close"` (its name was the glyph). Both close buttons were under the hit floor (28x28 digest, 36x36 task) and are now `var(--hit-min)` square with a `--focus-ring` box-shadow on `:focus-visible`.
- Measured before the fix, headless Chromium 1920x920 under `?ui_mock=1`, opener `#view-trigger` focused, modal opened through its real path (a routed `/api/activity` row click; the digest icon click): focus stayed on the opener behind the scrim, Tab walked the page, Escape left focus on the body.
- Not changed: both openers are keyboard-unreachable (the digest icon is `role="button"` with an Enter / Space handler but no `tabindex`, and sits under the hit floor; an activity row is a bare clickable `span`). Filed as RM-1425 / RM-1426, not ruled here.
- Guard: `tests/snapshot_panels/test_modal_focus_open_close.py` (red 23 failed / 4 passed, green 27 passed), `trapIndex` and the no-document cases in `web/js/lib/escape_layers.test.mjs`.

## 2026-11-04 - lane 4 headless, s144 cycle 112 (RM-1421, RM-1423)

### RULING
- **Ctrl+K / Cmd+K belongs to the prompt only while the prompt is rendered and nothing modal or menu-shaped is over the page.** `web/js/main.js` `_promptRendered()` (`#input-text` has a client rect) gates the branch, together with `_menuRendered()` and `modalLayerRendered()`; otherwise the chord is not prevented and reaches the browser (whose own Ctrl+K is the address-bar search). A rendered prompt keeps the old behaviour, held keys included.
- Measured before the fix, headless Chromium 1920x920 under `?ui_mock=1`, focus on the body: on Home, Lobby, Session, History, Replay, Settings, Champ Select, Historical PGR, Build Insights and User Builds `#input-text` had no client rects (`#input-bar` is `display: none` on every view since 2026-04-25, `web/css/panels/input_activity.css`), Ctrl+K was `defaultPrevented` and focus stayed on the body. With the prompt given a box, Ctrl+K behind either open modal moved focus out of the modal to the input under the scrim (RM-1423).
- The keybinds toast (? / H) lists Ctrl+K only while the prompt is rendered (its row carries `data-key="ctrl-k"` and is `hidden` otherwise), so it no longer advertises a key that does nothing.
- Alternative not taken: make Ctrl+K reveal the hidden input bar. That reverses the 2026-04-25 operator ruling that hid it ("Ask Agent 7 wasn't working as intended"); not a lane call.
- Not measured: the Active Match / Last Match views (`#active-match` needs live data under `ui_mock`); the gate reads the input's box, not the view, so it holds there by construction.
- RM-1425 / RM-1426 are refuted as filed: neither opener can be reached by ANY input, mouse included. `#digest-icon` carries `hidden` in `web/index.html` and no script removes it (`renderDigest` only sets its class, label and title; `.digest-icon[hidden]` is `display: none !important`), and `#activity-strip` is `display: none` (`input_activity.css`, operator request 2026-04-29). So both modals hardened in cycles 110 / 111 have no production entry point. Whether to restore an entry point or retire the modals is filed for the operator (RM-1427), not ruled.
- Guard: `tests/snapshot_panels/test_ctrl_k_needs_a_rendered_prompt.py` (red 13 failed / 2 passed, green 15 passed).

## 2026-11-04 - lane 4 headless, s144 cycle 113 (RM-1422)

### RULING
- **A transient layer that a scroll carries out of sight closes.** A layer registered with `scrollAway()` in `web/js/lib/escape_layers.js` is watched by one capture `scroll` listener: when a scroll of an element (or the page) that holds it leaves it showing less area than the most it has shown since it opened (clip = the viewport plus every ancestor whose overflow is not visible), `scrollAway()` runs. A scroll that reveals more keeps it open, so a menu that opened partly cut off can still be scrolled into view. The opener calls `armScrollAway(name)` after showing it and after its focus move, so the focus scroll of the open is not a scroll away.
- Wired to the two layers that live in a scroller: the Lobby lane popup (`#lv-lane-popup`) and the Lobby mode menu (`#lv-mode-menu`), both position:absolute inside `#view-lobby` (`overflow-y: auto`). The view menu and the Home Find Match picker are position:fixed, so a scroll never moves them; they are not registered.
- Focus that was inside the closed layer goes back to its trigger with `preventScroll`, so the page stays where the wheel put it (a plain `focus()` would scroll the trigger back into view and undo the user's scroll).
- Measured before the fix, headless Chromium under `?ui_mock=1#lobby`, a real wheel (`page.mouse.wheel`, 600 px) over the view: `#view-lobby` scrolls 200 px at 1280x720 and 30 px at 923x1280 (0 at 1920x920). At 1280x720 the open lane popup went from y 110..208 to y -90..8 with the view's top edge at 57, still open, rendered, focus on its MIDDLE cell, so every letter shortcut stayed dead (`_menuRendered`). Same for the mode menu scrolled back up past what it had shown.
- Alternative not taken: keep the popup on-screen (reposition it on scroll). It is anchored to the lane pair; following a scroll would detach it from its trigger. Closing matches how a native select popup behaves.
- Alternative not taken: make `_menuRendered` count only an in-viewport menu. That leaves an open menu out of sight with the shortcuts live; it reopens on scroll-back already open, with focus lost in between.
- Not changed, filed: at 923x1280 the lane popup opens with its top 26 px above the view's top edge (popup top 30.8, view top 57), so its lane label row is cut off at open (RM-1428).
- Guard: `tests/snapshot_panels/test_lobby_popup_closes_on_scroll.py` (red 6 failed / 2 passed, green 8 passed), `visibleArea` / `scrolledAway` / `armScrollAway` in `web/js/lib/escape_layers.test.mjs`.

## 2026-11-04 - lane 4 headless, s144 cycle 114 (RM-1428)

### RULING
- **The Lobby lane popup is whole inside the view at open.** `_openLanePopup` (`web/js/main.js`) places `#lv-lane-popup` above the lane pair as authored; when its top would sit above `#view-lobby`'s scroll origin (measured in CONTENT space: rect top minus the view's padding-box top plus `scrollTop`) it adds `.is-below` (`web/css/panels/header.css`: `top: calc(100% + 8px); bottom: auto`) and opens under the pair. The class is cleared on every open, so a resize between two opens never leaves a stale side. After the focus move the popup itself is scrolled into view (`block` / `inline` `nearest`), before `armScrollAway`, so the label row above the focused cell is never left past the view's edge.
- Measured before the fix, headless Chromium under `?ui_mock=1#lobby`: wherever the Lobby view stacks to one column (923x1280, 1024x600, 800x600) the pair's top is 79 px under the view's top and the popup needs 105 (97.2 tall plus the 8 px gap), so it opened at y 30.8 against a view top of 57 and its label row (y 41.8..61) was cut off where no scroll could reach. At 1920x920, 1280x720 and 1366x768 it fit (top 108.4..110.4) and keeps the above placement.
- Why content space, not the visible edge: a view merely scrolled down (1280x720 scrolled 200) has room above inside its content, so the popup still opens above and the open scrolls back to it, which the RM-1422 test `test_opening_from_a_scrolled_view_stays_open` pins.
- Alternative not taken: flip whenever the popup is cut by the VISIBLE edge. That flips a popup that only needs a scroll back, so the side would depend on scroll position instead of layout.
- Alternative not taken: move the lane pair down or pad the view top in the stacked layout. It changes the card layout for every user to fit a transient menu.
- Consequence for RM-1422: at 923x1280 the view scrolls only 30 px and the flipped popup stays whole after it, so it now correctly stays open; that test's second viewport moved to 1024x600 (the same stacked layout, 710 px of scroll), and its "the page stays where the wheel put it" check reads `min(600, maxScroll)` instead of assuming the wheel reached the end.
- 5-phase audit (headless, 1920x920 / 923x1280 / 1024x600): STRUCTURE popup inside the view, 0 px horizontal overflow on the document and the view, the popup paints on top at all 9 sampled points, never overlaps the lane pair; TYPOGRAPHY label 16px (`--fs-xs`), unchanged; HIT-TARGETS cells 46x46 against `--hit-min` 42px, keyboard-opened cell matches `:focus-visible` with a 2px solid ring; ASCII 0 non-ASCII bytes added; HIERARCHY label `oklch(0.94 0.02 305)` on the popup surface `oklch(0.27 0.06 302)`, unchanged.
- Guard: `tests/snapshot_panels/test_lobby_lane_popup_fits_at_open.py` (red 10 failed / 9 passed at HEAD before the scroll-away control was added, and 11 failed / 9 passed with it, measured by the verifier serving the HEAD main.js and header.css; green 20 passed).
