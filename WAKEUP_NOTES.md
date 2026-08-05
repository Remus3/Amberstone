# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-05a - lane 8 cycle 7: the deploy worker wrote wherever it was told

`ops/rc_transactional_deploy.py` had **zero test references** and joined every
request-supplied path onto its root with no containment check. Committed
`0647f3da` on `lane/true-audit`; LEDGER 1198; **branch is READY, not merged** -
per the lane fence, lanes 7 and 8 ship last and the merge is the merger's call.

- **The lane worktree did not exist at pre-flight.** `C:\rc-worktrees\` was empty
  and there was no `lane/true-audit` branch, so the launcher had never fired for
  this lane. Created it exactly as `ops/loop/lane_launcher.ensure_worktree`
  (`:180-190`) would rather than editing the main tree. Main tree confirmed clean
  and untouched at the end.
- **Proven, not read:** the verifier ran the OLD and NEW modules against the same
  hostile request. Old returned `phase=health_check` **having already written the
  file outside `project_root`** - it failed later, after the write. New returns
  `phase=validate` and writes nothing. On Windows `Path("C:/a") / Path("C:/b")`
  is `C:\b`, so an absolute component discards the root entirely.
- **A declared control that did not exist.** `rc_supervisor.py:29` documents that
  rollback excludes `API-Key-Claude.txt`. The deploy script named that file in a
  local `api_key` variable it never read. A grep for the exclusion passes; the
  exclusion is not there. Worth carrying: **a variable holding the right value is
  not an implementation, and it greps identically to one.**
- **A CRLF file makes a mutation silently no-op.** Two mutants "survived" the
  first pass; one was real (a test asserting only that something failed, over a
  guard whose absence changed only the diagnosis) and one was a harness artifact -
  a multi-line anchor containing `\n` never matches a CRLF file, so the mutation
  applies to nothing and reads as GREEN. **Assert the anchor is present before
  believing a surviving mutant.** Both were closed; 9 of 9 guards now die.
- **No restart makes this live.** The supervisor launches the file by absolute
  path from `C:\Riot Commander` (`ops/rc_config.json:9`), so `restart_trigger.txt`
  deploys nothing here - only the merge does. Item 1179 in reverse, caught before
  shipping rather than after.
- **RM-160 filed** (BACKLOG, Reliability / hardening): the drop directory has no
  producer and no ACL. Containment is now the only control standing on it.

---

# 2026-08-04j - headless run 2026-08-04-01: 6 slices, 3 refutations, 1 measured dead end

The run's real output is not the six merges - it is that **every one of the three
refutations was invisible to the slice's own passing suite**. Keep the verifier gate
as the default; this run is the evidence for why it is not optional.

- **S2 (RM-152)** ran 13 + 10380 + 102 tests green and honestly reported ONE suite it
  could not finish under box contention. That unrun suite held a deterministic 7-test
  auth regression. `_read_body_deadlined` did an unguarded `sock = self.connection`;
  the auth harness builds a socketless handler; the `AttributeError` fell into a broad
  `except` and answered **400 before the token check**, because the body read precedes
  the auth gate. An unrun gate is not neutral - it is where the bug is.
- **S3 (RM-153)** self-mutated 8 times and self-caught TWO vacuous guards, then shipped
  a THIRD inside the test protecting its own headline claim: a spy that signalled by
  RAISING, into a call site wrapped in `except Exception`. `AssertionError` IS an
  `Exception`, so it passed both ways. Finding the class once does not inoculate you.
- **S9 (claim gate)** passed 32 own tests, the full suite, and a genuine mutation probe
  (8/8 vs a naive rule's 1/8) while having SILENCED 16 laundering phrases the unmodified
  gate caught. Beating a deliberately-weak alternative is not soundness.

**Four rows said something untrue as filed.** RM-152's "`_proxy_to_supervisor` STREAMS"
(it buffers - `body = r.read()`, docstring self-contradictory in one sentence).
RM-153's duplicate-retention guess (2698 of 3123 timelines, 86.39 pct, are in NEITHER
`rewind_history` nor the `.rofl` archive - near-disjoint, so eviction destroys the only
copy). The Haiku charter's `dashboard/_champ_select.py` call site (none since
2026-06-06). And a recon's "16 of 89 responses intact" - **all 89 were log-clipped at
600 chars**, declared lengths 1113-2029, ZERO at or under 600, so `both = 0` was
substantially self-inflicted at write time rather than purely live-gated.

**Filed:** RM-158 - `laning_scenarios_arena.json` is SHA-256 IDENTICAL to the SR table
over 66,961,516 bytes; distinct real files differing only in the header `mode` and a
5-second `generated_at`, so a GENERATION bug, and every Arena number read off it was an
SR number. RM-155 - the Lane A gate still FAILS at 0.4887 with a base-rate census
proving zero mutual information, so the deferred ~190 MB/mode regen buys nothing.
**RM-159 CLOSED as a dead end** - two attempts, 16 then 28 bypasses, evasion by one-word
paraphrase (`couldn't`, `ought not`, `by happenstance`); structurally the gate audits
prose the agent itself writes, so any prose-level inference is gameable. Keep it strict.
Both refuted commits are TAGGED `evidence/rm-159-attempt-*` so the citations survive
worktree cleanup - the exact decay the LEDGER preamble documents at ~50 pct pre-2026-07.

**Environment facts that will otherwise cost a session.** The suite count is NOT stable:
18206-18351 passed across near-identical trees, 0-3 failures with DISJOINT failing sets -
check disjointness, not isolation, before calling a regression. Five concurrent pytest
processes DEADLOCK (byte-identical worker CPU over 10 min); `-n 4 --timeout=300` is the
safe recipe. **`tests/daemon_slayer` does not exist**, so `pytest tests/daemon_slayer`
exits 5 collecting nothing and reads as green. `docs-guards` triggers only on `**/*.md`
plus three named files, so a failure caused by a `.py` module cannot be re-tested by the
commit that fixes it - it needed a manual `workflow_dispatch`.

Gates run by the merger rather than inherited: RC 18351 passed / 0 failed, DS 10380
passed / 83 skipped / 6746 subtests from the repo root, RC restarted healthy,
`/metrics` scrape 0.022s with `rc_riot_api_cache_over_cap` already reading 1.

---

# 2026-08-04i - orchestrated 3-slice pass: RM-117 retention, RM-118 shields, RM-36 Ezreal (ENGINE 1.275.0)

Operator asked why open items were running one at a time instead of orchestrated
multi-agent. Answer: serial was drift, not policy - CLAUDE.md "Session Default" and
memory `feedback_standing_five_item_parallel_loop` both make orchestrated the baseline.
The exacting next-session prompt carries CONTENT, not cardinality. Ran the pass to prove it.

SHIPPED - two commits, both pushed (`9907dca3..b510ce20`):
- `1772c8d5` RM-117 (ii) `core/data_retention.py`, 4 classes, report-first. NOTHING DELETED.
  RM-117 (iv) closed as STALE (fixed by `baecb54b` 68 min after filing, never recorded).
- `b510ce20` merge, ENGINE 1.274.0 -> 1.275.0: RM-118 five per-item shield seams reach
  `/ehp` (exposure only, `ehp.py` untouched); RM-36 AD-axis dual-scaling split credit,
  Ezreal 0.0 -> 14.1067.

THE THREE FINDINGS THAT MATTER MORE THAN THE CODE:
1. Probing killed 2 of 5 proposed rows BEFORE any build. Filed rows are suspect until probed.
2. RM-118 was filed as "10 seams declined by design". An adversarial pass tasked with
   REFUTING that found 5 were live headless debt - their reason conflated route EXPOSURE
   with a DEFAULT FLIP. An operator-gated live flip blocks ONLY the flip. My own two kills
   were BOTH refuted by that pass; the reasoning I used to close RM-117 (iv) was vacuous
   even though the conclusion held.
3. MERGE HAZARD unique to parallel work: both DS slices recomputed the parity debt ledger
   against a baseline the other invalidated (54 vs 60; truth is 55). Two individually
   correct numbers, jointly wrong. Take the count by PARSING THE DICT.

DO NOT REDO:
- RM-35..RM-48 is CLOSED, all 14 resolved, narrative relocated to `docs/ROADMAP_HISTORY.md`.
  Do not re-open the roster.
- RM-117 (iv) is closed. `skipped: []` and `accounts_per_cohort: 14` are NOT evidence
  about MASTER - both traps are recorded on the ROADMAP row.
- The 5 seams remaining in `STRANDED_TODAY` are the s232 operator-CLOSED arc. Genuinely
  declined. `assume_lifeline_shield` is one of them despite the name.
- Neither new flag's default-ON flip is proposed. RM-36's rides G2-46 (blocked on RM-98).

FLAGGED, NOT FIXED: `tools/ship-batch.md` says "about 14 files" assert the ENGINE pin.
Real number is 125 files / 146 literals. Anyone trusting it ships a bump with ~110 red
tests and assumes breakage. Worth a one-line correction next session.

OPERATOR DECISION PENDING: 3.72 GB of `rewind_history.db` backups (11d/16d, zero readers)
plus 24.6 MB tier-2 and 137 MB tier-3. Reported, deliberately not deleted.
