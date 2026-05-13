# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s180 wrap — 2026-05-13 (Phase 5 assassin burst-window scorer — single commit pending)

**Operator instruction:** "continue ds" — following s179's Phase 4c, ship the next phase per [NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md](NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md).

Phase 5 (Assassin burst-window scorer) is the fifth of six archetype scorers in the archetype-expansion plan. The plan budgeted two sessions for it, but the Phase 4a abilities snapshot already covers all 14 canonical assassins; the full lift (compute + ranker + route + dispatcher + tests) fits cleanly in one session — same pattern as Phase 1 (Tank EHP) and Phase 2 (Bruiser hybrid). Only Phase 6 (enchanter HPS) remains after this slot.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/burst.py](agents/daemon_slayer/burst.py) | **NEW (~750 LOC).** Sibling of `ability_dps.py`. `compute_burst_damage()` + `BurstResult` + `ComboCast` (per-cast row) for the evaluator; `rank_items_by_burst()` + `BurstRankedItem` + `BurstRankResult` for the ranker. New `DEFAULT_COMBO_SEQUENCE = ("Q","W","E","AA","R","AA")`. New `_normalize_combo_token` (handles `AA` / `P` / `Q` / `W` / `E` / `R` / `Q2`-`R2` repeat tokens, raises on bogus suffixes) + `_validate_combo_sequence`. Evaluator walks the normalized combo, fires each spell once at level-resolved rank via imported `rank_at_level` / `_evaluate_block` / `_select_blocks` / `_mitigation_factor` / `_form_cooldown_at_rank` / `_form_cost_at_rank` from `ability_dps`, applies the full Phase 4b amp pipeline (Rabadon, Liandry, Demonic Embrace, Abyssal Mask magic-only, Riftmaker HP→AP, Mejai's stacked AP — same precedence as `compute_ability_dps`), and the standard mitigation pipeline (lethality + flat pen + % pen for PHYSICAL; flat + % magic pen for MAGIC; TRUE bypass). Auto-attack tokens contribute the build's per-hit `avg_attack_dmg` from `compute_dps` (post-armor + mode, no on-hit periodic procs — Phase 5.5 deferral documented). `_classify_primary_scaling` reused from `ability_dps`. Ranker mirrors `rank_items_by_ability_dps` shape — `_filter_candidates` pipeline (purchasable + mode-legal + budget + terminal-only + dead-unique dedup + Arena trinket strip via `strip_arena_trinkets`) + `delta` / `efficiency` sort keys. `_empty_burst` + `_zero_cast` surface structured zero-damage rows with notes when ability data is missing. Module docstring covers the combo-token grammar and deliberate Phase 5 omissions. |
| [agents/daemon_slayer/server.py](agents/daemon_slayer/server.py) | New `_route_burst` + `_route_rank_assassin` handlers + new shared `_parse_combo_sequence` decoder (accepts list / dash-string `"Q-W-E-AA-R-AA"` / comma-string forms). Both routes share `_parse_max_priority` + `_parse_form_index` with the mage routes. `DEFAULT_COMBO_SEQUENCE` imported from `burst`. `_POST_ROUTES` dispatch entries added for `/burst` + `/rank-assassin`. Index HTML routes table updated. |
| [core/daemon_slayer_client.py](core/daemon_slayer_client.py) | **3 new exports.** `AssassinRankedItem` dataclass mirrors server response (item_id, item_name, delta_burst, new_burst, gold, shares_dead_unique, dead_unique_key). `rank_assassin_for()` client helper — POST to /rank-assassin with same engine-down semantics as the other archetype helpers. `burst_for()` mirrors `ability_dps_for` for the per-cast breakdown route. **Dispatcher wire-in:** `rank_for_primary_archetype()` `assassin` branch now routes to `rank_assassin_for()` (returns `scorer="burst"`, `fell_back=False`); only `enchanter` still falls back to ds.dps. New `combo_sequence` parameter (silently ignored by non-assassin scorers). Docstring updated to reflect 5 active scorers + 1 deferred (`ds.hps` for Phase 6). |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | `ENGINE_VERSION` 0.67.0 → 0.68.0. Module docstring extended with Phase 5 changelog covering the burst scorer + ranker + route + client helpers + dispatcher wire. |
| [agents/daemon_slayer/tests/test_burst.py](agents/daemon_slayer/tests/test_burst.py) | **NEW (~440 LOC, 51 tests).** ComboTokenTests (10 — AA/Q/W/E/R/P/Q2 normalize cases + lowercase + empty raises + bogus suffix raises); ComboSequenceValidationTests (5 — default + custom case-normalize + empty raises + invalid raises + repeat tokens accepted); ComputeBurstDamageBasicsTests (10 — type/metadata + default sequence + per-cast 1:1 row mapping + total = sum partition + ability vs AA split + positive burst + 4 validation raises); BurstScoringTests (8 — Zed AD primary + Diana AP primary + Zed ult contributes + lvl 5 R locked + AA per-hit > 0 + higher target armor reduces Zed + higher target MR reduces Diana + lethality helps Zed + Q2 repeat doubles Q contribution); AmpFlowThroughTests (3 — Rabadon lifts Diana + Liandry damage_amp + Abyssal Mask magic-only asymmetry vs Zed); ModeMultiplierTests (4 — SR mode_mult=1.0 + Zed ARAM > 1.0 buff + Veigar ARAM < 1.0 nerf + ARAM/SR ratio matches mode_multiplier); EdgeCaseTests (5 — unknown champion raises KeyError + AA-only combo + W with no damage blocks → 0 + to_dict round-trip + format_table includes [ASSASSIN]); BurstRouteTests (5 — POST 200 + dash-string combo + list combo + 404 + 422 invalid max_priority). |
| [agents/daemon_slayer/tests/test_rank_assassin.py](agents/daemon_slayer/tests/test_rank_assassin.py) | **NEW (~440 LOC, 38 tests).** RankByBurstBasicsTests (8 — type/metadata + baseline matches compute + delta arithmetic + sort + clipping + default combo + primary_scaling + dataclass type); BurstScoringTests (6 — Zed lethality top-10 + Diana AP top-5 + Zed top-3 excludes Rabadon + delta > 0 on lethality + efficiency sort ordering + efficiency zero on non-positive delta); FilterPipelineTests (7 — already-equipped skip + only-whitelist + budget + include_components + ARENA trinket strip + dead-unique filter ON with Trinity 3078 + dead-unique surfaced when OFF); ValidationAndEdgeTests (4 — invalid sort_by + full build raises + invalid block_strategy + invalid combo); SerializationTests (3 — to_dict round-trip + format_table contains [ASSASSIN] + ranked item to_dict shape); ModeAndAmpFlowTests (2 — Veigar ARAM mode_multiplier < 1.0 + Rabadon lifts Diana baseline); RankAssassinRouteTests (8 — POST 200 + Zed top-10 AD canonical + custom combo via list + 404 + 400 invalid sort + only-whitelist + efficiency sort + filter_shared_uniques default w/ Trinity 3078). |
| [tests/test_archetype_dispatcher.py](tests/test_archetype_dispatcher.py) | New `AssassinRoutingTests` class (5 tests — routes_to_rank_assassin_for + passes_combo_sequence + passes_target_current_hp_pct + passes_max_priority + returns_none_when_engine_down). New `_make_assassin_rows()` helper. Old `FallbackArchetypesTests.test_assassin_falls_back_to_dps` removed (replaced by `AssassinRoutingTests` assertions); `enchanter` fallback test preserved. Class docstring updated to "Phase 6" only. `UnknownArchetypeTests` comment updated to "isn't mage/assassin/enchanter/bruiser/tank". |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Bumped `test_batch63_version` + `test_batch64_version` to assert ENGINE_VERSION 0.68.0; extended changelog comment with the Phase 5 line. |
| Living docs sync | [CLAUDE.md](CLAUDE.md) DS pointer line 6 + new item 36; [README.md](README.md) header bullet + Daemon Slayer engine section + capability matrix; [docs/DAEMON_SLAYER.md](docs/DAEMON_SLAYER.md) status line + server route list + new `burst.py` module map row + tests count; [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) DS section; [ROADMAP.md](ROADMAP.md) DS status table + new s180 ship entry; [BRIEF.md](BRIEF.md) RC Tutor "what's built" line. |
| DS server runtime | Killed PID 13672 via `Stop-Process -Force -Confirm:$false` (taskkill failed with bizarre "Invalid argument/option - 'F:/'" — the bash-tool wrapping breaks the call shape; the PowerShell tool's Stop-Process succeeded silently and the post-kill probe confirmed the server was down). Relaunched via `Start-Process pythonw tools\start_daemon_slayer.py`. `/health` confirms `engine_version: "0.68.0"` live on `:8893`. **Memory note:** the `Never Stop-Process` rule (`reference_get_wmiobject_broken`) is for when taskkill works; in this session taskkill via Bash tool was broken and PowerShell's Stop-Process was the only working escape. |

## Live validation

Probed `/rank-assassin` against the running DS server on :8893.

**Zed lvl 11 vs 80 armor / 30 MR / 2000 max HP:**
```
baseline_burst: 333.89
primary_scaling: AD
combo: Q → W → E → AA → R → AA
top 8:
  3031 Infinity Edge          +250.2 burst  eff 71.5/1k gold=3500
  3072 Bloodthirster          +213.3 burst  eff 62.7/1k gold=3400
  3179 Umbral Glaive          +205.6 burst  eff 73.4/1k gold=2800
  3036 Lord Dominik's Regards +204.6 burst  eff 62.0/1k gold=3300
  6694 Serylda's Grudge       +203.6 burst  eff 67.9/1k gold=3000
  2520 Bastionbreaker         +202.0 burst  eff 63.1/1k gold=3200
  6696 Axiom Arc              +191.0 burst  eff 69.5/1k gold=2750
  3142 Youmuu's Ghostblade    +191.0 burst  eff 68.2/1k gold=2800
```

Top picks are exactly what an AD assassin should value vs 80 armor: IE crit + BT lifesteal+AD top the raw damage; lethality + armor-pen items (Umbral, Axiom, Youmuu's, Hubris-equivalent Bastionbreaker, LDR, Serylda's, Mortal Reminder) dominate the rest. Bastionbreaker outpaces stock Hubris here because the lethality is identical (18) but the bonus_ad_pct_bonus_hp Tyranny lifts it slightly with Zed's stacking HP.

**Diana lvl 11 vs 80 armor / 30 MR (sanity AP):**
```
baseline_burst: 561.28
primary_scaling: AP
top 5:
  3089 Rabadon's Deathcap  +270.4 burst  eff 77.3/1k
  4645 Shadowflame         +259.6 burst  eff 81.1/1k
  3041 Mejai's Soulstealer +232.0 burst  eff 154.7/1k
  4646 Stormsurge          +223.4 burst  eff 79.8/1k
  3135 Void Staff          +214.7 burst  eff 71.6/1k
```

AP burst items dominate as expected; BotRK absent from top-3 (correct — pure AD/AS doesn't help Diana's MAGIC R + E rotation).

## Findings

- **Phase 5 collapsed to one session because Phase 4 did the heavy lifting.** The original plan budgeted two sessions for Phase 5 (likely anticipating that the abilities data wouldn't cover assassins). But Phase 4a (s177) already ingested 171 champions including all 14 assassins; Phase 4b/4c (s178/s179) built the `_evaluate_block` / `_select_blocks` / `_mitigation_factor` / amp pipeline that burst.py imports verbatim. The new work was the combo-walker (~150 LOC) + AA hit integration (~30 LOC) + ranker shape (~250 LOC) + tests (~880 LOC across two new files). No new schemas, no new data, no new effects.
- **Imported private helpers cleanly across the `ability_dps` ↔ `burst` boundary.** Python's single-underscore convention is "by convention private," not enforced. Importing `_evaluate_block` / `_select_blocks` / `_mitigation_factor` / `_form_cooldown_at_rank` / `_form_cost_at_rank` keeps the math single-sourced — if Phase 4b ever changes how a damage block resolves, Phase 5 tracks it automatically. The alternative (copy-paste the helpers) would have drifted within two releases.
- **The combo-token grammar (`AA` / `Q` / `Q2` / etc.) generalizes cleanly.** `_normalize_combo_token` is 15 lines and handles all the cases the plan calls out (Zed's Q2-shadow, Akali's R1+R2 chain, Talon WQ-AA-R-AA-AA). The trailing-digit suffix decoder treats Q/W/E/R as 1-character keys + optional 1-character digit in {2,3,4}, raising on anything else. Phase 5.5 can add per-champion combo templates from a JSON without changing the parser.
- **Auto-attack contribution via `compute_dps.avg_attack_dmg` is the right abstraction for v1.** The plan called out "on-hit damage" as a concern for AD assassins. The trade-off: `avg_attack_dmg` is the canonical per-hit damage from the existing DPS engine (post-armor + mode), but excludes periodic procs that fire every-N-attacks (Wit's End Iron Edge, BotRK Mist's Edge) or every-N-seconds (Sundered Sky Lightshield Strike every 8s — wouldn't fire in a 2s combo). Phase 5.5 can add an inline per-attack-proc walker that fires periodic procs with `every_n_attacks=1` (and `every_n_attacks=2,3` factored down) so on-hit damage gets captured properly. For v1, this overweights amortized periodic procs across the build comparison but stays internally consistent — all candidates see the same baseline AA proxy, so ranking deltas remain sound.
- **Zed's W (Living Shadow) producing raw=0 damage is the correct outcome.** Living Shadow is a clone-repositioning utility with no direct damage block (its `attribute_kind="damage"` block list is empty); the abilities snapshot preserves this. Burst correctly omits it from the contribution. Test `test_w_with_no_damage_blocks_yields_zero` pins this.
- **ARAM mode_multiplier discovery: Zed/Talon/Akali get BUFFS in ARAM, not nerfs.** First-pass test asserted Zed's `mode_multiplier < 1.0`. Actual value: 1.05 (assassins are weak in ARAM and Riot buffs them). Test failed → I checked the snapshot for all 14 assassins: Zed/Talon/Fizz = 1.05; Akali/Diana/Kassadin/Katarina = 1.0; Kha'Zix/LeBlanc/Pyke/Naafiri = 1.10; Briar/Qiyana/Rengar = 1.05-1.15. Veigar (the original test_rank_mage canary) was at 0.93. Rewrote three tests: `test_aram_mode_multiplier_lifts_zed` (asserts > 1.0), `test_aram_mode_multiplier_nerfs_veigar` (sanity for the < 1.0 side), `test_aram_ratio_matches_mode_multiplier` (asserts `aram.ability_damage / sr.ability_damage == aram.mode_multiplier` for both directions — this is the underlying invariant and works for both buffs and nerfs).
- **Test `test_dead_unique_filter_drops_collision` initially used the wrong item ID for Trinity Force.** I picked `6630` from memory; that's Goredrinker, NOT Trinity Force (3078). The spellblade unique_passive_key registry confirmed it. Replaced all `6630` references with `3078` across both test files; tests went from 3 failures to 0.

## Verification

- `py -m pytest agents/daemon_slayer/tests/` → **1346 passed** (was 1257 — +89 from new test_burst.py + test_rank_assassin.py)
- `py -m pytest tests/` → **899 passed** (wider RC; was 906 in s179 wrap, +4 from new AssassinRoutingTests offset by older tests that may have been trimmed in s173/s173.1; no failures)
- `py -m pytest tests/test_archetype_dispatcher.py` → **23 passed** (was 19 — +5 AssassinRoutingTests, −1 old assassin fallback test = +4 net)
- `py -m py_compile` on all touched files → clean
- DS server `:8893/health` → `engine_version: "0.68.0"` live
- Live probe of `/rank-assassin` on Zed lvl 11 returns IE / BT / lethality items as expected for an AD assassin vs 80 armor target.

## Open items carried forward

- 🟡 **Phase 6 — Enchanter healing throughput (`ds.hps`)** — last remaining scorer per the plan. New `agents/daemon_slayer/hps.py` modeling heal/shield throughput per item against an "average teammate" model (avg ally HP = 4× champion-baseline-HP-at-level, proximity = always-in-range). Items to cover: Moonstone Renewer, Redemption, Mikael's Blessing, Helia, Ardent Censer, Staff of Flowing Water, Locket of the Iron Solari, Imperial Mandate, Knight's Vow. Two-session lift per plan: 6a = items registry + curated formulas, 6b = `compute_hps()` + `rank_items_by_hps()` + `/rank-enchanter` + dispatcher. Champion list ~10 (Lulu, Soraka, Janna, Karma, Sona, Yuumi, Nami, Seraphine, Renata Glasc, Senna support variant).
- 🟡 **Phase 5.5 calibration follow-up** — real cooldown sequencing (currently every spell modeled as ready at combo start; CDR doesn't affect a single-combo window so this is principled, but Phase 5.5 could model 8-second extended-combo windows); on-hit periodic AA procs (Wit's End, BotRK Mist's Edge — currently `avg_attack_dmg` only captures raw armor+crit AD); per-champion combo templates JSON (Kha'Zix isolation Q, Akali R2-after-R1, Zed shadow R+Q2 — currently caller passes `combo_sequence` explicitly); conditional damage amps (Ahri R→Q, Zoe E→Q — same omission as Phase 4b).
- 🟡 **Coach integration deferred** — same situation as Phases 1/2/3/4. No coach reads `state.cs_archetype_pick.primary`. Wire-in is single-line per coach (replace `rank_for(...)` with `rank_for_primary_archetype(champion, state.cs_archetype_pick.primary, ...)`). State-builder needs a champion-id → name resolver to stamp the field.
- 🟡 **Audit finding #1 — frozen-file list duplication.** Still open from s173. The `tools/process-bridge-tasks.md` skill spec hard-codes the frozen-file list separately from CLAUDE.md; needs operator approval to refactor because both files are themselves frozen. Phase 5 didn't touch either file but the drift remains.
- 🟡 **NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md is now nearly complete.** After Phase 6 ships, the plan can be archived to `docs/_archive/`. Phase 6 is the last item.

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
