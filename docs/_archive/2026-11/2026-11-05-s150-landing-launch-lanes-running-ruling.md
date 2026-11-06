# s150z ruling: landing suite launch (distinct adjudicator, read-only, 2026-11-05 21:10)

Archive note: docs/LEDGER.md entry 2056 records this ruling and the landing agent's act on it. The clock times "21:05" and "21:10" below are the landing agent's mis-stated clock, passed to the adjudicator in its brief; the reads were taken 20:52-20:59 local and the ruling was written at 20:57. Nothing else differs from the ruling as written.

DECISION: NOT NOW. Launch with no further ruling at the first read where every precondition holds. The test is physical headroom, not lane state.

Q1
- Margin-ruling :40 and its lane-start stop LAPSE with the grant. They were its terms ("all under sections 1-2") and rested on the 100 MB fit at 2048. The default 4096 margin now governs commit, and lanes at rest are already in the free-commit read.
- Env-var Alt 5 "quiet box" is advice, but its purpose binds as a number: physical >= 24800 MB at launch. The 2053 run used 23762 MB (25410 down to 1648, s150y_sampler.jsonl), plus the 1024 stop.
- Read 21:05: 22419 MB with lanes up. Projected floor about -1300 MB. FAILS.
- The order plus the brief do not settle retry :120. "Run the landing suite" says nothing about lanes, and the no-pause line binds the agent, not the operator. Waiting for the rotator's own budget wait is allowed.
- New word: LEDGER 2053 bars a third run without one. The brief counts as one unless main says it re-cited the 2054 answer.
- Owed line, only if 24800 is still unmet after LW exits: "Pause the lanes about 25 min for the landing suite? yes/no".
- Other preconditions: gate free; main clean at f59da730f; no League/Riot/Vanguard; no MAIN landing note.

Q2 (VOID = taskkill /F /T /PID <gate pid>, never graded)
- Free commit under 1024 x3, 10 s apart: KEEP (LEDGER 2039 basis is independent of the grant).
- Lane/rotator start: DROP. Workers rotate about every 337 s (21:05). --exclusive and item 14 hold lane suites out.
- League/Vanguard appears: KEEP.
- Harness low-memory stop: VOID, NO retry (retry ruling :121), back to the operator.
- Physical: APPLY at 1024 x2, not 2048. 2048 x2 would have voided the only green run (1986 at 18:17:55, 1892 at 18:18:05). 1024 sits between that 1648 floor and the 721 failure.
- WinError 1455 / MemoryError / "crashed while running": KEEP, VOID.
- 31218 line: DROP (grant arithmetic). Record the peak only.
- Exit 3 or not admitted in 900 s: not void. One relaunch at the next qualifying read, then hold. No margin, cap, word or worker change.

Q3 --exclusive: YES. Item 17 is gate-scoped and silent on lanes. It keeps LW's 9.7 GB suite from starting beside ours, and the hash is unchanged. Keep --timeout 900.

Rejected: launch now with lanes up; lane-start stop; 2048 physical stop; the agent pausing lanes or writing a stop file; a margin/worker/word change; no --exclusive.

Reverses if: a MAIN ruling on landing stops or margin; the owed sampler lands with a measured threshold; a reap or crash above 1024 MB physical; the operator answers the line.
