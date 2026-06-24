# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-24 (R30 IN-GAME design review - champ-select COMPLETE + active-match map rethink; "live-gated" deferral debunked)

Interactive operator session. The prior 3 R30 sessions deferred ALL in-game pages as LIVE-GATED; that was
WRONG - champ-select / active-match / overlay render fully headless via the EXISTING ui_mock fixtures.
Extended the recon harness to `ops/runtime/ui_recon/recon.py <view> [mode] [overlay]` (drives
`?ui_mock=1&mode=<sr|aram|arena>#<view>` + `&overlay=1`), unblocking the whole in-game backlog. 4 slices
shipped + pushed, each RED-first + a 5-phase UI-audit subagent PASS + live-:8888 visual recon. Tier-1
frontend throughout; no engine / DS / Share / ENGINE_VERSION. Final gate 70 snapshot tests green.

CADENCE (same as out-of-game; reuse for the overlay + active-match tail): recon each view at 923 + 1920 via
`recon.py <view> [mode]`, READ + JUDGE the screenshots + ground-truth file:line, PRESENT keep/remove/add/alter
+ ONE framed scope AskUserQuestion, build the picked slice RED-first, 5-phase UI-audit gate, commit+push.

- CHAMP-SELECT (COMPLETE, SR/ARAM/Arena). (1) `b76bacf7` ARAM/Arena ASSESSMENT: the non-SR grid override
  dropped the `suggestions` grid-area -> the card orphaned out of grid flow (floating panel + huge void);
  restored a 2-row template + new `_csvRenderSuggestionsNonSr` fills the right column with TEAM DAMAGE LEAN +
  WATCH THEIR COOLDOWNS (counter-picks stays SR-draft-only). (2) `2f9daab7` Arena DS build wiring:
  `_csvRenderCentralPane` early-returned for Arena (no archetype picker, no build chooser despite the fixture
  data); removed the early-return -> Arena flows through the shared setup (archetype left col + duo/augments +
  build chooser + DS-vs-enemy-comp). SR/ARAM byte-identical; Arena variant rows are backend-fed (empty until a
  Jinx Arena loadout is saved - same path as SR/ARAM). (3) `c758254c` companion reflow:
  `@media (max-width:1200px)` single-column for all 3 modes + the no-scroll height-cap resets; mirrors item-602.
- ACTIVE-MATCH (1 slice). `174854c5` MAP real-estate rethink: Live Client has no coords (memory
  `reference_liveclient_no_positions`) so the static map can't plot positions; `_renderAmMap` now builds a
  column shell - `.am-map-intel` (PRIMARY: status + de-overlaid full-width roster) over `.am-map-figure`
  (SECONDARY: map img + ZOI canvas + gank band, height-capped 50%); ALL element IDs preserved (polling/overlay
  render untouched); grid 1.1fr/2fr -> 1.4fr/1.6fr. Sparse vision -> acceptable trailing space (real games fill
  the roster).

NEXT (remaining R30 in-game): the OVERLAY surface (unreconned - `recon.py active-match sr overlay`) +
active-match follow-ups (the ARAM ward-heat strip's TOP/JG/MID/BOT lane labels are meaningless single-lane;
active-match has 923 companion horizontal overflow, worstRight 1226 - needs a reflow like champ-select got).
Genuinely live-gated OWED (need a physical game): E.1 ACTIVE knob physical press + `RC_COMP_HP_LEAN` default-ON
flip. Harness + gemini_out.txt at `ops/runtime/ui_recon/`.

---

# 2026-06-23 (R30 CONTINUATION-2 - per-page UI/UX design review, pages 8 + 6 of 9; OUT-OF-GAME COMPLETE)

Interactive operator session finishing the R30 out-of-game review (pages 1-5,7,9 shipped prior; ledger
603-608). 2 pages shipped, 2 commits pushed, gate green (248 snapshot tests; 63 replay tests; a 5-phase
UI-audit subagent PASS each page; node --check OK). All Tier-1 frontend; no engine / DS / Share /
ENGINE_VERSION. mode=client, NO live game -> the in-game champ-select / active-match / overlay pages + the
2 OWED live-gated items (E.1 ACTIVE knob; RC_COMP_HP_LEAN flip) stayed un-buildable.

CADENCE (proven, reuse for the in-game pages): recon each view at 923 + 1920 via live-:8888 Playwright
(`ops/runtime/ui_recon/recon.py <view>`) -> READ + JUDGE the screenshots, ground-truth every finding at
file:line -> PRESENT keep/remove/add/alter + ONE framed scope AskUserQuestion -> build the operator-picked
slice RED-first + a 5-phase UI-audit subagent gate before commit -> commit+push. Gemini PART B per-view
intent in `ops/runtime/ui_recon/gemini_out.txt`.

- PAGE 8 BUILD INSIGHTS (`dec18ded`, full pass): the 4 WPA tables already avoid gemini's global-pickrate
  trap (personal residuals), so added a confidence-weighted TAKEAWAY rail beside each table - strongest +
  weakest mover ranked by `wpa_shrunk` (the shrink-adjusted residual, emitted by all 4 routes) so the
  TRUSTWORTHY signal wins not the noisiest low-n row (Skills fixture: raw-worst Corki n=25 vs shrunk-worst
  Kog'Maw n=39 -> the rail surfaces Kog'Maw). Fills the ~650px desktop dead zone; stacks above the table at
  companion (`order:-1`). + the Min-N control relabels per tab (buys/games/picks) + hides on the 4 chart
  tabs (inert no-op there). Also fixed a stale pre-existing DOM test (`test_uses_semantic_token` asserted
  the pre-reskin `var(--signal-*)`; file uses `--good`/`--bad` - failed on base, CI runs no pytest).
- PAGE 6 REPLAY (`1537f5d7`, "+reorder" full slice): gemini's job is "actionable event timeline, not a
  video player". (1) CLICK-TO-SEEK: each timeline event row seeks the scrubber to its `clock_s` (nearest
  snapshot by minute) + re-renders the grid at that frame - cross-module circular-import-free via a
  `setReplaySeekHandler` bridge (replay_events.js delegated click on `#replay-events-list` -> dev.js
  `_replaySeekToClock`). (2) REORDER: timeline section hoisted ABOVE the grid (event-index-first). (3)
  swept primitives.css fully ASCII-clean + tokenized `.replay-col-items` padding + index.html arrow -> "<-".
  KEPT the 4px icon radii (dashboard convention, 81x / 21 files); grid scroll-wrap untouched (operator-locked).
  LESSON: the `-F` commit-message-file path avoids the PS 5.1 here-string mangling that exit-128'd the first
  `git commit -m @'...'@`.

NEXT (operator directive): the OUT-OF-GAME review is COMPLETE (pages 1-9). Only the in-game champ-select /
active-match / overlay pages remain - LIVE-GATED. Resume them when a game is live, reusing the harness +
`gemini_out.txt`. Carry-forward OWED (live-gated): E.1 ACTIVE knob physical press; `RC_COMP_HP_LEAN` flip.

---

# 2026-06-23 (R30 CONTINUATION - per-page UI/UX design review, pages 3,4,5,7,9 of 9)

Interactive operator session continuing the R30 review (pages 1-2 shipped prior, ledger 603). 5 pages
shipped, 5 commits pushed, gate green (241 snapshot tests; 0 non-ASCII; a per-page 5-phase UI-audit
subagent PASS each page). All Tier-1 frontend; no engine / DS / Share / ENGINE_VERSION. mode=client,
NO live game all session -> the 2 OWED live-gated items (E.1 ACTIVE knob; RC_COMP_HP_LEAN flip) stayed
un-buildable.

CADENCE (proven, reuse pages 8 + 6): recon each view at 923 + 1920 via live-:8888 Playwright
(`ops/runtime/ui_recon/recon.py <view>`) -> READ + JUDGE the screenshots, ground-truth every finding at
file:line -> PRESENT keep/remove/add/alter + ONE framed scope AskUserQuestion -> build the operator-picked
slice RED-first + a 5-phase UI-audit subagent gate before commit -> commit+push. Gemini PART B per-view
intent in `ops/runtime/ui_recon/gemini_out.txt`.

- PAGE 3 PGR (`372b568b`, full pass): default tab Build->AI Analysis (autopsy-first; Build = gemini's
  named scoreboard trap) + tab reorder + a takeaway headline above the hero (my_chronic > real wrong_team
  > right); pure-CSS `::before` frame captions "Overall"(grade) + "Lobby"(score) so the 3 verdicts read as
  distinct frames; rank-compare collapses to selector+prompt when no tier (static averages, no auto-rank
  route exists); deferred token fold-in `--radius-sm`->`--panel-radius`(cards) / `--panel-radius-sm`(chips).
  LESSON: verified the AI-Analysis tab degrades to the quick-review when no Match-V5 timeline (safe default).
- PAGE 4 SESSION (`0fa3dd36`, full pass): the view's JOB (tilt/fatigue/limits) was entirely MISSING -
  added a tilt/fatigue verdict + chronological grade strip derived from `d.matches` (no backend); companion
  `.session-grid` -> 1-col (Modes-label collision); de-redundancy CHAMPIONS->REPLAYED CHAMPIONS (2+-game
  only, hidden when none) + removed the OVERVIEW "Started" header-dup.
- PAGE 5 HISTORY (`0c0bdc16`, full pass): VERIFY-BEFORE-DECLARE corrected my first read - the filters are
  already GLOBAL (`_historyApplyFilters`), trap avoided. Gap = a filter gave a LIST but no AGGREGATE; now
  SEASON STATS reflects the filtered subset (retitled "JINX STATS"; total/WR/KDA/most-played), restores on
  clear; empty state advertises global filtering; 3-col grid -> 1-col at companion.
- PAGE 7 USER BUILDS (`eb5aea8a`, full pass): CRUD already good (datalist autocomplete / inline edit-delete
  / side-pane editor not a modal / Delete confirm - trap avoided); fixed the dead-space (`.ub-layout`
  full-width at rest, 2-up only while editing via `:has()`) + item icons per row (`_resolveItemId` name->id).
  Updated `test_companion_reflow.py` (ub now 1-col at rest -> companion guard only).
- PAGE 9 SETTINGS (`3d52ee35`, picked 2+3): panel already centralized (scattering trap avoided - PGR knobs
  canonical here + mirrored); added a full-width quick-filter (`_settingsApplyFilter` shows only matching
  cards) + a density compaction (card gap + head margin).

NEXT (operator directive: WRAP here, resume next session): pages 8 (Build Insights -> `build_insights.css`)
+ 6 (Replay -> `primitives.css`) remain out-of-game; champ-select / active-match / overlay are LIVE-GATED
(need a game up - none this session). Reuse the harness + `gemini_out.txt`. Respect: replay scroll-wrap is
CORRECT (do NOT "fix" it); operator-locked `last_match.css` sub-floors. The full resume prompt was handed
to the operator in chat.
