# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-19 (gemini-loop R7-regress-fix cycle) - passive_as unit-mismatch fix (LEDGER 518)

Gemini AUDITOR flagged R7 (item 517) REGRESS. `agents/daemon_slayer/dps.py` per-stack self-AS
seam added `passive_as_bonus()`'s bonus-AS FRACTION (Irelia full L18 = 1.0; Jax L11 ~0.75)
directly to `stats_for_rotation["as"]` = FINAL attacks/sec (engine.py:195 `base_as*(1+bonus)`,
2.5-capped) -> over-credited AS by 1/base_as (~1.5x). Commit `ee90195d`; Tier-2, NO ENGINE bump
(stays 1.147.0), 0 frozen, Share re-synced same commit.

- FIX: fold the fraction onto the champ INNATE base AS - `+ innate_base_as * passive_as`
  (`champ["stats"]["attackspeed"]`, champ = snapshot.champion(...) dps.py:695 in scope); 2.5
  re-clamp kept; seam note reworded to "+X% bonus AS ... folded onto base AS".
- TDD RED-first: NEW `SeamAddsBaseAsScaledFraction` pins by colinearity (weighted_dps affine in
  rotation AS; off / pure-AS-Dagger(1042)-cal / on colinear; ON gain == c1*(base_as*pa) NOT
  c1*pa). RED 135.24 vs predicted_correct 118.75 -> GREEN (20/20). R7's 19 tests only asserted
  direction (on>off), true under both formulas -> missed the magnitude bug.
- NO bump: seam DEFAULT-OFF + operator-gated (not live), buggy math never hit a live consumer.
  SIBLING (FUTURE, not touched): Yun Tal cond_as (0.08, dps.py:849, batch 54) is the same unit
  class, pre-existing+tiny+separately pinned -> logged ORCH Findings.
- VERIFY: R7 20; DS-dir 7414 / 1 skip / 1942 subs; RC 8644 / 2 skip / 110 subs (lone fail = the
  expected Share-drift guard -> ds_share_sync re-mirror GREEN, --check in sync, 366 files);
  verifier CONFIRM all 6 claims (determinism teardown ERROR = live vision daemon mutating
  data/vision_state.json mid-run, environmental); ruff+py_compile clean; Share staged same commit.
- [[feedback_verify_before_declare_broken]] / [[reference_share_mirror_tools_drift]] /
  [[reference_ds_bump_run_tests_dir]] / [[feedback_ds_commit_share_test_mirror]].

---

# 2026-06-19 (gemini-loop R7 cycle) - DS per-stack self-Attack-Speed passive seam (LEDGER 517)

Gemini DIRECTOR refill R7 (ops/loop/control/directive.md, REFILL PROTOCOL): DS schema lift -
per-stack self-Attack-Speed passives. Commit `7c22e3bb`; Tier-2, ENGINE 1.146.0 -> 1.147.0,
DS :8893 restarted -> 1.147.0 live, Share re-synced SAME commit (--check green, 366 files), 0 frozen.

- GAP (verify-before-build): the stat pipeline has no signal for champion INNATE per-stack bonus
  ATTACK SPEED, so compute_dps under-credited a champ at full passive stacks. The only existing
  AS-fold lane is the item-effect total_conditional_as (Yun Tal) -> R7 is the champion-innate
  ATTACK-SPEED sibling registry, mirroring the cond_as fold exactly (same 2.5 hard-cap re-clamp).
- NEW agents/daemon_slayer/_passive_as_overrides.py (PassiveAsEntry: per-stack bonus-AS FRACTION
  low/high by level + max_stacks + ap_per_stack_per_100; _lerp_by_level 1->18). compute_dps gains
  default-OFF assume_passive_as_stacks; ON folds passive_as_bonus(cid, level, ap, fraction=1.0) into
  stats_for_rotation["as"]. AP-scaled passives read the resolved post-amp ap; raw_attack_dps left at
  the no-conditional baseline (matches cond_as).
- SEEDED 4 (champion_abilities.json 16.12.1, Meraki 25.15 effects_descriptions): Irelia Ionian Fervor
  10%:25% by lvl/stack max 4; Jax Relentless Assault 5%:12.5% by lvl/stack max 8; Ezreal Rising Spell
  Force 10% flat/stack max 5; Volibear The Relentless Storm (5% + 4% per 100 AP)/stack max 5 (AP-scaled).
  per_stack*max_stacks == documented max (self-clamping). on-hit/Lightning-Claws/Unsteady NOT the AS buff.
- TDD: test_passive_as_overrides_r7.py RED-first (seam absent) -> GREEN (19/19). ENGINE bump =
  quoted-literal pins only (80 test .py + __init__.py, 89 subs; CHANGELOG prose untouched).
- VERIFY: DS-dir 7413 passed / 1 skip / 1942 subtests; RC 8645 passed / 2 skip / 110 subtests; exit 0,
  ZERO mid-suite transients (sequenced ds_share_sync + DS restart BEFORE the RC suite, vs R3/R5). DS
  /health 1.147.0; ruff clean; Share --check green. Inline sole orchestrator (R9, one coupled engine
  change). Live flip operator-gated -> docs/LIVE_GAME_GATED_SYNC.md (R7 row; EXCLUDED L156 already
  names "per-stack assumed_stacks"). [[feedback_verify_before_declare_broken]] /
  [[feedback_engine_bump_quoted_literal_only]] / [[reference_ds_bump_run_tests_dir]] /
  [[reference_ds_server_not_supervisor_watched]].

---

# 2026-06-19 (gemini-loop R6 cycle) - dashboard-panel UI audit + dead-CSS removal (LEDGER 516)

Gemini DIRECTOR refill R6 (ops/loop/control/directive.md, REFILL PROTOCOL): Section-3b 5-phase UI
audit of the un-audited cooldown_watch + cc_conditional_pressure dashboard panels (JS+CSS) vs
UI_SCALE_SPEC_V2 v2.1. Commit `139ef216`; Tier-1 CSS+test only, NO ENGINE bump / 0 frozen / no DS
restart / no Share mirror / ADR-008 asset-hash auto-reload (no RC restart).

- SCOPE (verify-before-build): the directive's "tokenize sub-floor hardcoded font-sizes" = a verified
  NO-OP. The 2 JS files are pure ESM (no style decls); both CSS files were ALREADY fully tokenized
  (every font-size = var(--fs-*), all >= --fs-xs 16px; grep font-size:\d+px = 0 hits). Did NOT
  fabricate edits to manufacture a diff.
- MUST-FIX (genuine dead CSS): cc_conditional_pressure.css carried .cc-conditional-pressure-ratio +
  -ratio-value (3 rules / ~24 lines) ORPHANED since item 213 (2026-05-28) swapped the ratio render
  for the verdict line. Grep across web/ + tests/ = ZERO consumers -> removed. Zero pixel delta.
  cooldown_watch CSS classes all match JS-emitted (no dead CSS) -> guard test only.
- 5-phase: STRUCTURE/TYPOGRAPHY/ASCII/HIERARCHY PASS; HIT-TARGETS N/A (display-only chips).
- TDD red->green: test_no_orphan_ratio_selectors RED (1 fail) -> removed -> GREEN (44 passed); +2
  test_font_sizes_are_tokenized characterization guards (both panel test files) lock token compliance.
- VERIFY: verifier subagent CONFIRM all 4 claims (selector gone, 0 bare-px, 44 passed fresh, 0
  non-ASCII); full RC suite tests/ --ignore=tests/daemon_slayer = 8645 passed / 2 skip / exit 0
  (8642 + 3 new); ruff clean. Inline sole orchestrator (R9). [[feedback_phase3_fixture_ritual]] /
  [[feedback_verify_before_declare_broken]] / [[feedback_audit_proposals_are_intent]].
- NEW residuals (FUTURE): overlay.css 12/13px sub-floor (Electron, Lane D); next.css:10 21px
  hardcoded (above floor); cc-conditional-pressure-verdict actionable sentence at --fs-xs 16px
  (clears floor; tier-bump is a subjective readability call - not shipped blind).
