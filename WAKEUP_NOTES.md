# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s174 wrap — 2026-05-12 (Phase 1 Tank EHP scorer — multi-commit)

**Operator instruction:** "Read NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md. We're starting Phase 1 — Tank EHP scorer. Before writing code, confirm decisions on the four open design questions at the bottom of that doc. Then implement compute_ehp() + rank_items_by_ehp() + integrate with core/defensive_picks.py per the chosen option. Bump ENGINE_VERSION to 0.63.0; add tests; restart DS server; verify via /health + Game-PC monitor 1 capture before reporting done."

## Open design questions — decisions locked in this slot

1. **Option A vs B for `defensive_picks.py` integration** → **Option B** (layer). The s171 curated `_DEFENSIVE_ITEMS` catalog stays the operator-vetted pool; EHP math drives ordering within it via `only_item_ids` whitelist on `rank_items_by_ehp`. Preserves operator-validated work, math gives the order. Migration to Option A deferred until calibration shows curated list adds no value.
2. **ARAM EHP semantics — `aramDamageTaken`** → **applies**. Field name verified in snapshot at `champion.lolmath.aram_modifiers.aramDamageTaken` (e.g. Aatrox=1.0). Formula: `ehp_component = hp / (resist_factor × aramDamageTaken)`. A champion with `aramDamageTaken=0.95` takes 5% less damage → effective HP scales by 1/0.95 for ALL components (physical, magical, true). Mirrors `dps.py`'s `aramDamageDealt` handling pattern.
3. **Scorer dispatch location** → **defer the dispatcher abstraction**. For Phase 1, ship `rank_tank_for()` + `ehp_for()` as siblings of `rank_for()` / `dps_for()` in `core/daemon_slayer_client.py`. Formal dispatcher (e.g. `rank_for_primary_archetype()`) revisited at end of Phase 2 when 3+ scorers exist; Phase 3 wires it to `state.cs_archetype_pick`.
4. **Shield-throughput in Phase 1 vs 1.5** → **defer to Phase 1.5**. Plan already calls this out (line 142). Sterak's lifeline + Doran's Shield need uptime modeling that bloats Phase 1 scope. Pure EHP first; shields layered on later.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/ehp.py](agents/daemon_slayer/ehp.py) | **NEW (~440 LOC).** `compute_ehp()` + `EhpResult` + `_armor_factor()` + `_aram_damage_taken()` + `rank_items_by_ehp()` + `EhpRankedItem` + `EhpRankResult`. Closed-form math: `physical_ehp = hp / armor_factor(armor) / aramDamageTaken`, magical mirror via MR, `true_ehp = hp / aramDamageTaken`. `blended_ehp` weighted by caller-supplied `enemy_ad_share` / `enemy_ap_share` (remainder = true). Imports private filter helpers (`_filter_candidates`, `_is_terminal`, `strip_arena_trinkets`) from `rank.py` rather than duplicating; inlines `_armor_factor` rather than reaching into `dps.py`'s private helpers (decouples scorers). |
| [agents/daemon_slayer/server.py](agents/daemon_slayer/server.py) | Two new POST routes: `/ehp` (caster EHP under enemy damage profile) + `/rank-tank` (items ranked by EHP delta). Body shape mirrors `/dps` and `/rank` with `enemy_ad_share` / `enemy_ap_share` (floats) swapped for `target_armor` / `target_mr` (those describe target, not caster exposure). Index HTML route listing extended. |
| [core/daemon_slayer_client.py](core/daemon_slayer_client.py) | New `TankRankedItem` dataclass + `rank_tank_for()` + `ehp_for()` helpers. Same engine-down semantics as `rank_for` (None = unreachable, [] = nothing). `only_item_ids` param threads to body's `only` field — the integration point for Option B layering. |
| [core/defensive_picks.py](core/defensive_picks.py) | New `recommend_defensive_items_via_ehp()` + `_threat_to_damage_shares()` helper. Maps `ad_threat` / `ap_threat` (0..10) → `(ad_share, ap_share)` floats summing to ≤1.0 (reserves ~10% true-damage share when both signals ≥6). Passes catalog IDs as `only_item_ids` whitelist; falls back to existing `recommend_defensive_items` heuristic when engine down / champion missing / threat malformed. Lazy import keeps module import-clean for callers that don't need the EHP path. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | `ENGINE_VERSION` 0.62.0 → 0.63.0. Extended module docstring with Phase 0 + Phase 1 changelog entries. |
| [agents/daemon_slayer/tests/test_ehp.py](agents/daemon_slayer/tests/test_ehp.py) | **NEW (~380 LOC).** 44 tests across 8 test classes: ArmorFactorTests (5 pure-math), ComputeEhpBasicsTests (9), ItemContributionTests (8), LevelScalingTests (2), ARAMModeTests (5), ValidationTests (6), SerializationTests (3), ConsistencyTests (4), NotesTests (2). |
| [agents/daemon_slayer/tests/test_rank_tank.py](agents/daemon_slayer/tests/test_rank_tank.py) | **NEW (~210 LOC).** 19 tests across 5 classes: RankByEhpBasicsTests (9), CandidateFilteringTests (4), SharedUniqueFilterTests (2, lifeline dedup), EnemyShareSensitivityTests (2, AD-vs-AP item ordering), SerializationTests (2). |
| [agents/daemon_slayer/tests/test_server.py](agents/daemon_slayer/tests/test_server.py) | New `EhpRouteTests` class (4 tests): `/ehp` naked, `/ehp` pure-AD enemy, `/rank-tank` armor-prio top pick, `/rank-tank` share-validation 422. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Bumped `test_batch63_version` + `test_batch64_version` to assert 0.63.0; extended Phase 0/1 comment in batch63 docstring. |
| Living docs sync | CLAUDE.md (+s174 entry at item 31) · README.md (header DS bullet + capability matrix line) · docs/DAEMON_SLAYER.md (status + module map) · docs/ARCHITECTURE.md (DS section) · ROADMAP.md (DS status line + s174 ship entry) · BRIEF.md (RC Tutor "what's built" line). |
| DS server runtime | Killed pid 2968 + relaunched via `pythonw tools/start_daemon_slayer.py` (per `reference_ds_server_not_supervisor_watched` memory). `/health` confirms engine_version 0.63.0 live on :8893. |

## Live validation

Probed `/rank-tank` against real running DS server:

**Malphite + 90/10 AD enemy** (whitelist = 3075/3110/3047/3143/3742/6665/3068):
```
baseline_ehp: 3161.1
  3143  Randuin's Omen         +ehp=2,036.0  gold= 2700
  3742  Dead Man's Plate       +ehp=1,666.1  gold= 2900
  3068  Sunfire Aegis          +ehp=1,573.7  gold= 2700
  6665  Jak'Sho, The Protean   +ehp=1,573.7  gold= 3200
  3075  Thornmail              +ehp=1,530.2  gold= 2450
```

**Nasus + 30/70 AP enemy** (no whitelist — full catalog):
```
baseline_ehp: 3395.1
  2504  Kaenic Rookern         +ehp=2,023.5
  3083  Warmog's Armor         +ehp=1,695.9
  6665  Jak'Sho, The Protean   +ehp=1,651.9
  4401  Force of Nature        +ehp=1,603.1
  3084  Heartsteel             +ehp=1,526.3
```

Math is selecting correctly — armor-heavy items for AD-heavy enemy, MR-heavy items (Kaenic Rookern, FoN) for AP-heavy enemy. Operator-comprehensible.

## Findings

- **Item-stat calibration matters more than it does in DPS.** First test pass had `test_force_of_nature_lifts_mr_more_than_armor` asserting `magical_delta > 3 × physical_delta`. Failed because FoN ships +400 HP on top of +55 MR — the HP component lifts physical_ehp materially (Malphite at lvl 11 has 70+ armor → physical_factor ≈ 0.59 → 400 HP / 0.59 ≈ 680 EHP physical contribution from HP alone). Softened to `magical_delta > 1.5 × physical_delta` (observed ratio ≈ 2.3x). Lesson: defensive items are stat-dense (HP + resist + MS + AP often bundled); pin tests to qualitative directional claims rather than dimensional ratios.
- **Null-Magic Mantle is 20 MR, not 25.** My memory said 25; the snapshot says 20 (id 1033). Used `assertGreaterEqual(..., naked.mr + 20)` instead of strict `>` so the exact-equal case (no float fuzz) passes. Snapshot is canonical, memories aren't.
- **`shares_dead_unique` flag reuses from Phase 0 cleanly.** Lifeline-family dedup (Sterak's + Maw + Shieldbow + Verdant Barrier + Hexdrinker + Protoplasm Harness + Seraph's + Lifeline component) is the only frequent defensive collision; tests confirmed Sterak's-then-Maw filtered by default and surfaceable with `filter_shared_uniques=False`.
- **Phase 1 deliberately doesn't model enemy pen against caster.** Lethality + %MR pen applied BY enemies to the tank's resists would shift physical_ehp / magical_ehp downward in a real fight. Skipped per scope discipline — needs enemy-build plumbing that doesn't exist yet. Documented as a Phase 1.5 candidate.
- **`recommend_defensive_items_via_ehp` is opt-in, not a replacement.** Existing `recommend_defensive_items` heuristic stays in place; coaches that want EHP-ranked picks call the new function explicitly. No coach is wired to call it yet — operator decides at start of Phase 2 whether tank coach should use it or wait for the Bruiser hybrid scorer.

## Verification

- `py -m pytest agents/daemon_slayer/tests/` → **1022 passed** (was 955 — +67: 44 ehp + 19 rank_tank + 4 server EhpRouteTests)
- `py -m pytest tests/ --timeout=120` → **839 passed** (wider RC suite, no regressions)
- DS server `:8893/health` → `engine_version: "0.63.0"` live
- Game-PC monitor 1 capture: dashboard renders cleanly at idle (no game in progress); all standard panels intact (NEXT / RIGHT NOW / MAP STATE / ITEM BUILD / ADAPTATION); no JS errors; layout unbroken.

## Open items carried forward

- 🟡 **Phase 2 — Bruiser hybrid scorer** — next session per the archetype-expansion plan. `ds.hybrid` = α·dps + β·ehp with per-champion α/β table in `archetype_weights.json`. ~20 bruisers unlocked. 1 session of work.
- 🟡 **Phase 1.5 — shield/healing throughput** — Sterak's lifeline shield + Doran's Shield + Cinderhulk + Bloodthirster shield modeling. Needs avg-shield-uptime data; better fits alongside Phase 6 Enchanter HPS scorer than as a Phase 1 add-on.
- 🟡 **`recommend_defensive_items_via_ehp` wire-in** — function exists but no coach calls it. Defer to Phase 3 CS scorer-picker UI when `state.cs_archetype_pick` lands; tank-primary coach tick reads the pick and routes to the EHP ranker.
- 🟡 **DS calibration with EHP picks** — `data/ds_calibration.jsonl` doesn't yet log `scorer="ehp"` tag. Add when calibration analysis begins (blocked on richer rewind_history.db per CLAUDE.md item 14).
- 🟡 **Caster-side enemy pen modeling** — Phase 1 treats caster armor/MR as raw values. Enemy lethality + %MR pen applied AGAINST the tank would shift EHP downward in real fights. Needs enemy-build plumbing (`/api/ds-preview` already reads enemy items for offensive ranking; symmetric read needed for defensive). Phase 1.5+ candidate.

---

# s173.1 wrap — 2026-05-12 (audit thread continuation — 5 commits)

**operator slot complete** — `/what's-next` daytime run. Closes s173 audit findings #2 + #3, plus 3 bonus items spotted while in the area. All 5 commits CI-green on first push.

Operator brief: "1 then any other items listed in roadmap, readme, or other files for tasks to do, 2 will be later today in about 5 hours." Item 1 = s173 finding #2 (ENGINE_VERSION doc-sync). Item 2 = Active Match step 5 (deferred 5 hours per operator). Slot scope: anything well-scoped, no operator-approval-blocked, no live-game-blocked.

## Ships

| Commit | Theme |
|---|---|
| [5c8b53e](https://github.com/Remus3/riot-commander/commit/5c8b53e) | `docs:` sync ENGINE_VERSION 0.60.0 → 0.61.0 across 6 living docs (8 lines) — closes s173 finding #2. Historical references in archived notes + batch comments intentionally untouched. |
| [802ad90](https://github.com/Remus3/riot-commander/commit/802ad90) | `docs:` sync DS test count 929/911 → 949 across living docs — spotted drift while doing #2. Canonical 949 from `py -m pytest agents/daemon_slayer/`. Dated planning docs left at 929 (write-time accurate). |
| [38ca915](https://github.com/Remus3/riot-commander/commit/38ca915) | `test(snapshot_panels):` adversarial fixtures + mode-transition coverage; fix s151 `gameTime` ref-error. 4 new fixtures (no_coach / null_fields / empty_strings / out_of_range) + 2 new tests + closes the CLAUDE.md item-10 s151 follow-up (`panels/map_state.js:720` referenced bare `gameTime` outside the IIFE scope; only fired when `game_time_s` was numeric — adv_out_of_range surfaced it via -42). 11 of 11 tests green (was 6). |
| [16334b2](https://github.com/Remus3/riot-commander/commit/16334b2) | `refactor(champion-aliases):` unify three drift-prone maps via canonical JSON — closes s173 finding #3. New `web/data/champion_aliases.json` as source of truth; `web/js/lib/items_index.js` + `web/js/dashboard.js` fetch async; `tools/daemon_slayer_extract.py` reads at import-time. New `tests/test_champion_aliases.py` (4 regression guards). `agents/daemon_slayer/server.py:_resolve_champion_id` is a different pattern (builds revmap from DDragon data dynamically) — explicitly not a drift candidate. |
| [51e0da7](https://github.com/Remus3/riot-commander/commit/51e0da7) | `fix(console-pipe):` per-entry queue removal preserves entries on replay failure — closes BACKLOG item "Console-pipe localStorage flush failure-recovery loop". The original `flushQueueAfterSuccess` called `localStorage.removeItem(QUEUE_KEY)` BEFORE issuing replay fetches with `.catch(() => {})`; mid-flush endpoint outage lost every queued entry. Now each entry stays queued until its own 2xx; failures retry on next pipe-success (QUEUE_MAX=50 bounds growth). |

## Findings

- **The adversarial harness paid for itself on first run** — `test_adversarial[adv_out_of_range]` surfaced the s151 `gameTime` ref-error that had been pending as a "follow-up" deferral for ~10 days. The bug was previously invisible because no real game state has `game_time_s: -42`; only an adversarial fixture exercised the path. Closing the loop: BACKLOG-driven test design caught a CLAUDE.md item-10 known-unfixed bug. Worth keeping in mind for future test-coverage decisions — adversarial fixtures aren't just defense, they're discovery.
- **Champion alias unification was 5 files not 3** — the s173 wrap listed three sites (items_index.js, daemon_slayer_extract.py, dashboard.js). While implementing I checked one more candidate the audit brief had flagged (`core/champion_aliases.py` doesn't exist) and audited `agents/daemon_slayer/server.py:_resolve_champion_id` — which is a different pattern (dynamic revmap from DDragon `champions[].name`) and NOT a drift candidate. Test guard at `tests/test_champion_aliases.py:test_js_consumers_reference_canonical_file` greps both JS files to catch future regressions where someone re-hardcodes the map.
- **Console-pipe identity match by (ts, message-prefix)** — object identity doesn't survive the JSON round-trip through localStorage, so `_dropQueuedEntry` matches on (ts, message[:100]). Collisions are benign — at worst we drop a near-duplicate that retries on next flush. Heuristic chosen over assigning UUIDs at enqueue time to keep the fix surgical.

## Files touched this slot

**Doc-sync (2 commits, 9 line edits):**
- `CLAUDE.md` · `README.md` (×3 lines) · `docs/DAEMON_SLAYER.md` · `docs/ARCHITECTURE.md` · `BRIEF.md` · `NEXT_SESSION_PLAN_2026-05-10.md`

**Code + tests (3 commits, 8 files changed, 5 new):**
- `web/data/champion_aliases.json` (NEW)
- `web/js/lib/items_index.js` · `web/js/dashboard.js` · `web/js/main.js` · `web/js/panels/map_state.js`
- `tools/daemon_slayer_extract.py`
- `tests/test_champion_aliases.py` (NEW)
- `tests/snapshot_panels/test_panel_snapshots.py`
- `tests/snapshot_panels/fixtures/adv_no_coach.json` · `adv_null_fields.json` · `adv_empty_strings.json` · `adv_out_of_range.json` (4 NEW)

## Open items carried forward

- 🟡 **Active Match view step 5** — deferred per operator to ~5 hours after slot start. Sub-items: zen-lock in-game + RIGHT NOW fold + bridge-pending → dev-panel button + fleet view removal. CLAUDE.md item 18.
- 🟡 **s173.2 finding — `.claude/commands/process-bridge-tasks.md` is gitignored**. The s173.2 unification edit is live on Legion but won't ride with a fresh clone or deploy. Two paths for durability: (a) track a canonical at `tools/process-bridge-tasks-legion.md` mirroring the Peer template pattern + add it to CLAUDE.md frozen list; (b) accept local-only since the file lives alongside other local config (bridge secrets, MCP URLs). No urgency — runtime gate is correct on this machine.
- 🟡 **Live champ-select verification** — the Hunt 5 substitution from s173 (`907543f`) and the s171.8 cache-bust unification both await a real ChampSelect pop to reconfirm `_fetchDsPreview` fires with the correct mode label and the unified asset-hash propagates `champ_select.js` updates.
- 🟡 **dashboard.js console-pipe mirror** — same pre-emptive-remove bug at line 8109 left unfixed since the wrap noted dashboard.js is dead code (web/index.html only loads main.js). Sync deferred to land alongside any future dashboard.js removal.
- 🟡 **BACKLOG `MatchDB` thread-safety validation** entry is stale — `core/match_db.py` was refactored 2026-04-28 (audit proposal 1.2) from RLock to WAL + per-thread connections. The FIX-021 lock referenced in BACKLOG no longer exists. Worth a one-line BACKLOG edit when next in the area.

## Pending verification

🟢 All snapshot_panels tests + full pytest suite green throughout slot:
- After 38ca915: 821 (full) + 11 (snapshot_panels) = 832 passing
- After 16334b2: 836 passing (snapshot_panels rolled into full run + 4 new alias tests)
- After 51e0da7: snapshot_panels 11/11 — happy path unchanged for console pipe

🟡 Live verification of the s151 fix awaits next real game (current liveclient empty per startup probe). The `gameTime` ref-error in `_tickObjectiveCountdowns` fires only when `_currentGameTimeS()` returns a number, which means an active game with `game_time_s` populated. Adversarial fixture verified it; live confirm is bonus.

---

# s173.5 wrap — 2026-05-12 (DS dead-unique filter + archetype-expansion scope, 1 commit)

**Operator-approved fix + multi-session scope plan** for expanding Daemon Slayer from auto-attack-DPS-only to a 6-scorer suite covering tank/bruiser/mage/assassin/enchanter archetypes. Phase 0 closed this slot — the dead-unique candidate-filter bug — and Phases 1-6 are scoped in a self-contained doc for future sessions.

## Phase 0 ship — DS dead-unique filter

Operator observed: "Trinity Force was suggested and I was okay with it, after it was built, Essence Reaver was still a suggestion despite not being able to build it/utilize its item effect, intentional?" Engine investigation confirmed the gap: `collect_effects()` correctly dedupes the second Spellblade proc (proc + pen contributions zeroed), but the candidate's raw stat block (75 AD + 25% crit + 25% AS + mana) still lifted DPS enough to keep ER in the top-N ranking. Operator-facing this was wrong — wasted unique = worse value-per-gold than a non-redundant item.

### Engine changes

| File | Change |
|---|---|
| [agents/daemon_slayer/rank.py](agents/daemon_slayer/rank.py) | Added `shares_dead_unique: bool = False` + `dead_unique_key: str = ""` fields to `RankedItem`. Added `filter_shared_uniques: bool = True` parameter to `rank_items()`. Computed dead-unique flag from `ITEM_EFFECTS` BEFORE the `compute_dps()` call so filtered candidates skip the expensive scoring entirely. Backward-compat dataclass defaults. |
| [agents/daemon_slayer/server.py](agents/daemon_slayer/server.py) | `/rank` route forwards `filter_shared_uniques` from request body (default true). |
| [core/daemon_slayer_client.py](core/daemon_slayer_client.py) | Client `RankedItem` mirrors new fields; `rank_for()` exposes `filter_shared_uniques` param (default true). |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | `ENGINE_VERSION` 0.61.0 → 0.62.0 |
| [agents/daemon_slayer/tests/test_rank.py](agents/daemon_slayer/tests/test_rank.py) | New `SharedUniqueFilterTests` class with 6 tests covering Trinity→ER, Sterak's→Maw, Sunfire→Hollow Radiance families + clean-build no-flag + to_dict schema + filter-off opt-in path. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests bumped 0.61.0 → 0.62.0. |
| Living docs sync | CLAUDE.md · README.md · docs/DAEMON_SLAYER.md · docs/ARCHITECTURE.md · ROADMAP.md · BRIEF.md — version + test count + scorer description |
| DS server runtime | Killed pid 7944 + relaunched via `pythonw tools/start_daemon_slayer.py` (per `reference_ds_server_not_supervisor_watched` memory). `/health` confirms engine_version 0.62.0 live on :8893. |

### Affected unique families (now properly suppressed)

| Key | Family members |
|---|---|
| `spellblade` | Trinity Force · Essence Reaver · Lich Bane · Iceborn Gauntlet · Sheen · Divine Sunderer · Sundered Sky · Dusk and Dawn |
| `lifeline` | Sterak's Gage · Maw of Malmortius · Immortal Shieldbow · Seraph's Embrace · Hexdrinker · several defensive_only |
| `immolate` | Sunfire Aegis · Hollow Radiance · Bami's Cinder |
| `fiendhunter_barrage` · `hellfire_char` · `innervating_fill` | Single-item future-proofs |

### Findings

- **Computing the flag BEFORE `compute_dps` was the right call.** Default filter ON saves the expensive `compute_dps` evaluation for filtered candidates entirely — meaningful since `rank_items` is called every coach tick (8-25s) and each call is ~125-175 candidate evaluations.
- **Backward compat preserved via dataclass defaults.** Existing callers that pass positional args or omit the new kwarg still work; new fields default to `False`/`""`. The `to_dict()` change adds keys but doesn't remove any, so consumers parsing the JSON via `.get()` are unaffected.
- **Filter-off opt-in is operator's escape hatch.** Sophisticated callers (calibration analysis, debug tools) that WANT to see the stat-only DPS lift of a dead-unique candidate pass `filter_shared_uniques=False` and read `shares_dead_unique` to interpret the result.

## Phase 1-6 scope plan

Drafted [NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md](NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md) — self-contained multi-session guide. Architecture decisions locked in this slot (operator-confirmed; do not re-litigate):

1. **One engine, six scorers** (not six engines): keep `agents/daemon_slayer/` umbrella; add `ds.ehp`/`ds.hybrid`/`ds.ability`/`ds.burst`/`ds.hps` siblings to `ds.dps`. Share substrate (snapshot loader, `build_champion()`, `ItemEffect` registry, `CallContext`, `:8893` server).
2. **Daemon Slayer keeps umbrella name.** Internal scorers expose via per-archetype HTTP routes (`/rank-tank`, `/rank-mage`, etc.).
3. **Top-2 archetypes shown for all champs** in CS panel + in-game tab. Meta default pre-selected from DDragon `tags[0]` + win-rate priors. Selection gates coach + match analysis.
4. **Only primary scorer runs per coach tick.** Secondary freezes after initial CS + game-start passes; refreshes only on enemy/operator item-complete events.
5. **Mid-game switch supported.** New primary fires immediately; subsequent ticks use it.
6. **First-purchase-item inference = soft nudge** (one-time toast), not auto-override.

**Phases:** 0=shipped this slot · 1=Tank EHP (1 session) · 2=Bruiser hybrid (1) · 3=CS picker UI (1) · 4=Mage ability DPS (3) · 5=Assassin burst (2) · 6=Enchanter HPS (2). Total ~10 sessions for ~90 champions with archetype-appropriate scoring.

### Cadence model verified

Walked the operator through the actual DS runtime cadence — they had the wrong mental model ("30s init + re-run on item change"). Corrected: DS runs every coach tick (12-25s ARAM stable, 8-22s Arena, 7-20s Brawl, faster on state-change events). Each tick = ~125-175 `compute_dps()` calls. Sub-second on warm snapshot. Dashboard `/api/ds-preview` polls independently for the `#ds-pill` and champ-select view.

This cadence correction shaped the architecture: naively running all 6 scorers per tick would 6× the compute. The "primary only" rule keeps the budget bounded.

## Verification

- `py -m pytest agents/daemon_slayer/tests/ -q --timeout=60` → 955 passed (was 949 — +6 from SharedUniqueFilterTests)
- `py -m pytest tests/ -q --timeout=60` → 839 passed (unchanged)
- `py -m ruff check .` → all checks passed
- DS server `:8893/health` → engine_version 0.62.0 live
- Manual probe: `rank_for(champion="Aatrox", level=11, item_ids=["3078"])` returns ranking with NO Essence Reaver / Lich Bane / Iceborn Gauntlet (all spellblade-family) — fix working live.

## Open items closed this slot

- ✅ Operator question 1 — "Does DS evaluate based on currently purchased items?" — confirmed yes via [rank.py:281-293](agents/daemon_slayer/rank.py:281) baseline + delta walkthrough.
- ✅ Operator question 2 — Trinity → ER recommendation bug — fixed via Phase 0 dead-unique filter.
- ✅ Architecture decision: one engine vs six engines — one engine, six scorers (operator-confirmed).
- ✅ Architecture decision: CS scorer-picker UX shape — top-2-always-shown across all champs, primary gates coach, secondary refreshes on item-complete events (operator-confirmed).
- ✅ Phase 1-6 scope drafted in self-contained next-session plan.
