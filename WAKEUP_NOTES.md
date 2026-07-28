# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

## 2026-07-27i - R212 the Meraki half of the premise did not exist, the defect did (ENGINE 1.261.0 -> 1.262.0, `3811d2aa`)

**Ninth cycle in ten with a premise false on disk - but this one split cleanly
in half, and only one half was wrong.** The directive ordered a DS sweep of
Yasuo / Yone / Jhin / Senna innate crit modifiers "vs Meraki bulk truth" and
tagged that premise `[UNVERIFIED]` itself. Verified before any code:

- `data/daemon_slayer/16.14.1/` holds `items_meraki.json` and NO champion-level
  Meraki file at all. There is no Meraki bulk truth for a champion innate.
- `_passive_as_lock_overrides.py:12` already says so verbatim - "DDragon /
  Meraki strip Whisper's numbers (Jhin's champion record is prose-only)".
- `_crit_conversion_overrides.py:32-39` says no structured Meraki / DDragon
  field encodes a champion's crit rule, which is precisely why that sibling
  registry is hand-authored from cited prose.

So the METHODOLOGY was false. The SUBSTANCE was true, and re-grounding it on the
source the sibling registries already use - the on-disk `champion_abilities.json`
passive prose - turned a no-op directive into a real three-axis gap.

**The gap.** `dps.py:893` resolves every champion as `ad * (1 + crit * crit_bonus)`.
RM-46 overrides exactly one axis of that expression, the additive crit-damage
bonus, and only for Ashe. Nothing anywhere reached a crit-CHANCE multiplier
(Yasuo / Yone x2.0), the above-100-percent overflow conversion (0.5 bonus AD per
excess point; Senna 0.35 percent life steal), or a crit-damage MULTIPLIER on the
whole `(1 + crit_bonus)` product (Jhin 0.86) - the last of which is not
expressible as RM-46's additive term at all.

**Test-Not-Transcript.** Jhin's own note states the order of operations verbatim,
`(100 + 75) x 0.86` rather than `100 + (75 x 0.86)`, and both that and the
crit-damage-item form are pytest assertions rather than prose. A drift guard
opens the ability JSON at test time and asserts each quoted fragment still
exists, so a Riot rewrite goes RED instead of leaving a stale rule.

**Known limit stated, not hidden.** Senna's row is a ground-truth record with no
live term: `dps.py` clamps resolved crit at 1.0 before the registry is consulted
and her multiplier is 1.0, so her excess is always zero. No consumer was invented
for it. Yasuo / Yone overflow AD IS live.

DS 10053 -> **10100 passed** / 5701 subtests. RC `tests/` **13715 passed** /
106 skipped / 460 subtests. ruff clean, drift_guard 0 breaches, verifier CONFIRM
7/7. Tier-2: ENGINE bump across all 7 anchors, 146 pins over 125 DS test files,
both stamped build-order keyspaces regenerated, DS `:8893` bounced and re-probed
at 1.262.0, Share mirror `--check` green.

**CARRY-FORWARD, eighth cycle:** controller pid 18300 started `00:37:50` and
still cannot load its own self-reload fix. MUST BE BOUNCED BY HAND ONCE; it
cannot be done from inside a cycle it would kill.

---

## 2026-07-27h - R211 the incident writeup was the next incident (ENGINE-IMPACT NONE, `61401222`)

**Eighth cycle in nine with a premise false on disk, and this time the premise
came from us.** The directive was cycle 15's, repeated: fix-first REGRESS on
invalid action refs at `docs-guards.yml:62,69`. Disk says that file has `uses:`
at 61 and 68 only, both real tags; all 10 refs across the 3 workflow files are
real; `gh run list` shows every recent `ci` / `docs-guards` / `CodSpeed` run
completed SUCCESS, including at the exact HEAD the audit called regressed. Two
of the three reported failures were fabricated.

**The third was true, and it is the whole finding.** Item 1084 - R210's own
writeup, one cycle earlier - quoted the hallucinated literal VERBATIM into
durable prose. The auditor is a diff scanner over model-authored markdown, and
that token has the exact shape of a `uses:` ref whose version tag was replaced
by a file path. So every later diff carrying that doc line re-manufactures the
same false REGRESS. The fix documented the trap and armed it in the same commit.

DEFECT-CLASS ENUMERATION is why this was not a one-line edit. The directive
scoped the grep to `docs/LEDGER.md`. A literal grep finds 4 files. The
shape-precise sweep finds **7 lines across 4 files carrying THREE distinct
fabricated literals** - R210's, a 2026-07-05 one, an R175 one. The class is the
writeup habit, not the incident. And `ORCHESTRATION_FINDINGS_ARCHIVE.md:378` is
self-referential proof it recurs: it records cycle 8's auditor reading cycle 7's
QUOTATION of a hallucinated string and re-flagging the quote as a fresh defect.
Written down once, then left armed for three weeks.

All 7 now write the literal with `[at]` for the bare `@`. Preservation is
machine-checked, not eyeballed - `git diff --word-diff` is exactly 7 changed
word-pairs, each satisfying `minus.replace('@','[at]',1) == plus`, zero prose
reworded or deleted, so the historical records stay byte-intact.

New guard `tests/test_doc_action_ref_hygiene.py`, 7 tests. Three properties
worth keeping: it enumerates via `git ls-files` so an untracked scratch file
cannot fail the suite; it carries a negative control asserting the pattern still
MATCHES the real incident token, so a future failure cannot be "fixed" by
loosening the pattern until it matches nothing; and it builds that token by
runtime concatenation rather than containing it contiguously, because a guard
that re-armed the trap it disarms would be worse than no guard. Scope is `.md`
only and that fence is deliberate - the elided `test_x.py` form in
`ops/loop/executor.py` and `tests/test_loop_executor.py` is the exemplar R210's
grounding guard is specified against. Prose docs are the diff-poison surface;
code is not.

Verifier CONFIRM 9/10, the tenth being pre-existing LEDGER glyphs on untouched
lines. It proved the guard can FAIL rather than only pass: a poison line
appended to a tracked doc turned it red and named the file:line.

RC `tests/` 13706 -> **13713 passed** / 106 skipped / 460 subtests, +7 exact.
Ruff clean. DS untouched. Tier-1: no ENGINE bump, no DS bounce, no restart, no
Share sync.

**CARRY-FORWARD, seventh cycle, and it now has a measured cost.** Controller pid
18300 started `00:37:50`. The R210 guard - built to flag exactly this unverified
`[from-digest]` premise - landed in `executor.py` at `12:53:04` the same day. It
is on disk and DEAD IN MEMORY, which is precisely why this cycle's false premise
arrived unflagged. **It must be bounced by hand once**, and cannot be bounced
from inside a cycle it would kill.

Minor drift fixed in passing: R210's hand-off entry was written as an `h1` at
the BOTTOM of this file with a `2026-07-27c` suffix already used by R206.
Promoted to `##` and re-lettered `2026-07-27g` in place so `wakeup_prune.py`
sees it; its position at the file tail is left alone rather than risk a block
move, and is noted here for the next prune.

---

## 2026-07-27f - R209 docs-only pushes ran no CI while 49 guards read docs off disk (ENGINE-IMPACT NONE, `2719dc2a`)

**Seventh cycle in eight with a premise stale on disk.** The directive was
f1-phase6 item 5, the codebase-wide `skipif` audit, for the THIRD time. It shipped
at `54bad078` (R200) and its AST regression guard shipped at `f24dea5f` (R203); the
13 `pytest.mark.skipif` sites left on disk are the audited CAPABILITY-OK residue
plus the guard's own fixtures. R202's carry-forward still explains the repetition
and is now FIVE CYCLES OLD AND UNCHANGED: controller pid 18300 started 00:37:50,
before the self-reload fix `d4b1a762` landed, so the running image cannot load its
own fix. **It must be bounced BY HAND once.** Nothing in an executor cycle can do
it - the fix cannot install itself.

Re-cut to R208's own explicitly-unfixed carry-forward, which is the R207 class one
more time: a guard exempted from the thing it guards. `ci.yml` has carried
`paths-ignore` on markdown since the 2026-06-30 MINUTE SAVER, but 49 test modules
read a tracked `.md` off disk and assert on its content. **It had already fired
twice, in the two commits immediately before this one.** `6bad3814` was docs-only
and turned `test_real_orchestration_plan_newest_row_survives` RED; `8d22734b` was
the docs-only FIX, so the fix's own green was never machine-confirmed either.

Closed with a COMPLEMENT workflow rather than by weakening the filter. The minute
saver is untouched and now pinned by `test_minute_saver_is_still_in_place`;
`docs-guards.yml` fires on exactly what `ci.yml` and `codspeed.yml` decline. The
selected set is DERIVED AT CI TIME by `tools/md_guard_selector.py` against
`git ls-files`, never hand-listed in YAML - a hand-written universe is the
`SCHEDULED_SPAWNERS` scar and the R200 scar (51 conversions shipped with no machine
guard, so nothing stopped #52 and #52 already existed), and such a list stays GREEN
over its own blind spot.

Two class enumerations. Every paths filter: 6 across 3 workflows - `codspeed.yml`
was NOT assumed clean because `ci.yml` was the reported site, and it carries the
identical filter. Md-reading modules: 49. The build agent's first heuristic proved
its own hole and it said so - requiring disk IO beside the literal dropped
`test_doc_size_budget.py`, which reads CLAUDE.md through `.stat().st_size`.

**The verifier gate earned its slot on the count discrepancy.** The worktree run
reported 13644 passed / 146 skipped against a 13677 / 106 baseline. Rather than
wave that through as worktree noise it diffed the nodeid sets: 39 pass-on-main /
skip-on-branch, all gitignored-data reasons, and ONE pass-on-main / FAIL-on-branch.
Arithmetic closes exactly at 13677 + 7 - 39 - 1 = 13644.

**CARRY-FORWARD, pre-existing, NOT fixed here:** the suite writes gitignored
`data/fusion_shadow.jsonl` itself, so in a pristine checkout run 1 SKIPS
`test_real_fusion_shadow_corpus_invariants` and run 2 FAILS it, seeded by a single
238-byte record. Masked on main by a 285-record corpus. Proven by copying main's
corpus into a branch export and getting 13 passed.

**LIMIT:** the new workflow has never executed on GitHub. It parses with a real
parser and its filter is correct, but the GitHub-side trigger semantics are
unproven until the first docs-only push - which is the real acceptance.

RC `tests/` 13677 -> 13684 passed / 106 skipped / 460 subtests (+7 exact); ruff
clean; 0 non-ASCII. DS untouched. Tier-1. This row recorded as a TABLE ROW in
`docs/ORCHESTRATION_PLAN.md`, not a prose section, per `8d22734b`; newest row now
sits 14753 bytes from EOF against the 16000 tail.

---

## 2026-07-27e - R208 the director stamped its own premises UNVERIFIED and nothing read the stamp (ENGINE-IMPACT NONE, `f4815e16`)

**Sixth cycle in seven with a premise stale on disk.** The directive was the
f1-phase6 inbox apply again. STEP A ordered a commit of staged `.githooks` changes -
`git diff --cached` empty. STEP B ordered `winmutex.py.from-lw` applied plus the
item-5a pin - `ops/loop/winmutex.py` already `f1b4b011...`, byte-identical to the
inbox copy (bytes compared, not digests-of-record), already pinned by
`SHARED_SHA256` beside `slots.py` `95077a62...`, UNSERIALIZED already 3, both POSIX
monkeypatch tests already present. STEP C ordered claiming queue item 2, which
shipped `05319608` / `54bad078`. Nothing to do; measuring that was deliverable one.

**Re-cut to the guard that let it through.** `director_prompt.md:18` mandates a
`PREMISE-CHECK` line tagging each claim `[from-digest]` or `[UNVERIFIED]`.
`executor.py:420-424` checked the other two grounding fields and DELIBERATELY
abstained on this one as "free prose with no machine-readable referent". Half right:
the executor must not judge whether a semantic claim is true, but the referent is the
TAG - the director has already called the claim an unknown. The file states its own
doctrine four times that an unknown is never a pass (`:188`, `:213`, `:478`, `:558`),
and the one place the director stamps its OWN doubt was the only self-declared
unknown in the seam that failed OPEN. 13 `unverified` hits across `ops/loop`, all in
`executor.py`; three shapes already fail closed, the fourth fixed here.

**The defect was in the guard's own regression corpus from day one.** `_R200` at
`tests/test_loop_executor.py:1064`, the fixture for the ORIGINAL incident this guard
was written for, ends `PREMISE-CHECK: winmutex.py still carries the old bytes
[UNVERIFIED]` and main returns only `['stale-head']` on it. Every existing test
survived the change because every one filters by finding kind.

**The verifier gate refuted the build twice and both were false NEGATIVES.** (1) A
trailing tag folded in the preceding claim, and two trailing tags on one line dropped
the first claim outright. (2) Only the first line-anchored `PREMISE-CHECK` was
scanned, so an indented block-quote of a prior directive above the real field
silenced the guard - live shape, this loop quotes prior directives constantly. (3)
The sentence-split fix for (1) introduced a third: claims opening with an
abbreviation vanished (`e.g.` / `i.e.` / `cf.` / `etc.` / `vs.` / `no.`). Fixed by
keeping the sentence edge only on the BACKWARD path where defect 1 lived; forward
reads tag-to-next-tag and cannot mis-split an abbreviation.

**Don't-redo:** `PREMISE-CHECK` `[UNVERIFIED]` tags are now machine-read and produce
findings - do NOT re-pitch "the executor should check premises". `GROUNDING_MARKER`
stays `executor: STALE-GROUNDING` deliberately (operator grep token + historical
`controller.log` lines); the detail string carries the discriminator instead.
`grounding_findings` MUST stay pure - no fs, no git on the premise path.

**Counts:** `tests/test_loop_*.py` 361 -> 385 (+24 exact); RC `tests/` 13653 -> 13677
passed / 106 skipped / 460 subtests (+24 exact); ASCII hygiene 14; ruff clean
repo-wide; 0 non-ASCII. DS untouched. Tier-1. A build-agent count of 382 was retired
rather than carried - real run, wrong label (an explicit 19-file list including
`test_lcu_loop_resilience.py`, not a `test_loop*.py` glob match).

**Carry-forward, unchanged and now five cycles old:** the running loop controller
still predates `d4b1a762`, so it cannot load its own self-reload fix. It must be
bounced BY HAND once.

---

## 2026-07-27d - R207 the reports dir was exempt from the guard that would have caught it (ENGINE-IMPACT NONE, `829700e1`)

**The first cycle in six whose premise actually held on disk.** The named file really
did carry non-ASCII, so the deliverable was the thing the directive pointed at rather
than a correction of the directive - plus the structural reason it survived a week.

**Enumerated the directory, not the one file.** 4 tracked, 3 dirty, 58 bytes / 22
characters: `20260720-140835` U+2713 x3 + U+2014 x4, `20260721-140611` U+00D7 x8,
`20260727-141821` (the named one) U+2713 x3 + U+2014 x4, `20260719-183521-FAILED`
clean. Fixing only the named file leaves two siblings holding the identical class.
The director guessed "???, em-dashes, or emojis" and only em-dash was right; the real
set is a decorative checkmark, an em-dash, and a multiplication sign used as a table
bullet, mapped to `OK` / ` - ` / `x` so meaning and column width both survive.

**Two independent failures, and the second is the load-bearing one.** These files are
written by cloud scheduled routines committing straight to main
(`weekly-ddragon-audit@anthropic-routines`, `ef8ade31`), so no PreToolUse hook and no
git hook on Legion is ever in the path - CI is structurally the only gate that can
fire. And `test_smart_quote_hygiene.py:121-125` blanket-exempted the whole directory
from the tree-wide walk on an immutable-dated-artifact rationale. That rationale is
**correct for history and wrong for a directory a robot appends to weekly**: it
exempted not just the past but every future write. The one gate that could have
caught this had been told not to look.

**Both sides measured.** A guard passing on clean data proves nothing. Injecting
U+2713 + U+2014 fails BOTH the now-unexempted `test_no_smart_quotes_in_authored_source`
(em-dash) AND the new `test_agent6_reports_are_ascii` (checkmark). The banned set is 8
codepoints and would have caught only 8 of the 22 characters here, which is why the new
test asserts full 7-bit ASCII rather than the banned set.

**The repo corrected the fix.** First draft used `pytest.skip` on an absent dir;
`test_skip_condition_hygiene.py` rejected it - the dir is tracked, so absence is a
defect that must FAIL, not silently pass. Now a hard assert.

**STILL OWED:** the routine's prompt is the true origin, lives in cloud scheduling
config, is not in this repo, and is not reachable from an executor cycle (`CronList` is
session-scoped). Until an operator edits it via `/schedule`, next Monday may land
another checkmark - and CI will now go red on it by design rather than pass in silence.

Carry-forward, now seven cycles old: the running loop controller predates its own
self-reload fix and needs one manual bounce. No executor cycle can supply it.

RC 13653 passed / 460 subtests. DS 10053 passed / 5585 subtests.

---

## 2026-07-27c - R206 the guard recorded its correction where the guilty party never looks (ENGINE-IMPACT NONE, `7c8765a6`)

**Two of the directive's four steps were no-ops - fifth straight cycle with a stale
premise.** STEP 1 wanted a staged `.githooks` exec-bit commit: nothing staged, tree
clean, already `100755` since `19b680cc`. STEP 4 wanted the TEST-NOT-TRANSCRIPT rule
made durable: already at `director_prompt.md:147-153`, already pinned by a test.

**So the cycle became STEP 3, and item 7 turned out to have three pieces.** The parser
and serialize override shipped long ago; the director-side contract shipped R204. The
missing one was REPORTING.

Both executor guards correct a bad directive, log to `controller.log`, then ask the
model: *"State this deviation in your summary line."* That ask was the whole mechanism,
and **controller.log is not a director input** - the controller takes `rec.raw` (the
MODEL's payload) and dumps it forward as `=== LAST claude.done ===`. So whether the
director ever learned its directive was wrong depended on the model volunteering it.
A model that silently complies teaches it nothing, which is verbatim what the guards'
own comments say recording exists to prevent, one layer up. Now a mechanical stamp.

**The verifier gate paid twice, and the second one is the reusable lesson.** CONFIRM
8/8, plus one out-of-claim observation that was a real defect: the four sdk failure
paths stamped the record but left `raw` empty, so a cycle that deviated and then DIED
carried the correction nowhere - the branch with no model prose at all.

Then the merger found a second hole **by checking the PRODUCER instead of the test
fixture**. Every new test handed the ahk channel a payload with a `summary` key.
`done_sentinel.py:45` writes cycle / sha / tests_pass / regressions and no summary at
all - so every LIVE cycle took the branch no test exercised, and the unconditional
write-back was adding `"summary": ""` to the director's context on every CLEAN cycle.
A fixture shaped to the feature rather than to the real producer hides exactly this.

Both merger fixes proven by mutation, not argued: reverting the guard injects exactly
`'summary': ''`; dropping the error-path raw raises `KeyError: 'summary'`.

Cross-repo reply sent under the channel's dated convention rather than the
`rc_sync_reply.txt` the directive named (flagged, not silently renamed). It answers
LW's `is_absolute()` ordering question (RC guards inside `_cfg_path` before the
import-time mkdir - RC cannot mint the drive-letter dir), acks LW's own retraction of
a false CI-green claim, and records their blind-configuration rule as an OPERATOR
decision rather than building it. Neither shared file nor the pin was touched.

**CARRY-FORWARD, six cycles old: the controller must be bounced by hand once.** It
predates its own self-reload fix and no executor cycle can supply the bounce. This is
the measured cause of the stale-premise run.

RC `tests/` 13639 -> **13652 passed / 106 skipped / 460 subtests** (+13 exact: 9 build
agent, 4 merger). DS 10053 / 5585 untouched. ruff clean. 0 non-ASCII. Tier-1.

---

## 2026-07-27b - R205 the nightly was red for a month of cycles and the directive kept aiming elsewhere (ENGINE-IMPACT NONE, `1ce998a0`)

**The directive's four ordered tasks were all already on disk.** Fourth consecutive
cycle with a stale premise. Checked before writing anything: the winmutex inbox APPLY
was a no-op (both files hash `f1b4b011...`), the UNSERIALIZED bump / POSIX tests /
`SHARED_SHA256` pin are at `tests/test_loop_concurrency.py:310` / `:316` / `:336` /
`:362`, `_is_on_disk_executable` is at `ops/loop/executor.py:874`, and the skip audit
shipped `f24dea5f` and ran 22/22 green.

**So the work became what the directive was aiming at and had mis-diagnosed.** Nightly
`30261946219`: `5 failed, 23474 passed`. Every PUSH run green. The whole delta is that
those five tests assert against the Legion working tree - green here, structurally red
on any fresh POSIX clone.

**Two were real production defects, not test artifacts.**

- `loop_controller.py` defaulted its config to an absolute drive-letter literal. Off
  Legion the read raised, the except set `CFG = {}`, and the controller ran configless
  while reporting nothing. The tracked `config.json` was never the problem - it was
  never opened. The missing 5273-byte operator brief is one failure directly and the
  other transitively: overflow repayment only fires above `GEMINI_STDIN_CAP`, the live
  margin is 6591 bytes but 996 with `CFG={}`, so nothing overflowed and the plan marker
  stamped the full cap. **It was passing on Legion by 512 bytes of ambient margin.**
- The executor's teardown was `taskkill` alone. On POSIX that is a missing executable,
  the error was swallowed, the child survived, and the bounded reap re-raised
  `TimeoutExpired` outside any handler. That is why CI said 30 seconds against an
  injected 2s deadline: **the exception came from the reap, not the deadline.** A
  surviving child holds the mutex the next cycle waits on.

**The vacuous-pass twin is the finding worth carrying.** Fixing
`test_mutex_serializes_two_threads` (asserts `peak == 1`, which `winmutex` openly
declines off win32) meant auditing the skip, and the audit found
`test_mutex_is_reentrant_for_the_same_thread` broken the OTHER way: the POSIX no-op
nests happily, so it went GREEN on every Linux checkout while proving nothing. **No red
would ever have surfaced it.** When you skip a test for an absent capability, check
whether its siblings are passing for the same reason.

Skips must not delete coverage, so the POSIX contract gained the half nobody had pinned:
both existing no-op tests are single-threaded and only read the log, so "never claims
ACQUIRED" was covered and "never serializes" was covered by nobody.

**The hardcoded root was a class, not a line.** A sweep found `done_sentinel.py:15` and
`claude_stub.py:20` with the same literal and strictly worse - no override, no fallback -
unnoticed because neither mkdirs at import. Worst in `claude_stub.py`: the dry-run stub
exists to prove the plumbing without spend, so a stub that only runs on Legion cannot
prove the plumbing anywhere it is in doubt. Shipped `tests/test_loop_module_root_resolution.py`
(RED first, 5 failed). **Its first run flagged a fourth I had not seen** -
`adjudicator.py:25` `DEFAULT_CLAUDE_CMD` - which is an external TOOL path with no
repo-relative answer and an existing config override. Widening to cover it would have
forced a fake fix, so the scan is scoped by name and the exclusion is written in-file
with its reason.

**The verifier gate paid for itself twice.** Slice C was REFUTED: it hid the spawn behind
`**kwargs`, which the console-flash guard resolves BY AST, so the guard went 18 passed ->
2 failed and went blind to the loop's only spawn site. Runtime behavior was fine - but for
a defect whose only symptom is a flicker on the operator's desktop, **the static proof IS
the protection.** Rebuilt with `creationflags=` literal at the `Popen`; the guard itself
was not touched, because teaching a guard to trust an indirection defeats it for every
future spawn site. Slice B's verifier independently found the two sibling roots; slice A's
falsification-probed the new POSIX test; slice C's caught the agent's own arithmetic (87
baseline, not 95).

**CARRY-FORWARD, five cycles old and now worse - re-verified live, not recited:**
controller pid 18300 started `00:37:50`, `loop_controller.py` mtime `08:20:22`. This cycle
edited the very module the running image cannot reload. **It is un-actionable by any
executor:** bouncing the controller mid-cycle abandons the `claude.done` handshake it is
blocked on, and R202's self-reload guard is itself in the code the stale image cannot load.
It needs one external bounce. No cycle can supply it.

Reply written to the Sibling-A inbox with post-apply digests, flagging that both the
hardcoded-root and the vacuous-reentrancy defects are likely present LW-side. Neither
shared file was modified and no re-pin is proposed - said out loud, because a re-pin is a
joint act and silence reads as consent.

RC `tests/` **13639** / 106 skipped / 460 subtests. Loop set 111. Console-flash guard 18
(matches clean main). ruff clean, 0 non-ASCII, CI green on `f0f3fd32` and `1ce998a0`.
Tier-1: no ENGINE bump, no DS bounce, no RC restart, no Share sync.

## 2026-07-27a - R204 the executor could prove disjointness, the director was never told how (ENGINE-IMPACT NONE, `7f89cd6c`)

f1-phase6 items 7 and 11 land as durable HARD RULES in `ops/loop/director_prompt.md` - the
one file the controller re-reads every cycle, deliberately excluded from `CODE_FILES`.

**Item 7 was HALF SHIPPED and the missing half was the expensive one.**
`ops/loop/executor.py` already carries the entire enforcement side: `parallel_plan()` at
`:198`, the four-valued `none/disjoint/overlap/unverified` verdict, `SERIALIZE_HEADER`
`:253`, `UNVERIFIED_HEADER` `:254`, `PARALLEL_MARKER` `:101`. Nothing had ever taught the
DIRECTOR what shape that parser reads. R200 is the live scar: the directive named 2
parallel agents, `parallel_plan` could not read labelled file sets, the executor prepended
a serialize override - and the sets had been disjoint the whole time. The directive had
just not written them where the parser looks. R203 hit the same override and sidestepped
it by dropping to one agent.

So the rule does NOT say "assert disjointness". It carries a NORMATIVE exemplar between
`CANONICAL PARALLEL BLOCK - BEGIN/END` markers that the director copies, with the prose
explicitly subordinate ("if the two ever disagree, the BLOCK wins and the prose is the
defect"), plus machine-checkable `PARSES:` / `DOES NOT PARSE:` literal lists carrying the
`\d{1,2}` id width and the `^`-anchoring claim as EXAMPLES rather than as prose.

**The first build was refuted at the verifier gate, and the refutation is the lesson.**
Its 9 tests hardcoded `AGENT 1:` in their own bodies, so its docstring's anti-rot claim
was false. The verifier reworded the rule to prescribe a THREE-digit id (`_BLOCK_HEAD_RE`
accepts `\d{1,2}`) and separately to allow a mid-line heading (the regex is `^`-anchored) -
each aims the director at a guaranteed deviation - and all 9 tests stayed GREEN. Only
deleting one of 6 literal tokens killed anything: a substring pin wearing an anti-rot
label, the same always-passing class as `SCHEDULED_SPAWNERS` pre-`756db42a`. Rebuilt so
the shape is read OFF DISK - `_exemplar()` slices the marker block into the real
`parallel_plan()`, `KEYWORDS` is regexed out of the rule text, the PARSES/REJECTS literals
are read from their spans.

Second round MERGE: 12 tests, every one with an independent kill. The verifier also
attacked the marker slicer itself, where an always-passing guard would hide - deleting a
marker, planting a SECOND identically-marked block, and emptying the block between intact
markers each go RED, because `_exemplar()` asserts exactly-one before slicing. LIMIT
RECORDED, not papered over: a prose-only reword contradicting the exemplar stays uncaught,
because prose is not checkable - which is exactly why the block is normative.

STEP A of the directive was a no-op and measuring that was the first deliverable:
`git diff --cached` empty, `.githooks/*` already `100755` in the index. THIRD consecutive
cycle whose stated premise was stale on disk.

**CARRY-FORWARD, four cycles old and unchanged: controller pid 18300 started 00:37:50,
before `d4b1a762` landed, so the running image still cannot load its own self-reload fix.
IT MUST BE BOUNCED BY HAND ONCE.** Second carry-forward, newly ENUMERATED rather than
characterized: nightly `30261946219` is red on exactly 5 ubuntu-only loop-infra tests -
`test_mutex_serializes_two_threads`, `test_loop_director_context_caps` x2,
`test_sdk_timeout_kills_the_tree_and_fails_the_cycle`, `test_gate_is_active_in_this_repo`.
Predates this cycle; push CI green on HEAD.

RC `tests/` 13606 -> 13618 passed / 106 skipped / 460 subtests (+12 exact). DS 10053 / 0
skipped / 5585, untouched. ruff clean; `drift_guard` 0 breaches; 0 non-ASCII added.
Tier-1: no ENGINE bump, no DS bounce, no RC restart, no Share sync.

---

## 2026-07-27 - R202 the controller never loaded the fixes shipped to it (ENGINE-IMPACT NONE, `d4b1a762`)

**The directive ordered f1-phase6 item 2 for the SECOND time and it was already on disk**
(`ops/loop/executor.py:874-886` `_is_on_disk_executable`, pinned by
`tests/test_loop_executor.py:381-465`, shipped `05319608` / LEDGER 1074 at 03:23 the
same morning). A second refutation of the same row teaches the director nothing, so the
deliverable was the reason the repetition keeps happening.

**R201 diagnosed it correctly and shipped the fix to a process that could not receive
it.** `control/RUNNING.lock` pid 18300 started 00:37:50; `6c3851d0` / `ff439e14` /
`d048f96f` landed 05:03:56 / 05:24:57 / 05:34:14. Python binds a module ONCE at process
start. Two live artifacts prove it by strings CURRENT code cannot emit:
`control/_gemini_in.txt` (05:45, written BY that process) carries
`LEDGER head truncated at 8000 bytes`, the label of the PRE-fix `cap_bytes` call at
`6c3851d0^:431` (HEAD goes through `ledger_digest`, whose marker says "older items
omitted"); and `6c3851d0`'s OTHER fix
(`DIRECTIVE_METADATA_PREFIXES`, so a chain record stops being titled with its grounding
metadata) is equally inert - the records that process wrote at 05:04:46 and 05:45:58 are
still titled `GROUNDED-AGAINST: ...`.

**The stdin cap DID also fire at 05:45** - the pre-fix image overflows, so the blind
60/40 cut ate the plan tail and the ledger digest header, exactly the failure `ff439e14`
fixed at 05:24 and this process never loaded. **Near-miss worth keeping:** the artifact
carries `STDIN CAP: middle truncated` TWICE - one real cut, one quoted at
`docs/LEDGER.md:47` (item 1075 narrating the R201 fix). I found the quoted one first and
concluded the cap had not fired; the verifier refuted it on occurrence count. Check the
process start time against the file mtime BEFORE re-diagnosing code, and count marker
occurrences before attributing one.

**The fix.** `loop_controller` digests its own imported source (itself plus `executor` /
`adjudicator` / `slots` / `winmutex` - `_bind` puts all four in the same image) and
`os.execv`s at a cycle TOP when the digest moves. `os.execv` preserves the PID, which is
what makes it safe against `claim_repo` (holder is compared to `os.getpid()`). The guard
sits beside the cycle-top STOP poll, the only point with no handshake in flight. The
cycle counter survives via consume-once `control/resume_cycle.txt` so a code edit cannot
reset `max_cycles`, and gemini spend re-seeds from `budget.json` as a FLOOR so an
automatic restart cannot reset `ceiling_usd`. An exec failure logs and continues on the
stale image - a stale controller emits duplicate directives, a dead one emits nothing.
`director_prompt.md` is deliberately NOT in the digest (re-read every cycle), pinned by
test.

**CARRY-FORWARD, and it is the only thing that finishes this item: the running controller
must be bounced BY HAND once.** The fix cannot install itself - that is the finding.
`taskkill /F /PID <controller-pid>` then relaunch via
`ops/loop/launch_loop.ps1 -Mode live`. Until that happens the live loop is still the
00:37 image and will keep re-emitting closed rows.

**Six sibling gaps FILED not fixed** (BACKLOG "Reliability / hardening"), 39 candidates
dispositioned. Two were live-stale when measured: `RC-DS-MatchDB-MCP` pid 1940 (07-25
code, imports `core/build_order.py` edited 07-25 16:02 and `core/daemon_slayer_client.py`
edited 07-27 01:17) and the vision server pid 10788 (07-05 code, survives a `main.py`
restart because `dashboard/server.py:207-219` self-heals on PORT LIVENESS only). Memory
`reference_phase3_supervisor_stale_code` corrected: its "systemic gap" was closed
2026-05-18 and `rc_supervisor.py:379-386` is now the reference implementation.

RC `tests/` 13584 passed / 106 skipped / 460 subtests; DS 10053 passed / 5585 subtests;
ruff clean; Share `--check` in sync (1.261.0, 511 files). Tier-1: no ENGINE bump, no DS
bounce, no RC restart. TDD RED 17/17 -> GREEN 17/17.

---

## 2026-07-27 - R200 f1-phase6 items 2 + 5: the exec-bit commit gate and the 155-site skip audit (ENGINE-IMPACT NONE, `05319608` + `54bad078`)

**The directive came wrapped in an EXECUTOR OVERRIDE telling me to serialize because it
could not verify the two named agents had disjoint file sets.** It was verifiable, and
proving it before dispatch was the first deliverable: agent 1 owns
`{ops/loop/executor.py, tests/test_loop_executor.py}`, agent 2 owns `{the skip sites
under tests/** + agents/**/tests/**, docs/SKIPIF_AUDIT_2026-07-27.md}`, and
`tests/test_loop_executor.py` has ZERO skip constructs by grep, so the intersection is
empty and the round ran in PARALLEL as originally specified. Stated here and in the
LEDGER because the director never reads the override file back.

**Item 2 - the commit gate read the git INDEX mode and never the on-disk exec bit.**
Yesterday's fix caught the tracked-100644 case; a hook can be tracked 100755 and still
be 644 in the working tree (`chmod -x`, `core.fileMode=false`, an export or rsync that
dropped modes), and git skips it silently, so that clone ran ZERO hooks while
`gate_inactive_reason` said green. Same always-passing class, one layer down. Probe is
`os.access(p, os.X_OK)` behind `_is_on_disk_executable`, a documented no-op on nt, so
the POSIX branch is tested on Windows by monkeypatching the helper - NOT by a `skipif`,
which would have been the exact anti-pattern the sibling slice was removing in the same
round. Deliberately not scoped to tracked hooks (a `.git/hooks` install has no index
mode, and scoping to the index would rebuild the hole one level lower). Two PRE-EXISTING
fixtures needed an explicit on-disk chmod, and that is load-bearing: CI is
ubuntu-latest and `_tracked_hook_repo` set only the index mode, so its `executable=True`
repos were 644 on disk and would have gone red on Linux for a fixture reason.
59 -> 67 tests, RED first at 7 failed.

**Item 5 - 155 dispositions: 75 CAPABILITY-OK, 27 GITIGNORED-DATA-OK, 51 DEFECT-FIXED,
2 FUTURE, 0 unaudited.** NOTE for the next reader: the `2026-07-27b` entry below records
item 5 as done via `-> RM-119`. That pass audited CI COVERAGE and filed RM-119; it did
not convert any misaligned skip, and all 51 defects were still on disk at `e3f765e1`.
This cycle did the conversion. RM-119 stays OPEN - it is an operator-gated billing call
about widening push CI, not part of this scope. The rule was mechanical so it is
auditable: does the condition gate on something TRACKED IN GIT? If yes, the condition can
only be true when the thing under test is broken, so it must fail. **The headline is that
the DS suite's only skip had never asserted anything** - `test_ehp_shield_phase15.py` was
hardcoded to Aatrox, whose `aramDamageTaken` is exactly 1.0 in the shipped snapshot, so
it skipped every run since it landed. DS is now 10053 passed / **0 skipped**.

**CI safety was proven by clone, not argued** - the real risk of turning 51 skips into
failures. Three `git clone` clean checkouts (`core.longpaths=true`, else 16
`docs/_archive` files silently fail to materialize) with `install_hooks.py` run in each:
parent 13463 passed / 7 failed / 152 skipped vs slice 13464 / 7 / 152, IDENTICAL failure
SETS, net delta 0. The one first-run delta was chased down and is the known xdist
asyncio-loop flake, absent from a pristine re-run and a shifted `-n 6` control.

CARRY-FORWARD, stated rather than buried: `test_build_order_boots` now hard-asserts the
OLD `16.12.1/items.json`, so a future patch-dir prune turns CI red on an unrelated
cleanup; and several conversions now couple CI to `current.txt` / `latest_pulled`
pointing at a COMMITTED bundle, which is the intended drift guard but makes a patch bump
red until the bundle lands in the same commit. Pre-existing and untouched: the suite
writes `data/fusion_shadow.jsonl` into the checkout, so
`test_real_fusion_shadow_corpus_invariants` is order-dependent.

Fresh post-merge: RC `tests/` 13525 passed / 106 skipped / 460 subtests (13516 + 8 + 1,
exact); DS 10053 / 0 skipped / 5585 subtests; ruff clean; Share `--check` in sync at 511
files; 0 non-ASCII. Tier-1: no ENGINE bump, no DS bounce, no RC restart.

---

## 2026-07-27 - R199 loop console-flash back-port + the lane-count value contract (ENGINE-IMPACT NONE, `756db42a`)

**The directive was stale and measuring that first was the whole first half.** It asked
to commit staged `.githooks` mode flips and apply `moon_sync_inbox/winmutex.py.from-lw`
with the item-5a SHA pin. `git status` was clean, `ops/loop/winmutex.py` already hashed
`f1b4b011...` identical to both the inbox file and the Sibling-A tree, and
`tests/test_loop_concurrency.py` already carried the UNSERIALIZED-count 3, both POSIX
monkeypatch tests and `SHARED_SHA256`. It all landed in `e0f4d546`/`fbf744f5`/`2c2877a1`
and RC had already sent LW a queue-CLOSED ack at 02:10. Nothing was re-applied.

**The one live sub-task was the defect-class enumeration, and it paid for the cycle.**
Across all 86 same-path file pairs in the two repos the digest pin is SATURATED - the
only other identical pairs are a 23-byte empty `.mcp.json` and a gitignored gemini stderr
capture, neither a contract. But two defects a digest pin structurally cannot cover fell
out of it.

**RC had been flashing a console window on every single loop cycle.** LW's
`done_sentinel.py` and `claude_stub.py` both carry `creationflags=CREATE_NO_WINDOW` on
their `git rev-parse`; RC's did not, and `done_sentinel` is the FINAL action of every
cycle. Sibling sweep: exactly 2 of the 8 spawn sites in `ops/loop/` were affected.

**The guard for that exact bug existed and was green over it, for two independent
reasons.** `SCHEDULED_SPAWNERS` is a hand-written universe enumerated from the consumer
side and held zero `ops/loop/*` entries - the loop was invisible to it. And its constant
test asserted only that the substring `0x08000000` appeared ANYWHERE in the file, which
passes for a module that never passes the flag to anything, and which the
`getattr(subprocess, "CREATE_NO_WINDOW", 0)` form every loop module uses does not contain
at all. Replaced with an AST resolver following `creationflags` through variable
bindings, `IfExp` guards and `BitOr`, checking the getattr attribute name exactly -
because `CREATE_NO_WINDW` returns 0, spawns fine and still flashes. Teeth proven by
mutation (3 good forms True; typo / zero / wrong-value all False).

**One shared surface is a VALUE, not a file.** `max_concurrent_lanes` is the whole-box
concurrent ceiling across both repos against one shared slot root, but each repo reads
its own config, so a disagreement silently raises the ceiling to the larger value. RC's
own config note calls that "theater" and nothing asserted it. Pinned internally (CI
actually runs that half) plus cross-repo. Green on arrival at 2=2 by design.

**A 3-failure `snapshot_panels` run was chased, not waved through:** serial 33 passed,
directory-alone `-n 8` 413 passed, and the STASHED baseline gave 64 failed on entirely
different tests. Parallel resource contention, and the diff touches no render path.

CARRY-FORWARD: LW ack written to `moon_sync_inbox/2026-07-27-0300-from-RC-stale-directive-two-finds.md`
flagging that LW should grep its own console-flash guard for both shapes (hand-listed
universe, substring standing in for a value check), and that the lane count must move on
both sides in the same round. No re-pin owed; neither shared file was touched.

RC `tests/` 13516 passed / 106 skipped / 460 subtests (13504 baseline + exactly 12 new);
DS 10052 / 1 skipped / 5585, untouched; ruff clean; 0 non-ASCII. Tier-1: no ENGINE bump,
no DS bounce, no RC restart, no Share sync.

---

## 2026-07-27 - R198 Arena coach overlay UI audit (ENGINE-IMPACT NONE, `964f3be1`)

**The UI audit found a backend bug, and it was the most valuable thing in the run.**
`core/lead_projection.py` had no ARENA weight profile, so Arena silently inherited SR -
whose heaviest axis is `cs: 0.40`. Arena has no lane CS, so `cs_sig` sat at a permanent
`-1.0` and every Arena composite carried a fixed `-0.40` drag. A level-16 12/1/10 player
was told "Behind: scale, only fight with your team", at the top-centre eye-line anchor,
in a mode with no team. Fixed by deriving an ARENA row from ARAM (already `cs: 0.0`) and
adding `_ARENA_LINES` so no SR line naming CS / waves / towers reaches an Arena tick.

**A code comment claimed a check that had never been run.** The overlay WIDGETS registry
said every default position was "deliberately checked against EVERY other default". It
had only ever checked the others against `w-arambalance`. The guard found EIGHT
overlapping pairs plus one widget 58px off the right edge of the viewport. Six defaults
moved. `_clampXY` could never have caught the off-screen one - it only keeps the
top-left CORNER on-screen, so a wide widget anchored near the right edge is invisible to
it. Worth an operator glance: `w-stats` and `w-nextbuy` left the bottom-left quadrant
because `w-build`'s 412x594 box owns it and cannot share.

**Two guard weaknesses are filed, not fixed** (BACKLOG, from the verifier): the collision
guard's HEIGHT budgets are 7 measured / 6 estimated, and `w-enemyspells: 210` is an
unmeasured estimate carrying only 20px of the clearance that keeps the guard green. And
the hit-target guard honors a `HIT-MIN-EXCEPTION` inline comment, unused today but a
one-line silencer. Both are ways a green guard stays green over a real regression.

**Honest scope.** The headless Arena capture showed the four visible overlay defects are
IDENTICAL in the SR capture - shell-wide, not Arena regressions. No Arena-specific widget
renders on the overlay at all; none of the CHERRY round/placement data reaches it. The
9px build pips and the 13/12px sub-floor tokens are enumerated and logged FUTURE rather
than bumped, because raising a 9px pip on a 44px icon is a layout change, not a token fix.

DS 10052 / 1 skipped / 5585 subtests; RC `tests/` 13504 / 106 skipped / 460 subtests;
ruff clean. CSS auto-reloads via ADR-008 - no RC restart, no DS bounce, no Share sync.

---

## 2026-07-27 - R197 enchanter Heal/Shield Power sweep (ENGINE 1.261.0, `946da292`)

**What the directive asked vs what was true.** It asked for a DS sweep of enchanter HSP +
mana-regen magnitudes with an Arena/ARAM mirror audit. All 34 curated rows already matched
DDragon 16.14.1 exactly - zero drift. That is the THIRD consecutive cycle where the stated
scope was already closed, so measuring it first and re-aiming is now the reliable opening
move, not a one-off.

**Shipped (4 slices, Claude sole merger, 4 verifier gates).**
- Derived magnitude drift guard - expectations parsed from `items.json` at test time.
- `_scaling_hsp.py` DEFAULT-OFF lane: Dawncore First Light off base mana regen, floor steps.
- Route + client reachability for `assume_hsp_amp`, which was STRANDED (0 hits in server.py).
- Seam-reachability guard deriving its universe from the ENGINE via `inspect.signature`.

**The find worth remembering.** The headline was NOT in the directive - it came from a recon
grep. `assume_hsp_amp` had 0 occurrences in `server.py` while its sibling had 4. Enumerating
the class gave 195 seam-parameter occurrences / 74 names, 23 route-facing stranded. The
existing reachability guards were GREEN and structurally could not see it, because they
enumerate the keys server.py already parses - circular by construction.

**What the verifier gates caught that green suites did not.**
- A mis-transcribed EHP pair in commit prose (6966.71 -> 7440.21, not 7120.49 -> 7607.77).
  The test asserts direction, not an exact value, so no suite could have caught it.
- A FALSE CLAIM SHIPPED IN A DOCSTRING - `sustain_for` named `matchup` as a zero-caller
  function; it has two live callers. Struck at merge.
- Two overstatements about how "derived" the scaling coefficients are (they are literals
  pinned by a derived test - a real but different guarantee), and "Meraki has no mirror ids"
  (it has 6). I would have filed the absolute version as a durable fact and been wrong.

**Three slices refuted my own spec, each correctly:** the four-route wiring was impossible,
my cited test node IDs were not class-qualified, and "zero callers" is not this module's bar
for declining a wire. Writing "a REFUTE is an allowed deliverable" into every slice prompt is
what made that happen - keep doing it.

**Honest scope.** The seam is EXPRESSIBLE, not live. Zero non-test callers; the ranker lanes
still cannot express it. Do not let this read as a live-path win in a later summary.

**Trap re-confirmed:** BOTH build-order keyspaces need regen. `core.build_order_variants` is
a SEPARATE entry point from `core.build_order_precompute`; running only the latter leaves 6
stamp guards red.

DS 10052 / 1 skipped / 5585 subtests. RC 13485 / 106 skipped / 460 subtests.

---




## 2026-07-27g - R210 gemini-loop cycle 15. The premise was false; the guard was the work. 2 commits.

HEAD `594e458c`. CI 3/3 green (`ci`, `docs-guards`, `CodSpeed`). RC `tests/` 13706 passed
/ 106 skipped / 460 subtests, +22 exact over the 13684 baseline. DS untouched, no ENGINE
bump, Tier-1 throughout.

The directive ordered a fix-first REGRESS on `.github/workflows/docs-guards.yml:62,69`,
claiming the `uses:` refs had been corrupted into
`[at]agents\daemon_slayer\tests\test_magic_burst_valuation_dsv6.py`. It had not happened. All
10 `uses:` clauses across the 3 workflows are real tags, and `docs-guards` run
`30289333992` had completed SUCCESS at the very HEAD the directive was grounded against.
The claim was tagged `[from-digest]`, and `executor.py:537` skipped every tag that was not
`[UNVERIFIED]` - so R208's grounding guard, built for exactly this failure mode, watched
the one tag and not the other. Re-cut the slice to that: `digest-premise`, a fourth finding
kind that names the resolved path a from-digest claim cites and tells the session to
re-read it, without ever asserting the claim is false. Two tests pin that restraint.

Worth knowing next time: the premise field carried only the BASENAME `docs-guards.yml`, so
naive path-existence resolution would have found nothing and the guard would have shipped
green over its own incident. `_repo_path` falls back to a bounded `git ls-files` against
the index. That detail is the difference between a guard and a decoration.

The `docs-guards` workflow R209 shipped has now executed on GitHub for the first time and
passed in 1m33s, which retires R209's stated LIMIT (trigger semantics unproven).

CARRY-FORWARD, now six cycles old and still nobody's done it: controller pid 18300 started
00:37:50, before its own self-reload fix `d4b1a762` landed. It cannot load that fix. It
MUST BE BOUNCED BY HAND ONCE. Every stale-premise cycle since traces back here.


# 2026-07-27b - F1 queue drain, paired with Sibling-A. RC-owned items all closed.

Ran alongside the LW session on the shared 11-item f1-phase6 queue, coordinating
through the per-repo `moon_sync_inbox/` dirs. Operator was asleep for the whole
run; nothing was gated on them.

RC-OWNED, ALL DONE: 1 (exec bit), 2 (gate reads the index mode), 4 (anchor-site
rule), 5 (skip audit -> RM-119), 6 (CI arms the gate + e2e), 7 (disjointness),
9 + 5a (shared-file apply and pins), 10 (defect-class rule), 11 (invariance as a
test). LW owned and closed 3 and 12.

## The four things the queue did not know about

**The hooks were inert on Linux AND one was missing entirely.** Item 1 was the
exec bit. Fixing it armed the gate in CI for the first time, and the very first
armed run went red on something else: git-lfs installs FOUR hooks and only three
had ever been ported to `.githooks/`, so `git lfs post-merge` had never run on
any clone - a `git pull` left LFS pointers unsmudged. It was invisible locally
because Legion's clone never ran `git lfs install` and therefore had no file to
orphan; the runner does. THE LOCAL PASS WAS THE MISLEADING ONE.

**The "xdist shared-state failures" were never shared state.** WAKEUP has waved
these off run after run on a diagnosis nobody ever tested. Real cause: pytest 9
puts raw `subTest` kwargs in the report and emits one per subtest, execnet
serializes only builtins, so a bare `object()` raises DumpError inside
`subTest.__exit__` and fails the PARENT test. Serially there is no channel, so
the same matrix passes. Fixed by labelling with `repr()` - the hostile inputs
are byte-identical, because the garbage IS the test. A fifth instance in the DS
suite was found by ENUMERATING the class, which is the rule this same session
codified as item 10.

**The DS "flaky live tests" were a 5-deep listen queue.** One defect, not eleven.
`agents/daemon_slayer/server.py` never raised `request_queue_size`, so past 5
pending connects the OS REFUSES - unfixable by any client timeout. And
`core/daemon_slayer_client.py` maps every transport failure to `None`, which
callers read as an engine verdict, so a dropped socket surfaced as "this control
champion moved" and "expected 6 slots, got []". Backlog 128. DS suite `-n 8`
went 11 failed -> **9963 passed / 1 skipped / 0 failed in 44s**; live re-measure
500 POSTs at 16-way, zero failures. ENGINE-IMPACT NONE.

**A fourth instance of the same shape, found by CI on my own new guard.** The
strict table reader I added to close the corrupt-vs-absent conflation went red in
CI: `actions/checkout` does not fetch LFS objects and the laning_scenarios
tables are ~64MB LFS blobs, so on a runner the path EXISTS and holds a pointer
stub, which is legitimately not JSON. An unfetched pointer is a CAPABILITY gap,
not a corrupt table - it now skips, while a materialized-but-malformed file still
fails hard. The skip holds even when the require-flag is armed, because that flag
asserts the tables were GENERATED and LFS FETCH is a different question with a
different owner and ~190MB of cost. Clean on Legion (LFS smudges locally), broken
on the machine that never fetched - the same asymmetry as the post-merge hook.

**The ENGINE-IMPACT anchor count is SEVEN, not five.** The queue note omitted the
`ENGINE_VERSION` literal itself and `CLAUDE.md`; two memory files said four. The
derived list with file:line evidence now lives in `ops/loop/director_prompt.md`,
which is the template the controller reads EVERY cycle - deliberately not in
`directive_suffix`, which is transient run context and would take the rule with
it on the next rewrite.

## Cross-repo

Both sessions independently invented a NEW sync channel before finding the
existing `moon_sync_inbox/` one, and LW sat blocked on a reply RC was writing to
the wrong place. Now pinned in CLAUDE.md so the next session does not invent a
third. `slots.py` + `winmutex.py` are byte-identical again and `SHARED_SHA256`
is non-provisional on both sides. **Re-pinning is a JOINT act - both trees
hashing equal IS the acceptance, not a note claiming it.** LW's first status note
reported a divergence read from a stale snapshot and had to be withdrawn, while
the guard itself had already caught the real one.

`8986418f` in RC's history is LW's, not a mystery: they were authorized to
restart RC's stopped loop, committed two setup files with a pathspec, then saw
RC's file mtimes and STOOD DOWN rather than run a second driver.

## Also closed

Both drift_guard breaches that were open at the last wrap. The version-anchor
check now has line-level context (a line is history if it carries a
`N.N.N -> N.N.N` transition or a closure marker) - all three 1.259.0 sites it
had been reporting were correct history. The CHECK was fixed, not loosened: a
live claim next to real history in the same file still breaches, pinned by test.
ROADMAP relocation took it 94 percent -> 79 percent of budget.

## Open / owed

- **RM-119 needs an OPERATOR DECISION.** Push CI collects 85 of 807 RC test
  files and ZERO of 397 DS files; everything else is nightly-only and gates
  nothing. Not actioned unilaterally because it spends CI minutes. The cheapest
  option is now concretely cheap: the DS suite is parallel-safe at 44s.
- Skip audit buckets B2 / B4 / B5 filed in RM-119, not fixed.
- `docs/LIVE_GAME_GATED_SYNC.md` carries six `SOURCE: ROADMAP.md:<line>` tags;
  all six were ALREADY stale before this session's relocation. Line numbers into
  a file that gets relocated every few sessions is a provenance scheme that
  cannot hold - it wants a stable anchor, not a repair.

---

# 2026-07-26b - F1 cross-repo concurrency + the headless executor seam. 8 commits.

Paired session with Sibling-A. RC could not run headless at all before this: the
executor was inlined in the controller and hard-wired to the AHK GUI bridge, a
machine-wide singleton keyed on a window title. Full narrative in `docs/LEDGER.md` 1069.

SHIPPED
- `ops/loop/slots.py` + `ops/loop/winmutex.py` - BYTE-IDENTICAL-BY-CONTRACT with
  Sibling-A (`95077a62...` / `c21bfe4f...`). NEVER edit one repo's copy alone; both
  loops coordinate through `C:/ProgramData/lw-loop/slots` + the OS mutex namespace.
- `ops/loop/executor.py` - the channel seam. `channel` config key, sdk is now the DEFAULT.
- `claude_gui_bridge.ahk` double-Enter - a single `{Enter}` was being swallowed, leaving
  the directive typed-but-unsent until the deadline with no error.
- `{{FINAL_STEP}}` substitution - the two channels need OPPOSITE completion steps.
- Dollar cap REMOVED everywhere (Max 20x is a subscription; TIME is the only real budget).
- P5 concurrent run PASSED 4/4; phase-6 gate run PASSED 7/7.

DO NOT REDO
- Do NOT delete `done_sentinel.py`, `meter()`, `claude_gui_bridge.ahk` or the ahk path.
  Operator HELD the phase-6 deletions. Rollback is the one `channel` key.
- Do NOT re-derive the shared-file hashes from whatever is on disk later - they were
  pinned while both trees were provably in sync.

NEXT - an 11-item queue, agreed with LW, UNSTARTED:
1 `git update-index --chmod=+x .githooks/*` (all five are 100644, so hooks are INERT on
  any Linux clone) - 2 `gate_inactive_reason` checks the exec bit, not just presence -
3 log the sdk `session_id` on EVERY executor log path incl. success - 4 `ENGINE-IMPACT:
BUMP` must require a numbered step naming every anchor site (there are FIVE: the gate run
found `agents/daemon_slayer/CHANGELOG.md` is a different file from `Share/CHANGELOG.md`) -
5 `skipif` audit for preconditions that should be FAILURES - 5a pin the shared-file
sha256s as constants so CI enforces parity without the sibling tree - 6 CI arms the hook
gate then asserts it end-to-end, replacing the `skipUnless` that blinded RC - 7 directives
naming N parallel agents must assert disjoint files; the executor serializes AND RECORDS
the deviation - 9 `winmutex` POSIX branch emits `UNSERIALIZED` (today it is unserialized
AND untraced, so every guard passes vacuously off Windows) - joint edit, needs LW - 10
enumerate the defect class WITHIN the file before committing the fix - 11 score-invariance
claims ship as a test (the 171-champion claim was measured but left no durable artifact).

ALSO OPEN (drift_guard, 2 breaches, both pre-existing at wrap)
- `ROADMAP.md` at 94 percent of its 81920-byte budget - needs a relocation pass to
  `docs/ROADMAP_HISTORY.md`. Deliberately NOT grown this session because of it.
- version-anchor FALSE POSITIVE: the check excludes historical FILES by name but not
  historical LINES. `ROADMAP.md:98`, `docs/ORCHESTRATION_PLAN.md:649` and
  `Share/README.md:340,353` all name 1.259.0 as HISTORY, correctly. Fix the CHECK
  (line-level context) + add a `tests/test_drift_guard.py` case - do NOT loosen it.

---

# 2026-07-27a - R196 anti-tank kit-penetration tails. ENGINE 1.260.0. 3 commits.

**Loop cycle 6 (gemini director).** Closed the three R190 tails filed in `BACKLOG.md`:
Annie R uncredited, no AXIS field on `_ANTITANK_REGISTRY`, Amumu P mis-registered.

**The first decision was refusing the directive's shape.** It asked for 3 parallel
disjoint worktree slices; all three tails land in the same two files and slice 2's
AXIS field is a schema lift the other two consume, so they would have collided the
way R194's `_R194_TAIL` did. Auto-picked ONE worktree agent running 2 -> 1 -> 3 in
dependency order, still verifier-gated, Claude sole merger.

- **AXIS** - `AntiTankEntry.axis` (PHYSICAL / MAGICAL / BOTH, default BOTH) appended
  LAST with a default, stamped on all **31** resist-lowering rows across **30**
  champions (Mordekaiser carries two - the slice agent's commit prose said 30 rows and
  the verifier caught it). `_NON_GRANT_WITH_PHYSICAL_SIDE_ROW` + its companion test
  DELETED; the magic-side guard now reads `row.axis` instead of a hand-written K'Sante
  exemption. Metadata only, moves no score - measured twice independently (1368-dict
  digest before/after, plus the verifier's own 3-way mutation probe).
- **Annie credited** PERCENT_PEN / SUSTAINED / 0.7 / MAGICAL. **My `cond=True` premise
  was REFUTED and the refutation was right** - 16.14.1 prose is "Passive: Annie gains
  magic penetration." with no gate; "while Tibbers is alive" gates the RECAST.
- **Amumu removed** - the SHRED 0.6 row is wrong at 16.14.1 (10 pct bonus TRUE damage
  vulnerability, lowers no resist). He leaves the selective axis at 0.0, pinned by a
  tooltip-wording regression test.
- Registry totals UNCHANGED (103 mechanisms / 79 champions / 30 shreds_resist) because
  the add and the removal cancel; only `pen_count` 6 -> 7.

**TRAP WORTH REMEMBERING: there are TWO changelogs.** The DS guard reads
`agents/daemon_slayer/CHANGELOG.md` (paragraph entries keyed `1.260.0 (`), which is a
DIFFERENT file from `Share/CHANGELOG.md` release notes (`## old -> new` headers). I
edited the Share one first and the suite stayed red on exactly that test. Both need an
entry on every bump.

**Second trap:** the serial `tests/` run was at 6 percent after 10 minutes. `-n 8` did
it in 127s with 4 known xdist shared-state failures (`test_aram_action_rule.py`,
`test_aram_fight_risk.py`) that pass serially - re-ran them to confirm rather than
waving them off.

ENGINE 1.259.0 -> 1.260.0 in ritual order (126 .py bumped, DS bounce, `/health`
confirmed BEFORE regen, 9 tables, Share sync, docs, dual suite LAST). Regen was NOT
stamp-only: variants tables carry Amumu 0.51 -> 0.0.

DS **9949** / 1 skipped / 5311 subtests. RC `tests/` **13411** / 106 skipped / 442
subtests (-n 8). ruff clean, 0 non-ASCII, Share `--check` 505 files.
Still open: BACKLOG tails (d) max-rank-only magnitudes, (e) base/bonus armour split.
