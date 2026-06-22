# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-22 (headless continue 19 / R17) - DS anti-tank level-ramp %max-HP

Item 585, commit `5f308036` (feature, pushed) + this docs-sync. Tier-2 (DS schema / ENGINE_VERSION /
Share mirror): ENGINE 1.150.0 -> 1.151.0, DS :8893 bounced (pid 9340 -> new), Share re-synced.

CONTEXT: gemini+ahk loop executor cycle 6. Directive = ORCHESTRATION_PLAN R17 ds-sweep (antitank
ramp_lo/ramp_hi level-ramp %HP schema lift). Tightly-coupled single-file engine seam -> built inline
(full file context), verifier-gated before commit (no parallel-slice merge to gate).

WHAT: `AntiTankEntry` gains optional `ramp_lo`/`ramp_hi` endpoints (END-appended, default 0.0) +
`compute_antitank` gains optional `level`. Mirrors the P3.2 ap_ratio/ad_ratio default-OFF caster-stat
seam, for champion-LEVEL ramp. The hand-tuned magnitude encodes late-game (max-ramp) reliability; a
ramp-seeded row scales by `_level_ramp_factor` = lerp(ramp_lo,ramp_hi,(level-1)/17)/ramp_hi. DEFAULT-OFF:
level=None (the /anti-tank route default) AND level=18 are byte-identical to item 308/315; every
un-ramped row byte-identical at any level. Seeded 10 verified MAX_HP champion-level ramps (Aatrox 4:8,
Brand 8:12, KSante 1:2, Mordekaiser 1:5, Ornn 10:18, Renata 1:2, Skarner 5:9, Urgot 2:6, Zed 6:10,
Zeri 1:11).

DEVIATION (logged, intent over literal): director said "~16 rows", ground truth is 10 - the rest of the
%HP roster is rank-scaled (per-ability-rank) or flat, not champion-level ramps; Senna P (CURRENT_HP 1:10)
is a real level ramp but out of the %max-HP scope -> deferred sibling. A wrong seed is worse than a
missing one.

VERIFY: RED-first `test_antitank_ramp_r17.py` (25 cases). py_compile + ruff clean. DS suite 7497 passed /
1 skip / 1943 subtests; antitank cluster 94 passed. ENGINE pin sweep 85 files / 96 pins, 0 residual.
ds_share_sync --check green (372 files). Full RC suite 9367 passed - the 6 remaining RC failures are
PRE-EXISTING (reproduced on base `b00c4dc7` via stash: 3x CoachWire ARAM-template, doc_size_budget
ROADMAP-over-budget [FIXED this cycle - relocated 4 shipped bullets to ROADMAP_HISTORY, now under 80KB],
overlay.css sub-floor px, spell_autopush on dirty data/spell_prefs.json) - NONE are R17. Verifier
subagent CONFIRM (byte-identical contract independently reproduced).

CARRY-FORWARD: the 5 still-red pre-existing RC failures (3x CoachWire ARAM-template
`test_aram_user_template_format_with_field`, overlay.css sub-floor px, spell_autopush dirty-data) need a
separate cycle - NOT R17's scope. data/spell_prefs.json is a dirty runtime artifact left uncommitted.

LIVE-GATED: the default-ON flip (a survivability/draft consumer calling compute_antitank with the live
champion level) is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md (validate early-vs-late level-discounted
scores vs a real game before flipping).
