# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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
