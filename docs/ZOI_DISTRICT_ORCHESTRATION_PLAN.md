# ZOI / Minimap-District Deterministic-Macro Coaching - Orchestration Plan

## 1. Program summary + north-star

This program turns Riot Commander's presence-only ZOI minimap stack into a per-mode (SR / ARAM / Arena) deterministic-macro coaching system: the single outer minimap square becomes a labelled district partition, per-district team presence gets stable last-seen counters, those CV signals are cross-confirmed against the Live Client `:2999` event/state stream, and a pure rule/decision-tree engine emits macro callouts ("drake in 40s, 3 enemies MIA bot-river - ward and group") on the EXISTING served `/api/state.callouts` path. Later phases add minimap identity (template-match), MIA reachability rings, and capability-weighted influence bubbles with a fluid oil-and-water DMZ. NORTH-STAR: every macro read the system precomputes deterministically is a read the coach otherwise pays an LLM to reason about, so this program drives live Haiku/Sonnet spend toward ZERO by making the macro layer local, free, and correct-by-construction, with Claude reserved for the reads that genuinely need language.

## 2. What ALREADY EXISTS to build on (cited file:line)

The 4-stage CV chain is shipped and live: geometry -> grab -> blob-detect -> influence, all box-fraction `[0,1]`, all fail-soft.

- `core/minimap_geometry.py:82-116` - `compute_minimap_rect(scale, flip, W, H)` -> frozen `MinimapRect(x,y,w,h,flip)` (`:55-67`), AFFINE `side_frac = 0.0764*scale + 0.1651` (`:97`), bottom-right anchor flips to bottom-left (`:104-108`). Fixed 2026-07-05. Emits ONLY the outer square - no sub-geometry yet.
- `core/minimap_blob_detect.py:68` - `detect_team_dots(rgb)` -> `[{team, x_frac, y_frac, px, confidence}]` (`:110-114`), box-fraction within crop. PRESENCE, NOT IDENTITY (`:16-19`). `current_minimap_dots` grab layer (`:234`), native 416px grab `_grab_native_minimap` (`:187-206`, `RC_ZOI_NATIVE_GRAB` default on), `crop_minimap` fraction-of-frame (`:120-135`), numpy-absent degrade (`:83-84`).
- `core/zoi_influence.py:258-344` - `compute_zoi(dots, my_level, game_time_s)` -> EXACTLY `{bubbles, demarcation, map_control}`; bubbles `{team, cx, cy, r_frac, weight}` (`:290-295`, `weight = px*confidence`); `_bubble_radius_frac` (`:84`), `_ally_power`/`_enemy_power` (`:67, :78`); `_demarcation` straight clipped bisector (`:144`); `_action_quadrant` 9-cell prototype (`:177-203`) + `_QUADRANT_READABLE` (`:206-216`). Pure, no numpy, no I/O, never raises (`:10`).
- `dashboard/_state_builder.py:441-480` - `minimap_rect` (gated `sr/aram/brawl`, `:442`), `minimap_dots` (`:453-460`), `zoi` (gated `sr/aram`, `:468-480`); packed `:578-580`.
- `dashboard/_liveclient.py` - event stream (top-level `d.get("events")`, warned `:226-229`): `turret_events` (`:246-257`), `inhib_events` (`:230-241`), `objective_events` dragon/baron/herald + `killer_team` (`:265-306`); per-champ public scoreboard `allPlayers[]` (`:128-203`); active-player-only gold/HP (`:101-105`, `:147`). HARD LIMITS - no live enemy xy / HP / gold / wards / cooldowns / buffs (`:106-110`, `:155-159`).
- `core/vision_tracker.py:300-389` - per-enemy `{champion, team, level, is_dead, respawn_in_s, visible, missing_for_s, last_seen_pos:{x,z}, last_seen_t, last_seen_zone}`; SR map extent ~14800 (`:55`); shared-vision force `visible=true`/`on_bridge` for ARAM/KIWI (`:51, :332-340`); relay reset `_RELAY_MAX_AGE_S` (`:41, :234-241`).
- `core/event_callouts.py:66-112` static SR schedule + derived timings: `_INHIB_RESPAWN_S=300`, `_inhib_lane` (`:441-495`), `_BARON_BUFF_S`/`_ELDER_BUFF_S` (`:87-89`), `SR_DRAGON_RESPAWN_S=300`/`SR_BARON_RESPAWN_S=360` (`:67-69`); canonical callout schema `{tag, line, eta_s, kind}`.
- `dashboard/_deterministic_coaching.py:501-606` - `_compute_uncached` served splice sink (`det["callouts"]`); density clamp (`:596-600`); cache-sig completeness (`:418-488`); test-reset seam (`:231`); reused helpers `_next_objective_spawn` (`:158-176`), `_enemy_has_smite` (`:472-483`), `_is_enemy_jungle_zone` (`:486-498`), missing-filter (`:217-228`).
- `core/decision_detector.py:133-142` - `DECISION_REGISTRY` registry-of-pure-predicates doctrine (the pattern the macro engine mirrors).
- `core/feature_policy.py:71-77, 305-350` - existing per-mode capability matrix (`_KNOWN_FEATURES`, `is_allowed`, safe-default TRUE - the WRONG default for ward gating). Ward-scoring literal to replace: `game_reader/snapshot_normalizer.py:384-392` (`game_mode == "CLASSIC"`), generator `:987-1008`; ward prompting `coach_integration/_sr_prompt.py:97-102` (static) + `:438-439` (dynamic). Mode constants + `mode_from_game_mode_string` `core/game_snapshot.py:63-95`.
- `core/archetype_picks.py:592` - `get_archetype_for(champ)` -> `{"primary": one of carry/bruiser/tank/mage/assassin/enchanter}` (`:59`); reused by `core/build_planner/kit_synergy.py:97-113`. The capability-weight source for Phase 3.
- Overlay render: `web/index.html:2139` mount `#am-mmrect` + `#am-zoi-canvas`; `web/js/panels/minimap_rect.js:73-136` design-px -> window-fraction + zoom-cancel; `web/js/panels/minimap_zoi.js` box-fraction paint (`fracToPx:87-93`, `_paint:298-371`, `normZoi:140` drops unknown keys safely, opacity-fix `:415`, `MAX_ALPHA=0.55` `:48`, JS test export `:452`); the live-paint seam `web/js/main.js:6852-6876` (`setupMinimapPoller`, 2s, overlay-only, `sr/aram/brawl`).
- OBS enabler: `core/obs_publisher.py` complete OBS-WS v5 client (`_identify:222-263`, `_set_text:282-298` fire-and-forget, `_drain_pending:265-280`); wired `dashboard/server.py:259-260`, config-gated `obs.enabled`; `websockets` already in `requirements.txt` (NO new dep). Frame cache `vision_server/_frame.py:57-141, 231-254` (GDI self-grab swap point). Plan doc `docs/OBS_CV_MINIMAP_PLAN.md:56-64, 100-120`.
- Assets: `data/icons/champions/*.png` (173 icons on disk, verified), `data/meta/ddragon_champions.json` `stats.movespeed` (=345 confirmed), item MS stat vocab `agents/daemon_slayer/stats.py:107-108`.

GREEN-FIELD (do not exist yet, verified 2026-07-05): `core/minimap_districts.py`, `core/minimap_presence.py`, `core/mode_capabilities.py`, `core/district_fusion.py`, `core/macro_decision_tree.py`, `core/macro_context.py`, `core/minimap_identity.py`, `core/mia_reachability.py`, `core/champion_movespeed.py`, `core/zoi_capability.py`, `core/zoi_field.py`, `core/zoi_mia.py`, `config/minimap_grids/*.json`.

## 3. Phased dependency graph

```
                        [Phase 1 - cross-cutting]
                        W: mode_capabilities + ward-gate
                        (core/mode_capabilities.py NEW,
                         snapshot_normalizer.py:386, _sr_prompt.py:438)
                              |  (soft dep: provides has_capability)
                              v
   [Phase 1 - deep, the substrate + consumers]
   A: DISTRICTS substrate        core/minimap_districts.py + config/minimap_grids/*.json   (root, no deps)
        |
        +--> B: PRESENCE+COUNTERS   core/minimap_presence.py  (consumes district_of; emits zoi.districts)
        |         |
        +---------+--> C: API-FUSION   core/district_fusion.py  (consumes zoi.districts + lc events; emits zoi.districts_fused)
        |         |
        +---------+--> D: DECISION-TREE  core/macro_decision_tree.py + core/macro_context.py
                            (fog-only v0 needs NO districts; enriched v1 consumes zoi.districts)

   [Phase 2 - lighter]                      [Phase 3 - lighter]
   E: IDENTITY + MIA                         F: INFLUENCE BUBBLES + FLUID DMZ + RENDER
   core/minimap_identity.py                  core/zoi_capability.py + zoi_field.py + zoi_mia.py
   core/mia_reachability.py                  (edits core/zoi_influence.py, minimap_zoi.js)
   core/champion_movespeed.py                (consumes districts + archetype_picks; MIA needs enemy_track wired)
   (depends on A for district callouts;
    opencv-python new dep)

   [ENABLER, parallel throughout]
   O: OBS occlusion-proof frame provider
   core/obs_publisher.py + core/obs_frame_source.py + vision_server/_frame.py
   + core/minimap_blob_detect.py grab path (config-gated, GDI fallback kept)
```

Hard dependency edges (serialize ONLY these): A -> B (district_of); A/B -> C (zoi.districts to reconcile); A -> D-v1 (district weight); A -> E-MIA-callouts (ring covers a district cell); E-identity -> E-MIA (champion pins ring origin + MS). Everything else is parallel. W (ward-gate) is a SOFT dep for C and D (gate on `mode == "SR"` literal with a `# TODO(has_wards)` until W lands - one-line later swap). O is a pure enabler: it improves CV input fidelity but blocks nothing; its `obs.frame_source` flip is live-gated.

The SINGLE serialization point in the whole program is the shared render seam: `dashboard/_state_builder.py:468-480` (the zoi block) and `web/js/panels/minimap_zoi.js` + `core/zoi_influence.py`. Multiple consumers funnel through these three files. Assign ONE merger per contended file (sole-merger discipline); everything else lands in NEW files on disjoint worktrees.

## 4. Parallel agent assignment (per build wave)

Worktree-isolated build agents on DISJOINT file sets; a read-only `verifier` subagent gates before every merge; the main-thread merger owns the contended files. `.claude/agents/verifier.md` is the re-check gate (never trust a subagent's green/test-count claim without an independent probe).

### WAVE 1 (all concurrent - zero shared files, all roots)

| Agent | Writes (disjoint) | Depends on |
|---|---|---|
| `agent-districts` (A) | `core/minimap_districts.py`, `config/minimap_grids/{sr,aram,arena,brawl,tft}.json`, `tests/test_minimap_districts.py` | none |
| `agent-wardcap` (W) | `core/mode_capabilities.py`, `tests/test_mode_capabilities.py`, edits `game_reader/snapshot_normalizer.py:386`, `coach_integration/_sr_prompt.py:438-439` | none |
| `agent-obs` (O) | `core/obs_frame_source.py`, edits `core/obs_publisher.py`, `vision_server/_frame.py`, `core/minimap_blob_detect.py` (grab path), `config/coach_settings.json` | none |
| `agent-movespeed` (E-pre) | `core/champion_movespeed.py`, `tests/test_champion_movespeed.py` | none (reads ddragon + DS stat vocab) |

NOTE collision risk: both A and B author `core/minimap_districts.py`. RESOLUTION: `agent-districts` (A) is the SOLE author of `core/minimap_districts.py` and the config JSONs. The presence spec's district module is folded into A; B consumes it. Do NOT dispatch two agents against that file.

Merger gate after Wave 1: verifier confirms (a) `core/minimap_districts.py` `district_of` is total (4000-point sweep), (b) `has_capability` fail-CLOSED, (c) OBS flag defaults off + GDI fallback intact, (d) all new test files ruff-clean + pass. Merge A, W, O, E-pre.

### WAVE 2 (concurrent after A + W merged)

| Agent | Writes (disjoint) | Depends on |
|---|---|---|
| `agent-presence` (B) | `core/minimap_presence.py`, `tests/test_minimap_presence.py`; SPLICES `_state_builder.py:468-480` (districts key) | A |
| `agent-fusion` (C) | `core/district_fusion.py`, `tests/test_district_fusion.py`; SPLICES `_state_builder.py:468-480` (districts_fused key) | A, B, W(soft) |
| `agent-macro` (D) | `core/macro_decision_tree.py`, `core/macro_context.py`, `tests/test_macro_*.py`; EDITS `_deterministic_coaching.py`, adds `zoi=` kwarg at `_state_builder.py:499` | A (v1) / none (v0 fog-only), W(soft) |
| `agent-identity` (E-1) | `core/minimap_identity.py`, `tests/test_minimap_identity.py`; optional identity pass in `core/minimap_blob_detect.py` `current_minimap_dots` | E-pre, opencv-python |

CONTENDED FILE `dashboard/_state_builder.py`: B (districts splice `:468-480`), C (districts_fused splice `:468-480`), D (`zoi=` kwarg at `:499`). These are the SAME/adjacent regions. Assign the MAIN-THREAD MERGER as sole writer of `_state_builder.py`: B/C/D produce their pure modules + tests on worktrees, hand the exact splice diff to the merger, who applies all three edits in one coherent pass and runs the dual suite once. This is the program's one true serialization.

Merger gate after Wave 2: verifier confirms `zoi.districts` + `zoi.districts_fused` are ADDITIVE (existing `{bubbles, demarcation, map_control}` byte-unchanged), macro `zoi=None` is byte-identical to current callouts, no snapshot_panels fixture asserts on the exact `zoi` key-set. Dual suite green.

### WAVE 3 (concurrent after A + E-identity + E-pre merged)

| Agent | Writes (disjoint) | Depends on |
|---|---|---|
| `agent-mia` (E-2) | `core/mia_reachability.py`, `tests/test_mia_reachability.py`; builds `zoi.mia` at `_state_builder.py` (SR gate) | A, E-1, E-pre |
| `agent-influence` (F) | `core/zoi_capability.py`, `core/zoi_field.py`, `core/zoi_mia.py`, `tests/test_zoi_*.py`; EDITS `core/zoi_influence.py` (radius + new keys) | A, archetype_picks (exists) |
| `agent-render` (G) | `web/js/panels/minimap_zoi.js` (normZoi + _paint + _advanceEma), `web/css/overlay.css`, JS tests | consumes districts/districts_fused/mia/dmz contract |

CONTENDED FILES: `core/zoi_influence.py` (F only - sole writer; E-2 and MIA reachability use a NEW `zoi_mia.py`/`mia_reachability.py`, coordinate which owns the `zoi.mia` key so it is emitted once), `web/js/panels/minimap_zoi.js` (G only - sole writer of the render). E-2 and F both want a `zoi.mia` payload: DECIDE one producer (recommend F's `zoi_mia.py` for the render-facing ring, E-2's `mia_reachability.py` for the identity-corrected origin) OR merge them - see open decisions. `_state_builder.py` stays merger-owned.

Merger gate after Wave 3: verifier confirms MIA rings SR-only (empty in ARAM/Arena), influence bubbles byte-identical when `ally_roster=None`, DMZ falls back to legacy straight line when field degenerate, overlay renders under `MAX_ALPHA` (click-through preserved). Dual suite + JS tests green. Then the UI-fixture ritual (5-phase STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY) on the overlay BEFORE commit.

### Live-gated finalization (after all waves)
Per the do-not-flip-blind discipline (`OBS_CV_MINIMAP_PLAN.md:6-8`): in a practice SR game verify (a) macro callouts appear on `/api/state.callouts` when >=2 enemies go MIA near a drake spawn, (b) district vector populates on `/api/state.zoi.districts`, (c) OBS frames round-trip and match the GDI baseline before flipping `obs.frame_source`, (d) MIA rings + fluid DMZ + weighted bubbles render on the live minimap before flipping roster wiring on.

## 5. Per-mode + ward-gate rules

- **SR (reference, authored first)**: 13-district grid generalizing `_action_quadrant` (3 lanes, top/bot river as anti-diagonal polygons, 4 jungle quadrants, 2 bases, mid) with rich river-gank `shortcuts`. Full presence counters, full API-fusion (turrets/inhibs/dragon/baron/herald), full MIA derivation + reachability rings, full decision-tree registry, identity template-match, weighted bubbles + fluid DMZ. `has_wards=True`. This is the acceptance oracle: `district_of(...,"SR")` MUST reproduce the 9 `_action_quadrant` labels on their representative centroids.
- **ARAM (incl. KIWI/Mayhem)**: single-bridge partition (`aram_bridge` + 2 bases + flank brush), no river/jungle shortcuts (single-lane invariant). Presence counters meaningful (blob-driven, not fog-driven). Shared-vision forces `visible=true`/`on_bridge` (`vision_tracker.py:332-340`) so MIA/fog fusion is INERT and `mia` is always empty; structure-reclassify still applies to the one lane. Decision-tree = SMALL weight-only registry (no MIA-dependent rules). Weighted bubbles + fluid DMZ + district tints render; NO MIA rings. `has_wards=False` (hard-off).
- **Arena (CHERRY, lighter variant)**: tiny symmetric ring; config is a `grid_hint {cols:3, rows:3}` or a ring+center 2-region set - NO hand-authored polygons. Arena is NOT in the current zoi/rect gate (`_state_builder.py:442, 469` are `sr/aram[/brawl]`), so the Arena grid is authored + unit-tested but DORMANT: `compute_zoi`/`fuse_districts`/macro-tree are never invoked in Arena by construction. Do NOT widen the gate this program. Decision-tree registers Arena as an empty-but-present mode (no fallback). `has_wards=False`.
- **Brawl / TFT**: stub configs so the loader has one config per `ALL_MODES` value and CI round-trips every mode. Brawl has `minimap_rect` but no `zoi` (`:469` excludes it); TFT never reaches the zoi path. `has_wards=False`; TFT `district_config=None`.

### Ward-gate (cross-cutting, load-bearing)
Ward availability is an INTRINSIC, immutable mode property, NOT an operator toggle, so it uses a static fail-CLOSED truth table `core/mode_capabilities.py` (default `False`), NOT `feature_policy` (safe-default `True`, wrong for a capability that must fail closed outside SR). `MODE_CAPABILITIES` keyed by `game_snapshot` constants: `SR {has_wards:True, district_config:"sr_5lane"}`, `ARAM/ARENA/BRAWL {has_wards:False}`, `TFT {has_wards:False, district_config:None}`. `_normalize(mode)` accepts canonical (`"SR"`), lowercase key (`"sr"`), AND raw Riot (`"CLASSIC"/"KIWI"/"CHERRY"`) via `mode_from_game_mode_string`. The single most important literal to replace is `snapshot_normalizer.py:386` (`game_mode == "CLASSIC"` -> `has_capability(game_mode,"has_wards")`), which centrally hard-OFFs ward scoring outside SR. Also gate the dynamic ward prompt line `_sr_prompt.py:438-439`. Districts stay ward-agnostic but carry a `role` tag (`"river"`, `"jungle"`) a FUTURE ward-district callout will key on - that callout will itself be `has_wards`-gated. No ward output is written in any Phase-1 decision-tree v1; the only ward touch-point is the capability query.

## 6. Verification requirements

- **TDD, failing test FIRST**: every module ships with its characterization/regression test written before implementation (per CLAUDE.md TDD First + `test-driven-development` skill). Grep-confirm every method/field/data-shape a test touches exists (cite file:line) before scaffolding - never assume an API surface.
- **Tier classification (R5)**: Phase-1 districts/presence-module/ward-cap/fusion/macro are Tier-1 local-logic where they add NEW files + own tests, but any edit that changes `/api/state` schema (presence `zoi.districts`, fusion `zoi.districts_fused`, macro callouts path) is Tier-2 -> full DUAL suite (DS dir + `tests/`). No `ENGINE_VERSION`/scorer/item-effect touch anywhere in this program, so NO DS `:8860` restart or Share mirror is required (confirm before claiming - if no engine file changed, skip the DS bounce).
- **Ruff + ASCII-only**: every new module and test file passes `ruff` and `py_compile` BEFORE the agent reports done (subagent-generated test files have broken CI before - hard requirement). No em/en-dashes or smart quotes anywhere (7-bit ASCII); `tools/precommit_gate.py` is the backstop.
- **Fail-soft contract**: every new pure module (districts, fusion, macro, capability, identity, MIA, zoi_field) NEVER raises on any input (bad numerics, unknown mode, corrupt config, malformed dots) - fail-soft to `fallback`/`[]`/`None`, matching the `zoi_influence` and `_state_builder try/except -> None` patterns.
- **Frozen files (do NOT modify without explicit approval)**: `main.py`, `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`, `core/game_snapshot.py` (imported read-only for mode constants - NOT edited), `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`, `app/__init__.py`, `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`, `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`, `tools/diagnose.md`, `tools/caveman.md`. `dashboard/_state_builder.py`, `core/zoi_influence.py`, `core/minimap_blob_detect.py`, `web/js/panels/minimap_zoi.js` are NOT frozen - editable.
- **Subagent-First + verifier gate**: substantive design/build via worktree-isolated agents on disjoint files; a read-only `verifier` subagent re-checks (independent probe of test counts, file existence, green CI) BEFORE any merge or "done" claim. Never carry a subagent-reported count forward. Re-run the relevant suite fresh, `ls` every cited test file on disk, report the exact pass/fail you observed THIS run.
- **UI-fixture ritual**: the overlay render (Wave 3, `minimap_zoi.js`) runs the 5-phase visual-hierarchy audit BEFORE commit + push, not after; every MUST-FIX resolved in the same slice.
- **Byte-identity guards**: `compute_zoi(..., ally_roster=None)` and macro `zoi=None` MUST be byte-identical to current output (inertness proven by test) so each additive feature is provably inert until wired.
- **Live-gated before green**: the do-not-flip-blind items in section 4 finalization are verified in a real game before the program is declared done; the `obs.frame_source` and roster-wiring flips stay off until the live baseline matches.

## 7. Next-session kickoff

The next session has NO memory of this analysis. Bootstrap from this doc + CLAUDE.md + `docs/OBS_CV_MINIMAP_PLAN.md`, then dispatch WAVE 1 immediately - four fully independent, zero-shared-file worktree agents:

### First wave to dispatch (all concurrent)

1. `agent-districts` (A) - CREATE `core/minimap_districts.py` (pure: `District`/`GridConfig` dataclasses, `load_grid`, `district_of`, `neighbors`, `reachable`, `district_bbox_frac`, embedded fallback configs, de-flip on X) + `config/minimap_grids/{sr,aram,arena,brawl,tft}.json` + `tests/test_minimap_districts.py` (12 tests incl. the SR legacy-parity oracle vs `_action_quadrant`). SOLE author of the district module + configs.
2. `agent-wardcap` (W) - CREATE `core/mode_capabilities.py` (static fail-CLOSED `MODE_CAPABILITIES` + `has_capability` + `district_config` + `_normalize`) + `tests/test_mode_capabilities.py`; EDIT `snapshot_normalizer.py:386` + `_sr_prompt.py:438-439` behind `has_capability`. Grep-confirm zero remaining `== "CLASSIC"` ward gates after.
3. `agent-obs` (O) - CREATE `core/obs_frame_source.py` (sync `get_obs_frame()`); EDIT `core/obs_publisher.py` (add `_request` op6/op7 await + keep-warm frame slot), `vision_server/_frame.py` (`obs.frame_source` flag, OBS-first with GDI fallback), `core/minimap_blob_detect.py` (`_grab_native_minimap` prefers OBS). All config-gated, GDI fallback kept, flip live-gated.
4. `agent-movespeed` (E-pre) - CREATE `core/champion_movespeed.py` (`base_ms` from ddragon `stats.movespeed`, `item_ms` flat/pct from DS stat vocab, `est_ms`) + `tests/test_champion_movespeed.py`.

Each agent: failing test first, `ruff` + `py_compile` before reporting done. Read-only `verifier` gate before the merger integrates. Then proceed to Wave 2 (presence/fusion/macro/identity) with the main-thread merger as sole writer of `dashboard/_state_builder.py`.

### Phase-1 acceptance (declare Phase 1 done when ALL hold)
- `core/minimap_districts.district_of` is a total function: 20x20x2-flip x 5-mode sweep (4000 points) all return a valid district id; SR reproduces all 9 `_action_quadrant` labels on their centroids; flip proven to mirror on X.
- One valid config per `ALL_MODES` value; each parses + passes reference-integrity (every `adjacent`/`shortcuts` id exists, every `poly` >=3 verts in `[0,1]`).
- `MinimapPresenceTracker.update` emits the full per-district `{team_present, missing_since_s, last_seen_t}` vector, `missing_since_s` derived from `game_time` deltas (wipes on new-game/stale-relay, never carries across matches), full label set always emitted (no reflow).
- `has_capability("SR","has_wards") is True`, `False` for ARAM/ARENA/BRAWL/TFT (canonical + lowercase + raw-Riot forms); `snapshot_normalizer.py:386` no longer has the bare `== "CLASSIC"` ward literal; SR ward behavior byte-identical.
- `fuse_districts` API-ground-truth overrides CV (dead-champ weight cap, structure reclassify, objective confirm within `OBJ_FUSE_WINDOW_S=8.0`); ward-inference provably SR-only + `has_wards`-gated; `zoi.districts_fused` additive; ARAM no MIA, Arena/Brawl never invoke fusion.
- The operator decision-tree scenario passes: bot+sup MIA via river + jungler last bottom + mid pushed to dragon-river yields ONE deterministic `kind="macro"` callout naming drake window + missing count + ward/group action, with ZERO Haiku/Sonnet calls; `zoi=None` byte-identical to current served callouts.
- `/api/state.zoi` existing keys byte-unchanged (additive-only); dual suite green; ruff + ASCII clean; no frozen file modified; verified live in a practice SR game.

## 8. Open decisions for the operator (resolve before building)

1. **`zoi.mia` single producer**: Phase 2 (E-2 `mia_reachability.py`, identity-corrected origin + item-aware MS) and Phase 3 (F `zoi_mia.py`, render-facing ring) both propose a `zoi.mia` payload. Pick ONE producer, or merge them into a single module, before Wave 3 so the key is emitted once. RECOMMEND: one `core/mia_reachability.py` owns the payload; F's render consumes it (do not author `zoi_mia.py` separately).
2. **Districts substrate ownership**: two specs (p1_districts, p1_presence) each describe `core/minimap_districts.py`. CONFIRMED RESOLUTION in-plan: `agent-districts` (A) is sole author; presence (B) consumes. Operator only needs to confirm the SR grid is 13-district (p1_districts) not 9-cell (p1_presence) - RECOMMEND 13-district (superset; the 9 legacy labels remain a parity oracle).
3. **Decision-tree v0 vs v1 sequencing**: ship fog-only v0 (no district dep, works against existing `vision_state.json` + `objective_events`) FIRST, then enrich with district weight after A/B land - or wait for districts? RECOMMEND fog-only v0 in Wave 2 (covers the operator scenario partially with zero CV dependency), enrich in a follow-on.
4. **opencv-python install on Legion**: identity (E-1) is untestable live until `opencv-python` is installed under `Python314`; confirm the operator wants the dependency added to `requirements.txt` and installed before Wave 3.
5. **Arena zoi gate**: the Arena grid is authored but dormant (gate stays `sr/aram`). Confirm Arena should remain dormant this program (RECOMMEND yes; opening the Arena zoi gate is a separate future phase).

## 9. Live-verification results (2026-07-05, practice SR game)

The do-not-flip-blind finalization (section 4) ran in a live SR game. It surfaced 3 defects and validated 1 transport; NO live gate was flipped.

- **Check 1 - `zoi.districts` / `districts_fused` populate: PASS.** 13 districts with real per-team counts on `/api/state` while League is the focused window. Two caveats (not schema faults): the pipeline is FOREGROUND-GATED (the minimap grab only lands when League is focused, so the data empties on alt-tab), and the blob detector OVER-DETECTS (~70 dots vs 10 champions), inflating per-district counts.

- **Check 3 render - FLICKER found + FIXED.** The overlay canvas paints correctly (proven live via the built-in `DEBUG_ZOI` magenta probe) but strobed on/off ~1 Hz. Root cause: `core/minimap_blob_detect.current_minimap_dots` stamped `dots=[]` on a TRANSIENT failed grab (`crop is None`) identically to a legit-empty frame, so `/api/state.zoi` (gated on `minimap_dots` at `_state_builder.py:469`) emptied every other poll and the overlay hard-cleared. FIX (shipped, additive, byte-identical when dots are stably present): (a) server holds last-good dots for `_HOLD_LAST_GOOD_S=3.0` across a failed grab, distinguishing grab-failure (`crop is None`) from a legit-empty frame (grab landed, no champions - still clears); the previously-unbounded exception path is now bounded by the same window. (b) overlay `_nullDebounceStep` holds the last painted scene until `_NULL_CLEAR_STREAK=3` consecutive nulls (no strobe; still clears at a real game-end). Tests: `tests/test_minimap_blob_detect_hold.py` (6) + `minimap_zoi.test.mjs` debounce (5). DMZ ribbon is correctly ABSENT at default gates (no `dmz` key until roster-wiring flips ON); MIA rings correctly ABSENT (dead feed, Check 2). The district-tally is a deliberately SUBTLE corner dot-column (no browser district geometry - it never invents map coords); a visibility lift is a future UI call. OPERATOR RE-VALIDATE: DONE (2026-07-05) - operator confirmed live the overlay shading holds steady (no strobe) after the fix + the reliable OBS source. Flicker fully closed (unit tests + live eyeball).

- **Check 2 macro callout + MIA rings - BLOCKED (feed dead on SR), DEFERRED.** The fog-only macro tree needs `>=2 enemies missing_for_s>=8`; live, all enemies read `missing_for_s=None, last_seen_zone=None` permanently. Root cause: `core/vision_tracker.py` derives fog from Live Client `allPlayers[].position` COORDINATES, but this client emits `position` as a ROLE STRING (`MIDDLE`/`JUNGLE`/`NONE`), never coords - so the fog clock never starts. The localizer `core/minimap_identity.identify_dots` EXISTS but is NOT wired into vision_tracker. Both feed-fix options are BLOCKED on the same prerequisite (the ~70-vs-10 CV over-detection): wiring identity rests on ~86% noise; re-basing on anonymous district counts rests on an unclamped over-count (the `district_fusion` dead-cap is inert because `lc["players"]` carries no `isDead`/`respawnTimer`). A forced macro callout on this data would fire HARMFUL false directives. DEFERRED with a regression fence (`tests/test_macro_decision_tree.py::test_dead_fog_feed_never_fires_on_live_sr_shape`). PREREQUISITE (separate future lane): fix the minimap CV over-detection so dots approximate real champion count (tighter blob gating OR a live-validated `RC_ZOI_IDENTITY`), THEN wire the feed via the existing `zoi=`/`districts=` seam (`_deterministic_coaching.py:651-657` needs no change). Do NOT flip `RC_ZOI_IDENTITY` or roster-wiring until then.

- **Check 4 OBS round-trip - VALIDATED + FLIPPED (same session).** Initial probe found the source named "Game Capture" was actually a DISPLAY CAPTURE (DXGI desktop duplication) = the whole monitor incl. the RC overlay = NOT occlusion-proof and inflating the dot count. Operator switched it to a **Window Capture (WGC) of the League game window**: occlusion-proof (excludes the separate overlay window), Vanguard-safe (no injection), native 2560x1440 (matches `minimap_rect`, ZERO re-registration). LIVE-VALIDATED in-game: the OBS-frame minimap crop detects ~46-50 dots vs the GDI grab's 92 (the overlay was ~40 phantom dots), round-trip reliable. FLIPPED via `config/coach_settings.json` `obs.frame_source=true` + `password` (gitignored; `enabled=false` so the one-shot fetch path activates through the 5s config TTL - NO RC reload). Live `/api/state.minimap_dots` dropped 92 -> ~46, `/api/state` stayed fast (0.02s, cache-served), zoi steady (no flicker), no OBS errors. NOTE: the raw minimap STILL over-detects (~46 vs 10 real champs) - occlusion-proofing halved it, but the blob-gating tightening (the macro/MIA feed prerequisite) is still owed, now from a cleaner baseline.

Gate status after this session: `obs.frame_source` **ON** (WGC source, live-validated - local gitignored config), `RC_ZOI_IDENTITY` OFF (blocked on CV precision), roster-wiring OFF (no visible signal at defaults). obs.frame_source flipped ON LIVE-VALIDATED (not blind); the other two remain gated.
