# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-22 (headless continue 22 / R20) - Aggregator N lift: ARAM balance grid panel

Item 588, commit `e0f0ffac` (feature, pushed) + docs-sync. Tier-1 frontend (read-side route + panel +
pure accessor); NO engine / DS schema / ENGINE_VERSION / Share change (held 1.151.0); RC restarted
(pid 9480 -> 25356) to load the new route. gemini+ahk loop executor cycle 9. Directive = ORCHESTRATION_PLAN
R20 DIRECTOR REFILL - Section-7b competitor deep-dive lift of Aggregator N + ship any HIGH/LOW-risk presentation
finding in-run.

WHAT (lift). Aggregator N (aggregator N) heavyweight one-agent teardown, 6-point checklist, output
`docs/COMPETITOR_LIFT_2026-06-22_AGGREGATOR_N.md` (F1-F7). VERIFIED PREMISE (ground truth, not the agent's
word): `data/daemon_slayer/16.12.1/champions.json` `lolmath.aram_modifiers` carries all 7 ARAM fields
(Dealt/Taken/Healing/Shielding/Tenacity/AbilityHaste/AttackSpeed) for all 172 champs, but
`core/aram_balance_context.py` consumed only dealt+taken as a coach-PROMPT line and ZERO web panel
rendered any of it (grep-confirmed). So F1 = HIGH-value / LOW-risk / presentation-only over local data.

WHAT (ship). F1 SHIPPED IN-RUN: new `balance_grid_for`/`balance_grid_map` accessors (existing prompt
symbols byte-identical) + `GET /api/aram-balance` (`dashboard/routes_aram_balance.py`, 134 non-neutral
champs, live-proven 200/16.12.1/Aatrox +5%) + mode-gated `web/js/panels/aram_balance.js` grid (self from
`coach.champion`; ally/enemy from `liveclient.allPlayers`; signed green/red deltas, AH additive) + css/
index/main.js wiring. asset-hash auto-reload for JS/CSS; the new route needed the RC restart.

DEVIATION (intent over literal). Build spec assumed top-level `st.champion`/`st.my_team`; ground truth is
`coach.champion` + `liveclient.allPlayers` (the build agent self-corrected from the active_match.js
precedent). Single worktree build agent NOT parallel slices: the feature's wiring files (index.html /
main.js / dashboard.css / _dispatch.py) are shared, so parallel disjoint worktrees would only collide -
verifier-gated single agent is the correct shape for a cohesive vertical slice.

VERIFY. RED-first `tests/test_aram_balance_grid.py` (13). 1 worktree build agent -> read-only verifier
CONFIRM (re-ran 13 green, ruff clean, route 200, byte-identical existing defs, ASCII, node --check, no
frozen files) -> ff-only merge. Full RC suite `9391 passed / 2 skip / 103 subtests` (= R19's 9378 + 13
new), the SAME 12 pre-existing fails (3x CoachWire ARAM-template, 7 ds_pick_consumption ARAM subfails,
overlay.css sub-floor, spell_autopush on dirty `data/spell_prefs.json`) - 0 regressions. git: only the 9
intended files changed, none under `agents/daemon_slayer/` so DS suite not re-run + no DS Share sync owed.

CARRY-FORWARD (VISUAL OWED). The populated ARAM-mode panel capture: the panel is mode-gated and live state
is idle (mode=client); this headless cycle cannot drive `?ui_mock=1&mode=aram` - `preview_start` refuses to
attach to the supervisor-owned `:8888` (freeing the port kills the live runtime) and computer-use/Chrome
navigation needs an interactive `request_access` the away operator can't grant (would block the run). Per
Section-3b option 3 the code-side 5-phase audit + verifier + live backend proof stand in-slice; the
populated capture is OWED - drive it on the next cycle that has a live ARAM game or a connected
claude-in-chrome. Also still dirty + uncommitted: `data/spell_prefs.json` (runtime drift, not authored).

TRIAGE. F2 per-slot item win-rate ladder over rewind_history.db -> BACKLOG (MED-HIGH, thin solo sample);
F3/F5 already-have; F4 forbidden external winrate; F7 new TFT domain - all defer.

---

# 2026-06-22 (headless continue 21 / R19) - DS spell_damage_reduction_pct forward-marker

Item 587, commit `ee673c1d` (feature, pushed) + docs-sync `f5b94541`. DS schema surface (forward-marker
accessor); ENGINE HELD at 1.151.0 (NOT bumped), DS :8893 restarted, Share re-synced.

CONTEXT: gemini+ahk loop executor cycle 8. Directive = ORCHESTRATION_PLAN R19 DIRECTOR REFILL - NEW
forward-marker accessor `DataSnapshot.spell_damage_reduction_pct(champ_id, slot)` surfacing the per-rank
PERCENT damage reduction from `champion_abilities.json` defensive modifier blocks as a first-class
magnitude (the `modifier_blocks` taxonomy already classified them `defensive_self` but no accessor
exposed the numeric %).

WHAT: module-level `_extract_damage_reduction_pct` walks `AbilitiesSnapshot.iter_forms()`, keeps
`attribute_kind=="modifier"` + `classify_modifier_kind=="defensive_self"` + "damage reduction" in the
name, reads the FIRST `raw_modifiers` entry whose `units` are ALL the bare `"%"`. Lazy + frozen-safe
accessor (`object.__setattr__` cache; `DataSnapshot` is frozen), file-existence gate (byte-identical for
older snapshots, no broad except), returns `{label: per_rank_pct_tuple} | None`. 8 champs at 16.12.1
(Alistar R 55/65/75, Galio W magic 25..45 + physical 12.5..22.5, Garen/Gragas/MasterYi W,
Belveth/Braum/Warwick E 35..55). Pure-% filter excludes flat reductions (Amumu E, Leona W) + per-stat
scaling sub-modifiers ("% per 100 AP").

KEY DECISION (gemini director ruling B, synchronous gemini_ask). The directive said "ENGINE_VERSION
bump" but ALSO "Default-OFF, byte-identical when unconsumed. Live flip EXCLUDED" - internally
inconsistent. No consumer = byte-identical output, and the item-339/343 forward-marker convention
(`spell_sub_missile_speed`/`spell_cc_tags`) EXPLICITLY does NOT bump (~70 version-contract tests pin
1.151.0). Director chose B: HOLD 1.151.0, no pin churn. Share STILL re-synced (a `data_loader.py` edit
drifts `Share/src`; `--check` is the CI-only guard) + DS :8893 restarted (loads the code, /health stays
1.151.0).

VERIFY: TDD RED-first `test_spell_damage_reduction_pct.py` 14 cases (13 red first); 1 worktree build
agent on the disjoint data_loader + test slice + orchestrator independent re-run in main before commit.
DS suite 7511 passed / 1 skip / 1943 subtests; ruff clean; RC suite 9378 passed (the 12 fails ALL
pre-existing - 3 CoachWire ARAM-template + 7 ds_pick_consumption_p1l11 ARAM subfails + overlay.css
sub-floor + spell_autopush on dirty data/spell_prefs.json - 0 R19 regressions). ds_share_sync --check
green (373). ROADMAP 80KB trim: R15 + R16 bullets relocated to docs/ROADMAP_HISTORY.md.

FUTURE: a survivability/EHP consumer reading the % (fold prevented damage into the EHP numerator like
the flat-DR item-261/R9 path) - not wired blind. Live default-ON wiring EXCLUDED.

---

# 2026-06-22 (headless continue 20 / R18) - panel typography v2.1 sub-floor audit

Item 586, commit `0999d3eb` (pushed) + this docs-sync. Tier-1 frontend (CSS/JS = asset-hash
auto-reload ADR-008, no RC restart). No engine / DS schema / ENGINE_VERSION / Share / flip change.

CONTEXT: gemini+ahk loop executor cycle 7. Directive = ORCHESTRATION_PLAN R18 ui-audit (5-phase
fixture audit + sub-floor font tokenization of build_order / augment_reco / archetype_nudge_chip /
map_state panels). The directive's "4 disjoint CSS files" premise is FALSE (archetype chip has no
own CSS - lives in the shared grab-bag map_state.css), so parallel worktrees would collide ->
executed INLINE as orchestrator (directive "trivial item may use a single agent"); swept only the
cleanly panel-owned files per the spec's "each page sweeps its own panels only".

WHAT: build_order.css 8 `.bo-*` (12-14px) -> `var(--fs-xs)`, `.bo-name`/`.bo-delta` kept 15px as
documented operator-exceptions (operator-tuned "15px readable floor"). augment_reco.css 8 `.ar-*`
(12-15px) -> `var(--fs-xs)`. archetype_nudge_chip audited CLEAN (already 17/19px; X-button hit-target
a documented header-density exception). map_state.js 2 canvas labels (11/13px) got inline
operator-exception rationale (2D-canvas spatial annotations, no CSS token possible).

VERIFY: RED-first `tests/test_r18_panels_typography_v21_floor.py` (9 cases, mirrors R4 guard); 91
panel DOM + token/bundle-parity guards green; ruff clean. Full RC suite 9378 passed / 2 skip / 103
subtests - the 12 fails ALL PRE-EXISTING + unrelated (3x CoachWire + 7 ds_pick_consumption ARAM-
template, overlay.css [scans overlay.css only], spell_autopush on dirty data/spell_prefs.json drift);
git confirmed only the 5 R18 paths changed.

OWED (carry-forward): live populated-state visual capture. Claude_Preview refuses to attach to the
RC-owned self-signed :8888 (port held by live pythonw 9480; freeing it kills the runtime) + the
panels are in-game/champ-select-only (no live game now, mode=client). Code-side audit + test harness
are the in-slice proof. Same blocker as R4/R8/R13/R16.
