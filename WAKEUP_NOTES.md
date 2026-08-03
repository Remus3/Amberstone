# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-02i - headless run 02: the ARAM Haiku blocker was a PARSER bug, and one trinket bug spanned four layers

5 commits, pushed `f818d718..bae4d0e0`. Ledger 1173. 13 slices, 8 verifier gates, no game
available (continue-note FORK C). ENGINE unchanged 1.270.0 - no engine math touched, so no
Share sync and no DS bounce were owed. RC restarted, pid 24412.

**The Haiku-to-ZERO blocker was never a coaching gap.** `parse_fields` clipped every value
to 220 chars; a 2-entry `choices` array is ~315, so it decoded to `[]` every time. The LIVE
side had emitted `choices` **zero** times across the entire ARAM shadow log and the entire
Arena log - `both=0`, so the flip could never be validated on its primary surface. Not stale
data. SR alone was clean (own uncapped parser). Fix splits the bound by CONTENT CLASS
(prose 220 / structured 2000, both still enforced): a structured value goes to a decoder, so
a mid-value clip does not shorten output, it DESTROYS it. Same cap was also serving
`item_build_reasons` cut mid-word - 809 rows sat at exactly 220 with zero above.
**`reference_coach_choices_native_emit` was corrected in place** - it said the emit was live
for all 4 coaches, which was true of the wiring and false of the effect for 3.

**A log-spam finding turned out to be a live product bug, at four layers.** 765 of 857
warnings came from one line; 116 read "has 7 items", and seven cannot fit six slots - a ward
trinket was occupying an inventory slot, so builds with a free slot got NO advice, exactly
where last-item guidance matters. Fixed at the route, its silent sibling, the source, the
three non-SR coaches (which fed the DS dispatcher a phantom slot), and finally the id set.
**"0 bad rows" is only true against a SET:** the first backfill cleaned 468 and reported 0 -
against the old 9-member set. Against the corrected 58-member set: **1658** bad rows, incl.
945 Poro-Snax and 699 Arena trinkets nobody had listed. A pure `consumed:true` derivation is
REFUTED both ways (loses 4 trinkets, over-filters 2 Wardstones that carry real stats).

**ARAM agreement gap is a wiring asymmetry, not noise.** 98.6 pct of mismatches are exactly
one tier apart and the rule's only one-tier operator (`wave_pct`) is hardcoded off while
Haiku gets the value. Noise + timing skew both refuted by measurement. Counter-intuitive:
the DETERMINISTIC side is the volatile one (0.904 vs Haiku 0.998). Only Step 0 shipped.

**The verifier gate earned its keep.** 2 of 8 returned REFUTE. Three slices mis-reported
their own test counts while their code was correct; one claimed "0 non-ASCII" for a file
with 225 pre-existing non-ASCII bytes. **One slice found the regression its own fix
introduced** - and `tests/test_archetype_mismatch.py` stayed FULLY GREEN through it, because
its fixtures build the two lists parallel BY CONSTRUCTION. Filed as the top FUTURE item.

**Verified:** RC 17677 passed / 108 skipped / 1635 subtests; DS 10341 passed from repo root;
ruff clean repo-wide. **Owed:** `both=0` can only leave 0 after one live ARAM.

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
