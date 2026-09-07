---
description: Headless autonomous-run skill. Folds in /done /clear /continue /compact /memory /audit /test /iterate /new-tech. Full authority, no mid-run user gating (long 100 percent acceptance track record). Orchestrator pattern - one Claude merges; up to 100 worktree agents in parallel per task. Caveman ULTRA default. PRIMARY north star - drive live Haiku usage to ZERO by precomputing coaching from parallel DS combat-trigger scenario tables (laning trade/all-in/spike) + optimal metric-backed prebuilt build orders + the A+B deterministic-choice coach direction, plus the in-game overlay switch-up + UI lift + agent; runtime cost/latency is the SECONDARY sweep. Hard-coded with the durable don't-redo set, interrupt protocol, worktree cleanup, and the Desktop synopsis heartbeat.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

The operator has authorized a long unattended autonomous run with:
- Frozen-file edits allowed (the grant is for THIS run only; do NOT carry forward into later sessions).
- RC-wide test coverage at every stage gate.
- Orchestrator multi-agent dispatch: one Claude is the merger; up to 100 worktree agents run in parallel per task, partitioned to disjoint file sets.
- A standing PRIMARY objective: drive live Haiku usage to ZERO. Migrate coaching off live LLM calls onto precomputed DS patterns - parallel combat-trigger scenario tables for laning + optimal metric-backed prebuilt build orders + the A+B deterministic-choice coach direction + the overlay switch-up/UI lift. Every run advances this program (section 4b).
- A standing SECONDARY objective: find runtime cost/latency savings WITHOUT degrading the product (section 4).
- A living synopsis maintained atomically on the Legion Desktop.
- Full authority - no mid-run user gating. The operator is away; make the reasonable default, log it, proceed.
- Full computer access + open tool usage: any connected MCP server, CLI, skill, or fleet machine may be used when it serves a legitimate, lawful, non-destructive task. The tool lists in this skill are illustrative, NOT a whitelist - load deferred tools via ToolSearch and reach for whatever fits.
- Interrupt protocol: ANY operator entry during the run = interrupt signal (not a verbatim phrase match). Finish the in-flight slice, then run /done.

This skill is the durable record of how to run that loop cleanly. Run sections in order.

### 1. Pre-flight baseline (do this FIRST, every time)

- Read `CLAUDE.md` Active priorities + the "Settled - do not re-litigate" section + `MEMORY.md` index + `ROADMAP.md` top 80 lines + `BACKLOG.md` headings + recent 15 commits.
- Probe live state: `ops/runtime/health.json` (pid, alive, last_reload_ok), `https://127.0.0.1:8888/api/state` (RC), `http://127.0.0.1:8860/health` (DS engine_version; note it is HTTP not HTTPS).
- If DS engine_version is stale vs the repo `agents/daemon_slayer/__init__.py` ENGINE_VERSION constant, bounce DS: `taskkill /F /PID <ds-pid>` then `schtasks /Run /TN RC-DaemonSlayer`. DS is NOT supervisor-watched (per reference_ds_server_not_supervisor_watched). NEVER `Stop-Process` (CLAUDE.md hard rule).
- Git hygiene before any new work:
  - `gh run list --limit 6` - baseline must be green; if a recent push is red, fix the red FIRST.
  - `gh pr list` - reconcile/close any open PRs.
  - Delete stale remote branches that are fully merged: a branch is safe to drop when `git log origin/main..origin/<branch>` is empty. `git push origin --delete <branch>`.
  - Clean stale local worktrees left by prior orchestrator runs (they accrete and bloat disk - one run reached 7.3G across 49 locked worktrees). Verify 0 unmerged first (`git branch --no-merged main`), then `git worktree unlock` + `git worktree remove --force` each, `git worktree prune`, and `git branch -D` the merged worktree/slice branches.
- Write the initial synopsis to `C:/Users/Administrator/Desktop/RC_HEADLESS_SYNOPSIS_<YYYY-MM-DD>.md` (atomic Write). Header carries: HEAD sha, ENGINE_VERSION, DS test count, RC test count, CI status, item count, scope, stop rules, phase log table.
- Read the operator's own Desktop continue-notes (`RC RC Continue - N.txt` and siblings) before choosing the run's scope - they carry the operator's stated next task and its do-not-redo set, and they are frequently a better pick than a ROADMAP row. **Adjudicate them against ground truth rather than obeying them:** several have been measured STALE (their task already shipped), and a stale note that is executed manufactures work. Say in the synopsis which you probed and what you found.
- TaskCreate for each phase in the run so progress is visible.
- Init the resumable slice manifest so a crash (API 400 / socket drop / cascade-cancel) never wipes the run: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/slice_orchestrator.py init --run-id <YYYY-MM-DD-NN> --head <sha>`, then `add` one entry per planned slice. The manifest at `ops/runtime/slice_manifest.json` is the durable checkpoint; on a relaunch `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/slice_orchestrator.py resume` lists only the non-committed slices to redo. The wrapper `tools/headless_run.ps1` automates relaunch-on-crash + this resume handoff.
- If a prior manifest already exists with non-committed slices, this is a RESUME: skip the committed ones, re-verify the rest against ground truth, continue from there - do NOT re-init over it.

### 2. Orchestrator-merge pattern (the core framing)

- ONE Claude is the orchestrator and the only merger. Dispatch up to 100 worktree agents in parallel per task, each owning ONE slice partitioned to a DISJOINT file set so branches merge without conflict.
- Dispatch concurrent agents in a SINGLE message with multiple Agent tool blocks (operator's "parallel" instruction = true concurrency, not sequential).
- Each agent returns its branch (commit-bearing) or a verdict (read-only audit slices return NOW/FUTURE/CLOSED triage, not commits).
- Merge order matters: the engine / ENGINE_VERSION-bump slice merges FIRST, then dependent slices, then the living-docs sync commit LAST.
- Merge via `git merge --no-ff origin/<branch>` from the repo ROOT.
- CWD HAZARD (item 156): the shell CWD persists between Bash calls. Run `cd "C:/Riot Commander"` before each `git merge`, or use `git -C "C:/Riot Commander" merge ...`. A merge fired from a worktree dir lands on the wrong branch.
- **Verifier gate before any merge (ground truth, not the slice agent's word).** A slice agent's "green: N tests pass" is a CLAIM, not a fact - the pipe replays stale results and agents have cited non-existent test files (item 238). Before merging a slice, dispatch the read-only `verifier` subagent (`Agent` tool, `subagent_type: "verifier"`) with the claim + the cited test command + the cited files. It re-runs the suite fresh, confirms the cited files exist, cross-checks counts, and returns CONFIRM or REFUTE. Merge only on CONFIRM; on REFUTE re-dispatch the slice (mark it `failed` in the manifest) - never merge a refuted slice. The verifier has no Edit/Write tools so it cannot mutate anything; it only reports. **Truth-gate (mechanized layer, insights 2026-06-10):** for the FINAL pre-commit reconciliation of a multi-slice round, the verifier (or merger) runs `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/truth_gate.py --claims <claims.json>` - it re-runs the real suite to a file (stale-pipe-proof), re-reads every claimed file and confirms the claimed CONTENT is present (`must_contain` snippets, not just existence), probes CI for HEAD via `gh run list --commit`, and writes `ops/runtime/truth_gate_report.json` atomically. Exit 2 = REFUSE: commit is BLOCKED, `quarantined` lists the slices to re-dispatch with their discrepancy lines as added context. Exit 0 = PROCEED.
- **Checkpoint each slice in the manifest as it advances**: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/slice_orchestrator.py set --id <S> --status in_progress` when dispatched, `--status verified` after the verifier CONFIRMs, `--status committed --commit <sha>` after the merge + push land. A crash after a committed mark means that slice is durable and is skipped on resume.
- Bug-fix or data/pollution slices follow the `root-cause-fix` skill (failing repro first, sibling-case sweep, corrupted-row backfill) so a narrow first fix does not force a second pass (items 208 -> 213, 211).
- After ALL merges land: run the full relevant test gate, restart as needed, then a single surgical living-docs sync commit.

### 3. Phase loop discipline

Each phase/slice is one focused vertical slice. After EVERY phase:

1. **Lint locally before push**: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m py_compile <touched files>`; if any Python file was edited, also `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m ruff check .`. F541 (f-string no placeholder) is the most common CI-killer; catch it locally.
2. **Test gate**: run the relevant test subset green BEFORE committing. DS engine: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest agents/daemon_slayer/tests/ -q` (from the REPO ROOT - running it from inside the DS dir produces ~13 bogus CWD failures). RC backend: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest tests/ -q`. Frontend snapshots: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest tests/snapshot_panels/ -q`.
   **`tests/daemon_slayer` DOES NOT EXIST** (measured 2026-08-04) - the DS suite lives ONLY at `agents/daemon_slayer/tests` (419 files). Any `--ignore=tests/daemon_slayer` you see in an older doc is a harmless no-op, but the inverse bites: `pytest tests/daemon_slayer` silently collects nothing and exits 5 with "no tests ran", which is easy to misread as a green DS run. Check the collected count, not just the exit code.
   **Under parallel-slice contention, `-n 8` wedges.** Measured this run: five concurrent pytest processes deadlock with byte-identical worker CPU over 10 minutes, and xdist dies with `INTERNALERROR: Unexpectedly no active workers`. `-n 4 --timeout=300` completed both suites reliably at 24-35 live python processes - prefer it whenever other agents are running.
3. **Restart-aware**: editing dashboard routes -> `echo restart > restart_trigger.txt` then confirm health.json alive + last_reload_ok; editing engine math (`_effects_*.py` etc) -> `taskkill /F /PID <ds-pid>` + `schtasks /Run /TN RC-DaemonSlayer`; editing web/css|js/panels/* -> auto-reload via `compute_asset_hash` (ADR-008), no RC restart - say so in chat.
4. **Commit + push - HARD PRE-COMMIT GATES (insights 2026-06-10; no commit may push until ALL pass)**: (a) frontend slice -> the 3b UI-audit subagent has RUN and every MUST-FIX is resolved in-slice (page #8 shipped pre-audit once; never again); (b) the drift-guard set is green in THIS run's output (bundle-parity + ASCII/u2500 hygiene + any guard the slice touches); (c) multi-slice rounds -> `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/truth_gate.py --claims <claims.json>` exited 0 (PROCEED) - exit 2 blocks the commit and quarantines slices for re-dispatch. Then: do NOT `git add -A`; explicitly stage only the files you authored. Unstage `_scratch/` and any stray `.playwright-mcp/*.png`. Write the commit message via heredoc. Use the standard Co-Authored-By trailer the harness footer supplies for the current model - do NOT hardcode a model version in the skill.
5. **CI check after push**: `gh run list --limit 4`. If the just-pushed run goes red, FIX before starting the next phase. Pausing to fix < compounding broken state.
6. **Synopsis sync**: update the Desktop synopsis table row for the phase with status + short-SHA (atomic Write).
7. **TaskUpdate** to mark the phase completed; set the next phase in_progress.

### 3b. Frontend slice: visual proof + UI-audit agent (per the UI-audit ritual)

HARD PRE-COMMIT GATE: any slice that ships a frontend change (web/css|js/panels/*, index.html, a new panel or view) is NOT done - and MUST NOT commit/push - until it has BOTH a visual capture AND a spec-conformance audit. Tests + asset-hash reload prove the code loads; they do not prove the render is correct or on-spec.

1. **Visual proof (Legion capture)**: after the asset-hash auto-reload, capture the rendered page on Legion - the dashboard runs ON Legion now. Use a Legion desktop screenshot of the Chrome dashboard window (or GET `https://127.0.0.1:8889/latest-frame` for a live-game frame). For a page that needs data, drive it with the mock fixture: navigate Chrome to `https://legion-rc:8888/?ui_mock=1#<view>` (add `&mode=aram|arena` where the page is mode-specific), hard-reload Ctrl+Shift+R, then capture. Attach the capture as the slice's visual proof.
2. **UI-audit agent (keep within spec)**: dispatch an Explore/audit subagent to check the shipped surface against spec per feedback_phase3_fixture_ritual. It runs the 5-phase ritual and returns MUST-FIX / SHOULD-FIX / NICE-TO-HAVE:
   - STRUCTURE - panel/grid matches the intended layout
   - TYPOGRAPHY - all declarations on `docs/UI_SCALE_SPEC_V2.md` v2.1 tokens; no hardcoded sub-floor px below `--fs-xs` (16) unless a documented operator-exception carrying an inline rationale comment
   - HIT-TARGETS - clickables meet `--hit-min` (42px)
   - ASCII - 0 non-ASCII bytes introduced (no em/en/smart quotes)
   - HIERARCHY - readable at the 1920x1080 baseline without scroll
   Fix every MUST-FIX in the SAME slice before merge; log SHOULD/NICE as FUTURE.
3. **If the Legion capture path is unavailable** (no live frame at :8889 and no desktop screenshot access): the UI-audit still runs (it is code-side), but the visual capture is OWED. Log it explicitly as a carry-forward in WAKEUP_NOTES + the synopsis ("visual capture owed for page <X>"); do NOT silently skip it and do NOT block the run on it.

### 3c. UI/UX deep-dive checklist (per page when touched)

Beyond LoL when warranted. Research lift sources: Linear, Vercel, Figma, Apple HIG, Material 3, Carbon, Radix, Stripe Docs - methodology only, do NOT vendor.

- **Layout**: 8px grid; consistent paddings; left-rail / right-rail / main grid math.
- **Spacing**: vertical rhythm; section breaks; no orphan controls.
- **Typography**: 4-tier scale max; line-height 1.4-1.6 body; tabular-nums for stats.
- **Color theory**: semantic (good/warn/bad/dim/accent) > brand-only; data-attr driven, not class-explosion.
- **Unification**: same widget for same job everywhere; no two date pickers, two chip styles.
- **Overlay design**: position relative to anchor; ESC closes; backdrop opacity calibrated; never modal for read-only.
- **Ease of use**: 1-click to most-common action; muscle memory > novelty; persistent state via localStorage with explicit migration on shape change.

Per-page UI audit ritual: subagent reviews; orchestrator applies; tests pin contracts; commit; synopsis row.

### 4. Cost/latency reorientation (standing secondary objective)

Find runtime cost/latency savings WITHOUT degrading the product (the PRIMARY Haiku-elimination program is section 4b). Sweep these 7 levers each run; ship a fix only when net-positive AND tests green, otherwise record CLEAN no-commit with evidence:

1. Prompt-cache coverage - `cache_control` markers on coach prompts; every `messages.create()` caller covered or exempt.
2. Route TTL - module-level `_CACHE` constants on hot dashboard routes.
3. Polling cadences - no sub-500ms network polls; UI-local timers are fine.
4. Log spam - `_SUPPRESS_LOG_PATHS` keeps every path under ~1/sec; needles are bare prefixes (a trailing space silently fails the substring match - item 171).
5. Model tier - haiku is the INTERIM floor for any surface still on a live call, NOT the end state (the section 4b program retires each haiku site to a precomputed path); Sonnet/Opus only where the charter requires (agent6 auditor, vision); the `_model = "claude-sonnet-4-6"` assignments in the aram/arena/brawl coaches (`coaches/aram_coach.py:767`, `coaches/arena_coach.py:1188`, `coaches/brawl_coach.py:638`) ARE call-time model picks, NOT telemetry stamps - `modes/shared_vision.py:389-390` feeds the field straight into `messages.create(model=...)`, and the relay path at `:378` forwards the same field - yet they are still NOT a tier violation, for a different reason: they configure the charter-permitted VISION reader, and `read_tiered` (`modes/shared_vision.py:301-339`) routes OCR first with Sonnet only as the `escalate_fn`, behind a pre-screen skip on unchanged `state_summary` (`:314`). Verdict unchanged (not a violation); the rationale is not. Measured 2026-08-14 - the prior "POST-call telemetry stamps" wording was false, and a sweep trusting it would skip a real call-time model assignment.
6. Scheduled-task catalog - 14 RC-* tasks; no orphans.
7. Bundle parity - panel CSS file count == `dashboard.css` panel @imports (drift guard test).

Never trade product fidelity for cost. A degrade is not a saving.

### 4b. Haiku-elimination program (PRIMARY north star)

The product goal is ZERO live Haiku calls. Every coaching surface that today calls `claude-haiku-4-5` should migrate to a precomputed DS pattern read at request time. The live call sites to retire: `coaches/{aram,arena,brawl,champ_select,replay,experimental_builder,aram_team_analyzer}_coach.py`, `coach_integration/_coach.py`, `tft/{tft_coach_engine,tft_live_analysis,tft_pbe_engine,tft_vision_reader}.py`, `dashboard/_champ_select.py`. (agent6 auditor + vision Sonnet are charter-exempt - out of scope for this program.)

Each run advances the program via PARALLEL orchestrator lanes (dispatch them concurrently, disjoint file sets, per section 2):

**Lane A - combat-trigger scenario precompute (laning).** Use the DS combat substrate (`agents/daemon_slayer/scenario_matrix.py` + `combo.py` + `mana_sim.py` + `fight_report.py`) to precompute laning-phase verdicts - trade / all-in / back-off / recall / cooldown-window / spike-timing - across the cross product of (matchup x level x item-state x cooldown-state x mana-state). Sweep MANY scenario combinations in parallel. Persist the verdicts as lookup tables the live coach reads at request time instead of calling Haiku. The verdict math is deterministic DS engine output - no LLM in the loop.

**Lane B - item-usage-metric -> optimal prebuilt build orders.** In parallel, search EVERY item-usage metric source available (Meraki bulk `aram_modifiers` + item passive formulas, the DS ranker `agents/daemon_slayer/rank.py`, the build engine `core/build_order.py`, the curated loadout system, the operator's lolmath wiki data access) to precompute optimal build orders per (champ x mode x enemy-comp). Build coaching becomes a DS lookup, not a live call. Mirrors the existing curated-loadout pipeline; extend it to full coverage with metric-backed ordering.

**Lane C - A+B coaching direction.** Shift coach output from free-text Haiku generation to the deterministic A/B choice surface (`coach.choices`; chip UI under `#rn-immediate`, per reference_ab_tutoring_coach; native emit live in the aram/arena/brawl/sr coaches per reference_coach_choices_native_emit). The A/B chips are driven by the Lane A/B precomputed tables - two grounded choices each carrying the DS-backed verdict, not an LLM paragraph. This is the primary coaching surface going forward; emphasize it over prose generation.

**Lane D - overlay switch-up + UI lift + agent.** Advance the Electron overlay (`rc-shell/` Phase 1 shipped item 223; `docs/ELECTRON_OVERLAY.md` Phases 2+ pending). Build the in-game overlay surface-switch (companion <-> in-game HUD per the state machine), a UI lift for the overlay panels, and a dedicated overlay agent slice. Vanguard-safe constraints hold (DWM compositor window, NO DXGI capture, Borderless mandatory - per feedback_gamepc_screen_capture_bsod + feedback_gamepc_lcu_phase_watcher_bsod). Frontend slices follow the section 3b visual-proof + UI-audit ritual.

Retiring a Haiku call site is only "done" when the precomputed path produces a verdict the operator would accept in a live game - validate against a real or replayed game before flipping a coach off its live call. A precompute that is WRONG is worse than a Haiku call; do not flip blind. Until a surface's precompute path is validated, leave its live call in place (haiku is the interim floor, section 4 lever 5). DS schema lifts that unblock these lanes (new combat axes, new build metrics) run as their own parallel slices under section 8.

### 5. Frozen-file edits under this run's grant

- The grant is operator-authorized for the CURRENT run only. Do NOT extend into future sessions (per items 108 + 99). The grant does NOT carry forward.
- When you DO touch a frozen file, route AROUND when possible. Adding a single import line in main.py to wire a non-frozen module is fine; rewriting `_loop.py` is a separate dedicated session.
- Every frozen-file commit body explicitly notes "frozen-file edit under operator's headless-upgrade grant".

### 6. ASCII hygiene (hard rule)

- No em-dash, no en-dash, no smart quotes anywhere in authored text (.py / .md / .ps1 / .css / .js / commit messages / chat output).
- Use ` - ` (spaced hyphen) for a clause break, `-` otherwise.
- The `"-"` no-data sentinel in dashboard rendering is OPERATOR-APPROVED and stays.
- Pytest_guard catches Python; check `.md`/`.css`/`.js` by `grep -P "[\xE2\x80\x93\xE2\x80\x94\xE2\x80\x98\xE2\x80\x99\xE2\x80\x9C\xE2\x80\x9D]"` before commit when in doubt.

### 7. Multi-agent dispatch rules

- Cap: up to 100 concurrent worktree agents per task. Partition to disjoint file sets.
- Each agent prompt MUST carry the don't-redo set so it does not re-research closed topics. Source of truth: the `CLAUDE.md` "Settled - do not re-litigate" section + `docs/history_notes.md`. Examples for LoL overlay research: coachless.gg, baronbuff.com, aggregator Z13, aggregator J, draft tool L (the community fork), league_record, KebsCS, Pengu Loader, all generic LCU clients, ML win-predictors, .rofl parsing.
- Agents return TRIAGED NOW/FUTURE/CLOSED with reasons. Synthesize NOW items into BACKLOG.md + open issues; do NOT auto-implement everything.
- Verify agent premises against live data before acting (feedback_verify_generated_reports) - a research agent once claimed Meraki bulk lacked ARAM modifiers; live probe showed it has them on the CHAMPION bulk, not the ITEM bulk.
- Subagent-generated files (esp. tests) MUST pass `ruff` before the agent reports done (CLAUDE.md subagent-quality rule; subagent test files have broken CI before).

### 7b. Deep-dive competitor research (depth bar - NOT superficial)

When a task is "see what can be lifted from competitor X" (or a competitor-lift research lane), the bar is a TRUE teardown, not a homepage skim. A finding like "they have a build page" is a FAILURE - it must name the actual mechanic, the math/data behind it, and the RC integration point. Prefer DEPTH over breadth: one heavyweight agent per target doing a full teardown, not many shallow ones.

**Tooling allowance** - research agents may use the full MCP/scraping toolbelt freely. This tool spend is NOT subject to the cost/latency budget in section 4 (that budget governs RC RUNTIME spend, not one-off research). Load any deferred MCP tool via ToolSearch first (`select:<name>` or keyword search) - they are not pre-loaded. Use the agentType `general-purpose` (tools: *) so the agent can reach these and Write the report:
- Chrome DevTools MCP (`mcp__plugin_chrome-devtools-mcp_chrome-devtools__*`) or Claude-in-Chrome - render the LIVE page, `evaluate_script` against the DOM, and capture the network/XHR (`list_network_requests` + `get_network_request`) to see the ACTUAL API shapes + payloads powering the UX.
- Firecrawl (`firecrawl-scrape` / `firecrawl-crawl` / `firecrawl-agent`) - bulk structured extraction + crawl doc/feature sections.
- nimble `competitor-intel` / `competitor-positioning` / `company-deep-dive` - purpose-built teardown with before/after tracking.
- Playwright MCP - interaction-driven pages (click through tiers, trigger a calc, capture the result).
- Windows MCP / computer-use - a competitor DESKTOP app (overlay, native client); screenshot + inspect what the live tool actually renders.
- WebFetch / WebSearch / the `deep-research` skill - sourcing + cross-reference.
- Isolated execution: when a target needs something RUN or PARSED (a competitor overlay .exe, a downloaded data file, a headless render, a parser script), do it in an isolated Legion workspace - a temp dir or a disposable git worktree, kept off RC's runtime paths - via Windows MCP / computer-use. Keep it away from `data/` and the live RC process so the runtime env stays uncontaminated. Clean up any artifacts you create when done.
- The toolbelt above is ILLUSTRATIVE, not a whitelist. Reach for ANY connected tool / MCP server / CLI / skill that serves a legitimate parse-or-render task, listed here or not. The only bounds: lawful + authorized target (public sites/tools, or the operator's own machines) + non-destructive + the standing secrets and frozen-file rules. No credential theft, no malware, no destructive ops.

**Depth checklist - every finding must answer ALL six:**
1. WHAT - the specific mechanic / UX / math (the algorithm, the interaction, the data shape, the network call - not "feature Y exists").
2. HOW - it works under the hood (captured XHR payload, the formula, the state machine, the render).
3. HAVE - does RC already do this? grep RC + cite the file (many are already covered).
4. WHERE - the concrete RC integration point: specific file/module + layer (engine math vs route vs panel JS).
5. EFFORT + RISK - new data / Riot or Claude dependency / schema lift, or just a presentation layer over existing DS math.
6. LIFT verdict - HIGH / MED / LOW, with the reason.

**Lift appropriately (legal):** reimplement the mechanic / UX / math in RC's own code. Do NOT vendor competitor code without a license (KebsCS is reference-only, no license - never copy). The output is a re-implementation plan, not pasted code.

**Rules:** each agent carries the don't-redo set (CLAUDE.md "Settled" + the closed-negatives in reference_liftability_triage). Verify every scraped claim against the live source before recording - marketing copy is not implementation. Output a dated `docs/COMPETITOR_LIFT_<YYYY-MM-DD>.md` (mirrors the 2026-05-28 18-site artifact) with per-target HIGH/MED/LOW + mechanic + RC integration point + effort. Then ACT on the verdicts under the run's full-authority grant: a HIGH-lift that is low-risk (a presentation layer over existing DS math, no new Riot/Claude dependency, no schema lift, fully testable) gets implemented IN-RUN as its own slice with tests + the section 3b visual proof if it touches UI. A HIGH-lift that is high-effort or carries a new dependency / schema lift / product-direction call becomes a BACKLOG entry + open issue for the operator to gate - log it as FUTURE, do not build it blind. MED/LOW always defer to BACKLOG. The docs artifact records every verdict either way.

### 8. DS audit iteration loop

- DS schema lifts run as PARALLEL orchestrator slices (section 2), not only the serial audit loop - dispatch independent lifts concurrently on disjoint engine modules. Prioritize lifts that unblock the section 4b Lane A combat-trigger + Lane B build-order precompute (new combat axes, new build metrics).
- Stop rule: 11 consecutive no-change iterations.
- Source of truth: Meraki bulk (`/items.json`, `/items_meraki.json`, champion `aram_modifiers`) - never aggregator D, never aggregator A scrape. **CARVE-OUT, measured 16.15.1 (2026-08-08): Meraki is NOT the source for item PEN / LETHALITY / resist-reduction MAGNITUDES.** Those live ONLY in the DDragon `<stats>` description block. `items_meraki.json` carries 320 items against DDragon's 706 canonical, ZERO rows carry a `stats` key at all, and item 228005 is absent from Meraki entirely - so auditing a magnitude against Meraki manufactures PHANTOM mismatches (it cost one slice 7 of them). Meraki REMAINS correct and preferred for `aram_modifiers` and for item PASSIVE FORMULAS - but read the whole row: a passive can be filed under `active` rather than `passives` (223069 Void Immolation is, and a `passives`-only probe wrongly reads it as unsourced).
- Each iteration touches ONE math lane (lethality, %-pen compose, on-hit family, immolate family, etc) and either ships an ENGINE_VERSION bump + tests, or records "no-change" with explicit reasoning.
- After each ENGINE bump, sync the ENGINE_VERSION pins across DS tests + bounce DS server (NOT supervisor-watched).
- When ADDING tests, prefer parametrized property-style (parameterize over (level x AP/AD x item-set) tuples) over single-pin checks. Mathematical invariants > exact values.

### 8b. A/B tutoring prompt-style coach (when on the coach-prompt task)

Reorient the coach output from prose-block to A/B choice format:

- Each coaching tick produces 1-3 micro-decisions with explicit A / B (sometimes C) options.
- Each option carries: short label, expected outcome, confidence band (low/mid/high), data source tag.
- UI prominence: coach prompt is the SECOND-most-prominent element after live game data; never buried below 3 fold.
- Choice is read-only logged (no input wired yet) so post-game can replay decisions with outcomes.

### 8c. Rewind DB live wire

- `rewind_history.db` weekly catchup task already registered (`RC-RewindCatchup` Sundays 04:00).
- Live wire = streaming new match into DB as soon as Match-V5 returns post-game, without waiting for cron.
- Hook point: `post_game_*` route or `app/_state_authority.py` end-of-game callback.
- Idempotent INSERT OR IGNORE; reuse PUUID-rotation auto-handling via Account-V1.

### 9. Interrupt protocol (no verbatim phrase match)

- ANY operator message that arrives during the run is an interrupt signal. It does NOT have to say "wrap up" or any specific phrase. Treat any entry as: STOP starting new phases, FINISH the in-flight slice (never abandon a half-merged state), then run `/done`.
- If the operator's message is plainly a question (not a stop), answer it in caveman ULTRA and resume. If intent is ambiguous between question and stop, treat it as stop-and-wrap (safer; the next session can resume from WAKEUP_NOTES).
- NO blocking AskUserQuestion mid-run - the operator is away; a forced question hangs the run. Pick the reasonable default, log the choice in the synopsis + WAKEUP_NOTES, and proceed. A scope decision that genuinely needs the operator becomes a FUTURE item, not a block.
- If a message lands mid-critical-path (mid-restart, mid-merge), finish the critical path FIRST, then handle the interrupt.

### 10. Headless cadence health

- Living synopsis on Desktop: update every phase complete (atomic Write); never delete the file mid-run; final state survives as the durable record.
- Living docs (CLAUDE.md item N+1, ROADMAP.md, BACKLOG.md, WAKEUP_NOTES.md, docs/DAEMON_SLAYER.md): synced at run END as a single surgical commit, NOT per phase.
- WAKEUP_NOTES prune: `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:/Riot Commander/scripts/wakeup_prune.py" --keep 3` (no-op when already <=3 sessions).
- Worktree cleanup at run END: remove merged worktrees + `git worktree prune` + `git branch -D` merged slice branches, so disk stays lean for the next run (the orchestrator pattern is what bloats it).
- 10h+ extension: if still running past 10 hours, transition to a full RC refactor audit (multi-agent codebase split). Frozen-file edits still allowed; tests required.
- Token budget: caveman ULTRA is the default for fleet-wide overnight (per the SessionStart hook). Compress chat output ~90 percent; keep code tokens / paths / numbers / error strings byte-exact.

### 10b. Memory + audit + iterate (folded in)

- **Memory**: save non-obvious patterns surfaced during the run (lift methodologies, anti-patterns, calibration thresholds). Update `MEMORY.md` index single-line.
- **Audit**: per-page UI audit ritual + cost/latency sweep + DS coverage drift + ASCII drift.
- **Iterate**: per-phase, lint -> test -> commit -> CI -> synopsis. No multi-phase batching without commit gate.
- **Test**: prefer parametrized property tests; pin invariants not values; mathematical equivalence > exact float.
- **Improve**: each phase leaves a real, shippable improvement; no half-finished implementations.
- **New tech**: each run sweeps for upstream changes (Riot patch notes, claude API model bumps, browser API additions, repo deps).

### 10c. Context management is a first-class run constraint (not a courtesy)

The binding budget on a headless run is CONTEXT, not wall-clock and not tokens spent.
A run that blows its window mid-slice loses the merge state it was holding, and the
next session pays to rediscover it. Treat the context window the way you treat CI:
a gate that must stay green, checked continuously, never at the end.

**Push work OUT of the main thread by default.** This is the real reason the
orchestrator-merge pattern (section 2) exists, over and above parallelism:

- A worktree subagent's file reads, greps, and full test output NEVER enter the
  merger's context - only its roll-up does. A slice that would cost the merger 100k
  costs it the length of one report.
- The same applies to the read-only `verifier` gate. Do not re-run a slice's suite
  yourself to check it; dispatch the verifier and read its verdict.
- NEVER Read a subagent's `output_file` - it is the full JSONL transcript and reading
  it can end the run on the spot. If you need more from an agent, `SendMessage` it.
- Probe with a targeted grep before reading a file. `wc -l` / a `grep -n` for the
  anchor beats reading 2000 lines to find one constant.
- Ask agents for roll-ups, not transcripts. A report that states file:line, the
  numbers observed, and the decisions taken is worth more than a narration.

**Durable state lives on DISK, not in the conversation.** Everything that must
survive a `/clear` or a crash is already file-backed - use it deliberately:

| what | where | when written |
|---|---|---|
| slice checkpoints | `ops/runtime/slice_manifest.json` | as each slice advances (section 1) |
| the run record | the Desktop synopsis | every phase complete |
| per-item history | `docs/LEDGER.md` | run end |
| session continuity | `WAKEUP_NOTES.md` | run end |
| durable lessons | `memory/*.md` + the `MEMORY.md` index | as they surface (10b) |
| the next session's brief | a Desktop `RC RC Continue - N.txt` | see below |

If all six are current, losing the conversation costs nothing but the in-flight slice.
That is the actual test of whether context management is working - not how long the
window lasted.

**Write the next-session prompt BEFORE the banner, not after.** The hand-off is the
one artifact whose absence blocks the next session, so it must not be the last thing
attempted on a nearly-full window. Write it to the Desktop as soon as the work queue
is essentially settled, in the operator's own continue-note format:

```
NEXT SESSION
------------
Task: <a LIVE-STATE FORK, so the next session cannot pick a blocked item -
  "probe first; if a Mayhem game is playable do X, if SR do Y, if neither do Z">
Context: <ENGINE / patch / last run's commits / the probe commands>
READ THIS FIRST: <any trap that would otherwise burn the session - e.g. a working
  tree whose suite signal is unusable, with the measured numbers>
Acceptance: <per fork, concretely>
Do NOT redo: <the closed set relevant to those forks, with reasons>
Also owed: <the FUTURE items in priority order>
Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES + git log.
```

Rules for it: a bare "continue the work" is a failure. Name the fork on live state,
front-load the traps, and carry the do-not-redo set - a next session that re-derives a
closed finding is the exact waste this file exists to prevent. If the run measured
something that makes the obvious reading of the repo WRONG, that goes in READ THIS
FIRST with its numbers.

**Session boundaries.** One focused unit per session (CLAUDE.md "Session workflow").
`/clear` between Tier items, between coding and reviewing modes, and between
focus-area switches - a stale window costs more than a cold bootstrap, because
bootstrapping is cheap (CLAUDE.md + MEMORY.md + WAKEUP_NOTES + git log) and a
half-remembered decision is expensive. `/done` (section 11) then ends the session,
and it is what makes the next `/clear` safe.

**When the window gets tight mid-run:** finish the in-flight slice to a committed
state, checkpoint the manifest, sync the synopsis, write the next-session prompt, then
`/done`. Do NOT start another slice hoping to fit it, and do NOT leave a half-merged
tree - a merge abandoned mid-way is the one failure mode that costs the next session
more than it saves this one.

**Do not spend context on cleanup that needs judgement.** If a hook or a threshold
asks for a trim (the `MEMORY.md` index is the recurring one), MEASURE first and check
whether a mechanical pass actually helps. If reaching the threshold means dropping
information rather than reformatting it, that is curation and it wants its own
session - log it as a FUTURE item with the measurement and move on. Degrading the file
that bootstraps every session, in a hurry, at the end of a long run, is worse than
sitting over a soft limit.

### 11. The /done ritual at run end

Run `/done` (existing skill). It handles the local check gate, auto-commit + push, GitHub CI verification, background-task stop, bridge-loop liveness, WAKEUP_NOTES update + prune, living-doc sync, incoming-lessons drain, session-size check, and the final banner. DO NOT skip; the WAKEUP_NOTES update is what unblocks the next session's bootstrap.

Two things `/done` does NOT do, so do them first (section 10c): the Desktop
next-session prompt must already be written, and the working tree must be back the way
the operator left it - if the run stashed anything to get a clean measurement, pop it
and confirm `git stash list` is empty. A run that ends with the operator's data sitting
in a stash has silently changed their machine.

### 12. Anti-patterns (caught from past runs - do NOT repeat)

- Do NOT `git add -A` without unstaging `_scratch/` first.
- Do NOT skip the `ruff check` local lint - F541 has killed CI.
- Do NOT amend commits; always create new commits (CLAUDE.md hard rule).
- Do NOT `Stop-Process` - it hangs the MCP pipe; use `taskkill /F /PID <pid>` (CLAUDE.md hard rule).
- Do NOT leave locked worktrees uncleaned at run end; they bloat disk run over run.
- Do NOT hardcode a model version in the commit trailer; use the trailer the harness footer supplies.
- Do NOT trust an agent's premise without verifying against live data.
- Do NOT dispatch a research agent without an explicit don't-redo list.
- Do NOT skip the `compute_asset_hash` reload mention when shipping frontend changes.
- Do NOT add a feature flag or backwards-compat shim for changes that should just BE the new behavior (CLAUDE.md: no feature flags).
- Do NOT add comments that say WHAT the code does. Comments are for WHY only.
- Do NOT block on AskUserQuestion mid-run; the operator is away.
- Do NOT Read a subagent's `output_file` - it is the full JSONL transcript and it can end the run (section 10c).
- Do NOT leave the next-session prompt until after the banner; write it while there is still window to write it well (section 10c).
- Do NOT end a run with the operator's files still stashed. `git stash list` must be empty.
- Do NOT mark a frontend slice done without a visual capture + UI-audit (or an explicit OWED carry-forward when the Legion capture path is unavailable).

### 13. Final banner

When an interrupt fires (or the work queue is empty), emit one tight banner:

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
  Next session: C:/Users/Administrator/Desktop/RC RC Continue - <N>.txt
  Ready for /done.
```

Then call `/done`.
