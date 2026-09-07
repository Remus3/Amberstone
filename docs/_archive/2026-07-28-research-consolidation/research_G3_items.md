# research/ collapse - Group G3 extraction (8 files)

Read-only QA pass, 2026-07-28. Every item below was re-probed against the live tree
at `C:\Riot Commander` (HEAD 59e42205). Ground truth used:

- `data/daemon_slayer/current.txt` = **16.14.1**
- `agents/daemon_slayer/__init__.py:18` `ENGINE_VERSION = "1.262.0"`
- `data/daemon_slayer/` holds 16.10.1 .. 16.14.1 only (**no 16.15 dir**)

Two of the eight source files are grounded against STALE engine snapshots and their
own metadata should not be trusted forward:
`2026-07-16-ds-meta-valuation.md` cites ENGINE 1.216.0 on a throwaway worktree branch;
`OQ25_meta_divergence_report.md` cites ENGINE 1.210.0 / patch 16.13.1;
`COMPETITOR_LIFT_AGGREGATOR_C.md` cites ENGINE 1.212.0 / patch 16.13.1.

---

## docs/research/2026-07-16-ds-meta-valuation.md

| ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|
| Ezreal HIGH divergence - "kit-axis seam is DEFAULT-OFF live so Ezreal's meta #1 mana-caster core is buried"; wire `prefer_kit_axis_by_win` live | **REFUTED** | The seam was flipped default-ON **12 days BEFORE this doc was written**. `coach_integration/archetype_dispatch.py:217` `prefer_kit_axis_by_win: bool = True` with the `C4 FLIP (2026-07-04)` note at `:211`. `docs/LEDGER.md` item 778: "DONE 2026-07-04 (C4 seam FLIPPED default-ON ...) ... Proven live vs :8893: dispatch_for_coach(\"Ezreal\", ARAM) DEFAULT now floats Essence Reaver to #1 ... C4 is FLIPPED + CLOSED". The doc measured a stale worktree checkout of branch `docs/research-20260716` (ENGINE 1.216.0) and reported the ENGINE default, not the live caller default. **Do not re-open Ezreal on this premise.** | - |
| Residual half: `exempt_offclass_by_win` (DSP2 marksman off-class un-strip - Trinity Force + Spear of Shojin) still default-OFF | **STILL OPEN** | `coach_integration/archetype_dispatch.py:216` `exempt_offclass_by_win: bool = False`; `core/daemon_slayer_client.py:169` same. Grep of `prefer_kit_axis_by_win\|exempt_offclass_by_win` across all `*.py` returns exactly ONE flip record (the C4/DSP11 one) and none for DSP2. Table `agents/daemon_slayer/marksman_offclass_exempt.json` exists and carries Ezreal. | S to flip, but Tier-2 + live validation |
| Jhin residual - execute core stays buried at the tanky target; needs the squishy-carry target scenario (lever L4) | **DUPLICATE-OF** the OQ25 "extend the fight_length allow-map" row below | Same lever, same allow-map file. `core/ds_champion_fight_length.py:108` `jhin: 0.5` shipped. | - |
| Zed / Talon - `rank_assassin_for` never forwards `assume_takedown`, so the Collector/Hubris kill-state execute credit is dormant live | **STILL OPEN** | `core/daemon_slayer_client.py:1134-1180` (`def rank_assassin_for`) - full signature read; `assume_takedown` is NOT a parameter. Grep of `assume_takedown` across all `*.py` returns 40 hits, **ZERO of them in `core/daemon_slayer_client.py`** - it exists only inside `agents/daemon_slayer/{burst,dps,server,effects,_effects_*}.py`. Engine default `agents/daemon_slayer/burst.py:519` `assume_takedown: bool = False`; execute finisher gated at `burst.py:1075`. | S to plumb; scoring change so needs a live-gated flip |
| Varus secondary lethality-poke (Youmuu's / Muramana) path unsurfaced | **DUPLICATE-OF** the OQ25 allow-map extension row | Varus is named there as a NOW-tail candidate. | - |
| Kai'Sa poke -> Manamune research question | **REFUTED** | The doc closes it NEGATIVE itself (fringe: 0.1-0.2% pick, sub-45% WR; DS correctly omits). Also fenced by CLAUDE.md "the all-173 alphabetical DS_SWEEP is CLOSED ... do NOT re-open the roster". | - |

## docs/research/2026-07-16-patch-16.15-lookahead.md

| ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|
| "16.15 is not ingestable today - do not bump ENGINE for 16.15 yet"; re-scrape wiki VPBE + PBE posts 2026-07-20..07-26 and run the patch-refresh workflow | **STILL OPEN (now DUE)** | `data/daemon_slayer/current.txt` = `16.14.1`; `ls -d data/daemon_slayer/16.15*` -> "No such file or directory". Patch 16.15 goes live **2026-07-29**, i.e. tomorrow relative to this pass. The doc's re-scrape window has fully elapsed with no ingest. | M (standard patch-refresh: SWARM extract + merge-arbiter golden-diff + ENGINE bump + Share) |
| Section B - VERIFY that DS already carries the 16.14 tail (Garen R true damage, Mordekaiser E ratio, Immortal Path / Protoplasm Harness / Rocketbelt item stats) | **SUPERSEDED** | The 16.14.1 snapshot shipped and was then swept far harder than a 5-row spot-check: `DS_ABILITY_SHAPING_NOTES.md` measured all 171 champions against `data/daemon_slayer/16.14.1/champion_abilities.json` on 2026-07-18 (75 stale champions found, 6 actionable, all 6 shipped at ENGINE 1.248.0 per `ROADMAP.md:113`). `tools/ds_wiki_staleness_check.py` is the standing detector, wired into `upstream_drift_check --staleness-recent`. | - |
| Section C - shield-lerp flag: diff Immortal Shieldbow + Locket of the Iron Solari shield values when 16.15 balance data lands | **STILL OPEN** | No 16.15 data dir exists, so the diff has not been possible and has not been run. | S, fold into the 16.15 refresh above |

## docs/research/COMPETITOR_LIFT_INDEX.md

Fence applied per CLAUDE.md + the operator brief: the competitor-lift / overlay /
companion / stat-site category is DRAINED and RETIRED. Rows below are presumed
CLOSED unless a concrete un-built, un-refuted lift is cited.

| ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|
| Reference-only research records (baronbuff, league_record, aggregator Z13, aggregator J, quick-aggregator-a-scraper, LoL-AI-Draft-Picker, league-connect, LeagueBuilds, lolsite, Coaching App Z7, Draft Tool Z8, LoL Esports data portal, mwrogue, CommunityDragon `lol-game-data` 7-file catalog) | **SETTLED-DO-NOT-RELITIGATE** | CLAUDE.md Settled: "Research-list triage CLOSED negatives (do NOT re-research)". Each carries an unmet external trigger, none is an RC build item. | - |
| draft tool L Elo log-odds draft aggregator | **SHIPPED** | The file's own inline note: `core/draft_elo.py` + `core/draft_elo_db.py` + `dashboard/routes_draft_elo.py` + `web/js/panels/draft_elo.js`, 2026-05-20. | - |
| Riot per-role grading rubric calibration | **SHIPPED** | Item 335, `4d9a8adb`, `core/post_game_rubric.py`. | - |
| Aggregator C GPI 8-axis radar + weakest-axis tip + per-champion drill-down | **SHIPPED** | items 450 / 451 / 511; `core/player_gpi.py` + `/api/player-profile` + `web/js/panels/player_gpi.js`. | - |
| Overlay App E personal-WR build override (local-data half) | **SHIPPED** | `core/personal_build_wr.py` + `GET /api/personal-build`; the champ-select UI consumer landed as R34 F1. | - |
| Overlay App E LCU rune-page AUTO-WRITE half | **STILL OPEN** | Blocked on a non-frozen LCU wrapper: `lcu/lcu_client.py` is on the CLAUDE.md frozen-file list. No wrapper module exists. | M, frozen-file gated |
| Guide Site Q F1 lane/fight all-5-enemy threat/danger grid | **SHIPPED** | `web/js/panels/ds_matchup.js:313-317`: "F1 danger grid. One row per committed enemy: role pip, champion, verdict, swing." | - |
| R81 F5 matchup card reads the ROLE-MATCHED lane opponent (was `enemyIds[0]`) | **SHIPPED** | Same site, `ds_matchup.js:314`: "The role-matched laner is flagged so the grid and the headline card visibly agree". | - |
| **Laning precompute hold-band recalibration (PRIMARY Haiku-zero, #1-frequency flip)** - add a `hold`/farm band + soften the back_off threshold in the laning verdict generator, regen the LFS scenario tables, re-run the shadow report | **STILL OPEN** | Not a competitor lift - a Haiku-zero engine item recorded in this file. `agents/daemon_slayer/matchup.py:35-36` still `_TRADE_MARGIN = 0.10` / `_EVEN_BAND = 0.05`; the verdict path at `:202-204` emits only back_off / trade / even - grep for a `hold` band in that file returns nothing. Only the REPORT half landed (item 508, `4623edd7`, `tools/hz_shadow_report.py` even bucket). | L (Tier-2 + `data/daemon_slayer/laning_scenarios` LFS regen + report re-run + operator gate) |
| LBAND1 live wire-in (`core/live_benchmark_band` into `/api/state` + overlay, validate, flip) | **LIVE-GATED** | `docs/LIVE_GAME_GATED_SYNC.md:532` row **G2-37**. Only the shadow logger is wired: `dashboard/_deterministic_coaching.py:1635` `shadow_log_live_benchmark_band`. | M, needs a live game |
| Arena S2 Augment Level-Up + Crafting Round schema break | **LIVE-GATED** | External trigger (Riot PBE schema) plus a live Arena game to confirm. No `levels[]` axis exists on `compute_augment_stats()`. | M when triggered |
| Overlay App F post-game warding heatmap | **REFUTED** | Premise falsified 2026-06-25: Match-V5 carries no ward x/y (probed: WARD_PLACED 294518 rows, 0 with positions). File says "Do NOT re-pitch". | - |
| Overlay App E enemy ult / ability CD timers (automatic) | **REFUTED** | No enemy-cooldown feed on `:2999` (memory `reference_liveclient_no_hud_data`); the 2026-06-16 lift closed the AUTOMATIC path. | - |
| R100 F1 manual click-to-track enemy summoner/ult CD overlay | **LIVE-GATED** | `web/js/panels/enemy_spells.js` exists (summoner-spell half); the ult-CD half needs an operator-directed live overlay session, explicitly "do NOT build blind". Same item as LIFT_EXPANSION L5. | M |
| 2026-07-16 companion F2 enemy item-COMPLETION spike alert | **LIVE-GATED** | Needs a live enemy-roster verify; file states "NOT headless-blind-shippable". | M |
| Overlay App F lobby player-tags; R34 F3 per-opponent matchup delta-stats; R34 F8 phase/snowball rating bar; R34 F2/F5/F6; Guide Site Q F3 skill-order max-priority grid; Aggregator H F5 personal learning curve; R81 F3/F4; companion F8 projected-tier tile; F1 voice ASK; rate-wall lane NOW/FUTURE cluster; draft+coach NOW cluster; overlay+radar NOW cluster; tagged-players notes; Vite hot-swap; uxpatterns dials; FUTURE-tail one-liners | **SETTLED-DO-NOT-RELITIGATE** | Category fence (drained 5x; the file's own LOOP-HEALTH steer says "the next competitor pick rotates category or accepts the well is dry"). Each has an unmet trigger and none is a concrete un-built lift with a fresh empty search. | - |
| Aggregator H F3 snowball elasticity (WR by K-D@10/@20) | **SETTLED-DO-NOT-RELITIGATE** | Actively named as an anti-pattern in `docs/LEDGER.md` item 974: "laundering a personal-corpus correlation into the engine's optimality math would be the F3 snowball-elasticity mistake". | - |
| companion F6 ask-anything chat box; F3 post-game 0-100 grade | **SETTLED-DO-NOT-RELITIGATE** | F6 is an operator charter call against the Haiku-to-ZERO north star ("do NOT build headless"). F3 is the s220 PGR reframe, CLAUDE.md Settled, ROADMAP-S3 explicitly do-NOT-pre-build. | - |
| companion F4 zero-click rune+item import | **SHIPPED** | `lcu/lcu_rune_writer.py` + LEDGER 867; the swap defect was found and fixed same-day (`ae81e456`, 13 RED-first tests). File marks it "F4 fully CLOSED". | - |
| LCU toolkit: legal-move champ-select getters `/lol-champ-select/v1/{pickable,bannable,disabled}-champion-ids` | **STILL OPEN** | Grep `pickable-champion-ids\|bannable-champion-ids` across all `*.py` returns **ZERO hits**. In-transport LCU, no new dep, no ToS issue. | S |
| LCU toolkit: read Riot recommended runes `/lol-perks/v1/recommended-pages/champion/{id}` as a degrade fallback | **STILL OPEN** | Grep `recommended-pages` across all `*.py` returns **ZERO hits**. RC writes runes but never reads Riot's recommendation. | S |
| LCU toolkit: LCU WebSocket event stream (`lcu/lcu_events.py` sidecar, `OnJsonApiEvent`) replacing the 1 Hz poll | **STILL OPEN** | `lcu/lcu_events.py` does not exist (ls -> "No such file or directory"). Must not touch the frozen `lcu/lcu_client.py`. | M |
| SGP all-10 scouting client (`core/sgp_client.py`) | **STILL OPEN** | `core/sgp_client.py` does not exist. The one gating unknown IS now cleared - CLAUDE.md Settled records the 2026-07-19 RM-106 measurement that SGP returns KIWI / queue-2400 games in Match-V5 shape. Still ToS-HIGHEST, do-not-ship-blind. | L, ToS-gated, operator decision |
| LCU automation (auto-accept / auto-pick / dodge / honor / chat spoof) | **SETTLED-DO-NOT-RELITIGATE** | ToS + product-fit CLOSED in the file; RC is a coaching dashboard, not a bot. | - |
| Champ-Select SR `.csv-rune-side-tree` ~105px overflow at 920px | **REFUTED (as a MUST-FIX)** | The file itself classifies it non-baseline: the R118 audit was CLEAN at the shipping 1920x1080 baseline; 920px is not a shipping target. | - |
| OBS + deterministic-CV + minimap capability | **DUPLICATE-OF** `docs/OBS_CV_MINIMAP_PLAN.md` + the ROADMAP Lane-E row | The file names that canonical home itself. | - |

## docs/research/COMPETITOR_LIFT_AGGREGATOR_C.md

| ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|
| F1 Tab+Q per-player WR + playstyle badges | **SETTLED-DO-NOT-RELITIGATE** | Needs a Riot PRODUCTION key for arbitrary-summoner Match-V5 (ADR-006 CLOSED anchor) + a single-player-corpus violation for the badges. Reaffirms R112. | - |
| 2a lanes/team power-spike stoplight | **SHIPPED** | `/api/spike-curve` + `web/js/panels/spike_curve.js` + `agents/daemon_slayer/spike_markers.py` (R81 F1/F2). | - |
| **2b ENEMY ult power-spike pop-up (lvl 6/11/16) - backend one-field extract** | **SHIPPED** | The prescribed edit LANDED: `dashboard/_liveclient.py:93` now emits `"level": _as_int(p.get("level"))` inside the per-player `out["players"]` dict. The doc's stated data gap is closed. | - |
| **2b - the overlay panel half (per-enemy `crossedSpike` edge detector)** | **STILL OPEN** | `web/js/panels/enemy_spike_cue.js` does not exist (ls -> "No such file or directory"). Grep of `crossedSpike\|_SPIKE_LEVELS` across `web/js/` returns hits **only** in `web/js/panels/spike_cue.js` (`:28`, `:45`, `:50`, `:114`) which reads the ACTIVE player's level only. This is the file's one genuinely net-new residual and it is now frontend-only. | S-M; do NOT build blind - needs a live enemy roster to verify SR/ARAM/Arena gating |
| 2c completed-item event feed / per-player count | **SETTLED-DO-NOT-RELITIGATE** | Lower-fidelity duplicate of the R117-shipped item-value lens (`web/js/lib/item_value.js` `teamItemValueDiff`). | - |
| 2d live all-10 Standings ranking | **SETTLED-DO-NOT-RELITIGATE** | Repackages the economy + CS lenses RC already renders. | - |
| 3 Tab+E in-game matchup info | **SHIPPED** | `dashboard/routes_ds_matchup.py` + `web/js/panels/ds_matchup.js` incl. the F1 danger grid at `:313-317`. | - |
| 4 jungle timers | **REFUTED** | Sole source is the Overlay Platform M Game Events Provider; `:2999` emits no jungle-camp event. Architecturally unreachable for RC. | - |
| 5 champ-select Live Companion | **SHIPPED** | Covered across `routes_ds_combo.py` / `routes_ds_matchup.py` / spike-curve / `routes_team_context.py` / `routes_duo_synergy.py` / `routes_damage_mix.py` / `archetype_chip.js` / the PGR suite. Gank-ops is off-axis CLOSED. | - |

## docs/research/DS_ABILITY_SHAPING_NOTES.md

| ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|
| RM-95a - index `champion_has_ability_data` by BOTH DDragon id and display name; compose `has_ability_data AND is_current` | **SHIPPED** | `core/daemon_slayer_client.py:1903` resolves via `_canon_champ_key(champion)` and the docstring at `:1883-1884` states both keyspaces resolve; the composed tri-state landed as `ABILITY_DATA_ABSENT` / `ABILITY_DATA_STALE` / `ABILITY_DATA_CURRENT` (`:1913-1916`) with `_champion_is_stale` at `:1921`. `ROADMAP.md:108`: "**RM-95** ability-data COVERAGE - 95a FIXED 2026-07-25". | - |
| RM-95b - add a DDragon/CDragon per-champion ability fallback for Locke + Zaahen | **SHIPPED (rescoped) + SETTLED** | `agents/daemon_slayer/_ability_wiki_damage_registry.py` + `_ability_wiki_form_damage.py` exist; hook at `agents/daemon_slayer/abilities.py:1011,1192-1193` (`apply_wiki_form_damage`, DEFAULT-OFF). `ROADMAP.md:108`: "the 95b/B2 half adjudicated 2026-07-26: **do NOT build the B2 promoter** (the residual shipped at **1, not 3**, ENGINE 1.257.0 ...; Jayce W and Mel W are NOT data gaps and both refutations are pinned as tests)". | - |
| **Locke ships a 0-of-6 AP build while 92% magic - cheap interim: gate the kit-less ds.dps fallback on `damage_distribution` (refuse a zero-AP build above ~70% magic share)** | **STILL OPEN** | No magic-share gate exists: grep of `magic_share\|damage_distribution` across `core/` + `dashboard/` filtered to fallback/kitless/fell_back context returns **ZERO hits**. The RM-95b wiki registry does NOT close this on the live path because its seam is DEFAULT-OFF (`abilities.py:1011` `apply_wiki_form_damage: bool = False`), so the shipped `build_orders_sr.json` line is still the AD-bruiser fallback. This is a live, user-visible wrong-damage-type build order. | S for the damage-share gate; the alternative (flip `apply_wiki_form_damage`) is Tier-2 + live-gated |
| Zaahen kit hooks unpriced (%max-HP heal Q, %max-HP magic E, %armor-pen R passive, revive P - the third instance of the shipped Anivia/Zac revive EHP multiplier) | **STILL OPEN** | Same root cause: Zaahen's ability data is reachable only through the DEFAULT-OFF `apply_wiki_form_damage` seam, so no hook can be priced on the live default path. Build remains byte-identical to 8 other bruisers per the doc's measurement. | M, Tier-2 |
| Staleness checker blind spot - derive `ds_wiki_staleness_check.run` targets from `champions.json` not `champion_abilities.json`, and emit a `missing_ability_data` bucket | **STILL OPEN** | Grep of `missing_ability_data` across all `*.py` returns **ZERO hits**. The checker still iterates the file that is missing the champion, so an absent champion is silently certified "current". | S |
| RM-81 checker `meraki_endpoints` shape bug (concatenated per-level tail read as max-rank) + `SHAPE_SUSPECT` marker | **SHIPPED** | `tools/ds_wiki_staleness_check.py:283` `kept, marker = rank_series(vals, cooldown)` and `:328` `row["SHAPE_SUSPECT"] = suspect[attr]`; guard test `tests/test_ds_wiki_staleness_check.py:470`. LEDGER 947 (`4f7177c9`). Note the doc's PRESCRIBED fix (index by `len(cooldown)`) was **REFUTED** - it crashes on Aurelion Sol Q and mis-truncates 12 abilities; the shipped tell is the first INTERNAL DROP. | - |
| RM-81 re-source the 6 actionable champions (Mordekaiser Q, Naafiri R, Heimerdinger W, Azir W, Malzahar W, Ahri R) | **SHIPPED** | `ROADMAP.md:113`: "those six SHIPPED 2026-07-25 at ENGINE 1.248.0 as a CODE slice, not a data pull: new `_ability_base_overrides.py` + an `abilities.py` hook, DEFAULT-OFF `apply_ability_base_overrides`, flag ON moves exactly 6 of 1033 forms", each cited to `DS_ABILITY_SHAPING_NOTES.md:566-571`. | - |
| RM-81 rescope "do nothing about 69 of 75" | **SHIPPED (as doctrine)** | `ROADMAP.md:113` carries the rescope verbatim: "the actionable number is 6, not 75 ... 0 change a recommended core build". | - |
| Extend `tools/daemon_slayer_wiki_ability_extract.py` to emit base + cooldown per rank (converts RM-81 from a manual audit into a data refresh) | **STILL OPEN (operator decision)** | `ROADMAP.md:113`: "**KEY REFRAME - this is the open decision:** ... extending RC's own wiki extractor would fix RM-79 + RM-81 at the root (operator decision, not yet taken)". Decision docs shipped (`ed5ddc72`) recommending Option C. | L |
| Bruiser kit-less fallback label is incoherent - a kit-less bruiser serves ability-zeroed HYBRID rows relabelled "carry" | **STILL OPEN** | `dashboard/routes_state.py:844` is unchanged: `"archetype": "carry" if out.get("fell_back") else archetype`, and the justifying comment at `:839-843` still asserts "the dispatcher served a ds.dps carry build (fell_back)" which is true for mage/assassin/enchanter and false for bruiser (that branch returns hybrid rows directly with no re-rank). Zaahen is the champion that hits it. | S (label + regression test) |
| Warwick + Orianna scored at ZERO for a working, measured AA-routed passive (+24.5 / +35.7 DPS at lvl 11) - one-line caller default | **LIVE-GATED / DUPLICATE-OF LGS G2-21** | Confirmed still true: `agents/daemon_slayer/_passive_damage_overrides.py:1164-1169` lists `("Warwick","P",0)` and `("Orianna","P",0)` on `_AA_ROUTED_ON_HIT_KEYS`, but `agents/daemon_slayer/server.py:423` `/dps` defaults `apply_passive_damage` **False**, and the only route passing True is `onhit` (`core/daemon_slayer_client.py:2442`), whose roster `core/ds_onhit_ap_roster.json` is exactly `{Gwen, Kayle, KogMaw}`. Tracked as `docs/LIVE_GAME_GATED_SYNC.md:418` **G2-21**, flagged there as "NOT a clean transport flip". | M, live-gated |
| **Kayle E0 probable DOUBLE-COUNT - the only item that could be scoring too HIGH** | **STILL OPEN** | Kayle sits on BOTH `_AA_ROUTED_ON_HIT_KEYS` (`_passive_damage_overrides.py:1169`) and the onhit roster (`core/ds_onhit_ap_roster.json`, coherence 0.3), and the onhit branch passes `apply_passive_damage=True` unconditionally (`core/daemon_slayer_client.py:2442`), while `dps.py:1183-1186` reads the registry directly and bypasses the injector's `parse_status == "no_damage"` gate. Kayle E now parses `ok` upstream, so the native Meraki block and the synthetic override encode the same mechanic. Grep of `Starfire` across `docs/LEDGER.md`, `ROADMAP.md`, `docs/ROADMAP_HISTORY.md` returns **ZERO hits** - never adjudicated. Kog'Maw W0 is the same stale-registry shape, unconfirmed. | S to probe + assert; **highest-value item in this file** |
| Rammus P Spiked Shell (armor+MR -> bonus AD) as a defect | **REFUTED** | The doc's own conclusion: Rammus routes to `ds.ehp`, whose objective is effective HP and never reads modelled damage, so the coupling cannot move his item order. Same shape as the CLOSED `project_ds_vayne_silver_bolts_unmodelled`. File it as a documented modelling limitation, not a bug. Rammus W is additionally a documented NOT-seeded decision (`CHANGELOG.md:2549`). | - |
| Category (iii) parse failure (structured damage dropped to empty) | **REFUTED** | Measured 0 of 350. All 6 `unparsed`/`partial` forms retained their damage blocks. "should be closed, not investigated". | - |
| Prose can never reach a scorer (`effects_descriptions` is dropped at load) | **REFUTED as actionable** | `AbilityForm` declares 16 fields at `agents/daemon_slayer/abilities.py:220-235` and `from_dict` at `:244-263` parses exactly those; `effects_descriptions` is absent. No scorer work can reach prose - only a hand-authored registry entry can. Independently restated at `kit_conversion.py:33-35`. | - |
| ~103 unseeded prose-only damage forms; cheapest are the every-auto riders Corki P / Ashe P / Lucian P / Akshan P | **STILL OPEN** | Authoring work is real and un-done, but its consumer is the G2-21-gated `apply_passive_damage` default, so seeding without that flip produces zero live change. Sequence behind G2-21. | M authoring, then G2-21 |
| Rammus P / Hecarim P / Janna P class - pure stat couplings needing a coupling schema, not a DamageBlock | **STILL OPEN (schema lift)** | 23 forms enumerated at section 5d; `DamageBlock` prices damage, these modify a stat. No coupling schema exists. | L, schema lift - low expected yield |

## docs/research/LIFT_EXPANSION_UIUX_2026-06-26.md

Fence note: this file is under the retired-category presumption, but 3 of its top-5
NOW shortlist demonstrably SHIPPED, so the file was actioned rather than abandoned.
The rows below marked STILL OPEN each carry a fresh empty search, which is the
exception the brief allows.

| ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|
| L1 Epic buff-expiry timer (Baron/Elder 180s sided countdown) | **SHIPPED** | `core/event_callouts.py:87` `_BARON_BUFF_S = 180.0`, `:89` `_EPIC_BUFF_S`; tests `tests/test_event_callouts.py:351` `test_ally_baron_buff_countdown`, `:362` `test_enemy_baron_buff_defend`. | - |
| L2 Dragon soul-point tracker + soul-race verdict | **SHIPPED** | `core/event_callouts.py:737` `soul_point_{side}`, `:746` `soul_race_{leader}`; tests `tests/test_event_callouts.py:431/441/458/471`. | - |
| L3 Dynamic objective respawn callout (thread real take-times into `next_callouts`) | **SHIPPED** | `core/event_callouts.py:769-782` - `next_callouts` now takes `objective_events` (plus `inhib_events` / `turret_events`). | - |
| L4 Phase-D consumer for the 11 stranded DS capability scorers | **SHIPPED** | `core/ds_capability_gap.py` exists and is live-wired at `dashboard/routes_state.py:830-834` (`build_capability_gap`, emitted as `capability_gap` on the ds-preview payload at `:849`). | - |
| L5 Operator-armed manual-click summoner/ult cooldown tracker | **LIVE-GATED** | `web/js/panels/enemy_spells.js` exists (summoner-spell half shipped); the ult-CD half is the R100 F1 parking, "operator-directed live overlay session, not a headless slice". | M |
| L6 Cannon-wave + recall-window timer (pure `game_time` math) | **STILL OPEN** | Grep `cannon_wave\|next_cannon\|recall_window` across all `*.py` + `*.js` returns **ZERO hits**. | M |
| L7 Anti-sustain effective-throughput DS axis (credit Grievous Wounds items) | **STILL OPEN** | Grep `heal_cut\|grievous` across `agents/daemon_slayer/` + `core/` returns only `core/defensive_picks.py:126` (a display tag) and two unrelated seam tests - **no scorer consumer**. `_effects_data.py` still notes "heal-cut not modeled". | L, Tier-2, needs an enemy heal/s estimate |
| L8 Role-conditioned draft pair/matchup ratings | **REFUTED** | Corpus-blocked, and independently measured in this same batch: OQ22 S2 found only 660 SR-classic games in `rewind_history.db` with per-pair median n=2.5 and ZERO pairs at n>=10. Role-keying makes already-sparse cells sparser. `draft_elo_db.py:179-184` defers it in-code on exactly this condition. | - |
| L9 Feed live `championStats` into DS as ground-truth calibration | **SHIPPED** | `dashboard/_liveclient.py:145` `cs = ap.get("championStats") or {}` with the full combat block (`:163` "championStats is ground truth"); guard suite `tests/test_liveclient_championstats_ingestion.py`. | - |
| L10 Ingest live stat shards + full rune list from `/activeplayerrunes` | **SHIPPED** | `game_reader/snapshot_normalizer.py:1128` `shards = data.get("statRunes", [])`; fixture `tests/test_liveclient_championstats_ingestion.py:106`. (The per-patch shard -> stat-delta table feeding `base_stats` is the residual tail of the same item.) | - |
| L11 Shared DocumentFragment batching helper for high-churn panels | **STILL OPEN** | `DocumentFragment`/`replaceChildren` appear in only 3 panels (`active_match.js`, `aram_balance.js`, `ds_shaper.js`); no shared helper in `web/js/lib/`. Ad-hoc, not formalized. | S, low value |
| **E1 TFT deterministic coaching twin on CommunityDragon static data** | **STILL OPEN** | `core/precomputed_tft*.py`, `core/tft_shadow.py`, and `tools/*cdragon_tft*` all -> "No such file or directory". TFT remains the only mode with no deterministic precompute twin and is 100% Haiku-dependent - directly on the PRIMARY north star. | L (own session) |
| E2 Spatial position-trace metrics from Match-V5 timeline x/y | **STILL OPEN** | No `core/spatial*.py`. `core/replay_analysis.py:209` `position_at` is a REPLAY-timeline helper, not a `rewind_history.db` aggregator, and `core/replay_seek.py:19` flags `positions_available=False` for its own source. No rubric axis consumes position. | L |
| E3 `lol-challenges` percentile as a personalized weakness lens | **STILL OPEN** | Grep `lol-challenges` across all `*.py` returns **ZERO hits**. Riot-blessed, self-only, single-player-compliant. | M |
| E4 Closed-loop practice-drill prescriptions with cross-game progress | **STILL OPEN** | Grep `drill\|practice_tool` in `core/` hits only `core/player_gpi.py` champion-DRILLDOWN (unrelated). No recurrence detector, no prescription, no re-measurement. | M |
| U1 Bar-length depletion encoding for the objective ETA chip | **STILL OPEN** | `web/js/panels/callouts.js:64` `_fmtEta` returns text only; no bar/length element in the file. Closes RC's own `OVERLAY_DOCTRINE.md` rule 10 against its own renderer. | S |
| U2 ARIA-live on the RIGHT NOW coach action | **STILL OPEN** | `web/index.html:482` `<div class="action" id="rn-action">` and `:489` `#rn-immediate` carry **no** `aria-live` attribute. | S |
| U3 WCAG contrast + `prefers-contrast` on `--signal-dim` | **STILL OPEN** | Grep `prefers-contrast` across `web/css/` returns **ZERO hits**. | S |
| U4 Same-document View Transitions for the 11-view switch | **STILL OPEN** | Grep `startViewTransition` across `web/js/` returns **ZERO hits**. | S |
| U5 Anticipatory pre-spawn pre-roll (wire the stubbed `objectiveStealNow` predicate) | **STILL OPEN** | The predicate is still producer-less: `web/js/lib/overlay_priority.js:91/174` consume `objective_steal_now`, and grep of `objective_steal_now` across all `*.py` returns hits **only** in `tests/test_overlay_priority_rc2.py:223` - no backend emits it, so the priority-90 rung is never reached live. | M, over-fire tuning risk |
| U6 Command palette (Ctrl+K) | **STILL OPEN** | Grep `palette` in `web/js/main.js` hits only colour-palette comments (`:123`, `:4645`); no palette module or token. | M |
| U7 Cross-view drill-down (clickable champions/items/matches) | **STILL OPEN** | Grep `#history?champ` / `history?champ=` across `web/js/` returns **ZERO hits**; no shared deep-link helper. | M |
| U8 Keyboard view-switching (g-prefix / bracket keys) | **STILL OPEN** | `web/js/main.js` binds only A/F/Z/Esc/Ctrl+K/? ; `VIEW_IDS` is imported at `:17` and used for hash routing (`:594`, `:759`) but no key layer targets it. | S (pair with U6) |
| U9 Unified priority-aware dashboard toast service | **STILL OPEN** | No toast module under `web/js/lib/`; the 3 hand-rolled toasts remain independently timed. Doc itself rates the payoff low for a solo tool. | M, low value |
| U10 Audio earcons for the Emergency cue | **STILL OPEN** | Grep `AudioContext\|oscillator` across `web/js/` returns **ZERO hits**. | M |
| U11 Container queries for the active-match panes | **STILL OPEN** | Grep `container-type\|@container` across `web/css/` returns **ZERO hits**. | M |
| U12 Explainability trace for FLIPPED deterministic coaching | **STILL OPEN** | Grep `coach_trace` in `_deterministic_coaching.py` returns **ZERO hits** - the one path that reached Haiku-to-ZERO still emits no trace. Value grows precisely as the north star is achieved. | M |

## docs/research/OQ22_headless_validations.md

| ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|
| S1 comp-verdict inverted damage-type label (Vex -> Garen "All-AD comp") | **SHIPPED** | Fixed in-run with 3 RED-first regression tests in `tests/test_aram_comp_verdict.py`. | - |
| S1 secondary - decide whether DDragon-zeroed champs (Vex) should resolve their damage lean via `core.champion_info_overrides` | **STILL OPEN** | `core/champion_info_overrides.py` exists, but grep of `champion_info_overrides` inside `core/aram_comp_verdict.py` returns **ZERO hits**; `_damage_lean` at `:128` still resolves Vex to "hybrid", and mono-detection ignores hybrids by design (`:184-186`). | S |
| S2 champ_select pickban-DB flip | **LIVE-GATED** | Stays operator-gated: `docs/LIVE_GAME_GATED_SYNC.md:1218` ("OQ22 CORPUS-TOO-THIN (660 SR-classic, median pair n=2.5); flip stays ..."), and `ROADMAP.md:131` lists "champ_select pickban-DB flip after a counter-quality validation" under OPEN (operator-gated). Do NOT flip on the 49.5% coin-flip evidence. | L (needs a 10k+ lane-labeled SR corpus) |
| S3 `ROADMAP:72` stale prose ("substrate now ready / deferred" when the base fold-in is already live) | **SHIPPED (doc drift corrected)** | `ROADMAP.md:132` now states it correctly: "the BASE ability-HPS fold-in is ALREADY live per OQ22". | - |
| S3 `assume_missing_hp_heal_amp` heal-amp flip | **LIVE-GATED** | `docs/LIVE_GAME_GATED_SYNC.md:344` row **G2-04** (R5 heal-amp + live caster missing-HP feed); `ROADMAP.md:132` "hps.py:499/:828 default OFF". Correct expected state - scoring-math change, do not flip blind. | M, needs a live SR-support game |
| S3 enchanter registry omits 5 corpus-proven winners (Dream Maker 3870, Dawncore 6621, Shurelya 2065, Seraph's Embrace 3040, Luden's 6655) | **STILL OPEN** | Grep of those five item ids across `agents/daemon_slayer/hps.py` + `core/` returns **ZERO hits**; `hps.py:878` `enchanter_only: bool = True` still restricts the candidate pool to the 9-item registry, so `/rank-enchanter` cannot surface them. `ROADMAP.md:132` carries it explicitly as "enchanter registry omits 5 corpus-proven winners ... (FUTURE)". | M (registry expansion + a live SR-support game before any default-on) |
| S4 same-state Haiku-skip debounce default-ON flip | **LIVE-GATED** | `coaches/aram_coach.py:57` and `coaches/arena_coach.py:64` both still `os.getenv(..., "0") == "1"`. Rows `docs/LIVE_GAME_GATED_SYNC.md:703` **G3-12** and `:978` **G5-06**, plus the summary at `:1207`. Needs a live ARAM + a live Arena game in shadow. | M, live-gated |

## docs/research/OQ25_meta_divergence_report.md

| ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|
| Jhin fight_length lever - "do NOT re-pitch or re-wire, this is SHIPPED" | **SHIPPED** | `core/ds_champion_fight_length.py:108` `"jhin": 0.5`; LEDGER 875; `docs/specs/2026-07-13-ds-crit-burst-fix.md`. Jhin is the proof the NOW mechanism works. | - |
| **NOW tail - extend the `ds_champion_fight_length` allow-map to the remaining lethality / crit-primary carries (Varus poke, Miss Fortune crit), plus spec L5 (fed-conditional fight_length) and L6 (stale-catalog hygiene)** | **STILL OPEN** | The map is still exactly the six shipped entries: grep of `jhin\|draven\|samira\|twitch\|caitlyn\|jinx\|varus\|missfortune\|ezreal` in `core/ds_champion_fight_length.py` returns `jhin:0.5` (`:108`), `draven:0.3` (`:114`), `samira:0.3` (`:115`), `twitch:0.5` (`:118`), `caitlyn:0.5` (`:119`), `jinx:0.5` (`:120`) and **no varus, no missfortune, no ezreal**. | M per champion, Tier-2, TDD RED-first, per-champion live validation - never a blind bulk flip |
| FUTURE - lethality-valuation weighting term in `rank_items_by_burst` so `/rank-assassin` surfaces the pure-lethality snowball core for Zed / Talon / Qiyana | **STILL OPEN** | Grep of `lethality` in `agents/daemon_slayer/burst.py` filtered to `weight\|valuat\|snowball` returns **ZERO hits** - the burst ranker still values raw penetration + crit multipliers with no lethality-as-burst-enabler term. The crit-burst spec scopes it OUT ("widen to lethality champs Zed/Talon only on separate test evidence"). Overlaps the ds-meta-valuation `assume_takedown` row in SYMPTOM but is a different mechanism (weights lift vs caller flag) - adjudicate them together. | L, schema/weights lift, Tier-2 |
| The 11 VALIDATED-CORRECT on-hit / AS / crit marksmen (Ashe, Kalista, Kai'Sa, Kog'Maw, Vayne, Aphelios, Jinx, Caitlyn, Draven, Samira, Varus/MF on-hit) - "do NOT touch" | **REFUTED (as work)** | The report validates them; there is no action. Preserve the do-not-touch fence. | - |
| Probe caveat: raw `POST /rank` is the pre-policy baseline, NOT what the live coach serves | **SHIPPED (as a memory fence)** | Already canonical as memory `reference_ds_probe_rank_vs_archetype_route` + the CLAUDE.md Settled probe-trap note. Preserve the caveat when the file is archived. | - |

---

## Roll-up

### Verdict counts (78 items adjudicated)

| Verdict | Count |
|---|---|
| SHIPPED | 24 |
| SETTLED-DO-NOT-RELITIGATE | 12 |
| STILL OPEN | 30 |
| LIVE-GATED | 8 |
| REFUTED | 9 |
| SUPERSEDED | 1 |
| DUPLICATE-OF | 4 |

(Counts exceed 78 slightly because 4 rows resolve as DUPLICATE-OF and are also
counted at their primary home; treat DUPLICATE-OF rows as pointers, not work.)

### STILL OPEN - best first

1. **Kayle E0 probable double-count in the on-hit scorer** (S). The only finding in
   the whole batch that could be scoring something too HIGH. Kayle is on both
   `_AA_ROUTED_ON_HIT_KEYS` and the onhit roster, the onhit branch forces
   `apply_passive_damage=True`, and `dps.py:1183-1186` bypasses the
   `parse_status == "no_damage"` injector gate. Never adjudicated (zero `Starfire`
   hits in LEDGER / ROADMAP / ROADMAP_HISTORY). Probe first, then decide.
2. **Patch 16.15 ingest + the shield-lerp diff** (M). Live patch is 16.14.1, no
   16.15 data dir, and 16.15 ships 2026-07-29. Diff Immortal Shieldbow + Locket
   shield values on the same pass.
3. **E1 TFT deterministic coaching twin** (L). The only mode with no deterministic
   precompute twin and 100% Haiku-dependent - straight at the PRIMARY north star.
   Zero files exist.
4. **Laning precompute hold-band recalibration** (L, operator-gated Tier-2). The
   #1-frequency laning flip is stuck at 53% agreement; `matchup.py:35-36` still has
   no `hold` band. Report half done, engine half not.
5. **OQ25 fight_length allow-map extension** (M). Map is still exactly 6 entries;
   Varus poke + Miss Fortune crit are the named candidates, plus spec L5/L6.
6. **Locke ships a zero-AP build at 92% magic share** (S). Live, user-visible wrong
   damage type. The cheap fix (gate the kit-less ds.dps fallback on
   `damage_distribution`) does not exist anywhere.
7. **Bruiser kit-less fallback mislabelled "carry"** (S). `routes_state.py:844`
   relabels hybrid rows as carry; true for 3 branches, false for bruiser.
8. **Zed/Talon: `rank_assassin_for` never forwards `assume_takedown`** (S) AND the
   **lethality-valuation term in `rank_items_by_burst`** (L). Same symptom, two
   mechanisms - adjudicate together before building either.
9. **Aggregator C 2b enemy ult power-spike overlay panel** (S-M). The backend
   one-field extract already landed (`_liveclient.py:93`); only the per-enemy
   `crossedSpike` panel remains. Do not build blind - live enemy roster verify.
10. **Staleness checker `missing_ability_data` bucket** (S). Absent-champion silence
    still reads as "current".
11. **Enchanter registry omits 5 corpus-proven winners** (M). `enchanter_only=True`
    hard-blocks them from `/rank-enchanter`.
12. **Quick UI wins, S each**: U2 aria-live on `#rn-action`; U1 depleting ETA bar
    (closes RC's own doctrine rule 10); U3 `prefers-contrast`; U4 View Transitions;
    U8 bracket-key view nav.
13. **U12 deterministic-coach explainability trace** (M). The Haiku-zero path emits
    zero trace entries; the blind spot grows as the north star is reached.
14. **LCU cheap reads** (S each): legal-move champ-select getters; Riot
    recommended-runes as a degrade fallback. Both zero-hit greps, in-transport.
15. **L7 anti-sustain Grievous DS axis** (L, Tier-2). No scorer credits heal-cut.
16. **E3 lol-challenges weakness lens** (M); **E4 practice-drill loop** (M);
    **L6 cannon-wave/recall timer** (M); **E2 spatial position metrics** (L).
17. **`lcu/lcu_events.py` WebSocket sidecar** (M) replacing the 1 Hz poll.
18. **Wiki extractor extension to carry base + cooldown** (L). Named in ROADMAP.md
    as "this is the open decision", operator call not yet taken.
19. **U5 pre-roll producer, U6 palette, U7 drill-down, U9 toasts, U10 earcons,
    U11 container queries** (M each, lower value).
20. **`exempt_offclass_by_win` (DSP2) flip** (S code, Tier-2 validation).
21. **103 unseeded prose-only passive forms** (M authoring) - sequence BEHIND the
    G2-21 `apply_passive_damage` flip or it produces zero live change.
22. **Zaahen kit hooks unpriced** (M) - same DEFAULT-OFF seam as Locke.
23. **`core/sgp_client.py`** (L, ToS-HIGHEST, operator decision). The gating reach
    probe is now cleared by the 2026-07-19 RM-106 measurement.
24. **Vex damage-lean via `champion_info_overrides`** (S); **L11 DocumentFragment
    helper** (S); **Overlay App E LCU rune-page auto-write** (M, frozen-file blocked);
    **stat-coupling schema for Rammus P / Hecarim P / Janna P** (L, low yield).

### LIVE-GATED (need a real game; do not close headless)

1. **G2-21** `apply_passive_damage` default-ON - Warwick +24.5 and Orianna +35.7 DPS
   are authored, measured, and scored at zero in production
   (`docs/LIVE_GAME_GATED_SYNC.md:418`).
2. **G3-12 / G5-06** `RC_ARAM_STATE_DEBOUNCE` / `RC_ARENA_STATE_DEBOUNCE` default-ON
   (`:703`, `:978`) - needs one live ARAM + one live Arena in shadow.
3. **G2-04** `assume_missing_hp_heal_amp` heal-amp flip (`:344`) - live SR support.
4. **G2-37** LBAND1 live wire-in (`:532`) - only the shadow logger is wired.
5. **Pickban-DB flip** (`:1218`) - corpus too thin (660 SR games, pair median 2.5).
6. **R100 F1 / L5** manual click-to-track enemy ult CD - operator-directed overlay
   session only.
7. **Companion F2** enemy item-COMPLETION spike alert - live enemy roster verify.
8. **Arena S2 augment Level-Up schema break** - external Riot trigger + live Arena.
