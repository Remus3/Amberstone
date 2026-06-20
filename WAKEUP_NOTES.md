# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-19 (gemini-loop R5 cycle) - DS missing-HP heal-amplification seam (LEDGER 515)

Gemini DIRECTOR refill R5 (ops/loop/control/directive.md, REFILL PROTOCOL): DS schema lift -
passive_heal missing_hp_heal_amp. Commit `dc2eb0c3`, CI pending push; Tier-2, ENGINE 1.145.0 ->
1.146.0, DS :8893 restarted -> 1.146.0 live, Share re-synced SAME commit (--check green, 364 files),
0 frozen.

- SCOPE (verify-before-build): `ability_hps.py` ALREADY resolves missing-HP heal MAGNITUDE
  (`resolve_target_relative` v2 path). R5 = the SIBLING heal-AMP MULTIPLIER class - the one
  `_passive_heal_overrides.py:27` (item-253 header) explicitly EXCLUDED from the magnitude registry.
  Mirrors the `assume_ability_amp` seam (default-OFF bool, byte-identical off).
- IMPL (single coupled file, byte-identical at default): NEW `_MISSING_HP_HEAL_AMP[champ][spell] =
  max_bonus` registry + `_missing_hp_heal_amp_factor` (co-located w/ `_AOE_HEAL_TARGETS`);
  `compute_ability_hps` gains `assume_missing_hp_heal_amp` -> `heal_per_cast *= 1 + max_bonus *
  caster_missing_hp_pct` (HEAL-only, reuses the existing missing-HP param, full-HP = identity).
- SEEDED 4 (champion_abilities.json 16.12.1 effects_descriptions, file:line grep): Master Yi W
  Meditate (35042) / Lissandra R Frozen Tomb (31869) / Sylas W Kingslayer (56205) 0%:100% -> 1.0;
  Briar P Crimson Curse (7903) 0%:40% -> 0.40 (sub-term omitted, lower bound). Nidalee E probed
  (39896), NO amp text -> NOT seeded (3/4 directive examples verified, 1 corrected, +Briar bonus).
- TDD test_missing_hp_heal_amp_item515.py RED-first (ImportError) -> GREEN (~17 tests). VERIFY:
  DS 7394 / RC 8642 green (8 mid-suite restart/sync-window transients re-verified fresh = 40 passed);
  ruff + Share --check clean; DS /health 1.146.0. Inline sole orchestrator (R9; verifier skip R7 -
  fresh dual suite + live :8893 + file:line grep = the verify). Live flip -> LIVE_GAME_GATED_SYNC.md.
  [[feedback_engine_bump_quoted_literal_only]] / [[reference_ds_bump_run_tests_dir]].

---

# 2026-06-19 (gemini-loop R4 cycle) - core coaching panels typography-floor UI audit (LEDGER 514)

Gemini DIRECTOR refill R4 (ops/loop/control/directive.md, REFILL PROTOCOL): Section-3b 5-phase UI
audit of three un-audited core coaching panels. Commit `9e56d23d`, CI pending push; Tier-1 CSS-only,
0 ENGINE / 0 frozen / no DS / no Share / ADR-008 asset-hash auto-reload (no RC restart).

- SCOPE: typography floor only (colors already tokenized). Tokenized 14 in-scope sub-floor (<16px)
  font-sizes -> --fs-* (team_context 7x + .tc-slot radius; coach_choices .rc-src + stale fallbacks;
  item_build ds-chip/em + build-label + item-cost + ib-builds-status + cs-build-label + build-value).
  2 documented operator-exceptions kept sub-floor w/ inline rationale (.item-name 14px tile-clamp;
  .cs-build-runes 10px dense column). EXCLUDED the cross-panel .kv/#nx-wave/.minimap-grid blocks in
  item_build.css (already-audited Right Now/Next/Active-Match, C2).
- TDD: tests/test_core_panels_typography_v21_floor.py FIRST (5 fail/2 pass RED) -> fix -> 7/7 GREEN
  (mirrors test_csv_typography_v21_floor.py). Independent 5-phase audit subagent = SHIP, 0 MUST-FIX.
- VISUAL + DISCOVERY: Claude_Preview ATTACHES to https://localhost:8888/ (prior cycles' "cannot
  attach :8888" = the legion-rc hostname cert mismatch; localhost works). Computed-style probe on
  the LIVE stylesheet: every in-scope selector resolves >=16px, the 2 exceptions hold, .rc-chip 42px
  -> confirms the ADR-008 reload served the edits. [[reference_claude_preview_live_8888]]
- VERIFY: RC suite 8642 passed/2 skip/0 fail (incl hygiene + bundle-parity guards); DS N/A (CSS,
  Tier-1); ruff clean. Inline sole orchestrator (R9; verifier = audit subagent + live probe + fresh
  suite). [[feedback_phase3_fixture_ritual]] / [[feedback_execution_efficiency_rules]].
