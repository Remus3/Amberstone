# prefer-CDragon flip: INVESTIGATED, NOT FLIPPED (blocked on extractor defects)

Cycle outcome: the directive (flip `prefer_cdragon_ratios` default ON + bump ENGINE +
re-pin golden tests to CDragon values) was investigated and DEFERRED. Flipping ON ships a
broken engine. Hard ground-truth evidence below. Seam stays default OFF; no ENGINE bump;
suite restored to green baseline.

## What was done

- Ran `tools/daemon_slayer_cdragon_ratio_extract.py --drift -v` (live CDragon, patch 16.11.1).
  Result: 171 champs, mechanical=916, fallback=499, errors=0. Sidecar + drift generated.
- Flipped default ON, updated the seam test, ran `pytest agents/daemon_slayer/tests/`.
  Result: **79 failed, 6540 passed**. Inspected real failure diffs (not just the drift report).
- Reverted the flip + test (git diff clean). Engine byte-identical, suite green.

## Why the flip is unsafe (3 extractor/resolver defect classes)

The CDragon sidecar is NOT a clean improvement over Meraki. The resolver emits structurally
wrong arrays for a large fraction of abilities. Re-pinning the 79 golden tests to these
values would bake the defects into the live DS engine (violates root-cause-fix +
no-data-corruption + verify-before-ship).

### 1. Systemic off-by-one (DOMINANT) - leading rank-0 placeholder not trimmed
CDragon `DataValues` arrays are rank-indexed `[rank0, rank1..rank6]` (7 entries). The engine /
Meraki use `[rank1..rank5]`. The extractor emits the raw 7-entry array, so every value is
shifted one rank and a spurious rank-0 entry leads.

Alignment over all mechanical base arrays vs Meraki: **offset1 (true values at index 1) = 445,
offset0 (direct) = 3.** Examples (got vs expected):
- Aatrox Q base `(-5.0, 10.0, 25.0, 40.0, 55.0, 70.0, 85.0)` vs `(10.0, 25.0, 40.0, 55.0, 70.0)` -> `[1:6]` matches.
- Aatrox Q total_ad_pct `(52.5, 60, 67.5, 75, 82.5, 90, 97.5)` vs `(60, 67.5, 75, 82.5, 90)` -> `[1:6]` matches.
- Veigar Q base `(40,80,120,160,200,240,280)` vs `(80,120,160,200,240)` -> `[1:6]` matches.
- MasterYi Q TotalDamage base `[0.0,20,40,60,80,100,120]` -> `[1:6]` = Meraki `[20,40,60,80,100]`.

FIX (next cycle, needs TDD + per-champ validation): in `resolve_calc_block`, drop the leading
rank-0 entry from emitted base/ratio arrays when length indicates a rank-0 prefix (len >= 6).
Leave genuinely 5-length arrays untouched (the 3 offset0 cases). Affects base AND non-flat
ratios sourced from DataValues; flat broadcast ratios are unaffected (identical entries).

### 2. Value explosions on crit/cumulative calcs
Some named calcs resolve to absurd per-rank ratios (independent of the off-by-one):
- MasterYi Q `SingleCritTotalDamage` total_ad_pct `[122.5, 3622.5, 7122.5, 10622.5, 14122.5, 17622.5, 21122.5]`.
- MasterYi Q `SubesquentDamage` total_ad_pct `[70, 2070, 4070, 6070, ...]`.
These pair POSITIONALLY (`_apply_cdragon_ratio_preference`, abilities.py:430) onto real
Alpha Strike damage blocks -> MasterYi DPS would explode. Root cause: a Sum/Product or
referenced DataValue that is not a true ability ratio (likely a monster/bonus term). Needs a
resolver guard that marks these blocks `resolution="fallback"`.

### 3. Fractional-base mis-bucketing
Coefficients land in `base[]` (absolute-damage field) as fractions:
- Akshan Q base `[0.2, 0.2, ...]` (test expected `2x block0 = 30.0`); Ambessa Q base `[0.5,...]` / `[0.035, 0.04,...]`.
A `0.2` flat-damage base is nonsense. Likely a `NamedDataValueCalculationPart` referencing a
coefficient data value with no `mStat`. Needs the same fallback guard.

## Multi-hit-ult semantic mismatch (NOTE, not a hard blocker)
For multi-projectile ults the resolver emits per-hit ratios while Meraki stores the aggregate:
MissFortune R total_ad_pct CDragon `60` (per bullet) vs Meraki `[1050,1200,1350]` (full channel);
Lucian R `25` vs `575`. Even with defects 1-3 fixed, these are a SEMANTIC difference requiring
per-champion validation before CDragon becomes authoritative (operator rule: champion-specific
scorer changes are validated per-champion, not assumed).

## Conclusion / next-cycle plan to flip safely
1. Fix extractor defect 1 (off-by-one trim) with a TDD resolver test. Regenerate sidecar+drift.
2. Add a resolver fallback guard for defects 2+3 (explosion + fractional-base) with tests.
3. Re-run `pytest agents/daemon_slayer/tests/` WITH the flip ON; the remaining failures should be
   only genuine Meraki-vs-CDragon drifts. Validate a sample per-champion (Lux Q 65->75 AP, etc.).
4. Re-pin only the validated genuine drifts; flip default ON; bump ENGINE; sync living docs.

## Slice B (read-only sweep) findings
- Stale anchor: `ROADMAP.md:122` fleet-glance DS row reads `ENGINE 1.63.0 / 4894 tests / 172 champions`;
  live is `1.118.0` / DS suite ~6619 / 171 champions. Cosmetic glance-table drift (CLAUDE.md notes
  live truth = current.txt + __init__.py + /health). Fix in a docs-sync cycle.
- 7-lever cost/latency sweep: prompt-cache (cache_control on all static system blocks - saturated),
  route no-store default (`dashboard/_handler.py:158`), poll cadence (1.5s game / 15s bridge - sane),
  model tiers (Haiku coaches / Sonnet vision-escalation / Opus advisor - correct), asset-hash parity
  (ADR-008, `dashboard/_static.py:23` - all panels covered). All saturated. One marginal win:
  demote `vision_server/_inference.py:272` OCR-results INFO line to DEBUG (2s cadence, low value).

Regenerate evidence: `py tools/daemon_slayer_cdragon_ratio_extract.py --drift -v`
