# Riot Commander - Categorical Open-Item Review (2026-07-25)

Produced against HEAD `4f21782a`, ENGINE 1.241.0, patch 16.14.1. Loop HALTED
(`ops/loop/control/STOP` present, confirmed on disk).

**PART 0 through PART 3 are the review as originally written. PART 4 was appended
after a build session the same day acted on the top-5 plus the runner-up, and it
corrects several rows above - read PART 4 before treating any row here as current.**
Rows that the build closed are struck in place rather than deleted, so the reasoning
error stays legible. Engine at time of PART 4: **1.242.0**.

## Live probe (this session, not inherited)

| probe | result |
|---|---|
| `ops/runtime/health.json` | pid 19932, alive true, mode `client`, last_reload_ok true |
| `https://127.0.0.1:8888/api/state` | `mode_key=client`, `liveclient` empty (no game) |
| `http://127.0.0.1:8893/health` | engine 1.241.0, patch 16.14.1, 706 items / 173 champions |
| `data/daemon_slayer/current.txt` | 16.14.1 |

## Method + honesty bounds

Sources read: CLAUDE.md (Settled block), MEMORY.md, `git log -15`, `WAKEUP_NOTES.md`,
`ROADMAP.md` (all 241 lines), `BACKLOG.md`, `docs/LIVE_GAME_GATED_SYNC.md`,
`docs/ORCHESTRATION_PLAN.md`, `docs/LEDGER.md` head.

Three verification tiers are used below and each row says which it got:

- **PROBED** - I ran a command against disk / DB / live service this session.
- **SOURCE-READ** - I read the cited code or doc line, but did not execute anything.
- **AS-FILED** - carried forward on the filing's own evidence. Not independently
  re-verified. Roughly two thirds of the DS-sweep GAP rows are in this class; they
  were each measured at ship time by the sweep and the sweep is closed 173/173.

Anything in CLAUDE.md "Settled - do not re-litigate", any do-not-re-pitch fence, and
the ORCHESTRATION_PLAN EXCLUDED list is **excluded from this inventory**, not listed.

---

## PART 0 - ROWS THAT ARE SILENTLY CLOSED OR STALE (delete, do not build)

These read as open in ROADMAP / BACKLOG / ORCHESTRATION_PLAN but are not.

| # | reads-open at | verdict | check I ran |
|---|---|---|---|
| S1 | BACKLOG "deterministic champ-select brief FLIP (Haiku-elim)" (Coaching depth) | **CLOSED - the flip already happened 2026-06-06.** `dashboard/_champ_select.py:26` returns `brief_deterministic(...)` directly and `_champ_select_deterministic.py:23-25` states in-source "no live Haiku brief is left to shadow". The BACKLOG row still instructs a future flip. | PROBED (read both files) |
| S2 | ROADMAP RM-12 clause "the champ-select brief Haiku flip after shadow-log accrual" + ORCHESTRATION_PLAN EXCLUDED bullet 3 | **Same closure as S1.** Also gated row `G7-03` is already marked CLOSED-as-stale 2026-07-18. Three separate docs still carry it. | PROBED |
| S3 | BACKLOG expectation of `logs/champ_select_brief_shadow.jsonl` accrual | **File does not exist and never will** - the writer was retired with the flip. Only `tests/test_champ_select_deterministic.py` references the name. | PROBED (`ls` + grep) |
| S4 | ROADMAP RM-01 inline probe note: "`data/fusion_shadow.jsonl` does NOT yet exist on disk - zero real-game ticks have accrued" | **STALE.** File exists: **230 records, 272086 bytes**, first ts 1784424693, last ts 1784934301 (real games, gold/level/cs/kda populated). The Lane-E flip gate the note calls "genuinely unmet" is now MET on volume. See D-01 below - and the accrued data shows a defect. | PROBED |
| S5 | ROADMAP RM-32 "DS calibration pipeline (data-blocked)" - "queue 420 latest is still 2025-12-15 and `data/ds_calibration.jsonl` has 0 SR records" | **BOTH HALVES MEASURED FALSE.** `rewind_history.db` queue 420: 516 matches, max `game_creation_ts` = **2026-07-01**, **32 games since 2026-05-29**. `data/ds_calibration.jsonl`: 10139 records, **SR 4172** / ARAM 5257 / ARENA 710. The stated "~20+ ranked-game samples" threshold is exceeded. RM-32 is UNBLOCKED. | PROBED (sqlite3 + jsonl parse) |
| S6 | BACKLOG SGP bullet: "The ONE remaining live unknown = a Legion NA-region host reachability probe" | **PARTIALLY STALE.** CLAUDE.md Settled records SGP MEASURED 2026-07-19 (RM-106) returning KIWI / queue-2400 games in Match-V5 shape - i.e. reachability is answered. The ToS-HIGHEST framing survives; the "unknown" does not. | SOURCE-READ |
| S7 | ROADMAP RM-03 "ONLY the G1-00 live confirm owed" | **STALE.** `docs/LIVE_GAME_GATED_SYNC.md:5-15` records G1-00 BOTH CHECKS PASS in the 2026-07-20 drain, champ_select byte-identical True. The G1-00 body further down the gated doc was never struck, so the row reads open in two places. | PROBED |
| S8 | `docs/LIVE_GAME_GATED_SYNC.md` bodies for G1-00 / G6-02 / G2-18 / G2-29 / G2-34 / G2-35 | **Closed 2026-07-20, bodies retained unmarked.** A drain session reading gate-by-gate will re-attempt all six. | PROBED (id occurrence scan) |
| S9 | ROADMAP RM-112 (two bullets, one CLOSED one "original") | Already correctly marked CLOSED 2026-07-23 `083605c5`. Listed here only so it is not re-counted as open. | SOURCE-READ |
| S10 | ROADMAP RM-81 **P0** ("`prefer_cdragon_ratios` is default-ON and its sidecar is patch-blind"), chip `task_d665f88b`, and this document's own row A-01/A-02 | **CLOSED - the P0 shipped 2026-07-18.** `4cd3c4c6` (guard, RED-first, `strict_cdragon_patch` DEFAULT-OFF + diagnostic) and `544d6362` (16.14 CDragon re-extract + strict flip to DEFAULT-ON) are BOTH ancestors of HEAD. `abilities.py:679` is `strict_cdragon_patch: bool = True`; `cdragon_sidecar_patch()` exists at `:433`. The 16.14.1 sidecar carries payload patch `16.14.1` with its own distinct hash - only the three OLDER dirs are 16.11.1 copies. **"A 16.14.1 engine is serving 16.11.1 ratios" is FALSE.** | **PROBED** (merge-base + hashes + signature) |
| S11 | BACKLOG competitor-lift **F1 lane/fight threat column** ("today `enemyIds[0]` only") | **CLOSED - shipped `533e7e47` (2026-07-20)**, an ancestor of HEAD. `enemyIds[0]` has **0 hits** in `web/js/panels/ds_matchup.js`; the file already loops `cs.their_team` and bins severity. | **PROBED** |
| S12 | BACKLOG competitor-lift **F5 role-matched lane opponent** ("`ds_matchup.js:247` selects `enemyIds[0]`") | **CLOSED in the same commit.** `_laneOpponentIdx` / `_normRole` exist; the shipped test `test_panel_selects_role_matched_lane_opponent` already asserts `"enemyIds[0]" not in src`. | **PROBED** |
| S13 | ROADMAP RM-04's framing of the pool fix as "the CHEAPEST ACTIONABLE FINDING ... a filter-list edit, not L2 work" | **The FILTER half reproduces; the CHEAP half is REFUTED (see A-01 below).** The edit is real and shipped, and it changes nothing anyone can see. Re-file as L2 scorer work. | **PROBED** (live `:8893` + built seam) |

**Doc-drift risk note (not an open item, a constraint):** `ROADMAP.md` is **81472 bytes**
against the 81920-byte (`80KB`) `tests/test_doc_size_budget.py` ceiling - **448 bytes of
headroom**. Any new NOW row must relocate prose to `docs/ROADMAP_HISTORY.md` in the same
commit. This already broke a suite once (WAKEUP 2026-07-24, R186).

---

## PART 1 - CATEGORICAL OPEN INVENTORY

Size key: **1S** = one session, **MS** = multi-session, **SPIKE** = timeboxed
investigation with an explicit kill criterion.

### A. DS ENGINE MATH

| id | what + why open | blocked-by | size | source | tier |
|---|---|---|---|---|---|
| A-01 | ~~RM-04 carry-pool filter-list~~ **BUILT 2026-07-25 (ENGINE 1.242.0, DEFAULT-OFF `widen_carry_pool`) AND THE PREMISE IS HALF-REFUTED.** Mechanism confirmed by ID: `OFFCLASS_MARKSMAN_ITEM_NAMES` (`rank.py:83-127`) applied at `rank.py:711-712` behind `_is_ranged_marksman`. Bloodsong is a DIFFERENT deny (`_SR_EXCLUDED_ITEM_IDS`, the RM-93 support-quest filter) and stays denied - lifting it was previously measured harmful. **Pool is 108, not 111** (measured in-process AND live on `:8893`). Flag-ON grows it 108 -> 112 and changes **ZERO top-8 entries for any of the seven marksmen**; Senna's Black Cleaver lands #33, Smolder's Shojin #41. **Un-filtering is necessary and NOT sufficient - the burial is scorer kit-blindness (RM-86), so the residual is L2 work.** | residual: nothing (it is now RM-86-shaped) | residual MS | ROADMAP RM-04; ENGINE 1.242.0 CHANGELOG | **PROBED** |
| A-02 | ~~RM-81 P0 sidecar patch-blindness~~ **NOT AN OPEN ITEM - see S10.** Shipped 2026-07-18. This row was authored from stale ROADMAP prose (tier SOURCE-READ) and is retained struck so the error is legible rather than silently deleted. | n/a | n/a | ROADMAP RM-81 | **PROBED** |
| A-02b | **NEW, surfaced by the A-02 slice: six per-patch artifacts carry NO internal `patch` field at all**, and with `strict_cdragon_patch` now DEFAULT-ON, loading any of the three stale 16.11.1 sidecars would silently drop to Meraki. Same bug class as the closed P0, different artifacts. | nothing | 1S | LEDGER 1041; `4cd3c4c6` notes | SOURCE-READ |
| A-03 | **RM-81 re-source the 6 champions that matter.** 75 of 171 carry drifted values but only 6 change any ranked order, 2 touch a top-5, 0 change a recommended core. Re-source 6, not 75. | nothing | 1S | ROADMAP RM-81 | AS-FILED |
| A-04 | **RM-99b Heartsteel damage-half cadence.** `_effects_data.py` carries `every_n_seconds=3.5`, neither the 3s charge nor the 30s per-target cooldown; a single-target rotation gets ~8.57x the real proc count. The two halves of the Heartsteel model disagree about firing rate (R137's EHP half uses the real 30s). Arena mirror 223084 carries the same 3.5. | operator decision (DEFAULT-ON change, reorders live builds) | 1S | ROADMAP RM-99b | AS-FILED |
| A-05 | **RM-39 / RM-43 default-ON flip.** L1+L2 shipped DEFAULT-OFF (`apply_ad_axis_ability_damage`, ENGINE 1.222.0/1.223.0). 79 of 92 cohort champions reorder flag-ON. MIXED held, MAGIC excluded permanently. | operator decision | 1S | ROADMAP RM-39/RM-43 | SOURCE-READ |
| A-06 | **RM-98 cast-rate time base.** ADJUDICATED 2026-07-19: a GAME-AVERAGE cast rate is summed onto a COMBAT-WINDOW auto rate; ~7x characteristic (not 27x); already ships DEFAULT-ON in `ds.onhit` / `ds.dps` / `ds.hps`. Spec recommends demoting the measured rate to a cast-PROPENSITY prior, not replacing the denominator. Unbuilt. | operator decision (touches 3 default-ON scorers) | MS | ROADMAP RM-98, `docs/specs/SPEC_rm98_cast_rate_time_base.md` | SOURCE-READ |
| A-07 | **RM-40 / RM-45 / RM-47 mage cluster.** MEASURED BLOCKED 2026-07-24 at 1.240.0: Ahri / Annie / Aurora and the REFUTE control Anivia return the identical head through `/rank-mage`. The GAP champion and its own control are indistinguishable to the scorer, so no coefficient or filter edit can separate them. | schema lift (champion-sensitivity in the mage scorer = the RM-04 shape-build work) | MS | ROADMAP RM-40/45/47 block, LEDGER 1037 | SOURCE-READ |
| A-08 | **RM-35 crit-burst cohort (Miss Fortune).** R186 shipped the SYMMETRIC off-axis exclusion which covers RM-35's mirror clause; RM-35's own crit-burst cohort work (fight-length ~0.5, Hubris absent from top-20) is explicitly NOT covered. | nothing | 1S | ROADMAP RM-35 row, LEDGER 1036 | SOURCE-READ |
| A-09 | **RM-36 + RM-38 AD-caster (Ezreal, Corki).** Compound POOL + MODEL: Trinity 3078 / Shojin 3161 / Iceborn / Divine filtered from the SR carry pool, and no scorer models an AD-caster. One pool fix covers both. Batch them. | nothing | MS | ROADMAP RM-36/RM-38 | AS-FILED |
| A-10 | **RM-37 + RM-42 empowered-auto crit machinery (Lucian, Akshan).** Lightslinger double-tap + Dirty Fighting 200 pct crit double-shot unmodelled; `coherence_rerank` additionally DOCKS Lucian's #1 item Essence Reaver from raw #4 to #10-18. Shared machinery, batch. | nothing | MS | ROADMAP RM-37/RM-42 | AS-FILED |
| A-11 | **RM-44 Amumu magic-tank AP rush.** First tank gap; axis-neutral EHP scorer structurally cannot value an AP damage item; his highest-WR Abyssal Mask ranks #14. | nothing | 1S | ROADMAP RM-44 | AS-FILED |
| A-12 | **RM-46 Ashe Frost + Ranger's Focus.** Crits deal no bonus damage (crit chance converts to flat AD) so IE's multiplier is largely dead on her; Phantom Dancer dead-last even in a 6-item self-whitelist. Aphelios is the contrast twin. | nothing | 1S | ROADMAP RM-46 | AS-FILED |
| A-13 | **RM-48 Azir soldier axis + the pet-DPS cohort.** Rerouting to `ds.onhit` still leads Liandry's and still buries Nashor's #17 - no scorer models the soldier stream. Siblings: Yorick / Malzahar / Heimerdinger. Overlaps RM-97 pet damage. | nothing | MS | ROADMAP RM-48, RM-97 | AS-FILED |
| A-14 | **RM-79 Locke / Zaahen data coverage.** Absent from Meraki's 171-champ bulk map so every kit-dependent scorer falls through to `ds.dps`. Two fixes shipped off it; the ability-data half is blocked upstream. | schema lift / upstream (Meraki) | MS | ROADMAP RM-79 | AS-FILED |
| A-15 | **RM-80 Master Yi mis-ROUTED.** On-hit AS carry served by bruiser `ds.hybrid`. | nothing | 1S | ROADMAP RM-80 | AS-FILED |
| A-16 | **RM-82 Mordekaiser.** Rylai's / Riftmaker buried under a never-built AP-amp + magic-pen lead. | nothing | 1S | ROADMAP RM-82 | AS-FILED |
| A-17 | **RM-83 Naafiri / RM-85 Nasus / RM-96 Zilean / RM-97 Zyra.** Four remaining per-champion GAP specs, each needing its own RED-first slice. RM-85 is RC-2 pool membership; RM-97 is the pet-damage class shared with A-13. | nothing | 1S each | ROADMAP RM-83/85/96/97 | AS-FILED |
| A-18 | **RM-87 intra-pool `ds.ehp` weighting (Ornn / Rammus).** Resists pay twice while a self-EHP objective counts them once. | nothing | 1S | ROADMAP RM-87 | AS-FILED |
| A-19 | **RM-88 Pyke.** A throughput objective cannot price a discontinuous execute threshold plus a gold-and-reset economy. Objective-shape work, not a coefficient. | schema lift | MS | ROADMAP RM-88 | AS-FILED |
| A-20 | **RM-89 Quinn.** First champion carrying BOTH RC-1 and RC-2 - the proof that the shipped L1 kit-conversion lever is necessary and provably INSUFFICIENT. | nothing | 1S | ROADMAP RM-89 | AS-FILED |
| A-21 | **RM-90 support-cohort build-order collapse.** Verified against the shipped `build_orders_sr.json`; prior Alistar / Blitzcrank / Braum / Bard / Rakan REFUTEs judged TOO LENIENT. Check the shipped build order before any new team-aura REFUTE. | nothing | MS | ROADMAP RM-90 | AS-FILED |
| A-22 | **RM-91 HP-as-damage.** Bonus HP is scored EHP-only, so kits converting health into damage are undervalued; Randuin's is engine #1 for five tanks and in the real core of none. Tahm Kench vs Taric is the matched pair isolating this from RM-92. | schema lift | MS | ROADMAP RM-91 | AS-FILED |
| A-23 | **RM-92 residual = the ABILITY-HASTE class (5 champions).** SIZED 2026-07-18, verdict DEFER (`docs/specs/SCOPE_rm92_ability_haste.md`). The ally-facing slice already shipped (Term A `score_by="team_blended"`). All four separable tails shipped at ENGINE 1.221.0. What remains is the modelling question, which is A-06. | operator decision | MS | ROADMAP RM-92 | SOURCE-READ |
| A-24 | **RM-93 support-quest item candidacy.** Zaz'Zak's 3871 + Bloodsong 3877 are candidates on ZERO routes despite modelled damage formulas. Filter-list work, same class as A-01. | nothing | 1S | ROADMAP RM-93 | AS-FILED |
| A-25 | **RM-94 snowball stacks pinned at FULL value.** `_effects_data.py:3257` pins Mejai's at +125 AP so it ranks #6 for EVERY mage at 2-5 pct real presence. Not win-rate contamination - DS default is pure simulation. | nothing | 1S | ROADMAP RM-94 | AS-FILED |
| A-26 | **RM-95 ability-data coverage (DIAGNOSTIC).** 3 name-alias misses + Locke/Zaahen genuinely absent, and `champion_ability_data_is_current()` certifies all five as current because absent data cannot be drifted - so RM-81's staleness program under-reports by exactly the set it should flag hardest. | nothing | 1S | ROADMAP RM-95 | AS-FILED |
| A-27 | **RM-114 NEXT BUY gold feed.** `item_advisor.resolve_build` returns a build for exactly **6 of 172** champions (operator's own pool). The widget is faithful; the feed is empty for 97 pct of the roster. Two routes: re-source `next` from DS (173 champs, live at `:8893`) or widen `item_advisor`. The DS route changes what "next item" MEANS. | **operator decision** (deliberately not pre-decided) | 1S after the call | ROADMAP RM-114 | SOURCE-READ |
| A-28 | **RM-14 gated flip levers.** The canonical index of default-OFF seams awaiting a default-ON flip (`gate_ammo`, `apply_mode_modifiers`, `aoe_targets_hit`, `apply_ability_haste`, `apply_passive_damage`, assassin keystone auto-enable, `assume_missing_hp_heal_amp`, `rune_procs` into burst, the enchanter-registry 5). RM-19/20/21 fold into it. | live-game-gated + operator decision | MS | ROADMAP RM-14 | SOURCE-READ |
| A-29 | **BACKLOG R129 Viego R + the CDragon surplus-block class.** `prefer_cdragon_ratios` only OVERWRITES existing blocks, never APPENDS surplus ones, so Viego R's 120 pct total-AD block is dropped and `compute_ability_dps("Viego", R)` returns raw 0 at full HP. Siblings: Pyke R, Rengar R, Quinn R, Yorick R, Jinx Q. Two fix options (narrow per-champ override registry vs general APPEND seam). Not blind-shippable. | nothing (but each sibling needs per-champ validation) | MS | BACKLOG "DS scorer calibration" bullet 1, LEDGER 903 | AS-FILED |
| A-30 | **BACKLOG R129 bruiser/hybrid ability-DPS XOR.** `hybrid.py` scores damage as strict XOR - AD-axis champs score on AUTO DPS only and their non-zero ability DPS is never summed. A BLANKET sum is REFUTED-unsafe (double-counts auto-empower kits). Safe shape = `blend_ability_axis` bool + empty per-champ opt-in table. Overlaps A-05. | nothing | MS | BACKLOG bullet 2, LEDGER 903 | AS-FILED |
| A-31 | **BACKLOG R67 Terminus Light-side caster resists.** 6-8 armor+MR per stack x3. Needs an item-keyed conditional resist-grant path (`_passive_resist_overrides.py` is champion-keyed only). Source the Arena mirror `223302` from its OWN feed entry per doctrine B - do not assume Light-side magnitudes match SR. | schema lift | MS | BACKLOG | AS-FILED |
| A-32 | **BACKLOG R190 kit-penetration tails (a)-(e).** (a) Annie R 15/17.5/20 pct magic pen absent from `_ANTITANK_REGISTRY`; (b) registry rows carry no `axis` field so SHRED / PERCENT_PEN cannot distinguish armor-side from magic-side (KSante R is an exemption-based pin today); (c) Amumu P registered SHRED 0.6 but 16.14.1 is a 10 pct bonus-true vulnerability; (d) kit-pen magnitudes are max-rank only. **(e) gates the rest:** the target model carries ONE scalar armor with no base/bonus split, so percent-of-BONUS-armor pen (Yasuo R 60 pct, KSante R 50 pct) is registered-but-not-credited. | (a)(c) nothing; (b)(d) nothing; **(e) schema lift** | (a)(c) 1S, (b)(d) 1S, (e) MS | BACKLOG (FUTURE, from R190 / LEDGER 1040) | PROBED (`_kit_penetration.py` on disk, 15906 B) |
| A-33 | **BACKLOG DS cross-eval Tier-2 nominations.** (A) ARAM archetype-override table - kit-default archetype disagrees with the ARAM win-axis for a cluster; the `data/cs_archetype_picks.json` mechanism exists. (B) champion-kit-aware DPS crediting - AD scorers emit a near-identical BotRK/Runaan's/Kraken template regardless of kit; B1 = melee-applicability gate. (F2) gold-aware top. Each gated on per-champion rewind-WIN validation FIRST. | operator decision (A = off-meta-chase call) | MS each | BACKLOG, `ops/audit/ds_cross_eval/SYSTEMIC_FINDINGS.md` | AS-FILED |
| A-34 | **BACKLOG G6 cost model / cost-ignoring optimum.** DSP9 proved this - not comp-awareness or runes - is the residual driver of the lolmath-vs-DS gap. Gemini verdict was leave-FUTURE: a raw gold cost model conflicts with DS's empirical-WIN anchoring. Do not build blind. | operator decision | MS | BACKLOG | AS-FILED |
| A-35 | **BACKLOG Item Shaper full re-rank engine seam.** The shipped strip is an honest emphasis PREVIEW; `rank.py rank_items` takes NO weight-dict input and the archetype blend is 2-axis [alpha,beta], not 3-axis. Needs a defined 3-axis weight surface + threading it through the rank path. | schema lift + operator decision (which weight surface) | MS | BACKLOG (FUTURE, from OQ14) | AS-FILED |
| A-36 | **BACKLOG lolmath-wiki sidecar remaining scalar lanes.** `action=bucket` non-ARAM mode-mults (Arena/URF/NB), static-cooldown flags, charge model. Extractor + per-patch data in place through 16.14.1. DATA CEILING: only 61/171 champs have a real AA cast time in ANY source. | operator decision | 1S each | BACKLOG | AS-FILED |
| A-37 | **BACKLOG target-current-HP pct FLIP.** Seam fully wired at default 1.0 (byte-identical); open work is choosing a live fight-average value. Owes an ENGINE bump. **Do NOT touch the genuine pct-MAX-HP procs** (Eclipse 6692, Titanic 3748, Hullbreaker, Azakana's, Reaper's Toll 443090) - an investigating subagent already made that Eclipse mistake. | operator decision | 1S | BACKLOG | AS-FILED |
| A-38 | **BACKLOG situational / alternative builds (crit-vs-on-hit).** The engine emits ONE DPS-max build per champ; a real enhancement is >1 build keyed to matchup (vs-squishy crit, vs-tanky on-hit). Covers Kalista / Caitlyn / MF / Tristana. Larger DS feature. | schema lift | MS | BACKLOG | AS-FILED |
| A-39 | **BACKLOG boot-utility scorer v2 inputs.** Feed real per-champion enemy CC into `_select_boots` (v1 uses an AP-share proxy); MS boots need a kite/poke signal to ever win. The default-ON flip itself is live-gated and lives in the gated doc. | nothing | 1S | BACKLOG | PROBED (`boot_utility.py` on disk) |
| A-40 | **BACKLOG OQ24 build-coherence residuals (3).** (1) precompute build_order backfill, owed since Step 1a - but OPEN DESIGN Q FIRST: does `tools/daemon_slayer_build_orders_generate.py` POST raw to `:8893`, bypassing the core coherence dock? If so the backfill is a no-op. (2) Step-3 ally-synergy + NL "why X over Y". (3) Zeri Lich Bane / Liandry's AP-on-AD-marksman class. | (1) design question first | 1S / MS / 1S | BACKLOG, build-coherence spec:140 | PROBED (generator exists, 12765 B) |

### B. HAIKU-TO-ZERO LANES (A / B / C / E)

| id | what + why open | blocked-by | size | source | tier |
|---|---|---|---|---|---|
| B-01 | **RM-01 Lane E - the fusion shadow ledger has accrued and it shows a defect.** 230 real-game records. In BOTH the first and last record, `cv_reads.gold` is **1** while `live_client.gold` is 8703 / 6423, and because `live_stale` is true the fusion picks `{"value": 1, "source": "cv", "confidence": 0.7}` over the true value. This is precisely the "a wrong precompute is worse than a Haiku call" failure the do-not-flip-blind rule exists for - and it is now visible offline, no game required. Triage the CV gold read + the stale-override rule before anything else in Lane E. | **nothing** (offline-analyzable now) | 1S | ROADMAP RM-01; `data/fusion_shadow.jsonl` | **PROBED** |
| B-02 | **RM-01 Lane E - calibrate `augment_card_*` / `minimap_fog` rects, then a validated OCR-only flip.** The region atlas (25 regions) and dhash atlas (227 icons) are built and dormant. | live-game-gated (needs a real Arena/ARAM frame) | 1S | ROADMAP RM-01 (R121/R126) | SOURCE-READ |
| B-03 | **RM-09 / G7-01 HZ laning agreement -> flip chain.** Accrue real-game HZ shadow, re-measure precompute-vs-Haiku agreement on the item-614 corrected tables, then flip. `RC_LANING_CV_SERVED=1` gated on >=70 pct agreement. | live-game-gated | MS (accrual) | ROADMAP RM-09 -> `G7-01` | SOURCE-READ |
| B-04 | **RM-10 DS coach-hints surface.** Gated on `data/ds_coach_hints_shadow.jsonl` accruing + validating. **PROBED: the file has 7065 records**, newest ts 2026-07-21, engine_version 1.232.0 recorded. Accrual is no longer the blocker; the *validation pass* over the accrued rows has not been run, and it can be run offline. | nothing for the validation; live-gated for the surface flip | 1S (validation) | ROADMAP RM-10 | **PROBED** |
| B-05 | **RM-12 matchup-engine fidelity lift OR pivot.** STANDING GATE FINDING (do not re-litigate): the matchup engine validated as a COIN-FLIP vs real outcomes (48.8 pct / 51-52 pct, n in the thousands), so no coach was flipped off Haiku on it. Open choice: item-aware + real-level fidelity lift (uncertain payoff, likely a modeling ceiling) OR pivot to non-prediction surfaces. | operator decision | MS | ROADMAP RM-12 | SOURCE-READ |
| B-06 | **RM-12 champ_select pickban-DB flip** after a counter-quality validation. | operator decision + validation | 1S | ROADMAP RM-12 | SOURCE-READ |
| B-07 | **BACKLOG HZ-A laning choice-B is always economy/recall.** Every committed cell's `economy.recall` is `recall_now` / `back_soon` (live distribution 137600 + 217408, ZERO `hold`), so the combat-alt B branch at `core/precomputed_laning_coach.py:195-202` is production-unreachable and choice B is ALWAYS a recall directive. A coaching-content design call, not a mechanical bug. | operator decision (what should B be) | 1S | BACKLOG | AS-FILED |
| B-08 | **BACKLOG HZ-A Lane A v4 data-table regen.** v4 CODE shipped; the committed tables are still v3. Regen roughly doubles cells: ~190MB/mode LFS. Carries a monolith-vs-shard decision (`LANE_A_SCENARIO_PRECOMPUTE_SPEC.md` Risk 4) - do NOT commit the 190MB monolith blind. Serves nothing live until the Slice-F flip. | operator decision (shard design) + live-gated downstream | MS | BACKLOG | AS-FILED |

### C. OVERLAY / UI

| id | what + why open | blocked-by | size | source | tier |
|---|---|---|---|---|---|
| C-01 | **RM-113 TRINKET rule never activated.** 260 samples, `stageFor` provably returned `mid`/`late` for the final 12.5 min, so the stage gate cannot explain the silence. Reduces to ONE unrecorded fact: whether `owned_items` still held `stealth ward`. The probe now records it - the next SR game closes this with zero new analysis. | live-game-gated (one SR game) | 1S | ROADMAP RM-113 | SOURCE-READ |
| C-02 | **RM-22 Post Game Review aggregator G reframe, S2-S5.** CLAUDE.md names this the biggest pending non-engine item. Single-match richer layout; the 0-100 score is an RC heuristic with NO Claude/Riot dependency. Each stage its own session plus the per-page UI-audit ritual. | operator decision (stage sequencing) | MS (4 stages) | CLAUDE.md Settled; ROADMAP RM-22 -> `G4-27` | SOURCE-READ |
| C-03 | **RM-15 (b) operator packaging.** `npx electron-builder` + first GitHub Release + a packaged update check against the private repo (`GH_TOKEN`). | operator (it is an operator action) | 1S | ROADMAP RM-15 | SOURCE-READ |
| C-04 | **RM-15 (c) Phase 6 Pengu in-client panels, OPTIONAL.** Blocked on ONE operator decision recorded at `G1-05`: un-archive `docs/_archive/2026-07-07-pengu-stub/` back to `pengu/` and rebuild, or retire the row. Until answered there is nothing a game can drain. | **operator decision** | 1S or retire | ROADMAP RM-15; `G1-05` | SOURCE-READ |
| C-05 | **RM-06 overlay owed tail.** Offered not built: a manual ward tracker; folding the enemy-spell tap-tracker into the CD ledger if the operator prefers one panel. Standing fence: a native-HUD REPLACEMENT is impossible (Live Client exposes no cooldowns/buffs/wards/XP) so the tracker stays MANUAL. | operator decision (one panel or two) | 1S | ROADMAP RM-06 | SOURCE-READ |
| C-06 | **RM-26 vision-profile seeds are NOT WIRED.** `load_profile` keys on the exact `config_key` including HUD toggles, not the bare resolution the seeds use, so an ultrawide first run still falls through to `legacy_seed` at unscaled 1080p. Closing it is a live-path change. Second documented limit: proportional scaling stretches widths where League edge-anchors HUD elements, so the 16:9 2560x1440 seed is materially more accurate than the 21:9 / 32:9 ones. | nothing | 1S | ROADMAP RM-26 | PROBED (`core/vision_profiles.py` on disk) |
| C-07 | **BACKLOG mode-specific overlay layout + out-of-game stats mode selector.** Operator-requested 2026-06-30, queued for planning, NOT built. Key the layout store by `mode_key` with a shared/default fallback; migrate the existing single layout into the SR slot; decide how the rc-shell mirror + Alt+Shift+R reset interact with per-mode slots. The out-of-game stats panel needs a SR/ARAM selector that AUTO-SELECTS ARAM. Acceptance is live-gated (`G1-06`). | nothing to build; acceptance live-gated | MS (2 sessions + audits) | BACKLOG; `G1-06` | SOURCE-READ |
| C-08 | **BACKLOG per-enemy ult power-spike readout (R125 Aggregator C lift).** RC has the edge-trigger mechanism SELF-only. Per-enemy champion level is NOT in the Live Client envelope today - `dashboard/_liveclient.py:101` sets level from the ACTIVE player only and the `players` list carries only position/team/creep_score/is_active. Needs a one-field backend extract + a new stateful panel, so NOT presentation-only. | nothing | 1S | BACKLOG (FUTURE, R125) | AS-FILED |
| C-09 | ~~BACKLOG F1 lane/fight threat column~~ **NOT AN OPEN ITEM - see S11/S12.** Shipped `533e7e47` 2026-07-20. **A real defect was found in the shipped grid instead and fixed 2026-07-25:** it kept the pre-F1 `hide-on-not-ok` guard, so a pending or `no_matchup` HEADLINE collapsed all four other enemy rows and popped them back on landing - a direct `feedback_no_reflow_on_data_absence` violation. Also corrected `--` to the repo `-` sentinel. 5-phase audit run, 1 MUST-FIX (verdict track would two-line on `BACK OFF`) resolved in-slice. | n/a | n/a | BACKLOG F1/F5; commit in this session | **PROBED** |
| C-17 | **NEW, surfaced by the C-09 slice: the whole DS champ-select cluster gates on `isLive`**, so `ds_matchup` is unreachable under `?ui_mock=1`. That is precisely why the reflow bug survived earlier UI audits - headless audits cannot see this panel. Any future audit of it is source/geometry-based only until the gate is addressed. | nothing | 1S | `533e7e47` commit message; this session | SOURCE-READ |
| C-10 | **BACKLOG F5 + F4 matchup-card pair.** F5: `ds_matchup.js:247` selects `enemyIds[0]` instead of the role-matched laner though RC HAS role data. F4: `renderDsMatchupForChampSelect` mounts champ-select-only; the verdict half is liftable to the live active-match surface. Pair them. | nothing | 1S | BACKLOG F5/F4 (R81) | AS-FILED |
| C-11 | **BACKLOG small UI parity + polish set.** F2a Arena My Pick chip parity (Arena uses a separate `_csvArenaPaneHtml` layout and did not get the chip); F3 self power-spike transition toast (LOW); F2 recent-form W-L dots restyle (fold into R81, needs Laplace shrink before any tilt claim); F3 ARAM health-relic fixed-cadence timer; F8 projected-tier tile (fold into overlay item-8, not standalone). | nothing | 1S batched | BACKLOG competitor-lift set | AS-FILED |
| C-12 | **BACKLOG F2 enemy item-COMPLETION spike alert.** Edge-trigger on an enemy's first completed legendary, keyed to the DS build-order head. Component-item false alarms need a completed-legendary-only gate. NOT headless-blind-shippable. | live-game-gated for acceptance | 1S | BACKLOG (2026-07-16 AI-companion set) | AS-FILED |
| C-13 | **BACKLOG champ-select `.csv-rune-side-tree` narrow-width overflow.** ~105px overflow at 920px, which is BELOW the 1920x1080 shipping baseline. Explicitly a non-baseline NICE-TO-HAVE, not a MUST-FIX. Fix only if a companion/narrow champ-select ever ships. | nothing (but correctly deprioritized) | 1S | BACKLOG (R118, LEDGER 892) | AS-FILED |
| C-14 | **BACKLOG Vite-style push hot-swap.** On asset change push a ws event naming the file; hot-swap the CSS link in place, full reload only for JS. Upgrade to ADR-008 after the wss:// overlay fix lands. | dependency (wss:// overlay fix) | 1S | BACKLOG | AS-FILED |
| C-15 | **BACKLOG uxpatterns.dev + taste-skill design dials into the 5-phase UI-audit prompt.** Tagged NOW-cheap. Pure prompt/checklist work. | nothing | 1S | BACKLOG | AS-FILED |
| C-16 | **RM-17 live render review** of the champ-select Build Order B-card + `#ds-pill`. Code shipped and auto-serving; only the reviewed UI session + per-page audit is owed. | live-game-gated | 1S | ROADMAP RM-17 | SOURCE-READ |

### D. DATA / ETL

| id | what + why open | blocked-by | size | source | tier |
|---|---|---|---|---|---|
| D-01 | **RM-32 DS calibration pipeline - THE DATA BLOCK HAS CLEARED.** See S5. 32 queue-420 games since 2026-05-29 (max 2026-07-01) and 4172 SR records in `data/ds_calibration.jsonl`. This is a separate lane from the shipped postmortem analyzer. It is the only lane that turns DS simulation output into measured win-anchored feedback. | **nothing** | 1S | ROADMAP RM-32 | **PROBED** |
| D-02 | **RM-106 replay URL-rotation hypothesis.** Instrumented, not answered - four observations with no games played in between prove nothing. Play games, run `--pull`, read the rotation line. | live-game-gated (play games) | 1S after games | ROADMAP RM-106 | SOURCE-READ |
| D-03 | **RM-106b replay-API item progression.** The ONLY route that recovers ITEM progression for KIWI: with `EnableReplayApi=1`, a live replay serves `:2999/liveclientdata/allgamedata` for 10 players and `POST /replay/playback {"time":N}` seeks exactly, so per-timestamp item state is reconstructable by diffing across seeks. **NOT MEASURED: how far back the archive reaches** - test older ids before planning any bulk backfill. Skill order is NOT recoverable (`activeplayerabilities` 400s in replay). | nothing for the archive-depth spike; the backfill itself gates on its result | SPIKE then MS | ROADMAP RM-106b | SOURCE-READ |
| D-04 | **BACKLOG offline premade + tendency mining of `rewind_history.db`.** Tagged (NOW, zero-API, do-first). Match-intersection premade detection at ~0 API calls + role-conditioned behavior labels + timeline-derived gank-pressure metrics. Zero ToS risk. Caveat from memory: the DB has NO cohort population (23441 puuids, only 20 with 20+ games), so peer-benchmark features are not derivable - premade detection over the operator's own roster still is. | nothing | 1S | BACKLOG "Data pipeline" | AS-FILED |
| D-05 | **BACKLOG derived opponent-scouting layer.** Pure computation over the already-shipped Mastery-V4 + League-V4 fan-out: comfort-pool depth, banScore, a red RISK badge on pick cards. No new API calls. | nothing | 1S | BACKLOG | AS-FILED |
| D-06 | **BACKLOG game-start targeted Match-V5 timeline burst.** At `:2999` load-in the 5 enemy names are exposed; 5 enemies x (puuid + ids + 2-3 timelines) fits the 100-req/2min window. Anchors on GAME-START, not champ-select. Event modes excluded. | live-game-gated for acceptance | 1S | BACKLOG | AS-FILED |
| D-07 | **BACKLOG F3 snowball elasticity: WR by (K-D)@10/@20.** Raw data fully local (2954 matches of `timeline_events`); NO aggregator exists. New `core/` aggregator mirroring `duration_winrate.py`. Descriptive only - never fed into DS rank. | nothing | 1S | BACKLOG competitor-lift F3 (R71) | AS-FILED |
| D-08 | **BACKLOG F3 per-opponent matchup delta-stats + F1 lane-counter vs WR-counter split + F1a best/worst counters list.** Three aggregator-shaped items over the gitignored DB. All need fixtures (clean-checkout-probe risk) - do not build blind. | nothing (but fixtures first) | 1S each | BACKLOG competitor-lift F3/F1/F1a | AS-FILED |
| D-09 | **BACKLOG F2 tier-list WR-delta trend.** RC retains NO prior-patch WR snapshot to diff; needs a new patch-keyed WR snapshot store + a delta field. Not presentation-only. | schema lift (new store) | 1S | BACKLOG F2 (R117 Target C) | AS-FILED |
| D-10 | **BACKLOG cdragon by-level ratio resolver.** 111 Meraki-fallback ratio blocks are per-champ-level arrays the per-rank schema cannot represent. Drift-checked ALIGNED, not stale. Only worth doing if a future surface needs a champ-level-indexed ratio axis. | schema lift + a consumer that wants it | MS (~2 batches) | BACKLOG | AS-FILED |
| D-11 | **BACKLOG DPM damage-share curve.** Blocked on the cumulative-all-units `total_dmg` timeline field; RC stores no per-frame to-champions damage. Needs a new frame field / extractor. | schema lift | MS | BACKLOG | AS-FILED |
| D-12 | **BACKLOG aggregator XHR-first scrape (ToS-MED) and SGP channel (ToS-HIGHEST).** Both FUTURE, do-not-ship-blind. SGP's "one remaining unknown" is already answered (see S6); what survives is the ToS judgement, which is an operator call. | operator decision | MS | BACKLOG | SOURCE-READ |
| D-13 | **BACKLOG aggregator B carry-efficiency grade default-ON re-baseline.** `compute_role_grade(carry_efficiency=False)` today; flipping it is a grade re-baseline, a Tier-2 product call. | operator decision | 1S | BACKLOG | AS-FILED |
| D-14 | **BACKLOG Riot per-role grading rubric tail.** CC-score is a source-cited SUP signal with no rubric axis; `_ROLE_BASELINES` are SR-only so event modes grade against SR medians. | schema lift | 1S | BACKLOG | AS-FILED |
| D-15 | **item 211 residual: 7 orphan match rows.** `matches.tracked_puuid` can be stale - always re-resolve via Account-V1; Live Client rarely exposes `gameId` so `game_id=0` rides the ts-window fallback. Tracked as `G4-29`. | live-game-gated | 1S | ROADMAP RM-16 -> `G4-29` | SOURCE-READ |
| D-16 | **BACKLOG `rewind_history.db` SR records with `game_id`.** Wired in code (`d66d14b`), blocked on new records. PROBED: only 3 queue-400 matches since 2026-05-29, so the block is still real but thin, not absolute. | live-game-gated (play SR) | 1S | BACKLOG "Coaching depth" | **PROBED** |

### E. OPS / CI

| id | what + why open | blocked-by | size | source | tier |
|---|---|---|---|---|---|
| E-01 | **RM-100 surviving watch-item (NOT a re-open).** The RC-GeminiAudit `0xC000013A` last-run result is still UNPROVEN after six refuted hypotheses. The unconditional `START` log line makes the next occurrence attributable. If it recurs: the marker fix is not the cause, read the log. The asyncio marker leak itself is an ACCEPTED TRADEOFF - do not re-pitch a fix. | nothing (passive watch) | 0 | ROADMAP RM-100 | SOURCE-READ |
| E-02 | **RM-29 Share-mirror de-dup / build-time-gen.** The full 362-file de-dup stays deferred (outward-facing gist + CI `--check` coupling). Own session. Do NOT re-pitch the D4 hot-path-narrowing revert or the D12 logger reverts as bugs - they are deliberate. | operator decision | MS | ROADMAP RM-29 | SOURCE-READ |
| E-03 | **RM-33 auto-ops verb expansion.** Add `tail .* log`, `restart agent .*`, `verify .*` once Phase 3 auto-action success rate clears 95 pct. | dependency (95 pct threshold, unmeasured this session) | 1S | ROADMAP RM-33 | SOURCE-READ |
| E-04 | **RM-31 ADR-007 phase 3 prose-coach deprecation.** Mode coaches still narrate continuously in parallel with `decision_detector`. Detector-by-detector deprecation deferred until phase-1 detectors prove out in real games. | live-game-gated | MS | ROADMAP RM-31 | SOURCE-READ |
| E-05 | **RM-30 dashboard data-wiring gaps.** ~88 `st-*` ADAPTATION rows have no live producer (correctly HIDDEN in-game); `/api/ward-heat` permanently empty because Live Client emits no WARD_PLACED. Explicitly LOW value - wiring producers only affects the retired Chrome dashboard panel. | nothing | 1S | ROADMAP RM-30 | SOURCE-READ |
| E-06 | **RM-27 accepted-but-unbuilt triage items.** P2.2 structured-output (touches the live coach parse, partly redundant); P3.2 antitank dynamic pct-HP (a DESIGN change - antitank is intentionally static per item 308); the 6 UNIVERSAL_FILES template-convention update (also the whole residual of the old RM-18). | operator decision on P3.2 | 1S each | ROADMAP RM-27 | SOURCE-READ |
| E-07 | **BACKLOG local / free-tier LLM to replace the paid Gemini advisor.** Ground truth verified 2026-07-01: Gemini has THREE roles, and only the director is on premium `gemini-3-pro-preview` - ask+audit are already ~free. Plan: `tools/llm_advisor.py` behind `RC_LLM_BACKEND`, move ask+audit to a free tier first, QA the director against real transcripts before cutover. Honest caveat: a 20-32B model is weaker at director-grade judgement. **Setup is one QA session, then autonomous.** | operator decision (cutover) | 1S setup + MS | BACKLOG "Platform / observability" | AS-FILED |
| E-08 | **BACKLOG streaming vision: delta-encoded frames.** ~5x bandwidth reduction vs full JPEG every 2s. | nothing | 1S | BACKLOG | AS-FILED |
| E-09 | **BACKLOG `/api/analyze` streaming response.** Current 30s timeout is fine for ARAM (sub-second); may need SSE if full-mode analyses scale. Not currently binding. | nothing (not yet needed) | 1S | BACKLOG | AS-FILED |
| E-10 | **BACKLOG PyInstaller packaging.** `riot-commander.spec` exists as an opt-in starter. Explicitly not prioritized. | nothing | 1S | BACKLOG | AS-FILED |
| E-11 | **RM-28 DEEP-AUDIT PROGRAM.** Parked in LATER. Standing charter `docs/DEEP_AUDIT_CHARTER.md` (P0-P8), loop armed at max_cycles 100. Currently dormant with the loop halted. | operator decision (relaunch) | MS | ROADMAP RM-28 | SOURCE-READ |

### F. DOCS

| id | what + why open | blocked-by | size | source | tier |
|---|---|---|---|---|---|
| F-01 | **Strike the 9 stale rows in PART 0.** S1/S2/S3 (champ-select brief, 3 docs), S4 (RM-01 probe note), S5 (RM-32 data block), S6 (SGP unknown), S7 (RM-03 G1-00), S8 (6 gated-doc bodies). Each currently invites a wasted cycle. | nothing | 1S | this document | **PROBED** |
| F-02 | **ROADMAP.md is 448 bytes under its 80KB budget.** Any new NOW row must relocate prose to `docs/ROADMAP_HISTORY.md` in the same commit or `tests/test_doc_size_budget.py` goes red (it already did once, WAKEUP 2026-07-24 R186). | nothing | 1S | `wc -c ROADMAP.md` = 81472 | **PROBED** |
| F-03 | **RM-03 E10 ASCII + git-history rewrite.** Force-push, operator-gated. Part of the RC 2.0 program. | **operator decision** (history rewrite) | MS | ROADMAP RM-03 | SOURCE-READ |
| F-04 | **Smart-quote retroactive sweep.** CLAUDE.md records the em-dash purge as DONE and the smart-quote retro-sweep as explicitly NOT done - a separate operator-gated pass. Rule-banned going forward; historical instances remain. | operator decision | 1S | CLAUDE.md hard rules | SOURCE-READ |
| F-05 | **`docs/LIVE_GAME_GATED_SYNC.md` doc-hygiene follow-ups** (its own "PROPOSALS, not edits made here" section, line 1228). Includes the S8 body-striking. The `/live-gated-resync` skill exists for exactly this. | nothing | 1S | gated doc:1228 | PROBED |
| F-06 | **BACKLOG pre-release name-scrub.** Operator-authorized standing prerequisite; canonical plan `docs/PRE_RELEASE_NAME_SCRUB.md`. Scrub third-party names from content + full commit history (force-push pre-authorized for that pass). **DEFERRED to the release trigger - do NOT execute early.** | dependency (release decision) | MS | BACKLOG | SOURCE-READ |

### G. RESEARCH

| id | what + why open | blocked-by | size | source | tier |
|---|---|---|---|---|---|
| G-01 | **BACKLOG LCU lifts, tagged NOW + in-transport (no ToS issue).** (a) Legal-move champ-select getters `/lol-champ-select/v1/{pickable,bannable,disabled}-champion-ids` - RC does not call these; improves pick-card legality. (b) Riot recommended-runes read `/lol-perks/v1/recommended-pages/champion/{id}` as a degrade fallback when RC's DS rune plan is thin (RC writes runes today but never reads Riot's). Both use the existing Basic-auth transport, no new dep. | nothing | 1S batched | BACKLOG "LCU integration lifts" | AS-FILED |
| G-02 | **BACKLOG LCU WebSocket event stream.** Subscribe `OnJsonApiEvent` over WAMP for instant gameflow / champ-select / rune-write-timing pushes instead of the ~1 Hz poll. New `lcu/lcu_events.py` sidecar owning reconnect-on-lockfile-rotation into the asyncio AppLoop - do NOT edit the frozen `lcu/lcu_client.py`. | nothing | MS | BACKLOG | AS-FILED |
| G-03 | **BACKLOG tagged-players note layer + Overlay App E LCU rune-page auto-write.** Notes/tags table alongside `rewind_history.db` surfaced on the scouting card; rune auto-write needs a non-frozen wrapper around `lcu/lcu_client.py`. | nothing | 1S each | BACKLOG | AS-FILED |
| G-04 | **BACKLOG `.rofl` Layer-1 chunk half.** ESTIMATE REVISED 2026-07-19: the METADATA half is already done and cost ~10 lines - a `.rofl` ends with a plain JSON blob carrying `statsJson`, 10 players x 367 engine-named fields, no client and no patch gate. Only the Blowfish CHUNK half still costs real time. Load-bearing consequence: an archived replay is a permanent stats record for exactly the modes Match-V5 refuses. Steps 3-6 (Layer-2) stay out of scope. | nothing | SPIKE (~1.5-2d) | BACKLOG "Speculative" | SOURCE-READ |
| G-05 | **BACKLOG conditional-trigger watch items (5).** Arena S2 augment level-up + crafting round (trigger: 26.09 PBE schema); Brawl re-enable (trigger: Riot announcement); LoL Esports Data Portal community tier; CommunityDragon broader `lol-game-data` catalog (7 unconsumed files incl. canonical `queues.json` / `maps.json` - would replace the KIWI/queueId hacks); `mwrogue` MediaWiki Cargo client as a numeric backstop. **All are watches, not work.** | external trigger | 0 until triggered | BACKLOG | SOURCE-READ |
| G-06 | **BACKLOG F6 ask-anything chat box + F1 voice ASK path.** F6 is an operator CHARTER call - the prior R2 verdict CLOSED it as counter to Haiku-to-ZERO. New angle recorded: the structured backend already exists local-only (`tools/ds_matchdb_mcp_server.py` :8894), so a chat surface could be DS-precompute-first with LLM only on miss. F1 voice is gated BEHIND the F6 call. | **operator charter decision** | MS | BACKLOG (2026-07-16 AI-companion set) | SOURCE-READ |
| G-07 | **BACKLOG methodology references + remaining competitor-lift long tail.** baronbuff / league_record / aggregator Z13 / aggregator J / quick-aggregator-a-scraper / Coaching App Z7 / Draft Tool Z8 / Overlay App F lobby player-tags / Overlay App E enemy CD timers / F1 manual click-to-track CD overlay / F7 duo synergy-delta placement / F2 per-slot item WR ladder / F5 personal learning curve / F3 skill-order max-priority grid / F8 early-late rating bar / F2-F5-F6 Aggregator D defer set. Read-only refs plus ~14 candidate lifts, each individually LOW-MED. | mostly nothing; several need a corpus RC lacks | 1S each | BACKLOG "Research / inspiration" | SOURCE-READ |
| G-08 | **BACKLOG F1/F2/F7 pro-build + pick-rate corpus.** All three need a NEW external corpus RC deliberately does not carry - a blind-in-run-dependency reject. Do NOT build without operator sign-off AND a real data source. Listed so it is not rediscovered as an opportunity. | **operator decision + a data source** | MS | BACKLOG | SOURCE-READ |

---

## PART 2 - THE LIVE-GAME-GATED SET (counted on its own)

Source: `docs/LIVE_GAME_GATED_SYNC.md` (218190 bytes). Counted by parsing every
`- **GN-NN**` row id and its containing gate section.

| gate | what it needs | rows filed |
|---|---|---|
| GATE 1 | any lobby / champ-select, no game starts | 7 |
| GATE 2 | Practice Tool SR (bots + dummies) | 43 |
| GATE 3 | ARAM Mayhem (q2400, KIWI) | 15 |
| GATE 4 | real matchmade SR draft (make it ranked q420) | 29 |
| GATE 5 | Arena / Cherry (q1750) | 10 |
| GATE 6 | physical / operator hardware over any running game | 3 |
| GATE 7 | accrual rails - ride every session, never close on one game | 19 |
| | **TOTAL ROWS FILED** | **126** |

### Reconciliation to what is actually left

| | count | detail |
|---|---|---|
| rows filed | 126 | |
| less: closed 2026-07-18 by the synthetic triage pass (bodies retained, marked CLOSED in place) | -6 | G2-07, G3-05, G3-06, G3-07, G4-08, G7-03 |
| less: closed in the 2026-07-20 drain session (**bodies NOT struck - see S8**) | -6 | G1-00, G6-02, G2-18, G2-29, G2-34, G2-35 |
| less: not drainable by playing at all | -3 | G1-04 (blocked on a second account / real invite target), G1-05 (blocked on the Pengu operator decision), G1-06 (feature NOT BUILT yet) |
| **remaining, drainable by the operator at a keyboard** | **111** | |

**Caveat on the 111 (stated, not hidden).** Eleven further rows carry in-body
`NO LIVE RESIDUAL` or `DONE` text - G2-01, G2-41, G2-43, G3-04, G3-08, G3-09, G4-06,
G4-09, G4-11, G4-29, G5-04. Most of those are rows where the EYEBALL half is done and
only a default-ON FLIP AUTHORIZATION remains, which is an operator decision rather than
a game. I did not read all eleven bodies in full, so I am **not** asserting a number
below 111; a `/live-gated-resync` pass would settle it and is item F-05.

### Where the gated set concentrates

- **GATE 2 (43) and GATE 4 (29) are 58 pct of the file.** Both are SR. GATE 4 subsumes
  GATE 2 on the same branch, so **one real ranked SR game is the single highest-yield
  action available**, and it is the only path to the GATE 4 post-game rows.
- **GATE 7 (19) never closes on one game** by rule - those are accrual rails, so the
  realistic one-session ceiling is roughly the 92 non-GATE-7 rows minus what a single
  mode can reach.
- **GATE 6 (3) rides free** on top of any in-game gate.
- Prerequisite for every `[OVERLAY-*]` batch: **relaunch rc-shell (G6-01) BEFORE the
  game starts, not after.**

### The one measured fact about this set that should shape expectations

CLAUDE.md Settled: a 14-agent triage-then-adversarial-refutation pass over all 124 rows
(2026-07-18) closed **6**. The dominant kill was SUBSTITUTION - gate rows ask whether
something RENDERS / SENDS / UPDATES, and the compute half is always available headless
and always the wrong question. **This set is not synthetically drainable. Do not
re-attempt that.**

---

## PART 3 - TOTALS

| category | open items |
|---|---|
| A. DS engine math | 40 |
| B. Haiku-to-ZERO lanes A/B/C/E | 8 |
| C. Overlay / UI | 16 |
| D. Data / ETL | 16 |
| E. Ops / CI | 11 |
| F. Docs | 6 |
| G. Research | 8 |
| **subtotal, non-live-gated inventory** | **105** |
| live-game-gated rows, drainable by playing | 111 |
| stale rows to strike (PART 0) | 9 |

Blocked-by distribution across the 105: **nothing** ~52, **operator decision** ~31,
**schema lift** ~11, **live-game-gated** ~11 (the ones that also appear as gated rows).

Several A-rows are the same underlying fix filed under multiple champion ids
(A-09/A-10 are batched pairs by the sweep's own instruction; A-07 is three ids on one
blocked prerequisite). Counting fixes rather than ids, DS engine math is closer to
~32 distinct pieces of work.

---

## PART 4 - WHAT THE 2026-07-25 BUILD SESSION PROVED (appended after the fact)

Six slices were dispatched as parallel worktree agents against the top-5 plus the
runner-up. **Three of the six targets turned out to be already closed.** That is the
headline of this session and it validates the tier discipline in PART 0: every item
that collapsed was tagged SOURCE-READ or AS-FILED, and every item tagged PROBED held.

| slice | target | outcome |
|---|---|---|
| B-01 | RM-01 Lane E fusion triage | **REAL, FIXED.** 41 of 41 CV overrides in the ledger's whole history were garbage - all `gold`, all the literal value `1`, against real anchors of 913 / 8703 / 6423 / 12761 / 30410. Two independent causes: `core/vision_routing.py:118` merges any key the escalation returns unfiltered by the requested field list, and `core/vision_fusion.py` had NO plausibility check, so an unconditional 0.7 heuristic always cleared the 0.6 stale-override threshold. Shipped a plausibility gate. Ledger replay changes exactly 41 decisions, all gold, nothing else moves. |
| D-01 | RM-32 DS calibration | **REAL, BUILT, and the honest answer is "too thin".** 41 joinable games / 378 observations; `SR/dps` follow-rate 0.2341 with a shrunk win delta of +0.0677 that cannot be separated from noise on one account. Ships as instrumentation, not a verdict. |
| A-01 | RM-04 carry pool | **REAL, BUILT, PREMISE HALF-REFUTED.** See A-01 above. The filter edit lands and changes nothing visible. |
| A-02 | RM-81 P0 sidecar | **ALREADY CLOSED** (S10). Landed as a docs-only correction. |
| A-27 | RM-114 next buy | **REAL, BUILT.** 6/173 -> 173/173 in all three modes; 6 curated champions byte-identical across 54 comparisons; PRACTICETOOL / TFT / Brawl deliberately fail-closed. |
| C-09 | F1 threat grid | **ALREADY CLOSED** (S11/S12). A real reflow defect in the shipped grid was found and fixed instead. |

### New open items surfaced by the build (added to the inventory)

| id | finding | tier |
|---|---|---|
| A-02b | Six per-patch artifacts carry no internal `patch` field; with strict now DEFAULT-ON, loading a stale sidecar silently drops to Meraki. | SOURCE-READ |
| B-01b | `core/vision_routing.py:118` merges unrequested keys from the Sonnet escalation response. The upstream half of the fusion defect. Deliberately not fixed - it changes served coach dicts. | PROBED |
| D-01b | **100 pct of ARAM (5257) and Arena (710) calibration rows carry no `game_id`** and are permanently unjoinable to outcomes. Measured. The cause is NOT a forgotten kwarg - `coaches/aram_coach.py:599` hardcodes `"game_id": ""` and `core/live_metrics.py:46` states the Live Client never surfaces one for those modes. The real fix is routing the logger through the existing `core/live_metrics.py:100 match_key()` minting seam - a calibration-record schema change, not a one-liner. | **PROBED** |
| A-27b | **The Golden Spatula `224403` appears in 82 of 173 ARENA build orders.** SR and ARAM carry it zero times. Note `3600` is Kalista's Black Spear, NOT the Spatula - the slice agent misidentified it and understated the scale. Needs adjudication against `gold.purchasable` before anyone calls it the item-213 pollution class recurring. | **PROBED** |
| C-17 | The DS champ-select cluster gates on `isLive`, so `ds_matchup` is unreachable under `?ui_mock=1` and cannot be pixel-audited headless. | SOURCE-READ |
| A-01b | `core/daemon_slayer_client.py` is not seam-forwarded for `widen_carry_pool`, so the flag cannot reach RC's live carry chokepoint. | SOURCE-READ |

### Correction to PART 3 totals

Non-live-gated inventory moves from 105 to **101**: minus A-02, C-09 and the F5 row
(closed), minus A-01's original framing (rebuilt as an RM-86-shaped residual), plus the
six new rows above. Stale rows to strike moves from 9 to **13**.
