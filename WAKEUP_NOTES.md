# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) archived. Only the last 3 sessions kept here.

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

---

# 2026-07-04 (HEADLESS open items - header row-2 FINISHED + HOME chips A6/A7; LEDGER 770-771)

Closed the drain-session NEXT-block open items (no play needed - all headless).
- HEADER ROW-2 (item #1, DONE): finished the WIP on worktree-agent-a218a07c4022c7923.
  The FULL suite caught 2 hidden failures (test_motion_reduce_sweep_oq4 still expected the
  retired .hp.hp-critical loop) -> fixed to 8 live loops. Squash-merged `bfa78360` (the WIP-
  snapshot commit kept OUT of main); re-gated on merged main (snapshot_panels 320 + DOM 66);
  live re-render clean (1 .header-row, 0 row-2 tokens, trigger_pill.js -> 404); overlay
  unaffected (overlay.css untouched + display:none's the whole header). CI GREEN. Worktree +
  branch removed.
- TONIGHT'S PICK floor (item #3, ANSWERED): operator ruled KEEP CURRENT - no >=2-game floor
  (any champ incl 1-game; the existing "Small sample" tip caveats). No code change.
- CHIPS A6/A7 (item #2, DONE): NOT a rebase (no branch existed) - fresh data-fix, spec-first
  via a Plan subagent (spec corrected 3 premises: Recent-3 not 5; rewind CURRENT not stale;
  only ~28/110 joinable). A6 mode_subtype derives from the queueId already in
  raw_data.lcu_match_detail (NO schema migration - the spec's queue_id column was redundant);
  live Recent shows Tristana/Kalista subtype='Mayhem'. A7 NEW
  tools/backfill_home_items_from_rewind.py (STRICT champion + 10-min join, dry-run default)
  recovered 22 pre-ingest rows' items from rewind (gap 110 -> 88; 88 kept honest-empty).
  Both Tier-1, RED-first, consolidated home gate 71 passed.

NEXT: E11 remaining NON-HOME surfaces still OPEN in docs/RC2_PLAN.md (the HOME slice shipped).
Live-gated drain continuation is a PLAY session (ARAM seam flips are champ-gated:
Ezreal/Corki/Rakan/KSante/Rell/Cluster-A; ARENA still NEEDED for D2/D3/D7).
DO NOT redo: header-row-2 (merged bfa78360); A6/A7 (the queue_id column is deliberately NOT
added - queueId lives in raw_data); Tonight's Pick no-floor is an operator ruling.

---

# 2026-07-04 (/live-gated-drain - ARAM Mayhem sitting; LEDGER 769)

Drained docs/LIVE_GAME_GATED_SYNC.md while the operator played ARAM Mayhem (2 games: Kalista, Tristana).
Opus 4.8 max orchestrated (Fable limit). Read-only live validation (5-finder + adversarial verify workflow,
16 agents; NO DS restart/flip mid-game). Doc-only Tier-0, committed.
- CLOSED: B44 Guinsoo on-hit re-rank sanity (verifier-CONFIRMED live /rank Kalista -> Guinsoo #6, sane).
- ADVANCED (data-path/engine live, render halves OPEN): C1 build-chooser comp-aware, C11 cc_blended_ehp
  (DS /ehp 5776->2888 vs a real CC comp), C12 antiheal correct-silence, C13 enemy_spells.
- ACCRUAL: B20/R55 N=2 of 3 (marksman BotRK sane; R55 not a /rank body param -> DS-restart-gated).
- DEFER: all C3-C10 seam flips - NO tabled champ rolled (Kalista/Tristana); Tristana DSP11 = no-op.
- FINDINGS: screen_read stale=BY-DESIGN (operator-click-only sticky field, data/screen_read.json mtime
  2026-05-18; NOT a bug, no fix); :8889 frame NOT down (needs http + X-RC-Token, not https).
- OPS: RC restarted on operator request pid 18024->9280 (verified). Reverted the ad-hoc eyeball report
  overwrite; deleted merged branch a4934fc1. Targeted doc edit (B44 CLOSED + 2026-07-04 result block); did
  NOT run the full /live-gated-resync fan-out (small delta, doc fresh 3 days) - available next play-session.

NEXT (headless open items): (1) FINISH header-row-2 removal - WIP on worktree-agent-a218a07c4022c7923
(unmerged, KEPT, locked): complete tests, FULL tests/snapshot_panels/ gate, verify ?overlay=1 unaffected,
merge, re-render 2-3 pages, push - do NOT merge blind. (2) Backfill chips (items[] pre-ingest +
queue_id/mode_subtype) rebase onto HEAD. (3) Operator Q: Tonight's Pick >=2-game floor?
DO NOT redo: HOME round-2 shipped (LEDGER 768); B44 closed; screen_read by-design. Live-gated drain
continuation needs more play (ARAM seam flips champ-gated; ARENA still NEEDED for D2/D3/D7).

_(older 2026-07-04 blocks pruned to docs/history_notes.md; keep last 3)_
