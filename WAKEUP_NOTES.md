# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

Also this session: landed the audit-10 C-01 cron silent-fail stub + audit artifacts (`ef5a3937`),
independently verified + regression-tested (`tests/test_agent6_failure_stub.py`, 5 passed).

DON'T redo: HEXCORE built + the corrected RC self-map captured (route dispatch, coach coupling, DS
reactor topology all ground-truth-verified).

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

---

# 2026-06-21 (headless continue) - overlay doctrine to "pristine": tests + polish + new cues

Continued the overlay doctrine headlessly. 6 commits (pushed, CI green; LEDGER 565):
`cfdc9f22` rewrote the 10 `@_DOCK_RETIRED` snapshot tests to the widget-field model +
aligned overlay.css panel-set presets to the doctrine DELTA model (coach core
persists; build=+w-build+w-ovds-w-threat, threat=+w-threat-w-build-w-choices) + fixed
the `#rn-choices` id-mount specificity leak; also fixed 4 sibling DOM tests red since
slice-1 (b83006c3). `97d781ec` CSS polish (OBJECTIVE 2-line clamp, hex-notch corner
brackets, combat declutter). `72509d5c` rc-shell DURABLE widget-layout mirror
(rc-shell-state.json `overlay.widgetLayout`) + Alt+Shift+R reset (+13 node tests).
`ada17002` NEW cues w-spike (spike_cue.js, ult-level 6/11/16 cross from
liveclient.level) + w-trinket (ward_cue as a movable widget); both moved to am-grid
(transform-trap: a fixed child of a transformed .ovx-widget pane is clipped).
`fc438c24`+`dd9aae68` CALL tiering by data-call-line not nth-child (rows are
CONDITIONAL - the live OBJECTIVE was the 2nd child) + !important over _line() inline
styles -> labels drop, cyan/white/faint tiers + the clamp all hold live.

Live-verified over a real SR game via Windows-MCP across 3 rc-shell relaunches: CALL
clamped + label-free + tiered, WARD UP + ULT cues render as left-edge glyphs.

NEXT (this lane): ROADMAP queue #3 L1 minimap-anchored objective timers; the rc-shell
widget-layout IPC live round-trip (drag -> persist -> relaunch) + Alt+Shift+R are
wired + unit-tested, the live Electron round-trip is OWED. DON'T redo: the panel-set
DELTA model / the data-call-line CALL tiering / the transform-trap fix are settled.
