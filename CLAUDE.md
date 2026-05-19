# Riot Commander - Agent Context

Live League / TFT coaching dashboard. Reads Riot Live Client API, calls Claude Haiku for coaching and Sonnet for vision, writes JSON to `data/`, serves `:8888` HTTPS dashboard on Game-PC's secondary display. RC is tkinter-free; Daemon Slayer (`:8893`) computes real DPS math per champion.

> **Living docs (read at session start):** `docs/ARCHITECTURE.md` · `docs/OPERATIONS.md` · `docs/BRIDGE.md` · `ROADMAP.md` · `docs/API.md`
> **Deep references:** `docs/DAEMON_SLAYER.md` (DS engine · 547 items · ENGINE_VERSION 1.9.0 · all 6 archetype scorers wired) · `docs/AGENTS.md` (Phase 3 framework) · `BACKLOG.md` (aspirational)
> **Architectural decisions:** `docs/adr/` - before re-litigating a past choice, check here first.
> **Dated artifacts** in `docs/_archive/` (excluded from ripgrep searches).

## Topology

| Machine | Tailnet / IP | LAN IP | Role |
|---|---|---|---|
| **Legion** | `legion-rc` / `100.70.22.55` | `192.168.8.230` | Runs RC, supervisor, vision server, web dashboard |
| **Game-PC** | `gamepc-rc` / `100.95.66.128` | `192.168.8.237` | Runs League; Chrome on secondary display (panel is 1920×1280 native @ 100% scale) shows the dashboard |
| **Peer** | `peer-host` / `<peer-tailnet-ip>` | - | Cross-Claude peer; RC↔Peer bridge |

All three in tailnet `tailc150de.ts.net`. Prefer tailnet hostnames. Vision runs in-process at `127.0.0.1:8889`.

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
- **Restart via `restart_trigger.txt`** (write any content; supervisor clears + restarts within ~5s).
- **`SCRIPT_DIR` in `app/__init__.py` MUST be `Path(__file__).parent.parent`** (package layout).
- **State assumptions explicitly before coding.**
- **No em-dashes or en-dashes - ever (7-bit ASCII authored content).** Hard rule across Legion / Game-PC / Peer, in *all* authored text: code, comments, docstrings, `.md`, writeups, commit messages, WAKEUP/ROADMAP/CLAUDE, bridge messages, chat output. Use ` - ` (spaced hyphen) for a clause break, `-` otherwise. Also avoid smart quotes (U+201C U+201D U+2018 U+2019) and en/em dashes (U+2013 U+2014); stay ASCII. **Why:** Windows PowerShell 5.1 `ParseFile` ANSI-decodes a no-BOM `.ps1`, turning a UTF-8 em-dash inside a double-quoted string into a U+201D smart-quote that the tokenizer treats as a string terminator -> cascading parse failure (2026-05-18 `gamepc_boot.ps1` incident); also a standing operator style rule. **Retroactive purge done** (2026-05-18, `tools/strip_em_dashes.py` - reusable for drift checks): em+en dashes stripped repo-wide incl. the functional `"-"` no-data sentinel in code/JSON (operator-approved behavior change - empty dashboard cells render `-`). **NOT swept** (immutable history / non-source): `*.log` + rotated `*.log.N`, `docs/_archive/**` + dated artifacts, `.jsonl` ledgers, binaries, `.pyc`/`.git`. Smart quotes are rule-banned going forward but not yet retroactively swept (separate operator-gated pass).
- **Frozen files** (do not modify without explicit user approval):
  `main.py`, `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`,
  `core/game_snapshot.py`, `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`,
  `app/__init__.py`, `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`,
  `tools/bridge_watcher_classify.py`,
  `tools/bridge_watcher_actions.py`, `tools/bridge_watcher_action_prompt.md`,
  `tools/bridge_watcher_history.py`, `tools/bridge_watcher_install.ps1`,
  `tools/bridge_watcher_hook.ps1`, `tools/bridge_watcher_config.json`,
  `tools/bridge_post_result.py`, `tools/bridge_pull_tasks.py`,
  `tools/process-bridge-tasks.md`, `tools/diagnose.md`, `tools/caveman.md`,
  `dashboard/routes_bridge_pending.py`, `ops/RC-BridgeWatcher.xml`.

## Restart workflow

```
echo restart > restart_trigger.txt
```
Verify: read `ops/runtime/health.json`, confirm new `pid`, `alive=true`, `last_reload_ok=true`.
Hard fallback: `taskkill /F /PID <pid>` then `restart.bat`.

## Session workflow

Scoped sessions - each focused task is one session.
- **End:** commit + update `WAKEUP_NOTES.md` (keep last 2-3 sessions at full fidelity; archive older to `docs/history_notes.md`) + push.
- **Start:** `/clear`, bootstrap from CLAUDE.md + MEMORY.md + git log + WAKEUP_NOTES + `docs/ARCHITECTURE.md` + `ROADMAP.md` (all 4 under 800 lines total).
- `/clear` between Tier items, between coding/reviewing modes, between focus-area switches.

## Web dashboard

`web_dashboard.py` at `:8888` HTTPS. Key endpoints: `/`, `/api/state`, `/api/health/all`, `/api/bridge/pending`, `/api/input`, `/api/command`, `/api/ds-preview`, `/metrics`. Viewed in Chrome on Game-PC secondary at `https://legion-rc:8888/` - design baseline is **standard 1920×1080 with Chrome chrome present** (titlebar + URL bar + bookmarks bar visible, usable viewport ≈ 1920×~920). F11 fullscreen is optional and recovers the chrome chrome - `main` flex-grows into the extra height (no layout pinned to 1280). Cert via `tools/regen_rc_cert.ps1`. Each machine has its own Anthropic API key (`riot-commander-legion`, `riot-commander-gamepc`, `riot-commander-peer`).

## Scheduled tasks (Legion)

Key: `RC-Supervisor` (logon, Administrator, HIGHEST) · `RC-VisionServer` (startup, SYSTEM, HIGHEST) · `RC-BridgeWatcher` (logon, daemon). Full list + Game-PC tasks: `docs/OPERATIONS.md`.

## Vision pipeline

Game-PC `gamepc_screen_agent.py` POSTs frames every 2s to `:8889/upload-frame`. Coaches call `modes.shared_vision._capture_screen()` → GET `:8889/latest-frame`. **`_run_vision()` gates on `_fetch_game_data() is not None`** - vision never fires during lobby/idle. Tiered: OCR first, Sonnet escalation for misses. Calibrate `data/vision_regions.json` to expand OCR coverage.

## Mode detection

`game_reader.py._process_game()` → `core/game_snapshot.py` → mode strings. ARAM Mayhem (`KIWI`) → `MODE_ARAM`.

## Where to find current state

- Live PID + mode + health: `ops/runtime/health.json`
- Current game state: `data/{aram,arena,brawl,tft}_coaching_data.json`
- Recent activity: `logs/YYYY-MM-DD.log`
- Architecture / module map: `docs/ARCHITECTURE.md`
- Ops commands + restart: `docs/OPERATIONS.md`
- Bridge wire format + watcher: `docs/BRIDGE.md`
- Open work: `ROADMAP.md` · Aspirational: `BACKLOG.md` · History: `docs/history_notes.md`

## Useful commands

Full reference: `docs/OPERATIONS.md`. Quick-start:
```
python -c "import json; print(json.dumps(json.loads(open(r'ops/runtime/health.json').read()), indent=2))"
echo restart > restart_trigger.txt
curl -k https://127.0.0.1:8888/api/health/all
```

## Memory frontmatter - cross-project sync fields

Standard memory files carry `name`, `description`, `type`. Two optional fields
are valid for memories that should ride the RC↔Peer bridge (Phase 1 schema,
`docs io RC peer/RC_PHASE1_LESSON_SCHEMA_2026-05-02.md`):

```yaml
cross_project: true          # opt-in; default false. Only feedback/reference/project eligible.
applies_when: "<trigger>"    # required when cross_project=true; free-form grep-able phrase
does_not_apply_when:         # optional list; receiver skips if any entry matches local context
  - "<neg-trigger>"
```

`type: user` memories are never eligible. Default is OFF - author decides at write-time.
False-negatives are recoverable (edit frontmatter later); false-positives are bridge spam.

## Testing Discipline

Always run the full test suite after schema changes, engine version bumps, or item-effect additions. Avoid data-fragile cross-item comparison assertions; prefer assertions on computed quantities. When stubbing methods accessed via class, wrap with `@staticmethod` correctly.

## Windows Environment Notes

Claude Desktop on Windows may be installed via the Microsoft Store (check `%LOCALAPPDATA%\Packages`) in addition to standard install paths. Use `pythonw.exe` (not `python.exe`) for background daemons to avoid flashing console windows.

## Daemon Slayer Batch Workflow

When continuing Daemon Slayer work: pick the next batch from ROADMAP, implement schema/engine changes, add tests (target green before commit), bump engine version, commit + push, verify live, update hand-off notes.

## Session Wrap-up

When invoked with `/done` or asked to wrap a session: (1) audit pending changes, (2) commit and push, (3) update ROADMAP/CLAUDE/README if relevant, (4) process lessons/WAKEUP_NOTES, (5) run bridge probe, (6) print final banner. Run independent steps in parallel.

## Active priorities

99. ✅ **2026-05-19 - overnight autonomous run EXECUTED end-to-end (Phases 0-3 complete; 49 commits `9d1d8de`..`f6d0e02`, pushed; ENGINE 1.5.0->1.9.0; CI green). Was: corrected /insights regen + single-prompt overnight run QUEUED (`0bf2e3c`, pushed; prep only, no code/restart).** /insights froze on the s100-s185 window (claimed ENGINE 0.9.x->0.25.0, tests 161->929, 611 commits); verified live (ENGINE 1.5.0, DS 2283/748/0, RC 1457/0, 760 commits, patch 16.10.1, 547/705 items, 172 champs, 6 scorers wired no fallbacks) and wrote a corrected LOCAL sibling report `C:\Users\Administrator\.claude\usage-data\report-corrected-2026-05-19.html` (NOT in repo; original `report.html` untouched, it is a fixed system artifact). NEXT SESSION executes `NEXT_SESSION_QUEUE.md` end to end: Phase 0 = 7 setup tasks (PostToolUse docs-skip hook lever; ship-batch one-pass extension; LLM-cost tier trace+reconcile; corrected-report re-verify; parallel worktree multi-batch pipeline; self-healing cost/health watchdog; test-first autopilot) -> Phase 1 >=4h iterative DS audit (all engine math, every wireable sim, pick/ban vs itself + interacting systems, enemy-team 1-6 item variations across timeframes/levels, scope+apply trivial nuances) -> Phase 2 backlog drain (stop the DS loop only at 10+ consecutive no-change iterations, track+report the streak) -> Phase 3 full every-line/every-doc/every-trail conventions audit. **Operator AUTHORIZED full perms incl. every frozen file for that run** (the `NEXT_SESSION_QUEUE.md` header is the explicit grant). **Don't-redo:** the queue doc is intentional and authoritative, NOT drift - do not treat its presence as stale; the full WAKEUP entry + the queued kickoff prompt carry the detail. See memory [[feedback_verify_generated_reports]].

98. ✅ **2026-05-19 - Phase3-Supervisor false-anomaly fix + repo `\r\r\n` EOL purge + caveman full->ultra (`399fe89` `d893797` `e3b8b02` `eb904dd` `b7c23c6`, pushed; no RC restart).** `last_result=2147946720`=`0x800710E0` is Task Scheduler refusing a duplicate `IgnoreNew` singleton while the boot instance lives; rc_facts.py now suppresses it only when `state==Running`. Root cause of the giant diffs: `core.autocrlf=true` re-adding already-CRLF blobs wrote CR-CR-LF (`\r\r\n`) into 21 tracked .py; all purged to LF (rc_facts in `399fe89`, 19 more incl. 13 frozen in `eb904dd` - operator-authorized, pure-EOL, RC suite 1457/0), guarded by `.gitattributes *.py text eol=lf`. caveman fleet default flipped **full->ultra** (`b7c23c6`, operator, overnight-headless). **Don't-redo:** EOL-only commits are message-explained, NOT pollution - keep the split; do NOT revert the eol=lf guard or the ultra flip. **Flagged:** MEMORY.md 29 `\u2192` arrows (separate ASCII sweep); guard is .py-only (broaden only on operator call); peer ultra apply unverified. See memory [[reference_repo_eol_crlf_guard]].

97. ✅ **2026-05-19 - CLAUDE.md Active-priorities prune (`85624c3`, pushed; docs-only, no restart).** Operator-approved latency lever. The ledger had grown to 251,618 bytes reloaded into agent context EVERY turn; items 1-93 (100 entries incl. sub-letter ones) relocated VERBATIM to `docs/history_notes.md` (zero rewrite; ROADMAP-95 "keep history" honored via archive-not-delete). Items 94-96 kept inline at full fidelity + the new `### Settled - do not re-litigate` digest below preserves the load-bearing don't-redo guardrails in the hot path. CLAUDE.md 251,618 -> 20,179 bytes (~231 KB off every turn). **Don't-redo:** items 1-93 live in `docs/history_notes.md` verbatim (under the 2026-05-19 archive header), NOT lost - do NOT restore them inline or treat their absence as drift; the Settled digest is the inline pointer. cavemem was evaluated as a latency fix and DEFERRED (memory-recall, not the per-turn bottleneck) - do NOT re-pitch it (see item 96 + memory `feedback_caveman_default_fleet`).

96. ✅ **2026-05-19 - caveman full = fleet-wide session default (`tools/caveman_default.py` + `.claude/settings.json` SessionStart hook; Peer + Game-PC dispatched via bridge; no code/restart).** Operator reviewed the caveman ecosystem (caveman / cavemem / cavekit / cavegemma). Only **caveman** maps to "default on load": a 2nd SessionStart hook (alongside `rc_facts.py`) injects the full-level directive every session - exemptions stay normal prose (clarifying Qs, AskUserQuestion forks, errors-needing-context, per-page UI-audit ritual); "normal mode" disables per-session. Level = **full over ultra** (operator-confirmed; full keeps the one "why" clause for at-a-glance sanity-check, ultra strips it). **cavemem deferred - do NOT re-pitch as a latency fix:** it is memory-recall (SQLite+FTS5+MCP+worker), duplicates existing auto-memory / WAKEUP / history_notes / bridge-lessons, and does not touch the real per-turn bottleneck = this CLAUDE.md "Active priorities" ledger (~90 completed entries reloaded every turn, archival lapsed vs the session-workflow rule) + the full-pytest PostToolUse hook. cavekit = available skills only (not a default-on thing); cavegemma = N/A (62GB local Gemma LoRA, fleet runs Claude). Peers dispatched: gamepc `task-2f32e05de2e6`, peer `core.bridge.send` ok. **Don't-redo:** caveman-default is intentional, not drift - do NOT revert; cavemem/cavegemma are closed for this purpose; the real latency lever (prune ledger to `docs/history_notes.md` + scope the pytest hook) is operator-gated (history-keep per ROADMAP-95) and flagged, not folded in. **Operator-gated:** peer rollout unverified - if a future session sees only Legion has the hook, `/process-bridge-tasks` may not have auto-fired on Peer/Game-PC ([[project_bridge_skill_peer_autoinvoke_unreliable]]); nudge the peer Claude.

95. ✅ **2026-05-19 - sync-all-md skill self-fix + draft tool L (the community fork) triage (`c923eb0` `d12a98a`, pushed; no code/restart).** Operator housekeeping off one terse message. **(a)** The flagged "CHANGELOG broken ref" + "`.claude/commands` vs `tools/` sync-all-md drift" were ONE root cause - `/sync-all-md` self-staleness. Did NOT do the literal "repoint 3 cites": s222 already fixed the real cross-refs (the live `Completed work:` pointer is correct); the 4 residual `docs/_archive/CHANGELOG.md` hits are session-ledger NARRATIVE (2 literally describe the s222 fix) - repointing = history rewrite for zero gain. Fixed at source: retired the stale flag in skill §6 + §10 banner; inverted §9's backwards self-mirror precedence (it had the gitignored `.claude/commands/` copy winning, which would re-inject em-dashes into tracked `tools/` and undo s244) so the tracked canonical wins + added a no-em-dash guard; re-mirrored tools->commands (both byte-identical + ASCII-clean, verified). Existing CLAUDE.md/ROADMAP.md ledger prose deliberately NOT edited (operator chose "keep history" via AskUserQuestion). **(b)** draft tool L (the community fork) liftability-triaged into BACKLOG "Research / inspiration": FUTURE = the Elo log-odds draft-composition aggregator (the team-vs-team layer `dashboard/routes_pickban.py` lacks; composes on `core/smoothed_rates.py`, not a duplicate); CLOSED negatives recorded (no license on fork OR upstream `draft tool L`, aggregator-D-scrape data dead-end, "+" fork adds zero math) - never re-research. **(c)** New memory `feedback_ds_coverage_prose_recompute` - DS champ-coverage %/match-row prose is a DS-batch-session docs-sync job, never recomputed in a general sync (the 4 override registries use a nested schema a flat count mis-parses). **Don't-redo:** sync-all-md self-refute is fixed - do NOT re-flag the CHANGELOG ref or re-litigate §9; draft tool L (the community fork) is triaged - do NOT re-research; the coverage/match-row prose is intentional prior-batch state, not a bug.

94. ✅ **2026-05-19 - DS per-level stat-growth correctness fix: linear -> Riot quadratic (`fd80bf3` + docs-sync `17c782e`, pushed; ENGINE_VERSION 1.4.0->1.5.0).** Found cross-checking DS math vs lolmath `@lolmath/calc`. `agents/daemon_slayer/stats.py` scaled champion per-level base stats LINEARLY (`base + perlevel*(level-1)`); Riot is QUADRATIC (`base + perlevel*(level-1)*(0.7025 + 0.0175*(level-1))`) - curves coincide ONLY at level 1 (mult 0) and level 18 (mult exactly 17.0), so every per-level base stat (hp/mp/regen/armor/mr/ad) was over-stated for levels 2-17; a real bug, not a modeling choice. Fix: new `growth_multiplier()` + `scaled()`, the 8 `CHAMPION_SCALING_RULES` repointed off the deleted `linear`; `attack_speed_scaling`/`clamp_level`/structure untouched (AS was already correct Riot math); single application point `engine._scale_champion_base` (no double-scaling); the per-level ability lambdas in `_effects_data.py` are intentionally linear ability scalings and were correctly left alone. **TDD + proof-first (don't re-verify):** RED `test_stats.py` with hand-derived Riot values -> implement -> engine hand-proven correct BEFORE any rebaseline (16 stat curves Garen/Lux/Aatrox/Malphite x hp/ad/armor/mr @ L1/6/11/13/18 match `base+perlevel*growth_multiplier(level)` exactly; DPS/EHP pipeline traces exact; Garen/Lux HP match known in-game). Only 6 DS tests drifted (far less than feared): 4 genuine mid-level pins rebaselined to corrected output + 2 pre-existing fragile exact-float assertions made tolerant - all intended, do NOT re-investigate. ENGINE 1.4.0->1.5.0 + 14 version pins. Adjacent: corrected the stale/backwards pen-pipeline comment in `ability_dps.py:1142` to match `effects.effective_target_armor` (flat-reduction->%-reduction->%-pen->flat-pen); no pen code changed. **Verified:** DS 2283/748/0, wider RC 1457/0; production :8893 restarted (RC-DaemonSlayer task) -> serves 1.5.0, Garen L11=1549.95 (in-game 1550)/L18=2356 (unchanged endpoint). Living docs synced `17c782e` (ENGINE 1.5.0 + DS tests 2283 in CLAUDE/DAEMON_SLAYER/README/BRIEF). **Don't-redo:** bug fixed+proven; do NOT re-pitch touching AS scaling (correct) or pinning the 2 float-noise values (tolerant assertions are right); the 6 rebaselines are the intended consequence. **Flagged (not blocking):** DAEMON_SLAYER coverage prose "196/125,73%" + BRIEF "2,851 matches" left as prior-batch state (unrelated to this fix; a correct recompute is a DS-batch docs-sync job - the 4 registries use a nested `_meta`/`default`/overrides schema, a flat count mis-parses it); pre-existing broken ref `docs/_archive/CHANGELOG.md` + `.claude/commands` vs `tools/` sync-all-md.md drift surfaced for operator, not auto-fixed.

### Settled - do not re-litigate (items 1-93 relocated verbatim to `docs/history_notes.md` on 2026-05-19; read that archive for full context before re-opening any line below)

- **Phases 1-7, 2.1-2.4, 3, 4-6, FU01/FU02/FU04 all shipped; the 6-scorer archetype-expansion plan (carry/tank/bruiser/mage/assassin/enchanter) is fully wired and the dispatcher has no fallbacks.** FU03 was superseded by FU04. Do not re-plan these or re-pitch a scorer.
- **DS conditional-target-state arc is operator-CLOSED (s232).** Part-2 live target-state plumbing is shelved permanently; an s232 saturation guard exists. Do NOT re-pitch Part-2 or re-scan for conditional candidates.
- **DS block_index/form_index/max_priority/combo_sequence pure-data registries were swept s223-s232 and are provably saturated** (machine-guarded). Further growth needs a schema lift, not uncovered-champion scans. The reusable pre-filters (`tools/ds_*_prefilter.py`, `ds_block_scanner.py`) are durable for patch re-extracts. Never `--force` a Meraki re-extract (the `latest` endpoint is mutable).
- **AUTONOMOUS_AUDIT s5 menu is fully exhausted** (the effects.py facade split shipped s246). Do NOT re-pitch an effects.py re-merge, an `__all__`, or a FastMCP/SDK rewrite of the stdlib MCP servers.
- **Keystone fixed + live-proven (item 87): ARAM Mayhem reports queueId 2400** (not 920). The phase-driven view-router was proven correct - do NOT re-pitch a router change. The `cs.is_aram` rendering path is item-87-preserved.
- **The augment LCU/:2999 API is a confirmed dead-end** (no capture-free augment API mid-game). Augment-OCR into the coach is the proven path. Do NOT re-pitch an LCU augment API.
- **Game-end 0x50 BSOD root cause = the continuous DXGI screen-agent** (stays DISABLED). On-demand `mcp__gamepc__capture_monitor` is the separate BSOD-clean path but stays operator-gated ("now" / "got it"); re-confirm after Vanguard/League updates.
- **`core/build_order.py` no-double-unique rule is engine-authoritative** - do NOT add a family map (a guard test fails on any family literal); the engine has 6 unique-passive families, not 3.
- **Research-list triage CLOSED negatives (do NOT re-research):** every LCU client/codegen repo is inferior to RC's lockfile client; KebsCS is the reference catalog only (no license - do not vendor); the corpus has ZERO Arena/Cherry/Mayhem lobby-create payloads (a bespoke payload must come from live LCU capture); `.rofl` full-parse is a dead-end (Match-V5 SQLite is the substrate); ML win-predictors / CV-minimap / voice / `riot-offline-mode` are all CLOSED; Pengu `league-client-mcp` = NO (thinner than RC's client).
- **`core/smoothed_rates.py` is the shared Laplace/shrink primitive**; the s220 PGR 0-100 score is deferred to ROADMAP-S3 - do NOT pre-build it.
- **Brawl mode is retired from champ-select** (s214); legacy brawl backend is left as deadcode for a separate cleanup pass.
- **The Riot Personal key is valid and in-scope.** Match-V5 403/empty on event modes (ARAM Mayhem `gameMode=KIWI`, queue 2400) is EXPECTED, not a key fault; event-mode Match-V5 timeline placeholders are correct and permanent.
- **`web/js/dashboard.js` is dead code** (no `<script>` reference; only `/js/main.js` loads). The `dashboard.js:5055` `_replayQueueLabel` 920 bug is confirmed-dead legacy - leave it.
- **ADR-008 unified asset-hash:** editing `web/{js,css}/panels/*` auto-reloads via `compute_asset_hash` - no RC restart for asset-only changes.
- **No-em-dash retroactive purge is done** (s244 `tools/strip_em_dashes.py`, reusable for drift checks); the functional `"-"` no-data sentinel is operator-approved. The smart-quote retro-sweep is NOT yet done (separate operator-gated pass).
- **Live DS truth = `data/daemon_slayer/current.txt` + `agents/daemon_slayer/__init__.py` + `/health`** (do not trust ledger recollection of patch/ENGINE). DS coverage %/match-row prose is a DS-batch docs-sync job, never recomputed in a general sync (nested registry schema; a flat count mis-parses) - memory `feedback_ds_coverage_prose_recompute`.
- **Biggest pending non-engine item: the s220 aggregator-G-style Post Game Review reframe** (UI; operator-decided scope - single-match richer layout, the 0-100 score is an RC heuristic over enriched stats with NO Claude/Riot dependency; staged S2-S5, each its own session plus the per-page UI-audit ritual). Other pending: Legion 1-PC consolidation (decided s169, option B, still pending); the one-off 101.qq.com Game-PC CDN capture (FUTURE). Live open work is tracked in `ROADMAP.md` / `BACKLOG.md`.

Full open work + future: `ROADMAP.md` + `BACKLOG.md`. Completed work: `docs/history_notes.md`.
