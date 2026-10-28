# Amberstone - Daemon Slayer Build Engine

Local DPS-math service on `:8860`. Computes actual damage-per-second for any champion x item x target combination using real stat math. No API cost per query.

**Status: FUNCTIONALLY COMPLETE** - ENGINE_VERSION 1.290.0 - patch 16.21.1.

## Engine substrate & registries

- `mana_sim.py` finite-mana bounded rotation + `rune_procs.py` keystone/proc rune layer + `self_shred.py` target_shred DPS uplift + `scenario_matrix.py` cross-interaction invariant sweep + `ability_hps.py` v2 passive-P/target-relative heal-shield
- Item coverage at patch 16.21.1, every figure stated beside the population it counts (all re-derived from the data by `tests/test_docs_ds_item_coverage_drift.py`, so a patch bump that moves them fails loudly): `ITEM_EFFECTS` registry 549 entries; DDragon ships 699 items total, of which 537 carry the bare `gold.purchasable` flag and 467 clear the engine's own shop gate `_is_purchasable` (`gold.purchasable` AND `gold.total` > 0 - `agents/daemon_slayer/rank.py:668`, the predicate `_filter_candidates` actually applies, so 467 is the population the scorers can ever rank). 467 of those 467 carry an `ITEM_EFFECTS` entry: no purchasable row is uncredited since 16.21.1 dropped the seven `55xxxx` cosmetics (`550007` Party Favor was the one uncredited row through 16.20.1). The batch-55 coverage gate excludes the `9xxxxx` and `55xxxx` namespaces by prefix (here `994403` Golden Spatula), so coverage over that gate's own population is 466/466. The former `547/547` was ONE number written twice: 547 was `len(ITEM_EFFECTS)` on 2026-05-06 and has never matched any purchasable count at any patch on disk (RM-203).
- patch 16.21.1
- Test golden fixtures: `data/daemon_slayer/16.10.1` + `16.11.1` are the only two permanent frozen snapshot dirs (deep-audit P2b gemini ruling, 2026-06-11). New disk pins target 16.11.1; never mint a new fixture dir; 16.9.1 is retired. Guard: `tests/test_ds_fixture_policy.py`.
- cc_pressure aggregator + EHP-vs-CC blended scorer + `compute_hybrid(enemy_champions=...)` cc_blended_ehp scorer + dashboard UI consumer via `dashboard/routes_cc_blended_ehp_threat.py` (cc_blended_ehp ecosystem COMPLETE with 4 consumers: engine math + coach prompt + DS scorer + dashboard UI)
- `_PER_SPELL_CC_DURATIONS` registry 108 entries / 89 champs after wave 9 (item 147 ENGINE 1.43.0: +2 multi-wave coexistence Chogath W silence + Malzahar Q silence; silence joins first-order CC scope per wave 6 stasis precedent; saturated for net-new champions at 16.10.1 - audit walked all 226 unregistered spells of 89 champs) via `_build_per_spell_cc_durations()` setdefault builder
- `agents/daemon_slayer/cc_conditional.py` ships ConditionalCcEntry dataclass + 13 condition tags + 13 operator-tunable midpoints + `coexists_with_unconditional` flag + consumer MAX-rule semantics + `notes` field per spell form (item 188 Slice A) + **73-entry registry** (65 primary + 8 form-explicit sidecar, 58 champions) across waves 0-23 plus the R14 Ashe R entry (ENGINE 1.150.0) (per-wave lineage relocated to `docs/history_notes.md`). **cc_conditional ecosystem COMPLETE with 5 consumer surfaces** (cc_pressure + compute_ehp + compute_hybrid engine math, cc_conditional_impact_line coach prompt, routes_cc_conditional_pressure dashboard UI + champ-select chip); default `include_conditional=False` is byte-identical, True opts into the probability-weighted conditional sum with ARAM tenacity through the unified `effective_cc_duration` seam. **All 7 archetype scorers wired** (Slice B adds on-hit AP -> `ds.onhit`, ENGINE 1.216.0) through `rank_for_primary_archetype()` - carry -> `ds.dps`, tank -> `ds.ehp`, bruiser -> `ds.hybrid`, mage -> `ds.ability`, assassin -> `ds.burst`, enchanter -> `ds.hps`, on-hit AP -> `ds.onhit`. Coach integration via `coach_integration/archetype_dispatch.py`: all 4 mode coaches inject scorer-aware DS picks before each Haiku call; legacy `daemon_slayer_picks` shape preserved for dashboard compat. Per-(champion, key) override registries cover 77.2% of the 171-champion abilities keyspace (76.3% of the full 173 roster): `champion_max_priority.json` / `champion_combo_sequences.json` / `champion_form_index.json` / `champion_block_index.json` - **132 distinct champions / 167 (champion, registry) entries**, recomputed 2026-07-26. Per registry: block_index 125, max_priority 15, combo_sequences 15, form_index 12. **Count these from the nested `champions` key, never from the file's top level** - the schema is `{_meta, default, champions:{...}}`, so a flat top-level count returns 2 and the earlier "196 entries / 125 champions / 73%" reading was that mis-parse plus block_index's own count mistaken for the distinct total. All four pure-data registries were swept s223-s232 and are **provably saturated** (machine-guarded; see CLAUDE.md Settled) - further growth needs the conditional-target-state schema lift or upstream Meraki data fixes; max_priority + combo_sequences are play-pattern registries (meta-curated, NOT numeric-swept). Extractor hardening: `_canonicalize_unit()` (s223) strips Meraki's nested conditional `(+ ...)` parentheticals; `_UNIT_TO_FIELD` (s224) pins the health-unit text-drift family - together these recovered the %-HP damage component on ~22 champions. Cooldown inheritance from form 0 when non-form-0 has `cooldown=None` (s206). Full pre-compress narrative: `docs/history_notes.md` (relocated 2026-07-17).

## Changelog

**RELOCATED, NOT FROZEN.** This doc carries no changelog block at all. The entire summary changelog -
entries plus the 1.130.0-1.139.0 / 1.145.0-1.156.0 gap notes and the cc_conditional registry wave
lineage - was moved verbatim to `docs/history_notes.md` on 2026-07-17 (mdclean C6). 1.144.0 is merely
the newest entry that MOVED: it is NOT the current engine version, and this doc is NOT frozen or stale
at it (the live version is the status line at the top of this doc). Canonical per-version entries live
in `agents/daemon_slayer/CHANGELOG.md` + `docs/LEDGER.md`; new ENGINE bumps log to those canonical
files - do not resume a summary changelog here. (The Share mirror changelog went with the whole Share
package on 2026-09-07; older entries still name it as history.)

## Module map (`agents/daemon_slayer/`)

| File | Purpose |
|---|---|
| `__init__.py` | `ENGINE_VERSION` constant; `start_server()` entry point |
| `server.py` | Stdlib `ThreadingHTTPServer`; 34 routes - core `/health`, `/snapshot`, `/stats`; the DPS + build rankers `/rank`, `/dps`, `/beam`, `/ehp`; the 7 archetype rankers `/rank-tank`, `/hybrid`, `/rank-bruiser`, `/ability-dps`, `/rank-mage`, `/rank-onhit`, `/burst`, `/rank-assassin`, `/hps`, `/rank-enchanter`; the additive scored-axis routes `/anti-tank`, `/extended-duel`, `/sustain`, `/mobility`, `/scaling`, `/waveclear`, `/threat-range`, `/zone-control`, `/objective-damage`, `/cc-output`, `/ally-amp`, `/modifier-summary`; the DSP live-input producer routes `/summoner-fight-adj`, `/enemy-rune-threat`, `/ally-protected-ehp` (OQ18); the DS V2 unified routes `/v2/matchup` + `/v2/fight-report` |
| `effects.py` | Re-export facade (s246 split) - the 22 public effect-aggregation logic fns (`collect_effects`, `dedupe_context`, the 18 `total_*`, `effective_target_armor`, `effective_target_mr`; counts guarded by `tests/test_docs_ds_effects_facade_s144d21.py`) + full public-surface re-export. Logic only |
| `_effects_types.py` | **s246** - schema types + damage-type constants (`CallContext`, `DamageFn`, `PeriodicProc`, `ItemEffect`, `PHYSICAL/MAGICAL/TRUE`). Zero deps |
| `_effects_data.py` | **s246** - the `ItemEffect` registry: 549 entries (measured `len(ITEM_EFFECTS)` 2026-08-13), DDragon purchasable coverage COMPLETE. Patch-pinned per `current.txt`; refresh on patch bump |
| `dps.py` | `compute_dps()` over a `CallContext` (defined in `_effects_types.py`) - stat walk, armor/MR pen, on-hit, periodic procs, damage amps |
| `ehp.py` | **Phase 1 (s174)** - `compute_ehp()` + `EhpResult` + `rank_items_by_ehp()` + `EhpRankResult` - Tank EHP scorer; HP / armor_factor math with caller-supplied AD/AP/true enemy shares; ARAM `aramDamageTaken` modifier folded in |
| `hybrid.py` | **Phase 2 (s175)** - `compute_hybrid()` + `HybridResult` + `rank_items_by_hybrid()` - Bruiser hybrid scorer; composes `compute_dps` x `compute_ehp` weighted by per-champion (alpha,beta) from `archetype_weights.json`; normalized-percentage-delta sort keeps weights intuitive across the ~10x DPS/EHP magnitude gap. **RM-39/RM-43 AD-axis ability term** (DEFAULT-OFF `apply_ad_axis_ability_damage`; L1 ENGINE 1.222.0, L2 1.223.0): at L1 (patch 16.14.1) `_damage_axis` resolved 92 of 173 champions to `"ad"` from the DDragon `info.attack` / `info.magic` rating alone, and every `_ability_damage` call site gated on `"ap"`, so those 92 were scored on auto-attack DPS alone. Since 9ba55608e (2026-08-02) `_damage_axis` reads the kit's own `lolmath.damage_distribution` first and falls back to that rating only when the split is not decisive: at patch 16.21.1 it resolves 85 of 173 to `"ad"` (164 decided by the kit split; the rating alone would give 92), re-derived by `tests/test_docs_ds_damage_axis_s144d11.py`. `_physical_ability_damage()` now adds an ability term at all three gate sites, summing `compute_ability_dps(...).per_spell` rows whose damage type is in `_AD_AXIS_CREDITED_DAMAGE_TYPES`. L2 widened that set from PHYSICAL to PHYSICAL + TRUE (TRUE has no resist derivative - `_mitigation_factor` returns a flat 1.0 for it). MIXED is HELD (it splits 50/50 armor/MR, so a full credit would import magic-pen valuation; the honest shape is a 50% credit, a separate design) and MAGIC is EXCLUDED PERMANENTLY. Byte-identical at the default, proven by cohort golden diff plus a full build-order regen. Live default-ON flip is operator-gated and additionally blocked on RM-98 (the ability rate is a whole-game average, the auto rate a combat window) |
| `abilities.py` | **Phase 4a (s177)** - `AbilitiesSnapshot.load()` + `AbilityForm` + `DamageBlock` + `load_default()` singleton - champion ability data loader for the Meraki bulk ingest at `data/daemon_slayer/<patch>/champion_abilities.json`. 171/173 champions x P/Q/W/E/R (multi-form preserved); per-rank `cooldown`/`cost`/`damage_blocks[]` with typed scaling fields (`base`, `total_ad_pct`, `bonus_ad_pct`, `ap_pct`, `caster_max_hp_pct`, `caster_bonus_hp_pct`, target HP family, `target_armor_pct`, `bonus_armor_pct`, `bonus_mr_pct`, `caster_max_mp_pct`) |
| `ability_dps.py` | **Phase 4b + 4c (s178/s179)** - `compute_ability_dps()` + `AbilityDpsResult` + `AbilitySpellDps` + `AbilityContext` (4b evaluator) **plus** `rank_items_by_ability_dps()` + `AbilityDpsRankedItem` + `AbilityDpsRankResult` (4c ranker). Per-spell evaluator resolves Q/W/E/R at the canonical rank-at-level for the operator's max-priority order (Q-first default, configurable); sums first damage block's per-rank scaling x resolved caster context; applies mode multiplier + AP cross-derivations + damage amps + per-spell magic_amp on magic-typed spells; routes mitigation per damage type. Multiplies post-mitigation damage by measured `casts/sec` from `ult_rates.get_spell_casts_per_sec` (rewind-derived); falls back to `1/cooldown x mana_uptime` when no data. Ranker uses the same `_filter_candidates` pipeline as `rank_items` / `rank_items_by_hybrid` (purchasable + mode-legal + budget + terminal-only + dead-unique dedup) and scores each candidate by total-ability-DPS delta over the baseline. Sort keys: `delta` (raw) + `efficiency` (per 1k gold). `/ability-dps` + `/rank-mage` routes on `:8860` |
| `burst.py` | **Phase 5 (s180)** - `compute_burst_damage()` + `BurstResult` + `ComboCast` (per-combo evaluator) **plus** `rank_items_by_burst()` + `BurstRankedItem` + `BurstRankResult` (assassin ranker). Walks a caller-supplied `combo_sequence` (default `("Q","W","E","AA","R","AA")`; tokens `AA` / `P` / `Q` / `W` / `E` / `R` / `Q2`-`R2` for repeats at same rank), fires each spell once at level-resolved rank via shared `_evaluate_block` / `_select_blocks` from `ability_dps`, applies full Phase 4b amp pipeline (Rabadon, Liandry, Demonic Embrace, Abyssal Mask magic-only, Riftmaker HP->AP, Mejai's stacked AP) + mitigation pipeline (lethality + flat + % pen). Auto-attacks contribute build's per-hit `avg_attack_dmg` from `compute_dps` (post-armor + mode, no on-hit periodic procs - Phase 5.5 deferral). `/burst` + `/rank-assassin` routes on `:8860` |
| `hps.py` | **Phase 6 (s181)** - `compute_hps()` + `HpsResult` + `HpsItemContribution` (evaluator) **plus** `rank_items_by_hps()` + `HpsRankedItem` + `HpsRankResult` (enchanter ranker) **plus** `EnchanterFormulasSnapshot` + `EnchanterItemFormula` (curated formula loader + singleton `load_default_formulas()`). Total throughput = (healing_raw + shielding_raw) x product(1 + amp_pct) x mode_mult + sum(buff_credit). Per-item formulas from `data/daemon_slayer/<patch>/enchanter_items.json` (12 bare SR enchanter items hand-curated: Moonstone Renewer 30% chain amp, Redemption AoE heal 150->350, Mikael's Blessing single-target heal + cleanse, Echoes of Helia Soul Siphon 40->70 HP + 15% AP x 0.4/s, Ardent Censer +15 ally_buff_credit, Staff of Flowing Water +12, Locket of the Iron Solari AoE shield 290->360, Imperial Mandate +6, Knight's Vow +10, plus Forbidden Idol (16.13.1), Dawncore and Whispering Circlet (16.14.1); each bare row but Forbidden Idol also has two mirror rows - see the next row). ARAM `aramShieldsHealing` modifier applied if present. Operator override `targets_per_proc_override` retunes "average teammate" assumption (Arena 2v2 -> 1). `/hps` + `/rank-enchanter` routes on `:8860` |
| `data/daemon_slayer/<patch>/enchanter_items.json` | (s181) Hand-curated per-item heal/shield/buff formula registry - 34 rows at patch 16.21.1: 12 bare SR items plus 22 mirror rows (`22xxxx` = the Arena map-30 copy, `32xxxx` = the map-11-only copy, per `items.json` `maps`; R143: an explicit per-id truth table, never a prefix strip, because a mirror's magnitude can differ from its bare line). It read 9 through 16.12.1; every count here is re-derived by `tests/test_docs_ds_module_map_counts_s134d09.py`. Each row carries `heal_per_proc_base/per_level/ap_scaling`, `procs_per_second`, `targets_per_proc`, mirror fields for shielding, `heal_shield_amp_pct`, `ally_buff_credit_per_second` |
| `archetype_weights.json` | (s175) Per-champion bruiser alpha/beta table - 20 entries covering Jarvan IV, Darius, Garen, Camille, Renekton, Sett, Mordekaiser, Riven, Volibear, Nasus, Olaf, Skarner, Hecarim, Udyr, Vi, Xin Zhao, Lee Sin, MonkeyKing/Wukong, Warwick, Trundle; default (0.5, 0.5) |
| `stats.py` | Champion base-stat + per-level growth + DDragon stat-key map |
| `engine.py` | `build_champion()` - leveled base + items + augments -> resolved stat block |
| `rank.py` | `rank_items()` - single-slot DPS ranker over filtered candidate pool |
| `beam.py` | `beam_search_build()` - full-build beam search returning top-N complete builds |
| `data_loader.py` | Versioned `DataSnapshot` loader; reads `data/daemon_slayer/<patch>/` |
| `ult_rates.py` | Per-champion cast-rate lookup. Legacy `get_ult_casts_per_sec` (R-only, reads `ult_cast_rates.json`) preserved for Malignance Hatefog backward compat; `get_spell_casts_per_sec(champion, key, mode)` (Phase 4b, s178) reads `spell_cast_rates.json` for all 4 active spells; both derived from rewind_history.db via `scripts/build_spell_cast_rates.py`; 172 champions x 4 spells over up to 3 mode buckets (SR / ARAM / ARENA, each kept only at >= 5 samples) plus a `global` row per champion |
| `tests/` | The engine's own suite. **The count is deliberately NOT written down here or in the line-5 banner** - measure it with `pytest agents/daemon_slayer --collect-only -q` from the repo root. It is unguarded (`tests/test_docs_daemon_slayer_drift.py` pins ENGINE_VERSION, patch and the route list, and its docstring says it deliberately does not pin `def test_` counts), so any recital drifts on the next test added and nothing fails. That is exactly what happened four times - 10594, 10578, 10605, 10653 - the last of them stale by 31 within a day. Deleting the recital is the fix; do NOT restore one, and do NOT add a guard that pins it, which would make every new test a two-file change (RM-210) |

## Key data types

- **`ItemEffect`** - frozen dataclass: `periodics`, `damage_amp_pct`, `armor_reduction_pct`, `mr_reduction_pct`, `giant_slayer_*`, `unique_passive_key`, `defensive_only` flag
- **`PeriodicProc`** - `every_n_attacks` or `every_n_seconds`; `bonus_damage` is `(CallContext) -> float`
- **`CallContext`** - frozen; all 18 fields in declaration order (only the first three are required) - `base_ad, bonus_ad, level, target_armor, target_mr, ap, target_max_hp, caster_max_hp, caster_bonus_hp, targets_in_rotation, crit_chance, target_bonus_hp, caster_max_mp, caster_bonus_armor, caster_lethality, ult_casts_per_sec, target_current_hp_pct, is_melee`
- The `ItemEffect` and `PeriodicProc` lists above are a SELECTION (`ItemEffect` has 58 fields); the `CallContext` list is complete and guarded by `tests/test_docs_ds_key_data_types_s144d05.py`. Authoritative source for all three: `_effects_types.py` (`dps.py` imports `CallContext` from it). A new field still goes at the dataclass END with a default.
- **`unique_passive_key`** - prevents double-counting when multiple items share named passives (e.g. `"spellblade"`, `"immolate"`)

## DS-before-Haiku pattern (required in all coaches)

`coach_integration.archetype_dispatch.dispatch_for_coach()` must run **before** `messages.create()` so Haiku sees scorer-aware DS picks in the user turn. Since s182 (2026-05-13) no coach calls `rank_for()` directly: the dispatcher resolves the champion's archetype and ranks through its scorer (`rank_for_primary_archetype()`, see "Phase 3 archetype picker + dispatcher" below). Shape, from `coaches/aram_coach.py` (trimmed; the import aliases dropped):

```python
_ds_dispatch = None
_ds_picks_str = "unavailable"
_ds_label = "DPS"
try:
    _ds_dispatch = dispatch_for_coach(
        champion=champ, mode_engine="ARAM", level=_lvl,
        item_ids=_owned_ids, enemy_stats=_es, top=5,
    )
    if _ds_dispatch is not None:
        _ds_picks_str = _ds_dispatch.picks_str
        _ds_label = display_label(_ds_dispatch.scorer)
except Exception as _ds_exc:
    logger.debug("ARAM daemon_slayer pre-call: %s", _ds_exc)
# user turn: "DS top items ({_ds_label} ranked, own-items-accounted): {_ds_picks_str}"
# post-Haiku: cur["daemon_slayer_picks"] = _ds_dispatch.display_rows - no second engine call
```

## Phase 3 archetype picker + dispatcher (s176)

Scorer selection lands in four layers. The operator-facing picker s176 shipped is GONE (LEDGER 824, 2026-07-09); the resolved archetype is now shown read-only:

- **Storage**: `core/archetype_picks.py` - DDragon-tag -> archetype default + per-champion override. NOTE the two override layers are NOT interchangeable: `data/cs_archetype_picks.json` is **GITIGNORED runtime operator state** (`.gitignore:141`, cleared to `{}` in LEDGER 824 after operator picks polluted the committed precompute), while the git-tracked ROUTE corrections live beside the module as rosters consumed by `default_for_champion` - Slice A `_AP_ASSASSIN_IDS` (inline), Slice B `core/ds_onhit_ap_roster.json`, Slice C `core/ds_support_route_overrides.json` (RM-84, the Support-tag misroute). Six canonical archetypes in `ARCHETYPES`: `carry`, `bruiser`, `tank`, `mage`, `assassin`, `enchanter`, plus the `onhit` route that `default_for_champion` returns for the on-hit-AP roster - all seven wired through `rank_for_primary_archetype()` (carry -> ds.dps, bruiser -> ds.hybrid, tank -> ds.ehp, mage -> ds.ability, assassin -> ds.burst, enchanter -> ds.hps, on-hit AP -> ds.onhit at ENGINE 1.216.0 / LEDGER 911). Every archetype has its own scorer (s174-s181); `fell_back=True` comes only from the kit-less guard: mage / assassin / enchanter serve the ds.dps build, labelled `carry`, with `fell_back=True` when `_kitless_all_zero` sees an all-zero ranking (LEDGER 907); bruiser keeps its ds.hybrid build but also reports `fell_back=True` when `champion_has_ability_data` is False (LEDGER 931, RM-79). An unknown archetype string also falls through to ds.dps, with `fell_back=False`.
- **REST**: `GET /api/cs-archetype-pick?champion=X` returns merged pick (override OR default). `POST /api/cs-archetype-pick {champion, primary, secondary?, source?}` persists. `POST {champion, clear: true}` rolls back to default. Both routes stay registered (`dashboard/routes_archetype.py`), but no dashboard surface sends the POST any more: LEDGER 824 deleted both of its callers.
- **Dispatch**: `core.daemon_slayer_client.rank_for_primary_archetype(champion, archetype, ...)` returns `{ok, scorer, archetype, ranked, fell_back}` with `ok` always True, or `None` when the scorer POST fails (timeout, refused connection, any HTTP error status, a non-JSON body, a body that is not a JSON object or a `ranked` that is not a list; no path returns `ok=False`; a single malformed row is dropped, not defaulted, and that includes a row whose `item_id` is missing, null or empty; a null text field parses as `""`, never as `"None"`). Coaches read the picked archetype via `coach_integration/archetype_dispatch.py` (s182); all 4 mode coaches inject scorer-aware DS picks before each Haiku call.
- **UI**: read-only. The s176 6-button picker grid in the champ-select My Pick card (it wrote a `user_cs` pick through the POST above, mirrored in `localStorage`) and the in-game overlay's right-click archetype cycle were both deleted in LEDGER 824 (2026-07-09). The grid went because a pick POSTed into the shared `data/cs_archetype_picks.json` changed the committed build-order precompute for everyone; the overlay cycle never persisted a pick and went on operator directive. Champ-select now only GETs the server-resolved pick (`_csvFetchArchetype` / `_csvResolveArchetype` in `web/js/panels/champ_select.js`) and keys the DS build preview on it, so the preview uses the same scorer as the coach. It shows that pick as a read-only chip in the My Pick card (`archetypeChipHtml` from `web/js/panels/archetype_chip.js`, no fetch of its own). There is no manual override in the UI; on-hit AP (`ds.onhit`) and every other archetype reach a champion through `default_for_champion` defaults and the tracked route rosters only.

## Coach integration status

| Coach | DS call | Position | Pre-DS rules pruned |
|---|---|---|---|
| `coaches/aram_coach.py` | yes | Before Haiku | yes (-37% system prompt) |
| `coaches/arena_coach.py` | yes | Before Haiku | yes |
| `coaches/brawl_coach.py` (BRAWL mode retired from champ-select s214, but the module is NOT deadcode - see below) | yes | Before Haiku | yes |
| `coach_integration/_coach.py` (SR) | yes | Before Haiku | - |
| TFT | N/A | N/A | N/A |

**`brawl_coach.py` is live-reachable - do not delete it as deadcode (verified 2026-08-06; citations re-measured 2026-10-26).**
This row previously read "backend left as deadcode". That is wrong about the CODE, and a
cleanup pass acting on it would remove the coach for URF, ARURF, Nexus Blitz, One for All,
Ultimate Spellbook and GAMEMODEX. `core/game_snapshot.py:127-131`
returns `MODE_BRAWL` for `NEXUSBLITZ` / `NEXUS` / `ULTBOOK` / `URF` / `ARURF` / `GAMEMODEX` /
`ONEFORALL` (a prefix match). Riot's own Brawl mode never reaches that branch: since the 2026-08-11
compliance gate `BRAWL` is in `FORBIDDEN_GAME_MODES` (`core/game_snapshot.py:85`) and returns
`MODE_UNSUPPORTED` ahead of every other branch, so RC's `MODE_BRAWL` (a name that predates Riot's
mode) now covers the modes listed above only. `app/__init__.py:158` sets `_brawl_mode` from that,
`core/coach_registry.py:7` maps `_brawl_mode` -> `coaches.brawl_coach`, and
`app/_game_lifecycle.py:144-163` importlib-loads it on game start. `config/feature_flags.json:12-14`
has `brawl.live_coaching: "allow"`, so nothing gates it off. The end-to-end path is intact and
`coaches/brawl_coach.py:498` would issue a live Haiku call. What IS true: the module runs only
while one of those modes is in Riot's queue (Brawl itself is disabled by Riot, patch 25.23 - the
"Brawl mode re-enable" row in `BACKLOG.md` - and refused by RC as above), so it is currently
unexercised, which is a statement about Riot's rotation, not about reachability.
`ops/audit/HZ_HAIKU_CALL_INVENTORY.md` and `docs/specs/RM-141_JADE_MODE.md` carried the same
wrong label until both were corrected on 2026-08-06.

## Permanently deferred items (3)

1. **Lightning Braid** (4013) - not on any map in the current snapshot (DDragon `maps` all false); no formula in Meraki; also DPS-negative (-20% ability damage reduction)
2. **Kinkou Jitte** (447116) - Arena-only item; directional weakpoint, positional geometry unmodelable
3. **Mejai's Arena mirror** - no Arena (map 30) row in DDragon; 3041 is the only Mejai's row

**Key insight**: check Meraki `passives[].cooldown` (under `items_meraki.json` `items.<id>`; int, string or null) before deferring any "ability-triggered" item. If an item CD exists, use `PeriodicProc.every_n_seconds` = CD - no ability-frequency data needed.

## Calibration pipeline

`core/ds_calibration.py` `log_ds_run` appends one line to `data/ds_calibration.jsonl` (gitignored) for each coaching tick whose DS dispatch returned rows. Its callers are `coach_integration/_coach.py` (SR), `coaches/aram_coach.py`, `coaches/arena_coach.py` and `coaches/brawl_coach.py`. A line always carries `ts`, `champion`, `mode`, `level`, `owned_items`, `ds_picks`, `game_id` and `match_key`; the RM-875 re-run inputs are added only when a caller passes them.

`python tools/ds_calibration_report.py` runs `core/ds_calibration_agreement.py` over the log and writes `data/ds_calibration_agreement.json`. The join with `rewind_history.db` is exact on the Riot game id: a line's `game_id`, else a `match_key` of the form `live_<gameId>`, against the numeric suffix of `matches.match_id`. It is not a (champion, mode, ~ts) match. The synthetic `sess_<mode>_<champ>_<seq>` keys minted when the game state carries no game id never join and are counted in `records_without_game_id`. One observation is one (game, item, scorer), taken at the earliest tick that recommended the item while it was unowned; a (mode, scorer) cell is reported only at `MIN_BUCKET_N` = 20 observations or more. There is no games threshold, and how much has accrued is a property of the local log: run the report to measure it. The result is descriptive only and never feeds `agents/daemon_slayer` rank.

## Arena-specific: Arcane Sweeper

Every Arena player receives Arcane Sweeper (3348) in the trinket slot, and the live inventory poll returns it beside the six build slots. Two gates keep it out of DS:
- the candidate pool: `rank._filter_candidates` keeps only items passing `_is_purchasable`, and the DDragon row has `gold.purchasable` false and `gold.total` 0. Its `inject_ids` force-admit skips that gate; the only caller passing it is `ehp.py` (the tank survivability table), which holds no 3348;
- the caller's current items: `rank.strip_arena_trinkets` removes `ARENA_TRINKET_IDS` (3348) when the mode is ARENA (case-insensitive), so the slot count and the baseline are not padded with a zero-stat row. It is called by the carry ranker (`rank.py`), each archetype ranker (`_rank_mage.py`, `burst.py`, `ehp.py`, `hps.py`, `hybrid.py`, `onhit_dps.py`) and `beam.py`.

`defensive_only` is a documentation flag on `ItemEffect`; no scorer and not the beam search reads it.
