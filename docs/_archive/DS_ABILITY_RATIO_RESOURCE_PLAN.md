# DS ability-ratio re-source (DDragon/CDragon) - plan + status

Status: **mechanism shipped 2026-06-03** (resolver + drift tool + tests). Engine
cutover is **staged** (additive, default-off) - see the cutover steps below.

## Problem

Champion ability damage RATIOS (ap_pct, bonus_ad_pct, total_ad_pct,
caster_max_hp_pct, ...) in `data/daemon_slayer/<patch>/champion_abilities.json`
are sourced from Meraki. Meraki `latest` CONTENT is frozen at in-game patch
**25.15**; live is **16.11**. The ENGINE 1.108.0 content-freshness guard only
SURFACES this drift (a loud WARNING) - it does not cure it. The fix is to
re-source ratios from a LIVE source.

## Source verdict

- **DDragon** champion.json is **tooltip-text-only** on the modern patch -
  `spells[].vars` is empty, scaling lives only as `{{ }}` placeholders in
  tooltip/effectBurn. NOT a viable coefficient source.
- **CommunityDragon** character bins carry `mSpellCalculations` with
  `{mCoefficient, mStat}` formula parts over `DataValues[]` rank arrays. Viable.
  Distribution scan (130 GameCalculation blocks across 14 champs): ~66% are flat
  parts only; restricted to actual damage blocks the mechanical fraction is
  ~**75-80%**. The remaining tail needs a calc-graph evaluator or hand-curation.

## Tool (shipped)

`tools/daemon_slayer_cdragon_ratio_extract.py` - pure resolver core + thin
live/CLI shell, stdlib-only, atomic writes, fail-soft. Reuses the bin-walker
(slug/patch-dir/Q-W-E-R mapping) proven in `daemon_slayer_cdragon_spell_extract.py`.
Tests: `tools/tests/test_cdragon_ratio_extract.py` (35 green, offline fixtures).

Mechanical part-types resolved -> schema:
- `NamedDataValueCalculationPart` -> `base[]`
- `StatByNamedDataValueCalculationPart` / `StatByCoefficientCalculationPart` ->
  ratio (`mCoefficient` or named array) x100, stat via `mStat`
  (absent/0 -> ap_pct, 2 -> total_ad_pct, 8 -> bonus_ad_pct,
  12 -> caster/target_max_hp_pct)
- `GameCalculationModified` (named ref x multiplier) and flat
  `ProductOfSubParts` / `SumOfSubParts`

Fallback (NO ratio emitted, Meraki stays authoritative): `ByCharLevel*`,
`Breakpoint`, `BuffCounter*`, `GameCalculationConditional`, sub-part stat refs,
cross-refs into conditional/buff calcs, and any UNKNOWN stat enum (conservative).

CLI: default writes `cdragon_ability_ratios.json`; `--drift` adds
`cdragon_ratio_drift.json` (per-field meraki-vs-cdragon delta + summary);
`--champions A,B`, `--patch`, `--out`.

## Drift finding

Full `--drift` map (170 champs): **439 of 703 mechanically-comparable blocks
differ** from the frozen Meraki ratios (62%), plus 377 blocks present only in
live CDragon and 499 in the hard-fallback tier. (4-champ spot probe
Lux/Darius/Zac/Jhin: 19/26.) Regenerate the full map on demand:
`python tools/daemon_slayer_cdragon_ratio_extract.py --drift` (the sidecar
`cdragon_ability_ratios.json` + `cdragon_ratio_drift.json` are generated
artifacts, NOT committed - keeps the repo lean and the Share mirror clean).
A blind cutover would therefore shift ~62% of comparable damage numbers and
break every gold/golden DS test that pins them - hence the staged, reviewed
approach below.

## Staged cutover (the remaining DS batch)

1. (DONE) resolver + drift tool + 35 tests + additive `cdragon_ability_ratios.json`.
2. Generate + review the full `--drift` map; classify each changed field as
   "adopt" (real patch change) vs "resolver artifact".
3. Wire the engine to PREFER `cdragon_ability_ratios.json` mechanical blocks with
   Meraki fallback, behind a flag, DEFAULT-OFF (own DS batch).
4. Re-pin gold/golden DS tests from the reviewed drift diff (bounded re-pin).
5. Flip default-on; bump ENGINE_VERSION; restart the DS server (:8893); live-verify.

## Hard-case tail (resolver phase 2, future)

Conditional branches, buff/stack counters, by-champion-level interpolation +
breakpoint tables, and caster-vs-target max-HP disambiguation stay Meraki-sourced
until a recursive calc-graph evaluator lands. Arena (cherry) `DataValuesModeOverride`
is noted but the SR/default values are primary.
