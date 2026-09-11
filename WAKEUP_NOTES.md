# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-10, Q5-relay / gitignore-negation wrap (relocated `2026-09-10b` RM-398 partial; newest 3 = `2026-09-10e` Q5 relay + inert-negation fix, `2026-09-10d` RM-402 refuted, `2026-09-10c` RM-400 shipped / RM-401 refuted). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-10e - the Q5 ask was REDISCOVERY, and the ignored-tracked probe found ONE real defect in 342 hits

Tier-1, operator PRESENT. One `.gitignore` line plus a new guard test, shipped
as `5f3555ec4`, pushed `df58efa7e..5f3555ec4`. Plus one note DELIVERED to LW.

**THE JOINT RE-PIN WAS NOT TOUCHED AND IS STILL THE GATING ITEM, THIRD SESSION
RUNNING.** RSC silent since `2026-09-09-2100`; CS and LL silent. Do not re-pin.

**RE-ARM STATUS, since the operator expected one: PARTIAL AND NOT AS EXPECTED.**
LW re-armed as a CORRESPONDENT only - standby lifted 2026-09-10, two notes filed.
Its responder is BUILT and DELIBERATELY NOT ARMED (registering the task is D5).
RC's is `Ready`/disarmed too. **Nobody's responder is armed.**

**Q5 WAS ALREADY ANSWERED AND CLOSED - RM-389, LEDGER 1370, 2026-09-08.** Writing
a fresh answer would have been pure rediscovery; the recall gate earned its keep.
**The cause of LW reading it as open is in OUR record:** the operator narrowed the
exchange to RC <-> RSC only that day and put CS/LW/LL on standby, so RC's answer
was never written into LW's tree. Relay DELIVERED 2026-09-10 with operator
approval (sha `46a00569`, 4545 bytes, sibling sweep clean, 4 name slots armed).
CS and LL deliberately NOT written to - still on standby as far as we know.

**IGNORED-TRACKED PROBE (LW finding 5.3) RUN ON RC: 342 of 4726 tracked files sit
under an ignore rule, and 341 are ALREADY DOCUMENTED AND DELIBERATE.** `_archive/`
carries its own TRAP comment plus the `git mv` ritual; the 101qq block says
outright that listing a tracked file does not untrack it. Reporting those as
findings would have been three false MUST-FIX. **The one real defect:**
`!agents/state/resolved_decisions.json` was INERT - git cannot re-include a file
whose PARENT DIRECTORY is excluded. Fixed to `agents/state/*`; probe 342 -> 341,
nothing else exposed. The other two negations were checked and are effective.

**INSTRUMENT TRAP, cost one wrong table:** `git check-ignore -v` exits 0 on a
NEGATION match too, so `-v` output conflates "ignored" with "matched". Only the
bare `check-ignore -q` exit code answers the question. My first spot-check table
was wrong in every row; the 342 corpus count survived re-derivation unchanged.

**DO NOT REDO:** Q5 (closed, and now relayed). The `_archive/` and 101qq ignore
rules (deliberate, documented). An RM row for the negation - operator chose fix
over file, and it shipped with a red-before-green guard.

---

# 2026-09-10d - RM-402 REFUTED AS SCOPED, RM-398 residue RE-DERIVED, and a CIRCULAR MEASUREMENT caught by adjudication

Tier-1, operator AWAY: one comment block in `tools/stop_claim_gate.py`, two
BACKLOG rows, two ROADMAP rows. LEDGER 1386. Pushed `08fa98d2c..2c389200b`, CI
GREEN both workflows (`ci` + `docs-guards`), observed this run.

**THE JOINT RE-PIN WAS NOT TOUCHED AND IS STILL THE GATING ITEM, SECOND SESSION
RUNNING.** Inbox newest is still `2026-09-09-2100-from-RSC`, zero files dated
2026-09-10 or later, verbatim subdirs included. Do not re-pin unilaterally.

**CORPUS FROZEN FIRST AT 93 FILES**, live transcript excluded by name. 93 not 92
- a session landed since RM-401, which is exactly why the baseline was
RE-DERIVED. Whole-gate histogram at HEAD, reproduced by three separate passes:
28 findings / 19 sessions - `count_mismatch` 23, `full_suite` 2, `commit_claim`
1, `file_claim` 1, `hook_bypass` 1, **`push_claim_without_push` 0**.

**RM-402 REFUTED AS SCOPED, no code.** Its OWN FILED NUMBERS were wrong in both
directions: "6 live false positives, 2 of them this class" - there are **ZERO**
live findings of this check, and the latent non-git population is **15 across 9
sessions**. Cause read BY HAND at `tools/stop_claim_gate.py:480`: `did_push` is
computed ONCE over the session's whole bash record before the sentence loop at
`:495`, so all 15 sit in sessions it already clears and narrowing buys ZERO
live-finding reduction. The dominant class is NOT the repo listing the row leads
with - it is our own drift-guard budget idiom ("my entry pushed it over") at 10
of 15. Every removing candidate was RUN against its attack and fell, the row's
own named one included. Its suggested bash-record alternative measured WORSE in
both directions, because the budget idiom is written DURING THE WRAP, which is
exactly when pushes happen. **DO NOT RE-PITCH** an idiom / word-sense exclusion
list, a repo-listing shape, or a bash-window discriminator for `CLAIM_PUSH`.

**THE FINDING WORTH MORE THAN THE REFUTE: A CIRCULAR MEASUREMENT.** The
narrowing slice enumerated the non-git population with an IDIOM-SHAPED SCAN and
returned 6, while its entire job was evaluating idiom-list narrowings - so it was
structurally incapable of measuring its own false negatives, and every 0 in its
false-negative column was meaningless. Exhaustive classification returns 15; all
9 it missed lie outside its own three shapes. **Two agents agreeing would have
shipped that 6.** It was caught only because the counts DIVERGED and the
divergence was resolved against the corpus rather than averaged.

**RM-398 RESIDUE RE-DERIVED AT 1** - unchanged in count by RM-400
(`count_mismatch` 23 both sides), MOVED in mechanism: formerly an unindexed
fetch, now an INDEXED one whose real summary is split by a console wrap. **This
also explains the hand-off's 31-vs-28 divergence: that baseline was pre-RM-400.**

**A SHIPPED COMMENT STATED A REFUTED REASON, corrected here for the SECOND
time.** `tools/stop_claim_gate.py:305-310` called `42af2f7d` "a bare `28150
passed`" and "a LIVE POSITIVE CONTROL for the fence". Verified false against the
raw tool result: it is a GENUINE pytest summary hard-wrapped across three
physical lines, so it is a FALSE POSITIVE against a real summary. ROADMAP
corrected too; **LEDGER 1385 deliberately NOT edited** (append-only).

**THREE INSTRUMENT FAILURES THAT COST TIME, all caught.** (1) `grep -P` is
UNSUPPORTED in this locale - it exits 2 with "supports only unibyte and UTF-8
locales", and a `|| echo 0` fallback turned that error into a passing ASCII
scan. Verify the instrument before believing a clean 0. (2) `tools/md_guard_
selector.py` emits CRLF, so `xargs` passes a trailing `\r` INSIDE each filename
and pytest reports files missing that exist - pipe through `tr -d '\r'`.
(3) A `Monitor` watching CI emitted NOTHING for 30 minutes and timed out while
both jobs actually SUCCEEDED; its own filter failed silently. Silence from a
monitor is not success - query the SHA directly.

---

# 2026-09-10c - RM-400 SHIPPED and RM-401 REFUTED, and the verifier caught a FALSE SENTENCE in BOTH deliverables

Tier-1, operator AWAY: one tool module plus its test, one BACKLOG row, one data
snapshot. LEDGER 1385. Pushed `085236cf3..9d290f99e`, CI GREEN both workflows
(`ci` 16m46s, `docs-guards` 2m19s), observed this run.

**THE JOINT RE-PIN WAS NOT TOUCHED AND IS STILL THE GATING ITEM.** RSC's inbox
is silent: newest file `2026-09-09-2100-from-RSC`, zero files dated 2026-09-10 or
later. Do not re-pin unilaterally.

**EVERY NUMBER HERE WAS MEASURED OVER A FROZEN 92-TRANSCRIPT CORPUS COPY.** The
live directory holds the running session's own growing transcript. Baseline was
RE-DERIVED at `085236cf3` rather than inherited: 31 findings, `count_mismatch`
23, `ci_claim_without_probe` 3, `full_suite` 2, `file_claim` 1, `hook_bypass` 1,
`commit_claim` 1, **`push_claim_without_push` 0**.

**RM-400 SHIPPED (`7f2fc529e`).** `_QUOTED_EXE`'s directory group ended on
`[\/]`, which inside a character class is a forward slash and nothing else - the
escape is inert there. Fix is one character class, `[\\/]`. MEASURED 31 -> 28,
**3 removed, 0 added**, verifier-re-derived from both sides; all three are
`ci_claim_without_probe` in `653d2ee9`, which probed CI seven times via quoted
backslash paths and was told it never probed.

**RM-401 REFUTED AS SCOPED (`06f375c46`), no code.** A finding-level delta is
UNAVAILABLE - `did_push` is true by the END of any session that pushed, so
`push_claim_without_push` is 0 corpus-wide and no narrowing can move it. Scored
at the pattern level instead: **428 matches across 69 of 92 sessions; 19 sessions
have no push evidence and NONE of the 19 utters the word**, which is the whole
explanation of the zero. 16 candidates precede any push, 8 already `_negated`-
suppressed, 8 live at message granularity, **6 at TURN granularity**. Of those 6
the row's adjectival shape is exactly **1**, and there are **ZERO true
positives**. Four separating rules were built and killed. **DO NOT RE-PITCH a
part-of-speech / noun-class / determiner narrowing of `CLAIM_PUSH`.**

**THE PROCESS LESSON, and it repeated twice in one session: the verifier caught
a FALSE JUSTIFYING SENTENCE in BOTH deliverables, and BOTH TIMES the truth was
MORE FAVOURABLE than the claim.** RM-400's build wrote that the corpus held no
backslash `run view --log` FETCH, so that half was unexercised - false;
`42af2f7d` runs exactly one, its `ci_runs` goes 0 -> 1 under the fix, and its 31
output lines carry a bare `28150 passed` with ZERO `EV_SUMMARY_LINE` matches, so
the fence refused to credit it. That is a LIVE POSITIVE CONTROL sitting in the
corpus. RM-401's refute wrote that both its named residuals are evasion-free -
false for the `_negated` half. **Overstated ABSENCE of evidence is the recurring
build-agent failure shape here, not overstated results.** Both corrections landed
in the CODE COMMENT / row text, not only the commit message, and both were
independently re-probed at merge before being written down.

**MEASURED AND WORTH NOT REDISCOVERING: `_negated` on `CLAIM_PUSH` is ALREADY
launderable today.** Against the shipped gate, "This is not a guess: I pushed all
six commits to origin/main.", "Without further gating, I pushed the lane branch
to origin." and "Nothing was left uncommitted, and I pushed main to origin." are
ALL suppressed, while the bare "I pushed all six commits to origin/main." flags.
Those are the exact RM-398 laundering phrases. So the "widen the 40-char window"
residual is a laundering problem wearing a boundary-miss costume. Only the
NON-GIT-IDIOM residual ("pushed back", "pushed today") is genuinely evasion-free.

**A READING TRAP, now recorded: the sweep's `--tree` arm prints "PUSH HALTED" on
the known byte-pinned exception, but `.githooks/pre-push` invokes `--pre-push`,
which scores the DIFF.** This session's real push swept clean (11 files, 4 commit
messages, armed with 4 name slots + 4 counterparty codes). Reading the tree
banner as the push verdict would be a false alarm.

**DDragon 16.18.1 (`d0f7ab74f`)** committed on its own, matching the
16.11.1-16.17.1 precedent. Exactly 5 top-level JSONs track per version;
`champion_detail/` + `_assets_manifest.json` are gitignored at
`.gitignore:159-160`, which is why the dir read as fully untracked while only 5
of its 179 files staged.

**DO NOT REDO:** RM-397, RM-399, RM-400 SHIPPED. RM-398 PARTIAL with its
mechanism refuted. RM-401 REFUTED as scoped. The sweep re-verification (exactly
1 known finding) was run twice this session and has not moved.
