# Riot Commander - Daemon Slayer Build Engine

Local DPS-math service on `:8893`. Computes actual damage-per-second for any champion × item × target combination using real stat math. No API cost per query.

**Status: FUNCTIONALLY COMPLETE** - ENGINE_VERSION 1.22.0 - 2777 tests · 547/547 DDragon purchasable items · patch 16.10.1. **All 6 archetype scorers wired** through `rank_for_primary_archetype()` - carry → `ds.dps`, tank → `ds.ehp`, bruiser → `ds.hybrid`, mage → `ds.ability`, assassin → `ds.burst`, enchanter → `ds.hps`. Coach integration via `coach_integration/archetype_dispatch.py`: all 4 mode coaches (SR/ARAM/Arena/Brawl) inject scorer-aware DS picks before each Haiku call; legacy `daemon_slayer_picks` shape preserved for dashboard compat. Per-(champion, key) override registries cover 73% of the 171-champion roster: `champion_max_priority.json` / `champion_combo_sequences.json` / `champion_form_index.json` / `champion_block_index.json` (196 entries / 125 champions). The single-int/list `block_index` registry is **provably saturated** for new champions (s223 5-way scan of all 47 uncovered champs → 0 candidates) AND exhausted on unmapped keys of covered champs (s224→s225 pre-filter over all 125, re-run post-parser-fix → only Bel'Veth R + Varus W were clean finds); further growth needs the conditional-target-state schema lift or upstream Meraki data fixes. The sibling `champion_form_index.json` (12 champions after the s226 sweep - Swain R / Briar W / Evelynn E added: the canonical recast/empowered form the engine was defaulting away from) is likewise swept; remaining multi-form gaps are R-gated or contextual transforms (Heimer W/E, Gnar, RekSai, Skarner Q). `champion_max_priority.json` (15 champions after the s227 audit - Brand/Talon/Fiddlesticks W-first added) and `champion_combo_sequences.json` are **play-pattern registries**: the numeric pre-filter over-flags (its level-11 optimum ≠ real in-game max order - e.g. it flags Azir W-first vs the universal Q-max), so they are meta-curated, NOT numeric-swept; combo_sequence was assessed adequate for its reset/chain purpose (no clean adds). Extractor `_canonicalize_unit()` (s223) strips Meraki's nested conditional `(+ ...)` parentheticals; `_UNIT_TO_FIELD` (s224) additionally pins the text-drift health-unit family (double-space / "the target's" / caster pronoun+name) - together these recovered the %-HP damage component (previously trapped in `unparsed_modifiers`) on ~22 champions incl. Gwen Q·R, Varus W, Trundle R + Fiddlesticks Q (the latter two were 0 entirely), Cho'Gath E, K'Sante W, Sett Q, Sejuani W, Zac Q. Cooldown inheritance from form 0 when non-form-0 has `cooldown=None` (Riven R / Renekton E / AurelionSol R / Qiyana Q - s206).

## Module map (`agents/daemon_slayer/`)

| File | Purpose |
|---|---|
| `__init__.py` | `ENGINE_VERSION` constant; `start_server()` entry point |
| `server.py` | Stdlib `ThreadingHTTPServer`; `/rank`, `/dps`, `/health`, `/snapshot`, `/beam`, `/ehp`, `/rank-tank`, `/hybrid`, `/rank-bruiser`, `/ability-dps`, `/rank-mage`, `/burst`, `/rank-assassin`, `/hps`, `/rank-enchanter` endpoints |
| `effects.py` | Re-export facade (s246 split) - the 14 effect-aggregation logic fns (`collect_effects`, `total_*`, `effective_target_armor/mr`) + full public-surface re-export. Logic only |
| `_effects_types.py` | **s246** - schema types + damage-type constants (`CallContext`, `DamageFn`, `PeriodicProc`, `ItemEffect`, `PHYSICAL/MAGICAL/TRUE`). Zero deps |
| `_effects_data.py` | **s246** - the `ItemEffect` registry: 547 entries, DDragon purchasable coverage COMPLETE. Patch-pinned per `current.txt`; refresh on patch bump |
| `dps.py` | `CallContext` dataclass + `compute_dps()` - stat walk, armor/MR pen, on-hit, periodic procs, damage amps |
| `ehp.py` | **Phase 1 (s174)** - `compute_ehp()` + `EhpResult` + `rank_items_by_ehp()` + `EhpRankResult` - Tank EHP scorer; HP / armor_factor math with caller-supplied AD/AP/true enemy shares; ARAM `aramDamageTaken` modifier folded in |
| `hybrid.py` | **Phase 2 (s175)** - `compute_hybrid()` + `HybridResult` + `rank_items_by_hybrid()` - Bruiser hybrid scorer; composes `compute_dps` × `compute_ehp` weighted by per-champion (α,β) from `archetype_weights.json`; normalized-percentage-delta sort keeps weights intuitive across the ~10× DPS/EHP magnitude gap |
| `abilities.py` | **Phase 4a (s177)** - `AbilitiesSnapshot.load()` + `AbilityForm` + `DamageBlock` + `load_default()` singleton - champion ability data loader for the Meraki bulk ingest at `data/daemon_slayer/<patch>/champion_abilities.json`. 171/172 champions × P/Q/W/E/R (multi-form preserved); per-rank `cooldown`/`cost`/`damage_blocks[]` with typed scaling fields (`base`, `total_ad_pct`, `bonus_ad_pct`, `ap_pct`, `caster_max_hp_pct`, `caster_bonus_hp_pct`, target HP family, `target_armor_pct`, `bonus_armor_pct`, `bonus_mr_pct`, `caster_max_mp_pct`) |
| `ability_dps.py` | **Phase 4b + 4c (s178/s179)** - `compute_ability_dps()` + `AbilityDpsResult` + `AbilitySpellDps` + `AbilityContext` (4b evaluator) **plus** `rank_items_by_ability_dps()` + `AbilityDpsRankedItem` + `AbilityDpsRankResult` (4c ranker). Per-spell evaluator resolves Q/W/E/R at the canonical rank-at-level for the operator's max-priority order (Q-first default, configurable); sums first damage block's per-rank scaling × resolved caster context; applies mode multiplier + AP cross-derivations + damage amps + per-spell magic_amp on magic-typed spells; routes mitigation per damage type. Multiplies post-mitigation damage by measured `casts/sec` from `cast_rates.get_spell_casts_per_sec` (rewind-derived); falls back to `1/cooldown × mana_uptime` when no data. Ranker uses the same `_filter_candidates` pipeline as `rank_items` / `rank_items_by_hybrid` (purchasable + mode-legal + budget + terminal-only + dead-unique dedup) and scores each candidate by total-ability-DPS delta over the baseline. Sort keys: `delta` (raw) + `efficiency` (per 1k gold). `/ability-dps` + `/rank-mage` routes on `:8893` |
| `burst.py` | **Phase 5 (s180)** - `compute_burst_damage()` + `BurstResult` + `ComboCast` (per-combo evaluator) **plus** `rank_items_by_burst()` + `BurstRankedItem` + `BurstRankResult` (assassin ranker). Walks a caller-supplied `combo_sequence` (default `("Q","W","E","AA","R","AA")`; tokens `AA` / `P` / `Q` / `W` / `E` / `R` / `Q2`-`R2` for repeats at same rank), fires each spell once at level-resolved rank via shared `_evaluate_block` / `_select_blocks` from `ability_dps`, applies full Phase 4b amp pipeline (Rabadon, Liandry, Demonic Embrace, Abyssal Mask magic-only, Riftmaker HP→AP, Mejai's stacked AP) + mitigation pipeline (lethality + flat + % pen). Auto-attacks contribute build's per-hit `avg_attack_dmg` from `compute_dps` (post-armor + mode, no on-hit periodic procs - Phase 5.5 deferral). `/burst` + `/rank-assassin` routes on `:8893` |
| `hps.py` | **Phase 6 (s181)** - `compute_hps()` + `HpsResult` + `HpsItemContribution` (evaluator) **plus** `rank_items_by_hps()` + `HpsRankedItem` + `HpsRankResult` (enchanter ranker) **plus** `EnchanterFormulasSnapshot` + `EnchanterItemFormula` (curated formula loader + singleton `load_default_formulas()`). Total throughput = (healing_raw + shielding_raw) × product(1 + amp_pct) × mode_mult + sum(buff_credit). Per-item formulas from `data/daemon_slayer/<patch>/enchanter_items.json` (9 enchanter items hand-curated: Moonstone 30% chain amp, Redemption AoE heal 150→350, Mikael's single-target heal + cleanse, Helia Soul Siphon 50 HP × 0.4/s, Ardent +15 ally_buff_credit, Staff +12, Locket AoE shield 290→360, Mandate +6, Knight's Vow +10). ARAM `aramShieldsHealing` modifier applied if present. Operator override `targets_per_proc_override` retunes "average teammate" assumption (Arena 2v2 → 1). `/hps` + `/rank-enchanter` routes on `:8893` |
| `data/daemon_slayer/<patch>/enchanter_items.json` | (s181) Hand-curated per-item heal/shield/buff formula registry - 9 entries each carrying `heal_per_proc_base/per_level/ap_scaling`, `procs_per_second`, `targets_per_proc`, mirror fields for shielding, `heal_shield_amp_pct`, `ally_buff_credit_per_second` |
| `hybrid.py` | **Phase 2 (s175)** - `compute_hybrid()` + `HybridResult` + `rank_items_by_hybrid()` + `HybridRankResult` - Bruiser hybrid scorer (α·dps + β·ehp); per-champion (α,β) overrides in `archetype_weights.json`; ranker sorts by normalized percentage delta |
| `archetype_weights.json` | (s175) Per-champion bruiser α/β table - 20 entries covering Jarvan IV, Darius, Garen, Camille, Renekton, Sett, Mordekaiser, Riven, Volibear, Nasus, Olaf, Skarner, Hecarim, Udyr, Vi, Xin Zhao, Lee Sin, MonkeyKing/Wukong, Warwick, Trundle; default (0.5, 0.5) |
| `stats.py` | Champion base-stat + per-level growth + DDragon stat-key map |
| `engine.py` | `build_champion()` - leveled base + items + augments → resolved stat block |
| `rank.py` | `rank_items()` - single-slot DPS ranker over filtered candidate pool |
| `beam.py` | `beam_search_build()` - full-build beam search returning top-N complete builds |
| `data_loader.py` | Versioned `DataSnapshot` loader; reads `data/daemon_slayer/<patch>/` |
| `ult_rates.py` | Per-champion cast-rate lookup. Legacy `get_ult_casts_per_sec` (R-only, reads `ult_cast_rates.json`) preserved for Malignance Hatefog backward compat; `get_spell_casts_per_sec(champion, key, mode)` (Phase 4b, s178) reads `spell_cast_rates.json` for all 4 active spells; both derived from rewind_history.db via `scripts/build_spell_cast_rates.py`; 172 champions × 4 spells × 3 mode buckets |
| `tests/` | 2710 tests passing |

## Key data types

- **`ItemEffect`** - frozen dataclass: `periodics`, `damage_amp_pct`, `armor_reduction_pct`, `mr_reduction_pct`, `giant_slayer_*`, `unique_passive_key`, `defensive_only` flag
- **`PeriodicProc`** - `every_n_attacks` or `every_n_seconds`; `bonus_damage` is `(CallContext) -> float`
- **`CallContext`** - `base_ad, bonus_ad, level, ap, target_max_hp, caster_max_hp, caster_bonus_hp, targets_in_rotation, caster_max_mp, caster_bonus_armor, caster_lethality, ult_casts_per_sec`
- **`unique_passive_key`** - prevents double-counting when multiple items share named passives (e.g. `"spellblade"`, `"immolate"`)

## DS-before-Haiku pattern (required in all coaches)

DS `rank_for()` must run **before** `messages.create()` so Haiku sees per-champion DPS-ranked picks in the user turn.

```python
_ds_rows = None
_ds_picks_str = "unavailable"
try:
    _ds_rows = _ds_client.rank_for(champion=champ, level=level, item_ids=owned_ids, mode="ARAM", top=5)
    _ds_picks_str = " > ".join(f"{r.item_name}(+{r.delta_dps:.0f}dps,{r.gold}g)" for r in _ds_rows) if _ds_rows else "none"
except Exception as e:
    logger.debug("daemon_slayer pre-call: %s", e)
# user turn includes DS top items line
# post-Haiku: reuse _ds_rows for cur["daemon_slayer_picks"] - no second engine call
```

## Phase 3 archetype picker + dispatcher (s176)

Operator-facing scorer selection lands in three layers:

- **Storage**: `core/archetype_picks.py` - DDragon-tag → archetype default + per-champion override persisted to `data/cs_archetype_picks.json`. Six canonical archetypes: `carry`, `bruiser`, `tank`, `mage`, `assassin`, `enchanter` - all six implemented and wired through `rank_for_primary_archetype()` (carry → ds.dps, bruiser → ds.hybrid, tank → ds.ehp, mage → ds.ability, assassin → ds.burst, enchanter → ds.hps); no dispatcher fallbacks remain (s174-s181).
- **REST**: `GET /api/cs-archetype-pick?champion=X` returns merged pick (override OR default). `POST /api/cs-archetype-pick {champion, primary, secondary?, source?}` persists. `POST {champion, clear: true}` rolls back to default.
- **Dispatch**: `core.daemon_slayer_client.rank_for_primary_archetype(champion, archetype, …)` returns `{ok, scorer, archetype, ranked, fell_back}`. Coaches read the picked archetype via `coach_integration/archetype_dispatch.py` (s182); all 4 mode coaches inject scorer-aware DS picks before each Haiku call.
- **UI**: 6-button 3×2 picker grid in the My Pick card of the champ-select view. Clicks save to `localStorage.rc-cs-archetype-<champion>` + POST. Unimplemented scorers grayed but still clickable.

## Coach integration status

| Coach | DS call | Position | Pre-DS rules pruned |
|---|---|---|---|
| `coaches/aram_coach.py` | ✅ | Before Haiku | ✅ (−37% system prompt) |
| `coaches/arena_coach.py` | ✅ | Before Haiku | ✅ |
| `coaches/brawl_coach.py` | ✅ | Before Haiku | ✅ |
| `coach_integration.py` (SR) | ✅ | Before Haiku | - |
| TFT | N/A | N/A | N/A |

## Permanently deferred items (3)

1. **Lightning Braid** - no formula in Meraki; also DPS-negative (−20% ability damage reduction)
2. **Kinkou Jitte** - directional weakpoint; positional geometry unmodelable
3. **Mejai's Arena mirror** - no Arena ID in DDragon (3041 SR only)

**Key insight**: check Meraki `passives[].cooldown` before deferring any "ability-triggered" item. If an item CD exists, use `every_n_seconds=CD` - no ability-frequency data needed.

## Calibration pipeline

`core/ds_calibration.py` appends picks per game tick to `data/ds_calibration.jsonl`. After 50+ games, run calibration analysis: join log vs `rewind_history.db` on (champion, mode, ~ts). Status: accumulating.

## Arena-specific: Arcane Sweeper

Every Arena player receives Arcane Sweeper in the trinket slot - exclude it from DS candidate pool when `mode=ARENA`. The beam search filters `defensive_only` items; Arcane Sweeper is handled separately.
