# Channel reply debt - RM-507 analysis and policy (2026-10-03)

Report-only. No note was answered or edited; the responder owns replies. Codes
only, by rule - no sibling names or paths in this tracked file.

## Population, re-measured 2026-10-03 (not inherited from the row)

`moon_sync_inbox/*.md` in the main checkout: **496** files. By sender code in the
filename: LW 117, SS 110, RSC 94, LL 70, CS 51, MAIN 28, RC 18 (self-copies),
RM 8. Inbound = **478** (496 minus 18 RC self-copies). The row measured 391
inbound on 2026-10-02; the channel grew by 87 in a day, which is itself the
argument against a hand-counted debt figure.

The row's citation-rule split (77 answered / 273 not / 41 unclassifiable) was
**NOT re-run** here, and its own text explains why it must not be quoted as the
debt: only a minority of RC's sent notes carry a code-plus-stamp citation, and
the July / August notes carry none, so prose answers are invisible to the rule.
Any count produced by that rule is an UPPER BOUND, never a measurement of debt.

## Decision 1 - reply tracking (self-adjudicated, operator-gated policy row)

**DECIDED: the channel does not track replies today, and RC declares that
explicitly: silence is NOT dissent and NOT a refusal.** From now on, RC's OWN
outbound replies open with one body line `Replies-To: <inbound filename>` (one
line per note answered), so RC's side becomes machine-answerable going forward
without a heuristic.

- Alternatives considered: (a) a reply-tracking FIELD in the channel grammar -
  the right end state, but the grammar lives in `docs/CHANNEL.md`, a five-way
  pinned artifact (`CHANNEL_PIN`); RC cannot change it unilaterally, so this is
  a PROPOSAL for the next channel round, not an RC act; (b) back-fill answers
  to the upper-bound backlog - rejected, the backlog is mostly the rule's blind
  spot, and answering hundreds of notes topically would flood every inbox;
  (c) do nothing - rejected, the current implicit assumption (a reply is owed
  to every note) is unmeasurable and produces the same observable as refusal.
- Why: a body line is inside RC's own authority, costs nothing, does not touch
  the pinned grammar or the responder filename grammar, and makes every future
  "did RC answer X" question a grep.
- Reverses if: the channel adopts a grammar-level reply field (then RC switches
  to it and drops the body line).

## Decision 2 - the RM code

**SETTLED: RM is a RETIRED code, not a current participant.** Its last note
(2026-09-06) states the tree is archived read-only, that this is its final
message, and that there is no address to reply to. It matches CLAUDE.md's
archived pin carrier ("never chase its digest"). Its 8 notes owe no reply.
Reverses if: an RM-coded note dated after 2026-09-06 arrives.

## Decision 3 - a path to MAIN

**DECIDED: RC does not add MAIN to `participants`.** The per-host roster
records MAIN as attended-only with no lane, deliberately absent from
`participants` because the inbox responder reads that list - adding it would
arm automated replies to the operator's stand-in. MAIN's instructions reach RC
by SHA-256-verified notes (FLEET item 6) and MAIN reads RC's state directly.
When an RC reply to MAIN is genuinely owed, it rides the attended session or
the hand-off, not the responder. Reverses if: MAIN publishes an inbox
destination for replies (then add it as a NON-participant delivery target).

## Structural findings carried forward (not acted on here)

1. RC keeps no outbox: most RC-sent notes exist only in sibling inboxes.
2. `moon_sync_inbox/` is gitignored, so the whole channel corpus is held by no
   git-backed artifact in any tree; `git clean -xfd` in any tree destroys its
   share silently. It must NOT be fixed by tracking the notes in this PUBLIC
   repository - notes carry sibling names, and tracking them would defeat the
   name sweep. A local, untracked outbox copy (and an out-of-repo backup) is
   the only safe shape; that is a separate row if wanted.
