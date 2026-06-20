# RC 2.0 - Master Orchestration Plan

LIVING DOC. Single source of truth for the RC 2.0 program. `/RC2-Continue`
reads this, finds the first non-DONE stage (top-to-bottom), and resumes.
Continuity = this file + git history + `docs/LEDGER.md` + the directive chain.

ASCII only. No em-dashes, en-dashes, or smart quotes.

---

## PROGRESS

> **Design GREENLIT (Hextech); operator batch E1-E12 added - Stage 29 of 62 - approx 47% complete**
>
> _(% recomputed: 12 approved execution stages E1-E12 added to the 50 base = 62 total. Done: 22 base (+3.1 overlay condensation spec, +3.2 overlay structure/density: arbitration primitive + density clamp, +3.3 overlay shadow-wire S0 arbitration + 44px choice hit-target [LIVE: pulse flip operator-gated], +3.4 dashboard-persist keepCompanion/pin toggles reachable from overlay UI) + E3 win-capture + E5 hold-band + E8 design-system + E6 spell-fix + E9 rank/scouting + E4 counter-picks/ban-collapse + E1 persist/pinned/panel-toggles = 29. 29/62 = 46.8% -> ~47%.)_

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

## GREENLIGHT + OPERATOR DECISIONS (2026-06-20)

Design GREENLIT: theme = **Hextech Tactical**. P3/P4 redesign code is UNBLOCKED
(reskin to Hextech). League now runs **borderless @ 2560x1440** (overlay sizing
target). New global ask: **per-panel visibility toggles, separate for in-game vs
out-of-game** (Settings).

TOP-10 answers (from docs/RC2_TODO_QA.md):
1. **Dashboard persists in background while overlay active** + add a **pinned-on-top** setting. [P3.4]
2. **DS 3-game live-flip eyeball pass - APPROVED ("ready to start").** 11 default-OFF seams; needs live games. Prep the flip checklist/harness; flips are operator-played. [P2-DS / docs/LIVE_GAME_GATED_SYNC.md]
3. **End-of-game win capture - APPROVED.** Keystone (tracked_win on disk, not loaded). Operator note: after a match + honor page, re-entering lobby auto-flipped to PGR - verify the win was captured + that PGR auto-show does not clobber a wanted lobby view. [#3 win-capture]
4. **Counter-picks vs live enemy comp - APPROVED** + banned champions display COLLAPSES when the ban phase ends. [champ-select]
5. **Laning off Haiku + hold-band recalibration - APPROVED** (Tier-2 recalibration + regen, not blind). [P5.1]
6. **Responsiveness levers L1/L2/L4 - APPROVED** + FIX the summoner-spell flip-back: stop the poll loop re-pushing the default over a manual change; **% under spells = champion regional WR% for the mode**; on first lock pick the **highest-role-centric-WR spells**; **remember the operator's last-used spells per champion per mode**. [P6 + spell feature]
7. **LCU connection pooling - APPROVED now** (frozen lcu_client.py edit OK) + **ARAM bench-swap must be EXTREMELY responsive** (bench_swap_fast already bypasses the 5s client delay; tighten detection/latency). [P6.4 + bench]
8. **Accessibility/design HIGH-lifts - APPROVED** (reduced-motion-done-right + redundant status glyphs + threshold helper). [P3 design-system]
9. **Rank header + player scouting - PROMOTE BOTH to NOW.** [home rank + Riot scouting]
10. **ASCII retro-sweep - APPROVED: ALL files, frozen INCLUDED, git HISTORY INCLUDED** (history rewrite + force-push, pre-authorized). [P7.1 + history filter]

### Operator-approved execution batch (E-stages, added to TOTAL)
| E | Item | Status | Commit |
|---|------|--------|--------|
| E1 | Dashboard persist-in-bg + pinned-on-top + per-panel in/out-game toggles | DONE | overlay_state.keepCompanion + companionAlwaysOnTop + panel_visibility.js (needs rc-shell relaunch) |
| E2 | DS 3-game live-flip eyeball pass (operator-played, live-gated) | OPEN | |
| E3 | End-of-game win capture (history/home W/L + season WR) | DONE | ad4c9906 |
| E4 | Counter-picks vs live enemy comp + ban-phase collapse | DONE | GET /api/champ-select/counter-picks + _csvBanPhaseComplete collapse |
| E5 | Laning hold-band recalibration (shadow vocabulary) | DONE | 4da01fbe |
| E6 | Spell flip-back fix + WR% under spells + highest-role-WR on lock + remember last-used per champ/mode | DONE | _sync_spells per-lock idempotency + manual-override + WR route |
| E7 | ARAM bench-swap responsiveness + LCU connection pooling (frozen lcu_client.py) | OPEN | |
| E8 | Design system: reduced-motion-done-right + status glyphs + threshold statusFor() | DONE | 19f8116f |
| E9 | Rank/tier/LP header + player scouting (both NOW) | DONE | core/lcu_ranked.py + routes_scouting.py; Riot key = API-Key-Riot.txt via core/riot_api.py |
| E10 | ASCII retro sweep (all files, frozen) + git-history rewrite + force-push | OPEN | |
| E11 | Hextech reskin across surfaces (P3/P4 visual cutover) | OPEN | |
| E12 | Responsiveness levers L1/L2/L4 (SSE/build TTL halve, etc.) | OPEN | |

TOTAL_stages = 62 (50 base + 12 E-batch).

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
| 2.5 | DELIVERABLE: docs/design/RC2_DESIGN.html (visual+text, multiple options) | DONE | GREENLIT 2026-06-20: theme=Hextech; replaces current design on P3/P4 |

### Phase 3 - OVERLAY + DASHBOARD QUICK-GLANCE (multi UI-agent)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 3.1 | In-game priority-info condensation spec (glance test) | DONE | docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md |
| 3.2 | Overlay UI-agent pass 1 (structure/density) | DONE | web/js/lib/overlay_priority.js (`39303acb`) + callout 2-row clamp (`db6f77d4`) |
| 3.3 | Overlay UI-agent pass 2 (typography/hit-targets/hierarchy) + wire right_now.js/overlay_pulse.js to shouldPulse (spec-flagged behavior change; shadow + 5-phase audit + operator eyeball) | LIVE | `87f41baf` shadow-wire (signalFromState + data-s0-* stamp) + 44px choice hit-target; pulse flip owed -> LIVE_GAME_GATED_SYNC.md |
| 3.4 | Dashboard STAYS when overlay active (currently disappears) - fix | DONE | `183f1969` (E1 `a61703ef` shell mechanism + web keepCompanion/pin toggles) |
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
| 6.2 | Faster champ-select LCU polling (all modes), port-safe | DONE | RuneWriter 2.0s->1.0s env-tunable; tests/test_runewriter_poll_interval_rc2.py |
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
| 8.1 | Massive operator-Q/A TODO + future list -> docs/RC2_TODO_QA.md | DONE | docs/RC2_TODO_QA.md (97 items, 9 sections, TOP-10 decisions) |
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

## FINDINGS LOG (RC2)

- **P3.4 SHIPPED** (`183f1969`): dashboard-persist toggles reachable from the overlay UI. The shell-side mechanism shipped under E1 (`a61703ef`): `overlay_state.windowActionsWithPolicy` + `keepCompanion` DEFAULT-TRUE (the disappear-bug fix - the companion window is kept SHOWN alongside the in-game overlay instead of hard-hidden) + `companionAlwaysOnTop` pin, consumed in `main.js` `applySurface` / `applyCompanionAlwaysOnTop`, round-tripped over the `rc-shell:overlay-settings:get/set` ipcMain bridge (81/81 shell node tests, incl. the windowActionsWithPolicy + overlaySettingsFrom keepCompanion/pin coverage in overlay_state.test.js). The RESIDUAL closed this cycle: the web helper `web/js/lib/overlay_settings.js` only carried `pulseNotify`/`activeRevertSec`, so a `keepCompanion`/`companionAlwaysOnTop` write from the dashboard was silently dropped in `_coerce`/`writeOverlaySettings` before it could reach the shell. Fix: (a) carry both booleans (defaults true) through DEFAULTS/_coerce/write; (b) add **Keep dashboard** + **Pin on top** toggles to the `#ovset` overlay settings strip (`overlay_ds_controls.js`, reuse `.ovset-row.ovset-toggle`, 42px hit floor, default checked) = no-hotkey control of persist+pin (operator north star). TDD: `tests/test_overlay_settings_rc2.py` (node ESM, RED-first 6 assertions) + a real-Chromium DOM assertion in `test_overlay_view.py` (controls present, default checked, ASCII labels, hit-target floor = the 5-phase audit as a durable check). Tier-1 web JS; NO ENGINE/DS/Share. Note: the rc-shell Electron main process still needs a relaunch to pick up E1's shell-side default (the web toggles + dashboard auto-reload via asset-hash). The Hextech reskin of the strip is E11.
- **P3.3 SHIPPED (LIVE; shadow slice)** (`87f41baf`): the typography/hit-target half + a SHADOW of the pulse-rationing wire. (a) `overlay_priority.js` gains `signalFromState(p, band)` - the one pure coach-envelope -> selectPrimary-signal mapping (band passthrough + choices detect + Phase-4 crossing-edge predicates `spike_crossed`/`objective_steal_now`/`lethal_incoming` default-false, honored if a producer ever sets them; spec section 9 Q1/Q2 stay deferred, no assumed surface). (b) `right_now.js` SHADOW consumer: each render computes `selectPrimary` + `shouldPulse` and stamps `data-s0-cue` / `data-s0-tier` / `data-s0-pulse` on `#right-now` WITHOUT touching the live `.action` per-band pulse (`right_now.js:490-500`) or `overlay_pulse.js`. (c) `overlay.css` section-7 floor: `#rn-choices .rc-chip` min-height 44px overlay-scoped (dashboard keeps `--hit-min` 42). 29/29 node logic + 13/13 overlay snapshot (real Chromium, screenshots = fixture audit). **OWED LIVE FLIP (operator-gated, NOT headless):** re-point the `.action` per-band pulse + `overlay_pulse.js` MutationObserver at this shadow decision (consume the stamped `data-s0-pulse` instead of firing on every text/content change) - a SHARED dashboard+overlay behavior change -> `docs/LIVE_GAME_GATED_SYNC.md`. The Hextech color-literal swap is E11 (the overlay already uses `--signal-*` tokens, so it inherits E11's global token cutover; pop-out discipline A2 is enforced structurally by the single-winner arbitration, not new literals).
- **P6.2 SHIPPED** (1011f47d): RuneWriter.POLL_INTERVAL 2.0s -> 1.0s (env RC_RUNEWRITER_POLL_SEC), port-safe. Applies on next RC restart. Remaining P6 levers (from io_timing_map): halve SSE+build TTL 1.0->0.5s together (S/LOW, touches state pipeline); pool one keep-alive LCU socket (M/MED, frozen grant). The dashboard champ-select render envelope (champ_select.js ~2s) is the UI-responsiveness lever for 6.3.
- **P7.1 ASCII warning** = `tools/edit_lint_check.py` (PostToolUse) + `tools/precommit_gate.py` scan 6 banned glyphs only: em-dash U+2014, en-dash U+2013, smart quotes U+2018/2019/201C/201D. Box-drawing / arrows / math are NOT banned (functional, leave them). Census: 53 em-dashes total, ALL in `_archive/2026-05-01-audit/**` (dead pre-1PC tkinter code) + `agents/agent6_auditor/reports/*.md` (generated weekly reports); ZERO smart quotes; the live authored tree is CLEAN. These dirs are normally sweep-excluded (immutable). FIX: strip em-dashes in those files (tools/strip_em_dashes.py) AND extend the hook `_FROZEN_SKIP` to root `_archive/` + agent6 reports so it never re-warns; OR delete the dead `_archive/2026-05-01-audit` in P7.2/7.3 (it is the "unused >1wk" target).
- **P3.2 SHIPPED (structure/density pass 1)**: (a) `web/js/lib/overlay_priority.js` (`39303acb`) - the pure-logic S0 arbitration primitive: `selectPrimary(state)` single-winner ladder (lethal 100 / objective_steal 90 / urgent_headline 85 / choices 80 / spike 70 / fight 60 / good 40 / none 0) + `shouldPulse(prevCue, sel)` motion rationing (Emergency tier or one-shot-Urgent {spike,choices} on a CUE CROSS only) + `BAND_TIER` map; dual ESM/CJS export (Node 22 require-of-ESM), 21/21 node-driven tests (`tests/test_overlay_priority_rc2.py`, pre-authored untracked, now GREEN). (b) callout 2-row density clamp (`db6f77d4`) - overlay-scoped CSS `#rn-callouts .rc-co-row:nth-child(n+3){display:none}` so the HUD S1 slot shows the 2 nearest-ETA rows (dashboard keeps all 3); +1 snapshot test. **NOT yet wired:** the primitive is not consumed by a rendered panel - re-pointing `right_now.js` `.action` pulse (currently fires all 3 bands on text change, `right_now.js:490-500`) + `overlay_pulse.js` to `shouldPulse` is the spec-flagged BEHAVIOR change, carried to **3.3** (shared dashboard+overlay render path -> needs shadow + the 5-phase UI audit + operator eyeball, not a blind headless flip). DOM slot reorder deferred (current order audited + close to spec S0>S1>S2>S3).
- **P3.1 SHIPPED**: `docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md`. Reframes the 460px dock as 1 PRIMARY (S0) + 3 SUPPORT (S1-S3) fixed slots with a 3-tier model (Ambient/Urgent/Emergency) mapped onto the existing `classifyAction()` bands (`right_now.js:472`: urgent->Emergency, fight->Urgent, good->Ambient). Adds a deterministic S0 single-winner arbitration (priority 100 lethal -> 0 empty) so exactly ONE pop-out exists at any tick, and NARROWS the pulse channel from every-band-on-text-change to Emergency + one-shot-Urgent-cross only (kills alarm fatigue). 3.2 OWNS new `web/js/lib/overlay_priority.js` (selectPrimary + tier map, TDD fixture table) + callout 2-row clamp; 3.3 OWNS Hextech color-bin bindings (#E84057 lethal reserved for the lone S0 Emergency; gold caution; cyan info; green good) + per-element glance acceptance bars + the 5-phase fixture audit at `?overlay=1`. Open: Q2 lethal-incoming predicate field (grep coach.fight_rule / liveclient hp before wiring), Q1 minimap-anchor projection deferred to P4.1.
- **P5 coaching** spec = `docs/research/RC2_COACHING_SPEC.md`. The laning Haiku-flip is blocked at 39% det-vs-Haiku agreement by CALIBRATION (precompute verdict vocabulary has no hold/farm band, back_off-biased), NOT games-played (`ops/audit/HZ_HAIKU_CALL_INVENTORY.md:49-108`). Top lever: hold-band + `even` relabel in `core/precomputed_laning_coach.py` `_VERDICT_LABELS` (Tier-1, shadow-logged, 39% -> ~53%+). Then CV overrides (new core/laning_cv_overrides.py reading data/vision_state.json) + objective playbook row.
