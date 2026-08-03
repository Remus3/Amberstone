# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-02j - Mission Control lane 7 (Headless-Repo), first fire: the frozen list had an unguarded mirror, and 70 GB of out-of-repo scratch was mostly hardlinks

2 commits on `lane/repo`, `1b277a90` + `6d3f7e6c`. Ledger 1174. Worktree-first. **NOT merged** -
the merge is the merger's call and the main tree was not verified idle. ENGINE untouched at
1.270.0, so no Share sync, no DS bounce, no RC restart owed.

**The lane worktree did not exist.** `git worktree list` showed only `main`, so it was created
from the repo root rather than working in main - two writers in one working directory is the
unrecoverable index-corruption class. `core.hooksPath` re-confirmed ABSOLUTE
(`C:\Riot Commander\.githooks`); worktrees share `.git/config`, so `install_hooks.py` was NOT
run and nothing about the hook config was changed.

**CORRECTION, and it is the run's best finding: the rule has SIX representations, not four, and
the mirror this run first missed was the ONLY one that had drifted.** The stop-claim gate refused
an unbacked count, the re-grep surfaced a `FROZEN_FILES` nobody had looked at, and it turned out
`agents/agent1_lead/scheduler.py::FROZEN_FILES` held **13 against the authority's 16** - missing
`app/_loop.py`, `tools/diagnose.md`, `tools/caveman.md` - **unchanged since the initial commit**
while CLAUDE.md moved underneath it. Its own comment says "Synced with CLAUDE.md". Its sole
consumer `Scheduler.file_task()` appends category 1 -> `NEEDS_APPROVAL`, withheld from the ready
heap until `approve()`; with the entry missing, a task naming `app/_loop.py` went straight to
READY - an agent could edit an operator-frozen file with NO approval stop. Demonstrated against
the real scheduler, not argued. Fixed; 0 of 5811 live queue records newly gated; **inert until the
Phase 3 supervisor restarts** (PID 21304 holds the old set in memory). The guard now checks a
`PARITY_MIRRORS` list, with `core/hot_reload.py` deliberately held to a SUBSET rule instead - it
watches `.py` only, so equality there would go RED and pressure a WRONG fix. **Do not "fix" it.**
Census: authority 16 / ci_watchdog 16 / strip_smart_quotes 16 / repair_mojibake 16 / scheduler
was 13 now 16 / hot_reload 14 by design.

**The original framing, still true of the other mirror.** `tools/ci_watchdog.py:79`
`FROZEN_FILES` is a hand-maintained MIRROR of `CLAUDE.md:40-45`, consumed by `touches_frozen()`
at `:204-207` - the thing that stops the CI watchdog auto-merging a fix INTO a frozen file. Nothing
asserted the two still matched, so adding an entry to CLAUDE.md alone would leave the watchdog
silently auto-merging into a newly-frozen file. Same drift class as `tools/*.md` vs
`.claude/commands/*.md`, which ran a month. The pre-existing
`tests/test_constraint_single_source.py:18` only checks three anchor substrings appear - it never
parses the list. New `tests/test_frozen_file_list_contract.py` reads the contract off disk and
ties all four representations. **T4's direction is load-bearing:** a `frozen=yes` header on a file
absent from CLAUDE.md FAILS; an authority entry with no header does NOT. 12 headers vs 16 entries
is CORRECT and expected - `gen_archmap.py:22-23` says why. Never compute the frozen set from
headers. T3 was independently re-mutated both ways after the build agent's own pass: RED both times.

**The out-of-repo half returned nothing to reclaim, and that IS the finding.** 3 proposed, 0
approved, 0 executed, 0 bytes. The age-prune of `Temp\claude\C--Riot-Commander` was rejected on
measurement: the tree is full of NTFS HARDLINKS into the main repo's own `.git\lfs\objects`, so
`Get-ChildItem` counted one physical extent three and four times - `fsutil hardlink list` over the
400 largest delete-set files found 132 files / 1735 MB that reclaim ZERO bytes. The 2.78 GB
headline was ~62 percent air. The discriminator fails too: mtime inside a hardlinked clone is the
ORIGINAL object's mtime, so a 7-day cut strips ~583 MB out of the MIDDLE of each of three RC
clones. A second proposal cleared ~1.9 GB on a "HEAD confirmed in the main repo" check that
cannot exist - `base59`, `mut1`, `mut2` have no `.git` at all. `.claude/projects` and
`Temp\claude\C--Sibling-A` untouched by rule.

**The `_archive` silent-fail trap fired live.** A `git reset` between staging and commit dropped
both archive destinations from the index; because `_archive/` is gitignored they became
untracked-and-ignored on disk while `git add -A docs/` staged only the two DELETIONS - exactly the
"remove the file from version control entirely" failure `.gitignore:19-21` warns about. Caught
only because the `git ls-files` gate was run BEFORE committing, not after. Recovered with
`git add -f`. **Run that gate every time; `git status` alone looked fine.**

Verified: RC **18050 passed / 154 skipped / 1635 subtests** from the repo root, drift_guard 0
breaches, archmap + state_schema clean, ruff clean, named guards 45 passed. Verifier CONFIRM 11/11.
`test_loop_concurrency` ran 28 passed / **0 skipped** - `C:\Sibling-A` is present, so the
sibling byte comparison and the `SHARED_SHA256` pin genuinely executed.

Open: `%USERPROFILE%\.gemini` needs an operator ruling - `tools/headless-repo.md` contradicts
itself (table says PURGEABLE, section 2 says RETAIN). Held as RETAIN, untouched.

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
