# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s230 wrap — 2026-05-16 (DS Phase 5.9.30: conditional seed-expansion — Fiddle Q + Cassi E)

**Operator instruction:** "continue ds" (self-continuing loop). Continued the s229 NEXT bucket: pure-data conditional seed-expansion on the stable 2-term vocab. NO vocab change (s227 "don't over-build" — both entries reuse `target_no_setup`).

## What happened — rigor bar first, recollection rejected

The s229 NEXT list named Lux Illumination / Aatrox W / Fiddle Q / Cassi E. Verified every candidate against the live Meraki 16.10.1 `champion_abilities.json` (built `tools/ds_cond_inspect.py`, kept — reusable per-patch). **Lux CLOSED as a phantom carry-forward:** Lux P is `parse_status=no_damage` with zero damage_blocks; Q/E/R are each single-block — no discrete amped/un-amped pair anywhere in Lux's kit; it never met the discrete-pair rigor bar (the recurring "Lux Illumination" mention was recollection, not reality). **Aatrox W stays deferred:** "chain-landed" is a positional escaped/not-escaped condition, NOT an operator-applied target-state setup — fails the `target_no_setup` semantic. 2 clean entries shipped.

## Shipped (committed)

- **Fiddlesticks Q "Terrify" = `{"default": [2,3], "target_no_setup": [0,1]}`** — a NEW key (real correctness fix, NOT a no-op) AND the FIRST registry conditional whose branches are `list[int]` (combines the s207 sum-of-blocks list schema with the s228 conditional schema; ZERO engine change — `_normalize_block_index_value` already recursively normalizes each branch and only rejects a *nested* dict). Filtered damage blocks (raw[0]/raw[3] are duration, dropped by the `attribute_kind=='damage'` filter): fidx0 `target_current_hp_pct`[4..6], fidx1 base[40..120], fidx2 = EXACTLY 2.0× fidx0, fidx3 = EXACTLY 2.0× fidx1 — the textbook Terrify-double-vs-feared discrete pair. `default`=[2,3] (feared/amped sum — Fiddle's kit revolves around fear, operator-commits canonical), `target_no_setup`=[0,1] (un-amped vs not-yet-feared). Pre-s230 the engine scored Q at filtered-block-0 ONLY (un-amped %HP, missing the un-amped base AND the fear-amp). Live A/B :8893 (lvl11 80/30/2000): Q raw/cast **80→240 (+200%)**, Qdps 3.31→9.93, total_ability_dps 22.998→29.618; exact-2× check `registry 240 == 2.0 × no_setup 120` confirmed live.
- **Cassiopeia E "Twin Fang" int `1` → `{"default": 1, "target_no_setup": 0}`** — provable Part-1 no-op conversion (default==prior int 1, byte-identical). Twin Fang is enhanced vs a poisoned target (Cassi's own Q/W poison is the setup). **RESOLVES the s229 "Cassi E irregular 18-element Meraki array — defer until investigated" carry-forward:** the array is block 1's base scaling, rank-indexed by `_evaluate_block` exactly as since s191; the conditional conversion is orthogonal (Part-1 always resolves to default=1). Live A/B: registry raw 168 == forced E:1 == 168 (no-op match True); forced E:0 raw 100 (non-poisoned downgrade; load-bearing True).
- Registry stays **125 champions** (Fiddlesticks gains Q alongside R/W; Cassiopeia E converted in-place). `_meta` description+rationale appended via surgical str.replace (no JSON reformat). New `test_conditional_block_index_s230.py` (24 tests). 10 ENGINE pin bumps. **Cross-registry stale-pin migrations:** 4 `test_block_index_overrides` Cassi-E shape pins → conditional shape; s228/s229 `test_cassiopeia_E_still_plain_int` → s230 evolution guards (shape + Part-1 numeric equivalence); s223 byte-stable pin + s225 "swept keys not added" + s207 sum_of_blocks int-exemplar all migrated. ENGINE **1.1.0→1.2.0**. DS suite 2210→**2232**; wider RC **1107**; ruff+py_compile clean; DS restarted (taskkill 14372 → pythonw relaunch, not supervisor-watched) → `/health` **1.2.0**.

## Don't-redo / blockers

- **`test_max_priority_sweep_s227.test_fiddlesticks_w_first_beats_default` was MIGRATED, not "fixed".** s230's correct Fiddle Q boost (Q was under-counted at s227) flips the lvl-11 numeric A/B so Q-first now numerically beats W-first (ratio ~0.85, no longer >1.10). This is **precisely the s227 lesson** — max_priority is meta-curated, NOT numeric-sweepable. The W-E-Q registry entry is still real-meta-correct (Bountiful Harvest drain IS Fiddle's jungle max). The test now guards the *decision* (registry entry + resolution), not the now-stale inequality. **Do NOT revert the Fiddle max_priority entry or the s230 Q block_index entry to "restore" the old numeric margin** — both are correct; the margin was an artifact of the pre-s230 Q under-count.
- **Lux is a closed phantom — do not re-add it to the NEXT list.** No discrete pair exists in its kit (verified, not recalled).
- Fiddle Q is the first list-valued conditional; the schema already supported it (no engine change needed). Future list-branch conditionals are pure data.
- Conversions are intentionally zero-numeric-change (Part-1 resolves to `"default"`); don't "fix" the no-op.

## NEXT (self-continuing loop)

Remaining clean conditional candidates need fresh Meraki verification each (rigor bar — the s229/s230 lesson: ROADMAP/_meta recollection mis-names mechanics ~half the time). Likely-clean unexamined: more debuff-state-family amps (mark/charm/sleep beyond the shipped set). DrMundo E remains blocked on a `caster_low_hp` vocab decision (it's caster-missing-HP, NOT target — flag for operator before any vocab add). Aatrox W needs the positional-condition question answered architecturally, not pure-data. s220 aggregator G Post-Game-Review reframe remains the big pending UI item.

---

# s229 wrap — 2026-05-16 (DS Phase 5.9.29: conditional seed-expansion + vocab generalization)

**Operator instruction:** "continue" (continuing s228's option B). First surfaced — via AskUserQuestion — that the signed-off literal "B-2" (thread per-tick liveclient HP/CC into the ranking call) is a **mis-feature** for the only DS surface that exists (item-build recommendation): per-tick enemy HP would flicker build recs, and the operator-commits default (Part 1) is the *correct* strategic model — the schema's value is already delivered. **Operator chose "pivot → pure-data conditional seed-expansion"** (the proven s207→s215/s217 cadence).

## What happened

`target_current_hp_pct` is already plumbed end-to-end (only `_serve_ds_preview_post` doesn't supply it); `target_no_cc` has NO liveclient signal. So literal B-2 is shelved as a mis-feature (it would need a separate *live-advisory* product surface, not DS-engine work). Continued option B's spirit with a pure-data batch on the s228 schema.

## Shipped (committed)

- **Vocab generalized `target_no_cc` → `target_no_setup`.** s228 scoped the non-HP condition to its CC-family flagships (sleep/charm); the expansion candidates (Anivia *chill*, Brand *ablaze*) share the identical modeling semantic regardless of debuff type — "operator's own ability applied an amp-enabling target state; default = committed/canonical amped block, condition key = un-amped downgrade." 5+ concrete uses → the honest general term (vocab stays **2**: `{target_full_hp, target_no_setup}`, NOT over-built — s227's lesson was about numeric sweeps, not naming a 5-instance conditional). Engine validator now **rejects the old key** (stale `target_no_cc` fails loudly). s228's Zoe E + Evelynn Q migrated.
- **3 conversions of already-shipped unconditional entries** — all provably Part-1 no-op (`"default"` == prior int), verified per-rank vs Meraki 16.10.1, live-A/B confirmed on :8893: **Morgana W** `{default:3,target_full_hp:2}` (block 3 = exactly **2.7×** block 2; the <50%-max-HP amp — s195's "vs rooted" framing was imprecise, the Q-root is the operator's *setup*; reg 459.00==forced{W:3}), **Anivia E** `{default:1,target_no_setup:0}` (block 1 = **2.0×** block 0 vs Chilled; reg 300.00==forced{E:1}), **Brand W** `{default:1,target_no_setup:0}` (block 1 = **1.25×** block 0 vs ablaze; reg 318.75==forced{W:1}). Migrations live-verified (Zoe E 140.00, Evelynn Q 345.00; caller-cond Anivia E `{default:0,target_no_setup:2}`→150.00==forced{E:0}).
- Registry stays **125 champions** (in-place). `_meta` description+rationale appended (surgical str.replace). New `test_conditional_block_index_s229.py` (~30 tests) + global `target_no_cc`→`target_no_setup` rename (33 refs / 4 files) + 12 `test_block_index_overrides` stale pins migrated to conditional-shape + Part-1-equivalence (the s228 iterative-suite-pinpoint method) + 10 ENGINE pin bumps. ENGINE **1.0.0→1.1.0**. DS suite 2188→**2210**; wider RC **1107**; ruff+py_compile clean; DS restarted → `/health` **1.1.0**.

## Don't-redo / blockers

- **Conversions are intentionally zero-numeric-change** (Part-1 resolves to `"default"` == prior int). The amp ratios (2.7× / 2.0× / 1.25×) only manifest when a future *live-advisory* surface consumes the downgrade branch — NOT in item ranking. Don't "fix" the no-op.
- **The discrete-pair requirement** for a conditional conversion: the ability must have TWO same-shape damage blocks (amped vs un-amped). Bel'Veth R was rejected for exactly this — its 25% missing-HP is *continuous within* one block (handled by `_SCALING_TARGETS`), not a discrete pair. Continuous in-block %HP scaling is NOT a conditional candidate.
- **Veigar R is the canonical stable-int test fixture** (`test_sum_of_blocks` + `test_block_index_overrides` GetBlockIndexFor/ResolveBlockIndex/known_champion_overrides). It IS a clean target_full_hp execute (DMG1=2.0×DMG0) but converting it cascades a fixture-repoint — defer until a fixture migration is independently warranted, or pick a non-fixture execute.
- **DrMundo E is caster-missing-HP, not target** (its Min/Max scale on `caster_bonus_hp_pct`) — needs a `caster_low_hp` vocab term, flag for operator. The recurring "DrMundo E missing-HP" carry-forward keeps mischaracterizing this.
- Literal B-2 (per-tick HP→ranking) is **shelved as a mis-feature**; don't re-attempt it as DS-engine plumbing.

## NEXT (self-continuing loop)

More pure-data conditional seed-expansion on the stable 2-term vocab: Lux Illumination, Aatrox W chain-landed (resolve the positional-vs-CC question first), Fiddle Q fear-state, the debuff-state family (Cassi E poison once its irregular 18-element Meraki base array is understood). Each entry needs Meraki block verification (rigor bar — verify the discrete-pair requirement; do NOT trust ROADMAP/_meta block-number recollection). s220 aggregator G Post-Game-Review reframe remains the big pending UI item.

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
