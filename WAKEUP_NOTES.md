# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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
