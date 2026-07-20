# ADR-010: Arena S2 Augment Level-Up pre-stage doctrine

**Date:** 2026-05-21
**Status:** Accepted (pre-stage doctrine, no code change today)

## Context

Riot has announced Arena Season 2 in the patch 26.09 window. The headline
mechanic is per-augment Level-Up: each augment ramps 1 -> 2 -> 3 mid-match
instead of the current single-tier Silver / Gold / Prismatic system.
Round 8 becomes the Crafting Round - the operator either adds a new
augment slot OR removes an existing augment to level another one up.
A new Keystone tier appears at max level (visual + stat differentiation).

RC's current Arena encoding is single-level by construction:

- `agents/daemon_slayer/augments.py::Augment` is a frozen dataclass with
  a flat `data_values: dict` (no level axis). `from_record` reads
  `rec["dataValues"]` as a single mapping.
- `compute_augment_stats(augment_or_id, *, mode=...)` has no `level`
  kwarg. It reads `augment.data_values` once and emits a stat overlay.
- `_AUGMENT_STAT_OVERLAYS` (the hand-tuned tier-1 registry) keys on
  `apiName` alone - no level dimension.
- The cdragon `calculations` formula evaluator in `augment_formula_eval.py`
  (item 112, commit `21657eb`) walks `Augment.calculations` per augment;
  it has no level concept either.
- The Arena coach OCR layer matches by augment name. Today's screenshot
  shape has a single tier-icon per augment; the S2 shape adds 3 level
  pips (or 3 marks) per augment visible mid-match.

When 26.09 ships, both the data layer (cdragon's per-augment record
likely gains a `levels[]` axis) and the OCR layer (level-pip count in
the screenshot) break simultaneously. The Crafting Round itself adds a
new mid-match UI flow (add-slot vs. level-up branching) which RC has
nothing for today.

Three options for handling the impending break were considered:

1. **Speculative ship-now.** Pre-implement a `levels[]` schema today
   against a guessed cdragon shape. Rejected - PBE has not confirmed
   the field name or container; ship-now risks a churn cycle when
   the real schema differs in a small but load-bearing way.

2. **Wait for 26.09 PBE, then do everything in one session.** Workable
   but the schema break touches three layers (engine, registry, coach
   OCR) plus the Crafting Round adds a separate UI surface. A single
   session under live-patch pressure mixes the schema lift with the
   mechanic work and concentrates risk.

3. **Pre-stage the seam today, leave the registry empty.** Add the
   `level: int = 1` keyword on `compute_augment_stats` with an
   identity-at-level-1 boundary so production behavior is byte-identical
   pre-26.09. When PBE confirms the cdragon shape, the lift collapses
   to populating the seam (similar to the `STAT_GRANT_CALC_KEYS` empty
   registry pattern from item 112 - the wire is in place, the data
   is what arrives).

This ADR locks option 3 as doctrine.

## Decision

**Pre-stage the `level=1` identity boundary on `compute_augment_stats`
when 26.09 PBE confirms the schema, NOT today.** This ADR is the
anchor; the code change is one focused commit at PBE-confirm time.

The pre-stage seams to add when PBE confirms (one commit, ENGINE bump
owed only at the time of the data lift):

- `Augment.from_record` reads a `levels` field if present, falls back
  to single-level. The internal storage flips from `data_values: dict`
  to `data_values_by_level: dict[int, dict]` keyed by level 1..3 (or
  1..4 if Keystone is exposed as a fourth level rather than a flag).
- `compute_augment_stats(augment, *, level: int = 1, mode=...)` reads
  `augment.data_values_by_level.get(level, augment.data_values_by_level[1])`.
  Default-level=1 keeps existing callers (build planner, arena coach
  prompt, tests) on the same numeric path until they opt in.
- `_AUGMENT_STAT_OVERLAYS` keying extends to `(api_name, level)` tuples,
  with a fallback that re-uses the level-1 entry when no level-specific
  override is registered. Today's registry entries (Silver/Gold/Prismatic
  flat-stat overlays) map naturally to `(api_name, 1)` keys at PBE-confirm
  time.
- `augment_formula_eval.py` gains a `level` parameter on the per-augment
  evaluator path so cdragon `calculations` evaluation can pull
  level-specific `mFormulaParts` when the upstream schema carries them.
- A new test file `tests/test_arena_s2_augment_leveling.py` pins
  level-1 identity (output unchanged versus today's single-level path)
  plus level-2/3 deltas on a fixture augment, mirroring the value-pinned
  regression pattern from items 108-112.

The methodology composes on the empty-registry pre-stage pattern
already established in this repo:

- `STAT_GRANT_CALC_KEYS` (item 112, `21657eb`) shipped the cdragon
  formula evaluator with an empty displacement registry. Production
  behavior was byte-identical pre-Arena-patch, and future patches
  populate the registry without further engine changes. The S2
  level seam follows the same shape: wire the parameter, leave the
  multi-level data empty until PBE confirms, populate at patch flip.

## Consequences

**Good:**

- Zero behavior change today. `compute_augment_stats(augment)` at the
  default `level=1` returns exactly what it returns now; the build
  planner, arena coach prompt, and 38+ existing augment tests are
  unaffected at PBE-confirm time.
- Concentrates the 26.09 lift to a small named seam. The data layer
  change is ~1 commit (schema flip on `from_record`, parameter pass-
  through, registry key extension, fixture tests).
- Forward-compatible with the cdragon formula evaluator already
  shipped - the `level` parameter threads through `augment_formula_eval`
  on the same call path, no new traversal logic needed.
- Lets the Crafting Round mechanic and Keystone visual work proceed
  in separate, focused scopes once the data layer is stable.

**Trade-off:**

- Defers any actual Arena S2 readiness work until PBE drops. If the
  operator queues an Arena game on patch 26.09 before this seam is
  populated, augment-stat overlays will resolve to the level-1 (= S1)
  values - the build planner and coach prompt will under-credit any
  augment that has been leveled past 1. This is fail-soft (the engine
  ranks builds, it does not crash), but the rankings will lag the
  actual in-game power.
- The Crafting Round UI surface and the OCR multi-level pip detection
  are explicitly NOT covered by this ADR. The operator may see a
  patch-26.09 game where the engine math is correct (post-PBE-confirm
  commit) but the coach prompt has no awareness that round 8 is the
  Crafting Round. That is a separate work item.

**Watch for:**

- PBE 26.09 patch notes + dataDragon `arena-augments.json` schema diff
  at the patch flip. The probable field name is `levels[]` or
  `dataValuesByLevel` on each augment record, but neither is confirmed.
- cdragon shape change at `raw.communitydragon.org/latest/cdragon/arena/en_us.json`.
  The cdragon-arena entry's `dataValues` + `calculations` fields already
  ship per item 112's `8f7a71b` (calculations enrichment) + `21657eb`
  (formula evaluator). The S2 schema either nests these under a level
  key or duplicates them per level.
- Riot dev-portal devblog announcement of the S2 ship date. The patch
  26.09 window is approximate; an earlier or later flip changes when
  this seam needs to be populated, not whether.
- Any future contributor pre-implementing a `levels[]` schema before
  PBE confirms. Should not happen - this ADR is the doctrine that
  defers that work.

## Out of scope

The following are explicitly NOT covered by this ADR. Each gets its
own scope (and likely its own ADR) when 26.09 ships:

- **Crafting Round mechanic.** Round 8 add-slot vs. level-up branching.
  Touches `coaches/arena_coach.py` prompt + the live-match UI surface +
  the build planner's per-round projection. Separate session.
- **Keystone tier at max level.** Visual + stat differentiation when
  an augment reaches level 3 (or level 4 if exposed as a fourth tier).
  Touches the augment-icon renderer + the rarity_label mapping +
  the coach prompt's keystone-aware language. Separate work item.
- **cherry-augments.json OCR multi-level detection.** Reading the
  3-pip level indicator from a mid-match screenshot. Vision work,
  needs a calibration session against real S2 screenshots when
  available. Separate scope.
- **Build planner per-level projection.** Today the planner ranks
  augments by a single static stat overlay; S2 introduces a per-augment
  growth curve the planner could exploit ("pick A now because its
  level-3 ceiling is higher than B's"). Genuine new feature, not a
  schema lift. Separate work item.

## Linked work

- `agents/daemon_slayer/augments.py` - the `compute_augment_stats`
  signature this ADR pre-stages.
- `agents/daemon_slayer/augment_formula_eval.py` - the formula
  evaluator from item 112 (`21657eb`) that gains a `level` parameter
  at PBE-confirm time.
- `STAT_GRANT_CALC_KEYS` empty seam pattern (item 112) - the
  methodology mirror: pre-stage the wire, leave the registry empty,
  populate when upstream data confirms.
- BACKLOG.md "Multi-agent research wave triage - 2026-05-20" /
  Arena S2 FUTURE entry - the original capture of this work item
  from the research wave.
- ADR-009 - sibling pre-stage ADR style (Replay events sidecar).
