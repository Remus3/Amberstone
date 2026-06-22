# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-21 (headless continue 6) - overlay-polish queue item (1): already shipped, only a stale comment

Gemini director picked overlay-polish ROADMAP queue item (1) = "FIGHT MODEL pane `#am-pane-ovds` clips
in DEFAULT, gate to build-only." GROUND-TRUTH PROBE FOUND IT ALREADY SHIPPED: the doctrine widget-field
model (commit `7bd7d6a3`, the cfdc9f22 batch) gates `w-ovds` to the build panelset ONLY - overlay.css
section 4d hides it in default/coach/threat (L418/421/437) + shows it only in build (L451); the pane is
a `fit-content` `.ovx-widget` (no height cap, inner `overflow:visible`) so it auto-sizes and no longer
clips. The 25 Playwright overlay snapshot tests already render-assert `#am-pane-ovds`=none in default +
shown in build (all 25 PASS this run; the lone teardown ERROR was the session prod-artifact guard
tripping on the LIVE practice game writing `data/*.jsonl`, NOT an overlay-test failure).

SHIPPED (Tier-0): corrected the one genuinely-stale artifact - the `overlay_ds_controls.css` header
comment said "base subset + the build panelset" / "section 4b" (both wrong); now reads build-ONLY /
"section 4d" + documents the deliberate behavior change. ROADMAP queue item (1) marked RESOLVED with the
evidence + a do-NOT-re-chase-the-662/1305-clip note.

No live rc-shell relaunch: the change is a code comment (zero render delta); the prompt's relaunch
mandate is for NEW overlay JS/CSS that renders differently, and the gating is CSS-structural (proven by
the real-browser snapshot suite + live-CDP-verified last cycle for the ZOI canvas itself).

NEXT: the overlay-polish red queue (items 1-5) is now fully DONE/RESOLVED - only minor w-* default-
position tuning remains, so the "route EVERY cycle here" run is winding down. Re-interview Gemini for the
next priority: candidates = ZOI slice 4 (champion-only isolation via template matching), the ~88 unwired
ADAPTATION st-* rows (item 281), or the aggregator-G-style PGR reframe. WAKEUP is at 6 entries - due for a
weekly-hygiene trim to the last 2-3.

---

# 2026-06-21 (headless continue 5) - ZOI SLICE 3: influence bubbles + demarcation + coach feed

ZOI item 567 SLICE 3 shipped + live-verified. Commit `163b76ee` (code) + docs sync, pushed; CI has no pytest gate.

Subagent-first: Gemini consult -> Plan subagent spec (frozen `/api/state.zoi` contract) -> 2 disjoint build
agents (backend / frontend) -> verifier gate (caught + I fixed a 245x U+2500 box-drawing ASCII violation in
the JS comment banners) -> UI-audit SHIP-CLEAN.

SHIPPED: `core/zoi_influence.py` (pure, 18 tests) `compute_zoi -> {bubbles, demarcation, map_control}` in
box-fraction; stamps `/api/state.zoi` + feeds a deterministic map-control callout into `det.callouts` (no
Haiku). `web/js/panels/minimap_zoi.js` canvas inside `#am-mmrect`: low-alpha team bubbles + weighted-bisector
demarcation, EMA-smoothed, click-through. Strength is PRESENCE-grounded (dot px*conf + MY ult spikes 6/11/16 +
game_time) - the Live Client has no enemy level/alive/gold (honest scope). Threaded `zoi` at all 3 main.js poll
sites; ui_mock fixture + overlay threading test added.

KEY FIX (live CDP pixel sample): raw overlapping bubbles composited to alpha 0.467 (> the 0.25 readability
cap). Fixed with PER-TEAM OFFSCREEN COMPOSITING (flatten each team, blit at 0.25) -> 99.7% of pixels <= 0.25,
peak 0.349 only in the thin contested seam.

LIVE-VERIFIED: RC restart -> `/api/state.zoi` 29 bubbles + map_control 60-91% ally + callout in
`/api/state.callouts`; rc-shell relaunched (no hot-reload) + CDP inspect of `#am-zoi-canvas` (painting over the
real minimap, pointer-events:none both = click-through). DON'T redo: slices 1+2+3; the offscreen-compositing
alpha cap; the presence-vs-champion-only scope.

NEXT: ZOI program FOUNDATION+1+2+3 done. Future (no owner): champion-only isolation (template matching);
richer strength if an enemy-data source appears.

---

# 2026-06-21 (headless continue 4) - ZOI slices 1+2: box renders+frames minimap, blob dots ship

ZOI item 567 advanced 2 slices. 2 commits `f93f5f01` (slice 1) + `d6a853f2` (slice 2), pushed; CI n/a (no pytest in CI).

SLICE 1 (the OWED live-verify - became a 3-bug fix). The foundation box never rendered live + was mis-scaled.
Diagnosed via the Electron overlay's CDP DOM (the 1px/0.55 gold hairline is invisible in screenshots - DOM
inspection is the ground truth, not the eye). (a) `minimap_rect` was never threaded into client `state.latest`
at the 3 poll sites in `web/js/main.js` so renderMinimapRect always got null; the ui_mock test masked it.
(b) the rc-shell overlay window used the taskbar-excluded WORK AREA -> ovscale 1.3 not 1.333 -> box ~3%
up-left; fixed to full display BOUNDS. (c) Windows clamped the frameless window to 1400 -> re-assert bounds
AFTER topmost -> 1440 (bottom reachable). Outline -> 2px/0.85 gold (was invisible). GOTCHA: plain GDI
BitBlt does NOT capture the layered click-through overlay - use CAPTUREBLT flag or Windows-MCP.

SLICE 2. `core/minimap_blob_detect.py` pure-numpy (numpy 2.5.0 installed for py3.14) team-color blob
detection -> `/api/state.minimap_dots`. Saturation discriminates icon vs terrain tint; `crop_minimap` maps
the design-px rect onto the ~1280 frame by fraction (legacy /api/minimap-crop is mis-cropped at scale 1.62,
bypassed). 11 tests; live 32 dots in 1.6ms. It is a team-PRESENCE detector (incl wards/structures), not
champion-only (template matching = future).

NEXT (slice 3): low-opacity team-colored ZOI bubbles + demarcation inside the box, weighted by per-team
strength (alive/dead, gold, spikes), fed to coach; UI-audit ritual. DON'T redo slices 1+2. Also: the Peer
bridge probe / `/loop /process-bridge-tasks` re-run is now REMOVED from the /done ritual (operator).

---

# 2026-06-21 (architecture viz) - HEXCORE: 3D RC/DS knowledge-graph nexus

Built HEXCORE (`docs/HEXCORE.html`) - a standalone interactive 3D hextech "JARVIS" viewer of RC/DS's
own code architecture. 3d-force-graph WebGL; Hextech palette (gold #C8AA6E + cyan #0AC8B9 on navy
#0A0E14 / #16202E) + the overlay typography; design ideas sourced from Gemini (`tools/gemini_ask.ps1`).
Maps RC's ground-truth-verified architecture as a navigable hologram: the DS engine pinned as a reactor
core; the per-mode coaches; the CORRECTED route binding (RC dispatches paths via `GET_ROUTES` tables +
`_dispatch.dispatch_get`, NOT decorators); the web-panel HTTP fetch->endpoint data flow (cyan particle
streams); and the real git co-change coupling (the 3 mode coaches). Hover scans + highlights neighbors,
click locks + camera-flies, search locates. LEDGER 568.

Also this session (infra): (1) landed the audit-10 C-01 cron silent-fail stub + audit artifacts
(`8ee3aa43`), regression-tested (`tests/test_agent6_failure_stub.py`, 5 passed). (2) Fixed the stale
Share review-gist: its clone .git had bloated to 582MB / 179 commits (one ~4MB Share.zip appended per
sync, unbounded) past GitHub's gist size quota -> every push rejected ~3 days. `tools/gist_share_sync.py`
now rolls a SINGLE parentless commit each sync + force-push + prune so it can never re-bloat; the
over-quota gist was unrecoverable in place so it was RECREATED with a NEW id
`gist.github.com/<redacted-gist-id>` (RE-SHARE this link; old 4a485b47 is dead).
`Share/README.md` refreshed 1.108.0 -> 1.149.0. (3) `git filter-repo` scrubbed an external review-tool's
name + 2 docs from ALL history + force-pushed main (CI green); backup bundle `.git/backup-pre-scrub.bundle`.

DON'T redo: HEXCORE built + corrected RC self-map captured; the gist fix is durable (NEVER hand-edit the
gist remote - the sync clobbers it); the external review tool is fully scrubbed from working tree + git
history - do NOT re-add it.

---

# 2026-06-21 (headless continue 3) - ZOI overlay FOUNDATION (settings-driven minimap outline)

Re-opened the L1 minimap/ZOI work item 566 deferred. 1 commit `94b31bad` (pushed, CI green; LEDGER 567).

PREMISE: 566 deferred ZOI because Live Client :2999 has no coords. This session found a NO-API
coordinate source: League `game.cfg` `[HUD]` MinimapScale=1.62 + FlipMiniMap=0 geometry.
Operator picked ZOI scope "Foundation only".

SHIPPED: `core/league_settings.py` (game.cfg reader) + `core/minimap_geometry.py` (pure calibrated
scale->rect) -> `/api/state.minimap_rect` (design px, mode-gated) -> `web/js/panels/minimap_rect.js`
`w-mmrect` click-through gold-outline box. Calibration LIVE-measured from the operator's minimap
(side=0.2889*H, bottom-right -> design box 1600,761,312,312); green-box overlay confirmed tight fit.
SETTINGS-pinned, NO drag handle (grab zone over the click-critical minimap would eat clicks; rule-9
exception). overlay_layout.js UNTOUCHED. 19 unit + 1 snapshot green; backend verified live. Memory
`reference_minimap_geometry_calibration`.

OWED / DO NEXT: the composited box-on-real-minimap screenshot is the one deferred verify - rc-shell
must be RELAUNCHED to load the new JS module (it does NOT hot-reload new imports like Chrome) and the
game ended (minimap_rect null off a minimap mode). Next game: relaunch rc-shell, capture, nudge the
calibration constant if off. THEN slice 2 (pure-numpy team-color blob detection on the minimap crop
-> dot centroids) + slice 3 (ZOI bubbles + demarcation weighted by per-team strength, fed to coach;
all local/no-API). DON'T redo: foundation/calibration/no-handle.

---

# 2026-06-21 (headless continue 2) - overlay live-verify (IPC round-trip) + declutter sweep

Continued the overlay-polish run. 1 commit `ae09ab27` (pushed, CI green; LEDGER 566).

TASK 1 (owed live-verify): proved the rc-shell widget-layout durable mirror round-trip
over a live SR practice game. Seeded `overlay.widgetLayout` in `<userData>/rc-shell-state.json`
-> relaunch -> the CALL widget RESTORED to the seeded (x,y); cleared -> section-4 default
(== reset). Boot disk-dump confirmed the persist helpers preserve widgetLayout+settings
across the window-bounds save. GOTCHAS (memory `reference_overlay_live_verify_technique`):
Alt+Shift+A/R synthesized via Windows-MCP LEAK to League (open OPTIONS / recall) - they
reach the overlay only on PHYSICAL press (rc-shell is sole registrant, no conflict); seed
the state file with a NO-BOM writer or store.load's JSON.parse rejects the BOM -> silent default.

TASK 2 DEFERRED: L1 minimap-anchored timers/ZOI. The spec marks L1 out-of-scope (l40-42);
Live Client :2999 has NO coords (`reference_liveclient_no_positions`) so ZOI/anchoring can't
be grounded; objective ETAs already ship as w-callouts. Don't build the canvas.

TASK 3 (sweep): overlay impl substantially clean post-565. Shipped the only real items:
palette-token the 2 white literals -> `--ovx-text` (byte-identical, Playwright-checked),
doctrine `w-ovds` + neutral-text rows, ROADMAP spec-path fix (docs/ -> docs/research/).

NEXT (this lane): overlay is doctrine-faithful + clean. The live drag GESTURE + Alt+Shift+R
HOTKEY stay node-test-covered only (physical-press paths, not headless). Minor w-* default
position tuning is the only open polish. DON'T redo: tasks 1/3 above; task-2 minimap is deferred.
