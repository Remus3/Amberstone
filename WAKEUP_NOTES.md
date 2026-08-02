# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-02h - RM-147 decided, G6-03 closed, RM-146 measured + closed; a probe bug was blocking a gated row

5 commits, pushed `abd2d073..19197022`. Ledger 1170 + 1171 + 1172. Two live ARAM Mayhem games.

**G6-03 CLOSED (3rd GATE 6 row ever).** 25.08 min recorded across a real match end, zero
capture stalls (`outputDuration` +10133-10167 ms on all 140 polls), 6.35 GB mkv, ffprobe
clean. **Read the scope fence:** League was Borderless 2560x1440 on a 2560x1440 desktop, so
NO resolution swap occurred and item-209b's actual failure mode was never exercised. Open
tally 112 -> 111.

**RM-147 CLOSED.** Second `monitor_capture` added disabled-by-default beside the untouched
`window_capture`, used for one match, auto-disabled. **Its risk paragraph was REFUTED** - it
cited a memory deleted in the 2026-06-03 BSOD purge. Operator also corrected the WindowMode
encoding: **0=Fullscreen, 1=Windowed, 2=Borderless** (the memory had it backwards; fixed).

**RM-146 CLOSED - ceiling was wrong, nothing leaks.** 300/500 -> 700/1200, TDD, tests red
first. Two ARAMs on one process agreed on a 548 MB roof within 0.3 MB; second match added
~24 MB committed, not ~835. The 810 MB peak is POST-GAME work, not the resolution flips I
hypothesised - a restart measured 804.9 MB at 77s uptime because it booted post-match.

**`tools/gated_live_probe.py` was lying.** `https` against a plain-HTTP token-gated relay,
no `X-RC-Token` -> `frame_dead=True` unconditionally. That false negative had been written
into G3-13 as a blocking precondition. Live proof: `frame_bytes` 0 -> 249983,
`relay_present` False -> True. `_RELAY_BASE` also feeds `/latest-liveclient`, so **any older
gated note citing `frame_dead`/`relay_present` is suspect.**

**Do NOT redo:** RM-146/147/G6-03 are closed. Do not restore RM-147's BSOD framing. Do not
re-hypothesise resolution flips for the 810 MB peak. RM-148 is CONFIRMED (BACKLOG) - the
hermeticity guard false-fires on live-RC `data/` writes, duration-sensitive, so a batch run
showing 1 teardown error while every test passes alone is that, not a real failure.

**Owed:** G3-13 still OPEN - 278 samples over ~13 min of Mayhem produced ZERO augment keys
on either surface, but my watchers started ~200s in so an early window could have been
missed. `/api/state` `screen_read` was 6.1 HOURS stale while vision ran fine via
`moon_proxy` - that is the better suspect for a dark panel than the `cff8d678` cadence fix.
Start the augment watcher BEFORE queueing next time. Also on disk: 6.35 GB
`C:\RC-Recordings\2026-08-02_15-13-40.mkv`, operator's call to delete.

---

# 2026-08-02g - RM-145 live-confirmed, G6-04 closed; the prep half found the bug in the acceptance criterion

6 commits, pushed `07ddfae6..<this>`. Ledger 1169.

**G6-04 CLOSED - PASS both directions.** Live ARAM, rc-shell pid 4140. Desktop
2560x1440 -> 1920x1080 -> 2560x1440; overlay window tracked it exactly; access log carried
`?overlay=1` (scale 1.00) -> `?overlay=1&ovscale=1.33` on the return leg, which was the half
that was broken. Second GATE 6 row ever closed.

**The prep half was worth more than the run.** Before the game started, measured that the
row's OWN acceptance criterion was unsatisfiable: `overlay_state.js:171` appends `ovscale`
only when `|scale - 1| > 0.001`, so 1920x1080 gives scale exactly 1.00 and NO param. A
literal "two lines both carrying ovscale=N" check fails on correct behavior. Fixed the row
first (`12934b47`), then ran the game against a criterion that could actually pass.

**Three of my own claims were wrong, all caught by probing rather than reasoning:**
(1) "zero overlay requests today" read only the un-rotated log - the daily log rotates at
3MB and had rotated four times; the lines were in `.log.1` and `.log.3`. (2) I flagged
`health.json` `overlay_visible: false` as evidence the HUD was down - that field is DEAD,
set False at construction and never written again. (3) The first live attempt fired nothing
because Borderless does not resize the desktop; reading that as "the fix failed" was
available and wrong.

**Filed, not fixed:** RM-146 (RC permanently over its 500 MB ceiling, remediation
permanently suppressed by the restart-loop guard - the guard is correct, the steady state
it protects is not), RM-147 (G6-03 blocked: live OBS runs a window_capture, not the
continuous display capture the row is about; converting it re-introduces the BSOD surface,
so it is the operator's call), RM-148 (the hermeticity guard cannot tell a test from the
live daemon and intermittently reds the /done gate).

**OBS: set up as far as is safe.** `C:\RC-Recordings` created (the configured path did not
exist) and the record path proven end to end over obs-websocket. Capture METHOD deliberately
left alone - see RM-147.

Relocated RM-143/144/145 to `docs/ROADMAP_HISTORY.md`; ROADMAP was at 95% of budget, now 88%.

**Next:** G6-03 needs the RM-147 decision first. Otherwise pick from ROADMAP.

---

# 2026-08-02f - console flash named by measurement; three of my own suspects refuted

4 commits, pushed `a632cead..2d296991`. Ledger 1168.

**The flash is `LW-CIWatchdog`** - the SIBLING repo's task running
`python.exe C:\Sibling-A\tools\ci_watchdog.py` on a PT2M repeat. Named in one pass by
polling top-level windows for `ConsoleWindowClass` at 40ms and resolving each PID through
CIM: three visible windows in 7 minutes, all that command line. Free A/B in the same
capture - RC's twin `RC-CIWatchdog` fired on the same cadence under `pythonw` with zero
windows. Live task repointed to `pythonw.exe`, verified over a second capture (three fires,
no windows, `watchdog.log` still writing). Source fix (installer builds the task XML from
`sys.executable`) filed to the sibling via `moon_sync_inbox/`.

**The hand-off's prime suspect was WRONG.** The `Stop` hook ran at 12:04:39 inside the
capture window (`ops/runtime/stop_claim_history.jsonl`) and produced no console. Children
were already clean. Do not re-audit either.

**Two measured reversals of my own claims, both recorded:** `-WindowStyle Hidden` does NOT
suppress the flash (probe task: no flag -> visible, with flag -> STILL visible, S4U -> none);
and `RC-PatchRefresh` / `RC-PostmortemAnalyze` / `RC-WeeklyHygiene` were already S4U so none
of them could ever have flashed - I had flagged them off their command line without checking
the principal. Only `LW-WeeklyHygiene` was really exposed and is now S4U.

**Operator-directed second half:** CLAUDE.md's hostname drift. Fixed by DELETING the field
(`c645271e`), not by updating it - operator: the Windows name changes from time to time, so
pinning a value only resets the drift clock. `legion-rc` / `100.70.22.55` is canonical.

**MAIN WAS RED ON ARRIVAL and it was NOT this session's doing.** The previous session's
`8b91d13a` edited a LIVE span in `web/js/main.js` (the `setMode` first-render stamp) and the
RM-125 `_LIVE_HALF_DIGEST` guard is built to go red on exactly that and demand a deliberate
re-capture. That session wrapped while its push run was still in flight, so the red landed
after its banner and nobody collected it - main sat red from 16:34. Re-captured by the
documented two-tree diff (`ec55b133` vs now, one fixed tokeniser, 173 sources both sides,
exactly one file differs and it is `web/js/main.js`), `289c244e`. **Process lesson now
written into the guard's own note: if a push run is still in flight at wrap, COLLECT IT.**
I also briefly misattributed the red to my own footer-comment edit - wrong, a comment-only
change cannot move that digest, and the two-tree diff is what settled it.

**Next:** RM-145 still needs the live in-game confirmation (LIVE_GAME_GATED_SYNC G6-04) -
game up with overlay showing, flip the video mode AND flip it back, receipt is two access-log
lines with different `ovscale=N`. Needs the operator playing; nothing else blocks it.
