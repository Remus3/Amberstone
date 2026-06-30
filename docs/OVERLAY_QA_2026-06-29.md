# Overlay live-QA findings - 2026-06-29 (in-game Practice Tool SR)

Live operator QA pass over the in-game overlay. Status: DONE = fixed + committed,
LIVE = fix is hot-loaded, pending operator visual confirm, OPEN = not started.

## Fixed this session
1. **Minimap outline misaligned** - DONE. Was placed in design px + scaled by
   ovscale (a DPI knob), not native res. Now placed by window fraction, zoom-
   immune, + operator nudge (+6 right, +2 down). Operator-confirmed aligned.
   Commits: ovscale-immune placement + nudge (web/js/panels/minimap_rect.js).
2. **BUILD panel random flicker** - DONE. Transient empty-champion tick wiped
   innerHTML and rendered nothing. Added retain-last-good guard
   (_shouldRetainBuild). web/js/panels/active_match.js + test, 12/12 green.

## Pending verify
3. **ZOI / minimap dots never render** - LIVE (uncommitted, main.js). Root cause:
   zoi/minimap_dots are HTTP /api/state-only (build_state); the live overlay
   feed (:8891 WS push + the staleness-gated polls) never lands a non-null zoi
   in state.latest, so renderMinimapZoi(null) clears every tick. Added an
   unconditional 2s minimap poller (setupMinimapPoller). NEEDS operator visual
   confirm (faint blue/red bubbles inside the outline) before commit.

## Fixed this session (cont.)
4. **Coach card timer tags raw** - DONE. active_match.js routed
   action/immediate/next/objective through safe() (strips the bracket markup),
   matching right_now.js/next.js.
5. **Coach sub-text truncates** - DONE. OBJECTIVE line-clamp 2 -> 3 (overlay.css);
   paired with the tag-strip the prose is shorter so 3 lines lands the full call.
7. **META items show +0** - DONE. noDelta _dsIcon option suppresses the badge on
   the static META row; LIVE keeps real deltas.
6b. **FIGHT MODEL removal** - DONE. .bm-row.bm-knobs hidden on the overlay
   (overlay.css); dashboard keeps it.
6c. **META "loading standard build..."** - NOT A BUG. The POST /api/build-order
   returns a valid 6-item order; the placeholder is the pre-resolve state, caught
   transiently during the dev reloads. Clears on the next tick.

## Open (next batch)
6a. **BUILD panel horizontal 3-row** - the overlay renders a vertical 2-col grid,
   not the bm-module horizontal-3-row (B2). Needs investigation: is the overlay
   on an older renderer, or is bm-module CSS wrapping into a grid? NOT a quick
   patch - spec it.
8. **Enemy-spell pills truncated** - `Fla.../Pri.../Unl...` unreadable (A5
   widen+unname marked DONE but not in overlay path).
9. **Item tooltip** should show name-only on hover; panel hover tooltip renders
   far to the right + down (mispositioned).
10. **PANELS settings sliders (OP/SZ) non-functional** - dragging does nothing.

## Cross-cutting note
Items 6, 8 (and the timer tags) are the SAME failure shape: a fix verified on the
:8888 dashboard never reached the Electron overlay render path
(electron_overlay_only trap). Worth a single audit of overlay vs :8888 divergence
rather than per-symptom patching.
