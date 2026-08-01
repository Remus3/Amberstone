# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-31f - LANE-RESEARCH REFILL (headless lane 5): 2 stale strikes, id-registry fix, cdragon catalog torn down.

## Start here next session

**A RESEARCH LANE IS RUNNING RIGHT NOW - it is real work, not a test artifact.** Its run_id is
the unhelpful string `probe` because the merger session fired it BY ACCIDENT while trying to
read the lane lock: `fire_lane` is the only lock-state call exposed, and it does not merely
read - it reclaims a stale lock and launches. It was left running deliberately (the standing
operator directive is to keep a lane running) rather than killed. Treat its output exactly like
this entry's: merge `lane/research` when it lands, never merge from the worktree. Probe with
`curl -s --ssl-no-revoke https://legion-rc:8895/api/loop-status` (NEVER `-k`). **Do NOT call
`fire_lane` just to read lane state** - that is exactly what caused this.

This was a REFILL pass on `lane/research` (Mission Control lane 5), docs-only, no live game.
MERGED to main 2026-08-01 by the merger session (the 2026-07-31e entry below, which fired
this lane and then wrapped). Tier-0 docs; no engine, no Share, no restart. Detail in LEDGER 1141.
The lane exited code=0 at 23:58 after a ~15 min run; the RECLAIMABLE lock seen the next morning
was the 05:57 reboot clearing pid 14692, NOT a crash - the work was committed and pushed first.

## What shipped (all docs)

- **RM-128 filed** (cdragon `queues.json` grounds the hand-maintained `core/queue_modes.py:28`
  map + a drift guard; ITEM-87 SAFE - `core/game_snapshot.py` detects by gameMode-STRING, never
  queueId). Acceptance: a test asserting every `QUEUE_ID_TO_MODE_KEY` id still exists in a fresh
  `queues.json` with a consistent `gameSelectModeGroup`. Lane 6 or 7, Tier-1.
- cdragon `lol-game-data` 7-file teardown filed in `BACKLOG.md` (F2/F3 trigger-gated, F4/F5
  deferred, F6/F7 REJECT-recorded). License cleared (Riot data, no copyleft).
- Struck the STALE DDragon 16.15.1 patch-refresh row (shipped 2026-07-30, item-1130 / `9df58480`;
  live `/health` = 16.15.1, worktree clean).
- Fixed the `docs/DS_SWEEP_TRACKER.md` "next free" pointer: was RM-119 (stale), now RM-129.
- Decided the `tft/` U+2192 ASCII row: 24 arrows, all display-only, STRIP-SAFE, acceptance-bearing.

## Do NOT redo

- Do NOT re-run the DDragon 16.15.1 patch refresh - it is DONE (item-1130). If you see fake
  ddragon suite failures, that is a NEW dirty MAIN tree per `reference_dirty_ddragon_tree_fakes_49_failures`,
  not this row.
- Competitor-lift research is RETIRED/drained 4x (ROADMAP RM-01) - the cdragon teardown was Riot
  DATA, not a competitor; do not treat it as re-opening that lane.
- Before taking a new RM id, run the grep recipe in `DS_SWEEP_TRACKER.md` - do NOT trust ROADMAP prose.

## Next

Lanes have well-formed work waiting: RM-128 (lane 6/7), the tft-arrow strip (lane 7), the six
stale-process restart-owner gaps (`BACKLOG.md`, lane 7), the DS RM-118 4 wireable seams (lane 6).

---

# 2026-07-31e - DESKTOP INGEST PHASE 1 (12 files classified) + research lane FIRED.

## Start here next session

The research lane this session fired has since COMPLETED (run_id `ingest-580bb7d6`, exit 0,
~15 min) and its branch is MERGED - see the 2026-07-31f entry above. The lane lock reads
RECLAIMABLE only because the 05:57 reboot cleared its pid; release it before firing another.
Status: `curl -s --ssl-no-revoke https://legion-rc:8895/api/loop-status` (NEVER `-k`; mkcert
CA has no CRL/OCSP).

**The remaining ingest work is RM-127**, and its two input files were deliberately LEFT on
the Desktop because the row cites them as its working input: `First-Pass.md` (105 KB, 155
operator note pairs) and `First-Pass-Addendum.md` (13 KB). Everything else is in
`Desktop/_ingested/` (10 files, reversible - the operator deletes that folder themselves).

## What shipped (`7cd9a812`, Tier-0 docs only)

All 12 Desktop planning files classified against ground truth; **zero duplicates filed**.

- **RM-121 CLOSED + relocated.** It read "items 1-3 DONE, two files left" for three days
  after LEDGER 1094 closed item 4 - the exact stale-ROADMAP class LEDGER 1093 named
  ("the stale artifact was not the digest, it was ROADMAP.md"). BOTH stale copies fixed
  (ROADMAP.md pointer + the `ROADMAP_HISTORY.md:28` copy), and the authoritative R217
  narrative retagged off `[WIP]`. That relocation also cleared a live drift_guard breach:
  the RM-127 addition took ROADMAP to 91 pct of budget, relocation brought it to 88.8.
- **RM-127 FILED - CCR link-ingest Phase 2 is UNBLOCKED.** Phase 1 (LEDGER 1108) ended
  awaiting operator notes; they have landed. RM-127b covers the build-calculator parity
  report (export ingest path already solved; 220 KB JSON, only 7 objects vary per champion).
- **BACKLOG: TFT F8 + F1** from `docs/COMPETITOR_LIFT_2026-07-30.md`, both rated HIGH in
  that teardown's own verdict table and never carried into any tracker.
- Verified-and-left-alone (no duplicate): G3-13 / G2-39 (gated sync), RM-124, RM-118,
  RM-122 (already absorbs `pending ui ux.txt`, with corrected line numbers), TFT Set 17
  constants + `tft_roll_odds` wiring + `tft_pbe_data` arrows, MEMORY.md compaction.
  CI run 30592954426 confirmed green LIVE rather than assumed.

## Lessons worth keeping

1. **Two grep patterns lied in the same session, both by near-miss.** `!= =!` returned 0
   because the CCR marker wraps the note TEXT (`**!= note =!**`) - that nearly closed
   RM-127 as "no operator notes yet" when 155 had landed. Then `MEMORY.md compact` missed
   the real row through its surrounding backticks, and nearly produced a duplicate BACKLOG
   row. **An empty grep is a claim about your pattern, not about the repo.**
2. **A ROADMAP row is a claim with a timestamp.** LEDGER 1093 wrote that lesson about this
   very row and the row went stale again anyway, because closing a ledger entry and closing
   the tracker row are two separate acts and only one of them is anybody's habit.
3. **`fire_lane`'s own docstring says it "never spawns anything" - that is STALE**, S5 added
   the launch directly below it. Read past a docstring to the code under it.
4. A live lane pid proves nothing (DETACHED_PROCESS no-op). The real probe is a `claude.exe`
   CHILD of the worker shell - confirmed here at pid 18400 / 382 MB.

## Do NOT redo

- RM-121 is CLOSED. The five-file queue is drained, there is no file 5.
- Do not re-move `First-Pass.md` / `First-Pass-Addendum.md` - RM-127 cites their Desktop paths.
- `logins.txt`, `LW continue.txt`, `RM continue.txt` were correctly left untouched (credentials
  + sibling-repo prefixes). Verified present and unmodified at wrap.
- `ops/loop/control/STOP` holds a REAL operator halt from 2026-07-28 and is UNTOUCHED. It gates
  the gemini CONTROLLER, not the lanes - the lane lock was FREE and fired normally with STOP in
  place. Do not clear it.
- Lanes 7 (repo) and 8 (true-audit) still have NEVER been fired and remain operator-gated.

---

# 2026-07-31d - MISSION CONTROL S10 SHIPPED + MERGED (decoupled from the dashboard).

## Start here next session

S10 is DONE and on `main`. Mission Control is its own process on `:8895` under the
`RC-MissionControl` scheduled task; the dashboard's copy is deleted, so
`/api/loop-status` and `/api/loop-control` 404 on `:8888` by design.

Shipped (9 tasks, 20 commits, merged fast-forward): `mc/` package + `mission_control.py`,
bearer-token auth that FAILS CLOSED, bind restricted to loopback + tailnet only,
`web/mc/` standalone asset tree, `dashboard/_matchers.py` (the split that keeps pydantic
out of the control plane), and the dashboard-side removal. Post-merge: token ACL locked
to SYSTEM + Administrators, plus two guard fixes (`ab3d8b0b`, `2a55f40f`).
Detail in LEDGER 1139 + 1140. Design history in `docs/MISSION_CONTROL_PLAN.md` "S10 as shipped".

## Do NOT redo

- **S10 is complete and merged.** Do not re-plan it, re-pitch a `/healthz` watcher, or
  "fix" the two scheduled-task triggers - the logon trigger plus a time-based repeating
  trigger is the working combination, proven by a real reboot AND a taskkill recovery at t+49s.
- **The SDD execution workspace under `.superpowers/sdd/` is deleted on purpose.** Git
  history + LEDGER 1139/1140 + the BACKLOG entries are the record. Do not hunt for it.
- **Tailscale IS installed and running** (`legion-rc` / `100.70.22.55`). A mid-session claim
  that it was absent was WRONG - three guessed `Test-Path` checks against a machine where
  `Get-Process` would have settled it in one call. Lesson appended to memory
  `feedback_verify_before_declare_broken`.
- **`ops/loop/control/STOP` holds a REAL operator halt** ("operator halt via LW session
  2026-07-28"). It survived the whole build untouched. Do not clear it as a test artifact.
- Lanes 7 and 8 have still never been fired. Deliberate; ask before firing.

## Next

Top open item is whatever `ROADMAP.md` carries as the next `[!]`. The highest-value S10
follow-up in `BACKLOG.md` is `dashboard/_errors.send_error` leaking `str(exc)[:200]` to
`:8895` via the imported loop routes - pre-existing on `:8888`, so not urgent, but it
collides with the CLAUDE.md no-raw-error-strings rule. An owed pixel-screenshot pass on
`https://legion-rc:8895/` is also logged (Browser pane would not composite frames this session).
