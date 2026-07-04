# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) archived. Only the last 3 sessions kept here.

---

# 2026-07-04 (RC2 no-live-LLM precompute-DB lane: 3 slices + first-ever DS seam flip; LEDGER 775-778)

Operator picked the precompute-DB program (ROADMAP L15) as the next RC2 lane (E10/E2 stay operator-gated).
Spec-first via Plan subagents; each build verifier-gated. 7 commits, all pushed + CI green.
- SLICE 1 (`f5939253`, LEDGER 775): ARAM deterministic `build_block` gained a 7th `choices` key - the
  PRIMARY A/B surface (shadow-measurable). Spec corrected 3 stale plan-doc premises (SR is NOT code-level
  zero-Haiku; the ARAM Stage-1/2 block was already shipped LEDGER 763; from_fields is a decoder).
- SLICE 2 (`20962f03`, LEDGER 776): NEW tools/aram_shadow_report.py (sibling of hz_shadow_report) -
  per-field deterministic-vs-Haiku agreement + dead-state ("WAIT RESPAWN") exclusion. First live reading:
  action 74% (>=70% gate MET), choices ~1%. ALSO the live C4/Ezreal+Corki DSP11 eyeball = SANE.
- SLICE 3 (`25955559`, LEDGER 777): widened _safe_choices to all 5 ARAM labels -> A/B (source_tag
  "aram_rule"), superseding slice-1's 2-label reuse. Coverage lifts as new games accrue.
- C4 FLIP (`523206d6`, LEDGER 778): DSP11 prefer_kit_axis_by_win DEFAULT-ON. Flipped RC-SIDE at
  archetype_dispatch.py:210 (NOT the DS server - that entangles the shared /rank passthrough test on
  Ezreal). RC-side caller change so NO ENGINE bump / NO DS restart / NO Share. Proven live: Ezreal default
  floats Essence Reaver #1 vs #4 off. FIRST-EVER DS seam flip - precedent set (see the seam memory).

RC reloaded (pid 21356). docs/LIVE_GAME_GATED_SYNC.md C4 = FLIPPED/CLOSED.
NEXT: ARAM item_extra/objective deterministic gaps; then Arena's remaining Haiku (763 built its block) +
the CV vision atlas (the bigger SECOND program). Other C-seams (C5-C13) still champ-gated for eyeballs.
DO NOT redo: C4 is FLIPPED - the flip point is the RC-side caller (archetype_dispatch.py:210), NOT the DS
server; do NOT bump ENGINE for a caller-default flip. Slice-1's "reuse synth" don't-redo is SUPERSEDED by
slice 3. E10/E2 stay operator-gated. A duplicate templater chip-session may exist on the operator side
(redundant - slice 3 is merged).

---

# 2026-07-04 (RC2 E11 CLOSED - PGR reskin-complete + BUILD dead-code purge + batched sweep; LEDGER 773-774)

Closed E11 (Hextech reskin across surfaces): OPEN -> DONE. RC2 banner 56/62 -> 57/62 (~92%).
- PGR (`1771f532`): 6-mapper MAP found PGR was ALREADY reskin-complete (the s220 reframe built the 4
  pgr_* sub-panels token-first: var(--hextech-token,#fallback), token wins at runtime; R47 already
  5-phase-audited them 2026-06-30). Only bare hex = augment rarity tiers (KEPT sanctioned, lobby
  .lv-rank-* precedent). Operator ruled a THIN hygiene slice: removed the pre-S3 BUILD-section dead
  code (_setEnrichedBuild + _setDsPicks + 4 orphaned clear-stubs + ~77-line orphaned CSS; 4 ins/142
  del, ZERO visual delta). Verifier PASS, 444 scoped tests, ui_recon both widths, CI green.
- HISTORY: verified reskin-complete (R30 `0c0bdc16`; 0 dead JS unlike PGR, 100% tokenized).
- BATCHED SWEEP (`b242aa28`, operator-chosen over per-surface method): 4 verification mappers confirmed
  session/user-builds/build-insights/settings ALL Hextech-reskin-COMPLETE, 0 code delta. All 9
  out-of-game surfaces done. QA docs: docs/qa/{PGR_QA,E11_SWEEP}_2026-07-04.md.
- recon.py:40 stale PGR selector fixed LOCAL-ONLY (ops/runtime gitignored, scratch harness).

NEXT: E11 is DONE. Remaining RC2 = E10 (ASCII git-history rewrite - destructive force-push, operator
go/no-go OWED) + E2 (DS 3-game live-flip - needs live games) + Phase 9 drain (when those clear).
DO NOT redo: every E11 out-of-game surface is Hextech-reskin-COMPLETE (do NOT re-audit for palette);
the #1c1c2a shared .view-tab:hover shade is sanctioned (do NOT tokenize - it touches every view's tabs);
the per-page UI-QA method is EXHAUSTED for E11 out-of-game (overlay HUD = separate polish lane, R72).

---

# 2026-07-04 (RC2 E11 LOBBY surface SHIPPED - operator UI-QA method; LEDGER 772, `1cf122e2`)

Ran the operator per-page UI-QA method on the pregame LOBBY (E11 non-home surface). CI green.
- SURFACE (router-traced): operator sees the dedicated `#view-lobby` companion VIEW (main.js
  _lobbyViewRefresh). The inline `#lobby-overlay` was SUPERSEDED legacy - a Lobby phase force-
  promotes to #view-lobby over any Home manual (main.js:704 + :941-970), so it was only phase-blip
  reachable (resolved an M1/M6 mapper disagreement by tracing the router). Lobby was ALREADY
  reskinned (8069d0b9), so this was a REFINEMENT pass.
- METHOD: 6-mapper MAP -> 4-Q advocate round + 1 confirm -> ONE worktree build agent + verifier
  (0 orphaned callers) + 5-phase audit (SHIP after 1 MUST-FIX in-slice) + ui_recon both widths.
- SHIPPED (`1cf122e2`, net -543): R1 mains tab-aware (YOUR MAINS Recent/Overall[dropped the raw
  KDA triplet]/Form[KP%,CS-m,DMG]; PARTY MAINS Mastery+Recent - dropped always-empty per-tab
  cols); R2 dead code D1-D5 incl the inline #lobby-overlay cluster; R3 lcu_agent emits party_size
  + max_party_size (count was always 0; tab auto-switch was dead; TDD RED-first); R4 sub-16px ->
  --fs-xs floor + tabular-nums; V2 .lv-fr-copy/invite 44px. D5 overlay CSS lived in home.css
  (-138); HOME verified UNAFFECTED (ui_recon + DOM). Verifier PASS, 355 scoped tests, CI green.
- QA doc: docs/qa/LOBBY_QA_2026-07-04.md. DEFERRED: G3 live rank enrich (League-V4 DB), G4 ready
  pip, G5 backend passthrough cleanup, MY-TOP-8 reserved-rows vertical cost.

NEXT: E11 remaining NON-home/lobby surfaces still OPEN (PGR / history / session / user-builds /
build-insights / settings + overlay). Same operator UI-QA method per surface. DO NOT redo:
#lobby-overlay is REMOVED (superseded, do not re-add); .lv-rank-* hex is a SANCTIONED brand tint
(do NOT tokenize); companion font floor = --fs-xs 16px.
