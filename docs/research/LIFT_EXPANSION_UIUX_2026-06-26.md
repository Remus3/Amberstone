# LIFT / EXPANSION / UI-UX Research Synthesis - 2026-06-26

## Executive summary

Across 9 research vectors (lift-competitors, lift-oss-techniques, lift-data-sources,
expand-coaching-surfaces, expand-ds-engine, expand-novel-angles, ui-information-arch,
ui-overlay-glance, ui-tech-perf-a11y), 27 candidate findings were generated and put
through adversarial verification. 25 survived (grounded, novel, off the CLOSED list);
after de-duplication 24 distinct findings remain (the Baron/Elder buff countdown
appeared in two vectors and is merged). Every survivor is single-player-compliant and
either zero-LLM or pure-frontend - none reopen a CLOSED surface.

Top 3 recommendations:
1. Deterministic objective-state pack (dragon-soul tracker + epic buff-expiry timer +
   dynamic respawn fix) - three S-effort, high-confidence, zero-LLM folds over the
   DragonKill/BaronKill event stream RC already reads and discards.
2. Live championStats + stat-shard ingestion into DS - read two already-fetched-but-
   discarded Live Client fields to calibrate the engine against the operator's REAL
   AD/AP/pen/AH/shards instead of theoretical level-scaled stats.
3. Phase-D capability-scorer consumer - turn 11 already-built-but-stranded DS axes into
   a live composition-gap verdict; the code comments themselves call this the next job.

---

## Section 1: LIFT (technique / mechanic lifts and read-side wiring)

Ranked by value x confidence / effort.

### L1. Epic buff-expiry timer - Baron/Elder 180s sided countdown (MERGED: lift-competitors + expand-coaching-surfaces)
- **What:** On a BaronKill (and Elder via DragonType) event, arm a deterministic 180s
  buff window keyed by killer_team and emit a live sided countdown: enemy has it ->
  "enemy baron 1:12 left, defend, do not face-check"; you have it -> "baron 1:40 left,
  take towers NOW". ETA = (down_at_s + 180) - game_time.
- **Why it matters to RC:** Single highest-leverage macro read in mid/late SR; the
  correct response to an enemy epic buff is entirely a function of the timer. RC tells
  the operator to "wait it out" but never how long.
- **Grounding:** core/event_callouts.py:328 inhibitor_callouts proves the identical
  (down_at_s + window) - game_time pattern; dashboard/_liveclient.py:215 carries
  BaronKill with killer_team + down_at_s; macro_response.py:74 emits a one-shot
  "Baron lost" line with no countdown. Buff = stable 180s map constant.
- **RC gap:** No buff-DURATION countdown anywhere; grep baron_buff/buff_remaining = 0
  functional hits. Shipped objective surfaces all stop at the moment-of-take.
- **Effort S / confidence high / risk low.** Additive advisory row, no engine/flip touch.
- **First slice:** Ship Baron alone (unambiguous BaronKill EventName) as one advisory
  countdown row; Elder (DragonType discriminator, already read) is a trivial follow-on.

### L2. Dragon soul-point tracker + soul-race verdict
- **What:** Fold the objective_events DragonKill stream into a per-side 0-4 dragon-stack
  count and emit a glanceable row: at 2 "soul point next drake", at 3 "SOUL next drake -
  force or deny", plus a soul-race delta and the locked element (DragonType already read).
- **Why it matters to RC:** The dragon-soul race is the biggest macro inflection in SR;
  "next drake is soul" is exactly the glanceable correct-by-construction nudge a heads-
  down solo player needs. RC has zero stack awareness despite parsing every DragonKill.
- **Grounding:** dashboard/_liveclient.py:215-236 (DragonKill with killer_team);
  core/macro_response.py:71-73 one-shot lost-drake only; grep soul/dragon_count = 0;
  DragonType read at _state_cooldowns.py:138.
- **RC gap:** No module counts DragonKill per side; event_callouts emits a static
  schedule with no stack awareness.
- **Effort S / confidence high / risk low.** Unresolved killer fails soft to "unknown".
- **First slice:** Count ally/enemy DragonKill events, emit only the 3-stack "SOUL next"
  callout first; add the soul-race delta and element label as follow-ons.

### L3. Dynamic objective respawn callout (fix the static 5:00 cadence)
- **What:** Promote the dynamic last_kill_t + respawn math that already exists in
  decision_detector._next_objective_spawn into the served next_callouts path, so drake/
  baron ETA tracks the real take instead of a fixed game-start cadence.
- **Why it matters to RC:** A drake ETA that drifts after the first take is actively
  misleading (shows "next drake 10:00" when it respawns 12:30). This is plumbing of
  already-written, already-validated math, not new logic.
- **Grounding:** event_callouts.py:62-76 hardcode the static 300s cadence anchored at
  game start; decision_detector.py:155-173 already computes last_kill_t + respawn but
  only behind the vision-gated contest trigger (:179). The two never share take-times.
- **RC gap:** next_callouts has no objective_events param; the accurate computation is
  siloed and only fires on >=2 enemies missing.
- **Effort S / confidence high / risk med (edits a flipped served path).** Reconcile the
  300s dragon / 360s baron constants to one cited source.
- **First slice:** TDD-first characterization test pinning current behavior, then thread
  objective_events into next_callouts for dragon ETA only; baron after.

### L4. Auto-pairing Phase-D consumer for the 11 stranded DS capability scorers
- **What:** Build the explicitly-deferred "Phase D consumer" that reads the 11 additive
  capability routes (anti-tank, zone-control, extended-duel, ...) and emits a single
  composition-gap verdict at champ-select / active-match ("bottom-quartile anti-tank vs
  their 2 stacking-HP frontliners - prioritize %HP shred").
- **Why it matters to RC:** Unlocks a large capability surface RC already paid for - 11
  scored axes sit computed-but-unconsumed. No current surface produces a "which axis is
  your team missing" synthesis.
- **Grounding:** CHANGELOG.md:1945-2052 + cc_output.py:21 repeatedly label the consumer
  "NEXT (Phase D)"; _passive_ally_grant_overrides.py:39-40 cites the same. The OLD
  composition_advisor.py is a static AD/AP item-flagger, NOT a reader of these routes.
- **RC gap:** No consumer reads the 11 capability routes into a verdict.
- **Effort M / confidence high / risk med (cross-axis normalization).** Ship default-OFF
  behind a flag, shadow-validate per RC flip discipline.
- **First slice:** Read ONE axis (anti-tank) against the live enemy comp and emit a
  single advisory line; expand the axis set once the normalization is validated.

### L5. Operator-armed manual-click summoner/ult cooldown tracker
- **What:** Wire RC's already-built haste-aware compute_cooldowns to an operator click:
  click the enemy Flash/ult row to inject a synthetic "used at now()" event, after which
  RC counts it down with full Ionian/Cosmic-Insight/level haste. Sidesteps the 06-16
  cast-detection blocker by making the operator the sensor.
- **Why it matters to RC:** Enemy Flash timing is the single most consequential 1v1 lane
  read. RC already paid for the hard part (haste math); the only missing piece is an
  event source, and a manual click is a proven, valid one.
- **Grounding:** dashboard/_state_cooldowns.py:231-240 returns [] BY DESIGN (all spells
  render READY); compute_cooldowns is haste-aware at :161-227. The 06-16 lift
  (COMPETITOR_LIFT_2026-06-16.md:83-107) CLOSED only the AUTOMATIC path.
- **RC gap:** No UI path injects a "used" event; the haste math never receives a non-
  empty event list.
- **Effort M / confidence high / risk med (UX mis-click, not correctness).** Needs a
  click handler + small POST + localStorage persistence.
- **First slice:** Arm ONLY enemy Flash (the highest-value timer) via one overlay click
  + localStorage; extend to ults later.

### L6. Cannon-wave + recall-window timer (pure game_time math)
- **What:** From game_time alone, compute next cannon wave (first 1:05, 30s cadence,
  every 3rd cannon to 20:00, every 2nd to 35:00) and a recall-safety window ("back NOW,
  next cannon in 24s, you will not miss it"). Low-tier ambient SR overlay cue.
- **Why it matters to RC:** CS-from-recall-timing is a top beginner/intermediate macro
  leak, 100% computable from game_time. Fills the laning recall branch with a concrete
  timer instead of the generic recall_now/back_soon verdict BACKLOG:38 flags as monotonous.
- **Grounding:** grep cannon/wave.spawn in core = only post-game cannon_cs
  (match_metrics.py:244); precomputed_laning_coach.py:84-85 recall branch is generic-
  verdict-only. Distinct from BACKLOG F6 (jungle/relic timers).
- **RC gap:** No live wave-cadence / recall-window computation exists.
- **Effort M / confidence med / risk low.** SR-only mode gate; ration via ambient tier
  to avoid per-wave over-fire.
- **First slice:** A single "next cannon in N s" ambient cue, SR-only; add the recall-
  safety verdict once cadence math is validated live.

### L7. Anti-sustain effective-throughput DS axis (credit Grievous Wounds items)
- **What:** New selective DS axis (parallel to anti-tank) crediting Grievous-Wounds items
  with effective-DPS-vs-a-healing-target value (a 40% heal-cut converts enemy heal/s into
  net DPS you no longer out-damage), wired into a deterministic anti-sustain build variant.
- **Why it matters to RC:** The engine tells the operator to buy anti-heal (heal_threat
  callout) but scores every Grievous item at ZERO DPS value, so the build optimizer can
  never surface "this grievous item beats the raw-DPS item vs THIS enemy" - the exact
  call needed vs Vladimir/Soraka/Aatrox/Mundo.
- **Grounding:** _effects_data.py:344/1782/1846 all note "heal-cut not modeled"; grep
  grievous/heal_cut across scorer files = 0 consumers; anti-tank precedent at
  build_order_variants.py:23 proves the wiring pattern.
- **RC gap:** No DS scorer credits Grievous effective-throughput; only a Haiku-free prompt
  callout exists (the inverse GRIEVOUS_WOUNDS_PCT constant models enemy->us).
- **Effort L / confidence med / risk med (needs an enemy heal/s estimate).** Selective +
  default-inert, gate the flip behind the heal_threat detector, shadow-log first.
- **First slice:** Add the axis as a default-inert route that credits one item
  (Mortal Reminder) only when heal_threat flags a sustain-heavy enemy; shadow-log.

### L8. Role-conditioned draft pair/matchup ratings (lane-aware synergy)
- **What:** Re-key draft_elo smoothed pair/matchup rates on (champ_a, role_a, champ_b,
  role_b) instead of bare id tuples, with a sample-count floor falling back to role-blind.
- **Why it matters to RC:** Sharpens the draft-Elo chip exactly where positional combos
  matter (top-Malphite + mid-Yasuo) without averaging over irrelevant role splits.
- **Grounding:** draft_elo_db.py:122-186 keys on champion_id ONLY; lines 179-184
  EXPLICITLY defer lane filtering as a "future tightening if sample density grows".
- **RC gap:** Model is role-blind. NOTE: the exact idea + sample-floor fallback is already
  anticipated in-code as deferred, gated on the thin solo corpus.
- **Effort M / confidence low / risk high (solo role-keyed cells go sparse fast).**
- **First slice (FUTURE):** Only if corpus density grows - ship default-OFF behind the
  shadow harness for the densest role-pair cells.

### L9. Feed live championStats into DS as ground-truth calibration
- **What:** RC reads activePlayer.championStats but keeps only HP/mana. Read the full
  combat block (AD/AP/armor/MR/pen/lethality/AH/AS/crit/lifesteal) and emit a "DS-assumed
  X vs actual Y" divergence line, optionally seeding DS rank/dps with real stats so mid-
  game recs reflect actual buffs/runes/elixirs/objective bonuses.
- **Why it matters to RC:** DS is the crown jewel but mid-game scores against a theoretical
  level-scaled stat line that ignores rune shards, elixirs, drake/baron stacks, conditional
  passives already live in championStats. Reads an already-fetched-but-discarded field.
- **Grounding:** dashboard/_liveclient.py:89-105 discards every combat stat but HP/mana;
  engine.py:442 base_stats=scaled (level-derived, :139-161).
- **RC gap:** No DS path ingests the live combat block.
- **Effort M / confidence high / risk med (activePlayer-only; transient buffs must be
  labeled so a Baron-window divergence does not read as "DS is wrong").**
- **First slice:** Surface the read-only "DS assumed pen X, actual Y" divergence line
  first (no DS seed-back) so it is purely advisory and cannot mis-rec.

### L10. Ingest live stat shards + full rune list from /activeplayerrunes
- **What:** snapshot_normalizer._read_my_runes collapses /activeplayerrunes to one display
  string, discarding statRunes (the 3 shards) and generalRunes. Parse the structured ids
  and thread the real shard choices into DS base_stats and rune_procs.
- **Why it matters to RC:** Knowing the live shards (double-adaptive vs HP+armor) lets DS
  burst/dps/ehp scorers reflect the operator's real stat line for free, and unlocks a
  "your shards favor X, build should lean Y" nudge. The shard-id->label map already exists
  (_champ_select_deterministic.py:48), used only in the champ-select WRITE path today.
- **Grounding:** snapshot_normalizer.py:1007-1014 returns a flat string; rune_wpa.py:131
  explicitly excludes shards.
- **RC gap:** No in-game DS consumer reads the operator's actual shard selection.
- **Effort M / confidence high / risk low (fixed Riot vocabulary; patch-key the shard->
  stat-delta table like other DS tables).**
- **First slice:** Parse statRunes into the snapshot first and surface the chosen shards
  in DS context; feed into base_stats once the per-patch delta table is keyed.

### L11. Formalize batched DOM writes (DocumentFragment) for high-churn panels
- **What:** Add a fragment-batching helper alongside idempotentRender: build rows into a
  DocumentFragment and do ONE container.replaceChildren(frag) per changed render, so the
  sig-gate decides WHETHER to render and the helper makes the render a single reflow.
- **Why it matters to RC:** On a CHANGED tick the heavy panels (ADAPTATION ~120 rows,
  history, cd_ledger, DS clusters) rebuild row-by-row into the live DOM, thrashing layout
  exactly when the game is busiest (SSE 15s heartbeat + 0.5s L4 tick).
- **Grounding:** idempotent_render.js:25-31; DocumentFragment/replaceChildren in only 2
  files vs innerHTML across 43+ panel sites.
- **RC gap:** No shared fragment-batching primitive; the "now rebuild" half is ad-hoc.
- **Effort S / confidence med / risk low (replaceChildren is a drop-in).** Scope to the
  3-4 measured worst churners, not a repo-wide sweep.
- **First slice:** Apply the helper to the ADAPTATION stats-view alone, measure the reflow
  win, then extend to history/cd_ledger.

---

## Section 2: EXPANSION (new deterministic surfaces over owned data)

### E1. TFT deterministic coaching twin on CommunityDragon static data
- **What:** TFT is the ONLY in-game mode with no deterministic precompute twin (SR/ARAM/
  Arena each have one). Build a TFT substrate the way DS was built: pull CDragon TFT static
  set data (item-component graph, trait minUnits breakpoints, unit costs - pure game data,
  not winrate meta), deterministically generate recipe/breakpoint/econ advice the single
  Haiku call currently improvises, shadow-log det-vs-Haiku, flip.
- **Why it matters to RC:** Directly advances the PRIMARY north star (Haiku-to-ZERO) for
  the one mode that is 100% Haiku-dependent, and retires a stale hand-maintained meta seed.
- **Grounding:** tft_coach_engine.py:701 single Haiku messages.create; data/meta/
  tft_set17_meta.json hand-maintained; no core/precomputed_tft*.py / tft_shadow.py /
  cdragon_tft extractor exists. CDragon TFT static data is permissible game-data (distinct
  from the CLOSED letter.gg TFT meta SCRAPE).
- **RC gap:** No deterministic TFT engine, shadow, or CDragon-TFT extractor.
- **Effort L / confidence high / risk med (trait breakpoints shift per set - needs the
  per-set content guard; comp tier-ranking stays out of scope).**
- **First slice:** CDragon-TFT extractor + a deterministic item-recipe (2-component ->
  completed item) table behind a shadow log; trait/econ follow.

### E2. Spatial position-trace metrics from Match-V5 timeline x/y
- **What:** rewind_history.db already holds 676,802 timeline frames carrying
  participantFrames[].position {x,y} for all 10 players every 60s - RC parses gold/xp/cs
  but DELIBERATELY skips position. Derive deterministic per-game spatial axes: distance
  traveled (roaming), map-coverage area, fraction of minutes in enemy half (aggression),
  and a TRUE proximity-to-objective window (replacing obj_participation's counter proxy).
- **Why it matters to RC:** Mines a 676K-frame asset RC owns and ignores, producing causal
  skill axes the post-game rubric can currently only approximate from challenge counters.
- **Grounding:** builders_lcu_enrich.py:203-205 "position data is deliberately NOT parsed
  here"; obj_participation.py:27-37 counter-based stand-in. Distinct from the CLOSED CV-
  minimap (LIVE OpenCV) and ward-heatmap (no ward x/y) items - this is POST-GAME x/y.
- **RC gap:** No spatial metric module; draft/rubric/session pages have zero positional axes.
- **Effort L / confidence med / risk low (SR-only; fail-soft to placeholder).**
- **First slice:** Compute ONE descriptive axis (fraction of minutes in enemy half) over
  the existing frames and surface it on the post-game rubric.

### E3. lol-challenges percentile as a personalized weakness lens
- **What:** RC reads champion-mastery but never /lol-challenges/v1/challenges/local-player,
  which returns the operator's per-challenge level + percentile + value for ~300 behaviors.
  Pull it once per session and expose the weakest percentile axes as a deterministic focus-
  area line in champ-select / session view.
- **Why it matters to RC:** A Riot-blessed, self-only, single-player percentile source that
  quantifies the operator's actual behavioral weaknesses against Riot's own cohort - the
  personalized non-meta signal RC's charter favors.
- **Grounding:** grep *.py for lol-challenges = 0 LCU-endpoint hits (the 7 "challenges"
  matches are obj_participation, not the API). Mastery IS consumed (lcu_agent.py:425).
- **RC gap:** The operator's percentile-ranked behavioral profile is entirely unused.
- **Effort M / confidence med / risk low (coarse, lifetime-cumulative - frame as a standing
  focus area, not a per-game nudge).**
- **First slice:** Pull the local-player challenge set and surface the single weakest
  percentile axis as one session-view line.

### E4. Closed-loop practice-drill prescriptions with cross-game progress
- **What:** RC DIAGNOSES weaknesses (match_metrics improvement_target/cs_at_10; player_gpi
  8-axis radar + _AXIS_TIPS) but dead-ends at a tip. Add a loop that (1) detects a RECURRING
  weakness across last N games, (2) emits a specific deterministic Practice Tool drill
  ("100 CS by 10:00, no abilities, turret invuln"), (3) re-measures the live cs_at_10 / GPI
  axis next game to show whether the drill moved the needle. All over rewind_history.db.
- **Why it matters to RC:** The missing "next loop" for a solo improvement tool - turns a
  passive diagnosis into an active, measurable, self-relative prescription.
- **Grounding:** match_metrics.py:245/327; player_gpi.py:62 _AXIS_TIPS static prose,
  :300-302 weakest-axis tip; no recurrence detector / re-measurement anywhere. Practice
  Tool / drills appear NOWHERE on the CLOSED list.
- **RC gap:** No drill prescription, recurrence detector, or progress tracker.
- **Effort M / confidence med / risk med (needs a small UI surface + a tunable N-of-M
  threshold to avoid over-prescribing).**
- **First slice:** Detect ONE recurring axis (farming below baseline 4-of-5) and emit a
  single fixed drill prescription on the session page; add re-measurement after.

---

## Section 3: UI / UX (frontend, overlay, a11y - all pure-frontend, no LLM)

### U1. Bar-length depletion encoding for the objective ETA chip
- **What:** Render the objective callout ETA as a short depleting bar (in addition to /
  instead-of-in-combat the M:SS text) - the doctrine rule 10 and condensation spec both
  literally specify "bar = time-to" for this exact cue, but callouts.js renders text only.
- **Why it matters to RC:** The single biggest preattentive lever the doctrine names is
  unimplemented for the most time-critical recurring cue. A depleting bar is read in
  peripheral vision in <200ms; parsing "0:08" requires foveation - violating the combat-
  tier no-text rule (rule 3) the same doctrine enforces.
- **Grounding:** callouts.js:64-96 _fmtEta returns text only; CONDENSATION_SPEC.md:112
  "bar = time-to"; OVERLAY_DOCTRINE.md:60 rule 10. Both specs exist; the bar was never built.
- **RC gap:** No bar/length/position element on the ETA chip.
- **Effort S / confidence high / risk low.** Keep M:SS for the dashboard read; swap to bar-
  dominant only under body[data-fight=1] (combat_mode.js already raises this latch).
- **First slice:** Add the depletion bar to the objective ETA row under data-fight=1 only.

### U2. ARIA-live on the RIGHT NOW coach action
- **What:** #rn-action and #rn-immediate (the most time-critical coaching text) have NO
  aria-live, while lower-stakes surfaces (zone-pill, archetype-nudge, coach-decisions, all
  4 bi-summary asides) already do. Add aria-live=assertive aria-atomic to #rn-action and
  aria-live=polite to #rn-immediate, toggled from the same render that sets the pulse class.
- **Why it matters to RC:** In solo live-coaching the operator's eyes are ON THE GAME. An
  announced coach call (OS/Chrome live-region, or a hook for future deterministic TTS) is
  the glance-free delivery the whole overlay doctrine chases. Zero render cost.
- **Grounding:** index.html:535/542 have no aria-live; :77/119/461/1522 do. right_now.js:4
  already imports selectPrimary/shouldPulse - the announce-tier decision is in hand.
- **RC gap:** No live region on the primary coach action; R30 had no a11y phase.
- **Effort S / confidence high / risk low (gate assertive on shouldPulse so a byte-
  identical 15s heartbeat does not re-announce).**
- **First slice:** Add the two aria-live attrs and gate the assertive level on the existing
  change-detection.

### U3. WCAG contrast + prefers-contrast pass on --signal-dim after the Hextech reskin
- **What:** --signal-dim (#8FA3BF, tokens.css:39) on the new dark Hextech backings
  (#16202E/#0A0E14) is borderline/failing at the 13/15/18px floors and there is zero
  prefers-contrast support. (1) lift --signal-dim where it carries real info, (2) add
  @media (prefers-contrast: more) re-pointing it via the existing token indirection.
- **Why it matters to RC:** A single-operator tool read at a viewing distance during a live
  game (an explicit operator concern). Dim text failing contrast at 13px is read at the
  worst moment; prefers-contrast is the standardized zero-cost lever.
- **Grounding:** tokens.css:39; overlay.css:23-24 backings; token re-point proven at
  overlay.css:48-58. grep prefers-contrast = 0. The Hextech reskin re-pointed every hue
  with no contrast re-audit; R30's 5 phases exclude contrast-ratio.
- **RC gap:** No contrast audit of --signal-dim against the new backgrounds.
- **Effort S / confidence high / risk low.** Split --signal-dim (informational, lifted)
  from a separate --sentinel-dim (kept low) so the "-" sentinel weight does not regress.
- **First slice:** Add the prefers-contrast media block re-pointing --signal-dim; split the
  sentinel token if the "-" cells get too loud.

### U4. Same-document View Transitions for the 11-view switch
- **What:** Wrap applyView's dataset.view flip in document.startViewTransition() (feature-
  detect fallback). The browser auto-animates a GPU crossfade with zero keyframes; ~6 lines
  of ::view-transition CSS + a prefers-reduced-motion guard tune it.
- **Why it matters to RC:** A soft transition gives a perceived-latency win and a spatial
  cue for the AUTO-promote moments (champ-select -> active-match -> last-match) where the
  view changes WITHOUT a click - signaling "the app moved you". Chrome-on-Legion-only makes
  the 111+ floor a non-issue; zero deps respects ADR-008.
- **Grounding:** main.js:718-727 hard-flips dataset.view; grep startViewTransition/view-
  transition across web/ = 0. Distinct from the CLOSED FastAPI/Tauri framework items.
- **RC gap:** No transition layer on view switching.
- **Effort S / confidence high / risk low (gate off under data-shell=overlay; honor
  reduced-motion).**
- **First slice:** Wrap applyView with feature-detected startViewTransition + the reduced-
  motion guard.

### U5. Anticipatory pre-spawn pre-roll for objective callouts
- **What:** Add a lead-time threshold so a drake/baron/herald cue crosses Ambient->Urgent a
  fixed window (10-15s) BEFORE the spawn with a one-shot promotion pulse, wiring the already-
  stubbed objectiveStealNow predicate that today has "no producer yet".
- **Why it matters to RC:** A contest is decided by who is in position when it spawns, so
  the useful alert time is the rotation window before it. Firing only at NOW is reactive;
  pre-rolling converts a "you missed it" callout into a "go now" callout.
- **Grounding:** overlay_priority.js:174 objectiveStealNow "no producer yet" - the priority-
  90 rung is never reached live; CONDENSATION_SPEC.md:112 leaves the cross window
  unparameterized; event_callouts.py holds the deterministic spawn schedule.
- **RC gap:** No anticipatory window producer feeds the arbitration ladder.
- **Effort M / confidence med / risk med (over-fire / alert-fatigue trap).** Route through
  the EXISTING one-shot promotion rule (single pulse on lead-edge) + a configurable window.
- **First slice:** Wire a deterministic 12s pre-roll producer for the dragon cue into the
  stubbed objectiveStealNow predicate; tune the window from there.

### U6. Command palette for view nav + global actions (Ctrl+K)
- **What:** A real Cmd/Ctrl+K command-palette overlay (fuzzy search + result list + recents)
  that jumps to any of the 11 views and fires global actions (Analyze, toggle Zen, coach
  toggle, DS route, jump to a match). Today Ctrl+K only focuses the prompt input; nav is the
  header dropdown only. Sits on the existing hash-router, no rewrite.
- **Why it matters to RC:** 11 views + ~50 panels + many toggles is exactly the "many
  destinations + power-user commands" profile the pattern targets; collapses the multi-step
  header trip and the scattered toggle hunt into one keystroke for a daily power-user.
- **Grounding:** main.js:6907 Ctrl+K only does input.focus(); main.js:872 location.hash=
  '#'+v; digits 1-9 are dev sim fixtures. No palette token in main.js/state.js.
- **RC gap:** No command palette; no keyboard path to a named view.
- **Effort M / confidence med / risk low (remap prompt-focus to Ctrl+/ or make it the
  palette's first action; guard against firing in INPUT/TEXTAREA).**
- **First slice:** Palette with view-jump only (the 11 views); add global actions after.

### U7. Cross-view drill-down: clickable champions/items/matches
- **What:** Establish "entities are links": a champion name deep-links to History/Build-
  Insights filtered to it; a match row deep-links to its Replay/Post-Game. Standardize on
  a hash+query convention (#history?champ=Ahri) the destination view reads on load. Today
  only sparse bespoke hash jumps exist.
- **Why it matters to RC:** RC's value is connecting live decisions to the operator's own
  2944-match corpus. Seeing an enemy champ, the natural next question is "what's MY record
  vs this champ" - clickable entities eliminate the manual switch-view-and-refilter loop.
  This is the IA glue the per-page review left between pages.
- **Grounding:** sparse bespoke jumps (main.js:2153/3157/3595/3786/3841), no shared helper.
  Reuses champ-keyed routes (/api/personal-vs, /api/personal-build, /api/history) - wiring,
  not new data. Distinct from the CLOSED cross-player scouting/multisearch.
- **RC gap:** No general cross-view linking pattern; entity mentions are inert text.
- **Effort M / confidence med / risk med (half-wiring: link exists but destination ignores
  the filter).** Scope to the highest-value pair first.
- **First slice:** Make the active-match enemy champ deep-link to #history?champ= and have
  History read the param on load.

### U8. Keyboard view-switching (g-prefix / bracket keys)
- **What:** Bind a keyboard layer for direct view nav (g-then-letter, or [ / ] to cycle),
  reusing the same location.hash path the dropdown calls; update the keybinds toast.
- **Why it matters to RC:** The lowest-effort, highest-frequency ergonomics win for a daily
  operator who switches Home/History/Build-Insights/Post-Game constantly; the fast-path
  companion to the palette (which handles the long tail).
- **Grounding:** main.js:6842-6917 binds only A/F/Z/Esc/Ctrl+K/?; VIEW_IDS at state.js:37;
  main.js:872 already writes the hash. Digits 1-9 are dev-only, leaving a clean surface.
- **RC gap:** No keyboard view-switch. NOTE: overlaps heavily with U6 - consider together.
- **Effort S / confidence med / risk low (gate behind g-prefix/brackets to avoid the dev
  digit binds; guard INPUT/TEXTAREA).**
- **First slice:** Bind [ / ] to cycle prev/next view in VIEW_IDS order.

### U9. Unified priority-aware dashboard toast system
- **What:** Consolidate the 3 independent hand-rolled toasts (keybinds/advisory/rebuild)
  into one service with a single stacking container, a small priority/queue, dedupe, and an
  aria-live=polite region - porting the overlay's Ambient/Urgent/Emergency arbitration brain
  down to the dashboard.
- **Why it matters to RC:** The 3 bespoke toasts manage their own DOM/timeout with no
  coordination - two can occupy the same corner and the later silently wins, and none are
  announced. The overlay already solved this; the 1920 dashboard has the naive version.
- **Grounding:** header.css .keybinds-toast:3332 / .advisory-toast:3360 / .rebuild-toast:3404,
  each timed independently in main.js (6655/6795/6919); no aria-live on any. overlay_priority.js
  has the 3-tier ladder.
- **RC gap:** 3 uncoordinated toasts, no queue/dedupe/aria-live.
- **Effort M / confidence med / risk low (additive refactor; shim the 3 call sites).** Low
  payoff for a solo tool with infrequent concurrent toasts.
- **First slice:** One shared container + queue behind the existing call sites; add aria-live.

### U10. Audio earcons for the single Emergency cue
- **What:** A tiny rationed Web Audio earcon layer firing ONLY on the edges
  overlay_priority.shouldPulse() already gates - one short non-speech tone per cue class
  (lethal / objective-steal-NOW / choices-appeared), keyed off the exact prevCue!=sel.cue
  cross so audio and visual pop can never disagree. Volume slider, default-OFF mute.
- **Why it matters to RC:** Every cue today is VISUAL and still needs an eye-flick mid-fight.
  Audio is the one modality that delivers a status change while the eyes stay on combat
  (the Halo shield-break proof), occupying zero screen real-estate - advancing rule-6
  never-center-obstruct.
- **Grounding:** grep AudioContext/oscillator/.wav across web/js = 0 (the right_now.js/next.js
  hits are unrelated); overlay corpus has 0 audio/earcon matches. shouldPulse edge exists at
  overlay_priority.js:115. The CLOSED voice items are speech-recognition/TTS, a different thing.
- **RC gap:** No audio output anywhere in the overlay (note: a TTS voice_coach exists, so this
  is specifically the absent non-speech preattentive channel).
- **Effort M / confidence med / risk med (audio fatigue; ration to 2-3 tones).** Web Audio in
  the Electron renderer is inert browser audio - no game-process hooks, no Vanguard exposure.
  Default-OFF.
- **First slice:** One tone for the lethal Emergency edge only, default-OFF behind a settings
  toggle; add the other two classes after living with it.

### U11. Container queries for the active-match panes (one def, 3 widths)
- **What:** Put container-type:inline-size on each .am-pane body and @container rules to
  collapse internal rows/chips, so one pane definition renders in the 1920 cell, the 923
  companion, AND the narrow overlay - shrinking the overlay.css dual-maintenance fork.
- **Why it matters to RC:** RC maintains a heavy overlay.css fork precisely because panels
  cannot self-size to their container; container queries are the modern answer to the exact
  "same panel, three widths" problem, reducing the parallel-codebase tax.
- **Grounding:** active_match.css:35-37 fixed-fr grid; overlay.css:143 max-width:210px fork;
  grep container-type/@container across web/css = 0. Baseline 2024.
- **RC gap:** All responsive logic is viewport @media, which cannot see a pane's rendered width.
- **Effort M / confidence med / risk med (interacts with the overlay's zoom:var(--rc-overlay-
  scale) - the @container measures zoomed px).** Scope first adoption to ONE dashboard-only
  pane (DS combat cluster) before touching the zoomed overlay path.
- **First slice:** container-type + one @container rule on the BUILD pane in the 1920
  dashboard only; validate before the overlay.

### U12. Explainability surface for FLIPPED deterministic coaching
- **What:** /api/coach/trace (coach_trace.py ring buffer) only captures Haiku/Sonnet calls.
  The laning A/B choices are FLIPPED to deterministic-served, so the one path that reached
  Haiku-to-ZERO produces ZERO trace entries. Add a deterministic-decision trace recording the
  DS delta/score + matchup source + the registry rule that fired, surfaced in the same "why"
  tab; add a numeric evidence field to CoachChoice.
- **Why it matters to RC:** Trust + tunability - a solo operator driving Haiku to zero needs
  to verify the engine is "saner not different" before flipping more paths. A why-it-fired
  trace makes shadow-flip validation a glanceable UI act instead of a jsonl grep, and the
  blind spot grows precisely as the north star is achieved.
- **Grounding:** coach_trace.py is API-round-trip-only; _deterministic_coaching.py:645
  resolve_choices has zero coach_trace append; coach_choices.py:58-77 CoachChoice has
  source_tag but no numeric DS-evidence field.
- **RC gap:** Deterministic-served choices emit no trace and have no explainability row.
- **Effort M / confidence med / risk low.** Append the new CoachChoice field at the END with
  a default (CLAUDE.md item-216 lesson).
- **First slice:** Record a trace entry on resolve_choices with the DS delta + source; reuse
  the existing why-tab to render it.

---

## NOW shortlist (highest-leverage, lowest-risk; route through the headless loop next)

| # | Finding | Effort | Why now |
|---|---|---|---|
| 1 | L1 Epic buff-expiry timer (Baron/Elder 180s) | S | High-value macro fact, zero-LLM fold over already-read events, proven inhib-callout pattern |
| 2 | L2 Dragon soul-point tracker | S | Biggest SR macro inflection, S-effort fold, fails soft |
| 3 | L3 Dynamic objective respawn fix | S | Corrects a misleading shipped surface; math already written in decision_detector |
| 4 | U2 ARIA-live on RIGHT NOW action | S | Glance-free coach delivery, zero render cost, un-audited a11y axis |
| 5 | U1 Bar-length objective ETA | S | Closes RC's own doctrine rule 10 against its own renderer; combat-tier no-text win |

Secondary NOW candidates if the loop has headroom: U3 (contrast/prefers-contrast - S),
U4 (View Transitions - S), L4 (Phase-D consumer - M, high-confidence value unlock),
L9 (championStats divergence line - M).

## FUTURE list

- E1 TFT deterministic twin (L, high-confidence north-star advance - large session)
- E2 spatial position-trace metrics (L, net-new but largest scope)
- E4 practice-drill prescriptions (M, needs new UI + tuning)
- E3 lol-challenges weakness lens (M)
- L5 operator-armed CD tracker (M, UX-heavy)
- L6 cannon-wave/recall timer (M)
- L7 anti-sustain DS axis (L, needs enemy heal/s estimate)
- L8 role-conditioned draft (low confidence, gated on corpus density - do last)
- L10 stat-shard ingestion (M)
- L11 DocumentFragment batching (S, perf polish)
- U5 anticipatory pre-roll (M, tuning risk)
- U6 command palette / U8 keyboard nav (consider together, M/S)
- U7 cross-view drill-down (M)
- U9 unified toast / U10 audio earcons / U11 container queries / U12 det-coach explainability

## Explicitly excluded (filtered against the heavy CLOSED surface)

These findings were vetted against the CLAUDE.md "Settled - do not re-litigate" block and
BACKLOG's long "CLOSED" list. They deliberately do NOT reopen: cross-player MMR / global
tier lists / external winrate scrapes (draft tool L, letter.gg, aggregator J), automatic enemy-cast
detection (06-16 cooldown closure), LIVE CV-minimap (LeagueMinimapDetectionOpenCV), ward
heatmaps (no ward x/y), voice/speech coaching, augment-LCU APIs, the FastAPI/Tauri framework
rewrites, or any shipped DS scorer / CC ecosystem / saturated registry. Each survivor is
either a deterministic fold over data RC already reads-and-discards, a read-side consumer the
code itself defers, or a pure-frontend / a11y axis the R30 per-page review never covered.
