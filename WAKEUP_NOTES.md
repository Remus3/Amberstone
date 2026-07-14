# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09 + R100 competitor-lift (2026-07-10, LEDGER 841) archived 2026-07-10 + R101-C OCR shadow-report (2026-07-10, LEDGER 843) archived 2026-07-10 (R102 wrap) + Lane-A-debias+Seraph's-shield (2026-07-10, LEDGER 844-845) archived 2026-07-10 (R103 wrap) + R102 GA item-revive (2026-07-10, LEDGER 847) archived 2026-07-11 (R105 wrap) + R103 item-stasis (2026-07-10, LEDGER 848) archived 2026-07-11 (R106 wrap) + R106 item-resist-grant (2026-07-11, LEDGER 851) archived 2026-07-11 (Lane-A-report wrap) + R107 Warmog-Vitality HP-amp (2026-07-11, LEDGER 852) archived 2026-07-11 (R108 wrap) + HEXCORE offline viewer (2026-07-11) archived 2026-07-11 (R109 wrap) + overlay-HUD-flip+minimap-perf (2026-07-11, LEDGER 859) archived 2026-07-11 (item-1 Phase 4 wrap) + overlay-overhaul (2026-07-11, LEDGER 860) archived 2026-07-11 (item-1 Phase 5 wrap) + item-1 Phase 2+3 (2026-07-11, LEDGER 861) archived 2026-07-12 (item-1 Phase 6 wrap). Only the last 3 sessions kept here.

---

# OVERNIGHT AUTONOMOUS DIRECTIVE (operator, 2026-07-13, going to sleep) - Gemini-headless loop

Operator granted a full autonomous overnight run (AHK + Gemini headless) with FROZEN-FILE ACCESS ALLOWED + GRANTED. Self-`/done` and continue between phases. Priority chain:

1. **Implement `docs/specs/2026-07-13-ds-crit-burst-fix.md`** (the coordinated crit-burst fix: L1 coherence-respects-burst -> L2 arm the execute [Tier-2 ENGINE bump + Share + :8893] -> L3 fight_length allow-map for crit ADCs -> L4 squishy-target scenario; L5 fed-conditional + L6 stale-catalog are follow-ups). TDD, per-champion, LIVE-path fidelity (the Step-1a lesson: validate against the live ds-preview path, not an in-process fixed cell). Root cause: the sustained-DPS scorer hands crit ADCs an on-hit build; crit's value is short-TTK BURST vs SQUISHY carries when FED. Context: LEDGER 874 (Step 1a shipped) + `docs/specs/2026-07-13-ds-build-coherence-refactor.md` + memory `project_ds_build_reco_optimal_not_winrate`.
2. **Then the other DS build-reco refactor slices** (from `docs/specs/2026-07-13-ds-build-coherence-refactor.md`): Step 0 seam prunes (DSP11 coach revert is a GATED live-behavior change - coach-picks diff first), Step 2 wire the dormant `situational.py` counter-build into the overlay, Step 3 ally synergy + NL reasoning. Plus DS seams / testing / upgrades broadly.
3. **If still uninterrupted:** per-champion META BUILD online research (aggregator B/aggregator D/aggregator A via web tools) - compare each champ's meta build to what the engine offers, analyze for divergence/issues; if found, continue fixing headless.

Each phase: verifier-gate before "done" (independent re-probe, NOT subagent counts), commit + push, LEDGER entry, live-verify where possible. Do NOT flip gated live-behavior (DSP11 coach revert, any coach flip) without the eyeball diff. QA baseline: `ops/audit/DS_BUILD_RECO_OVERLAY_QA.md`.

---

# 2026-07-14 (R126 gemini-loop cycle 24 - Lane E CV substrate: OCR region-map atlas + LiveClient/CV fusion; ENGINE-IMPACT NONE; LEDGER 900)

Haiku-to-ZERO rotation (R125 4th competitor-lift DRAIN -> off competitor sweeps). Built the Lane E
fusion substrate per docs/NO_LLM_PRECOMPUTE_PLAN.md, the region-map companion to R121's icon atlas.
2 disjoint build agents + independent ground-truth verifier gate (sole merger). Slice A
core/vision_region_atlas.py + data/daemon_slayer/vision_region_atlas.json: versioned 25-region atlas
(21 calibrated HUD rects VERBATIM from vision_regions.json api_gap=false + 4 API-gap slots -
minimap_fog dynamic via core.minimap_geometry.compute_minimap_rect, augment_card_1/2/3 owed) +
fail-soft build_atlas/write_atlas/scale_region/api_gap_fields. Slice B core/vision_fusion.py:
fuse_reads merges LC-exact-1.0 vs CV-heuristic-0.7, api_gap CV-authoritative, 0.6 stale-override,
never-raises (district_fusion precedent), fuse_with_atlas lazy import. BUILD + PERSIST ONLY, both
DORMANT (no coach flip, no live wire - a wrong precompute is worse than a Haiku call). Premise-checked
before build: :2999 (dashboard/_liveclient.py) already emits enemy_item_ids/players, so the TRUE
structural gaps are augments (no capture-free API) + fog positions (no coords). GATE: Slice A 19 +
Slice B 14 fresh; RC 11672 passed (the 2 test_coach_poll_offload_hot03 = pre-existing LEDGER-828
async flake, pass 2/2 isolated, 0 R126 regressions); DS 8461 passed / 1948 subtests
(baseline-identical, 0 DS impact); ruff clean; 0 non-ASCII; ds_share_sync --check green 456 files;
CI green. feat `beac83cf` + docs(loop) `29a23da4` -> origin/main. NEXT (live-gated): calibrate the
augment_card_*/minimap_fog rects against a real Arena/ARAM frame + wire fuse_reads into the ARAM/Arena
coaches shadow-first (extends the R101 data/ocr_shadow.jsonl lane), then a validated OCR-only flip.
Competitor-lift/overlay/companion/stat-site family DRAINED 4x (R100/R112/R120/R125) - retired as a
director rotation target.

---

# 2026-07-14 (R119 gemini-loop cycle 17 - DS-sweep Navori Flickerblade phantom-proc refute+fix; ENGINE 1.211.0; LEDGER 893)

DS-sweep rotation via a fresh adversarial Meraki(16.13.1)-vs-registry refute pass (4 parallel
read-only research agents). REFUTED every candidate NEW offensive lane on ground truth (Navori
"Impermanence" amp = STALE premise - 6675 is Flickerblade now, no such passive; Hexplate 3073 /
Axiom 6696 ult-haste = CLOSED item 310 + schema lift; Malignance 3118 MR-shred = ult-gated
schema lift; Liandry/Blackfire/Demonic burns Meraki-exact) - BUT the sweep FOUND a real bug I
verified against Meraki MYSELF: SR base item 6675 (Navori Flickerblade) phantom-credited Kraken
Slayer's "Bring It Down" 120->168 physical every-3rd-attack proc that Meraki 16.13.1 does NOT
list (6675 = Transcendence CDR only), a 6672-vs-6675 key-collision artifact - inconsistent with
the item's own already-correct Arena mirror 226675 + the 226672 correction comment. FIX
(R116-precedent refute+correct, scoring-active proc so ENGINE bump): removed the phantom proc,
6675 now utility-only (defensive_only) matching Meraki; removes phantom physical over-credit for
crit-ability carries (Yasuo/Yone/Zeri/Xayah); crit/AS/MS stats unaffected. TDD RED-first (new
guard test_navori_phantom_proc_refute_r119.py) + updated 2 OLD phantom-encoding tests + fixed a
latent gold-efficiency Meraki-absent-item (667109 Cruelty) fragility. ENGINE 1.210.0 -> 1.211.0
(114 pins); build-order precompute + variants regen (full roster); ds_share_sync 454 files
--check GREEN; DS :8893 bounced to 1.211.0. DS 8449 pass / 1 skip / 1948 subtests; RC 11602 pass
(24 initial fails were ALL the bump regen cascade + 2 pre-existing coach_poll flakes + 1
pre-existing roadmap-budget, pruned). No LIVE_GAME_GATED_SYNC row (correctness removal, nothing
to flip). done_sentinel --tests 8449 --regressions 0.

---

# 2026-07-13 (R113-fix gemini-loop cycle - FALSE-POSITIVE REGRESS #5 + RC-suite guard; LEDGER 882)

Directive ordered a "missing" test for the R113 total-AD physical burst seam (auditor flagged HEAD `374e8f44` REGRESS). DISPROVEN vs ground truth: the seam was tested - DS-dir `test_item_hydra_active_burst_r113.py` (447 lines / 27 tests) + Share mirror shipped in the R113 FEAT commit `93cac79c` (verifier 27/27 fresh; LEDGER 881 recorded it). `374e8f44` is the R113 FINALIZE (re-stamp) commit; the auditor diffed it in isolation = same diff-window misattribution as cycle-13 (#4). Now #5 of the cycles-7/8/9/13 family. Root cause OPEN (loop infra): R61's `audit_range` (`d1a143d4`) needs a controller RESTART to activate + a merge second-parent window fix (`93cac79c` enters HEAD via the `b003dac5` merge). ACTION: shipped a legitimate non-duplicative RC-suite guard `tests/test_item_hydra_active_burst_r113.py` (12 tests; RC CI had zero `physical_burst_total_ad_ratio` coverage; not the cycle-13 duplicate anti-pattern). verifier CONFIRM: RC 12/12 + DS-dir 27/27 + collect 11623/0-err + ruff clean + zero engine diffs. Test-only, ENGINE-IMPACT NONE (under `tests/`, no Share/DS bounce). PART C escalation -> `gemini_ask.txt`: fix the audit window + REDIRECT the loop to the operator's overnight priority chain (#1 `docs/specs/2026-07-13-ds-crit-burst-fix.md`). `done_sentinel --tests 12 --regressions 0`.

---

# 2026-07-13 (R111 gemini-loop cycle 3 - Overlord's Bloodmail Retribution missing-HP AD offense seam; ENGINE 1.209.0; LEDGER 879)

DS-sweep rotation via a fresh adversarial Meraki(16.13.1)-vs-registry refute pass.
NEW default-OFF `assume_caster_lowhp` seam credits Overlord's Bloodmail (SR 2501 /
Arena 447111) "Retribution" missing-HP-scaled bonus AD - NEW field
`missing_hp_ad_amp_max_pct` (0.12 / 0.175) folded into compute_dps + compute_burst,
the caster-self-state parallel of the DSV2 takedown seam (0.5-of-max ramp midpoint,
`_ASSUMED_CASTER_MISSING_HP` 0.35 / cap 0.70). Byte-identical OFF. Director labeled
this "R104" but it was RENUMBERED R111 (R104 = shipped Annul spell-shield 7646e65d;
the build agent caught the collision). Verifier CONFIRM 7/7; DS 8421 / 0 fresh; RC
11586 passed / 3 pre-existing (2 coach-poll LEDGER-828 asyncio flake pass-isolated +
1 R102 `build_module.css` dark-literal ratchet, file untouched by R111 - chipped as a
separate frontend task) / 0 R111 regressions. HZ-B 6 tables stamp-only re-stamp (guard
6/6); DS `:8893` bounced 1.209.0 live; `ds_share_sync --check` green 452 files. merge
`7cf051db`, reconcile `9e61f8a0`. Live default-ON flip -> LIVE_GATED B49 (practice-SR
own-build eyeball). Don't-redo: 2501/447111 Retribution SHIPPED; the item-keyed
incoming-DR lane (crit R77 / AA R80 / AS-slow R86) is saturated; R77's Steelcaps
sibling director-note is STALE (shipped R80).

---

# 2026-07-13 (nightly reds cleared + DSP11 Step-0b gate RESOLVED do-not-revert + kit-axis table fresh-DB refresh; a+b+c chain; LEDGER 876)

Operator "go a+b+c chain" then "/done + continue headless with ahk + gemini". 3 commits pushed to main:
- **(a)** `35732e4e` loadout dedup: 18 double-pen unique-family clashes (LastWhisper/VoidPen keys from 1.207.0, LEDGER 872 - loadouts never regenerated). ROOT-CAUSE tool = the item-s8 sweep (`tools/champion_loadout_sweep_item_s8.py`), NOT align.py: the WAKEUP "re-run align.py" hint was STALE - align.py only rewrites `v["items"]`, but 16/18 clashes live in `build_paths[*]["items"]` it never walks. Surgical 25/25 diff; 1646 loadout guards + full suite green.
- **(b)** `2f90fd28` ROADMAP trim 83217 -> 80955 bytes (< 81920): relocated the stale 2026-06-05 NEXT-UP block verbatim to ROADMAP_HISTORY, kept the P3.2 residual, shortened the P6 stub. test_doc_size_budget green.
- **(c)** `5081ab91` DSP11 (Step 0b) gate RESOLVED = **DO-NOT-REVERT**. The operator-gated coach-picks diff ran at TRUE coach fidelity (`dispatch_for_coach` top-5 + real frontline/squishy comps + independent rewind re-query; report `ops/audit/ds_perm_swarm/report/dsp11_gate_diff.md`) and REFUTED the spec premise: Step 1a fixes crit-ADC coherence ONLY, not the lethality/assassin/manamune DSP11 champs - reverting drops Pyke's whole lethality core live. Instead kept the mechanism + gave `build_kit_axis_item_credit.py` a fresh-DB re-validation gate + refreshed the table (drops Ezreal-ER [table 56.2%/n16 -> fresh 40.9%/n22] + Naafiri [at/below baseline]; keeps Pyke/Corki/Nilah/Senna + Ezreal-Trinity). Data-only, NO ENGINE bump. Share-synced + `:8893` restarted + live-verified (Naafiri inert, Pyke intact). DS 8404 + consumers 106 + DSP11 12 green.

Gemini director re-tested **UP** (was down last session, executor-direct). NEXT (overnight directive priority 2, continuing headless): Step 0a DSP2 byte-identical prune, Step 2 wire `situational.py` counter-build into the overlay, Step 3 ally synergy + NL reasoning; then priority 3 per-champ meta-build online research (aggregator B/aggregator D/aggregator A vs engine). **Do NOT re-pitch the DSP11 mechanism revert** (gate-closed do-not-revert; spec 0b RESOLVED).

---

# 2026-07-13 (DS crit-burst fix L1-L4 SHIPPED + live-validated; EXECUTOR-DIRECT - Gemini down; self-audited director-proxy; LEDGER 875)

Gemini-headless loop launched but the Gemini DIRECTOR was DOWN (Google-side 503 on gemini-3-pro-preview + fallback 2.5-flash; TCP 443 fine, so Google-side not Legion egress). Operator chose EXECUTOR-DIRECT ("use yourself as pseudo proxy"); loop halted (STOP dropped; controllers + ahk killed). Executed priority (1) = the crit-burst spec, self-auditing as director + auditor proxy since Gemini could not.

5 commits pushed to main: L1 `9708e3bf` (coherence respects burst score) -> L2 `54d5efc8` (ENGINE 1.207->1.208, arm the execute) -> L3 `83624198` (crit-ADC fight_length allow-map) -> L1'/L4 `f2ecafe8` (the DEEP fix) -> backfill `4e00df61`. Full detail: LEDGER 875.

DEEP DISCOVERY: L1/L3 were INERT live - the client `RankedItem.from_dict` DROPPED the server's `effective_score`, so the coherence burst branch read base 0.0 (a target-blind kit-fit sort). An L4 subagent STOPPED + surfaced it (proven: rank_for raw-server differs by target, rank_for_primary_archetype final does not); I verified + authorized the combined fix (parse effective_score + eff-branch dock `_MU_EFF=80` + SQ-70 squishy target at the chokepoint, gated `apply_squishy_burst_target`). Caught + corrected TWO subagent misreports (the "no-op" STOP was the real root cause; a mislabeled "pre-existing" anti_tank regression was actually mine -> the variant opt-out fix). Memory `reference_ds_client_effective_score_parse`.

LIVE-VALIDATED via /api/ds-preview on the restarted RC: Jinx IE#4/Collector#3, Twitch IE#3/Collector#2, ER/Eclipse out of top-8; Vayne (on-hit control)/Lux/Ornn byte-identical. `:8893` @ 1.208.0, Share --check green, consumer set 0 failures (was 12), DS suite 8406 passed.

NIGHTLY CATCH (fixed `9b811356`): the schedule-only full suite caught ONE crit-burst regression the push-CI + my consumer-set filter missed - `test_archetype_dispatcher::test_carry_propagates_target_armor` used Caitlyn (now a mapped burst carry, so L4 correctly swaps her target); retargeted to Vayne + added mapped-swap coverage. Also authored the owed 1.208.0 changelogs (Share + engine + DAEMON_SLAYER status 8403).

PRE-EXISTING nightly reds (NOT crit-burst, do NOT attribute to this session): `test_champion_loadouts_no_unique_clash` (18 double-pen family clashes in `data/champion_loadouts.json` - the LEDGER-872 1.207.0 double-pen fix added the unique keys but never regenerated the curated loadouts; needs a loadout regen + backfill); `test_doc_size_budget::test_roadmap_md_under_budget` (ROADMAP.md 83217 > 81920 bytes - relocate shipped entries to docs/ROADMAP_HISTORY.md); plus runner-only env fails (asyncio.run in a running loop, :8893-down Jhin plan, missing 3858.png icon).

NEXT: (a) regenerate champion_loadouts.json to clear the 18 double-pen clashes; (b) trim ROADMAP.md under budget; (c) priority (2) the other DS build-reco refactor slices (Step 0/2/3 of `docs/specs/2026-07-13-ds-build-coherence-refactor.md`) + priority (3) per-champ meta research. Spec L5 (fed / comp-aware fight_length) + L6 (Stormrazor 3097 stale-catalog hygiene) are follow-ups. A real IN-GAME crit-ADC eyeball is owed (do-not-flip-blind). If Gemini recovers, the loop can resume.
