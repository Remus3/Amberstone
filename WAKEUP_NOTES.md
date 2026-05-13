# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s179 wrap — 2026-05-12 (Phase 4c mage ability DPS ranker — single commit pending)

**Operator instruction:** "continue ds work" — following s178's Phase 4b mage ability DPS evaluator, ship the per-archetype ranker + route + dispatcher integration per [NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md](NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md).

Phase 4c is the third and final session of the Phase 4 lift. Phase 4a (s177) produced the ability data; Phase 4b (s178) ships the formula evaluator. Phase 4c (this slot) is the ranker + `/rank-mage` route + dispatcher mage-branch wire-in, which closes the Phase 4 lift and removes mage from the `fell_back=True` set in `rank_for_primary_archetype()`.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/ability_dps.py](agents/daemon_slayer/ability_dps.py) | **~250 LOC of additions.** New `AbilityDpsRankedItem` dataclass (item_id, item_name, gold, delta_ability_dps, new_ability_dps, ability_dps_per_1k_gold, is_terminal, tags, shares_dead_unique, dead_unique_key + `to_dict()`). New `AbilityDpsRankResult` (champion + level + mode + current_item_ids + baseline_ability_dps + primary_scaling + target_* + target_current_hp_pct + max_priority + block_strategy + mode_multiplier + budget + slot_count + sort_by + candidates_considered/evaluated + ranked + notes + `to_dict()` + `format_table()`). New `rank_items_by_ability_dps()` — mirrors `rank_items_by_hybrid` / `rank_items_by_ehp` shape: clamps level + strips Arena trinkets + computes baseline via `compute_ability_dps()` + walks `_filter_candidates` from `rank.py` (purchasable + mode-legal + budget + terminal-only + optional whitelist) + dead-unique dedup via current build's unique_passive_key set + scores each candidate via `compute_ability_dps()` with the candidate appended + sorts by `delta` (raw `total_ability_dps` gain) or `efficiency` (per 1k gold). Module docstring updated to cover both 4b + 4c. Imports tighten: pulls `ITEM_EFFECTS` for unique-key checks, `_filter_candidates` / `_is_terminal` / `strip_arena_trinkets` / `DEFAULT_SLOT_COUNT` / `DEFAULT_TOP_N` / `SORT_KEYS` from `rank.py`. |
| [agents/daemon_slayer/server.py](agents/daemon_slayer/server.py) | New POST/GET `/rank-mage` route + `_route_rank_mage()` handler. Body union of `/ability-dps` + `/rank` parameters (target_*, target_current_hp_pct, max_priority, block_strategy, form_index, budget, slots, top, sort, include_components, only, filter_shared_uniques, augments). Shared `_parse_max_priority()` + `_parse_form_index()` helpers extracted so `/ability-dps` and `/rank-mage` parse operator-supplied priority/form overrides identically (list / comma-string / compact "QWE" for priority; JSON dict for form_index). Index HTML routes table updated. `_POST_ROUTES` dispatch entry added. |
| [core/daemon_slayer_client.py](core/daemon_slayer_client.py) | **3 new exports.** `MageRankedItem` dataclass mirrors server response (item_id, item_name, delta_ability_dps, new_ability_dps, gold, shares_dead_unique, dead_unique_key). `rank_mage_for()` client helper — POST to /rank-mage, same engine-down semantics as `rank_for` / `rank_tank_for` / `rank_bruiser_for` (None = unreachable, [] = nothing to recommend). `ability_dps_for()` mirrors `dps_for` / `ehp_for` / `hybrid_for` for the per-spell breakdown route. **Dispatcher wire-in:** `rank_for_primary_archetype()` mage branch now routes to `rank_mage_for()` (returns `scorer="ability"`, `fell_back=False`); assassin + enchanter still fall back to ds.dps with `fell_back=True` pending Phases 5-6. Signature gained mage-specific params: `target_current_hp_pct` (default 1.0) + `max_priority` + `block_strategy` + `form_index` (silently ignored by non-mage branches). Docstring updated to reflect 4 active scorers (ds.dps / ds.ehp / ds.hybrid / ds.ability) + 2 deferred (ds.burst / ds.hps for Phases 5-6). |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | `ENGINE_VERSION` 0.66.0 → 0.67.0. Module docstring extended with Phase 4c changelog covering the ranker + route + client helpers + dispatcher wire. |
| [agents/daemon_slayer/tests/test_rank_mage.py](agents/daemon_slayer/tests/test_rank_mage.py) | **NEW (~430 LOC, 36 tests).** RankByAbilityDpsBasicsTests (7 — result type + baseline match + delta arithmetic + sort + clipping + primary_scaling + dataclass type); AbilityDpsScoringTests (5 — Rabadon's top-3 for Veigar + BotRK absent from mage top-3 + positive delta on Rabadon-only + efficiency sort ordering + efficiency zero on negative delta); FilterPipelineTests (7 — already-equipped skip + only-whitelist + budget + include_components + ARENA trinket strip + dead-unique filter ON + dead-unique surfaced when OFF); ValidationAndEdgeTests (4 — invalid sort_by + full build raises + invalid block_strategy + invalid max_priority); SerializationTests (3 — to_dict round trip + format_table contains [MAGE] + ranked item to_dict shape); ModeAndAmpFlowTests (2 — ARAM mode_multiplier < 1.0 for AP carry + AP-amp item lifts baseline); RankMageRouteTests (8 — POST 200 + AP item in top-5 + 404 unknown champ + 400/422 invalid sort + only-whitelist + max_priority compact form + filter_shared_uniques default + efficiency sort). |
| [tests/test_archetype_dispatcher.py](tests/test_archetype_dispatcher.py) | New `MageRoutingTests` class (5 tests — routes_to_rank_mage_for + passes_target_current_hp_pct + passes_max_priority + passes_form_index + returns_none_when_engine_down). New `_make_mage_rows()` helper. Old `FallbackArchetypesTests.test_mage_falls_back_to_dps` removed (replaced by the new MageRoutingTests assertions); assassin + enchanter fallback tests preserved. Class docstring updated to "Phases 5-6". |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Bumped `test_batch63_version` + `test_batch64_version` to assert ENGINE_VERSION 0.67.0; extended changelog comment with Phase 4c line. |
| Living docs sync | [CLAUDE.md](CLAUDE.md) DS pointer line 6 + new item 35; [README.md](README.md) header bullet + Daemon Slayer engine section + capability matrix; [docs/DAEMON_SLAYER.md](docs/DAEMON_SLAYER.md) status line + server route list + ability_dps.py row; [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) DS section; [ROADMAP.md](ROADMAP.md) DS status table + new s179 ship entry; [BRIEF.md](BRIEF.md) RC Tutor "what's built" line. |
| DS server runtime | Killed PID 7052 via `taskkill /F` (PowerShell call after Get-CimInstance located it — never `Stop-Process` per CLAUDE.md hard rule + `reference_get_wmiobject_broken`). Relaunched via `Start-Process pythonw tools\start_daemon_slayer.py`. `/health` confirms `engine_version: "0.67.0"` live on `:8893`. |

## Live validation

Probed `/rank-mage` against the running DS server on :8893.

**Veigar lvl 11 naked vs 30 MR**:
```
baseline_ability_dps: 25.07
primary_scaling: AP
top 5:
  3089 Rabadon's Deathcap       gold=3500  +13.58  new=38.65  adps/1k=3.88
  4645 Shadowflame              gold=3200  +13.26  new=38.33  adps/1k=4.14
  3041 Mejai's Soulstealer      gold=1500  +11.65  new=36.72  adps/1k=7.77
  4646 Stormsurge               gold=2800  +11.44  new=36.51  adps/1k=4.09
  3135 Void Staff               gold=3000  +10.96  new=36.03  adps/1k=3.65
```

Math sanity-check: Rabadon's +130 AP × 1.30 amp = 169 effective AP. Veigar Q rank 4 base 240 + 169 × 0.70 = 358.3 raw, post-mit (30 MR) 275.6, × cps 0.098 ≈ 27 DPS. W + R contributions push the total to 38.65, matching s178's evaluator probe (which also reported 38.65 for the exact same build via `/ability-dps`). Round-trips cleanly through the new ranker — same evaluator, same numbers, just stratified into per-item delta rows.

`candidates_considered=705 / candidates_evaluated=175` matches the SR purchasable + terminal filter pipeline used by `/rank` and `/rank-tank`.

## Findings

- **The 4c lift was 95% mechanical once 4b landed.** Phase 4b did the hard work — the per-cast formula evaluation, the AP/damage amp pipeline parity with `compute_dps`, the cast-rate plumbing. Phase 4c is "wrap a baseline call + N candidate calls in the existing `_filter_candidates` pipeline and surface a sortable row." The dataclass shape and the route handler are direct mirrors of `rank_items_by_hybrid` / `rank_items_by_ehp`. No new math; no new schemas. The only meaningful design decision was whether to put the ranker in a new file (`ability_dps_rank.py`) or extend `ability_dps.py`; chose extend because the same caller cares about both the evaluator and the ranker and they share the bulk of the imports.
- **The shared `_parse_max_priority` / `_parse_form_index` helpers in server.py paid off on the first refactor.** Both `/ability-dps` and `/rank-mage` need to decode the same operator-supplied priority/form fields (list / comma-string / compact "QWE" for priority; JSON dict for form_index). Phase 4b shipped the parsing inline in `_route_ability_dps`; Phase 4c could have copy-pasted into `_route_rank_mage` but the two would have drifted within a release. Extracting helpers also makes Phase 5's `/rank-assassin` route cheap to add — it'll need the same parsing.
- **The dead-unique filter coverage caught a real edge case in the test pass.** Initial test asserted Sundered Sky (6610) would be filtered out when Lich Bane (3100) was in the current build, because both are spellblade items. Wrong — per engine docstring (batches 11/21/23), Sundered Sky's "Lightshield Strike" is intentionally untagged with the "spellblade" key (distinct mechanic from Trinity Force / ER / Lich Bane / Iceborn Gauntlet / Divine Sunderer). Test fix surfaced the correct expectation. This is a coverage gap in the test suite — the engine's unique_passive_key registry is the authoritative answer, not "looks like a spellblade item to me." Test now uses the correct sib set + adds a comment explaining the carve-out.
- **The dispatcher's old `fell_back=True` path for mage was a documented placeholder, not a hack.** When Phase 3 (s176) shipped the dispatcher, the comment said mage/assassin/enchanter "fall through to ds.dps with `fell_back=True` until Phases 4-6 ship dedicated scorers." Phase 4c removes mage from that set (assassin + enchanter remain). The plan's "explicit branch per scorer" design holds — no refactor needed when 4c lands, just a new `if arch == "mage":` branch before the fall-through. Phase 5 (assassin) will add `if arch == "assassin":` the same way; Phase 6 (enchanter) the same.
- **Live `/rank-mage` round-trip matches `/ability-dps` exactly.** Baseline ability DPS at lvl 11 naked vs 30 MR: 25.07 from both routes. Top candidate Rabadon's lifts to 38.65 in both. Confirms the ranker is calling the evaluator without any drift — same `compute_ability_dps()` under the hood, same numbers out. If the evaluator's math is correct (validated in s178), the ranker's math is correct by construction.

## Verification

- `py -m pytest agents/daemon_slayer/tests/` → **1257 passed** (was 1221 — +36 from new test_rank_mage.py)
- `py -m pytest tests/` → **906 passed** (wider RC — was 905+1fail pre-restart, now all green after DS server restart picked up 0.67.0)
- `py -m pytest tests/test_archetype_dispatcher.py` → **19 passed** (was 15 — +5 MageRoutingTests, −1 old mage fallback test)
- `py -m py_compile` on all touched files → clean
- DS server `:8893/health` → `engine_version: "0.67.0"` live
- Live probe of `/rank-mage` matches s178's `/ability-dps` baseline + top-pick math for Veigar lvl 11 vs 30 MR

## Open items carried forward

- 🟡 **Phase 5 — Assassin burst-window scorer** — next per the plan. New `agents/daemon_slayer/burst.py` with `compute_burst_damage()` + `rank_items_by_burst()` scoring max damage in a single combo rotation (Q→W→E→AA→R→AA) rather than sustained DPS. Reuses Phase 4 ability data (form / damage_blocks / scaling fields) + ult_rates (one-shot per combo). True damage components (Talon E, Wukong R) bypass resists. Champion list ~15 (Zed, Talon, Akali, Kha'Zix, Rengar, Fizz, Diana, Kassadin, Katarina, LeBlanc, Qiyana, Pyke, Naafiri, Briar + Yone burst-variant).
- 🟡 **Phase 4d calibration follow-up** — per-champion `max_priority` overrides JSON (Veigar/Lux always Q-first but Karthus W-first / Akali E-first / Cassiopeia E-first benefit from explicit overrides); per-champion `form_index_overrides` JSON (Aphelios weapon defaults, Jayce stance defaults). Phase 4c ships defaults that match the canonical max-order for most mages; overrides become useful when calibration data shows the rankings are wrong for specific champions.
- 🟡 **Coach integration deferred** — no coach reads `state.cs_archetype_pick.primary` yet. Phases 1/2/3/4 all share this deferral. Wire-in adds a single line per coach (`coaches/aram_coach.py` / `arena_coach.py` / `brawl_coach.py` / `coach_integration/_coach.py`): replace `rank_for(...)` with `rank_for_primary_archetype(champion, state.cs_archetype_pick.primary, ...)`. Reads from the dashboard's state envelope which doesn't yet stamp the field — state-builder injection (server-side champion-id → name resolver) is the precursor.
- 🟡 **No coach is consuming the new mage scorer yet.** Same situation as Phases 1-3. The dispatcher is callable; the ranker is callable; `/rank-mage` is live. Just no coach makes the call. Operator can validate via the dashboard's DS preview routes once a mage CS pop happens.
- 🟡 **Cast-rate dataset freshness** — `spell_cast_rates.json` is derived from 2851 matches with newest match 2025-12-16 (same gate as the DS calibration pipeline, CLAUDE.md item 14). When operator resumes play + RC-RewindCatchup wires in, this auto-refreshes.

---

# s178 wrap — 2026-05-12 (Phase 4b mage ability DPS evaluator — single commit pending)

**Operator instruction:** "continue DS Phase 4b —" — following s177's Phase 4a champion ability ingest, ship the formula evaluator per [NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md](NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md).

Phase 4b is the formula-evaluator middle of the three-session Phase 4 lift. Phase 4a produced the data; Phase 4b consumes it. Phase 4c (next) will ship the per-archetype ranker + `/rank-mage` route + dispatcher integration.

## Ships

| File | Change |
|---|---|
| [scripts/build_spell_cast_rates.py](scripts/build_spell_cast_rates.py) | **NEW (~150 LOC).** Derives `data/daemon_slayer/spell_cast_rates.json` from `data/rewind_history.db.participants.spell[1-4]_casts / matches.game_duration_s`. Mode buckets: SR (420/400/430/440/700) / ARAM (450/100) / ARENA (1700/1710) / global rolled together. Median per champion × mode × spell key; min 5 samples per mode bucket (global accepts smaller N). Output JSON shape mirrors the existing `ult_cast_rates.json` extended to Q/W/E/R per mode. Run produces 172 champs / 669 buckets kept / 15 dropped on the current 2851-match DB. Re-runnable for future patches. |
| [data/daemon_slayer/spell_cast_rates.json](data/daemon_slayer/spell_cast_rates.json) | **NEW snapshot.** 172 champions × Q/W/E/R × SR/ARAM/ARENA/global. Backward-compat: legacy `ult_cast_rates.json` stays in place for `get_ult_casts_per_sec` (Malignance Hatefog still reads it). |
| [agents/daemon_slayer/ult_rates.py](agents/daemon_slayer/ult_rates.py) | Extended to expose `get_spell_casts_per_sec(champion_name, key, mode)` for all 4 active spells. New `_load_spells()` + module-level `_spell_cache`. Legacy `get_ult_casts_per_sec` preserved for Malignance Hatefog — tolerates BOTH the flat-float `global_fallback` (legacy) and the new dict shape (forward-compat for when `ult_cast_rates.json` gets regenerated). New `reset_cache()` clears both caches for test fixtures. Module docstring rewritten to cover both layers. |
| [agents/daemon_slayer/ability_dps.py](agents/daemon_slayer/ability_dps.py) | **NEW (~600 LOC).** Phase 4b evaluator. `compute_ability_dps()` + `AbilityDpsResult` (per-spell breakdown + total + primary scaling classifier) + `AbilitySpellDps` (per-spell record with raw / post-mode / post-mit damage per cast + measured cps + source tag + mana_uptime_factor + DPS) + `AbilityContext` (resolved caster stats — base/bonus AD/HP/armor/MR + max MP + mp_regen + target HP family with current/missing derivation). Helpers: `rank_at_level(key, level, max_priority)` pins canonical Q-first / W-second / E-third tables (R unlocks 6/11/16); `_mitigation_factor` routes per damage type; `_select_blocks` supports first/sum/max strategies with first as default; `_evaluate_block` walks per-rank scaling fields. Per-spell loop applies mode_mult + AP cross-derivations (ap_from_hp + stacked_ap + ap_amp + hp_ap_amp ported from compute_dps) + build-wide damage_amp + giant_slayer + target_bonus_hp_amp + per-spell magic_amp on magic-typed spells + effective armor/MR (lethality + flat/% pen pipeline). Cast rate: measured from spell_cast_rates.json when available, falls back to `1/cooldown × mana_uptime` otherwise. `_classify_primary_scaling` inspects damage_blocks pre-build for stable AP/AD/HP/MIXED classification. Missing-snapshot path: `_empty_result` surfaces zero DPS + structured note (vs crashing). |
| [agents/daemon_slayer/server.py](agents/daemon_slayer/server.py) | New POST/GET `/ability-dps` route + `_route_ability_dps()` handler. Body union of `/dps` params + `target_current_hp_pct` (default 1.0) + `max_priority` accepts list / comma-string / compact 3-char string ("WQE") + `block_strategy` enum + `form_index` dict (JSON-only). Index HTML table extended. Routes table dispatch entry added. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | `ENGINE_VERSION` 0.65.0 → 0.66.0. Module docstring extended with Phase 4b changelog covering the per-spell evaluator design + the new spell_cast_rates.json + the AP/damage amp parity work + Phase 4c deferral. |
| [agents/daemon_slayer/tests/test_cast_rates.py](agents/daemon_slayer/tests/test_cast_rates.py) | **NEW (~180 LOC, 14 tests).** SpellCastRateLookupTests (9 — champ+mode happy path + fallback chain through champ-global → global_fallback → 0.0 + invalid key raises ValueError); UltRateBackwardCompatTests (4 — legacy file takes precedence + missing-file default 0.0073 + dict-shaped global_fallback compat); LiveSpellRatesSnapshotTests (3 — smoke against the real shipped JSON, non-zero Veigar Q + global fallback >= 0 for all spells). |
| [agents/daemon_slayer/tests/test_ability_dps.py](agents/daemon_slayer/tests/test_ability_dps.py) | **NEW (~600 LOC, 56 tests).** RankAtLevelTests (7), AbilityContextTests (4), MitigationFactorTests (6 — including MIXED + negative armor + None defaults to MAGIC), BlockEvaluationTests (11 — pure base / AP / total_ad / bonus_ad / target_max_hp + locked rank + sum/first/max selection + non-damage block filter), PrimaryScalingTests (5), ComputeAbilityDpsTests (14 — Veigar AP scaling + Aatrox PHYSICAL routing + Ezreal AD-mage + ARAM mode_mult applied to per-cast (NOT total — measured cast rates differ between modes) + Liandry's damage amp + structural to_dict/format_table + 3 validator-raises), CastRateIntegrationTests (2 — measured source flag + Q vs locked-R ordering), ServerRouteTests (5 — POST 200 + items lift DPS + 404 unknown + 422 invalid strategy + max_priority compact string form). |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Bumped `test_batch63_version` + `test_batch64_version` to assert 0.66.0; extended comment in batch63 covering Phase 4a/4b history. |
| Living docs sync | [CLAUDE.md](CLAUDE.md) DS version pointer line 6 (0.65.0 → 0.66.0). [README.md](README.md) header DS bullet + Daemon Slayer engine section (test counts + Phase 4b additions). [docs/DAEMON_SLAYER.md](docs/DAEMON_SLAYER.md) status line + module map row for `ability_dps.py` + `ult_rates.py` row rewrite. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) DS section. [ROADMAP.md](ROADMAP.md) DS status line + s178 ship entry. [BRIEF.md](BRIEF.md) RC Tutor "what's built" line. |
| DS server runtime | Killed PID 13940 (PowerShell `taskkill /F`) + relaunched via `Start-Process pythonw tools/start_daemon_slayer.py`. `/health` confirms `engine_version: "0.66.0"` live on `:8893`. |

## Live validation

Probed `/ability-dps` against real running DS server.

**Veigar lvl 11 + Rabadon's Deathcap (3089) vs 30 MR**:
```
total: 38.65 primary: AP
  Q Baleful Strike    rank=4 dpc=275.6 cps=0.098 dps=26.94
  W Dark Matter       rank=2 dpc=254.0 cps=0.041 dps=10.46
  E Event Horizon     rank=0 dpc=0.0   cps=0.016 dps=0.00 (CC-only, no damage block)
  R Primordial Burst  rank=1 dpc=283.3 cps=0.004 dps=1.24
```
Rabadon's +130 AP × 1.30 amp = 169 effective AP. Q rank 4 base 240 + 169 × 0.70 = 358.3 raw magic → post-mit (30 MR) 275.6. Matches hand calculation.

**Aatrox lvl 11 naked vs 100 armor / 30 MR — physical mitigation routing**:
```
total: 9.67 primary: AD
  Q The Darkin Blade   type=PHYSICAL dpc=84.5 dps=8.54
  W Infernal Chains    type=PHYSICAL dpc=47.0 dps=1.00
  E Umbral Dash        type=None     dpc=0.0  dps=0.00
  R World Ender        type=None     dpc=25.4 dps=0.13
```
100 armor → exactly 0.5 mitigation factor applied (validated by ratio test).

## Findings

- **`compute_dps`'s AP amp pipeline matters more than expected for ability scoring.** The first cut just used `stats["ap"]` directly; live test showed Rabadon's increased ability DPS by 45% but should be ~54%. Tracking down the gap: Rabadon's 130 flat AP × 1.30 multiplicative amp = 169 effective AP, but `stats["ap"]` exposes only the 130 (matches `/stats` endpoint convention). The fix is to mirror `compute_dps`'s post-batch-32 AP-amp pipeline — `ap_from_hp + stacked_ap + ap_amp + hp_ap_amp` — applied to the AbilityContext via `dataclasses.replace`. Once ported, Veigar Q damage went 226→275 with Rabadon's (matches hand-calc). Same precedence applies to `damage_amp` (Riftmaker/Liandry) + `target_bonus_hp_amp` (LDR Giant Slayer @ enemy bonus HP) + `giant_slayer` (Perplexity @ HP diff) + `magic_amp` (Abyssal Mask, magic-only). Now per-cast damage matches the auto-attack scorer's amp pipeline exactly, so future item rankings between Mage and Carry rankers stay coherent.
- **Cast rate from measured rewind data is dramatically better than `1/cooldown` for mage scoring.** Veigar Q has 4s base cooldown → theoretical 0.25 casts/sec; measured median is 0.098 casts/sec (40% of theoretical). That's mana / fight-window / sieging downtime baked into one number. The theoretical fallback path applies a `mana_uptime` denominator only for resource=="MANA" champs (energy/manaless users get full uptime); but for the 172 champions × 4 spells × 3 mode buckets covered in the dataset, measured rates dominate. Phase 4c's ranker will produce ordering that reflects how items actually pay out in real games rather than "if you spammed every spell every CD."
- **Mode-multiplier × cast-rate interplay is non-monotonic.** Naive expectation: ARAM = lower per-cast damage (Veigar `aramDamageDealt=0.93`) → lower ARAM total DPS than SR. Reality: ARAM has 1.5-2× higher cast rates for W/E/R (more team-fights / shorter games / more action density), which more than offsets the 7% per-cast nerf. Total ARAM ability DPS can be HIGHER than SR despite the mode multiplier. The test `test_aram_damage_dealt_applied_to_per_cast` checks the per-cast effect (not totals) to avoid the trap; CONTEXT/CLAUDE.md item 34 should reflect this if anyone ever expects "ARAM nerf = less DPS in scorer."
- **Multi-block / multi-form abilities are a Phase 4c+ problem.** Aphelios 6× Q forms (weapon stances), Aatrox Q's 3-cast chain (6 damage blocks), Jayce stance Q/W/E pairs (2× per affected key) all collapse to `form_index=0` + `block_strategy="first"` in this slot. The `form_index_overrides` param + `block_strategy="sum"/"max"` are wired but not selected automatically. Operator can pass them per-call; per-champion overrides JSON deferred. Doesn't block the typical mage scorer use case — Veigar/Lux/Annie/Brand/Syndra all have single-block single-form abilities.
- **Mana economy as an "informational" output rather than a scale factor.** The Phase 4 plan called for "uptime_factor handles mana economy + downtime" baked into the DPS multiplier. I built `_mana_uptime_factor` to compute it but only apply it on the theoretical fallback path. Measured cast rates already encode mana downtime, so re-multiplying would double-discount. Surface area: `AbilitySpellDps.mana_uptime_factor` carries the raw computed value for debug visibility; the active DPS uses measured rate as-is.

## Verification

- `py -m pytest agents/daemon_slayer/tests/` → **1221 passed** (was 1151 — +70: 14 cast_rates + 56 ability_dps)
- `py -m pytest tests/` → **902 passed** (wider RC suite — no regressions, same count as before)
- DS server `:8893/health` → `engine_version: "0.66.0"` live
- Live probe of `/ability-dps` matches hand-calculated values for Veigar Q + Aatrox Q

## Open items carried forward

- 🟡 **Phase 4c — `rank_items_by_ability_dps()` + `/rank-mage` route + dispatcher integration** — next session per the plan. Ships the per-item ranker mirroring `rank_items_by_hybrid`'s shape (single-slot delta against baseline), wires the dispatcher entry point in `core/daemon_slayer_client.py::rank_for_primary_archetype()` so `state.cs_archetype_pick.primary == "mage"` routes to ds.ability instead of falling back to ds.dps. Tests target ~30 cases including item AP scaling, mana-economy edge cases, ARAM mode amp, dead-unique filter parity, augments.
- 🟡 **Phase 4b deferrals** — multi-form abilities default to `form_index=0` (Aphelios weapon-1, Jayce hammer stance); multi-block abilities use the first block only. Per-champion `max_priority` overrides + `form_index` defaults JSON to ship in Phase 4c calibration follow-up.
- 🟡 **No coach is wired to call `compute_ability_dps` yet.** Same situation as Phase 1 EHP and Phase 2 hybrid — the picker persists `state.cs_archetype_pick.primary = "mage"` but no coach reads it. Phase 3 dispatcher exists but currently falls back to ds.dps for mage with `fell_back=True`. Phase 4c lands the dispatcher entry; full coach integration is a separate follow-up.
- 🟡 **Passive ability scoring deferred entirely.** P keys fall through `rank_at_level` to level-1 rank but are excluded from the per-spell loop (only Q/W/E/R iterated). Kayle/Senna/Aatrox passives are not scored. Most passive damage is on-hit which `compute_dps` already handles via the rotation scorer; pure-passive damage scaling (Lillia P, Ekko P) is rare and operator-tunable via custom block strategies. Phase 5 may revisit.
- 🟡 **Cast-rate dataset freshness** — `spell_cast_rates.json` is derived from 2851 matches with newest match 2025-12-16. Same `rewind_history.db` staleness gate as the DS calibration pipeline (CLAUDE.md item 14). When operator resumes play + RC-RewindCatchup scheduled task is wired, this will refresh automatically alongside the calibration data.

---

# s177 wrap — 2026-05-12 (Phase 4a champion ability ingest — single commit pending)

**Operator instruction:** "continue with the DS updates" — after s176 landed Phase 3, ship the next phase in [NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md](NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md).

Phase 4 is the largest data lift in the 6-archetype plan — three sessions (4a Meraki ingest + 4b `compute_ability_dps()` + 4c `rank_items_by_ability_dps()`). Phase 4a is data-only: pull the Meraki Analytics bulk champions endpoint, normalize each ability form into typed `damage_blocks` keyed by attribute with per-rank scaling fields, persist as a versioned snapshot. No formula evaluator this session — that ships in 4b.

## Ships

| File | Change |
|---|---|
| [tools/daemon_slayer_abilities_extract.py](tools/daemon_slayer_abilities_extract.py) | **NEW (~360 LOC).** Standalone extractor for Meraki bulk champions endpoint (`https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json`, 13MB single request, ~0.4s fetch). Pure functions: `_normalize_damage_type` (PHYSICAL_DAMAGE → PHYSICAL etc.); `_is_aoe` heuristic on `affects` + `targeting`; `_values_tuple` for mixed numeric/string Meraki value lists (handles "5%" strings); `_normalize_cooldown_or_cost` for both dict (`{modifiers:[{values:[...]}]}`) and bare-list inputs; `_classify_attribute` with NON_DAMAGE_HINTS denylist (reduction/amplify/critical-damage/monster/minion/non-champion) checked BEFORE damage allowlist so "Damage Reduction" / "Critical Damage" / "Monster Bonus Damage" route to "modifier"; `_normalize_modifiers` walks Meraki's `units[]` strings against `_UNIT_TO_FIELD` map producing typed scaling fields + an `unparsed_modifiers` bucket; `_build_damage_block` calls into both; `_build_form` aggregates blocks + computes per-form `parse_status` via three-disposition logic (typed_blocks / unparsed_blocks / empty_blocks). CLI: `py tools/daemon_slayer_abilities_extract.py [--force] [--patch X]`. Coverage logged at INFO level + persisted in snapshot. |
| [data/daemon_slayer/16.9.1/champion_abilities.json](data/daemon_slayer/16.9.1/champion_abilities.json) | **NEW snapshot.** 171/172 DDragon champions (Meraki bulk lags Zaahen by one patch — flagged). 927 ability forms total: 569 ok / 5 partial / 4 unparsed / 349 no_damage. Multi-form keys preserved: Aphelios 6× per Q/P (weapon stances), Jayce/Elise/Karma/LeeSin/Nidalee 2× per affected key, Sylas E 2×. **4 remaining unparsed** documented for Phase 4b follow-up: Illaoi.E "Damage Transmission" (spirit-reflection aggregate), Ryze.R "Bonus Overload Damage" (legacy field), Trundle.R "Subjugate" (ult HP-drain via target max HP%), MonkeyKing.W "Warrior Trickster" (clone-output scalar). |
| [agents/daemon_slayer/abilities.py](agents/daemon_slayer/abilities.py) | **NEW (~280 LOC).** Frozen dataclass loader: `DamageBlock` (attribute + attribute_kind + 14 per-rank scaling fields all `tuple[float,...] \| None` + `unparsed_modifiers` + `raw_modifiers`); `AbilityForm` (key + name + form_index + cooldown + cost + damage_type + targeting + affects + resource + is_aoe + damage_blocks + raw_effects_count + raw_leveling_count + parse_status + parse_notes); `AbilitiesSnapshot` with `.load(patch=None, data_root=None)` + `.get_abilities(champion_id)` + `.get_ability(champion_id, key, form_index=0)` + `.iter_forms()` + `.parse_status_counts()` + `.has_champion()` + `.champion_ids()`. Module-level `load_default()` / `reset_default_cache()` singleton mirrors `ult_rates.py`'s lazy-cache pattern. `DamageBlock.value_at(field_name, rank)` clamps rank to last element (single-value lists return that value at every rank — matches Meraki's "uniform across ranks" convention). |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | `ENGINE_VERSION` 0.64.0 → 0.65.0. Extended module docstring with Phase 4a changelog entry covering the Meraki schema-typing design, the 4 remaining unparsed niche aggregates, and the deferred Phase 4b/4c lifts. |
| [agents/daemon_slayer/tests/test_abilities.py](agents/daemon_slayer/tests/test_abilities.py) | **NEW (~430 LOC, 85 tests).** Pure-unit half covers extractor's normalization helpers via synthetic Meraki-shaped dicts (no HTTP): NormalizeDamageTypeTests (6), IsAoeTests (5), ValuesTupleTests (5), NormalizeCooldownOrCostTests (4), ClassifyAttributeTests (11 — pins denylist behavior on damage-reduction / critical-damage / monster / minion), NormalizeModifiersTests (10 — including same-field-summing + double-space variant for "%  of target's maximum health"), BuildDamageBlockTests (3), BuildFormTests (4 — pins parse_status decision-table across ok/no_damage/partial/unparsed). End-to-end half loads the live 16.9.1 snapshot: SnapshotLoadTests (9 — including MonkeyKing-keyed-by-DDragon-id guard + KSante / Wukong-not-present invariants), AatroxQTests (3), VeigarQTests (3), EzrealQTests (1), EzrealRTests (2 — 3-rank cooldown for ult), MultiFormTests (3 — Jayce 2×, Aphelios 6×), DamageBlockTests (5 — `value_at` clamp behavior), AbilityFormTests (1), CoverageThresholdTests (4 — locks 85% ok / 95% parsed bounds + iter_forms total + per-status drift guard), SingletonCacheTests (2), MissingSnapshotTests (4). |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Bumped `test_batch63_version` + `test_batch64_version` to assert ENGINE_VERSION 0.65.0; extended comment in batch63 docstring with the Phase 4a line. |
| Living docs sync | [CLAUDE.md](CLAUDE.md) (+s177 entry at item 34 + DS version pointer line 6) · [README.md](README.md) (header DS bullet + capability matrix + Daemon Slayer engine section) · [docs/DAEMON_SLAYER.md](docs/DAEMON_SLAYER.md) (status + module map row for `abilities.py` + `hybrid.py` backfill) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (DS section) · [ROADMAP.md](ROADMAP.md) (DS status line + s177 ship entry) · [BRIEF.md](BRIEF.md) (RC Tutor "what's built" line). |
| DS server runtime | Restart pending — `abilities.py` isn't loaded by the server yet (Phase 4b's evaluator will be the first consumer), but ENGINE_VERSION bump warrants a `Stop-Process` + relaunch so `/health` reports 0.65.0 next time anyone probes it. |

## Live validation

Extractor run on Legion against live Meraki bulk:

```
$ py tools/daemon_slayer_abilities_extract.py --force
2026-05-12 [INFO] fetching Meraki bulk champions: https://cdn.merakianalytics.com/...
2026-05-12 [INFO] Meraki bulk fetched: 171 champions (0.4s)
2026-05-12 [INFO] coverage: 927 forms · ok=569 partial=5 unparsed=4 no_damage=349
                  (ok_rate=98.4% parsed_rate=99.3%)
2026-05-12 [INFO] ✓ wrote data/daemon_slayer/16.9.1/champion_abilities.json (171 champions, 927 forms)
```

Loader round-trips for known shapes:

```python
>>> from agents.daemon_slayer.abilities import load_default
>>> snap = load_default()
>>> q = snap.get_ability('Aatrox', 'Q')
>>> q.name, q.damage_type, q.is_aoe
('The Darkin Blade', 'PHYSICAL', True)
>>> q.damage_blocks_only()[0].base, q.damage_blocks_only()[0].total_ad_pct
((10.0, 25.0, 40.0, 55.0, 70.0), (60.0, 67.5, 75.0, 82.5, 90.0))

>>> veigar_q = snap.get_ability('Veigar', 'Q')
>>> veigar_q.cooldown, veigar_q.cost
((6.0, 5.5, 5.0, 4.5, 4.0), (30.0, 35.0, 40.0, 45.0, 50.0))
>>> veigar_q.damage_blocks_only()[0].ap_pct
(50.0, 55.0, 60.0, 65.0, 70.0)

>>> ez_q = snap.get_ability('Ezreal', 'Q')   # Mystic Shot 130% AD across all ranks
>>> ez_q.damage_blocks_only()[0].total_ad_pct
(130.0, 130.0, 130.0, 130.0, 130.0)

>>> snap.has_champion('MonkeyKing'), snap.has_champion('Wukong')
(True, False)   # Meraki bulk keys by DDragon ID, not display name

>>> len(snap.get_abilities('Jayce')['Q']), len(snap.get_abilities('Aphelios')['Q'])
(2, 6)    # Hammer/Cannon stances; Severum/Gravitum/Infernum/Crescendum/Calibrum + base
```

## Findings

- **Meraki's bulk endpoint reverses the `id`/`key` field semantics versus the per-champion endpoint** — bulk top-level keys are DDragon-style (`Aatrox`, `MonkeyKing`, `KSante`), inside each record `id` is the numeric Riot key and `key` is the DDragon string. The per-champion endpoint flips them. Initial extractor passed `payload.get("id")` as the canonical key, which produced numeric-keyed output that no DDragon consumer could match. Fix: use the bulk's top-level key directly as canon. Test `test_monkeyking_keyed_by_ddragon_id` + `test_ksante_keyed_by_ddragon_id` pin this so future Meraki schema drift can't silently regress.
- **Cooldown/cost ship as `{modifiers: [{values: [...], units: [...]}]}`, not bare lists** — first extractor pass assumed bare lists per the plan's mental model. Fix: `_normalize_cooldown_or_cost` walks both shapes; preserves bare-list fallback for legacy compatibility. Veigar Q `(6.0, 5.5, 5.0, 4.5, 4.0)` confirms.
- **The "Damage Reduction" / "Critical Damage" / "Monster Bonus Damage" attribute-name footgun.** First-pass classifier flagged any attribute containing "damage" as damage-bearing — but Meraki uses "Damage Reduction" (a percent modifier), "Critical Damage" (a crit multiplier, not a damage source), and jungle-only "Monster Bonus Physical Damage" (irrelevant for champion-vs-champion DPS) under the same word. Fix: NON_DAMAGE_HINTS denylist checked BEFORE the allowlist. Bumped coverage from 86% ok to 98.4% ok on second pass.
- **Empty-damage-block aggregate footgun.** Nidalee Q's "Maximum Increased Damage" attribute ships in Meraki with `modifiers: []` (aggregate value computed from Min/Max + Increase columns). My status logic flagged the WHOLE form as `unparsed` if ANY damage block had no typed fields — even if all SIBLING blocks (Min Magic Damage, Max Magic Damage, Prowl-Enhanced Min/Max) parsed cleanly. Fix: three-disposition status logic (typed_blocks / unparsed_blocks / empty_blocks); a form with at least one typed block + some empty aggregates becomes `partial`, not `unparsed`. Bumped coverage from 88.9% ok to 98.4% ok.
- **Coverage exceeds the plan's 80% target by 18 percentage points (98.4% ok).** Only 4 forms genuinely unparsed; all are niche aggregates Phase 4b's evaluator can fall back on free-text parsing of `effects[].description` for if any become coach-critical. Comparable rates per ability key: P=100% (only one passive has damage modifiers in Meraki — Mel — and it parses), Q=98.9%, W=99.1%, E=99.3%, R=98.5%. No systemic per-key blind spot.
- **Multi-form preservation matters more than I initially budgeted for.** Aphelios alone is 6 forms × 5 keys = 30 ability records; without form_index discipline the engine would silently see Calibrum's Q and Severum's Q as the same form. Mid-game weapon swaps mean the active form changes ability-to-ability — Phase 4b's evaluator needs to consume a `current_form` field from the LCU agent or fall back to form_index=0 average.
- **`load_default()` singleton + `reset_default_cache()` is the right pattern for hot paths.** Each coach tick will run `compute_ability_dps()` on ~5 abilities × 8 candidate items; without caching the snapshot the JSON parse cost would dominate. The lazy-singleton path matches `ult_rates.py`'s pattern operator-validated against the warm-Agent-7 prime budget. Test `test_load_default_caches` pins it.

## Verification

- `py -m pytest agents/daemon_slayer/tests/test_abilities.py -v` → **85 passed**
- `py -m pytest agents/daemon_slayer/tests/` → **1151 passed** (was 1066 — +85 net)
- `py -m pytest tests/ --timeout=120` → **902 passed** (wider RC; no regressions)
- `py -m ruff check agents/daemon_slayer/abilities.py agents/daemon_slayer/tests/test_abilities.py tools/daemon_slayer_abilities_extract.py` → all checks passed
- Coverage threshold test in `CoverageThresholdTests` defends future Meraki schema drift: asserts `ok_rate >= 0.85` + `parsed_rate >= 0.95` (currently 0.984 / 0.993).
- Live extractor run shows the new snapshot 13MB Meraki fetch is ~0.4s; total extract+normalize+write 0.5s end-to-end.

## Open items carried forward

- 🟡 **Phase 4b — `compute_ability_dps()` evaluator** — next session per the plan. New `agents/daemon_slayer/ability_dps.py` resolves the typed scaling fields against `CallContext` (current AD/AP/HP/level/target stats), computes per-cast damage, multiplies by cast rate. Extend `ult_rates.py`'s schema to P/Q/W/E from current ult-only — `rewind_history.db.participants.spell{1,2,3,4}_casts / game_duration_s` already has the data. Mana-economy denominator (`mana_per_rotation / caster_max_mp`) gates Phase 4b's "rotation feasibility" sanity check.
- 🟡 **Phase 4c — `rank_items_by_ability_dps()` + `/rank-mage`** — third session of the lift. Mirror `rank_items` / `rank_items_by_ehp` / `rank_items_by_hybrid` shape but score candidates by `ability_dps_total` delta. Wire `/rank-mage` route + `rank_mage_for()` client helper + integration into `rank_for_primary_archetype()` dispatcher's mage branch (removes the `fell_back=True` path).
- 🟡 **4 unparsed forms** — Illaoi.E Test of Spirit, Ryze.R Realm Warp, Trundle.R Subjugate, MonkeyKing.W Warrior Trickster. All niche aggregates. Phase 4b can fall back to free-text parsing of `effects[].description` if any become coach-critical; documented in the test file under `CoverageThresholdTests` so the threshold guard catches a regression below 85% ok.
- 🟡 **DS server restart** — `/health` will report 0.64.0 until next stop+relaunch. Phase 4a doesn't change any active route, but the version pointer drifts. Run `taskkill /F /PID <pid>` + `pythonw tools/start_daemon_slayer.py` (per `reference_ds_server_not_supervisor_watched`) before declaring s177 fully landed.
- 🟡 **Phase 4 cadence vs Phase 5/6** — once Phase 4 lands, dispatcher's mage branch loses `fell_back=True`. Phase 5 (Assassin burst) reuses Phase 4 ability data and adds a combo-window scorer (Q→W→E→AA→R→AA per champ). Phase 6 (Enchanter HPS) is the lowest-fidelity tier per the plan — model heal-per-gold against a static "average teammate" model.
- 🟡 **Meraki schema drift watchdog** — `CoverageThresholdTests` will redden CI if Meraki changes their unit strings or attribute taxonomy meaningfully. Worth adding a Phase 7-style nightly cron that re-runs `tools/daemon_slayer_abilities_extract.py --force` + smoke-tests the loader; for now the threshold test catches it on the next CI run.
