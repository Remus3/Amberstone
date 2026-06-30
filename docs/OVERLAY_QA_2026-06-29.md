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
3. **ZOI / minimap dots never render** - ROOT-CAUSED + FIXED 2026-06-30. The
   canvas (#am-zoi-canvas) was rendering at computed **opacity 0** in the live
   Electron overlay - the ZOI fill drew correctly but was fully transparent, so it
   NEVER appeared in-game even though the data, box, sizing, and paint were all
   right. Proven live with an on-canvas magenta probe + an on-screen numeric
   readout (op=0; forcing opacity=1 made the fill appear). No CSS/JS rule sets it
   (most likely a Chromium quirk for an absolutely-positioned child inside the
   position:fixed + zoomed #am-mmrect). FIX: `canvas.style.opacity = "1"` in
   renderMinimapZoi (the ZOI faintness is the 2D globalAlpha cap, not element
   opacity), plus an explicit px display-size pin. The data-side groundwork from
   the prior session (the unconditional setupMinimapPoller in main.js feeding
   /api/state.zoi) stays - it was necessary but not sufficient. DEBUG_ZOI back OFF.
   Open tail: confirm the real faint bubbles read well next game; one-line alpha
   bump (MAX_ALPHA / OFFSCREEN_CORE_ALPHA) if too subtle.

   ALSO fixed this session: the in-game overlay DID hot-reload, but only because
   the earlier asset-stamp fix (commit 6c355c34) made /api/asset-stamp track
   js/panels + js/lib; before that, panel edits never reloaded the overlay (the
   electron_overlay_only trap). The long "no magenta" run was partly stale JS.

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

## ROOT CAUSE of the electron_overlay_only trap (2026-06-29, this session)
The overlay's in-page hot-reload poller (main.js _hotReloadInit) polls
/api/asset-stamp every 3s and reloads on an mtime bump. But _serve_asset_stamp
(dashboard/routes_state.py) only stats THREE files: index.html, css/dashboard.css,
js/main.js. It does NOT walk js/panels/*. So every edit to a panel module
(minimap_zoi.js, active_match.js, etc.) NEVER bumps the stamp -> the overlay never
auto-reloads -> the operator only ever saw stale panel JS unless they manually
relaunched rc-shell. This is WHY panel fixes "never reached the overlay" all saga.
compute_asset_hash (dashboard/_static.py) already walks js/panels for cache-bust,
and _send defaults Cache-Control: no-store, so a reload DOES fetch fresh panel JS -
the only gap is the stamp file list. FIX: add the js/panels (+ css/panels, js/lib,
css/overlay.css) walk to _serve_asset_stamp so panel edits trigger the reload.
(Needs RC restart to take effect.) Interim unblock used this session: `touch`
web/js/main.js to force the stamp to bump.

## ZOI verdict (item 3) - STILL PENDING a live game
First "NO magenta" verdict was on STALE JS (stamp never bumped, above). After the
main.js touch the overlay reloaded with DEBUG_ZOI=true loaded, but the game ended
before re-check. DEBUG_ZOI is left TRUE; operator will read the magenta verdict in
the next SR Ranked. minimap_zoi.js reasoning confirmed this session: renderMinimapZoi
DOES receive valid 15-bubble data (SSE payload carries zoi + the dedicated 2s
minimap poller feeds it); the snapshot test proves canvas sizes to 312px with no JS
error. So the bug is purely paint/visibility - magenta probe will disambiguate.

## New operator findings (2026-06-29, between games) - NOT yet fixed
A. **Out-of-game overlay flickers a bit.** Unverified cause (could be the one-time
   reload from the stamp touch, or a render idempotency miss). Watch for repeat.
B. **In-game panel drag glitch / unretrievable.** - LIVE (pending operator
   confirm). Dragging a movable widget near the minimap made it "glitch to the
   bottom of the screen and be un-retrievable." Mechanism (overlay_layout.js): the
   bottom-corner anchor snap (_applyPos: p.y > H*0.5 -> top:auto; bottom:16px, added
   2026-06-29 for the tall BUILD panel) fired for ANY widget dropped below the
   midline, teleporting it to the bottom; combined with NO on-screen clamp on the
   drag nx/ny, a widget could land off-screen / behind the minimap with no grabbable
   handle. FIX (operator chose "snap only tall panels"): the bottom-snap now keys
   off a per-widget `tall` flag (only w-build carries it) - every other panel is
   free-placed exactly where dropped; a new pure _clampXY keeps each widget's
   top-left (MIN_VISIBLE=48px) on-screen during the drag, on drop, and on load, so
   nothing is ever stranded. The launcher button is clamped too. node --test green
   (web/js/lib/overlay_layout.test.mjs).
C. **Champ-select coaching defaults to MID, not the operator's assigned lane.**
   - OPEN. Live shot 2026-06-29: operator was Caitlyn BOTTOM/ADC (RC build dropdown
   correctly read "Caitlyn sr-collapsed-a dc-crit"), but PICK-INTO-THIS-COMP /
   counter panels showed MID content (Akali/Diana/Talon "counters Annie"). Suspect:
   _csvResolveRole (web/js/panels/champ_select.js:3898) reads assignedPosition via
   cs.my_team.find(cellId === cs.local_cell); when that lookup misses it returns "-"
   and downstream counter/tip pools render mid-centric. Root-cause (is local_cell /
   my_team / assignedPosition populated in ranked solo? does "-" fall through to a
   MID default pool?) + fix DEFERRED to post-game (editing champ_select.js mid-draft
   would hot-reload the live pick screen).
D. **Champ-select view flicker (item A, refined).** renderChampSelectView
   (champ_select.js:675) rebuilds large body.innerHTML every envelope tick; add an
   entry sig-guard so it only rebuilds on real state change. DEFERRED to the same
   post-game window as C.
