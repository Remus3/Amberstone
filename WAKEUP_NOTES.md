# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

---

# s176 wrap — 2026-05-12 (Phase 3 CS archetype-picker UI + dispatcher — single commit pending)

**Operator instruction:** "continue" — after the Phase 2 push lands, ship Phase 3 in the same slot.

Phase 3 in [NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md](NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md): operator-driven scorer selection. The plan calls this "single session, pure UI" but realistically the full scope (state-builder injection + coach integration + soft-nudge + in-game switch tab) is more than one slot. Shipped the **data + REST + dispatcher + picker UI** today; **deferred coach wiring + nudge + state-builder stamp** to a follow-up session per the "MVP what unblocks operator" discipline from s174.

## Ships

| File | Change |
|---|---|
| [core/archetype_picks.py](core/archetype_picks.py) | **NEW (~300 LOC).** Storage layer + tag-default resolver. Six canonical archetypes: `carry`, `bruiser`, `tank`, `mage`, `assassin`, `enchanter`. `tag_to_archetype()` maps DDragon `tags[i]` (Fighter→bruiser, Mage→mage, Marksman→carry, Tank→tank, Support→enchanter, Assassin→assassin). `default_for_champion()` returns `(primary, secondary)` from `tags[0]` + `tags[1]` (with `_fallback_secondary` heuristic when only one tag exists). Per-champion overrides persist in `data/cs_archetype_picks.json` via atomic write (mirror of `routes_lobby_aux._save_top8` pattern). `get_archetype_for(champion)` returns the merged view with `source` field (`default` / `user_cs` / `user_ingame` / `nudge`). |
| [dashboard/routes_archetype.py](dashboard/routes_archetype.py) | **NEW.** `GET /api/cs-archetype-pick?champion=X` returns merged pick + archetype enum metadata. `POST /api/cs-archetype-pick {champion, primary, secondary?, source?}` persists. `POST {champion, clear: true}` rolls back to DDragon-tag default. 4xx on invalid archetype/source/missing-champion. |
| [dashboard/_dispatch.py](dashboard/_dispatch.py) | Wired `routes_archetype.GET_ROUTES` + `POST_ROUTES` into the dispatcher's `_gather_get` + `_gather_post` so the new endpoints are live without a separate registration step. |
| [core/daemon_slayer_client.py](core/daemon_slayer_client.py) | New `rank_for_primary_archetype(champion, archetype, …)` dispatcher routes carry → `rank_for()` (ds.dps), bruiser → `rank_bruiser_for()` (ds.hybrid), tank → `rank_tank_for()` (ds.ehp). mage/assassin/enchanter fall back to ds.dps with `fell_back=True` until Phases 4-6 ship dedicated scorers. Returns canonicalized `{ok, scorer, archetype, ranked, fell_back}` envelope so callers don't need to know which underlying client fired. |
| [web/js/panels/champ_select.js](web/js/panels/champ_select.js) | New 6-button 3×2 archetype picker grid in the My Pick card render path (`_csvRenderCentralPane`), wedged between lock button and build chooser. `_csvFetchArchetype()` polls `/api/cs-archetype-pick?champion=X` on render; `_CSV_ARCH_CACHE` mirrors the response for subsequent ticks. Click handlers save to `localStorage.rc-cs-archetype-<champion>` (instant subsequent render) + POST to persist server-side. Optimistic DOM update so click→active feels instant. Unimplemented scorers carry `.placeholder` class (grayed) but stay clickable so the dispatcher's `fell_back` path runs. |
| [web/css/panels/champ_select_view.css](web/css/panels/champ_select_view.css) | New `.csv-archetype-picker` section (~80 LOC) — 3-column grid, info-blue active state (`#5fa8ff` border + `#0e1a2e` fill matching the existing DS pill colors), gray-out placeholder buttons at 0.55 opacity. Sits between `.csv-lock-btn` and `.csv-builds`. |
| [tests/test_archetype_picks.py](tests/test_archetype_picks.py) | **NEW.** 33 tests across 5 classes: tag-mapping (3), default-for-champion (9 including Aatrox/Lulu/Yasuo/Malphite/Caitlyn/MonkeyKing/Wukong/unknown/empty), fallback-secondary (5), persistence round-trip (15 — save/get/clear/list/validation), constants (3). Tempdir-patched so the real data file is untouched. |
| [tests/test_routes_archetype.py](tests/test_routes_archetype.py) | **NEW.** 15 tests across 3 classes: GET (4 — no-champion list + champion-default + override + archetype enum), POST (9 — save + clear + validation 400s + default source), dispatch-table registration (2 — pins the wiring so a refactor doesn't silently drop the routes). Uses a `StubHandler` stand-in so no real HTTP server spins up. |
| [tests/test_archetype_dispatcher.py](tests/test_archetype_dispatcher.py) | **NEW.** 15 tests across 6 classes: carry routing (2), bruiser routing (2 incl alpha/beta passthrough), tank routing (3 incl `only_item_ids` whitelist), fallback archetypes (3 — mage/assassin/enchanter all flagged `fell_back=True`), engine-down (3 — None propagation), unknown archetype (2). Mocks underlying `rank_for`/`rank_tank_for`/`rank_bruiser_for` so the test doesn't touch :8893. |
| Living docs sync | CLAUDE.md (+s176 entry at item 33 + DS-pointer line) · README.md (header DS bullet + capability matrix + coverage block) · docs/DAEMON_SLAYER.md (status + Phase 3 section) · docs/ARCHITECTURE.md (DS section) · ROADMAP.md (DS status line + s176 ship entry). |
| RC restart | `echo restart > restart_trigger.txt` to pick up the new route module — supervisor reloaded RC pid 15428 cleanly; `/api/cs-archetype-pick?champion=Aatrox` returns 200 with default `{primary: "bruiser", source: "default"}`. |

## Live validation

```
$ curl -sk "https://127.0.0.1:8888/api/cs-archetype-pick?champion=Aatrox"
{"ok": true, "champion": "Aatrox", "pick": {"champion": "Aatrox", "primary": "bruiser",
 "secondary": "tank", "source": "default"}, "archetypes": ["carry", "bruiser", "tank",
 "mage", "assassin", "enchanter"], "implemented": ["bruiser", "carry", "tank"]}

$ curl -sk -X POST .../api/cs-archetype-pick -d '{"champion":"Aatrox","primary":"tank","source":"user_cs"}'
{"ok": true, "pick": {"champion": "Aatrox", "primary": "tank", "secondary": "bruiser",
 "source": "user_cs", "set_at": "2026-05-13T00:53:02Z"}}

$ curl -sk .../api/cs-archetype-pick?champion=Aatrox  # confirms persistence
{... "source": "user_cs" ...}

$ curl -sk -X POST .../api/cs-archetype-pick -d '{"champion":"Aatrox","clear":true}'
{"ok": true, "cleared": true, "pick": {... "source": "default" ...}}
```

Live dispatcher probe (with the running DS server on :8893):

```python
>>> rank_for_primary_archetype('Malphite', 'tank', level=11, item_ids=[],
...                            enemy_ad_share=0.9, enemy_ap_share=0.1, top=3)
{'ok': True, 'scorer': 'ehp', 'archetype': 'tank', 'fell_back': False,
 'ranked': [{'item_id': '3143', 'item_name': "Randuin's Omen", 'delta': 2036, …},
            {'item_id': '663058', 'item_name': 'Shield of Molten Stone', 'delta': 1871, …},
            ...]}

>>> rank_for_primary_archetype('Veigar', 'mage', level=11, item_ids=[], top=3)
{'ok': True, 'scorer': 'dps', 'archetype': 'mage', 'fell_back': True, ...}
```

Math behaves as expected — tank routing surfaces armor items for AD-heavy enemies; mage routing flags `fell_back=True` so the UI can render a "Phase 4 pending" badge.

## Findings

- **The "single session, pure UI" framing in the plan was misleading.** Phase 3 as written touches 7+ subsystems (state-builder, dispatcher, REST, picker UI, CSS, coach integration ×4, soft-nudge toast, in-game switch tab, invalidation events). Shipping all of that in one slot would either bloat the PR or skip tests. Split: MVP today (data + REST + dispatcher + picker), coach wiring + nudge + in-game tab in a follow-up. Same discipline as s174 Phase 1 where shield-throughput was deferred to 1.5.
- **State-builder injection needs a server-side champion-id → name resolver that doesn't exist.** The LCU agent ships `my_champion` as an integer ID; the dashboard's JS side uses DDragon to resolve to display name (e.g. `Aatrox`). For the state-builder to stamp `state.lcu.champ_select.cs_archetype_pick`, Legion would need its own champion-id → name resolver. Three options: (a) build it via DDragon's `champion.json` (~30 LOC, low risk); (b) make the LCU agent send `my_champion_name` alongside `my_champion`; (c) defer to JS-side stamping. Chose (c) for Phase 3 because the picker UI doesn't need the state field — it fetches `/api/cs-archetype-pick` directly. Will reconsider when wiring coaches.
- **Optimistic DOM update + localStorage write before the fetch resolves is the right UX latency model.** Operator clicks "Tank" → button highlights instantly (DOM toggle), localStorage saves instantly (next render shows correct state), POST fires in background. Failure case: POST fails but localStorage already saved → next reload retries via the GET resolving local → fetch. No flicker, no lost work.
- **Carry/bruiser/tank with implemented scorers vs mage/assassin/enchanter as placeholders is the right v1.** Showing all 6 in the picker — even the unimplemented ones — preserves the taxonomy. Hiding them would mean future Phase 4 ships requiring a UI revamp; greying them with `fell_back=True` semantic means the dispatcher graceful-degrades and the operator still gets useful output. Same pattern as Galeforce (Arena re-skin) — visible but tagged.
- **Mock-based dispatcher tests beat live-engine tests for routing logic.** The dispatcher's value is "this archetype goes to that scorer with these params" — that's pure routing logic, not a DS engine math check. Mocking `rank_for`/`rank_tank_for`/`rank_bruiser_for` keeps the test independent of `:8893` health, makes CI deterministic, and runs in <50ms. Live DS tests still exist (`test_server.py::HybridRouteTests` etc.) for the underlying scorers.

## Verification

- `py -m pytest tests/test_archetype_picks.py tests/test_routes_archetype.py tests/test_archetype_dispatcher.py -v` → **63 passed**
- `py -m pytest tests/ agents/daemon_slayer/tests/ --timeout=120` → **1968 passed** (was 1905 — +63 net, no regressions)
- `py -m ruff check core/archetype_picks.py dashboard/routes_archetype.py dashboard/_dispatch.py core/daemon_slayer_client.py tests/test_archetype_picks.py tests/test_routes_archetype.py tests/test_archetype_dispatcher.py` → all checks passed
- RC restart via `restart_trigger.txt` → pid 15428 alive, `/api/cs-archetype-pick` live
- Live POST/GET/clear roundtrip → 200 + persisted JSON file shape correct
- `/api/ui-version` rotated → operator's browser will pick up new JS/CSS on next tab focus

## Open items carried forward

- 🟡 **Coach integration for state.cs_archetype_pick** — `coaches/aram_coach.py` / `arena_coach.py` / `brawl_coach.py` / `coach_integration/_coach.py` currently call `rank_for()` directly. The wire-in adds a single line per coach: replace `rank_for(...)` with `rank_for_primary_archetype(champion, state.cs_archetype_pick.primary, ...)`. Reads from the dashboard's state envelope (which doesn't yet stamp the field — see next item).
- 🟡 **State-builder stamping of `state.lcu.champ_select.cs_archetype_pick`** — needs a server-side champion-id → name resolver. ~30 LOC if we build one from DDragon `champion.json` directly in `_state_builder.py`. Unblocks coach integration above.
- 🟡 **First-purchase-mismatch soft-nudge** — when state.cs_archetype_pick.primary = "tank" but operator buys Liandry / Luden's / IE in the first ~3 min, surface a one-time toast: "Switch primary scorer to mage?". Per-match localStorage gate so it doesn't re-fire. Bigger UX lift than the picker — separate session.
- 🟡 **In-game switch tab** — mid-match archetype change UI in the active match view (currently `web/js/panels/dev.js` or a new `in_game_archetype_tab.js`). New primary fires immediately (one-shot warm pass per the s173.5 architecture lock-in); subsequent ticks use it.
- 🟡 **Secondary-scorer caching + refresh on item-complete events** — `enemy_item_complete`, `self_item_complete`, `level_threshold_crossed` invalidate the secondary's cached result. Current MVP doesn't run the secondary at all — only the primary fires per coach tick.
- 🟡 **Phase 4 — Mage ability DPS scorer** — three-session lift per the plan. Phase 4a Meraki ability ingest, 4b `compute_ability_dps()`, 4c `rank_items_by_ability_dps()` + integration. Once Phase 4 lands, `mage` archetype no longer falls back to dps in the dispatcher.

---

# s175 wrap — 2026-05-12 (Phase 2 Bruiser hybrid scorer — single commit pending)

**Operator instruction:** "next DS in the plan" → "YES" to ship Phase 2.

Phase 2 in [NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md](NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md): single-session, low-risk extension of the Phase 1 EHP work. Composes `compute_dps()` + `compute_ehp()` into a single archetype score for bruisers via per-champion α/β weights. ~20 bruisers unlocked.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/hybrid.py](agents/daemon_slayer/hybrid.py) | **NEW (~450 LOC).** `compute_hybrid()` + `HybridResult` + `rank_items_by_hybrid()` + `HybridRankedItem` + `HybridRankResult` + `get_weights_for()` + `_load_archetype_weights()` + `_hybrid_delta_pct()`. Scorer formula: `hybrid_score = α·dps + β·ehp` (raw scalar exposed in `HybridResult.hybrid_score`). Ranker sort key: `α · (dps_delta/baseline_dps) + β · (ehp_delta/baseline_ehp)` — normalized percentage delta so weights stay intuitive across the ~10× DPS/EHP magnitude gap. Imports private filter helpers from `rank.py` rather than duplicating; reuses lifeline-family dead-unique dedup. `alpha`/`beta` default to per-champion lookup; explicit floats override (UI sliders, A/B testing). `alpha_source` field tracks "champion" vs "default" vs "override". |
| [agents/daemon_slayer/archetype_weights.json](agents/daemon_slayer/archetype_weights.json) | **NEW.** 20-bruiser α/β table keyed by DDragon champion ID. Convention α+β=1.0 (operator-facing slider semantics). Default fallback (0.50, 0.50). Coverage: JarvanIV 0.55/0.45 · Darius 0.65/0.35 · Garen 0.55/0.45 · Camille 0.65/0.35 · Renekton 0.65/0.35 · Sett 0.55/0.45 · Mordekaiser 0.50/0.50 · Riven 0.70/0.30 · Volibear 0.55/0.45 · Nasus 0.50/0.50 · Olaf 0.60/0.40 · Skarner 0.50/0.50 · Hecarim 0.55/0.45 · Udyr 0.55/0.45 · Vi 0.55/0.45 · XinZhao 0.60/0.40 · LeeSin 0.65/0.35 · MonkeyKing 0.60/0.40 · Warwick 0.55/0.45 · Trundle 0.60/0.40. |
| [agents/daemon_slayer/server.py](agents/daemon_slayer/server.py) | Two new POST routes: `/hybrid` (caster combined score) + `/rank-bruiser` (items ranked by weighted percentage delta). Body shape is the union of `/dps` and `/ehp` params with optional `alpha`/`beta` overrides via new `_opt_weight()` helper. Index HTML route listing extended. |
| [core/daemon_slayer_client.py](core/daemon_slayer_client.py) | New `BruiserRankedItem` dataclass + `rank_bruiser_for()` + `hybrid_for()` helpers. Same engine-down semantics as `rank_for` / `rank_tank_for`. `alpha`/`beta` kwargs default `None` so the server-side per-champion table is used; pass floats to override. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | `ENGINE_VERSION` 0.63.0 → 0.64.0. Extended module docstring with Phase 2 changelog entry covering the composition design + the (α,β) table + ranker normalization rationale. |
| [agents/daemon_slayer/tests/test_hybrid.py](agents/daemon_slayer/tests/test_hybrid.py) | **NEW (~400 LOC).** 40 tests across 8 classes: WeightsTableTests (6 — registry + α+β=1.0 convention + MonkeyKing-not-Wukong key check), ComputeHybridBasicsTests (7 — field-by-field match against compute_dps/compute_ehp + linearity), HybridDeltaPctTests (4 — pure-math normalized-delta + div-by-zero guard), RankByHybridBasicsTests (12 — including α=1/β=0 matching pure-DPS ranker top + α=0/β=1 matching pure-EHP ranker top), CandidateFilteringTests (4), SharedUniqueFilterTests (2), ARAMModeTests (2), SerializationTests (3). |
| [agents/daemon_slayer/tests/test_server.py](agents/daemon_slayer/tests/test_server.py) | New `HybridRouteTests` class (4 tests): `/hybrid` naked w/ champion-table lookup, `/hybrid` alpha/beta override, `/rank-bruiser` shape + fields, `/rank-bruiser` share-validation 422. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Bumped `test_batch63_version` + `test_batch64_version` to assert 0.64.0; extended comment in batch63 covering Phase 0/1/2 history. |
| Living docs sync | CLAUDE.md (+s175 entry at item 32 + DS version pointer) · README.md (header DS bullet + capability matrix line + coverage block) · docs/DAEMON_SLAYER.md (status + module map) · docs/ARCHITECTURE.md (DS section) · ROADMAP.md (DS status line + s175 ship entry) · BRIEF.md (RC Tutor "what's built" line). |
| DS server runtime | Stopped pid 2388 (PowerShell `Stop-Process`) + relaunched via `pythonw tools/start_daemon_slayer.py`. `/health` confirms engine_version 0.64.0 live on :8893. |

## Live validation

Probed `/rank-bruiser` against real running DS server.

**JarvanIV + 50/50 enemy mix** (table default α=0.55/β=0.45 → "champion" source):
```
baseline_dps=57.8 baseline_ehp=2810
  3078  Trinity Force      +dps=98.9
  3508  Essence Reaver     +dps=90.7
  3097  Stormrazor         +dps=89.7
  3084  Heartsteel         +dps=64.2  +ehp=515
  3032  Yun Tal Wildarrows +dps=79.6
```

**Nasus with defensive override α=0.2/β=0.8** (overrides table 0.50/0.50):
```
  3084  Heartsteel       +dps=64.4  +ehp=501
  3078  Trinity Force    +dps=88.6  +ehp=555
  6662  Iceborn Gauntlet +dps=53.5  +ehp=998
  3083  Warmog's Armor   +dps=0.0   +ehp=668
  3877  Bloodsong        +dps=77.1  +ehp=334
```

Math behaves as expected — JarvanIV at default DPS-leaning weight picks Trinity (classic Jarvan core); Nasus with strong EHP weighting surfaces Heartsteel + Warmog's near the top. Operator-comprehensible.

## Findings

- **Raw `hybrid_score = α·dps + β·ehp` would have been misleading.** DPS scales ~100s, EHP scales ~1000s. A naive linear combination has β dominating by 10× even at α=β=0.5 — meaning a tuned (0.55, 0.45) "DPS-leaning" pair would still produce EHP-dominated rankings. Solution: normalize each delta against its own baseline at the ranker stage (`α · dps_delta/baseline_dps + β · ehp_delta/baseline_ehp`). Operator can think of (0.65, 0.35) as a true 65/35 weight. The raw `hybrid_score` field is kept on `HybridResult` for completeness; the ranker uses the normalized form.
- **Two-stage compute per candidate is unavoidable.** Each candidate evaluation runs both `compute_dps()` and `compute_ehp()` — 2× the per-candidate cost vs single-archetype rankers. At ~125-175 candidates per `rank_items_by_hybrid` call, that's ~250-350 sub-engine calls. Still sub-second on warm snapshot (verified — `/rank-bruiser` returns in ~50-100ms live). The "primary scorer only per coach tick" architecture (per s173.5 lock-in) keeps the budget bounded — bruiser coaches don't also call tank/mage scorers.
- **The α=1.0 / β=0.0 → pure DPS top-pick equivalence held automatically.** Tests `test_extreme_alpha_matches_pure_dps_ranker_top` + `test_extreme_beta_matches_pure_ehp_ranker_top` pin this invariant. Useful regression guard for future engine-math refactors — confirms the hybrid scorer is a pure linear combination of the two existing scorers with no hidden cross-terms.
- **MonkeyKing-not-Wukong test caught a real footgun.** Display name "Wukong" → DDragon ID "MonkeyKing" is the canonical RC alias gotcha (per `web/data/champion_aliases.json` shipped in s173.1). The table MUST be keyed by DDragon IDs because server-side `_resolve_champion_id` runs the display→ID translation BEFORE compute_hybrid sees the name. If someone later adds "Wukong" instead of "MonkeyKing" to the table, the override silently never fires. Test `test_monkeyking_uses_ddragon_id_not_display_name` would catch that.

## Verification

- `py -m pytest agents/daemon_slayer/tests/` → **1066 passed** (was 1022 — +44: 40 hybrid + 4 server HybridRouteTests; live-engine assertion fixed after DS server restart)
- `py -m pytest tests/ --timeout=120` → **839 passed** (wider RC suite — Phase8 live-engine test passed after restart; no regressions)
- DS server `:8893/health` → `engine_version: "0.64.0"` live
- Live probe of `/rank-bruiser` with two distinct (α,β) pairs shows reordering — weights are doing the right thing

## Open items carried forward

- 🟡 **Phase 3 — CS scorer-picker UI** — next session per the plan. Single session, pure UI work. Adds `#cs-archetype-picker` row in My Pick card + state.cs_archetype_pick wiring + dispatcher in `core/daemon_slayer_client.py` (`rank_for_primary_archetype()`) that routes to ds.dps / ds.ehp / ds.hybrid based on `state.cs_archetype_pick.primary`. Invalidation events for secondary refresh (enemy_item_complete, self_item_complete, level_threshold_crossed). First-purchase mismatch soft-nudge.
- 🟡 **Phase 2.5 — calibration (deferred)** — once `data/ds_calibration.jsonl` accumulates `scorer="hybrid"` rows with match outcomes from `rewind_history.db`, calibrate per-champion α/β by maximizing predicted-ranking → actual-buy-order alignment. Blocked on rewind_history.db freshness (per CLAUDE.md item 14).
- 🟡 **Phase 3 dispatcher will deprecate explicit `rank_bruiser_for()` calls** — coaches won't call `rank_bruiser_for()` directly; they'll call `rank_for_primary_archetype()` and the dispatcher routes based on `state.cs_archetype_pick.primary == "bruiser"`. Current direct-call API stays for testing + debug + UI tools.
- 🟡 **No coach is wired to call `rank_bruiser_for` yet.** Same situation as Phase 1's `recommend_defensive_items_via_ehp` — Phase 3 lands the wire-in via the CS picker. Direct API available for testing in the meantime.
- 🟡 **Phase/level-aware weights** — current (α,β) is global per champion. Early-game Camille is more snowball-DPS than late-game Camille. Deferred to a future v2 of the table (operator can override per-call via `alpha`/`beta` params in the meantime).
