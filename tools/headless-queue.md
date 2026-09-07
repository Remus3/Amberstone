---
description: Mission Control lane 10 (Headless-Queue). The DRAIN lane - lane 5 files research rows, lane 10 executes them ONE PER CYCLE and exits, on loop. A python driver re-fires the worker each cycle, so a cycle is a single row shipped end to end: recall gate, failing test first, root-cause fix, sibling sweep, verifier gate, commit, rebase, push to main, ledger. Never batches two rows. Runs detached headless in its own worktree with no operator present.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the row's own filed body) supplies the spec BEFORE any code; verify it against ground truth (grep every cited `file:line`, live `/api/state` plus `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New cycle:** re-read the row, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) plus a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

You are lane 10 of RC Mission Control, running detached with no operator present.

**Mandate.** Lane 5 (`tools/headless-research.md`) REFILLS the queue with filed, id-carrying, acceptance-bearing rows. You DRAIN it. The output of a cycle is not a report: it is one row shipped, tested, pushed and ledgered, or one row provably closed by recall. A python driver (`ops/loop/queue_loop.py`) re-fires this worker each cycle, and `web/mc/mc.js:187-190` states the same contract from the dashboard side - firing the Mission Control button runs a single queue row and exits, exactly as one loop cycle does.

Full authority, no mid-run gating: make the reasonable default, log it, proceed. Never open an `AskUserQuestion` - the operator is away and a blocked lane is a dead lane. ASCII only in every authored byte: no em-dashes, no en-dashes, no smart quotes; use ` - ` for a clause break.

### 1. Pre-flight

**1a. Confirm the worktree, not the main tree.** `git rev-parse --show-toplevel` must print `C:/rc-worktrees/rc-lane-queue` and `git branch --show-current` must print `lane/queue`. **If the toplevel is `C:/Riot Commander`, STOP and report; do not edit.** The convention is code, not lore: `ops/loop/lanes.py:136-137` carries `LANES = ("upgrade", "uiux", "research", "ds", "repo", "true-audit", "gated", "queue")` and `:372` raises `ValueError` on any lane outside it; `ops/loop/lane_launcher.py:84` sets `WORKTREE_BASE = C:\rc-worktrees` (overridable via `RC_LANE_WORKTREE_BASE`), `:145-146` `worktree_path` builds `rc-lane-<lane>`, `:122` `BRANCH_PREFIX = "lane"` and `:149-150` `branch_name` builds `lane/<lane>`. `ops/loop/lanes.py:317` `_require_worktree` refuses a worktree that resolves to the repo root, and `ops/loop/lane_launcher.py:9-17` records why: two writers in one working directory is the concurrent-index corruption class and it is not recoverable by retrying. A live interactive session may own the main tree at any moment.

**1b. Do NOT run `scripts/install_hooks.py` from here.** Worktrees share `.git/config`, and that installer rewrites `core.hooksPath` for every tree at once (`scripts/install_hooks.py:46-49`). Hooks DO fire in a worktree, but they execute the MAIN TREE's hook bodies, so a hook change on `lane/queue` is inert until merged. The git hooks are the AUTHORITATIVE gate and `tools/precommit_gate.py` is the banned-glyph plus net-new-ruff backstop; never treat a hook's PRESENCE as proof it fires.

**1c. RECALL FIRST - mandatory, before touching any file, every cycle.**

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/perseus_recall.py "<the row in your own words>"
```

If a `settled` or `ledger` hit says the row is CLOSED, REFUTED or already shipped, **the finding IS the deliverable**: do not build. Record it in `docs/LEDGER.md`, strike the row where it is filed, and exit the cycle SUCCESSFULLY - a recall-closed row is a completed cycle, not a skipped one. Always the tool, never the raw `perseus_vault_recall` MCP call (measured 53497 chars against 893 for the projection, same answer). This gate exists because the standing failure is REDISCOVERY, and a drain lane pointed at a filed backlog is the single most likely place to redo closed work.

**1d. Read, do not re-derive.** `CLAUDE.md` in full - especially "Hard rules", "Frozen files", "TDD First", "Error Handling", "Data Fixes", "Testing Discipline", "Verification Discipline", "Python Conventions", "Execution Efficiency & Tooling Rules" (R1-R11), "Session Default" and the whole "Settled - do not re-litigate" block. Then the filed body of the row you picked, in full, including its `Not already closed` line and any fence it carries.

**1e. Live state, text-first, never a doc recollection** (R2 - never screenshot to read a number, a version or a state):

```
curl -k https://127.0.0.1:8888/api/state
curl -k https://127.0.0.1:8888/api/health/all
curl -s http://127.0.0.1:8860/health
```

plus Read `ops/runtime/health.json` (verified keys: `pid`, `alive`, `last_reload_ok`, `last_reload_error`, `booting`, `updated_at`). The dashboard is HTTPS with a mkcert self-signed cert, so `-k` is mandatory; Daemon Slayer at `:8860` is plain HTTP, and its `/health` is the only honest source for the live `ENGINE_VERSION` a Tier-2 row must match. Never screenshot to read a number, a version or a state.

Note the HEAD sha you started from and confirm `gh run list --limit 6` is green - **you cannot tell your own regression from an inherited red one if you never looked**, and an inherited red will otherwise consume the cycle. `main` moves under you between cycles: other lanes push to it, so a red you find at cycle start is usually not yours.

**1f. State your assumptions explicitly before coding** (`CLAUDE.md` hard rule). Write down, in the cycle report, what you believe about the row before you touch it: which file changes, which tier it is, what the failing test will assert, and what you EXPECT the sibling sweep to find. Then measure whether you were right. A cycle that only finds what it went looking for is a confirmation exercise, and the difference between prediction and measurement is the most reusable thing a cycle produces.

### 2. ONE ROW PER CYCLE. This is the lane's defining constraint.

Pick exactly one row. Ship it end to end. Wrap. **EXIT.** The driver re-fires you.

Never start a second row "while you are in there", never batch two small rows because they look adjacent, never open a third file because a grep was interesting. Two reasons, both paid for:

1. **A crashed multi-row cycle loses everything after the first row.** The worker is a `claude -p` process fed this doc on stdin; when it dies, uncommitted work in the worktree is orphaned and the next cycle starts from a tree it did not build. One row per cycle bounds that loss to the row in flight.
2. **One row per cycle keeps each commit reviewable.** A commit carrying three unrelated root-cause fixes cannot be reverted for one of them, and its ledger entry cannot honestly state which test proves which claim.

If a row turns out to be two rows, ship the half that matches the filed acceptance and FILE the remainder as a new id (section 5). That is what RM-345 did when it shipped partial and spawned RM-366 (`ROADMAP.md:53`). "SHIPPED-PARTIAL by measurement, not by scope cut" is an honest verdict; "shipped" over a half-done row is not.

**2b. What this lane does NOT do.** Four headless lanes are all described as "work the backlog" and will otherwise fight over the same commits.

| | lane 5 (Research) | lane 7 (Repo) | lane 8 (True-Audit) | lane 10 (this lane) |
|---|---|---|---|---|
| unit of work | the SEARCH | the TREE | ONE FILE | ONE FILED ROW |
| verb | find, cite, file | restructure, relocate, delete | audit, rewrite, harden | execute, prove, ship |
| output | rows with acceptance | an outsider-clean repo | a hardened file | a pushed commit that closes a row |
| files new rows | YES, that is its job | incidental | incidental | only the RESIDUE of the row it shipped |
| picks its own subject | YES | YES | YES | **NO - the queue picks it** |

**You do not go hunting.** A defect you notice outside the row in flight is FILED with an id (section 5) and left alone; a queue lane that chases interesting greps stops being a drain and becomes a second research lane, and the queue then never empties. The one exception is section 6 step 3: sibling cases sharing the SAME root cause as the row you are shipping are IN scope and must be swept, because a fix that leaves its siblings is not a root-cause fix.

**2c. Read the filed row as a spec, not as a summary.** Every row carries a defect statement with `file:line` citations, an **ACCEPTANCE** clause, and a **Not already closed** line. The acceptance clause is the definition of done - meet it literally, and when it cannot be met literally (a zero-caller row, a frozen file, a live gate), say so explicitly and say what you did instead. Do not quietly substitute a weaker check. RM-347 is the worked example (4e). The citations were true when written: re-open every one before you rely on it.

### 3. The queue, in order

This is the INITIAL order. Take the first row that is still open and not gated.

| # | id | tier / lane | one-line |
|---|---|---|---|
| 1 | ~~RM-348~~ | **SHIPPED 2026-09-06** | closed by cycle 1 - LEDGER 1339, `c4657e8df`. Do not re-take it; see 4a, which stays as the record of what the row meant |
| 2 | RM-349 | Tier-1 | "Never raises" is false: the parse call sits outside the try |
| 3 | RM-350 | Tier-1 | a read route is issued as POST, and the test pins the bug rather than the contract |
| 4 | RM-351 | Tier-1 | unbounded response read at the single outbound chokepoint |
| 5 | RM-352 | Tier-1 | the DDragon version fetch omits the status check its own sibling method performs |
| 6 | RM-353 | Tier-1 | an unvalidated CDN string becomes a filesystem path segment, and `mkdir(parents=True)` follows it out of the cache root |
| 7 | RM-354 | Tier-1 | a 200-response bot wall destroys the good cached page and is stamped "ok" |
| 8 | RM-355 | Tier-1 | the crawl's inner loop has no bound of its own, so a non-ARAM stream never terminates |
| 9 | RM-356 | Tier-1 | `same_team` is unconditionally False in the non-default mode |
| 10 | RM-357 | Tier-1 | the base worker documents a pulse clock that contradicts both subclasses AND the consumer |
| 11 | RM-358 | Tier-0, LANE 7 | stale DEFAULT-OFF comment in a FROZEN file - **FILED, NOT PROPOSED FOR EDIT** (see 4b) |
| 12 | RM-359 | Tier-0/1, LANE 7 | a 168-line module with zero production callers whose rune path lacks its live twin's validation |
| 13 | RM-360 | Tier-0, LANE 7 | the authoritative id registry's next-free id is stale by six |
| 14 | RM-363 | Tier-1 | two unvalidated retention caps repeat the RM-161 shape, and one deletes the log a live writer holds open |
| 15 | RM-364 | Tier-1 | the prompt sanitizer's POPULATION - 14 wire-text builders that skip it (`BACKLOG.md:247`) |
| 16 | RM-365 | Tier-0, LANE 7 | `RC_LCU_POOL` DEFAULT-OFF prose stale in two sites (`BACKLOG.md:249`) |
| 17 | RM-367 | Tier-1 | the LIVE gameflow reader reports an EMPTY body as the phase `""` (`BACKLOG.md:245`) |
| 18 | RM-343 | Tier-1, LANE 7 | every lane WORKTREE materializes 1884 LF-normalized tracked files with CRLF on disk while `git status` reports the tree clean (`ROADMAP.md:51`, `BACKLOG.md:246`) |

Bodies for rows 1 through 14 are in `docs/_research_refill_2026-09-05.md` (headers at `:213`, `:248`, `:276`, `:306`, `:332`, `:363`, `:396`, `:435`, `:464`, `:494`, `:526`, `:555`, `:590`, `:718`), pointed at by `ROADMAP.md:54`. Bodies for rows 15 through 18 are in `ROADMAP.md` / `BACKLOG.md` at the lines above. RM-361 and RM-362 are deliberately absent - both SHIPPED (LEDGER 1335 and 1336). **RM-366 is absent and stays absent: see 4c.**

**Row 18 (RM-343) is directly relevant to THIS lane, because this lane runs in a worktree.** It is the inherited red behind section 12 trap 6: `tests/test_text_line_endings.py::test_no_normalized_tracked_file_has_crlf_on_disk` fails in `C:/rc-worktrees/rc-lane-queue` on a large set of files that no lane authored (measured at 1884 before the generated DS review mirror was removed from the repo, so re-measure rather than quoting that figure), worst-first the `data/daemon_slayer/{16.13.1,16.14.1,16.15.1,16.10.1}/scenarios.json` set (`data/daemon_slayer/16.15.1/scenarios.json` holds 114231 CRLF pairs in a worktree and 0 in the main tree). Its acceptance is to explain why `git worktree add` produces CRLF where the main-tree checkout does not - comparing the effective `core.autocrlf` / `core.eol` and the `.gitattributes` in force when each tree was materialized, noting `.git/config` is SHARED so a per-worktree override is not available and no fix may mutate the main tree's setting - then prove a FRESH `git worktree add` passes that single test with zero files reported. **Do NOT close it by re-materializing those paths inside a feature branch**, which cycle 48 deliberately declined; that is a lane-7 commit wearing a lane-10 hat and it would bury the row.

**THE TABLE ABOVE IS THE AUTHORITATIVE QUEUE WHILE IT LASTS. Do not re-derive over it, and never treat an `OPEN` grep as the census of what is left.** Fourteen of these eighteen rows carry NO `OPEN` marker anywhere in the tree: `grep -ohE "RM-[0-9]{2,3} OPEN" ROADMAP.md BACKLOG.md` matches 92 distinct ids and NOT ONE of RM-348..RM-360 or RM-363, whose only ROADMAP presence is the collapsed FILED pointer at `ROADMAP.md:54` and whose bodies live in `docs/_research_refill_2026-09-05.md`. A driver that re-derived at cycle 1 would therefore silently drop rows 1 through 14 and call the queue drained with fourteen rows unshipped. Measured 2026-09-05 by the adversarial gate that reviewed this doc, which is why the rule is written down rather than assumed.

Two consequences, both binding:

- **A row is DONE only when its id carries a closure record** - a `docs/LEDGER.md` entry, or a SHIPPED / CLOSED / struck line in `ROADMAP.md` or `BACKLOG.md`. **Never** because it failed to appear in an `OPEN` grep. Absence from that grep is a claim about the marker, not about the row (`feedback_empty_grep_is_a_claim_about_the_pattern`).
- **The re-derivation below kicks in ONLY after every row in the table above is closed by that test.** Until then it is dead text; running it early is the failure it exists to prevent.

**Once the table IS fully closed, re-derive the next rows yourself. The selection rule, stated so cycle 20 picks correctly with no operator present:**

1. Scan `ROADMAP.md` NOW (the bucket opens at `ROADMAP.md:36`) and `BACKLOG.md` for rows whose marker is `OPEN` - **and then scan the two places an open row hides with no marker at all**, because that is exactly how this doc's own queue became un-derivable: (a) every `docs/_research_refill_*.md` research-refill doc, whose row bodies carry an `ACCEPTANCE` clause and a `Not already closed` line but no status marker; (b) every `FILED` pointer line in `ROADMAP.md` (`ROADMAP.md:54` is the live example), which collapses a whole refill batch to one line and names the doc holding the bodies. A filed row's body does not live in `ROADMAP.md` and is not marked `OPEN`, so an `OPEN`-only scan cannot see it. Take the UNION of the three scans, then subtract every id with a closure record.
2. Drop anything gated: any row naming a FROZEN file from the `CLAUDE.md:41-46` list as the thing that must change, anything marked OPERATOR-GATED, and anything routed to `docs/LIVE_GAME_GATED_SYNC.md` (the live-gated set is NOT synthetically drainable - measured 2026-07-18 over all 124 rows, and substituting a headless proof for a live acceptance was its dominant failure).
3. Order what remains newest-filed first, by `RM-NN` descending, because the newest rows carry freshly-measured `file:line` citations and the oldest carry the most decayed ones.
4. Take the first. Record in the cycle report WHY it was first, so the next cycle can tell a deliberate pick from a drift.

### 4. Row fences. Each one already cost a run.

**4a. RM-348.** The backoff wait at `core/lcu_events.py:287-290` DOES `await asyncio.wait_for(self._stop.wait(), timeout=delay)` - the await itself is `:288`, wrapped by the `try` at `:287` and the `except (asyncio.TimeoutError, TimeoutError): pass` at `:289-290` - so **stop already works BETWEEN connections. Do NOT "fix" that path.** (This fence previously cited `:281-283` for that await and was wrong: `:281-283` is the preceding `if self._stop.is_set():` / `return` / `delay = DEFAULT_BACKOFF_SECONDS[` block. Corrected 2026-09-05 by the gate that reviewed this doc.) The defect is the idle CONNECTED read loop - `:293-294` checks `self._stop.is_set()` only AFTER a frame arrives, and `:267` `ping_interval=None` disables the keepalive that would otherwise unblock the async iterator. The second half of the row is separate and lives in the same function: `:269` sets `attempt = 0` on handshake completion rather than after a sustained session, so a socket that connects and instantly closes reconnects at the 1.0s floor forever and never reaches the 30.0s cap at `:59`. Both halves ship together or the row is partial and says so.

**4b. RM-358 is FILED, NOT PROPOSED FOR EDIT.** It is a stale comment in `lcu/lcu_client.py`, which is on the frozen list at `CLAUDE.md:42`. **Do not edit a frozen file to close it.** The `CLAUDE.md` frozen list governs; an edit to any entry on it requires an ADJUDICATING AGENT THAT DID NOT AUTHOR THE CHANGE, recorded in the slice, plus explicit operator approval, tests and CI green. Close what you can outside the frozen file (the row names a non-frozen sibling in `tests/test_lcu_pool.py:6`, and RM-365 names the non-frozen `game_reader/poller.py:336`), state plainly which half remains, and leave the frozen half open. A prior operator frozen-grant on that file exists on the record; it is context for an adjudicator, not permission.

**4c. RM-366 is OPERATOR-GATED. SKIP it. Never silently take it.** It cannot be executed without an edit to the frozen `lcu/lcu_client.py:191` give-up path (`BACKLOG.md:248` says so in the row itself). It is not in the section 3 queue and must not be re-added by a later re-derivation - step 2 of the selection rule drops it.

**4d. RM-367 carries a trap that inverts the obvious fix.** A FALSY phase is LOAD-BEARING in the runtime view router: `web/js/main.js:711` (`_VIEW.gameStarted === "champ-select" && !phase && live`, the s209 sticky-guard inference) and `:728` (`!phase && live && inGame`, the item-281 null-phase in-game promotion) both branch on it, and `"Unknown"` is truthy and matches no explicit `phase === ...` arm, so the one-line consistency fix silently disarms both. **`dashboard/view_router_state.py` is a TEST-ONLY MIRROR, not the consumer** - its own header at `:1-7` says it is not imported at runtime. Read the filed row's own fence at `BACKLOG.md:245` before touching anything.

**4e. RM-347 is SHIPPED (LEDGER 1337, `be7747fcb`, `ROADMAP.md:52`). Do not redo it.** Do not re-file its log level - failure logging was deliberately left at debug so a polling caller cannot spam a warning once per tick while the client is closed. Do not "unify" the three in-tree failure-value conventions (`lcu/lcu_pregame.py` now `None`, `lcu/lcu_postgame_collector.py:1034` `""`, `lcu/snapshot_shape.py:415-421` `"Unknown"`); consistency could not settle that choice and the consumer contract did. **Its second acceptance clause was met with consumer-contract tests, not a caller test, because `get_gameflow_phase` has ZERO in-repo callers** - the same shape as RM-346's three readers. That precedent is how a zero-caller row is closed honestly: pin the consumer's contract, say in the test docstring that these are not caller tests, and state that inventing a call path would prove nothing.

**4f. RM-360 (row 13) is ALREADY HALF-CLOSED by later work. Ship only the missing half.** Its body (`docs/_research_refill_2026-09-05.md:590-625`) quotes two values as evidence of drift, and BOTH quotes are now stale in the row's own favour: it reads `docs/DS_SWEEP_TRACKER.md:72` as `Next free id = **RM-337**` (that line now reads **RM-368**, updated 2026-09-05 by LEDGER 1337) and `ROADMAP.md:55` as `next free id RM-343` (that pointer has since moved - `:55` is now the LANE 10 wiring line, and the live next-free pointer is `ROADMAP.md:52`). So the row's FIRST acceptance clause - "the registry's next-free-id updated to the true value" - was satisfied by intervening sessions, not by this lane. **What remains is the GUARD half only**, and it is genuinely undone: `tests/test_rm_id_registry_drift.py` DOES NOT EXIST (measured 2026-09-05). Ship the test, state in the ledger that the data half was already true on arrival and that you verified it rather than redid it, and do not re-edit a tracker line that is already correct. **One trap in the guard itself:** the acceptance says the id named on that line must not appear as an ALLOCATED `RM-NN` in `ROADMAP.md`, `BACKLOG.md` or `docs/LEDGER.md` - written naively as "must not appear at all" it goes RED on day one, because RM-368 legitimately appears as next-free POINTER prose in `ROADMAP.md:52` and `docs/LEDGER.md:47`. Use the allocated-versus-pointer predicate from section 5, and mutation-test it by pointing the tracker at an id that IS allocated.

**4g. Never add a `Co-Authored-By: Claude` trailer, and never file its absence as a defect.** `.githooks/commit-msg:23-29` STRIPS it per operator policy 2026-06-03 (deletion, not rejection, which is why it reads as an authoring omission). Auditing this with a bare `grep -ci 'Co-Authored-By'` matches prose ABOUT the trailer; use an anchored predicate and read the message TAIL.

### 5. Ids

Next free id is **RM-370** as of 2026-09-06, pinned at `docs/DS_SWEEP_TRACKER.md:72` and again at the newest SHIPPED line in `ROADMAP.md`. `ROADMAP.md:14` names the tracker the authoritative registry. **RM-368 and RM-369 are both ALLOCATED** - RM-368 by another lane on 2026-09-05, RM-369 by queue cycle 1. The worked example below still reads RM-368 because it is the RECORD of one re-derivation, not a live answer; re-derive anyway, and note the lesson cycle 1 paid for: **RM-368 was free when that cycle started and was minted by a parallel lane while it worked, so re-derive AFTER `git fetch`, never from a pre-fetch tree.**

**That pointer is UNGUARDED and has been stale by six before, which is itself row RM-360.** Never mint from it on faith. Re-derive from the tree every time you file:

```
grep -rhoE "RM-[0-9]{2,3}" --include='*.md' --include='*.py' . | sort -t- -k2 -n | tail -3
```

**The rule is max ALLOCATED plus 1, and that is NOT the same as max OCCURRING plus 1** - the recipe above finds occurrences, and the highest occurrence today is the next-free POINTER itself. Run it now and it returns `RM-368` three times; taking "max plus 1" literally yields RM-369 and burns an id nobody used. An earlier draft of this section said RM-368 was next free and then gave a recipe answering RM-369, contradicting itself in eight lines.

**Allocated** means the id HEADS A FILED ROW BODY (`### RM-NNN (Row N) - ...` in a refill doc, `- **RM-NNN OPEN ...` in `ROADMAP.md` or `BACKLOG.md`) or CARRIES A STATUS MARKER (`OPEN`, `FILED`, `SHIPPED`, `CLOSED`, `DONE`, `REFUTED`). A bare mention is not allocation. The distinguishing check, run on each candidate from the tail before you accept it:

```
grep -rn "RM-368" --include='*.md' --include='*.py' .
```

Read every hit. If ALL of them are next-free pointer prose - `Next free id = **RM-368**`, `next free id RM-368` - the id heads no row and is FREE; take it. If ANY hit heads a row body or carries a status marker, it is allocated: step up and re-check the next id the same way. Measured 2026-09-05: outside this doc, RM-368 occurs in exactly five files - `docs/DS_SWEEP_TRACKER.md:72`, `docs/LEDGER.md:47`, `docs/ROADMAP_HISTORY.md:14`, `ROADMAP.md:52`, `WAKEUP_NOTES.md:18` - and every one of them is next-free pointer prose, heading no row body and carrying no status marker. So **RM-368 IS the next free id** and RM-369 is not.

When the tracker and `ROADMAP.md` disagree, believe the HIGHER one, then re-derive anyway. When you consume an id, update the tracker line AND the `ROADMAP.md` pointer in the SAME commit - the documented way this pointer goes stale is a batch moving only one of the two.

### 6. Execution contract, per cycle

1. **TDD, order not negotiable** (`CLAUDE.md` "TDD First", plus the `root-cause-fix` skill): the failing regression or characterization test comes FIRST, then the fix, then the suite. A test written after the fix proves the fix ran, not that the bug existed. A finding without a red test is an opinion.
2. **Mutation-test every regression test you write.** Break the production line it guards, confirm RED, restore. A guard on a non-default call path is UNTESTED - if every test passes the default, deleting the guard stays green.
3. **Root-cause first, then sweep the siblings.** Grep for other modules, other modes and duplicate code paths sharing the same root cause, and add a test per case, BEFORE calling it fixed. The measured failure is a first fix that is too narrow (item 208 missed Golden Spatula and a duplicate build path, forcing the item-213 cleanup). A pattern-scoped sweep is not a root-cause sweep.
4. **Tier the verification** (R5-R7). **Most queue rows are Tier-1:** `py_compile` plus that module's tests. Tier-0 cosmetic (doc, comment, string, non-runtime constant): Edit plus `py_compile` if `.py`. **Tier-2 is schema / engine / scorer / item-effect / `ENGINE_VERSION`** and pays the full dual suite plus the DS `:8860` restart. Say which tier you paid and why.
5. **Backfill.** State what the ALREADY-BAD state was and whether a backfill was needed. Per `CLAUDE.md` "Data Fixes", a fix that only prevents future occurrences leaves the existing bad rows wrong. Generalize it: fix a non-atomic writer, then repair the half-written files it already left; fix a validator, then re-run it over the existing corpus.
6. **Verifier gate before any "done" claim.** An independent read-only `verifier` subagent (`.claude/agents/verifier.md`, no Edit or Write) re-runs the suite fresh, confirms every cited file exists on disk, and returns CONFIRM or REFUTE, **defaulting to REFUTED when uncertain**. The agent that produced the change never grades it, and agreement between two agents is not evidence.
7. **Atomic writes only** for anything polled: `tmp.write_text(...); tmp.replace(target)`, or better, the canonical helpers in `core/polled_json.py`. **`py_compile` before any restart** - syntax errors crash silently under `pythonw.exe`. Restart via `echo restart > restart_trigger.txt`, then confirm a NEW `pid` with `alive=true` and `last_reload_ok=true` in `ops/runtime/health.json`. Asset-only edits under `web/{js,css}/panels/*` need no restart (ADR-008).
8. **Never surface a raw API error string** - credit or balance exhaustion, a 400, a rate limit, a thinking-block error - in the coach UI or any user-facing dashboard panel (`CLAUDE.md` "Error Handling"). Catch it, render a friendly degraded-mode message, log the raw error to `logs/`. The pattern already exists in the tree; imitate it rather than inventing a new one, and check the panel still RENDERS when degraded instead of collapsing. Several queue rows touch HTTP and cache paths where this is the natural place to get it wrong.
9. **Python conventions.** A new required field on a dataclass is APPENDED at the END with a default; a mid-class insertion breaks every existing positional construction (item 216 broke 41 of them). Adding a required field mid-class is not a refactor, it is a Tier-2 blast radius wearing a Tier-1 hat.
10. **Third-party lift is a hard stop.** Before lifting ANYTHING from an external repo, check the license and SAY what it is - a repo can contradict itself between `LICENSE` and its manifest, a LICENSE file can name NOBODY, and the person who cleared it may not own it. GPL and copyleft stay DO-NOT-VENDOR regardless of verbal clearance. The always-legal path is the one RC already uses: re-implement the mechanic from the observed behaviour. Techniques and protocol facts are not copyrightable; source is.

### 7. Suites - from the REPO ROOT only

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest tests -q -n 8
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest agents/daemon_slayer/tests -q
```

- **BOTH suites, EVERY cycle, before you push - not only at Tier-2.** The tiered rule in `CLAUDE.md` governs how much you verify while you WORK; this lane's push gate is separate and is not negotiable, because a push lands on `main` unattended. The pair above is exactly what `.github/workflows/ci.yml:504-505` runs, so a local green is the same evidence CI would give you, roughly 40 minutes sooner. Report both counts, observed this run.
- **Never `pytest .`.** It has DELETED the live supervisor lock (`reference_pytest_root_deletes_supervisor_lock`), and `CLAUDE.md:208` bans it by name.
- **Never run a full suite while a verifier or a slice agent is running one.** Parallel slices each running the full suite OOM the box, and it presents as an API error rather than as memory pressure.
- **Assert on the summary line AND the exit code.** A crashed xdist run leaves a truncated log with no summary, and `grep -c FAILED` over it returns 0, which reads exactly like green. Write pytest output to a FILE and read the file; raw stdout is not ground truth when the pipe wedges.
- **Never run the DS suite from `agents/daemon_slayer/`.** Measured 2026-07-26: 13 pure CWD artifacts whose failure names read like real regressions (`test_registry_still_125_champions`, `test_module_is_ascii`). Do not start "fixing" a data file.
- Report the counts YOU observed THIS run. Never carry a prior or subagent-reported count forward.

### 8. Shipping. This is NEW for this lane - read it exactly.

The loop must not accumulate unshipped rows, so a cycle ends on `main` whenever it can.

1. **Commit on `lane/queue`.** Stage only the files you authored; **never `git add -A`**. Never amend. Message via `git commit -F <tmpfile>` (Write the file, ASCII-only) or a single-quoted here-string - **never a double-quoted here-string and never a piped string** (BOM plus ANSI-mangle risk, the same root cause as the no-em-dash rule).
2. `git fetch origin`, then rebase onto `origin/main`, then **re-run the tier's tests** on the rebased tree. A rebase can land your change on top of someone else's and a suite that passed pre-rebase proves nothing about the merged result.
3. `git push origin HEAD:refs/heads/main`. **Fast-forward only. NEVER `--force`.**
4. **If the push is rejected**, re-fetch and rebase ONCE more. If it is still rejected, push `lane/queue` instead, say so plainly in the cycle report with the reason, and continue to the next cycle. Do not loop on a contested ref.

**Why straight to `main`:** `.github/workflows/ci.yml:8-9` fires on push to `main` only, plus pull requests to `main` (`:26-27`) and the nightly schedule (`:30-31`). **Lane branches get no CI at all**, so a row parked on `lane/queue` is a row whose acceptance was never independently checked.

**NEVER write into the main working tree `C:\Riot Commander`.** Pushing a ref is not touching that tree - the push goes to the remote, and the main tree updates only when a human or the supervisor pulls. The single exception is the drain sentinel in section 11, which is a gitignored control-plane file.

### 9. CI acceptance

Read `jobs[].steps[]`, never the run conclusion:

```
gh run list --limit 6
gh run view <id> --json jobs
```

The step that must reach `success` is named **`full dual suite (RM-119 - push CI now gates the whole tree)`** (`.github/workflows/ci.yml:419`, inside the `check` job at `:142`; its command is `pytest tests/ agents/daemon_slayer/tests/` at `:504-505`).

- **DO NOT WAIT FOR CI, AND DO NOT TRIGGER A RUN. THE DRIVER OWNS THIS NOW** (`ops/loop/queue_loop.py`, `wait_for_ci`). Push, wrap, exit. The driver then resolves `origin/main`, ensures a run exists for it, waits for it to complete, reads the `check` job's dual-suite step, and writes the verdict into your cycle's own row in `ops/loop/reports/queue_loop.jsonl`. A `failure` stops the whole loop rather than pushing the next row onto a red `main`.
- **Why this stopped being your job, stated so nobody moves it back into prose:** it was your job for exactly six cycles and it did not hold. Cycles 2 and 3 blocked as instructed (102.7 and 113.3 minutes, both green), but cycles 4, 5 and 6 ran 45, 24.2 and 38.5 minutes - each shorter than a CI run - so those workers exited before their run finished and the next cycle's dispatch cancelled it, three consecutively. **An instruction a worker can rationalize past is not a mechanism.** The driver cannot rationalize: it is the only thing that starts the next cycle, so while it waits, nothing exists that could cancel the run.
- **What you still owe:** the LOCAL dual suite before you push (section 7), and an honest ledger line saying the CI verdict is recorded by the driver, not observed by you. Never claim a green you did not read.
- The rest of this section is REFERENCE for reading a verdict by hand when an operator asks, not a per-cycle step.
- **(historical, superseded above) BLOCK UNTIL YOUR RUN COMPLETES.** This is the whole fix, and the reason is arithmetic: a `ci` run takes roughly 45 minutes, a cycle takes roughly 26, and `cancel-in-progress` is keyed on a group that every cycle re-enters - so whichever group you use, cycle N+1 cancels cycle N's run. MEASURED 2026-09-05/06, five runs in a row: three `push` runs cancelled by the following push, then a `workflow_dispatch` run (34012397811) cancelled 23 minutes later by the NEXT CYCLE'S dispatch (34013317217). Moving groups does not help; only serializing does. Because cycles are serial, a worker that WAITS is a worker nothing can supersede. Poll `gh run view <id> --json status,conclusion` every 60s for **up to 90 minutes**. If it still gets cancelled, re-dispatch ONCE and wait again. **90, not 60, and the number is measured rather than picked:** RM-370 timed a real wait at **67 minutes**, so the first budget written here was under-set and a worker obeying it would have abandoned a run that was about to pass. The driver's hard cycle kill was raised to 4 hours in the same change - a 90-minute block plus one 90-minute re-dispatch plus the work itself does not fit inside a 90-minute cycle timeout, and a legitimate wait must never be what trips the kill. If that is also inconclusive, say so plainly and cite the LOCAL dual suite as the gate - never dress a cancelled run up as green.
- **The LOCAL dual suite is the pre-push gate, and it is not a lesser one:** `.github/workflows/ci.yml:504-505` runs `pytest tests/ agents/daemon_slayer/tests/`, which is the same command section 7 gives you. Run BOTH suites from the repo root before you push, every cycle, whatever the tier - a Tier-1 row that only ran its own module's tests can still redden the tree, and finding that out locally costs 6 minutes against 45 spent waiting for CI to say it.
- **YOUR PUSH RUN WILL BE CANCELLED BY THE NEXT CYCLE, SO DO NOT WAIT ON IT. MEASURED 2026-09-05, the first night this lane ran.** `ci.yml:38-40` sets `cancel-in-progress: true` on the group `${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}`, a `ci` run takes roughly 45 minutes, and a cycle takes roughly 26 - so every push run on `main` was cancelled by the following cycle's push, three in a row, and the acceptance was unsatisfiable as originally written. **The fix is in that same concurrency key: `event_name` is part of the group, so a `workflow_dispatch` run sits in a DIFFERENT group and a later push cannot touch it.** After your push, trigger one and watch THAT run:

```
gh workflow run ci.yml --ref main
sleep 20 && gh run list --workflow=ci.yml --event=workflow_dispatch --limit 3 --json databaseId,headSha,status
gh run view <id> --json jobs
```

  Only another `workflow_dispatch` can supersede it, and the next one is a cycle away because cycles are serial. Confirm the run's `headSha` actually contains your commit before you cite it - `gh workflow run` takes a BRANCH ref, so it builds `main` as of trigger time, which is your commit or a descendant of it. A dispatch also runs `nightly-full-suite` (`:44`), so expect two heavy jobs, and read the `check` job's step, not the nightly's.
- **Never cite the run conclusion.** `gh run watch --exit-status` returns 0 on CANCELLED, and a superseded run and a job timeout both report `cancelled`. A cancelled run is NOT a red - it usually means a newer push superseded it - but it is not a green either, and it may never be cited as acceptance.
- **A green run may have SKIPPED the job you care about.** `check` carries `if: github.event_name != 'schedule'` (`:143`) and `nightly-full-suite` carries the complementary `if` (`:44`), so the scheduled nightly never runs `check`. Open `jobs[].steps[]` and confirm the named step actually ran.
- **A docs-only push runs no `ci.yml` at all** - `paths-ignore: '**/*.md'` at `:24-25` and `:28-29`. Its complement is `.github/workflows/docs-guards.yml`, pinned by `tests/test_ci_docs_guard_coverage.py`. **A push carrying both code and docs commits DOES run `ci.yml`**, which is the normal shape of a queue cycle, so the docs half is covered for free. A docs-only cycle (a recall-closed row, a Tier-0 prose fix) cannot prove itself through `ci.yml`; check `docs-guards` instead and say which one you read.

### 10. Docs, per cycle

- **`docs/LEDGER.md`** gets the long entry, newest-first at the TOP, numbered from the current head (LEDGER 1337 sits at `docs/LEDGER.md:47`). Cite the PUSHED sha. Write the defect, the root cause, the sibling sweep result, the tests by name, the mutation-test result, the tier paid, the backfill answer, the verifier verdict, and the exact suite counts you observed this run.
- **`ROADMAP.md` gets a SHORT line.** It is at **89.5 percent of its 81920-byte budget** (`tools/drift_guard.py:57` `DOC_BUDGETS`, `:58` `BUDGET_WARN_PCT = 90.0`), so the guard warns at 90. **Write the ledger long and the roadmap short.** If the file crosses 90 percent, relocate a CLOSED body verbatim to `docs/ROADMAP_HISTORY.md` and leave a pointer - that is exactly what `ROADMAP.md:50` and `:52` already did.
- **`BACKLOG.md`** for rows filed there (RM-364 / RM-365 / RM-367 and anything you newly file).
- **NEVER append to `CLAUDE.md`** - CI size-budgeted under 60KB, touched only for rule, frozen-list or Settled changes.
- Then `python tools/perseus_sync.py` (idempotent; `--verify` checks coverage). The vault is a MIRROR, never the source of truth.

### 11. Ending a cycle, and ending the loop

**Every cycle ends by exiting after one row.** That is not an early return; it is the contract.

**The drain sentinel.** If NO open, non-gated row remains after applying the section 3 selection rule, write:

```
C:\Riot Commander\ops\loop\control\lanes\QUEUE_DRAINED
```

one line, the ISO timestamp and the reason, then exit. **This is the ONLY write into the main tree this lane may ever make.** It is legal because `ops/loop/control/` is gitignored (`.gitignore:284`, confirmed by `git check-ignore`) and is the loop's control plane, not source. It is what stops the driver.

**Stop files, checked at CYCLE START, before picking a row.** If either exists, wrap immediately without starting a row:

- `C:\Riot Commander\ops\loop\control\STOP` - the shared loop stop, already honoured across `ops/loop/loop_controller.py:828`, `:842`, `:1086` and `ops/loop/claude_stub.py:76`.
- `C:\Riot Commander\ops\loop\control\lanes\QUEUE_STOP` - this lane's own.

An operator message mid-cycle is an interrupt: finish the in-flight row, never abandon a half-applied fix, then wrap.

**Wrap checklist, in order:** fresh suites from the repo root for the tier you paid; `-m ruff check .` (F541 is the recurring CI killer, and the BLE ratchet flags any NEW bare `except Exception`) plus `-m py_compile` on every touched `.py`; ASCII sweep of every authored line; runtime verification if the slice touched runtime code; backfill statement; verifier gate; commit, rebase, push (section 8); CI read (section 9); docs (section 10); `git status` clean and `git stash list` empty.

### 12. Measured traps this lane WILL hit

1. **A filed row is a hypothesis until re-probed.** Check its AGE first, then re-open every cited `file:line` yourself. Every filed count that was re-derived turned out wrong at least once, and two rows in one run refuted their own authors. The row's citations were true when written and the tree has moved.
2. **A row can be closed by SUBSTITUTION without anyone noticing.** When a row asks whether something RENDERS or SENDS or UPDATES, the compute half is always available headless and is always the wrong question. That substitution was the dominant kill across all 124 gated rows on 2026-07-18.
3. **A test-only mirror is not the consumer** (`dashboard/view_router_state.py:1-7` is the live example, and RM-367 turns on it). A module can be a faithful, current, maintained mirror of live logic and still be zero-consumer code. A scan is not a reachability probe: open the call path.
4. **An empty grep is a claim about your PATTERN.** Four layers bite here: data delimiters, shell quoting, count semantics, and UTF-16 bytes. Prove the pattern matches something before concluding it matches nothing.
5. **`node --check` is BLIND on `web/js`** - every module there opens with `import`, and on an import-leading file it returns exit 0 on a duplicate `const`. The gate is `tests/test_web_js_esm_parse.py`, a real ES-module parse. An undefined CSS custom property likewise fails SILENTLY and passes every source grep for the token name.
6. **`Path.write_text` rewrites LF as CRLF on Windows** and `read_text` hides it on the way back, so byte counts and digests disagree with disk. Write BYTES with an explicit newline policy when a count or a hash matters. Related and already filed: RM-343 records that every lane worktree materializes 1884 LF-normalized tracked files with CRLF while `git status` reports clean, so `tests/test_text_line_endings.py` is an INHERITED red each lane must re-measure to clear itself - do not close it by re-materializing 1884 paths inside a feature branch, and do not report it as your regression.
7. **The tool pipe can replay stale results.** Ground truth when it wedges is `git status`, Edit success or failure, pytest written to a FILE, and a DONE-exit sentinel - not raw stdout. Item 238 hit a severe replay: a fabricated "1 failed", a non-existent dtype, a pre-bump `/health`, invented filenames.
8. **Proving your change happened is not proving it matters.** Three inert fixes shipped in one run. Diff the CONSUMER's artifact, not only the file you edited.
9. **A verifier needs a FROZEN tree** - and so does your own suite run. A backgrounded pytest that straddles a docs edit reports on a tree that no longer exists. Finish editing, THEN dispatch the verifier, THEN leave the tree alone until it returns.
10. **A caveat said in chat is not a caveat in the artifact.** A qualification you state while working and omit from the ledger entry did not survive the cycle - the ledger is the only thing the next cycle reads.
11. **A guarded doc LINE is not a guarded NUMBER.** Read a drift guard's own docstring before believing it pins what you assume: `tests/test_docs_daemon_slayer_drift.py` pins `ENGINE_VERSION`, `patch` and the route list in the DS banner and says in as many words that it deliberately does NOT pin the `def test_` counts. That is how the banner sat at 10594 against a true 10578. Measure suite counts with `--collect-only -q`, never quote a doc.
12. **Filed counts are hypotheses.** Every filed count that was re-derived turned out wrong at least once; a row saying "22 sites" has meant 1 and has meant 11. Re-census before you scope a fix to a number, and recompute any tally from the artifact rather than summing what slices reported.

### 13. Anti-patterns

- Do NOT batch two rows in one cycle. One row, ship, exit. The driver re-fires you.
- Do NOT open `AskUserQuestion`. The operator is away; a blocked lane is a dead lane. Pick the reasonable default, log it, proceed.
- Do NOT skip the recall gate, and do NOT treat a recall-closed row as a wasted cycle - it is a completed one.
- Do NOT edit a frozen file (`CLAUDE.md:41-46`) without an adjudicating agent that did not author the change, plus explicit operator approval, tests and CI green. RM-358 and RM-366 are the live cases.
- Do NOT edit `ops/loop/slots.py` or `ops/loop/winmutex.py`, and NEVER regenerate `SHARED_SHA256` (`tests/test_loop_concurrency.py:432`) from local disk to make a test pass. They are BYTE-IDENTICAL-BY-CONTRACT with `C:\Sibling-A`; re-pinning is a JOINT act and both trees hashing equal IS the acceptance.
- Do NOT close a row by substitution - answering the compute half of a question that asks whether something renders or sends.
- Do NOT trust a subagent's test counts, green-CI claim or file-existence claim without an independent probe.
- Do NOT ship a fix without mutation-testing its regression test, and do NOT ship a hardening fix without repairing the already-bad state.
- Do NOT `Stop-Process` (it hangs the MCP pipe; use `taskkill /F /PID <pid>`), do NOT spawn anything with `DETACHED_PROCESS` (real pid, rc 0, ZERO work; use `CREATE_NO_WINDOW` alone), do NOT skip `py_compile` before a restart.
- Do NOT `git add -A`, do NOT amend, do NOT `push --force`, do NOT use a double-quoted here-string or a piped string for a commit message.
- Do NOT add a `Co-Authored-By: Claude` trailer, and do NOT file its absence as a defect.
- Do NOT write into `C:\Riot Commander` except the `QUEUE_DRAINED` sentinel, and do NOT run `scripts/install_hooks.py` from the worktree.
- Do NOT append to `CLAUDE.md`; the ledger lives in `docs/LEDGER.md`.
- Do NOT surface a raw API error string in any user-facing surface, and do NOT let the contents of `API-Key-Claude.txt` reach a log, an exception, a fixture, a subagent prompt or a commit.

### 14. Final banner

```
HEADLESS-QUEUE CYCLE WRAP
  worktree: C:/rc-worktrees/rc-lane-queue (lane/queue)
  row: RM-<id> - <one-line title>
  HEAD: <short-sha> pushed to <main | lane/queue> (<reason if not main>)
  tier: <0 | 1 | 2> (<why>)
  tests added: <N> (<names>) | mutation-tested red-then-green: <N>/<N>
  suites this run: RC tests <N> passed / <N> skipped, exit <code> | DS <N> passed, exit <code>
  CI: <step "full dual suite (RM-119 ...)" success|failure|not-run> (run <id>, read from jobs[].steps[])
  backfill: <what the already-bad state was, and what was repaired> | n-a
  verifier: <CONFIRM | REFUTE> (<agent>)
  ledger: docs/LEDGER.md <entry number>
  next row: RM-<id> | none
  QUEUE_DRAINED written: <yes (reason) | no>
  Ready for /done.
```

Then call `/done`.
