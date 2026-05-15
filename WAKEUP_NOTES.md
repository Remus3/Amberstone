# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s209–s213 wrap — 2026-05-15 (Champ-select full view redesign + tooltips + adaptive summoners)

**Operator instruction:** Iterative ~14-round design redesign of the champ-select view, starting with "see about the lobby transition + champ-select not surfacing rune builds & summoner spells" (closes s208 regression carry-forward).

## Shipped — commit f1ca81e

Net diff: +2181 / −1368 across 26 files (4 deletions). Pushed `04a1288..f1ca81e main -> main`.

### Layout
- Grid reshape: Enemies row 1 + new Suggestions row 2 right (was Enemies-spans-both).
- My Pick header dropped; portrait + name + LOCKED stack horizontally to free a 4th build chooser row.
- Loading view retired entirely (games load too fast); GameStart routes direct to active-match. Sticky-guard `game-start` tier dropped; CS→null infers in-progress.
- Pre-stamped `<body data-view="home">` eliminates the cold-load flash.

### Build chooser
- 3 curated variants + auto-generated Experimental row (DS-engine items + archetype-derived keystone + adaptive summoners).
- 2-row card per variant: colored badge label (cyan/red/violet/amber), left-aligned keystone disc + keystone name spelled out, 42px items, stacked summoner spells (D over F).
- Click pushes runes + items + summoners via `/api/loadout/apply` with new `override_runes` + `override_items` + `override_summoners` payload fields. Backend bypasses variant resolver when all 3 overrides present (synthetic `_build_experimental_resolved`).
- 3rd Vayne variant added: "lethality" (Press the Attack, Collector + Opportunity + Yun Tal + Edge of Night + LDR).

### Pick & Ban panel
- Mood toggle (Comfort/Limit/New/Synergy) **actually wired**: each mood branches the performance query in `routes_pickban.py` + drives a matching champion → counters lookup in new `data/meta/champion_counters.json` so bans flip with the recommended pick.
- "MOOD" label + single-word ALL-CAPS button names (was 2-line PICK/ONE COMFORT/PICK etc.).
- PICK/BAN headers centered over their column content + 13px font (was 11px floating).
- One-time click + lockout removed; LCU decides what sticks.

### Suggestions panel (new — row 2 right)
- Phase-aware: 4 ban-suggestion cards during ban phase (from `data/meta/global_top_bans.json`); 2×5 banned grid post-ban-phase (ally bans top, enemy bans bottom).
- 3 role-keyed pick-order tips per role.
- DS engine item output row removed (Experimental build chooser row carries that now).

### Archetype picker
- "DAEMON SLAYER BUILD ARCHETYPE" title.
- `IMPLEMENTED_SCORERS` flipped to all 6 (s174–s181 archetype-expansion plan was 100% shipped but the flag stayed at 3).
- AUTO toggle: green when on DDragon-tag default, grey-clickable to revert. Active button: 1px border + 4px violet left-edge accent + indigo fill (was heavy 2px blue competing visually with LOCKED green above).
- Sig fix: `_csvComputeSig` now includes archetype `primary:source` so the picker re-renders without page reload when operator clicks through archetypes.

### Adaptive summoners (new endpoint)
- `/api/champ-select/adaptive-summoners` reads enemy comp + champion, swaps Heal → Cleanse (CC ≥4/10) or Heal → Barrier (burst ≥6/10) for ADC-style roles. Curated + Experimental rows pull the recommendation; apply pipeline pushes the swapped pair. Frontend ⚡ badge on the swapped icon.

### Tooltips (rich)
- New `web/js/lib/lol_descriptions.js` — lazy-fetches DDragon items.json + runesReforged.json via new `/api/dictionary/items` + `/api/dictionary/runes` endpoints, strips LoL HTML tags, serves cleaned content via the existing `data-tt-html` app-tooltip system.
- Item icons show name + gold + bold stats + passive/active.
- Keystones show name + tree + short description.
- Event-driven re-render via `rc:lol-descriptions-ready` + `rc:champion-tags-ready` so tooltips stamp without page reload.

### Enemies panel
- Lock 🔒 emoji removed (cell outline encodes state).
- "(guess)" replaced with 2-piece tag chips (CC/BURST/AD/AP × TANK/BRUISER/ASSASSIN/SUPPORT/ADC/MAGE/FLEX) from new `/api/dictionary/champion-tags` endpoint + `champion_tags.js` lib.
- Role-confidence pill: 100% locked / 85% LCU-guess / 50% unassigned.
- Cell grid widened to 7 cols (icon, name, timer, tags, spacer, role, confidence) with explicit `grid-row: 1` on every child to prevent grid auto-flow from wrapping to 2 rows.

### Allies panel
- Self-row position pip gold → indigo (matches `.csv-team-cell.me` cell border). Closes the audit-flagged 3-treatment role-chip asymmetry.

### Mains icons fix
- `/api/mains` backend was emitting `/data/ddragon/<patch>/img/champion/<name>.png` which 404'd (`data/ddragon/` mount doesn't exist). Switched to `/icons/champions/<slug>.png` — DB stores DDragon-slug names already.

### Sim mode fixes
- Multiple endpoints added to `_SYNTH_BYPASS` so sim mode hits real backend: ds-preview, loadout/list, cs-archetype-pick, archetype-nudge, mains, top8, pickban-recs, adaptive-summoners, ban-suggestions, dictionary/items, dictionary/runes, dictionary/champion-tags. Pre-fix these returned `{_sim, _path}` garbage and silently broke each feature.
- `cs.bans` shape: LCU agent ships `{my_team:[ids], their_team:[ids]}` (dict), NOT array. `_csvBansSig` helper tolerates both shapes — pre-fix `.map is not a function` crashed `renderChampSelectView`.

### Tests
- 27 view-router tests rewritten for the dropped loading tier.
- 11 panel snapshot tests pass through the redesign.
- `tests/test_archetype_picks.test_implemented_scorers_are_subset` asserts all 6.

### Deletions (~430 LOC)
- `data/sim/flow_01_lobby_solo.json`
- `data/sim/flow_04_loading_screen.json`
- `web/css/panels/loading_view.css`
- `web/js/panels/loading.js`

## Audit ritual run

Operator dispatched UI-audit subagent mid-session. 5 must-fix + 3 consider items returned; **all 5 must-fix closed** + 2 of 3 consider closed + 1 consider explicitly kept (6-button archetype grid — operator preferred visual presence over collapse-to-chip).

## Carried forward to next session

Operator's `/done` was preceded by a fresh batch of asks that did NOT ship this session. Tomorrow-you, do these next — they are queued and reasoned, not redo-from-scratch:

1. **Ban strip — drop "CURRENT BANS" title row** when phase shifts to picks (cosmetic). The `.csv-sugg-row-label` element needs to be cleared (not just retext'd) in the banned-grid mode.
2. **Keystone alignment** — operator wants the keystone name text to start at the same X position across all 4 build chooser rows. Likely fix: change `.csv-build-rune-main` from flex to grid with fixed `30px auto` cols so the name always starts at x=36 regardless of img-load state.
3. **Experimental row should update on archetype change** — currently the keystone/trees update (synchronous lookup), but `/api/ds-preview` items don't refetch because the cache key is `name|dsMode` not `name|dsMode|archetype`. Fix: include archetype in `_CSV_DS_CACHE` key + retrigger fetch when arch changes.
4. **Hover hit-area** — operator says hover targets feel small; need to bump padding/min-size for items + name elements.
5. **Keystone icon + name should share the same tooltip** — likely already works via `closest("[data-tt-html]")` on the parent `.csv-build-rune-main`. Verify with operator.
6. **Pick & Ban filter constraints** — recommendations should hide champions that are: already banned, already picked, or unavailable in current mode (ARAM pool, etc.).
7. **LIMIT / NEW / SYNERGY rows 2+3 follow row 1 heuristic** — currently rows 2 (MASTERY) + 3 (META) show fixed per-role placeholders regardless of mood. Operator wants the mode-specific filter from row 1 to also constrain rows 2+3. SYNERGY needs team-comp aware lookup (deferred — needs design). Backend lift in `_csvMergePickBanData`.
8. **Countdown timers**: remove from allies + enemies panels. Bans-at-start vs tournament-style ban detection — validate by mode (ranked vs normal draft).
9. **LOCKED state move**: "✓ LOCKED [champion name]" centered BELOW the champion icon (was: portrait-row with name+state on the right).
10. **Suggestion panel tips** should incorporate operator role + ally composition + enemy composition (not just role-keyed static text).

## Future feature (note for after DS is at 100% champion coverage)

Operator's idea: **interactive Item Shaper with 3 modifiers** (DAMAGE / SURVIVABILITY / UTILITY) — increase/decrease on the fly based on game context, automatic. Reset to default shaping for the archetype when the match ends. Architectural: hooks into the DS engine's archetype scorer weights. Defer until DS engine ships every champion's per-key block-index + scoring complete.

## Verification

- RC restarted multiple times during session, all `last_reload_ok=true`.
- Asset hash flipped cleanly each edit cycle; auto-reload via `/api/ui-version` polling held up.
- 11/11 panel snapshot tests pass. 27/27 view-router tests pass.
- `node --check` clean across all touched JS.

---

# s208 wrap — 2026-05-14 (Retire legacy #cs-overlay champ-select page)

**Operator instruction:** "champ select is not forwarding meta rune and spell choices for champ" → investigation surfaced two parallel champ-select renderers (legacy `#cs-overlay` flashing on top of view-lobby + the s164 new full-page view). Operator: "retire old".

## Shipped — commit 2eff521

Net diff −1137 lines across 9 files (1 deleted file).

**Cuts:**
- `web/index.html`: `<div id="cs-overlay">` 124-line block
- `web/css/panels/champ_select.css`: entire 365-line stylesheet
- `web/js/panels/champ_select.js`: `renderChampSelectPanel` (~280 LOC) + `_fetchDsPreview` + `champSelectViewEnabled` gate + force-Flash-Snowball override + ARAM team-comp analyzer + cs-lock/reroll button wiring (~624 LOC total)
- `web/js/main.js`: removed `renderChampSelectPanel` + `champSelectViewEnabled` imports + collapsed view-router gate (ChampSelect phase always routes to `champ-select` view; sticky-guard simplified to match)
- `dashboard/view_router_state.py`: dropped `champ_select_view_enabled` param; Python mirror collapsed to match JS
- `web/css/panels/champ_select_view.css`: removed `body[data-view="champ-select"] #cs-overlay { display: none !important; }`
- Stale `cs-overlay` comment references in `team_context.css` + main.js cleaned up

**Tests updated:**
- `tests/test_view_router_state.py`: removed `ChampSelectViewGateTests` opt-out tests (2 of 3); replaced with single positive `ChampSelectViewTests.test_cs_phase_routes_to_champ_select`. `_run` helper's `csv=` param removed.

**Bonus fix:** removing the force-Flash-Snowball override (lived inside the dead overlay) closes operator's original "meta rune and spell choices not forwarding" complaint — variant summoners now push to LCU on every build pick. Previously, when the toggle was on, the variant's `summoners` were suppressed and a hardcoded `set_summoners {d:4, f:32}` was sent.

## Verification

- Python tests: **911 / 911 green**; view-router 25 / 25; panel snapshots 11 / 11
- `node --check` clean on `main.js` + `champ_select.js`; `ruff check` clean on touched .py files
- RC restarted via `restart_trigger.txt` — pid 7484, `last_reload_ok=true`
- Asset hash flipped (`5208321bea`); `curl /` returns 0 `cs-overlay`, 1 `view-champ-select`
- Live-captured Game-PC monitor 1 — dashboard renders cleanly

## Carried forward (spawn_task chip)

Orphaned helper cleanup in `web/js/panels/champ_select.js`: `_csOnChampionOrModeChange`, `_csRenderBuildList`, `_csOnBuildRowClick`, `_csApplyLoadout`, `_csMarkSelectedRow`, plus the entire `_srDraft*` cluster all have zero callers. Left in place because `_csDiffItemIds` has a downstream caller in `web/js/panels/item_build.js:327` that doesn't import it — pre-existing latent ReferenceError bug. Don't chain-delete without fixing that.

## Don't redo

- Old `#cs-overlay` retirement — shipped this session in 2eff521. The dual-renderer flash on CS open is gone.
- `champSelectViewEnabled` gate — removed; `?cs=0` opt-out path no longer exists. Anyone asking for the old page is asking for a regression.
- Force-Flash-Snowball override — removed permanently. If operator asks "summoners are forced to Flash+Snowball regardless of build", check it's not `set_summoners` being sent on the LCU side now (which would be a different bug).

---

# s207 wrap — 2026-05-14 (Phase 5.9.20 sum-of-blocks schema lift + 4 seed entries + README rewrite)

**Operator instruction:** "have the readme be in a more summary overview than technical, remove the parts for the cross-machine specifics, mentioning it is fine details are not needed, bridge application is fine, remove the 2 machine installation part. change how the check lists of things done and stuff to do is presented. remove the RC Tutor section entirely since i am slowly getting RC Tutor to be one and the same with RC, it is redundant. Simplify some descriptions for non technical non league people reading it. then continue ds" — two-part session. Part 1 is a deep README rewrite. Part 2 is the s205+s206-deferred sum-of-blocks schema lift.

## Part 1 — README rewrite (313 → 86 lines)

**Removed entirely:**
- Topology table (Legion / Game-PC / Peer with IPs / hostnames / scheduled tasks)
- Architecture file tree
- Phase 3 agent framework table (8-row internal coordination)
- Cross-Claude infrastructure deep details (Tailscale config, bearer tokens, bridge wire format)
- Bridge Watcher daemon table (4 phases + per-phase rules)
- Bring-up section (per-machine install workflow — operator's explicit ask)
- Engineering audit table (Tier 1-3)
- Roadmap section (cross-Claude learning sync, Bridge Watcher hardening, vision calibration phases)
- RC Tutor — Future Direction (operator: "redundant since RC Tutor is becoming RC")
- Operational notes (atomic writes, restart workflow, frozen files — internal dev knowledge)

**Restructured:**
- One-paragraph elevator pitch up top
- "What it does" — 5 prose paragraphs (no bullets-of-bullets), simplified for non-League readers (e.g. "champion select" glossed as "the picking phase before each match")
- "How it works" — 2 paragraphs covering the coaching tick + build engine
- "Daemon Slayer build engine" — preserved as the technical centerpiece, with the 6-archetype scoring table (the only retained checklist-style structure in the README)
- "Where it runs" — 2 sentences mentioning the 2-machine + bridge architecture as background only, no IPs / hostnames / task names
- "Project status" — narrative paragraph + 4 plain-prose bullets describing active work direction (replaced the multi-tier ✅/🟡/🔴 checklist)
- "More" — pointer list to CLAUDE.md / ROADMAP.md / docs/DAEMON_SLAYER.md / docs/ARCHITECTURE.md / docs/adr/

## Part 2 — Phase 5.9.20 sum-of-blocks schema lift

**Schema change** in `champion_block_index.json`:
```diff
- "Camille":  { "Q": 2 }
+ "Camille":  { "Q": 2, "W": [0, 1] }
+ "Heimerdinger": { "W": [0, 1, 1, 1, 1] }
+ "Katarina": { "R": [1, 3] }
+ "Malphite": { "W": [2, 3] }
```

Value type widens from `int` to `int | list[int]`. List values express "operator commits to landing every component" — when the realistic single-target damage is the sum across multiple Meraki damage blocks. Index repetition (`[0, 1, 1, 1, 1]`) elegantly expresses multipliers without needing dedicated multiplier syntax.

**Engine signature changes** (`ability_dps.py`):
- New `_normalize_block_index_value(v)` — rejects bool / str / float / None; accepts int + list[int] + empty list. ValueError on garbage with explicit reason.
- `_select_blocks(... block_index: int | Sequence[int] = 0, ...)` — when sequence supplied under "indexed" strategy, loops + sums per-element with same clamp semantics.
- `get_block_index_for(champion_id) -> tuple[dict[str, int | list[int]], str]`
- `_resolve_block_index_overrides(...) -> tuple[dict[str, int | list[int]], str]`
- 5 sites of `Optional[dict[str, int]]` widened to `Optional[dict[str, int | list[int]]]` (in `compute_ability_dps` / `rank_items_by_ability_dps` / `compute_burst_damage` / `rank_items_by_burst` parameters)

**Server `_parse_block_index`** in `server.py` — accepts JSON arrays alongside ints; defensively skips bool / non-int payloads silently (matches `_parse_form_index` / `_parse_max_priority` defensive policy).

## Live A/B headlines (Legion :8893 /ability-dps lvl 11 vs 80/30/2000)

| Champion | Key | Registry | block-0 only | sum | Delta | Ratio |
|---|---|---|---|---|---|---|
| Camille | W | [0, 1] | 100.0 | 240.0 | +140 | **2.4×** |
| Malphite | W | [2, 3] | 50.0 | 70.0 | +20 | **1.4×** |
| Heimerdinger | W | [0, 1, 1, 1, 1] | 140.0 | 260.0 | +120 | **1.86×** |
| Katarina | R | [1, 3] | 0.0 | 562.5 | +562.5 | (block 0 was bAD-only at naked AD = 0; sum captures full physical+magic volley) |

**Heimerdinger sanity check:** the sum result (260 raw) exactly matches the precomputed "Combined Total Non-Minion Damage" block (raw_modifiers values=[80, 125, 170, 215, 260] at ranks 1-5) which the engine couldn't address before because that block is `kind=modifier` and gets filtered out pre-index. The sum [0, 1, 1, 1, 1] reaches the same number through `kind=damage` blocks the indexed strategy CAN see.

## Test counts

- DS suite: **1979 → 2022** (+43 in new `test_sum_of_blocks.py`)
- Wider RC: **1013** (no regressions)

Test classes:
- `NormalizeBlockIndexValueTests` (9) — validator behavior, bool rejection, list rejection of non-ints
- `SelectBlocksListTests` (8) — int-path unchanged, list path semantics, clamping, empty-list, tuple support
- `RegistrySeedEntriesTests` (4) — 4 new entries present + correct shape
- `ResolveBlockIndexListMergeTests` (4) — caller-int wins over registry-list and vice versa, list preservation
- `AbilityDpsSumOfBlocksTests` (7) — integration: sum > forced-single + arithmetic equality (Camille / Malphite / Heimerdinger / Katarina)
- `BurstSumOfBlocksTests` (3) — burst.py call site mirrors
- `BackwardCompatIntEntriesTests` (3) — Veigar R / Cassi E still int-typed
- `ServerRouteSumOfBlocksTests` (5) — live :8893 verification including caller-supplied list via JSON body

Plus 2 existing-test updates:
- `test_every_value_is_int` → `test_every_value_is_int_or_list_of_ints` (widened to validate both shapes)
- `test_pre_s198_camille_unchanged` extended for new W=[0,1] entry

## Files touched

| File | Change |
|------|--------|
| `README.md` | Full rewrite 313 → 86 lines per operator restructure ask |
| `agents/daemon_slayer/__init__.py` | ENGINE_VERSION 0.91.0 → 0.92.0 |
| `agents/daemon_slayer/ability_dps.py` | `_normalize_block_index_value` + `_select_blocks` list path + 4 type-hint widenings |
| `agents/daemon_slayer/burst.py` | 2 type-hint widenings |
| `agents/daemon_slayer/server.py` | `_parse_block_index` accepts arrays |
| `agents/daemon_slayer/champion_block_index.json` | 4 seed entries (Camille W extension + 3 new champs) + _meta description extended |
| `agents/daemon_slayer/tests/test_sum_of_blocks.py` | NEW — 43 tests |
| `agents/daemon_slayer/tests/test_block_index_overrides.py` | 2 existing-test updates for new schema |
| `agents/daemon_slayer/tests/test_effects_expansion.py` | 2 ENGINE_VERSION pin bumps + 0.92.0 changelog comment |
| `CLAUDE.md` | Deep-references ENGINE_VERSION ref bumped + priority #65 added |
| `docs/DAEMON_SLAYER.md` | Test count + ENGINE_VERSION refs synced |
| `docs/ARCHITECTURE.md` | Test count + ENGINE_VERSION refs synced |

## Hand-off notes

- **DS server pid 14476** running 0.92.0 / 16.10.1 (was pid 11352 on 0.91.0); verified `/health` + 4 A/B routes post-restart.
- **No RC supervisor restart needed** — s207 only touched DS engine code.
- **Cumulative override coverage** now at 189 entries / 121 champions / 71% roster (was 185/118/69% pre-s207).
- **README is now a summary overview**, not a technical reference. Future sessions should resist the temptation to re-add detailed sections — use `CLAUDE.md` or `docs/DAEMON_SLAYER.md` for technical context.

## Carried forward to s208+

- 🟢 **Sum-of-blocks data batch** — 6+ remaining candidates queued (Thresh E souls+magic, Taliyah E impact+detonations, Sona Q spell+Power Chord, Malzahar E/R on-cast+DOT, Kalista E per-stack, Jinx R distance-scaled). Schema is in place; just need to add JSON entries + test assertions.
- 🟡 **Nested missing-HP parser** — Kindred E, Kayle E, Belveth R execute curve. Phase 4a `unparsed_modifiers` extractor needs upgrade to handle "X% (+ Y% per Mark) of target's missing health" format.
- 🟡 **Conditional target-state schema lift** — 6+ candidates remain (Lux Illumination, DrMundo E missing-HP, Evelynn Q charm, Kayle E missing-HP, Kindred E mark, Vayne E wall-stun). Defer until sum-of-blocks data batch ships.

## Don't redo

- Sum-of-blocks SCHEMA — shipped this session. Don't re-architect the `int | list[int]` shape; the index-repetition pattern is the canonical way to express multipliers.
- README compression — done. Future sessions should add to `CLAUDE.md` or `docs/DAEMON_SLAYER.md` instead of re-bloating the README with monotonic enumerations.

---

# s206 wrap — 2026-05-14 (Phase 5.9.19 cooldown inheritance from form 0 + README cleanup)

**Operator instruction:** "clean up readme.md and then continue ds" — two-part session. Part 1 compresses the monotonic s174-s182 enumeration that grew across recent sessions. Part 2 closes the s205 carry-forward "Engine None-cooldown fallback" — but with a re-framing because the original diagnosis was wrong about the impact magnitude.

## Part 1 — README cleanup

3 paragraphs compressed:

| README location | Before | After |
|----|----|----|
| Line 12 "Daemon Slayer build engine" bullet | ~1.5KB enumerating s174 → s182 inline | Stable summary: 6 archetype scorers + per-(champion, key) override registries + coach integration |
| Line 244 "Daemon Slayer engine — current state and remaining work" | ~2KB enumerating s174 → s181 inline | 2 tables (scorer routing + override registries) + coach wire-in checklist |
| Line 311 RC Tutor capability table row | ~600B enumerating s174 → s181 | Stable one-liner: "1979 tests, ENGINE 0.91.0, all 6 archetype scorers fully wired" |

Plus same compression pass on `docs/DAEMON_SLAYER.md` line 5 status header + `docs/ARCHITECTURE.md` line 151 DS section. Living docs now describe **what RC is**, not the changelog of how it got there.

## Part 2 — Phase 5.9.19 cooldown inheritance

**Engine signature change** (`ability_dps.py`):
```python
def _form_cooldown_at_rank(form, rank, fallback_form: AbilityForm | None = None) -> float:
    if form.cooldown:
        # use primary form's per-rank CD
    if fallback_form is not None and fallback_form.cooldown:
        # inherit from fallback (typically forms[0])
    return 60.0  # generic fallback (preserves pre-s206 behavior)
```

Both call sites (`ability_dps.py:1021` + `burst.py:731`) now pass `forms[0] if form_idx != 0 else None`. Form-swap mechanics share the actual game cooldown with their parent form, so inheritance is correct.

## Re-framing the s205 carry-forward

The s205 hand-off claimed "engine None-cooldown fallback ... under-counts by ~8.5× per-cast DPS conversion". Investigation found that diagnosis was incorrect because **all 4 affected entries have `casts_per_sec_source: "measured"`** from `spell_cast_rates.json` (covering 172 champs × Q/W/E/R × 3 modes from 2851 rewind matches). The cooldown lookup is only used for DPS when measured rate is absent — which it isn't for any of these.

**Actual s206 impact:**
1. `per_spell.cooldown` metadata now correct (was uniformly wrong 60s for 4 entries)
2. ComboCast row metadata in burst output now correct
3. Theoretical-fallback DPS conversion (only fires when measured rate absent) now uses correct CD — forward-compat for new form-swap champions before their measured rates ship

So this is a **metadata + theoretical-fallback correctness fix**, not a DPS-scoring lift. Total ability_dps for the 4 entries unchanged.

## Live A/B (Legion :8893 /ability-dps lvl 11 vs 80/30/2000)

| Champion | Key | Pre-s206 cd | Post-s206 cd | DPS unchanged? |
|---|---|---|---|---|
| Riven | R | 60.0s | **90.0s** (form 0 cd[1] @ rank 2) | ✅ 2.45 unchanged |
| Renekton | E | 60.0s | **16.0s** (form 0 cd[0] @ rank 0) | ✅ 3.16 unchanged |
| AurelionSol | R | 60.0s | **110.0s** (form 0 cd[1] @ rank 2) | ✅ 1.73 unchanged |
| Qiyana | Q | 60.0s | **7.0s** (form 0 cd[0] @ flat 7s) | ✅ 10.26 unchanged |

DPS values unchanged because all 4 use measured cps_source — confirms the intended s206 framing.

## Test counts

- DS suite: 1953 → 1979 (+26 in new `test_cooldown_inheritance.py`)
- Wider RC: 1013 (no regressions)

Test classes:
- `CooldownHelperBackwardCompatTests` (5) — pre-s206 behavior preserved when no fallback supplied
- `CooldownHelperFallbackTests` (7) — fallback inherits when primary has None; explicit None fallback returns 60s; clamping
- `AbilityDpsCooldownInheritanceTests` (7) — Riven R / Renekton E / ASol R / Qiyana Q + form-0 unaffected + unmapped Veigar R unaffected
- `BurstCooldownInheritanceTests` (3) — burst.py call site mirrors
- `ServerRouteCooldownTests` (4) — live :8893 verification

## Files touched

| File | Change |
|------|--------|
| `agents/daemon_slayer/__init__.py` | ENGINE_VERSION 0.90.0 → 0.91.0 |
| `agents/daemon_slayer/ability_dps.py` | `_form_cooldown_at_rank` signature + s206 inline comment at call site |
| `agents/daemon_slayer/burst.py` | Mirror call site update |
| `agents/daemon_slayer/tests/test_cooldown_inheritance.py` | NEW — 26 tests |
| `agents/daemon_slayer/tests/test_effects_expansion.py` | 2 ENGINE_VERSION pin bumps + 0.91.0 changelog comment |
| `README.md` | 3 paragraphs compressed + version refs bumped |
| `docs/DAEMON_SLAYER.md` | Status header compressed + version bumped |
| `docs/ARCHITECTURE.md` | DS section compressed + version bumped |
| `CLAUDE.md` | Deep-references ENGINE_VERSION ref bumped + priority #64 added |

## Hand-off notes

- **DS server pid 11352** running 0.91.0 / 16.10.1 (was pid 6052 on 0.90.0); verified `/health` + `/ability-dps` post-restart.
- **DS server is HTTP not HTTPS** on :8893 — curl --insecure fails with `schannel SEC_E_INVALID_TOKEN` because the schannel implementation rejects mkcert. Use `http://127.0.0.1:8893/health` directly.
- **No RC supervisor restart needed** — s206 only touched DS engine code; web dashboard + state-builder unchanged.
- **Dispatcher coverage unchanged** at 6/6 archetypes, no fallbacks. Cumulative override coverage stays at 185 entries / 118 champions / 69% roster.

## Carried forward to s207+

- 🟢 **Sum-of-blocks schema lift** — now 10+ candidates queued (Heimerdinger W, Thresh E souls+magic, Taliyah E impact+detonations, Sona Q spell+Power Chord, Camille W flat+max-HP, Katarina R bAD+AP, Malphite W first+subsequent, Malzahar E/R on-cast+DOT, Kalista E per-stack, Jinx R distance-scaled). Schema: extend `block_index_overrides` value type from `int` to `int | list[int]` where list means sum. **Lift warranted next session.**
- 🟡 **Nested missing-HP parser** — Kindred E, Kayle E, Belveth R execute curve. Phase 4a `unparsed_modifiers` extractor needs upgrade to handle "X% (+ Y% per Mark) of target's missing health" format.
- 🟡 **Conditional target-state schema lift** — 6+ candidates (Lux Illumination, DrMundo E missing-HP, Evelynn Q charm, Kayle E missing-HP, Kindred E mark, Vayne E wall-stun). Defer until Sum-of-blocks ships.
- 🟢 **form_index registry expansion** — TwistedFate W (Pick a Card), TahmKench R Regurgitate, Annie R Tibbers — needs runtime player-choice plumbing, not registry-only.

## Don't redo

- Cooldown inheritance — shipped this session. Don't add more inheritance layers; the form_0 → form_N pattern is the only one Meraki actually uses.
- README cleanup — done. Future sessions add to the s174-style monotonic enumeration only at their peril; instead, update the stable summary fields (test count, ENGINE_VERSION, archetype count, coverage %).
