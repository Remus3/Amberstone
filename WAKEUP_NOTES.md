# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816). Only the last 3 sessions kept here.

---

# 2026-07-09 (deep-audit sweep + next-session plan)

Audit-only session (2 multi-agent workflow passes, 56 agents, adversarial verify per finding).
- 42 verified findings: orphans/scratch, py dead-code, function verification, optimize/refactor,
  open-item verification, web-js orphans, config/test health, full entry-point wiring test.
- Full plan: docs/AUDIT_2026-07-09_NEXT_SESSION_PLAN.md (8 execution lanes).
- WIRING: all 6 entry points INTACT (66 routes, 16 supervisor-proxy paths, 4 tasks, 11 rc-shell).
- OPEN ITEMS: legitimately live-gated; ORCHESTRATION_PLAN fully drained.

Shipped P1 fixes (commit 174c44c9):
- Restored CLAUDE.md from a crash-leftover budget-saver lean-swap stub (full context was only in
  untracked CLAUDE.md.full; a git add -A would have clobbered canonical context). Gitignored /CLAUDE.md.full.
- DAEMON_SLAYER.md engine banner 1.182.0 -> 1.184.0 (test_docs_daemon_slayer_drift was RED on main, now green).

NEXT: run docs/AUDIT_2026-07-09_NEXT_SESSION_PLAN.md on Opus 4.8 max, orchestrated. Lane 0 (CLAUDE.md)
+ Lane 1 (banner) ALREADY DONE - start at Lane 2 (config correctness) via worktree slices.

Do NOT redo: CLAUDE.md restore, DAEMON_SLAYER banner, the wiring/import/route audit (clean), test/launcher
health (clean). Pre-existing working-tree changes (agent6 reports, ddragon ASCII, lean-settings, force_scan)
left for Lane 5 - lean-settings enables bypassPermissions, confirm before committing.

---

# 2026-07-08 (/live-gated-drain Arena + ARAM Mayhem)

Session -- 1 Arena game (Kai'Sa 11-7) + 1 ARAM Mayhem game (Jinx vs Kog'Maw/Sion/Yuumi/Yasuo/Bard):

Arena items (NO code changes -- observation only):
- D6 shadow: force_scan trigger fix (10374d02) NOT loaded (committed after RC boot). RC restarted end-of-session.
- D2: Cherry augment endpoints known-404 on 16.13.1.
- D3: no boot anvil rolled.
- D4/D5/D9: no roll/not evaluable (Goredrinker not picked, mode_modifiers GET identical ON/OFF).

ARAM PASS (4 items):
- C13 enemy_spells: 5 enemies x 2 spells correct
- C12 antiheal POSITIVE: heal_threat detected (Yuumi Heal + Sion sustain)
- C1 build logic: BotRK recommended for Jinx (correct on-hit ADC)
- C14 debounce OFF: coach refreshes coherently (fight_rule = CC threats)

PENDING:
- CSS visual verify: overlay still hidden at session time
- Arena retest after RC restart (b39a9fca + 10374d02 now loaded)

Shadow accrual: arena_coach_shadow.jsonl 463 rows / hz_choice_shadow.jsonl 45307.

NEXT: Arena game to test D6 shadow seeding post-restart, or CSS visual verify via overlay snapshot.

---

# 2026-07-08 (/live-gated-drain ARAM Mayhem Kai'Sa)

Session -- live ARAM drain, 1 Mayhem game (Kai'Sa, enemy Leona/Renata/Kennen/Hwei/Ekko):
- PASS (4 items): C13 enemy_spells data path (5 enemies x 2 spells correct), A/B choices (3 choices with labels/outcomes), reset_item ARAM-aware ("No fountain"), R78 item_extra shadow-only.
- NOT CHECKED (wrong conditions): C12 antiheal, C15/C16 augment, C3/C5/C8 (Kai'Sa not tabled), C11 cc ecosystem, B28-DS level-tick stability, C13 pixel capture (overlay hidden).
- 2 LIVE BUGS FOUND (code patches not yet written):
  1. STALE COACH ARTIFACT: aram_coaching_data.json fight_rule/risk referenced Annie/Morgana from previous game vs current enemies Leona/Renata/Kennen/Hwei/Ekko. Root cause: _base_coach.py _ensure_data() only writes blank on missing file; stale daemon_slayer_picks/scorer/fight_rule survive game restart. Artifact has no game_id for cross-game invalidation.
  2. VOID IMMOLATION LEAK (symptom of #1): daemon_slayer_picks showed 223069 #1 with scorer="hybrid" for Kai'Sa. DS /rank correctly excludes it. The stale hybrid scorer picks were from a previous bruiser game.
- NEXT: fix stale-artifact bug (blank on game_id change), then continue ARAM Mayhem drain.
- DO NOT redo: stale-artifact fix (shipped b39a9fca, verified 2026-07-08 Arena session). D6 force_scan trigger (10374d02 verified working -- 12/12 bumps across 3 Arena games; shadow gap is vision model detection, not trigger).

DO NOT redo: T3 boot fix, map_control dupe, recall_callout/ARAM leak, HZ build-order, enemy-spells CSS.
