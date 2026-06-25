# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-25 (Track-1 red-cleanup - named full-suite reds CLEARED + DS patch-drift found + auto-accept re-enabled)

Continued ledger 616's NEXT (Track 1). All 7 operator-named pre-existing full-suite reds triaged stale-test vs
real-regression (NONE were product regressions) + fixed; 1 commit (`0cdafe9c`, 12 files), CI green (3m50s).
Tier-0/1 (docs + test files; no engine/DS/Share/ENGINE_VERSION). Full suite after = 10 failed / 9414 passed,
and ALL 10 are the pre-existing snapshot_panels Playwright at-scale flake (0 non-snapshot failures); the named
logic reds are GONE. GROUND-TRUTH LESSON: my first check passed the WRONG files (`*_view.py` instead of the
note's `*_dom.py`/`*_e4_counters.py`) and nearly mis-declared the cluster green - the full suite caught it.

- ROADMAP 104KB -> 80KB: relocated 20 shipped entries to docs/ROADMAP_HISTORY.md (3 done UI bullets + 13 overlay
  SHIPPED slices R17-R28 + 4 closed sub-items), breadcrumb under the overlay header. EOL gotcha: pathlib
  read_text collapsed CRLF->LF mid-relocate; re-normalized both to uniform CRLF (git stores LF via autocrlf, diff
  clean -20/+1 + 25/0).
- aram_balance KeyError (COMPLETE 4-file sibling set): ARAM coach _USER_TMPL gained an {aram_balance} slot; added
  the key to ds_pick_consumption + the 3 cc_*/enemy_cc context test format() calls (grepped aram_tenacity= for
  ALL siblings first - the initial fix patched only 1 of 4).
- Fragile live-data guards -> hermetic: auto_accept_pref/route value-assertion replaced with a module-scoped
  byte-untouched redirect-regression guard (the flag is operator-toggleable, a False on disk is legit);
  spell_autopush_e6 first-lock isolated to tmp prefs (live spell_prefs.json mutates by_champ.SR.Caitlyn).
- Stale R30-redesign DOM tests (functionality verified intact in source, NOT regressions): last_match default tab
  = AI Analysis not Build (ledger 604); historical_pgr wiring moved into _historyMatchRowEl (0c0bdc16);
  champ_select counter-picks regex anchored to `_csvRenderSuggestions(` excluding the new NonSr sibling.
- Auto-accept RE-ENABLED (operator request; gitignored, official set_enabled path). New memory
  reference_snapshot_panels_session_browser_flake.

PATCH DRIFT (headline orchestrated NEXT): live League + RC DDragon mirror = 16.13.1 (mirror auto-refreshed
2026-06-24, the unstaged data/meta/* + new 16.13.1/ dir); DS engine current.txt = 16.12.1. The DS patch-refresh
+ patch-keyed precompute (laning/build/HZ) regen to 16.13.1 is the top multi-agent NEXT (SWARM per
reference_patch_refresh_workflow). Track-2 stays operator-gated/live-blocked: CI Watchdog ARM (do-not-flip-blind),
HZ re-measurement (needs real-game shadow + now patch-affected), R30/PGR tail (physical game).

---

# 2026-06-25 (bridge decommission COMPLETED - surviving-ref sweep + 2 live residual fixes + stale-test realign)

Follow-on to LEDGER 615 (the prior session removed the bulk but claimed "every importer unwired" - it was NOT).
Validated end-to-end + finished it so nothing silent-fails. 1 commit (`49b1c9ea`, 176 files), pushed, CI green.
Tier-1 (scripts/agents/tests; no engine / DS / Share / ENGINE_VERSION).

- Swept surviving refs from 15 live files: ops/startup scripts (rc_bootstrap, run_self_healing_watchdog,
  rc_league_watcher, launch_new_system/start_ops/setup_dirs/autostart bats) stopped spawning the deleted
  rc_file_bridge.py; legion_on/off + start_claude + legion_agent_boot dropped removed RC-Bridge* tasks +
  process-bridge-tasks.md; deleted installer install_RC_LegionBridgeDaemon.ps1; purged stale ops/runtime
  bridge/lessons/peer_health artifacts; legacy_index.html dead /api/bridge UI + drift --bridge-note help cleaned.
- 2 LIVE residuals the bulk MISSED (fixed + agents restarted): (A) supervisor bridge-publisher watchdog filed a
  zombie triage task every 6h for the dead peer peer; (B) lcu_agent gated the FU02 team-context POST on the removed
  BRIDGE_SECRET -> champ-select team-context was SILENTLY BROKEN (route is no-auth local-only now; posts unconditionally).
- 4 stale test files mocking removed routes_team_context._bridge realigned (team_context/fanout/lcu_agent_refresh/
  p2w1_dash_c); team-context decommission suite 133/133; full-suite collect 17585 clean.

NEXT (operator wants BOTH next session):
1. FINISH CLEANING the pre-existing NOT-decommission full-suite reds (CONFIRMED red-at-HEAD, not regressions):
   ROADMAP.md over the 80KB budget (relocate shipped entries to docs/ROADMAP_HISTORY.md); stale DOM tests (last_match
   Build-tab-default, champ_select counter-picks, historical_pgr wire) vs intentional UI redesigns; live-data prefs
   (auto_accept_pref/route, spell_autopush_e6); coach aram_balance KeyError (cc_*/enemy_cc) + ds_pick_consumption ARAM
   subfails. Triage stale-test vs real-regression per cluster (CI clean-checkout passes snapshot panels).
2. RESUME pre-decommission active ROADMAP work: CI Watchdog ARM (item 204, operator-gated, do-not-flip-blind - create
   C:\RC-CIWatchdog\ worktree + repo auto-merge + --arm in RC-CIWatchdog.xml); HZ laning precompute-vs-Haiku agreement
   RE-MEASUREMENT on the corrected 16.12.1 tables (item 614 NEXT, gated); R30/PGR live-gated tail.

---

# 2026-06-24 (CI Watchdog dispatch wiring - item 204)

Interactive operator session. R30 UI review complete + no live game -> presented the headless-buildable,
non-blind ROADMAP candidates via one framed AskUserQuestion; operator picked the CI Watchdog dispatch wiring.
2 commits pushed (`ade16c7f` wiring / `cb96be1f` ROADMAP state), CI green. Tier-1 tooling; no engine/DS/Share.

- Replaced the documented dispatch STUB at `tools/ci_watchdog.py:330` with a real, dry-run-default dispatch:
  pure `plan_dispatch()` returns the ordered 10-step (label, argv) plan; `execute_dispatch(arm=)` surfaces it
  (dry run, runs/mutates nothing) or runs it - worktree sync -> tool-restricted `claude -p` fix -> frozen guard
  (BETWEEN fix + push) -> push -> `gh pr create` -> `gh pr merge --squash --auto`. `main()` gained `--arm`; the
  bare invocation is READ-ONLY (logs the plan to audit.jsonl, mutates no sentinel/attempts/pr state). Headless
  fix whitelist-gated (no `--dangerously-skip-permissions`; Write + git push disallowed; cannot push). +8
  RED-first tests (27 total), ruff clean repo-wide.
- Live-verified: a bare dry run `skip_stale`-skipped the 4 then-stale reds (HEAD green) with the sentinel left
  absent; `execute_dispatch(arm=False)` printed the exact plan + the whitelist-gated claude command.

NEXT (operator ARM step, do-not-flip-blind): create the `C:\RC-CIWatchdog\` worktree + enable repo auto-merge
+ append `--arm` to `ops/RC-CIWatchdog.xml` + soak `audit.jsonl` on a live red main. DON'T re-wire the dispatch
(done) - only the ARM remains. Full detail: LEDGER 613 + `docs/CI_WATCHDOG_PLAN.md` "Build status".

---

# 2026-06-24 (R30 IN-GAME continuation - active-match follow-ups: companion header reflow + ARAM ward-heat hide)

Interactive operator session continuing ledger 611. Cleared the named active-match follow-up tail. 2 feature
commits + 1 CI-lint fix, all pushed; 14/14 in `test_active_match_review_r30.py`; each slice RED-first + a
5-phase UI-audit subagent PASS + live-:8888 recon. Tier-1 frontend; no engine / DS / Share / ENGINE_VERSION.

- SLICE 1 header reflow (`5ef87dd0`): the in-game header's two fixed-width no-wrap rows overflowed the 923
  companion (row 1 ~1224px) and `body{overflow:hidden}` CLIPPED the heartbeat + vision pills off-screen. A
  single `@media (max-width:1200px)` block in header.css wraps `.header-row` + drops the heartbeat
  `margin-left:auto` -> companion wraps to 2 clean lines (worst 778 <= 923); 1920 desktop unchanged (hb 1902).
- SLICE 2 ARAM ward-heat hide (`c1410a1b`): the MAP-pane ward-heat strip renders 4 lane cells (TOP/JG/MID/BOT)
  x2 teams; ARAM is single-lane (6/8 cells dead). `_renderWardHeatTick(ctx)` now `display:none`s `#am-ward-heat`
  in ARAM (restores on mode switch); SR/Arena keep it; ARAM vision still shown via the MAP intel MIA roster.
- CI-UNBLOCK (`678b4c95`): prior-session `test_champ_select_review_r30.py` had a ruff B023 (pageerror lambda
  closing over the for-loop `errors`); CI runs `ruff check .` REPO-WIDE so it was red on every push since 611
  incl. mine, while each slice's file-SCOPED ruff was green. Fixed via default-arg binding. DON'T-REDO: at
  /done run repo-wide `ruff check .`, not a file-scoped check.

NEXT: the R30 in-game named tail is CLEAR. The OVERLAY was reconned clean (low yield, RC2-mined; the empty
`#am-mmrect` frame is coordinate-gated = no-op). Only LIVE-GATED items remain (need a physical game): the E.1
ACTIVE knob physical press + the `RC_COMP_HP_LEAN` default-ON flip. Harness + gemini_out.txt at `ops/runtime/ui_recon/`.
