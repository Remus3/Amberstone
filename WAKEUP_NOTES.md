# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09. Only the last 3 sessions kept here.

---

# 2026-07-10 (R101 ARAM+Arena OCR shadow-field wiring - Haiku-to-ZERO Lane E CV, shadow-first - vision-cv; ENGINE-IMPACT NONE)

Gemini-loop DIRECTOR REFILL R101 = Haiku-to-ZERO Lane E CV OCR wiring. Full detail: LEDGER 842. Commit `c5301370` (docs `5a383ea3`).

- Wire the already-built OCR numeric fields into ARAM + Arena coaches SHADOW-FIRST (log OCR-vs-Sonnet, NON-CONSUMING).
  Premise verified: SHADOW_FIELDS + ocr_shadow were doc-only (grep-absent from all .py); the pre-existing *_shadow tests are
  the SEPARATE det-choices coach-block shadow (dashboard._deterministic_coaching), no collision.
- SLICE A core/vision_routing.py + modes/shared_vision.py: read_or_escalate shadow_fields kwarg (shadow fields ALWAYS
  escalate to Sonnet even when OCR validates; Sonnet wins in the returned dict, OCR log-only) + _ocr_shadow_path
  (RC_OCR_SHADOW_PATH override else data/ocr_shadow.jsonl) + _log_ocr_shadow (JSONL {ts,field,ocr_val,sonnet_val,match},
  fail-soft, ensure_ascii); GameVisionReader.SHADOW_FIELDS class attr (default [] = unchanged) threaded into read_tiered.
- SLICE B coaches/aram_coach.py + coaches/arena_coach.py: 8 shadow numerics (ally_1..4_hp 0-100, gold, level 1-18,
  cs 0-1000, kda x/y/z) into SHADOW_FIELDS + TIERED_FIELDS + TIERED_VALIDATORS; ARAM inline _run_vision config LIFTED to
  class-level _ARAM_TIERED_FIELDS/_ARAM_SHADOW_FIELDS/_ARAM_TIERED_VALIDATORS for testability; NON-CONSUMING (SHADOW_FIELDS
  strict-subset of TIERED_FIELDS, no served-dict mutation, PROMPT untouched).
- COST NOTE: ARAM/Arena already escalate to Sonnet most ticks (semantic fields augment_select/fight_state have no OCR
  region), so shadow-forcing adds negligible live cost - mainly the OCR-vs-Sonnet log seeding the Lane E migration dataset.
- 2 parallel worktree slices, TDD RED-first, verifier CONFIRM 10/10 (18 new + 85 regression pass, ruff clean, clean tree
  no ocr_shadow.jsonl pollution, 0 added non-ASCII, exactly 6 files). Integrated: 103 focused + 1150 scoped consumer pass
  + 59 subtests; full-suite partial 79% 0-fail (Tier-1 per R5). RC :8888 restarted pid 1404 -> 6092 (alive/reload_ok).
  ENGINE-IMPACT NONE. done_sentinel --tests 1150 --regressions 0.
- NEXT (live-gated): tools/ocr_shadow_report.py match-rate gate over accrued rows -> validated per-field OCR-only flip
  (needs shadow accrual + operator OK). Don't-redo: ARAM+Arena OCR shadow wiring SHIPPED (do NOT re-pitch wiring the built
  OCR fields into the coaches - done shadow-first); the OCR-vs-Sonnet log lives at data/ocr_shadow.jsonl.

---

# 2026-07-10 (R100 Overlay App F Section-7b competitor lift - RESEARCH-ONLY, ship-premise refuted live - competitor-lift; ENGINE-IMPACT NONE / docs-only)

Gemini-loop DIRECTOR REFILL R100 rotated REFILL PROTOCOL -> #2 (Research + competitor lift) after R99 drained the DS sweep. Full detail: LEDGER 841. Commit `(this commit)`.

- DEEP-DIVE (1 heavyweight research subagent, 6-point checklist) + orchestrator verify-premises: VERDICT ~90% DUPLICATE.
  Overlay App F = live pre-game + in-game scouting companion; its whole chain needs a Riot PRODUCTION spectator-v4 key +
  scraped warehouse (arbitrary-summoner live scout) = CLOSED for RC's personal key (ADR-006; enemies client-hidden until :2999).
- Pre-game card (rank/LP/WR/mastery/mains/W-L streak) BUILT via FU02 (routes_team_context.py:200-239 + riot_api.py:611-670);
  premade/playstyle/self-tilt QUEUED via R81; matchup/spike/objective-timers BUILT/queued via R89/R81/event_callouts.
- VERIFY-PREMISES (decisive): the agent's sole ship candidate - render "unrendered" w_l_streak_7 as dots - REFUTED live;
  team_context.js:126-133 ALREADY renders it as text ("4W 3L"). NO in-run ship (research-only, R85/R94/R98 tradition).
- Artifact docs/COMPETITOR_LIFT_2026-07-10_OVERLAY_APP_F.md; 2 residuals -> BACKLOG FUTURE (F1 manual click-to-track enemy
  summ/ult CD overlay = the one NEW mechanic, MED do-not-build-blind; F2 W-L dots restyle + shrink-guarded tilt hint, LOW,
  fold into R81's snapshot card). ENGINE-IMPACT NONE (docs-only; DS live 1.192.0 healthy; no code/engine/Share/restart).
- LOOP-HEALTH: the live-scouting/overlay competitor CATEGORY is DRAINED (FU02+R81+R89+event_callouts); the R100 dup-check
  compared only vs R89 and missed R81 where ~90% of Overlay App F lives - next competitor pick should target a DIFFERENT category
  or rotate to the meatier DS-sweep / Haiku-to-ZERO lanes. done_sentinel --tests 11277 --regressions 0.
- Don't-redo: Overlay App F + the live-scouting/overlay category is torn down + DRAINED (do NOT re-pitch scouting card/premade/
  tilt/matchup/overlay-timer); the w_l_streak_7 render EXISTS (do NOT re-pitch "render the unrendered streak").

---

# 2026-07-10 (R99 Chainlaced Crushers (3173) magic-shield EHP credit + R98 vision-OCR escalation resolve - ds-engine; ENGINE 1.191.0 -> 1.192.0)

Gemini-loop DIRECTOR REFILL R99 = ESCALATION RESOLVE + DS SWEEP. Full detail: LEDGER 840. Commit `c335eafb`.

- PART 1 (escalation resolve): retired the ROADMAP "VISION-OCR HARDENING" bullet (relocated verbatim to
  docs/ROADMAP_HISTORY.md, marked DONE R94-R98) + moved the grab_native() OCR-crop-path seam to
  docs/LIVE_GAME_GATED_SYNC.md B48 (live-gated Lane E). ROADMAP.md 79731B (budget 81920).
- PART 2 (ds-sweep refute pass): a research subagent + an independent orchestrator scan CONVERGED - only Ambessa +
  Annie carry un-registered shred/pen and NEITHER has a clean numeric Meraki field, so the clean-numeric candidate won:
  Chainlaced Crushers (item 3173) "Noxian Persistence" magic shield was UNCREDITED (bare defensive_only ItemEffect,
  no shield). Meraki 16.13.1: taking magic damage grants a shield absorbing 100 (L1)->200 (L18) +8% bonus HP for 5s (15s CD).
- FIX (R92 Kaenic / R97 Eclipse ItemShield precedent, NO schema lift): shield=ItemShield(MAGICAL, flat=100,
  level_lerp_low=1/high=18/high_value=200, bonus_hp_scaling=0.08, default_off=True) on ITEM_EFFECTS 3173 (SR-only,
  no Arena mirror) + per-shield arming gate (iid=="3173") threaded through ehp._collect_shields/compute_ehp. Zero
  cross-contam vs Kaenic/Eclipse.
- ENGINE 1.191.0->1.192.0 (108 version-pin files). DS :8893 bounced 1.192.0; ds_share_sync 423 files --check green +
  Share/CHANGELOG entry; 6 HZ-B build-order tables re-stamped (STAMP-ONLY, 0 content lines); DAEMON_SLAYER banner 1.192.0/8158.
- TDD RED-first test_chainlaced_shield_r99.py (16 tests, 14 RED pre-fix) + VERIFIER GATE 7/7 CONFIRM (OFF byte-identical:
  magical 2970->3256 ON-only, physical + true unchanged; build-orders stamp-only). GATES: DS 8158/1skip/1943subtests;
  RC 11277 passed (the only 2 fails = the pre-existing LEDGER-828 coach-poll asyncio flake, pass 2/2 isolated, R99 engine
  files carry 0 asyncio refs, 0 R99 regressions); ruff + ASCII clean.
- Live default-ON flip (an EHP consumer passing assume_chainlaced_shield=True) -> LIVE_GATED. Don't-redo: Chainlaced 3173
  Noxian Persistence shield SHIPPED; Ambessa/Annie pen has no clean numeric Meraki field (rejected this pass); the
  vision-OCR recalibration + native-crop wiring stays DONE R94-R98 (relocated to ROADMAP_HISTORY; grab_native OCR-path tail
  = LIVE-GATED Lane E B48, do NOT re-pitch as a headless slice).
