# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-21 (interactive) - overlay doctrine: fullscreen movable Hextech widget field + coach JSON-fence fix

Operator: the in-game overlay was "utterly not it" / "so intrusive". Built a NEW
overlay doctrine (`docs/OVERLAY_DOCTRINE.md`): the Electron overlay is the ONE user
surface (Chrome dashboard retired); a FULLSCREEN transparent click-through window
with independently MOVABLE, position-PERSISTENT Hextech widgets (drag the gold-dot
handle -> saves to localStorage). Verified LIVE over a real SR game via Windows-MCP.

Commits (all pushed, CI green): `b83006c3` doctrine + `web/js/lib/overlay_layout.js`
field manager + `overlay.css` rewrite; `df4c8d38` coach `_parse_response` JSON-fence
fallback (live coach went BLANK on a ```json-fenced Haiku reply -> stuck on the
"will render mid-game" scaffold; now reads real calls); `3bd5668f` rc-shell
fullscreen overlay window (`main.js` bounds = work area) + left-edge widget
defaults; `b234ce8d`+`7b2224e5` smaller/see-through/recede + killed the companion
boot-flash (true overlay-only); `aa6f670d` migrated panel snapshot tests off the
retired 460px dock.

NEXT SESSION (continue headlessly): (1) REWRITE the 10 SKIPPED overlay snapshot
tests (`tests/snapshot_panels/test_overlay_view.py`, `@_DOCK_RETIRED`) to the
widget-field model - `.ovx-widget` position:fixed, left-edge defaults, reveal-only
build/threat, panel-set widget visibility, fullscreen window; do NOT re-assert the
460px dock. (2) Overlay polish: clamp the long objective line, eyeball
lead/callouts/choices in the column, the hex-notch + combat-declutter from the
doctrine, rc-shell DISK mirror of the layout + Alt+Shift+R reset. (3) The spawned
coach-parser chip (task_ad0539d3) is SUPERSEDED - the fix landed in `df4c8d38`;
close that session, do not redo.

---

# 2026-06-21 (headless gemini+AHK DIRECTOR REFILL, cycle R12) - DS all-source target-vulnerability mark seam

Item 563 / R12. Engine commit `cad49029` (pushed). DS schema lift: NEW
`agents/daemon_slayer/_target_vulnerability_overrides.py` models all-source
vulnerability MARKS - a debuff the wielder lays on the TARGET that makes it take
+X% damage FROM ALL SOURCES (the all-source half the per-spell self-amp
`_ability_amp_overrides` cannot express). `TargetVulnEntry` + `_CHAMPION_VULN_OVERRIDES`
(champion_id->ability) + `_ITEM_VULN_OVERRIDES` (item-id->item) + `target_vuln_multiplier`
(product of (1+amp), multiplicative, de-duped per item). Default-OFF
`apply_target_vuln` seam on `dps.compute_dps` scales `weighted_dps` + `phase_dps`;
byte-identical OFF.

SEEDED 2 ACTIVE vs 16.12.1 ground truth: Vladimir R Hemoplague 10% (DDragon
effect[2]=[10,10,10]) + Evenshroud 3001/Arena 223001 Coruscation 7%. GROUND-TRUTH
DEVIATION (logged, not silent): the director named Imperial Mandate 4005 at 6%,
but 16.12.1 Coordinated Fire is a current-HP mark-DETONATION (10% current HP bonus
magic damage on ally consume), NOT a +X% all-source amp -> recorded in
`_NONFIT_VULN_CANDIDATES` (documented, NOT seeded) rather than modeled as a
fiction (a WRONG precompute is worse than none).

Tier-2: ENGINE 1.148.0 -> 1.149.0 (quoted-literal pins only, 83 DS files), DS
:8893 restarted -> 1.149.0 live, Share synced 370 / --check green, all SAME
commit. TDD RED-first (23 R12 tests); read-only verifier subagent CONFIRM 7/7; DS
suite 7459 passed / 1 skipped / 1942 subtests; ruff clean.

NEXT (owed -> docs/LIVE_GAME_GATED_SYNC.md): live default-ON flip needs a real
game; broaden the consumer beyond AA-DPS to ability_dps + burst (an all-source
mark amplifies those too - this seam wires the AA-DPS scorer first). The mark
UPTIME model (Vlad R cooldown, Evenshroud's 5s post-immobilize window) is a
live-consumer concern, not baked. Imperial Mandate's detonation could seed a
future ally-detonation / current-HP-burst seam (distinct registry).
