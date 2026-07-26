# Riot Commander - Daemon Slayer Build Engine

Local DPS-math service on `:8893`. Computes actual damage-per-second for any champion x item x target combination using real stat math. No API cost per query.

**Status: FUNCTIONALLY COMPLETE** - ENGINE_VERSION 1.254.0 - 9746 tests - patch 16.14.1.

## Engine substrate & registries

- `mana_sim.py` finite-mana bounded rotation + `rune_procs.py` keystone/proc rune layer + `self_shred.py` target_shred DPS uplift + `scenario_matrix.py` cross-interaction invariant sweep + `ability_hps.py` v2 passive-P/target-relative heal-shield
- 547/547 DDragon purchasable items
- patch 16.14.1
- Test golden fixtures: `data/daemon_slayer/16.10.1` + `16.11.1` are the only two permanent frozen snapshot dirs (deep-audit P2b gemini ruling, 2026-06-11). New disk pins target 16.11.1; never mint a new fixture dir; 16.9.1 is retired. Guard: `tests/test_ds_fixture_policy.py`.
- cc_pressure aggregator + EHP-vs-CC blended scorer + `compute_hybrid(enemy_champions=...)` cc_blended_ehp scorer + dashboard UI consumer via `dashboard/routes_cc_blended_ehp_threat.py` (cc_blended_ehp ecosystem COMPLETE with 4 consumers: engine math + coach prompt + DS scorer + dashboard UI)
- `_PER_SPELL_CC_DURATIONS` registry 108 entries / 89 champs after wave 9 (item 147 ENGINE 1.43.0: +2 multi-wave coexistence Chogath W silence + Malzahar Q silence; silence joins first-order CC scope per wave 6 stasis precedent; saturated for net-new champions at 16.10.1 - audit walked all 226 unregistered spells of 89 champs) via `_build_per_spell_cc_durations()` setdefault builder
- `agents/daemon_slayer/cc_conditional.py` ships ConditionalCcEntry dataclass + 13 condition tags + 13 operator-tunable midpoints + `coexists_with_unconditional` flag + consumer MAX-rule semantics + `notes` field per spell form (item 188 Slice A) + **72-entry registry across waves 0-23** (per-wave lineage relocated to `docs/history_notes.md`). **cc_conditional ecosystem COMPLETE with 5 consumer surfaces** (cc_pressure + compute_ehp + compute_hybrid engine math, cc_conditional_impact_line coach prompt, routes_cc_conditional_pressure dashboard UI + champ-select chip); default `include_conditional=False` is byte-identical, True opts into the probability-weighted conditional sum with ARAM tenacity through the unified `effective_cc_duration` seam. **All 7 archetype scorers wired** (Slice B adds on-hit AP -> `ds.onhit`, ENGINE 1.216.0) through `rank_for_primary_archetype()` - carry -> `ds.dps`, tank -> `ds.ehp`, bruiser -> `ds.hybrid`, mage -> `ds.ability`, assassin -> `ds.burst`, enchanter -> `ds.hps`, on-hit AP -> `ds.onhit`. Coach integration via `coach_integration/archetype_dispatch.py`: all 4 mode coaches inject scorer-aware DS picks before each Haiku call; legacy `daemon_slayer_picks` shape preserved for dashboard compat. Per-(champion, key) override registries cover 73% of the 171-champion roster: `champion_max_priority.json` / `champion_combo_sequences.json` / `champion_form_index.json` / `champion_block_index.json` (196 entries / 125 champions). All four pure-data registries were swept s223-s232 and are **provably saturated** (machine-guarded; see CLAUDE.md Settled) - further growth needs the conditional-target-state schema lift or upstream Meraki data fixes; max_priority + combo_sequences are play-pattern registries (meta-curated, NOT numeric-swept). Extractor hardening: `_canonicalize_unit()` (s223) strips Meraki's nested conditional `(+ ...)` parentheticals; `_UNIT_TO_FIELD` (s224) pins the health-unit text-drift family - together these recovered the %-HP damage component on ~22 champions. Cooldown inheritance from form 0 when non-form-0 has `cooldown=None` (s206). Full pre-compress narrative: `docs/history_notes.md` (relocated 2026-07-17).

## Changelog

**RELOCATED, NOT FROZEN.** This doc carries no changelog block at all. The entire summary changelog -
entries plus the 1.130.0-1.139.0 / 1.145.0-1.156.0 gap notes and the cc_conditional registry wave
lineage - was moved verbatim to `docs/history_notes.md` on 2026-07-17 (mdclean C6). 1.144.0 is merely
the newest entry that MOVED: it is NOT the current engine version, and this doc is NOT frozen or stale
at it (the live version is the status line at the top of this doc). Canonical per-version entries live
in `agents/daemon_slayer/CHANGELOG.md` + `Share/CHANGELOG.md` + `docs/LEDGER.md`; new ENGINE bumps log
to those canonical files - do not resume a summary changelog here.

## Module map (`agents/daemon_slayer/`)

| File | Purpose |
|---|---|
| `__init__.py` | `ENGINE_VERSION` constant; `start_server()` entry point |
| `server.py` | Stdlib `ThreadingHTTPServer`; 34 routes - core `/health`, `/snapshot`, `/stats`; the DPS + build rankers `/rank`, `/dps`, `/beam`, `/ehp`; the 7 archetype rankers `/rank-tank`, `/hybrid`, `/rank-bruiser`, `/ability-dps`, `/rank-mage`, `/rank-onhit`, `/burst`, `/rank-assassin`, `/hps`, `/rank-enchanter`; the additive scored-axis routes `/anti-tank`, `/extended-duel`, `/sustain`, `/mobility`, `/scaling`, `/waveclear`, `/threat-range`, `/zone-control`, `/objective-damage`, `/cc-output`, `/ally-amp`, `/modifier-summary`; the DSP live-input producer routes `/summoner-fight-adj`, `/enemy-rune-threat`, `/ally-protected-ehp` (OQ18); the DS V2 unified routes `/v2/matchup` + `/v2/fight-report` |
| `effects.py` | Re-export facade (s246 split) - the 14 effect-aggregation logic fns (`collect_effects`, `total_*`, `effective_target_armor/mr`) + full public-surface re-export. Logic only |
| `_effects_types.py` | **s246** - schema types + damage-type constants (`CallContext`, `DamageFn`, `PeriodicProc`, `ItemEffect`, `PHYSICAL/MAGICAL/TRUE`). Zero deps |
| `_effects_data.py` | **s246** - the `ItemEffect` registry: 547 entries, DDragon purchasable coverage COMPLETE. Patch-pinned per `current.txt`; refresh on patch bump |
| `dps.py` | `CallContext` dataclass + `compute_dps()` - stat walk, armor/MR pen, on-hit, periodic procs, damage amps |
| `ehp.py` | **Phase 1 (s174)** - `compute_ehp()` + `EhpResult` + `rank_items_by_ehp()` + `EhpRankResult` - Tank EHP scorer; HP / armor_factor math with caller-supplied AD/AP/true enemy shares; ARAM `aramDamageTaken` modifier folded in |
| `hybrid.py` | **Phase 2 (s175)** - `compute_hybrid()` + `HybridResult` + `rank_items_by_hybrid()` - Bruiser hybrid scorer; composes `compute_dps` x `compute_ehp` weighted by per-champion (alpha,beta) from `archetype_weights.json`; normalized-percentage-delta sort keeps weights intuitive across the ~10x DPS/EHP magnitude gap. **RM-39/RM-43 AD-axis ability term** (DEFAULT-OFF `apply_ad_axis_ability_damage`; L1 ENGINE 1.222.0, L2 1.223.0): `_damage_axis` resolves 92 of 173 champions to `"ad"` and every `_ability_damage` call site gated on `"ap"`, so those 92 were scored on auto-attack DPS alone; `_physical_ability_damage()` now adds an ability term at all three gate sites, summing `compute_ability_dps(...).per_spell` rows whose damage type is in `_AD_AXIS_CREDITED_DAMAGE_TYPES`. L2 widened that set from PHYSICAL to PHYSICAL + TRUE (TRUE has no resist derivative - `_mitigation_factor` returns a flat 1.0 for it). MIXED is HELD (it splits 50/50 armor/MR, so a full credit would import magic-pen valuation; the honest shape is a 50% credit, a separate design) and MAGIC is EXCLUDED PERMANENTLY. Byte-identical at the default, proven by cohort golden diff plus a full build-order regen. Live default-ON flip is operator-gated and additionally blocked on RM-98 (the ability rate is a whole-game average, the auto rate a combat window) |
| `abilities.py` | **Phase 4a (s177)** - `AbilitiesSnapshot.load()` + `AbilityForm` + `DamageBlock` + `load_default()` singleton - champion ability data loader for the Meraki bulk ingest at `data/daemon_slayer/<patch>/champion_abilities.json`. 171/172 champions x P/Q/W/E/R (multi-form preserved); per-rank `cooldown`/`cost`/`damage_blocks[]` with typed scaling fields (`base`, `total_ad_pct`, `bonus_ad_pct`, `ap_pct`, `caster_max_hp_pct`, `caster_bonus_hp_pct`, target HP family, `target_armor_pct`, `bonus_armor_pct`, `bonus_mr_pct`, `caster_max_mp_pct`) |
| `ability_dps.py` | **Phase 4b + 4c (s178/s179)** - `compute_ability_dps()` + `AbilityDpsResult` + `AbilitySpellDps` + `AbilityContext` (4b evaluator) **plus** `rank_items_by_ability_dps()` + `AbilityDpsRankedItem` + `AbilityDpsRankResult` (4c ranker). Per-spell evaluator resolves Q/W/E/R at the canonical rank-at-level for the operator's max-priority order (Q-first default, configurable); sums first damage block's per-rank scaling x resolved caster context; applies mode multiplier + AP cross-derivations + damage amps + per-spell magic_amp on magic-typed spells; routes mitigation per damage type. Multiplies post-mitigation damage by measured `casts/sec` from `cast_rates.get_spell_casts_per_sec` (rewind-derived); falls back to `1/cooldown x mana_uptime` when no data. Ranker uses the same `_filter_candidates` pipeline as `rank_items` / `rank_items_by_hybrid` (purchasable + mode-legal + budget + terminal-only + dead-unique dedup) and scores each candidate by total-ability-DPS delta over the baseline. Sort keys: `delta` (raw) + `efficiency` (per 1k gold). `/ability-dps` + `/rank-mage` routes on `:8893` |
| `burst.py` | **Phase 5 (s180)** - `compute_burst_damage()` + `BurstResult` + `ComboCast` (per-combo evaluator) **plus** `rank_items_by_burst()` + `BurstRankedItem` + `BurstRankResult` (assassin ranker). Walks a caller-supplied `combo_sequence` (default `("Q","W","E","AA","R","AA")`; tokens `AA` / `P` / `Q` / `W` / `E` / `R` / `Q2`-`R2` for repeats at same rank), fires each spell once at level-resolved rank via shared `_evaluate_block` / `_select_blocks` from `ability_dps`, applies full Phase 4b amp pipeline (Rabadon, Liandry, Demonic Embrace, Abyssal Mask magic-only, Riftmaker HP->AP, Mejai's stacked AP) + mitigation pipeline (lethality + flat + % pen). Auto-attacks contribute build's per-hit `avg_attack_dmg` from `compute_dps` (post-armor + mode, no on-hit periodic procs - Phase 5.5 deferral). `/burst` + `/rank-assassin` routes on `:8893` |
| `hps.py` | **Phase 6 (s181)** - `compute_hps()` + `HpsResult` + `HpsItemContribution` (evaluator) **plus** `rank_items_by_hps()` + `HpsRankedItem` + `HpsRankResult` (enchanter ranker) **plus** `EnchanterFormulasSnapshot` + `EnchanterItemFormula` (curated formula loader + singleton `load_default_formulas()`). Total throughput = (healing_raw + shielding_raw) x product(1 + amp_pct) x mode_mult + sum(buff_credit). Per-item formulas from `data/daemon_slayer/<patch>/enchanter_items.json` (9 enchanter items hand-curated: Moonstone 30% chain amp, Redemption AoE heal 150->350, Mikael's single-target heal + cleanse, Helia Soul Siphon 50 HP x 0.4/s, Ardent +15 ally_buff_credit, Staff +12, Locket AoE shield 290->360, Mandate +6, Knight's Vow +10). ARAM `aramShieldsHealing` modifier applied if present. Operator override `targets_per_proc_override` retunes "average teammate" assumption (Arena 2v2 -> 1). `/hps` + `/rank-enchanter` routes on `:8893` |
| `data/daemon_slayer/<patch>/enchanter_items.json` | (s181) Hand-curated per-item heal/shield/buff formula registry - 9 entries each carrying `heal_per_proc_base/per_level/ap_scaling`, `procs_per_second`, `targets_per_proc`, mirror fields for shielding, `heal_shield_amp_pct`, `ally_buff_credit_per_second` |
| `archetype_weights.json` | (s175) Per-champion bruiser alpha/beta table - 20 entries covering Jarvan IV, Darius, Garen, Camille, Renekton, Sett, Mordekaiser, Riven, Volibear, Nasus, Olaf, Skarner, Hecarim, Udyr, Vi, Xin Zhao, Lee Sin, MonkeyKing/Wukong, Warwick, Trundle; default (0.5, 0.5) |
| `stats.py` | Champion base-stat + per-level growth + DDragon stat-key map |
| `engine.py` | `build_champion()` - leveled base + items + augments -> resolved stat block |
| `rank.py` | `rank_items()` - single-slot DPS ranker over filtered candidate pool |
| `beam.py` | `beam_search_build()` - full-build beam search returning top-N complete builds |
| `data_loader.py` | Versioned `DataSnapshot` loader; reads `data/daemon_slayer/<patch>/` |
| `ult_rates.py` | Per-champion cast-rate lookup. Legacy `get_ult_casts_per_sec` (R-only, reads `ult_cast_rates.json`) preserved for Malignance Hatefog backward compat; `get_spell_casts_per_sec(champion, key, mode)` (Phase 4b, s178) reads `spell_cast_rates.json` for all 4 active spells; both derived from rewind_history.db via `scripts/build_spell_cast_rates.py`; 172 champions x 4 spells x 3 mode buckets |
| `tests/` | 11754 tests passing (full tests/ run at 1.216.0, LEDGER 911 verbatim) |

## Key data types

- **`ItemEffect`** - frozen dataclass: `periodics`, `damage_amp_pct`, `armor_reduction_pct`, `mr_reduction_pct`, `giant_slayer_*`, `unique_passive_key`, `defensive_only` flag
- **`PeriodicProc`** - `every_n_attacks` or `every_n_seconds`; `bonus_damage` is `(CallContext) -> float`
- **`CallContext`** - `base_ad, bonus_ad, level, ap, target_max_hp, caster_max_hp, caster_bonus_hp, targets_in_rotation, caster_max_mp, caster_bonus_armor, caster_lethality, ult_casts_per_sec`
- Field lists above are the CORE originals; newer seam fields (DSV1-4 kill-state/amp, R-wave, melee-gate etc.) are appended at the dataclass END per convention - authoritative source: `_effects_types.py` + `dps.py`.
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

- **Storage**: `core/archetype_picks.py` - DDragon-tag -> archetype default + per-champion override. NOTE the two override layers are NOT interchangeable: `data/cs_archetype_picks.json` is **GITIGNORED runtime operator state** (`.gitignore:77`, cleared to `{}` in LEDGER 824 after operator picks polluted the committed precompute), while the git-tracked ROUTE corrections live beside the module as rosters consumed by `default_for_champion` - Slice A `_AP_ASSASSIN_IDS` (inline), Slice B `core/ds_onhit_ap_roster.json`, Slice C `core/ds_support_route_overrides.json` (RM-84, the Support-tag misroute). Seven canonical archetypes: `carry`, `bruiser`, `tank`, `mage`, `assassin`, `enchanter`, `onhit` - all seven implemented and wired through `rank_for_primary_archetype()` (carry -> ds.dps, bruiser -> ds.hybrid, tank -> ds.ehp, mage -> ds.ability, assassin -> ds.burst, enchanter -> ds.hps, on-hit AP -> ds.onhit at ENGINE 1.216.0 / LEDGER 911); no dispatcher fallbacks remain (s174-s181).
- **REST**: `GET /api/cs-archetype-pick?champion=X` returns merged pick (override OR default). `POST /api/cs-archetype-pick {champion, primary, secondary?, source?}` persists. `POST {champion, clear: true}` rolls back to default.
- **Dispatch**: `core.daemon_slayer_client.rank_for_primary_archetype(champion, archetype, ...)` returns `{ok, scorer, archetype, ranked, fell_back}`. Coaches read the picked archetype via `coach_integration/archetype_dispatch.py` (s182); all 4 mode coaches inject scorer-aware DS picks before each Haiku call.
- **UI**: 6-button 3x2 picker grid in the My Pick card of the champ-select view. Clicks save to `localStorage.rc-cs-archetype-<champion>` + POST. Unimplemented scorers grayed but still clickable. NOTE: the grid predates `ds.onhit` - no manual on-hit button yet (LEDGER 911 deferred follow-up); onhit reaches champs via `default_for_champion` roster defaults only.

## Coach integration status

| Coach | DS call | Position | Pre-DS rules pruned |
|---|---|---|---|
| `coaches/aram_coach.py` | yes | Before Haiku | yes (-37% system prompt) |
| `coaches/arena_coach.py` | yes | Before Haiku | yes |
| `coaches/brawl_coach.py` (LEGACY - brawl retired from champ-select s214; backend left as deadcode) | yes | Before Haiku | yes |
| `coach_integration.py` (SR) | yes | Before Haiku | - |
| TFT | N/A | N/A | N/A |

## Permanently deferred items (3)

1. **Lightning Braid** - no formula in Meraki; also DPS-negative (-20% ability damage reduction)
2. **Kinkou Jitte** - directional weakpoint; positional geometry unmodelable
3. **Mejai's Arena mirror** - no Arena ID in DDragon (3041 SR only)

**Key insight**: check Meraki `passives[].cooldown` before deferring any "ability-triggered" item. If an item CD exists, use `every_n_seconds=CD` - no ability-frequency data needed.

## Calibration pipeline

`core/ds_calibration.py` appends picks per game tick to `data/ds_calibration.jsonl`. After 50+ games, run calibration analysis: join log vs `rewind_history.db` on (champion, mode, ~ts). Status: accumulating.

## Arena-specific: Arcane Sweeper

Every Arena player receives Arcane Sweeper in the trinket slot - exclude it from DS candidate pool when `mode=ARENA`. The beam search filters `defensive_only` items; Arcane Sweeper is handled separately.
