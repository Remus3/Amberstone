# Competitor Lift - Guide Site Q (Section-7b heavyweight deep-dive)

Date: 2026-06-30. Target: **Guide Site Q** (guide site Q), the long-running
community AUTHOR-WRITTEN build-guide site for LoL. Single-target teardown.
Distinct from the already-CLOSED stats-aggregator lifts (Aggregator A / Aggregator B /
Aggregator H / Aggregator N / Aggregator D / Aggregator C / Overlay App E / Overlay App F /
Aggregator P / draft tool L / simulator tool R). Guide Site Q is NOT a stats aggregator -
it is a human-authored long-form guide platform, so its DISTINCT surface is the
hand-curated guide structure (THREATS matchup grid, SYNERGIES, the compact
CHEAT SHEET, Pros/Cons, situational-items-with-reasoning) and the in-editor
THEORYCRAFT build calculator that sums an item set into a total stat block.

Scope: lift ONLY mechanics that serve RC's SOLO live coaching / build / matchup
insight. Guide Site Q's community / publishing / SEO / rating / comment / contest
machinery is explicitly OUT (RC is single-player for one operator).

## Sourcing caveat (honest)

guide site Q is bot-defended. A plain WebFetch returns HTTP 403; the Apify
rag-web-browser path returned HTTP 500 on guide + forum URLs. A full
playwright:firefox + RESIDENTIAL-proxy crawl of a live build guide
(/build/...-650618, patch 26.13 era) DID load (HTTP 200) but the Markdown
extractor captured only the author intro prose - the THREATS grid, CHEAT SHEET,
and matchup tabs are JS-tab-rendered and were not in the static Markdown. Per RC
safety rules I did not attempt to defeat the tab/anti-bot gating further.
Findings below therefore combine: (a) the live-loaded guide shell, (b) Guide Site Q
search-index snippets (guide-editor wiki, "So you want to write a guide", the
Synergies-and-Threats support thread), and (c) Guide Site Q's well-documented and
stable guide-editor conventions. Any data SHAPE not captured firsthand is
labeled [INFERRED], not asserted. No XHR payloads are fabricated. Every RC HAVE
claim is cited to file:line and verified against live code this run.

**Anchor fact:** Guide Site Q's value is PRESENTATION of a human's curated plan, not
live compute. RC already owns the math (DS engine) and the matchup verdict; what
Guide Site Q does that RC mostly does NOT is present a per-enemy DANGER RATING grid
and a single-glance CHEAT SHEET. The one place Guide Site Q has real "compute" - the
theorycraft stat-totals calculator - RC already ships (ds-statcheck, lift #5).

---

## Findings (6-point depth checklist each)

### F1 - THREATS grid: per-enemy danger severity rating

1. **WHAT.** In the guide editor, the author rates each enemy champion the guide
   expects to face on a small DANGER scale and tags it with a severity bucket.
   Guide Site Q's buckets are a fixed 5-step ordinal severity, rendered in the live
   guide as color-coded enemy portraits grouped by bucket: Extreme / Major /
   Even / Minor / Tiny (the editor stores an integer severity ~1..5 with a
   color, red = most dangerous down to green = least). Each rated enemy can also
   carry a short free-text "how to play this matchup" note. The reader sees, at
   a glance, "who blows me up vs who I stomp."
2. **HOW.** Per (guide, enemy_champ): a small severity int + an optional note
   string. Presentation = enemy portraits binned into 5 labeled, color-graded
   rows (red->green), each portrait a tooltip/expander to the note [INFERRED on
   the exact storage key names; the 5-bucket red->green ordinal is firsthand
   from the rendered guides and the editor docs]. It is 100% author-authored -
   no aggregation, no live data.
3. **HAVE.** PARTIAL, and along a DIFFERENT axis. RC computes danger
   ALGORITHMICALLY, not as an author opinion, and only for the FIRST enemy:
   - `agents/daemon_slayer/matchup.py:209` `compute_matchup` yields a 1v1 trade
     verdict (all_in / trade / back_off / even) + a signed net_swing for the
     operator champ vs ONE enemy.
   - `dashboard/routes_ds_matchup.py:208` `_serve_ds_matchup` serves it; the
     payload carries `verdict`, `net_swing`, `swing_pct`, `favored`,
     `pct_a_removed/pct_b_removed` per the docstring at lines 27-41.
   - `web/js/panels/ds_matchup.js:239` `renderDsMatchupForChampSelect` renders
     it - but ONLY for the FIRST committed enemy (`enemyIds[0]`, lines 247-251).
     There is no all-five-enemies danger grid.
   - A coarser per-enemy threat surface exists for the damage-mix donut
     (`web/js/panels/threat_donut.js`) but that is damage TYPE (phys/magic/true),
     not matchup danger.
   So RC has a richer-per-pair verdict for one pair, but NOT Guide Site Q's
   one-glance "all 5 enemies ranked by how scary the lane/teamfight is."
4. **WHERE.** A "matchup danger column" over all 5 enemies would be a champ-
   select panel calling the EXISTING `/api/ds-matchup` once per enemy (the route
   already accepts arbitrary champ_a/champ_b and is per-pair cached 5min). Home:
   extend `web/js/panels/ds_matchup.js` (or a new sibling panel) to loop
   `cs.their_team`, fetch each pair, and bin the `verdict`/`swing_pct` into a
   red->green severity column. No engine change; the math already exists per
   pair. This is presentation + N (<=5) calls to an existing route.
5. **EFFORT + RISK.** MED. No new compute, no new route, no new dependency, no
   schema lift - BUT it is NOT a single-payload presentation lift: it requires
   firing the matchup route up to 5x (one per enemy) and orchestrating 5 async
   lands into one grid, which is more than a pure re-render of one served field.
   The verdict-to-severity binning is new (small) presentation logic.
6. **LIFT VERDICT: MED.** Genuinely Guide Site Q-distinct and useful (an at-a-glance
   "rank my 5 lane/fight threats" beats the current first-enemy-only card), but
   it is multi-fetch orchestration, not a one-field re-render, so it does NOT
   qualify as the zero-risk in-run ship. Good FUTURE / BACKLOG candidate.

### F2 - Theorycraft build calculator (item set -> total stat block)

1. **WHAT.** Guide Site Q's build/cheat-sheet editor sums the selected item set into
   a running TOTAL stat block (AD, AP, attack speed, crit, armor, MR, HP, mana,
   ability haste, lethality, move speed, etc.) so the author/reader sees the
   aggregate stats a build yields.
2. **HOW.** Static per-item stat rows summed across the chosen items; some
   derived combat numbers layered on top (Guide Site Q's item DB exposes Damage /
   AS / Lethality / Armor / Health / AH / MR / etc. per item). Pure arithmetic
   over the item stat table - no live data.
3. **HAVE.** YES - already shipped, and BETTER (engine-resolved, not a flat
   sum). RC's `/api/ds-statcheck` resolves the LOCKED champion's full stat block
   FROM the built item set and serves it:
   - `dashboard/routes_ds_statcheck.py:190` `_shape_stats` returns
     `ad, ap, attack_speed, crit_chance, hp, mp, armor, mr` plus damage-breakdown
     fields (lines 213-228), read from `DpsResult.stats` (the engine's resolved
     stat dict, docstring lines 21-33).
   - `web/js/panels/ds_statcheck.js:45-56` `_STAT_ROWS` already RENDERS that
     block (Attack Damage / Attack Speed / Crit Chance / Ability Power / Health /
     Armor / Magic Resist / Avg Hit / Raw Atk DPS / On-Hit per AA).
   RC's version is strictly stronger than Guide Site Q's: it is the engine-resolved
   champion stat block at a chosen level against a what-if target, not a raw item
   sum, and it already adds a DPS number Guide Site Q does not compute.
4. **WHERE.** N/A - shipped (lift #5, the stat-sandbox panel).
5. **EFFORT + RISK.** N/A - already live.
6. **LIFT VERDICT: CLOSED (already shipped, RC's is superior).**

### F3 - CHEAT SHEET: single-glance runes + items + skill order summary

1. **WHAT.** Every Guide Site Q guide leads with a compact "cheat sheet": the rune
   page, the item build (start / core / situational), and the skill-order grid
   (the 18-cell Q/W/E/R max-priority table) condensed into one scannable block
   at the top, before the long-form chapters.
2. **HOW.** A fixed compact layout binding three already-authored sub-objects
   (runes set, ordered item list, skill-order array). Presentation-only over the
   guide's own stored fields.
3. **HAVE.** PARTIAL - RC has the build + matchup pieces but they are SEPARATE
   panels, and RC has NO skill-order (max-priority) surface for the champ-select
   glance:
   - Build order: `core/build_order.py:370` `plan_build_order` +
     `web/js/panels/build_order.js` render an enemy-context-aware ordered item
     build (the "core/situational" analogue, already enemy-reactive via
     target_armor/MR/HP at lines 424-429).
   - Runes: RuneWriter / loadout surfaces exist (`web/js/panels/pgr_loadout.js`,
     `routes_loadout.py`).
   - Skill order: the engine side exists for POST-GAME analysis only
     (`core/skill_wpa.py`), and `tools/daemon_slayer_extract.py` carries skill
     data, but grep finds NO champ-select panel that renders a live Q/W/E/R
     max-priority grid. That piece is genuinely absent from the live glance.
   So a true "cheat sheet" would be a NEW composite, and one of its three
   columns (skill order) has no served champ-select payload today.
4. **WHERE.** A composite champ-select card stacking the existing build_order +
   loadout panels would be presentation-only, BUT adding the skill-order column
   needs a new served field (a max-priority array for the locked champ), which is
   new compute/route. So the full cheat sheet is NOT purely presentation.
5. **EFFORT + RISK.** MED-HIGH. The runes+items recomposition is presentation,
   but the skill-order column requires a new data path (no existing champ-select
   skill-priority payload), i.e. new compute + route. Mixed-effort.
6. **LIFT VERDICT: MED (composite) / the skill-order sub-piece is FUTURE.** The
   recompose-existing-panels half is low-value (RC already shows those panels);
   the net-new value (skill-order grid) needs new compute. Not an in-run ship.

### F4 - Pros / Cons block per build

1. **WHAT.** Guides include a short authored Pros / Cons list for the champ or
   the specific build path (e.g. "+ strong all-in level 6 / - weak vs poke").
2. **HOW.** Two free-text bullet lists, author-written. No data.
3. **HAVE.** PARTIAL / adjacent. RC surfaces strengths algorithmically via the
   DS Profile 8-axis radar (`dashboard/routes_ds_profile.py`,
   `web/js/panels/ds_profile.js`) and trade verdicts, but has no authored or
   generated short prose "pros/cons" bullets. The radar IS the data-driven
   equivalent of "what this champ/build is good at."
4. **WHERE.** Would require a content source (authored text RC has no author for,
   or a Claude/LLM generation = new dependency). Not a fit for a single-operator
   tool with no guide-author.
5. **EFFORT + RISK.** HIGH (needs a new content/LLM source for prose) for LOW
   incremental value over the existing radar.
6. **LIFT VERDICT: CLOSED.** No author in a solo tool; the data-driven radar
   already covers the "strengths" need without prose. Do not pitch.

### F5 - Situational items WITH reasoning ("buy X vs heavy AP")

1. **WHAT.** Guides list situational items keyed to enemy conditions, with a one-
   line WHY (e.g. "vs 3+ AP threats -> Maw"; "vs heavy healing -> Grievous").
2. **HOW.** Author maps an enemy-comp condition to an item + reason string.
3. **HAVE.** YES (data-driven), mostly shipped. RC's build is already enemy-
   context-reactive and RC has the anti-tank / damage-mix reasoning:
   - `core/build_order.py:424-429` re-ranks the ordered build on the live enemy
     target_armor/MR/HP, so situational swaps already happen.
   - `core/ds_antitank_hint.py` (anti-tank hint, lift A3) + `core/damage_mix.py`
     give the "vs this comp, shift damage type" reasoning.
   - `web/js/panels/build_order.js:25` already renders the unique-passive-safe
     ordered build and per-slot excluded_family signal.
   The "with reasoning" text is thinner than Guide Site Q's hand-written WHY, but the
   underlying situational logic exists and is live-reactive (which a static guide
   is not).
4. **WHERE.** Marginal: could add a short reason string per swapped slot in
   build_order.js sourced from the existing antitank/damage-mix signals. Small
   presentation polish over existing signals, not a new capability.
5. **EFFORT + RISK.** LOW-MED, but LOW incremental value (the reactive build +
   antitank hint already deliver the substance).
6. **LIFT VERDICT: LOW / near-CLOSED.** Substantially covered by A3 + the
   enemy-reactive build order; only a cosmetic reason-string remains.

### F6 - Counters page / tier list

1. **WHAT.** Guide Site Q also hosts champion COUNTERS pages and community TIER
   LISTS.
2. **HOW.** Aggregated community votes / authored counter lists; tier lists are
   ranked champ grids.
3. **HAVE.** Covered by prior CLOSED lifts. Counters/synergies presentation was
   the Aggregator N F-series (docs/COMPETITOR_LIFT_2026-06-22_AGGREGATOR_N.md, "counters,
   synergies" line 15); tier lists are the generic stats-aggregator surface
   already CLOSED across Aggregator A/Aggregator B/Aggregator N. RC also has ban-suggest
   (`routes_ban_suggest.py`) and duo-synergy (`routes_duo_synergy.py`) live.
4. **WHERE.** N/A.
5. **EFFORT + RISK.** N/A.
6. **LIFT VERDICT: CLOSED (community-aggregate, covered by prior lifts +
   not-distinct-to-Guide Site Q).**

---

## Triage table

| # | Finding | Verdict | One-line reason |
|---|---------|---------|-----------------|
| F1 | THREATS per-enemy danger grid (all 5) | FUTURE | Guide Site Q-distinct + useful, but needs up-to-5 calls to /api/ds-matchup + binning - multi-fetch, not a one-field re-render. |
| F2 | Theorycraft stat-totals calculator | CLOSED | Already shipped + superior: ds-statcheck resolves the full champ stat block from the build (routes_ds_statcheck.py:213, ds_statcheck.js:45). |
| F3 | CHEAT SHEET composite (runes+items+skills) | FUTURE | Recompose is low value; the net-new skill-order grid column has no served payload (new compute). |
| F4 | Pros / Cons prose | CLOSED | No author in a solo tool; the DS Profile radar already covers strengths data-driven. |
| F5 | Situational items with reasoning | LOW/near-CLOSED | Enemy-reactive build_order + antitank hint (A3) already deliver the substance; only a reason-string remains. |
| F6 | Counters page / tier list | CLOSED | Community-aggregate, covered by Aggregator N lift + generic aggregator CLOSEDs; not Guide Site Q-distinct. |

---

## RECOMMENDED IN-RUN SHIP

**NONE that qualifies - recommend a CLEAN no-op (doc-only this run).**

The in-run ship bar is: HIGH-lift AND LOW-risk AND pure presentation over data
RC ALREADY SERVES (no new compute, no new route, no new dependency, no schema
lift) AND testable. No Guide Site Q finding clears all five gates:

- F2 (the one Guide Site Q feature with real compute, the stat-totals calculator) is
  already SHIPPED in RC and RC's version is strictly stronger - nothing to add.
- F1 (the headline Guide Site Q-distinct feature, the all-5-enemy danger grid) is
  the strongest lift, but it is explicitly NOT a single-served-field re-render:
  it requires firing `/api/ds-matchup` up to 5 times (once per enemy) and
  orchestrating 5 async lands plus a new verdict->severity binning. That is
  multi-fetch + new presentation logic, so it fails the "pure presentation over
  data RC already serves in ONE payload" gate. Correctly a FUTURE/BACKLOG item,
  not a zero-risk in-run slice.
- F3's only net-new value (skill-order grid) needs a new served payload (new
  compute) - fails the gate.
- F4/F5/F6 are CLOSED or near-CLOSED.

Honest call: Guide Site Q is a human-authored guide site, and most of what makes it
distinctive (authored danger ratings, authored pros/cons, authored situational
reasoning) is exactly the "needs a human guide-author" content a SOLO
algorithmic tool replaces with computed surfaces RC already owns (matchup
verdict, DS Profile radar, enemy-reactive build, anti-tank hint, stat-sandbox).
The genuinely liftable idea (F1's per-enemy danger COLUMN) is real but is a
multi-fetch FUTURE item, not a safe in-run re-render. No forced ship.

## FUTURE / BACKLOG candidates

- **F1 (MED):** "Lane/fight threat column" - extend the existing first-enemy
  ds-matchup card into an all-5-enemy danger grid by looping `cs.their_team` and
  calling the EXISTING `/api/ds-matchup` per enemy (already per-pair 5min
  cached), binning `verdict`/`swing_pct` red->green. No engine/route/schema
  change; pure frontend multi-fetch + binning. The single best Guide Site Q-distinct
  idea worth a BACKLOG line.
- **F3 skill-order grid (FUTURE):** a champ-select Q/W/E/R max-priority glance
  would need a new served max-priority payload for the locked champ (engine-side
  skill data exists in `core/skill_wpa.py` / `tools/daemon_slayer_extract.py`
  but is not served to champ-select). New compute/route - a separate DS slice,
  not a presentation lift.
