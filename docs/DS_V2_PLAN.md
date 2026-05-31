# Daemon Slayer V2 - Bounded Combat Simulator (plan + module contracts)

_Authored 2026-05-30 (headless-upgrade run). Supersedes nothing; ADDITIVE to the
ENGINE 1.63.0 steady-state engine. This doc is the shared contract every V2 slice
builds against so the net-new modules compose without conflict._

## 1. Why V2

DS V1 is a STEADY-STATE per-second damage calculator: it answers "what is this
champion's DPS / burst / EHP against a target right now" assuming **infinite
resources** and **no time dimension** beyond cooldowns. It is functionally
complete for build ranking and that is its job.

The gaps V1 closes by design (each explicitly flagged in source):

1. **Infinite mana.** `combo.py` docstring: "NO regen / mana-gating between
   actions ... RC's per-cast damage is mana-independent (the burst walker credits
   each authored cast)". A mana champion in V1 can cast forever. Real fights are
   bounded by the mana pool + regen. THE flagship V2 correction.
2. **No rune proc layer.** item 226 verified "RC has zero rune-proc layer".
   Electrocute / Dark Harvest / Arcane Comet / Press the Attack / Conqueror etc.
   contribute real combat damage + amps that V1 ignores entirely.
3. **No cross-interaction scenario validation.** V1 answers one (champion, build,
   target) tuple per call. Nothing sweeps a MATRIX of fights/combos and asserts
   the math holds across it (monotonicity, family-dedup, mode scaling).
4. **Ability heal/shield is active-only, lower-bound.** `ability_hps.py` v1 skips
   passive-P heal/shield (Aatrox/Vladimir/DrMundo) + target-relative units
   (Taric W bonus-armor-scaled). Flagged lower-bound.
5. **Self-shred uplift unmodeled.** `modifier_blocks.py` classifies `target_shred`
   (Nasus E armor shred etc.) but nothing computes the DPS uplift from shredding
   the target's own resistances over a fight.

V2 = a **bounded combat simulator**: a fight has finite mana, runs over a
timeline, procs runes + passives, and is validated across expansive scenario
matrices. V1 stays the fast ranking path; V2 is the correctness + simulation path.

## 2. Architecture (additive; no V1 scorer is rewritten this run)

```
                       V1 (steady-state, ENGINE 1.63.0 - unchanged)
  stats.py  ->  dps/ability_dps/burst/ehp/hps  ->  hybrid/rank  ->  :8893 scorers
       |                    |
       |                    | per-cast damage + cost (ComboCast.cost)
       v                    v
  V2 substrate (NEW, additive, not wired into live scorers this run)
   mana_sim.py        bounded rotation: finite mana pool + regen gating
   rune_procs.py      keystone/proc rune damage + amp registry
   self_shred.py      target_shred -> own-DPS uplift over a fight
   ability_hps.py v2  passive-P + target-relative heal/shield (edit)
   scenario_matrix.py cross-interaction sweep + invariant assertions
```

Each V2 module is fail-soft (mirrors `combo.py` / `cooldown_watch.py`), pure
(no I/O beyond the patch-pinned JSON the loaders already read), ASCII-only, and
property-tested. None bumps ENGINE_VERSION this run (additive substrate, nothing
consumes them in the live :8893 scorers - same call as item 226 shipping
`ability_hps.py` + `modifier_blocks.py` with NO bump). The enchanter-HPS scorer
that WIRES `ability_hps` into hybrid/rank IS a scoring change and is its own
ENGINE-bump slice, sequenced AFTER the substrate lands.

## 3. Module contracts (build to these signatures)

### 3.1 `mana_sim.py` - bounded rotation (flagship)

```python
@dataclass(frozen=True)
class ManaLedgerHit:   # one cast in the bounded timeline
    index: int; action: str; ability_key: str; t: float
    cost: float; mana_before: float; mana_after: float
    raw: float; mitigated: float; cumulative: float
    status: str  # "ok" | "oom" (insufficient mana) | "on_cooldown"
    note: str = ""

@dataclass(frozen=True)
class ManaBoundedResult:
    champion: str; champion_name: str; level: int; mode: str
    resource_type: str   # "mana" | "energy" | "manaless" | "rage" | ...
    mana_pool: float; mana_regen_per_s: float
    sequence: Tuple[str, ...]; hits: Tuple[ManaLedgerHit, ...]
    casts_allowed: int; casts_requested: int
    mana_spent: float; oom_at_t: Optional[float]
    total_mitigated: float; duration_s: float
    bounded_dps: float          # total_mitigated / duration_s (finite mana)
    unbounded_dps: float        # same walk with infinite mana (V1 parity ref)
    notes: Tuple[str, ...]

def compute_mana_bounded_combo(champion, level, item_ids=None, sequence=None,
        target_armor=0.0, target_mr=0.0, target_max_hp=0.0, target_bonus_hp=0.0,
        mode="SR", snapshot=None) -> ManaBoundedResult: ...
```

- Per-cast damage + `cost` from `burst.compute_burst_damage(..., combo_sequence=seq)`
  exactly as `combo.py` does (so per-hit damage agrees byte-for-byte with the
  burst scorer; NO scoring math duplicated).
- Mana pool = `stats.scaled(base_mp, mpperlevel, level)` + item mana from
  `stats.aggregate_item_stats` (FlatMPPoolMod) + Manamune/Tear-family bonus mana
  already in the item stat blocks. Mana regen/s = `scaled(base_mpregen,
  mpregenperlevel, level)` then **/5** (DDragon mpregen is per-5s) + item mpregen/5.
- Walk: clock from combo cadence; between casts add `regen_per_s * dt`; cap mana
  at pool; on a cast deduct `cost`; if `mana_before < cost` -> `status="oom"`,
  skip, do not advance the spent ledger, note remaining shortfall. `bounded_dps`
  divides the achievable mitigated total by the time the pool sustained.
- **Manaless / energy / rage champions** (`partype` != "Mana" or mp<=0): pool
  treated as effectively infinite -> `bounded_dps == unbounded_dps`, byte-identical
  to V1; surface `resource_type` so the caller knows it was not mana-gated.
- Tear-family note: Manamune/Archangel's/Tear/Seraph's bonus mana already lands in
  the item stat blocks (effects_data batch 27/28); the sim reads the aggregated
  pool, it does NOT re-model Manaflow stacking (steady-state assumption holds).

### 3.2 `rune_procs.py` - keystone/proc rune layer (net-new)

```python
@dataclass(frozen=True)
class RuneProc:
    rune_id: int; name: str; tree: str
    proc_type: str        # "on_proc_burst" | "per_attack" | "stacking_amp" | "adaptive"
    cooldown_s: float     # 0 for no internal CD
    formula: str          # human-readable
    def damage(self, *, level, ad, ap, bonus_hp, ...) -> float: ...

RUNE_PROCS: Dict[int, RuneProc]   # keyed by Riot perk id

def compute_rune_proc_damage(rune_id, level, ad=0.0, ap=0.0, bonus_hp=0.0,
        target_max_hp=0.0, mode="SR") -> float: ...
def keystone_amp(rune_id, base_damage, *, stacks=None) -> float: ...  # Conqueror/PtA-style amps
```

- Cover at minimum the damage/amp keystones + procs: Electrocute (8112),
  Dark Harvest (8128), Arcane Comet (8229), Press the Attack (8005 amp),
  Conqueror (8010 adaptive+amp), Sudden Impact (8143), Cheap Shot (8126),
  Scorch (8237), Comet+. Formulas from DDragon perk descriptions / wiki; pin the
  level/AD/AP/bonus-HP scaling per rune. ASCII formula strings.
- Self-contained registry like `ITEM_EFFECTS`; nothing wires it into a live
  scorer this run (additive). A `compute_rune_proc_damage` smoke per rune.
- Data sourcing: DDragon `runesReforged.json` (already mirrored under
  `data/meta_build/ddragon/<patch>/`) for ids/names/tree; numeric coefficients
  hardcoded with a verbatim formula comment (mirrors effects_data style).

### 3.3 `ability_hps.py` v2 - passive-P + target-relative heal/shield (edit)

- Extend the existing data-driven heal/shield extraction to (a) passive `P`-slot
  heal/shield (Aatrox P heal-on-ability, Vladimir P, DrMundo P regen) and
  (b) target-relative units (Taric W shield scaling off bonus armor; "% of
  bonus armor" unit). Keep v1 active-slot output byte-identical when the new
  paths do not apply. Add tests for the new units; do NOT regress the v1 pins.
- This is the ONLY slice that edits `ability_hps.py`. It does not touch any scorer.

### 3.4 `self_shred.py` - target-shred own-DPS uplift (net-new)

- Consume `modifier_blocks.classify` `target_shred` entries (Nasus E armor shred,
  Corki E armor shred, etc.). Given the champion's own physical/magic damage and
  a target armor/MR, compute the DPS uplift from the shred over a fight window
  (shredded armor -> higher mitigation factor on the champion's OWN subsequent
  damage). Pure function; fail-soft to 0.0 uplift when no shred block applies.
- Reads `modifier_blocks.py` (exists on main) + `dps.armor_mitigation` style math.

### 3.5 `scenario_matrix.py` - cross-interaction sweep + invariants (net-new)

```python
@dataclass(frozen=True)
class ScenarioCell:
    champion: str; level: int; item_ids: Tuple[str, ...]
    target_armor: float; target_mr: float; mode: str
    metric: str; value: float

@dataclass(frozen=True)
class InvariantViolation:
    invariant: str; detail: str; cells: Tuple[ScenarioCell, ...]

def sweep_scenarios(champion, levels, item_sets, target_profiles, modes=("SR",),
        metric="dps", snapshot=None) -> List[ScenarioCell]: ...
def check_invariants(cells) -> List[InvariantViolation]: ...
```

- Harnesses EXISTING scorers only (`compute_dps` / `compute_burst_damage` /
  `compute_combo`) so it is independent of the other V2 slices for parallel merge.
- Invariants asserted across the matrix: physical DPS is non-increasing in
  target_armor; magic DPS non-increasing in target_mr; DPS non-decreasing in level
  for a fixed build; mode multiplier applied consistently; no NaN/negative. Returns
  the violating cells (this is the cross-interaction VALIDATION the operator asked
  for - "expansive scenarios of fights and combinations").
- Tests: a small real-champion matrix (e.g. Caitlyn AD + Lux AP) proving 0
  violations + a synthetic monotonicity probe.

## 4. Slice plan (this run)

Round 1 (parallel, disjoint files, additive, NO ENGINE bump, NO DS restart):
- A `mana_sim.py`        + tests
- B `rune_procs.py`      + tests
- C `ability_hps.py` v2  + tests (edit)
- D `self_shred.py`      + tests
- F `scenario_matrix.py` + tests
- L lolmath changelog verify (READ-ONLY; report NOW/FUTURE/CLOSED, orchestrator
  applies any real data fix to avoid file collision).

Round 2 (sequenced after C lands; ENGINE bump 1.63.0 -> 1.64.0 + pin sync + DS
restart): enchanter-HPS scorer wiring `ability_hps` v2 into a hybrid/rank surface.
Built only if Round 1 lands clean and budget remains; else FUTURE with substrate ready.

## 5. Do-not-redo (carried into every V2 agent)

- DS conditional-target-state arc is operator-CLOSED (s232). Do NOT re-pitch.
- block_index/form_index/max_priority/combo_sequence registries are saturated
  (machine-guarded); growth needs a schema lift, not champion scans.
- Meraki bulk is the data source-of-truth; never aggregator D/aggregator A scrape. Never
  `--force` a Meraki re-extract (the `latest` endpoint is mutable).
- `core/build_order.py` no-double-unique rule is engine-authoritative (6 families).
- Mana: Manaflow/Tear STACKING is intentionally not modeled (steady-state); V2
  reads the aggregated pool, it does not re-stack.
- ASCII only. No em/en dash, no smart quotes. Fail-soft, never raise.
