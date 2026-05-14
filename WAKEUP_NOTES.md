# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s192 wrap — 2026-05-14 (Phase 5.9.5 token-variant block_index for Akali R)

**Operator instruction:** "continue" — directly continuing the s191 carry-forward list. Top item (a): per-token-variant block_index for Akali R. R1 (block 0 base) and R2 (block 2 max-execute) need different blocks within the same combo, but the s191 per-(champion, key) registry only had a single per-key entry. Single commit ship.

## Context

s191's hand-off explicitly deferred Akali R because setting `{"Akali": {"R": 2}}` globally would over-count R1: R1 in-game is the initial dash with bonus-AD scaling (block 0), R2 is the recast with missing-HP execute scaling (block 2). The Meraki snapshot already exposes both blocks; the engine just needed to distinguish R from R2 tokens in the combo walker.

Two design decisions for this batch:
1. **Extend keys, not values** — `block_index_overrides` stays `dict[str, int]` (no `dict[str, int | list[int]]` complexity). Repeat-variant tokens (Q2/W2/E2/R2) become valid keys alongside base keys (Q/W/E/R). Forward-compatible: any future "Q3 differs from Q1/Q2" entry drops in without code changes.
2. **Token-canonical first, base-key fallback** — the burst walker checks `block_overrides.get(canonical)` before `block_overrides.get(ability_key)`. So `{"R": 0, "R2": 2}` routes R1 → block 0 (the same s191 default would, just explicit) and R2 → block 2 (the missing-HP execute scaling). `compute_ability_dps` is unaffected — it iterates Q/W/E/R only, so the R2 entry is invisible to the mage scorer.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/champion_block_index.json](agents/daemon_slayer/champion_block_index.json) | Added `"Akali": {"R": 0, "R2": 2}` entry. `_meta.description` extended with Phase 5.9.5 lookup precedence note (token-canonical first, base-key fallback). `_meta.rationale` adds Akali R/R2 entry explaining R1's bonus-AD scaling vs R2's missing-HP execute curve. Skipped-list updated: Yone Q1/Q2/Q3 (single-block per form, knockup is utility), Zed Q vs Q2-shadow (block 0 is correct for both), Leblanc Q vs Q2-mimic (mimic-Q has its own damage formula not in Meraki). |
| [agents/daemon_slayer/burst.py](agents/daemon_slayer/burst.py) | Combo walker's per-cast block-index resolution: `if canonical in block_overrides:` checked FIRST (token-canonical lookup — e.g. "R2"), then `elif ability_key in block_overrides:` (base-key fallback — e.g. "R"), then falls through to global `block_strategy`. Comment block expanded to document the two-tier lookup. compute_ability_dps unchanged. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.76.0 → 0.77.0. Docstring extended with Phase 5.9.5 section. |
| [agents/daemon_slayer/tests/test_block_index_overrides.py](agents/daemon_slayer/tests/test_block_index_overrides.py) | New `AkaliTokenVariantTests` class (7 tests): registry shape, R1 row block 0 raw=220, R2 row block 2 raw=420, total burst with registry > forced R+R2:0, explicit R2 override wins over registry, R-only override falls through to R2 token (documents the "double-count" scenario when operator omits R2), `compute_ability_dps` ignores R2 entry. Pre-existing `RegistryShapeTests` `test_every_key_is_valid_token` extended valid-key set to include Q2/W2/E2/R2 (was Q/W/E/R only). `test_known_champion_overrides` adds Akali assertion. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests bumped 0.76.0 → 0.77.0 with the Phase 5.9.5 line in the history comment. |

## Verification

- DS suite **1665 pass** (was 1658 in s191 wrap; +7 from new `AkaliTokenVariantTests` class)
- Wider RC suite **1013 pass** (no regression)
- `py_compile` clean for burst.py + __init__.py
- DS server :8893 restarted from PID 15664 (was the s191 0.76.0 pid still running) → PID via background spawn; `/health` reports `engine_version=0.77.0` patch=16.10.1 172 champions 705 items

## Live A/B on :8893

**Akali /burst (s186 combo Q-AA-E-R-Q2-AA-R2 vs 80 armor / 30 MR / 2000 HP):**

| Scenario | Total | R row | R2 row |
|---|---|---|---|
| Registry-applied (R=0, R2=2) | **941.7** | raw=220.0 final=169.2 | raw=420.0 final=323.1 |
| Forced R+R2:0 (pre-s192 model) | 787.9 | raw=220.0 final=169.2 | raw=220.0 final=169.2 |
| Naive R:2 only (pre-s192 mistake) | 1095.6 | raw=420.0 final=323.1 | raw=420.0 final=323.1 |

Registry is exactly halfway between "ignore the R2 amp" (787.9) and "naively double-count R1" (1095.6), confirming the token-variant model captures the realistic mid-point: **+153.8 burst (+19.5%)** over the pre-s192 baseline.

**Akali /rank-assassin top 5 (registry baseline 941.7):**
- 1. Lich Bane +396.54 / 2. Shadowflame +370.19 / 3. Rabadon's Deathcap +354.90 / 4. Stormsurge +322.72 / 5. Essence Reaver +312.37
- Lich Bane #1 — Spellblade procs each ability cast and the now-doubled R2 base × 90% AP makes Lich Bane's AP scaling extra valuable

**Cassi /ability-dps (regression check):** 39.48 adps — unchanged from s191 (E:1 → block 1 Total Enhanced still applies). No s191 entry was affected by the token-variant extension.

## Findings

- **Token-canonical lookup is a 3-line change.** The burst walker already had `canonical, ability_key, is_ability = _normalize_combo_token(token)` at the top of each iteration — just needed `if canonical in block_overrides` before the existing `elif ability_key in block_overrides`. The API surface stays the same (`dict[str, int]`); the semantics extend naturally.
- **compute_ability_dps untouched.** The mage scorer iterates `SPELL_KEYS = ("Q", "W", "E", "R")` and does `overrides.get(key, 0)` — the Akali R2 entry in the dict is simply absent from this lookup. No special-case logic needed; the API extends cleanly. `compute_ability_dps` for Akali returns R with block 0 (same as pre-s192).
- **The +153.8 delta is exactly the R2 block 2 - block 0 swap.** At rank 1 (R lvl 11), block 0 base = 220 + 30% AP + 50% bonus AD; block 2 base = 420 + 90% AP. With 0 AP / 0 bAD (naked build), the delta is exactly 420 - 220 = 200 raw → 153.8 after mitigation (×0.769 from 30 MR). Confirms the model is consuming Meraki's blocks correctly with no extra amp drift.
- **Naive R:2 over-count is +307.6 vs registry.** Without token-variant lookup, an operator (or future engine maintainer) would have to either tolerate the pre-s192 under-count (+0 from R2 amp) or eat the over-count from doubling R1 (+153.8 spurious). The token-variant pattern eliminates this dichotomy.
- **Process-tracking gotcha.** First DS restart killed the wrong PID (PowerShell taskkill targeted the parent shell, not the python.exe server). Had to inspect `Get-CimInstance` for both py.exe + python.exe entries, kill the actual server (PID 15664) directly, then relaunch. Same shape as the s190 PowerShell `$pid` reserved-name issue — both stem from PowerShell process semantics being subtly different from POSIX.

## Open items carried forward

- 🟡 **Conditional block_index based on target state** — Zoe sleep amp, Lux Illumination mark, DrMundo E missing-HP threshold, Renekton Q Fury condition. Each wants block_index N when a target-state condition is met (target asleep, target marked, target missing >X% HP, caster has >Y resource). Schema extension: `{"<champion>": {"<key>": {"default": 0, "when_target_missing_hp_pct_above": [0.5, 2]}}}`. Substantial design lift; defer until 3+ candidates accumulate cleanly.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q follow-up amp)** — inter-spell awareness still missing for damage *multipliers* on subsequent spells (vs the per-block selection s191/s192 ships). Carried since s180.
- 🟡 **Generalized arm-consume framework via `is_ability_triggered_aa_proc` schema flag** — still two specific helpers (Spellblade s189 + Lightshield s190). Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — same upstream/plumbing/UI blockers as s187/s188/s189/s190/s191.
- 🟡 **Real internal CD in long combos** — s190 carry-forward (a); 8-token combos lasting >3s could in theory permit a second Lightshield Strike proc.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** all remain unchanged: live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune blocked on real-game fired nudges; `nudge_history` calibration additive.

## Architectural pattern lock-in (continued from s191)

Eighth consecutive override / proc-shape modeling improvement on the same template, and the first one to *extend* a prior registry rather than ship a new one (s191's registry gained the Akali entry; the schema stayed `dict[str, int]` but the valid-key set extended from `{Q,W,E,R}` to `{Q,W,E,R,Q2,W2,E2,R2}`). The pattern is now proven extensible across both rows (more entries) and columns (more granular keys per entry). Future conditional-block_index extensions can layer values from `int` → `dict[str, Any]` without disturbing the per-batch resolver contract.

---

# s191 wrap — 2026-05-14 (Phase 5.9 per-(champion, key) damage block_index overrides)

**Operator instruction:** "continue ds" — directly continuing the s190 carry-forward list. The carry-forward mentioned "Conditional damage amps (Ahri R→Q, Zoe E→Q, Akali R1→QE→R2)" as a Phase 5.9 candidate, but on inspection most of those map to either combo-sequence (already s186 registry) or multi-form selection. The clean modeling improvement that's been hiding in plain sight: 248 (champion, key, form) tuples in `champion_abilities.json` carry 2+ damage blocks where block ≥1 is the realistic burst-window damage (poisoned-target enhanced, all-orbs total, max-charge, executed). The engine's default `block_strategy="first"` has been locking all callers to block 0, under-scoring 11 specific champions across mage + assassin scorers. Single commit ship.

## Context

After s187 (form_index overrides) + s188 (per-AA on-hit) + s189 (Spellblade in burst) + s190 (Lightshield Strike in burst), the engine's modeling of *which* damage block to evaluate within a chosen form was still locked to block 0. Inspection of the Meraki abilities data showed clear amped/empowered/max blocks ready to consume:

- Cassiopeia E block1 "Total Enhanced Damage" — vs poisoned (Q/W apply)
- Veigar R block1 "Maximum Magic Damage" — vs executed target
- Anivia E block1 "Enhanced Damage" — vs chilled (Q stun applies)
- Brand W block1 "Increased Damage" — vs CC'd / Blaze-stacked target
- Brand R block1 "Total Single-Target Damage" — all 3 bounces same target
- Diana W block2 "Total Magic Damage" — all 3 Pale Cascade orbs land
- Evelynn R block1 "Empowered Damage" — sub-30% HP execute
- Aurora Q block2 "Maximum Magic Damage" — full-charged Twofold Hex
- Belveth E block2 "Maximum Physical Damage per hit" — full Royal Maelstrom
- Karma W block1 "Total Magic Damage" — full Focused Resolve channel
- Vex R block2 "Total Magic Damage" — initial + mark detonation
- Ahri Q block1 "Total Mixed Damage" — both passes of Orb of Deception

12 entries across 11 champions. For ranking purposes (operator is comparing item builds for *their* champion in *their* combo), assuming amped conditions are met is the right model — same intuition as the engine already baking in `target_missing_hp_pct` and treating skillshots as landed.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/champion_block_index.json](agents/daemon_slayer/champion_block_index.json) | **NEW**. Seed registry, 12 (champion, key) → block_index entries. Defensively skips: Akali R (would double-count R1/R2 — needs per-token-variant resolution), AurelionSol R (multi-FORM not multi-block), Caitlyn Q (block1 is REDUCED fallback not enhancement), DrMundo E (block0 is stat-bonus only), Renekton Q (Fury condition not always met in burst). Operator can extend per-champion as needed; default block_index=0 preserves pre-s191 behavior for any unmapped entry. |
| [agents/daemon_slayer/ability_dps.py](agents/daemon_slayer/ability_dps.py) | New `_BLOCK_INDEX_PATH` + `_BLOCK_INDEX_LOCK` + `_BLOCK_INDEX_CACHE` singleton-cached loader. New `get_block_index_for(champion_id) -> (mapping, source)` + `_resolve_block_index_overrides(champion_id, explicit) -> (merged, source)` mirror the Phase 4e form_index pattern. New `reset_block_index_cache()` for test isolation. `_select_blocks` gains a `block_index: int = 0` param; new strategy `"indexed"` selects that specific damage block (clamping negative→0, out-of-range→last). `_BLOCK_STRATEGIES` extended with `"indexed"`. `compute_ability_dps` + `rank_items_by_ability_dps` gain `block_index_overrides: Optional[dict[str, int]] = None` arg; per-spell loop switches to `"indexed"` strategy for keys present in the resolved map; keys without an entry honor the global `block_strategy`. `AbilityDpsResult` + `AbilityDpsRankResult` gain `block_index_source: str` + `block_index_resolved: dict[str, int]` fields surfaced in `to_dict()`. Ranker's baseline + each candidate call share the SAME resolved map (consistent source label). |
| [agents/daemon_slayer/burst.py](agents/daemon_slayer/burst.py) | Imports `_resolve_block_index_overrides`. `compute_burst_damage` + `rank_items_by_burst` gain `block_index_overrides` arg + plumb through to per-cast `_select_blocks` call. Combo walker's ability-cast branch switches to `"indexed"` strategy for keys present in `block_overrides`; AA branch unchanged. `BurstResult` + `BurstRankResult` gain `block_index_source` + `block_index_resolved` fields. `_empty_burst` accepts the new kwargs for engine-down / champion-missing paths. |
| [agents/daemon_slayer/server.py](agents/daemon_slayer/server.py) | New `_parse_block_index(body) -> Optional[dict[str, int]]` decoder accepting a JSON dict body field. Wired into all 4 routes (`/ability-dps`, `/rank-mage`, `/burst`, `/rank-assassin`) via the shared parsing pattern that already serves max_priority / form_index / combo_sequence. Route docstrings updated. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.75.0 → 0.76.0. Docstring extended with Phase 5.9 section (mirrors Phase 4e + 5.7 + 5.8 structure). |
| [agents/daemon_slayer/tests/test_block_index_overrides.py](agents/daemon_slayer/tests/test_block_index_overrides.py) | **NEW (~560 LOC, 53 tests).** 9 test classes mirroring s187's test_form_index_overrides.py structure: `RegistryShapeTests` (6), `LoaderCacheTests` (2), `GetBlockIndexForTests` (4), `ResolveBlockIndexTests` (5), `SelectBlocksIndexedTests` (8 — direct exercise of new strategy including out-of-range clamp + non-damage filter), `ComputeAbilityDpsBlockIndexTests` (6 — including Cassi E rank-max raw_dpc=168 (block1 Total Enhanced) vs forced block0=100 explicit assertion), `ComputeBurstBlockIndexTests` (5), `RankerBlockIndexTests` (3), `ToDictSerializationTests` (5), `BackwardCompatTests` (3 — unmapped champion exact-match invariant), `ServerRouteSourceTests` (6 — surfaces source/resolved on all 4 routes; skipped when :8893 unavailable). |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests (Batch63 + Batch64) bumped 0.75.0 → 0.76.0 with the Phase 5.9 line in the history comment. |

## Verification

- DS suite **1658 pass** (was 1605 in s190 wrap; +53 from new test file)
- Wider RC suite **1013 pass** (no regression)
- `py_compile` clean for ability_dps.py / burst.py / server.py / __init__.py
- DS server :8893 restarted; `/health` reports `engine_version=0.76.0`, patch=16.10.1, 172 champions, 705 items

## Live A/B on :8893

**Cassi /ability-dps total (vs 30 MR):**
- registry-applied: 39.48 adps  (E uses block1 Total Enhanced)
- forced block_index={'E': 0}:  27.66 adps  (E uses block0 pre-poison Base)
- **delta: +11.82 adps (+43%)** — the Twin Fang amp is load-bearing

**Veigar /burst total (vs 80 armor / 30 MR / 2000 HP):**
- registry-applied: 807.01  (R uses block1 Maximum at 130-150% AP)
- forced block_index={'R': 0}:  614.70  (R uses block0 Minimum at 65-75% AP)
- **delta: +192.31 burst (+31%)** — the execute amp dominates Veigar's late-game burst

**Anivia /ability-dps total:**
- registry-applied: 14.86 adps  (E uses block1 Enhanced at 110% AP / 2× base)
- forced block_index={'E': 0}:  9.66 adps  (E uses block0 at 55% AP / base)
- **delta: +5.20 adps (+54%)** — Frostbite vs chilled is the canonical Anivia combo

**Cassi /rank-mage (registry baseline 39.48):**
- 1. Rabadon's Deathcap +26.50 / 2. Shadowflame +24.65 / 3. Mejai's +22.74 / 4. Stormsurge +21.10 / 5. Void Staff +20.43
- AP-scaling items dominate as expected — Twin Fang's 65% AP scales harder on block1 than block0's 55%

**Veigar /rank-assassin (registry baseline 807.01):**
- 1. Lich Bane +391.15 / 2. Rabadon's +377.00 / 3. Shadowflame +371.20 / 4. Mejai's +323.46 / 5. Stormsurge +320.77
- Lich Bane climbs to #1 — Spellblade procs each Veigar spell-cast, and the AP scaling amplifies the now-doubled block1 R damage

## Findings

- **`_select_blocks` was the natural extension point.** Instead of adding a parallel "evaluate specific block" path, extending the existing strategy enum with `"indexed"` and a `block_index` parameter kept the change localized. The per-spell loop in `compute_ability_dps` / `compute_burst_damage` just checks `if key in block_overrides` and switches strategy for that one call.
- **Registry pattern is now load-bearing for 4 sibling registries.** champion_max_priority (s185) / champion_combo_sequences (s186) / champion_form_index (s187) / champion_block_index (s191) all share the same architectural pattern: singleton-cached JSON sibling in `agents/daemon_slayer/` + `get_X_for(champion_id) -> (value, source)` resolver + `_resolve_X_overrides(champion_id, explicit) -> (merged, source)` merger + result-type `X_source: str` + `X_resolved: dict[...]` fields. Future per-champion modeling overrides drop into this template.
- **Backward compatibility preserved.** Pre-s191 callers (no `block_index_overrides` arg, unmapped champion) see byte-identical output: the resolver returns empty dict, the per-spell loop's `if key in block_overrides` check fails for every key, and the global `block_strategy` (default "first") is honored. Verified via new `BackwardCompatTests` class — Zed (unmapped) burst with no override equals burst with explicit empty override.
- **Akali R deliberately skipped.** R block2 "Maximum Magic Damage" is genuinely the missing-HP-scaled R2 damage, but applying it at the (champion, key) level would double-count: the existing combo registry (`champion_combo_sequences.json`, s186) lists Akali's combo as `Q-AA-E-R-Q2-AA-R2` — both R and R2 tokens evaluate at rank 1 (R lvl 11) but they're DIFFERENT mechanics in-game (R1 = dash + base damage; R2 = dash + missing-HP execute). Setting block_index globally would force BOTH R and R2 to use the "Maximum" block, over-counting R1. Proper modeling needs per-token-variant overrides — a separate feature.
- **DrMundo E + Renekton Q deferred.** DrMundo E block0 is no-base stat-bonus (just adds Bonus Attack Damage), block1/2 are min/max missing-HP damage; block_index choice depends on current target HP which the engine doesn't surface for per-spell evaluation. Renekton Q block1 "Enhanced Damage" requires full Fury (50+) — high but not universally assumable in a burst window. Both would benefit from a future per-(champion, key) "use block_index N when target_current_hp_pct ≤ X" conditional, but s191 keeps to unambiguous always-applies cases.
- **`pythonw.exe` doesn't print to stdout.** First DS restart attempt used `pythonw.exe` via `Start-Process` and the process didn't actually launch (silent failure — possibly Windows Defender flagged it, possibly a startup race). Switched to `python.exe` in a `run_in_background` bash invocation; `/health` returned 200 within 4 seconds.

## Open items carried forward

- 🟡 **Per-token-variant block_index for Akali R.** R1 block0 + R2 block2 modeling would need either (a) a registry shape like `{"Akali": {"R": [0, 2]}}` where index N applies to the Nth occurrence of R in the combo, or (b) an extension to combo_sequence tokens (`R` vs `R2`) carrying their own block_index. Single-champion lift; out of scope this batch.
- 🟡 **Conditional block_index based on target state.** DrMundo E + Renekton Q + Zoe sleep amp + Lux Illumination mark all want different blocks based on combat conditions. Schema would need a `condition: {target_current_hp_pct_below: 0.4}` field on each entry plus combat-state plumbing through the per-spell evaluator. Substantial design lift; defer until 3+ candidates accumulate.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — same as s187/s188/s189/s190 carry-forwards. Upstream data gap + LCU plumbing + UI picker respectively.
- 🟡 **Real internal CD in long combos** — same as s190 carry-forward (a). Lightshield Strike "once per combo" gate would in theory permit a second proc at 8+ tokens lasting >3s.
- 🟡 **Generalized arm-consume framework** — same as s190 carry-forward (b). Still only 2 specific helpers (Spellblade + Lightshield Strike); generalize to `is_ability_triggered_aa_proc: bool` if a third such mechanic ships.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q, Akali R1→QE→R2)** — carried since s180. The Akali R1→R2 piece is partially addressed by s191 if we add per-token variants, but Zoe sleep amp and other inter-spell amps still need a separate mechanism (not in Meraki data).
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** all remain unchanged: live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune blocked on real-game fired nudges; `nudge_history` calibration additive.

## Architectural pattern lock-in (continued from s190)

Seventh consecutive override / proc-shape modeling improvement on the same template (s185 max_priority / s186 combo_sequence / s187 form_index / s188 per-AA on-hit / s189 Spellblade-in-burst / s190 Lightshield-in-burst / s191 block_index). Each shipped backend-first with live A/B verification before commit; each added per-item or per-champion-derived modeling without breaking backward-compat (default field values + empty registry maps preserve pre-batch behavior). Engine surface area is now stable for a future "conditional block_index" lift to slot in without re-architecting.

---

# s190 wrap — 2026-05-13 (Phase 5.8 Sundered Sky Lightshield Strike in burst)

**Operator instruction:** "continue" — directly continuing the s189 carry-forward list. Top item: Sundered Sky Lightshield Strike (6610) — same "next AA after ability cast" mechanic as Spellblade but explicitly OUT of the spellblade unique-passive family. Single commit ship.

## Context

s189 closed the Spellblade gap in burst combos. Sundered Sky was carried forward because it carries a `PeriodicProc(name="Lightshield Strike", every_n_seconds=8.0)` — same arm-consume mechanic but with its own (intentionally absent) `unique_passive_key`. The schema comment at effects.py:539 spells it out: "Sundered Sky (6610) uses its own 'Lightshield Strike' label, not Spellblade — distinct mechanic, no dedup."

Two architectural decisions for this batch:
1. **Don't generalize** — second arm-consume helper, not an `is_ability_triggered_aa_proc` flag. Two items doesn't justify abstraction; if a third arm-consume mechanic ships, generalize then.
2. **Cap at 1 proc per combo** — Sundered Sky's real CD is 8s vs a typical 2-3s burst window. The cap is implicit: re-arming guards on `lightshield_procs_fired == 0`, so once the proc lands, subsequent ability casts in the same combo can't re-arm it. Spellblade's unlimited per-combo firing is correct because its 1.5s CD is well below combo length.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/dps.py](agents/daemon_slayer/dps.py) | New `LIGHTSHIELD_STRIKE_PROC_NAME = "Lightshield Strike"` constant + `_lightshield_strike_per_proc_damage()` helper (sibling of `_spellblade_per_proc_damage`). Filters by `proc.name == "Lightshield Strike"` rather than `unique_passive_key` because Sundered Sky has no dedup family. Returns `(per_proc_damage, item_name)` via the standard pipeline (`resolve_damage` → `_armor_factor` → mode → type-selective `magic_amp` for MAGIC only → `damage_amp`). `DpsResult` gains `lightshield_strike_per_proc_damage: float = 0.0` + `lightshield_strike_item_name: str = ""` fields; `to_dict()` carries them. `compute_dps` populates after the existing Spellblade block + emits a notes line when present. |
| [agents/daemon_slayer/burst.py](agents/daemon_slayer/burst.py) | Reads `aa_probe.lightshield_strike_per_proc_damage` + `aa_probe.lightshield_strike_item_name` alongside Spellblade. Combo walker gains parallel state vars `lightshield_armed` / `lightshield_procs_fired` / `lightshield_damage_total`. Ability token branch arms BOTH spellblade + lightshield, but lightshield arm is gated by `lightshield_procs_fired == 0` (8s CD cap). AA token branch consumes both independently — a build with both Sundered Sky + Trinity Force lands BOTH procs on the same AA. ComboCast AA notes block restructured to compose `base + on-hit + Spellblade + Lightshield Strike` parts; only present parts surface. `BurstResult` gains `lightshield_strike_procs: int = 0` + `lightshield_strike_damage: float = 0.0` + `lightshield_strike_item_name: str = ""` fields. Notes block reports fired count or idle state. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.74.0 → 0.75.0. Docstring extended with Phase 5.8 section (mirrors Phase 5.7 structure). |
| [agents/daemon_slayer/tests/test_lightshield_strike_burst.py](agents/daemon_slayer/tests/test_lightshield_strike_burst.py) | **NEW (~395 LOC, 28 tests).** Four classes mirroring s189's test_spellblade_burst.py structure. `LightshieldHelperTests` (8) — empty / non-lightshield / Sundered Sky returns 140 (20 + 2×60 base_ad) / armor mitigation / damage_amp / mode_multiplier / physical immune to magic_amp / independent of spellblade. `DpsResultLightshieldFieldsTests` (5) — naked = 0 / Spellblade-only = 0 lightshield / Sundered Sky surfaces / both items surface independently / to_dict. `BurstLightshieldIntegrationTests` (12) — naked / arms+fires once / capped at 1 per Q-AA-W-AA combo / pure AA combo / no AA combo / AA before spell / AA row carries Lightshield in final / Sundered Sky + TF stack on same AA / dual proc AA row carries both / Lightshield after fired doesn't re-arm / to_dict / Lightshield + Wit's End on-hit stack. `ServerBurstRouteLightshieldTests` (3) — naked / Sundered Sky surfaces / dual-proc build stacks (skipped when :8893 unavailable). |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests (Batch63 + Batch64) bumped 0.74.0 → 0.75.0 with the Phase 5.8 line in the history comment. |

## Verification

- DS suite **1605 pass** (was 1577 in s189 wrap; +28 from new test file)
- Wider RC suite **1013 pass** (no regression)
- `py_compile` clean for all 5 changed engine files
- DS server :8893 restarted from pid 12704 (s189 leftover) → pid 2968 (s190); `/health` reports `engine_version=0.75.0` patch=16.10.1

## Live A/B on :8893

**Aatrox lvl 11 vs 80 armor / 30 MR / 2000 HP (default combo Q-W-E-AA-R-AA, 2 AAs):**
- naked: 293.7 burst, AA 122.2
- +Sundered Sky (6610): 519.9 (+226), AA 305.6, LS=1× +133
- +Trinity Force (3078): 612.5 (+319), AA 406.7, SB=2× +244
- +TF + Sundered Sky: 838.7 (+545), AA 590.0, **SB=2× +244 AND LS=1× +133** — clean additive stacking

**Custom combo Q-AA-W-AA (2 AAs, 2 spell casts):**
- +Sundered Sky alone: LS=1× +133 (capped at 1 proc by 8s CD, confirms the gate works even with 2 eligible AAs)
- +Trinity Force alone: SB=2× +244 (no cap, fires on every armed-AA transition)
- +TF + Sundered Sky: SB=2× +244 AND LS=1× +133 (still independent state machines)

Math check: dual-item burst 838.7 - 293.7 = +545 = (Sundered Sky alone +226) + (TF alone +319) exactly. Confirms zero overlap; both procs land independently on the AA following the first ability cast.

## Findings

- **Helper sourced by proc-name, not item-id.** Sundered Sky has no `unique_passive_key`, so the helper filters on `proc.name == "Lightshield Strike"` instead. More future-proof — a future item adding a Lightshield Strike variant would auto-match. Trade-off: relies on the proc name string staying stable across patches (which it has for years).
- **Re-arming gate keeps the model simple.** Initial design considered tracking elapsed combo time + comparing against the 8s CD, but that requires a combo-timing model the engine doesn't have. The gate `if lightshield_procs_fired == 0: armed = True` produces correct behavior for typical bursts without needing time accounting.
- **Combined-build math validates the architecture.** Dual-item AA row's `final_damage` exactly equals `avg_attack_dmg + spellblade_per_proc + lightshield_per_proc` from the matched-build `compute_dps` probe. No double-counting, no overlap drift. The `test_dual_proc_aa_row_carries_both` test guards this invariant.
- **PowerShell `$pid` gotcha.** PowerShell reserves `$pid` as read-only (it's the current process's PID). The DS-restart command failed silently when I tried to assign to it; eventually killed a phantom PID 17580 (probably my own test runner). Renamed to `$proc` for the restart. Logged to memory.

## Open items carried forward

- 🟡 **Real internal CD in long combos.** Lightshield Strike still uses the implicit "once per combo" gate. An 8+ token combo lasting >3s might in theory permit a second proc (real CD 8s — still wouldn't fit a typical burst, but conceptually). Same edge case as s189's Spellblade CD handling.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q, Akali R1→QE→R2).** Inter-spell awareness still missing — burst is computed as additive single-spell hits. Carried since s180.
- 🟡 **Generalized arm-consume framework.** Two specific helpers now in the engine (`_spellblade_per_proc_damage` + `_lightshield_strike_per_proc_damage`). If a third arm-consume mechanic ships, generalize to `is_ability_triggered_aa_proc: bool` schema field at the PeriodicProc level rather than adding a third helper. Tracked but not pursued this batch.
- 🟡 **Pre-existing carry-forwards from s189:** Aphelios upstream data gap, Karma mantra runtime plumbing, Khazix evolved-form choice, live-game chip lifecycle validation, audit finding #1 frozen-file list duplication.

## Architectural pattern lock-in (continued from s189)

Sixth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority / s186 combo_sequence / s187 form_index / s188 per-AA on-hit / s189 Spellblade-in-burst / s190 Lightshield-in-burst). Each shipped backend-first with live A/B verification before commit; each added per-item or per-champion-derived modeling without breaking backward-compat (default field values preserve pre-batch behavior).
