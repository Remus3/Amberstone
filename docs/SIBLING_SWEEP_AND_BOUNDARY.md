# Sibling-name sweep, the byte-leaves-tree boundary, and the headless-looping program

**Demoted out of `CLAUDE.md` on 2026-10-01 to recover auto-load budget.** This file is the
AUTHORITATIVE LONG FORM of what used to be a single 7514-byte paragraph on `CLAUDE.md` line 240.
`CLAUDE.md` now carries the SHORT FORM - the rules a session must have in context on every turn -
and points here for the evidence, the dated supersession history and the blind-spot detail.

**Nothing here was deleted or softened.** Every sentence of the demoted paragraph survives VERBATIM
below; the only change is that the sentences are grouped under headings. The demotion was explicitly
constrained so that a session could not "fix" the `CLAUDE.md` size budget by DELETING a fence. If you
are about to trim this file, that is the same move under a different name: relocate, never delete.

Read this before trusting a CLEAN sweep report, before re-pitching a destination-based push rule, and
before restoring any sentence that this file records as SUPERSEDED.

## The program and the runner

**HEADLESS-LOOPING PROGRAM (standing, operator 2026-09-09): the five-way responder work - its tests and its fixes - runs on a HEADLESS LOOP, not as attended per-row sessions.** **The RUNNER ITSELF IS ALREADY BUILT** - RM-384 shipped it 2026-09-08 (LEDGER 1364) and RM-385 + RM-386 shipped both tails the same day; `docs/RESPONDER_RUNNER_SPEC.md` is the spec it was built FROM, not open work. So the loop's scope is tests, fixes and hardening on a shipped runner. A first draft of this rule called the runner unstarted, which was one day stale. The loop does not ask permission per cycle.

## The boundary

**THE BOUNDARY (operator-adopted 2026-09-09, SUPERSEDING the ARMING-only reading): halt before any byte leaves the tree.** The loop halts and PINGS THE OPERATOR before any write, delete or lock acquisition outside the repository root, before any PUSH WHOSE DIFF CAN LEAK (the diff gate below - the destination rule that used to sit here is SUPERSEDED), and before any edit to a cross-repository byte-pinned or grammar-pinned artifact - not merely before arming a task. Arming REMAINS a halt point; it is simply no longer the only one and no longer the earliest.

**SCOPE, decided by the operator in the same breath: this binds EVERY RC session, ATTENDED ONES INCLUDED.** Every byte-leaves-tree act halts in an attended session too. Do not read "headless loop" in this heading as the limit of the rule.

## The one carve-out

**ONE STANDING CARVE-OUT, operator-granted 2026-09-20, and it is NARROW: delivering a channel REPLY into a sibling's `moon_sync_inbox/` is PRE-AUTHORISED and does NOT halt.** The operator's words were "yes always deliver a reply". **Its scope is the agreed inbox surface and nothing else** - it does not authorise writing, deleting or locking anything else outside the root, it does not authorise reading a sibling's tree beyond what a reply needs, and it does not touch the PUSH half or the byte-pinned-artifact half, both of which still halt. **Deliver, then RE-HASH every destination and publish the reached-count** (a discipline adopted from a sibling: an outbound note sitting in your own outbox is not delivery, and only the recipient's copy proves it).

## The push gate is on diff content

**THE PUSH HALF IS GATED ON DIFF CONTENT, NOT ON DESTINATION (operator-adopted 2026-09-09, SUPERSEDING the one-day-old carve-out that pre-authorised a push to RC's OWN origin; that sentence is deleted, not softened, and both readings must never sit in this file at once).** A push HALTS and pings when its DIFF touches a cross-repository byte-pinned artifact (`ops/loop/slots.py`, `ops/loop/winmutex.py`, pinned by `SHARED_SHA256` in `tests/test_loop_concurrency.py`, parametrised over `sorted(SHARED_SHA256)` in the same file - **cited by SYMBOL deliberately, never by line, per the standing rule at `ROADMAP.md` NOW-"three small lanes"; the line numbers have now drifted THREE times (`:474`->`:480`, `:542`->`:548`->`:574`)**; `docs/CHANNEL.md`, pinned by `CHANNEL_PIN` in `tests/test_channel_doc_pin.py`), or when it trips the sibling-name sweep. It does NOT halt on an ordinary push that passes the suites and the sweep. A DESTINATION rule is wrong in BOTH settings (evidence: `docs/history_notes.md` 2026-09-16). A content rule halts on neither ordinary case and halts on precisely the pushes that can leak.

## The sweep: armed, with a measured escape rate above zero

**THE SWEEP EXISTS AND IS ARMED (RM-399 SHIPPED 2026-09-10): `tools/sibling_name_sweep.py`, guarded by `tests/test_sibling_name_sweep.py`, wired into `.githooks/pre-push` AHEAD of the preserved `git lfs pre-push "$@"`.**

**But the honest claim is "the sweep half is ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO", never "sibling names cannot leak", and that phrasing must not be softened.** Specifying it found **FIVE REAL ESCAPES in RC's own tree**, all live in HEAD and **ALL ALREADY PUBLISHED to the public remote**. Four were remediated at HEAD (`f6cf005bb`); **remediating HEAD does NOT undo publication, and no history rewrite was performed.** **The fifth was CLOSED UNILATERALLY 2026-09-12; the fence that called it joint was wrong on its premise** (`SHARED_SHA256` pins only `slots.py` and `winmutex.py`; evidence: `docs/history_notes.md` 2026-09-16). `KNOWN_EXCEPTIONS` in the tool is now `{}` - there is no declared exception left, and this sentence must not be restored to claim one.

## Named blind spots

**Named blind spots:** A BARE CHANNEL CODE IS NEVER DETECTED - measured 2026-09-20 in the NEEDLE-arm runner in `tools/sibling_name_sweep.py`, whose own docstring reads "Never matches a code on its own": the code arm only escalates `SEV_NAME` to `SEV_RESOLUTION` near an existing NAME match, so it is a severity MODIFIER and never a detector. **Cited by SYMBOL and by quoted docstring, not by line, and that is the fix rather than a style choice: on 2026-09-30 all three line numbers in this paragraph and the one above were found STALE (`:904`, `:936-941`, `:548`), and every one of them still RESOLVED while pointing at unrelated text, so nothing flagged them.** A fourth cite in the same paragraph (`:480`) was correct, so a spot check of one would have passed the paragraph - sampling does not work on this failure class. A citation here is load-bearing because CLAUDE.md auto-loads every turn; grep the SYMBOL, never inherit a number.

The sweep reported `ops/loop/winmutex.py` CLEAN while its line 118 named a carrier, and reports clean for every other counterparty code too. **That INSTANCE was repaired 2026-09-20 by ROUND B (`3ca8be8ce`; bytes 6190 -> 6184, `df0a7a40`, pin moved in the same commit), so do not go looking for it - but the BLIND SPOT is unchanged and the example must not be read as closing it.** A repaired instance is not a repaired detector. RC's earlier channel wording, "matches project names not channel codes", UNDERSTATED this - the codes are not a weaker arm, they are not an arm at all.

LFS OBJECT CONTENT is never scanned by `--pre-push` (the pointer is, and scans clean truthfully) - **but that is FALSE of `--tree` on a smudged checkout, measured 2026-09-20 (RM-477): the tree arm reads the WORKING TREE, so it scans the full smudged payload, 633,521,375 bytes over 4911 files. That is MORE coverage than this line used to claim, not less, and the general trap is that a fact about the OBJECT STORE is not a fact about the CHECKOUT;** `--no-verify` bypasses the whole hook and nothing can prevent it; `RC_SIBLING_SWEEP_BYPASS=1` proceeds but prints the full would-have-halted report and appends it to a gitignored log.

**It is NOT contiguity-only:** its positive-control arm is seeded from RC's OWN five escapes and includes a SPLIT-FORM control catching a name broken across a comment-continuation line wrap, which no whole-token search can see.

## No timeout, and RC-InboxResponder stays disarmed

**And there is NO TIMEOUT: RC halts and WAITS.** It never proceeds after a delay, because a bilateral rule that auto-proceeds is a unilateral rule with extra steps. `RC-InboxResponder` stays DISARMED until an expiring agreement record arms it, and an unattended loop must never arm another repo.

## Outbound documents others may vendor: licence beats their name sweep (RM-505)

Read this BEFORE authoring any RC document meant for a sibling to adopt. Measured 2026-10-02 on `docs/CITE_BY_SYMBOL.md`: a sibling licence gate correctly refused it for carrying NO licence statement; RC added repository, visibility, licence and copyright holder; that fix then made the bytes un-vendorable into a sibling's tracked path, because a public tree's name sweep refuses RC's project name. Provenance REQUIRES naming the source; a recipient's name sweep REQUIRES not carrying it. The same bytes in a tracked path cannot satisfy both.

**DECISION (self-adjudicated 2026-10-03, operator-gated policy row):** every outbound document carries its licence and provenance IN THE ARTIFACT, and RC states in the delivery note that the expected adoption is the IDEA with attribution, not the BYTES. Both recipients chose exactly that independently, unprompted.

- Rejected: licence only in the delivery note - the artifact then travels unlicensed, which was the original defect.
- Rejected: a names-free variant beside the licensed one - doubles the artifacts, invites drift, and still ships an unlicensed copy.
- Never: remove or spell around the licence or the name to get past a recipient's sweep. That was the correct refusal, and evading a sweep hides the pattern from the next human reader too.
- Reverses if: a recipient's tree adopts a vendoring path that exempts attributed third-party files from its name sweep (then bytes become adoptable as-is).

## Superseded readings that must never be restored

The 2026-09-09 gap sentence that sat here - asserting in capitals that RC had no such sweep, that no such test file existed, and that pre-push was LFS ONLY - was true when written and is now false in all three halves; it is deleted, not softened, and must not be restored.

**RSC REFUTED the older ARMING-only reading** with seven seams that reach another repo with NOTHING armed: the shared `slots.py` root, `reap()` unlink, `Global\` mutexes, the byte-pinned pair, responder filename grammar, push, and unconfined subagent writes (full text: `docs/history_notes.md` 2026-09-16).
