# WP-C2 SPEC - Build scoring model + candidate generation + beam search

Status: GROUNDED SPEC (headless run 2026-06-29-01). READ-ONLY planning artifact.
No production code authored. This is the only file written by this run.

Section C build-planner module #2. A planner ABOVE Daemon Slayer (DS): DS answers
"which set maxes DPS"; WP-C2 answers "best coherent, ordered PLAN given kit + gold +
owned + enemy". DS output is read-only ground truth.

---

## 0. CRITICAL DISCREPANCY - READ BEFORE BUILDING (ground truth wins)

The launch prompt asserts "deps C1 satisfied, item 660 ... the cohesion term reuses
C1 synergy" and "DO-NOT-REDO: C1 is DONE". **Ground truth contradicts this on every
point.** The build agent MUST resolve this before writing `scoring.py`.

| Prompt claim | Ground truth | Evidence |
|---|---|---|
| C1 module `core/build_planner/kit_synergy.py` exists | Does NOT exist. `core/build_planner/` directory is absent. | `Glob core/build_planner/**/*.py` -> no files; `ls core/build_planner/` -> "No such file or directory". Only `core/build_order*.py` exist. |
| `synergy_score()` is a callable public API to reuse | Exists ONLY as a planned formula string in the master plan, never implemented. | `Grep "synergy_score"` -> single hit: `docs/OVERLAY_BUILD_MASTER_PLAN.md:172` (the WP-C1 "Fix" cell). Zero `.py` matches. |
| "item 660", LEDGER 660 NEXT note | No item 660. Latest LEDGER item is 344 (2026-06-07). No WP-C1/WP-C2 entry in the LEDGER at all. | `tail docs/LEDGER.md` -> last numbered item 344; `Grep "660|WP-C1|WP-C2|C1 satisfied"` in LEDGER -> no matches. |
| `get_archetype_for` / `kit_damage_axis` "used by C1" | Both exist and are real, but in `core/archetype_picks.py`, NOT in a C1 module. | `get_archetype_for` @ `core/archetype_picks.py:592`; `kit_damage_axis` @ `core/archetype_picks.py:223`. |

**Implication.** WP-C2's `cohesion(set)` term depends on WP-C1's `synergy_score`. C1 is
NOT done. Per the master plan dependency graph (`OVERLAY_BUILD_MASTER_PLAN.md:645`:
"C1 -> C2 -> {C3,C4}") C2 is blocked on C1. The build agent has two grounded options
(see OPEN RISKS R1) - it must pick one explicitly and not silently scaffold a call to a
function that does not exist.

---

## 1. NEW FILES

Both new, both under a new package directory `core/build_planner/` (which must also get
an `__init__.py` - the dir does not exist yet):

- `core/build_planner/__init__.py` - package marker (empty or re-exporting the two public dataclasses + entry fn).
- `core/build_planner/scoring.py` - the weighted scoring model (pure functions over a build + context).
- `core/build_planner/planner.py` - candidate generation + beam search; the public entry point.

Tier-1 classification (see Section 7): new module + own tests, NO `agents.daemon_slayer`
import, NO `ENGINE_VERSION` bump, NOT Share-mirrored.

---

## 2. PUBLIC FUNCTION SIGNATURES

### 2.1 `core/build_planner/scoring.py`

Mirror the dataclass + `to_dict()` discipline already used in `core/build_order.py`
(`BuildStep`/`BuildOrderResult`) and `agents/daemon_slayer/beam.py` (`RankedBuild`).

```python
@dataclass(frozen=True)
class ScoreTerms:
    """Per-term breakdown so the score is explainable (acceptance req:
    'scoring is explainable (per-term breakdown)')."""
    dps: float            # w_dps  * DS dps/ehp/etc term (from the seed rows)
    cohesion: float       # w_cohes * cohesion(set)   [C1 reuse - see R1]
    situational: float    # w_situ * situational_fit  [STUB in C2; C3 fills it]
    spike: float          # w_spike * spike_value(prefix, clock)
    gold: float           # w_gold * gold_efficiency(set)
    penalties: float      # subtracted: legality/redundancy/overcap
    total: float
    stage: str            # "early" | "mid" | "late" - which weight set applied

    def to_dict(self) -> dict: ...


def stage_for(clock_s: float, owned_count: int) -> str:
    """Map game clock + build progress -> 'early'|'mid'|'late'. Stage shifts
    the weight vector (early: spike/defense; late: pen-offense/dps)."""


def score_build(
    *,
    item_ids: list[str],          # ordered partial/full build being scored
    seed_rows: dict[str, dict],   # item_id -> DS seed row (from candidate gen)
    champion: str,
    archetype: str,
    scorer: str,                  # dps|ehp|hybrid|ability|burst|hps (from seed)
    clock_s: float = 0.0,
    cohesion_fn: Optional[Callable[..., float]] = None,  # C1 synergy_score adapter (R1)
    weights: Optional[dict] = None,                       # stage->weight overrides
) -> ScoreTerms:
    """Weighted score of one (ordered) build. Pure - no I/O, no engine call.
    Reads the DS dps/ehp term from ``seed_rows`` (already fetched), NOT by
    calling the engine. ``cohesion_fn`` defaults per R1 resolution."""
```

### 2.2 `core/build_planner/planner.py`

```python
@dataclass(frozen=True)
class PlannedItem:
    item_id: str
    item_name: str
    order_idx: int                # 0-based position in the planned sequence
    score_terms: dict             # ScoreTerms.to_dict() at the step it was added
    gold: int
    def to_dict(self) -> dict: ...


@dataclass
class BuildPlan:
    champion: str
    archetype: str
    scorer: str
    mode: str
    level: int
    owned: list[str]              # fixed prefix (already-purchased)
    plan: list[PlannedItem]       # ordered next-purchases (best beam)
    alternatives: list[list[PlannedItem]] = field(default_factory=list)  # other surviving beams
    context: dict = field(default_factory=dict)   # target_armor/mr/hp/clock - proves match-specificity
    beam_width: int = 6
    depth: int = 6
    builds_evaluated: int = 0     # bounded-eval acceptance proof (mirror beam.py:builds_evaluated)
    unique_passive_safe: bool = True
    notes: list[str] = field(default_factory=list)
    def to_dict(self) -> dict: ...


def plan_build(
    champion: str,
    archetype: str,
    *,
    level: int,
    owned_item_ids: Iterable[str],
    mode: str = "SR",
    clock_s: float = 0.0,
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    beam_width: int = 6,          # 5-8 per spec; default mid-range
    depth: int = 6,               # full build = 6 slots
    seed_fn: Optional[Callable[..., dict]] = None,   # candidate seed source (INJECTABLE - see R2/test plan)
    cohesion_fn: Optional[Callable[..., float]] = None,
    weights: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> Optional[BuildPlan]:
    """Beam search over ordered partial builds. Returns None when the seed
    source is unreachable or champion is blank (mirrors plan_build_order /
    dispatch_for_coach contract: core/build_order.py:410, :520). A reachable
    seed with nothing to add yields a BuildPlan with a short plan + note,
    NOT None.

    ``seed_fn`` defaults to an HTTP adapter that POSTs /api/ds-preview +
    /api/build-order (see Section 4). INJECTABLE so headless tests run with a
    fake seed - no live dashboard, no live :8893 engine (the exact pattern
    core/build_order.py uses with rank_fn: core/build_order.py:386,413)."""
```

`beam_width` and `depth` are validated `1 <= beam_width`, `1 <= depth <= 6`; values
outside the spec band 5-8 are allowed but the default sits at 6 (mid-band). Mirror
`beam.py:226` (`if beam_width < 1: raise ValueError`).

---

## 3. SCORING MODEL

Per master plan `OVERLAY_BUILD_MASTER_PLAN.md:184`:

```
Score = w_dps  * DS_dps(set, target)
      + w_cohes* cohesion(set)
      + w_situ * situational_fit(set, enemy, ally)
      + w_spike* spike_value(prefix, clock)
      + w_gold * gold_efficiency(set)
      - penalties(legality, redundancy, overcap)
```

### 3.1 Term sources (every external value cited)

- **`DS_dps(set, target)`** - DO NOT recompute DPS in C2 (that would need the engine =
  split-brain). Read it from the seed rows. The per-row delta key depends on the scorer
  the engine routed (`rank_for_primary_archetype`, `core/daemon_slayer_client.py:935`):
  the dispatcher ALWAYS emits a unified `"delta"` key per row regardless of scorer
  (`daemon_slayer_client.py:1038` ehp, `:1114` ability, `:1155` burst, `:1191` hps,
  `:1240` dps). The `/api/ds-preview` route re-keys this to `delta_dps` on the wire
  (`dashboard/routes_state.py:592-597`, `DsPreviewItem.delta_dps` @
  `dashboard/api_schema.py:104`). So: **the seed DPS term per item = `ranked[i].delta_dps`
  from the `/api/ds-preview` response.** Scorer label is top-level `scorer`
  (`routes_state.py:636`) + per-row `scorer` (`api_schema.py:106`). For a partial build's
  total DPS term, sum the deltas of the items in the set that appear in the seed, or
  re-seed per beam frontier (see R4 - the seed is computed against a fixed `owned`
  baseline, so naive summing double-counts; flagged as an open decision).
- **`cohesion(set)`** - reuses C1 `synergy_score`. **C1 does not exist (Section 0).** Per
  master plan `:184`: "cohesion = pairwise kit-alignment (C1) + named-effect synergies -
  overcap penalties". Resolution path in R1. The `cohesion_fn` parameter is the injection
  seam so C2 is testable and unblockable independent of C1's arrival.
- **`situational_fit(set, enemy, ally)`** - **OUT OF SCOPE for C2; this is WP-C3**
  (`OVERLAY_BUILD_MASTER_PLAN.md:190-200`, "Deps: C2"). In C2 ship it as a STUB returning
  0.0 (so `w_situ * 0 = 0`), with the term + weight wired so C3 drops in without a
  signature change. Do not build the enemy-profile/antiheal logic here.
- **`spike_value(prefix, clock)`** - power-spike value of completing this item now vs the
  clock. C2-local heuristic (no engine): reward terminal-item completion
  (`RankedItem.is_terminal`, present on seed rows via `agents/daemon_slayer/rank.py:251`,
  surfaced through the DS server; note the dashboard `/api/ds-preview` projection does NOT
  currently forward `is_terminal` - see R3) and 2/3/4-item spike thresholds. Ordinal only.
- **`gold_efficiency(set)`** - DPS-or-EHP-delta per 1000 gold. The seed already carries
  `gold` per row (`api_schema.py:105`); `dps_per_1k_gold` exists on the engine
  `RankedItem` (`rank.py:255`) but is NOT forwarded by `/api/ds-preview` (R3). Compute
  locally as `term/ (gold/1000)` from the forwarded `delta_dps` + `gold`.
- **`penalties`** - legality + redundancy + overcap. The unique-passive no-double rule is
  the legality core and is ENGINE-AUTHORITATIVE (Section 5) - do NOT re-implement a family
  map. Overcap (crit>100%, AS>2.5, 2nd %pen, redundant antiheal) is named in the master
  plan (`:184`) but the underlying stat caps live in the engine; in C2 the only
  penalty that can be applied WITHOUT the engine is the unique-passive collision (available
  on seed rows as `shares_dead_unique`/`dead_unique_key`, `api_schema.py` is `_AllowExtra`
  so these pass through if the route forwards them - R3). Crit/AS overcap needs item stat
  vectors = a C1 concern (R1). Ship overcap as a documented stub if C1 absent.

### 3.2 Stage-dependent weights

`stage_for(clock_s, owned_count)` -> `"early" | "mid" | "late"`. Master plan
`:184`: "Stage weights shift (early: spike/defense; late: pen-offense/dps)". Ship as a
module-level constant table (mirror the stable-constant pattern in
`core/build_order.py:72` `_UNIT_SUFFIX`, which is kept as a deliberate small independent
copy, NOT imported, to avoid drift). Concrete starting weights are an operator-tunable
decision (R5) - the spec fixes the SHAPE, not the magic numbers:

```
_STAGE_WEIGHTS = {
  "early": {"dps": .., "cohes": .., "situ": .., "spike": HIGH, "gold": .., },
  "mid":   {...},
  "late":  {"dps": HIGH, "cohes": .., "situ": .., "spike": LOW,  "gold": .., },
}
```

Tests assert RELATIVE shape (early spike weight > late spike weight; late dps weight >
early dps weight), never exact magnitudes (data-fragile rule).

---

## 4. CANDIDATE GENERATION (seed set)

### 4.1 Seed sources (cited wire shapes)

The candidate pool = **DS top-K seed + fixed situational set** (`master plan :183`:
"top-K (12-15) DS items + fixed situational set").

**Source A - `/api/ds-preview` `ranked[]`** (`dashboard/routes_state.py:498`
`_serve_ds_preview_post`; route registered `routes_state.py:932`). Request body
`DsPreviewRequest` (`api_schema.py:93`): `{champion, mode="SR", level=6, items=[], archetype=""}`.
Response (`routes_state.py:634-642`, schema `DsPreviewResponse` @ `api_schema.py:109`):
```
{ ok, ranked:[{item_id, item_name, delta_dps, gold, scorer}], scorer, archetype,
  target_stats, threat, defensive, capability_gap }
```
Each `ranked[]` row is the C2 seed candidate (`DsPreviewItem` @ `api_schema.py:101`). Note
`/api/ds-preview` calls `rank_for_primary_archetype(... top=8 ...)`
(`routes_state.py:562-564`) - it returns **top 8**, not 12-15. To get the master plan's
12-15 the build agent must pass a larger `top`/`level` or call with explicit body; the
route does not currently expose a `top` override in `DsPreviewRequest` (R3).

**Source B - `/api/build-order` `order[]`** (`routes_state.py:858` `_serve_build_order_post`;
registered `routes_state.py:933`). Request `BuildOrderRequest` (`api_schema.py:119`):
`{champion, mode="SR", level=11, items=[], archetype="", slots=6}`. Response is
`BuildOrderResult.to_dict()` (`core/build_order.py:331`) + `{ok, target_stats}`
(`routes_state.py:905-907`):
```
{ champion, archetype, scorer, mode, level, owned,
  order:[{slot, item_id, item_name, delta, gold, scorer, unit,
          excluded_family, excluded_example, locked_family}],
  order_str, context, unique_passive_safe, notes, ok, target_stats }
```
The `order[]` entries are `BuildStep.to_dict()` (`core/build_order.py:288`). This is the
greedy single-path order; C2 uses it as a strong seed / warm-start beam and as the
ordinal baseline the beam must MATCH-OR-BEAT (acceptance: MF SR fixture).

**Source C - fixed situational set** (antiheal/resist/%pen/lethality/GA/QSS,
`master plan :182`). In C2 this is a small hardcoded id/name set (the master plan lists
the categories). It is NOT the enemy-aware selection (that is C3). Keep it a stable
constant in `planner.py`, same anti-drift discipline as `build_order.py:_BOOTS_IDS`
(`core/build_order.py:95`).

### 4.2 The `seed_fn` boundary (CRITICAL - split-brain)

C2 must NOT import `agents.daemon_slayer` (Section 5 guard). The seeds come over HTTP from
the dashboard routes (which themselves reach the engine via the sanctioned :8893 client,
`core/daemon_slayer_client.py`). The default `seed_fn` is a thin HTTP adapter:

- POST `http://127.0.0.1:<dashboard_port>/api/ds-preview` and `/api/build-order`,
  parse JSON, return a normalized `{ "ds_preview": {...}, "build_order": {...} }`.
- Fail-soft to `None` on connection error / non-200 (mirrors
  `core/daemon_slayer_client.py:_post_json` @ `:59`, and the `plan_build_order` None
  contract @ `core/build_order.py:520`). `plan_build` then returns `None`.
- `seed_fn` is INJECTABLE; every test passes a fake (Section 6). This is the exact seam
  `core/build_order.py` uses with `rank_fn` (`build_order.py:386` param, `:413` default
  lazy import, `:512` call site).

DECISION FOR BUILD AGENT (R2): whether the HTTP adapter targets the dashboard routes
(compose-from-routes, per master plan `:182`) or calls `core.daemon_slayer_client`
directly (one fewer hop, still HTTP-to-engine, but then C2 re-implements the ds-preview
projection + the build-order orchestration that `routes_state.py`/`build_order.py` already
do). The master plan text says compose from `/api/ds-preview` + `/api/build-order` -> the
route-composition path is the documented intent. Either way C2 imports NEITHER
`agents.daemon_slayer` NOR (to stay clean) `dashboard.routes_state`; it speaks HTTP.

---

## 5. BEAM SEARCH

State = an ordered partial build (`tuple[str, ...]` of item ids, `owned` as fixed prefix).
Transition = append one candidate not already in the build. Prune to `beam_width` by
`score_build(...).total`. Depth = number of NEW slots to fill (`depth - len(owned)`,
capped at 6 total). Prior art to MIRROR (read-only, do NOT import): the DS engine's own
beam `agents/daemon_slayer/beam.py:190` `beam_search_build` + its algorithm docstring
(`beam.py:9-27`). C2's beam differs by scoring with `score_build` (kit-aware, multi-term)
instead of raw `compute_dps`, and by NOT touching the engine.

Algorithm (mirror `beam.py` structure, swap the score fn + remove engine calls):
1. Seed beam = `[owned]` (the fixed prefix). Build the candidate pool once from Section 4
   sources (dedupe ids; drop ids already in `owned`).
2. For each depth level up to `depth`:
   - Expand every surviving beam by every candidate not already in it.
   - Dedupe by `frozenset(item_ids)` - order-invariant, equal sets scored once
     (`beam.py:18`, `beam.py` dedup). Enforce one-boots-per-build if boots are in the pool
     (`beam.py:16`, `_BOOTS_TAG` @ `beam.py:43`).
   - Score each expansion via `score_build`.
   - Keep top `beam_width` by total score (`beam.py:382` `beams = next_beams[:beam_width]`).
3. Return the best beam as `plan`, the remaining survivors as `alternatives`. Record
   `builds_evaluated` (the bounded-eval acceptance proof; mirror `beam.py:builds_evaluated`
   @ `beam.py:86`).

### 5.1 The unique-passive no-double rule is ENGINE-AUTHORITATIVE

The hard rule (never recommend two items sharing a unique passive) is owned by the engine
dedup, NOT by C2. Source of truth: `agents/daemon_slayer/rank.py:657-665` builds
`current_unique_keys` from `ITEM_EFFECTS[id].unique_passive_key` and `rank.py:759-761`
drops collisions when `filter_shared_uniques=True` (default). The 6 unique-passive families
are engine-internal (`core/build_order.py:36-48` enumerates them in prose: spellblade,
lifeline, immolate, hydra_cleave, fiendhunter_barrage, hellfire_char, innervating_fill -
NOTE the prompt says "6 families", `build_order.py` docstring says "7"; this is a prose
discrepancy, flag R6 - either way DO NOT hardcode the list).

**C2 obligation:** do NOT propose or hardcode a family map (the prompt warns "a guard test
fails on family literals", and `build_order.py:42-47` calls this the "s173 anti-drift
trap"). Instead, C2 inherits the rule two ways:
- The `/api/build-order` seed already enforces it (`build_order.py:501`
  `filter_shared_uniques=True`, never flipped; `unique_passive_safe` flag @
  `build_order.py:318`).
- Each seed row carries `unique_passive_key` + `shares_dead_unique` + `dead_unique_key`
  (engine-supplied: `rank.py:259-263`, mirrored on the client `RankedItem`
  `core/daemon_slayer_client.py:40-44`). C2's beam transition skips appending a candidate
  whose `unique_passive_key` already appears among the build's accumulated keys - using the
  ENGINE-SUPPLIED key, never a C2 literal. Set `BuildPlan.unique_passive_safe=True` by
  construction and assert it in tests (mirror `build_order.py:553-561`).

### 5.2 Beam params

- `beam_width`: 5-8 (spec). Default 6. Validate `>= 1` (mirror `beam.py:226`).
- `depth`: 6 (full build). Validate `1 <= depth <= 6`.
- Pruning rules (master plan `:183`): (1) dedupe-by-set; (2) relative-threshold prune
  (tau ~ 0.85 - keep a child only if its score >= tau * best-sibling-score, RELATIVE not
  absolute); (3) per-parent offspring cap. All three keep `builds_evaluated` bounded.

---

## 6. TEST PLAN (RED-first, ordinal/relative assertions only)

New file `tests/test_planner_beam_search.py` (master plan names it `:183`). Follow the
exact conventions of `tests/test_build_order.py:1-70`: a `FakeEngine`/fake `seed_fn` that
faithfully reproduces the wire shape, injected so NO live dashboard + NO live :8893 engine
is needed (`test_build_order.py:18,31-55`). All assertions are RELATIVE/ordinal - the
project's data-fragile rule forbids exact-value cross-item comparisons (stated verbatim in
`test_ds_preview_e2e_p1l21.py:40-41`: "no hardcoded magic numbers, no fragile cross-item
comparisons").

RED-first invariants (write failing first, then implement):

1. **Beam width respected** - `len(plan.alternatives) + 1 <= beam_width` at every depth;
   survivors never exceed width. (Mirror `beam.py` `beams[:beam_width]`.)
2. **Depth respected** - `len(plan.plan) <= depth - len(owned)`; never exceeds 6 total
   slots; owned prefix preserved in order at the front.
3. **Higher-synergy item ordered above lower for champ X** - with a fake `cohesion_fn`
   that returns a higher value for item A than item B on champ X (and DS deltas held
   equal), the plan orders A before B. ORDINAL: assert index(A) < index(B), never the
   score magnitudes. (This is the C1-reuse contract test; uses the injected `cohesion_fn`,
   so it passes even while C1 is unbuilt - R1.)
4. **Match-specificity** - flipping enemy context (`target_armor` high vs `target_mr`
   high) reorders the plan when the fake seed makes an armor-pen item's `delta_dps` rise
   with armor. Direct regression for "always the same items" (mirror
   `test_build_order.py:8-12` rationale).
5. **No-double unique held** - fake seed includes two items with the same engine-supplied
   `unique_passive_key` (e.g. two "spellblade"); assert the plan contains AT MOST ONE, and
   `plan.unique_passive_safe is True`. Assert C2 never references a family string literal
   (structural: `ast`-scan `planner.py`/`scoring.py` for the known family names, expect
   zero - mirror the structural guard style in `test_ds_preview_e2e_p1l21.py:191`).
6. **Bounded eval count** - `plan.builds_evaluated <= depth * beam_width * pool_size`
   (the `beam.py:24` worst-case bound); assert it is FINITE and below a generous ceiling -
   the "real-time" acceptance proxy. Not an exact count.
7. **Dedupe-by-set** - two orderings of the same item set are scored once (assert
   `builds_evaluated` with a duplicate-inducing pool is strictly less than the naive
   without-dedupe product). Ordinal.
8. **Relative-threshold prune** - a clearly-dominated child (score << tau * best sibling)
   is dropped; a near-tie child is kept. Assert membership, not values.
9. **None contract** - `seed_fn` returning `None` (engine/dashboard down) -> `plan_build`
   returns `None`; blank champion -> `None` (mirror `build_order.py:410,520`,
   `test_build_order.py` engine-down case).
10. **Build-full** - `owned` already 6 items -> non-None `BuildPlan` with empty `plan` +
    explanatory note (mirror `build_order.py:442-446`).
11. **MF SR fixture (B4)** - WHEN WP-B4 lands its fixture, assert the MF SR seed produces
    the expected ordered plan. **B4 does not exist yet** (`Glob tests/test_planner*.py` ->
    none; B4 status OPEN @ `OVERLAY_BUILD_MASTER_PLAN.md:808`). Mark this test
    `skipUnless(fixture present)` so C2 is not blocked on B4 (R7). The fixture assertion is
    ordinal (expected item at expected slot), per B4's own "render + scoring acceptance
    oracle" framing (`:149`).
12. **Explainability** - `ScoreTerms.to_dict()` round-trips all 6 terms + total + stage;
    `total` equals the weighted sum of the parts (intra-row identity, not cross-item).

Optional second JS-free file is NOT needed; C2 is pure Python (the panel/route is WP-C5).

---

## 7. TIER CLASSIFICATION

**Tier-1** (per `OVERLAY_BUILD_MASTER_PLAN.md:186`: "Tier-1 (new modules; no DS engine
change, no ENGINE bump)"). Concretely, for this build:

- New module + its own test file (`tests/test_planner_beam_search.py`). No edits to engine
  files under `agents/daemon_slayer/`.
- **NO `agents.daemon_slayer` import** anywhere in `core/build_planner/`. This is the
  split-brain guard generalized from `routes_state.py:549` (test
  `test_routes_state_has_no_in_process_engine_import` @
  `tests/test_ds_preview_e2e_p1l21.py:191`; the guard `ast`-walks for any import whose
  module starts with `agents.daemon_slayer`). C2 reaches DS ONLY via HTTP seeds (Section
  4.2). RECOMMEND the build agent add the analogous structural guard for the new package
  (test invariant 5 above already covers family literals; add an import-scan twin).
- **NO `ENGINE_VERSION` bump.** C2 does not touch the engine; the version lives in
  `agents/daemon_slayer` and is owned by the engine (`test_ds_preview_e2e_p1l21.py:20-21`).
  C2 must not import or assert it (contrast the shadow modules that DO read
  `ENGINE_VERSION`, e.g. `core/anvil_shadow.py:124` - C2 is NOT a shadow).
- **NOT Share-mirrored.** The `Share/` tree mirrors the DS engine package
  (`Share/src/agents/daemon_slayer/rank.py` exists per `Glob`). C2 is a `core/` consumer,
  not an engine artifact - it does not get copied into `Share/`. No Share package commit
  ritual for this WP.

---

## 8. LOADER PATTERN (if C2 reads any data file)

If C2 needs the situational-set ids or any champion/item data file directly, mirror the
fail-soft loader in `core/archetype_picks.py:174-220`:
- patch resolution: `data/daemon_slayer/current.txt` -> patch string
  (`archetype_picks.py:174-180`, `_DS_DIR` @ `:146`).
- read `data/daemon_slayer/<patch>/items.json` / `champions.json`
  (`archetype_picks.py:197`).
- fail-soft to an empty map on any read/parse error (`archetype_picks.py:215-218`), cache
  behind a lock (`_AXIS_LOCK` @ `:150`, `_DAMAGE_AXIS_CACHE` pattern), with an
  invalidation hook (`_invalidate_axis_cache` @ `:231`).
This is the same pattern C1 was specified to mirror; C2 should too. NOTE: in C2 most data
arrives pre-resolved inside the HTTP seed payload (item names, gold, deltas), so a direct
file read may be unnecessary except for the fixed situational set + any kit data the
cohesion adapter needs (which is really a C1 concern - R1).

---

## 9. OPEN RISKS / DECISIONS FOR THE BUILD AGENT

**R1 (BLOCKER) - C1 `synergy_score` does not exist; cohesion term has no backing.**
Section 0 proves WP-C1 is unbuilt despite the prompt's "C1 is DONE". The build agent MUST
choose, explicitly:
  (a) Build WP-C1 first (`core/build_planner/kit_synergy.py` per
  `OVERLAY_BUILD_MASTER_PLAN.md:165-175`, `synergy_score(item, champ) = dot(kit_weights,
  item_vector) + effect_synergy - anti_synergy`), then have C2's default `cohesion_fn`
  call it. This honors the master plan dependency `C1 -> C2` (`:645`) and is the
  recommended path. OR
  (b) Ship C2 with `cohesion_fn` as a required-injection / no-op-default seam (cohesion
  term = 0 until C1 lands), delivering candidate-gen + beam + the other 4 score terms now,
  and wiring cohesion when C1 arrives. C2 stays useful and fully tested via the injected
  fake (test invariant 3). This unblocks C2 without faking a C1 API.
  DO NOT scaffold a call to `core.build_planner.kit_synergy.synergy_score` as if it exists
  - it does not, and an unguarded import will hard-fail at runtime.

**R2 - seed source: compose-from-routes vs direct client.** Master plan text says compose
from `/api/ds-preview` + `/api/build-order` (`:182`). That requires a reachable dashboard
HTTP server (port + lifecycle). The alternative (`core.daemon_slayer_client` directly) is
fewer hops but re-implements the route projection + build-order orchestration. Decide and
document; either way NO `agents.daemon_slayer` import.

**R3 - `/api/ds-preview` does not forward all fields C2 wants.** The route projects only
`{item_id, item_name, delta_dps, gold, scorer}` (`routes_state.py:592-597`) and caps at
`top=8` (`:564`). C2's scoring wants `is_terminal`, `dps_per_1k_gold`,
`unique_passive_key`, `shares_dead_unique` (all present on the engine `RankedItem`
`rank.py:251-263` + client mirror `daemon_slayer_client.py:40-44`, but DROPPED by the
dashboard projection). And it wants top-K = 12-15, not 8. Options: (i) widen the
`/api/ds-preview` projection + add a `top` field to `DsPreviewRequest` (touches
`routes_state.py` + `api_schema.py` - still Tier-1, no engine change), or (ii) seed
unique-passive/terminal data from the richer `/api/build-order` `order[]` rows (which DO
carry `locked_family`/`excluded_family`, `build_order.py:288-300`) and accept top=8 from
ds-preview. Flag for decision; (i) is cleaner for the beam's overcap/legality terms.

**R4 - partial-build DPS term double-counting.** Each `/api/ds-preview` `delta_dps` is a
MARGINAL delta computed against the SAME fixed `owned` baseline (`rank.py:781`,
`routes_state.py` passes `items` once). Summing deltas for a multi-item beam frontier
double-counts diminishing returns. Decide: (a) re-seed ds-preview per beam node with that
node's `item_ids` as `items` (accurate, but N HTTP calls = latency, fights "real-time"),
or (b) use the single marginal delta as an ORDINAL signal only and lean on cohesion/spike
for set-level value (cheaper, ordinal-honest, matches the data-fragile test posture). (b)
is recommended for C2; (a) is a C4-replan refinement.

**R5 - stage weight magnitudes are unspecified.** The shape is fixed (Section 3.2); the
numbers are operator-tunable and must NOT be asserted by exact value in tests. Build agent
picks sane starting constants; tests assert only relative ordering across stages.

**R6 - family count prose drift (6 vs 7).** Prompt says "6 unique-passive families";
`core/build_order.py:36-48` docstring enumerates 7 (adds `hydra_cleave`, Iter 3). This is
PROSE only and does NOT affect C2 (the rule is engine-authoritative, C2 hardcodes no
list). Noted so the build agent does not "correct" one to match the other.

**R7 - WP-B4 MF SR fixture is not built.** It is C2's acceptance oracle (`:155,187`) but
its status is OPEN (`:808`) and no `tests/` fixture exists. The MF-fixture test (invariant
11) must be `skipUnless`-gated so C2 ships + passes independently; un-skip when B4 lands.

**R8 - dashboard port / server lifecycle for the HTTP seed in tests.** Tests inject a fake
`seed_fn` so this never bites in CI. But the PRODUCTION default `seed_fn` needs the
dashboard base URL/port. Source it from the same config the rest of the dashboard uses
(do not hardcode); fail-soft to `None` when unreachable (Section 4.2). This is the only
real-environment coupling and it is fully behind the injectable seam.

---

## 10. CITED GROUND-TRUTH INDEX (file:line)

- C1 absence: `Glob core/build_planner/**/*.py` (none); `core/archetype_picks.py:592`
  (`get_archetype_for`), `core/archetype_picks.py:223` (`kit_damage_axis`).
- `synergy_score` is plan-only: `docs/OVERLAY_BUILD_MASTER_PLAN.md:172`.
- WP-C1 spec: `docs/OVERLAY_BUILD_MASTER_PLAN.md:165-175`.
- WP-C2 spec + scoring formula: `docs/OVERLAY_BUILD_MASTER_PLAN.md:177-188` (formula `:184`).
- Dep graph C1->C2: `docs/OVERLAY_BUILD_MASTER_PLAN.md:645`. B4 status OPEN: `:808`.
- DS ranker output shape (`RankedItem`): `agents/daemon_slayer/rank.py:243-303`
  (`unique_passive_key` `:263`, `shares_dead_unique`/`dead_unique_key` `:259-261`,
  `is_terminal` `:251`, `dps_per_1k_gold` `:255`). `rank_items` `:527`.
- Engine no-double dedup: `agents/daemon_slayer/rank.py:657-665` (`current_unique_keys`),
  `:759-761` (collision drop on `filter_shared_uniques`).
- Existing build-order engine + 6/7-family prose + anti-drift trap warning:
  `core/build_order.py:36-48`; `plan_build_order` `:370`; None contract `:410,:520`;
  `filter_shared_uniques=True` pinned `:501`; `unique_passive_safe` `:318,:553-561`;
  injectable `rank_fn` `:386,:413`; stable-constant copy discipline `:72`,`:95`.
- Existing DS beam (prior art to mirror, do NOT import): `agents/daemon_slayer/beam.py:1-27`
  (algorithm), `:190` (`beam_search_build`), `:226` (width validation), `:382` (prune),
  `:86` (`builds_evaluated`). DS server `/beam` route `agents/daemon_slayer/server.py:1649`
  (NOT exposed via dashboard route table).
- `/api/ds-preview` handler: `dashboard/routes_state.py:498`; projection `:592-597`;
  `top=8` call `:562-564`; response envelope `:634-642`; route reg `:932`.
- `/api/build-order` handler: `dashboard/routes_state.py:858`; `plan_build_order` call
  `:892-899`; response `:905-907`; route reg `:933`.
- Wire schemas: `dashboard/api_schema.py:93` (`DsPreviewRequest`), `:101` (`DsPreviewItem`),
  `:109` (`DsPreviewResponse`), `:119` (`BuildOrderRequest`).
- Dispatcher unified `delta` key per scorer: `core/daemon_slayer_client.py:935`
  (`rank_for_primary_archetype`), `:1038/:1114/:1155/:1191/:1240` (per-scorer `"delta"`).
- HTTP client boundary (:8893, fail-soft): `core/daemon_slayer_client.py:26-28,:59`;
  client `RankedItem` mirror `:31-56`.
- Split-brain guard: `dashboard/routes_state.py:547-549` (comment) +
  `tests/test_ds_preview_e2e_p1l21.py:183-237` (the three `ast` import-scan guards).
- Loader pattern (fail-soft, current.txt -> patch -> json): `core/archetype_picks.py:146`
  (`_DS_DIR`), `:174-220`, `:150` (`_AXIS_LOCK`), `:231` (cache invalidation).
- Test conventions to mirror: `tests/test_build_order.py:1-70` (fake engine injection);
  data-fragile rule verbatim `tests/test_ds_preview_e2e_p1l21.py:40-41`.
- LEDGER has no item 660 / no WP-C1/C2: `docs/LEDGER.md` latest item 344 (2026-06-07).

---

## 11. SUMMARY FOR THE BUILD AGENT

Ship `core/build_planner/{__init__,scoring,planner}.py` + `tests/test_planner_beam_search.py`
as a Tier-1 module: pure-Python beam search over ordered partial builds, seeded over HTTP
from `/api/ds-preview` `ranked[]` + `/api/build-order` `order[]` (injectable `seed_fn`),
scored by an explainable weighted model whose DPS term is READ from the seed (never
recomputed), whose no-double-unique legality is INHERITED from the engine-supplied
`unique_passive_key` (no family literals), and whose `cohesion` term routes through an
injectable `cohesion_fn`. **First resolve R1**: C1 is not built - either build it or ship
cohesion as a no-op-default seam. Beam width 5-8 (default 6), depth 6, three prune rules,
bounded `builds_evaluated`. All tests RED-first and ordinal. No `agents.daemon_slayer`
import, no `ENGINE_VERSION` bump, not Share-mirrored.
