# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s228 wrap — 2026-05-16 (DS Phase 5.9.28: conditional-target-state block_index schema lift — Part 1)

**Operator instruction:** "continue DS". Surfaced via AskUserQuestion that pure-data registry work is **exhausted** (s223-227, 5 iterations, all 4 override registries swept) and the only remaining DS vein is the conditional-target-state schema lift — flagged across the s225/s226/s227 hand-offs as architectural + needing sign-off. **Operator chose option B** (multi-session: schema + live target-state plumbing). This commit = **Part 1**.

## What happened — the schema lift, phased exactly like s207

Part 1 scope = the schema-lift foundation (the s207 `int→int|list[int]` shape: land schema+validator+resolver+flagship seeds; bulk seeding + B-2 live plumbing are follow-ups). `block_index` value widens `int | list[int]` → ALSO `dict[str, int|list[int]]`. `"default"` (REQUIRED) = the operator-commits/canonical-amped branch (the ranking assumption — s191 model); other keys = positive live-target-state descriptors selecting a *downgrade* (never more optimistic). Closed vocab `_BLOCK_INDEX_CONDITIONS = {target_full_hp, target_no_cc}` (mirrors `_BLOCK_STRATEGIES`); an unknown key **raises**. **Part-1 resolver: `_select_blocks` resolves any conditional dict to its `"default"` branch UNCONDITIONALLY → byte-identical to the equivalent int/list entry (provably zero regression).** Live predicate evaluation = Part 2.

## Shipped (committed)

- Engine: `_normalize_block_index_value` dict branch (one-level-only guard; bool/str/nested/missing-default rejection) + `_BLOCK_INDEX_DEFAULT_KEY`/`_BLOCK_INDEX_CONDITIONS` + `_select_blocks` dict→default resolver + type-widening across `ability_dps.py`+`burst.py` (also fixed a latent s207 staleness where `block_index_resolved` was left `dict[str,int]`) + server `_parse_block_index` accepts well-formed conditional objects & **skips malformed defensively** (untrusted-body no-500/registry-fallback; the engine validator is the HARD enforcer for the trusted on-disk registry — two layers, same rule, different failure mode per trust level; do NOT unify them).
- **3 flagship seeds — all CONVERSIONS of already-shipped unconditional entries** so Part 1 is provably no-op vs s204/s204/s223: **Zoe E** `{default:2,target_no_cc:0}` (sleep 2×; live A/B reg 140.00==forced{E:2}, 2× block-0 70.00), **Evelynn Q** `{default:5,target_no_cc:0}` (charm triple-spike total; 345.00==forced{Q:5}, 7.7× block-0 45.00; sibling R:1 preserved), **Kindred E** `{default:1,target_full_hp:0}` (7.5%-vs-5% missing-HP execute; 80.00==forced{E:1}==forced{E:0} — honest full-HP no-op: the amp is missing-HP-gated, which IS Part-2's signal). Caller conditional dict via wire proven (`{default:0,target_no_cc:2}`→70.00==forced{E:0}).
- `_meta` description+rationale appended via surgical str.replace (no JSON reformat — file stays hand-formatted). Registry stays **125 champions** (3 in-place conversions, no new champs).
- Tests: new `test_conditional_block_index_s228.py` (~52: vocab/validator/resolver/seed-routing/Part-1-invariant/burst/`_parse_block_index`-unit/backward-compat/live-route); `test_block_index_overrides` shape-pins migrated for the 3 conversions (incl. `test_every_value_is_int_or_list_of_ints`→`_int_list_or_conditional`, mirrors how s207 widened it for int→list); 5 s223–s226 backward-compat pins updated to assert the new shape **+ Part-1 equivalence** (the s223 KindredEEntryTests class's 4 semantic-guarantee tests pass UNCHANGED — strong proof the conversion preserves s223's guarantees); 9 ENGINE pin bumps. ENGINE **0.99.0→1.0.0**. DS suite 2136→**2188**; wider RC **1107**; ruff+py_compile clean; DS restarted (taskkill pid 13452 → pythonw relaunch; not supervisor-watched) → `/health` **1.0.0**.

## Don't-redo / blockers

- **Part 1 is INTENTIONALLY a zero-numeric-change schema lift.** The 3 seeds resolve to `"default"` == their old int — anyone seeing "no A/B delta" should read THIS: the payoff is Part 2 (live state makes downgrade branches fire). Do not "fix" the no-op.
- **DrMundo E is NOT a target-state conditional** — verified its Min/Max blocks scale on `caster_bonus_hp_pct` (Dr. Mundo's OWN missing HP), not target HP. The recurring "DrMundo E missing-HP" carry-forward (s203/s204/etc. _meta) mischaracterized it. A caster-state conditional needs a vocab extension (e.g. `caster_low_hp`) — **flag for operator, out of the signed-off target-state scope**.
- Closed vocab is deliberately minimal — only the 2 conditions the seeds need (s227's "don't over-build / play-pattern registries aren't auto-sweepable" lesson). Adding a condition = add to `_BLOCK_INDEX_CONDITIONS` **and** wire its Part-2 predicate, together.
- Don't `--force` re-extract Meraki to "apply" anything (mutable `latest`); the registry edits are pure JSON.

## NEXT (operator option B continues)

**B-2 — live target-state plumbing (the next session):** thread real liveclient target HP%/CC into the ranking call so conditional dicts resolve against actual game state instead of always `"default"`. Touches `coach_integration/archetype_dispatch.py` + `dashboard/_state_builder.py` + `/api/ds-preview` (`dashboard/routes_state.py`) + `core/daemon_slayer_client.py` + the DS server routes (`agents/daemon_slayer/server.py`). Design: add a predicate layer (gated on a NEW optional live-state arg) above/inside `_select_blocks`; `AbilityContext` already carries `target_current_hp_pct` (→ `target_full_hp` predicate, clean liveclient enemy HP signal). `target_no_cc` has NO clean liveclient signal → it stays commits-default (resolves to `"default"`) until a CC-state source exists — honest scoping, document at ship. **HARD invariant:** Part-1 callers (no live-state arg) MUST keep resolving to `"default"` — `test_conditional_block_index_s228.AbilityDpsPart1InvariantTests` + `SelectBlocksConditionalTests` pin this; keep green.
**Pure-data conditional seed-expansion (fast, interleavable, the s207→s215/s217 pattern):** the deferred bucket on the now-stable schema — Lux Illumination, Aatrox W chain-landed, Fiddle Q fear-state, more sleep/charm/mark amps. Each entry needs Meraki block verification (the rigor bar — do NOT trust ROADMAP recollection of block numbers). DrMundo E only after a caster-state vocab decision.
s220 aggregator G Post-Game-Review reframe remains the big pending UI item.

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
