# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-06, automatic via `scripts/wakeup_prune.py --keep 3` (relocated lane 8 cycle 8 `2026-08-05b`; newest 3 = headless run 2026-08-06-01 `2026-08-06a` + lane 8 cycle 10 `2026-08-05d` + lane 8 cycle 9 `2026-08-05c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-06a - headless run 2026-08-06-01: four fixes, and three of them mask or measure something bigger than themselves

Six merges `de5b5488..e8802e21` (`a8515a98`, `71f172aa`, `eba815e5`, `c5f1e4c8`,
`8f417bc3`, `e8802e21`) plus this docs commit. LEDGER 1202-1206; six rows filed
RM-163 .. RM-168.

- **CI IS OWED FOR EVERY SHA IN THIS RUN AND IT IS NOT A REPO FAULT.** GitHub
  Actions was in a MAJOR OUTAGE from 2026-08-06 15:22:49 UTC, so every push
  created ZERO workflow runs and `gh run list` shows only the previous day -
  which reads exactly like a broken trigger. Ruled out by probe: Actions
  enabled, all 3 workflows `state=active`, `ci.yml` `paths-ignore` is
  `**/*.md` ONLY while every push carried `.py`, commits ARE on GitHub. NOT
  ruled out: **billing** (the local `gh` token lacks the `user` scope the usage
  endpoint needs). A manual `gh workflow run` DID create run `31127029404`, so
  the failure is push-event DELIVERY, not run creation. **Do not write "CI
  green" anywhere for these shas** - every merge passed a LOCAL gate only.
- **RM-158's root cause was an unregistered dict key, and the corruption is
  wider than the row said.** `core/lead_projection.py` registered gold-income
  rates for SR and ARAM only, so `gold_income_per_min("ARENA")` fell through to
  a default byte-identical to SR's 450.0 - and at schema v3 that was ARENA's
  LAST mode-differentiating input, which is why the output was a byte-COPY
  rather than merely similar. **BOTH shipped arena tables are SR copies**
  (16.12.1 `cec62070b61e7c35` as well as 16.13.1 `22982424e69c42cc`, hashes
  re-derived independently). The fix registers the row AND makes `main()`
  REFUSE an unregistered mode, so the next one fails loudly. **The DATA half is
  still open:** regen both, and 1,148 `mode=arena` rows in
  `data/hz_choice_shadow.jsonl` are SR measurements labelled arena - drop or
  relabel, never average.
- **The obvious Lane B improvement was MEASURED AND REJECTED, and that is the
  substantive half.** `sort_by="efficiency"` as the build ordering metric
  changed 52 of 60 cells over 15 champions x 4 comp archetypes and pulled
  Doran's Helm / Doran's Bow / Guardian's Blade into slots 3-5 of the final six.
  It DEGRADES the tables. Shipped instead: the starter-tier invariant the tables
  held only by ACCIDENT, now pinned (`Lane` tag AND gold < 1000 - and the
  ceiling sits in a provably EMPTY band: no Lane item between 950g and 2500g).
- **Lane B's real blocker is a CONSUMER, not data.** The HZ-B1 comp-archetype
  table is the largest and richest of three families and has ZERO PRODUCTION
  CONSUMERS - definition plus 5 test call sites, nothing under `tools/` or
  `ops/audit/`. So the richest precomputed build data RC holds is on no path a
  coach reads. Filed RM-164. Coverage being full and machine-guarded told us
  nothing about whether anything READS it.
- **A cache that fixes a latency number can hide the cause.** `/api/last-match`
  went 0.475s cold -> 0.0078s cached, but 289ms of 291ms of the build was ONE
  urlopen, because `core/riot_api.py:520-522` stores a result only
  `if data is not None`. A `None` is never cached, so a match Riot has no
  timeline for refires forever - and `None` is the NORMAL case (event modes
  return empty by design). Filed RM-163, highest-value open non-gated row.
  Cold is the number a real fix moves.
- **The instrument was calibrated on fake data.** Tests were driving the REAL
  cost tracker: 13,141 synthetic calls across 40 of 84 day-files. The
  consequence, not the row count, is the finding -
  `tools/cost_health_watchdog.py`'s trailing-median baseline read $0.039424
  against a true $0.300906, **7.63x low and composed ENTIRELY of test rows**.
  Prevention is an autouse conftest fixture; the backfill filters PER BUCKET,
  never per file, because a day-file mixes real and synthetic rows.
- **Two negatives held honestly.** The `recent_matches.json` zero-`by_gate`
  producer stays UNIDENTIFIED - the first attribution was REFUTED by
  measurement and no test in `tests/` calls `save_match` at all. And a negative
  control on the conftest fixture was DECLINED on purpose: running the polluters
  under the old conftest would have spent real money testing a guard against
  spending real money.
- **`.githooks/commit-msg:23-29` STRIPS the `Co-Authored-By: Claude` trailer**
  (operator policy 2026-06-03, deletion not rejection). This run paid for that
  three times: three slice prompts told agents to add it, TWO verifier passes
  returned REFUTE on its absence as a genuine defect, and two merge bodies
  assert they carry a trailer the hook removed. Audit it with an ANCHORED
  predicate and read the message TAIL - `grep -ci` matches prose ABOUT the
  trailer. Now a one-line hard rule in CLAUDE.md.

---

# 2026-08-05d - lane 8 cycle 10: RM-161 closed, and the sibling sweep found the instance with the teeth

Three retention knobs took an age cap that erases everything it can reach at
zero or below. LEDGER 1201; 23 new tests; 13/13 mutants killed; verifier
CONFIRM 9/9; RM-162 filed LOW.

- **The filing named two instances. The one that actually deletes was the
  third.** RM-161 listed `prune_task_logs` and the FROZEN
  `ops/rc_supervisor.py:1442`. But `:1442` only READS the value and hands it to
  `ops/rc_incident_log.IncidentLog`, whose `_purge_old_locked` does the
  deleting - a module with **zero test references**. Reading the CONSUMER of a
  filed row, not just the row, is what found it.
- **Closing a frozen path without editing it.** The config key reaches the
  frozen supervisor, so the fix went upstream: `core/config_validator.py` gained
  a `field_ranges` mechanism and now rejects the profile before the supervisor
  ever reads it. That was the filing's own suggestion and it held up.
- **Raising was checked against the caller, not assumed safe.** The
  `IncidentLog` construction sits inside `_start_self_monitor`'s `try`, whose
  handler logs "SelfMonitor start failed (non-fatal)". So a rejected policy
  costs an unstarted monitor, never a supervisor crash. Verify the handler
  before choosing raise over clamp.
- **A range violation is an ERROR even on an OPTIONAL key.** Wrong type stays a
  WARNING there. The range table is curated to knobs whose bad value is
  DESTRUCTIVE, and a warning the operator scrolls past is the wrong severity for
  "this erases your incident log".
- **One of two first-pass mutation survivors was EQUIVALENT, not a test gap.**
  `not _check_type(data.get(key), ...)` reaches the same `continue` an absent
  key already took - it cannot change behaviour. The other survivor was real:
  the assertion looked for the substring "range", which the demoted message
  still contained. **A survivor is a claim about the test; sometimes it is a
  claim about the mutant.** Say which.
- **Scope was held, deliberately.** `image_retention_days` and
  `control_file_retention_hours` are typed in the same file and were NOT ranged:
  a tree-wide grep shows zero Python consumers, so bounding them bounds nothing.
  Interval knobs are a different root cause (hot loop, not erase) and were left.
- **Backfill probed live and CLEAN.** Shipped profile carries 7; incident log
  intact at 8374 lines / 2.4 MB. Latent, never realised - which is the honest
  answer, established by reading the live files.

---

# 2026-08-05c - lane 8 cycle 9: the log trimmer protected nothing, not even the log being written

`core/log_retention.py`, 190 lines, **zero test references**, started at RC boot
from frozen `main.py:158`, deleting files on an hourly timer for RC's whole
process lifetime. Commit `481e3ed5`; LEDGER 1200; 18 new tests; RM-161 filed.

- **The live measurement chose the file, and then justified it.** `logs/` was at
  **99.6 MB against this module's own 100 MB cap**, oldest file **9.0 days** -
  inside the 14-day window. So the age pass reclaims nothing and the next sweep
  to cross the cap runs the size pass over live files. Reading the module would
  have found the same six bugs; only the probe showed it was about to matter.
- **Windows was doing the module's job for it, and that is what hid the bug.**
  Nothing was ever exempt from deletion - including the file the running logger
  has open. It survived only because Windows refuses to unlink an open handle,
  and that refusal was swallowed at DEBUG. Now `_protected_paths()` reads
  `baseFilename` off every live handler and pins it in both passes.
- **The first RED run was VACUOUS and looked fine.** Both live-handler tests
  passed before the fix, because `active.exists()` is true on Windows whether or
  not the module protects anything. The honest assertion is that the path is
  never among the ATTEMPTED unlinks - via a spy that RECORDS and delegates, not
  one that raises (a raising spy is vacuous against fail-soft code).
- **A false SURVIVED from stale bytecode - new trap, worth keeping.**
  `max_age_days` and `max_total_mb` are the SAME LENGTH, so two mutants produced
  byte-identical file SIZES; Python revalidates a `.pyc` by source
  mtime-in-whole-seconds plus size, so one mutant silently ran the other's
  bytecode and its guard read as unneeded. Mutation harnesses need `-B`,
  `PYTHONDONTWRITEBYTECODE=1` and a `__pycache__` purge between mutants.
- **`git checkout --` destroyed the unstaged rewrite mid-investigation.** Exactly
  `reference_git_checkout_destroys_unstaged_mutation_probe`. Recovered byte-exact
  only because the harness keeps a copy-aside backup. Keep doing that.
- **The verifier corrected a number AND caught a real defect.** RC count was
  18410 in the commit draft; it measured **18411** and proved it (baseline 18393
  with the file ignored, + 18 = 18411) rather than accepting either figure. It
  also caught the rewritten file being **CRLF** against `.gitattributes eol=lf` -
  `Path.write_text` on Windows, the same trap as cycle 8. Normalised before commit.
- **Backfill probed, not assumed:** 13 real sweeps have fired, daily series
  `07-27..08-05` CONTIGUOUS, cap never crossed. The bad state was **latent**.
- **NOT armed by this branch.** RC runs `main.py` from `C:\Riot Commander`, so
  only the merge to `main` plus a restart deploys it.
