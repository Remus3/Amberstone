# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

---

# s223 wrap — 2026-05-16 (DS Phase 5.9.23: nested %HP parser fix + provable block_index saturation)

**Operator instruction:** "continue ds work in parallel for the next hour self continue — opus 4.7 1m maximum effort". Self-paced loop; this is iteration 1.

## What happened — parallel batch ran, found the registry is saturated, pivoted to the real debt

Applied the **parallel-batch-agents** pattern: built `tools/ds_block_scanner.py` (filtered-index ground-truth A/B helper — verified against Aatrox's documented s197/s199 multipliers) then spawned **5 parallel research agents** over all **47 not-yet-covered champions** (alphabetical slices). Every agent independently returned **zero** block_index proposals. Cross-checked by an independent enumeration: only 20 multi-damage-block (key,form) pairs exist among the 47, every one a documented skip (single-block / block-0-already-single-target-max / nested-parser / malformed-Meraki / card-choice / turret-pet). **The s191→s217 single-int/list `block_index` registry is provably saturated** — future growth needs the conditional-target-state schema lift or upstream Meraki fixes, not more uncovered-champion scanning. This is a real, valuable negative result (closes a 12-session line of work).

**Pivot** (don't ship an empty batch): tackled the longest-deferred DS debt instead — the s199→s217 "nested missing-HP parser bucket". Root cause: Meraki encodes %-target-health scalings behind nested conditional `(+ ...)` parentheticals (Kindred E `"% (+ 0.5% per Mark) of target's missing health"`, K'Sante W doubly-nested per-resist, Kindred E block1 recursively-nested) that `_normalize_modifiers` dropped into `unparsed_modifiers` → the entire %HP damage component was silently uncounted since Phase 4a.

## Shipped (uncommitted at time of writing — committing now)

- **`tools/daemon_slayer_abilities_extract._canonicalize_unit()`** — strips `(+ ...)` groups innermost-first (regex loop, handles arbitrary nesting). Purely additive: no-op for units without `(+`, so recognized units are byte-identical (raw-match-wins guard). Wired as a fallback after the raw `_UNIT_TO_FIELD` lookup.
- **`tools/migrate_abilities_nested_hp_s223.py`** — deterministic **zero-re-fetch** in-place migration (re-parses only `unparsed_modifiers`, which preserve original `{values,units}`). Imports the extractor's own helpers so logic == a future clean re-extract. **Hard audit gate**: aborts without writing unless it touches exactly the 22 audited mods across the 10 expected champions (drift = Meraki changed). Promoted 22 mods / 10 champs (Amumu W · Cho'Gath E×2 · Elise Q×2 both forms · Evelynn E×2 · K'Sante W×4 · Kindred W+E×2 · Kled W · Sett Q×2 · Shen Q×4 · Zac W). Live A/B (vs 2000 HP): Cho'Gath E +250%, Zac W +200%, K'Sante W +152%, Amumu W +300%, Sett Q +40% raw.
- **`Kindred: {E: 1}`** registry entry — enhanced-execute (7.5% missing-HP vs block 0's 5%). Monotone ≥ block 0; exact no-op at full HP (engine default `target_current_hp_pct=1.0`); +21% at 40% HP. Registry 124→125 champs.
- **`tools/ds_block_scanner.py`** (kept — reusable for any future scan/audit).
- ENGINE_VERSION 0.94.0→0.95.0; 4 pin bumps. **`agents/daemon_slayer/tests/test_nested_hp_parser_s223.py`** (26 tests: canonicalizer / `_normalize_modifiers` integration / live-snapshot migration correctness / Kindred E A/B monotone+no-op / saturation guards). DS suite 2060→**2086**; wider RC **1107**; DS server restarted (pid was 16472) → `/health` 0.95.0.

## Don't-redo / blockers

- **Do NOT re-scan uncovered champions for block_index** — provably saturated (the registry `_meta.description` Phase 5.9.23 note + `test_nested_hp_parser_s223.SaturationAndBackwardCompatTests` pin this). Next block_index work is the **conditional-target-state schema lift** (`block_index: int | list[int] | dict[str,int]`) — needs operator schema sign-off, candidates: Lux Illumination, DrMundo E missing-HP, Renekton Q full Fury, Zed shadow-Q, TwistedFate card-choice.
- **Do NOT re-run the extractor (`--force`)** to apply the parser fix — it hits Meraki's mutable `latest` and would risk a patch bump + smear unrelated churn. The migration is the deterministic path; it's idempotent (re-running finds 0 to promote).
- Kayle E / Bel'Veth R are **NOT** parser-gap champions — their `target_missing_hp_pct` was already parsed pre-s223 (only second-order `% per 100 AP` amps stay unparsed). The s217 hand-off mischaracterized them. No entry warranted; Bel'Veth keeps only its prior `{E:2}`.
- DS server :8893 is HTTP not HTTPS and NOT supervisor-watched — restart via `taskkill /F /PID` (use the **PowerShell tool**, Git-Bash mangles `/F`) + `Start-Process pythonw tools\start_daemon_slayer.py`.

## NEXT (self-continuing loop)

Conditional-target-state schema lift is the next DS frontier but is an architectural change wanting operator sign-off — flag it rather than ship autonomously. Subsequent loop iterations: audit covered champions for *additional* uncovered KEYS (distinct from the saturated new-champion space), or DS calibration once rewind data refreshes. s220 aggregator G Post-Game-Review reframe remains the big pending UI item.
