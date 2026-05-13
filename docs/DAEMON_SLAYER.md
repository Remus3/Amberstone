# Riot Commander — Daemon Slayer Build Engine

Local DPS-math service on `:8893`. Computes actual damage-per-second for any champion × item × target combination using real stat math. No API cost per query.

**Status: FUNCTIONALLY COMPLETE** — ENGINE_VERSION 0.68.0 · 1346 tests · 547/547 DDragon purchasable items · Tank EHP scorer (s174) + Bruiser hybrid scorer (s175) + CS archetype-picker UI + dispatcher (s176) + Phase 4a champion ability ingest (s177) + Phase 4b mage ability DPS evaluator (s178) + Phase 4c mage ability DPS ranker + `/rank-mage` + dispatcher wire-in (s179) + **Phase 5 assassin burst-window scorer + `/rank-assassin` + dispatcher wire-in (s180)** ship the complete Phases 1-5 lift — **5 of 6 archetype scorers are now fully wired** through `rank_for_primary_archetype()` (carry/bruiser/tank/mage/assassin). Only Phase 6 (enchanter HPS) remains — `enchanter` archetype still falls back to `ds.dps` with `fell_back=True`. Coach integration deferred to a follow-up session — the picker persists the operator's pick + the dispatcher is callable, but no coach reads `state.cs_archetype_pick.primary` yet.

## Module map (`agents/daemon_slayer/`)

| File | Purpose |
|---|---|
| `__init__.py` | `ENGINE_VERSION` constant; `start_server()` entry point |
| `server.py` | Stdlib `ThreadingHTTPServer`; `/rank`, `/dps`, `/health`, `/snapshot`, `/beam`, `/ehp`, `/rank-tank`, `/hybrid`, `/rank-bruiser`, `/ability-dps`, `/rank-mage`, `/burst`, `/rank-assassin` endpoints |
| `effects.py` | `ItemEffect` registry — 547 entries, DDragon purchasable coverage COMPLETE |
| `dps.py` | `CallContext` dataclass + `compute_dps()` — stat walk, armor/MR pen, on-hit, periodic procs, damage amps |
| `ehp.py` | **Phase 1 (s174)** — `compute_ehp()` + `EhpResult` + `rank_items_by_ehp()` + `EhpRankResult` — Tank EHP scorer; HP / armor_factor math with caller-supplied AD/AP/true enemy shares; ARAM `aramDamageTaken` modifier folded in |
| `hybrid.py` | **Phase 2 (s175)** — `compute_hybrid()` + `HybridResult` + `rank_items_by_hybrid()` — Bruiser hybrid scorer; composes `compute_dps` × `compute_ehp` weighted by per-champion (α,β) from `archetype_weights.json`; normalized-percentage-delta sort keeps weights intuitive across the ~10× DPS/EHP magnitude gap |
| `abilities.py` | **Phase 4a (s177)** — `AbilitiesSnapshot.load()` + `AbilityForm` + `DamageBlock` + `load_default()` singleton — champion ability data loader for the Meraki bulk ingest at `data/daemon_slayer/<patch>/champion_abilities.json`. 171/172 champions × P/Q/W/E/R (multi-form preserved); per-rank `cooldown`/`cost`/`damage_blocks[]` with typed scaling fields (`base`, `total_ad_pct`, `bonus_ad_pct`, `ap_pct`, `caster_max_hp_pct`, `caster_bonus_hp_pct`, target HP family, `target_armor_pct`, `bonus_armor_pct`, `bonus_mr_pct`, `caster_max_mp_pct`) |
| `ability_dps.py` | **Phase 4b + 4c (s178/s179)** — `compute_ability_dps()` + `AbilityDpsResult` + `AbilitySpellDps` + `AbilityContext` (4b evaluator) **plus** `rank_items_by_ability_dps()` + `AbilityDpsRankedItem` + `AbilityDpsRankResult` (4c ranker). Per-spell evaluator resolves Q/W/E/R at the canonical rank-at-level for the operator's max-priority order (Q-first default, configurable); sums first damage block's per-rank scaling × resolved caster context; applies mode multiplier + AP cross-derivations + damage amps + per-spell magic_amp on magic-typed spells; routes mitigation per damage type. Multiplies post-mitigation damage by measured `casts/sec` from `cast_rates.get_spell_casts_per_sec` (rewind-derived); falls back to `1/cooldown × mana_uptime` when no data. Ranker uses the same `_filter_candidates` pipeline as `rank_items` / `rank_items_by_hybrid` (purchasable + mode-legal + budget + terminal-only + dead-unique dedup) and scores each candidate by total-ability-DPS delta over the baseline. Sort keys: `delta` (raw) + `efficiency` (per 1k gold). `/ability-dps` + `/rank-mage` routes on `:8893` |
| `burst.py` | **Phase 5 (s180)** — `compute_burst_damage()` + `BurstResult` + `ComboCast` (per-combo evaluator) **plus** `rank_items_by_burst()` + `BurstRankedItem` + `BurstRankResult` (assassin ranker). Walks a caller-supplied `combo_sequence` (default `("Q","W","E","AA","R","AA")`; tokens `AA` / `P` / `Q` / `W` / `E` / `R` / `Q2`-`R2` for repeats at same rank), fires each spell once at level-resolved rank via shared `_evaluate_block` / `_select_blocks` from `ability_dps`, applies full Phase 4b amp pipeline (Rabadon, Liandry, Demonic Embrace, Abyssal Mask magic-only, Riftmaker HP→AP, Mejai's stacked AP) + mitigation pipeline (lethality + flat + % pen). Auto-attacks contribute build's per-hit `avg_attack_dmg` from `compute_dps` (post-armor + mode, no on-hit periodic procs — Phase 5.5 deferral). `/burst` + `/rank-assassin` routes on `:8893` |
| `hybrid.py` | **Phase 2 (s175)** — `compute_hybrid()` + `HybridResult` + `rank_items_by_hybrid()` + `HybridRankResult` — Bruiser hybrid scorer (α·dps + β·ehp); per-champion (α,β) overrides in `archetype_weights.json`; ranker sorts by normalized percentage delta |
| `archetype_weights.json` | (s175) Per-champion bruiser α/β table — 20 entries covering Jarvan IV, Darius, Garen, Camille, Renekton, Sett, Mordekaiser, Riven, Volibear, Nasus, Olaf, Skarner, Hecarim, Udyr, Vi, Xin Zhao, Lee Sin, MonkeyKing/Wukong, Warwick, Trundle; default (0.5, 0.5) |
| `stats.py` | Champion base-stat + per-level growth + DDragon stat-key map |
| `engine.py` | `build_champion()` — leveled base + items + augments → resolved stat block |
| `rank.py` | `rank_items()` — single-slot DPS ranker over filtered candidate pool |
| `beam.py` | `beam_search_build()` — full-build beam search returning top-N complete builds |
| `data_loader.py` | Versioned `DataSnapshot` loader; reads `data/daemon_slayer/<patch>/` |
| `ult_rates.py` | Per-champion cast-rate lookup. Legacy `get_ult_casts_per_sec` (R-only, reads `ult_cast_rates.json`) preserved for Malignance Hatefog backward compat; `get_spell_casts_per_sec(champion, key, mode)` (Phase 4b, s178) reads `spell_cast_rates.json` for all 4 active spells; both derived from rewind_history.db via `scripts/build_spell_cast_rates.py`; 172 champions × 4 spells × 3 mode buckets |
| `tests/` | 1346 tests passing (51 in `test_burst.py` + 38 in `test_rank_assassin.py` added in s180) |

## Key data types

- **`ItemEffect`** — frozen dataclass: `periodics`, `damage_amp_pct`, `armor_reduction_pct`, `mr_reduction_pct`, `giant_slayer_*`, `unique_passive_key`, `defensive_only` flag
- **`PeriodicProc`** — `every_n_attacks` or `every_n_seconds`; `bonus_damage` is `(CallContext) -> float`
- **`CallContext`** — `base_ad, bonus_ad, level, ap, target_max_hp, caster_max_hp, caster_bonus_hp, targets_in_rotation, caster_max_mp, caster_bonus_armor, caster_lethality, ult_casts_per_sec`
- **`unique_passive_key`** — prevents double-counting when multiple items share named passives (e.g. `"spellblade"`, `"immolate"`)

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
# post-Haiku: reuse _ds_rows for cur["daemon_slayer_picks"] — no second engine call
```

## Phase 3 archetype picker + dispatcher (s176)

Operator-facing scorer selection lands in three layers:

- **Storage**: `core/archetype_picks.py` — DDragon-tag → archetype default + per-champion override persisted to `data/cs_archetype_picks.json`. Six canonical archetypes: `carry`, `bruiser`, `tank`, `mage`, `assassin`, `enchanter`. Three are implemented today (carry → ds.dps, bruiser → ds.hybrid, tank → ds.ehp); mage/assassin/enchanter route through the dispatcher with `fell_back=True`.
- **REST**: `GET /api/cs-archetype-pick?champion=X` returns merged pick (override OR default). `POST /api/cs-archetype-pick {champion, primary, secondary?, source?}` persists. `POST {champion, clear: true}` rolls back to default.
- **Dispatch**: `core.daemon_slayer_client.rank_for_primary_archetype(champion, archetype, …)` returns `{ok, scorer, archetype, ranked, fell_back}`. Coaches wiring up to read `state.cs_archetype_pick.primary` is the next session's lift; existing coaches continue calling `rank_for()` directly.
- **UI**: 6-button 3×2 picker grid in the My Pick card of the champ-select view. Clicks save to `localStorage.rc-cs-archetype-<champion>` + POST. Unimplemented scorers grayed but still clickable.

## Coach integration status

| Coach | DS call | Position | Pre-DS rules pruned |
|---|---|---|---|
| `coaches/aram_coach.py` | ✅ | Before Haiku | ✅ (−37% system prompt) |
| `coaches/arena_coach.py` | ✅ | Before Haiku | ✅ |
| `coaches/brawl_coach.py` | ✅ | Before Haiku | ✅ |
| `coach_integration.py` (SR) | ✅ | Before Haiku | — |
| TFT | N/A | N/A | N/A |

## Permanently deferred items (3)

1. **Lightning Braid** — no formula in Meraki; also DPS-negative (−20% ability damage reduction)
2. **Kinkou Jitte** — directional weakpoint; positional geometry unmodelable
3. **Mejai's Arena mirror** — no Arena ID in DDragon (3041 SR only)

**Key insight**: check Meraki `passives[].cooldown` before deferring any "ability-triggered" item. If an item CD exists, use `every_n_seconds=CD` — no ability-frequency data needed.

## Calibration pipeline

`core/ds_calibration.py` appends picks per game tick to `data/ds_calibration.jsonl`. After 50+ games, run calibration analysis: join log vs `rewind_history.db` on (champion, mode, ~ts). Status: accumulating.

## Arena-specific: Arcane Sweeper

Every Arena player receives Arcane Sweeper in the trinket slot — exclude it from DS candidate pool when `mode=ARENA`. The beam search filters `defensive_only` items; Arcane Sweeper is handled separately.
