# s150 ruling: landing launch line re-check, lanes idle (distinct adjudicator, read-only, 2026-11-06 about 18:45 CST)

Recorded by docs/LEDGER.md entry 2057. Supersedes only the owed operator line of the s150z ruling (`2026-11-05-s150-landing-launch-lanes-running-ruling.md`); its Q1 line, Q2 stops and Q3 flags stand.

DECISION: C, with a read-only launch watch. The 24800 MB physical launch line STANDS. No launch below it. Option B was done and CONFIRMS the line; it does not lower it. The landing suite launches tonight only if PhysicalAvailable reaches the line on its own inside the quiet window; otherwise it waits for ONE batched operator ask.

INPUTS: LEDGER 2046-2056; the s150 rulings in this folder (landing-launch-lanes-running = s150z, suite-gate-landing-margin, suite-retry-after-harness-stop, reaper-env-var, rm1427). Brief reads 18:25-18:35 CST 2026-11-06 by read-only agents, not re-measured here: physical 23070 of 32375 MB, 0 lane workers, rotator pid 6176 in its budget pause to about 20:12; commit 13.3 of 48.4 GB; memory compression off; leftovers about 285 MB firm plus a possible 531 MB vmmem with a dead parent; origin main `52266153f` red in `ci` on 6 Linux-only tests, the fixes on local main `ba0df749f`, 7 ahead.

## 1. Re-derivation (option B)

- LEDGER 2053, the only green run and the line's basis: launch physical 25400 (s150z cites 25410), floor 1648 at 18:18:36, drop 23762 MB; gate tree private peak 23749 MB. Lane state at launch: "rotator pid 6176 in its budget wait ('cycles done 396; running none'), no child". The drop was NOT lane load: it equals the suite's own private peak within 13 MB.
- Reaper void: 2053 completed rc 0 with no reap, so its drop carries no void. The void was LEDGER 2050 (killed at 94 percent, physical floor 3850 at 11:09:38).
- LEDGER 2052 (completed rc 1, rotator in its budget wait, no lane child): 25151 down to 2084, drop 23067 MB; tree peak 23266 MB.
- LEDGER 2050 (void at 94 percent): 26221 down to 3850, 22371 MB before the last 6 percent.
- Suite-alone draw, two completed runs: 23067 to 23762 MB, each matching its tree peak. The line = max draw + the 1024 stop = 24786, rounded 24800. The lowest line the same data can defend (min draw + stop) is 24091.
- 23070 fails both: projected floor 23070 - 23762 = -692 MB, and 23070 - 23067 = 3 MB, each under the 1024 stop. B returns no corrected line that admits now. The lost `s150y_sampler.jsonl` changes nothing: every figure above is in LEDGER 2052 and 2053.

## 2. Why not A (launch now below 24800)

- A predicts a VOID on both measured draws; it is not a coin flip. The 1024 stop protects the box from a crash, not the run from being wasted.
- "The cost of a stop is one voided run" understates it. The harness reaper fired in LEDGER 2050 at physical 3850-4136 MB, far above 1024, and killed the sampler with the gate. A reap is VOID with NO retry (LEDGER 2051 ruling; s150z Q2), the harness text says not to restart unasked, and the reap can take other background shells of the same session. A run projected to near zero physical is the likeliest reap there is.
- No s150z reversal condition is met: no MAIN ruling, no in-tree sampler with a measured threshold, no reap or crash above 1024 since, no operator answer. The only new fact is a LOWER idle baseline (23070 now against 25400 at the 2053 launch), which argues against launching.

## 3. Why not D (each conflict named)

- Fewer than 8 workers: MAIN ORDER 2026-10-25 2045 (`-n 8`, never `-n auto`). Rejected.
- A slice or serial run: the Tiers rule and FLEET item 16 c (whole suite only, only through the gate). Rejected.
- `CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP`: the reaper-env-var ruling, not set at any scope. Rejected.
- Turning memory compression on or changing the pagefile: machine config, out of tree, halt boundary; it would also void the measured basis of the line. Rejected here; an ask for MAIN if wanted.
- A push without gate exit 0 on the exact sha, or `--no-verify`: the push rule. Rejected.
- This tree closing Chrome or Claude Desktop, killing the leftovers or the vmmem, pausing lanes or writing a stop file: operator acts, the brief and the FLEET banner. Rejected.

## 4. Launch condition (tonight; no further ruling needed)

Run the s150z Q3 command (gate, `--exclusive --timeout 900`, the ruled words, `-n 8 --dist loadfile --max-worker-restart=0 --timeout=300`, no plugin, NO margin env var) with run sha = HEAD = local main (`ba0df749f` plus the doc-only commit carrying this ruling) at the first moment ALL of these hold:
- PhysicalAvailable >= 24800 MB on two consecutive GetPerformanceInfo reads 10 s apart, the second within 60 s before launch;
- the clock reads no later than 19:45 CST 2026-11-06 (the run holds the gate about 21 min and must end before the rotator's pause ends about 20:12);
- rotator still in its budget pause with 0 lane workers; gate free; main clean; no League, Riot or Vanguard process; no live claim; no MAIN note on landings or margins.
If any is unmet at 19:45: NO launch tonight. The watch is read-only: nothing is killed, closed, paused or stop-filed to make the line.

## 5. Stop conditions (s150z Q2, unchanged; VOID = `taskkill /F /T /PID <gate pid>`, never graded)

- PhysicalAvailable under 1024 MB on 2 consecutive reads 10 s apart: VOID.
- Free commit under 1024 MB on 3 reads 10 s apart: VOID.
- A League or Vanguard process appears: VOID.
- Harness low-memory stop: VOID, NO retry, back to the operator.
- WinError 1455, MemoryError or "crashed while running": VOID.
- Exit 3 or not admitted in 900 s: not void; one relaunch at the next qualifying read, still by 19:45, then hold.
- Lane or rotator start: not a stop (dropped by s150z); the physical stop covers its load. Peak: recorded only.
Push only on gate exit 0, no void marker, pushed sha == run sha, then the verifier.

## 6. If no launch (expected: the line is about 1730 MB away)

ONE batched operator ask, replacing the s150z owed line:
"Landing suite (about 25 min) needs 24800 MB free RAM; the idle box reads about 23070. OK to pause the lanes, close Chrome, and let RC end the stale leftovers (about 285 MB) and the orphan vmmem (about 531 MB) for that run? yes/no"
Arithmetic: 23070 + Chrome 1021 + 285 + 531 = 24907 >= 24800. Chrome alone reaches about 24091 and is short. A partial yes launches only if the re-read reaches 24800. Each leftover's end method is named before it runs (FLEET item 9). Origin stays red on the 6 at `52266153f` meanwhile.

## 7. Alternatives and why

- A, launch now below 24800: rejected (section 2).
- B, re-derive and lower the line: done; it confirms the line (section 1).
- C, keep 24800 and wait for the operator: ADOPTED, with the read-only watch added because it costs nothing and takes a launch if the box frees on its own.
- D, any rule conflict: rejected (section 3).

REVERSES IF: the operator answers the ask; a MAIN ruling on landing stops, margin or the physical line; the owed in-tree sampler lands with a measured threshold; a completed gated run measures a suite draw that moves the line (recompute: max completed-run draw + 1024); a reap or crash above 1024 MB physical; memory compression, RAM or the pagefile changes on the box.
