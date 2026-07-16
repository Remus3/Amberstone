# DS AP-axis kit sweep - Slice B: on-hit AP combined-DPS scorer

- Date: 2026-07-16
- Status: APPROVED design (pre-implementation)
- Author: brainstorming session (DS meta-valuation sweep lane)
- Tier: Tier-2. NEW DS engine scorer (7th archetype) + `/rank-onhit` route =>
  ENGINE_VERSION bump + Share mirror + DS `:8893` restart + full dual suite
  (DS dir + `tests/`) + live `/api/build-plan` validation. PLUS an RC-side
  routing change (classifier roster + `default_for_champion`) => RC reload.

## 1. Problem

On-hit AP champions (Gwen, Kayle, Kog'Maw-AP) scale their damage off BOTH
abilities AND attack-speed / on-hit-magic autos. Nashor's Tooth is the bridge
item: it grants AP + attack speed + ability haste + an on-hit magic proc
(Icathian Bite, `agents/daemon_slayer/_effects_data.py:929-942`,
`bonus_damage = 15 + 0.15 * c.ap`). No DS scorer values that bridge, so Nashor's
never surfaces and these champs are handed a pure burst-mage DoT core.

Live evidence (probed 2026-07-16 via `POST /api/build-plan {champion, mode:"SR",
level:13}` + `POST /api/ds-preview {..., archetype}`):

| Champ  | Default lead (scorer)                                              | Nashor's? |
|--------|-------------------------------------------------------------------|-----------|
| Gwen   | `Liandry's > Blackfire > Cryptbloom > Rabadon's > Shadowflame ...` (ability) | no |
| Kayle  | `Liandry's > Cryptbloom > Stormsurge > Blackfire > Rabadon's ...` (ability)  | no |
| Kog'Maw| (AP) same sustained-DoT ability family                              | no |

Forcing the `carry` / `hybrid` archetype (probed 2026-07-16) gives the opposite
failure - a pure-AD auto build with still no Nashor's, because that scorer sees
only autos and none of the ability burst:

| Champ  | Forced `carry` build (scorer=dps)                                       |
|--------|-------------------------------------------------------------------------|
| Gwen   | `BotRK > Trinity Force > Kraken Slayer > Essence Reaver > Stormrazor ...`|
| Kayle  | `BotRK > Kraken Slayer > Eclipse > Stormrazor > Trinity Force ...`       |
| Kog'Maw| `BotRK > Runaan's Hurricane > Kraken Slayer > Essence Reaver ...`        |

Cross-eval confirms the miss independently: `ops/audit/ds_cross_eval/reports/
Kayle.md` verdict MISMATCH - scorer top-8 is entirely AP-DoT with ZERO overlap
with Kayle's empirical above-baseline winners (all on-hit: BotRK, Guinsoo,
Terminus, Wit's End, Recurve Bow); the one AP winner (Riftmaker) sits at scorer
rank 10.

This is the AP-axis analog of Slice A's AP-assassin miss, but harder: Slice A
was a REROUTE to an existing already-correct scorer. Slice B has no correct
scorer to route to - the combined ability + on-hit-auto DPS term does not exist.
Validated NOT fixable by reroute (2026-07-16): forcing `bruiser`/`carry` gave AD
builds; the mage scorer is abilities-only. It is a genuine modeling gap.

## 2. Scope

- **Slice B (THIS spec):** a NEW 7th DS archetype scorer that composes ability
  DPS + on-hit-inclusive auto DPS into a single combined-DPS score, plus a
  broad-scan classifier that routes on-hit AP champions to it.
- **Out of scope:**
  - The 6 existing scorers (carry/tank/bruiser/mage/assassin/enchanter) are NOT
    modified. This is additive.
  - Slice A's AP-assassin reroute (`_AP_ASSASSIN_IDS`, LEDGER 910) is DONE - not
    touched. The new roster is DISJOINT from it.
  - Win-rate matching. Per memory `project_ds_build_reco_optimal_not_winrate`,
    the target is the simulation-optimal build, not the empirical meta table.
    Success = Nashor's / on-hit-AP items surface AND the build is coherent. For
    Kayle specifically this may stay more AP-leaning than her empirical
    on-hit-AD-hybrid meta; that is acceptable and correct-by-simulation.
  - Zhonya's / defensive-slot buys (a squishy-carry defensive concern, separate).

## 3. Root cause (validated)

No DS scorer computes ability DPS + on-hit-auto DPS TOGETHER. Each existing
scorer sees only one half, so Nashor's (which pays off in both halves at once)
is undervalued everywhere:

- **`/rank-mage` (mage, `agents/daemon_slayer/ability_dps.py`)** - abilities
  only. `compute_ability_dps` sums per-spell Q/W/E/R DPS and DELIBERATELY
  excludes the passive + on-hit (docstring lines 44-46 + 198-201: "the
  `compute_dps` auto-attack scorer covers on-hit passives"). So Nashor's attack
  speed and its on-hit magic proc are invisible; only its raw AP counts, and
  Nashor's gives less AP than Rabadon's -> it loses. This is the DEFAULT scorer
  for these AP champs.
- **`/rank` (carry, `agents/daemon_slayer/dps.py`)** - autos + item procs +
  on-hit ONLY, no ability burst. `compute_dps` DOES credit Nashor's on-hit magic
  (`_periodic_proc_dps`, dps.py:267; per-attack proc for item 3115). But with no
  ability contribution and no AP items in the auto-optimal build, AD-crit items
  out-DPS an AP-on-hit build at level 13 -> pure-AD lead, Nashor's buried.
- **`/rank-bruiser` (hybrid, `agents/daemon_slayer/hybrid.py`)** - already
  AP-axis-aware (for an AP champ `_damage_axis == "ap"`, hybrid.py:462-469 uses
  `_ability_damage` = `compute_ability_dps().total_ability_dps` as the damage
  term). But it scores damage + EHP (alpha/beta ~0.5/0.5), not damage + damage.
  Wrong axis for a squishy on-hit carry, and it still never sees the on-hit
  autos.

The two damage halves are NON-OVERLAPPING by design: passive (P) on-hit lives in
`compute_dps` (dps.py), the four active spells (Q/W/E/R) live in
`compute_ability_dps` (ability_dps.py). So their SUM is the champion's true total
sustained DPS with no double count (see 5.7 for the audit).

## 4. Approach decision

**Chosen (operator-approved 2026-07-16): a new combined-DPS scorer.** Rejected
alternatives:

- *Extend the carry `/rank` scorer* to add ability DPS for on-hit-AP champs -
  mutates the load-bearing pure-ADC path; the DSP11 kit-axis note
  (`project_dsp11_gate_do_not_revert`) warns against flipping shared scorers.
- *Reroute to bruiser + reweight* - bends a damage+EHP scorer into damage+damage;
  the alpha/beta table has no meaning for a squishy carry, and it still misses
  the on-hit autos.

**Why this is not a re-pitch of the settled 6-scorer plan.** The CLAUDE.md
"Settled" note ("the 6-scorer archetype-expansion plan ... is fully wired ... Do
not re-plan these or re-pitch a scorer") forbids re-litigating the SIX existing
scorers. This is a NET-NEW 7th scorer for a capability none of the six cover,
directed by the operator this session - not a re-plan of the six.

**Why a plain SUM, not alpha/beta.** Unlike hybrid.py (which mixes DPS units
with EHP units and therefore needs normalization + weights), both halves here are
in the SAME units (sustained damage per second). Their plain sum IS the
champion's total DPS - no normalization, no weights. v1 ships the plain sum
(YAGNI); an optional per-champ ability/auto weight is a future lever only if a
champ proves lopsided, deferred.

## 5. Design

### 5.1 New scorer module - `agents/daemon_slayer/onhit_dps.py`

Mirrors `hybrid.py`'s compose structure (import both computes, expose a
`compute_*` + a `rank_items_by_*`).

- `compute_onhit_dps(snapshot, champion_id, level, item_ids, mode, target_*,
  augments, ...) -> OnhitDpsResult` where the score is:
  `onhit_dps = compute_ability_dps(...).total_ability_dps
             + compute_dps(...).weighted_dps`
  Both sub-computes already exist; both receive the same target + mode +
  augments plumbing. `OnhitDpsResult` surfaces the two component DPS values plus
  the sum (explainability), analogous to `HybridResult`.
- `rank_items_by_onhit(snapshot, champion_id, level, current_item_ids, ...,
  target_*, top_n, sort_by, ...) -> OnhitDpsRankResult` - same candidate
  pipeline as the other rankers (`_filter_candidates`, `_is_terminal`,
  `strip_arena_trinkets`, melee-gate via `_champion_is_melee`). For each
  candidate: `delta = compute_onhit_dps(build + cand) - baseline`, sort by
  `delta` (default) or `delta per 1k gold` (`efficiency`). Reuse the shared
  `SORT_KEYS`. Inherit `unique_passive_key` + dead-unique dedup exactly as the
  DPS ranker.
- Ranked rows carry `delta_dps` (the combined delta), `ability_dps` +
  `auto_dps` component splits, `gold`, `is_terminal`, `unique_passive_key`,
  `dps_per_1k_gold` so the RC-side `/api/ds-preview` thin projection
  (`dashboard/routes_state.py:592-597`) and `core/build_planner/scoring.py`
  read it with no changes (scoring.py reads `delta_dps` and tolerates absent
  fields - `core/build_planner/scoring.py:20-24`).

### 5.2 Engine route + client + dispatcher wiring

- **Server route:** add `_route_rank_onhit` handler + register
  `"/rank-onhit": _route_rank_onhit` in the dispatch dict
  (`agents/daemon_slayer/server.py:2025-2030`, alongside `/rank-mage`
  `/rank-assassin`). Add the doc-table row (server.py:126-131). Parse the same
  shared body (target overrides, level, items, slots, top_n, sort_by) the
  sibling routes use.
- **Client:** add `rank_onhit_for(...)` in `core/daemon_slayer_client.py`
  (sibling of `rank_mage_for` at :502 / `rank_assassin_for` at :648), POSTing
  `/rank-onhit`, same engine-down fail-soft semantics (None on failure) + the
  same `RankedItem` parse used by the DPS path so `effective_score` /
  `delta_dps` survive (memory `reference_ds_client_effective_score_parse`).
- **Dispatcher:** add an `archetype == "onhit"` branch in
  `rank_for_primary_archetype` (`core/daemon_slayer_client.py:1001`) that calls
  `rank_onhit_for`. Kit-dependent like ds.ability/ds.burst - the all-zero-kit
  guard (client.py:980-985) already routes kit-less champs away from
  kit-dependent scorers; keep `onhit` on the kit-dependent side so a champ with
  no ability entries does not 0.0-collapse.

### 5.3 Broad-scan classifier + roster - `tools/ds_onhit_ap_prefilter.py`

The operator chose a broad auto-scan (not a hand-pinned set). The scan tool
(mirrors the `tools/ds_*_prefilter.py` + block-scanner idiom) reads champion
records + ability/effects data and emits CANDIDATES via a kit-shape predicate,
which are then live-validated down to the committed roster.

Predicate - a champion is a candidate when BOTH:

1. **AP damage axis** - `info.magic > info.attack` (the `_damage_axis` signal,
   hybrid.py:73-79). Fallback for DDragon-zeroed-info champs: ability-block
   classification `_classify_primary_scaling` (ability_dps.py:873) == "AP".
2. **Attack-speed / on-hit reliance** - ANY of:
   - a kit on-hit / per-attack MAGIC damage component that scales with AP
     (Gwen P, Kayle E, Kog'Maw W) - detected from ability data / a small
     curated on-hit-kit hint list when the ability schema does not tag it
     cleanly;
   - an attack-speed steroid ability (large bonus AS on cast);
   - elevated `stats.attackspeedperlevel` on an AP-axis champ (weak signal,
     validation-gated).

The predicate is deliberately permissive (broad scan). It does NOT need to be
perfectly precise because (a) the scorer is self-limiting (5.5) and (b) every
candidate is LIVE-VALIDATED before it enters the roster: probe
`/api/ds-preview {archetype:"onhit"}` vs the champ's current default, KEEP only
where an on-hit-AP item (Nashor's / Guinsoo / on-hit family) genuinely surfaces
AND the build reads coherent (per the CLAUDE.md "Engine / Build Conventions"
per-champion validation rule). The committed roster is the validated subset,
written as a registry JSON consumed RC-side (5.4). Re-run on patch refresh (a
reviewer note, like `_AP_ASSASSIN_IDS`).

### 5.4 RC routing - `core/archetype_picks.py`

Add a roster read + a parallel routing check in `default_for_champion`
(`core/archetype_picks.py:444`), immediately alongside the Slice A
`_AP_ASSASSIN_IDS` check (archetype_picks.py:475). When
`canonical_champion_id(champion)` is in the on-hit-AP roster AND the call is the
default path (an explicit operator pick returns early, unchanged), force
`primary = "onhit"` and demote the tag-derived primary to `secondary` (so the
operator can flip back in one tap). The roster is DISJOINT from
`_AP_ASSASSIN_IDS` (a test asserts no overlap - an AP assassin routes to burst,
an on-hit AP routes to onhit).

### 5.5 Self-limiting safety argument

The combined scorer is a strict generalization that is SAFE on a false-positive.
If a pure mage (no AS steroid, no on-hit magic passive, low base AD + low AS) is
wrongly routed to `onhit`, its `compute_dps().weighted_dps` auto half is
negligible next to its ability half, so `onhit_dps ~= total_ability_dps` and the
ranking degenerates to ~the mage answer - Nashor's still loses to Rabadon's.
The auto half only changes the outcome for champs whose autos are material (the
real on-hit-AP champs). Over-routing therefore degrades to the current behavior
by construction, not to a wrong build. This is the backstop behind the
permissive predicate.

### 5.6 Controls (MUST NOT change)

- Pure sustained AP mages stay effectively as-is: `Syndra, Xerath, Cassiopeia,
  Vladimir, Vex` (autos negligible -> onhit ~= mage; and most are not even
  routed by the predicate).
- AP assassins stay `assassin` (Slice A): `Akali, Ekko, Fizz, Katarina,
  LeBlanc, Diana`.
- AD carries stay `carry`; AD assassins stay `assassin`.
- Operator picks always win (the override is default-path only).

### 5.7 Double-count audit (implementation checkpoint)

Before shipping, confirm no single damage source is counted in BOTH sub-computes
for each roster champ. Known-clean by design (P in dps.py, QWER in
ability_dps.py), but dps.py has an opt-in "route an on_hit passive to AA cadence"
path (dps.py:1162-1207, `aa_routed_on_hit_entry`). Assert the roster champs'
on-hit passives are credited in exactly one half (add a per-champ test comparing
`ability_dps + auto_dps` against a hand-computed expected for at least one roster
champ). If a champ double-counts, prefer keeping the on-hit in dps.py (autos) and
confirm ability_dps.py excludes it (it excludes P wholesale, so this is the
expected resolution).

### 5.8 Data flow

`default_for_champion` (roster) -> `get_archetype_for` ->
`routes_state._serve_ds_preview_post` / `_serve_build_order_post` ->
`core.daemon_slayer_client.rank_for_primary_archetype(archetype="onhit")` ->
POST `/rank-onhit` to `:8893` -> `rank_items_by_onhit` -> `compute_onhit_dps`.
The build-order path (`core/build_order.plan_build_order`) iterates the same
per-archetype scorer, so the ordered plan flows through `onhit` too once the
dispatcher branch exists.

## 6. Tests (RED-first, TDD)

Engine (DS dir + Share mirror):

- `compute_onhit_dps` returns `total == ability_dps_component + auto_dps_component`
  for a fixed Gwen build (exact-sum invariant, the double-count guard of 5.7).
- `rank_items_by_onhit` surfaces Nashor's Tooth (3115) in the top-N for Gwen /
  Kayle / Kog'Maw at SR L13 vs the tanky mode-level-curve target. (RED today:
  no such scorer / route exists.)
- Route smoke: `/rank-onhit` returns a well-formed ranked list; unknown-kit champ
  degrades (kit-dependent-guard) rather than 500.

RC-side (`tests/`):

- Each validated roster champ: `default_for_champion` -> `primary == "onhit"`,
  `secondary` = the demoted tag primary.
- Controls unchanged: `Syndra`/`Cassiopeia` NOT `onhit`; `Akali`/`Ekko`
  (Slice A) stay `assassin`; a representative AD carry stays `carry`.
- Roster disjoint from `_AP_ASSASSIN_IDS` (set-intersection empty).
- Operator pick still wins (a persisted `mage` pick on a roster champ is not
  overridden).
- Integration: `/api/build-plan` for a roster champ returns `scorer == "onhit"`
  and an on-hit-AP-inclusive build (assert scorer + Nashor's presence, NOT a
  brittle exact-item list).

## 7. Verification + release (Tier-2)

1. `py_compile` every touched `.py` before any restart (CLAUDE.md hard rule).
2. Finish ALL DS-engine edits before running the full suite (memory
   `feedback_finish_ds_edits_before_full_suite`).
3. Bump `ENGINE_VERSION` in `agents/daemon_slayer/__init__.py:18` (currently
   `"1.215.0"` -> next minor). Replace only the quoted literal
   (`feedback_engine_bump_quoted_literal_only`).
4. Stage the Share mirror in the SAME commit (`feedback_ds_commit_share_test_mirror`);
   watch tools/Share drift (`feedback_share_mirror_tools_drift`). Regen the dist
   bundle if a worktree merge is involved (`feedback_ds_worktree_merge_regen_dist_bundle`).
5. Run the FULL dual suite ONCE (DS dir + `tests/`); trust the exit code (R6).
   Re-verify fresh before any green claim (Verification Discipline).
6. Restart DS `:8893` - `schtasks /End` + `/Run RC-DaemonSlayer`, confirm the
   port is free first (`reference_ds_server_not_supervisor_watched`). Wait for
   the Share sync + restart to settle before any live probe
   (`feedback_finish_ds_edits_before_full_suite`).
7. Reload RC via `restart_trigger.txt`; confirm `health.json` new pid + alive +
   `last_reload_ok`.
8. Live-validate `/api/build-plan` on the roster + controls; confirm Nashor's
   surfaces for roster champs and controls are unchanged.
9. LEDGER entry (newest-first, `docs/LEDGER.md`) + DS docs sync
   (`feedback_ds_coverage_prose_recompute` - do NOT recompute coverage % in a
   general sync).

## 8. Risks

- **Classifier over/under-reach.** Mitigated by the self-limiting scorer (5.5)
  + per-champ live validation (5.3) + control tests (6). The roster is the
  VALIDATED subset, not the raw predicate output.
- **Double count** across the two halves (5.7) - guarded by the exact-sum test.
- **Patch drift.** New on-hit-AP releases or AS/kit changes need a roster
  re-scan; guarded by a reviewer note + the scan tool being re-runnable.
- **Kayle divergence.** Kayle's simulation-optimal onhit build may not match her
  empirical AD-on-hit-hybrid meta. Per `project_ds_build_reco_optimal_not_winrate`
  this is acceptable; success is Nashor's surfacing + a coherent build, not a
  win-rate match. Flagged so it is not mistaken for a defect at validation.
- **Live-gated tail.** An overlay RENDER eyeball of the new onhit builds needs a
  real game -> `docs/LIVE_GAME_GATED_SYNC.md` (mirrors Slice A's live tail).

## 9. Relationship to Slice A

Slice A (AP-assassin burst reroute, `_AP_ASSASSIN_IDS`, LEDGER 910) is DONE,
shipped, CI-green - not touched. Slice B is additive and disjoint: a new scorer +
a new, non-overlapping roster. The two together close the AP-axis kit-blindness
that OQ23-25 closed on the AD axis (LEDGER 875/885/886).
