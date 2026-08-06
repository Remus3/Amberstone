# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-08-05b - lane 8 cycle 8: the validator crashed, then blamed `<unknown>`

`lane/true-audit` MERGED to main first (fast-forward `b1541d96..5da5cc7c`, the
cycle-7 deploy containment now actually live since the supervisor loads it by
absolute path). Then cycle 8: `core/config_validator.py`, 407 lines, **zero test
references**, imported at import time by frozen `main.py:67`. Commit `17aa390a`;
LEDGER 1199; 40 net-new tests.

- **Read the CONSUMER before deciding what is worth fixing.** `main.py` wraps the
  call in a bare `try/except` and **discards the return value**. The module's
  entire product is its log line - so the bugs that mattered were the ones that
  mangle the log line, not the ones that change a status code nobody reads.
- **`key not in data` is a SUBSTRING test when `data` is a string.** A config
  whose top-level JSON was a string passed the whole required-key loop, then
  raised `TypeError` on `data[key]`. `validate_all` caught it and filed it under
  the literal file name **`<unknown>`** - losing the file name in exactly the
  case the module exists to diagnose. Fixed both ends: guard before any key
  lookup, and pair every validator with its path UP FRONT so `<unknown>` is
  unreachable.
- **A permissive default is a silent off-switch.** `_check_type` returned True
  for a type spec it did not recognise, so one typo in a `field_types` value
  disabled that field's validation permanently with no signal. The shipped specs
  moved into a declarative `_CONFIG_SPECS` registry so a test can sweep them.
- **Emptiness is not falsiness.** Required keys must now be non-empty
  (`python_exe: ""` and `app_cmd: []` both validated **OK** before), but judged
  by container, so `false` and `0` stay legitimate configured values.
- **A ruled-OUT assertion is not a pinned-DOWN one.** First mutation pass had a
  survivor: the unreadable-file test asserted only that the word "expecting" was
  ABSENT, which a collapsed generic message satisfies just as well as a correct
  one. Strengthened to assert the OS detail survives AND that the read and parse
  messages differ. **8 of 8 mutations now killed.**
- **A required config that `.gitignore` excludes ERRORs on every fresh clone.**
  `config/coach_settings.json` (`.gitignore:40`) is genuinely required and
  genuinely absent in CI. Kept the ERROR, made it actionable by naming the
  tracked `coach_settings.example.json`. Same reason `LiveConfigTests` is scoped
  to configs that EXIST - a blanket "zero ERROR" gate passes on Legion and fails
  in CI, which is a test that lies about where it works.
- **`write_text` re-encoded the target to CRLF** during the mutation run
  (`reference_windows_write_text_crlf_byte_count`). Caught by the `git diff` EOL
  warning pre-commit and normalised back to LF. Pair it with the cycle-7 lesson:
  CRLF breaks mutation anchors AND sneaks into commits.
- Live config dir before and after: **4 OK, unchanged**. Full RC suite from the
  REPO ROOT: **18393 passed, 154 skipped, 0 failed**.
