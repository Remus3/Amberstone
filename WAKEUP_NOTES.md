# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-11, RM-405 wrap (relocated `2026-09-10d` RM-402 refuted + circular measurement; newest 3 = `2026-09-11b` RM-405 caller-seam silent degrade, `2026-09-11a` stale-fallback + three silent failures, `2026-09-10e` Q5 relay + inert-negation fix). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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
