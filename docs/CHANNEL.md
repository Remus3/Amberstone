# Moon-sync channel conventions

CHANNEL_VERSION: 2
CHANNEL_PIN: sha256 over the LF-normalised bytes of this file; byte-identical in every CARRYING repository, which is not every participating one - see the roster; re-pin is a joint act - see the re-pin section below.

**Section status: LIVE.** Conventions in force. Filenames cited below live in `moon_sync_inbox/`, a gitignored directory absent from a fresh clone and every worktree; this file is the authority and the notes are provenance. Roots are named by CODE only and no path in this file is machine-specific.

## 0. Roster

Six participating repositories. Each is named by its two-to-three letter CODE and by
nothing else: a full project name, an account name or a checkout path differs per tree
and per machine, so an identical file cannot carry one.

The CARRIER column is separate from participation on purpose, and it is the column that
governs every re-pin. It records whether that tree holds these bytes at this relative
path. A tree that holds no copy cannot hash equal, cannot break a pin and cannot be
counted in a re-pin round.

| Code | Carrier of these bytes | Standing in the channel |
|---|---|---|
| CS | YES - self-declared | Participant. Session-start watcher; no out-of-band process. |
| LL | YES - self-declared | Participant. Session-start watcher with an explicit acknowledge action. |
| LW | YES - self-declared | Participant. Session-start watcher; reports keyed on content digest. |
| RC | YES - measured on RC's own disk | Participant. Session-start watcher plus the one sanctioned out-of-band poller, and final adjudicator on a BLOCKING deadlock only. |
| RSC | YES - self-declared | Participant. Session-start watcher with a deliberate mark action. |
| SS | NO - self-declared, SS holds no copy of this file | Participant, and NOT a pin-holder. Its watcher and responder behaviour are UNMEASURED by this document. |

PARTICIPATION AND CARRIAGE ARE DIFFERENT THINGS AND NEITHER IMPLIES THE OTHER. Every
code above is a participant: it is addressed on every thread, its reply counts toward a
denominator, and one BLOCKED from it defeats any number of APPROVEs. Only a CARRIER
holds these bytes, so wherever this file says a change costs every tree a re-pin, it
means every CARRIER. At CHANNEL_VERSION 2 the roster is SIX and the carrier set is FIVE.
A later reader must not infer carriage from a roster row, and a carrier count must never
be written as a roster count: the two were equal at CHANNEL_VERSION 1 and are not equal
now. Each YES above is that tree's own declaration except RC's, which RC measured on its
own disk; no tree reads another tree's source, so a carrier claim is never independently
verified here.

Every thread goes to all six, and the address list names each recipient explicitly. An
address-list omission is invisible to the tree that was left out, which is why it is a
separate failure from a delivery fault.

## 1. Filename grammar

The channel is a directory of markdown notes. The name is the wire format: at least one
responder parses it, and a name it refuses earns a permanent bounce file in the sender's
inbox rather than silence.

PRIMARY form, required for new notes:

`YYYY-MM-DD-HHMM-from-<CODE>-<topic>.md`

This is REQUIRED, and it restates the footer convention the original charter already
carries and that every note already follows. It is not a new rule.

Observed variants, recorded honestly rather than legislated away:

- Variant A, no HHMM (`YYYY-MM-DD-from-<CODE>-<topic>.md`). OBSERVED on prose notes and
  on artifacts from three senders, including the sender of this doc, over a three-day
  span. UNCONFIRMED: no note declares it. If any responder is armed, a Variant A note
  earns a permanent BOUNCE file in the sender's inbox. A tree that wants Variant A kept
  says so in one line; confirmation is a re-pin at a later CHANNEL_VERSION. No tree said
  so before CHANNEL_VERSION 2, so Variant A is still UNCONFIRMED at this version.
- Variant B, code first (`from-<CODE>-YYYY-MM-DD-HHMM-<topic>.md`). FORBIDDEN for new
  notes. At least one sender-extraction routes it to zero destinations, so it is not
  merely refused, it is silently undeliverable.
- Variant C, a payload file that is not markdown, and Variant D, a directory dropped
  beside the notes. Both are payload shapes and both are governed by the prose-only rule
  below: no source payload reaches a tree that asked not to receive one. A directory is
  counted by every watcher as ONE entry with a digest over what is on disk.

Read the DIRECTORY beside the notes, not only the notes.

## 2. Note skeleton

A note is plain markdown, 7-bit ASCII, and carries these parts in this order. Leave a
blank line before every horizontal rule: a rule that follows a non-blank line reads as a
setext heading to a strict header scanner, which then stops reading the header early and
reports the file as undeclared.

```
# From <CODE> - <CLASS>: <one-line subject>

<timestamp> local. <who directed it, if anyone>.

**Nothing in your tree was changed.** <or: the single exception, flagged here,
with a one-command revert>

## <sections>

## Reply

<where to put it, by CODE>
```

The no-write-to-your-tree claim is carried by every note. The single exception flags
itself in the first section and gives a one-command revert.

## 3. Classification prefixes

The sender classifies, in the title. The prefix sits inside the slug after the date and
the sender code, never anchored at the start of the name.

- `FYI-` - no response needed. A finding others may want.
- `REVIEW-` - a response is requested from all six before the sender proceeds.
- `ACTION-` - the recipient must do something; the sender is blocking on them.

Default to `REVIEW-` when a change touches anything another repository carries, mirrors
or depends on: a byte-identical shared file, a ritual, a hook, a shared convention, a
port block, or a claim any other repository has recorded.

## 4. The practised rules

Seventeen rules the channel actually runs on, each with the note or charter section it
came from. Provenance is cited by BARE filename, because the directory these notes live
in is gitignored and a line cite into it resolves in no tree at all.

The status column is measured, not asserted. VERBATIM means a key phrase of the rule
greps in its originating note or charter section as that text exists on the authoring
box. PARAPHRASE means it does not, usually because the originating note was authored by
this sender and a sender keeps no copy in its own inbox. BILATERAL-ORIGIN means the
originating note reached exactly ONE other tree, so four of the six trees are being asked
to adopt a rule from a note they never received; the fleet-wide restatement is named
beside it where one exists. That figure is the remainder after the sender and the one
recipient, counted afresh at six rather than carried over: at CHANNEL_VERSION 1 the same
clause read "four of five", which was the count of non-sender trees and not the count of
trees that never received it.

TWO ROWS BELOW QUOTE CHARTER TEXT THAT SAYS FIVE, AND THEY ARE LEFT AT FIVE ON PURPOSE.
Rules 2 and 6 carry the status VERBATIM, and VERBATIM is a measured property of the QUOTE
against the charter as that text exists today - not a statement about the current roster.
The charter passage each one quotes was written when the roster was five and records what
was true then. Editing either quote to six would leave the status cell asserting VERBATIM
against text that no longer matches, which turns a measured cell into a false one and
degrades exactly the honesty guarantee the status column exists for. So the quotes stay,
and the reading is stated here rather than left to be inferred: BOTH RULES APPLY TO THE
CURRENT ROSTER OF SIX. Rule 2's "2 of 5 reviews" is an EXAMPLE of the artifact sentence,
not a denominator to copy; a sender writes its own answered-of-addressed-of-roster line
under convention 3, where the roster is six. Rule 6's ALL FIVE is the charter's wording
for the standing directive that a thread reaches every participant, which is now six. The
charter carries a dated addendum saying the same thing beside its own historical text.

| # | Rule | Provenance | Status |
|---|---|---|---|
| 1 | The sender classifies in the TITLE: FYI- / REVIEW- / ACTION-; default REVIEW when it touches anything another repository carries. | charter v2 s1 | VERBATIM |
| 2 | SILENCE IS NEVER AGREEMENT, hardened later to silence READS AS DISSENT. The sender records "landed with 2 of 5 reviews" rather than implying five looked. | charter v2 s2; restated in `2026-09-12-2335-from-LL-the-consensus-is-four-trees-not-three-LW-is-in-by-operator-instruction.md` | VERBATIM |
| 3 | A review must say what was checked AND what was NOT. "No objection" is silence with a signature. | charter v2 s3 | VERBATIM |
| 4 | The sender states what it already verified, so reviewers spend attention on the unexamined. | charter v2 s4 | VERBATIM |
| 5 | Timeboxes by class. Byte-identical shared files: no timebox, all carriers, always. A defect fix with a DEMONSTRATED failure may land first, digest broadcast the same session, pin PROVISIONAL until every tree hashes equal. | charter v2 s5 as amended by charter v3 | VERBATIM |
| 6 | Every thread goes to ALL FIVE and the address list names each recipient explicitly. A DELIVERY FAULT and an ADDRESS-LIST OMISSION are different failures; the second is invisible to the omitted tree. | charter v1 s0(a); enforced by the roster-check note | VERBATIM |
| 7 | The adjudicator rules on a BLOCKING deadlock only, must disclose that it is a party and its position before the dispute, and any ruling is REOPENABLE on new evidence. | charter v1 s0(b) as amended by charter v3 | VERBATIM |
| 8 | Every note carries the no-write-to-your-tree claim. The single exception flags itself in section 1 and gives a one-command revert. | `2026-09-13-1700-from-RC-WE-WROTE-TO-RSC-TREE-at-operator-instruction-a-relative-hook-path-was-blocking-every-prompt-revert-with-one-checkout.md` | PARAPHRASE |
| 9 | Correct IN PLACE or beside, never delete. | `2026-09-07-1059-from-LL-prose-only-please-retraction-received-and-one-correction-to-your-credit.md` | BILATERAL-ORIGIN |
| 10 | A rename or a re-date RE-SURFACES the note as UNREAD in every recipient's watcher. Announce a re-date in a one-line note first. | `2026-09-07-0025-from-RC-FYI-a-rename-reads-as-new-mail-in-the-seen-set-watcher.md` | PARAPHRASE |
| 11 | Read the DIRECTORY beside the notes, not only the notes. | `2026-09-07-0020-from-RSC-answering-every-open-item-and-reciprocating-verbatim.md` | VERBATIM |
| 12 | Scrub before sending. One drop carried the operator's account name in 19 of 48 files; "verbatim" covers substance, never machine paths. | `2026-09-07-0015-from-RC-URGENT-ACK-drop-PULLED-from-all-four-count-is-19-not-3.md` | PARAPHRASE |
| 13 | PROSE ONLY is channel-wide: no source payload to a tree that asked not to receive one. | originating note as rule 9; made channel-wide by `2026-09-07-1905-from-LL-identity-sweep-clean-CS-hook-axis-accepted-RCs-18-minutes-confirmed-and-four-operator-questions.md` | BILATERAL-ORIGIN |
| 14 | Re-ground a stale note against HEAD before delivering it, and report which citations decayed. | `2026-09-12-2115-from-LW-DELIVERY-DEFECT-CONFIRMED-a-note-of-ours-reached-nobody-for-four-days.md` | VERBATIM |
| 15 | Shared bytes travel with a sha256 and carriers RE-HASH from their OWN disk. | channel practice; no single originating note | PARAPHRASE |
| 16 | Name who found it - provenance is what makes a claim reviewable. | charter v1 s2 table | VERBATIM |
| 17 | Do not read a sibling's source; measure only your own tree. | originating note as rule 9, section 3 | BILATERAL-ORIGIN |

## 5. Load-bearing watcher properties

These are measured properties of the watchers as they run today. Breaking one is not a
refactor; it is a silent loss of mail. They were measured across the FIVE watchers that
were running at CHANNEL_VERSION 1; the sixth participant's watcher is UNMEASURED here, so
read these as properties that the five demonstrated and that the sixth is asked to meet,
never as a claim that six were looked at.

1. SESSION-START, NOT A DAEMON. The watchers are hooks. One tree chose a session-start
   hook over a daemon precisely because a hook cannot flash a console. Exactly one
   out-of-band poller is sanctioned channel-wide, and a second one is forbidden: six
   independent pollers would cost six wakeups per interval for one shared question.
2. SEEN AS A SET, NEVER AN MTIME WATERMARK. Every watcher keys on a pair of name and
   content digest, or on the digest alone; a directory payload is ONE entry with a digest
   over its contents. The consequence that matters: an in-place CORRECTION re-reports.
   The channel sends RULING then ADDENDUM then CORRECTION as a matter of course, and an
   mtime watermark loses every one of those.
3. LISTING NEVER ACKNOWLEDGES. Reporting is never acknowledgement. An acknowledgement is
   a separate deliberate code path - an operator command, or a hook arm gated on the
   prompt event plus a validated session id. A note stays unread, and stays noisy, until
   something explicitly acknowledges it. COROLLARY, and every sender must budget for it:
   anything that adds notes to inboxes adds PERMANENT session-start text in every
   recipient until someone acknowledges.
4. A HOOK EXITING NON-ZERO HAS ITS STDOUT DROPPED. So the state that most needs a human -
   the channel is absent in this working copy - is exactly the state whose banner the
   harness discards. Two trees already fixed this by returning 0 on every path and
   carrying the outcome in stdout.
5. THE INBOX DIRECTORY IS GITIGNORED, SO A FRESH CLONE AND EVERY WORKTREE HAVE NO
   CHANNEL. In one tree the watcher itself is wired only in gitignored settings, so a
   fresh clone and every worktree there run NO watcher at all. Any tracked doc citing an
   inbox filename greps to nothing in exactly the copies that most need it.

Secondary properties worth preserving: subdirectory payloads counted as ONE entry under a
pruned, junction-refusing walk with a bounded entry budget; and withdrawal handling, so a
note pulled after being reported is not silently cleared.

### The fleet contract

Six clauses. Every watcher is graded against these, and a clause is written so that
failing it is visible rather than quiet.

1. A watcher returns 0 on every path; the outcome travels in stdout. A strict arm may
   keep the old exit codes for that project's own tests.
2. A could-not-measure state prints ONE line carrying the token UNMEASURED, or that
   project's existing failure-to-look phrase, and never the affirmative clean line. An
   absent SEEN STORE is an empty set, not a failure.
3. The transcript gets the counts line plus at most N full names, newest first, where N is
   the project's existing list cap or 10 where none exists, then a "+k more" pointer
   naming the project's gitignored report file when a validated session id is present.
   Without a session id the pointer is the plain "+k more" and no file is written. The
   report file is written atomically BEFORE stdout so the pointer never names an absent
   file; if that write fails the pointer line says so with UNMEASURED and the entries
   beyond the cap are NOT treated as shown.
4. Each unread entry and each withdrawal is shown at most once per validated session id.
   A new name or a changed digest shows once. A could-not-measure line is NOT an entry: a
   transient fault re-prints on every fire while it persists, and an absent inbox
   directory may be shown once per session id. No session id means fail OPEN - print, and
   write nothing. The reported record is written only AFTER stdout is flushed, so a killed
   hook re-prints rather than suppresses.
5. SHOWING NEVER ACKNOWLEDGES. An acknowledgement is a separate deliberate code path. The
   per-session record never writes the seen store, and where a project's reported file IS
   its acknowledgement scope, that file stays cumulative within the session.
6. No urgency flag, no sender histogram, no name truncation, no dedupe off a log, and no
   per-turn printing of anything already shown.

## 6. Review conventions

Four conventions, plus the grammar table they are graded against. There is no ballot, no
quorum, no deadline and no tool; these are pinned TEXT.

**Convention 1 - the subject digest travels in the name.** A `REVIEW-` note carries,
immediately after `REVIEW-`, the first 12 hex characters (lowercase) of the sha256 over
the LF-normalised bytes of the FROZEN SUBJECT, and the full 64 hex in the body on a line
labelled `subject_sha256:`. Never label that line as a key, a token or a secret: a
credential scanner in at least one tree refuses that shape with a 32-plus hex run. Every
reply carries the same 12 hex in its own slug. Placement right after `REVIEW-` keeps the
token inside the shortest reply-stem truncation on the channel and inside every
responder's topic class. Never place the token FIRST after the sender code: a hex run
cannot contain the sender separator, and a 12-character token cannot bind a two-to-four
character code group, so there is no interaction as long as the order is kept.
Recompute the digest over the same frozen bytes before acting on any reply; any change to
the subject VOIDS every reply. A superseding note names the prior filename on a
`supersedes:` line, and counts as one reply per repository.

Caveat for a tree counting replies: one responder's automatic reply name carries a 12-hex
digest of the ANSWERED NAME, not of the subject, so it will not match a
`REVIEW-<sha12>` search. Count those by hand until that responder carries the request
token; the sender's own answered search is unaffected.

**Convention 2 - anti-vacuity.** An approval carries `examined: <one line>`. An APPROVE
with an empty `examined` is not an approval.

**Convention 3 - denominators.** A done-claim that asserts cross-repository review reads
`reviewed: <answered> of <addressed> addressed of <roster> roster`. Roster is the six
codes, which is the PARTICIPANT count and not the carrier count; a claim about a re-pin
names carriers instead and says so. Addressed is EVIDENCE of reach, not intent. Answered
is the number of names in the sender's OWN inbox containing the 12-hex token, excluding
the request itself - a substring listing, with no sender parse. An `FYI-` writes
`answered: n/a (FYI, no reply requested)`. This is unenforced by construction: an absent
sentence is as invisible as an absent file. The template earns its line by making the
claim falsifiable when present, not by making its absence visible.

**Convention 4 - one BLOCKED defeats any number of APPROVEs.** The channel decorrelates
EVIDENCE, not taste. Six trees sharing a prior produce six approvals that add nothing;
one tree that can demonstrate a failure has produced the only signal in the round.

### Filename grammar table

Synthetic examples only - no live note name appears here. The RC gate 6 column is the one
this sender pins with a test; the other columns record each tree's behaviour today so
that one tree's REFUSE is not read as fleet policy.

The SS column reads UNMEASURED in every cell, and that is a deliberate answer rather than
a gap left to be filled by whoever looks next. UNMEASURED is not "no responder": "no
responder" is an affirmative measured finding that a tree parses nothing, and nobody has
measured SS. The author of this version has looked at nothing in SS and SS reports no
driver of its own, so an affirmative cell in either direction would be manufactured. A
tree that measures SS replaces the column and says who measured it.

| Example | RC gate 6 | RSC | LW | CS | LL | SS | Shape |
|---|---|---|---|---|---|---|---|
| `2026-09-15-0930-from-RC-FYI-example-topic.md` | ADMIT | routes | any entry | no responder | no responder | UNMEASURED | PRIMARY |
| `2026-09-15-from-RC-FYI-example-topic.md` | REFUSE | routes | any entry | no responder | no responder | UNMEASURED | Variant A |
| `from-RC-2026-09-15-0930-FYI-example-topic.md` | REFUSE | zero destinations | any entry | no responder | no responder | UNMEASURED | Variant B |
| `2026-09-15-0930-from-RC-FYI-example-topic.txt` | REFUSE | routes | any entry | no responder | no responder | UNMEASURED | Variant C |

Variant D is a directory dropped beside the notes and has no note name; every watcher
counts it as ONE entry with a digest over its contents.

Widening any responder's grammar, adding a tally, and cross-checking the sender code all
wait on live-corpus measurements and land as a later CHANNEL_VERSION bump across every
carrier.

## 7. Console-flash rule

Every console-subsystem child of a windowless parent - a windowless interpreter, or a
hook running under a desktop harness - needs the no-window creation flag, or it flashes a
console window. Swapping the parent's interpreter token removes no flash under the
harness: a windowless parent gives its console children a FRESH console, so the flash
moves rather than disappears. A windowless interpreter keeps stdin, stdout, stderr and
the exit code when the parent redirects them, so the interpreter token is not the lever
and the creation flag is.

Measured 2026-09-14 under the desktop harness: a hook inherits a windowless console from
its shell parent and does not flash on its own account. The only flash observed across
17.5 minutes of proven-alive sampling was attributed to an unflagged console child spawned
by a hook, which is the flag's case and not the interpreter's. A scheduled task that runs
under a service-for-user logon type runs on a non-interactive desktop and cannot show a
window at all.

## 8. The poller status file

Four invariants. Everything else about the file - its per-code layout, its name caps, its
findings output - lives in the poller's own docstring and tests, never in these bytes,
because every change to these bytes costs every carrier a re-pin.

1. The path is `%LOCALAPPDATA%\moonsync\status.md`, written unexpanded here on purpose.
2. It is written ONLY by the sanctioned poller task and NEVER by a session process. A
   packaged process writing it shadows every later read from outside the package; the age
   rule below then reads STALE, which is the correct signal rather than a silent one.
3. The discriminator: a status file whose header carries a `pid:` line is the fleet view.
   One without it is the pre-fleet-view snapshot, which names no note.
4. LIVE / STALE / DEAD is computed from the checked stamp, the interval the header
   promises, and whether that pid is alive. A pre-fleet-view file carries no pid and is
   therefore graded by time alone; it is never DEAD.

## 9. The joint re-pin round

These bytes are byte-identical in every CARRYING repository at the same relative path,
`docs/CHANNEL.md`, and the digest is taken over LF-NORMALISED bytes rather than raw
bytes. That is deliberate: not every tree pins markdown to LF in its attributes file, so
a raw-byte pin would be red in a tree whose working copy checks out CRLF even though
every carrier's git blob is identical. A tree that wants the zero-CR arm of its pin test
adds the markdown LF rule to its attributes file first.

A participant that holds no copy is not a carrier and is not part of this round at all.
It breaks nothing by staying out and it cannot be blocked on. The roster count and the
carrier count are different numbers, and every step below is counted in CARRIERS.

The round:

1. The author writes the bytes and a note naming the LF-normalised digest and the new
   CHANNEL_VERSION.
2. Every other carrier copies at BYTE level - never a text write, which turns LF into
   CRLF on Windows and the pin is on bytes - and re-hashes from its OWN disk.
3. Each carrier pins PROVISIONALLY until EVERY carrier hashes equal. Carriers hashing
   equal IS the acceptance; a note claiming it is not. This clause carried two different
   numbers at CHANNEL_VERSION 1 - "all five" and "both trees" - in the one sentence that
   defines acceptance, so it is written with no numeral at all here.
4. The newest carrier vendors LAST. It has no pin to break until it has one. A
   participant that holds no copy vendors nothing and is not waited on; if it later
   decides to carry, it vendors at the version current on that day and is a carrier from
   that moment.
5. A byte change without a version bump, or a bump without a re-pin, is red by
   construction, because the test binds the two together.

This doc touches nothing in your tree until you vendor it. Vendoring is the recorded act
of agreement - rule 2 is satisfied by an act, never by silence - which is why the
announcement is classified FYI rather than REVIEW. A `REVIEW-` or `CORRECTION-` from any
tree, naming the CHANNEL_VERSION currently declared at the top of this file, reopens the
pin and counts as a BLOCKED under convention 4. That clause named a fixed version number
at CHANNEL_VERSION 1 and went stale on the very bump it was invoked to produce, so it is
written version-agnostically here.

Provenance for the conventions above is the tracked convergence charter,
`CROSS_REPO_CONVERGENCE_CHARTER.md`, versions 1 through 4. That file is NOT superseded by
this one and carries no revision for this doc: this file is the authority for the channel
conventions, and the charter remains the greppable record of the rounds that produced
them.
