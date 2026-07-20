# Riot Commander - Agent Context

Live League / TFT coaching dashboard. Reads Riot Live Client API, calls Claude Haiku for coaching and Sonnet for vision, writes JSON to `data/`, serves `:8888` HTTPS dashboard locally on Legion (1-PC since 2026-05-29; ADR-011). RC is tkinter-free (scheduler is asyncio AppLoop; 13 residual .after() files); Daemon Slayer (`:8893`) computes real DPS math per champion.

> **Living docs (read at session start):** `docs/ARCHITECTURE.md` · `docs/OPERATIONS.md` · `ROADMAP.md` · `docs/API.md`
> **Deep references:** `docs/DAEMON_SLAYER.md` (DS engine - 706 items / 173 champs - ENGINE_VERSION 1.232.0 (patch 16.14.1) - all 7 archetype scorers wired (Slice B on-hit AP ds.onhit) + Term A ally-granted EHP (ds.ehp score_by=team_blended, DEFAULT-OFF) + canonical cast-rate keys (ult_rates apply_canonical_cast_rate_keys, DEFAULT-OFF) + RM-39/RM-43 AD-axis ability term (ds.hybrid apply_ad_axis_ability_damage, DEFAULT-OFF; L2 1.223.0 credits PHYSICAL+TRUE, MIXED held, MAGIC permanently excluded) + per-spell CC consumer + cc_blended_ehp ecosystem COMPLETE 4 consumers + per-spell CC wave 9 108/89 + cc_conditional ecosystem COMPLETE 5 consumers wave 6 36/32 + survivability axes heal/shield/DR/resist-grant COMPLETE across both EHP scorers incl flat + rank-scaled-block + percent-of-resist + unlabeled-multi-stat-block + form-occupancy + per-stack-unbounded modes + revive/second-life EHP-numerator multiplier Anivia/Zac) - `docs/AGENTS.md` (Phase 3 framework) - `BACKLOG.md` (aspirational)
> **Architectural decisions:** [`docs/adr/README.md`](docs/adr/README.md) (indexed, 12 ADRs) - before re-litigating a past choice, check here first.
> **Dated artifacts** in `docs/_archive/` (excluded from ripgrep searches).

## Topology

| Machine | Tailnet / IP | LAN IP | Role |
|---|---|---|---|
| **Legion** | `legion-rc` / `100.70.22.55` | `192.168.8.230` | 1-PC (2026-05-29, ADR-011): runs League + Vanguard + RC + supervisor + vision server + dashboard + OBS. Relocated agents run local as ONLOGON tasks: RC-LCUAgent / RC-LiveClientRelay / RC-HotkeyListener. Tailscale node stays `legion-rc` though Windows hostname is now `DESKTOP-JKZECV9` |
| **Peer** | `peer-host` / `<peer-tailnet-ip>` | - | Separate machine (separate private project); RC<->Peer cross-Claude bridge decommissioned 2026-06-24 |

Both in tailnet `tailc150de.ts.net` (Game-PC retired from the pipeline 2026-05-29, ADR-011). Prefer tailnet hostnames. Vision runs in-process at `127.0.0.1:8889`. The game host is config not code: `core/game_host.py` `RC_GAME_HOST` (default `127.0.0.1`) is where every live reader finds Live Client `:2999` + LCU.

## Paths

- Project root: `C:\Riot Commander\`
- Python: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
- API key: `C:\Riot Commander\API-Key-Claude.txt` (gitignored)
- Health: `C:\Riot Commander\ops\runtime\health.json`
- Logs: `C:\Riot Commander\logs\YYYY-MM-DD.log`

## Hard rules

- **Always `py_compile` before restart.** Syntax errors crash silently under `pythonw.exe`.
- **Atomic writes only:** `tmp.write_text(...); tmp.replace(target)`. Overlays poll mid-write.
- **Never `Stop-Process`.** Hangs MCP pipe. Use `taskkill /F /PID`.
- **Commit messages with special chars:** use `git commit -F <tmpfile>` (Write the file, ASCII-only) or a single-quoted here-string - never a double-quoted here-string or a piped string (BOM + ANSI-mangle risk, same root cause as the no-em-dash rule below). `tools/precommit_gate.py` (PreToolUse hook on `git commit` + PowerShell) is the backstop: it blocks banned glyphs + net-new ruff on staged lines.
- **Restart via `restart_trigger.txt`** (write any content; supervisor clears + restarts within ~5s).
- **`SCRIPT_DIR` in `app/__init__.py` MUST be `Path(__file__).parent.parent`** (package layout).
- **State assumptions explicitly before coding.**
- **No em-dashes or en-dashes - ever (7-bit ASCII authored content).** Hard rule across Legion / Peer, in *all* authored text: code, comments, docstrings, `.md`, writeups, commit messages, WAKEUP/ROADMAP/CLAUDE, chat output. Use ` - ` (spaced hyphen) for a clause break, `-` otherwise. Also avoid smart quotes (U+201C U+201D U+2018 U+2019) and en/em dashes (U+2013 U+2014); stay ASCII. **Why:** Windows PowerShell 5.1 `ParseFile` ANSI-decodes a no-BOM `.ps1`, turning a UTF-8 em-dash inside a double-quoted string into a U+201D smart-quote that the tokenizer treats as a string terminator -> cascading parse failure (2026-05-18 boot-script incident); also a standing operator style rule. **Retroactive purge done** (2026-05-18, `tools/strip_em_dashes.py` - reusable for drift checks): em+en dashes stripped repo-wide incl. the functional `"-"` no-data sentinel in code/JSON (operator-approved behavior change - empty dashboard cells render `-`). **NOT swept** (immutable history / non-source): `*.log` + rotated `*.log.N`, `docs/_archive/**` + dated artifacts, `.jsonl` ledgers, binaries, `.pyc`/`.git`. Smart quotes are rule-banned going forward but not yet retroactively swept (separate operator-gated pass).
- **Frozen files** (do not modify without explicit user approval):
  `main.py`, `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`,
  `core/game_snapshot.py`, `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`,
  `app/__init__.py`, `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`,
  `tools/diagnose.md`, `tools/caveman.md`.

## Restart workflow

```
echo restart > restart_trigger.txt
```
Verify: read `ops/runtime/health.json`, confirm new `pid`, `alive=true`, `last_reload_ok=true`.
Hard fallback: `taskkill /F /PID <pid>` then `restart.bat`.

## Session workflow

Scoped sessions - each focused task is one session.
- **End:** commit + update `WAKEUP_NOTES.md` (keep last 2-3 sessions at full fidelity; archive older to `docs/history_notes.md`) + push.
- **Start:** `/clear`, bootstrap from CLAUDE.md + MEMORY.md + git log + WAKEUP_NOTES + `docs/ARCHITECTURE.md` + `ROADMAP.md`.
- `/clear` between Tier items, between coding/reviewing modes, between focus-area switches.

## Session-End Ritual

When user says 'wrap', '/done', or 'end session': run tests, commit with descriptive message, push, sync living docs (append the per-item ledger entry to `docs/LEDGER.md`, NOT CLAUDE.md), and confirm CI green before declaring done.

## Output Constraints

Keep individual responses under 500 output tokens to avoid API errors. Break long work into multiple turns or use file writes for verbose output.

## Style Rules

- No em-dashes anywhere (repo-wide hard rule, enforced).
- Watch for em-dashes in PowerShell double-quoted strings - they cause mojibake parse failures.

## Execution Efficiency & Tooling Rules

Operator-agreed 2026-06-13 to cut per-edit + audit wall-clock. Default to fast, direct, text-based tools; scale verification to blast radius. SCOPES "Testing Discipline" + "Verification Discipline" below (those apply at Tier-2). Memory: `feedback_execution_efficiency_rules`.

Text-first (R1-R4) - never default to visual / computer-use for text, code, or state:
- **R1** Files = Read / Edit / Write / Grep / Glob ONLY. NEVER computer-use / Windows-MCP to read or change a file.
- **R2** Runtime / dashboard state via `curl -k https://127.0.0.1:8888/api/...` or Read `ops/runtime/health.json`. NEVER screenshot to read a number, version, or STATE.
- **R3** Visual tools (screenshot / computer-use / Windows-MCP / preview / capture_monitor) ONLY for rendered-pixel / CSS / layout checks with no text equivalent, and live-game capture. The UI-audit ritual + game-monitor are the sanctioned visual uses (`feedback_screenshot_after_ui_changes`).
- **R4** Prefer built-in tools over Bash / PowerShell. When shell is needed: absolute paths (no `cd`), one compound command over many round-trips.

Tiered verification (R5-R7) - Tier-0/1 do NOT pay the Tier-2 tax (operator-accepted tradeoff):
- **Tier-0** cosmetic (doc / comment / string / non-runtime constant): Edit + `py_compile` if .py. No suite, no restart.
- **Tier-1** local logic (one module): `py_compile` + that module's tests only.
- **Tier-2** schema / engine / scorer / item-effect / `ENGINE_VERSION`: full dual suite (DS dir + `tests/`) + DS `:8893` restart + Share mirror.
- **R5** Classify every change into a tier; run only that tier's verification.
- **R6** Run the relevant suite ONCE; trust exit code + result file. Re-run only if I edited since, or the pipe demonstrably glitched - not prophylactically.
- **R7** `verifier` subagent ONLY for parallel-slice / subagent claims or a real stale-pipe event - not my own single-thread edits.

Overhead (R8-R11):
- **R8** Never re-Read a file I just Edited to confirm (Edit fails loudly).
- **R9** No subagents / worktrees under ~3 files. Inline.
- **R10** Batch independent reads / greps in one message.
- **R11** Skip the screenshot ritual for backend / version / doc changes (scoped to web/* visual changes).

Enforcement (hooks in `.claude/settings.json`): PostToolUse `tools/pytest_guard.py` is py_compile-only by default (no auto full-suite per edit); `RC_FULL_SUITE=1` restores auto-suite for a Tier-2 batch. PreToolUse `tools/text_first_guard.py` denies pure screen-text/state readers (Windows-MCP Scrape, computer-use read_clipboard) with a text-path pointer; escape hatch `ops/runtime/allow_visual.flag`.

## Web dashboard

`web_dashboard.py` at `:8888` HTTPS. Key endpoints: `/`, `/api/state`, `/api/health/all`, `/api/input`, `/api/command`, `/api/ds-preview`, `/metrics`. Viewed in Chrome on Legion at `https://legion-rc:8888/` - design baseline is **standard 1920×1080 with Chrome chrome present** (titlebar + URL bar + bookmarks bar visible, usable viewport ≈ 1920×~920). F11 fullscreen is optional and recovers the chrome chrome - `main` flex-grows into the extra height (no layout pinned to 1280). Cert via `tools/regen_rc_cert.ps1`. Each machine has its own Anthropic API key (`riot-commander-legion`, `riot-commander-peer`).

## Scheduled tasks (Legion)

Key: `RC-Supervisor` (logon, Administrator, HIGHEST). Vision has NO scheduled task (removed 2026-06-11, deep-audit P2): `dashboard/server.py` self-heals `:8889` in-process. Full list: `docs/OPERATIONS.md`.

## Vision pipeline

The `screen_agent.py` agent (Legion-local) POSTs frames every 2s to `:8889/upload-frame`. Coaches call `modes.shared_vision._capture_screen()` → GET `:8889/latest-frame`. **`_run_vision()` gates on `_fetch_game_data() is not None`** - vision never fires during lobby/idle. Tiered: OCR first, Sonnet escalation for misses. Calibrate `data/vision_regions.json` to expand OCR coverage. The sibling Live Client relay (`:8889/upload-liveclient` <- RC-LiveClientRelay agent; `/latest-liveclient` -> poller + `core/liveclient_cache`) self-heals: `vision_server/_relay.get_latest_liveclient()` reads `:2999` in-process when the relayed snapshot is stale + `GAME_HOST` is local, so the relay agent is non-integral to DS/RC (1-PC, ADR-011 update 2026-06-02).

## Mode detection

`game_reader.py._process_game()` → `core/game_snapshot.py` → mode strings. ARAM Mayhem (`KIWI`) → `MODE_ARAM`.

## Where to find current state

- Live PID + mode + health: `ops/runtime/health.json`
- Current game state: `data/{aram,arena,brawl,tft}_coaching_data.json`
- Recent activity: `logs/YYYY-MM-DD.log`
- Architecture / module map: `docs/ARCHITECTURE.md`
- Ops commands + restart: `docs/OPERATIONS.md`
- Open work: `ROADMAP.md` · Aspirational: `BACKLOG.md` · History: `docs/history_notes.md`

## Useful commands

Full reference: `docs/OPERATIONS.md`. Quick-start:
```
python -c "import json; print(json.dumps(json.loads(open(r'ops/runtime/health.json').read()), indent=2))"
echo restart > restart_trigger.txt
curl -k https://127.0.0.1:8888/api/health/all
```


## TDD First

All feature work and bug fixes follow TDD: write failing characterization/regression test first, then implement, then verify full suite (20,190 tests) before committing.

## Subagent Code Quality

When spawning subagents to generate files (especially tests), require them to run ruff/lint before reporting done. Subagent-generated test files have broken CI in the past.

## Subagent-First Protocol

Standing operator directive (2026-06-20): ALWAYS use subagents for substantive design / build / research work - do not build solo in the main thread. Refines R9 (truly trivial one-line cosmetic edits may still inline).
- **Spec first, then act:** a Plan/design subagent (or the Gemini director) emits the spec/plan BEFORE any code; verify it against ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
- **New session:** interview the Gemini director (or the operator if Gemini is down) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
- **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
- Every `.claude/commands/*.md` carries the SUBAGENT-FIRST block (local, gitignored). See memory `feedback_subagent_first_protocol` + `feedback_parallel_batch_agents`.

## Testing Discipline

Always run the full test suite after schema changes, engine version bumps, or item-effect additions. Avoid data-fragile cross-item comparison assertions; prefer assertions on computed quantities. When stubbing methods accessed via class, wrap with `@staticmethod` correctly. Before writing any probe or test, grep the codebase to confirm every method, field, and data shape it will use actually exists - cite file:line for each; never scaffold against an assumed API surface (past misses: heal/shield assumed in raw_modifiers, wrong file shapes). **Tier scope (R5):** "full suite" = Tier-2 (schema / engine / ENGINE_VERSION / item-effect); Tier-0 cosmetic + Tier-1 local-logic edits are exempt - see "Execution Efficiency & Tooling Rules".

## Error Handling

Never surface raw API error strings (credit/balance exhaustion, 400, rate-limit, thinking-block) in the coach UI or any user-facing dashboard panel. Catch and render a friendly degraded-mode message (e.g. "coaching paused - retrying") and log the raw error to `logs/`. Applies to all coaches + dashboard panels.

## Verification

Before asserting external state - API key validity, account IDs, process/PID metrics, "X is dead/missing/broken" - verify it live against the source of truth; never rely on a stale doc or another agent's unverified output. Re-probe first, then assert. See memories `feedback_verify_generated_reports` / `feedback_verify_before_declare_broken` / `feedback_audit_proposals_are_intent`.

## Verification Discipline

Re-verify against ground truth before claiming any task green; the tool pipe can replay stale or out-of-order results (item 238 hit severe stale-tool-result replay - fabricated "1 failed", a non-existent dtype=None, a pre-bump /health, invented filenames). Ground truth when the pipe wedges = `git status` + Edit success/fail + pytest written to a file + a DONE-exit sentinel, NOT raw stdout. Before reporting complete: re-run the relevant suite fresh, confirm every cited test file actually exists on disk (`ls` it), and report the exact pass/fail counts you observed THIS run - never carry a prior or subagent-reported count forward. NEVER trust a subagent's claim about test counts, green CI, or file existence without an independent probe; subagents have cited non-existent test files and used broken commands (wmic, pre-restart cumulative measurements). The `verifier` subagent (`.claude/agents/verifier.md`) exists for exactly this re-check. See `feedback_verify_generated_reports` / `feedback_verify_before_declare_broken`. **Tier scope (R6-R7):** this re-verify-fresh + verifier mandate applies at Tier-2; Tier-0/1 follow tiered verification (run once, trust exit code unless edited-since or the pipe glitched) - see "Execution Efficiency & Tooling Rules".

## UI Fixture Ritual

Any UI page change runs the visual-hierarchy / fixture audit subagent BEFORE the commit + push, not after. Do not commit a page until the 5-phase audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) completes and every MUST-FIX is resolved in the same slice. Shipping a page ahead of its audit (page #8) was a process miss the operator called out explicitly. See `feedback_phase3_fixture_ritual` + headless-upgrade section 3b.

## Python Conventions

When adding a required field to a dataclass, append it at the END with a default; do not insert mid-class. A mid-class required field breaks every existing positional construction + test (item 216 inserted an AbilityContext field mid-class and broke 41 manual constructions; the fix was to default it at the end).

## Data Fixes

A data-corruption or pollution fix is not done until already-corrupted rows are backfilled + recovered, not just future occurrences prevented. A race-condition guard that only stops future races leaves the existing bad rows wrong (item 211 needed two extra backfill + Match-V5 recovery rounds AFTER the guard landed). Plan the recovery pass in the SAME fix and verify the historical rows are corrected live.

## Engine / Build Conventions

Champion-specific build / scorer fixes are validated per-champion, not with one generic ADC-crit shape; expect to patch multiple champions. A narrow first fix (item 208 marksman pollution) missed Golden Spatula + duplicate-path pollution and forced a second comprehensive cleanup (item 213). Before shipping a build/scorer fix: grep for sibling cases (other champions, other modes, duplicate build paths) and add a test covering each, root-cause-first (see the `root-cause-fix` skill). When narrowing a proc/effect fold (burn / kill-state / item-DoT credit): start with the tightest matching item/effect set and add a test asserting unrelated proc types (physical / tank / spellblade) are excluded BEFORE widening; widen only on test evidence (the DSV1 burn-proc fold over-counted on its first pass and took two narrowing iterations).

## Windows Environment Notes

Claude Desktop on Windows may be installed via the Microsoft Store (check `%LOCALAPPDATA%\Packages`) in addition to standard install paths. Use `pythonw.exe` (not `python.exe`) for background daemons to avoid flashing console windows.

## Daemon Slayer Batch Workflow

When continuing Daemon Slayer work: pick the next batch from ROADMAP, implement schema/engine changes, add tests (target green before commit), bump engine version, commit + push, verify live, update hand-off notes.

Before launching a background RC or test suite right after a DS change, wait for the Share mirror sync + DS `:8893` restart to settle; a mid-suite DS bounce produces false anchor-mismatch / live-integration failures that then cost a re-run to confirm they were transient.

## Session Wrap-up

When invoked with `/done` or asked to wrap a session: (1) audit pending changes, (2) commit and push, (3) update ROADMAP/README + append the per-item completion entry to `docs/LEDGER.md` (NEVER to CLAUDE.md; it is CI size-budgeted < 60KB - touch CLAUDE.md only for rule/frozen-list/Settled changes), (4) process lessons/WAKEUP_NOTES, (5) print final banner. Run independent steps in parallel. (Deprecated 2026-06-21 per operator: the Peer cross-Claude bridge probe / `/loop /process-bridge-tasks` re-run is NO LONGER part of the /done ritual - do not probe the bridge or flag a dead Peer loop at wrap.)

## Active priorities

Per-item completion ledger relocated to `docs/LEDGER.md` (append-only, newest-first) on 2026-06-02 to keep CLAUDE.md out of the per-turn auto-load budget. CLAUDE.md is CI size-budgeted (< 60KB) - NEVER append item-ledger entries here; append them to `docs/LEDGER.md`.

- Open work + NEXT: `ROADMAP.md` + `BACKLOG.md`
- Recent session fidelity (last 2-3): `WAKEUP_NOTES.md`
- Per-item completion ledger (item 325 and newer): `docs/LEDGER.md`
- Deep archive (items 1-324 + pruned wakeups): `docs/history_notes.md`

### Settled - do not re-litigate (items 1-149 relocated verbatim to `docs/history_notes.md` (1-93 on 2026-05-19, 94-149 on 2026-05-23); read that archive for full context before re-opening any line below)

- **Phases 1-7, 2.1-2.4, 3, 4-6, FU01/FU02/FU04 all shipped; the 6-scorer archetype-expansion plan (carry/tank/bruiser/mage/assassin/enchanter) is fully wired and the dispatcher has no fallbacks.** FU03 was superseded by FU04. Do not re-plan these or re-pitch a scorer.
- **DS conditional-target-state arc is operator-CLOSED (s232).** Part-2 live target-state plumbing is shelved permanently; an s232 saturation guard exists. Do NOT re-pitch Part-2 or re-scan for conditional candidates.
- **DS block_index/form_index/max_priority/combo_sequence pure-data registries were swept s223-s232 and are provably saturated** (machine-guarded). Further growth needs a schema lift, not uncovered-champion scans. The reusable pre-filters (`tools/ds_*_prefilter.py`, `ds_block_scanner.py`) are durable for patch re-extracts. Never `--force` a Meraki re-extract (the `latest` endpoint is mutable).
- **AUTONOMOUS_AUDIT s5 menu is fully exhausted** (the effects.py facade split shipped s246). Do NOT re-pitch an effects.py re-merge, an `__all__`, or a FastMCP/SDK rewrite of the stdlib MCP servers.
- **Keystone fixed + live-proven (item 87): ARAM Mayhem reports queueId 2400** (not 920). The phase-driven view-router was proven correct - do NOT re-pitch a router change. The `cs.is_aram` rendering path is item-87-preserved.
- **The augment LCU/:2999 API is a confirmed dead-end** (no capture-free augment API mid-game). Augment-OCR into the coach is the proven path. Do NOT re-pitch an LCU augment API.
- **`core/build_order.py` no-double-unique rule is engine-authoritative** - do NOT add a family map (a guard test fails on any family literal); the engine has 6 unique-passive families, not 3.
- **Research-list triage CLOSED negatives (do NOT re-research):** every LCU client/codegen repo is inferior to RC's lockfile client; KebsCS is the reference catalog only (no license - do not vendor); the corpus has ZERO Arena/Cherry/Mayhem lobby-create payloads (a bespoke payload must come from live LCU capture); `.rofl` full packet-parse stays out of scope as a shipping feature (per-patch Layer-2 obfuscation re-RE cost; a patch-stable Layer-1 header/chunk spike is logged in BACKLOG - the old "subset of Match-V5" reason was corrected 2026-06-03 since the format does carry per-cast/windup telemetry); ML win-predictors / CV-minimap / voice / `riot-offline-mode` are all CLOSED; Pengu `league-client-mcp` = NO (thinner than RC's client).
- **`core/smoothed_rates.py` is the shared Laplace/shrink primitive**; the s220 PGR 0-100 score is deferred to ROADMAP-S3 - do NOT pre-build it.
- **Brawl mode is retired from champ-select** (s214); legacy brawl backend is left as deadcode for a separate cleanup pass.
- **The Riot Personal key is valid and in-scope.** Match-V5 403/empty on event modes (ARAM Mayhem `gameMode=KIWI`, queue 2400) is EXPECTED, not a key fault; event-mode Match-V5 timeline placeholders are correct and permanent. **But Match-V5 is not the only route (MEASURED 2026-07-19, RM-106):** SGP, the client's own LCU-session-authenticated match-history backend, DOES return KIWI / queue-2400 games in Match-V5 shape. The statement above still stands; its CONSEQUENCE - that event-mode match data is unobtainable - does not.
- **`web/js/dashboard.js` is GONE** (quarantined `dab3ca74`; only `/js/main.js` loads). It was dead code - no `<script>` reference - and the `dashboard.js:5055` `_replayQueueLabel` 920 bug died with it. Nothing to leave alone; this line is a closed fence, kept only so the 920 bug is not re-reported against a file that no longer exists.
- **ADR-008 unified asset-hash:** editing `web/{js,css}/panels/*` auto-reloads via `compute_asset_hash` - no RC restart for asset-only changes.
- **No-em-dash retroactive purge is done** (s244 `tools/strip_em_dashes.py`, reusable for drift checks); the functional `"-"` no-data sentinel is operator-approved. The smart-quote retro-sweep is NOT yet done (separate operator-gated pass).
- **The all-173 alphabetical DS_SWEEP is CLOSED (2026-07-18, batch32): 173/173 - GAP 135, REFUTE 35, FENCED 3, Remaining 0.** Do NOT re-open the roster or re-scan for uncovered champions; further growth needs a schema lift, not another pass. Next free spec = RM-98. Two probe traps make a re-run produce plausible-but-WRONG output: `POST /rank` is the CARRY scorer and silently ignores `enemy_ad_share`/`enemy_ap_share` (use `/rank-<archetype>`), and probing at `item_ids=[]` under-ranks amp/complementary items - that artifact manufactured the two headline RM-92 instances (Soraka Moonstone reads #10 of 10 empty, #2 at depth, and the shipped build order already buys it). See memories `reference_ds_probe_rank_vs_archetype_route` + `reference_ds_probe_empty_build_artifact`.
- **The live-gated set is NOT synthetically drainable - measured, do not re-pitch.** A 14-agent triage-then-adversarial-refutation pass over all 124 rows (2026-07-18) closed **6**. Dominant kill was SUBSTITUTION: gate rows ask whether something RENDERS / SENDS / UPDATES, and the compute half is always available headless and always the wrong question. `docs/LIVE_GAME_GATED_SYNC.md` carries the full note.
- **Ledger commit citations before 2026-07 are ~50% unresolvable and that is EXPECTED** (387 of 1148). Not a history rewrite - worktree-agent slice SHAs that never survived cherry-pick. The work landed; verify by merge hash / file / test, never by a slice hash. Self-corrected: 0 of 537 July citations are dead. See the preamble in `docs/LEDGER.md`.
- **Live DS truth = `data/daemon_slayer/current.txt` + `agents/daemon_slayer/__init__.py` + `/health`** (do not trust ledger recollection of patch/ENGINE). DS coverage %/match-row prose is a DS-batch docs-sync job, never recomputed in a general sync (nested registry schema; a flat count mis-parses) - memory `feedback_ds_coverage_prose_recompute`.
- **Biggest pending non-engine item: the s220 aggregator-G-style Post Game Review reframe** (UI; operator-decided scope - single-match richer layout, the 0-100 score is an RC heuristic over enriched stats with NO Claude/Riot dependency; staged S2-S5, each its own session plus the per-page UI-audit ritual). Legion 1-PC consolidation is DONE (decided s169, EXECUTED item 215 2026-05-29, ADR-011; RC_GAME_HOST defaults 127.0.0.1; Game-PC retired from the pipeline + the relocated-agent rename/Game-PC-bridge teardown executed 2026-06-20) - only deferred tails remain (OBS launch-test live-gated; Phase 11 vision relay full-collapse partly done items 267/276). 101.qq.com duo-synergy is DONE + LIVE-WIRED (item 277): captured + characterized (faas getRankDouble, lane1/lane2 strings, championid 1:1 DDragon, NOT geo-fenced - reachable from Legion), then operator chose the LIVE dependency - NEW `core/synergy_external_source.fetch_rows` feeds the EXISTING item-199 `core/smoothed_rates_101qq` lane (live-first, static May-25 seed fallback, `RC_DUO_SYNERGY_LIVE=0` kill switch); `/api/duo-synergy` route + bot/sup grid unchanged; raw payload gitignored (redistributable). Live open work is tracked in `ROADMAP.md` / `BACKLOG.md`.

Full open work + future: `ROADMAP.md` + `BACKLOG.md`. Per-item ledger (325 and newer): `docs/LEDGER.md`. Deep archive (items 1-324 + pruned wakeups): `docs/history_notes.md`.
