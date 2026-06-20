# RC 2.0 - Master Orchestration Plan

LIVING DOC. Single source of truth for the RC 2.0 program. `/RC2-Continue`
reads this, finds the first non-DONE stage (top-to-bottom), and resumes.
Continuity = this file + git history + `docs/LEDGER.md` + the directive chain.

ASCII only. No em-dashes, en-dashes, or smart quotes.

---

## PROGRESS

> **Phase 2 of 9 (design DELIVERED - GATE: awaiting greenlight) - Stage 16 of 50 - approx 32% complete**

Recompute on every stage flip: `% = DONE_stages / TOTAL_stages * 100`.
If stages are added or removed, update TOTAL and re-derive the percent so the
banner always reflects the live denominator (operator directive: redo the % to
match up or down even as phases/stages grow).

Status legend: `OPEN` (not started) - `WIP` (in flight) - `DONE` (shipped, sha) - `GATE` (operator greenlight pending) - `LIVE` (code done, live-game visual owed).

---

## OPERATOR DIRECTIVE (2026-06-19, verbatim intent)

Exhaustive UI/UX research (League + non-League) -> implement headlessly via
Gemini -> Electron overlay sizing studied against how other apps do it -> deep
research on League apps/utilities/visual-effects/operation/useful-info for every
game surface (home / pregame lobby / champ select / in-match / PGR / history /
timeline) -> multiple UI-agent passes condensing in-game priority info on BOTH
overlay and dashboard -> Haiku-free laning coach tuned for local CV (not Sonnet)
-> ABC choices more specific + condition-change best-path branching -> mid/late
game + objective plays + lost-objective/stagnation response -> faster LCU
champ-select polling (all modes) + UI responsiveness without blowing out ports +
a push/pull-with-League timing map -> dashboard STAYS while overlay active
(currently disappears) -> massive operator-Q/A TODO+future list -> a visual+text
HTML of whole-app design choices (any theme, free of the current layout; if
greenlit it REPLACES the current design) -> single-monitor-friendly, non-intrusive
in-game overlay, every setting changeable WITHOUT hotkeys, separated windows OK ->
ASCII-violation sweep of all old files (kill the warning) -> project-folder cleanup
of files unused >1 week -> DS true-completeness gap analysis -> then a 2nd full
iteration (Gemini-gated to make headless). This becomes RC 2.0.

## POLICY (this program)

- **No budget.** Claude/executor spend uncapped. Gemini spend capped by `ops/loop/config.json` ceiling (runaway backstop only).
- **Gemini-credit fallback:** if Gemini runs out of credits, proceed on best recommended judgment. Do NOT default decisions back to the operator.
- **Frozen-file edits AUTHORIZED** for this program (operator grant 2026-06-19).
- **Full computer usage AUTHORIZED:** download / install / run applications as needed (operator turned off the 2nd monitor to fix default app placement).
- **Swarm:** orchestrate up to 100 parallel agents (worktree-isolated on disjoint file sets, sole merger, verifier-gate before merge). No session cap - report `Phase X of 9, Stage Y of N, ~Z%` each cycle.
- **Per-stage ritual:** TDD (failing test first where logic) -> py_compile before restart -> tiered verification (R5-R7) -> UI stages also run the 5-phase fixture audit + Claude_Preview vs /api/state -> commit + push + CI green -> `/done` ritual (append `docs/LEDGER.md`, sync this file + ROADMAP).
- **DS seams** ship DEFAULT-OFF, Meraki + rewind WIN anchored, ENGINE bump + DS :8893 restart + Share sync in the same commit; live default-ON flip is EXCLUDED -> `docs/LIVE_GAME_GATED_SYNC.md`.
- **Cadence:** use AHK / Gemini / commit+push+CI / `**/done` / `**/clear` / `**/continue` appropriately across cycles.
- **Greenlight gate:** the P2 design HTML is the ONE operator-review artifact. Everything else proceeds without mid-run gating. The full redesign cutover (P3+ replacing the current layout) is gated on that greenlight; if not yet given, P3+ build the NEW design behind a flag and keep the current design live.

## DECISIONS (operator, 2026-06-19)

- **Remote control:** desktop computer-use control ENABLED for app install + window placement (request_access on first desktop task). The operator connects their phone via their own `**/remote-control` command to type into this session mid-match.
- **Theme:** build 3 themes side-by-side into `RC2_DESIGN.html`; operator picks on review.
- **In-game primary surface:** OVERLAY-CENTRIC - a lean glanceable HUD on top of the game; the full dashboard is one toggle / 2nd window away and STAYS available (fixes the disappear bug).
- **League window:** 1920 fullscreen OR borderless default-res both acceptable; the overlay may assume this.
- **Greenlight = HARD PAUSE on redesign code (Phase 3 + Phase 4) after the Phase 2 HTML.** The non-redesign phases CONTINUE meanwhile: P5 coaching, P6 responsiveness, P7 hygiene, P8 TODO/DS-gap (none are "redesign code"). Resume P3/P4 only on operator greenlight of `RC2_DESIGN.html`.

## EXECUTION MODEL

Headless via the Gemini-directed loop (`.claude/commands/gemini-headless-upgrade.md`
+ `ops/loop/`). Each cycle: director picks the first non-DONE stage here, executor
runs the swarm for it, `/done`, `/clear`, `/continue`. Resume after any interrupt
with `/RC2-Continue`. Background-task pane (TaskCreate) carries one chip per phase
so the operator sees gray/blue progress live.

---

## STAGES

### Phase 1 - RESEARCH (exhaustive; output -> docs/research/RC2_*.md)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 1.1 | Electron/overlay sizing + DPI + click-through: how Overlay App E/Overlay App F/Aggregator C/aggregator A/Aggregator B overlays, OBS, RTSS, Discord overlay size + place an in-game HUD | DONE | docs/research/RC2_RESEARCH_overlay_sizing.md |
| 1.2 | League home/profile dashboard landscape sweep | DONE | docs/research/RC2_RESEARCH_home_profile.md |
| 1.3 | Pregame lobby UX references | DONE | docs/research/RC2_RESEARCH_lobby.md |
| 1.4 | Champ-select UX references (all modes) | DONE | docs/research/RC2_RESEARCH_champ_select.md |
| 1.5 | In-match overlay references: density, glanceability, what-to-show | DONE | docs/research/RC2_RESEARCH_in_match_overlay.md |
| 1.6 | PGR / post-game-review references (aggregator G / league-of-graphs class) | DONE | docs/research/RC2_RESEARCH_pgr.md |
| 1.7 | History / match-list references | DONE | docs/research/RC2_RESEARCH_history.md |
| 1.8 | Timeline-breakdown references (gold graphs, teamfight timelines) | DONE | docs/research/RC2_RESEARCH_timeline.md |
| 1.9 | Non-League UI/UX + visual-effects/design-language refs (glanceable HUDs, dark telemetry dashboards) | DONE | docs/research/RC2_RESEARCH_nonleague_uiux.md |

### Phase 2 - DESIGN SYNTHESIS (the greenlight gate)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 2.1 | Information architecture: what info lives where across surfaces, single-monitor model | DONE | docs/design/RC2_DESIGN.html |
| 2.2 | Color-theme + design-language options (>=3 themes) | DONE | docs/design/RC2_DESIGN.html |
| 2.3 | Overlay layout mockups (in-game, non-intrusive, glanceable) | DONE | docs/design/RC2_DESIGN.html |
| 2.4 | Dashboard layout mockups (single-monitor, settings-without-hotkeys) | DONE | docs/design/RC2_DESIGN.html |
| 2.5 | DELIVERABLE: docs/design/RC2_DESIGN.html (visual+text, multiple options) | GATE | docs/design/RC2_DESIGN.html (awaiting operator greenlight) |

### Phase 3 - OVERLAY + DASHBOARD QUICK-GLANCE (multi UI-agent)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 3.1 | In-game priority-info condensation spec (glance test) | OPEN | |
| 3.2 | Overlay UI-agent pass 1 (structure/density) | OPEN | |
| 3.3 | Overlay UI-agent pass 2 (typography/hit-targets/hierarchy) | OPEN | |
| 3.4 | Dashboard STAYS when overlay active (currently disappears) - fix | OPEN | |
| 3.5 | Settings-without-hotkeys surface | OPEN | |
| 3.6 | Dashboard UI-agent condensation passes | OPEN | |

### Phase 4 - SINGLE-MONITOR + OVERLAY UX
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 4.1 | Electron overlay sizing/DPI/multi-res correctness | OPEN | |
| 4.2 | Non-intrusive overlay (click-through zones, opacity, auto-hide) | OPEN | |
| 4.3 | Single-monitor window management (separated windows OK) | OPEN | |
| 4.4 | Settings UI: no-hotkey control of everything | OPEN | |
| 4.5 | Overlay + dashboard coexistence | OPEN | |
| 4.6 | Live-game visual validation (gated) | OPEN | |

### Phase 5 - COACHING ENGINE
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 5.1 | Haiku-free laning coach tuned for local CV (off Sonnet/Haiku in laning) | OPEN | |
| 5.2 | CV signal integration for laning verdicts | OPEN | |
| 5.3 | ABC choices specificity uplift | OPEN | |
| 5.4 | Condition-change branching (best path when conditions change) | OPEN | |
| 5.5 | Mid-game playbook | OPEN | |
| 5.6 | Late-game + objective plays | OPEN | |
| 5.7 | Lost-objective / stagnation response playbook | OPEN | |

### Phase 6 - RESPONSIVENESS (without blowing out ports)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 6.1 | LCU/LiveClient push/pull function + timing map (document RC<->League I/O cadences) | DONE | docs/research/RC2_RESEARCH_io_timing_map.md |
| 6.2 | Faster champ-select LCU polling (all modes), port-safe | OPEN | |
| 6.3 | UI responsiveness (render cadence, debounce, no-store idempotency) | OPEN | |
| 6.4 | Port-safety audit (connection reuse, no fan-out storms) | OPEN | |
| 6.5 | State-pipeline latency reduction | OPEN | |
| 6.6 | Verify no port/CPU footprint regression | OPEN | |

### Phase 7 - HYGIENE
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 7.1 | ASCII-violation full sweep of old files (kill the startup warning) | OPEN | |
| 7.2 | Stale-file census: .md/scripts unused >1 week of iterations | OPEN | |
| 7.3 | Dead-code / unused-asset removal (safety-verified) | OPEN | |
| 7.4 | Repo folder reorg | OPEN | |
| 7.5 | Verify dual suite green post-cleanup | OPEN | |

### Phase 8 - TODO/FUTURE + DS-COMPLETENESS
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 8.1 | Massive operator-Q/A TODO + future list -> docs/RC2_TODO_QA.md | OPEN | |
| 8.2 | DS true-completeness gap analysis -> docs/DS_COMPLETENESS_GAP.md | DONE | docs/DS_COMPLETENESS_GAP.md |
| 8.3 | Operator Q/A consolidation | OPEN | |

### Phase 9 - ITERATION 2 (Gemini-gated to make headless)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 9.1 | Re-run research sweep (delta-focused) | OPEN | |
| 9.2 | Re-run design synthesis | OPEN | |
| 9.3 | Final consolidation + RC 2.0 banner | OPEN | |

TOTAL_stages = 50.

---

## RESUME PROTOCOL (`/RC2-Continue`)

1. Read this file; find the first stage not `DONE`/`CLOSED` (top-to-bottom).
2. If it is `GATE` and the operator has not greenlit, build behind a flag and move on (do not block).
3. Recompute the PROGRESS banner.
4. Sync the background-task pane (one chip/phase; mark active phase WIP).
5. Run the per-stage ritual for that stage; flip it DONE with the commit sha; loop.
6. On full drain (all stages DONE): run Phase 9 once, then emit the RC 2.0 banner and stop.

## DELIVERABLE INDEX

- Research: `docs/research/RC2_RESEARCH_*.md`
- Design HTML (greenlight): `docs/design/RC2_DESIGN.html`
- Operator Q/A TODO: `docs/RC2_TODO_QA.md`
- DS completeness gap: `docs/DS_COMPLETENESS_GAP.md`
- Per-item ledger: `docs/LEDGER.md` (RC2-* entries)
