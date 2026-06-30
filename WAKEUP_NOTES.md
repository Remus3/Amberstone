# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) archived. Only the last 3 sessions kept here.

---

# 2026-06-30 (R45 headless cycle 14 - DS schema lift: percent-of-resist LOW-HP DOUBLED tier (Poppy W); ENGINE 1.158.0 -> 1.159.0)

Gemini-directed headless loop cycle 14 (from directive.md; operator-triggered single cycle). DS schema lift. Full detail in LEDGER 699 + ORCHESTRATION_PLAN R45.

- **Premise correction (spec subagent + my independent re-verify of every cite).** The item-268 percent-of-resist mode already credited Poppy W +12% of TOTAL armor/MR + Rell W +15% of BONUS; the directive's "Poppy 10%/20%, Rell 10%" numbers were WRONG vs Meraki 16.13.1. The ONE genuine gap = Poppy "doubled to 24% below 40% max HP" (omitted at `_passive_resist_overrides.py:407`). Rell was already correct - untouched.
- **Seam (`22dca695` feat).** `PassiveResistEntry` gains 3 END-appended fields (`low_hp_pct_armor` / `low_hp_pct_mr` / `low_hp_threshold`, default 0.0 dormant); `resist_grants` gains keyword-only `caster_current_hp_pct=1.0` (END) + an INCREMENTAL low-HP branch inside the percent block (base 12% + incremental 12% = 24% when caster HP < threshold); `compute_ehp` + `compute_hybrid` thread it (forward-only). Poppy seeded 12/12/0.40.
- **DEFAULT-OFF byte-identical on two axes:** `apply_passive_resist=False` short-circuits; `apply_passive_resist=True` at the default full-HP 1.0 leaves the low-HP branch dormant (1.0 not < 0.40) = identical to 1.158.0. No live consumer passes the kwarg.
- **Tier-2.** TDD RED-first `test_passive_resist_low_hp_tier_r45.py` (RED 15-fail -> GREEN). Build agent (main tree) + read-only verifier CONFIRM 6/6 (independent `resist_grants` math 0.24*200=48.0; Rell + unseeded byte-identical; scope clean). ENGINE 1.158.0 -> 1.159.0 (92 files / 105 pins, 0 stray) + DS `:8893` taskkill (PID 11308) / relaunch (live 1.159.0) + Share `--check` green (383 files) + DAEMON_SLAYER.md banner 7621 -> 7640 SAME feat commit. DS 7640 pass / RC 10128 pass.
- **NEXT:** live default-ON flip EXCLUDED (the EHP scorer never reads caster HP) -> `docs/LIVE_GAME_GATED_SYNC.md`. Resume the headless loop.

---

# 2026-06-30 (R44 headless cycle 13 - Section-7b competitor deep-dive: Guide Site Q; docs-only CLEAN no-op)

Gemini-directed headless loop cycle 13 (from directive.md). Competitor-lift research, ENGINE-IMPACT NONE. Full detail in LEDGER 698 + ORCHESTRATION_PLAN R44.

- **Deliverable (`(docs)` commit).** docs/COMPETITOR_LIFT_2026-06-30_GUIDE_SITE_Q.md - Section-7b 6-point teardown of Guide Site Q (the human-authored guide site, NOT a stats aggregator), one heavyweight general-purpose agent. Guide Site Q bot-defended (WebFetch 403 / rag 500; playwright+residential-proxy loaded only the JS-tab-gated static shell -> THREATS/cheat-sheet shapes [INFERRED]); every RC HAVE cited to live code.
- **RECOMMENDED IN-RUN SHIP = NONE (CLEAN no-op).** Independently re-verified the 3 load-bearing cites before accepting "no ship": F2 theorycraft stat-totals ALREADY SHIPPED + stronger in RC (ds-statcheck: routes_ds_statcheck.py:213-228 serves the resolved stat block, ds_statcheck.js:45-56 renders it) -> CLOSED; F1 all-5-enemy danger grid is the best Guide Site Q-distinct idea but RC renders only enemyIds[0] (ds_matchup.js:247-251) and the lift is multi-fetch (up-to-5 /api/ds-matchup calls) not a one-served-field re-render -> fails the HIGH+LOW+one-payload gate -> FUTURE.
- **BACKLOG FUTURE:** F1 lane/fight threat column (MED, pure frontend multi-fetch over the EXISTING per-pair-cached /api/ds-matchup) + F3 skill-order max-priority grid (new compute; core/skill_wpa.py exists but is not served to champ-select). F4/F5/F6 CLOSED. Triage NOW=0 / FUTURE=2 / CLOSED=4.
- **Tier-0 docs-only:** no code/engine/route/JS/DS/Share change, no restart, no UI-audit (no frontend slice). ASCII-hygiene gate green. Vendor name (Guide Site Q) kept in docs only, out of repo source.
- **NEXT:** resume the headless loop. F1 is the standout BACKLOG candidate if the operator later wants a champ-select multi-enemy threat readout.

---

# 2026-06-30 (R42 headless cycle 7 - DS engine fix: Yun Tal conditional-AS unit mismatch; ENGINE 1.156.0 -> 1.157.0)

Gemini-directed headless loop cycle 7 (from directive.md). DS engine math fix. Full detail in LEDGER 696 + ORCHESTRATION_PLAN R42.

- **Bug + fix (`01875f4e` feat).** `compute_dps` folded `cond_as` (a bonus-AS FRACTION from `total_conditional_as`, Yun Tal Flurry ~0.08) directly onto the FINAL rotation AS, but `stats["as"]` is attacks/sec (`base_as * (1 + bonus_pct)`), so the raw add over-credited AS by `1/base_as`. Now scales the fraction by innate base AS before adding (`base_as * cond_as`), same 2.5 hard-cap re-clamp - the IDENTICAL unit bug + fix pattern as R7's `passive_as` fold ~20 lines below. `raw_attack_dps` unchanged (un-folded `eff_as`); explain note repointed to "+X% bonus AS ... folded onto base AS".
- **TDD RED-first** `test_conditional_as_base_fold_r42.py` (2 cases, mirrors R7 `SeamAddsBaseAsScaledFraction`): cond_as has no flag, so the counterfactual is a `mock.patch` of `dps.total_conditional_as`=0 + a Dagger (1042) pure-AS calibration; pins `on.weighted_dps` to the base_as-scaled magnitude, NOT the raw fraction. RED confirmed (63.659 vs 62.721); GREEN after.
- **Dependent fix:** `test_routes_ds_relscore.py` double-rounding tolerance 0.2 -> 0.25 (the corrected Yun Tal DPS shifted item 3032 onto a float-epsilon boundary: route score_pct uses unrounded delta, test recomputes from 1dp-stored -> `71.3 - 71.1 = 0.2000...0284`). NOT a route bug nor a fix bug.
- **Tier-2.** ENGINE 1.156.0 -> 1.157.0 (90 pins, 0 stray) + DS `:8893` taskkill/relaunch (live 1.157.0) + Share `--check` green (381 files) + DAEMON_SLAYER.md banner 7604 -> 7606, all in the feat commit. DS 7606 pass / RC 10128 pass; read-only verifier CONFIRM (7/7, fix base_as-scaled at dps.py:865-866). Built inline (trivial one-file, verifier-gated).
- **NEXT:** resume the headless loop. No live-flip gate needed - this corrects an already-live default-ON path (cond_as fires whenever Yun Tal is in a build), not a default-OFF seam.
