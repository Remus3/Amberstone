# Riot Commander — Daemon Slayer Build Engine

Local DPS-math service on `:8893`. Computes actual damage-per-second for any champion × item × target combination using real stat math. No API cost per query.

**Status: FUNCTIONALLY COMPLETE** — ENGINE_VERSION 0.60.0 · 929 tests · 547/547 DDragon purchasable items

## Module map (`agents/daemon_slayer/`)

| File | Purpose |
|---|---|
| `__init__.py` | `ENGINE_VERSION` constant; `start_server()` entry point |
| `server.py` | Flask HTTP; `/rank`, `/dps`, `/health` endpoints |
| `effects.py` | `ItemEffect` registry — 547 entries, DDragon purchasable coverage COMPLETE |
| `dps.py` | `CallContext` dataclass + `compute_dps()` — stat walk, armor/MR pen, on-hit, periodic procs, damage amps |
| `stat_walk.py` | Champion base-stat + per-level growth interpolation |
| `beam_search.py` | `rank_for()` — beam search over item combinations; returns ranked `DpsRow` list with `delta_dps` + `gold` |
| `data_loader.py` | Versioned `DataSnapshot` loader; reads `data/daemon_slayer/<patch>/` |
| `ult_rates.py` | Per-champion ult cast rate lookup from `data/daemon_slayer/ult_cast_rates.json`; 172 champions |
| `tests/` | 929 tests passing |

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
