# Competitor Lift - Aggregator N (Section-7b heavyweight deep-dive)

Date: 2026-06-22. Target: **Aggregator N** (aggregator N), a long-running
statistical builds / tier-list / guides site for LoL + TFT (also WoW /
Valorant). Single-target teardown across LoL champion builds, ARAM, ARAM
Mayhem, Arena, and TFT, with emphasis on the ARAM balance-adjustment
surface per the charter.

## What Aggregator N is

Aggregator N is a pre-aggregated stats site: it ingests millions of games per
patch and runs a proprietary scoring algorithm over win rate, pick rate,
ban rate, KDA, and game volume to rank every champion S+ .. D and to
publish "highest win rate" builds (runes, starting / core / situational
items, skill priority, summoner spells), counters, synergies, and - for
ARAM specifically - Riot's per-champion ARAM balance adjustments. It is
the closest public analogue to several RC surfaces, and unlike a live
coach it renders flat per-patch data; its value to RC is almost entirely
in PRESENTATION patterns over data RC already computes or already holds
locally.

**Sourcing caveat (honest).** aggregator N is Cloudflare-gated with a
managed "Just a moment..." challenge. A plain WebFetch returns HTTP 403
and the in-browser challenge did not auto-clear; per RC safety rules I
did NOT attempt to defeat bot-detection. Firsthand page renders were
therefore not captured this run. Findings below are built from: (a) live
search-index snippets of the patch 26.12 / 16.12-era Aggregator N pages, (b)
Aggregator N's well-documented and stable UX conventions, and (c) the
publicly visible balance-grid presentation on sibling ARAM sites
(aramnerfs.com, aggregator A/lol/modes/aram, aram-balance.lol) which display the
identical Riot data Aggregator N surfaces. Any data SHAPE I could not capture
firsthand is labeled INFERRED, not asserted as fact. No XHR payloads are
fabricated. Every RC HAVE claim is cited to file:line and verified
against live code + the live `champions.json` snapshot.

---

## Findings (6-point depth checklist each)

### F1 - ARAM per-champion balance-adjustment grid (THE headline lift)

1. **WHAT.** ARAM build pages and sibling ARAM trackers display Riot's
   per-champion ARAM balance modifiers as a first-class visible grid:
   Damage Dealt, Damage Taken, Healing, Shielding, Tenacity, Ability
   Haste (and Attack Speed / Energy on some). Each is shown as a signed
   delta with directional color (green = buff, red = nerf), e.g. "Damage
   Dealt -10%", "Damage Taken +10%". This is the single most ARAM-native
   data surface and it is presented as a static per-champ table, not
   buried in prose.
2. **HOW.** The underlying numbers are Riot's ARAM balance multipliers
   shipped per patch (the same `aramDamageDealt` etc. fields Meraki and
   Data Dragon expose). Presentation = a small labeled stat block, one
   row per modified stat, neutral stats hidden; multiplier rendered as
   `round((mult - 1.0) * 100)` percent with sign + color. Ability Haste
   is an additive flat bonus, not a multiplier (shown as e.g. "+10 AH"),
   so it is rendered differently from the x-multiplier stats. No live
   aggregation - it is static patch data.
3. **HAVE.** PARTIAL - data fully present, display absent.
   RC INGESTS the complete grid already: live `champions.json` at patch
   16.12.1 carries `aramDamageDealt, aramDamageTaken, aramHealing,
   aramShielding, aramTenacity, aramAbilityHaste, aramAttackSpeed` under
   `data[<champ>].lolmath.aram_modifiers` (verified live: 172 champs;
   non-neutral counts dealt=101, taken=102, healing=21, shielding=9,
   tenacity=17; AbilityHaste stored as an additive value where 0 = no
   change). RC CONSUMES only a slice, and only as Claude prompt text:
   - `core/aram_balance_context.py:105` `aram_balance_line()` emits a
     self-only "you deal +X%, take -Y% damage" line (dealt+taken ONLY;
     healing/shielding/tenacity/AH/AS dropped). Its sole consumer is the
     ARAM coach prompt (`coaches/aram_coach.py`, beside the tenacity
     line). The module docstring (`core/aram_balance_context.py:19-24`)
     explicitly marks the ENEMY-side rollup a NON-GOAL "for the prompt"
     because 126/172 champs are non-neutral and it would add prompt
     noise without a clean action.
   - `core/aram_tenacity_context.py` is the proven sibling and already
     has BOTH `aram_tenacity_line` and `enemy_aram_tenacity_line`
     (`coaches/aram_coach.py:29-31, 813-816`) - so the enemy-side read
     pattern already exists in the codebase.
   - The DPS engine path consumes `aramDamageDealt` as a math input only
     (`dashboard/routes_damage_mix.py:14, 114`), not as a displayed
     modifier.
   Grep confirms ZERO web panel renders these multipliers as a number:
   no match for the balance fields in `web/js/panels/*` except unrelated
   `cc_blended_ehp` / `cc_conditional` panels (string false-positives on
   "balance"/"blended"). The dashboard never shows the ARAM grid, and
   never shows it for the enemy team.
4. **WHERE.** Presentation-only slice over existing local data:
   - NEW `dashboard/routes_aram_balance.py` (mirror the shape of
     `dashboard/routes_ds_statcheck.py:361` / `routes_damage_mix.py`):
     `GET /api/aram-balance?champ=<id>[&team=...]` reads the same
     `champions.json` snapshot already loaded by DS and returns the
     non-neutral rows for the operator champ + (optionally) the
     live `liveclient` ally/enemy champs.
   - REUSE `core/aram_balance_context.py` - add a pure data accessor
     `get_balance_grid(champion) -> dict[str, float]` returning ALL
     non-neutral fields (the existing `get_balance_mults` only returns
     the dealt/taken pair). No engine touch, no schema change.
   - NEW `web/js/panels/aram_balance.js` + `web/css/panels/aram_balance.css`:
     a small mode-gated grid (render only when `mode_key == aram`),
     green/red signed deltas, neutral stats hidden, registered like the
     other ARAM-gated panels. Optional second column for the enemy team
     using the live champ list - the enemy rollup that is "too noisy for
     a prompt" is genuinely useful as a glanceable grid (which champs are
     buffed/nerfed this game).
5. **EFFORT + RISK.** LOW. No new external dependency, no Riot/Claude
   call, no DS schema lift, no engine-version bump. Data is already on
   disk, patch-keyed, fail-soft-loaded. One new route + one new panel +
   one pure accessor + one CSS file. Testable headlessly: assert the
   route returns the known live non-neutral values (e.g. Aatrox
   aramDamageDealt 1.05 -> "+5%"); a renderer-idempotency + ASCII test
   mirrors the existing panel tests. Only nuance: render AbilityHaste as
   additive (+N AH) not a percent, and hide the AttackSpeed/AH rows when
   their stored value means "no change".
6. **LIFT VERDICT: HIGH (value) / LOW (risk) - SHIP IN-RUN.** RC already
   holds the exact data Aggregator N and every ARAM site display; RC just
   never surfaces it. Presentation-only over existing local data, no
   dependency, no schema, fully testable. This is the ship-ready
   candidate.

### F2 - Per-slot item table with win-rate + sample on every candidate

1. **WHAT.** The build page frames itemization as a slot-by-slot decision
   table (Starting / Core / Boots / 4th / 5th / 6th slot), each slot
   listing 1-3 competing options, each option annotated with its own win
   rate % and game count. The recommended pick is the frequency-above-
   baseline build, not raw max win rate.
2. **HOW.** Per-slot array `{itemId, winrate, games}` served as flat
   per-patch JSON [INFERRED - shape not captured firsthand; consistent
   with sibling sites and Aggregator N's documented "highest win rate builds"
   framing]. Win rate is empirical from the match corpus, not simulated.
3. **HAVE.** DIFFERENT BASIS. RC's `core/build_order.py` + HZ precompute
   tables produce an optimal ordered build, and `web/js/panels/item_build.js`
   / `build_order.js` render it - but RC's basis is DS combat-sim
   optimality + frequency, NOT an empirical per-slot win-rate ladder with
   sample sizes. RC has no per-item win-rate aggregate table.
4. **WHERE.** Would require aggregating per-item win rate from
   `rewind_history.db` (~2846 matches) keyed (champ, item-slot) - a new
   compute path, new route, new panel column.
5. **EFFORT + RISK.** MED-HIGH. New aggregation over a gitignored SQLite
   DB (needs fixtures; clean-checkout-probe risk), and ~2800 personal
   matches is a thin per-(champ,slot) sample. RC's sim-based build is
   arguably a stronger basis than a low-n personal win-rate ladder.
6. **LIFT VERDICT: LOW.** Overlaps RC's existing build surface on a
   weaker statistical basis for a solo corpus; not worth the new compute.

### F3 - Win-delta vs sample-size confidence signaling

1. **WHAT.** Aggregator N tempers each ranked stat with game volume - tiers
   and "best build" picks weight win rate by sample, and low-volume rows
   are visibly deprioritized so a 55% win rate on 30 games does not
   outrank a 51% on 30,000.
2. **HOW.** Score algorithm blends win/pick/ban/KDA weighted by volume
   [INFERRED methodology; Aggregator N documents "proprietary algorithm" over
   those inputs]. Sample count shown alongside the metric.
3. **HAVE.** YES - RC already owns this primitive. `core/smoothed_rates.py`
   is the shared Laplace/shrink estimator and `web/js/panels/duration_winrate.js`
   already renders shrink-tempered personal win rates with sample context.
4. **WHERE.** n/a - already present; any new personal-stat panel should
   reuse `core/smoothed_rates.py` rather than raw ratios.
5. **EFFORT + RISK.** n/a.
6. **LIFT VERDICT: LOW (already have it).** Reaffirms an existing RC
   convention; nothing to lift.

### F4 - Statistical tier list (S+ .. D) with score column

1. **WHAT.** The ARAM and SR tier lists rank all champions S+/S/A/B/C/D
   with a numeric "score" plus win rate, pick rate, KDA, and game-volume
   columns; ARAM and ARAM Mayhem are separate tier lists.
2. **HOW.** Empirical aggregate per (champ, mode, patch) -> proprietary
   score -> tier bucket. Flat per-patch data, region/rank filterable.
3. **HAVE.** NO direct analogue, and DELIBERATELY OUT OF SCOPE. RC is a
   single-player live coach over the operator's own corpus + DS sim math;
   a global empirical tier list would require a live external winrate feed
   (aggregator A/aggregator-D-class scraping), which the charter forbids as an
   engine data source. RC's DS relative-score (`web/js/panels/ds_relscore.js`)
   is sim-derived, not a population tier list.
4. **WHERE.** Would need an external population-stats dependency - out of
   bounds.
5. **EFFORT + RISK.** HIGH - new external scraped dependency, forbidden
   data source.
6. **LIFT VERDICT: LOW / OUT OF SCOPE.** Conflicts with RC's data-source
   rules; do not pursue.

### F5 - Arena augment PICK-rate presentation (winrate forbidden)

1. **WHAT.** Aggregator N's Arena pages list augments and prismatic items by
   popularity/pick rate (Riot DevRel forbids augment WIN-rate display).
2. **HOW.** Pick-rate counts per augment per patch, flat data.
3. **HAVE.** YES. RC already pulls augment PICK-rate from overlay app E/iesdev
   (`core/augment_external_source.py`) and surfaces it; winrate is
   correctly NOT shown (matches the closed-negative set).
4. **WHERE.** n/a - already present.
5. **EFFORT + RISK.** n/a.
6. **LIFT VERDICT: LOW (already have it; winrate is forbidden anyway).**

### F6 - Patch-freshness signaling

1. **WHAT.** Every Aggregator N page stamps the patch ("Patch 26.12") in the
   title and header so the reader trusts data currency.
2. **HOW.** Static patch label injected at render from the build's patch
   version.
3. **HAVE.** YES, internally. RC keys everything on
   `data/daemon_slayer/current.txt` (16.12.1) and the DS `/health`
   surface; the dashboard knows its patch. Whether every ARAM panel
   stamps it visibly is a minor polish item, not a lift.
4. **WHERE.** A new ARAM-balance panel (F1) should print the patch label
   in its header for free (read from `current.txt`, already loaded).
5. **EFFORT + RISK.** TRIVIAL - folds into F1.
6. **LIFT VERDICT: LOW (fold into F1 header).**

### F7 - TFT comps / item-builder (lower priority, noted only)

1. **WHAT.** Aggregator N TFT pages rank comps and provide an item-builder
   (component -> completed item grid).
2. **HOW.** Flat per-patch comp aggregates + a static component
   combination matrix.
3. **HAVE.** RC's TFT surface is coaching-oriented, not a comp tier list
   or item-builder; no direct analogue.
4. **WHERE.** Would be a large new TFT data + UI build.
5. **EFFORT + RISK.** HIGH - new data domain + UI.
6. **LIFT VERDICT: LOW / out of run scope.** Noted for completeness only.

---

## RANKED LIFT TABLE

| Finding | Verdict | Risk | Ships in run? |
|---|---|---|---|
| F1 - ARAM per-champion balance-adjustment grid panel | HIGH | LOW | YES - presentation-only over existing local champions.json |
| F6 - patch-freshness label on the new panel | LOW | TRIVIAL | YES - folds into F1 header |
| F3 - win-delta vs sample-size shrink | LOW (already have) | n/a | n/a - reaffirm `core/smoothed_rates.py` |
| F5 - Arena augment pick-rate | LOW (already have) | n/a | n/a |
| F2 - per-slot item win-rate ladder | LOW | MED-HIGH | NO - new DB aggregation, weak solo sample |
| F4 - global statistical tier list | LOW / OUT OF SCOPE | HIGH | NO - forbidden external winrate source |
| F7 - TFT comps / item-builder | LOW | HIGH | NO - new data domain |

## Bottom line

The one clean, ship-ready lift is **F1: an ARAM balance-adjustment grid
panel**. RC already ingests the full 7-field Riot ARAM modifier grid
locally in `champions.json` (verified live, 172 champs) but only feeds a
2-field self-only slice into the Claude prompt and never displays it on
the dashboard - and never for the enemy team. Aggregator N and every ARAM
sibling site show this grid as a core surface. Re-implementing it in RC's
own code is presentation-only over existing local, patch-keyed data: no
new dependency, no Claude/Riot call, no DS schema lift, no engine-version
bump, fully testable headlessly against known live values. The enemy-team
column (a documented NON-GOAL for the prompt because it is too noisy as
prose) becomes the panel's differentiator as a glanceable grid.
