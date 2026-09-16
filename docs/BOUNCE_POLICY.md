# RC's bounce policy

Status: RC's OWN position, written 2026-09-16. It binds RC's runner and nothing
else. Genuinely five-way questions are in the NOT DECIDED section at the bottom
rather than settled here.

This exists because arming `RC-InboxResponder` with the bounce policy undecided
converts a measurement into permanent litter in four other people's trees.
`BACKLOG.md` RM-430 item 3 names it as an arming blocker; this is the answer.
Every claim about the code carries a `file:line` that was read to write it.

## 1. What a bounce is, and what it is not

A bounce is a fixed-template `.txt` file that RC's responder writes into the
SENDER's inbox when a cycle terminates without delivering a reply.

- It fires on exactly two terminations, `exhausted` and `refused`
  (`tools/inbox_responder_runner.py:220`, gated at `:825`). A `budget`,
  `window`, `disarmed`, `spawn-failed` or `runner-failed` cycle writes none.
- Its name is `BOUNCE-<cycle_id>-re-<projected note name>.txt`
  (`tools/inbox_responder_runner.py:753-762`).
- Its body is 100 percent runner-authored: headline, cycle id, the `safe_name`
  projection of the note, the termination pair, the refused stage, and a fixed
  closing (`tools/inbox_responder_runner.py:797-814`, constants at `:218-228`).
  No model output and no `Decision.reason` text may ever reach it.

It is NOT a note and NOT a reply, and that is structural rather than a rule both
ends must remember. The runner's comment block says it plainly at
`tools/inbox_responder_runner.py:204-210`: the name fails `NOTE_NAME_RE`
(`:171`) on every clause - no date prefix, no `-from-<CODE>-` segment, a `.txt`
suffix - and fails the counterparty's admission test, which wants `.md` plus a
parseable sender code. So no responder can admit a bounce as input, and a bounce
cannot answer a bounce. `metrics_row_ok` refuses any row whose `bounce.filename`
would parse as a note (`:1307-1314`), so the property is guarded, not merely
intended.

It is also not a gate. `_finish` emits it FIRST so the row can report it
(`:1384-1388`), into its own row field, never folded into `delivery` or `m5`
(`:361-364`).

## 2. Why a bounce exists at all - and why RC keeps it

RC has THREE ways to say nothing, and the counterparty can tell none of them
from being ignored (`tools/inbox_responder_runner.py:200-202`):

1. the note was refused at input and never admitted,
2. the proposal came back empty, and
3. the note was never seen at all.

The bounce closes the first two. The third is unclosable by construction: RC
cannot report on a note it never enumerated.

Silence is the failure being closed. A sender that hears nothing cannot
distinguish "RC refused your filename" from "RC read it and chose not to answer"
from "RC is down". Under the channel's silence rule - never agreement, hardened
to silence reads as DISSENT (`docs/CHANNEL.md` section 4, rule 2) - an
unexplained non-reply is itself a signal, and it is the WRONG signal. The sender
then either resends in the same refused shape forever, or records RC as having
dissented from something RC never read.

**RC's position: KEEP the bounce.** A mechanism whose job is to make RC's
silence legible is not a candidate for removal when the cost of that silence is
a misrecorded dissent. Everything below narrows the bounce; nothing deletes it.

## 3. The cost, in the unit that matters

The unit is not bytes and not one file. Per `docs/CHANNEL.md` section 5 property
3, reporting never acknowledges, and its corollary is explicit: anything that
adds files to an inbox adds PERMANENT session-start text in the recipient until
something explicitly acknowledges it. So: **one bounce = one permanent unread
entry in a sibling's session-start banner, on every session that sibling starts,
until a human there explicitly acknowledges it.** There is no timeout and no
mtime watermark that ages it out (section 5 property 2 - seen is a SET).

Two multipliers make this a real number rather than a rounding error:

- A grammar that refuses N notes emits up to N bounces. Measured and recorded in
  `docs/LEDGER.md` entry 1417 and `BACKLOG.md` RM-430 item 1: RC's live
  `NOTE_NAME_RE` refuses **21 of the 176 `.md` notes** on disk (20 Variant A, 1
  Variant B), counted 2026-09-15.
- Rule 9 of the channel is correct in place or beside, NEVER delete
  (`docs/CHANNEL.md` section 4). Litter on this channel is not reversible.

That is the whole argument for the narrowings in section 4.

## 4. RC's position, question by question

### (1) Does RC bounce on a name-grammar refusal, or hold silently?

**RC BOUNCES.** A name-grammar refusal is the single case where nothing else in
the funnel will ever mention the note: it is refused at gate 6
(`tools/inbox_responder_runner.py:1568`, the `name-grammar` problem raised at
`:467-468`), so no reply, no measurement and no delivery entry is produced,
while the sender's own record says the note reached RC's disk. Holding silently
there is the exact failure the bounce was built for, and the runner already sets
`bounce_target` BEFORE gate 6 for that reason (`:1563-1566`).

Two conditions ride with this and are not exceptions to it: RC does not bounce
on a grammar clause RC has itself measured as refusing the live corpus (the
pre-arm rule in (5)), and the refusal is deduplicated by REASON rather than by
note (see (3)) - telling a sender twenty times that they omit HHMM is one fact
charged twenty times.

### (2) Is a bounce ever retracted or corrected?

**Never deleted. Corrected by a NOTE, never by a second bounce.**

Reconciling with `docs/CHANNEL.md` rule 9 (correct in place or beside, never
delete): rule 9 governs NOTES, and a bounce is definitionally not a note
(section 1). RC adopts rule 9 anyway, with one narrowing it does not anticipate.

- **Never delete.** Undoing a bounce would require RC to write into a sibling's
  tree a SECOND time. That is strictly worse than leaving the file: two boundary
  crossings instead of one, and the deletion is itself invisible to a watcher
  that keys on a set.
- **Correct beside, but the "beside" must be a NOTE.** A corrected bounce could
  be joined to the original by no machine on the channel, because no responder
  can read either one. Only a note carries a correction a human and a watcher
  both see, so the correction is a `CORRECTION-` note naming the bounce filename
  in its body.
- The code already forecloses the re-bounce path: the allowance is keyed
  `<agreement_id>:<note_sha12>` (`tools/inbox_responder_runner.py:765-767`) and
  consumed before the write (`:830-839`), so a second bounce for one note under
  one agreement is unreachable.

### (3) Rate limiting: is there a cap per sender per window?

**MEASURED GAP: no. There is no per-sender cap and no per-window cap today.**

The only cap in the code is ONE bounce per NOTE per AGREEMENT
(`tools/inbox_responder_runner.py:765-767`, enforced at `:830-833`, fail-closed
on an unreadable record at `:770-785`). Twenty unparseable notes from one sender
under one agreement produce twenty bounces. Against the corpus in section 3 that
is up to 21 permanent files over four trees on the first pass, all of them
saying one of two things.

**RC proposes** two additional caps, both of which only ever REDUCE what RC
writes:

- **One bounce per sender per distinct refusal REASON per agreement.** The
  reason tag is what a human acts on - `problems[0]` from `note_shape_ok`
  (`:459-495`): `name-grammar`, `note-oversize`, `note-shape:not-a-file` and so
  on. The second and twentieth `name-grammar` bounce to one sender carry no new
  information.
- **An absolute per-agreement ceiling on total bounces**, so a pathological
  sender cannot fill an inbox even across distinct reasons.

Suppressed bounces are not silent to RC: the count belongs in the metrics row,
which already carries a dedicated `bounce` field (`:361-364`, serialised at
`:1164` and `:1181`).

Tightening RC's own emission is unilaterally safe and RC treats it as RC's to
do. LOOSENING it is not - that is in NOT DECIDED.

### (4) Does a bounce consume hop budget?

**Measured: NO, on every counter, and RC ENDORSES that.**

What the code does today:

- `_emit_bounce` writes no delivery entry. Its only record is
  `inbox_responder_bounces.json` through `_record_bounce`
  (`tools/inbox_responder_runner.py:787-795`); the invariant is stated in its
  own docstring at `:820-823`.
- `budget_consumed` counts only entries in `inbox_responder_deliveries.jsonl`
  with status `attempted` or `delivered` (`:628-639`), and a bounce appends
  none.
- `delivered_count`, M1's operand, likewise (`:643-651`), and `metrics_row_ok`
  validates `m1.hops` against it at `:1269-1270`.

RC endorses it because `budget_consumed` is a PUBLISHED counter with a stated
definition - delivery ATTEMPTS - quoted into the channel's hops-to-quiescence
figure through `LABEL_A5_TEMPLATE` (`:182-186`). Folding an unanswerable
template file into it would change what the number means without changing its
name, which is the exact drift class this repository keeps paying for.

The honest cost, stated rather than glossed: the bounce is then the one outbound
act RC performs that NO budget bounds. Its bound is an allowance, and an
allowance caps repeats of one note, not total outbound volume. That is precisely
why (3) is a gap rather than a nicety.

### (5) The pre-arm rule

**RC MUST NOT ARM while its own measured grammar refusal rate over the live
corpus is nonzero.** Arming converts a measurement into a spray, and per section
3 the spray is permanent and undeletable.

As a gate, so it is checkable rather than a sentiment:

- Before arming, re-derive the count of `.md` names in every inbox RC can read
  that `NOTE_NAME_RE` (`tools/inbox_responder_runner.py:171`) refuses.
- Arming proceeds only if that count is ZERO, or if bounce emission is disabled
  behind an explicit flag for that agreement.
- The count is stamped to the commit it was measured at. It was 21 of 176 at
  2026-09-15 (`docs/LEDGER.md` entry 1417), and that figure is a hypothesis
  about today, not a fact about today.
- A refusal rate that is nonzero for a reason OTHER than the grammar - an
  oversize note, a junction - does not block arming, because those are genuine
  per-note faults rather than a systematic disagreement about naming.

Guards that already exist for the shape of the bounce, cited so nobody rebuilds
them: `tests/test_inbox_responder_runner.py:2585`, `:2605`, `:2631`, `:2651`,
`:2669`, `:2679`, `:2704`, `:2716`, `:2839`.

## 5. NOT DECIDED - five-way questions, not RC's to settle

Each of these is here because settling it alone would bind a tree that never
agreed to it.

- **Whether the other four trees accept bounce emission into their inboxes at
  all.** RC cannot consent on a sibling's behalf to a permanent, undeletable
  entry in the sibling's session-start banner. RM-430 item 3 states the two
  acceptable outcomes: all five accept it in writing inside their own agreement
  records, or RC disables the emit behind a flag. Section 2 is an argument for
  the first, not a substitute for it.
- **Whether the bounce filename grammar is pinned.** The "neither side can read
  it" property (section 1) rests on RC's `NOTE_NAME_RE` AND on each
  counterparty's admission test as each stands today. A sibling that widens its
  admission test to accept `.txt` breaks the property and RC would not learn of
  it. Pinning the bounce shape is a channel convention, so a `CHANNEL_VERSION`
  bump.
- **Whether the note-name grammar widens to admit Variant A.** A
  `CHANNEL_VERSION 2` five-way re-pin over the table inside `docs/CHANNEL.md`
  section 6, as that doc says in its own text. It is the cheapest way to drive
  the refusal rate in (5) to zero, and RC still may not do it alone.
- **Whether bounces are subject to any retention or archive rule.** There is no
  retention rule for the inboxes at all and no note proposes one (RM-430 item
  5). Any such rule is a shared convention, never a unilateral act.
- **Whether a RECEIVING tree may delete a bounce from its own inbox.** Rule 9
  binds what participants do to the channel's NOTES. A tree tidying its own
  directory is its own act and RC takes no position - RC's undertaking in (2) is
  only that RC will never delete one.
