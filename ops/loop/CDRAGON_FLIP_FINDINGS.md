# prefer-CDragon flip: FLIPPED + SHIPPED (ENGINE 1.119.0, 2026-06-06) - see POST-319 section at end

> STATUS UPDATE 2026-06-06: the flip is now LIVE (default ON, ENGINE 1.119.0). The
> historical deferral analysis below (item 311 / POST-317) is preserved verbatim for
> provenance; the executed-cutover record is the final "POST-319 FLIP EXECUTED" section.

# prefer-CDragon flip: INVESTIGATED, NOT FLIPPED (blocked on extractor defects) [HISTORICAL]

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

Regenerate evidence: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/daemon_slayer_cdragon_ratio_extract.py --drift -v`

## POST-317 RE-INVESTIGATION (2026-06-06): flip STILL unsafe - positional-pairing block-mismatch

Cycle re-fired the same directive (flip default ON + bump ENGINE 1.119.0 + re-pin). Item 317
(HEAD `fab49c51`) fixed extractor defects 1+2 (off-by-one trim + explosion guard); the drift
audit confirms both are gone. Re-ran the empirical gate (NOT a blind re-pin):

- `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/ds_cdragon_drift_audit.py`: n_changed=433, explosion=0, off_by_one_residue=0,
  large_divergence=173, rank_shape_mismatch=145, n_suspect=318.
- Flipped `abilities.py:467` default True + `pytest agents/daemon_slayer/tests/`:
  **70 failed / 6620 passed** (item 311 was 79; item-317 data fix = -9).
- Reverted (abilities.py byte-identical to HEAD); post-revert DS suite
  **6690 passed / 1 skip / 1 xfail / 1936 subtests** = green baseline, 0 regressions.

The 70 failures are NOT Meraki-staleness balance drifts (the directive's premise). They are
STRUCTURAL block-relationship invariants broken by the consumer seam
`_apply_cdragon_ratio_preference` (abilities.py:430), which pairs CDragon mechanical blocks with
engine damage blocks BY POSITION (`zip(mech, dmg_idx)`). CDragon's DataValues block
decomposition does NOT correspond 1:1 positionally with the engine/Meraki `damage_blocks`
decomposition for multi-block abilities, so the wrong CDragon block lands on the wrong engine
block. Concrete diffs (flip ON):
- Ambessa Q: block1 base 50.0 != 2x block0 (40.0)   [invariant: block1 == 2x block0]
- Gwen R:    block4 base 540.0 != 9x block0 (50.0)   [invariant: block4 == 9x block0]
- Udyr R:    block1 base 80.0 != 8x block0 (20.0)    [invariant: block1 == 8x block0]

Re-pinning these would destroy documented in-game multi-hit/escalating-damage relationships and
bake wrong DPS into the live engine (~32 routing+multiplier tests across
Ambessa/Gwen/Udyr/Akshan/Kayn/Viktor/Karthus/Nautilus/Irelia/Sion/...). This is the exact class
item 317 left gated: "Flip remains gated on a positional-pairing audit + per-champ review (Zac
Q/W wrong-calc class)."

DECISION (auto-picked SAFE path per operator standing rules that OVERRIDE the literal directive:
root-cause-fix / no-data-corruption / verify-before-ship / better-engine north star; item-311
precedent): NOT flipped. ENGINE stays 1.118.0. Seam stays default-OFF. DS NOT restarted. Net
code diff = ZERO.

NEXT (the real fix - a separate gated cycle, NOT a re-pin): replace the positional
`zip(mech, dmg_idx)` in `_apply_cdragon_ratio_preference` with a STRUCTURE-AWARE pairing that
overrides a block only when the CDragon block provably corresponds to that engine block (match
on rank-vector shape + preservation of the block-to-block multiplier relationship, else per-block
Meraki fall-back). Build a per-champ block-decomposition alignment map for the multi-block
abilities (the ~32 routing/multiplier failures enumerate the candidate set). Re-run the flip-ON
suite; only then should residual failures be genuine balance drifts (Lux Q 65->75 AP) safe to
re-pin, after which: flip default ON + bump ENGINE + sync docs + restart DS. Until that seam fix
lands, do NOT flip and do NOT bump ENGINE.

## POST-319 FLIP EXECUTED (2026-06-06): the seam fix landed - flip is now SAFE + SHIPPED

The "real fix" the POST-317 NEXT block called for shipped as item 319 (the semantic
block-matcher: `_apply_cdragon_ratio_preference` now does a stat-FAMILY-signature bijection
with whole-form Meraki fall-back on any ambiguous multi-block structure, replacing the
positional `zip`). This cycle re-fired the flip directive against that matcher and it is now
SAFE. Hard ground-truth evidence (NOT a blind re-pin):

- Flipped `abilities.py` default True, ran `pytest agents/daemon_slayer/tests/` BEFORE any
  re-pin: **5 failed / 6693 passed** (item 311 was 79; POST-317 positional-zip was 70; the
  semantic matcher cut the 70 STRUCTURAL failures to ZERO). The 5 residuals were exactly two
  classes, both benign:
  1. FLOAT32 NOISE (NOT a drift): VeigarQ ap `(50, 55.000001, 60.000002, 64.999998, ...)` vs
     Meraki `(50,55,60,65,70)`; EzrealQ tad `129.999995` vs `130.0`. CDragon bins store ratios
     as float32, so `fraction*100` then round6 leaks 6th-decimal noise on values that are
     mechanically IDENTICAL to Meraki.
  2. GENUINE balance drift: LuxQ golden `366.75 != 349.85` (75% vs 65% AP).

- ROOT-CAUSE FIX for class 1 (TDD): NEW `tools/daemon_slayer_cdragon_ratio_extract._snap`
  (round-4) snaps emitted base+ratios so float32 noise collapses to the clean authored value
  while every genuine ratio (67.5/82.5/0.35) survives. Sidecar regenerated live: 171 champs /
  838 mechanical / 577 fallback / 0 errors. Post-snap VeigarQ/EzrealQ byte-match Meraki -> those
  two failures vanish with NO ugly re-pin.

- PER-CHAMPION VALIDATION for class 2 (wiki + live bin, cited): LuxQ Light Binding is 75% AP
  live (Meraki 65% stale); EzrealQ Mystic Shot is 130% AD + 40% AP live (Meraki recorded a stale
  15% AP); VeigarQ unchanged. CDragon is authoritative for both genuine drifts -> re-pinned only
  the validated LuxQ golden (`test_golden_e2e_p1l24` 0.65 -> 0.75). The 2 seam tests re-pointed
  for the new default (explicit `prefer_cdragon_ratios=False` is now the legacy Meraki path).

- SHIPPED: default ON, ENGINE 1.118.0 -> 1.119.0, 64 test-assertion files re-pinned, CHANGELOG
  prepended, Share mirror + doc anchors synced (`ds_share_sync.py`), DS :8860 restarted -> 1.119.0
  (pid verified, `/health` engine_version=1.119.0). Final suite: DS `agents/daemon_slayer/tests/`
  **6699 passed / 1 skip / 1 xfail / 1936 subtests / 0 failed**; root DS-anchor + preview +
  phase8 live-integration tests green post-restart. The directive's premise held: with the
  item-319 matcher in place, the only residual changes were one validated balance drift plus
  float32 denoising - exactly the "safe to re-pin" state the POST-317 NEXT block predicted.
