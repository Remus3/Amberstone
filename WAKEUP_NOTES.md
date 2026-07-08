# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05. Only the last 3 sessions kept here.

---

# 2026-07-07 (LIVE-VERIFY 2026-07-06 overlay+DS work in ARAM Mayhem game; Aphelios; engine 1.184.0)

Live-verified the 5-commit range `c51108e1..32132f22` in a real ARAM Mayhem game on Legion:

(1) DS stability (PD->Kraken flip): PASS. Build order byte-identical across levels 5-11 for Aphelios. Incumbent hysteresis code verified wired (build_order.py:384-400, 3% margin). No close-tie case in Aphelios build (PD vs Kraken ~5% gap, outside 3% threshold), but the hysteresis primitive is present and correct.

(2) B45/B46 EHP (Randuin+Steelcaps): PASS. Live-verified via DS /ehp endpoint. Nautilus lvl 11 ARAM: no-items phys_ehp=2527, Steelcaps=3024 (AA-DR x0.95 confirmed), Steelcaps+Randuin=5957. Full ratio: 5957/4813 = +23.8% phys EHP credit. Crit-DR and AA-DR default-ON in compute_ehp (ehp.py:1069-1070).

(3) BATCH B (canvas lock, minimap gold border): CODE CORRECT, VISUAL PENDING. rc-shell running (PID 13512) but title stale ("17:34" from prior game) - still running pre-commit main.js. Commit c51108e1 dropped injectDragRegion from overlay did-finish-load (kept companion-only). Relaunch rc-shell to pick up.

(4) BATCH C (gauges row, stats role, enemy clips): CODE CORRECT, LIVE DATA FLOWING. Enemy spells populated (5 enemies: Flash/Ghost/Barrier/Mark). Gauges CSS = horizontal row (objective_gauges.css:4). Stats role detection reads lc.champion (Aphelios) -> championTags -> Marksman -> "bot" (stats_panel.js:73-78). Live Client Mayhem mode: players[] lacks champion names but detection falls back to lc.champion correctly.

BUGS NOTED (operator "Aphelios builds are wrong"):

A. Void Immolation (Arena prismatic id 223069) is #1 EHP pick for ARAM Nautilus. Should be ARENA-only excluded from ARAM pool. Impact: rank-tank + build-order for tanks recommend unobtainable Arena item.

B. Aphelios crit-capping: engine caps crit at 100% (dps.py:1289) but Aphelios passive (The Hitman and the Seer) converts excess crit chance to AD. After 4 crit items engine treats 5th+ crit as dead stat; real champion gets AD. Impact: DS undervalues crit items past slot 4 for Aphelios specifically.

C. Aphelios rotation-DPS fallback: all 3 laning-scenario phases have basic=0 (weapon-swap kit in lolmath), so DPS falls back to raw_attack_dps * mode_mult (dps.py:1034). Impact: on-hit procs (Kraken, BoRK) may be under-credited; weapon-specific synergies absent.

D. Aphelios passive stat leveling: picks AD/AS/Lethality per level instead of standard growth. DS uses DDragon base growth. Impact: stat curve diverges from real game at higher levels.

DO NOT redo: all 6 commits SHIPPED + verified (17359ca9..32132f22); incumbent hysteresis + EHP credit + BATCH B/C code = correct. The 3 archetype test failures are LOCAL gitignored cs_archetype_picks.json (CI GREEN).

---

# 2026-07-07 (Session reflection + 3 auto-improvements; commits `29fb5b5b` + `ceb2f584` + `e736a896`)

Transcript analysis of 512 sessions (666 MB, June 3-July 7) -> Desktop/reflection-notes.md. Three highest-leverage fixes built:

1. **edit_lint_check.py ruff surfacing** - the PostToolUse hook ran `ruff check --fix` on every edit but silenced output. Now ruff findings are written to stderr so model sees lint errors immediately. Also fixed `py` launcher -> `sys.executable` (was resolving to bare pythoncore with no ruff installed - hook was silently broken for entire history).

2. **core/hot_reload.py auto-restart** - daemon thread polls non-frozen .py mtimes every 2s. On change: py_compile gate, then atomic-write restart_trigger.txt. Wired in web_dashboard.py. 18 tests green. Verified: touch -> new pid in ~10s. Status: ops/runtime/hot_reload.json. Halt: ops/runtime/hot_reload_halt.txt.

3. **.claude/commands/section-j-dispatch.md** - Workflow skill reads OVERLAY_BUILD_MASTER_PLAN.md Section J, dispatches OPEN WPs to parallel worktree agents.

Edge fixes: budget-saver .claude/settings.local.json bypass flags (was missing), Sibling-A .claude/settings.local.json model=rc-main (was claude-fable-5 hitting Anthropic direct), BLE001 blind-exception cleanup.

**NEXT SESSION:** pick from Section J OPEN WPs (E5 doc sweep, F5-L03 inventory stale, F6c park auto-ops gate) - use `/section-j-dispatch` to fan out. Hot_reload + edit lint are auto now - no manual steps. **DO NOT redo:** the 3 improvements are SHIPPED; ruff hook was historically broken (`py` launcher -> pythoncore) - FIXED; Sibling-A is now on budget-saver routing.

---

# 2026-07-06 (LIVE-GATED DRAIN Session 1  -  practice SR; budget-saver smart profile; commits `8c5be61a` + `76411845` + `e36eeaea` + `706d8e20`, LEDGER 809-810)

First drain session ON the budget-saver brain (smart = DeepSeek-primary). Practice SR: Caitlyn + Jinx. B47 Frozen Heart default-ON flip shipped (ENGINE 1.183.0). Bloodsong/Zaz'Zak/Atlas SR-exclude deny shipped (ENGINE 1.184.0 + DDragon inversion tracked). A1/A2 RE-VALIDATED live (League-restart->new lobby->RuneWriter push clean, Flash+Cleanse confirmed). E5: Ctrl+Shift+A overlay ACTIVE toggle works (NOT Alt+Shift+A  -  wrong keys). E6: overlay lead/callouts/choices now feed from 2s poll (was dark in-game). minimap_rect trim calibrated (18px left, 14px top @2560x1440). Accrual rails: G1 HZ-A 52% agreement (below 0.70), G17 Arena shadow 0/20 awaiting_accrual.

Context-shrink: LEAN_CLAUDE.md (80 lines vs 223) auto-swapped by all three shims at launch with crash recovery via try/finally. Biggest quality lever for local model  -  CLAUDE.md+MEMORY.md+hooks were ~1500 lines of context overhead.

**NEXT SESSION:** launch `budget-saver.ps1` (local-first, NOT smart  -  remaining drain items are Tier-0/1). Continue drain at Session 2 (REAL SR matchmade game) or repeat Session 1 practice tool for remaining B-seam eyeballs (B1-B19, B24-B30, H4). The smart profile was $X; local-first saves the DeepSeek plan for real engine turns. DO NOT redo: B47 is SHIPPED (ENGINE 1.184.0, 8052 green), SR-exclude is SHIPPED, A1/A2 re-validated, context-swap is automatic.

---

# 2026-07-06 (RC Budget-Saver SHIPPED - local-LLM fallback for Claude Code; PRs #7 + #8 merged, LEDGER 808)

Operator-directed build (NOT the gemini loop): a local fallback so RC keeps operating when the Claude plan hits 0. Full brainstorm -> spec -> no-placeholder plan -> subagent build -> whole-branch review -> ship. Live game NOT involved. New `ops/budget_saver/`; no frozen file; no DS touch.
- **SHIPPED + PROVEN LIVE (PRs #7 `88061f7f` + #8 `22a053b4`).** claude -> LiteLLM proxy (:4000 /v1/messages) -> ollama_chat/llama3.1:8b local ($0 default) + deepseek escalation + nvidia nemotron fallback. Still Claude Code end to end (skills/MCP/memory/TDD/git); `budget-saver.ps1` = budget-saver mode. e2e proven: claude --print -> proxy -> llama3.1 -> valid tool_use exit 0. 14/14 unit tests, ruff clean.
- **Honest ceiling:** llama3.1:8b drives the loop but is weak on RC's heavy CLAUDE.md context. Live bench (qualify.py): local 2/3 (PASS tier-0/1, FAIL tier-2 math), deepseek 3/3 - confirms the R5 boundary. Local = keep-lights-on; DeepSeek (~50-100x < Opus) for real work. Both cloud keys placed + probed PASS. Isolated venv on Python 3.12 (litellm 1.91.0 needs <3.14; RC is 3.14).
- **Auto-flip wired:** RC-BudgetSaverWatchdog (15-min) + usage_feeder.py (Anthropic cost_report API, opt-in via RC_BUDGET_CEILING_USD) arm/disarm; RC-BudgetSaverProxy autostarts the proxy at logon. HONEST: tracks the API-$ budget, not the subscription plan (no standalone API for that).
- **5 live-verify fixes:** litellm py3.14-incompat (-> venv on 3.12), prometheus_client unbundled, ollama-died-post-pull, qwen emits TEXT-not-tool_calls (-> llama3.1 driver), Claude Code `thinking` param 500s a non-thinking model (-> MAX_THINKING_TOKENS=0). Whole-branch review: 1 critical (installer pulled qwen not llama3.1) + 4 hardening, all fixed.

**NEXT SESSION:** run the live-gated drain (`docs/LIVE_GAME_GATED_SYNC.md`) ON budget-saver to conserve the Claude plan - launch `powershell -NoProfile -File "C:\Riot Commander\ops\budget_saver\budget-saver.ps1"` then invoke the live-gated-drain skill. Use `budget-saver-smart.ps1` (DeepSeek-primary) for any engine-class turn llama3.1 fails. Optional: `setx RC_BUDGET_CEILING_USD <cap> /M` enables $-auto-flip. **DO NOT redo:** budget-saver is SHIPPED + merged (#7/#8); qwen is off the driver path (text-only tools); subscription-plan auto-flip is manual-by-design (no API).
