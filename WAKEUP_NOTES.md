# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09 + R100 competitor-lift (2026-07-10, LEDGER 841) archived 2026-07-10. Only the last 3 sessions kept here.

---

# 2026-07-10 (DS Meraki-refute R100: Riftmaker (4633) max-stacks omnivamp EHP-sustain credit; ENGINE 1.193.0 -> 1.194.0)

Manual operator-directed session (AskUserQuestion: operator picked "Omnivamp refute" over Lane A; not playing so live-gated drain was out). Spec-first: grounded scout -> worktree build subagent (TDD RED-first) -> read-only verifier gate -> merger. Full detail: LEDGER 846. Commits `860477fc` (build) + `8b28c7f6` (bump) + docs-sync.

- GAP (R100): Riftmaker Void Corruption grants 10% melee / 6% ranged omnivamp at max stacks (Meraki items_meraki.json:44481), but stats.py has no omnivamp mod so `stats['omnivamp']` was never fed -> the already-built `_vamp_heal_pool` consumer (ehp.py:1610) resolved heal_omnivamp 0.0 on every build; the Riftmaker ItemEffect even said "intentionally not modeled" (stale reason).
- FIX: NEW `_item_omnivamp` registry (mirrors `_item_tenacity`; 4633 + Arena 224633 = (0.10, 0.06)) + default-OFF `assume_max_stacks_omnivamp` seam on compute_ehp injecting `stats['omnivamp']` AFTER blended_ehp. OFF byte-identical; ON credits SUSTAIN axis only (`effective_ehp_with_sustain`/`sustain_ehp_delta`), blended_ehp byte-identical ON vs OFF (verified Morde L13 3600.12 both, heal_omnivamp 44.0; Ezreal ranged 26.4). Deferred conditional siblings 2517/3156/447103.
- CEREMONY: ENGINE 1.193.0->1.194.0 (130 pins), CHANGELOG, DAEMON_SLAYER banner 8196, 6 build-order tables re-stamped (stamp-only), Share sync (426 files, --check green), DS :8893 -> 1.194.0. 17 new tests. DS 8196/0-fail; RC 11298 pass (the 21 reds ALL pre-commit ceremony artifacts: 19 stamp/Share-sync FIXED post-commit + re-verified in a 41-test re-run, 2 = LEDGER-828 coach-poll flake passing 2/2 in isolation).
- NEXT: the DS Meraki-refute rotation is still LIVE - a refill MUST pick a DIFFERENT mechanic (BOTH the ItemShield lifeline family AND now omnivamp are saturated - do NOT re-pick either). OR advance Lane A combat-trigger precompute. OR, if playing, drain live-gated flips (the `assume_max_stacks_omnivamp` default-ON flip is operator/live-gated, LIVE_GAME_GATED_SYNC.md). Lane E OCR flip stays idle until real ARAM/Arena games accrue data/ocr_shadow.jsonl.
- Don't-redo: Riftmaker 4633 omnivamp SHIPPED; `_item_omnivamp` registry exists for any future clean always-on/max-stacks omnivamp item.

---

# 2026-07-10 (Lane A HZ gate de-bias + DS Meraki-refute Seraph's shield - operator-directed manual session, 2 slices; ENGINE 1.192.0 -> 1.193.0)

Operator picked "lane a and ds meraki-refute rotation" (Lane E OCR flip was live-gated IDLE - no game running). Two slices, both spec-first via Plan subagents + TDD RED-first. Full detail: LEDGER 844 (Lane A) + 845 (Meraki). Commits `70a87318` (Lane A) + `6bef45a4` (Meraki).

- LANE A (Tier-1, tools-only, ENGINE-IMPACT NONE): de-biased tools/hz_shadow_report.py - the precompute-vs-Haiku flip-readiness gate (the do-not-flip-blind gate Lane A's coach flip waits on) was read off a MACRO-polluted sample. Objective map-calls (SETUP DRAKE/BARON, END GAME, DEFEND TOWER, CRASH/FREEZE/PUSH wave, CAMP PHASE) leaked as false comparable "hold" (~8.3k via A/B chip fallback) + flooded unclassified_native (20.8k). NEW _NON_LANING_ACTION_MARKERS + a GUARDED branch in _is_non_laning_native_state: drop only when native_action carries a macro marker AND classify_verdict(action) is None, so a compound "SETUP LANE TRADE"->trade is PRESERVED (over-exclusion verified 0). Live: unclassified 20,810->1,045, comparable 8,975->5,608, rate 0.470->0.459 (DOWN = honest; the macro "hold" leaks were INFLATING it; anti-circularity, not tuned to rise). 44/44 tests.
- MERAKI-REFUTE (Tier-2, ENGINE 1.192.0->1.193.0): credited Seraph's Embrace (3040) Lifeline shield to EHP - it carried the Awe AP passive but NO ItemShield, so its 18%-max-mana low-HP shield earned ZERO EHP (its always-on lifeline siblings Sterak/Maw/Shieldbow/Hexdrinker were all credited; 3040 was skipped because ItemShield lacked a mana term). NEW ItemShield.max_mana_scaling + max_mana threaded through resolve_magnitude/_collect_shields/compute_ehp (from resolved.stats['mp']); shield on 3040/223040/323040 via a default-OFF assume_seraphs_shield seam (byte-identical OFF, ZERO cross-contam). Meraki 16.13.1 = 18% max mana ANY absorb (stale "350+max-mana%" note corrected). Armed: Ryze L11 -> 344.6 shield, all 3 EHP axes rise. Ceremony: 129 pins, CHANGELOG, banner 8179, build-orders stamp-only, Share 424 --check green, DS :8893 -> 1.193.0. 21 new tests; DS 8179/0-fail, RC 11317 pass (2 reds = pre-existing LEDGER-828 coach-poll asyncio flake, unrelated). Worktree build subagent + verifier gate + merger re-ran fresh.
- NEXT: the DS Meraki-refute rotation is still LIVE - a refill MUST pick a DIFFERENT mechanic/item (the ItemShield lifeline family is now saturated: Sterak/Maw/Shieldbow/Hexdrinker/Kaenic/Eclipse/Chainlaced/Seraph's all credited - do NOT re-pick a lifeline shield). Lane A's coach FLIP + Meraki's assume_seraphs_shield default-ON flip are BOTH operator/live-gated (do-not-flip-blind; LIVE_GAME_GATED_SYNC.md). Lane E OCR flip stays idle until real ARAM/Arena games accrue data/ocr_shadow.jsonl rows.
- Don't-redo: the HZ macro de-bias is SHIPPED; Seraph's 3040 shield is SHIPPED; ItemShield.max_mana_scaling exists for any future max-mana shield.

---

# 2026-07-10 (R101-C OCR shadow-report flip-readiness gate - tools/ocr_shadow_report.py - Lane E OCR migration step 2; ENGINE-IMPACT NONE)

Manual /done session (not Gemini-loop), executing the R101 (LEDGER 842) NEXT. Full detail: LEDGER 843. Code commit `6e5a0354`.

- tools/ocr_shadow_report.py: READ-ONLY per-field OCR-vs-Sonnet match-rate report over data/ocr_shadow.jsonl
  (the {ts,field,ocr_val,sonnet_val,match} log R101 wired). Two-part flip gate mirrors aram_shadow_report: a field
  is flip-eligible only at >=MIN_SAMPLES rows AND >=MATCH_GATE match (defaults 50 / 0.90, CLI --min-samples/--gate).
  0.90 > aram's 0.70 because OCR-only replaces Sonnet as the numeric source of truth. Fail-soft (missing/empty/
  malformed log -> zeroed, never raises); FLAGS readiness only - no flip authorization.
- KNOWN_FIELDS = the 8 coach shadow numerics (ally_1..4_hp, gold, level, cs, kda), seeded so a zero-row field still
  renders; present_rate + accuracy_when_present sit beside match_rate so a fail reads miss-vs-mismatch.
- TDD RED-first (ImportError) -> GREEN 19 tests (tests/test_ocr_shadow_report.py). Tier-1 (one read-only tool, no
  engine/schema/DS): py_compile + full ruff check . green + hygiene guards + the module slice (32 passed), per R5.
  Single-thread inline (2 files, under R9); no worktree/subagent. RC NOT restarted (a tool, not RC-loaded); DS
  untouched (1.192.0). Committed 6e5a0354; docs-sync commit follows.
- NEXT (live-gated): run the report once data/ocr_shadow.jsonl accrues rows from a live ARAM/Arena game; when a
  field clears the gate + operator OKs, flip that field OCR-only (~1-line coach-side, NOT re-wiring, NOT blind).
  Don't-redo: the report + its gate are SHIPPED (do NOT rebuild); the log path/schema are FIXED by R101.

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
