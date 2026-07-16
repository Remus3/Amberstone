# DS AP-axis kit sweep - Slice B: on-hit AP itemization (combined scorer + kit on-hit + axis coherence)

- Date: 2026-07-16
- Status: APPROVED design v2 (pre-implementation). v1 (compose-scorer-only) was
  proven necessary-but-insufficient by live re-verify; see section 4.
- Author: brainstorming session (DS meta-valuation sweep lane)
- Tier: Tier-2. NEW DS engine scorer + kit-on-hit crediting + axis-coherence gate
  => ENGINE_VERSION bump + Share mirror + DS `:8893` restart + full dual suite
  + live `/api/build-plan` validation. PLUS RC-side routing (classifier roster +
  `default_for_champion`) => RC reload.

## 1. Problem

On-hit AP champions (Gwen, Kayle, Kog'Maw-AP) scale off BOTH abilities AND
attack-speed / on-hit-magic autos. Nashor's Tooth is the bridge item (AP + AS +
ability haste + on-hit magic proc). No DS scorer surfaces it - these champs get
handed a pure burst-mage DoT core.

Live evidence (probed 2026-07-16, `POST /api/build-plan {mode:"SR",level:13}`):
Gwen -> `Liandry's > Blackfire > Cryptbloom > Rabadon's > Shadowflame`; Kayle ->
`Liandry's > Cryptbloom > Stormsurge > Blackfire > Rabadon's`. No Nashor's.

## 2. Scope

- **Slice B (THIS spec):** the validated 3-part fix (section 5) - a new combined
  on-hit DPS scorer, kit-on-hit crediting for the roster champs, and an AP/AD
  axis-coherence gate - plus a broad-scan classifier that routes on-hit AP champs
  to the new scorer.
- **Out of scope:** the 6 existing scorers stay unmodified (additive). Slice A's
  AP-assassin reroute (`_AP_ASSASSIN_IDS`, LEDGER 910) untouched; the new roster
  is disjoint from it. Win-rate matching (target is simulation-optimal, memory
  `project_ds_build_reco_optimal_not_winrate`). A general burst/fight-length
  reweight for these champs (proven the WRONG lever, section 4).

## 3. Root cause (validated, full picture)

Three compounding gaps, each verified live this session:

1. **No combined ability+on-hit-auto scorer.** `/rank-mage` (ability_dps.py) is
   abilities-only (excludes on-hit, docstring 44-46 + 198-201). `/rank`
   (dps.py) is autos-only (no ability burst). `/rank-bruiser` is ability+EHP.
   Nashor's, which pays off across ability AND auto, is undervalued in each.
2. **Champion kit on-hit magic is unmodeled.** The real reason to stack AS/on-hit
   on these champs is their kit's on-hit magic - and it is not credited in either
   DPS half: Gwen P "A Thousand Cuts" is registered (`_passive_damage_overrides.py:599`,
   cadence on_hit) but `apply_passive_damage`-gated (default OFF) AND absent from
   the AA-routed allowlist (`_AA_ROUTED_ON_HIT_KEYS`, dps.py:1052, only
   Warwick/Orianna); Kayle E and Kog'Maw W on-hit magic have NO registry entry
   (their passives are explicitly classed non-damage, `_passive_damage_overrides.py:114,163`).
3. **AD items swamp the AP field.** BotRK (3153) - flat AD + %HP on-hit + AS +
   lifesteal, and AD so it does not compete for the AP budget - ranks #1 in
   EVERY autos-counting scorer (carry, bruiser, burst, and the new combined
   scorer) because the marginal single-item ranker cannot see its AD is wasted on
   an AP champ.

## 4. Why 3 parts, not 1 (the re-verify journey)

v1 assumed a combined scorer alone would surface Nashor's. Live re-verify
(throwaway probes reproduced against the live snapshot, numbers inline below)
disproved that and pinned the real lever:

- **Combined scorer alone:** Nashor's absent from Gwen's top-12; lead is
  `BotRK > Liandry's > Trinity > Kraken`.
- **+ kit-on-hit credit (forced Gwen P onto the AA-routed allowlist +
  apply_passive_damage):** Nashor's rises only to #12. Single-item combined DPS
  vs the tanky curve (armor105/mr52/hp2430): BotRK 148.6 > Liandry's 139.1 >
  Nashor's 100.2 > Lich Bane 98.3 > Rabadon's 78.8. BotRK/Liandry's still
  dominate.
- **Target is NOT the confound:** vs a squishy (armor60/mr40/hp1900) BotRK
  159.4 dominates HARDER and Nashor's falls to absent - lower armor amplifies
  BotRK's raw AD more than its %HP loss costs. A short `fight_length` (the
  existing Jhin burst blend, `core/ds_champion_fight_length.py`) would push
  Nashor's DOWN, since it is a SUSTAINED AS item, not burst - the WRONG lever.
- **Axis-coherence IS the lever:** with the pool restricted to AP-axis items
  (BotRK/Trinity/Kraken removed) + kit-on-hit credited, Nashor's surfaces at #5:
  `Liandry's > Dusk&Dawn > Guinsoo > Statikk > Nashor's(38.1) > Blackfire >
  Lich Bane`.

Conclusion: the fix is combined scorer (part 1) + kit-on-hit credit (part 2) +
AP/AD axis-coherence (part 3). Parts 1-2 make Nashor's *rankable*; part 3 stops
AD items from burying it.

## 5. Design

### 5.1 Part 1 - combined on-hit scorer (DONE, Tasks 1-2)

`agents/daemon_slayer/onhit_dps.py`: `compute_onhit_dps` = plain sum of
`compute_ability_dps().total_ability_dps` + `compute_dps().weighted_dps` (same
DPS units, non-overlapping halves - P in dps.py, QWER in ability_dps.py); plus
`rank_items_by_onhit`. Built + reviewed (T1 clean, T2 code-complete with xfail
markers that flip to pass once parts 2-3 land).

### 5.2 Part 2 - kit-on-hit credit (engine)

Credit the roster champs' on-hit magic in the auto half so AS/on-hit itemization
pays off. `compute_onhit_dps` calls `compute_dps(apply_passive_damage=True)` (the
onhit scorer is exactly the scorer for champs whose passive/ability on-hit
matters - enabling it here is correct, and remains default-OFF for every other
scorer).

- **Gwen P** (already registered): add `("Gwen","P",0)` to `_AA_ROUTED_ON_HIT_KEYS`.
  The existing AA-routing (dps.py:1174-1212) then credits it as an AS-scaling
  on-hit (`per_hit * eff_as`), byte-identical mechanism to Warwick/Orianna.
- **Kayle E + Kog'Maw W:** author new on-hit-rider entries (sustained
  approximation of their timed steroids: Kayle E Starfire Spellblade bonus magic
  on-hit once ranked; Kog'Maw W Bio-Arcane Barrage %max-HP magic on-hit while
  active, with an uptime discount). These are E/W-slot, but `aa_routed_on_hit_entry`
  consults only the P-slot in v1 - EXTEND it (or a small dedicated kit-on-hit
  registry) to route non-P on-hit riders. Each entry validated per-champ live.

### 5.3 Part 3 - AP/AD axis-coherence gate (the real lever)

For AP-axis champs on the onhit scorer, penalize pure-AD items (tag has
"Damage"/"CriticalStrike"/"AttackSpeed" WITHOUT "SpellDamage") so BotRK / Trinity
/ Kraken / LDR stop burying the AP on-hit field. Design:

- A **per-champ coherence strength** carried on the roster: HARD for AP-first
  champs (Gwen - effectively drop pure-AD from the pool, reproducing the #5
  result) and SOFT / OFF for genuine hybrids (Kayle - she really does build
  Guinsoo / BotRK / Wit's End alongside Nashor's + Riftmaker, per
  `ops/audit/ds_cross_eval/reports/Kayle.md`).
- Implemented as a candidate-pool gate or a scoring penalty in
  `rank_items_by_onhit`, reusing/extending `core/build_planner/coherence.py`.
  This lands Slice A's explicitly-deferred "AD-artifact coherence filter"
  (2026-07-16 AP-assassin spec section 5.4).
- Strength is a validated per-champ value (like the Jhin fight_length map / the
  ARAM archetype-override table), NOT a blind heuristic.

### 5.4 Routing / roster

Broad-scan classifier (`tools/ds_onhit_ap_prefilter.py`) emits candidates
(AP-axis + attack-speed/on-hit-reliant); each is live-validated; the committed
roster (`core/ds_onhit_ap_roster.json`) carries `{champion: coherence_strength}`.
`core/archetype_picks.default_for_champion` routes roster champs to `ds.onhit`
(alongside the Slice A `_AP_ASSASSIN_IDS` check, disjoint from it). The dispatcher
(`rank_for_primary_archetype`) forwards the per-champ coherence strength +
`apply_passive_damage`.

### 5.5 Controls (MUST NOT change)

- Pure mages (Syndra/Cassiopeia): autos negligible so onhit ~= mage; not routed.
- AP assassins (Akali/Ekko, Slice A): stay `assassin` (burst).
- AD carries stay `carry`; AD assassins stay `assassin`.
- Operator picks always win (override is default-path only).

## 6. Acceptance (revised, honest)

- Nashor's SURFACES as a viable core AP on-hit option for the roster champs
  (validated #5 for Gwen with parts 1-3) - NOT necessarily #1 (Liandry's
  legitimately leads Gwen; that is correct).
- Kayle gets a hybrid on-hit build with Nashor's in the mix (soft coherence).
- Controls unchanged. Full dual suite + CI green.

## 7. Tests (RED-first)

Engine (DS dir + Share mirror):
- `compute_onhit_dps` exact-sum invariant (DONE, T1).
- With parts 2-3 wired, `rank_items_by_onhit` surfaces Nashor's (3115) in the
  top-N for Gwen / Kayle / Kog'Maw at SR L13 tanky target (the T2 xfail markers
  flip to strict-pass).
- Gwen P AA-routed on-hit adds AS-scaling DPS (per-hit * eff_as) - a numeric
  check on the credited delta.
- Kayle E / Kog'Maw W on-hit entries evaluate > 0 and are AS-scaling.
- Axis-coherence: for an AP-first roster champ, pure-AD items (BotRK 3153) are
  gated out / penalized below the AP on-hit field; for a soft-coherence champ
  they are retained.
- Controls: a pure mage / an AD carry ranking is unchanged by the gate.

RC-side (`tests/`):
- roster champs -> `default_for_champion` primary `onhit`, secondary demoted.
- roster disjoint from `_AP_ASSASSIN_IDS`; controls not routed; operator pick wins.
- `/api/build-plan` for a roster champ returns `scorer == "onhit"` + Nashor's
  present (assert scorer + presence, not a brittle exact-item list).

## 8. Release (Tier-2)

py_compile -> finish ALL engine edits -> bump `ENGINE_VERSION`
(`agents/daemon_slayer/__init__.py:18`, `"1.215.0"` -> next minor, quoted literal
only) -> stage Share mirror in the same commit (the `ds_share_sync` precommit
hook mirrors staged DS source) -> full dual suite ONCE (trust exit code) ->
restart DS `:8893` (confirm port free first) -> reload RC via `restart_trigger.txt`
-> live-validate `/api/build-plan` roster + controls -> verifier subagent gate ->
LEDGER (newest-first) + DS docs sync (no coverage-% recompute) + LIVE_GAME_GATED
note (overlay render eyeball).

## 9. Risks

- **Kit on-hit approximation.** Kayle E / Kog'Maw W are timed steroids modeled as
  sustained on-hit; an uptime discount keeps it honest. Per-champ live validation.
- **Coherence over-reach.** A hard gate on a champ who actually wants hybrid
  on-hit (Kayle) would mis-build her; the per-champ strength (hard Gwen / soft
  Kayle) + control tests mitigate. Strength is validated, not heuristic.
- **Extending AA-routing beyond P-slot** touches a load-bearing seam; guard with
  a byte-identical-when-off test (non-roster champs unchanged).
- **Patch drift** (new on-hit AP releases / kit changes): roster + coherence
  re-scan on patch refresh; reviewer note.
- **Live-gated tail:** overlay RENDER eyeball needs a real game -> LIVE_GAME_GATED_SYNC.

## 10. Relationship to Slice A

Slice A (AP-assassin burst reroute, LEDGER 910) is DONE, disjoint, untouched.
Slice B lands the AD-artifact coherence filter Slice A deferred (5.4). Together
they close the AP-axis kit-blindness OQ23-25 closed on the AD axis (LEDGER 875/885/886).
