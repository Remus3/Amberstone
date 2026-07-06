# Overlay UI redesign + DS-stability - next-session spec (2026-07-06)

Handoff from the 2026-07-05/06 live-ARAM session. The operator flagged a grab-bag
of overlay issues + a DS build-suggestion instability while playing. The CV-precision
work (minimap scale 3.0) was resolved or SR-gated; the UI grab-bag was dispatched as 3
parallel worktree build agents that DIED early (only TDD stubs written), so the UI work
was DEFERRED to a clean out-of-game session (this spec). Execute out-of-game: overlay
edits hot-reload into the live overlay (ADR-008 asset-hash), so a bad edit breaks a live
game; and the DS-stability fix is Tier-2 (needs a DS :8893 restart + Share suite).

Ground truth captured live this session (verify still current before building):
- mode was ARAM, MinimapScale=3.0 (game.cfg), native 2560x1440.
- /api/state.minimap_rect auto-computes to {x:1487,y:647,w:426,h:426} (design px).

## CV precision - status (mostly done or SR-gated; NOT part of the UI redo)

- STEP 1 rect@3.0: DONE + VERIFIED. The affine model in core/minimap_geometry.py
  (side_frac = 0.0764*scale + 0.1651) extrapolates correctly to scale 3.0. Measured the
  actual minimap on a live native grab: content bbox ~(1989,865)-(2559,1439) vs computed
  (1982,862)-(2550,1430) = within ~9px. No re-calibration needed. (Optional micro-nudge:
  the computed rect is ~9px short on the right/bottom; not worth a restart.)
- MINIMAP GOLD BORDER MISALIGNMENT (operator-reported): the rect VALUE is correct (above),
  so the misalignment the operator sees in the overlay is OVERLAY-RENDER-side, not the
  affine model. Two candidates, both overlay-lane (see BATCH B): (1) ovscale/full-bounds -
  the overlay window sized to the taskbar work-area (2560x1400) not full bounds
  (2560x1440) offsets every design-px widget (memory reference_minimap_geometry_calibration
  item 570 + reference_overlay_ovscale_positioning); the big scale-3.0 minimap shows it
  most. (2) stale rect - the overlay rendering the old scale-1.62 rect (312px) not the new
  426px one (a web/js/main.js threading gap at the 3 poll sites). Diagnose with a composited
  overlay screenshot: minimap-sized-but-offset = ovscale; much-smaller box = stale rect.
  web/js/panels/minimap_rect.js is the renderer.
- STEPS 2-3 (blob-gating/identity + macro/MIA feed): SR-GATED, unchanged from the ZOI
  plan section 9. On ARAM, champions overlap into 679/622px mega-blobs; identity
  template-match hit only 1/13 even with the correct roster injected (scale-3.0 icons are
  big enough - clustering is the wall, not icon size). The macro callout + zoi.mia are
  SR-only (dashboard/_deterministic_coaching.py:636 `if lower == "sr"`), so they cannot
  fire/validate on ARAM regardless. Validate on a practice SR game. Do NOT flip
  RC_ZOI_IDENTITY / roster-wiring blind. NOTE: the earlier "_live_roster returns []" was a
  COLD-STANDALONE-PROCESS artifact - the running RC's warm liveclient_cache has all 10
  champs (verified via :8889/latest-liveclient). Prod roster path is fine.

## BATCH A - in-game BUILD panel redesign + 3 bugs

Files: web/js/panels/active_match.js (the panel; _renderAmBuildBody at line 458),
web/js/panels/ds_shaper.js (DMG/SURV/UTIL shaper), web/css/panels/active_match.css,
web/css/panels/ds_shaper.css. Engine item-conflict may touch core/build_order.py (Tier-2).

Current code (grounded): the BUILD panel is ALREADY a 4-row module (bm-module) in
_renderAmBuildBody: Row1 LIVE (_maybeRefreshDsPicks), Row2 META (_maybeRefreshBuildOrder,
"loading standard build..." empty strip at line 601), Row3 FIGHT MODEL (_renderBmKnobs),
Row4 SHAPER (renderShaperStrip). The redesign reshapes this to the operator's EXAMPLE.

Operator EXAMPLE (target layout):
    Daemon Slayer [SR: Bottom] | [DS Archetype dropdown]
    {up to 7 item imgs}      (7 slots; boots do NOT cost a slot after the SR quest)
    Meta Build [dropdown if >1 flavor]   (this row must NOT flip/change or be empty)
    {up to 7 item imgs}
    Ultimate Build [dropdown if >1 flavor]
    {up to 7 item imgs}
     - 0 +   - 0 +   - 0 +
    DMG     SURV     UTIL

Fixes:
1. REMOVE the "BUILD" title bar (operator knows what it is; wastes vertical space).
2. BLANK-META BUG: Row2 META stuck on "loading standard build..." (line 601) because
   _maybeRefreshBuildOrder returns []. Root-cause why /api/build-order never lands for the
   live champ/mode and fix so meta items render. (Likely tied to the DS-stability re-fetch
   path - see DS-STABILITY below.)
3. ITEM-CONFLICT BUG: LIVE row shows multiple same-unique-family items (owner has LDR /
   Lord Dominik 3036, yet Mortal Reminder 3033 + Serylda 6694 - all Last-Whisper - also
   surface). The LIVE row is a raw DS delta ranking (rank_items) that does NOT de-dupe by
   unique family for display; the META row (build_order.py) IS family-safe
   (unique_passive_safe). Fix: family-dedupe the LIVE display using the family-safe order[]
   as the family authority (no client family-literal map - the engine no-double rule is
   authoritative, CLAUDE.md Settled).
4. DEAD-COUNTER BUG: the DMG/SURV/UTIL +/- buttons in the SHAPER (ds_shaper.js
   renderShaperStrip) do not change the 0 value on click. Root-cause the broken
   click/increment handler + persist to the shaper state (GET /api/ds-shape).
5. COUNTER LAYOUT: 3 categories left-to-right on one row ("- 0 +   - 0 +   - 0 +") with
   cyan DMG/SURV/UTIL labels directly below (compact 2-row block), per the EXAMPLE.
6. Space-optimize the cramped panel.

ACCEPTANCE TEST (from the salvaged Agent-A stub - implement the helpers to pass it):
new pure helpers in active_match.js, `_bmComposeRows({live, meta, ultimate})` -> 3 NAMED
rows [{label:"Daemon Slayer",items},{label:"Meta Build",items},{label:"Ultimate Build",
items}] with a 7-slot cap; an empty meta source yields items:[] (NOT a stuck placeholder
flag - the blank-meta fix); and `_bmFamilyDedupe(rawOptimal, familyById)` keeps ONE item
per unique family (drops the 2nd/3rd Last-Whisper), passthrough when familyById is null
(fail-open, never blanks a row). The full salvaged test is at
.claude/worktrees/agent-ac5d1a86921343231/web/js/panels/active_match_buildrows.test.mjs
(preserve it before removing the worktree - copy into web/js/panels/ once the helpers exist).
"Ultimate Build" source: investigate whether a 3rd real build source exists (full DS-optimal
endgame vs meta=popular); if only 2 sources, map the best candidate + NOTE the gap - do NOT
fabricate data.

## BATCH B - overlay canvas / scaling / repositioner / minimap-border

Files: web/js/lib/overlay_layout.js, rc-shell/src/main.js (Electron main - Ctrl+Shift+A
handler + window bounds; NOT the frozen Python main.py), rc-shell/src/overlay_state.js,
rc-shell/src/preload.js, web/css/overlay.css (canvas sizing - merger-owned).

Fixes:
1. Ctrl+Shift+A reposition mode: the operator can currently drag the whole screenspace
   CANVAS. Lock it - only individual panels should move, never the background canvas.
2. SCALING RECENTER BUG: scaling any panel pulls ALL panels to the canvas center. Fix so
   scaling preserves each panel's on-screen position (scale in place, no recenter).
3. CANVAS UNDERSIZED: the canvas does not cover the full 2560x1440 resolution, so panels
   cannot be placed across the full screen. Make the overlay window cover full display
   bounds - re-assert overlayWindow.setBounds(fullBounds) AFTER setAlwaysOnTop
   (resolveOverlayScale min(w,h) axis + the Windows work-area create-clamp; memory
   reference_minimap_geometry_calibration item 570 + reference_overlay_ovscale_positioning).
4. PANEL-MOVE WALL + AUTO-SCROLL: dragging a panel to an edge hits a wall and the view
   auto-scrolls. Remove the scroll region / clamp; panels placeable anywhere on the full
   canvas.
5. MINIMAP GOLD BORDER: fixing #3 (full-bounds + correct ovscale) should land the
   minimap_rect gold border (minimap_rect.js) on the actual minimap - the cleanest
   acceptance test for the canvas fix. If minimap_rect is a settings-pinned special path
   that bypasses the shared ovscale, adjust it too.

## BATCH C - per-panel polish

Files: web/js/panels/objective_gauges.js + web/css/panels/objective_gauges.css,
web/js/panels/stats_panel.js, web/js/panels/enemy_spells.js (stats/enemy-spell CSS may be
inline or in overlay.css - if shared overlay.css, merger applies it).

Fixes:
1. OBJECTIVE GAUGES: DRAKE/BARON/ELDER render as an awkward cluster/L-shape ("not
   horizontal or vertical"). Make them one consistent axis (horizontal row preferred).
2. STATS PANEL default-role: YOU-vs-AVG defaults to MID regardless of the player's role
   (Kai'Sa/Aphelios are bot/ADC but it shows MID). Default to the detected role; ARAM has
   no lanes -> a non-MID sensible default (champion class or an "all/average" compare).
   Keep the manual dropdown override.
3. ENEMY SPELLS: summoner-spell indicators truncated ("F. P." / "F. I." / "B. I." cut off).
   Widen / consistent-abbreviate / wrap so they are fully visible without overflow.
4. INCONGRUENT PANEL BORDERS: panel containers use --ovx-gold at scattered alphas (0.70 /
   0.85 / 1.0 / 0.55 / 0.40 / 0.10 in overlay.css). Standardize the generic panel-container
   border to ONE token (keep the semantic good/red/warn/cyan status borders as intentional).
   tokens.css is the source. Merger-owned (overlay.css).

## DS build-suggestion instability (PD -> Kraken) - Tier-2 engine, out-of-game

Root cause VERIFIED against ground truth this session (greedy ranker + zero hysteresis):
- agents/daemon_slayer/rank.py:942-953 `_base_key` returns a float 2-tuple
  (delta_dps, dps_per_1k_gold) with NO stable tiebreak; sorted reverse at line 961.
- core/build_order.py:347-367 `_pick_top_safe` returns rows[0] greedily per slot.
- The frontend re-fires the ranker on small input changes (web/js/panels/build_order.js:40
  _boKey includes _enemySig -> re-fetch when ARAM enemies resolve empty->known;
  web/js/panels/active_match.js:114-118 _dsRerankKey re-ranks on a level/item tick).
- Deterministic WITHIN a process (identical POST 3x = byte-identical), but a level tick
  genuinely crosses close items (repro: Kraken 122.3 -> Hexoptics 124.5 at lvl 12->13) and
  exact ties can flip across a :8893 restart (dict iteration order). SAME ranker feeds
  champ-select AND the in-game LIVE/META rows -> one fix cures both.

Fix (Tier-2 - full DS/Share suite + DS :8893 restart; do NOT run mid-game):
- (a) rank.py: append `item_id` to the sort key (all 4 _base_key branches) -> deterministic
  ties, cross-restart stable.
- (b) build_order.py: thread an optional `incumbent` (+ margin ~3%) into plan_build_order /
  _pick_top_safe; keep the incumbent unless a challenger beats it by the margin. ADDITIVE -
  byte-identical when no incumbent is passed (existing tests/behaviour preserved).
- Frontend opts in: champ_select.js + build_order.js + active_match.js pass the currently
  displayed pick(s) as the incumbent. (active_match.js overlaps BATCH A - do it in the same
  slice.)

## Also owed (unchanged, gated)

- B45/B46 EHP flips: Randuin's crit-DR / Steelcaps AA-DR - DS-restart-gated eyeball.
- R81 phase-strip overlay pixels - live-game-gated capture.

## Execution notes

- Do this OUT OF GAME. Overlay JS/CSS hot-reloads into the live overlay (ADR-008); the
  build panel is live-critical. New imports in active_match.js need an rc-shell RELAUNCH
  (not an RC restart) to load - plan for it.
- The parallel background-worktree-agent dispatch DIED early this session (empty transcripts,
  frozen worktrees ~40 min). Prefer foreground/inline or a smaller agent fan-out next time;
  verify agent liveness via worktree mtime + transcript size early.
- Verify each panel with the 5-phase UI fixture ritual BEFORE commit (STRUCTURE / TYPOGRAPHY
  / HIT-TARGETS / ASCII / HIERARCHY). ASCII-only, no em/en-dashes or smart quotes.
