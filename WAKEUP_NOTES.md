# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05. Only the last 3 sessions kept here.

---

# 2026-07-05 (operator handoff PHASE 1 - DS/haiku-zero ORUN waves; LEDGER 784-785)

Operator away, Fable-5 competitor-research handoff: run at MAX effort as orchestrator, PHASE 1 = DS lift waves then PHASE 2 = gemini-headless-upgrade. GROUND TRUTH FIRST corrected the premise: the DS ENGINE is genuinely exhausted this patch (ENGINE 1.179.0 / 7997 tests / registries "provably saturated"; the R66 adversarial residual list is EXHAUSTED per R70, do NOT re-pick #1-#6, #7 shield-lerp is next-patch-ingest gated). So "next DS batches" = the director's real OPEN queue (docs/ORCHESTRATION_PLAN.md ORUN1-5), which is what the Gemini director itself reads. Verified-premise + shipped the 2 headless-safe, non-engine ORUN units as separate verifier-gated commits:
- ORUN1 (`677f5237`): NEW tools/arena_shadow_report.py, the Arena sibling of hz_shadow_report.py (deterministic-vs-Haiku agreement + flip-readiness gate over data/arena_coach_shadow.jsonl; dead-state de-bias; fail-soft awaiting_accrual). Tier-1 tooling, 16 tests, verifier CONFIRM.
- ORUN5 (`6da64adc`): assume_carry_share_grade default-OFF grade fold on post_game_rubric.py (OR-alias of the pre-existing carry_efficiency fold; byte-identical OFF proven across 7 fixtures). NO ENGINE bump (heuristic rubric). 15 tests, verifier CONFIRM. G18 gated-sync row updated to the shipped state.
Correct tiers applied per R5: both Tier-1 (NO ENGINE bump / NO Share mirror / NO :8893 restart - the handoff's generic DS-wave ritual does NOT apply to non-engine units). ORCHESTRATION_PLAN ORUN1/ORUN5 marked DONE + Findings entries appended so the Phase-2 loop does not re-pick shipped work.

NEXT: PHASE 2 = invoke the gemini-headless-upgrade skill (turns this session into the ephemeral executor for the Gemini-directed loop; it continues the ORUN queue top-down - ORUN2 snowball-elasticity / ORUN3 Aggregator B per-stat / ORUN4 Aggregator D game-flow strip are the next OPEN rows + the REFILL PROTOCOL when it drains).
DO NOT redo: the DS engine is exhausted this patch (do NOT fabricate engine lift waves - registries saturated, R66 list exhausted); ORUN1 + ORUN5 are SHIPPED (do NOT re-pick); a DS-sweep refill MUST come from a FRESH adversarial Meraki-vs-registry refute pass, never a re-pick.

---

# 2026-07-05 (card MERGED to main via PR #6 + overlay-polish live-recon; LEDGER 783)

Merged the player-snapshot card + shipped 3 overlay-polish slices while the operator live-recon'd the real Electron overlay (ground truth the agent cannot see headless).
- MERGE: PR #6 (`feat/player-snapshot-card` -> main), CI green (check 4m39s + benchmarks + CodSpeed), rebase-merged. `main`@`43e9f4c1`, tree byte-identical to old head `f1d46773`. Rebase REWROTE SHAs (`b1a0c3b8`->`cc332a67`, `f1d46773`->`43e9f4c1`); mapping logged in ROADMAP so prose refs still resolve. Branch pruned.
- Overlay recon technique: `recon.py` renders `ui_mock` fixtures (NOT live) - wrote a throwaway legion-rc-origin live-capture vs live `/api/state` instead. The objective gauges do NOT show in fixtures (no game_time) - only live.
- SLICE 1 `5d5a33f6`: DS `#ovds` item names were nowrap+ellipsis-clipped to ~5 chars; now wrap + 16px + title attr (overlay slice 131 pass).
- SLICE 2 `717b1958`: removed 3 broken/unneeded HUD widgets - ward cue (`w-trinket`), threat/CDs ledger (`w-threat`, overlay-only de-register; dashboard cd_ledger kept), SUMMS dial (always UP). Kept DRAKE/BARON/ELDER + ZOI minimap (operator: ZOI DOES show in-game). node 28/28, pytest 162.
- SLICE 3 `45b51bff`: DRAKE dial suppressed once Elder is up/taken (redundant pit); node 13/13.
- DS unique-dedup note (LDR/Terminus share a unique) -> chip task_9ea11b0d (its own Tier-2 session).

NEXT (operator LIVE-GATES next session in a live game; Pengu stub is ON + displaying, so Pengu-sourced items qualify): round-1 missing-in-game cluster (`rn-lead`/`rn-choices`/`rn-callouts`/`w-spike` render headless but dark in the real overlay) + bugs (static META row, dead knob +/-, dead item radial) + stats-panel clarify; round-2 the DRAG/MOVE system (finicky anchors far from the widget, drag drops when the cursor leaves, can't move all elements anywhere, border-drag moves the whole screen - `overlay_layout.js` pointer-capture) + context-menu/item tooltip (cropped icon + far) + PR enemy-spell timer + gauges 1-line layout (horizontal/vertical). Root-cause is fine; each fix needs the operator's live Ctrl+Alt+A verify before it lands.
DO NOT redo: the card is MERGED (do not re-merge); the 3 removed widgets are gone (all broken - no Live Client CD data - do not re-add); the ZOI minimap SHOWS in-game (do not hide); overlay recon must use a LIVE capture (`recon.py` = ui_mock, hides the gauges); the remaining overlay findings are LIVE-GATED.

---

# 2026-07-05 (player-snapshot card SHIPPED - GPI-24h Home + role-rubric PGR; subagent-driven TDD; LEDGER 782)

Built the player-snapshot card end-to-end on branch `feat/player-snapshot-card` (PUSHED, head `b1a0c3b8` + LEDGER `68f37197`; NOT merged) via superpowers subagent-driven-development: 10 tasks, fresh implementer + spec/quality reviewer per task, a verifier gate + an Opus whole-branch review. Spec (2026-07-04) -> plan (`docs/superpowers/plans/2026-07-04-player-snapshot-card.md`) -> build.
- TASK 1 corrected a stale recon: rc-shell is a LIVE 2-surface Electron app; the companion window loads the shared `web/` tree from :8888, so v1 mounts in `web/` with ZERO `rc-shell/src` edits. The prior "overlay gone / all :8888" claim was WRONG (MEMORY was right).
- Backend: `player_gpi.py` `since_ts` window + win/streak/K-P/kda_mean/strongest-axis; new DB-pure `/api/player-snapshot` route (registered in `_dispatch.py`).
- Frontend: presentational `renderPlayerSnapshot` (tokens-only, ASCII, SVG arc-gauge dial); Home adapter (GPI 24h per mode tab + hero ABSORB); PGR adapter (role-rubric fold, NO new fetch, hero/rubric SUPPRESS); View Profile -> first production mount of the GPI radar.
- Verify: 5-phase UI audit 0 MUST-FIX; verifier 132/132; snapshot_panels 336; the Opus review caught 1 CRITICAL (PGR radar mounted into a `display:none` subtree) - FIXED `b1a0c3b8` (per-view containers). RC reloaded pid 12284, live `/api/player-snapshot` returns a valid model.
- Also: appended the operator's session-2 URLs to the canonical `_handoff_competitor_deep_research.md` (memory dir, non-repo per name-scrub); deleted a stray repo-root copy.

NEXT (operator /clears + starts on MAIN): open a PR for `feat/player-snapshot-card` -> main + merge (CI is PR-gated, no branch-push run) OR merge when ready. Then the Fable-5 competitor deep-research fan-out (QUEUED, memory-dir handoff, run in a dedicated Fable-5 session) + the lolmath DS-knob coverage check (separate). Operator-glance owed: dial arc-gauge vs `luna-sever-2.jpg`.
DO NOT redo: rc-shell IS alive (companion = the :8888 web tree in Electron - do NOT re-pitch "overlay gone"); the card is BUILT + reviewed + pushed on `feat/player-snapshot-card` (do NOT rebuild); the 1 Critical is FIXED; the model contract + 65/35 dial bands + visual-only absorb/suppress are settled.


---

# 2026-07-05 (weekly-hygiene pass - unattended)

Automated unattended hygiene pass (RC-WeeklyHygiene).

RELOCATED: 2026-07-04 /live-gated-drain (LEDGER 780) -> docs/history_notes.md (verbatim).

MEMORY UPDATE: reference_model_config.md - removed retired Game-PC entry (ADR-011 2026-05-29).

ANOMALY TRIAGE (rc_facts.py 04:17 2026-07-05):
- :8889 vision not listening -> EXPECTED (no game in progress; self-heals in-process).
- LCU agent not posting -> EXPECTED (no champ-select in progress).
- All 18 RC-* tasks Ready/Running, DS :8893 ok patch=16.13.1.

FLAGS FOR OPERATOR:
1. `_next_session_snapshot_card_build.md` (memory dir) - stale next-session prompt for player-snapshot card build; card is MERGED (LEDGER 782-783). Not indexed in MEMORY.md. Confirm OK to delete?
2. `reference_gamepc_retired_adr011.md` contains dead cross-link [[reference_bridge_dispatch_target_paths]] - no matching file in memory dir.

DO NOT redo: session 4 relocated verbatim; model_config Game-PC line removed.