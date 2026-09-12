# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-11, headless-loop-stop wrap (relocated `2026-09-10e` Q5 relay + inert-negation fix; newest 3 = `2026-09-11c` the 8-cycle loop run stopped by operator STOP, `2026-09-11b` RM-405 caller-seam silent degrade, `2026-09-11a` stale-fallback + three silent failures). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.
>
> **RELOCATION DUE (noted 2026-09-11k):** this file now holds FOUR full sessions, one over the keep-3 rule - the docs slice that added `2026-09-11d` was not permitted to edit `docs/history_notes.md`. At the next wrap, relocate the OLDEST section (`2026-09-11a`) VERBATIM to the top of the archive section there (`scripts/wakeup_prune.py --keep 3`), then delete this note.

---

# 2026-09-11d - operator-directed lane-8 pre-flight: 4 hardening slices shipped, 5 directive claims refuted or already-shipped

LEDGER 1398 (`2026-09-11k` there). NOT a loop cycle: operator-directed while
`ops/loop/control/STOP` sat on disk. Worktree `lane/true-audit`, merge sha in
LEDGER 1398 at wrap. Tier-1, ENGINE-IMPACT NONE, RC restart required. 7
agents, 993884 subagent tokens, 18.4 min. Verifier: 9 pytest commands, 0
failed / 0 errors; `py_compile` OK on all 8 changed files; ruff clean; 0
non-ASCII, 0 CR bytes.

**TRIAGE FIRST - five directive claims did not survive it.** (1) REFUTED:
`dashboard/_state_builder.py` "duplicate `/activeplayerrunes` request tax" -
zero rune hits in that file. (2) REFUTED: "move `PolledJsonFile` onto
`NamedMutex`" - `core/polled_json.py:204` records ZERO production
instantiations (RM-264 holds adopt-or-remove); `ops/loop/winmutex.py` has NO
`NamedMutex` (only `hold()` `:51` + `MutexTimeout` `:46`); both byte-pinned,
nothing changed. (3) orphan tree wiring = RM-407, ALREADY SHIPPED today. (4)
split-form sibling-name scanner = RM-399 (`tools/sibling_name_sweep.py:113`),
ALREADY SHIPPED. (5) `SHARED_SHA256` pins MATCH live bytes. STOP (operator
17:32, "No cycle 9") deliberately NOT cleared - clearing re-arms the loop,
the arming halt point. `RUNNING.lock` pid 22888 = electron.exe, left alone.

**SLICE A - RM-234 CLOSED as DEDUPE.** `game_reader/snapshot_normalizer.py`
derives `my_runes` from `runes_full` via new pure `_runes_text_from_structured`
(`:136-164`, `:596`); second GET gone. `tests/test_rm234_runes_single_get.py`
8 tests RED "got 2" -> GREEN; 38 named existing tests green; refuter PASS.
PREMISE CORRECTION: BACKLOG RM-234 and LEDGER 1117 claimed "no production
consumer of `my_runes`" - FALSE, `coaches/aram_coach.py:430` + `:1031` feed it
into the Haiku prompt. True only for `runes_full` / `stat_shards`.

**SLICE B - FROZEN `app/_state_authority.py`, operator-named, refuter APPROVE.**
`calc_win_pct` +6/-3: keeps str, decodes bytes, skips int/None/dict/list;
`tests/test_calc_win_pct_type_clamp.py` 23 tests, mutation-red. Correction:
`app/_game_lifecycle.py:465-467` already caught the crash - effect was STALE `win_pct`.

**SLICE D - `tools/precommit_gate.py` +129, `RC_ATOMIC_WRITE_GATE` warn
(default) / block / off.** 43 tests (41 red with the scanner reverted); gate
family 90 green. Whole tree: strict 4 hits / 2 files, lenient 11 / 9. BLOCK
MODE NOT VIABLE YET, and that is the finding - the BACKLOG row carries the
false-negative / false-positive lists and the `ops/` + root scope gap.

**SLICE E - `item_advisor.py` +45/-11.** H1 REAL (failed loads cached as `{}`
for the process lifetime, no log - now not cached, one WARNING per path); H3
REAL (fully-bought curated champion read "Unknown champion" - now gates on
`CHAMPION_BUILDS`); H2 aliasing REFUTED. 14 tests, mutation-red 8. The
directive's `:79` / `:89` cites belonged to `coaches/_arena_item_advisor.py`,
NOT edited. **OSS extraction blueprint** (operator message) ASSESSED, NOT
executed: C1 extractable, C2 partial, C3 NO (byte-pinned across three repos,
API mismatch, carries the known sibling-name escape). Filed to BACKLOG.

**NEXT SESSION**
(a) Slice D block-mode follow-up: `ops/` + root into scope, fix the hunk-level
    `str.replace(` exemption, one red-first case per listed false negative.
(b) Slice E residuals: `dashboard/_liveclient.py:455` predicate;
    `coaches/_arena_item_advisor.py:73-90` + `:110-127` H1 pattern.
(c) `ops/loop/control/STOP` is STILL PRESENT - operator decides whether to
    clear it before the next loop launch.
(d) `moon_sync_inbox` 2026-09-11-1415 `lw_write_tracer.py.from-lw` (Apache-2.0): license-gated evaluation pending, not vendored.
(e) Inert stubs `r._read_my_runes = lambda: ""` at `tests/test_liveclient_championstats_ingestion.py:163`
    + `tests/test_p2w1_app_a.py:61` - harmless, deletable in a later cleanup.

# 2026-09-11c - the headless loop ran 8 cycles and was stopped by the OPERATOR, not by max_cycles

Run `63545b4e`, `loop start dry_run=False max_cycles=100 head=eaf13e82` at
10:52:26, controller exit at 18:04:04 on `external STOP seen (cycle top)`.
Eight cycles, LEDGER 1392 through 1397, plan rows R226 through R230. Six of the
eight reported an executor cost and those six total **$104.18**; cycle 1 and
cycle 6 reported none. Final HEAD `1f4b8a23e` == `origin/main`, working tree
clean, `ci` and `docs-guards` both **success** at that sha. Live at wrap: pid
40472 alive, `mode=client`, `last_reload_ok=true`. Operator-run verification at
wrap: `pytest tests` 21890 passed / 102 skipped / 4938 subtests in 1:12:22.

**THE RUN ENDED BY OPERATOR STOP AND THE STOP WAS OBEYED EXACTLY AS WRITTEN.**
`ops/loop/control/STOP` was written 17:32:14 reading "operator 2026-09-11 17:32
- finish cycle 8, then disarm for /done. No cycle 9." Cycle 8 was already in
flight; it finished normally at 18:01:53 (`sha=1f4b8a23 tests=21895
regress=False`), audited CLEAN at 18:04:04, and the controller then exited at
the cycle top without opening a cycle 9. **The cap was never approached** - 8 of
100. The STOP file is still on disk, so a re-arm has to clear it deliberately.
Three headless-claude scheduled tasks were disabled in the same wrap:
`RC-CIWatchdog`, `RC-WeeklyHygiene`, `RC-InboxResponder`. Re-arming the loop
means clearing STOP **and** re-enabling those three deliberately.

**WHAT EACH CYCLE SHIPPED.** Cycle 1 (10:55-12:25) shipped NOTHING - `sdk
timeout after 5400s - killing the child tree`, sha unchanged at `eaf13e82`,
audit CLEAN on an unchanged tree. Cycle 2 shipped RM-406 (`c00b9af89`, LEDGER
1392, plan row R226 - the suite writing the operator's LIVE tree) plus the
next-free-id pin advance to RM-407 (`591bf1e0d`). Cycles 3 and 4 shipped RM-407,
the orphan test-tree CI wiring (LEDGER 1393, R227). Cycle 5 shipped the
R227-REGRESS-FIX (`54fcf67c8`, LEDGER 1394). Cycle 6 cleared the `drift_guard`
RED by relocating `ROADMAP.md` 74881 -> 65475 bytes (`23c1bca31`, LEDGER 1395,
R228). Cycle 7 shipped RM-410, the direct byte/atomicity test for the ddragon
fetch writer (`7ff5fc853`). Cycle 8 shipped the RM-411 half - the destination-
scoped `os.replace` fault injection, the `.tmp` leak CHARACTERIZATION, and the
process-wide census (`eb440accf`, LEDGER 1396, R229 + R230) - then the director
tail-window fix (`ea45b15e3`, LEDGER 1397).

**CYCLE 3 AUDITED REGRESS, AND THE REASON IS THE ONE WORTH CARRYING.** It
reached the right RM-407 verdict and wrote the repair into the working tree,
then ended without a wrap commit. So HEAD `c00e2f1d6` spent a full cycle running
`pytest agents/agent3_testing/suite` BARE, zero exclusions, inside a
push-BLOCKING job - shipping the 1-in-3 `test_supervisor.py::
test_supervisor_starts_and_binds_ports` flake that the same cycle had just
measured (run 1 of 3: 1 failed / 348 passed / 2 skipped / 2 deselected, runs 2
and 3 green, 3/3 in isolation). Cycle 4 was directed to LAND THE ALREADY-WRITTEN
FIX rather than redesign it, and did: `2df4d10e0` declares the tree EXCEPTED -
not wired, not excluded, not forgotten - with the measured flake as the stated
reason, and aligns gate, guard row and audit verdict on one word. `tools/tests`
(348 collected) IS wired into the push `check` job; `agents/agent3_testing/suite`
(359 collected) is not.

**CYCLE 4 THEN AUDITED REGRESS TOO, FOR A DIFFERENT AND DOCS-ONLY REASON -
correct any recollection that says only cycle 3 did.** The RM-407 wrap moved
RM-406's residuals block onto the RM-407 row, so for one cycle RM-407 published
four false residuals about itself while RM-406, which has no `BACKLOG.md` body
row, carried no limits at all. Cycle 5 moved it back (`54fcf67c8`, byte-identity
proved at 353 bytes / sha256 `3e4f71e9...` on both sides) and audited CLEAN. The
defect class is row MISATTRIBUTION, not a typo: every byte was valid prose on
the wrong owner, which no spell-check, ASCII guard or link checker can see.

**CYCLE 7 SHIPPED WITHOUT RUNNING THE SUITE AND CYCLE 8 PAID FOR IT - the guard
was ALREADY RED at `7ff5fc853`.**
`tests/test_loop_director_context_caps.py::test_real_orchestration_plan_newest_row_survives`
was failing, and the only reason it was found is that cycle 8 ran the full
`tests/` tree. The stated reason cycle 7 skipped it - a prior serial run
measured at roughly four hours - no longer held: under `-n 8` the same tree
finishes in **307 seconds**. The failure is not cosmetic.
`ops/loop/loop_controller.py:623` `build_director_context` caps the plan
head-and-tail and CUTS THE MIDDLE, the session table sits in the middle, and
each appended findings block walks the newest row toward the cut - past which
the director plans the next cycle without ever seeing the newest session row.
FIXED STRUCTURALLY, not by raising the cap: six older blocks relocated VERBATIM
into `docs/ORCHESTRATION_PLAN_HISTORY.md`, R230 21306 -> **9692 bytes** against
the 15888-byte window, and a new arm requires 4000 bytes of clearance derived
from `lc.PLAN_CTX_CAP` / `lc.PLAN_CTX_HEAD` rather than a literal.

**THE EXECUTOR OVERRIDE FIRED ON SEVEN OF EIGHT CYCLES AND ITS TWO COMPLAINTS
ARE BOTH STRUCTURAL.** STALE-GROUNDING on every cycle except cycle 2 - 1, 3, 4,
5, 6, 7 and 8 - because the director keeps sourcing premises from an audit
DIGEST rather than the tree, and it was right to: cycle 7's headline premise
("NO test anywhere calls
`lib/ddragon/fetch.py`'s own writer") was REFUTED before any code was written.
SERIALIZED-DEVIATION on cycles 6, 7 and 8, on non-disjoint agent file sets. Its
collision lists are not trustworthy in detail - one names "AGENT 1 and AGENT 1"
against genuinely disjoint sets - but serializing was kept anyway as strictly
safer at the cost of one round.

**NOTHING LEFT THE TREE BEYOND ORDINARY PUSHES AND THE JOINT RE-PIN STAYED
GATED, SEVENTH SESSION RUNNING.** Zero commits today touch `ops/loop/slots.py`
or `ops/loop/winmutex.py`. RSC's newest inbox note is still
`2026-09-09-2100-from-RSC`. **Four inbox notes landed mid-run** (mtimes 12:49 to
12:55: two from LW on plugin licences and a superseded plugin, two from CS
including a WITHDRAWAL of two of their own claims and a defect report that our
hook DOES export `GIT_DIR`). **No tracked file in this run's commit range names
any of the four**, so they are unread work for the next session, not something
this run answered.

Next session: the loop is disarmed with STOP on disk and the tree clean at
`1f4b8a23e`. Read the four mid-run inbox notes before arming anything, and run
the full `tests/` tree per cycle now that `-n 8` puts it at 307 seconds - the
four-hour figure that justified skipping it is dead.

**DO NOT REDO:** RM-406, RM-407, RM-410 all SHIPPED. RM-411 is the FILED
destructive-patch subset (8 call sites across 6 files, dispositions in
`docs/audits/LF_WRITER_DIRECT_COVERAGE_2026-09-11.md`), body in `BACKLOG.md`,
next-free pin now RM-411 in `docs/DS_SWEEP_TRACKER.md`. **The `.tmp` leak in
`lib/ddragon/fetch.py:33-44` is CHARACTERIZED, NOT FIXED** - both fault arms
assert the sibling LEAKS, so a future `finally` must flip those assertions
DELIBERATELY. Do NOT re-wire `agents/agent3_testing/suite` without measuring the
supervisor flake on the runner first; the exception is the result, not a
shortfall. Do NOT re-file "`-n 8` widens the `os.replace` exposure" - xdist
workers are separate PROCESSES and that premise is REFUTED; the real window is
same-process callers, threads above all.

---

# 2026-09-11b - RM-405 SHIPPED: RM-312 had fixed the silence one layer too low, and the CALLER re-swallowed it

Tier-1, one module plus one new 19-arm guard, shipped as `fc0058441` and pushed
to `origin/main`. 9 files, 525 insertions, 24 deletions. LEDGER 1391. No engine,
no `ENGINE_VERSION` bump, no DS bounce, no Share sync, no `web/` change, no
frozen file touched. Live at wrap: pid 23096 alive, `mode=client`,
`last_reload_ok=true`.

**THE JOINT RE-PIN OF `SHARED_SHA256` IS STILL BLOCKED AND IS STILL THE GATING
ITEM, SIXTH SESSION RUNNING.** RSC silent since
`moon_sync_inbox/2026-09-09-2100-from-RSC...`. The newest inbox item overall is
`2026-09-11-0030-from-LW`, already read, no reply owed. **Nothing was armed and
nothing left the tree beyond the ordinary push** - the push diff touched neither
`ops/loop/slots.py` nor `ops/loop/winmutex.py`, and the pre-push sibling-name
sweep reported CLEAN (28588 bytes, 9 files, 1 commit message, 0 binary/LFS blobs
- LFS OBJECT CONTENT is never content-scanned, which is a named blind spot, not
a clean bill). Do NOT re-pin unilaterally and do NOT regenerate the digests from
local disk; a BYTE-level copy only, because `write_text` turns LF into CRLF and
the pin is on bytes.

**THE DEFECT: RM-312 (`3e5451ff3`, LEDGER 1390) made a fault raised INSIDE
`dashboard/_lcu_inprocess.py` visible, and its DIRECT CALLER swallowed the same
fault one frame higher.** `_read_lcu_snapshot()` at `dashboard/_state_builder.py`
caught `Exception` and set `snap = None` with no log line. **This was not
rediscovery** - RM-312's own SHIPPED body had REPORTED that site as a sibling
candidate under its fence against an unbounded bare-`except Exception` sweep, so
the previous slice filed it and this one closed it.

**THE HALF RM-312 PROVABLY CANNOT COVER IS AN `ImportError` ON THE LAZY IMPORT.**
When `from dashboard._lcu_inprocess import lcu_summary_inprocess` raises, the
module never loaded, so RM-312's logger never existed to run. That is a
structural limit of a module-local logger, not a gap in RM-312, and it has its
own arm - which also asserts RM-312's module state stays untouched, so neither
seam can mask the other. Independent lock and throttle state, deliberately
different prose, so a log reader can tell WHICH layer faulted.

**`str(exc)` IS NEVER EMITTED, RE-PROVED AT THIS SEAM RATHER THAN INHERITED.**
No `exc_info`, no `stack_info`, no f-string. A verifier drove
`RuntimeError("puuid=SECRET-LEAK-MARKER")` live and observed the marker absent
from `getMessage()`, `record.args`, `record.__dict__` and a full `Formatter`
render. The repo is PUBLIC and LCU payloads carry PUUIDs, so this gets measured
per seam every time. Contract byte-for-byte unchanged: still `None` on fault,
still falls through to `lcu_summary()`, and the success / `snap is None` /
flag-unset paths all stay SILENT.

**THE PRE-FIX RED WAS WEAK BY CONSTRUCTION AND IS NOT OFFERED AS DEFECT
EVIDENCE.** All 19 arms went red pre-fix, but on a MISSING TEST HELPER, not on
the defect - LEDGER 1390 had to make that exact correction one entry earlier, so
this slice anticipated it rather than being caught by it. **The real evidence is
anti-vacuity: stub the log call to a no-op and 13 of 19 arms go red while 6
survive, and the 6 are exactly the silent-path arms that must survive.** An
INDEPENDENT verifier reproduced the 13/6 split from a scratchpad copy instead of
inheriting the number.

**THE SLICE STALED ITS OWN CITATIONS - CAUGHT BY THE FIRST VERIFIER PASS, NOT BY
THE AUTHOR.** +83 lines near the top of `_state_builder.py`, +5 in
`_lcu_inprocess.py`. Repo-wide re-derivation followed: shift-caused offsets fixed
at +82 and +5 onto byte-identical code checked against `git show HEAD:`,
citations already wrong at HEAD for unrelated reasons left alone and reported.
`feedback_your_own_edit_staled_the_citation`, three times in four days.

**READ THIS BEFORE BELIEVING ANY `_state_builder.py:<n>` IN AN OLDER RECORD.**
`WAKEUP_NOTES.md:144` (the 2026-09-11a entry; it was `:47` before this entry was
prepended) and the pre-rewrite
`RC-NEXT-SESSION.txt:11,32` carried `_state_builder.py:92` and `:96`. Those were
TRUE AT THEIR OWN WRAP and were deliberately left as the historical record; the
`:92` gate now lives at `:173` and the `:96` except at `:177-179`. Do not read
them as live citations and do not "fix" the dated wakeup entry. **The
docs-sync pass also found that the commit's "repo-wide" sweep did NOT reach
`ROADMAP.md` or `BACKLOG.md`** - neither is in the 9-file diff - so the RM-312
SHIPPED body at `BACKLOG.md` was still quoting pre-shift offsets. All re-derived
from disk and corrected in the 2026-09-11d docs-sync; `tools/lcu_agent.py:1612`
was left VERBATIM because it was already wrong at HEAD for an unrelated reason.

**TIER-0 IN THE SAME SLICE, and it is the same shape as 2026-09-11a's lesson: a
build's FIX was right while its JUSTIFICATION was inherited from a comment.**
RM-312's shipped comment claimed 1 Hz from the stale "1.0s TTL" prose. Measured
truth is `RC_STATE_CADENCE_SEC`, default 0.5s with a 0.1 floor
(`dashboard/routes_state.py:167-178`), about 2 Hz, so the worst case is ~7200
lines/hr not ~3600. The path is DARK today - the gate at
`dashboard/_state_builder.py:173` reads `RC_LCU_INPROCESS`, unset on this box.

**OBSERVED, both figures re-run independently by a verifier to an exact match:
19 passed on the new guard; 192 passed / 21716 deselected / 56 subtests on the
widened scope; ruff clean on 8 `.py` files; 0 codepoints above 126 across all 9.**
NOT live-verified and not claimed: `RC_LCU_INPROCESS` is unset and no live
champ-select was driven, so the WARN's production text is proven by unit test
only.

**WRAP ADDENDUM - `tools/stop_claim_gate.py` blocked this session TWICE, and was
right both times.** Every headline number in the first two reports had been
MEASURED BY A SUBAGENT, never by the main thread, so the gate read them as
unbacked claims. That is the gate working as designed, not a false positive:
CLAUDE.md's Verification Discipline already says never carry a subagent-reported
count forward, and a verifier's CONFIRM is the adversarial gate on the SLICE -
it is still not the main thread's own measurement. All headline figures were
then re-run in the main thread and matched exactly: 359 + 348 = 707 uncovered
tests, 19 on the new guard, 192 / 21716 deselected / 56 subtests widened, ruff
clean on 8 files. The `ci.yml:165` + `:537` "neither CI tree" half was likewise
re-derived by hand rather than inherited.

ONE figure was first retracted as unreproducible and then turned out to be both
reproducible AND WRONG. The docs slice reported `md-guards 1782 passed`. The
selection is NOT bespoke - `tools/md_guard_selector.py` is a tracked CLI that
emits it, and `tests/test_ci_docs_guard_coverage.py:56` already names it. Run
fresh at HEAD `c7c7247b2`: **65 modules, 1777 passed, 1 skipped, 327 subtests in
149.86s**. The filed number was over by 5. Calling it unreproducible was the
LAZIER error of the two - the selector was one grep away, and running it is what
exposed the bad count.

**CRLF TRAP, worth more than the count.** The first invocation piped the
selector's output straight into pytest and printed `no tests ran in 0.05s` with
**exit code 0**. The selector's stdout carries `\r`, so every path was malformed,
pytest matched nothing, and the run reported SUCCESS. A CI step shaped that way
is silently always-green over zero tests - the `INDEX_testing_traps`
empty-enumeration class, arriving through line endings rather than through a
guard. `tr -d '\r'` fixes it. Anyone wiring the orphan suites (the fallback
below) will be composing exactly this shape: assert a NONZERO collected count,
never just an exit code.

Next session: run the numbers you intend to PRINT before you print them, or
attribute them to the agent that ran them.

**DO NOT REDO:** RM-405, RM-403, RM-404, RM-312 all SHIPPED. RM-387 / RM-388
shipped 2026-09-08. RM-313 deliberately OPEN. A general bare-`except Exception`
sweep - RM-312's fence stands, the remaining sites are a CANDIDATE POPULATION
needing its own census, and their line numbers MUST be re-derived because this
slice moved code in that file.

---

# 2026-09-11a - the HAND-OFF PROMPT was the defect, and three silent failures shipped with guards

**THE SESSION'S OWN FALLBACK WAS STALE, which is why RM-403 exists.** The 09-10e
hand-off said: if RSC is still silent, pick up RM-387 or RM-388. RSC IS still
silent (inbox newest from them remains `2026-09-09-2100`, checked FIRST as
directed, and the JOINT RE-PIN stayed gated and untouched for the FOURTH session
running). But RM-387 and RM-388 had BOTH SHIPPED on 2026-09-08, LEDGER 1368/1369,
provable in source at `tools/inbox_responder_runner.py:1772` and `:976`. Second
consecutive session opening on rediscovery - 09-10e was Q5. **The difference: no
recall gate covers a stale FALLBACK, because ROADMAP was the instrument and
ROADMAP was wrong.** So the answer was a machine check, not a doc edit.

**THREE ITEMS SHIPPED, ALL THE SAME FAILURE MODE IN DIFFERENT COSTUMES - nothing
announced itself.**

- **RM-403** (`8895793d9`, filings `dd0a2f3b0`, LEDGER 1388) - ROADMAP and BACKLOG
  could disagree about whether a row was OPEN and nothing checked. FOUR rows were
  drifted (RM-250 / RM-291 / RM-387 / RM-388), each corroborated TWICE, by a
  LEDGER entry AND a code probe. Guard `tests/test_roadmap_backlog_disposition_drift.py`.
  **The binding rule is the whole substance:** a disposition binds to the NEAREST
  PRECEDING id only. Two live controls are pinned - `RM-281 HALF-CLOSED + RM-283
  OPEN` (the OPEN belongs to RM-283) and RM-204, whose first vocabulary hit sits
  in lowercase prose. A first parser called RM-204 a fifth drift row and was
  NARROWED, never allowlisted. Do not widen it.
- **RM-404** (`2ca7bb66c`, LEDGER 1389) - **4 of 5 printed `schtasks` commands were
  broken and the failure is SILENT**: PowerShell reports errors=0 and splits the
  block into 2 statements, running `schtasks /Create` WITHOUT its `/TR` payload.
  `tools/liveclient_relay.py:14` measured FINE and was deliberately left alone.
  Repaired with `Register-ScheduledTask`; **do NOT hand-fix the caret escaping.**
- **RM-312** (`3e5451ff3`, LEDGER 1390) - `dashboard/_lcu_inprocess.py` swallowed
  every L3 fault with NO logger in the module at all. Row was ACCURATE, not stale.
  Now throttled WARNING; contract unchanged; **`str(exc)` never emitted** because
  the repo is PUBLIC and LCU payloads carry PUUIDs.

**THE RECURRING SHAPE THIS SESSION, worth carrying forward: a build agent's FIX
was right while its JUSTIFICATION was wrong.** RM-312's "1 Hz hot path" was
inherited from a STALE COMMENT (`routes_state.py:210` says 1.0s TTL); the real
cadence is `RC_STATE_CADENCE_SEC` default 0.5s (~2 Hz), and the path is **DARK**
today - `_state_builder.py:92` gates it on `RC_LCU_INPROCESS`, which is unset.
RM-404's builder reported 9/9 red with one message when only 8 carried it. Both
corrected in the shipped artifacts, not just in chat.

**ANTI-VACUITY WAS PROVEN, NOT ASSERTED, on every guard** - stubbing RM-403's
parser empty turns 15 arms red; RM-312's arm went red alone under a mutated
short-circuit. A guard asserting an empty set passes forever once the docs are fixed.

**CI TRAP, now measured: two `ci` runs this session read `cancelled`, which is
SUPERSESSION, not failure** - each was killed by the next push. Only the final
HEAD's run is authoritative. `3e5451ff3` is green on BOTH `ci` and `docs-guards`.

**INBOUND: three LW notes read, none requiring a reply.** LW refuted the
shared-conftest premise on a SECOND tree (now dead, not merely retracted), and
repaired their own 43 false-RED sites to 0. Their 00:30 note disclosed a published
`schtasks` line that did not work - **that is where RM-404 came from.** The rule:
an arm proving a command is not executed says nothing about whether it is correct.

**DO NOT REDO:** RM-403, RM-404, RM-312 SHIPPED. RM-387/RM-388 shipped 2026-09-08.
RM-313 deliberately OPEN. The joint re-pin is still BLOCKED on RSC - do not re-pin
unilaterally and do not regenerate digests from local disk.
