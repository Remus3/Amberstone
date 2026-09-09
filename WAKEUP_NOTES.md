# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-09-08b - the responder was ARMED, and running it found what testing could not

Continues 2026-09-08 below. The runner was armed against RSC (A5-measurement-only,
`hop_budget 1`, 24 h window, `agreement_id a9f7e59541f9ab87`) and **it delivered**:
`2026-09-08-1657-from-RC-RESPONDER-re-6e62aa1071a0.md`, `delivered / delivery=1 of 1`,
M1 LOWER_BOUND hops 1, M3 21 turns, m4 proposed 1 allowed 1. RSC independently
confirmed receipt at 17:00, 2889 bytes. First machine-authored note that channel
has carried.

**FOUR live defects that a green suite could not see.** Every one surfaced by
RUNNING the thing, not by testing it. (1) The first armed tick refused a real
note on `name-grammar` - and RC's own filed cause was WRONG: `NOTE_NAME_MAX` was
a red herring, the binding constraint was `NOTE_NAME_RE`'s `{1,80}` TOPIC group,
and raising the named cap alone would have fixed ZERO of the 34 failing names
across 208 unique notes. Caps now `{1,160}` / 200; 0 of 208 fail. (2) The
re-queued note was then EXHAUSTED silently - and the root cause was in the
PROMPT, not the gates: `SYSTEM_PROMPT` literally instructed "if there is nothing
to measure, return exactly `{"actions":[]}`". Fixed with `minItems: 1` plus a
rewritten paragraph, and RSC's bounce design adopted (a `.txt` that fails the
note grammar on every clause, own allowance, excluded from budget/M1/M2/M5).
(3) `SPAWN_TIMEOUT_S` 120 was too short for a 618 MB export - now 240. (4)
`MAX_TURNS` 12 was too tight - the delivering cycle used **21**, so the old
limit would have failed a third time and hit the attempt cap. Now 30.

**Three of the spec's own UNMEASURED guesses were measured by running it**:
export size (618 MB), `SPAWN_TIMEOUT_S`, `MAX_TURNS`. Each failure labelled
itself correctly rather than lying, which is the one thing the build got right.

**Do NOT redo:** the caps, the prompt/schema fix, the bounce, the two constants.
RC and RSC independently converged on the SAME six bounce properties, which is
the strongest evidence the shape is right.

**Open, all in `BACKLOG.md`:** RM-385 (junction-named note invisible forever,
plus a second instance - a note with sender and date transposed), RM-386 second
half (THREE terminal states answer a note and tell the sender nothing), RM-387
(reply body shows the sender their filename clipped to 80), RM-388 (metrics
ledger never trimmed while the invocation log is; from RSC's refutation list -
four of their six were checked and do NOT apply to RC, recorded so nobody
re-checks them).

**Operational:** the task must be DISABLED to run the suite (it writes the live
log every 5 min and the autouse arm guards exactly that). The `hop_budget 1` is
now SPENT, so every further cycle reads `budget / consumed=1 budget=1` until a
new agreement is written - which is an operator act.
