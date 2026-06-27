# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-26 (L4 Phase-D capability-gap consumer SLICE 3 - item 633, `62fe235a`)

Operator picked "surface it" over adding more axes. Promoted the item-632 shadow-log to a user-visible champ-select chip behind its own default-OFF flip flag.

- **Backend.** `dashboard/routes_state.py` `_serve_ds_preview_post`: NEW `capability_gap` field on the `/api/ds-preview` envelope, gated on `RC_CAPGAP_SURFACE` (default OFF). Resolves enemy comp via the existing `_resolve_enemy_champions`, runs `build_capability_gap`, populates only when `applies` else null; never raises. Built RED-first by a worktree subagent, merged + re-verified on main.
- **Frontend.** `web/js/panels/champ_select.js` `_csvRenderCapabilityGap` (render tick, after cooldown-watch) + new `web/css/panels/capability_gap.css`: amber GAP badge + axis label (Anti-tank / Anti-heal / Anti-poke) + verdict; self-contained fetch/cache off the same route; hidden until a gap fires (inert until flag flipped). `ui_mock` short-circuit seeds a grounded `capability_gap` block in `web/data/ui_mock/champ_select_sr.json` (real Jinx-vs-comp verdict) for the visual audit.
- **Verified.** `test_ds_preview_capgap.py` 11 passed (with sibling route test); 74-test focused sweep; ruff + `node --check` clean; 0 non-ASCII; live preview (`?ui_mock=1#champ-select`) renders the chip, styles resolve from tokens, no console errors; 5-phase UI-audit clean (zero MUST-FIX); RC restarted (pid 16072), live `/api/ds-preview` curl confirms field serves null with flag OFF (default-OFF deploy proven). No ENGINE bump, no Share (DS untouched).
- **To activate live:** set `RC_CAPGAP_SURFACE=1` in the RC env + restart -> chip lights up in real champ-select.

NEXT (L4 tail): the two remaining axes (zone-control `controls_terrain`/`zonecontrol_score`, objective-damage `pressures_structures`/`objdamage_score` - both scorers confirmed to expose usable fields) + an active-match twin of the chip + live SR-game validation with the flag ON. STILL UNVERIFIED: no live SR-game validation of 627-633 (all client mode). Pre-existing anomaly (not mine): RC-LiveFlipWatcher Disabled/result=1.

---

# 2026-06-26 (L4 Phase-D capability-gap consumer SLICE 2 - item 632, `de4c40e4`)

Operator picked "both directions" this session: extend the capgap registry AND wire the live shadow-log.

- **Extend - sustain axis.** `core/ds_capability_gap.py` `_detect_sustain_gap` keys on `SustainResult.total_sustain_score` vs a live-calibrated `SUSTAIN_HIGH_SCORE=1.5` cut (probed `compute_sustain`: Warwick 11.7 / Aatrox 7.0 / Swain 3.3 / Fiddle 2.9 / Vlad 1.6 vs DrMundo 0.6 down). Fires when >=2 heavy-sustain enemies AND I do not out-sustain in kind -> anti-heal/Grievous. `_AXIS_PRIORITY` now (anti_tank, sustain, poke).
- **Wire - live shadow-log.** `dashboard/routes_state.py` `_capgap_shadow_log` runs at the end of `_serve_state`, gated on `RC_CAPGAP_SHADOW` (default OFF). Resolves my champ + enemy comp from the liveclient snapshot, logs the top deficit (throttled 30s, skips stale >=8s, never raises). NO served-field change.
- **Verified:** RED-first both slices. `test_ds_capability_gap.py` 20/20 + new `test_capability_gap_shadow.py` 9/9; ruff clean; regression sweep 1365 passed. No ENGINE bump, no Share (DS untouched), no RC restart (flag OFF -> live behavior unchanged).
- Commit-msg gotcha: first push mangled the subject (PowerShell `@'...'@` heredoc used in the Bash tool is literal) - fixed via amend + `--force-with-lease`. Use a `-F msgfile` for multi-line Bash commit messages.

NEXT (L4 tail): more axes (zone-control / objective-damage) + promote the shadow-log to a user-visible champ-select/active-match surface once telemetry validates the axes. Other report bets: L9/L10 live championStats + stat-shard ingestion (M), E1 TFT deterministic twin (L). STILL UNVERIFIED: no live SR-game validation of 627-632 (all client mode). Pre-existing anomaly (not mine): RC-LiveFlipWatcher Disabled/result=1.

---

# 2026-06-26 (L4 Phase-D capability-gap synthesizer - item 631, `d52d6152`, CI green)

First bet from the item-626 research report after the objective-state pack. Operator picked L4,
then the multi-axis-synthesizer slice. Grounding found the report's "first slice = anti-tank, it
is unconsumed" was WRONG: `core.ds_antitank_hint.build_antitank_hint` already exists + is consumed
(A3 axis in build_order_variants), and `routes_ds_profile.py` already does a single-champion radar.
So slice 1 = the genuinely-unbuilt SYNTHESIS.

- NEW `core/ds_capability_gap.py` `build_capability_gap(my_champ, enemies, mode)` - detector-registry
  consumer that reads existing DS scorers vs a live enemy comp, emits the single highest-severity
  capability DEFICIT. v1 detectors: **anti_tank** (delegates to build_antitank_hint) + **poke** (keys
  on `ThreatRangeResult.is_artillery`). Ranks by enemy-demand count, tie-break anti_tank>poke. Adding
  an axis = append a detector.
- Pure read-only, never raises, **default-inert** (NOT yet wired into a served path - awaits a live
  coach surface + shadow-log per flip discipline). No ENGINE bump, no Share mirror. Tier-1.
- RED-first; fixtures grounded vs live scorer output. GREEN: 17/17 new tests, ruff clean, sibling
  ds_antitank_hint 13/13.

NEXT: more detectors (sustain/zone/objdamage) + wire into a live coach surface behind a shadow flag.
Other untouched report bets: L9/L10 live championStats + stat-shard ingestion, E1 TFT det twin.
STILL UNVERIFIED (carried): no live SR-game validation of EITHER the 627-630 objective rows OR this
consumer - all client mode. Do NOT re-derive anti-tank or the ds-profile radar (both already exist).
