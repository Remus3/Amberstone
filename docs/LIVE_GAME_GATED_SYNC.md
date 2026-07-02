# Live-Game-Gated Sync Checklist

PURPOSE. One consolidated list of every RC/DS item that CANNOT be finished headless because it
needs one of: a real live LCU session (lobby/champ-select), live game data on `:2999`, rendered
in-game pixels (overlay/vision/OCR), a live-flip EYEBALL of a DS seam re-rank vs a real game,
post-game Match-V5 ingest of a real match, a physical operator keypress over League, or
multi-game ACCRUAL of real-game data. If an item CAN be validated headless (fixture, harness,
dev-preview, replay corpus, unit test, synthetic liveclient) it does NOT belong here - see
"Not actually live-gated (validate headless)" below.

RESYNCED 2026-07-01: full-repo gated-item resync (9 living docs + repo sweep + git-closure audit
+ a seam-flag ground-truth probe). Confirmed-done rows removed (history lives in the ledger below
+ `docs/LEDGER.md`); missing open items added with SOURCE refs; every open row carries an
environment tag at line start: (PRACTICE-SR) / (REAL-SR) / (ARAM-MAYHEM) / (ARENA) / (ANY-LOBBY)
/ (POST-GAME) / (PHYSICAL) / (ACCRUAL). PRACTICE-SR only where bots/dummies + no Match-V5 record
genuinely suffice. Practice-tool limits (operator-confirmed): bots/dummies only, NO real enemy
comps or enemy rune sets, NO allies, custom games NEVER appear in Match-V5, no ranked queue.
ARAM Mayhem (queue 2400, gameMode KIWI, RC MODE_ARAM) gives real comps but is Match-V5
403/excluded - so anything Match-V5- or win-anchored is REAL-SR or ACCRUAL.

The headless loop MAINTAINS this file: every DEFAULT-OFF seam it ships (DSV*/DSP*/RF*/R*)
appends its live default-ON flip here. The loop NEVER flips these blind (charter 4b
do-not-flip-blind). SEAM GROUND TRUTH 2026-07-01: NOTHING is wired-on-live - every seam is
default-OFF at its live call site. DSP2/DSP11/F2/RF1/RF2/RF3 are transport-plumbed across /rank
(item 638) but every live caller omits the flags; DSV2/3/4, DSP4, DSP8, B1, R50/R51/R53 +
Phase-D are ENGINE-ONLY (need route + client plumbing before any eyeball); DSP5/6/7 + anti-tank
P3.2 are producer-only orphans (test imports only); env gates RC_COMP_HP_LEAN /
RC_LANING_CV_SERVED are cold (no supervisor or machine-env wiring).

How to use: operator runs the drain-plan sessions below (replaces the 2026-06-17 bundle plan);
tick each row; report results so the loop's next cycle can flip the validated seams default-ON.
RC auto-serves UI via ADR-008 (no restart for web changes); engine flips need a DS `:8893`
restart. `tools/live_flip_watcher.py` (RC-LiveFlipWatcher task, armed + Running) auto-toasts
seam verdicts during real games; `ops/audit/ds_perm_swarm/live_flip_eyeball.py` dumps OFF-vs-ON
top-6 per (champ, seam), so most seam eyeballs need NO mid-game DS restart.

NOTE (resync ruling): the LGS1 ledger entry's "OPEN1/OPEN2 still pending" reference (2026-06-17,
below) is defined nowhere in the repo - resolved this resync as a stale label with no target;
no row carries it.

---

## A. Champ-select / lobby

- A1. (ANY-LOBBY) LCU push re-confirm tick (residual of the 2026-07-01 FIX): lockfile-rotation
  reconnect shipped (`27f99a95`, `lcu/lcu_client.py` mtime-guarded `_refresh_conn_if_changed`).
  Confirm runes/items/spells push fires on the FIRST champ-select AFTER a League restart
  mid-RC-session, and the pushed page matches the DS pick. SOURCE: docs/LEDGER.md item 711;
  memory reference_runewriter_dies_after_game1.
- A2. (ANY-LOBBY) CS2 summoner-spell auto-push confirm via `/lol-champ-select/v1/session/
  my-selection` (`29cd2788`; role-aware mid-pick fix `1aed8f06` loaded post-restart). STATUS:
  LGS2 was inconclusive (client default already correct); `data/spell_prefs.json` drift shows
  captures accrue - the explicit push/no-revert confirm is still owed. SOURCE:
  docs/ORCHESTRATION_PLAN.md:69.
- A3. (ANY-LOBBY) CC-conditional pairing UI renders on champ-select (`541cd9d3`) - visual
  confirm; scenario-gated (needs a CC-pairing lobby to roll; LGS2 never rolled one).
- A4. (ANY-LOBBY) LOBBY1 top-8 friend-invite live verify (`1f4f4118`) + QA24 non-friend invite
  path end-to-end (needs a real invite target / second account). SOURCE:
  docs/ORCHESTRATION_PLAN.md:63; RC_WORK_TRACKER.md:73.
- A5. (ANY-LOBBY) rc-shell PRE-GAME LOBBY `lcu.lobby.members[]` render (YOUR MAINS / PARTY /
  MY TOP-8; if empty, capture the agent's live `/lol-lobby/v2/lobby` read +
  `_slim_lobby_member` output) + eyeball the overlay surface gate `cac1df3a` (companion in
  lobby/CS, lean HUD once liveclient populates). SOURCE: ledger 2026-06-20 below.
- A6. (ARAM-MAYHEM) E7a bench-swap queue-drain eyeball (`64591d5f`): click a bench champ in a
  real ARAM champ-select and confirm the swap registers visibly faster. SOURCE: ledger
  2026-06-20 below.
- A7. (ANY-LOBBY) E12-L2 RuneWriter lobby-gameMode memoization eyeball (`48fcee51`):
  mode-correct runes/spells still push on champ-select enter; a mode change across
  back-to-back champ-selects re-detects. SOURCE: ledger 2026-06-20 below.
- A8. (PRACTICE-SR) Locked-own-champ champ-select panel captures (a practice/custom lobby
  suffices - self-side data only): ds-sweep graph, ds-relscore bar, ds-statcheck sandbox
  (R52 note: these dashboard panels have no sanctioned audit surface post the 2026-06-27
  overlay-only doctrine - operator call whether moot), ds_skill_order card (R54,
  `7f7b82cb`), personal-build WR card (needs a champ with >=8-game history), build-order
  B-card + its per-page UI-audit ritual. SOURCE: docs/LEDGER.md items 715/717/623/635;
  BACKLOG.md:31; ROADMAP.md:98.
- A9. (REAL-SR) Enemy/ban-dependent champ-select captures (need a real draft lobby):
  OQ9 ban-reason labels (`30bef7bc`), cooldown-watch card (render-gated on committed
  enemies), UIX1 champ-select SR live capture (`3c123060`). SOURCE: docs/LEDGER.md item 726;
  BACKLOG.md:31; docs/ORCHESTRATION_PLAN.md:86.
- A10. (ARAM-MAYHEM) KEYSTONE residual: operator visual reassurance of the rendered bench on a
  future Mayhem champ-select (data path proven; no capture pursued). SOURCE: ROADMAP.md:100.
- A11. (ANY-LOBBY) OVL2 Pengu Surface C live validation (`aab53e37`): real League client with
  the Pengu loader injecting the plugin (operator install step included). SOURCE:
  docs/ORCHESTRATION_PLAN.md:82.
- A12. (ANY-LOBBY) Mode-specific overlay layout AUTO-SELECT-ARAM acceptance (queued for
  planning, not yet built): once built, the auto-select needs a live ARAM queue/lobby state;
  per-mode in-game placement wants an eyeball per map. SOURCE: BACKLOG.md:48.
- A13. (ANY-LOBBY) item 215 carry (a): champ-select rune/item/summoner push + in-game `:2999`
  reads LIVE VERIFY post 1-PC consolidation. STATUS: largely re-proven by the 2026-06-27..30
  live sessions - fold into the session-1/3 ticks and close. SOURCE: ROADMAP.md:78.

## B. In-game - PRACTICE-TOOL-VIABLE (own build / HP / level / stacks; bots + dummies suffice)

- B1. (PRACTICE-SR) Build-chooser pushes correct runes/items/spells mid-game to LCU (3-variant
  + Experimental row).
- B2. (PRACTICE-SR) DS Phase-D default-ON flag flips: `apply_passive_damage`, the 4
  non-every-AA `on_hit`, per-stack `assumed_stacks` - saner-not-different own-build re-rank.
  NOTE: `apply_passive_damage` stays /dps-scoped after OQ17 (matches the R7/R12 precedent -
  `rank_items` does not forward it); the "4 non-every-AA on_hit" are the un-routed remainder
  of that same router, not a distinct seam. /rank exposure + client plumbing still pending.
  SOURCE: ROADMAP DS Phase-D.
- B3. (PRACTICE-SR) DSV seam flips: `assume_takedown` (DSV2) / `assume_squishy_target` (DSV3)
  / `assume_ability_amp` (DSV4) on the BURST scorer `agents/daemon_slayer/burst.py
  rank_items_by_burst` (NOT rank.py). ENGINE-ONLY - route transport WIRED OQ17 (/rank-assassin
  reads all three; /burst also reads assume_takedown + assume_ability_amp; ENGINE 1.168.0).
  Client-helper emit + the live default-ON flip still pending. DS `:8893` restart on flip.
- B4. (PRACTICE-SR) Anti-tank P3.2: wire a survivability/draft surface to call
  `antitank.compute_antitank_live` with the live build + eyeball scaled %max-HP magnitudes.
  HTTP TRANSPORT WIRED OQ18 (`/anti-tank` now routes to `compute_antitank_live` when the body
  carries a non-empty `item_ids`; ENGINE 1.169.0) - headless-prep-done; the eyeball (POST a real
  build + confirm the seeded row scales) stays gated. No DS restart on the live flip.
- B5. (PRACTICE-SR) DSP2 `exempt_offclass_by_win` flip (transport-plumbed; live callers omit):
  Ezreal surfaces Trinity/Manamune, crit ADCs byte-identical. DS restart.
- B6. (PRACTICE-SR) DSP4 `score_completion_runes` flip (Shield Bash 8401): burst-NUMBER delta
  on `compute_burst_damage`/`compute_combo` with a real runes set - direct-call eyeball, NOT
  in the re-rank harness. Route transport WIRED OQ17 (/burst reads it + now parses `runes`;
  ENGINE 1.168.0); the live flip stays pending.
- B7. (PRACTICE-SR) B1 `apply_melee_aa_gate` flip: melee bruiser build drops Runaan's, ranged
  carry byte-identical. ENGINE-ONLY - /dps route transport WIRED OQ17 (/dps-scoped like R7/R12;
  ENGINE 1.168.0); the live flip stays pending. DS restart.
- B8. (PRACTICE-SR) R7 `assume_passive_as_stacks` flip (Irelia/Jax/Ezreal/Volibear at full
  stacks; stacks buildable vs dummies/minions; stack fraction operator-tunable). DS restart.
  SOURCE: ledger 2026-06-19 below.
- B9. (PRACTICE-SR) R5 `assume_missing_hp_heal_amp` flip + live caster missing-HP feed (drop
  own HP vs bots; coach-side hp/hp_max already emitted, item 639). DS restart. SOURCE:
  ledger 2026-06-19 below.
- B10. (PRACTICE-SR) R12 `apply_target_vuln` flip (Vladimir/Evenshroud; broaden the consumer
  beyond AA DPS to ability_dps + burst) + R43 Imperial Mandate rider (4005/224005/324005
  read sanely higher once R12 validates; unmarked wielder byte-identical). DS restart.
  SOURCE: ledger 2026-06-21 + 2026-06-30 below.
- B11. (PRACTICE-SR) R14 `apply_cc_floor`: thread the flag through the compute_ehp /
  compute_hybrid / cc-blended-EHP consumer chain (none thread it yet) + floor-model sanity
  for close-range Maokai/Ashe/Hecarim R. DS restart. SOURCE: ledger 2026-06-22 below.
- B12. (PRACTICE-SR) R17 + R39 anti-tank level-ramp seams (`compute_antitank(level=)`): wire
  the live champion level; level-3 < level-16 sanity (Aatrox-family ramps + Senna P
  current-HP ramp). HTTP TRANSPORT WIRED OQ18 (`/anti-tank` now reads an optional `level` body
  param and threads it into `compute_antitank(level=)`; ENGINE 1.169.0) - headless-prep-done;
  the eyeball (POST the live level + confirm the early-vs-late ramp) stays gated. DS restart
  on flip. SOURCE: ledger 2026-06-22 + 2026-06-30 below.
- B13. (PRACTICE-SR) R30/DSV6 `assume_magic_burst` flip (Luden's/Stormsurge/Malignance on an
  AP burst build ranks its on-cast item higher; compute_ability_dps deliberately inert). DS
  restart. SOURCE: ledger 2026-06-27 below.
- B14. (PRACTICE-SR) R35 `apply_passive_mitigation` + snapshot flip (Galio/Garen/MasterYi
  percent-DR ranks EHP/defensive items higher; rank-4 + 0.3-uptime assumptions read sane).
  DS restart. SOURCE: ledger 2026-06-27 below.
- B15. (PRACTICE-SR) R45 Poppy W low-HP doubled percent-of-resist tier: feed
  `caster_current_hp_pct` (drop own HP), sub-40%-HP EHP ranking sane. DS restart. SOURCE:
  ledger 2026-06-30 below.
- B16. (PRACTICE-SR) R46 `assume_passive_health_stacks` (Sion W / Cho'Gath R / Swain P;
  stacks farmable on minions in practice tool); ideally later replace the assumed-stack
  curve with a live stack feed. DS restart. SOURCE: ledger 2026-06-30 below.
- B17. (PRACTICE-SR) R49 `assume_passive_reflect` (Rammus W): practice-tool BOTS do attack,
  so the 1.0s cadence + 3.0s window assumptions are exercisable; ranking-vs-real-comp is
  the stricter read (re-check in the Mayhem game). DS restart. SOURCE: ledger 2026-06-30
  below.
- B18. (PRACTICE-SR) R51 `gate_target_hp_amp` per-instant consumer (dummy HP is settable) -
  per-instant / stepped scenario eval, NOT a blind burst-scorer flip. Route transport WIRED
  OQ17 (/burst reads it + `target_current_hp_pct`; ENGINE 1.168.0). SOURCE: ledger
  2026-07-01 below.
- B19. (PRACTICE-SR) R53 `gate_caster_hp_amp` per-instant consumer (own HP droppable) - same
  per-instant discipline. Route transport WIRED OQ17 (/burst reads it + `caster_current_hp_pct`;
  ENGINE 1.168.0). SOURCE: ledger 2026-07-01 below.
- B20. (PRACTICE-SR) OQ1/R55 `assume_archetype_hp_pct` 3-game own-build re-rank eyeball
  (BotRK 3153 / Hellfire 4017 / Fulmination 443055 only; bruiser/marksman BotRK neither
  over- nor under-ranks). The 0.5 sustained-fraction CALIBRATION is an ACCRUAL tail (G14).
  DS restart. SOURCE: docs/LEDGER.md item 718; ledger 2026-07-01 below.
- B21. (PRACTICE-SR) 627-630 objective-state rows live validation (take drake/baron/herald in
  practice tool; `:2999` emits the events; all validation so far was client-mode). SOURCE:
  ROADMAP.md:16.
- B22. (PRACTICE-SR) Inhibitor-callout fires when an inhib is down (destroy one in practice
  tool) - also the post-`7b325e3e` live confirm that event-derived siege/objective callouts
  fire at all. SOURCE: ROADMAP.md:47; docs/LEDGER.md item 643.
- B23. (PRACTICE-SR) OQ16 objective-gauge widget in-game overlay capture (`w-objgauges`;
  gates on mode_key sr + finite game_time - practice tool registers as SR). SOURCE:
  docs/LEDGER.md item 730.
- B24. (PRACTICE-SR) Overlay populated pixel-capture family (over a live practice game):
  OVL1 settings controls (`4d09f8ac`); R33 ward_cue / spike_cue / objective_chips /
  minimap_zoi / minimap_rect (`9eb644c9`); R40 draft_elo chip + ward_heat strip
  (`b06ec877`); W3E callouts + lead_projection; spike-markers live-clock cursor; item 662
  first-match no-flash confirm. SOURCE: docs/ORCHESTRATION_PLAN.md:81/231/239;
  ROADMAP.md:55; BACKLOG.md:31; docs/LEDGER.md item 662.
- B25. (PRACTICE-SR) Overlay build-module interaction round-trips: D1 tooltip hover, D2
  right-click radial + zone flip/wedge clicks landing mid-game, D3 override survives a
  re-plan + Defer-Once re-entry + reset (plus the cross-tick LIVE-route Defer-Once
  per-match store gap - code work), settings-slider drag mid-game, B2/B3/C5 module
  captures. SOURCE: docs/LEDGER.md items 670-680.
- B26. (PRACTICE-SR) ZOI shading alpha/blur live tune (MAX_ALPHA 0.55 / ZOI_BLUR_PX 12
  shipped, pending operator verify) + `#rn-choices` live DOM inspect (has data + renderer
  runs, absent in DOM). The ARAM flood-tint question re-checks in the Mayhem game. SOURCE:
  docs/LEDGER.md item 688.
- B27. (PRACTICE-SR) LBAND1 live wire-in eyeball: `core/live_benchmark_band` into the
  deterministic-coaching surface + overlay (live cs+level vs own per-champion percentile).
  SOURCE: BACKLOG.md:148.
- B28. (PRACTICE-SR) Vision-region calibration frame (`data/vision_regions.json`; grab
  `:8889/latest-frame` in-game; ARAM-specific HUD regions ride the Mayhem game). SOURCE:
  ROADMAP.md:114; RC_WORK_TRACKER.md:129.
- B29. (PRACTICE-SR) QA6 fullscreen-detect "switch to Borderless" hint + QA13 UIPI
  elevation-parity detect final validation (low-confidence inferred rows; build headless
  first). SOURCE: RC_WORK_TRACKER.md:63/65.
- B30. (PRACTICE-SR) DS ratio-block spot verify vs target dummies (~174/577 flagged;
  DS-batch scoped - sample a handful per session, not a bulk pass). SOURCE:
  docs/DS_COMPLETENESS_GAP.md:79; docs/OVERLAY_BUILD_MASTER_PLAN.md:496.
- B41. (PRACTICE-SR) R58 `assume_ms_utility` flip (bruiser/juggernaut MS-utility DPS
  credit): buy Dead Man's Plate 3742 + Force of Nature 4401 on a juggernaut (Darius) in
  practice tool, eyeball the /rank-bruiser re-rank sanity (MS items gain modest credit,
  order stays sane; Warmog-class MS-less items unchanged) before defaulting ON; the 0.5
  fraction / 0.15 cap midpoints are the tunables. DS restart. SOURCE: docs/LEDGER.md
  item 738; ledger 2026-07-02 below.

## B (cont). In-game - REAL-SR REQUIRED (real enemies / allies / combat pressure)

- B31. (REAL-SR) DSP5 summoner-spell plumb + eyeball: player's + ENEMY's live summoner sets
  into `dsp_live_consumers.summoner_fight_adjustments`; re-anchor wiki magnitudes at flip.
  HTTP TRANSPORT WIRED OQ18 (NEW POST `/summoner-fight-adj` route reads the producer;
  ENGINE 1.169.0) - headless-prep-done; the live plumb (feed the real summoner set + eyeball)
  stays gated.
- B32. (REAL-SR) DSP6 enemy-rune threat plumb + eyeball: ENEMY's live rune set into
  `dsp_live_consumers.enemy_rune_threat` (PtA/Conqueror/Grasp shifts; no-threat lobby
  unchanged). Practice tool has NO enemy rune sets. HTTP TRANSPORT WIRED OQ18 (NEW POST
  `/enemy-rune-threat`; ENGINE 1.169.0) - headless-prep-done; live plumb stays gated.
- B33. (REAL-SR) DSP7 ally aura/enchanter plumb + eyeball: live ally team into
  `dsp_live_consumers.ally_protected_ehp` (ally beside Janna/Lulu/Soraka shows higher EHP;
  solo ally unchanged). Practice tool is solo. HTTP TRANSPORT WIRED OQ18 (NEW POST
  `/ally-protected-ehp`; ENGINE 1.169.0) - headless-prep-done; live plumb stays gated.
- B34. (REAL-SR) DSP8 `target_preset` derived from the LIVE enemy comp into burst /
  /rank-assassin (lethality vs tank comp, magic pen vs high-CC comp). ENGINE-ONLY -
  /rank-assassin route transport WIRED OQ17 (ENGINE 1.168.0); the live enemy-comp derivation
  into the body + the flip stay pending. DS restart.
- B35. (REAL-SR) R9 `assume_passive_flat_mitigation`: flip in the live survivability path +
  tune `_ASSUMED_FLAT_DR_INSTANCES`=6 / `_ASSUMED_ABILITY_RANK`=4 vs a real fight clock
  (needs sustained real incoming pressure). SOURCE: ledger 2026-06-21 below.
- B36. (REAL-SR) R50 `apply_all_out_bonus` (K'Sante): confirm the empowered-mark value in an
  actual All Out fight + tune `conditional_probability` 0.5 vs real All-Out uptime. DS
  restart. NOTE: OQ17 EXCLUDED this seam - `apply_all_out_bonus` is a load-time
  `AbilitiesSnapshot.load()` flag (abilities.py:610), NOT a per-call compute param, so it is
  not a pure HTTP flag-flip; burst compute always uses the cached flags-off `load_default()`
  snapshot. Threading it needs per-request snapshot construction (separate task, logged
  FUTURE). SOURCE: ledger 2026-07-01 below.
- B37. (REAL-SR) L4 capability-gap live validation with `RC_CAPGAP_SURFACE=1` (gap detectors
  key on real enemy champion identity). SOURCE: ROADMAP.md:16; docs/LEDGER.md items
  631-634.
- B38. (REAL-SR) RC2 P3.3/S0 pulse-rationing remaining eyeball: suppressed pulses were all
  benign re-emits AND the Emergency tier / one-shot Urgent cross still glows (lethal cues
  need real combat pressure - the item-598 capture verified only the suppression half).
  SOURCE: ledger 2026-06-20 P3.3 below.
- B39. (REAL-SR) RC2 P4.1-P4.5 composited-over-a-real-League-game eyeballs at 2560x1440
  borderless (DPI/dock sizing; opacity recede + idle dim + hover zones + drag strip;
  separated-window arrangement; #ovset panel selector + Interact-now; Re-arrange + Show
  dashboard). P4.6 IS this whole-of-Phase-4 checklist. rc-shell MAIN relaunch first.
  Geometry halves are practice-tool-acceptable; combat-driven cues want a real game.
  SOURCE: ledger 2026-06-20 P4.x entries below; item 686 proved the 4.1 ovscale model
  live-buggy once already.
- B40. (REAL-SR) Live UI watch standing ritual (items 243/244): tick champ-select + in-game
  dashboard vs `/api/state` each ranked game (standing per-game, not one-shot). SOURCE:
  ROADMAP.md:56.

## C. ARAM / ARAM Mayhem (queue 2400, KIWI)

- C1. (ARAM-MAYHEM) Build-chooser populates + pushes for ARAM picks; comp-aware row-3 MAYHEM
  tip renders.
- C2. (ARAM-MAYHEM) Comp-verdict VARIANT branch still unobserved (SWAP + STAY validated at
  LGS2); rides champ-selects until a variant scenario rolls. Soundness check moved to the
  headless list.
- C3. (ARAM-MAYHEM) DSP3 ARAM archetype-override flip (`prefer_aram_win_axis=True`): needs a
  tabled Cluster-A champ to roll (Zilean/Shaco/Shyvana/Taric/KogMaw/Kayle). RC-side
  resolver, NO DS restart.
- C4. (ARAM-MAYHEM) DSP11 kit-axis flip [LIVE-VALIDATED 2026-06-17 - FLIP-READY]: lethality
  (Senna) + crit (Quinn) + negative control (Caitlyn) validated live; residual = the
  Ezreal/Corki manamune sub-case + the operator flip decision. DS restart on flip.
- C5. (ARAM-MAYHEM) RF1 bruiser survivability flip [LIVE-VALIDATED 2026-06-18 Yasuo -
  FLIP-READY]: 1 of 9 tabled bruisers eyeballed (SANER); flip stays operator-gated + DS
  restart; further tabled rolls (Darius/Udyr) optional.
- C6. (ARAM-MAYHEM) RF2 enchanter survivability flip: Rakan-as-tank-support INJECTs + floats
  Warmog's/Heartsteel; Soraka/Janna byte-identical. DS restart.
- C7. (ARAM-MAYHEM) RF3+RF6 tank survivability flip: KSante floats Thornmail/Iceborn, Rell
  Fimbulwinter INJECTed past the purchasable gate; Malphite/Ornn byte-identical. DS restart.
- C8. (ARAM-MAYHEM) F2 `cost_ceiling` flip eyeball: exclude the 6000g Void Immolation 223069
  from bruiser/tank rank-1 (premise reproducible via a headless /rank-bruiser query; the
  re-ranked top-6 eyeball wants the ARAM mega-item context). DS restart.
- C9. (ARAM-MAYHEM) T1-F3 enemy-pen-aware effective-resist EHP flip (opt-in
  enemy_lethality/enemy_*_pen kwargs on compute_ehp): needs real enemies carrying real pen
  items - bots do not build them. SOURCE: BACKLOG.md:32.
- C10. (ARAM-MAYHEM) R41 `assume_ally_detonation` (Leona P Sunlight): needs real ALLIES
  consuming marks; 2.5s cadence + 0.5 proc-rate sanity. DS restart. SOURCE: ledger
  2026-06-30 below.
- C11. (ARAM-MAYHEM) cc_blended_ehp + cc_conditional ecosystem live validation (all 9
  consumer surfaces shipped headless; needs real enemy comps casting real CC). SOURCE:
  BACKLOG.md:23.
- C12. (ARAM-MAYHEM) Antiheal/grievous deterministic callout in-game visual (fires on
  sustain-heavy enemy comps - opportunistic per lobby). SOURCE: ROADMAP.md:47;
  BACKLOG.md:37.
- C13. (ARAM-MAYHEM) R38 enemy_spells tap-tracker + stats_panel populated in-game capture
  (allPlayers-fed; best vs real enemies). SOURCE: docs/LEDGER.md item 692.
- C14. (ARAM-MAYHEM) RC_ARAM_STATE_DEBOUNCE default-ON flip validation: prove the
  state-signature does not stale the coach mid-fight vs real enemies (a replayed-game feed
  is an allowed alternative - try headless first). SOURCE: BACKLOG.md:64.
- C15. (ARAM-MAYHEM) Augment recommender OCR -> rank vs the pick made (Mayhem in-game
  augment-select satisfies it; Arena avoidable for this row). SOURCE: ROADMAP.md:122.
- C16. (ARAM-MAYHEM) s244 carry: live Mayhem augment-select RENDER validation (proven only by
  snapshot fixtures). SOURCE: ROADMAP.md:94.

## D. Arena / Cherry (queue 1750) - ARENA REQUIRED: every row here is Arena-only, FLAG LOUDLY

- D1. (ARENA) Arena 6x3 champ-select visual capture - STATUS UNCLEAR: ROADMAP.md:18 records
  champ-select COMPLETE across SR/ARAM/Arena via the headless ui_mock fixtures; keep only if
  the operator still wants a live Arena capture beyond the fixture render. Re-check before
  booking the game. SOURCE: ROADMAP.md:97 vs :18.
- D2. (ARENA) set_augment_intent 4-PATCH endpoint discovery at a real Arena augment phase
  (`tools/gamepc_lcu_agent.py:1179` - path is stale post Game-PC retirement, re-home the
  chain before running; recipe `docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md`). SOURCE:
  ROADMAP.md:113.
- D3. (ARENA) Arena boots 22xxxx mirror residual: augment-phase VISUAL confirm the pushed boot
  renders (icon may 404 per reference_items_index_alias_ids, display name correct). The data
  fix itself shipped headless (real commit `54d0706a`; the `c258c4ab` hash cited in older
  docs does not resolve). SOURCE: ROADMAP.md:43; docs/LEDGER.md item 499.
- D4. (ARENA) `apply_mode_modifiers` Arena re-rank validate (Arena ar/swift growth-addends are
  the only schedulable mode where this seam re-ranks; URF/OFA/USB/NB rotate). DS restart.
  SOURCE: BACKLOG.md:27; ROADMAP.md:69.
- D5. (ARENA) RC_ARENA_STATE_DEBOUNCE default-ON flip validation (a replayed-game feed is an
  allowed alternative - try that first to dodge Arena). SOURCE: BACKLOG.md:64.
- D6. (ARENA) Arena augment-select shadow (`data/augment_shadow.jsonl`) + item-anvil shadow
  (`data/anvil_shadow.jsonl`) seeding: ZERO rows on disk 2026-07-01 - the first Arena game
  seeds both files; ongoing multi-game accrual then follows the section-G rail pattern.
  SOURCE: commits 0c75a469 + 5da48ade.
- D7. (ARENA) Arena PGR capture (Arena IS Match-V5-eligible, unlike Mayhem). SOURCE:
  ROADMAP.md:48.
- D8. [HOLD 2026-06-20] (ARENA) Arena S2 augment level-up + crafting - trigger on 26.09 PBE
  (separate PBE install). SOURCE: RC_WORK_TRACKER.md:126.

## E. Physical / operator-hardware (over a running League game on Legion)

- E1. (PHYSICAL) ACTIVE knob-interaction round-trip - NEEDS ADJUDICATION: physical hotkey
  delivery IS live-verified 2026-06-28 (WH_KEYBOARD_LL; Ctrl+Shift+A/B stamp signals under
  League focus, LEDGER 638/640/641), but a knob -> ACTIVE -> 20s-auto-revert round-trip
  confirm over League is not recorded. Do NOT re-attempt headless (synthesized presses leak
  into the game; rcShell bridge is preload-only).
- E2. (PHYSICAL) Ctrl+Shift+B VISIBLE panel-cycle confirm in-game (listener layer proven;
  rc-shell has since relaunched, but an in-game visible-cycle press is not recorded).
  SOURCE: docs/LEDGER.md item 640.
- E3. (PHYSICAL) rc-shell Electron MAIN relaunch owed (disappear-fix/pinned behavior + the
  P4.x window logic) + the post-W5 interaction-layer live verify pass
  (docs/OVERLAY_BUILD_MASTER_PLAN.md:666 - the 2026-06-29 F1-01 confirm covered render
  surfaces only). SOURCE: ROADMAP.md:23; docs/OVERLAY_BUILD_MASTER_PLAN.md:666/828.
- E4. (PHYSICAL) OBS DXGI match-end capture watch: lock one resolution + League Borderless
  while recording; observe a real match end. SOURCE: ROADMAP.md:78(c).

## F. Post-game / Match-V5 (a real MATCHMADE NON-EVENT match - practice customs and Mayhem
   q2400 never reach Match-V5)

- F1. (POST-GAME) PGR visual capture S3/S4/S5 + @N timeline metrics (gold@10/cs@10 need
  per-participant Match-V5 frames). SOURCE: ROADMAP.md:48.
- F2. (POST-GAME) REPLAY1: Replay/Session/History ingest freshness after a real game end (90s
  Match-V5 writer, `647b455e`). SOURCE: docs/ORCHESTRATION_PLAN.md:65.
- F3. (POST-GAME) PGR auto-show on game-end live confirm (real commit `a7714376`; the
  `68b6cc54` view-router hash cited in LEDGER item 520 does not resolve; a fired instance
  is not recorded anywhere). SOURCE: docs/LEDGER.md item 520.
- F4. (POST-GAME) Per-page UI-audit ritual on the next live PGR open. SOURCE: ROADMAP.md:109.
- F5. (POST-GAME) rewind_history.db SR records with game_id (wired `d66d14b`). STATUS: likely
  stale - queue-420 rows now number 516; probe the DB for populated game_id BEFORE booking a
  game for this. SOURCE: RC_WORK_TRACKER.md:107; BACKLOG.md:28.
- F6. (POST-GAME) R47 PGR child-panel capture - UNCLEAR / likely moot (the entry itself says
  the baseline render is byte-identical, so there is no pixel delta to capture); operator
  call to discharge as no-op. SOURCE: docs/LEDGER.md item 702.

## G. ACCRUAL rails (many games; re-run the rail, NEVER flip on one game)

- G1. (ACCRUAL) HZ Lane-A laning-agreement flip gate - HOLD: R32 re-measured 2026-06-27 on
  24,289 shadow records, flip readiness NOT met (comparable agreement 0.4662; the new
  all_in->hold Renekton-vs-Gragas pocket logged FUTURE). Rail: accrue real SR laning ticks
  -> `tools/hz_shadow_report.py` -> operator OK. SOURCE:
  ops/audit/HZ_REMEASUREMENT_2026-06-27.md.
- G2. (ACCRUAL) HZ Lane-B build-order flip gate - HOLD (@651 SR +2.3pp coin flip, 1/51
  per-item carriers). Rail: `tools/replay_build_order_validate.py --limit 0` as
  rewind_history.db grows. HEADLESS PREREQ: regen the build-order tables to the live engine
  first (16.13.1 tables stamp 1.151.0 vs live 1.166.0).
- G3. (ACCRUAL) Champ-select brief Haiku -> deterministic flip: shadow-log accrual over real
  champ-selects + operator OK (`dashboard/_champ_select.py`).
- G4. (ACCRUAL) ~88 `st-*` ADAPTATION live-producer census (rows render "-" in-game): note
  which surface live vs stay post-game-only; rides games. SOURCE: ROADMAP item 281.
- G5. (ACCRUAL) RC2 P5.1/P5.2 CV laning: accrue `cv_override` rows in
  `data/hz_choice_shadow.jsonl` -> re-run hz_shadow_report WITH the CV layer -> set
  `RC_LANING_CV_SERVED=1` at >=70% agreement (tighten the ~8s stale-chip cache sig in the
  same flip slice if the eyeball shows lag).
- G6. (ACCRUAL) DS calibration pipeline: needs ~20+ RANKED SR (queue 420) games - customs and
  Mayhem cannot feed it. SOURCE: ROADMAP.md:115.
- G7. (ACCRUAL) post_game_score LR retrain at N>=20 real timelines
  (`core/post_game_score.py:220`). SOURCE: docs/OVERLAY_BUILD_MASTER_PLAN.md:500.
- G8. (ACCRUAL) hz_mismatch ground-truth cross-ref: richer rewind SR coverage per matchup
  (most calibration classes read insufficient_data). SOURCE: ROADMAP.md:44.
- G9. (ACCRUAL) Draft-Elo pairwise WR corpus densification (tightens as matchmade games
  accumulate). SOURCE: RC_WORK_TRACKER.md:127.
- G10. (ACCRUAL) B1 det_coach_shadow / WS3 objective_playbook_shadow / WS4
  macro_response_shadow flip gates (rows accruing: ~37.6K / 33.6K / 32.7K on 2026-07-01;
  the flip decisions themselves are pending). SOURCE: commits 8470c3cc / 6a615fad /
  0949fde5.
- G11. (ACCRUAL) A3 tail: surface the DS-coach hints (anti-tank + scaling power-curve,
  SHADOW-only per item 328) only after `data/ds_coach_hints_shadow.jsonl` accrues +
  validates. SOURCE: ROADMAP.md:41.
- G12. (ACCRUAL) ADR-007 phase 3 prose-coach deprecation - after phase-1 detectors prove out
  in real games. SOURCE: ROADMAP.md:112.
- G13. (ACCRUAL) E2 umbrella: the DS 3-game live-flip pass (operator-played; rides the
  drain-plan sessions below). SOURCE: ROADMAP.md:23; RC_WORK_TRACKER.md:134.
- G14. (ACCRUAL) OQ1/R55 sustained-fraction calibration: replace the 0.5 design midpoint with
  a measured average-current-HP-over-fight (lolmath baseline impossible - site parked).
- G15. [HOLD] (ACCRUAL) HZ-A v4 laning-table regen + shadow validation - blocked on a real
  ALIVE laning tick existing (zero today) + the 190MB monolith-vs-shard commit decision.
  SOURCE: BACKLOG.md:54.
- G16. [PARKED] (ACCRUAL) Aggregator N F2 per-slot item win-rate ladder - defer until a richer
  corpus exists. SOURCE: BACKLOG.md:15.

## PARKED / HOLD (one line each)

- [PARKED 2026-07-01] (REAL-SR) ZOI per-champion minimap detection: color/size/motion
  isolation live-confirmed dead-end; operator wants a FUTURE exploration only (sub-second
  frame-diff + portrait template-match combo; memory project_zoi_minimap_reality) - not
  scheduled. Native-res grab (`f9ebcd3f`) stays as the foundation.
- [PARKED 2026-06-20] (REAL-SR) Overlay-App-E-style enemy ult/ability CD timers (needs enemy
  cast-detection via vision). SOURCE: RC_WORK_TRACKER.md:50.
- [HOLD] (REAL-SR) HZ-A choice-B even<->hold band flip (+57 ticks quantified; operator-gated,
  not applied). SOURCE: RC_WORK_TRACKER.md:111.
- [HOLD] (ARAM-MAYHEM) DS target-current-HP% / enemy-pen product-call flips (operator
  off-meta-chase decision first, then the C9/B20 eyeballs). SOURCE:
  docs/OVERLAY_BUILD_MASTER_PLAN.md:429.
- [PARKED] (PHYSICAL) OBS publisher - dormant until the operator streams. SOURCE:
  RC_WORK_TRACKER.md:125.

## Not actually live-gated (validate headless) - moved OFF the checklist this resync

- Operator packaging: `npx electron-builder` + first GitHub Release + packaged update check -
  operator/release-gated, needs NO game.
- DSV5 RC_COMP_HP_LEAN default-ON flip AUTHORIZATION: the live eyeball is DONE 2026-06-23
  (R24, SANER NOT DIFFERENT); the remainder is ONE operator env / frozen-file decision
  (`ops/rc_supervisor.py` env or machine env) - consolidates the tripled ledger obligation
  (R24 / ledger 592 / ledger 593) into a single non-game decision.
- OQ13 `#home-weekly-digest` Electron-COMPANION capture: needs rc-shell running on the Legion
  desktop, NOT a game (companion is hidden in-game by design). Backend live-proven on
  `/api/home/summary`. SOURCE: docs/LEDGER.md item 733.
- OQ12 PGR bench sub-lines Electron capture: the real Vayne SR payload already sits in the DB
  (`/api/last-match` live-proven); launch the companion and capture - no new game needed.
  SOURCE: docs/LEDGER.md item 732.
- Comp-verdict SOUNDNESS check (Vex->Garen "all-AD comp - mix damage type" reads inverted):
  code-logic review of `core/aram_comp_verdict.py`. SOURCE: LGS2 findings below.
- champ_select pickban-DB flip counter-quality validation (headless vs the rewind corpus).
  SOURCE: ROADMAP.md:55.
- ability_hps v2 wiring validation vs real enchanter BUILD data (rewind corpus). SOURCE:
  ROADMAP.md:72.
- item 211 seven residual orphan rows (1640/1633/1519/1518/1517/1506/1487): needs live RC +
  the Riot key + an operator per-row decision - no game. SOURCE: ROADMAP.md:82.
- UI scale v2.1 pages #11/12/13 + item 212(b) chooser-row captures: the ui_mock/recon.py
  fixture harness covers these (ROADMAP.md:18) - re-check there before ever booking a lobby.
- DS cross-eval A/B/F2 rewind-WIN validations (`ops/audit/ds_cross_eval/` harness over
  rewind_history.db; residual gate = operator decision). SOURCE: BACKLOG.md:11.
- HZ-B build-order table regen to ENGINE 1.166.0 (deterministic --static path; the headless
  prereq for rail G2).
- R2 carry-efficiency grade fold default-ON re-baseline (computable over the existing corpus;
  operator decision). SOURCE: RC_WORK_TRACKER.md:112.
- Same-state Haiku-skip fidelity proof: try replay/logged-state validation first; only fall
  back to the C14/D5 live rows if logs prove insufficient. SOURCE: RC_WORK_TRACKER.md:123.
- item-WPA build-insights view capture (`?ui_mock=1#build-insights` renders from the local
  corpus). SOURCE: BACKLOG.md:35.
- WP-F4a ward-stack keep-vs-retire (operator decision; Match-V5 carries NO ward positions so
  KEEP is likely infeasible; the retire path is fully headless). SOURCE:
  docs/OVERLAY_BUILD_MASTER_PLAN.md:824.
- RF2-hps `inject_ids` sibling (future headless slice; already logged FUTURE in the ledger
  below).

---

## Drain plan 2026-07-01 (operator prefs: practice SR / ARAM Mayhem / Arena only if needed)

PREP (headless, before session 1): plumb the ENGINE-ONLY seams across /rank + client (DSV2/3/4,
DSP4, DSP8, B1, R50/R51/R53, Phase-D) or lean on `live_flip_eyeball.py` OFF-vs-ON dumps; wire
the DSP5/6/7 + P3.2 consumers to live inputs; relaunch rc-shell (E3 - picks up the P4.x MAIN
logic); confirm RC-LiveFlipWatcher armed; regen HZ-B tables to 1.166.0; probe F5 (rewind
game_id) and D1 (Arena fixture coverage) so neither books a game it does not need.

SESSION 1 - PRACTICE TOOL SR (1 custom lobby + 1-2 practice games, one sitting).
Champ-select (practice lobby): A8 panel captures, A1 LCU-push re-confirm (restart League
mid-RC-session first, then enter champ-select), A2 CS2 spell push, A7 E12-L2, A3 CC-pair UI if
it rolls. In-game: B1 build-chooser push; the practice-viable seam eyeballs B2-B19 (harness
dumps + live_flip_watcher toasts; DS restarts batched); B20 game 1/3; B21 objective rows (take
drake/baron); B22 inhibitor callout (destroy an inhib); B23 OQ16 gauges capture; B24 overlay
capture family; B25 D-series interactions; B26 ZOI tune; B27 LBAND1; B28 vision-region frame;
B29 QA6/QA13; B30 ratio spot-checks; B4 anti-tank P3.2 wire eyeball. PHYSICAL over this game:
E1 ACTIVE-knob round-trip, E2 Ctrl+Shift+B visible cycle, E4 prep, B39 geometry halves.

SESSION 2 - REAL SR (1 matchmade draft game; make it RANKED to feed rail G6).
Champ-select (draft): A9 ban/enemy captures, A4 invite verify pre-queue. In-game: B31-B33
DSP5/6/7 plumbed eyeballs; B34 DSP8 preset; B37 L4 capgap flag-ON; B35 R9 fight-clock tune;
B36 R50 if K'Sante is played (else defer to any later real game); B38 P3.3/S0 Emergency
eyeball; B20 game 2/3; B40 live UI watch tick; A13 close-out. Post-game (this is the
Match-V5-eligible match): F1 PGR S3/S4/S5 + @N capture, F2 REPLAY1 freshness, F3 PGR
auto-show, F4 PGR UI-audit ritual, F5 game_id probe confirm, F6 operator no-op call.

SESSION 3 - ARAM MAYHEM (1-2 games, queue 2400, one sitting).
Champ-select: A6 bench-swap, A10 bench reassurance, C2 VARIANT (scenario-gated), A3 CC-pair if
it rolls; pick tabled champs when the bench offers them (Rakan / KSante or Rell / a Cluster-A /
Ezreal or Corki) to drain C6/C7/C3/C4-manamune. In-game: C1 build-chooser + MAYHEM tip; C8
cost_ceiling eyeball; C9 enemy-pen flip; C10 R41 if Leona; C11 cc ecosystem; C12 antiheal
(opportunistic); C13 enemy_spells/stats capture; C14 debounce (if the headless replay proof
fell short); C15 augment OCR rank-vs-pick; C16 augment-select render; B17 R49 stricter read;
B20 game 3/3; B28 ARAM HUD regions.

SESSION 4 - ARENA (1 game, queue 1750) - ONLY because open Arena-only items remain.
ARENA NEEDED: YES - items: D1 6x3 champ-select capture (re-check fixtures first), D2
set_augment_intent endpoint discovery, D3 boots-mirror augment-phase visual, D4
apply_mode_modifiers re-rank, D5 arena-coach debounce (try the replay alternative first), D6
augment + anvil shadow seeding (accrual can only start here), D7 Arena PGR capture. If D1 and
D5 discharge headless and the operator defers D4/D6, the session can slip - but D2/D3/D7 have
NO non-Arena path.

ACCRUAL items (ride every session; close on later cycles, never on one game): G1 Lane-A
(`tools/hz_shadow_report.py`), G2 Lane-B (`tools/replay_build_order_validate.py --limit 0`
after the table regen), G3 brief-flip shadow, G4 st-* census, G5 CV P5.1/5.2
(hz_shadow_report WITH CV -> RC_LANING_CV_SERVED=1 at >=70%), G6 DS calibration (RANKED only),
G7 LR retrain, G8 hz_mismatch coverage, G9 Draft-Elo corpus, G10 B1/WS3/WS4 shadow gates, G11
A3 hints, G12 ADR-007 deprecation, G13 E2 umbrella, G14 R55 calibration tail.

ESTIMATED SESSIONS TO DRAIN ONE-SHOT ITEMS: 4 (practice SR -> real SR -> ARAM Mayhem ->
Arena); scenario-gated residue (C2 VARIANT, A3 CC-pair, tabled-champ rolls, C12 sustain comps,
B36 K'Sante) may spill into 1-2 extra Mayhem/SR sittings. The accrual tail (G1-G14) closes
over normal play across later cycles, not in these sessions.

---

## Doc hygiene follow-ups (2026-07-01 sweep) - PROPOSALS for the operator / next session, not applied here

(a) Stale rows found in other docs:
- ROADMAP.md:90/92/105-108 - s220 PGR reframe still listed pending; it shipped (line 76 +
  `372b568b`). Prune all five carries.
- ROADMAP.md:50/52 - "DS resist exclusions (Anivia P / Orianna E)" listed open; the cutover
  shipped default-ON item 321 (line 48 says so). Mark done.
- ROADMAP.md:88/97 - pages #11/12/13 + Arena 6x3 captures predate the ui_mock headless harness
  (line 18). Re-mark headless or close.
- ROADMAP.md:14 - "awaits live ARAM/Arena/Brawl trace data to root-cause" is stale; the
  slow-tick root cause is CONCLUSIVE (LEDGER 640, two live games).
- ROADMAP.md:111 - trim the s214/s215 live-ARAM row to the unverified residue (the line-56
  watches covered the rest).
- ROADMAP.md:130 - fleet stamp "ENGINE 1.121.0 / 16.12.1 as of 2026-06-14" badly drifted; drop
  the parenthetical or refresh it.
- ROADMAP.md:120 - Peer auto-action lanes row orphaned post the Peer decommission; verify + prune.
- README.md:21/46/48/54/56/62/71 - Brawl still listed as covered, DS counts 547/6142 stale,
  two-machine topology + third-machine-bridge prose stale (counts = DS-batch docs-sync job).
- docs/ARCHITECTURE.md:165-166 - item-276 "Live in-game validation OWED" is stale (live
  self_grab frames proven, LEDGER 685/688/711). Also :47/:228 tkinter prose contradicts the
  shipped asyncio loop.
- docs/ORCHESTRATION_PLAN.md:247 - C-phase visual path bullet still cites Claude_Preview vs
  :8888 (cannot attach, per R2); name the Playwright harness + :8810 static preview instead.
  :81 - "(Game-PC MCP :8892 down)" is stale (machine retired). :42 - annotate that OQ16's owed
  capture supersedes the OQ3 findings-entry capture.
- docs/OPERATIONS.md:69 vs :168-174 - RC-DS-MatchDB-MCP registered-vs-pending contradiction;
  reconcile.
- BACKLOG.md:28 - rewind SR game_id "blocked on new records" likely stale (queue-420 rows
  exist; probe first). :30 - the Item Shaper "100% champion coverage" blocker appears
  satisfied (172-173 champs covered); lift or restate.
- docs/OVERLAY_BUILD_MASTER_PLAN.md:828/:666/:422 - F1-01 confirmed 2026-06-29 but still in
  the plain GATED list; the post-W5 interaction pass is unmarked; the F.2 header overclaims
  "All GATED" (lines 427/430 are headless).
- RC_WORK_TRACKER.md:69 - QA17 weekly mode-factored digest shipped as OQ13 (LEDGER 733); move
  to CLOSED. :24 - the QA11 owed-example sentence is superseded by line 121. :139 - QA96 is
  misfiled in the GATED-LIVE bundle (it is the release-gated name-scrub, line 144).
- CLAUDE.md (Vision pipeline) - "screen_agent.py POSTs frames every 2s" is stale (continuous
  loop retired; on-demand in-process self-grab is the producer).
- Share/docs/05_AUDIT_AND_REFACTOR.md:20-21 - "7144 tests / 227 files" stale vs the fresh
  7733-passed run at 1.166.0 (DS-batch docs job).
- Stale-hash citations to correct wherever they appear OUTSIDE append-only ledgers: LGS1
  `ba3d3ea1` -> `67c10a0a`; item 499 `c258c4ab` -> `54d0706a`; item 508 `4623edd7` ->
  `5db73817`; QA4 chips `f570f527` -> `03c8d49b`; item 520 view-router `68b6cc54` ->
  `a7714376` (fix(ui): auto-show Post Game Review on game-end).

(b) Archive candidates (top ~15; operator-gated moves to docs/_archive/, links updated on move):
1. tools/DISTRIBUTION_LAYOUT.md - April distribution-era doc, unreferenced.
2. tools/LAUNCH_STRATEGY.md - April launch strategy, superseded by supervisor + OPERATIONS.
3. tools/PYTHON_BUNDLING_STRATEGY.md - bundling decision long settled.
4. tools/PEER_ROADMAP_SUGGESTIONS.md - Peer bridge decommissioned 2026-06-24; dead artifact.
5. tools/done-peer.md - dead Peer /done ritual mirror.
6. docs/API_SURFACE_AUDIT.md - one-shot generated audit; its parent plan already archived.
7. tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md - one-shot probe, complete.
8. docs/DS_GAP_COMPLETION_PLAN.md - session executed; unreferenced by living docs.
9. docs/UI_SCALE_SPEC_V2.md - draft superseded by the RC2 redesign program.
10. docs/CAPTURE_101QQ_INSTRUCTIONS.md - item 277 is live-wired; the capture recipe is history.
11. docs/LCU_PHASE_CAPTURE_WATCHER_PLAN.md - explicit SHIPPED 2026-05-27 marker.
12. ops/audit/P0_INVENTORY.md + P0_WORKMAP.md + P1_INVENTORY.md - deep-audit cycle-1
    baselines; phases done.
13. ops/audit/P2W4_TOOLS_SLICES.md + P2W4_HW2_SLICES.md + P2_FANOUT_MANIFEST.md - executed
    fanout manifests (KEEP ops/audit/P2_FINDINGS.md - living DEFER ledger).
14. ops/audit/ds_cross_eval/reports/ - 172 per-champion reports, program DONE 2026-06-16;
    archive reports/ only, KEEP PROGRAM/REPORT/SYSTEMIC_FINDINGS/TIER2_REPORT.
15. docs/CI_WATCHDOG_PLAN.md - scoping doc; the watchdog is implemented + ARMED (KEEP
    tools/ci_watchdog_fix.md - the live prompt). Out-of-scope flag: the tracked
    "docs io RC peer/" directory is fully dead post the bridge decommission - strong
    whole-directory candidate if the operator widens scope.

---

## Live-flip ledger (loop appends; newest first)

- 2026-07-02 R58 `assume_ms_utility` shipped default-OFF (ENGINE 1.167.0, commit `304c88dd`):
  MS-utility DPS credit for the bruiser/juggernaut scorer (`compute_hybrid` +
  `rank_items_by_hybrid`, hybrid.py only; 1 pct bonus MS ~= 0.5 pct effective DPS, cap 0.15).
  Byte-identical OFF (omitted-vs-False full-dict equality pinned). Flip gated as B41
  (PRACTICE-SR own-build re-rank eyeball). Stack-ramp MS registry (Shipwrecker +20 flat /
  Steadfast +6 pct) is a follow-up seam feed, not yet resolved into stats["ms"].
- 2026-07-01 (SYNC) full-repo gated-item resync: header + play order + sections rebuilt from a
  9-doc read (WAKEUP / ORCHESTRATION_PLAN / LEDGER / ROADMAP / BACKLOG /
  OVERLAY_BUILD_MASTER_PLAN / ARCHITECTURE / OPERATIONS / RC_WORK_TRACKER) + repo sweep +
  git-closure audit + a seam-flag ground-truth probe (every DS seam confirmed default-OFF at
  its live call site; RC_COMP_HP_LEAN / RC_LANING_CV_SERVED cold). Items removed as done: the
  E.1 in-game overlay capture row (item 598), the PM7 Arena-boots DONE wrapper (real commit
  `54d0706a`; the augment-phase visual residual kept as D3), the vision self-heal / item-276
  self-grab live validation (proven by live self_grab frames, LEDGER 685/688/711), and
  operator packaging (reclassified release-gated, headless list). Items added: ~78 tagged rows
  - the R5-R55 / DSP5-DSP8 / RF / F2 seam obligations promoted out of this ledger into section
  rows, the champ-select + overlay pixel-capture families, RC2 P3.3/P4.x eyeballs,
  physical-press rows, the post-game/Match-V5 set, and 16 accrual rails. DSV5's tripled flip
  obligation consolidated to ONE operator decision (headless list). The undefined LGS1
  "OPEN1/OPEN2" reference resolved as a stale label with no target. Count now open: 108 rows =
  86 one-shot active + 14 active accrual rails + 8 PARKED/HOLD; 16 items reclassified headless.
  Drain plan: 4 sessions (practice SR -> real SR -> ARAM Mayhem -> Arena). ARENA NEEDED: YES
  (D1-D7).

- 2026-07-01 (R53, LOOP) caster_hp gate seam for Last Stand 8299 - ENGINE 1.163.0 -> 1.164.0, DEFAULT-OFF,
  live default-ON flip EXCLUDED. `keystone_amp(..., gate_caster_hp=False)` +
  `compute_burst_damage(..., gate_caster_hp_amp=False, caster_current_hp_pct=1.0)`. Last Stand's amp scales
  with the CASTER's health (DDragon 16.13.1 longDesc verbatim: "Deal 5% - 11% increased damage to champions
  while you are below 60% health. Max damage gained at 30% health."; the item-232 `_last_stand_amp` ramp -
  1.0 at/above 0.60 caster HP -> 1.11 at/below 0.30 - is unchanged and already correct for 16.13.1). The
  burst scorer feeds Last Stand `caster_hp_pct` (live default 1.0 -> full HP -> NO amp), so Last Stand
  contributes NOTHING to the default burst total. R53 adds the seam: `gate_caster_hp_amp=True` routes Last
  Stand's amp to read `caster_current_hp_pct` instead, so a per-instant scenario eval credits the honest
  low-HP amp while Absolute Focus 8233 (gates on HIGH caster HP) keeps reading `caster_hp_pct` (the two
  caster-hp gates do not conflict). At the DEFAULT `gate_caster_hp_amp=False` Last Stand reads `caster_hp_pct`
  exactly as pre-R53 -> BYTE-IDENTICAL (no live consumer passes the flag; /rank / ds-preview / burst
  unchanged). `keystone_amp`'s `gate_caster_hp` is byte-identical parity plumbing (the 8299 ramp is
  single-sourced on `caster_hp_pct`). OWED (operator/Gemini-gated, NOT headless - charter 4b
  do-not-flip-blind): wire a per-instant scenario / fight_report consumer to pass `gate_caster_hp_amp=True`
  with the caster's real current-HP fraction (or a per-timestep HP band), then confirm the gated burst reads
  sane vs a real game. Gating a whole burst on a single caster-HP snapshot is a scenario/stepped-eval use,
  NOT a blind flip of the burst scorer. No DS math change on flip (seam already live); DS `:8893` needs no
  restart for the flip itself. Does NOT block any further stage.

- 2026-07-01 (R51, LOOP) target_hp gate seam for Cut Down 8017 / Coup de Grace 8014 - ENGINE 1.162.0 ->
  1.163.0, DEFAULT-OFF, live default-ON flip EXCLUDED. `keystone_amp(..., gate_target_hp=False)` +
  `compute_burst_damage(..., gate_target_hp_amp=False)`. Pre-R51 the burst-MAX scorer applied both Precision
  slot-4 amps (Cut Down >60% target HP, Coup de Grace <40% target HP) UNCONDITIONALLY - the burst-window
  approximation, since a burst spans the target HP range. R51 makes the gate HONESTLY expressible: with
  `gate_target_hp=True`, `keystone_amp` amps Cut Down only when `target_hp_pct` is strictly ABOVE 0.60 and Coup
  de Grace only when strictly BELOW 0.40 (verbatim DDragon 16.13.1 longDesc: "more than 60% health" / "less
  than 40% health"; magnitude 1.08 unchanged). At the DEFAULT `gate_target_hp=False` the gate block is skipped
  entirely -> BYTE-IDENTICAL to the pre-R51 unconditional approximation (no live consumer passes the flag, so
  /rank / ds-preview / burst are unchanged). OWED (operator/Gemini-gated, NOT headless - charter 4b
  do-not-flip-blind): wire a per-instant scenario / fight_report consumer to pass `gate_target_hp_amp=True` with
  a real `target_hp_pct` snapshot (or a per-timestep HP band) so the two runes credit only when the target is
  actually in-band, then confirm the gated burst reads sane vs a real game. Gating a whole burst on a single HP
  snapshot is LESS accurate than the unconditional window approximation for a full burst, so the honest use is
  a per-instant / stepped eval, NOT a blind flip of the burst scorer. No DS math change on flip (seam already
  live); DS `:8893` needs no restart for the flip itself. Does NOT block any further stage.

- 2026-07-01 (R50, LOOP) K'Sante P "All Out Bonus" bilinear caster-resist seam - ENGINE 1.161.0 -> 1.162.0,
  DEFAULT-OFF, live default-ON flip EXCLUDED. New registry `_ALL_OUT_BONUS_OVERRIDES` + new
  `AbilitiesSnapshot.load(apply_all_out_bonus=...)` flag inject a SECOND K'Sante-P synthetic damage block modeling
  the R-empowered All Out Bonus (verbatim 16.13.1: "1% (+ 1% per 100 bonus armor) (+ 1% per 100 bonus magic
  resistance) of the target's maximum health") as a linear 1% max-HP plus two `_per_100` bilinear terms
  (`caster_bonus_armor` x `target_max_hp` + the `caster_bonus_mr` sibling), gated by `conditional_probability` 0.5
  (documented amortized All-Out-uptime firing midpoint, operator-tunable). Default OFF is byte-identical (no live
  consumer passes the flag; the base item-255 mark-consume entry is untouched). OWED (operator/Gemini-gated, NOT
  headless - charter 4b do-not-flip-blind): (1) wire a live rank / dps / burst consumer to pass
  `apply_all_out_bonus=True` (ideally only while K'Sante's R "All Out" is active) and confirm his in-All-Out
  empowered-mark value reads sane vs a real game; (2) tune `conditional_probability` 0.5 against real All-Out uptime
  (or feed a live All-Out-state gate so the full in-form value is credited only during R). A WRONG precompute is
  worse than none, so do NOT default-ON until validated in an actual All Out fight. DS `:8893` restart on flip.
  Does NOT block any further stage.

- 2026-07-01 RuneWriter silent-after-League-restart PERMANENT FIX (`lcu/lcu_client.py`, frozen-grant).
  Operator live-flagged rune push dead on the last champ-select. Root cause: the long-lived RC (up since
  6-29) held a STALE lockfile port after League restarted (the lockfile rotates port+password each launch);
  `LcuClient` read the lockfile only once at connect() and never re-read, so get_champ_select() returned None
  forever and RuneWriter (shares the one _lcu) went silent - NOT the 2026-06-17 re-arm theory (that path was
  already fixed; the 6-29 log shows a clean Caitlyn write + re-arm). Immediate remediation: RC restart re-read
  the lockfile (fresh port 50237). PERMANENT: ported the RC-LCUAgent `ensure_lcu_conn()` resilience into
  `LcuClient` - mtime-guarded `_refresh_conn_if_changed()` on the 1 Hz auto-accept tick (heals every consumer
  sharing the instance) + reactive reconnect-and-retry-once in `_request` on a dead-port connection error.
  TDD: 6 new tests (`tests/test_lcu_client_lockfile_reconnect.py`) - rotate / no-op / gone + dead-port retry +
  no-infinite-retry + tick-calls-refresh; the 114 prior LCU/RuneWriter/spell/loadout tests stay green. Tier-1
  (LCU client logic; no ENGINE bump / Share sync / DS restart). Activation needs an RC restart to load the
  edited frozen module - DEFERRED past the operator's live ARAM (do not bounce RC mid-game).

- 2026-06-23 (item 598, R25) IN-GAME OVERLAY CAPTURE - E.1 cleared (validation + 1 durable test,
  NO live flip). Live SR game (champ Syndra AP mage vs a Braum/Gragas tank+CC comp); the rc-shell
  Electron overlay (PID 9736, title "RC . Syndra") ran over League. Playwright on the LIVE
  `https://legion-rc:8888/?overlay=1` (not a fixture, not 127.0.0.1 - the legion-rc origin so wss://
  is real), read off the REAL coach state: `body[data-shell]="overlay"`; `#right-now` `s0Cue="choices"`
  `s0Tier="urgent"` `s0Pulse="0"` (a SUSTAINED one-shot-urgent CHOICES cue did NOT arm a pulse ->
  producer-side motion rationing verified live, no over-fire); the CALL action row
  `data-call-band="fight"`, border-left-color rgb(200,170,110) gold 3px, verb color rgb(236,242,255)
  white, glyph U+25BA (item 591 band channel, live-faithful); eye-line widgets rn-lead / rn-choices
  (showed "A / Trade now / Braum lvl 18 / Alt+1") / rn-callouts (WARD UP green pill) / am-ward-cue /
  am-mmrect present+positioned, am-spike-cue + am-pane-ovds fight-model correctly hidden in the coach
  panelset, primary CALL font-size 22px. Only console error: favicon.ico 404 (benign). A Legion desktop
  screenshot caught the REAL Electron overlay compositing transparently over the live Rift (CALL
  "SETUP DRAKE FIGHT" gold bar + WARD UP + minimap-rect box float over the game with no opaque backing).
  DURABLE: new `tests/snapshot_panels/test_overlay_view.py::test_overlay_s0_pulse_rations_sustained_choices_via_producer`
  pins the DOM-PRODUCER s0-pulse path (the node PulseDecisionChainTests never import right_now.js; the
  manual-stamp consumer tests set the attribute by hand - neither exercised the live producer render).
  Screenshot is local-only (`tests/snapshot_panels/screenshots/` gitignored), NOT committed. STILL OWED:
  the ACTIVE knob-interaction (Alt+Shift+A re-rank) round-trip - the capture validated render+compositing,
  not a live knob press.

- 2026-06-23 RC_COMP_HP_LEAN (DSV5) LIVE EYEBALL DONE (R24; validation only, NO code change).
  The OWED AP-mage-vs-2+-tank eyeball (ledger 592) cleared on a real live SR game: me=Seraphine
  vs enemy Braum / Master Yi / Cho'Gath / Ziggs / Gragas. `compute_enemy_stats` classified
  `tanky_count=3` (Braum + Cho'Gath = tank, Master Yi = bruiser) -> `hp_scale` **1.20x**, applied
  `target_max_hp` 2980 -> 3576 (+596) at L18. RANKER OFF-vs-ON (`dispatch_for_coach`, top-6):
  (a) Seraphine routes to the **HPS / enchanter** scorer, so the seam is a NO-OP for her
  (enchanters do not build %max-HP DoT) - the LIVE coach champ was unaffected; (b) pure mages
  (Veigar / Heimerdinger, the ability-DPS scorer) - the seam boosts ONLY the genuine %max-HP DoT
  item **Liandry's Torment** (+6.5 dps L18 / +5.4 dps L11, ~+17%, proportional to the 1.20x
  max-HP) and leaves flat-magic items (Void Staff / Rabadon's / Shadowflame / Mejai's / Blackfire)
  byte-identical. VERDICT: **SANER NOT DIFFERENT confirmed** - the seam can only nudge Liandry's
  UP, never reorder toward a worse pick, so do-not-flip-blind (charter 4b) is SATISFIED. CAVEAT:
  the visible top-6 IMPACT is narrow - Liandry's is already rank-1 in the mage build at these
  levels, so the 1.20x widens an existing lead WITHOUT reordering the top-6; the seam only changes
  a served ranking in the borderline case where Liandry's is NOT already top, AND only for
  mage-scorer champs (enchanters / non-AP unaffected). RECOMMENDATION: flip is validated-SAFE, ON
  recommended - but NOT auto-flipped this session because the supervisor-env route is a FROZEN-file
  edit (`ops/rc_supervisor.py`) and defaulting a global coaching heuristic ON is a deliberate
  operator call. Method: probed the live `/api/state` comp + ran `compute_enemy_stats` /
  `dispatch_for_coach` OFF (`comp_hp_lean=False`) vs ON (`=True`) headlessly - no live-process
  disruption, no env change.

- 2026-06-22 DSV5 no-comp-info guard (ledger 593, `coach_integration/enemy_stats.py`) - a
  PREREQUISITE-to-flip SAFETY FIX, not a new seam. Verify-the-premise against the live SR comp
  (Jinx vs Lucian/Sion/Wukong/Pantheon/Soraka, tanky_count 3) exposed that `_comp_hp_scale`
  applied a blind **0.90** max_hp discount whenever `RC_COMP_HP_LEAN` was ON with NO
  `enemy_champions` (`1 + 0.10*(0 - 1)`), conflating "no comp data" with "all-squishy comp" and
  contradicting its own docstring. The champ-select / preview routes (`routes_state` ds-preview
  Path 3, `routes_ds_knobs`, `routes_ds_relscore`, `routes_ds_statcheck`) ALL call
  `compute_enemy_stats(mode, level)` with no comp, so a global default-ON flip would have silently
  de-rated every preview ranking by 10%. FIX: `_comp_hp_scale` now short-circuits to `(1.0, 0)`
  when there is no classifiable comp (None / `[]` / all-blank), so no-info is byte-identical to the
  flat curve when ON; a REAL all-squishy comp (>=1 classifiable champ, 0 tanky) still earns the
  intended 0.90 discount, and a tank comp still earns the uplift. This RESOLVES the preview-route
  safety blocker on the RC_COMP_HP_LEAN default-ON flip below. Tier-1 (NO ENGINE bump / Share sync /
  DS :8893 restart - coach-integration heuristic). RED-first +4 tests (the bug-shaped
  `test_no_comp_info_on_is_neutral` assertion corrected to 1.0 to match its own name + the docstring,
  plus blank-comp, no-info-vs-known-squishy contrast, and an env-ON-no-comp byte-identical guard);
  43/43 enemy-stats tests green. The default-ON FLIP itself stays operator-gated (gemini ruling:
  hold for a separate operator-run) - see the DSV5 entry below.

- 2026-06-22 DSV5 comp-conditioned enemy max-HP seam (ledger 592, `coach_integration/enemy_stats.py`).
  DEFAULT-OFF env gate **`RC_COMP_HP_LEAN`** (set `=1` in the RC runtime env; the read is per-call so no
  restart is needed - it is a coach-integration heuristic, NOT a DS `:8893` engine flip, so do NOT restart
  DS for it). When ON, a tank-heavy enemy comp scales `target_max_hp` up (1 + 0.10*(tanky_count - 1),
  clamped [0.85, 1.30]) so DSV1's ability-burn / %max-HP valuation tilts the live item ranking toward DoT
  (Liandry's/Blackfire/Demonic) vs tanks, matching the rewind WIN-anchored signal (winning AP carries vs
  2+ tanks build DoT over burst +12.0pt; burst usage halves). OFF == byte-identical flat curve.
  LIVE EYEBALL DONE 2026-06-23 (R24 - see ledger top; do NOT flip blind, charter 4b): in a real SR/ARAM game on an AP mage facing a 2+
  tank/bruiser comp, set `RC_COMP_HP_LEAN=1` and confirm the build-chooser top-6 re-rank elevates the
  %max-HP DoT items (Liandry's especially) vs the OFF ranking, and that it stays "saner not different"
  for a squishy comp (scale 0.90 should NOT swing picks materially). Inspect the applied modifier via the
  `core.coach_trace.record_enemy_target` plumb (`kind:enemy_target` records: base vs applied max_hp +
  hp_scale + tanky_count). Only after the eyeball checks out, authorize the default-ON flip (drop the gate
  or default `RC_COMP_HP_LEAN=1` in the supervisor env). NO ENGINE_VERSION bump / Share sync (engine
  untouched - the seam only changes the TARGET fed to the already-shipped DSV1 scorer).

- 2026-06-20 RC2 rc-shell standalone-app live session (code fixes shipped `cac1df3a` + `81f74d88`;
  runtime recovery). LIVE-VERIFY OWED (needs a live ARAM/any lobby): `lcu.lobby.members[]` must render
  in the rc-shell PRE-GAME LOBBY panel (YOUR MAINS / PARTY / MY TOP-8). The agent DOES forward members[]
  (`tools/lcu_agent.py:706-717`) but the operator saw empty members during a live lobby; could NOT
  reproduce after they left it (LCU phase=None). Next lobby: confirm the panels populate; if empty,
  capture the agent's live `/lol-lobby/v2/lobby` read + `_slim_lobby_member` output to find why members
  drop (suspect event-mode 2400 member shape OR the post-RC-restart stale-agent window). ALSO eyeball
  the overlay surface gate (`cac1df3a`): companion dashboard shows in the lobby/champ-select and flips to
  the lean HUD only once `liveclient` populates (a real game starts). Separately tracked (NOT live-gated,
  headless next session): agent restart-resilience - RC-LCUAgent/Hotkey/Relay must survive boot + auto-
  resync after an RC restart (the systemic root cause of the whole session's cascade). NOT a DS seam.

- 2026-06-20 RC2 E-batch E12-L2 + E7a (RC-side, NOT DS seams; shipped code-safe, no flip flag).
  E7a (`64591d5f`) tightens the RC-LCUAgent bench-swap queue-drain (fast 0.1s re-poll on a
  latency-sensitive cmd vs the 0.5s idle wait). LIVE EYEBALL OWED: in a real ARAM champ-select,
  click a bench champ and confirm the swap registers visibly faster - cannot be exercised offline
  (needs a live LCU champ-select with a populated bench). The RC-LCUAgent runs as an ONLOGON task
  with no restart_trigger, so a code refresh needs `taskkill /F` the agent pid + `Start-ScheduledTask
  RC-LCUAgent`. E12-L2 (`48fcee51`) memoizes RuneWriter's lobby gameMode per champ-select session.
  LIVE EYEBALL OWED: confirm RuneWriter still pushes the correct mode-appropriate runes/spells on
  champ-select enter (cache is per-session, cleared on `_reset_spell_state`) and a mode change across
  back-to-back champ-selects re-detects. Neither blocks any further stage.

- 2026-06-20 RC2 P5.2 CV served integration (COACHING, NOT a DS seam; shipped code-safe
  DEFAULT-OFF). 5.1 built the CV override + shadow column; 5.2 builds the SERVED-FLIP
  MECHANISM: `core.laning_cv_overrides.apply_cv_to_choices` maps a fired override onto the
  served A/B chips (`cv_choice_pair`: enemy DEAD -> "Shove + take plates/prio" high;
  MISSING >=3s -> "Back off + ward" mid; my HP <0.35 vs an aggressive verdict -> "Disengage"
  high; source_tag `cv-laning`; a trailing build `C` choice is preserved). Wired through
  `core.laning_verdicts.laning_choices(apply_cv=, hp_fraction=, vision_state=)` (default
  apply_cv=False -> byte-identical) and gated in `dashboard/_deterministic_coaching._compute_uncached`
  behind `_cv_served_enabled()` (env `RC_LANING_CV_SERVED`, DEFAULT-OFF). `_build_game_state`
  now stamps `gs["hp_fraction"]` (lc-first; additive, only the gated path reads it). OFF is
  byte-identical (the `laning_choices(gs, mode=upper)` call is unchanged). THE SERVED FLIP =
  `RC_LANING_CV_SERVED=1` in the RC runtime env (no restart for the env read on next RC
  start; the producer runs in-process). OWED (operator/Gemini-gated, NOT headless): (a) accrue
  real laning games so `data/hz_choice_shadow.jsonl` `cv_override` rows fill (5.1's shadow);
  (b) re-run `tools/hz_shadow_report.py` and read det-vs-Haiku agreement WITH the CV layer;
  (c) when agreement climbs toward the >=70% target (`HZ_HAIKU_CALL_INVENTORY.md:75`), set
  `RC_LANING_CV_SERVED=1` to flip the served chips. KNOWN at flip time: the served `_CACHE`
  sig (`_cache_sig`) is intentionally UNCHANGED (off-path byte-identical), so a flipped-ON CV
  transition (enemy dies / my HP drops mid-bucket) can serve a stale chip for up to the 3.0s
  TTL + 5s game-time bucket - acceptable for a gated/eyeballed flip; tighten the sig (coarse
  low-HP bool + a cheap fog-freshness key) in the same flip slice if the live eyeball shows lag.
  Does NOT block any further stage.

- 2026-06-19 R7 per-stack self-AS passive (ENGINE 1.147.0): the per-stack champion self-Attack-Speed
  passive seam shipped DEFAULT-OFF on the AA DPS scorer. NEW `agents/daemon_slayer/_passive_as_overrides.py`
  registry (`PassiveAsEntry` per champion_id: per-stack bonus-AS FRACTION low/high by level + max_stacks +
  ap_per_stack_per_100) + `assume_passive_as_stacks` on `agents/daemon_slayer/dps.py compute_dps`; when ON,
  `passive_as_bonus(cid, level, ap, stack_fraction=_ASSUMED_PASSIVE_AS_STACK_FRACTION=1.0)` folds the
  champ's innate per-stack bonus AS at full stacks into the rotation AS (same 2.5 hard-cap re-clamp as the
  Yun Tal conditional-AS path; raw_attack_dps left at the no-conditional baseline). Seeded 4 from
  champion_abilities.json 16.12.1 effects_descriptions: Irelia Ionian Fervor (10%:25% by level/stack, max 4),
  Jax Relentless Assault (5%:12.5% by level/stack, max 8), Ezreal Rising Spell Force (10% flat/stack, max 5),
  Volibear The Relentless Storm ((5% + 4% per 100 AP)/stack, max 5 - the one AP-scaled passive, reads the
  resolved post-amp AP). A champion with no registered passive is byte-identical even with the flag on. No
  live scorer passes the flag yet (default False -> byte-identical). LIVE FLIP = wire the DPS / hybrid
  scorer-dispatch (`agents/daemon_slayer/server.py` the `compute_dps` call sites + `rank.py rank_items` /
  `core/daemon_slayer_client` wrappers - the same dispatch the B1 melee gate flips) to pass
  `assume_passive_as_stacks=True` for the 4 tabled champs (extend `core/archetype_picks` or the scorer call
  to thread the flag). Validate in a real game that Irelia/Jax/Ezreal/Volibear show a sanely higher
  auto-attack DPS / item ranking that favors AS-synergy items at full stacks, and a non-tabled champ
  (Caitlyn) + any operator pick are byte-identical. The assumed stack count
  (`_ASSUMED_PASSIVE_AS_STACK_FRACTION`) is operator-tunable; dial it below 1.0 if full-stack steady state
  over-credits a poke kit (Ezreal). Re-anchor the registry from the live patch's `champion_abilities.json`
  effects_descriptions each patch (re-scan for new per-stack self-AS passive lines). Needs a DS `:8893`
  restart on flip. Do NOT flip blind (charter 4b; CLAUDE-Settled "per-stack assumed_stacks").
- 2026-06-19 R5 missing-HP heal-amp (ENGINE 1.146.0): the missing-HP heal-AMPLIFICATION seam shipped
  DEFAULT-OFF on the ability-HPS scorer. NEW `assume_missing_hp_heal_amp` on
  `agents/daemon_slayer/ability_hps.py compute_ability_hps`; when ON, a `(champ, spell)` in
  `_MISSING_HP_HEAL_AMP` has its `heal_per_cast` multiplied by `1 + max_bonus * caster_missing_hp_pct`
  (Master Yi W Meditate / Lissandra R Frozen Tomb / Sylas W Kingslayer = 1.0; Briar P Crimson Curse =
  0.40). No live scorer passes the flag yet (default False -> byte-identical; full-HP / 0-missing also
  byte-identical). LIVE FLIP = wire the HPS/enchanter scorer-dispatch
  (`agents/daemon_slayer/server.py _route_rank_enchanter` -> `rank_items_by_hps`, and/or any coach
  surface calling `compute_ability_hps`) to pass `assume_missing_hp_heal_amp=True` AND feed the live
  caster's missing-HP fraction as `caster_missing_hp_pct`. Validate in a real game that a low-HP
  Sylas/Master Yi/Lissandra/Briar shows a sanely higher ability-heal throughput and a full-HP cast +
  any non-tabled champ are byte-identical. Re-anchor `_MISSING_HP_HEAL_AMP` from the live patch's
  `champion_abilities.json` effects_descriptions each patch (re-scan for new 0%:X%-based-on-missing-
  health heal lines). Needs a DS `:8893` restart on flip. Do NOT flip blind (charter 4b).
- 2026-06-18 PM7 Arena boots mirror (ENGINE 1.144.0): NOT a default-OFF seam - a DATA-correctness
  fix shipped LIVE (item 499). `core.build_order._select_boots` remaps Arena/CHERRY tier-2 boots to
  their `22`-prefixed map30-legal mirror; all 3 Arena build tables regenerated (boots-only). No flip
  pending (already live); the only live-OWED piece is the section-D visual confirm at an Arena augment
  phase. ALSO logged here: an operator ARAM Yasuo this run produced the first live RF1-tabled-bruiser
  eyeball - RF1 ON (hybrid `prefer_survivability_by_win`) floats Wit's End + Jak'Sho into Yasuo's top-6
  and drops Runaan's + Stormrazor = SANER, clearing the LGS2-open "RF1 needs a tabled champ to roll"
  gap. The RF1 default-ON flip itself stays operator-gated (section B; not flipped mid-game). NEW `cost_ceiling` param
  on the shared `_filter_candidates`, threaded through `rank_items`/`rank_items_by_ehp`/
  `rank_items_by_hybrid`; drops any candidate whose `gold.total` STRICTLY exceeds the ceiling. Live
  flip = pass `cost_ceiling=<N>` (e.g. 4000) at the build-chooser /rank-bruiser + /rank-tank call
  sites (section B), excluding the 6000g ARAM/Arena mega-item Void Immolation 223069 the
  `sort_by="delta"` absolute-gain surface floats to rank-1. Byte-identical OFF (reproduced live:
  Garen bruiser ARAM rank-1 = 223069). Validate the re-ranked ARAM/Arena bruiser+tank top-6 vs a
  real game before flipping (do-not-flip-blind).
- 2026-06-18 B1 (ENGINE 1.141.0): melee-applicability gate shipped DEFAULT-OFF (item 496, PM4). Live
  flip = `apply_melee_aa_gate=True` on the dps/hybrid scorer call sites (section B), zeroing a
  `PeriodicProc.ranged_only` proc (Runaan's Hurricane bolts) on a melee auto (attackrange <
  `MELEE_RANGE_CEILING`=350). Validate the re-rank vs a real melee ARAM game (Briar/XinZhao/Nilah)
  before flipping.
- 2026-06-17 LGS2 LIVE PLAY (no ENGINE bump - validation session, zero code change): operator ran
  6 ARAM Mayhem champ-selects (Olaf, Sivir, Senna->Mundo, Lissandra, Vex->Quinn, Caitlyn) under a
  persistent champ-select catcher (poll lcu.phase, emit on ChampSelect-enter; ARAM CS is too fast
  for a from-ReadyCheck poll) + per-champ `live_flip_eyeball.py` OFF-vs-ON re-rank.
  RESULTS:
  * DSP11 kit-axis = LIVE-VALIDATED both sub-cases + negative control -> FLIP-READY pending operator
    decision + DS :8893 restart. Senna (lethality) ON surfaces +Black Cleaver; Quinn (crit) ON
    surfaces +Infinity Edge(top)/The Collector/Statikk Shiv/Lord Dominik's; Caitlyn (the documented
    non-tabled control) shows ZERO DSP11 movement (byte-identical). Seam correctly scoped.
  * Comp-verdict (section C) renders correctly on SWAP (Senna->Lux HIGH, Lissandra->Hecarim MEDIUM,
    Vex->Garen MEDIUM) AND STAY (Caitlyn STAY LOW). VARIANT branch still unobserved. Bench-swap UI +
    build-chooser (3 variants + runes) + MAYHEM flag all render live; build reasons are comp-aware.
  * DSP3 / RF1 / RF2 / RF3+RF6 = no-op on every champ played (none tabled for those seams) ->
    byte-identical half re-confirmed; the TABLED half for RF1/RF2/RF3+RF6/DSP3 + the DSP11-manamune
    sub-case still needs a tabled champ to roll (RF1 bruiser / Rakan / KSante|Rell / Cluster-A /
    Ezreal|Corki).
  * DSP8/DSV3/DSV4 move saner per champ (theoretical - burst path, not the live ranker for most picks).
  OPEN FINDINGS:
  * SECTION A LCU PUSH = FAIL. RuneWriter (`lcu/lcu_rune_writer.py`) wrote runes ONLY on the first
    champ-select of the RC session (game1 Yuumi->Olaf 21:56); SILENT on every later champ-select
    despite RC detecting them (cs_pick updated). No crash/traceback -> champ-select re-detection does
    not re-arm after the first "champ select ended" (L451). Item-set + summoner-spell push share the
    CS-enter path = same suspect. Fix is post-session (needs RC restart), NOT frozen. See memory
    reference_runewriter_dies_after_game1.
  * Comp-verdict SOUNDNESS flag (low-confidence): Vex(AP)->Garen(AD) cited "all-AD comp - mix damage
    type", which reads inverted (swapping the only AP to AD removes the mix). Verify the ally-comp
    logic in `core/aram_comp_verdict.py`.
  CS2 spell push inconclusive (summoner_override=False every game; client default was already
  Flash+Mark, nothing to force). CC-pair UI not observed (no CC-pairing scenario rolled). HZ Lane-A/B
  accrued ~6 ARAM games to rewind_history.db (still HOLD - need corpus + rail clear).

- 2026-06-17 DSP5/6/7 CONSUMERS (ENGINE 1.140.0): the three DSP substrate seams now have a
  consumer layer - NEW `agents/daemon_slayer/dsp_live_consumers.py` (`summoner_fight_adjustments`
  / `enemy_rune_threat` / `ally_protected_ehp`). Previously a flag-flip did nothing (no scorer read
  the registries); now the seams are LIVE-TESTABLE - the remaining gated work is PLUMBING the real
  live-client summoner/rune/ally set INTO the consumer + eyeballing the adjusted readout (NOT
  building a consumer). Each is byte-identical on an EMPTY context. DSP7's `ally_protected_ehp` ALSO
  covers the item-321 ehp ally-resist producer (Orianna E / Braum W / Taric W via `ally_resist_grant`
  -> `external_resist_armor/mr`). +10 tests; DS 7334 / RC 8333 green; Share 364; DS :8893 restarted
  -> 1.140.0. NOT flipped (do-not-flip-blind).

- 2026-06-17 RF6 (ENGINE 1.139.0): tank-template survivability INJECT seam shipped DEFAULT-OFF -
  extends the RF3 ehp/tank float (no NEW scorer flag; the SAME `prefer_survivability_by_win` on
  `ehp.rank_items_by_ehp`). RF4 found RF3's float is a no-op for Rell: its sole tabled winner
  Fimbulwinter 3121 is the non-purchasable mana-line transform of Winter's Approach
  (`gold.purchasable`=False), so `_filter_candidates` drops it (RF4 `in_pool=False`) and the float has
  nothing to lift. NEW `inject_ids` force-admit param on `rank._filter_candidates` (bypasses the
  `only_ids` whitelist + `exclude_names` deny + `_is_purchasable` gate; still honors current /
  non-coachable / mode-legality / terminal / budget; `None` default = byte-identical for every caller);
  `rank_items_by_ehp` passes `inject_ids=surv_ids` only when the seam is ON. The LIVE flip is the SAME
  one tracked in section B above (wire `server.py` `rank_items_by_ehp` ~L557 / `rank_tank_for` to pass
  `prefer_survivability_by_win=True`) - flipping it now ALSO surfaces Rell's Fimbulwinter, not just
  KSante's already-pooled winners. NOT flipped (do-not-flip-blind); needs a real ARAM + a DS `:8893`
  restart. KNOWN SIBLING (FUTURE): RF2's hps `only_ids |= surv_ids` union likewise cannot surface
  Rakan's tabled 3121 (same purchasable gate) - the `inject_ids` mechanism now exists to fix it if a
  future RF wires the hps lane through it; not done here (RF2 is a DONE seam).
- 2026-06-17 RF2 (ENGINE 1.137.0): enchanter-template survivability item-credit seam shipped
  DEFAULT-OFF. NEW `prefer_survivability_by_win` on `hps.rank_items_by_hps` (the hps/enchanter scorer
  lane), driven by the WIN-anchored `agents/daemon_slayer/survivability_item_credit_enchanter.json`
  (1 champ / 4 items - Rakan: Guardian's Horn / Warmog's Armor / Heartsteel / Fimbulwinter). The flip
  wires `agents/daemon_slayer/server.py _route_rank_enchanter` (+/- the
  `core/daemon_slayer_client.rank_enchanter_for` wrapper) to pass `prefer_survivability_by_win=True`.
  KEY difference from RF1: the enchanter scorer's `enchanter_only` pool EXCLUDES HP/tank items entirely
  (zero HPS throughput) so the seam INJECTS the tabled ids into the pool BEFORE floating them (RF1's
  hybrid lane already pools them and only floats). NOT flipped (do-not-flip-blind) - validate the
  re-rank in a real ARAM (Rakan-as-tank-support surfaces Warmog's/Heartsteel; non-tabled Soraka/Janna
  byte-identical). Cluster A (Zilean/Seraphine AP-in-ARAM) NOT tabled. Re-anchor the table each patch
  via `ops/audit/ds_perm_swarm/build_survivability_item_credit_enchanter.py`. Needs a DS `:8893`
  restart on flip.
- 2026-06-17 RF1 (ENGINE 1.136.0): generic-bruiser-template survivability item-credit seam shipped
  DEFAULT-OFF. NEW `prefer_survivability_by_win` on `hybrid.rank_items_by_hybrid` (the hybrid/bruiser
  scorer lane), driven by the WIN-anchored `agents/daemon_slayer/survivability_item_credit.json` (9 bruiser
  champs / 28 items). The flip wires `agents/daemon_slayer/server.py _route_hybrid` (+/- the
  `core/daemon_slayer_client.hybrid_for` wrapper) to pass `prefer_survivability_by_win=True` so the buried
  survivability winners float above the generic AD-DPS template (section B row above). NOT flipped
  (do-not-flip-blind) - validate the re-rank in a real ARAM. Distinct from the DSP11 DPS/burst kit-axis
  flip (which gates on `delta_dps>0`); survivability items add EHP not DPS so RF1 floats by WIN-table
  membership. Re-anchor the table each patch via `ops/audit/ds_perm_swarm/build_survivability_item_credit.py`.
  Needs a DS `:8893` restart on flip.
- 2026-06-17 LGS1 (no ENGINE bump - pure docs audit): live-sync list audited authoritative. (1) CORRECTED
  the DSV seam-flip row's location - `assume_takedown`/`assume_squishy_target`/`assume_ability_amp` flip the
  BURST scorer `agents/daemon_slayer/burst.py rank_items_by_burst` (+ `compute_burst_damage`), NOT `rank.py`
  (verified by grep: `rank.py rank_items` carries ONLY the DSP2 `exempt_offclass_by_win` + DSP11
  `prefer_kit_axis_by_win` seams; the DSV/DSP8 seams live in `burst.py`, DSP4 `score_completion_runes` in
  `burst.py`+`combo.py`). (2) ADDED a section-B row for the EXCLUDED anti-tank P3.2 live caster-stat producer
  (`antitank.py effective_magnitude` ap/ad_ratio scaling) + the `ehp.py compute_ehp(external_resist_*)`
  Orianna-E/Braum-W/Taric-W ally-resist survivability producer (egg-resist already default-ON item 321) -
  previously the only EXCLUDED live item with no checklist row. Every other rank.py/burst.py/combo.py
  default-OFF seam (DSP2/DSP4/DSP8/DSP11) + the ROADMAP Phase-D flips + champ-select Haiku flip already had
  an accurately-located row. No new seam shipped; no new OPEN work discovered (OPEN1/OPEN2 still pending).
- 2026-06-17 HZU1 (no ENGINE bump - tooling + docs; the item-level CODE shipped item 457 @a30cbba4):
  the HZ Lane-B build-order Haiku-flip gate already mines item-level signal, but its VERDICT is HOLD.
  Fresh re-run @651 SR matches (`--limit 0`) independently REPRODUCED item 457 byte-for-byte: lean-level
  followed-vs-not +2.3pp (766 vs 1066 rows, 95%=[-2.3,+6.9], flip_ready=False); completion-timing also a
  coin flip (fast<=20.82min 56.1% vs slow 56.7%); and 1/51 per-item carriers over the 4627
  lean-ambiguous rows = Infinity Edge anti_squishy +12.6pp (95%=[+0.7,+24.4]), with Serylda's Grudge
  +11.3pp just missing (lo=-0.9). NO live flip is shipped - the build coach AND the laning coach both
  HOLD Haiku until the gate clears its flip rail on a larger corpus and is eyeballed live. The live-gated
  rows for both the Lane-A laning read and the Lane-B build flip are recorded in section C above; re-run
  the gate as `data/rewind_history.db` grows. Artifact: `ops/runtime/build_order_validation.json`.
- 2026-06-17 DSP11 (ENGINE 1.135.0): Cluster-B2 kit-axis item-credit seam shipped DEFAULT-OFF.
  NEW `prefer_kit_axis_by_win` on `rank_items` (dps) + `rank_items_by_burst` (burst), driven by
  the WIN-anchored `kit_axis_item_credit.json` table (7 champs / 21 terminal items, built by
  `ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py` from the DSP10 buried-winner report +
  rewind). When ON: (1) un-strips the champ's kit-axis items from the ranged-marksman off-class
  deny set (Ezreal's hard-excluded Trinity Force becomes a candidate), and (2) floats every
  positive-delta kit-axis item above the generic AD template (model order preserved within tiers).
  NO live scorer passes the flag (default False -> byte-identical). FLIP = wire the dps + burst
  scorer-dispatch to pass `prefer_kit_axis_by_win=True` (section B above). Validate the re-rank vs a
  real Pyke/Nilah/Ezreal ARAM before flipping (do-not-flip-blind). Cluster A (Zilean/Shaco/Kayle/
  Seraphine AP-in-ARAM) is a SEPARATE operator-gated archetype-routing decision, NOT in this table.
- 2026-06-17 DSP9 (no ENGINE bump - offline AUDIT tooling): NO new seam, so NO new
  flip row. The G7 comp-aware parity harness (`ops/audit/lolmath_ds_sweep/g7_comp_harness.py`)
  found that feeding DS the comp-matched build variant does NOT improve parity vs
  lolmath-ULTIMATE (burst_heavy 1.49 < mixed 1.84 < poke 1.86 < frontline_heavy 2.00
  mean item-overlap); lolmath-ULTIMATE is the cost-ignoring raw-stat pile, so the
  residual is the G6 cost-model axis, not comp-awareness. IMPLICATION for the live
  pass: the existing DSP8 `target_preset` flip (section B) is still worth validating
  for assassin-vs-comp correctness, but do NOT expect it to move lolmath-ULTIMATE
  parity - that gap is G6 (deferred FUTURE/BACKLOG per the Gemini-consult, do NOT
  blind-build a gold cost model). No new live-gated work added by DSP9.
- 2026-06-17 DSP7 (ENGINE 1.133.0): ally aura/enchanter seam shipped DEFAULT-OFF. NEW separate
  registry `_ALLY_FLAT_HP_GRANT_OVERRIDES` (in `_passive_ally_grant_overrides.py`) models the flat
  EHP an enchanter's shield/heal CONFERS on a protected ally - the THIRD ally-grant EHP mode
  (after resist + revive) and the SHIELD/HEAL bucket item-289 excluded. 7 enchanter grants
  (Janna/Lulu/Karma/Yuumi E + Seraphine W shields, Soraka/Nami W heals), base values from
  `champion_abilities.json` 16.12.1. Generic consumer seam `compute_ehp(external_flat_hp=)` (default
  0.0 -> byte-identical); no live scorer passes it. Live flip = wire a peel/EHP consumer reading the
  live ally team's granter set (section B above). Re-anchor base + add the granter AP ratio at flip.
  Validate the protected-ally EHP uplift vs a real game before wiring.
- 2026-06-17 DSP6 (ENGINE 1.132.0): enemy-rune threat seam shipped DEFAULT-OFF. NEW
  `agents/daemon_slayer/enemy_runes.py` (the enemy-side mirror of `summoners.py`) models 4 enemy
  runes on the preset each threatens - Press the Attack 8005 (incoming_amp 0.08 on the player),
  Conqueror 8010 (damage_ramp 21.6-48.0 max-stack Adaptive Force + 8%/5% lifesteal), Grasp 8437 +
  Second Wind 8444 (poke_sustain) - plus the non-rune antiheal constant (`GRIEVOUS_WOUNDS_PCT`
  0.40 + `enemy_antiheal_pct`). No live scorer consumes it (`ENEMY_RUNE_SEAM_IDS` marks the ids),
  so /rank is byte-identical. Live flip = wire an EHP / target-preset consumer that reads the
  enemy's live rune set (section B above). Magnitudes are DDragon-16.12.1-cited and re-anchor at
  flip. Validate the re-ranked anti-tank / sustain build vs a real game before wiring.
- 2026-06-17 DSP5 (ENGINE 1.131.0): summoner-spell seam shipped DEFAULT-OFF. NEW
  `agents/daemon_slayer/summoners.py` registry models 6 combat summoner spells (Ignite/Exhaust/Heal/
  Barrier/Cleanse/Ghost) on their scoring axis; no live scorer consumes it (`SUMMONER_SEAM_IDS` marks
  the ids), so /rank is byte-identical. Live flip = wire a fight_report/matchup/coach consumer that
  reads `summoners.py` against the live summoner set (section B above). Magnitudes are LoL-wiki-cited
  (DDragon/CDragon zero them) and re-anchor to the live patch at flip. Validate the adjusted
  survivability/antiheal/CC readout vs a real game before wiring.
- 2026-06-17 DSP4 (ENGINE 1.130.0): self-rune completion seam shipped DEFAULT-OFF. Added Shield Bash
  8401 (Resolve) - the one unmodeled LIVE pickable direct-damage rune proc - to RUNE_PROCS behind
  `COMPLETION_RUNE_IDS`. Live flip = `score_completion_runes=True` on the burst/combo scorer call site
  (section B above). Adds the 5-30 + 2.5% bonus-HP shield-proc floor to a shielded carrier's burst.
  Validate vs a real Shield-Bash game (Leona/Braum/Shen) before flipping.
- 2026-06-17 DSP3 (no ENGINE bump - RC-side resolver, no engine math): ARAM archetype-override seam
  shipped DEFAULT-OFF. Live flip = `core.archetype_picks.get_archetype_for(champion,
  prefer_aram_win_axis=True)` at the ARAM archetype-dispatch site (section C above). Re-bases the
  kit-default archetype to the rewind-WIN archetype for 6 Cluster-A champs; operator picks untouched.
  Validate the re-ranked scorer vs a real Kayle/KogMaw/Zilean/Shaco/Shyvana/Taric ARAM game first.
- 2026-06-17 DSP2 (ENGINE 1.129.0): off-class WIN-exemption seam shipped DEFAULT-OFF. Live flip =
  `rank_items(exempt_offclass_by_win=True)` at the carry/dps scorer call site (the caster-marksman
  re-include; section B above). Validate the re-rank vs a real Ezreal/Corki game before flipping.
- 2026-06-17 seeded from ROADMAP open-tail consolidation. DSP* seam flips append here as they ship.
- 2026-06-20 RC2 P3.3 overlay pulse-rationing flip (UI behavior, NOT a DS seam; `87f41baf` shipped
  the SHADOW). Shadow: `right_now.js` stamps `data-s0-cue` / `data-s0-tier` / `data-s0-pulse` on
  `#right-now` each render via `overlay_priority.signalFromState` -> `selectPrimary` -> `shouldPulse`,
  with ZERO live pulse change. SHIPPED LIVE (operator-approved 2026-06-22, verify-next-game): the
  `.action` per-band pulse (`right_now.js`, the `if (isFreshAction && _s0Pulse)` site near line 540,
  was line 533; the shadow block hoists `_s0Pulse = shouldPulse(...)` near line 496) AND
  `overlay_pulse.js` (MutationObserver, now early-returns via `_s0PulseArmed()` reading
  `#right-now[data-s0-pulse="1"]`) now CONSUME the stamped decision - so motion fires ONLY for the
  Emergency tier (incl. the lethal cue carrying the `lethal_incoming` passthrough) + a one-shot Urgent
  cross (spike/choices) (spec section 5 / acceptance A5). The flip is conservative-only by construction
  (`isFreshAction && _s0Pulse` is a strict subset of the old `isFreshAction` per-band path; the overlay
  gate only adds an early-return) - it can never add a pulse that did not fire pre-flip, only suppress
  benign 'good' / sustained-same-cue re-emits. Regression coverage: `tests/test_overlay_pulse_flip_rc2.py`
  (decision chain a-d + conservative-subset proof + consumer wiring). REMAINING EYEBALL (verify-next-game,
  NOT headless): on a real game confirm the suppressed pulses were all benign re-emits and the Emergency /
  one-shot Urgent cross still glows. The arbitration single-winner (A2) + 44px choice hit-target already
  ship live.
- 2026-06-20 RC2 P4.1 DPI/resolution overlay sizing live eyeball (UI geometry, NOT a DS seam; `4d5d54f0`
  shipped the code). The shell now sizes the overlay window by the work-area scale (resolveOverlayMetrics)
  and zooms the dock content to match (overlay.css `--rc-overlay-scale`). Headless-verified via the
  real-Chromium `test_overlay_view` fixture audit at 2560x1440 (dock zooms to ~598px right-anchored,
  screenshot `overlay_sr_1440_scaled.png`) + baseline-1920 no-op. OWED (operator-gated, NOT headless):
  eyeball the overlay COMPOSITED OVER A REAL LEAGUE GAME at 2560x1440 borderless - confirm the zoomed
  dock reads cleanly over a bright game scene, does not clip the bottom panes against the work area, and
  the right-edge dock lands where expected over the HUD (stage 4.6, live-game visual validation). The
  rc-shell Electron MAIN process needs a relaunch first to pick up the new window-size logic (the web
  renderer half auto-reloads via ADR-008 asset-hash). Does NOT block any further stage.
- 2026-06-20 RC2 P4.2 non-intrusive overlay live eyeball (UI behavior + geometry, NOT a DS seam; this
  cycle shipped the code DEFAULT-ON safe). Three additive overlay behaviors: (1) operator opacity slider
  -> rc-shell `overlayWindow.setOpacity` (the HUD recedes into the game), (2) click-through ZONES
  (`overlay_state.effectiveIgnoreMouse` + `clickthrough_zones.js` hover detector over the preload bridge)
  so PASSIVE captures clicks ONLY over an interactive control (#ovset / #rn-choices / #am-pane-ovds /
  drag strip) without the global ACTIVE hotkey, (3) auto-hide idle recede (`web/js/lib/overlay_idle.js`
  stamps `data-rc-idle` after ~8s of no coach change + no pointer activity; `overlay.css` dims the dock
  to 0.35 opacity; snaps back on the next change / hover). Headless-verified: rc-shell node suite 220/220
  + `test_overlay_idle_rc2` 16 + `test_overlay_settings_panel_dom` (extended) + real-Chromium
  `test_overlay_view` 36, live `:8888` serves the assets. OWED (operator-gated, NOT headless): eyeball
  COMPOSITED OVER A REAL LEAGUE GAME at 2560x1440 borderless - confirm (a) the opacity recede reads
  cleanly and the idle dim is not distracting / wakes correctly on a real coach update, (b) hover-to-
  interact flips the cursor capture crisply over #ovset / choices without eating game clicks elsewhere,
  (c) the drag strip is grabbable on hover. The rc-shell Electron MAIN process needs a relaunch first to
  pick up the new shell logic (preload setZoneHover + main.js opacity/zones); the web renderer half (idle
  recede + the #ovset controls) auto-reloads via ADR-008 asset-hash. Does NOT block any further stage.
- 2026-06-20 RC2 P4.3 single-monitor separated-window arrangement (window-management geometry, NOT a DS
  seam; this cycle shipped the code DEFAULT-ON safe). When the in-game overlay shows alongside the kept
  dashboard (E1/3.4 keepCompanion) on a SINGLE monitor, the shell now arranges them as SEPARATED side-by-
  side windows: an overlapping companion is repositioned (never resized - the size preset survives) to the
  work-area edge on whichever side of the overlay has more free room, top-aligned, so the dashboard sits
  BESIDE the HUD instead of under it. `overlay_state.resolveSeparatedCompanionBounds` is the pure decision
  (respects a companion already clear of the overlay -> moved:false); `main.js applySingleMonitorLayout`
  gates on `screen.getAllDisplays().length === 1` (multi-monitor untouched) + the new `separateWindows`
  setting (no-hotkey #ovset kill switch, default ON). Headless-verified: rc-shell node suite 232/232 (+15
  overlay_state geometry/setting), `test_overlay_settings_rc2` + `test_overlay_settings_panel_dom`
  (extended), real-Chromium `test_overlay_view` 44 (the #ovset Separate-windows toggle renders, defaults
  checked, ASCII label, clears the 42px hit floor), live `:8888` serves the assets. OWED (operator-gated,
  NOT headless): eyeball it OVER A REAL LEAGUE GAME at 2560x1440 borderless - start a game with the
  dashboard parked centered/over-the-right-dock and confirm (a) the dashboard auto-jumps to the free left
  side fully clear of the overlay, (b) it keeps its size (no preset corruption), (c) toggling "Separate
  windows" off in #ovset leaves an overlapping dashboard where the operator put it. The rc-shell Electron
  MAIN process needs a relaunch first to pick up the new main.js logic + the separateWindows authority;
  the web renderer half (the #ovset toggle) auto-reloads via ADR-008 asset-hash. Does NOT block any
  further stage.
- 2026-06-20 RC2 P4.4 settings-UI no-hotkey overlay actions (UI control surface, NOT a DS seam; this
  cycle shipped the code safe - additive #ovset controls, no render-path flip). The overlay's last
  keyboard-only behaviors are now on-screen #ovset controls over a new one-way `overlay-action` IPC: a
  Coach/Build/Threat panel-set segmented selector (the twin of Alt+Shift+C; lights the active segment from
  the body panelset, a pick fires `set-panel` and the shell persists + reloads the overlay onto that set)
  and an "Interact now" button (twin of Alt+Shift+A; fires `set-active`, forces ACTIVE with the same 20s
  auto-revert). `overlay_state.normOverlayAction` is the pure allow-list the main process trusts;
  `main.js applyPanelSet`/`setOverlayActive` are shared by the hotkeys AND the IPC so the two paths never
  drift. Hide/show (Alt+Shift+O) STAYS a hotkey by design (it clears BOTH surfaces, so a self-hiding on-
  screen control would have no way back). Headless-verified: rc-shell node 240/240 (+5 normOverlayAction,
  +3 action-IPC wiring), `test_overlay_settings_panel_dom` 33 (+8), real-Chromium `test_overlay_view` 19
  (+2: the selector + button render at the 42px floor with ASCII labels; panelset=build lights exactly the
  Build segment), live `:8888` serves the controls. OWED (operator-gated, NOT headless): eyeball it OVER A
  REAL LEAGUE GAME at 2560x1440 borderless - confirm (a) clicking Coach/Build/Threat in #ovset swaps the
  overlay panel set (no Alt+Shift+C), (b) the lit segment matches the shown set, (c) "Interact now" makes
  the HUD interactive then auto-reverts after ~20s. The rc-shell Electron MAIN process needs a relaunch
  first to pick up the new IPC handler + applyPanelSet/setOverlayActive; the web renderer half (the #ovset
  selector + button) auto-reloads via ADR-008 asset-hash. Does NOT block any further stage.
- 2026-06-20 RC2 P4.5 overlay + dashboard coexistence (UI control surface, NOT a DS seam; shipped
  code-safe - two additive #ovset action buttons over the existing 4.4 IPC, no render-path flip). Two
  payload-free coexistence commands on the `rc-shell:overlay-action` channel: `rearrange` (re-separate
  the overlay + kept dashboard NOW, forcing past the separateWindows auto kill switch) + `raise-companion`
  (showInactive-if-hidden + moveTop the kept dashboard, then a forced re-arrange). overlay_state
  OVERLAY_ACTIONS grew to 4 members (still frozen); main.js applySingleMonitorLayout({force}) bypasses the
  auto gate; raiseCompanion() reposition-only (no resize). #ovset .ovset-actpair = Re-arrange + Show
  dashboard. Headless-verified: rc-shell node 245/245, test_overlay_settings_panel_dom 37 (+4),
  real-Chromium test_overlay_view 20 (+1: both buttons at the 42px floor, ASCII labels, one row); 0 banned
  glyphs; live `:8888` serves the controls + CSS HTTP 200. OWED (operator-gated, NOT headless): eyeball it
  OVER A REAL LEAGUE GAME at 2560x1440 borderless - with the dashboard kept beside the HUD, confirm (a)
  dragging the dashboard under the overlay then clicking Re-arrange re-separates them side-by-side, (b)
  Show dashboard brings a buried/behind dashboard forward beside the HUD without resizing it, (c) neither
  button ever hides the overlay (no stranding). The rc-shell Electron MAIN process needs a relaunch first
  to pick up the new IPC dispatch + raiseCompanion/force-layout; the web renderer half (the #ovset buttons)
  auto-reloads via ADR-008 asset-hash. P4.6 (live-game visual validation, flipped LIVE) IS this whole-of-
  Phase-4 eyeball - this entry plus the P4.1-4.4 entries above are its checklist. Does NOT block any stage.
- 2026-06-20 RC2 P5.1 local-CV laning overrides (COACHING, NOT a DS seam; shipped code-safe SHADOW-ONLY -
  the served `choices` are NOT altered). The CV override (`core/laning_cv_overrides.py`: enemy DEAD ->
  shove, MISSING >=3s -> back off, my HP <0.35 vs an aggressive verdict -> disengage) currently rides ONLY
  the `data/hz_choice_shadow.jsonl` `cv_override` column. The SERVED FLIP (let the CV override drive the
  live A/B chips in `dashboard/_deterministic_coaching._compute_uncached`) is stage 5.2 and is GATED on the
  agreement re-measurement, NEVER a blind overnight flip. OWED (operator/Gemini-gated, NOT headless):
  (a) accrue real laning games so the new `cv_override` column fills (the live producer runs in-process on
  next RC restart - confirm rows appear with kind enemy_dead / enemy_missing / low_hp at the right moments);
  (b) re-run `tools/hz_shadow_report.py` and read det-vs-Haiku agreement WITH the CV layer applied; (c) when
  agreement climbs toward the >=70% target (`HZ_HAIKU_CALL_INVENTORY.md:75`), authorize the 5.2 served flip.
  Does NOT block any further stage.
- 2026-06-20 RC2 P6.4 port-safety pooled LCU connection (`RC_LCU_POOL` default-ON flip). The L6 keep-alive
  connection pool (`core/lcu_pool.py`) ships DEFAULT-OFF; the live path is byte-identical until `RC_LCU_POOL=1`.
  OWED (operator-gated, NOT headless): over a REAL champ-select + match, set `RC_LCU_POOL=1` and confirm
  (a) champ-select reads (`game_reader/poller._lcu_get`) still return correct sessions with the pool active,
  (b) no `UNEXPECTED_EOF_WHILE_READING` / SSL EOF on the reused socket (if it appears, check
  `netsh interface portproxy show all` FIRST per `reference_iphlpsvc_portproxy_2999` - that is a self-loop
  rule, not a pool bug), (c) the reconnect-on-drop path self-heals across a client restart mid-session, and
  (d) loopback socket count stays bounded (one long-lived socket per LCU port instead of one-per-call) under
  a tightened poll cadence. Only after (a)-(d) check out over a live game, authorize the default-ON flip.
  UPDATE 2026-06-30 (E7): the frozen `lcu/lcu_client.py._request` is NOW wired onto the same pool (commit
  `453b9ddd`, operator frozen-grant, still DEFAULT-OFF), so the every-tick auto-accept path
  (`LcuClient._auto_accept_tick`, ~2 LCU GETs/s) pools too once flipped - extend check (a) to also confirm
  auto-accept + rune-apply read correctly with the pool active. After (a)-(d) pass, the flip is a one-liner
  (`core/lcu_pool.py:40` default or `RC_LCU_POOL=1` in the runtime env). Does NOT block any further stage.
  Bench-swap state-render responsiveness (E7 TODO-1, commit `fe34040c`) shipped independently, NOT gated.
  **VALIDATED + FLIPPED 2026-07-01 (`c699b915`):** all four checks passed over a real live game - (a) auto-accept +
  poller reads correct with the pool active (game started clean), (b) 0 SSL EOF on the reused socket (log + a raw
  60-GET keep-alive control), (c) a forced-drop reconnect recovered HTTP 200, (d) main RC held exactly ONE persistent
  loopback socket to the LCU port past 169s (bounded, no per-call churn). Flipped `core/lcu_pool.py:40` default 0->1 +
  the tests to the default-ON contract. E7 default-ON flip is DONE - do NOT re-open this gate.
- 2026-06-21 R9 DS flat damage-reduction EHP seam (`assume_passive_flat_mitigation`, default-OFF). The NEW
  per-instance flat-DR registry (`agents/daemon_slayer/_passive_flat_mitigation_overrides.py`: Fizz P / Amumu E /
  Leona W) ships DEFAULT-OFF on `compute_ehp` + `rank_items_by_ehp` - the EHP math is byte-identical until
  `assume_passive_flat_mitigation=True`. OWED (operator/Gemini-gated, NOT headless - charter 4b "do not flip
  blind"): (a) over a real/replayed game, flip the seam on in the live survivability scorer path and confirm the
  flat-DR champions' (Amumu / Leona / Fizz) EHP-ranking shifts read sane vs eyeball + rewind-WIN data; (b) validate
  the two operator-tunable midpoints against live per-instance data - `_ASSUMED_FLAT_DR_INSTANCES`=6 (the
  representative count of mitigated instances over a fight - the live per-instance damage feed we lack) and
  `_ASSUMED_ABILITY_RANK`=4 (the per-rank Amumu/Leona flat-block read level). A WRONG precompute is worse than no
  credit, so do NOT default-ON until the midpoints are tuned to a live fight clock. Does NOT block any further
  stage.
- 2026-06-21 R12 all-source target-vulnerability mark seam (`apply_target_vuln`, ENGINE 1.149.0, default-OFF).
  The NEW cross-source vulnerability registry (`agents/daemon_slayer/_target_vulnerability_overrides.py`:
  Vladimir R Hemoplague 10% all-source + Evenshroud 3001 / Arena 223001 Coruscation 7%) ships DEFAULT-OFF on
  `agents/daemon_slayer/dps.py compute_dps` - the AA-DPS math is byte-identical until `apply_target_vuln=True`,
  when the wielder's whole DPS is multiplied by the product of every mark she owns (champion ability x each
  registered item, multiplicative). OWED (operator/Gemini-gated, NOT headless - charter 4b "do not flip blind"):
  (a) wire the scorer-dispatch (`agents/daemon_slayer/server.py` compute_dps call sites + `rank.py` / coach
  surfaces) to pass `apply_target_vuln=True` for a marked wielder (Vladimir, or any build holding Evenshroud),
  AND broaden the consumer beyond AA DPS to ability_dps + burst (the all-source mark amplifies those too - this
  seam wires the AA-DPS scorer first); (b) validate in a real game that a marked-target scenario shows a sanely
  higher effective DPS / item ranking, and an unmarked wielder stays byte-identical. The seam models the
  fully-marked target at full magnitude (the assume_takedown / assume_ability_amp developed-fight doctrine);
  uptime gating (Vlad R cooldown, Evenshroud's 5s post-immobilize window) is a live-consumer concern not baked
  here. Imperial Mandate (4005) is EXCLUDED as a non-fit (current-HP detonation, not an all-source %amp). A
  WRONG precompute is worse than no credit, so do NOT default-ON until validated. DS `:8893` restart on flip.
  Does NOT block any further stage.
- 2026-06-30 R43 Imperial Mandate target-vulnerability mark SEEDED (ENGINE 1.158.0, default-OFF) - SUPERSEDES
  the R12 bullet's "Imperial Mandate (4005) is EXCLUDED" note above. DDragon 16.13.1 `item.json` reworked
  Imperial Mandate to "Command: On Immobilizing an enemy champion, mark them as 7% Vulnerable for 4 seconds" -
  a +7% all-source mark - so 4005 / Arena 224005 / ARAM 324005 are now seeded at 0.07 in
  `_target_vulnerability_overrides._ITEM_VULN_OVERRIDES` (R41's handoff, executed; the stale Meraki Coordinated
  Fire mirror is overridden by the official Riot rework). This rides the EXISTING R12 `apply_target_vuln` seam
  and carries NO new flag: a build holding Imperial Mandate is amplified x1.07 only when that flag flips ON, so
  it is folded into the R12 flip already OWED above (wire the scorer-dispatch / rank / coach surfaces to pass
  `apply_target_vuln=True` for a marked wielder). OWED (operator/Gemini-gated, NOT headless): when the R12 seam
  is validated in a real game, also confirm an Imperial Mandate build's marked-target effective DPS / item
  ranking reads sanely higher, and an unmarked wielder stays byte-identical. A WRONG precompute is worse than no
  credit, so do NOT default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
- 2026-06-22 R14 cc_conditional durations_floor_s CC-floor seam (`apply_cc_floor`, ENGINE 1.150.0, default-OFF).
  The NEW guaranteed-minimum floor band on distance / channel-scaled conditional CC
  (`agents/daemon_slayer/cc_conditional.py` ConditionalCcEntry.durations_floor_s: Maokai R 0.75 / Hecarim R 0.75 /
  Ashe R 1.0 / KSante W 0.5 / Sion R 0.25) ships DEFAULT-OFF on `agents/daemon_slayer/cc_pressure.py`
  compute_cc_pressure - the CC-pressure math is byte-identical until `apply_cc_floor=True`, when a floor-tagged
  entry is credited floor + probability * (max - floor) instead of max * probability (in BOTH the standalone and
  the coexistence MAX-rule paths). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind):
  (a) wire the seam ON through the live consumer chain - compute_cc_pressure is consulted by compute_ehp /
  compute_hybrid (via include_conditional) and the cc-blended-EHP threat surface, none of which thread
  apply_cc_floor yet; thread it (default-OFF preserved) and confirm the floor-tagged champions' CC-pressure /
  blended-EHP-threat read sane vs eyeball; (b) validate the floor model (floor + prob*(max-floor)) reads better
  than the prior max*prob for a close-range Maokai/Ashe/Hecarim R or a short-channel KSante/Sion vs a real game -
  e.g. Ashe R OFF credits 3.5*0.4=1.4s (< unconditional 1.5s, the flat baseline wins) but ON credits
  1.0+0.4*(3.5-1.0)=2.0s (the floor-aware credit wins the coexistence MAX). A WRONG precompute is worse than no
  credit, so do NOT default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
- 2026-06-22 R17 anti-tank level-ramp %max-HP seam (`compute_antitank(level=)`, ENGINE 1.151.0, default-OFF).
  A real subset of antitank %max-HP rows scale their percentage with the CASTER's champion level
  (`agents/daemon_slayer/antitank.py` AntiTankEntry.ramp_lo/ramp_hi: Aatrox P 4:8, Brand P 8:12, KSante P 1:2,
  Mordekaiser P 1:5, Ornn P 10:18, Renata P 1:2, Skarner P 5:9, Urgot P 2:6, Zed P 6:10, Zeri P 1:11). The
  hand-tuned magnitude encodes the max-ramp (late-game) reliability; compute_antitank stays byte-identical until a
  `level` is injected, when a ramp-seeded row's effective magnitude scales by lerp(ramp_lo, ramp_hi,(level-1)/17)/
  ramp_hi (level=18 and level=None both byte-identical; un-ramped rows byte-identical at any level). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a survivability / draft consumer to
  call compute_antitank with the live champion level (the /anti-tank route still passes no level, byte-identical),
  and confirm the early-vs-late level-discounted anti-tank scores read sane vs a real game (e.g. a level-3 Aatrox
  ranks below a level-16 Aatrox on the same tank). A WRONG ramp is worse than the flat magnitude, so do NOT
  default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
- 2026-06-30 R39 anti-tank current-HP level-ramp %current-HP seam (`compute_antitank(level=)`, ENGINE 1.155.0,
  default-OFF). The CURRENT_HP sibling of R17: a real subset of antitank %current-HP rows scale their percentage
  with the CASTER's champion level (`agents/daemon_slayer/antitank.py`
  AntiTankEntry.current_hp_ramp_lo/current_hp_ramp_hi: Senna P 1:10 - Absolution "1% : 10% (based on level) of
  target's current health"). The hand-tuned magnitude encodes the max-ramp (late-game) reliability;
  compute_antitank stays byte-identical until a `level` is injected, when a current-HP-ramp-seeded row's effective
  magnitude scales by lerp(lo, hi,(level-1)/17)/hi via the shared _current_hp_level_ramp_factor (level=18 and
  level=None both byte-identical; rows with no current-HP ramp byte-identical at any level - the same additive
  contract R17 holds, and the two ramp kinds never compound since a row carries at most one pair). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a survivability / draft consumer to
  call compute_antitank with the live champion level (the /anti-tank route still passes no level, byte-identical),
  and confirm the early-vs-late level-discounted Senna anti-tank score reads sane vs a real game (a level-3 Senna
  ranks below a level-16 Senna on the same target). A WRONG ramp is worse than the flat magnitude, so do NOT
  default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
- 2026-06-27 R30 / DSV6 on-cast magic-burst seam (`compute_burst_damage(assume_magic_burst=)`, ENGINE 1.152.0,
  default-OFF). Item on-cast magic procs the per-cast burst combo loop never credited
  (`agents/daemon_slayer/_effects_data.py` magic_burst_base/magic_burst_ap_ratio: Luden's Echo 6655 75+5%AP,
  Stormsurge Squall 4646 125+10%AP, Malignance Hatefog 3118 180+15%AP one ult-zone). compute_burst_damage stays
  byte-identical until `assume_magic_burst=True`, when sum(base + ap_ratio*ap) is credited MR-mitigated (MAGIC
  routing) x mode_mult x magic_amp into total_burst (after the rune + execute layers). compute_ability_dps takes
  the same kwarg but is DELIBERATELY INERT (a one-shot magnitude has no place in a per-second metric; compute_dps
  already values these at their PeriodicProc rate, so folding them in the ability-DPS scorer would be wrong-units
  AND a partial double-count). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a
  burst-scoring / rank consumer (burst.rank_items_by_burst, /rank-assassin, the offense-burst surface) to call
  compute_burst_damage with assume_magic_burst=True, and confirm an AP/magic burst build (Veigar/Syndra/Annie with
  Luden's or Stormsurge) ranks its on-cast magic item ABOVE where the seam-OFF engine placed it, vs a real game.
  A WRONG burst credit is worse than no credit, so do NOT default-ON until validated. DS `:8893` restart on flip.
  Does NOT block any further stage.
- 2026-06-27 R35 survivability percent-DR LIVE consumer (`mitigation_multipliers(snapshot=)` /
  `compute_ehp(apply_passive_mitigation=)`, ENGINE 1.153.0, default-OFF). The R19 forward-marker accessor
  `DataSnapshot.spell_damage_reduction_pct(champ, slot)` (per-rank PERCENT damage reduction from
  champion_abilities.json defensive modifier blocks) now has a consumer: when `apply_passive_mitigation=True` AND a
  snapshot is passed, each (champ, slot) percent-DR block folds into the EHP DENOMINATOR (mit_phys / mit_mag /
  mit_true) read at `_ASSUMED_ABILITY_RANK`=4, amortized by `_ACTIVE_DR_PROB`=0.3, axis by substring (8 snapshot
  champs: Alistar R / Belveth E / Braum E / Galio W split phys+mag / Garen W / Gragas W / MasterYi W / Warwick E).
  compute_ehp stays byte-identical until `apply_passive_mitigation=True` is flipped (the default-False path
  short-circuits to (1,1,1) before the snapshot is consulted; no live scorer/rank call passes the flag today). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a survivability / EHP-rank consumer
  (rank_items_by_ehp, compute_hybrid_mitigation, the tank/bruiser survivability surface) to call with
  `apply_passive_mitigation=True` + the live snapshot, and confirm a percent-DR champ (Galio / Garen / MasterYi
  mid-fight) ranks its EHP / defensive items ABOVE where the seam-OFF engine placed it, vs a real game - and that the
  rank-4 + 0.3-uptime assumption reads sane (a Galio with W up survives the magic burst the OFF engine under-credited).
  A WRONG DR credit is worse than none, so do NOT default-ON until validated. DS `:8893` restart on flip. Does NOT
  block any further stage.
- 2026-06-30 R41 ally mark-detonation seam (`compute_dps(assume_ally_detonation=)` /
  `compute_burst_damage(assume_ally_detonation=)`, ENGINE 1.156.0, default-OFF). A champion whose MARK an ALLY
  consumes for bonus damage (the new PURE registry `agents/daemon_slayer/_ally_detonation_overrides.py`; seeded
  Leona P Sunlight FLAT_MAGIC 32:151 based-on-level, 2.5s mark cadence, verified vs champion_abilities.json
  16.13.1) is credited the amortized TEAM damage her mark enables: per-event magic for burst, per-event/cadence for
  the DPS rate, each MR-mitigated (MAGIC routing) x mode_mult x magic_amp x `_ASSUMED_ALLY_DETONATION_PROB`=0.5.
  Both compute_* stay byte-identical until the flag is True; an unmarked champion contributes 0 even with the flag
  on (the AA-probe call inside compute_burst_damage leaves the seam OFF, so the detonation is credited once in the
  burst total - no double-count). Imperial Mandate 4005 (the directive's named "10% current-HP" detonation) is a
  documented NON-FIT: DDragon 16.13.1 shows it REWORKED to a 7% Vulnerable all-source amp (Control / Command
  passives); the 16.12.1 Coordinated Fire detonation is gone (only the stale Meraki items mirror, content_patch
  None, still carries it), so seeding it would be a WRONG precompute - it now belongs in
  _target_vulnerability_overrides, not this detonation seam. OWED (operator/Gemini-gated, NOT headless - charter 4b
  do-not-flip-blind): wire a DPS / burst / rank consumer (compute_dps / compute_burst_damage / a rank surface) to
  call with `assume_ally_detonation=True` and confirm Leona's mark-enabling team value ranks ABOVE the seam-OFF
  placement vs a real game, and that the 2.5s Sunlight cadence + 0.5 proc-rate assumptions read sane. A WRONG
  detonation credit is worse than none, so do NOT default-ON until validated. DS `:8893` restart on flip. Does NOT
  block any further stage.
- 2026-06-30 R45 Poppy W low-HP doubled percent-of-resist tier (`resist_grants(caster_current_hp_pct=)` /
  `compute_ehp(caster_current_hp_pct=)` / `compute_hybrid(caster_current_hp_pct=)`, ENGINE 1.159.0, default-OFF).
  Poppy W "Stubborn to a Fault" already credited +12% of TOTAL armor + MR; R45 adds the Meraki-16.13.1 "doubled to
  24% while below 40% maximum health" tier as an INCREMENTAL percent applied when the caster's current-HP fraction
  drops below `low_hp_threshold` (Poppy 0.40), i.e. +12% more (24% total) at low HP. DEFAULT-OFF byte-identical on
  two axes: the seam rides the EXISTING `apply_passive_resist` flag AND the new `caster_current_hp_pct` defaults to
  1.0 (full HP) so the low-HP branch is dormant (1.0 not < 0.40) -> identical to 1.158.0. OWED (operator/Gemini-gated,
  NOT headless - charter 4b do-not-flip-blind): wire a live EHP / survivability consumer to pass Poppy's real
  current-HP fraction (the scorer today never reads caster HP) and confirm her sub-40%-HP EHP ranking reads sane vs a
  real game. A WRONG precompute is worse than none, so do NOT default-ON until validated. DS `:8893` restart on flip.
  Does NOT block any further stage.
- 2026-06-30 R46 stacking permanent max-HP passive registry (`compute_ehp(assume_passive_health_stacks=)`, ENGINE
  1.160.0, default-OFF). A NEW survivability axis + the SECOND EHP-NUMERATOR term: champion passives that grant
  PERMANENT bonus max health PER STACK (the new PURE registry `agents/daemon_slayer/_passive_health_overrides.py`;
  seeded Sion W Soul Furnace +4/kill, Cho'Gath R Feast +80/120/160 per stack by rank, Swain P Ravenous Flock +15 per
  Soul Fragment, all verified vs champion_abilities.json 16.13.1). When the flag is True the per-champ bonus max-HP is
  added RAW to every per-type EHP numerator (physical/magical/true), riding the same armor/MR curve. The per-stack HP
  is EXACT Meraki; the assumed STACK COUNT by level is an operator-tunable CONSERVATIVE midpoint (the live stack feed
  we lack). DEFAULT-OFF byte-identical (flag False -> 0.0; no live consumer passes it). OWED (operator/Gemini-gated,
  NOT headless - charter 4b do-not-flip-blind): (1) wire a live EHP / survivability consumer to pass
  `assume_passive_health_stacks=True` for Sion/Cho'Gath/Swain and confirm their stacked EHP ranks ABOVE the seam-OFF
  placement vs a real game; (2) ideally replace the conservative assumed-stack curve with the LIVE stack count (the
  in-game buff/stack reading from the Live Client buff list, if/when that surfaces) so the credit tracks the real
  game state, not a midpoint. A WRONG precompute is worse than none, so do NOT default-ON until validated. DS `:8893`
  restart on flip. Does NOT block any further stage.
- 2026-06-30 R49 on-being-hit reflect damage seam (`compute_dps(assume_passive_reflect=)` /
  `compute_burst_damage(assume_passive_reflect=)`, ENGINE 1.161.0, default-OFF). Rammus W Defensive Ball Curl reflects
  magic damage to basic attackers - a REACTIVE (incoming-triggered) TOTAL-resist form the empowered-AA
  `_passive_damage` seam could not carry. The new registry `agents/daemon_slayer/_passive_reflect_overrides.py`
  (seeded 1 vs verbatim 16.13.1 Meraki: Rammus W "15 (+ 10% total armor) (+ 10% total magic resistance) magic")
  computes the per-incoming-attack magnitude on the caster's resolved TOTAL armor/MR (full-MR via the new
  `caster_mr` scaling target). When the flag is True the reflect is MR-mitigated by the duel target's effective MR
  and amortized into DPS by the assumed incoming attack rate (1 / `reflect_cadence_s`, default 1.0s), or into burst
  over the `_ASSUMED_REFLECT_BURST_WINDOW_S` exposure window. The % terms scale on the build's resolved resists which
  do NOT include W's own active self-buff resists (the `_passive_resist` EHP seam) - a documented LOWER BOUND.
  DEFAULT-OFF byte-identical (both flags False -> the registry is never read; unregistered champ contributes 0 even
  ON). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): (1) wire a live DPS / burst / rank
  consumer to pass `assume_passive_reflect=True` for Rammus and confirm his W-tank reflect value ranks ABOVE the
  seam-OFF placement vs a real game, and that the `reflect_cadence_s` 1.0s incoming-attack + 3.0s burst-window
  assumptions read sane; (2) ideally feed the W-ACTIVE buffed total armor/MR (so the % terms match League's
  recalculate-over-duration) instead of the resting build resists. A WRONG precompute is worse than none, so do NOT
  default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
- 2026-07-01 R55 archetype-aware DEFAULT for the `target_current_hp_pct` seam
  (`rank_for_primary_archetype(assume_archetype_hp_pct=)`, ENGINE 1.165.0, default-OFF). The seam (item 374) scales
  ONLY the three genuine %-current-HP procs (BotRK 3153 / Hellfire 4017 / Fulmination 443055). R55 plumbs it into the
  CARRY (`rank_items`) + BRUISER (`rank_items_by_hybrid`) scorers -> `compute_dps` (it previously reached only
  mage/assassin) and adds a caller-side resolver `core.ds_archetype_hp_pct.archetype_target_current_hp_pct` mapping an
  archetype to a conservative DEFAULT current-HP fraction (SUSTAINED/juggernaut -> 0.5, target ground down over the
  fight; BURST + non-damage/unknown -> 1.0). DEFAULT-OFF byte-identical (flag False -> carry/bruiser get no override,
  mage/assassin get the caller's value; no live consumer passes the flag). STEP-1 lolmath baseline validation was
  IMPOSSIBLE - lolmath.com is parked (302 -> ww1.lolmath.com, connection refused), so the 0.5 is a conservative DESIGN
  midpoint, NOT a measured constant. OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): (1)
  wire a live carry/bruiser rank consumer to pass `assume_archetype_hp_pct=True` and eyeball across ~3 real games that
  the archetype-resolved current-HP ranks read sane vs the flat-1.0 placement (especially that a bruiser/marksman
  building BotRK does not over/under-rank it); (2) CALIBRATE the exact sustained fraction from a real
  average-current-HP-over-fight measurement (replace the 0.5 midpoint) - the seam is linear in the fraction so the
  value is a single tunable. A WRONG precompute is worse than none, so do NOT default-ON until validated. DS `:8893`
  restart on flip. Does NOT block any further stage.
