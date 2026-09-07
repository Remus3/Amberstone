---
description: Self-directed autonomous headless-upgrade loop, merged with the full 13-section orchestrator framework. Claude (read-only, --permission-mode plan) is DIRECTOR + AUDITOR; a Python controller (ops/loop/loop_controller.py) is the brain; an AutoHotkey v2 bridge types into THIS Claude window. Invoking this turns the CURRENT session into the ephemeral executor - AHK /clears it and feeds one director-authored directive per cycle. Continuity lives on disk (git history + docs/LEDGER.md + the directive chain). Each executor cycle natively runs the orchestrator-merge pattern (1 Claude merger + up to 100 parallel worktree agents on disjoint file sets + read-only verifier gate before merge), the section 3b UI-audit ritual, the section 4/4b cost + Haiku-to-ZERO program, the section 5/6 frozen-file grant + ASCII hygiene, section 7/7b multi-agent + deep-dive competitor research (6-point depth checklist), section 8-13 DS audit loop / interrupt / cadence / anti-patterns / done / banner, and the two-way escalation channel. Model + cycle cap in ops/loop/config.json. Proven end-to-end 2026-06-05.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

Invoking this command hands THIS Claude session over to the autonomous loop. After launch,
AHK will `/clear` this session and type one director-authored directive per cycle into it; the
loop's brains are the external Python + AHK processes plus read-only Claude calls, not this session. The
executor (each cleared cycle) reads `ops/loop/control/directive.md` and runs it under the full
framework in PART B + C below. Run PART A now, then STOP and end the turn.

================================================================================
PART A - LAUNCH SEQUENCE (this session, ONE time)
================================================================================

### A1. Pre-flight (abort if any check fails)
Run this and confirm all four are OK:
```powershell
"claude=$([bool](Get-Command claude -ErrorAction SilentlyContinue))"
"ahk=$(Test-Path 'C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe')"
$w=Get-Process claude -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowTitle}
"claude_windows=$(@($w).Count) (expect exactly 1 - this session)"
```
If `claude_windows` is not 1, tell the operator to close extra Claude windows first (AHK
targets the single window). If any check is false, report it and stop - do NOT launch. A live
adjudicator signal exists when `ops/loop/control/controller.log` shows a recent
`adjudicator=claude est=$<n>` line. There is no API key to check and no second vendor: since
2026-08-01 the director, the executor and the auditor are all Claude, authenticated from the
operator's own session.

### A2. Launch the loop (detached)
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\loop\launch_loop.ps1" -Mode live
```
This auto-detects the Claude window PID, writes `ops/loop/control/{target_pid.txt,ahk_mode.txt=live}`,
starts the AHK bridge + the controller (config.json), and pre-cleans stale sentinels (incl. a
stale STOP from a prior `max_cycles reached`).

### A3. Confirm + yield
- Read `ops/loop/control/controller.log` tail; confirm a fresh `loop start dry_run=False` line.
- Print a one-line banner: ceiling, max_cycles, and the abort path (drop `ops/loop/control/STOP`).
- Then STOP. Take no further actions. Within ~45s the controller finishes the first
  director call, AHK types `/clear` + the directive into THIS window, and the loop runs.

================================================================================
PART B - PER-CYCLE EXECUTOR FRAMEWORK (every cleared directive runs ALL of this)
================================================================================
Canonical long-form: `.claude/commands/headless-upgrade.md`. Run sections in order. Full
authority, no mid-run user gating; the operator is away - make the reasonable default, log it,
proceed. Caveman ULTRA output default (compress ~90 percent; code/paths/numbers byte-exact).

### 1. Pre-flight baseline (FIRST, every cycle)
- Read CLAUDE.md Active priorities + the "Settled - do not re-litigate" section + MEMORY.md
  index + ROADMAP.md top 80 + BACKLOG.md headings + recent 15 commits.
- Probe live state: `ops/runtime/health.json`, `https://127.0.0.1:8888/api/state`,
  `http://127.0.0.1:8860/health` (DS engine_version; HTTP not HTTPS).
- DS stale vs repo `agents/daemon_slayer/__init__.py` ENGINE_VERSION -> bounce DS:
  `taskkill /F /PID <ds-pid>` then `schtasks /Run /TN RC-DaemonSlayer` (DS not supervisor-watched;
  NEVER Stop-Process).
- Git hygiene: `gh run list --limit 6` green baseline (fix red FIRST); `gh pr list` reconcile;
  delete stale merged remote branches; clean stale local worktrees (verify 0 unmerged first,
  unlock + remove --force + prune + branch -D).
- Write/refresh `C:/Users/Administrator/Desktop/RC_HEADLESS_SYNOPSIS_<YYYY-MM-DD>.md` (atomic).
- TaskCreate per phase. Init/resume the slice manifest:
  `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/slice_orchestrator.py init --run-id <YYYY-MM-DD-NN> --head <sha>` then `add` per slice;
  a prior manifest with non-committed slices = RESUME (skip committed, re-verify rest).

### 2. Orchestrator-merge pattern (core framing)
- ONE Claude is the orchestrator + the ONLY merger. Dispatch up to 100 worktree agents in
  parallel per task, each ONE slice on a DISJOINT file set. Dispatch concurrent agents in a
  SINGLE message with multiple Agent blocks (true concurrency).
- Merge order: engine / ENGINE_VERSION-bump slice FIRST, then dependents, living-docs sync LAST.
  Merge via `git -C "C:/Riot Commander" merge --no-ff origin/<branch>` (CWD hazard item 156).
- VERIFIER GATE before any merge (ground truth, not the slice agent's word): dispatch the
  read-only `verifier` subagent with the claim + cited test cmd + cited files. Merge only on
  CONFIRM; on REFUTE mark `failed` + re-dispatch - never merge a refuted slice.
- TRUTH-GATE (mechanized, insights 2026-06-10): final pre-commit reconciliation of a multi-slice
  round = `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/truth_gate.py --claims <claims.json>` (fresh suite to file, content-level
  claimed-edit re-read via must_contain, gh CI probe, atomic report to
  ops/runtime/truth_gate_report.json). Exit 2 = commit BLOCKED + `quarantined` slices re-dispatch.
- Checkpoint each slice in the manifest (in_progress -> verified -> committed --commit <sha>).
- Bug/data slices follow `root-cause-fix` (failing repro first, sibling sweep, backfill).
- After ALL merges: full relevant test gate, restart as needed, ONE surgical living-docs commit.

### 3. Phase loop discipline (after EVERY phase)
1. Lint: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m py_compile <touched>`; any .py edited -> `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m ruff check .` (F541 is the common CI-killer).
2. Test gate green BEFORE commit: DS `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest agents/daemon_slayer/tests/ -q`; RC
   `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest tests/ --ignore=tests/daemon_slayer -q`; snapshots `tests/snapshot_panels/`.
3. Restart-aware: routes -> `echo restart > restart_trigger.txt` + confirm health alive/last_reload_ok;
   engine math -> taskkill DS + `schtasks /Run /TN RC-DaemonSlayer`; web/css|js/panels/* -> asset-hash
   auto-reload (ADR-008), no RC restart - say so.
4. Commit + push - HARD PRE-COMMIT GATES (no push until ALL pass): (a) frontend slice -> 3b
   UI-audit RUN + every MUST-FIX resolved in-slice; (b) drift-guard set green THIS run
   (bundle-parity + ASCII/u2500 + touched guards); (c) multi-slice round ->
   truth_gate exit 0. Then: NO `git add -A`; stage only authored files; unstage `_scratch/` + stray
   `.playwright-mcp/*.png`; heredoc message; use the harness-supplied Co-Authored-By trailer (do
   NOT hardcode a model version).
5. CI after push: `gh run list --limit 4`; red -> FIX before next phase.
6. Synopsis row update (atomic). 7. TaskUpdate phase completed; next in_progress.

### 3b. Frontend slice: visual proof + UI-audit ritual (HARD PRE-COMMIT GATE)
Any slice shipping a frontend change (web/css|js/panels/*, index.html, new panel/view) is NOT
done - and MUST NOT commit/push - until it has BOTH a visual capture AND a spec-conformance audit.
1. Visual proof: after asset-hash reload, capture the ELECTRON OVERLAY on Legion (the Chrome
   :8888 dashboard is RETIRED as a viewing/audit surface per the 2026-06-27 overlay-only directive -
   overlay ONLY). Capture the rc-shell Electron overlay window over League (desktop screenshot), or
   GET `https://127.0.0.1:8889/latest-frame` for the in-game frame, or drive
   `https://legion-rc:8888/?overlay=1` (the overlay render off live /api/state) + capture. Do NOT
   screenshot a Chrome dashboard window.
2. UI-audit agent (5-phase ritual; returns MUST-FIX / SHOULD-FIX / NICE-TO-HAVE):
   - STRUCTURE - panel/grid matches intended layout.
   - TYPOGRAPHY - all declarations on `docs/UI_SCALE_SPEC_V2.md` v2.1 tokens; no hardcoded px below
     `--fs-xs` (16) unless a documented operator-exception with inline rationale.
   - HIT-TARGETS - clickables meet `--hit-min` (42px).
   - ASCII - 0 non-ASCII bytes introduced (no em/en/smart quotes).
   - HIERARCHY - readable at 1920x1080 baseline without scroll.
   Fix every MUST-FIX in the SAME slice before merge; log SHOULD/NICE as FUTURE.
3. If the Legion capture path is unavailable (no live frame at :8889 and no desktop screenshot
   access): the code-side audit still runs; the visual capture is OWED - log it as carry-forward in
   WAKEUP_NOTES + synopsis. Do NOT silently skip and do NOT block the run on it.

### 4. Cost/latency reorientation (SECONDARY objective)
Sweep these 7 levers each run; ship a fix only when net-positive AND tests green, else record CLEAN
no-commit with evidence. Never trade product fidelity for cost.
1. Prompt-cache `cache_control` coverage on every `messages.create()` caller.
2. Route TTL `_CACHE` constants on hot dashboard routes.
3. Polling cadences - no sub-500ms network polls.
4. Log spam - `_SUPPRESS_LOG_PATHS` keeps paths under ~1/sec (bare prefixes; trailing space fails - item 171).
5. Model tier - haiku is the INTERIM floor for any live-call surface, NOT the end state (section 4b retires each);
   Sonnet/Opus only where charter requires (agent6 auditor, vision).
6. Scheduled-task catalog - no orphans. 7. Bundle parity - panel CSS count == `dashboard.css` @imports.

### 4b. Haiku-elimination program (PRIMARY north star)
Goal = ZERO live Haiku calls. Migrate each coaching surface to a precomputed DS pattern read at
request time. Live sites to retire: `coaches/{aram,arena,brawl,champ_select,replay,experimental_builder,aram_team_analyzer}_coach.py`,
`coach_integration/_coach.py`, `tft/{tft_coach_engine,tft_live_analysis,tft_pbe_engine,tft_vision_reader}.py`,
`dashboard/_champ_select.py` (agent6 auditor + vision Sonnet are charter-exempt). Advance via PARALLEL
orchestrator lanes (concurrent, disjoint file sets):
- Lane A - combat-trigger scenario precompute (laning): DS substrate (`scenario_matrix.py` + `combo.py`
  + `mana_sim.py` + `fight_report.py`) -> trade/all-in/back-off/recall/cooldown/spike verdicts across
  (matchup x level x item x cooldown x mana); persist as lookup tables the coach reads instead of Haiku.
- Lane B - item-usage-metric -> optimal prebuilt build orders: search EVERY metric source (Meraki bulk
  `aram_modifiers` + passive formulas, `agents/daemon_slayer/rank.py`, `core/build_order.py`, curated
  loadouts, lolmath wiki) -> precompute build orders per (champ x mode x enemy-comp).
- Lane C - A+B coaching direction: shift coach output to the deterministic `coach.choices` A/B chip
  surface (#rn-immediate; native emit live in aram/arena/brawl/sr), driven by Lane A/B tables.
  STATUS 2026-07-06: the det-choices templater lever is CODE-COMPLETE for ARAM (all 5 labels,
  LEDGER 775/777/790/801) AND Arena (`_ARENA_CHOICE_LABELS`, this session - build_block 8th `choices`
  key + arena shadow carries it on both columns). Both blocks assemble Haiku-free. Do NOT re-pitch a
  choices templater - it is done for ARAM + Arena. Every det-choices FLIP is live-gated: needs shadow
  accrual (arena is awaiting_accrual 0/20) + the tools/{aram,arena}_shadow_report.py >=70% action gate
  + operator flip auth. The genuinely-unbuilt NEXT NO-LLM target is Lane E (the SECOND program).
- Lane E - client-side CV vision atlas (the bigger SECOND program; `docs/OBS_CV_MINIMAP_PLAN.md` +
  `docs/NO_LLM_PRECOMPUTE_PLAN.md`): replace the vision-Haiku/Sonnet escalation with a deterministic
  template-match tier (DDragon icons mirrored locally) + the OCR-first tier + a confidence-weighted
  PARTIAL-READ fusion of the Live Client API (high trust) and CV reads. Prereq VISION-OCR hardening is
  in flight (ROADMAP; `/vision-calibrator` + native-res crops). This is where NO-LLM cycles route now.
- Lane D - overlay switch-up + UI lift + agent: advance the Electron overlay (`rc-shell/`;
  `docs/ELECTRON_OVERLAY.md` Phases 2+), Vanguard-safe (DWM window, NO DXGI capture, Borderless).
Retiring a site is "done" only when its precompute is validated against a real/replayed game; a WRONG
precompute is worse than a Haiku call - do not flip blind (haiku stays as interim floor until validated).

### 5. Frozen-file edits under this run's grant
- Operator-authorized for the CURRENT run ONLY; do NOT carry forward (items 108 + 99).
- Route AROUND when possible (a single import line in main.py to wire a non-frozen module is fine;
  rewriting `_loop.py` is a separate session).
- Every frozen-file commit body notes "frozen-file edit under operator's headless-upgrade grant".
- Frozen list is authoritative at the TOP of CLAUDE.md (main.py, core/log_setup.py, core/moon_proxy.py,
  lcu/lcu_client.py, core/game_snapshot.py, ops/rc_dev_runtime.py, ops/rc_supervisor.py, app/__init__.py,
  app/_loop.py, app/_health_monitor.py, app/_remediation.py, app/_state_authority.py, app/_overlay_manager.py,
  app/_game_lifecycle.py, tools/diagnose.md, tools/caveman.md). `app/__init__.py` SCRIPT_DIR MUST stay
  `Path(__file__).parent.parent`. Re-read CLAUDE.md rather than trusting this copy - the bridge entries
  (tools/bridge_watcher_*, tools/bridge_post_result.py, tools/bridge_pull_tasks.py, tools/process-bridge-tasks.md,
  dashboard/routes_bridge_pending.py, ops/RC-BridgeWatcher.xml) were listed here until 2026-08-16 and were
  never on CLAUDE.md's list; all six paths were deleted with the bridge decommission (ADR-012, 2026-06-24)
  and verified absent from disk.

### 6. ASCII hygiene (hard rule)
- No em-dash, en-dash, or smart quotes anywhere (.py/.md/.ps1/.css/.js/commit/chat). ` - ` for a clause
  break, `-` otherwise. The `"-"` no-data sentinel in dashboard rendering is operator-approved + stays.
- The /done gate runs `tests/test_smart_quote_hygiene.py tests/test_mojibake_hygiene.py
  tests/test_u2500_hygiene.py`; drift fix = `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/strip_smart_quotes.py --apply`.

### 7. Multi-agent dispatch rules
- Up to 100 concurrent worktree agents per task, disjoint file sets. Each agent prompt MUST carry the
  don't-redo set (CLAUDE.md "Settled" + docs/history_notes.md) so it never re-researches closed topics.
- Agents return TRIAGED NOW/FUTURE/CLOSED with reasons; synthesize NOW into BACKLOG + issues, do NOT
  auto-implement everything. Verify agent premises against live data. Subagent files (esp. tests) MUST
  pass `ruff` before the agent reports done.

### 7b. Deep-dive competitor research (depth bar - NOT superficial)
A "lift from competitor X" task is a TRUE teardown: name the actual mechanic + math/data + RC
integration point. Prefer DEPTH (one heavyweight `general-purpose` agent per target) over breadth.
Tooling allowance (NOT subject to section 4 runtime budget; load deferred MCP via ToolSearch first): Chrome
DevTools MCP / Claude-in-Chrome (render live, evaluate_script, capture XHR), Firecrawl, nimble
competitor-intel/positioning/deep-dive, Playwright MCP, Windows MCP / computer-use for a desktop app,
WebFetch/WebSearch/deep-research. Run/parse competitor binaries in an isolated Legion workspace (a
temp dir / disposable worktree); clean up artifacts. Illustrative not a whitelist; bounds = lawful +
authorized (public sites or operator machines) + non-destructive + secrets/frozen rules hold.
Depth checklist - every finding answers ALL six:
1. WHAT - the specific mechanic/UX/math (algorithm, interaction, data shape, network call).
2. HOW - under the hood (captured XHR payload, formula, state machine, render).
3. HAVE - does RC already do this? grep RC + cite the file.
4. WHERE - concrete RC integration point: file/module + layer (engine math vs route vs panel JS).
5. EFFORT + RISK - new data / Riot or Claude dependency / schema lift, or presentation-only over DS math.
6. LIFT verdict - HIGH/MED/LOW + reason.
Lift legally: re-implement in RC's own code (never vendor unlicensed competitor code; KebsCS reference-only).
Output `docs/COMPETITOR_LIFT_<YYYY-MM-DD>.md`. Then ACT: a HIGH-lift that is low-risk (presentation over
existing DS math, no new dependency/schema lift, testable) ships IN-RUN as its own slice (+section 3b proof if
UI). A HIGH-lift with new dependency / schema lift / product-direction call -> BACKLOG + issue (FUTURE),
not built blind. MED/LOW always defer.

### 8. DS audit iteration loop
- DS schema lifts run as PARALLEL slices (section 2), prioritizing lifts that unblock section 4b Lane A/Lane B.
- Stop rule: 11 consecutive no-change iterations. Source of truth: Meraki bulk (`/items.json`,
  `/items_meraki.json`, champion `aram_modifiers`) - never aggregator D/aggregator A.
  **CARVE-OUT, measured 16.15.1 (2026-08-08): Meraki is NOT the source for item PEN / LETHALITY /
  resist-reduction MAGNITUDES** - those live ONLY in the DDragon `<stats>` description block.
  Meraki carries 320 items against DDragon's 706 canonical, ZERO rows carry a `stats` key, and
  228005 is absent entirely, so auditing a magnitude against Meraki manufactures PHANTOM mismatches
  (7 of them in one slice). Meraki REMAINS correct for `aram_modifiers` + item PASSIVE FORMULAS -
  but read the WHOLE row: a passive can sit under `active` rather than `passives` (223069 does).
- Each iteration touches ONE math lane and either ships an ENGINE_VERSION bump + tests, or records
  "no-change" with reasoning. After each bump: sync ENGINE_VERSION pins across DS tests + bounce DS.
  Prefer parametrized property-style tests (invariants over exact values).

### 9. Interrupt protocol (no verbatim phrase match)
- ANY operator message during the run = interrupt. STOP starting new phases, FINISH the in-flight
  slice (never abandon a half-merged state), then run `/done`. A plain question -> answer in caveman
  ULTRA and resume; ambiguous question-vs-stop -> treat as stop-and-wrap.
- Mid-critical-path (mid-restart, mid-merge) -> finish the critical path FIRST, then handle.
- See PART C for the escalation channel (replaces a blocking AskUserQuestion).

### 10. Headless cadence health
- Desktop synopsis: update every phase complete (atomic); never delete mid-run.
- Living docs (CLAUDE.md item N+1, ROADMAP, BACKLOG, WAKEUP_NOTES, docs/DAEMON_SLAYER.md): synced at
  run END as ONE surgical commit. WAKEUP prune: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" scripts/wakeup_prune.py --keep 3`.
- Worktree cleanup at run END (remove merged + prune + branch -D). 10h+ -> transition to a full RC
  refactor audit (frozen edits still allowed; tests required). Caveman ULTRA token discipline.

### 11. The /done ritual at run end
Run `/done` (existing skill - local check gate, auto-commit + push, CI verify, bg-task stop, bridge
liveness, WAKEUP update + prune, living-doc sync, lessons drain, banner). If this run touched DS or its
components (any path under `agents/daemon_slayer/`, `tools/daemon_slayer_*`, `tools/ds_*`,
`data/daemon_slayer/`) - ESPECIALLY after any ENGINE_VERSION bump or math change - credit the upstream
sources (Riot Data Dragon / CommunityDragon / Meraki) in the commit body, and confirm CI green for the SHA.

### 12. Anti-patterns (do NOT repeat)
No `git add -A` without unstaging `_scratch/`; no skipping `ruff check` (F541 kills CI); no `--amend`;
no `Stop-Process` (use taskkill /F /PID); no uncleaned locked worktrees at run end; no hardcoded model
trailer; no trusting an agent premise unverified; no research agent without a don't-redo list; no skipped
asset-hash reload mention; no feature flags / backwards-compat shims for what should just BE the new
behavior; no WHAT-comments (WHY only); no blocking AskUserQuestion mid-run (use PART C); no frontend
slice marked done without section 3b visual capture + UI-audit (or an explicit OWED carry-forward).

### 13. Final banner (on interrupt or empty queue), then call /done
```
HEADLESS UPGRADE WRAP
  HEAD: <short-sha> (<N> commits this run)
  ENGINE: <old> -> <new>
  DS: <N> tests / <N> subtests
  RC: <N> tests
  CI: <N>/<N> green (<N> red)
  cost/latency: <N levers swept, M shipped | all CLEAN>
  ui proof: <N pages captured + audited, M owed | n/a>
  worktrees: <cleaned N | none>
  Synopsis: C:/Users/Administrator/Desktop/RC_HEADLESS_SYNOPSIS_<date>.md
  Ready for /done.
```

================================================================================
PART C - ESCALATION CHANNEL (replaces a blocking AskUserQuestion)
================================================================================
The operator is away; NEVER block on AskUserQuestion. When you need a scope decision, hit an
architectural roadblock, or need ROADMAP/BACKLOG reshaped mid-run, escalate to the DIRECTOR. The
director is READ-ONLY - it DECIDES and DIRECTS; the next executor cycle does every file write. Do
not claim the director "physically implements" anything.

The synchronous side-channel that used to sit here was a second-vendor wrapper script, deleted
2026-08-01 with that vendor, and deliberately NOT replaced. Asking the same model you already are,
in a separate one-shot with no repo context, is not a second opinion - it is a slower way to ask
yourself. Resolve what you can mid-cycle on your own judgement, log the choice in the synopsis +
WAKEUP_NOTES, and PROCEED. Escalate only a TRUE blocker, below.

DURABLE hand-off (for a TRUE blocker that should end the cycle and reshape the next directive):
   - Atomic-write the findings + context + the explicit question to `ops/loop/control/gemini_ask.txt`
     (tmp + os.replace; plain ASCII).
   - Finish the in-flight slice (never a half-merged state), then run the FINAL STEP
     `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" ops/loop/done_sentinel.py --tests <N> --regressions <0|1>` to end the cycle cleanly.
   - The controller consumes `gemini_ask.txt` into the NEXT director call under an `EXECUTOR ESCALATION`
     header (consume-once). That filename is legacy and keeps its name on purpose - renaming a control
     file that appears across append-only history buys nothing. The DIRECTOR resolves it and emits the next directive that encodes the
     decision + instructs the scaffolding + any ROADMAP.md / BACKLOG.md reshape. The per-cycle `/done` +
     `/clear` already run automatically, so continuity is preserved on disk.
   - If you cannot safely proceed AND cannot end the cycle, default to the safest reversible option, log
     it loudly, and record the decision as a FUTURE item - a genuinely operator-only call becomes a
     BACKLOG entry, not a hang.

================================================================================
PART D - LOOP BEHAVIOR / STOP CONDITIONS / TUNING (controller-driven, automatic)
================================================================================

### Per cycle (all automatic)
- The DIRECTOR reads git log + docs/LEDGER.md + ROADMAP + last result (+ any EXECUTOR ESCALATION) ->
  writes one orchestrator-pattern directive (TDD, parallel disjoint slices, Claude sole merger,
  verifier-gate each slice, commit-local, no AskUserQuestion, ends with the done_sentinel FINAL STEP).
- AHK types `/clear` + "read+execute ops/loop/control/directive.md" into this window.
- The executor (this session) runs PART B + C, commits locally, runs
  `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" ops/loop/done_sentinel.py --tests <N> --regressions <0|1>` -> writes control/claude.done.
- Controller meters spend from the pinned executor JSONL, then the AUDITOR scores the diff. CLEAN -> next
  item; REGRESS (or self-reported regressions) -> next directive is FIX-FIRST.

### Stop conditions (any one writes control/STOP; AHK + controller exit)
- NO spend stop condition. The ceiling was a rail on the retired metered vendor and was removed
  2026-08-01 with it; all spend is now Claude spend, which operator policy leaves UNCAPPED, so
  max_cycles and cycle_deadline_sec are the only limiters.
- directive absent / the director returns NO_WORK; claude.done not seen within cycle_deadline_sec (hang);
  2 consecutive cycles with the same git sha (no progress); max_cycles reached; operator drops
  `ops/loop/control/STOP` by hand (instant abort).

### Tuning (operator edits ops/loop/config.json)
`max_cycles`, `cycle_deadline_sec`, `claude_adjudicator`, `clear_each_cycle`, `directive_suffix`
(e.g. allow push). Dry-test the plumbing with no spend:
`launch_loop.ps1 -Mode dry` (uses config.dry.json + claude_stub.py).
