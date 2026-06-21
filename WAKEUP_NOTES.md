# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-21 (interactive, continue) - overlay CALL focal hierarchy + ASCII arrow MUST-FIX

Continued item 558's overlay-audit NEXT queue. Two commits (pushed): `a4d6e6ba`
overlay.css sec 3b - the CALL pane now out-weights peers (4px `--signal-info`
indigo rail + tinted `rgba(28,30,48,0.93)` backing + accent head; overlay-scoped,
higher-specificity than the sec-3 base) so the eye lands on the time-critical
RIGHT NOW/ACTION first in the ~1.5s glance. `806c77dd` ascii-clean arrows - the
audit's ASCII phase caught coach.action "CRASH BOT -> SETUP DRAKE" with a real
U+2192; item 558's `_ascii_clean` missed arrows. Extended `_ASCII_PUNCT`
(arrow/symbol family) + a NFKD+ascii-ignore fallback so NO codepoint>127 can
reach the HUD; +11 TDD cases (chr(0xNNNN) inputs so the test stays 7-bit ASCII).

Tier-1 (overlay CSS + one dashboard module + test), no engine/DS/Share. RC
restarted (pid 8904, reload_ok, game re-detected mode=sr). LIVE-VERIFIED on the
legion-rc origin (live SR bot-practice game): CALL hierarchy renders, live
/api/state coach ASCII-CLEAN (action 'SETUP DRAKE'), WS SecurityError gone (item
558 fix holds; 1 console error = favicon 404). Read-only 5-phase fixture audit =
ship-ready, no MUST-FIX. This also CLOSED item 558's owed live-render verify.

NEXT (item-558 queue tail): L1 minimap-anchored objective timers (needs an
overlay minimap canvas), L3 live spike cue (HIGH, computed). Background chip
spawned: FIGHT MODEL pane (`#am-pane-ovds`) clips in the default subset - gate it
to the build panelset (pre-existing, audit-found, NOT this slice).

---

# 2026-06-21 (interactive) - overlay live-render TRUE root-cause (WS mixed-content) + ds-503 + ASCII coach

CORRECTS the prior entry. The "overlay dead/placeholder in-game" bug was NOT
backgroundThrottling (red herring; `8c7319f5` kept as harmless hardening). TRUE cause:
the overlay loads HTTPS at legion-rc:8888 and main.js opened an INSECURE
ws://legion-rc:8891 -> browsers BLOCK mixed-content ws:// for non-localhost hosts ->
SecurityError at boot aborted init -> placeholders. It hid for months because the
"test in a normal browser" step used 127.0.0.1, which is EXEMPT from the block and
masked it. RULE: test the overlay on the legion-rc origin, NOT 127.0.0.1.

Commits (all pushed): `91cf480a` overlay WS fix + SR-coach PRACTICETOOL re-enable +
rc-shell occlusion switches ; `44174fb1` ds-preview/ds-knobs graceful build_complete 200
(was 503 spam on a full 6-item build) ; `d2170d4d` ASCII-clean coach text in build_state
(Haiku em-dash reached the HUD) ; `0a70a547` route WS to ws://127.0.0.1:8891 (kills
SSL-handshake spam; :8891 has no TLS, 127.0.0.1 is exempt + co-located). Updated memory
reference_electron_overlay_throttling. rc-shell bounced to a fresh instance (pid 4996).

NEXT (operator AFK in a practice match for this): UI passes from the live UI/UX audit -
pop-out/hierarchy SHOULD-FIX (CALL action must out-weight peers), L1 minimap-anchored
objective timers, L3 live spike cue (HIGH, computed, gated out of overlay.css). Verify the
in-game overlay now renders live coach. Tail: :8891 no TLS (push via ws://127.0.0.1, fine on 1-PC).

---

# 2026-06-21 weekly-hygiene (scheduled, unattended)

## What was done

**Section 1 (WAKEUP trim):** No relocation. WAKEUP_NOTES had exactly 3 sessions (all 2026-06-21) - within the 2-3 keep window.

**Section 2 (CLAUDE.md overhead):** No changes. 25KB (budget 60KB), no stray ledger entries.

**Section 3 (memory updates applied - HIGH confidence, retired infra):**
- `reference_gamepc_agents.md`: marked RETIRED (ADR-011 2026-05-29); agents now on Legion.
- `project_gamepc_mcp_boot_gap.md`: marked RETIRED (ADR-011 2026-05-29).
- `reference_gamepc_http_server_redeploy.md`: marked RETIRED (ADR-011 2026-05-29).
- MEMORY.md index: 3 game-pc lines annotated "RETIRED ADR-011"; `project_legion_migration_planned` line corrected from "PENDING" to "DONE ADR-011 item 215 2026-05-29".

## Judgment calls flagged (your call)

**Memory suspects (MEDIUM confidence - verify before editing):**
1. `reference_topology.md`: still describes Game-PC as the dashboard surface (2 monitors + Chrome). Stale - League + dashboard moved to Legion ADR-011.
2. `user_operator_profile.md`: "Game-PC (runs League; dashboard shown in Chrome on its secondary monitor)". Same staleness.
3. `reference_gamepc_monitor_index_volatility.md`: entirely about Game-PC capture_monitor indices. Retired fleet member, no active use.
4. `feedback_delegate_to_gamepc_claude.md`: guides delegating tasks to Game-PC Claude. Game-PC retired from pipeline.
5. `feedback_caveman_default_fleet.md`: "all three machines" / "Peer and Game-PC received bridge tasks". Now a 2-machine fleet (Legion + Peer).
6. `reference_bridge_dispatch_target_paths.md`: describes 3 dispatch paths including target=gamepc. Game-PC retired.
7. `feedback_gamepc_league_fullscreen_lockup.md`: about Game-PC exclusive-fullscreen + virtual display lockup. Retired.
8. CLAUDE.md `docs/DAEMON_SLAYER.md` blurb: cites "ENGINE_VERSION 1.101.0" - live version is 1.149.0. Operator-curated prose; update via normal Settled/DS-batch workflow, not hygiene pass.

**Anomaly: RC-BridgeDaemon + RC-BridgeWatcher both state=Ready, last_result=1 (since 6/20 4:30 PM).**

Root cause verified from `bridge_watcher_2026-06-20.log`:
- Watchdog forced exit at 10:02 AM on 6/20 (designed - stall > 120s threshold after a push-notif 20s timeout).
- Restarted at 16:30 PM; ran < 1s (3 log lines, all at 16:30:30), then silently exited code 1. No error line logged.
- No `bridge_watcher_2026-06-21.log` exists - both daemons offline since.
- Impact: Legion cannot auto-process incoming Peer tasks. Queue is 0, no data loss.

Recommendation: `Start-ScheduledTask -TaskName RC-BridgeDaemon; Start-ScheduledTask -TaskName RC-BridgeWatcher`

Also worth: investigate why the watcher silently exits code 1 after a successful first poll at restart. The 16:30 RC restart (9s before watcher start) may have left a stale lock or triggered a fast watchdog re-fire. The code-1 path that bypasses logging is a gap to fix.

## Second pass (RC-WeeklyHygiene scheduled, ~05:00 CDT)

Bridge daemons recovered automatically on RC reboot at 04:58 CDT - both Running, queue=0. Memory RETIRED annotations from first pass verified applied. No new relocation, no new flags. data/spell_prefs.json has an unstaged modification not authored by hygiene pass - left unstaged per scope rules.
