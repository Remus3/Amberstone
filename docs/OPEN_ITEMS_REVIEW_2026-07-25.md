# Amberstone - Categorical Open-Item Review (2026-07-25)

Produced against HEAD `794c5a9f`, ENGINE 1.241.0, patch 16.14.1. Loop HALTED
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
| S9 | ROADMAP RM-112 (two bullets, one CLOSED one "original") | Already correctly marked CLOSED 2026-07-23 `7f0ba303`. Listed here only so it is not re-counted as open. | SOURCE-READ |
| S10 | ROADMAP RM-81 **P0** ("`prefer_cdragon_ratios` is default-ON and its sidecar is patch-blind"), chip `task_d665f88b`, and this document's own row A-01/A-02 | **CLOSED - the P0 shipped 2026-07-18.** `46bbc24b` (guard, RED-first, `strict_cdragon_patch` DEFAULT-OFF + diagnostic) and `e1b42e89` (16.14 CDragon re-extract + strict flip to DEFAULT-ON) are BOTH ancestors of HEAD. `abilities.py:679` is `strict_cdragon_patch: bool = True`; `cdragon_sidecar_patch()` exists at `:433`. The 16.14.1 sidecar carries payload patch `16.14.1` with its own distinct hash - only the three OLDER dirs are 16.11.1 copies. **"A 16.14.1 engine is serving 16.11.1 ratios" is FALSE.** | **PROBED** (merge-base + hashes + signature) |
| S11 | BACKLOG competitor-lift **F1 lane/fight threat column** ("today `enemyIds[0]` only") | **CLOSED - shipped `35d96e79` (2026-07-20)**, an ancestor of HEAD. `enemyIds[0]` has **0 hits** in `web/js/panels/ds_matchup.js`; the file already loops `cs.their_team` and bins severity. | **PROBED** |
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
| A-01 | ~~RM-04 carry-pool filter-list~~ **BUILT 2026-07-25 (ENGINE 1.242.0, DEFAULT-OFF `widen_carry_pool`) AND THE PREMISE IS HALF-REFUTED.** Mechanism confirmed by ID: `OFFCLASS_MARKSMAN_ITEM_NAMES` (`rank.py:83-127`) applied at `rank.py:711-712` behind `_is_ranged_marksman`. Bloodsong is a DIFFERENT deny (`_SR_EXCLUDED_ITEM_IDS`, the RM-93 support-quest filter) and stays denied - lifting it was previously measured harmful. **Pool is 108, not 111** (measured in-process AND live on `:8893`). Flag-ON grows it 108 -> 112 and changes **ZERO top-8 entries for any of the seven marksmen**; Senna's Black Cleaver lands #33, Smolder's Shojin #41. **Un-filtering is necessary and NOT sufficient - the burial is scorer kit-blindness (RM-86), so the residual is L2 work.** **A-01d (the two seam-reachability residuals) SHIPPED 2026-07-25, ENGINE 1.245.0, and residual (b) was STRICTLY WORSE than filed.** (a) `dashboard/routes_state.py` `/api/ds-preview` called the dispatcher with a fixed explicit kwarg list forwarding ZERO seam flags, so no seam was reachable from the route at all - not a `widen_carry_pool` problem, it blocked all nine; `caster_missing_hp_pct` was also unreachable and is now wired. (b) The filing said `plan_build_order` lacks `widen_carry_pool`; in fact `core/build_order.py:475` ALREADY HAS `rank_kwargs` splatted into every ranker call - the plumbing existed and was unused. The real bug: `archetype_dispatch.py`'s `with_build_order` branch passed NO `rank_kwargs` and forwarded ZERO seams, and since `prefer_kit_axis_by_win` DEFAULTS TRUE a `with_build_order=True` dispatch **RANKED with that seam ON and PLANNED with it OFF - every seam diverged, not one.** Both sides now build the seam set once and agree (`test_rank_and_plan_agree_on_every_seam`). MEASURED: Corki's planned order changes (BotRK -> The Collector at slot 1), 100 pct attributable to `prefer_kit_axis_by_win`; Ezreal / Senna / Quinn show no movement and that no-op was PROVEN by a spy `rank_fn` recording all 5 planner calls now carrying the seams. `apply_squishy_burst_target` deliberately NOT exposed (defaults True, so a forward-when-truthy idiom cannot express turning it off - needs a tri-state); `score_by` is absent from `dispatch_for_coach` entirely. **A-01e: that tri-state SHIPPED 2026-07-25 (ENGINE 1.246.0).** `None` = inherit / `True` / `False`, threaded through `routes_state.py` (new `_DS_PREVIEW_SEAM_TRISTATE` + `_parse_tristate`) and `archetype_dispatch.py` (new `Optional[bool]=None` appended at the END of `dispatch_for_coach` per the mid-class-field rule, forwarded on `is not None` so RANK and PLAN agree). **`core/daemon_slayer_client.py` NOT edited and did not need to be** - `None` resolves at the route layer by omitting the kwarg, leaving the client's True default untouched. Ints deliberately REJECTED as malformed (a client sending 0/1 for "unset" would otherwise force the seam). **The byte-identical pin was EXTENDED, not relaxed:** `test_flagless_request_kwargs_are_byte_identical` is untouched and the new key joins the shared `_SEAM_KEYS` tuple, strengthening every existing no-op pin; two new pins assert the identical exact-dict for key-absent and explicit `null`. MEASURED (Caitlyn L13, Kraken+Boots, target 140/90/2800): forcing OFF swaps **3 of 8 rows by identity** (Terminus, Serylda's, Runaan's enter); `inherit == forced_on` True, `inherit == forced_off` False - the proof that absent inherits the engine default. Spy `rank_fn` recorded the kwarg as ABSENT/False/True per case, so the movement is proven from the new path, not inferred. | residual: nothing (it is now RM-86-shaped) | residual MS | ROADMAP RM-04; ENGINE 1.242.0 + 1.245.0 + 1.246.0 CHANGELOG | **PROBED / A-01d+e SHIPPED** |
| A-02 | ~~RM-81 P0 sidecar patch-blindness~~ **NOT AN OPEN ITEM - see S10.** Shipped 2026-07-18. This row was authored from stale ROADMAP prose (tier SOURCE-READ) and is retained struck so the error is legible rather than silently deleted. | n/a | n/a | ROADMAP RM-81 | **PROBED** |
| A-02b | **NEW, surfaced by the A-02 slice: six per-patch artifacts carry NO internal `patch` field at all**, and with `strict_cdragon_patch` now DEFAULT-ON, loading any of the three stale 16.11.1 sidecars would silently drop to Meraki. Same bug class as the closed P0, different artifacts. | nothing | 1S | LEDGER 1041; `46bbc24b` notes | SOURCE-READ |
| A-03 | **RM-81 re-source the 6 champions that matter.** 75 of 171 carry drifted values but only 6 change any ranked order, 2 touch a top-5, 0 change a recommended core. Re-source 6, not 75. **SHIPPED 2026-07-25 at ENGINE 1.248.0 as a CODE slice, not a data pull** - new `_ability_base_overrides.py` + `abilities.py` hook, DEFAULT-OFF, 6 champions, exactly 6 of 1033 forms move. See PART 8. | nothing | 1S | ROADMAP RM-81 | ~~AS-FILED~~ **PROBED + SHIPPED** |
| A-04 | ~~RM-99b Heartsteel damage-half cadence~~ **SHIPPED 2026-07-25 (ENGINE 1.245.0). REAL, and the filed 8.5714x is EXACT** (unlike RM-94, whose filed magnitude was wrong): `procs = duration / every_n_seconds` at `dps.py:327` makes 30/3.5 exact by construction, reproduced in 15 of 15 measurements at shipped-build depth. The over-credit supplied **13-32 pct of total credited auto DPS** on shipped bruiser builds and Heartsteel ranked #1 or #2 for every bruiser measured. **SR 3084 corrected to 30.0 DIRECTLY in the data table, DEFAULT-ON** (operator call) - no consumer wire needed since all six scorers read `ITEM_EFFECTS`. **Arena 223084 HELD at 3.5** per doctrine B: absent from Meraki, own DDragon renders `(0s)`, and Riot retuned that mirror on other axes, so 30s there would be unsourced. Seam `apply_heartsteel_cadence_fix` survives rescoped to the Arena mirror only. Regen: SR 3084 135 -> 6, ARAM 156 -> 27, Arena 223084 107 -> 107. One correction to the filing: "R137's EHP half uses the real 30s" is looser than stated - the 30 lives only in prose and its proc count is an operator-tuned constant anchored on it. **NEW residual filed: `3131` Sword of the Divine, 15.0 vs a 90s active cooldown, uncited 6x over-credit** - **SHIPPED 2026-07-25 (ENGINE 1.246.0), corrected 15.0 -> 90.0.** Sourced from its OWN DDragon feed per doctrine B (absent from Meraki): description renders `Divine Blessing ... (90(0s))` AND `effect.Effect5Amount = "90"` - two independent statements - while 15.0 is recoverable from NO field (pinned). Ratio exactly **6.0000** proc-isolated. **Three corrections to the residual as filed:** `_effects_data.py` has ONE `ITEM_EFFECTS` dict so there is no SR/mirror split; a suffix scan over all 706 ids returns exactly `['3131']` so there is no mirror; `443060`/`663060` share only the display name (Excoriate, no periodic). **And the merger's own probe was corrected by the build agent: map 21 is Nexus Blitz, NOT ARAM** (ARAM is map 12). Since `MODE_MAP_ID` wires only 11/12/30/35, **3131 is pool-illegal in SR, ARAM, ARENA and BRAWL alike** and appears in ZERO shipped build rows across all 9 table files (machine-checked with a `3006`-hits-78-times positive control). Reachable only via an explicit `compute_dps` item list, where it measured -1.87% to -6.01% across 5 champions at shipped-build depth. **A correctness fix on a near-dead path, recorded as such.** Faithful remodel DECLINED with evidence: the 100%-AS-for-3s half has no representable field (`bonus_as_conditional` is permanent, not a timed window), so modelling the crit half alone would zero the item while leaving AS uncredited - strictly worse. Needs a timed-buff-window schema lift; filed as a follow-up. | 3131 remodel: schema lift | DONE | LEDGER 1044, ENGINE 1.245.0 + 1.246.0 CHANGELOG | **SHIPPED** |
| A-05 | **RM-39 / RM-43 default-ON flip.** L1+L2 shipped DEFAULT-OFF (`apply_ad_axis_ability_damage`, ENGINE 1.222.0/1.223.0). 79 of 92 cohort champions reorder flag-ON. MIXED held, MAGIC excluded permanently. | operator decision | 1S | ROADMAP RM-39/RM-43 | SOURCE-READ |
| A-06 | **RM-98 cast-rate time base.** ADJUDICATED 2026-07-19: a GAME-AVERAGE cast rate is summed onto a COMBAT-WINDOW auto rate; ~7x characteristic (not 27x); already ships DEFAULT-ON in `ds.onhit` / `ds.dps` / `ds.hps`. Spec recommends demoting the measured rate to a cast-PROPENSITY prior, not replacing the denominator. Unbuilt. | operator decision (touches 3 default-ON scorers) | MS | ROADMAP RM-98, `docs/specs/SPEC_rm98_cast_rate_time_base.md` | SOURCE-READ |
| A-07 | **RM-40 / RM-45 / RM-47 mage cluster.** MEASURED BLOCKED 2026-07-24 at 1.240.0: Ahri / Annie / Aurora and the REFUTE control Anivia return the identical head through `/rank-mage`. The GAP champion and its own control are indistinguishable to the scorer, so no coefficient or filter edit can separate them. | schema lift (champion-sensitivity in the mage scorer = the RM-04 shape-build work) | MS | ROADMAP RM-40/45/47 block, LEDGER 1037 | SOURCE-READ |
| A-08 | **RM-35 crit-burst cohort (Miss Fortune).** R186 shipped the SYMMETRIC off-axis exclusion which covers RM-35's mirror clause; RM-35's own crit-burst cohort work (fight-length ~0.5, Hubris absent from top-20) is explicitly NOT covered. **SPLIT 2026-07-25 at ENGINE 1.247.0.** Clause 2 (the AP off-class exclusion) SHIPPED as `exclude_off_axis_items` on `rank.rank_items` + `/rank`, DEFAULT-OFF, reusing the RM-41 axis gate: MF Lich Bane #6 and Rabadon's #14 stripped (Rabadon's scores `delta_dps` 0.000 of `effective_score` 176.21), hybrid Gunblade SURVIVES #18 -> #16, pool 107 -> 71, Shaco byte-identical from a non-empty AP-carrying baseline. The live-reachable win is **Twitch, already in the shipped allow-map and serving Lich Bane at #7 today**. Clause 1 (the FL ~0.5 cohort entry) is **BLOCKED-UNFALSIFIABLE**: MF burst share 0.904 against controls Vayne 0.903 / Ashe 0.892 while MAPPED Twitch 0.828 sits BELOW all three, so no threshold separates them and a "MF lifts at FL=0.5" test passes unchanged with Ashe substituted. Filed "BotRK #1" was an empty-build artifact (real depth lead Runaan's / LDR / Terminus); "Hubris absent from top-20" holds at #23. | clause 1 is an operator-gated meta assertion | clause 2 done | ROADMAP RM-35 row, LEDGER 1036 | ~~SOURCE-READ~~ **PROBED + SHIPPED (clause 2)** |
| A-09 | **RM-36 + RM-38 AD-caster (Ezreal, Corki).** Compound POOL + MODEL: Trinity 3078 / Shojin 3161 / Iceborn / Divine filtered from the SR carry pool, and no scorer models an AD-caster. One pool fix covers both. Batch them. | nothing | MS | ROADMAP RM-36/RM-38 | AS-FILED |
| A-10 | **RM-37 + RM-42 empowered-auto crit machinery (Lucian, Akshan).** Lightslinger double-tap + Dirty Fighting 200 pct crit double-shot unmodelled; `coherence_rerank` additionally DOCKS Lucian's #1 item Essence Reaver from raw #4 to #10-18. Shared machinery, batch. | nothing | MS | ROADMAP RM-37/RM-42 | AS-FILED |
| A-11 | ~~**RM-44 Amumu magic-tank AP rush.** First tank gap; axis-neutral EHP scorer structurally cannot value an AP damage item; his highest-WR Abyssal Mask ranks #14.~~ **BLOCKED-UNFALSIFIABLE, MEASURED 2026-07-25 at 1.246.0 - see PART 6.** Abyssal is #14 for Amumu and for Mundo / Poppy / Malphite / Rammus / Ornn / Sion / Cho'Gath alike, #12 for Alistar (REFUTE) and Galio (GAP) together; shipped `balanced` order byte-identical across 6 tanks; its rank tracks enemy magic share, not the kit (#7 for Amumu AND Mundo at ap 0.90). Siblings RM-51 / RM-55 inherit. | schema lift (champion-sensitivity in `ds.ehp`) | MS | ROADMAP RM-44 | ~~AS-FILED~~ **PROBED** |
| A-12 | **RM-46 Ashe Frost + Ranger's Focus.** Crits deal no bonus damage (crit chance converts to flat AD) so IE's multiplier is largely dead on her; Phantom Dancer dead-last even in a 6-item self-whitelist. Aphelios is the contrast twin. **FROST HALF SHIPPED 2026-07-25 at ENGINE 1.248.0** (`_crit_conversion_overrides.py`, DEFAULT-OFF, plumbed to POST /rank): IE #8 -> #10, PD #36 -> #30. The filed headline was BACKWARDS - the engine UNDER-values her crit. Ranger's Focus half still OPEN. See PART 8. | nothing | 1S | ROADMAP RM-46 | ~~AS-FILED~~ **PROBED + SHIPPED (Frost half)** |
| A-13 | **RM-48 Azir soldier axis + the pet-DPS cohort.** Rerouting to `ds.onhit` still leads Liandry's and still buries Nashor's #17 - no scorer models the soldier stream. Siblings: Yorick / Malzahar / Heimerdinger. Overlaps RM-97 pet damage. | nothing | MS | ROADMAP RM-48, RM-97 | AS-FILED |
| A-14 | **RM-79 Locke / Zaahen data coverage.** Absent from Meraki's 171-champ bulk map so every kit-dependent scorer falls through to `ds.dps`. Two fixes shipped off it; the ability-data half is blocked upstream. | schema lift / upstream (Meraki) | MS | ROADMAP RM-79 | AS-FILED |
| A-15 | ~~**RM-80 Master Yi mis-ROUTED**~~ **REFUTED + CLOSED 2026-07-25 (ENGINE 1.246.0).** Category error: `ds.onhit` is the on-hit-**AP** scorer (`core/ds_onhit_ap_roster.json` = Gwen/Kayle/KogMaw only); Yi is pure AD. Probed both routes at his real 3-item core, `top=250` over the full 138-candidate set: bruiser ranks his own documented build BETTER on 3 of 4 items (Experimental Hexplate #24 vs #43, Death's Dance #37 vs #39, Wit's End #22 vs #24). 2 of his 6 meta slots are defensive (Death's Dance, Guardian Angel), which the blended `alpha*dps + beta*ehp` scorer credits and a pure-DPS scorer cannot. Slice-C bar fails outright - bruiser top-3 is BotRK (57.98% WR alt core) > Trinity > LDR (62.37% WR vs-tank 4th), nowhere near ~0%. **Sibling sweep: 44 bruiser-primary enumerated, 11 probed, 0 moved.** Nilah/Tryndamere/Yasuo/Yone scored marginally better on-hit but are killed by the family clause - `ds.onhit` sums ability+auto DPS so it over-credits AP burn for AD champs, putting Liandry's in the `/rank-onhit` top-3 for 7 of them (#1 for Yone). `champions` runtime table byte-unchanged; `_comment` broadened to general route adjudications, verdict recorded in `_held` + `_rm80_onhit_sweep`. | nothing | DONE | ENGINE 1.246.0 CHANGELOG | **REFUTED** |
| A-16 | **RM-82 Mordekaiser.** Rylai's / Riftmaker buried under a never-built AP-amp + magic-pen lead. | nothing | 1S | ROADMAP RM-82 | AS-FILED |
| A-17 | **RM-83 Naafiri / RM-85 Nasus / RM-96 Zilean / RM-97 Zyra.** Four remaining per-champion GAP specs, each needing its own RED-first slice. RM-85 is RC-2 pool membership; RM-97 is the pet-damage class shared with A-13. | nothing | 1S each | ROADMAP RM-83/85/96/97 | AS-FILED |
| A-18 | **RM-87 intra-pool `ds.ehp` weighting (Ornn / Rammus).** ~~Resists pay twice while a self-EHP objective counts them once.~~ **SHIPPED 2026-07-25 at ENGINE 1.247.0 - and the double-count reading was REFUTED.** `ehp.py:1926-1927` counts each resist exactly once and `_item_resist_grants.py:255-257` already de-dups by family; the real defect is the INVERSE, a single-count UNDER-credit, because `ehp.py` imports no abilities and reads zero `damage_blocks` so a kit that converts its own resists into damage is paid only for surviving. NEW `_resist_damage_coupling.py` (6 rows, machine-swept saturated), credited SORT-ONLY in `_base_key`, DEFAULT-OFF. Ornn Thornmail #16 -> #11, Kaenic #6 -> #3, Warmog's #2 -> #7; Poppy control byte-identical ON. | n/a | done | ROADMAP RM-87 | ~~AS-FILED~~ **PROBED + SHIPPED** |
| A-19 | **RM-88 Pyke.** A throughput objective cannot price a discontinuous execute threshold plus a gold-and-reset economy. Objective-shape work, not a coefficient. | schema lift | MS | ROADMAP RM-88 | AS-FILED |
| A-20 | **RM-89 Quinn.** First champion carrying BOTH RC-1 and RC-2 - the proof that the shipped L1 kit-conversion lever is necessary and provably INSUFFICIENT. **BOTH SLICES SHIPPED 2026-07-25 at ENGINE 1.248.0** - the filed claim was FALSE AS MEASURED (Quinn was not in `_KIT_CONVERSION`, so the lever was exactly inert for her). BotRK #1 -> #31; pool 107 -> 109. Stormrazor does NOT move. See PART 8. | nothing | 1S | ROADMAP RM-89 | ~~AS-FILED~~ **PROBED + SHIPPED** |
| A-21 | **RM-90 support-cohort build-order collapse.** Verified against the shipped `build_orders_sr.json`; prior Alistar / Blitzcrank / Braum / Bard / Rakan REFUTEs judged TOO LENIENT. Check the shipped build order before any new team-aura REFUTE. **S1+S2 PLUMB SHIPPED 2026-07-25 at ENGINE 1.248.0 and the ACCEPTANCE CRITERION IS REFUTED** - the tank distinct-order count does NOT move off 1-of-28 in any of 7 cells; Locket is live at the RANKING level but never wins a greedy slot. Order-level movement needs the S3 schema lift. See PART 8. | S3 schema lift | MS | ROADMAP RM-90 | ~~AS-FILED~~ **PROBED + PARTLY SHIPPED** |
| A-22 | **RM-91 HP-as-damage.** Bonus HP is scored EHP-only, so kits converting health into damage are undervalued; Randuin's is engine #1 for five tanks and in the real core of none. Tahm Kench vs Taric is the matched pair isolating this from RM-92. | schema lift | MS | ROADMAP RM-91 | AS-FILED |
| A-23 | **RM-92 residual = the ABILITY-HASTE class (5 champions).** SIZED 2026-07-18, verdict DEFER (`docs/specs/SCOPE_rm92_ability_haste.md`). The ally-facing slice already shipped (Term A `score_by="team_blended"`). All four separable tails shipped at ENGINE 1.221.0. What remains is the modelling question, which is A-06. | operator decision | MS | ROADMAP RM-92 | SOURCE-READ |
| A-24 | ~~RM-93 support-quest item candidacy~~ **REFUTED 2026-07-25 - CLOSED, NO FIX. This row described the INTENDED state as a bug, and it was already shipped in the opposite direction.** `agents/daemon_slayer/tests/test_sr_quest_line_deny_rm93.py` pins the ENTIRE World Atlas line off the SR pool and names 3871 + 3877 explicitly as "the two line items carrying modelled damage formulas, so they ranked HIGH and drew a deny" - the modelled formulas are the REASON for the deny, not evidence against it. Admitting them was MEASURED to put Bloodsong at #2 for Vel'Koz and #3 for Jinx, an RM-92 mispricing; the doctrine is `test_enchanter_pool_hsp_rm90.py:31-36` (400g mutually-exclusive quest rewards are a category error to rank against 3000g legendaries). RM-93's genuinely-open half was 3869 / 3870 / 3876 and it already shipped. **Do NOT re-open.** | nothing | CLOSED | `test_sr_quest_line_deny_rm93.py` | **REFUTED** |
| A-25 | **RM-94 snowball stacks pinned at FULL value.** `_effects_data.py:3257` pins Mejai's at +125 AP so it ranks #6 for EVERY mage at 2-5 pct real presence. Not win-rate contamination - DS default is pure simulation. | nothing | 1S | ROADMAP RM-94 | AS-FILED |
| A-26 | **RM-95 ability-data coverage (DIAGNOSTIC).** **HALF MIS-FILED, half REAL - SHIPPED 2026-07-25 (ENGINE 1.246.0).** The filed "3 name-alias misses where the data exists" is **STALE and was already fixed on disk**: roster 173 vs abilities keyspace 171, and the only misses are `['Locke','Zaahen']`. The three unbridgeable display names (Wukong->MonkeyKing, Nunu & Willump->Nunu, Renata Glasc->Renata) are already resolved by `_canon_champ_key` (`core/daemon_slayer_client.py:1147`) at every call site (`:1208`, `:1251`, `:1294`) - independently re-probed on main. No production change was needed for that half; the pre-existing alias test pinned a hardcoded list and was replaced with a data-driven 173-entry parity sweep plus an anti-vacuity guard. **The certification bug is the actual defect and is REAL:** `champion_ability_data_is_current('Locke')` and `('Zaahen')` both returned **True** on main. Fixed via new sibling `champion_ability_data_status() -> 'absent'|'stale'|'current'` (ABSENT beats STALE), old bool kept as a thin wrapper. Option (a) chosen over a bool-contract flip on a real caller inventory: `is_current` has **ZERO production callers**, `champion_has_ability_data` has one (`:1557`); ABSENT and STALE stay separate because they are differently actionable (STALE = data refresh, ABSENT = blocked upstream). Two-directional fail-soft preserved by construction. Mutation-checked 10/4/3 red. **RM-95 splits: 95a closed, 95b (sourcing Locke/Zaahen kits) genuinely open.** | 95b: blocked upstream in Meraki | DONE | ENGINE 1.246.0 CHANGELOG | **SHIPPED (half refuted)** |
| A-27 | **RM-114 NEXT BUY gold feed.** `item_advisor.resolve_build` returns a build for exactly **6 of 172** champions (operator's own pool). The widget is faithful; the feed is empty for 97 pct of the roster. Two routes: re-source `next` from DS (173 champs, live at `:8893`) or widen `item_advisor`. The DS route changes what "next item" MEANS. **CLOSED - ALREADY SHIPPED, re-probed 2026-07-25:** the DS route landed 2026-07-24 as `core/next_buy_fallback.py` and is DEFAULT-ON (kill `RC_NEXTBUY_DS_FALLBACK=0`), wired at `dashboard/_liveclient.py:385` and consulted only when `resolve_build` returns `[]`. Live in-process check: Amumu / Ornn / Viego all return real SR orders. The next-session prompt re-filed this as a fresh build target from `item_advisor.py` alone; that was a duplicate. | n/a | n/a | ROADMAP RM-114 | ~~SOURCE-READ~~ **PROBED** |
| A-28 | **RM-14 gated flip levers.** The canonical index of default-OFF seams awaiting a default-ON flip (`gate_ammo`, `apply_mode_modifiers`, `aoe_targets_hit`, `apply_ability_haste`, `apply_passive_damage`, assassin keystone auto-enable, `assume_missing_hp_heal_amp`, `rune_procs` into burst, the enchanter-registry 5). RM-19/20/21 fold into it. | live-game-gated + operator decision | MS | ROADMAP RM-14 | SOURCE-READ |
| A-29 | ~~BACKLOG R129 Viego R + the CDragon surplus-block class~~ **SHIPPED 2026-07-25 (ENGINE 1.245.0, DEFAULT-OFF `apply_cdragon_surplus_ad`). Mechanism HELD; the general fix and one number are REFUTED.** Confirmed overwrite-only at `abilities.py:723` with a cardinality guard falling the form back to Meraki; Viego R measured **0.000 -> 1.169** DPS at L16 full HP (the filed "~130" is per-CAST damage, not DPS). **All five filed siblings are FALSE POSITIVES** on their own effects text - Pyke R is an execute health THRESHOLD, Rengar R an auto-empower, Quinn R is `form_index` 1 and unreachable, Yorick R a pet, Jinx Q an auto modifier - and each has zero Meraki damage blocks so no fix can reach them. **Viego is the entire population (1, not 6).** **Option (b) the general APPEND seam is REFUTED on measurement:** 329 blocks across 220 pairs, 65 of which already carry >= as many Meraki blocks as the sidecar resolves, and 8 of 8 spot checks duplicated coefficient-for-coefficient. **LEAP-06's D2 is also corrected: an APPEND is INERT** - `block_strategy="first"` reads `damage_blocks[0]` only and Viego has no `champion_block_index.json` entry, so index 1 is never read. Shipped as a field-level MERGE into block 0 instead; block count stays invariant. This is LEAP-06 Sub-fix A (never executed); Sub-fix B is the shipped `apply_ad_axis_ability_damage`. | nothing | DONE | LEDGER 1044, ENGINE 1.245.0 CHANGELOG | **SHIPPED** |
| A-30 | **BACKLOG R129 bruiser/hybrid ability-DPS XOR.** `hybrid.py` scores damage as strict XOR - AD-axis champs score on AUTO DPS only and their non-zero ability DPS is never summed. A BLANKET sum is REFUTED-unsafe (double-counts auto-empower kits). Safe shape = `blend_ability_axis` bool + empty per-champ opt-in table. Overlaps A-05. **CLOSED - ALREADY SHIPPED, measured 2026-07-25:** this IS `apply_ad_axis_ability_damage` (ENGINE 1.223.0, `hybrid.py:687/1236/1336`, 37 pins). Flag ON moves 27-38 of 40 rows for Riven / Jarvan / Renekton / Viego, AP control unmoved; for Riven the two formulations are numerically identical (87.0619). B's residual = MAGIC rows + `item_proc_dps`, both refuted by name at RM-39, and its double-count premise is refuted at `dps.py:808-826`. Do NOT build `blend_ability_axis`. Successor = the A-05 default-ON flip. | n/a | n/a | BACKLOG bullet 2, LEDGER 903 | ~~AS-FILED~~ **PROBED** |
| A-31 | **BACKLOG R67 Terminus Light-side caster resists.** 6-8 armor+MR per stack x3. Needs an item-keyed conditional resist-grant path (`_passive_resist_overrides.py` is champion-keyed only). Source the Arena mirror `223302` from its OWN feed entry per doctrine B - do not assume Light-side magnitudes match SR. **SR HALF SHIPPED 2026-07-25 at ENGINE 1.247.0; the filed schema-lift blocker was STALE BY 8 DAYS** - `_item_resist_grants.py` IS the item-keyed lane and landed 2026-07-11 (R106, ENGINE 1.199.0), and its own docstring says so verbatim. SR `3302` credited as an explicit 18-tuple (18 / 21 / 24 total at L1 / L11 / L14, `conditional_probability=1.0` matching the already-shipped Dark half of the same clause). **Arena `223302` deliberately NOT credited:** no on-disk feed states a Light magnitude, so it is recorded in the new `_ITEM_RESIST_UNSOURCED_MIRRORS` rather than inheriting the SR value by arithmetic. | n/a (no schema lift was needed) | done | BACKLOG | ~~AS-FILED~~ **PROBED + SHIPPED (SR half)** |
| A-32 | **BACKLOG R190 kit-penetration tails (a)-(e).** (a) Annie R 15/17.5/20 pct magic pen absent from `_ANTITANK_REGISTRY`; (b) registry rows carry no `axis` field so SHRED / PERCENT_PEN cannot distinguish armor-side from magic-side (KSante R is an exemption-based pin today); (c) Amumu P registered SHRED 0.6 but 16.14.1 is a 10 pct bonus-true vulnerability; (d) kit-pen magnitudes are max-rank only. **(e) gates the rest:** the target model carries ONE scalar armor with no base/bonus split, so percent-of-BONUS-armor pen (Yasuo R 60 pct, KSante R 50 pct) is registered-but-not-credited. | (a)(c) nothing; (b)(d) nothing; **(e) schema lift** | (a)(c) 1S, (b)(d) 1S, (e) MS | BACKLOG (FUTURE, from R190 / LEDGER 1040) | PROBED (`_kit_penetration.py` on disk, 15906 B) |
| A-33 | **BACKLOG DS cross-eval Tier-2 nominations.** (A) ARAM archetype-override table - kit-default archetype disagrees with the ARAM win-axis for a cluster; the `data/cs_archetype_picks.json` mechanism exists. (B) champion-kit-aware DPS crediting - AD scorers emit a near-identical BotRK/Runaan's/Kraken template regardless of kit; B1 = melee-applicability gate. (F2) gold-aware top. Each gated on per-champion rewind-WIN validation FIRST. | operator decision (A = off-meta-chase call) | MS each | BACKLOG, `ops/audit/ds_cross_eval/SYSTEMIC_FINDINGS.md` | AS-FILED |
| A-34 | **BACKLOG G6 cost model / cost-ignoring optimum.** DSP9 proved this - not comp-awareness or runes - is the residual driver of the lolmath-vs-DS gap. Gemini verdict was leave-FUTURE: a raw gold cost model conflicts with DS's empirical-WIN anchoring. Do not build blind. | operator decision | MS | BACKLOG | AS-FILED |
| A-35 | **BACKLOG Item Shaper full re-rank engine seam.** The shipped strip is an honest emphasis PREVIEW; `rank.py rank_items` takes NO weight-dict input and the archetype blend is 2-axis [alpha,beta], not 3-axis. Needs a defined 3-axis weight surface + threading it through the rank path. | schema lift + operator decision (which weight surface) | MS | BACKLOG (FUTURE, from OQ14) | AS-FILED |
| A-36 | **BACKLOG lolmath-wiki sidecar remaining scalar lanes.** `action=bucket` non-ARAM mode-mults (Arena/URF/NB), static-cooldown flags, charge model. Extractor + per-patch data in place through 16.14.1. DATA CEILING: only 61/171 champs have a real AA cast time in ANY source. | operator decision | 1S each | BACKLOG | AS-FILED |
| A-37 | **BACKLOG target-current-HP pct FLIP.** Seam fully wired at default 1.0 (byte-identical); open work is choosing a live fight-average value. Owes an ENGINE bump. **Do NOT touch the genuine pct-MAX-HP procs** (Eclipse 6692, Titanic 3748, Hullbreaker, Azakana's, Reaper's Toll 443090) - an investigating subagent already made that Eclipse mistake. | operator decision | 1S | BACKLOG | AS-FILED |
| A-38 | **BACKLOG situational / alternative builds (crit-vs-on-hit).** The engine emits ONE DPS-max build per champ; a real enhancement is >1 build keyed to matchup (vs-squishy crit, vs-tanky on-hit). Covers Kalista / Caitlyn / MF / Tristana. Larger DS feature. | schema lift | MS | BACKLOG | AS-FILED |
| A-39 | **BACKLOG boot-utility scorer v2 inputs.** Feed real per-champion enemy CC into `_select_boots` (v1 uses an AP-share proxy); MS boots need a kite/poke signal to ever win. The default-ON flip itself is live-gated and lives in the gated doc. **CC HALF SHIPPED 2026-07-25 at ENGINE 1.247.0** (DEFAULT-OFF, opt-in by passing `enemy_champions`): `boot_utility.comp_cc_signal()` replaces `core/build_order.py:255` `cc_proxy = float(enemy_ap_share)` with the real `cc_output.compute_cc_output(...).total_lockdown_score` (161/173 registered) against `_CC_LOCKDOWN_REF = 3.0` resolved at CALL time, returning `None` not 0.0 when unreadable. At a balanced 0.5/0.5 split so share cannot explain the delta: heavy-CC comp 1.0000 vs CC-less control 0.0433 where the proxy said 0.5000 for both; tank/bruiser/hybrid/ehp flip 3047 -> 3111 on heavy CC only. **Best result is a REMOVED FALSE FLIP:** an AP-heavy CC-less comp used to hand a MARKSMAN Mercury's 3111 and now keeps Berserker's 3006 while the tank in the same matchup still takes 3111. **Kite/poke half deliberately NOT shipped and NOT data-blocked** - `_MS` 0.35 must clear the `_KIT` prior 1.0 plus the 15pct margin, which re-calibrates every champion, and the signal direction is ambiguous. | kite/poke half = operator calibration | CC half done | BACKLOG | **PROBED + SHIPPED (CC half)** |
| A-40 | **BACKLOG OQ24 build-coherence residuals. (1) SHIPPED 2026-07-25; (2) and (3) still OPEN.** **(1) The "OPEN DESIGN Q" was STALE - already answered on disk** in `docs/specs/leap/LEAP-04-build-order-precompute-backfill.md:84-121` (`UNVERIFIED-SKIP count: 0`), re-cited by LEAP-07:88-95, and independently re-probed 2026-07-25: `daemon_slayer_build_orders_generate.py:89` imports `plan_build_order`, whose default `rank_fn` applies `coherence_rerank` CLIENT-SIDE after the :8893 POST. **The generator does NOT bypass the dock; no ranking-path fix was needed.** Delivered LEAP-04's actual scope instead: the **FIRST Family A staleness + dock-parity guard** (`tests/test_build_orders_family_a_guard.py`, 115 collected - Family A had NO guard, unlike Family B), which **immediately caught a real live bug** LEAP-04 missed because its evidence section only probed `build_orders_sr.json`: `kit_synergy.py _SPELLBLADE_IDS` was SR-id-literal, so the carry coherence dock was **INERT IN ARENA** and Essence Reaver's mirror 223508 sat at slot 1 for 6 carries. Fixed DEFAULT-ON via a width-gated `canonical_item_id`; 3 id sets repaired, 14 mirror forms; Arena 223508 18 -> 0, SR/ARAM provably unchanged. Two LEAP-04 cites corrected: `rank_for_primary_archetype` is at `:1360` not `:1141`, and its "first 3 of one rank call" parity comparison is invalid because `build_order.py:704-724` injects a synthetic boots id at slot 2 that is never engine-ranked. **(2) Step-3 ally-synergy + NL "why X over Y" - OPEN.** **(3) Zeri AP-on-AD-marksman class - SEAM BUILT 2026-07-25 (ENGINE 1.246.0) to LEAP-07 DD1 shape; allow-map ships EMPTY, behavior byte-identical.** Membership re-measured at 1.246.0 rather than trusting the spec's 1.216.0 cell: Zeri sits strictly BELOW both pure-AD controls on both items in both cells (Lich Bane 21.87 vs Caitlyn 26.16 / Jinx 24.65; Liandry's 28.81 vs 29.98 / 29.29), so no member qualifies. **Two spec statements have DRIFTED and are corrected:** Liandry's is no longer out-of-top-40 (#2 for Zeri, #6 for Jinx - her distribution is compressed, which is not AP credit), and her Lich Bane delta is 21.87 not 32.8. **The contingency dock is NOT shipped and the spec's predicted REASON is REFUTED.** The RED probe DID reproduce (Liandry's #4, member-less), but removing Cruelty 667109 still yields it at #4, so the Cruelty-adjacency attribution is wrong. The real driver is **Dusk and Dawn 2510** (ghost-list, 60 AP) - drop it and Liandry's vanishes entirely. Decisive, independently reproduced by the merger: at identical prefix `[3153,3047,2510]` the pure-AD controls credit Liandry's MORE than Zeri (**Zeri 34.89 / Jinx 36.54 / Caitlyn 39.80**). A champion-invariant prefix effect is not a coherence artifact of this class, so a class-scoped dock is the wrong instrument. **The Cruelty data-fix alone will NOT clear this pollution.** `kit_synergy.py` untouched; stale `coherence.py:138-141` docstring replaced. | (2) nothing; (3) general item-valuation slice for 2510 | (2) MS / (3) DONE | LEDGER 1044, LEAP-04, LEAP-07, ENGINE 1.246.0 | **(1)+(3) SHIPPED** |

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
| C-06 | ~~**RM-26 vision-profile seeds are NOT WIRED.**~~ **FIXED 2026-07-26.** Confirmed exactly as filed: `config_key` is `"WxH|GlobalScale=..|ShowTeamFramesOnLeft=..|..."` (`core/hud_settings.py:133-134`), so the shipped `3440x1440.json` seed was unreachable on disk and every first run fell to `legacy_seed` at unscaled 1080p. New `resolution_seed` tier sits between the exact hit and `legacy_seed`, preferring the live integer `width`/`height` (`core/hud_settings.py:121-122`) and only parsing the key's leading token as a fallback; both paths go through the existing `validate_base`. Downstream safe: `dashboard/routes_vision_calibrator.py:204` special-cases only `legacy_seed`. Known limit preserved verbatim in the docstring, NO parity claim across aspect ratios. | nothing | 1S | ROADMAP RM-26 | ~~PROBED~~ **SHIPPED** |
| C-07 | **BACKLOG mode-specific overlay layout + out-of-game stats mode selector.** Operator-requested 2026-06-30, queued for planning, NOT built. Key the layout store by `mode_key` with a shared/default fallback; migrate the existing single layout into the SR slot; decide how the rc-shell mirror + Alt+Shift+R reset interact with per-mode slots. The out-of-game stats panel needs a SR/ARAM selector that AUTO-SELECTS ARAM. Acceptance is live-gated (`G1-06`). | nothing to build; acceptance live-gated | MS (2 sessions + audits) | BACKLOG; `G1-06` | SOURCE-READ |
| C-08 | **BACKLOG per-enemy ult power-spike readout (R125 Aggregator C lift).** RC has the edge-trigger mechanism SELF-only. Per-enemy champion level is NOT in the Live Client envelope today - `dashboard/_liveclient.py:101` sets level from the ACTIVE player only and the `players` list carries only position/team/creep_score/is_active. Needs a one-field backend extract + a new stateful panel, so NOT presentation-only. | nothing | 1S | BACKLOG (FUTURE, R125) | AS-FILED |
| C-09 | ~~BACKLOG F1 lane/fight threat column~~ **NOT AN OPEN ITEM - see S11/S12.** Shipped `35d96e79` 2026-07-20. **A real defect was found in the shipped grid instead and fixed 2026-07-25:** it kept the pre-F1 `hide-on-not-ok` guard, so a pending or `no_matchup` HEADLINE collapsed all four other enemy rows and popped them back on landing - a direct `feedback_no_reflow_on_data_absence` violation. Also corrected `--` to the repo `-` sentinel. 5-phase audit run, 1 MUST-FIX (verdict track would two-line on `BACK OFF`) resolved in-slice. | n/a | n/a | BACKLOG F1/F5; commit in this session | **PROBED** |
| C-17 | ~~the whole DS champ-select cluster gates on `isLive`~~ **FILED CAUSE REFUTED + REAL CAUSE FIXED 2026-07-26.** The `isLive` claim is FALSE: `?ui_mock=1` sets `lcuPhase: "InProgress"` (`web/js/main.js:1393`), so the gate always passed and `am-sub` rendered "SR - Jinx - phase InProgress" while every card stayed hidden. **REAL cause: `_amDsSyntheticCs` called `parseInt(_resolveChampId(slug))`, but `_resolveChampId` returns a SLUG** (`web/js/lib/items_index.js:111` reads `CHAMPS.byName`, verified in-page returning `"Jinx"`), so `parseInt` was always NaN -> `myId = 0` -> early return hiding all seven cards. Same defect a second time on the enemy loop, so `their_team` was always empty. **This was NEVER mock-only - the cluster was dead in every real game too** (8 consumers: sweep / matchup / combo / relscore / profile / knobs / statcheck + the L4 capability-gap chip). Fixed by one shared `_champNumericKey` helper collapsing three duplicate implementations. LIVE-PROVEN: all 7 cards SHOWN, matchup renders "Jinx vs Kaisa BOT LANE / BACK OFF / 15% / 26% removed". | nothing | 1S | `35d96e79` commit message; this session | ~~SOURCE-READ~~ **PROBED + SHIPPED** |
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
| C-17 | ~~The DS champ-select cluster gates on `isLive`~~ **REFUTED + FIXED 2026-07-26** - see the C-17 row above. The `isLive` gate always passed; the real cause was a slug fed to `parseInt`, and the cluster was dead in LIVE games too. | ~~SOURCE-READ~~ **PROBED + SHIPPED** |
| A-01b | ~~`core/daemon_slayer_client.py` is not seam-forwarded for `widen_carry_pool`~~ **CONFIRMED + FIXED 2026-07-26.** Threaded through `rank_for` (`:156`, body injection `:230-231`) and `rank_for_primary_archetype` (`:1411`, forwarded `:1801`, CARRY-ONLY). **A-01c follow-through:** the seam still could not reach a coach, because `coach_integration/archetype_dispatch.py` assembles an explicit kwargs whitelist rather than a passthrough - now closed at `:230` + `:294-295`, so the chain is unbroken coach -> `agents/daemon_slayer/rank.py:1141`. **Two residual gaps CONFIRMED, deliberately NOT fixed:** `dashboard/routes_state.py:612-619` forwards ZERO seam flags (pre-existing, affects all nine, not just this one), and `core/build_order.py:622` `plan_build_order` has no `widen_carry_pool`, so a `with_build_order=True` dispatch ranks widened but PLANS un-widened. | ~~SOURCE-READ~~ **PROBED + SHIPPED** |

### Correction to PART 3 totals

Non-live-gated inventory moves from 105 to **101**: minus A-02, C-09 and the F5 row
(closed), minus A-01's original framing (rebuilt as an RM-86-shaped residual), plus the
six new rows above. Stale rows to strike moves from 9 to **13**.

## PART 5 - WHAT THE 2026-07-26 BUILD SESSION PROVED (second build off this inventory)

Five slices dispatched against the PART-4 rows plus A-25. **All five were REAL -
none collapsed.** That is the difference PART 4 predicted: PART 4's rows were
written after probing, and every row tagged PROBED reproduced exactly.

| id | outcome |
|---|---|
| A-27b | **REAL.** Item 213 denied ONE of THREE purchasable Golden Spatula ids. `224403` was the FIRST BUY in 104 of 246 branch-instances across 82/173 Arena champions - the PART-4 note said "slot 3", which understated it. Sibling sweep found `443064` too, reachable only by an ID-SUFFIX pass. Arena regen 82/173, 246 -> 0. |
| A-25 / RM-94 | **REAL, wrong constant.** 125.0 -> 25.0. **The filed "#6 for every mage" was itself an `item_ids=[]` artifact - at depth it was #9.** Now 33-35. Build orders unchanged in all three modes; the movement is on the rank route + NEXT BUY only. |
| B-01b | **REAL.** Shipped DEFAULT-OFF: default-ON would have regressed the ARAM Mayhem augment-select path via the `is_augment_select` alias. 104/232 shadow records change. |
| D-01b | **REAL.** Producer + consumer + a 572-row backfill. Joins 41 -> 50, observations 378 -> 462, first ARENA cell. ARAM's 5257 rows are provably unrecoverable. |
| A-02b | **REAL but MIS-COUNTED - two artifacts, not six.** Ten of twelve already carried a marker in one of five spellings. Guard ships DEFAULT-OFF on measurement. |

### Corrections this build made to PART 0-4

- A-25's cited `_effects_data.py:3257` is `:3309`.
- A-02b's "six per-patch artifacts" is **two**.
- D-01b's keyless-row count is **6109**, not 5967 - 142 SR rows are also keyless.
- A-27b's "slot 3" is a slot CENSUS: index 0 x104 / 2 x121 / 3 x15 / 4 x2 / 5 x4.

## PART 6 - WHAT THE THIRD BUILD SESSION PROVED (2026-07-25, ENGINE 1.247.0)

Five rows were named by the hand-off prompt. **Three dissolved under probe** - two
were already shipped and one is unfalsifiable - so two replacement rows were pulled
from this inventory. Running total across three sessions: **9 mis-files caught
before any code was written.** The rate is NOT falling, and the reason is now
legible: the mis-files are no longer bad research, they are **stale research**. Two
of this session's three (A-27, A-30) were closed by work that landed 1 and 13 days
after the row was written, and a third (A-31) named a schema lift that had existed
for 8 days. A row's tier records how well it was probed, not how recently.

| id | outcome |
|---|---|
| A-18 / RM-87 | **REAL, BUILT, and the FILING WAS INVERTED.** No double-count exists (`ehp.py:1926-1927` counts once, `_item_resist_grants.py:255-257` de-dups by family); the defect is a single-count UNDER-credit, because `ehp.py` imports no abilities. Ornn+Thornmail is worth +1217.68 dEHP AND +0.327 ability_dps, and only the first was scored. NEW `_resist_damage_coupling.py`, 6 machine-swept rows, sort-only credit, DEFAULT-OFF. Ornn: Thornmail #16 -> #11, Kaenic #6 -> #3, Warmog's #2 -> #7, Heartsteel #3 -> #13. Poppy control byte-identical ON. |
| A-31 / R67 | **REAL, BUILT (SR half), BLOCKER STALE BY 8 DAYS.** The item-keyed lane the row asked for landed 2026-07-11. SR `3302` Light = 18 / 21 / 24 at L1 / L11 / L14 from Meraki's own breakpoints. **Arena `223302` refused:** no on-disk feed carries a Light magnitude, so doctrine B forbids it and it is recorded as an unsourced mirror instead. |
| A-08 / RM-35 | **SPLIT.** Clause 2 (AP off-class exclusion on the CARRY route) REAL and BUILT - and its payoff is not Miss Fortune: **Twitch is in the shipped allow-map and serves Lich Bane #7 today.** Clause 1 (FL ~0.5 cohort entry) BLOCKED-UNFALSIFIABLE: MF 0.904 vs Vayne 0.903 / Ashe 0.892, mapped Twitch 0.828 below all three. |
| A-39 | **REAL, BUILT (CC half).** The AP-share proxy is replaced by the real per-champion lockdown score. Strongest evidence is a REMOVED FALSE FLIP, not a new one: an AP-heavy CC-less comp used to put Mercury's on a MARKSMAN. Kite/poke half withheld with its reason (a `_MS` recalibration, not a data gap). |
| A-27 / RM-114 | **ALREADY SHIPPED 2026-07-24** as `core/next_buy_fallback.py`, DEFAULT-ON. The prompt re-derived the row from `item_advisor.py` alone and missed the fallback module entirely. |
| A-30 / R129 | **ALREADY SHIPPED at ENGINE 1.223.0** as `apply_ad_axis_ability_damage`. Sub-fix B's residual is MAGIC rows + `item_proc_dps`, both refuted by name at RM-39, so building it would REGRESS. Its double-count premise is refuted at `dps.py:808-826`. |
| A-11 / RM-44 | **BLOCKED-UNFALSIFIABLE.** Abyssal #14 for the GAP champion and for 7 controls; #12 for Alistar (REFUTE) and Galio (GAP) together; shipped tank order byte-identical across 6 champions. Its rank tracks enemy magic share, not the kit. |

### Corrections this session made to PART 0-5 and to the hand-off prompt

- A-18's filed direction is backwards. "Resists pay twice while the objective counts
  them once" is true of the GAME, and the prompt's reading of it (two additive terms
  inside one objective) is measurably false in the CODE.
- A-31's "needs an item-keyed conditional resist-grant path" was already false when
  written into the prompt.
- A-08's "BotRK #1 for Miss Fortune" is an `item_ids=[]` artifact. At her own shipped
  depth the leads are Runaan's / LDR / Terminus. Fourth headline this artifact has
  manufactured.
- The prompt's own hazard list says map 21 is Nexus Blitz; confirmed again, and
  `3302` is legal on 11 / 12 / 21 / 35 so the single SR row covers SR + ARAM + Brawl.

### A residual flagged for the operator, deliberately not taken

The A-18 registry sweep surfaced **K'Sante Q Ntofo Strikes at bonus_armor_pct 40 /
bonus_mr_pct 40**, a clean linear form that the documented K'Sante **P** reject
(`_passive_damage_overrides.py:839-843`) does not cover. It is held OUT of the
shipped registry. Promoting it is a valuation call, not a data question.

### Method note that generalises

Two fixes were measured as no-ops and were NOT. The build-order regen read 0/173
changed because it routes to the live `:8893` server, which is not
supervisor-watched and still ran the old engine; the calibration backfill read 0
new joins because it wrote a full `NA1_<id>` where the index keys the bare
suffix. **A measured "no movement" must be shown to come from the NEW code path
before it is believed.**

## PART 7 - SIX ROWS PROBED READ-ONLY (2026-07-25, fourth session off this inventory)

No code shipped for any row below. ENGINE stays 1.247.0. Six probe agents ran in
parallel, read-only, each required to age-check the cited files, grep `docs/specs/**`
plus `tests/**` before believing a row unbuilt, carry the full DS probe-trap list, and
treat BLOCKED-UNFALSIFIABLE as an acceptable answer. Two rows closed without code.
**All four survivors were mis-scoped by their filing** - none was buildable as written.

| row | verdict | what the filing got wrong |
|---|---|---|
| A-16 / RM-82 Mordekaiser | **CLOSED, BLOCKED-UNFALSIFIABLE** | inherits the A-07 `ds.ability` block; no coefficient exists to turn |
| A-10 / RM-37 + RM-42 Lucian/Akshan | **CLOSED, unmeasurable as filed** | symptom is champion-invariant across 12+ ADCs; the ER dock is intended |
| A-03 / RM-81 | BUILDABLE, 1S | it is a code slice, not a data pull - no tool can re-source 6 champions |
| A-12 / RM-46 Ashe | BUILDABLE | headline backwards - the engine UNDER-values her crit, it does not lead with it |
| A-20 / RM-89 Quinn | BUILDABLE, 2 slices | the L1 lever is exactly inert for her - she is not in the registry |
| A-21 / RM-90 support cohort | BUILDABLE, 3 slices | under-scoped - the collapse is 28-of-28 on the TANK route, not 5 champions |

### The two closures

**A-16 / RM-82** routes `/rank-mage` = `ds.ability`, the scorer already blocked at A-07.
Against the batch32 REFUTE control Ziggs at identical params (`level 13`, `items
["3047"]`, armor 100 / MR 60 / 2400 max HP / 1200 bonus HP, `top 200`): Rylai's #24 both,
Riftmaker #9 both, Liandry's #1 both. At depth the top-8 head is byte-identical across
Mordekaiser / Ziggs / Anivia / Xerath. Re-run gate-ON with `apply_ability_amps:true` -
byte-identical, so this is NOT a flag-OFF negative. The `/rank-bruiser` reroute lifts the
filed items equally for Ziggs and Rumble, champions who build neither: a cohort-wide route
shift, not champion signal. Two missing terms are now named, which is this probe's value
over a fourth invariance measurement: `ability_dps.py` holds ZERO `slow` tokens (Rylai's is
registered `defensive_only=True` in `_effects_data.py:1783-1791`), and `ability_dps.py:44-45`
excludes `P` abilities, so Darkness Rise - his whole signature - is invisible to his own
scorer. That is also why a burn item leads: the engine cannot see he already owns the burn.
Fold into the A-07 mage-cluster block as a fourth instance; do NOT re-probe standalone.

**A-10 / RM-37 + RM-42** dies on its own control. `rank_for_primary_archetype(champ,
"carry", level=16, items=["3153","3047"], armor=110, mr=52, max_hp=2500, bonus_hp=1200,
top=40)` returns Infinity Edge at **exactly #11 for Lucian, Akshan, Xayah, Tristana, Sivir
and Kalista**, and twelve ADCs emit the byte-identical shipped order `[BotRK, Plated,
Runaan's, LDR, Terminus, Yun Tal]`. The sole discriminator is membership in
`core/ds_champion_fight_length.py:105` (six champions), which BOTH filings explicitly reject
as the fix. Cleanest disproof: **Sivir IS in the aa-empower registry and is indistinguishable
from Lucian** - registry membership currently changes nothing, because the seam is gated on
`apply_ability_amps` and `_route_rank` (POST `/rank`) never parses it. The `coherence_rerank`
half is INTENDED, not a defect: `coherence.py:155-158` names Lucian deliberately, rationale at
`coherence.py:4-19`, constants marked DO-NOT-RETUNE at `coherence.py:42-54`, and
`anti_synergy_penalty("3508", champ)` is 2.500 identically for Lucian / Akshan / Jinx /
Caitlyn / Draven / Twitch. The filed magnitude does not reproduce - ER is raw **#10** at
shipped-build depth, not #4; the #4 is the empty-build artifact, now its FIFTH false headline.
**Successor row (falsifiable, subsumes RM-37 / RM-42 / RM-38):** the champion-invariant carry
on-hit bias across 12+ ADCs, where the six fight-length members are the built-in control group
and the real question is whether that map should be a hand-curated list at all.

### The cross-cutting blocker, verified in the main thread

**`agents/daemon_slayer/server.py` contains ZERO `kit_conversion` / `conversion_strength`
references.** The RM-86 L1 lever is Python-API-only, and
`tools/daemon_slayer_build_orders_generate.py` drives the shipped build tables through
`:8893`, so no kit-conversion fix can reach a shipped artifact today. This is a prerequisite
slice for BOTH A-12 and A-20, and it is why those two cannot be proven end-to-end as filed.

### Re-scoping notes for the four survivors

- **A-03 / RM-81.** The 6 champions are already on disk at
  `docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:445-620` (Mordekaiser, Naafiri, Heimerdinger,
  Azir, Malzahar, Ahri); Ahri R and Naafiri R re-verified stale in
  `data/daemon_slayer/16.14.1/champion_abilities.json`. But
  `tools/daemon_slayer_abilities_extract.py:761-774` is `--force`/`--patch` only, all-or-
  nothing, with `_EXPECTED_MERAKI_CONTENT_PATCH = "25.15"` frozen at `:128`, so re-running it
  REPRODUCES the stale numbers; the wiki extractor writes a geometry sidecar with no base
  damage. Shape is a new `_ability_base_overrides.py` registry plus an `abilities.py` hook,
  following the `_passive_damage_overrides.py` precedent. The committed
  `ability_staleness.json` baseline predates the `4f7177c9` shape fix (it still reports
  Mordekaiser Q at 389 pct against a true 4.6 pct), so any before/after must regenerate it
  first or the baseline lies. 4 of the 6 move only at ranks 8 / 19 / 25 / 37.
- **A-12 / RM-46 Ashe.** Gate passed wide against Aphelios at identical params: Ashe BotRK #1
  / Runaan's #2 / IE #8 vs Aphelios Yun Tal #1 / IE #2 / BotRK #13 - the control returns the
  opposite ordering. But the engine models `ad * (1 + 1.00c)` where correct Ashe is
  `ad * (1 + 1.15c)`, so it UNDER-values her crit by 22.9 pct at c=1.00 and a Frost model
  RAISES her crit items; what Frost correctly does is demote IE relative to pure crit-chance
  items (simulated IE #8 -> #9, PD #35 -> #29). Symptom relief lives in the on-hit half.
  Third small term: Runaan's needs its own deny (DDragon's Ashe P states Hurricane bolts deal
  no additional damage on crit), because under a Frost sim it otherwise RISES. Drop "Phantom
  Dancer dead-last" as an acceptance criterion - its Ashe value is Spectral Waltz move-speed,
  which no DPS objective contains, the same limit `kit_conversion.py:50-55` already names.
- **A-20 / RM-89 Quinn.** Separation measured 116-of-134 rows (Naafiri) vs 0-of-104 (Quinn)
  vs 0-of-103 (Jinx) at `kit_conversion_strength` 0.0 -> 1.0. `_KIT_CONVERSION` holds exactly
  8 champions (`kit_conversion.py:106-212`) and **Quinn is not one**, so the lever returns
  `_IDENTITY` and is exactly inert for her - the filed claim that L1 suppresses her three bad
  leads is false as measured. RC-2 half re-measured against `widen_carry_pool` (shipped
  1.242.0, AFTER the row was written): pool 104 -> 108, Profane Hydra 6698 + Umbral Glaive
  3179 still absent, because both names sit in `OFFCLASS_MARKSMAN_ITEM_NAMES`
  (`rank.py:107-108`) applied behind `_is_ranged_marksman` at `rank.py:1044`. Quinn is in
  neither escape hatch. Prefer a per-champion `marksman_offclass_exempt.json` entry over
  editing `CARRY_POOL_WIDEN_ITEM_NAMES`, which is class-wide. Both halves must land for the
  row's thesis to be discharged: L1 can only demote (`conversion_factor` never exceeds 1.0),
  and pool-widening alone was already measured to change zero top-8 entries.
- **A-21 / RM-90 support cohort.** Distinct 6-item orders in the shipped
  `build_orders_sr.json`, both keyspaces: **tank 1 of 28**, enchanter 2 of 11, mage 6 of 45,
  assassin 10 of 15, bruiser 21 of 44, **carry control 14 of 27**. The true support cohort
  (11 enchanter-routed + 12 Support-role tank-routed) emits **3 distinct orders across 23
  champions**. All five named REFUTEs (Alistar / Blitzcrank / Braum / Bard / Rakan) overlap
  their real `data/meta_build/sr_champion_builds.json` build **0 of 6**, while real tanks
  score 1-3 of 6 - so the route is mediocre for tanks and categorically wrong for supports.
  Bard / Rakan / Taric / Thresh were moved onto this route BY RM-84 Slice C, which swapped a
  10-into-1 collapse for a 28-into-1 one. The `_aura_caveat` pin at
  `core/ds_support_route_overrides.json:62` is falsified on its operative half: the
  `score_by="team_blended"` seam landed at ENGINE 1.220.0 AFTER it was written and is
  correctly champion-selective (Locket #22 -> #6 for Alistar / Braum / Thresh / Taric / Rakan,
  byte-identical #23 for Malphite and Ornn) but `core/build_order.py` and
  `core/build_order_precompute.py` contain ZERO `score_by` occurrences, so no shipped table
  can emit it. `_champion_ally_reach.py:152` covers 36 of 173 and omits Blitzcrank / Leona /
  Nautilus / Poppy. `_item_ally_grant.py:95-105` hard-excludes Knight's Vow 3109, Zeke's 3050,
  Bandlepipes 2524 and Solstice Sleigh 3876, so flipping the seam recovers exactly ONE of six
  real support core items - the rest are a schema lift (S3), not a coefficient. Acceptance
  metric for the whole row: support-cohort distinct-order ratio 3/23 -> >= 10/23 with carry
  14/27 unchanged and Malphite / Ornn / Sion byte-identical.

### Corrections this session made to the hand-off prompt

- **"Never run an extract in the same commit as a table regen" is UNVERIFIED.** It appears
  nowhere in code, docs, memory or `tools/precommit_gate.py`, and
  `feedback_engine_bump_ritual_order` mandates roughly the opposite (regen is step 3 of the
  same Tier-2 bump commit). Do not design a slice around avoiding it. The sibling hazard -
  never `--force` a Meraki re-extract, because `latest` is mutable - IS confirmed at three
  independent sites.
- **Any slice touching `dps.py` inherits an owed bump.** Its HEAD is `c9296b34` "wip(ds):
  G2-12 ranged reflect exposure factor - NOT SHIPPABLE, ENGINE bump owed" (2026-07-20),
  confirmed in the file's git log.
- The empty-build probe artifact claimed its **fifth** false headline this session (the filed
  Lucian "Essence Reaver raw #4"). The count in PART 6 said four.

## PART 8 - THE FOUR SURVIVORS BUILT (2026-07-25, fifth session off this inventory)

ENGINE 1.247.0 -> **1.248.0**. Four parallel worktree agents on disjoint file sets, one
Claude as sole merger. Every row below was built to its PART 7 RE-SCOPE, not to its
original filing - all four had been found mis-scoped, and two of the four re-scopes
turned out to be further wrong in the agent's favour (see the corrections at the end).

| row | verdict | headline measurement |
|---|---|---|
| prerequisite | **SHIPPED** | `kit_conversion_strength` route-exposed on POST /rank; omit == 0.0 byte-identical |
| A-12 / RM-46 Ashe | **SHIPPED (Frost half)** | IE #8 -> #10, PD #36 -> #30, Yun Tal #11 -> #8, ER #7 -> #5; Aphelios inert |
| A-20 / RM-89 Quinn | **SHIPPED (both slices)** | BotRK #1 -> #31, Runaan's #2 -> #41; pool 107 -> 109 admits `{6698, 3179}` |
| A-03 / RM-81 | **SHIPPED (6 champions)** | exactly 6 of 1033 ability forms move; Ziggs / Zed / Lux identical |
| A-21 / RM-90 S1+S2 | **plumb SHIPPED, acceptance criterion REFUTED** | tank distinct-order count **unmoved at 1 of 28** across 7 cells |

### The one refutation

**A-21 S1's own acceptance metric does not hold.** The filing asked for the tank cohort
to move off 1-of-28. It does not move, in any of 7 keyspace / profile cells, and the carry
control is 14 of 27 both ways. Malphite / Ornn / Sion are byte-identical only trivially,
because all 28 tank orders are. The plumb is not broken and the seam is live and correct
at the RANKING level - Locket moves #23 -> #6 for Alistar and #20 -> #5 for Thresh while
Malphite / Ornn / Sion / Rammus stay pinned - it simply never wins a greedy slot. At
Leona's last slot Locket scores 3116.8 team-blended against Spirit Visage 4389.6, a
1272.9 EHP shortfall where the ally credit is only +496.8. Confirmed cause is the S3
ceiling PART 7 already named: with 3109 / 3050 / 2524 / 3876 excluded at
`_item_ally_grant.py:95-105`, Locket is the only priced support core item.
**Order-level movement needs the S3 schema lift, not a coefficient and not a flag.** Do
not re-attempt S1 expecting table movement.

### Corrections PART 8 makes to PART 7

- **A-12's third term is weaker than filed.** The Runaan's crit deny is a REGRESSION
  GUARD, not a demotion: Wind's Fury is a flat `2 x 55% total AD` with no crit term
  (`_effects_data.py:184-202`), so bolt damage was already conversion-invariant
  (`per_attack_on_hit_damage` 53.27208333333334 identical ON/OFF). It is proven to bite
  in-test against Essence Reaver, whose proc DOES read `CallContext.crit_chance`.
- **A-12's ground truth is stronger than filed.** `champion_abilities.json` Ashe P states
  "Critical strikes do not deal any additional damage", which fixes 1.15 AND makes
  Infinity Edge's +0.30 inert - so the conversion REPLACES the item crit-damage sum
  rather than adding to it. PART 7 filed only the 1.15.
- **The simulated magnitudes moved.** PART 7 simulated IE #8 -> #9 and PD #35 -> #29; the
  BUILT seam measures #8 -> #10 and #36 -> #30. The built numbers are what is recorded.
- **"4 of the 6 A-03 champions move only at ranks 8 / 19 / 25 / 37" is a MISREAD** of
  `DS_ABILITY_SHAPING_NOTES.md` - that column is first divergence in the ranked ITEM
  order, not an ability rank. There is no ability rank 19. Three of the six are unchanged
  at rank 0; the drift is in the per-rank slope.
- **A-20's Stormrazor lead does not move** (#5 -> #5). Its score IS scaled 0.75x, but
  every neighbour falls further, so its rank is preserved. One filed symptom is
  unrelieved.
- **`_champion_ally_reach.py` covers 38 champions at 16.14.1, not the filed 36** (42 after
  S2).
- **`/rank-tank` already parsed `score_by`** (`server.py:639-643, :713`), so S1 was purely
  a client-side plumb - no server change was needed.

### Follow-ons this session opened

- **`apply_crit_conversion` is plumbed through `rank_items` and POST /rank** (operator-
  approved mid-session). A-12 shipped the seam in `compute_dps` only, which would have
  left it unable to reach a shipped table - the same blocker PART 7 named for RM-86. It
  reaches BOTH `compute_dps` call sites; feeding only one would subtract a converted score
  from an unconverted baseline and manufacture a delta out of the seam itself.
- **`tools/daemon_slayer_build_orders_generate.py` gained the `score_by` pass-through and
  `--score-by` flag.** The A-21 agent was scoped out of `tools/`, so the FLAT keyspace
  generator could not have emitted the seam it had just plumbed.
- **Two test premises were superseded by this session's own work and were repaired, not
  suppressed.** A-12's helper monkeypatched `rank.compute_dps`, and a call-time keyword
  now overrides a `functools.partial` keyword - it would have SILENTLY NO-OPPED, so it was
  rewritten onto the shipped code path. The prerequisite's Quinn negative control stopped
  being true the moment A-20 seeded her, so it now derives controls from
  `registry_champion_ids()`.
- **Regen result: stamp-stripped payload diff SAME on all 9 files.** Correct and expected,
  since every seam is DEFAULT-OFF. Recorded as corroboration of the no-movement claim
  rather than as a claim taken on report.

## PART 9 - FIVE ROWS PROBED, TWO BUILT, THREE CLOSED, ONE UNFILED DEFECT FOUND (2026-07-25, sixth session off this inventory)

ENGINE 1.248.0 -> **1.249.0**. Five read-only probe agents ran first, in parallel, each
required to age-check cited files, grep `docs/specs/**` + `tests/**` before believing a row
unbuilt, carry the full DS probe-trap list, and treat BLOCKED-UNFALSIFIABLE as an acceptable
answer. Four worktree build agents then ran on disjoint file sets with one Claude as sole
merger. **The mis-file rate did not fall: three of the five named rows closed without code,
and the session's largest win was a live shipped-table defect that no row had filed.**

| row | verdict | headline measurement |
|---|---|---|
| **UNFILED** alias/mirror build dedup | **SHIPPED, DEFAULT-ON** | 14 cells / 2 champions shipping FIVE-item builds; 3619 of 3633 cells byte-identical |
| A-07 / RM-82 TERM 2 passive aura | **SHIPPED, DEFAULT-OFF** | Mordekaiser ability DPS 11.677 -> 72.155; 14 of 140 rows move; 143 controls unmoved |
| carry tail: client seam plumb | **SHIPPED** | both 1.248.0 seams were 0-of-27 on the client path; now Ashe and Quinn move |
| A-26 / RM-95b Locke / Zaahen | **SHIPPED (B1), DEFAULT-OFF** | "blocked upstream" was FALSE - it is an RC-controlled roster cap |
| A-21 / RM-90 S3 | **CLOSED, BLOCKED-UNFALSIFIABLE** | ally-lane ceiling 496.8 against a 1700-4800 per-slot self-EHP deficit |
| A-12 / RM-46 Ranger's Focus | **CLOSED, BLOCKED-UNFALSIFIABLE** | Caitlyn and Master Yi show the IDENTICAL swap under an AS proxy |
| RM-37/42/38 successor | **CLOSED-WITH-A-FINDING** | 125 scalar quantities scanned; ZERO separate the six-member map |

### The unfiled defect - the best result of the session

A six-item build was naming five items. `core/build_order.py:714` rejected duplicates with a
raw string compare, and DDragon ships one item under a base id plus per-mode variants, so
`3004`/`323004` Manamune and `6676`/`667666` The Collector both survived. **Viego and Samira,
every damage profile, both keyspaces, SR only - 14 cells.** ARAM and Arena were clean.

The naive fix would have been worse than the bug. Blind structural folding of the 2-digit
prefix produced **84 FALSE POSITIVES** where `223069` Void Immolation and `443069`
Hamstringer - different items - both collapsed onto an absent `3069`, which would have
suppressed 84 legal Arena purchases. `canonical_item_id` was extended with a validated fold
(`_same_item`, name OR tags - measured over all 200 structural pairs, name alone rejects 8
real renamed mirrors and tags alone rejects 28 tag-drifted ones, union is exact), an 18-entry
catalog-derived residual alias index for the non-structural cases such as `667666 -> 6676`,
and identity-preservation for unresolvable 6-digit ids. Shipped DEFAULT-ON: the OFF position
is a known-wrong build. Proof is a full re-plan of all 3633 generated cells through both real
generator entry points - **3619 byte-identical, 14 changed, exactly the defective set** - run
twice with byte-equal diffs. The latent Locket `3190`/`323190` case found by the A-21 probe is
covered and guarded.

### The three closures

**A-21 / RM-90 S3 is BLOCKED-UNFALSIFIABLE and its population is 1, not 4.** All four
exclusion reasons at `_item_ally_grant.py:95-105` verify TRUE against their own 16.14.1 feeds:
Zeke's 3050 has zero ally-facing text on any of its three ids (pricing it is a category
error), Bandlepipes 2524 grants ally ATTACK SPEED and the only ally-offense field in the repo
(`ally_buff_credit_per_second`, `hps.py:613`) lives on the ENCHANTER route in RATE units so
mixing it is the cross-unit error the module forbids at `:23-27`, Solstice Sleigh 3876 is
pool-illegal everywhere behind the do-not-reopen RM-93 deny, and Knight's Vow 3109 is a
pre-mitigation damage REDIRECT needing an assumed-ally-stat prior that no registry carries.
**The prize was sized and it does not exist:** the entire ally lane's ceiling is 993.6 raw HP
(Locket, the largest grant in the game), amortized 496.8, against a self-EHP deficit of
1700-4800 per slot. Sweeping the amortizer gives 1 distinct order at p=0.5, still 1 at p=0.78,
and needs p=1.0 to move anything - a coefficient and an invented constant, not a schema lift.
**Also corrected: "Locket is the ONLY priced support core item" is FALSE** - Redemption 3107
(+401.4), Mikael's 3222 (+94.1) and Echoes of Helia 6620 (+28.8) are priced and in the tank
pool. The support-cohort collapse is a `ds.ehp` champion-sensitivity problem, the same
structural finding as A-11 / RM-44 and A-22 / RM-91. Do not file a fifth ally-grant row.

**A-12 / RM-46 Ranger's Focus is BLOCKED-UNFALSIFIABLE, and the row mis-names the ability -
Ranger's Focus is Ashe's Q; `data.Ashe.W` is Volley.** A per-champion self-AS lane already
exists (`_passive_as_overrides.py`, consumer `dps.py:1174`, gated `assume_passive_as_stacks`),
so this would have been a registry row - except `grep assume_passive_as_stacks rank.py`
returns ZERO, so that seam is `/dps`-scoped and provably inert in every build table. The gate
then fails on measurement: 22 self-AS blocks across 20 champions with Ashe's 75 pct ranking
about eighth, and injecting +45 pct AS as a proxy moves head-4 not at all and produces exactly
one adjacent swap that **Caitlyn and Master Yi show identically** - neither has a kit AS
steroid. The reorder belongs to the item pool at that AS level, not to the champion. The
prescription is also directionally suspect, since AS raises the very on-hit proc rate it was
meant to demote. The genuinely champion-selective term is the flurry asymmetry (110-140 pct
total AD per auto while on-hit applies ONCE); that is a different, unmeasured row.

**The RM-37 / RM-42 / RM-38 successor closes with a finding: keep the map hand-curated.** The
invariance reproduces exactly (IE at #11 for all six named ADCs; 12 of 27 shipped carries emit
the byte-identical order), but "the fight-length map is the SOLE discriminator" is REFUTED -
the client path emits 16 distinct top-6 orders over 27 champions. A brute-force scan of **125
scalar quantities** (every numeric leaf of the champion snapshot plus 12 engine axis routes)
separates the six-member map ZERO times; best near-miss still admits 4 of 21 unmapped
champions. The one corpus source that qualifies on n - `rewind_history.db`, 274890 of 274890
`CHAMPION_KILL` rows carrying `victim_damage_json`, n >= 650 for 27 of 27 because dealer keying
draws from all ten players so the 92-pct-one-account limit does not bind - does not reproduce
it either (basic-attack share mapped [21.2, 49.1] vs unmapped [0.1, 46.3], fully interleaved).
A-08 / RM-35's ordering is REPRODUCED, not contradicted. The map is purely editorial; its
provenance is the operator's live evidence recorded at `core/ds_champion_fight_length.py:66-72`.
**Fence: an allow-map entry is an operator meta assertion validated by live play, and adding
one requires operator evidence, not a threshold.**

### Corrections PART 9 makes to PART 7 / PART 8 and to the hand-off prompt

- **A-07's two named terms both survive probing, but TERM 1 is dead and TERM 2 is narrower
  than filed.** TERM 1 (slow credit / Rylai's `defensive_only`) is BLOCKED: 88 of 161
  champions in `cc_output.py`'s registry carry a SLOW entry, so crediting it lifts GAP Aurora
  and REFUTE control Anivia together. TERM 2 is real but the data premise inverts - only
  **1** of 171 champions (Aphelios) has any P `damage_blocks` from Meraki, so the P lane is
  the hand-authored 32-entry registry, and Mordekaiser was simply not in it.
- **The A-07 block premise "GAP champion and control are indistinguishable" is REFUTED.** A
  roster-wide sweep at the A-16 params returns **78 distinct top-8 heads, 20 among the 84
  AP-scaling champions**, and Anivia - the REFUTE control - is already alone in its own class
  at top-8 under default flags. The invariance was a top-3 stat-dominance artifact confined to
  a hand-picked 4-champion sample. Four sessions measured that artifact and called it a block.
- **`apply_passive_damage` does NOT already cover the P gap and this was measured.** Forcing
  it ON injects Aurora's P block and the mage scorer is byte-identical, because `SPELL_KEYS`
  never reads `P`. A distinct `apply_passive_aura_damage` kwarg was required because the
  existing registry mixes cadences: 25 entries are `on_hit` riders belonging on the auto clock,
  and the `dot` cadence authors a TOTAL over a burn duration, not a per-second rate.
- **RM-82's own acceptance hope is refuted by the build that satisfied its criterion.**
  Rylai's does NOT move - #24 OFF, #24 ON. Its value is the slow, and aura damage does not
  price a slow. TERM 2 shipped anyway because its blast radius is provable; the Rylai's
  question needs TERM 1, which is blocked.
- **A-26 / RM-95b was mis-filed as "blocked upstream in Meraki", and the answer had been on
  disk for seven days** at `docs/specs/DECISION_cdragon_cross_reference.md:150` (`ed5ddc72`,
  2026-07-18), titled verbatim "RM-79 is NOT blocked upstream. RC's own extractor filters
  Locke and Zaahen out". The four "independent" 171-keyed sidecars are ONE feed - every one
  derives its champion list from `champion_abilities.json`. **CDragon bins for both exist**
  (HTTP 200, 57068 B and 55748 B, at the URL the ratio extractor already uses), so that spec's
  own `:458` contradicted its `:182-186` and is now reconciled.
- **B1 is a partial and is recorded as one.** The de-cap buys cast times, cooldowns, CC tags
  and geometry - not damage. `wiki_ability_stats.json` carries no `leveling` key and no damage
  field for ANY champion, and DDragon supplies none either (`spells[0].vars == []`,
  `effectBurn == [None,'0','0','0']` for Locke, Zaahen **and Ahri**). **Locke's
  `/rank-assassin` `baseline_burst` still reads 0.0** against Zed 938.46. B2 stays open.
- **Two 1.248.0 seams were inert everywhere that matters.** `apply_crit_conversion` and
  `kit_conversion_strength` were parsed by the server and accepted by the engine but absent
  from `core/daemon_slayer_client.py`, so the chokepoint every live coach tick and every
  generated table passes through could not forward them: 1-of-27 movement on `/rank` direct,
  **0-of-27 on the client path**. This is `reference_ds_kit_conversion_not_route_exposed` one
  layer further down the stack, and it is worth checking on every future seam.
- **The empty-build artifact claimed no new headline this session.** Every probe carried an
  explicit non-empty item list and explicit non-zero target stats. The count stays at five.

## PART 10 - FIVE ROWS PROBED, FOUR CLOSED WITHOUT CODE, AND THE PROBES ALL FOUND THE SAME BUG (2026-07-25, seventh session off this inventory)

ENGINE 1.249.0 -> **1.250.0**. Five read-only probe agents ran first, in parallel, each on a
different menu row. **For the first time in this program they converged: every one of the five
independently surfaced the same systemic defect, and no row had filed it.** Three worktree build
agents then ran on disjoint file sets with one Claude as sole merger.

| row | verdict | headline measurement |
|---|---|---|
| **UNFILED** the three-gate seam census | **MEASURED + GUARDED** | 43 route-parsed seams, **9** reachable through the client, **34** stranded |
| A-11 / RM-44 + A-22 / RM-91 + A-21 S3 | **CLOSED, PREMISE REFUTED** | champion-sensitivity in `ds.ehp` shipped at 1.247.0; the invariance is two 0.5 constants |
| assumed-share exposure (the real fix) | **SHIPPED**, byte-identical by default | Randuin's #1 -> #6 forced off; +49.7 pct armed |
| A-26 / RM-95b B2 Locke + Zaahen | **SHIPPED, DEFAULT-ON** | burst 0.0 -> 418.61 / 959.79; Locke's whole SR build corrected |
| A-13 / RM-48 Azir soldier axis | **CLOSED, BLOCKED-UNFALSIFIABLE** | nine mages, pet or no pet, all return Liandry's #1 / Nashor's #16-19 |
| **UNFILED** degenerate DPS fallback | **SHIPPED, DEFAULT-ON** | 3 of 173 champions shipped `weighted_dps == 0.0` silently |
| A-32 / R190 kit-pen tails (a)-(d) | **CLOSED, 3 of 4 MIS-FILED** | row names the wrong module; (c) is intended behavior |
| A-17 RM-85 Nasus | **MIS-FILED** | five routes return the IDENTICAL 135-item set |
| A-17 RM-83 Naafiri | **SHIPPED-ALREADY, gate-blocked** | seeded 2026-07-18; `/rank-assassin` swallows the flag |
| A-17 RM-96 Zilean | **REAL, specced, not built** | cast rate 0.00424, 15.9x below Soraka - cleanly separable |

### The convergent finding - a DS seam has THREE gates and most seams clear one

Every probe hit this from a different direction, so it is recorded once here rather than five
times. Measured in the main thread, not inherited:

- **43** seam-shaped kwargs are parsed by `server.py` route handlers.
- **9** are expressible through `core/daemon_slayer_client.py`.
- **34** are default-OFF and stranded.

`core/daemon_slayer_client.py` is the chokepoint that every generated build table and every live
coach tick passes through. `rank_for` (24 params), `rank_tank_for` (15) and
`rank_for_primary_archetype` (40) carry **no `**kwargs`**, and `core/build_order.py`'s own
docstring says its `rank_fn` takes none either - so a stranded seam cannot be smuggled through
`rank_kwargs`. This was verified by calling `inspect.signature` on all three, not by grep.

The consequence is not academic. **A-28 / RM-14 is filed as "the canonical index of default-OFF
seams awaiting an operator decision". Even if the operator decided, there is no wire.**

Named casualties, each independently confirmed:

- `apply_ability_base_overrides` - the A-03 / RM-81 six hand-authored ability-base corrections,
  selected precisely BECAUSE they change a ranked order. **Zero** occurrences in `server.py`,
  `rank.py` and the client. Reachable only from its own test file. Six known-wrong ability bases
  are live in every shipped table.
- `apply_passive_aura_damage` - **shipped one release earlier at 1.249.0.** Cleared gates 1 and 2,
  dead at gate 3. The hand-off prompt that shipped it carried the warning about exactly this.
- `_kit_penetration.py` - the entire 15.9 KB module has **zero production callers**; its only
  non-test reference is a docstring mention at `effects.py:596`. Darius 40 pct, Ambessa 30 pct and
  Pantheon 30 pct are as uncredited as the bonus-armor rows the BACKLOG singles out.
- `kit_conversion.py` (RM-86 L1) - a curated, prose-justified, test-guarded 9-champion registry
  that reaches **1 champion**. `server.py` parses `kit_conversion_strength` at exactly one site
  (`:481`, CARRY), and `hybrid.py` contains **zero** occurrences, stranding Olaf / Pantheon /
  RekSai / Riven at gate 1. Memory `reference_ds_kit_conversion_not_route_exposed` reads as
  resolved by `27ffd8de` and is not.

Shipped this session: `test_route_seams_reach_the_client.py` collects the route-parsed seam set by
introspection and asserts client expressibility, carrying the stranded set as an explicit debt
ledger. GREEN on arrival, RED the moment a new route seam ships without a wire.

### The headline row was mis-filed, and the real cause was two constants

**A-11 / RM-44, A-22 / RM-91 and A-21 / RM-90 S3 had all independently named "champion-sensitivity
in `ds.ehp`" as their blocker and successor. That prerequisite already shipped at 1.247.0.**
Forcing `_resist_damage_coupling` ON reorders 43 rows for Ornn, 38 Taric, 40 Galio, 24 Rammus,
21 Rell, 19 Malphite, with Poppy and Amumu byte-identical as controls.

The residual invariance is `ehp.py:1212-1218`, which sets `assume_item_crit_dr`,
`assume_item_aa_dr` and `assume_item_enemy_as_slow` to **True** off two champion-blind module
constants, `_ASSUMED_INCOMING_CRIT_SHARE = 0.5` (`:521`) and `_ASSUMED_INCOMING_AA_SHARE = 0.5`
(`:559`). `rank_items_by_ehp` exposed none of the three and `server.py` parsed none, so no caller
could disable them. Measured (Amumu L13, SR, prefix `['3068','3047']`, shares 0.50/0.50):

| item | armed | forced off | delta |
|---|---|---|---|
| Randuin's 3143 | 2419.9494 | 1616.2956 | **+49.7 pct** |
| Frozen Heart 3110 | 1209.3659 | 774.1125 | +56.2 pct |
| Warmog's 3083 (control) | 2097.5007 | 2031.2375 | +3.26 pct |

Head flips `3143, 3083, 3084, 6665, 2504, 3053` -> `3083, 3084, 2504, 6665, 3053, 3143`.

Corroborated against the shipped artifact rather than asserted: `build_orders_sr.json` `mixed`
carries 58 distinct orders over 173 champions with a largest cohort of **28 sharing one
byte-identical order led by 3143**; `burst_heavy` 63/28; `frontline_heavy` 56/25. The `poke`
profile, which targets a squishier dummy, drops Randuin's to slot 6 - the tell. 71 of 173
champions carry 3143 somewhere in their SR order.

All three candidate lift shapes were REJECTED on measurement, not on taste:

- an RM-91 HP-to-damage sort credit at the shipped calibration moves **one row across seven
  champions** (Warmog's 800 HP at Cho'Gath's 10 pct = +1.98 pct against a 15.37 pct gap to #1);
- extending the resist coupling from sort-only to scored credits ARMOR, so it **raises** Randuin's
  and pulls opposite to RM-91;
- importing `damage_blocks` into `ehp.py` is a genuine unit-mixing lift with no defensible
  conversion constant, plus the partial-module cycle risk its own lazy-import comment documents.

**Do not re-file this as a schema lift.** The lift exists; the constants are the row.

### The two unfiled defects that shipped

**Three champions shipped `weighted_dps == 0.0`, silently.** `dps.py` gated the degenerate-scenario
fallback on `not any(phase_dps.values())`, so a champion with a real early rotation and an empty
late one never tripped it. Azir 0.0 -> 94.325, Karthus 0.0 -> 63.903, Viktor 0.0 -> 70.792; the
other 170 byte-identical on `(weighted_dps, raw_attack_dps, mode_multiplier, phase_dps, notes)`.
**This is the actual cause of the four-session A-13 / RM-48 misdiagnosis:** `onhit_dps.py:162`
computes `onhit_dps = ability_dps + baseline_auto_dps`, so a 0.0 made `/rank-onhit` return a
`/rank-mage`-identical response with `notes == []`, and four sessions read that as a missing pet
model. Recorded caveat, in three places in-source: the fallback credits AD/crit, which is the
**wrong model for Azir** (soldiers scale 45-65 pct AP, zero AD). It ships because a 0.0 breaks
every blended scorer that weights on it. Do not cite it as "Azir's soldiers are modelled".

**Two champions had no ability data at all.** Roster 173, ability keyspace 171, difference exactly
`['Locke','Zaahen']`; champions with zero damage-kind blocks: 0. `abilities.py:1076` iterates the
snapshot, and every existing override registry AMENDS a form rather than INJECTING a champion.
New `_ability_wiki_damage_registry.py`, 10 hand-authored forms, injected keys-not-present-only,
DEFAULT-ON (a champion the snapshot lacks has no prior behavior to preserve). Locke `baseline_burst`
**0.0 -> 418.6104**, Zaahen **0.0 -> 959.7884**, Zed control exactly 807.3862433862435 unchanged,
171 of 171 pre-existing champions byte-identical, 0 degenerate rows left.

**Locke's shipped SR build was wrong and is now right:**

```
old  3153 BotRK / 3111 / 3097 / 3078 Trinity / 3036 LDR / 3031 IE      (a marksman build)
new  6653 Liandry's / 3111 / 2503 Blackfire / 3135 Void / 4645 Shadowflame / 4646 Stormsurge
```

Zaahen's order correctly did NOT move - his authored damage is PHYSICAL (Grim Deliverance
+200 pct bonus AD), so the AD template already pointed the right way. Six of nine tables changed,
Locke-only, proven by a stamp-stripped payload diff.

Three transcription corrections were made against the live wiki by the build agent and
independently re-verified by the merger via the wiki API: **Grim Deliverance is `(+ 200 pct bonus
AD)`, not the 50 pct in the brief; `Ritual Nails` is LOCKE's Q, not Zaahen's; and that page carries
`leveling` = Armor Penetration with damage in `leveling2`.** The last one matters: `_evaluate_block`
does not filter on `attribute_kind` and `_select_blocks` reads `damage_blocks[0]`, so an armor-pen
row left at index 0 would have scored as raw damage.

### Corrections PART 10 makes to PART 9 and to the hand-off prompt

- **The prompt's menu was wrong about its own top item.** "The single best-evidenced open row and
  it is now three rows deep in agreement" was three rows agreeing on a prerequisite that had
  already shipped. Agreement between rows is not evidence when all three inherited the same
  unverified premise.
- **The merger's own seam census was inflated.** It reported 36 stranded seams using substring
  matching; `gate_caster_hp` and `gate_target_hp` do not exist in `server.py` and were artifacts
  of `gate_caster_hp_amp` / `gate_target_hp_amp`. Word-boundary count is **34**. The build agent
  caught this and was right to trust its own measurement over the brief.
- **RM-95b B2 as specced is not what closes the symptom.** The spec bills "wiki becomes the numeric
  authority for bases, ratios and cooldowns across 171" and "close Locke's 0.0" as one job at
  1-1.5 sessions. They are different jobs: the second is a 2-champion registry, the first is a
  genuine schema lift and should be re-costed well above that before anyone starts it.
- **B1 shipped code with no data.** `--full-roster` exists but no 16.14.1 artifact was regenerated
  with it - `wiki_ability_stats.json` (mtime 07-16), `cdragon_ability_ratios.json`
  (`_champ_count: 171`) and `cdragon_spell_stats.json` all still contain zero Locke/Zaahen records.
  The CC / geometry / cooldown half B1 claimed is not available to any consumer.
- **RM-85's RC-2 claim rests on a `top=40` truncation.** Five routes return the identical 135-item
  set at both gates; at `top=300` Protoplasm Harness is #54 bruiser / #20 tank. So the RM-86 spec's
  "RC-2 is structurally the inverse of RC-1" has **one** instance (Quinn, via the carry-only client
  gate), not two.
- **A probe-hygiene trap worth the same status as the `top=40` and empty-list traps:** `/rank*`
  returns `item_id` as a **string**. A probe comparing against integer ids reads ABSENT for every
  watched item and looks exactly like a clean pool-exclusion finding.
- **`parse_leveling_bases` has a structural blind spot** (`ds_wiki_staleness_check.py:188-196`): it
  keeps only the first label pair per `{{st}}` block, and over a 50-page sample **31 of 90 blocks
  carry two or more pairs, dropping 35 labels** that match Meraki attributes verbatim. The
  RM-81 staleness report is an undercount, and `_ability_base_overrides`'s "exactly those six"
  scope was derived from it.
