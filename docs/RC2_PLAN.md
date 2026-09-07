# RC 2.0 - Master Orchestration Plan

> **SCOPE (2026-07-26, one-tracker pass):** this is a PROGRAM SUBPLAN, not a rival tracker.
> It is authoritative for the RC 2.0 program's stage sequence ONLY. All open work is tracked
> in `ROADMAP.md` (see its "WHERE WORK LIVES" table); the RC 2.0 lane there is RM-03. Do not
> file general open work here. It previously read "Single source of truth", which collided
> verbatim with `docs/ORCHESTRATION_PLAN.md`'s identical claim.

LIVING DOC for the RC 2.0 program. `/RC2-Continue`
reads this, finds the first non-DONE stage (top-to-bottom), and resumes.
Continuity = this file + git history + `docs/LEDGER.md` + the directive chain.

ASCII only. No em-dashes, en-dashes, or smart quotes.

---

## PROGRESS

> **Design GREENLIT (Hextech); operator batch E1-E12 added - Stage 57 of 62 - approx 92% complete**
>
> _(Detail: 57/62 done = ~92%. The full done-set recompute line relocated verbatim to
> docs/history_notes.md (mdclean C7, 2026-07-17); per-stage statuses + SHAs live in STAGES +
> the E-stage table. Remaining: E10 ASCII history-rewrite (operator go/no-go owed), E2 DS
> 3-game flip (live-gated), Phase 9 final drain (9.1-9.3) when all else DONE.)_

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
- **DS seams** ship DEFAULT-OFF, Meraki + rewind WIN anchored, ENGINE bump + DS :8860 restart + Share sync in the same commit; live default-ON flip is EXCLUDED -> `docs/LIVE_GAME_GATED_SYNC.md`.
- **Cadence:** use AHK / Gemini / commit+push+CI / `**/done` / `**/clear` / `**/continue` appropriately across cycles.
- **Greenlight gate:** the P2 design HTML is the ONE operator-review artifact. Everything else proceeds without mid-run gating. The full redesign cutover (P3+ replacing the current layout) is gated on that greenlight; if not yet given, P3+ build the NEW design behind a flag and keep the current design live.

## DECISIONS (operator, 2026-06-19)

- **Remote control:** desktop computer-use control ENABLED for app install + window placement (request_access on first desktop task). The operator connects their phone via their own `**/remote-control` command to type into this session mid-match.
- **Theme:** build 3 themes side-by-side into `RC2_DESIGN.html`; operator picks on review.
- **In-game primary surface:** OVERLAY-CENTRIC - a lean glanceable HUD on top of the game; the full dashboard is one toggle / 2nd window away and STAYS available (fixes the disappear bug).
- **League window:** 1920 fullscreen OR borderless default-res both acceptable; the overlay may assume this.
- **Greenlight = HARD PAUSE on redesign code (Phase 3 + Phase 4) after the Phase 2 HTML.** (SPENT: design GREENLIT 2026-06-20 - next section; P3/P4 unblocked and since DONE.)

## GREENLIGHT + OPERATOR DECISIONS (2026-06-20)

Design GREENLIT: theme = **Hextech Tactical**. P3/P4 redesign code is UNBLOCKED
(reskin to Hextech). League now runs **borderless @ 2560x1440** (overlay sizing
target). New global ask: **per-panel visibility toggles, separate for in-game vs
out-of-game** (Settings).

TOP-10 answers (from docs/_archive/RC2_TODO_QA.md):
Consolidated -> docs/RC2_QA_CONSOLIDATED.md (stage 8.3, f05b853d); the 10 verbatim answers
relocated to docs/history_notes.md (mdclean C7, 2026-07-17). Decisions live on in the E-stage
table below (E1-E12 map 1:1 to the answers).

### Operator-approved execution batch (E-stages, added to TOTAL)
| E | Item | Status | Commit |
|---|------|--------|--------|
| E1 | Dashboard persist-in-bg + pinned-on-top + per-panel in/out-game toggles | DONE | overlay_state.keepCompanion + companionAlwaysOnTop + panel_visibility.js (needs rc-shell relaunch) |
| E2 | DS 3-game live-flip eyeball pass (operator-played, live-gated) | OPEN | |
| E3 | End-of-game win capture (history/home W/L + season WR) | DONE | ad4c9906 |
| E4 | Counter-picks vs live enemy comp + ban-phase collapse | DONE | GET /api/champ-select/counter-picks + _csvBanPhaseComplete collapse |
| E5 | Laning hold-band recalibration (shadow vocabulary) | DONE | 4da01fbe |
| E6 | Spell flip-back fix + WR% under spells + highest-role-WR on lock + remember last-used per champ/mode | DONE | _sync_spells per-lock idempotency + manual-override + WR route |
| E7 | ARAM bench-swap responsiveness + LCU connection pooling (frozen lcu_client.py) | DONE | E7a `64591d5f` bench-swap fast re-poll (latency-sensitive cmds skip the 0.5s drain wait; drain_once helper; 82 phase_b green); pooling shipped 6.4; E7b pool-wire optional; live bench-swap eyeball owed -> LIVE_GAME_GATED_SYNC |
| E8 | Design system: reduced-motion-done-right + status glyphs + threshold statusFor() | DONE | 19f8116f |
| E9 | Rank/tier/LP header + player scouting (both NOW) | DONE | core/lcu_ranked.py + routes_scouting.py; Riot key = API-Key-Riot.txt via core/riot_api.py |
| E10 | ASCII retro sweep (all files, frozen) + git-history rewrite + force-push | OPEN | |
| E11 | Hextech reskin across surfaces (P3/P4 visual cutover) | DONE (all 9 out-of-game surfaces; overlay via separate lane) | home 768 / champ-select 765-766 / lobby `c6670b19` (772) / PGR `83418d2b` (773) via the operator UI-QA method; history/session/user-builds/build-insights/settings verified complete via the E11 batched sweep (LEDGER 774); overlay HUD Hextech via the separate overlay-polish lane (R72, LEDGER 760) |
| E12 | Responsiveness levers L1/L2/L4 (SSE/build TTL halve, etc.) | DONE | L1/L4 shipped 6.3; L2 `48fcee51` RuneWriter lobby-mode memoization (per-session _cached_lobby_mode, port-safe fewer LCU GETs, +4 tests). Residual QA62 / lever L3: prerequisite shipped R148 (`lcu/champ_select_shape.py`) - the L3 rewire itself stays OPEN, see the R148 finding for why the research note understated it |

TOTAL_stages = 62 (50 base + 12 E-batch).

## EXECUTION MODEL

Headless via the Gemini-directed loop (`.claude/commands/gemini-headless-upgrade.md`
+ `ops/loop/`). Each cycle: director picks the first non-DONE stage here, executor
runs the swarm for it, `/done`, `/clear`, `/continue`. Resume after any interrupt
with `/RC2-Continue`. Background-task pane (TaskCreate) carries one chip per phase
so the operator sees gray/blue progress live.

---

## STAGES

### Phase 1 - RESEARCH (exhaustive; output -> docs/_archive/2026-07-28-research-consolidation/RC2_*.md)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 1.1 | Electron/overlay sizing + DPI + click-through: how Overlay App E/Overlay App F/Aggregator C/aggregator A/Aggregator B overlays, OBS, RTSS, Discord overlay size + place an in-game HUD | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_overlay_sizing.md |
| 1.2 | League home/profile dashboard landscape sweep | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_home_profile.md |
| 1.3 | Pregame lobby UX references | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_lobby.md |
| 1.4 | Champ-select UX references (all modes) | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_champ_select.md |
| 1.5 | In-match overlay references: density, glanceability, what-to-show | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_in_match_overlay.md |
| 1.6 | PGR / post-game-review references (aggregator G / league-of-graphs class) | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_pgr.md |
| 1.7 | History / match-list references | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_history.md |
| 1.8 | Timeline-breakdown references (gold graphs, teamfight timelines) | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_timeline.md |
| 1.9 | Non-League UI/UX + visual-effects/design-language refs (glanceable HUDs, dark telemetry dashboards) | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_nonleague_uiux.md |

### Phase 2 - DESIGN SYNTHESIS (the greenlight gate)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 2.1 | Information architecture: what info lives where across surfaces, single-monitor model | DONE | docs/design/RC2_DESIGN.html |
| 2.2 | Color-theme + design-language options (>=3 themes) | DONE | docs/design/RC2_DESIGN.html |
| 2.3 | Overlay layout mockups (in-game, non-intrusive, glanceable) | DONE | docs/design/RC2_DESIGN.html |
| 2.4 | Dashboard layout mockups (single-monitor, settings-without-hotkeys) | DONE | docs/design/RC2_DESIGN.html |
| 2.5 | DELIVERABLE: docs/design/RC2_DESIGN.html (visual+text, multiple options) | DONE | GREENLIT 2026-06-20: theme=Hextech; replaces current design on P3/P4 |

### Phase 3 - OVERLAY + DASHBOARD QUICK-GLANCE (multi UI-agent)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 3.1 | In-game priority-info condensation spec (glance test) | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_OVERLAY_CONDENSATION_SPEC.md |
| 3.2 | Overlay UI-agent pass 1 (structure/density) | DONE | web/js/lib/overlay_priority.js (`39303acb`) + callout 2-row clamp (`db6f77d4`) |
| 3.3 | Overlay UI-agent pass 2 (typography/hit-targets/hierarchy) + wire right_now.js/overlay_pulse.js to shouldPulse (spec-flagged behavior change; shadow + 5-phase audit + operator eyeball) | LIVE | `87f41baf` shadow-wire (signalFromState + data-s0-* stamp) + 44px choice hit-target; pulse flip owed -> LIVE_GAME_GATED_SYNC.md |
| 3.4 | Dashboard STAYS when overlay active (currently disappears) - fix | DONE | `183f1969` (E1 `a61703ef` shell mechanism + web keepCompanion/pin toggles) |
| 3.5 | Settings-without-hotkeys surface | DONE | `f2bdb2fa` (no-hotkey Force vision scan Settings control; the lone hotkey-only action now keyboard-free; backend /api/command force_vision pre-existed) |
| 3.6 | Dashboard UI-agent condensation passes | DONE | `web/js/lib/condense.js` (`2d347dc0`) - condenseKvRows collapses empty supporting KV rows in RIGHT NOW + NEXT |

### Phase 4 - SINGLE-MONITOR + OVERLAY UX
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 4.1 | Electron overlay sizing/DPI/multi-res correctness | DONE | `4d5d54f0` overlay_state.resolveOverlayMetrics (DPI-guarded, work-area scale) + main.js window-size + ovscale -> web overlay.css `--rc-overlay-scale` zoom |
| 4.2 | Non-intrusive overlay (click-through zones, opacity, auto-hide) | DONE | `85d6b29e` effectiveIgnoreMouse + clickthrough_zones.js hover detector + setOpacity slider + overlay_idle.js idle recede (data-rc-idle) |
| 4.3 | Single-monitor window management (separated windows OK) | DONE | `1a96b764` overlay_state.resolveSeparatedCompanionBounds + rectsOverlap + separateWindows setting; main.js applySingleMonitorLayout (single-display-gated, reposition-only) + #ovset Separate-windows toggle |
| 4.4 | Settings UI: no-hotkey control of everything | DONE | `7de74b2c` overlay-action IPC: #ovset panel-set selector + interact-now (overlay_state.normOverlayAction allow-list; main.js applyPanelSet/setOverlayActive shared with the cycle/active hotkeys); hide stays a hotkey by design |
| 4.5 | Overlay + dashboard coexistence | DONE | `f7a667f9` overlay_state OVERLAY_ACTIONS += rearrange/raise-companion + main.js applySingleMonitorLayout({force}) / raiseCompanion() + #ovset .ovset-actpair (Re-arrange / Show dashboard) over the 4.4 action IPC |
| 4.6 | Live-game visual validation (gated) | LIVE | no headless work remains; operator eyeball of P4.1-4.5 over a real 2560x1440 borderless game owed -> docs/LIVE_GAME_GATED_SYNC.md |

### Phase 5 - COACHING ENGINE
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 5.1 | Haiku-free laning coach tuned for local CV (off Sonnet/Haiku in laning) | DONE | `77ef5e2a` core/laning_cv_overrides.py (CV override pipeline) + resolve_band + hz_choice_shadow cv_override column; shadow-only, served flip -> 5.2/LIVE_GAME_GATED_SYNC.md |
| 5.2 | CV signal integration for laning verdicts | LIVE | `fd5e6872` served-flip mechanism (laning_cv_overrides.apply_cv_to_choices + laning_choices apply_cv + _cv_served_enabled RC_LANING_CV_SERVED gate, default-OFF byte-identical); default-ON flip agreement-gated -> LIVE_GAME_GATED_SYNC.md |
| 5.3 | ABC choices specificity uplift | DONE | `9d892ed8` CoachChoice.trigger condition field (served + shadow chips, .rc-trigger sub-line) |
| 5.4 | Condition-change branching (best path when conditions change) | DONE | `6673e619` CoachChoice.rebranch_when/rebranch_to + pure laning_rebranch (adjacent-cell probe) on shadow chip A |
| 5.5 | Mid-game playbook | DONE | `68eb01bc` core/objective_playbook.playbook_callout (objective schedule x lead -> kind=playbook row, phase-gated, CV upgrades) + objective_playbook_shadow; _deterministic_coaching vision_summary stamp + sig + eta-sorted splice; lead_projection.phase_for |
| 5.6 | Late-game + objective plays | DONE | `4c3a3c2d` core/objective_playbook.LATE_OBJECTIVE_PLAYBOOK late-phase escalation (baron/dragon closing directives; elder base "*", herald base fallback); additive, no wiring change |
| 5.7 | Lost-objective / stagnation response playbook | DONE | `08ec3ebd` core/macro_response.py (lost_objective_response + stagnation_response + macro_response_callout, kind="macro_response") + core/macro_response_shadow.py; _liveclient objective_events + det-coach splice/_STATE_SINCE memory/cache-sig/shadow wire |

### Phase 6 - RESPONSIVENESS (without blowing out ports)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 6.1 | LCU/LiveClient push/pull function + timing map (document RC<->League I/O cadences) | DONE | docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_io_timing_map.md |
| 6.2 | Faster champ-select LCU polling (all modes), port-safe | DONE | RuneWriter 2.0s->1.0s env-tunable; tests/test_runewriter_poll_interval_rc2.py |
| 6.3 | UI responsiveness (render cadence, debounce, no-store idempotency) | DONE | `e9b1a5d0` routes_state `_STATE_CADENCE_S` env-tunable shared SSE-tick+TTL (default 0.5s, L4) + `idempotent_render.makeStreamGate` SSE dedup wired in main.js + no-store regression guard |
| 6.4 | Port-safety audit (connection reuse, no fan-out storms) | DONE | `3263dc40` core/lcu_pool.py HttpsConnectionPool (L6 keep-alive reuse) + MinIntervalGuard (L7 floor) + pool_enabled RC_LCU_POOL default-OFF; poller `_lcu_get` opt-in pilot; docs/_archive/2026-07-28-research-consolidation/RC2_PORT_SAFETY_AUDIT.md; L8 :2999 >=1.5s floor regression-locked |
| 6.5 | State-pipeline latency reduction | DONE | `74e9cf1b` build_state overlaps the independent liveclient relay round-trip (`_RELAY_POOL` ThreadPoolExecutor submit before lcu/coach reads, join before first use) - removes one localhost round-trip from the serial /api/state path + bounds a hung relay at max() not sum() of the two 1s timeouts; port-safe; tests/test_state_builder_latency_rc2.py (start/end ordering proof) |
| 6.6 | Verify no port/CPU footprint regression | DONE | `92ca2279` consolidated footprint guard `tests/test_port_cpu_footprint_rc2.py` (13) re-asserting every Phase 6 lever in one gate + `docs/_archive/2026-07-28-research-consolidation/RC2_PORT_CPU_FOOTPRINT_VERIFICATION.md` (per-lever socket/CPU delta table + live loopback baseline) |

### Phase 7 - HYGIENE
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 7.1 | ASCII-violation full sweep of old files (kill the startup warning) | DONE | `dbbd7a8d` tree provably banned-glyph clean (only immutable _archive retains em-dashes); p3 comment+docstring sweep 0 residual across 546 .py; test_smart_quote_hygiene now INCLUDES frozen (operator "frozen INCLUDED") + test_frozen_files_clean_of_banned_glyphs lock; docs/_archive/2026-07-28-research-consolidation/RC2_ASCII_SWEEP_VERIFICATION.md |
| 7.2 | Stale-file census: .md/scripts unused >1 week of iterations | DONE | `29fa1750` 998 stale (no-commit >1wk), 254 removable-class examined by 3 disjoint census agents; 0 REMOVE / ~96 ARCHIVE-CANDIDATE / rest KEEP; ~744 live-code KEEP-out-of-scope (dead-code -> 7.3); cross-ref-breaker caveats logged (routes_static _AGENT_ALLOWED, BACKLOG/ROADMAP back-refs, no-rm dated artifacts, P0/P1 hold-til-phase-close); docs/_archive/2026-07-28-research-consolidation/RC2_STALE_FILE_CENSUS.md |
| 7.3 | Dead-code / unused-asset removal (safety-verified) | DONE | `5f3391c8` safety-verify of the 7.2 census: bulk archive-candidates re-probed COUPLED (live regression tests / living docs / routes_static _AGENT_ALLOWED / immutable agent history / P0-P1 hold-til-phase-close) -> RETAINED, correcting the census labels; only 8 provably-orphan one-shot tools quarantined to `_archive/2026-06-20-rc2-p73/` (git mv, history preserved as renames): hotfix_sr_adc_loadouts_item167 / hotfix_arena_mage_mislabel_item273 / migrate_abilities_units_2026_05_30 / caveman_default / champion_loadout_handcurate(+_merge) / migrate_carry_summoners_flash_barrier / champion_loadout_backfill_item208_carry; NEW tests/test_rc2_p73_quarantine.py (4: gone-from-tools + in-archive + siblings-retained + no-live-import static guard); 2288 passed across loadout/champion/tools risk surface, 0 broken; 5 tools/*.md skill-dups DEFERRED (noisy substring refs) |
| 7.4 | Repo folder reorg | DONE | `386d5e2c` structure verified-canonical (3-agent census + independent re-verify): archived the spent one-shot repo-audit prompt+output pair -> `docs/_archive/2026-06-17-repo-audit/` (history-preserving renames), only live ROADMAP ref repathed, LEDGER/history_notes left append-only; verified KEEP-AT-ROOT set documented - advisor cluster (`composition_advisor`/`item_advisor`/`performance_tracker`) eager-imported by FROZEN `app/__init__.py`+`app/_game_lifecycle.py`, `docs io RC peer` rename hits frozen CLAUDE.md + 10 `.gitignore` secret globs (un-ignore hazard), `start_claude.ps1` is a LIVE session launcher (not an artifact), tooling-anchored configs + portable `.bat` set; root files 35->33; docs/_archive/2026-07-28-research-consolidation/RC2_FOLDER_REORG.md |
| 7.5 | Verify dual suite green post-cleanup | DONE | `afa07330` full dual suite GREEN: 17151 passed / 7 skipped / 2052 subtests / 0 failed (root pytest, Share excluded per pytest.ini norecursedirs). Root-caused 5 agent3 round tests (round16/24/25/28/29) asserting stale unicode arrows that production correctly emits as ASCII `^`/`v`/`\|` per the no-unicode rule - fixed the 4 failing asserts + 2 tautology/dead siblings; + ROADMAP.md 88772->65096 bytes (3 shipped mega-bullets relocated to docs/ROADMAP_HISTORY.md) restoring the 80KB doc-size-budget guard. Tier-1 test+doc, no engine/DS/Share/frozen. Phase 7 HYGIENE COMPLETE (7.1-7.5) |

### Phase 8 - TODO/FUTURE + DS-COMPLETENESS
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 8.1 | Massive operator-Q/A TODO + future list -> docs/_archive/RC2_TODO_QA.md | DONE | docs/_archive/RC2_TODO_QA.md (97 items, 9 sections, TOP-10 decisions) |
| 8.2 | DS true-completeness gap analysis -> docs/DS_COMPLETENESS_GAP.md | DONE | docs/DS_COMPLETENESS_GAP.md |
| 8.3 | Operator Q/A consolidation | DONE | `f05b853d` docs/RC2_QA_CONSOLIDATED.md - 97 items reconciled vs HEAD (33 SHIPPED / 13 GATED-LIVE / 18 GATED / 31 OPEN / 2 CLOSED); 6-agent reconcile, evidence-cited, sample re-verified; raw RC2_TODO_QA.md now points here. Phase 8 COMPLETE |

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

- Research: `docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_*.md`
- Design HTML (greenlight): `docs/design/RC2_DESIGN.html`
- Operator Q/A TODO: `docs/_archive/RC2_TODO_QA.md`
- DS completeness gap: `docs/DS_COMPLETENESS_GAP.md`
- Per-item ledger: `docs/LEDGER.md` (RC2-* entries)

## FINDINGS LOG (RC2)

24 SHIPPED mega-entries (P3.x-P8.x + E-lane rounds) relocated verbatim to docs/history_notes.md
(mdclean C7, 2026-07-17); the STAGES + E-stage tables above carry the same SHAs. Append new
findings here.
