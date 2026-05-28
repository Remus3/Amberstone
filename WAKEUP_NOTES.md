# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-27 (evening) - item 206 SHIPPED: DDragon + DS patch 16.10.1 -> 16.11.1 + 9 patch-drift test fixes

Operator: "new patch  // check everywhere for updates and commit + push". Live DDragon dropped 16.11.1; RC was pinned at 16.10.1 (cached 2026-05-13). Full refresh chain executed end-to-end. 1 commit `ac83a4b` pushed origin/main `9af3c1a..ac83a4b`; ENGINE_VERSION unchanged at 1.61.0 (data refresh only). DS :8893 restarted via `schtasks /Run /TN RC-DaemonSlayer` -> serves patch=16.11.1 / 172 champs / 705 items. RC :8888 unchanged pid 16064 alive=True mode_key=client throughout.

**Refresh chain:**
- `py scripts/data_pipeline.py all` -> DDragon meta refresh (703 items / 172 champs / 35 spells / 16.11.1)
- `py tools/daemon_slayer_extract.py` -> data/daemon_slayer/16.11.1/{champions,items,scenarios,arena_augments,items_meraki,manifest}.json + current.txt flip
- `py tools/daemon_slayer_abilities_extract.py` -> data/daemon_slayer/16.11.1/champion_abilities.json (171 champs / 927 forms / 99.0% ok_rate)
- `py tools/ddragon_mirror_refresh.py` -> web/data/ddragon/16.11.1/ (577 MB; gitignored) + data/meta_build/ddragon/16.11.1/{champion,item,profileicon,runesReforged,summoner}.json
- Hand-curated artifacts copied 16.10.1 -> 16.11.1: `enchanter_items.json` + `cherry_augments.json` + `mayhem_augment_stats.json` (not auto-generated; cross-patch stable)

**Patch-drift fixes (9 tests):**
- 4 Yunara tests pinned to `DataSnapshot.load(patch="16.10.1")`: Riot lifted Yunara's ARAM disable (aramDamageDealt 0 -> 1.0) in 16.11.1; no champion is currently ARAM-disabled, so engine-invariant zero-multiplier tests pin to the prior snapshot.
- 2 IE-divergence tests pinned to 16.10.1: Riot unified SR / Arena-mirror Infinity Edge AD to 75 in 16.11.1 (was SR 75 vs Arena 55).
- 1 IE-divergence test swapped to Bloodthirster (3072 SR 80 AD vs 223072 Arena 70 AD - still divergent at 16.11.1).
- 1 Phase B Cherry test updated for item 188 Slice C handler (was asserting deleted no-op stub behavior; now covers 4-endpoint PATCH chain + no-augment-id reject).
- 1 smart-quote hygiene allowlist extended: DDragon-delivered `ddragon_items.json` (Riot ships an en-dash) + `agents/agent6_auditor/reports/` (dated artifacts).

**Living docs synced (live patch header only - historical wave anchors at 16.10.1 preserved per `feedback_no_history_rewrite`):**
- BRIEF.md L20: `ENGINE_VERSION 1.61.0 (16.10.1)` -> `(16.11.1)`
- docs/DAEMON_SLAYER.md L5: `patch 16.10.1` -> `16.11.1`
- docs/ARCHITECTURE.md L161: `patch 16.10.1` -> `16.11.1`
- dashboard/routes_dictionary.py docstring: `currently 16.10.1` -> `currently 16.11.1`
- web/js/main.js 5 hardcoded `/data/ddragon/16.10.1/` paths + CHAMPS.version fallback strings -> `16.11.1`

**Verified:** DS suite 4872 passed / 1 skipped / 1 xfailed / 1781 subtests in 67s. RC suite 3674 passed / 1 skipped in 60s. Phase 8 smoke 70/70. `py -m ruff check .` ALL CHECKS PASSED. DS `/health` returns engine_version=1.61.0 / patch=16.11.1 / 172 champs / 705 items.

**Don't-redo (tomorrow-you):**
- The 16.10.1 DS snapshot dir STAYS in `data/daemon_slayer/` indefinitely - 11 DS test files reference it as a frozen historical anchor (CC entries pinned to specific Meraki data state). The 4 Yunara tests + 2 IE tests added this session join that pattern.
- DS `/health` items=705 is the canonical catalog count (incl. Arena mirrors + mode-specific copies); DDragon purchasable subset is 547 + total entries 703 - 3 separate counts, all legitimate. Do NOT flip the README's 547 to 703 / 705.
- Yunara + Zaahen missing from Meraki bulk is HISTORICAL PATTERN for new champs (they were missing at 16.10.1 release too); Meraki catches up within 1-2 patches. Do NOT re-pitch as a bug.
- Hand-curated artifacts (`enchanter_items.json` + `cherry_augments.json` + `mayhem_augment_stats.json`) must be COPIED FORWARD on every patch refresh until either (a) operator decides to update them with patch-specific value drift or (b) they're auto-generated. Their schema_version=1 + patch field tracks the original authoring patch.
- The smart-quote hygiene allowlist for `data/meta/ddragon_items.json` + `ddragon_runes.json` + `ddragon_summoner_spells.json` is now durable; Riot-delivered punctuation in catalog data is NOT authored-source drift.
- `agents/agent6_auditor/reports/` is now in the hygiene allowlist as dated immutable artifacts.

**Carries forward:** All item 205 + item 204 carries unchanged. Mid-game capture for any UI v2.1 page-#11/12/13 still operator-gated (game state mode_key=client at /done time = safe to /clear). 7 prior-session items still in WAKEUP_NOTES (205 + 204 + 203 from item-201 chain) - eligible for archive via `wakeup_prune.py --keep 3` post-this-session.

---

# 2026-05-27 - item 205 SHIPPED: UNIVERSAL_FILES portable bootstrap kit updated 2026-05-19 -> 2026-05-27

Operator: "update the desktop folder UNIVERSAL_FILES, with all the new changes that would apply forward to a project. all tools and methods and watchers". Target = `C:\Users\Administrator\Desktop\UNIVERSAL_FILES\` (6 .md files / NOT a git repo / portable bootstrap kit for fresh Claude Code projects on Windows). Lifted forward all durable patterns proven on RC items 134-204 (40+ orchestrator-merge runs).

**Files updated (out-of-tree, no git commit):**
- `1_ENV_CHECK.md`: 426 -> 621 lines (+195). Checks 15-24 added: drift guards, ADR-008 asset-hash, cost-trace shim, v2.1 tokens, phase8_smoke, bridge watcher cadence, memory state, in-repo skills + mirror drift, scheduled tasks catalog, Phase 3 supervisor stale-code probe. Extended SYSTEM SUMMARY template.
- `2_BOOTSTRAP.md`: 1134 -> 1715 (+581). 14 new slash command here-strings: /verify /run /review /code-review /security-review /loop /schedule /insights /headless-upgrade /process-incoming-lessons /init /update-config /fewer-permission-prompts /keybindings-help. NEW Step 10.5 (mirror tracked commands loop for full 26-cmd set), Step 11.5 (phase8_smoke scaffold), Step 12.6 (ADR-008 asset-hash skeleton).
- `3_MASTER.md`: 1404 -> 2245 (+841). Parts 21-32 appended: orchestrator-merge pattern, AskUserQuestion scope-fork cadence, 7-lever CLEAN wave audit, BACKLOG stale-sweep, v2.1 tokens + 5-phase UI audit ritual, ADR-008 asset-hash, slice-based commits, drift-guard tests, record_anthropic_response shim, HTTP-pull redeploy dance, mojibake byte-repair, updated quick-ref card.
- `4_PROJECT_MIGRATION.md`: 472 -> 598 (+126). 16 gap-analysis items added (drift guards, cost-trace, tokens, mock fixtures, asset-hash, .claude/skills, etc), NEW Steps 4i (drift-guard tests) + 4j (ADR-008) + 4k (cost-trace shim), 4 new pitfalls (verify_generated_reports / no_history_rewrite / backlog_path_stale_check / verify_before_declare_broken).
- `5_NEW_PROJECT.md`: 369 -> 451 (+82). Scaffold items 30-43 (tokens.css verbatim / ui_mock dir / cost-tracker + shim / phase8_smoke / 4 hygiene tests / repair tools / .claude/skills / asset-hash route / 5 feedback memories / docs/cost_trace.md). NEW Q7.4-7.6 (mojibake check / cost-trace audit cadence / drift guard patterns).
- `6_USAGE_GUIDE.md`: 333 -> 461 (+128). Part H (14 new slash commands quick-ref) + Part I (8 new troubleshooting items for caveman ULTRA / subagent verify / Phase3 stale / Git-Bash taskkill / v2.1 tokens / cost-trace / bridge watcher cadence / scope cadence).

Total: +1953 lines across 6 files. All bumped 2026-05-19 -> 2026-05-27. ASCII clean (no em-dashes / smart quotes added).

**Method:** 4 parallel general-purpose agents drafted surgical additions (one per file pairing). Orchestrator applied via Edit/Write to existing files. 6 TaskCreate/TaskUpdate items tracked end-to-end (all completed).

**Don't-redo (tomorrow-you):**
- UNIVERSAL_FILES is NOT a git repo - desktop folder lives at `C:\Users\Administrator\Desktop\UNIVERSAL_FILES\`. Edits there do NOT need git commit. If operator wants version control later, `git init` it as its own repo.
- All 26 slash commands now documented across the 3 files where they belong (2_BOOTSTRAP installs them, 3_MASTER references them in quick-ref, 6_USAGE_GUIDE explains them to humans). Do NOT add new commands without updating all 3.
- The v2.1 token scale (--fs-xs=16 through --fs-display=46 / --hit-min=42) is documented verbatim in 3_MASTER Part 25 + 5_NEW_PROJECT item 30. Future projects scaffolded via /init pick this up automatically.
- ADR-008 unified asset-hash pattern (compute_asset_hash MD5 over web/{js,css,data/ui_mock}/ mtime+size; ?v=<hash> query) is now scaffold item 41. Future dashboards get it by default.
- record_anthropic_response + tracked_anthropic shim pattern documented in 3_MASTER Part 29 + scaffold items 32-33 + drift-guard test item 37. Future Claude API projects auto-cost-trace once they wire the shim.
- 5 new feedback memory files scaffolded as item 42 (verify_generated_reports / no_history_rewrite / backlog_path_stale_check / verify_before_declare_broken / scope_decision_cadence). Future projects get the memory pattern at scaffold time.

**Carries forward:** All item 204 carries unchanged (CI Watchdog + LCU Phase Capture Watcher PLAN.md still gated on operator answering open questions). RC pid=16064 alive=True last_reload_ok=True mode_key=client throughout. No bridge tasks pending. No RC repo edits this session.

---

# 2026-05-26 - item 204 SHIPPED: /insights 2026-05-26-185928 followup - CLAUDE.md +5 sections + 2 scoping docs + edit_lint_check hook + verify-before-declaring memory

Operator ran `/insights` after wrap. Drained the report's actionable suggestions across 2 commits + 1 memory write outside repo. 1 commit `adb2e96` on origin/main `0676407..adb2e96`; non-frozen; non-engine; no DS restart; no RC restart (no route/coach module edits this run). 3 worktree-agent dispatches NOT used this session (single Claude orchestrator + scoping work only).

**Shipped (4 files / +340 / -0):**
- `CLAUDE.md` +5 sections from report: `## Session-End Ritual` + `## Output Constraints` + `## Style Rules` + `## TDD First` + `## Subagent Code Quality` (lines 65-77 + 124-130).
- `docs/CI_WATCHDOG_PLAN.md` NEW (5.4 KB / 88 lines) - scoping ONLY for auto-fix red CI via headless `claude -p` on dedicated worktree at `C:\RC-CIWatchdog\`. 3 open questions block implementation (PR auto-merge policy / bridge escalation envelope / stale-fix cancellation).
- `docs/LCU_PHASE_CAPTURE_WATCHER_PLAN.md` NEW (10.4 KB / 127 lines) - scoping ONLY for replacing champ-select / augment / lobby polling with LCU WAMP push events on Game-PC. 5 open questions block implementation (monitor target by RESOLUTION not index / debounce window / frame format / Cherry urgency / bridge envelope).
- `tools/edit_lint_check.py` NEW (~75 LOC) - PostToolUse hook helper: reads `$CLAUDE_FILE_PATHS`, runs `py -m ruff check --fix` on .py files, byte-scans for U+2014 / U+2013 / U+201C / U+201D / U+2018 / U+2019. Advisory non-blocking exit 0. Uses `chr(0xNNNN)` form in `_BANNED` dict to avoid self-violating the rule (item 154 precedent).

**Local-only (NOT in commit, NOT in repo):**
- `.claude/settings.json` PostToolUse hook entry added at L22-26 calling `edit_lint_check.py`. File is gitignored (`.gitignore:65`); change is LEGION-LOCAL. Operator must replay this edit on Game-PC + Peer if they want the hook on those fleets.
- `C:\Users\Administrator\.claude\projects\C--Riot-Commander\memory\feedback_verify_before_declare_broken.md` NEW - feedback memory: "X is dead / missing / broken / not installed" verdicts need a second independent probe + named stale-doc risk before stating. Indexed in `MEMORY.md` line 34 between `[[feedback_verify_generated_reports]]` + `[[feedback_backlog_path_stale_check]]`. Memory files live outside the repo per `auto memory` system.

**Don't-redo (tomorrow-you):**
- `/wrap` skill drop SKIPPED. Existing `C:\Users\Administrator\.claude\commands\wrap.md` is 7-section superset of the pasted version (git status + push + Game-PC bridge probe + RC restart check + memory updates + session size guard + final summary). Do NOT drop `.claude/skills/wrap/SKILL.md` - would downgrade.
- Pasted parallel-agents prompt was just a copyable quote, no infra to ship.
- CI Watchdog + LCU Phase Capture Watcher IMPLEMENTATION is gated on operator answering the open questions at bottom of each PLAN.md. Do NOT start coding either before that. Both are TDD-first per new `## TDD First` rule.
- New hook helper `tools/edit_lint_check.py` is ADVISORY non-blocking (exit 0 always). Future edits will surface em-dash / smart-quote warnings to stderr but never abort the operator's flow. The drift guard is dual-layered: hook catches at edit-time + `tools/strip_em_dashes.py` + `tools/strip_smart_quotes.py` sweep at audit-time.
- The 5 CLAUDE.md sections are baseline now; do NOT re-pitch a "TDD First" or "Output Constraints" section.
- Smoke-tested the hook on a synthetic em-dash file: detected `em-dash x1` and exit 0. Smoke-tested on the helper itself (clean): exit 0 no output.

**Carries forward:** All item 203 carries unchanged. RC pid 15960 alive=True last_reload_ok=True mode_key=client throughout. No bridge tasks pending.
