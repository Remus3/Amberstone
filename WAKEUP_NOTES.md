# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s215 wrap — 2026-05-15 (Loadout auto-generator + DS Phase 5.9.21 sum-of-blocks data batch)

**Operator instruction:** "continue loadout then continue ds" — close the s214 carry-forward 3-curated-variant auto-generator, then keep DS engine moving.

## Shipped — commits `b395032` + `77d716c`

Pushed `e89a94c..77d716c main -> main` (4 commits, 2 features). CI status pre-flight: `py_compile` clean (2350 .py), `ruff` clean, 508 phase2+regression+phase8+fu02 pass, 11 snapshot panels pass.

### s215 part A — Loadout auto-generator (commit `b395032`)
New `tools/champion_loadout_autogen.py` (~400 LOC). Emits 3 algorithmic build variants per (champion, mode) into `data/champion_loadouts.json` via `rank_for_primary_archetype` per archetype. Hand-curated wins: each (champion, mode) counts curated variants with that mode in `modes[]`; only fills to 3 with auto entries when count < 3. Stable keys `auto-<mode>-<slot>-<archetype>` so reruns refresh in place. Runes mirror `_CSV_EXPERIMENTAL_RUNES` from `champ_select.js`; summoners archetype-keyed for SR + mode-default for ARAM (4,32) / Arena (4,7). 35 new tests via DS-stub mocks; 1064 wider RC tests pass (+40 vs s214). Full 172-champ run: 13.7s, 1017 auto entries added (332 SR + 169 ARAM + 516 Arena), 0 unfilled. Vayne/Lulu/Veigar curated entries spot-verified preserved.

### s215 part B — DS Phase 5.9.21 sum-of-blocks data batch (commit `77d716c`)
First pure-data batch consuming s207's schema lift. 4 new (champion, key) entries to `champion_block_index.json`: Thresh.E=[1,2] (Maximum Bonus Magic at full Souls + canonical Magic Damage — lifts s203's single-int {E:2}), Sona.Q=[0,1] (active + Power Chord), Kalista.E=[0,1,1,1,1] (base Rend + 4× stacks = 5-stack model), Malzahar.R=[0,2] (Total Magic channel + Total target-max-HP% bonus). ENGINE_VERSION 0.92.0 → 0.93.0. DS server restarted live to pid pinned at /health=0.93.0. **Live A/B headlines:** Kalista E **+147%** raw, Malzahar R **+150%** raw, Thresh E **+94%** raw, Sona Q **+16%** raw (Power Chord block has unparsed AP scaling Phase 4a can't extract). 19 new tests in `agents/daemon_slayer/tests/test_sum_of_blocks_expansion_s215.py` + 4 prior-batch tests updated for new Thresh shape. DS suite 2022 → 2041; wider RC 1064 green.

### What's next
- **Live ARAM Mayhem test** still scheduled by operator post-/clear (carried from s214). Now also has 3-variant build chooser to validate live on every locked champion + Phase 5.9.21 Thresh/Sona/Kalista/Malzahar ability_dps lifts ride through to `/api/ds-preview` for the build chooser's experimental row.
- **DS Phase 5.9.22+ sum-of-blocks candidates remaining**: Taliyah E (mechanic uncertain — block 2 'Total Maximum Detonation' already aggregates), Jinx R secondary AOE (not single-target), Kindred E (nested missing-HP parser bucket — Phase 4a parser limitation), Kayle E (same bucket), Belveth R execute curve (same bucket). Bucket queue moves from 6 → 2 with s215 closing Thresh/Sona/Kalista/Malzahar.
- **Loadout autogen calibration**: operator may want to flip some `default_per_mode` pointers post-Mayhem if a curated default loses to the auto-primary on live ARAM rounds. No code work — pure JSON edit. Autogen preserves operator's manual default choices on re-run.
- **Deadcode cleanup (carried)**: `coaches/brawl_coach.py` + brawl mode detection across 6 files.

### Blockers / don't redo
- Loadout autogen runs DS engine ~1500 times per full pass (~14s). If DS server is down during a run, all auto entries for unfilled slots stay missing — script reports them in the `unfilled` stat. Operator can re-run after starting DS. Not a bug, by design.
- Phase 4a Meraki parser limitation on Sona Q block 1's "X% of Sona's AP" (unparsed_modifiers) is upstream — the sum-of-blocks entry correctly captures the flat base (10-30) but the AP scaling is invisible to the engine until the Phase 4a parser learns to read nested `% of <champion>'s AP` syntax. Out of scope for this batch.

---

# s214 wrap — 2026-05-15 (Champ-select s213 carry-forward + UI audit batch)

**Operator instruction:** Run through the s213 carry-forward list (11 items) — drop CURRENT BANS title, keystone alignment, archetype-change → experimental refresh, hover hit-areas, Pick & Ban filter constraints, LIMIT/NEW/SYNERGY cascade rows, SYNERGY team-comp lookup, drop allies/enemies countdown timers, validate champ-select timings, LOCKED below portrait, tip text role+comp aware. Then audit + iterate on follow-ups operator surfaced live (scrollbars, keystone right-edge constraint, P&B 3-row uniform height, icon panel-centered, 2-row left-aligned keystone text).

## Shipped — commit `f31bc1b`

Net diff: +947 / −280 across 6 files. Pushed `c864638..f31bc1b main -> main`.

### s213 carry-forward (all 11 closed)
- **CURRENT BANS title row dropped** from Suggestions card (`web/index.html` + `_csvRenderSuggestions`); parent card head + ALLY/ENEMY side labels carry the state.
- **Countdown timers removed** from allies + enemies cells + ticker interval no-op'd (`csv-team-cell-timer` + `csv-arena-cell-timer` no longer rendered).
- **LOCKED state shifted** through 3 iterations: centered-below → left-of-icon → final 3-col grid `[1fr | auto icon | 1fr]` so the portrait sits at exact panel center with state/name flanks not influencing icon position.
- **Build chooser keystone alignment**: badge + rune strip pinned to 130px width, 2-row keystone name slot (always reserves 2 lines, left-aligned). "Press the Attack" wraps "Press the/Attack"; "Conqueror" fills line 1 with line 2 reserved for vertical rhythm across all 4 rows.
- **Hover hit-areas expanded**: champion-name cells + build-item icons get padded hover surfaces with blue ring affordance. Item-strip gap bumped 3→6px.
- **Unified keystone tooltip**: bare `title` removed from img so parent's `data-tt-html` rich tooltip fires on either icon or name.
- **Archetype → experimental refresh** wired: `_csvDsCacheKey(name, dsMode, archetype)` folds archetype into cache key; archetype-button click invalidates other-archetype entries on the same champion; `/api/ds-preview` POST passes `archetype` payload. AUTO button clears everything for that champion.
- **Pick & Ban filter constraints + cascade** shipped backend (`routes_pickban.py`): queries now return `list[dict]` with `top=` + `exclude_ids` + `ally_ids` params; response gains `performance_picks` list alongside legacy single `performance` for back-compat. Client-side: COMFORT keeps 3-source layout; LIMIT/NEW/SYNERGY render 3 same-mood rows; exclude set folds ally + enemy bans + locked picks + hover intents.
- **SYNERGY team-comp lookup**: when `allies=` is provided, SQL scores by joint-WR-with-locked-allies (≥2 games threshold). Falls back to recent-form proxy when no allies locked yet. Reason text reflects "alongside locked allies · comp fit".
- **Tips role + comp aware**: new `_csvCompAwareTip()` reads `championTags` for locked allies + visible enemies, derives Fighter/Mage/Marksman/Tank/Support/Assassin counts, role-conditionally swaps row-3 tip (BOT/SUP/TOP/JNG/MID/ARAM). Falls through to static role tip when comp data is too thin.
- **Champ-select timing validated**: queue-agnostic `active_round` from `session.actions` already covers SR Normal Draft (400) / Ranked (420/440) / Blind (430) / Quickplay (490) — phase logic was correct, but `pickClickEnabled` gate retightened from coarse `cs.phase` to `cs.active_round.type === "ban"` so operator can set pick intent during pick rounds.
- **BACKLOG**: Interactive Item Shaper (post-DS-100%) recorded — 3 modifiers DAMAGE/SURVIVABILITY/UTILITY that nudge active archetype scorer weights mid-game, reset per match.

### Live audit iterations
- **No scrollbars policy**: `.csv-card-body { overflow: auto }` → `overflow: hidden`. Operator: "I do not want any scrollbar showing unless I explicitly state."
- **Pick & Ban 3 rows uniform height**: `flex: 1 1 auto` → `flex: 1 1 0` so the 3 rows distribute panel space equally regardless of reason-text length.
- **P&B reason text clamped to 3 lines** via CSS line-clamp so the fallback prefix `[no <mood> data] ` can never bloat to 4 lines (operator: "row text now 4 lines... can not ever be 4 lines. always 3").
- **Pick-order tips uniform**: 44px min-height for visual rhythm whether tips wrap to 1 or 2 lines.
- **Enemy 100%-confidence pills dimmed** (opacity 0.55) so eye-line attention budget goes to is-med / is-low rows.
- **Keystone 2-row left-aligned** (final form): `.csv-build-rune-tree-name` set to `display: block; text-align: left; height: 2.3em; overflow: hidden; white-space: normal` — guarantees 2 rows reserved always, wraps long names at whitespace, left-aligned at icon's right edge.

### Wiring confirmed
All 4 build chooser rows (On-Hit / Crit / Lethality / Experimental) fire `_csvApplyLoadout` → POST `/api/loadout/apply` → enqueues `rune_cmd` + `item_cmd` + `summ_cmd` to LCU agent via `:8889/lcu-cmd`. Experimental row carries `override_runes` + `override_items` so backend bypasses variant resolver and builds LCU commands inline from DS top-6 items + archetype-keyed keystone/tree pair.

### Tests
- 5 new s214 cases in `tests/test_routes_pickban.py`: `TestS214CascadeAndMultiPick` covering top-N + exclude_ids + synergy ally_ids paths + parse_csv_ints. 22 pickban tests pass (was 17).
- Wider RC suite: 1018 pass + 30 subtests. View-router: 25. Panel snapshots: 11.

### s214 v2 follow-up — Brawl mode retired from champ-select (commit `85fc157`)
Pushed `0c064c7..85fc157` immediately after the s214 living-doc sync. Operator deferred the 3-curated-variant auto-generator until after Mayhem games tonight; brawl strip was the immediate ride-along since brawl is no longer in live rotation. Net diff +44 / −135 across 5 files (1 deletion).
- `_csvDetectMode` + `_csvDsModeFor` + `modeLabel` dict + `buildsTitle` chain stripped of brawl branches.
- Ally / enemy renderers no longer test `mode === "brawl"`.
- 5 CSS branches dropped (pickban hide, grid reflow, allies col, enemies col + summ + name align).
- `flow_03d_brawl_select.json` deleted; routes_pickban.py + index.html comment strings cleaned.
- Legacy `coaches/brawl_coach.py` + dashboard-side brawl detection in `_liveclient.py`/`_state_builder.py`/`builders.py`/`view_router_state.py` left in place as deadcode — separate cleanup pass.

### What's next
- **Live ARAM Mayhem test** scheduled by operator post-/clear — they'll fire a real game; I'm authorized to monitor + fix inconsistencies live without permission. Watch for: build-chooser pushing correctly to LCU runes/items/spells, archetype-mismatch nudge surfacing on first non-trivial item buy, comp-aware row-3 tip rendering for ARAM mode (which uses MAYHEM role label), 3-row P&B layout collapsing cleanly to hidden via `data-cs-mode="aram"` CSS rules.
- **After Mayhem session**: build-chooser auto-generator for the 3 curated variants per (champion, mode) using DS engine scorer weights + DDragon-tag classification. Goal: every champion ships with 3 algorithmic variants + the Experimental 4th row, not just Vayne. Then continue DS engine work (next phase TBD — Phase 5.9.21 sum-of-blocks bucket extension is the most-likely candidate based on s207's queued list).
- **Deadcode cleanup (low priority)**: `coaches/brawl_coach.py` + brawl mode detection in dashboard/_liveclient.py / _state_builder.py / builders.py / view_router_state.py. Brawl coach was a copy of ARAM coach with mode-flag swap; removal is mechanical but spans 6 files.

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
