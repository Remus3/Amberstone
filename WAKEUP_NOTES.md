# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s227 wrap — 2026-05-16 (DS Phase 5.9.27: max_priority audit + combo_sequence assessment)

**Operator instruction:** same self-paced loop. **Iteration 5** (s223-227 all same session-day; ENGINE 0.94→0.99).

## What happened — the last two override registries; key methodology finding

block_index (s223-225) + form_index (s226) coverage swept. Iteration 5 applied the same pre-filter+A/B method to the final two: max_priority + combo_sequence. **Critical finding: these are play-pattern registries, NOT numeric-sweepable.** `tools/ds_max_priority_prefilter.py` flagged 59 champions where some non-QWE order numerically beats default at lvl 11 — but the numeric optimum ≠ real in-game max order (it flags **Azir W-first**, contradicting the universal Azir Q-max; Ziggs/Ryze/Taliyah numerically reorder but really max Q which default already does). Blindly shipping numeric optima would degrade rankings. So I filtered to ds.ability/ds.burst-archetype champs AND cross-checked established meta — only **3 clean, universally-known non-default orders** the registry genuinely missed.

## Shipped (committing now)

- **`Brand` ["W","E","Q"]** — Pillar of Flame is Brand's primary damage + waveclear; W-max-first has been THE Brand order for years. The original s185 _meta WRONGLY listed Brand as a "default Q-first is fine" example — **corrected this session**. Live A/B **+18.7%** (default left W at rank 2; W-first → rank 4).
- **`Talon` ["W","Q","E"]** — Rake (W) is Talon's canonical max-first (waveclear+poke+damage). A/B **+12.0%**.
- **`Fiddlesticks` ["W","E","Q"]** — Bountiful Harvest (W) drain is the standard jungle max. A/B **+16.4%**.

**combo_sequence assessed → ADEQUATE, no adds** (valid negative result): genuinely-unmapped assassin-archetype champs are just Shaco/Ekko (Fizz+Katarina ARE curated in the 15) and neither has the reset/shadow/chain mechanic the default `Q-W-E-AA-R-AA` misses — the registry's stated purpose is fully covered.

max_priority 12→**15 champs**. ENGINE 0.98→0.99; 8 pin bumps + `test_max_priority_sweep_s227.py` (13 tests incl. the Azir over-flag guard + combo-adequacy negative-result guard). DS 2123→**2136**; wider RC **1107**; DS restarted → 0.99.0.

## Don't-redo / blockers

- **max_priority + combo_sequence are play-pattern (meta-curated) registries — do NOT numeric-sweep them.** The pre-filter over-flags by ~20×; its level-11 optimum is not the real max order. Future additions need real-meta/operator knowledge per champion. Pinned by `test_max_priority_sweep_s227.test_over_flag_finding_azir_not_shipped`.
- **All 4 override registries (block_index / form_index / max_priority / combo_sequence) are now swept** across 5 iterations (s223-227). Pure-data registry-coverage DS work is **exhausted**. Don't re-run any of the 4 pre-filters expecting yield.
- The remaining DS frontier is the **conditional-target-state schema lift** (`block_index: int|list|dict`) — it's the common blocker for every deferred case (Heimer R-upgraded W/E, Fiddle fear-state, Skarner boulder, LeBlanc Mimic, Zoe/Lux/DrMundo-E target-state). It's **architectural** — flag for operator sign-off, do NOT ship autonomously.

## NEXT (self-continuing loop)

Pure-data registry sweeps are done (5 iterations, ENGINE 0.94→0.99, ~30 high-value correctness fixes shipped). Iteration 6+ has no obvious autonomous pure-data DS work left that meets the rigor bar. Options: (a) **flag the conditional-target-state schema lift for the operator** (the now-clearly-dominant next DS investment, but architectural — needs sign-off); (b) a calibration/data-quality pass if rewind data refreshed; (c) consider the autonomous DS loop complete for this session and surface the summary. Recommend (a)+(c): the high-ROI autonomous vein is mined out; further block_index/registry work needs the schema lift which wants operator input. s220 aggregator G Post-Game-Review reframe remains the big pending UI item.

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
