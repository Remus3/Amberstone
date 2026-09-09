# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-08, RM-387 pass (relocated `2026-09-08b` "the responder was ARMED"; newest 3 = RM-387 `2026-09-08e` + RM-385 `2026-09-08d` + RM-386 second half `2026-09-08c`). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-08g - RM-389: five questions answered, and three outbound notes that each needed correcting

Single-row outward session, operator AWAY. Tier-0 code impact (three doc
commits), plus three cross-repo notes to RSC. Task DISABLED before the first
suite run and re-enabled at wrap. `df07bfe1c`, `0895db035`, `3ae50ddb3`, all
pushed. Responder slice 595 passed / 1 skipped. Full account in LEDGER 1370.

**The row shipped.** All five of RSC's consensus questions are answered:
Q1/Q4 agreed, Q2 `# GATE:<tag>` with the census trap stated in BOTH directions,
Q5 answered as the SHAPE (`GATE_MUTANTS` plus four machine-checked companions,
with the honest caveat that `GATE_STATEMENT_LINES = 4` makes "the gate's own
statement" a 5-LINE WINDOW rather than an AST scope). The correction RC owed
them was delivered: they quoted RC's `start`/`deliver` blind spot as an open
warning and both are CLOSED.

**Q3 was answered by AUDITING, and RC failed its own audit.** 39 of 115
external-binary call sites are FALSE-RED RISK, 4 false-green. MEASURED, not
static-read: with git off PATH, `tests/test_inbox_responder_runner.py` gives
17 passed / 205 errors of 221 collected, `FileNotFoundError [WinError 2]`
raised inside the SESSION fixture. RC has a 2116-line guard against false-GREEN
skips and NOTHING against false-RED, and it is structurally blind to an ungated
`subprocess.run([...], check=True)` because there is no skip to inspect.

**THE PROCESS LESSON, which cost more than the row.** RC wrote note 1 DIRECTLY
into the sibling's inbox and gated it AFTERWARDS. The gate found nine defects,
so RC edited a delivered note - breaking `docs/CONCURRENT_HEADLESS_CONTRACT.md`
rule 7.2 - and RSC had already read v1 and rebroadcast RC's wrong "121 of 139"
to four inboxes. **A verification step placed after the irreversible act turns
its own findings into a contract violation.** Note 2 then shipped three NEW
false sentences. Note 3 was drafted to SCRATCH and took FIVE gate passes before
it was clean; every pass found real defects, and the last two found only prose,
never a figure.

**What separated the good numbers from the bad:** not machine-versus-memory -
the wrong 121 came from a grep. Every figure that survived was RE-DERIVED BY A
SECOND METHOD (125 survived because an AST pass disagreed with the grep).
Every sentence written from recollection between gates was wrong, including
three claims RC made ABOUT ITS OWN prior errors, one of which "quoted" a phrase
that existed only in an undelivered draft.

**A count this repo was wrong about in three directions.** `738ec83af` edited
THREE places in `RESPONDER_RUNNER_SPEC.md` - true as an EDIT count, which is
what its message meant. Exactly ONE carried the false `name == safe_name(name)`
claim; a SECOND site (`:149`) survived. RC called it "the fourth site" in
`df07bfe1c`, then over-corrected to "never true", also false. **The "Corrected
in three places" wording at `WAKEUP_NOTES.md:134` below, `BACKLOG.md:264` and
`docs/LEDGER.md:51` is that same claim-count reading and is superseded by
LEDGER 1370** - three places edited, one carrying the claim, one claim site
missed. `df07bfe1c`'s message stays wrong in the permanent record; no rewrite.

**NEXT:** RM-390 (does the `trial_rows` quotable set span
`responder_metrics.<stamp>.jsonl` archives? Decide and write it into the spec
either way; no production call site yet, so it is a seam to settle before it
has a consumer), then RM-391 if time. Next free id RM-392. **Adopt inbound and
unmeasured:** RSC's finding that a pre-push hook runs with a PATH that is not
the shell's (git puts `mingw64/libexec/git-core` on it), which puts the 39
FALSE-RED classification in doubt in exactly the environment that gates every
push.

---

# 2026-09-08f - RM-388: the ledger rotates, and "which agreement is live" took three answers

Single-row session, straight after RM-387. Tier-1, no `ENGINE_VERSION` bump,
no DS bounce, no Share sync, no frozen file. Task DISABLED before the first
edit, re-enabled at wrap. Commit `470d3158a`, pushed; CI `check: success` and
`docs-guards: success` on that sha (`nightly-full-suite` skipped, as every
push run skips it - the run conclusion alone would not have said so). LEDGER
1369 (which calls this session `2026-09-08e`; the letter series are PER FILE
and have diverged - see the header note).

**The fix.** `responder_metrics.jsonl` grew forever while its sibling
invocation log was trimmed. A `_trim` here was the wrong answer and the filed
row said so: that file is where M1-M5 live and `trial_rows` quotes it into an
arming note. Rows now MOVE to `responder_metrics.<stamp>.jsonl` and none is
discarded; the trigger is BYTES via one `stat`; the carry is the last 200 rows
plus every row of the live agreement.

**THREE VERIFIER PASSES, THE FIRST TWO REFUTED IT, and both refutations were
the same question with different answers.** "Which agreement is live" is the
whole item. (1) `result.agreement_id` is set at GATE 2, so a stop-flag tick, a
malformed record and a prelude failure all reach `_finish` with None while an
agreement is live - measured `trial_rows` 30 -> 0. (2) A passed-in `root` then
failed through the DRY path, where the cycle runs against a scratch root while
its rows go to the LIVE ledger - measured 30 -> 0 again, and my docstring had
the rationale backwards. (3) Shipped: `_rotate_metrics(path)` reads the
agreement record BESIDE the ledger it is rotating. Nothing is passed in, so
nothing can be passed in wrong. Memory:
`feedback_which_instance_is_live_is_its_own_question`.

**Do NOT** add `_trim` to the ledger, and **do NOT** add a parameter telling
the rotator which agreement is live - that exact parameter was refuted twice.

**Companion audit (RSC refutation 3).** The `mkdir(parents=True)` /
`WinError 183` shape reproduces on RC; nine sites; exactly one had their
partial-write-then-crash half - `main`'s prelude handler. The two writes are
independent now, and when NEITHER lands the OSError still escapes, so exit 2
never claims a failure was recorded when nothing was. The rest write nothing
before they can raise and are RECORDED, not changed.

**Two process notes.** A procedure-A mutant needle broke twice mid-item
because it quotes runner source text at a call site this work moved. And
verifier pass 3 reported `RC-InboxResponder` as "not registered at all" -
FALSE; re-probing found it registered and Disabled. A subagent's claim about
MACHINE state deserves the same distrust as its claim about a test count.

**Suite:** runner + mutants 298 passed / 1 skipped (+11 arms), the eight
sibling responder files 295 passed, ruff clean, 0 non-ASCII in four files.

## NEXT SESSION - HEADLESS, and every sibling has the same directive

Operator, 2026-09-08: all five repos were told to continue the responder work
and propagate it, and RSC immediately asked for consensus BEFORE anyone builds
(`moon_sync_inbox/2026-09-08-2155-from-RSC-consensus-requested-...`, five
questions, one to RC by name, and it states that SILENCE READS AS DISSENT).
**The operator then narrowed it: `CS`, `LW` and `LL` are on STANDBY** ("i will
keep it to the test for now"), so the exchange is **RC <-> RSC ONLY** and
nothing is written into the other three trees. **The operator is AWAY and both
sessions run headless:** a decision that would normally be escalated goes to
an ADJUDICATOR agent - a distinct agent choosing between the stated positions
against stated criteria, never the agent that authored one of them - and the
decision plus its criteria are recorded in the ledger entry. The one act that
does NOT get adjudicated is ARMING: writing an agreement record commits RC to
a counterparty under a budget, and nothing in this queue needs it (RSC has
said it will not build a runner or arm either), so if a row ever seems to
require it, that row is out of scope until the operator returns.

Rows, in order: **RM-389** (answer the consensus note and propagate - ONE note
to RSC, measured claims only, no request for a reply),
**RM-390** (`trial_rows` sees only the live ledger now that rotation exists -
settle whether the quotable set spans archives, and write it into the spec),
**RM-391** (the per-note records, filed WITH their measurement: they grow per
NOTE, not per tick, and `deliveries.jsonl` is the budget governor and must
never be trimmed).

Concurrency, because RSC runs headless on this same box at the same time:
read `docs/CONCURRENT_HEADLESS_CONTRACT.md` first; do NOT re-pin
`SHARED_SHA256` (`tests/test_loop_concurrency.py:474`) unilaterally, since
both trees hashing equal IS the acceptance and a sibling's file is taken with
a BYTE-level copy, never `write_text`; and keep suite parallelism modest,
because parallel full-suite slices have OOM'd this box and it presents as an
API error.

Still open and unchanged: the responder is DISARMED and `hop_budget 1` is
SPENT, so a new agreement is an OPERATOR act and every outbound note is
hand-delivered rather than a trial hop. The one false entry in
`inbox_responder_answered.json` still stands per LEDGER 1366.

---

# 2026-09-08e - RM-387: a row's 80-char bound had reached the human-readable body

Single-row session, straight after RM-385. Tier-1, no `ENGINE_VERSION` bump, no
DS bounce, no Share sync, no frozen file. Task DISABLED before the first edit
and re-enabled at wrap. Commit `738ec83af`, pushed; CI `check: success` and
`docs-guards: success` on that sha (`nightly-full-suite` skipped, as a push run
always does - the run conclusion alone would not have said that).

LETTER SERIES NOTE, so nobody "reconciles" it later: `docs/LEDGER.md` calls this
session **2026-09-08d** (entry 1368) because the two files started lettering on
different sessions. They have already diverged for RM-385, which is `c` in the
LEDGER and `d` here. Neither is wrong; do not renumber either.

**The defect.** `assemble_body(note_filename=result.note)` was handed the ROW's
`safe_name` projection, which clips at 80 to satisfy `ROW_NOTE_RE`, so the
counterparty read their own filename truncated in the one line written for a
human. Pre-existing; the RM-386 topic-cap raise made it routine rather than rare.

**The decision, which is the item's real content.** `ROW_NOTE_RE` was NOT
widened - it is a published row interface RSC may parse and it carries a mutant
needle, and the row-consumer side was measured first (only `metrics_row_ok` plus
four arms read that field). The row wants a bounded, regex-pinned value; the body
wants the name the sender chose. They stopped sharing one projection. The row,
`safe_name`, `NOTE_NAME_RE` and `NOTE_NAME_MAX` are byte-unchanged, and the whole
production diff is one argument plus its comment.

**Why the raw name is safe there:** assembly is reachable ONLY after gate 6,
where the name has passed `NOTE_NAME_RE` - the same ground the stdin envelope has
stood on since the first build. The BOUNCE deliberately keeps the projection on
both halves: it is the one sender-visible body that must also serve a name which
never passed the grammar.

**The spec was carrying a false premise and that is where the defect grew.**
Section 2 asserted a post-gate-6 name "equals its own `safe_name` by
construction". False the day it was written (the grammar already admitted 109
characters), routine after the cap raise, and asserted by no test. Corrected in
three places. New memory:
`feedback_shared_projection_carries_the_tightest_bound`.

**Two arms, both on the SENDER-VISIBLE string** (the clipped name is a PREFIX of
the raw one, so a plain substring check passes on the broken body): the delivered
file must carry `answering <raw>; cycle ` and not the clipped clause; and a name
carrying `hop` past character 80 now refuses a LATENCY-ONLY cycle the clip used
to hide - fail closed, correct (a LATENCY-ONLY body saying `hop` reads as M1),
one grammar wide, delivering normally under A5. The second was found by the
adversarial verifier, not by me; its other residual (a post-gate-6 bounce still
clips) was answered in the comment rather than filed.

**Do NOT redo:** RM-387 in any form, and do not revisit widening `ROW_NOTE_RE` -
that was considered and rejected on the row-consumer measurement, not skipped.

**Still open and unchanged:** RM-388 (metrics ledger never trimmed; do NOT just
add `_trim`, it is the M1/M2/M3 evidence base) which also carries the unaudited
`mkdir(parents=True)` / `WinError 183` shape across 8 runner call sites. The two
RSC notes (1640, 1705) are still pending and unanswered - `hop_budget 1` is SPENT
so every cycle reads `budget`, and a new agreement is an OPERATOR act. The one
false entry in `inbox_responder_answered.json` still stands per LEDGER 1366.

---

# 2026-09-08d - RM-385: what is NOT a note still has to be SEEN

Single-row session, straight after RM-386 and dependent on it. Tier-1, no
`ENGINE_VERSION` bump, no frozen file. Task DISABLED before the first edit,
re-enabled at wrap.

**Two silent filters, one class.** `pending_notes` dropped an entry on
`Path.is_file()` (false for a junction - always a directory reparse point) and
on `_sender_code(...) is None` (true for a name that BEGINS `from-`, sender and
date transposed). Neither produced a refusal, a hold, a row field or a log
line: the cycle said `empty / none_pending`, which is the responder reporting
nothing pending while something is. Admission is now by NAME and by the
answered record, so both reach gate 6 and are refused.

**The fence expired.** Spec section 15 put `inbox_responder.py` out of scope
for the RM-384 build, which is why this shipped as a strict-xfail instead of a
fix. `test_a_note_that_is_a_junction_is_refused` is now a PASSING arm - the
stated acceptance and the last strict-xfail in the responder suite. Its
companion containment arm was re-pointed at the refusal path, not deleted.

**RM-386 supplied the disposal.** The row asked for "refused, answered so it
stops re-cycling" - and answering is exactly what RM-386 had just stopped
doing. The refusal is HELD instead. In the other order this would have shipped
a permanent answer for a note nobody read.

**The line NOT crossed:** a note from a sender outside the agreement is still
dropped silently - somebody else's correspondence, not a silent failure - and
an arm pins that. Admitting is not trusting: `NOTE_NAME_RE` is strictly
stronger than `_sender_code`, so a code-less name is refused `name-grammar`
before any spawn.

**New label with its own mutant:** a plain directory named like a note reads
`note-shape:not-a-file`, ordered after the reparse branches so a junction keeps
`note-shape:linked`. Without it the entry is still refused, but as `linked`,
and a directory is linked to nothing.

**Live impact ZERO, and my first probe of it was wrong.** The transposed-name
file is inside the answered record, so the pending set is the same two RSC
notes before and after. Both arm comments were corrected to say so. (The
verifier's one soft spot: that 106 of the record's 108 entries are the
operator seed is INHERITED from LEDGER 1366, not re-derived - the file is a
flat sorted list with no seed marker. The load-bearing half, that the file is
in the record at all, is measured here.)

**Suite:** 581 passed / 1 skipped / 0 xfailed / 0 failed (`pytest tests -k
inbox_responder`). Ruff clean.

**THEN CI FOUND A REAL BUG NO WINDOWS GATE COULD SEE - keep this one.** The
push run went red, 2 failed / 32296 passed, both mine: `note-shape:linked !=
note-shape:not-a-file`. **A directory's `st_nlink` is 2 on POSIX and 1 on
Windows.** The new branch sat one line BELOW the `st_nlink != 1` check, so on
Linux every directory was claimed `linked` first, while on Windows it fell
through and read correctly. Local suite, local slice AND the verifier's direct
`note_shape_ok` calls were all green - every one ran on this machine. Fixed in
`dd156b690`; order is now symlink, reparse, not-a-regular-file, then nlink.
**Also:** the first RM-385 CI run read `cancelled` (two later docs pushes
superseded it), and `gh run watch --exit-status` exits 0 on cancelled - read
`conclusion`, never the exit code.

**Still open:** RM-387, RM-388.

---

# 2026-09-08c - RM-386 second half: a refusal is no longer an answer, and the row asking for it was two-thirds stale

Single-row session. Tier-1, no `ENGINE_VERSION` bump, no DS bounce, no frozen
file. `RC-InboxResponder` was DISABLED for the run and re-enabled at wrap.

**Read the code before the row.** RM-386's body named three terminal states
that "answer a note and tell the sender NOTHING". Two were already closed when
the session opened - the bounce shipped the same afternoon fires on exactly
{exhausted, refused} and had arms proving it, and the `minItems: 1` fix made an
empty proposal illegal. The third was always the RM-385 class. What was open
was the clause the row filed as an OPTION: refusals were written to the
answered record, which made them PERMANENT, which is why RC deleted an entry by
hand to re-cycle RSC's 1456 note. A session that trusted the row's summary
would have rebuilt the bounce.

**Shipped.** `record_responded` went from FIVE call sites to ONE (inside
`_deliver`), so the record means only what it says. Refusals and exhaustion now
write a HOLD record, `ops/runtime/inbox_responder_held_notes.json`, keyed by
`note_sha12` of the RAW name: the note stays pending and unanswered,
`pick_note` skips it as it skips one at the spawn cap, every row carries
`notes_held`, and gate 4b says `runner-failed / notes-held` rather than
`empty` - `attempt-cap` still wins when a note is also at the spawn cap, and
the guarantee is that neither is ever `empty`. One deleted entry re-cycles the
note.

**Both costs RSC disclosed are paid, not argued away:** the repeat-refusal
storm (288 held dirs a day) is suppressed by the hold, and head-of-line
starvation - which RC had been buying off by answering refusals without knowing
it, RSC refutation 6 - is prevented by a younger note being picked ahead of the
held one, with an arm driving exactly that. Both record faults fail CLOSED:
unreadable terminates `held-record-unreadable` before anything is spent,
unwritable clears `bounce_target` so nothing goes into the sibling's tree.

**Traps worth keeping.** A fixture that makes the record a DIRECTORY does not
test the unwritable path - the unreadable gate catches it first; the arm needs
the `.json.tmp` name occupied instead. And `metrics_row_ok` bans the substring
`refus` on a non-refused row, so the vocabulary had to be `notes-held`, not
anything spelled with "refusal".

**Live data measured, and one entry deliberately LEFT.** The answered record
holds 108 entries: 106 are the deliberate seed, one is the correctly answered
1530 note, and one - the 1456 note, `e83297be2bf9` - is the single false entry
the old code wrote (only ever refused then exhausted, never replied to).
Deleting it is an OPERATOR call, not a neutral repair: it is older than the two
unanswered notes now in the inbox, so it would sort to the head and spend the
first hop of the next agreement. Command is in `docs/LEDGER.md` 1366.

**Do NOT redo:** the hold record and its two fail-closed directions, the
`notes-held` / `held-record-unreadable` vocabulary, the three repaired mutants
plus the one added, the amended spec sections 2 and 4b.

**Still open:** RM-385 (strict-xfail untouched), RM-387, RM-388. A
`destination`-stage refusal is still answered on purpose - `_deliver` records
before the link attempt and a mutant pins that order.
