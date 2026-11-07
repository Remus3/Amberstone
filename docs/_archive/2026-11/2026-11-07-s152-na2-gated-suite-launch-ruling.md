# s152 NA2 ruling: gated whole dual suite on local HEAD after the RM-1974 landing (distinct adjudicator, read-only, 2026-11-07 07:39-07:45 CST)

Inputs read: RC-NEXT-SESSION.txt (NA2, NA2-owed, C10 ask, s150 "NEVER pause the lanes", IN-FLIGHT rotator); LEDGER 2053, 2056, 2057, 2058, 2064, 2065; docs/_archive/2026-11/2026-11-06-s150-landing-launch-line-recheck-ruling.md (ruling C) and the s150z ruling (Q2 stops, Q3 --exclusive --timeout 900); memory reference_parallel_slices_full_suite_oom.md and reference_gated_suite_n8_nearly_exhausts_commit.md; `fleet_suite_gate.py --help` (v21 admission: commit-aware, exclusive, per-tree, CPU cap); gate durations.jsonl.

## Measurements (this adjudicator, live)

- GetPerformanceInfo PhysicalAvailable: 25437 / 25435 MB (07:40:23 / 07:40:33), then 25578 / 25563 MB (07:42:27 / 07:42:37), of 32374. Line 24800: MET by 635-778 MB.
- Win32_OperatingSystem FreePhysicalMemory: 25262 MB (07:39:40), 25518 MB (07:42:25), of 32375.
- Free commit (CommitLimit - CommitTotal): 37347-37560 of 48374 MB. Gate need at default margin 29614.4 MB (LEDGER 2053): fits.
- vmmem pid 15900: working set 0 MB, private 531 MB (unchanged since LEDGER 2058). Not touched.
- Chrome: 0 processes. msedge 8 processes about 271 MB WS (not an ask item).
- League / Riot / Vanguard (LeagueClient*, League of Legends, RiotClient*, vgc, vgtray): none.
- Rotator pid 6176: alive, pythonw `s144_lane_driver.py --rotate`. s144-lanes.json 07:40:14 "cycles done 1196; running none". Log: "budget wait: 400/500 runs in the rolling 24h window (reserve 100)" every 10 min since 04:54:38; last lane child exited 04:54:38.
- `fleet_headless.py budget show --code RC`: count 400, cap 500, next_free 2026-11-07T20:12:31-06:00 (oldest start 11-06 20:12:31; next age-outs 20:12:31, 20:13:39, ...). So the rotator's NATURAL budget pause, 0 lane workers, holds until 20:12:31 tonight. Lane progress files lane-0..5 all status done (last 04:54:12).
- `fleet_suite_gate.py status`: "0 of 2 slot(s) held, lane free", no queue.
- Main checkout: clean at 07:42 (`git status --porcelain` empty), HEAD 765ab2d77 (committed 07:40:33, main is moving: the merger is landing). Origin/main..main 202.
- pytest trees: a merger -n 4 targeted run (pid 1640) was live at 07:41 and gone by 07:42:25 (0 pytest/xdist processes).
- Live claims: one, another agent's worktree test file (not the main checkout). No MAIN note on landings, margins or memory newer than 2026-11-01 in moon_sync_inbox.
- Suite growth since the line's basis run (52266153f, LEDGER 2053): test files 2779 -> 2920 (+141, +5.1 percent). Gate tree peaks on record: 33345 (pre-RM-1506, exit 1), 25518, 23288, 23783 MB - no file-count trend.

## DECISION

GO WHEN all of the following read true at launch (ruling C of LEDGER 2057 carried forward, re-dated to today; nothing lowered):

1. RM-1974 landed on local main; run sha = `git rev-parse main` = HEAD of the main checkout. The merger's own targeted runs on that sha are green: the RM-1974 (a) ratchet files, the (b) `tests/test_web_css_split_plan_rm726.py`, and the (c) modules named in the BACKLOG row under `-n 8 --dist loadfile` on just those files, 2 runs, no hang (a hang ends the gated run under --max-worker-restart=0).
2. PhysicalAvailable >= 24800 MB on two GetPerformanceInfo reads 10 s apart, the second within 60 s before launch.
3. `python ops/fleet_kit/fleet_headless.py budget show --code RC` reads count >= 400 with next_free >= launch + 45 min, s144-lanes.json step contains "running none", and no lane worker process exists. Practically: launch no later than 19:27 CST 2026-11-07.
4. `fleet_suite_gate.py status` reads "0 of 2 slot(s) held, lane free" with no queue line.
5. Main checkout `git status --porcelain` empty, and it stays FROZEN until the gate exits: no commit, merge, checkout or edit in the main checkout during the run (the suite runs in that tree; a straddle voids it).
6. No League / Riot / Vanguard process; no pytest or xdist process tree alive other than the run's own.
7. No MAIN note on landings, margins, memory or the physical line newer than 2026-11-01 in moon_sync_inbox.
8. The landing agent's sampler is running BEFORE launch: every 10 s, GetPerformanceInfo physical + free commit + the game-process list + main HEAD, to a file in its own scratch subfolder; it enforces the stops below.

COMMAND (unchanged words, hash `fcacfd0c713e39a3`, s150z Q3 flags): `python ops/fleet_kit/fleet_suite_gate.py run --owner <id> --exclusive --timeout 900 -- python -m pytest tests agents/daemon_slayer/tests -q -n 8 --dist loadfile --max-worker-restart=0 --timeout=300` (no plugin, no FLEET_SUITE_COMMIT_MARGIN_MB, output to a file, summary line AND exit code asserted).

STOPS (LEDGER 2057 section 5, unchanged, plus one): physical < 1024 MB on 2 reads 10 s apart VOID; free commit < 1024 MB on 3 reads VOID; League or Vanguard appears VOID; harness low-memory reap VOID, NO retry; WinError 1455 / MemoryError / "crashed while running" VOID; exit 3 or not admitted in 900 s: one relaunch at the next qualifying read, still by 19:27, then hold. ADDED: main HEAD or porcelain changes during the run VOID (straddle). VOID = `taskkill /F /T /PID <gate pid>`, never graded. A lane start is not a stop (it cannot happen before 20:12:31 without an operator budget reset).

AFTER: record launch physical, floor, draw and the durations row's peak_commit_mb. If draw > 23776 MB, the new line is draw + 1024 (ruling C reverses-if). Push only on gate exit 0, no void marker, pushed sha == run sha.

IF NOT MET by 19:27 CST: no launch today; the C10 operator ask stays owed at /done, re-read with tonight's numbers. The lanes are never paused; nothing is closed or killed to make the line.

## ALTERNATIVES

- NO-GO -> C10 operator ask now: rejected. The line is met on the idle box with Chrome already closed and vmmem untouched; the ask exists only for the case where the line is unmet.
- GO now, before RM-1974 lands: rejected. (a) and (b) red any tree by design and (c) can end the run; about 21 min of a clean window spent for a known red, no push possible.
- Raise the line for the +5.1 percent test-file growth (proportional: draw about 24974, line about 26000): rejected as a launch bar. Draw is not a measured function of file count (tree peaks 25518 -> 23288/23783 fell across file growth after RM-1506); a larger draw is caught by the 1024 physical stop as a VOID, not a crash; and free commit 37.3-37.6 GB against the post-fix tree peak 23.8 GB (even the pre-fix 33.3 GB) leaves no WinError 1455 path. A completed run will measure it.
- Lower the line, -n under 8, a slice, the reaper env var, memory compression or pagefile changes: rejected (ruling C section 3; MAIN ORDER 2026-10-25 2045; Tiers rule; halt boundary).
- Pause the lanes or write a stop file to make a window: rejected (operator s150 "No, keep lanes running"). Not needed: the budget pause runs to 20:12:31.

## WHY

Ruling C (LEDGER 2057) set the launch line at 24800 MB = max completed-run draw 23762 (LEDGER 2053, matching its tree peak) + the 1024 stop, with a launch allowed in a natural rotator pause with 0 lane workers. Its window lapsed on 2026-11-06 only because the box read 23070-24106 MB (LEDGER 2057/2058/2064). Today the same box reads 25435-25578 MB on four GetPerformanceInfo reads (projected floor 1673-1816 MB on the 2053 draw, above the 1024 stop), the rotator sits in its own budget wait (400/500, reserve 100) with next_free 20:12:31, so the s150 no-pause order is kept by construction, the gate is free and no game runs. Every ruling-C precondition is readable now; only the RM-1974 landing is outstanding. FLEET item 1: a blocked decision is taken by the adjudicator; the operator ask is not required while the line holds.

## REVERSES IF

Any condition 1-8 reads false at the launch moment (hold, re-read each 60 s, until 19:27); the operator answers the C10 ask or orders otherwise; a MAIN ruling on landing stops, margin or the physical line; an operator budget reset ends the pause early; a completed gated run measures a draw that moves the line (recompute max draw + 1024); a reap or crash above 1024 MB physical; RAM, memory compression or the pagefile changes on the box.
