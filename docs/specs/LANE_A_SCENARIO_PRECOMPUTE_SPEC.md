# Lane A Scenario Precompute SPEC - Combat-Trigger LANING-Verdict Lookup

Headless run 2026-06-29-01. READ-ONLY planning slice. NO production code in this slice.
PRIMARY north star: drive live claude-haiku-4-5 usage to ZERO by precomputing LANING-phase
coaching verdicts from the deterministic Daemon Slayer (DS) combat substrate so the live
coach reads a lookup table instead of round-tripping the trade question through Haiku.

Verified against the CURRENT tree (HEAD f99de71b; the orchestrator briefed `~4f1d4126`, the
working checkout is at f99de71b - every API below is cited to the f99de71b source).

> Scope boundary, stated up front (charter 4b): this slice = GENERATE + TEST the tables
> OFFLINE. The COACH-FLIP (retiring the live Haiku laning call) is a SEPARATE, gated step,
> currently BLOCKED on a validated real/replayed game. A wrong precompute is worse than a
> Haiku call - do NOT flip blind.

---

## 0. CRITICAL FINDING - this is an EXTENSION, not a greenfield build

The Lane A laning-scenario precompute **already exists and is shipped**. Grounding:

- `core/laning_scenario_precompute.py` - the sweep + persist + fail-soft reader, keyed
  `(my_champ x enemy x level-band x mana-state x cd-state)`, verdicts
  `all_in / trade / back_off / even` (`VALID_VERDICTS`, line 150-152), plus an HZ-A2
  `economy` block (`recall` in `recall_now / back_soon / hold`, `next_spike`, `gold_at_band`).
- Shipped artifacts: `data/daemon_slayer/laning_scenarios/<patch>/laning_scenarios_{sr,aram,arena}.json`
  for patches 16.11.1 / 16.12.1 / 16.13.1. Confirmed schema `laning_scenarios/v3`, compact,
  ASCII, sorted keys (inspected `16.13.1/laning_scenarios_sr.json`).
- `core/precomputed_laning_coach.py` - the request-time READER (HZ-C1): maps live state
  (`band_for_level`, `mana_state_for`, `cd_state_for`) to the discrete keys, emits two A/B
  `CoachChoice` objects. SHADOW ONLY today.
- `dashboard/_deterministic_coaching.py` - the live integration seam: `shadow_log_precomputed_choices`
  logs the precompute verdict alongside the live Haiku verdict to `data/hz_choice_shadow.jsonl`
  for offline agreement validation; `compute_deterministic` serves deterministic A/B choices
  via `core.laning_verdicts.laning_choices` (live DS matchup over :8893) with a TTL cache.
- The flip gate exists: `tools/hz_shadow_report.py` (agreement metric), `tools/replay_laning_verdict_validate.py`
  (replay validator), `tests/test_hz_shadow_live_gate.py` (live-game gate).

Therefore the **actual gap** this SPEC addresses is narrow and precise:

1. **Two of the six required verdict types are MISSING from every cell**: `cooldown-window`
   and `spike-timing`. The substrate for both exists but is UNWIRED into the precompute
   (`agents/daemon_slayer/cooldown_watch.py`, `agents/daemon_slayer/recharge_ledger.py`,
   `agents/daemon_slayer/spike_markers.py`). Confirmed by grepping the shipped artifact's
   key set: only `verdict / net_swing / pct_my_removed / pct_enemy_removed / economy.{recall,
   next_spike, gold_at_band}` are present.
2. **No explicit item-state axis**: the table is itemless (`item_ids=()` throughout). The
   brief's requested `item-state` dimension is absent.
3. **The flip remains gated/blind**: shadow agreement is data-starved (see Blockers).

The four named DS substrate files in the brief (`scenario_matrix.py`, `combo.py`, `mana_sim.py`,
`fight_report.py`) ALL EXIST with the assumed APIs (Section 1). The current shipped precompute
does NOT actually use `scenario_matrix` / `combo` / `fight_report` - it composes
`agents.daemon_slayer.matchup.compute_matchup` (which itself composes `burst` + `engine` +
`mana_sim`). This SPEC keeps `compute_matchup` as the trade primitive and adds the missing
verdicts via the additional substrate.

---

## 1. VERIFY-FIRST API LEDGER (every API the SPEC relies on, cited file:line)

### 1.1 DS combat substrate (the four named files - ALL CONFIRMED PRESENT)

**`agents/daemon_slayer/scenario_matrix.py`** - cross-interaction sweep HARNESS over existing
scorers (no new math).
- `sweep_scenarios(champion, levels, item_sets, target_profiles, modes=("SR",), metric="dps",
  snapshot=None, sequence=None, runes=None) -> List[ScenarioCell]` (line 218). Cross-product
  `levels x item_sets x target_profiles x modes`; `target_profiles` are `(armor, mr[, max_hp,
  bonus_hp])` tuples. `VALID_METRICS = ("dps","burst","combo","mana_bounded_dps","rune_burst")`
  (line 74). Fail-soft: a scorer that raises on a cell -> `value=nan` + note, sweep never aborts.
- `ScenarioCell` (frozen dataclass, line 89): `champion, level, item_ids, target_armor,
  target_mr, mode, metric, value, note`.
- `check_invariants(cells, ad_champions=None, ap_champions=None) -> List[InvariantViolation]`
  (line 362). Named invariants: `dps_non_increasing_in_armor`, `magic_non_increasing_in_mr`,
  `value_non_decreasing_in_level`, `no_nan` / `no_negative`, `mode_multiplier_consistency`.
  **This is the directly-reusable invariant checker for the test plan (Section 7).**

**`agents/daemon_slayer/combo.py`** - action-queue clock simulator over the burst walker.
- `compute_combo(champion, level, item_ids=None, sequence=None, target_armor=0.0, target_mr=0.0,
  target_max_hp=0.0, target_bonus_hp=0.0, mode="SR", snapshot=None, runes=None,
  score_completion_runes=False) -> ComboResult` (line 232).
- `ComboHit` (line 94): per-action row `t, cast_time, cooldown_s, raw, mitigated, cumulative,
  status` (`"ok"` | `"on_cooldown"`). `ComboResult` (line 129): `hits, total_raw,
  total_mitigated, duration_s, notes`. v1 SKIPS on-cooldown re-casts (does not delay).
  **Verdict-relevant outputs**: per-cast cooldown windows (`cooldown_s`, `status="on_cooldown"`
  with remaining-seconds note), damage-over-time (`cumulative`), `duration_s`.

**`agents/daemon_slayer/mana_sim.py`** - finite-mana bounded rotation (DS V2 flagship).
- `compute_mana_bounded_combo(champion, level, item_ids=None, sequence=None, target_armor=0.0,
  target_mr=0.0, target_max_hp=0.0, target_bonus_hp=0.0, mode="SR", snapshot=None,
  gate_ammo=False, apply_ability_haste=False) -> ManaBoundedResult` (line 494).
- `ManaBoundedResult` (line 145): `resource_type, mana_pool, mana_regen_per_s, hits,
  casts_allowed, casts_requested, mana_spent, oom_at_t, total_mitigated, duration_s,
  bounded_dps, unbounded_dps, notes`. `ManaLedgerHit` (line 116): `t, cost, mana_before,
  mana_after, raw, mitigated, cumulative, status` (`"ok"|"oom"|"on_cooldown"|"no_ammo"`).
  **Verdict-relevant outputs**: `mana_pool` / `mana_after` per cast (the mana-state key
  source - already used by `_affordable_sequence`), `oom_at_t`, `casts_allowed`.
  Manaless / non-Mana `partype` -> `mana_pool = inf`, no gate (line 216-220).

**`agents/daemon_slayer/fight_report.py`** - the COMPOSE layer over 7 V2 substrate modules
(NEVER raises; each section try/except'd).
- `compute_fight_report(champion, level=1, item_ids=None, sequence=None, runes=None,
  target_armor=0.0, target_mr=0.0, target_max_hp=0.0, target_bonus_hp=0.0, mode="SR",
  snapshot=None, caster_hp_pct=1.0, game_time_s=0.0, recharge_window_s=10.0, gate_ammo=False,
  apply_ability_haste=False, apply_mode_modifiers=False) -> FightReport` (line 168).
- `FightReport` (line 50) bundles: mana section (`bounded_dps`, `oom_at_t`, `casts_allowed`),
  `recharge_slots` (charge-availability per slot), `missile_slots`, `scenario_cells` +
  `invariant_violations` (it INTERNALLY calls `sweep_scenarios` + `check_invariants`, line
  364-369), `ability_hps_total`, etc. `to_dict()` is JSON-safe (coerces `inf` mana_pool to None,
  line 133). **Use as the single per-(champ,level,build) substrate probe** when a cell needs
  the cooldown + recharge + mana picture in one fail-soft call.

### 1.2 The trade primitive the shipped precompute actually uses

**`agents/daemon_slayer/matchup.py`** - Lane A 1v1 head-to-head (the deterministic Haiku
substitute, module docstring line 1-5).
- `compute_matchup(snapshot, champ_a_id, champ_b_id, level_a, level_b, item_ids_a=None,
  item_ids_b=None, mode="SR", hp_a_pct=1.0, hp_b_pct=1.0, sequence_a=None, sequence_b=None)
  -> MatchupResult` (line 209).
- `MatchupResult` (line 39): `pct_a_removed, pct_b_removed, net_swing, verdict,
  a_can_full_combo, b_can_full_combo, a_casts_allowed, ...`. `net_swing = pct_b_removed -
  pct_a_removed` in [-1,1] (positive = A favored).
- `_classify(net_swing, pct_a_removed, pct_b_removed, a_can_full_combo)` (line 184) - thresholds
  `_ALL_IN_KILL_THRESHOLD=1.0`, `_TRADE_MARGIN=0.10`, `_EVEN_BAND=0.05` (line 34-36). all_in
  requires `pct_b_removed >= 1.0 AND a_can_full_combo AND pct_a_removed < 1.0` (the kill-threshold
  gate - directly satisfies the brief's "all-in verdict requires kill-threshold met" invariant).

### 1.3 Burst per-cast row (the cooldown source for the new verdicts)

**`agents/daemon_slayer/burst.py`**
- `compute_burst_damage(...) -> BurstResult` (line 461). `BurstResult.per_cast` is a tuple of
  `ComboCast` (line 248): `token, is_ability, ability_key, rank, cooldown, cost, damage_type,
  raw_damage, final_damage`. The `.cooldown` field per cast is the live cooldown the
  `cooldown-window` verdict reads.

### 1.4 The cooldown-window + spike-timing substrate (UNWIRED today - the gap)

**`agents/daemon_slayer/cooldown_watch.py`**
- `compute_cooldown_watch(roster, top_n=5) -> CooldownWatchResult` (line 229). `CooldownWatchCard`
  (line 62): `champion, spell_key, spell_name, cc_kind, cc_duration_s, cooldown_s,
  cooldown_by_rank, conditional, probability`. The ENEMY's highest-threat CC ability paired
  with its max-rank base cooldown - "after they whiff <spell>, you have ~<cd>s". Base cooldown
  by rank, NOT haste-adjusted (honesty contract, docstring line 24-31).

**`agents/daemon_slayer/recharge_ledger.py`**
- `compute_recharge_ledger(snapshot, champion, slot, window_s, rank=None, ability_name=None)
  -> RechargeLedger` (line 77). `RechargeLedger` (line 48): `source ("cdragon"|"wiki"|"none"),
  recharge_s, max_charges, charges_at_start, recharges_in_window, total_casts_available`.
  Charge-bearing slots only; `source="none"` otherwise.

**`agents/daemon_slayer/spike_markers.py`**
- `compute_spike_markers(champion, level, item_ids=None, mode="SR", item_count_done=None,
  include_minor=False, annotate_dps=True) -> SpikeMarkersResult` (line 216). `SpikeMarker`
  (line 85): `kind ("level"|"item"), threshold, label, crossed, next, dps_at`.
  `SpikeMarkersResult.next_marker` = the single nearest not-yet-crossed spike. Level spikes
  6/11/16 (+9/13/18 minor); item spikes 1/2/3 finished legendaries. `dps_at` annotates level
  markers via `compute_dps_curve`. **This is the spike-timing verdict source.**

### 1.5 Live coach call sites this would retire (the laning portion)

**SR coach** - `coach_integration/_coach.py`:
- Haiku call: `self._client.messages.create(model=self._model, ...)` at line 370 (model
  `claude-haiku-4-5-20251001`, line 37). `purpose="sr_coach"` (cost_tracker, line 402).
- Request-time inputs available (line 300-323): `game_state.get("champion")`, `level`
  (`game_state.get("level")`), owned items (`game_state.get("items")` -> `_ds_resolve_inventory`),
  enemy comp (`game_state.get("enemy_comp")`), `game_seconds`, `hp`, `hp_max`. **These ARE
  enough to build the lookup key for everything except live mana% and live cooldown state.**

**ARAM coach** - `coaches/aram_coach.py`:
- Haiku calls at line 883 and 1063 (both `claude-haiku-4-5-20251001`). The laning-trade prose
  (`HP > 80% ... ALL-IN`, `HP 60-80% ... POKE`, line 256-257) is exactly the verdict surface
  this table replaces. NOTE: ARAM has no recall (line 263-270) - the `recall` economy verdict
  is suppressed in the ARAM table (already handled by the reader's mode routing).

### 1.6 Live-data key inputs at request time + the missing-producer FLAG

The live read seam already resolves the key from the dashboard payload
(`dashboard/_deterministic_coaching.py::_build_game_state`, line 293):
- `my_champion` (coach.champion or lc.champion), `enemy_comp` (lc.enemy_team), `level`,
  `items` / `my_item_ids` (-> item count), `game_time_s`, `hp_fraction` (`_hp_fraction`,
  line 914), `mana_fraction` (`_mana_fraction`, line 887 - reads `mana`/`max_mana` or
  `mana_pct`).

**FLAG (per `reference_liveclient_no_hud_data`): there is NO Live Client producer for live
ability cooldown state.** Grounded in `dashboard/_deterministic_coaching.py:1019-1022`:

```
# Live ult-cooldown is not surfaced to the coach dict today; default to
# the all_up baseline (cd_state_for(None)). A future event source can
# thread it through here without touching the reader.
ult_up = None
```

`cd_state_for(None) -> "all_up"` (`precomputed_laning_coach.py:212`). Consequence: the
`cd_state` axis is live-keyable ONLY at the `all_up` baseline today; the `no_ult` cells are
generated and shadow-validatable but the live read cannot SELECT them until a cooldown
producer exists. Mana% IS partially live (`_mana_fraction`), but mana-state defaults to
`full` when absent (`mana_state_for(None) -> "full"`, line 198-209). A summoner+ult cooldown
layer DOES exist elsewhere (`core/summoner_cooldowns.py`, `dashboard/_state_cooldowns.py`,
referenced in `cooldown_watch.py` docstring line 27-30) but is NOT threaded into the laning
reader. **Implication for this SPEC**: keep the key built only from fields that ARE live
(champ, enemy, level->band, item-count->item-state, mana%) and treat `cd_state` as a
model-only refinement that defaults to `all_up` live until a producer lands (do NOT block the
table on it).

### 1.7 Existing precompute / persistence precedent (mirror, do not duplicate)

- **Persistence + patch-keying**: `core/laning_scenario_precompute.py::atomic_write` (line 523)
  - tmp + `os.replace`, ASCII, `sort_keys=True`, compact `separators=(",",":")`, one trailing
  newline. `resolve_patch()` reads `data/daemon_slayer/current.txt` (line 500). Output path
  `data/daemon_slayer/laning_scenarios/<patch>/laning_scenarios_<mode>.json` (`_db_path`, line 555).
- **Fail-soft reader**: `load_laning_scenarios(mode, patch)` (line 559) - mtime-aware cache,
  `{}` on any miss/parse error. `lookup(payload, my, enemy, band, mana, cd)` (line 585).
- **Sibling precedents to match**: `core/build_order_precompute.py` + `core/build_order_variants.py`
  (the HZ-B build-order pipeline - curated loadout, DO NOT duplicate), `core/pickban_targets.py`,
  `core/laning_verdicts.py` (the live 1v1 seam). All share the same atomic-write + patch-key +
  fail-soft-`{}` convention.

---

## 2. SCENARIO DIMENSIONS (the lookup key)

Cross product, pruned to live-keyable + tractable. **Existing axes are KEPT as-is** (the shipped
table already ships them); the SPEC ADDS one axis (item-state) and two derived verdict blocks.

| Axis | Values | Source / keyable-live? | Status |
|---|---|---|---|
| `my_champ x enemy` | canonical DDragon id pair | live (`champion` x `enemy_comp[0]`) | EXISTS |
| `level-band` | `L2`(2) `L6`(6) `L11`(11); `L16`(16) maps->L11 on read | live (`band_for_level`); GEN omits L16 (`GEN_BANDS`, line 136) | EXISTS |
| `mana-state` | `full` / `low` (low = affordable prefix at `LOW_MANA_FRACTION=0.35`) | live-partial (`_mana_fraction`; defaults `full`) | EXISTS |
| `cd-state` | `all_up` / `no_ult` | model-only live today (`ult_up=None`->`all_up`); FLAG 1.6 | EXISTS |
| **`item-state`** | **`none` / `one_item` / `two_item`** (0 / 1 / 2 completed core legendaries) | **live (item count from `items`/`my_item_ids`)** | **NEW (this SPEC)** |

### 2.1 Item-state axis (the one new dimension)

- Keyed on **completed-legendary count**, NOT specific items - mirrors `spike_markers`
  `_ITEM_SPIKES = (1,2,3)` and the existing reader's coarse `item_count` proxy
  (`dashboard/_deterministic_coaching.py::_completed_item_count`, line 275). This keeps the
  axis live-keyable (the live coach knows item count, and per-item identity is the separate
  HZ-B build-order pipeline's job - do NOT re-pitch item identity here).
- The concrete item-id list fed to `compute_matchup(item_ids_a=...)` per item-state comes from
  the **already-shipped curated build-order table** (`build_orders_<mode>.json` via
  `dashboard/_deterministic_coaching.py::_full_build_order`): item-state `one_item` = the first
  completed legendary in the champion's balanced build order; `two_item` = first two. This
  REUSES the curated loadout pipeline (charter: mirror, do not duplicate) instead of inventing
  a build.
- Bound the blow-up: 3 item-states x existing (3 bands x 2 mana x 2 cd) = 36 cells per
  `(my,enemy)` pair (was 12). Full-roster `171x171x36 ~ 1.05M cells`. The shipped compact write
  keeps this tractable (the v3 leaf is ~4 short fields); if size is a concern, gate item-state
  by band (item-state is meaningless at L2 - `none` only), reducing to L2:{none}, L6:{none,one},
  L11:{none,one,two} = a pruned ladder. **RECOMMENDED: prune item-state by band** (matches the
  honest "you don't have 2 items at level 2" reality and roughly halves the new cells).

### 2.2 Dimensions explicitly NOT added (do-not-redo)

- Per-item identity axis (that is HZ-B build-order, shipped).
- Live target-state / conditional-target plumbing (operator-CLOSED arc per the brief).
- Enemy item-state asymmetry (the enemy mirrors my level + item-state + cd-state; only MY mana
  varies asymmetrically - this is the existing `_matchup` rule, line 341-366, and must be
  preserved or the mirror-symmetry invariant breaks).

---

## 3. VERDICT SCHEMA (per cell: the 6 verdict types + DS-backed numbers)

Each leaf cell extends the EXISTING v3 leaf. Schema bumps to laning_scenarios/v4. All six
verdict types are derived from deterministic DS engine output - NO LLM in the verdict math.

Leaf cell shape (v4):

- COMBAT verdict (EXISTS - from compute_matchup; covers trade / all_in / back_off):
  - "verdict": "all_in|trade|back_off|even"   (MatchupResult.verdict via matchup._classify)
  - "net_swing": float                         (MatchupResult.net_swing in [-1,1])
  - "pct_my_removed": float                    (MatchupResult.pct_a_removed)
  - "pct_enemy_removed": float                 (MatchupResult.pct_b_removed)
  - "kill_threshold_met": bool                 NEW - pct_enemy_removed >= 1.0 AND a_can_full_combo
    (the all-in gate, surfaced explicitly so the test invariant can assert it)

- ECONOMY / RECALL verdict (EXISTS - HZ-A2; covers recall):
  - "economy": { "recall": "recall_now|back_soon|hold", "next_spike":
    "component|first_item|two_item|three_item|complete", "gold_at_band": float }
    (recall from _recall_verdict, lead_projection-backed)

- COOLDOWN-WINDOW verdict (NEW; from cooldown_watch + the cell per-cast cooldowns):
  - "cooldown_window": {
      "enemy_threat_spell": spell_key       (CooldownWatchCard.spell_key, enemy highest-threat CC)
      "enemy_cc_s": float                    (CooldownWatchCard.cc_duration_s, lockdown if it lands)
      "enemy_cd_s": float                    (CooldownWatchCard.cooldown_s, the punish window)
      "my_ult_cd_s": float                   (my R cooldown at this cell, ComboCast.cooldown for "R")
      "window_verdict": "punish_now|wait_cd|even"
        derived: punish_now when the enemy threat is on cd AND my combo is up; wait_cd when my
        key cd (R) is down (the no_ult axis); else even. Deterministic from the two cooldown
        numbers + the cd_state axis. }

- SPIKE-TIMING verdict (NEW; from spike_markers at this band + item-state):
  - "spike_timing": {
      "next_kind": "level|item"              (SpikeMarker.kind of next_marker)
      "next_threshold": int                   (SpikeMarker.threshold, e.g. 6, 11, or item 1/2/3)
      "next_label": label                     (SpikeMarker.label, "R unlock" / "two items" / ...)
      "crossed_dps_at": float|null            (dps_at the band level, SpikeMarker.dps_at)
      "spike_verdict": "play_for_spike|spike_up|even"
        derived: spike_up when this band/item-state is AT a major spike (R unlock crossed, or the
        item-state just crossed); play_for_spike when the next spike is imminent (gap of 1
        level/item); else even. Deterministic. }

### 3.1 Verdict-type -> DS source map (the no-LLM-in-the-math guarantee)

| Verdict type | DS source (cited) | Deterministic number behind it |
|---|---|---|
| trade | matchup.compute_matchup -> _classify | net_swing >= _TRADE_MARGIN (0.10) |
| all-in | same | pct_enemy_removed >= 1.0 AND a_can_full_combo AND pct_my_removed < 1.0 |
| back-off | same | net_swing <= -0.10 OR (pct_my_removed >= 1.0 AND pct_enemy_removed < 1.0) |
| recall | core.lead_projection via _recall_verdict | gold_at_band vs spike thresholds + mana-state |
| cooldown-window | cooldown_watch.compute_cooldown_watch + ComboCast.cooldown | enemy max-rank CC cd vs my R cd |
| spike-timing | spike_markers.compute_spike_markers | next_marker gap + dps_at at band/item-state |

### 3.2 Determinism note

Every *_verdict derived field is a pure function of DS scalar outputs + the cell discrete axes.
No field consults an LLM. The two NEW derived classifiers (window_verdict, spike_verdict) live
in the precompute module as pure helpers (mirroring laning_band in precomputed_laning_coach.py,
line 235) so they are unit-testable without the engine.

---

## 4. PRECOMPUTE GENERATION APPROACH

Extend core/laning_scenario_precompute.py (do NOT fork a new module - the reader, tests, shadow
logger, and flip gate all import it). Concretely:

1. Add the item-state axis to the sweep: a new ITEM_STATES = ("none","one_item","two_item")
   constant + a build_for_item_state(champ, item_state, mode) helper that reads the curated
   build_orders_<mode>.json (reuse _full_build_order loader pattern) and returns the first
   0/1/2 completed-legendary item ids. Thread the resolved item_ids into the existing
   compute_cell -> _matchup (which already accepts item_ids). Prune by band per 2.1.

2. Add the two new verdict blocks to _cell_from_result:
   - cooldown_window: one compute_cooldown_watch([enemy], top_n=1) call per enemy - memoize
     across bands/mana/item-state (enemy CC cd is level-and-build-invariant per the
     cooldown_watch honesty contract). Pull my_ult_cd_s from the cell own burst.per_cast R-row
     cooldown (already resolved inside compute_matchup; expose it or re-derive via one
     compute_combo call on the my side at the cell level + items).
   - spike_timing: one compute_spike_markers(my, level_for_band(band), item_ids,
     item_count_done=0|1|2) call per (my, band, item-state) - memoize across enemy/mana/cd
     (independent of the enemy + my resource state).

3. The verdict math stays the existing compute_matchup for trade/all-in/back-off. NO new combat
   math; scenario_matrix/combo/mana_sim/fight_report are used as PROBES for the new blocks + the
   test-time invariant sweep, not as a replacement trade engine.

### 4.1 Parallelization / build fan-out (the partitioning)

The generation is embarrassingly parallel along the my_champ (outer) axis - each champion rows
are independent (the enemy side is modelled from shared snapshot data, no cross-champ state).
The existing generator is single-process; this SPEC adds a partitioned offline build:

- Partition key = my_champ (or a contiguous slice of the roster). The CLI already supports
  --champions / --enemies (line 630-633). A build round spawns N worker invocations each with a
  disjoint --champions slice and --out <tmp_partition_dir>, then a single MERGE step concatenates
  the per-partition scenarios dicts into the final per-mode artifact and does ONE atomic_write.
  Disjoint my_champ slices = disjoint top-level scenarios keys = a trivial dict-merge with no key
  collisions.
- This mirrors the orchestrator pattern (1 merger + up to 100 disjoint worktree agents). The
  per-partition artifacts are intermediate (tmp); only the merged table is committed.
- Within a worker, the substrate calls are memoized per Section 4 step 2 (sequence per
  (champ,level,mana,cd) already memoized at line 429; add the cooldown/spike memo caches).

See Section 9 (BUILD FAN-OUT) for the concrete disjoint slices.

---

## 5. PERSISTENCE FORMAT + PATH

Mirror the existing convention exactly (do not invent a new one):

- Path: data/daemon_slayer/laning_scenarios/<patch>/laning_scenarios_<mode>.json
  (<mode> in sr / aram / arena). Patch from current.txt (resolve_patch).
- Write: atomic_write (tmp + os.replace, ASCII, sort_keys=True, compact, one trailing newline) -
  UNCHANGED. A reader polling mid-write must never see a partial file (hard rule).
- Schema string bumps laning_scenarios/v3 -> laning_scenarios/v4 (the reader must accept v4; see
  6.1). dimensions gains item_states: [...] and the two new verdict blocks are nested per leaf.
- Size: with band-pruned item-state (2.1) the full-roster artifact roughly doubles the current
  v3 size (~55MB compact at 467k cells -> ballpark ~110MB at ~1M cells, less with pruning). If
  this is too large for git, the build fan-out can emit per-mode-per-partition shards and the
  reader can lazy-load a shard by my_champ first-letter bucket - but ONLY if the merged single
  file proves unwieldy (start with the single-file convention; do not pre-optimize).

---

## 6. LIVE-READ SEAM (the integration point - defaults to the existing Haiku path)

The seam ALREADY EXISTS and stays shadow-only this slice. The wiring changes are additive:

- Reader: core/precomputed_laning_coach.py gains an item_state_for(item_count) -> str helper
  (parallel to mana_state_for / cd_state_for) and threads item_state through lookup (which gains
  the 6th key step) and precomputed_choices. The two new verdict blocks feed additional
  CoachChoice content (the cooldown-window punish line + the spike-timing play-for-X line) -
  additive chips, not a replacement of the A/B trade chips.
- Live seam: dashboard/_deterministic_coaching.py::shadow_log_precomputed_choices (line 984)
  passes the resolved item_state (from _completed_item_count) into the reader. The served path
  (compute_deterministic) continues to default to the existing core.laning_verdicts.laning_choices
  (live DS matchup) + the coach Haiku path (resolve_choices fallback chain, line 687) UNTIL the
  flip gate clears.
- Defaulting / fail-soft: missing table / uncovered cell -> [] -> the coach keeps its existing
  Haiku path (the reader contract, precomputed_laning_coach.py:504-532). A v4 table read by an
  old reader, or a v3 table read by the new reader, must both degrade to the intersecting fields
  (the new blocks are OPTIONAL in the reader: absent -> no extra chip).

### 6.1 Backward / forward compatibility

- The reader must treat cooldown_window / spike_timing as optional (cell.get(...) with a {}
  default) so a v3 artifact (no new blocks) still yields the trade + recall chips. This matches
  the existing fail-soft style throughout precomputed_laning_coach.py.
- The 6-key lookup must fail-soft to the 5-key behavior when item_state is absent in an old
  payload (descend-only fallback, mirroring the L16->L11 band fallback at line 423-433).

---

## 7. TEST PLAN (ordinal / invariant assertions per the data-fragile rule)

Follow the EXISTING tests/test_laning_scenario_precompute.py conventions: pure-helper tests (no
engine) + a shared-DataSnapshot characterization class + ordinal invariants (never assert exact
damage numbers - data-fragile). Reuse scenario_matrix.check_invariants where it applies.

### 7.1 Characterization (the cell equals a live engine call)

- cooldown_window.enemy_cd_s == compute_cooldown_watch([enemy], top_n=1).cards[0].cooldown_s for
  the same enemy (exact equality - both deterministic).
- spike_timing.next_threshold == compute_spike_markers(my, level, items, item_count_done=k)
  .next_marker.threshold for the same (my, band, item-state).
- The trade fields keep the EXISTING characterization (cell["verdict"] ==
  compute_matchup(...).verdict, current test line 116-133) - regression guard that v4 did not
  perturb v3 numbers.

### 7.2 Ordinal / monotonic invariants (the data-fragile rule)

- all-in gate: every cell with verdict == "all_in" MUST have kill_threshold_met == True AND
  pct_enemy_removed >= 1.0 AND pct_my_removed < 1.0 (the brief named invariant; pins
  matchup._classify).
- spike-timing monotonic in item-state: for fixed (my, enemy, band, mana, cd),
  spike_timing.crossed_dps_at is NON-DECREASING as item-state goes none -> one_item -> two_item
  (more items, more DPS - the brief named invariant). Reuse the _check_monotone helper shape from
  scenario_matrix.
- net_swing non-decreasing in MY item-state (fixed everything else): more of MY items ->
  net_swing does not drop (I out-trade harder). A clean ordinal check; tolerate _MONO_EPS.
- mirror symmetry preserved: same-champ same-level same-cd same-item-state mirror at full mana ->
  net_swing == 0.0, verdict == "even" (the item-575 invariant, existing test line 232-265 - must
  still hold with item-state added on both sides).
- cooldown-window sanity: cooldown_window.enemy_cd_s >= 0 and enemy_cc_s >= 0; a no_ult cell has
  my_ult_cd_s > 0 (ult is on cd by definition of the axis).
- no NaN / no negative across the whole sweep: run scenario_matrix.check_invariants over a
  sweep_scenarios probe of the seed champions at the generated bands/item-states and assert zero
  no_nan / no_negative / value_non_decreasing_in_level violations - this validates the underlying
  substrate the new blocks read from, not just the leaf shape.

### 7.3 Persist + reader round-trip (no engine)

- atomic_write round-trips ASCII v4 JSON; the new blocks survive (extend existing test line 76-83).
- lookup with the 6th item_state key navigates; missing item-state descends to the item-state-none
  cell (new fallback) rather than {}.
- load_laning_scenarios fail-softs to {} on a missing v4 file for every mode (extend line 97-104).
- Reader compat: a v3 payload (no new blocks) read by the v4 reader yields the trade+recall chips
  and NO cooldown/spike chip (no raise).

### 7.4 Shadow / flip-gate (validation, not flip)

- Extend tests/test_hz_shadow_live_gate.py so the shadow logger records the new verdict blocks in
  the hz_choice_shadow.jsonl row (so tools/hz_shadow_report.py can later measure cooldown-window /
  spike-timing agreement). The flip itself stays gated.

---

## 8. TIER CLASSIFICATION

Tier 2 (generate + persist + test offline; additive, no live flip).

Rationale: this slice ADDS two verdict blocks + one axis to an existing shipped, fail-soft,
shadow-only precompute pipeline and its tests. It touches:
- core/laning_scenario_precompute.py (generator + schema v4),
- core/precomputed_laning_coach.py (reader: item-state key + optional new chips),
- dashboard/_deterministic_coaching.py (shadow logger threads item-state + logs new blocks),
- tests/test_laning_scenario_precompute.py (+ shadow gate test).

It does NOT touch any ENGINE scorer (no agents/daemon_slayer/* math change - it only CALLS the
existing substrate), does NOT flip any live served field (Haiku stays the floor), does NOT bump
ENGINE_VERSION, and is fully fail-soft. No frozen-file edits. The COACH-FLIP that would retire
the Haiku call is a separate, higher-tier, operator/Gemini-gated step (Section 0 + Blockers).

---

## 9. BUILD FAN-OUT (disjoint parallel slices for a future build round)

Each slice is a worktree-isolated agent operating on a DISJOINT file set; a single merger
integrates. Slices A-D are code/test (parallel, disjoint files); slice E is the data build
(parallel by roster partition); slice F is the gated flip (sequential, AFTER validation).

- Slice A - generator + schema v4 (core/laning_scenario_precompute.py ONLY): add ITEM_STATES,
  build_for_item_state (reuse curated build-order loader), thread item-state through
  compute_cell/generate_table/lookup/dimensions, add cooldown_window + spike_timing blocks to
  _cell_from_result with the memoized substrate probes, bump schema to v4, add the two pure
  derived classifiers (window_verdict, spike_verdict).
- Slice B - reader (core/precomputed_laning_coach.py ONLY): item_state_for, 6-key lookup thread
  + descend-only fallback, optional new chips from the new blocks (absent-safe).
- Slice C - live shadow seam (dashboard/_deterministic_coaching.py ONLY): thread item_state (from
  _completed_item_count) into shadow_log_precomputed_choices; log the new verdict blocks into the
  shadow row. Served path UNCHANGED (still defaults to Haiku/laning_verdicts).
- Slice D - tests (tests/test_laning_scenario_precompute.py + a new tests/test_lane_a_v4_verdicts.py
  ONLY): all of Section 7 (characterization + ordinal invariants + round-trip + reader compat).
  Disjoint from A-C (test files only).
- Slice E - data build (parallel by roster partition): run the extended generator over disjoint
  --champions slices (e.g. roster split into K contiguous alphabetical buckets), each to
  --out <tmp/partition_k>, for each mode sr/aram/arena. Merger concatenates the per-bucket
  scenarios dicts and does ONE atomic_write per mode -> the committed v4 artifacts. (Depends on
  Slice A landing.)
- Slice F - GATED flip (sequential, NOT in this round): after Slice E artifacts exist AND a
  real/replayed game clears the tools/hz_shadow_report agreement gate, flip the served laning
  field onto the precompute reader. BLOCKED today (see below). Do NOT bundle into the parallel
  round.

Merge order: A (and E depends on A) land first; B, C, D are independent of each other and of E
and can land in parallel; F is deferred.

---

## 10. OPEN RISKS / BLOCKERS

1. FLIP IS BLOCKED - live validation pipeline is down / data-starved (CRITICAL). The
   hz_choice_shadow agreement sample is structurally empty: per docs/LEDGER.md (cycle 55,
   2026-06-16), laning coverage was 45/910 ticks (~5%) with 0/0 comparable-covered agreement
   because NO match has run a genuine ALIVE laning tick under the freshness guard (the live
   aram_coaching_data.json was frozen at a post-game WAIT RESPAWN state). The flip CANNOT be
   validated without a live/replayed game. This SPEC scope is explicitly GENERATE+TEST offline;
   the flip (Slice F) stays gated. A wrong precompute served blind is worse than a Haiku call.

2. No live cooldown producer (FLAG, Section 1.6). ult_up is hardcoded None -> cd_state defaults
   to all_up at read time (_deterministic_coaching.py:1019-1022). The no_ult cells (incl. the new
   cooldown_window block my_ult_cd_s) are GENERATED and shadow-validatable but NOT live-selectable
   until a cooldown producer threads through. Mitigation: the SPEC keeps the key on live-only
   fields and treats cd_state as a model refinement; a future core/summoner_cooldowns /
   dashboard/_state_cooldowns bridge can thread it without touching the reader. Do NOT block the
   table on it.

3. Mana% is only partially live. _mana_fraction reads mana/max_mana if present, else defaults
   full. If the live payload lacks mana, the low cells (and the mana-driven recall) are never
   selected live. Acceptable for offline generation; flagged for the flip-readiness review.

4. Item-state cardinality / artifact size. 3 item-states roughly triple the per-pair cells before
   band-pruning. RECOMMENDED prune (2.1) caps it. If the merged v4 file exceeds a comfortable git
   size, fall back to per-bucket shards in the reader - but only if proven necessary.

5. Item-state build provenance. The item-id list per item-state comes from the curated build-order
   table; if a champion is absent from that table, item-state degrades to none (itemless) - the
   cell is still generated, just without the item bonus. The reader must not over-promise an item
   spike the build table cannot back.

6. cooldown_watch is base-cd, not haste-adjusted, and enemy-CC-only. It reports the enemy single
   highest-threat CC cooldown, not a full ability-cooldown map. The cooldown_window verdict is
   therefore a punish-their-key-CC-whiff signal, NOT a general cooldown tracker - the SPEC names
   it honestly. Champions with no registered first-order CC get no enemy_threat_spell (the block
   degrades to even).

7. spike_markers dps_at can fail-soft to None. compute_dps_curve errors yield dps_at=None (line
   192-193); the monotonic-in-item-state invariant (7.2) must SKIP None cells (a missing point
   cannot prove an ordering break - exactly the scenario_matrix NaN-skip discipline).

8. Do-not-redo guardrails honored. No live target-state plumbing (operator-CLOSED). No rebuild of
   scenario_matrix/combo/mana_sim/fight_report (all confirmed present + used as-is). No LLM in the
   verdict math. The curated-loadout pipeline is REUSED for item-state, not duplicated. Event-mode
   Match-V5 excluded (expected).

---

## Critical Files for Implementation

- C:\Riot Commander\core\laning_scenario_precompute.py    (generator + schema; Slice A)
- C:\Riot Commander\core\precomputed_laning_coach.py       (request-time reader; Slice B)
- C:\Riot Commander\dashboard\_deterministic_coaching.py    (live shadow seam + flip gate; Slice C/F)
- C:\Riot Commander\agents\daemon_slayer\matchup.py         (trade verdict primitive - unchanged, called)
- C:\Riot Commander\tests\test_laning_scenario_precompute.py (characterization + invariant tests; Slice D)
