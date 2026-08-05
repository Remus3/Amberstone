# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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
