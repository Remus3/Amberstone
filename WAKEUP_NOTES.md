# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s226 wrap — 2026-05-16 (DS Phase 5.9.26: first form_index coverage sweep since s205)

**Operator instruction:** same self-paced loop. **Iteration 4** (s223=it1, s224=it2, s225=it3, all same session-day).

## What happened — pivoted the proven methodology to a fresh registry

block_index coverage exhausted across s223-225 (both scan axes). Applied the SAME pre-filter+ground-truth-A/B methodology to the far-less-scrutinized `champion_form_index.json` (only 9 champs vs block_index's 25+ batches). New `tools/ds_form_index_prefilter.py` A/B'd forced form 0 vs each later form over all 16 multi-DAMAGE-form (champ,key) pairs not yet mapped → 9 flagged, 3 clean ADDs after per-champion judgment.

## Shipped (committing now)

- **`Swain {R:1}`** — form 0 'Demonic Ascension' is the 7.5-17.5 drain-channel per-tick; form 1 'Demonflare' is the 150-350 + 50% AP recast nuke (Swain's ult payoff). Live A/B **12.5→250 (20×)**. Same shape as the pre-existing AurelionSol R=1.
- **`Briar {W:1}`** — form 0 'Blood Frenzy' has **zero damage blocks** (it's the AS/MS frenzy-buff cast); form 1 'Snack Attack' is the entire W damage incl. the s224-migrated 9% missing-HP. A/B 72→129.5.
- **`Evelynn {E:1}`** — form 1 'Empowered Whiplash' = Eve's canonical Demon-Shade-opened combo E (1.33× form 0 + 4% vs 3% max HP). **Composes orthogonally** with Evelynn's s204 block_index `{R:1,Q:5}` (form_index picks the form, block_index the block within it — like Jayce Q s194). A/B 120→160.

form_index 9→**12 champs**. ENGINE 0.97→0.98; 8 pin bumps + `test_form_index_sweep_s226.py` (10 tests). DS 2113→**2123**; wider RC **1107**; DS restarted → 0.98.0.

## Don't-redo / blockers

- **Skips are deliberate + documented in the registry _meta rationale**: Heimerdinger W/E form 1 = the R-UPGRADED one-shot cast → R-gated; modeling W/E as upgraded over-attributes R's empower to W/E (must score R-independent — same principle as s225 Varus W block 2 vs R-entangled block 4). These belong to the **conditional-target-state schema-lift bucket** along with Fiddle fear-state, Skarner boulder, LeBlanc Mimic. Gnar Q/E + RekSai Q = contextual transforms (uncontrollable Rage / burrow-dance) — form 0 is the dominant-uptime default, correct as-is.
- form_index and block_index are **orthogonal registries that compose** — Evelynn now exercises both. Don't assume a champion in one is absent from the other.
- Both block_index AND form_index coverage spaces are now swept (4 iterations s223-226). Don't re-run these scans expecting yield.

## NEXT (self-continuing loop)

Iteration 5 options: (a) **combo_sequence registry audit** (assassin burst combos — even less scrutinized than form_index; does the default `Q-W-E-AA-R-AA` under-represent specific champions' real burst rotations?); (b) **max_priority registry audit** (mage spell-max order — s185 did 12 champs, are there more?); (c) flag the conditional-target-state schema lift for operator (architectural; it's now the common blocker for Heimer/Fiddle/Skarner/LeBlanc). s220 aggregator G Post-Game-Review reframe remains the big pending UI item.

---

# s225 wrap — 2026-05-16 (DS Phase 5.9.25: post-parser-fix block_index sweep — Varus W)

**Operator instruction:** same self-paced loop ("continue ds work in parallel for the next hour self continue — maximum effort"). **Iteration 3** (same session-day; s223=it1, s224=it2).

## What happened — closed the iteration-2 Varus-W follow-up

s223+s224's parser fixes re-parsed %HP onto many blocks. Re-ran `tools/ds_unmapped_key_prefilter.py` over the POST-s224 snapshot — champions whose candidate blocks evaluated ~0 pre-migration now show real ratios. Shortlist: 6 (Corki R / DrMundo Q = documented skips; Fizz W = confirmed skip block-0-is-"Total"; LeBlanc R = deferred s197 data-gap; Fiddlesticks Q = no entry needed; **Varus W = the one clean ADD**).

## Shipped (committing now)

**`Varus: {W: 2}`** — "Blighted Quiver" block 2 `Bonus Magic Damage at Max Stacks` proven **exactly 3× block 1's per-Blight-stack** value at every rank (the 3-stack detonation = Varus's standard combo: W-passive stack via AAs/Q then Q/R-detonate). Engine defaulted to block 0 (6-30 + 35% AP passive on-hit) → scored W at ~7% of reality; **live A/B 18→240 raw (13.3×)**. Pattern D resource-state (operator fully self-controls stacking; precedent Twitch E 6-stack / Renekton full Fury). Chose block 2 over block 4 (1.5× block 2) because block 4 entangles Varus R amp — W scores R-independent. Varus → `{Q:1, W:2}`. ENGINE 0.96→0.97; 6 pin bumps + `test_block_index_overrides` Varus shape-pin + `test_post_parser_sweep_s225.py` (9 tests, incl. the 3×-mechanic proof). DS 2104→**2113**; wider RC **1107**; DS restarted → 0.97.0.

## Don't-redo / blockers

- **Fiddlesticks Q is correctly scored — do NOT add an entry.** s224's current-HP parse fix already made its engine-default block 0 (% current HP max'd with the Minimum floor) the right single-Q value. Its "Increased" block (2×) is a fear-sequence target-state condition → conditional-schema-lift bucket, not a clean unconditional commit.
- **Both block_index scan spaces are now exhausted** (3 iterations): uncovered champions (s223, 0 found) + unmapped keys on covered champs (s224 Bel'Veth R, s225 Varus W — both follow-ups now closed). Don't re-run these scans expecting yield. The conditional-target-state schema lift is the next frontier but is architectural — flag for operator, don't ship autonomously.
- The two migration scripts + 2 scanners are durable artifacts; reuse on patch re-extracts, don't refactor old ones.

## NEXT (self-continuing loop)

Block_index pure-data work is done. Iteration 4 options: (a) audit the **form_index / combo_sequence / max_priority** registries for the same class of parser/coverage gaps the block_index sweeps found (these registries got far less scrutiny than block_index's 25+ batches); (b) DS calibration if rewind data has refreshed; (c) flag the conditional-target-state schema lift for operator. s220 aggregator G Post-Game-Review reframe remains the big pending UI item.

---

# s224 wrap — 2026-05-16 (DS Phase 5.9.24: unmapped-key pass — Bel'Veth R + _UNIT_TO_FIELD variant family)

**Operator instruction:** same self-paced loop ("continue ds work in parallel for the next hour self continue — maximum effort"). This is **iteration 2** (s223 was iteration 1, same session-day).

## What happened — worked the space orthogonal to s223's saturation finding

s223 proved the *uncovered-champion* block_index space saturated. s224 worked the other axis: ability KEYS on already-covered champions not yet in the registry. Built `tools/ds_unmapped_key_prefilter.py` (runs the s223 ground-truth A/B over every unmapped key of all 125 covered champs, full-HP + 40%-HP passes) → tight **7-item shortlist**. 2 were documented skips (Corki R = s194 every-4th-missile; DrMundo Q = s203 conditional-higher-vs-full-HP), 3 were false flags on already-mapped siblings. Two real findings:

## Shipped (committing now)

1. **`Belveth: {R: 1}`** — block 1 "True Damage" (150-250 + 100% AP + 25% missing-HP) is the canonical Endless-Banquet recast nuke; engine defaulted to block 0 ("Bonus True Damage" 6-10), live A/B **8→450 raw (56×)**. This **corrects s223's over-conservative "Bel'Veth R = no entry, already parsed" call** — field-parsed ≠ engine-block-selected (engine always defaults to block 0; an explicit entry is needed to select block 1). The s223 test `test_kayle_belveth_R_remain_unmapped` was rewritten → `test_kayle_unmapped_belveth_R_added_s224` (s223→s224 evolution guard). Bel'Veth → `{E:2, R:1}`.
2. **`_UNIT_TO_FIELD` text-drift family (s223-sibling)** — the pre-filter exposed 8 missing Meraki health-unit variants: double-space `"%  of target's current health"`, `"the target's"` maximum/missing forms (single+double space), caster-max pronoun/name forms (`"% of his/her maximum health"`, `"% of Braum's/Zac's maximum health"`). Added; `tools/migrate_abilities_unit_variants_s224.py` (same audit-gated zero-re-fetch contract as s223, reuses its `_promote`/`_recompute_parse_status`, idempotent) promoted **exactly 32 mods across 13 champs** (Ambessa Q · Braum Q · Briar W · Fiddlesticks Q · Gnar E · Gwen Q·R · Maokai Q · Sejuani W · Skarner E · TahmKench R · Trundle R · Varus W · Zac Q) whose %HP component was dropped. **Trundle R + Fiddlesticks Q evaluated 0 entirely pre-s224** (live A/B Trundle R 0→500, Fiddle Q 0→72). Skipped non-clean: TahmKench Q / Pantheon W `% AP per 100 bonus health` (hybrid), AurelionSol Q malformed Stardust string.

ENGINE 0.95.0→0.96.0; 5 pin bumps + `test_block_index_overrides` Belveth shape-pin update + `test_unit_variants_s224.py` (18 tests). DS suite 2086→**2104**; wider RC **1107**; DS server restarted → `/health` 0.96.0.

## Don't-redo / blockers

- **Don't `--force` re-extract** to apply parser fixes — Meraki `latest` is mutable (patch-bump + churn risk). The two migration scripts (`migrate_abilities_nested_hp_s223.py`, `migrate_abilities_unit_variants_s224.py`) are **historical artifacts** like DB migrations — don't refactor old ones; write a new dated one per parser change. All idempotent + hard audit-gated.
- **Varus W is now a FUTURE block_index candidate** — s224 parsed its Blight-stack maxHP (blocks 1-4) but the engine defaults Varus W to block 0 (18-dmg passive on-hit). A `Varus: {W: <blight-block>}` entry would surface the detonation — but pick the right block (per-stack vs max-stack vs the Q/R-detonation interaction) carefully; this is iteration-3+ material.
- s224's `test_target_max_hp_textdrift_promoted` etc. pin the live snapshot — if the snapshot is ever cleanly re-extracted (new patch), these stay green because the fixed `_UNIT_TO_FIELD` produces the same typed fields.

## NEXT (self-continuing loop)

Unmapped-key space near-exhausted (only Bel'Veth R was a clean find across 125 champs). Iteration 3 options: (a) Varus W block_index entry (data now parsed); (b) audit the *form_index* / *combo_sequence* registries for similar gaps; (c) the conditional-target-state schema lift (architectural — flag for operator, don't ship autonomously). s220 aggregator G Post-Game-Review reframe remains the big pending UI item.
