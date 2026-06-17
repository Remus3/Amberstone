# DS Permutation Swarm - Maximize DS Logic Across All Context Permutations

OPERATOR DIRECTIVE 2026-06-17 (headless loop). Maximize Daemon Slayer build/scorer
correctness across EVERY context permutation: self runes + summoner spells + ally team
+ ally runes/auras + enemy team + enemy runes. Adapt to lolmath at minimum. Implement
findings to the smallest benefit. Outcome-anchored on `data/rewind_history.db` WIN data,
never eyeballed. Many sessions; the gemini director picks ONE bounded session per cycle.

## Tractability (raw cross-product is astronomical - bucket, do not enumerate)

172 champs x runes x summoners x ally-comp x enemy-comp is millions of cells. We do NOT
enumerate. We model each dimension as a SEAM on the scorer that consumes a small set of
representative BUCKETS, validate the seam offline against Meraki + WIN data, ship it
DEFAULT-OFF, and leave the live default-ON flip to the synced live-game pass.

Buckets per dimension:
- enemy-comp: frontline_heavy / burst_heavy / poke / mixed (the HZ-B2 set, `core/aram_comp_verdict.compute_factors`).
- enemy target presets: tank-heavy / squishy-carry / bruiser-mixed / high-CC (extends DSV3 `assume_squishy_target`).
- self-rune keystones (combat): PressTheAttack / LethalTempo / Conqueror / Electrocute / DarkHarvest / Comet / FleetFootwork / Grasp / HailOfBlades + relevant minors.
- enemy-rune threat: enemy Conqueror (true-dmg ramp) / PtA (amp) / Grasp+SecondWind (poke resist) / antiheal-source present.
- ally aura/enchanter: enchanter-present {none, shield-heavy, heal-heavy} + external resist grant (Locket/Orianna-E class).
- summoner combat set: Ignite / Exhaust / Heal / Barrier / Cleanse|QSS / Ghost.

## Engine seams - HAVE vs NEW (grounded 2026-06-17)

| Dimension | Status | Seam / file | Pattern |
|---|---|---|---|
| enemy target armor | HAVE | `burst.py` `assume_squishy_target` + `effects.effective_target_armor` (DSV3) | extend to comp presets |
| enemy item modeling | HAVE | `agents/daemon_slayer/tests/test_enemy_item_modeling_p1l1.py` + hybrid-enemy | reuse |
| kill-state passives | HAVE | `dps.py`/`burst.py` `assume_takedown` (DSV2) | reuse |
| ability amp | HAVE | `dps.py` `assume_ability_amp` (DSV4) | reuse |
| ally amp / aura | HAVE | `agents/daemon_slayer/allyamp.py` + `_passive_ally_grant_overrides.py` + Orianna-E external_resist (item316) | extend to aura buckets |
| self runes (procs) | HAVE partial | `rune_procs` (test_rune_procs.py) + per_attack + keystones + `core/rune_wpa.py` | complete keystone+minor coverage |
| summoner spells | NEW | none - build `agents/daemon_slayer/summoners.py` seam | default-OFF |
| enemy runes (threat) | NEW | none - build enemy-rune threat modifiers on target/EHP presets | default-OFF |

## The seam contract (every DSP engine session)

1. Root-cause-first (`/root-cause-fix`): failing characterization test FIRST, sibling sweep, backfill.
2. Default-OFF, byte-identical when off (the DSV1-4 precedent). NEW `ItemEffect`/scorer-kwarg seam.
3. Offline validation: Meraki bulk (`/items.json`, `aram_modifiers`) for magnitudes; `data/rewind_history.db`
   WIN data for direction. NEVER aggregator D/aggregator A for magnitudes.
4. `ENGINE_VERSION` bump (quoted-literal only, `feedback_engine_bump_quoted_literal_only`) + DS `:8893`
   taskkill+`schtasks /Run /TN RC-DaemonSlayer` + `ds_share_sync.py` + `--check` in the SAME commit.
5. The live default-ON flip is EXCLUDED (do-not-flip-blind) -> append it to `docs/LIVE_GAME_GATED_SYNC.md`.

## Validation anchor

- `data/rewind_history.db` (~2941 matches, 147-col participant rows) = WIN outcomes per (champ, build, comp).
- `ops/audit/ds_cross_eval/data/<Champ>.json` (172 files) = the 2026-06-16 per-champion cross-eval baseline;
  the swarm CONSUMES + extends it. Systemic clusters from that run: A archetype-vs-ARAM-win divergence,
  B generic-marksman-template on AD scorers, C Aphelios zero-output (FIXED, ENGINE 1.128.0).
- Harness (DSP1) scores DS top-N vs WIN-rate per context bucket; difference-of-differences, not fragile
  cross-item equality.

## Swarm topology

- Per-champion AUDIT lanes (DSP2/3/10): 1 worktree agent per champion or champion-cohort, disjoint
  `ops/audit/ds_cross_eval/data/<Champ>.json` + per-champ test files. Up to 100 concurrent, sole merger.
- Per-dimension SEAM lanes (DSP4-8): 1 agent per seam on a disjoint scorer-file set.
- Every agent prompt carries the don't-redo set (CLAUDE.md "Settled" + this contract) + must `ruff` before done.
- `verifier` subagent gates each slice claim before merge; `truth_gate.py` before any multi-slice commit.

## Bounded sessions (director picks ONE per cycle, top-down)

- DSP1 harness + anchor (BUILD only, no engine change): per-(champ x bucket) DS-top-N vs rewind WIN-rate scorer
  + report writer under `ops/audit/ds_perm_swarm/`. Hermetic tests. Foundation for all below.
- DSP2 Cluster B fix: generic-marksman-template leaking onto non-marksman AD scorers (named systemic bug).
- DSP3 Cluster A fix: archetype-vs-ARAM-win divergence (weights/archetype resolution; `core/archetype_picks`).
- DSP4 self-rune completion seam: keystones+minors not yet scored; extend `rune_procs`/`core/rune_wpa.py`.
- DSP5 summoner-spell seam (NEW `summoners.py`): Ignite antiheal+true, Exhaust incoming-DR, Heal/Barrier EHP,
  Cleanse/QSS CC-duration discount, Ghost MS. default-OFF.
- DSP6 enemy-rune threat seam (NEW): enemy Conqueror/PtA/Grasp+SecondWind/antiheal modulate target + EHP presets. default-OFF.
- DSP7 ally aura/enchanter seam: extend `allyamp.py` + `_passive_ally_grant_overrides.py` to enchanter/shield/heal buckets. default-OFF.
- DSP8 enemy-comp target-preset seam: extend DSV3 into tank-heavy/squishy/bruiser/high-CC presets. default-OFF.
- DSP9 lolmath parity fold (P6 G3 runes + G7 comp-harness): re-run `ops/audit/lolmath_ds_sweep` with DSP4-8 seams
  ON in-harness; close residuals to >= lolmath parity. G6 cost-model = Gemini-consult (PART C), not blind build.
- DSP10 full permutation cross-eval re-run: per-champion swarm over the bucket matrix, all seams harness-ON,
  WIN-anchored; emit consolidated mismatch report + per-champ implement-to-smallest-benefit fixes.

## Done / stop

- Each DSP session ships an ENGINE bump + tests OR records a CLEAN no-change with WIN-data evidence.
- Stop the swarm when DSP10 returns 2 consecutive no-new-fix passes (the loop-until-dry rule).
- Every default-OFF seam's live flip lands in `docs/LIVE_GAME_GATED_SYNC.md` for the operator's live pass.
