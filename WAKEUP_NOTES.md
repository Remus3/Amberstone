# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-07, automatic via `scripts/wakeup_prune.py --keep 3` (relocated lane 8 cycle 9 `2026-08-05c`; newest 3 = RM-26 anchor model + calibrator `2026-08-07b` + headless run 2026-08-06-02 `2026-08-07a` + lane 8 cycle 10 `2026-08-05d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-07b - RM-26 anchor model, then the calibrator: the filed bug was the smallest of four

Commits `4b157aef` (anchor model), `68ba3fb3` (CI fix), `f8aaa7ef` (calibrator).
CI green on all. Interactive session, inline, no subagents (harness directive).

- **The RM-26 acceptance criterion could not be met, and the reason generalises.**
  It asked for the anchor model to be "validated against a real frame - not a
  model". Every reference still on disk is 2560x1440, and **at a matching aspect
  the width ratio EQUALS the height ratio, so left / center / right / top /
  bottom anchoring all produce the byte-identical box.** 16:9 cannot discriminate
  between anchor classes at all. That is also why the earlier best-anchor error
  measured exactly 0.00x - **that number was never evidence about anchoring.**
  Model built and DEFAULT-OFF; one native 21:9 or 32:9 still is the only gap.
- **Not inert, and measured before claiming so** (the LEDGER 1227 lesson): 0 of
  21 boxes change at 2560x1440, 21 of 21 at every ultrawide, worst 492px at
  5120x1440.
- **The acceptance criterion's own top/bottom axis is arithmetically INERT.**
  Under scale-by-height, bottom anchoring reduces to top anchoring. Filed and
  pinned rather than quietly implemented as if it mattered.
- **Two of my tests asserted hand-computed integers and FAILED on int()
  truncation.** Corrected to property assertions with a stated 1px tolerance -
  the implementation keeps `_scale_bbox`'s convention rather than being bent to
  my prediction.
- **A test that asserts on a GITIGNORED directory is green only on Legion.**
  `data/vision_calib_reference` is untracked by design, so CI went red. Now a
  CAPABILITY skip per the LEDGER 1228 B5 rule. Local green is not CI green.
- **THE BIG ONE: reading the page beat fixing the filed line.** The calibrator's
  seed warning was written into `#status`, which `loadFrame()` overwrites on
  every boot - **nobody had ever seen it.** A wording-only fix would have shipped
  a correct sentence no one reads.
- **The UI audit found a live correctness bug that made the page useless for its
  one job.** Boxes were laid out in FRAME space while their coordinates are in
  PROFILE space; the live path serves a halved 1280x720 frame against a
  2560x1440 base, so all 21 drew at double scale, the rightmost at 2471px on a
  1265px page. Same mismatch in the save payload. **Run the audit on the page,
  not on the diff.**
- **Two measurements discarded rather than reported:** a `clientWidth: 0` probe
  (zero-width pane) that claimed all 21 regions escaped, and an "all 21 labels
  flipped" reading that was stale state because the harness's programmatic
  resize does not dispatch `resize` to the page.
- Do NOT redo: the resolver, consumer fix, crop-rect guard, anchor model, or the
  calibrator. Do NOT re-measure anchors at 16:9 - it cannot answer the question.

---

# 2026-08-07a - headless run 2026-08-06-02: 21 slices over four cycles, and the adversarial pass earned its cost every single time

Operator asked for five open ROADMAP items, orchestrated multi-agent, self-
adjudicating and self-adversarial, self-looping for ten hours. Ran 18:00 to 02:30.
Four cycles, 21 build slices plus 16 independent verifier passes, all worktree-
isolated on disjoint files with one merger. Merges: `c20bf2c6..d6764910`.
LEDGER 1207-1228. Dual suite closed at 29398 passed / 0 failed; drift guard clean;
ROADMAP held at 72217 bytes.

**The single most important line: a CLAUDE.md `Settled - do not re-litigate` entry
called a LIVE paid Haiku path deadcode, and it was false on the day it was
written.** Five game modes route to `coaches/brawl_coach.py`, the feature flag
allows it, and construction alone spawns its poll loop. A cleanup pass acting on
the old wording would have deleted it. Corrected in place (LEDGER 1222/1226).

**Why the adversarial pass is not optional.** Every cycle it caught something the
slice could not see in itself:
- It CONSTRUCTED a catastrophic write - a process that won a relocated claim would
  stamp its own live pid into the real supervisor sentinel.
- It caught a skip converted into a NO-OP (an assertion true by construction), which
  is worse than the skip it replaced because a visible SKIPPED became a silent dot.
- It found a guard pointed at a different address than the thing it guarded.
- It proved three separate fixes were arithmetically INERT downstream.
- Twice it found a TRUE conclusion resting on a citation that did not exist.

**Every filed count that was re-derived was wrong** - B5 `about 22` was 1, B4
`about 22` was 11, B2 `19` was 20 - and two rows I wrote myself were refuted by the
slices I sent to execute them. Treat a filed number as a hypothesis.

**Three things I got wrong and the run corrected:** I pushed once with a failing
test because a shell `&&` chain read `tail`'s exit code instead of pytest's; my own
repo-root `pytest .` runs were deleting the live supervisor lock every time (that
IS the RM-173 root cause); and I proposed a poll-based fix for the overlay flake
that would have made it fail slower rather than pass.

**The cross-slice failure only the merge could find:** the B5 skip guard did not
know git-LFS exists, and two slices were both right. Tracked-and-LFS is a
capability gate; tracked-and-not-LFS stays a defect; and the rescue quantifier must
be ALL, not ANY, or the whole class re-opens. Five green branch reports would have
shipped it.

Rows closed: RM-163, RM-165, RM-158 data half, RM-119 B5/B4/B2 (the R219 skip audit
is now fully drained), RM-164 provenance, RM-169, RM-170, RM-171, RM-172, RM-173,
RM-174, RM-175 (ADR-014), RM-155 retired (ADR-013), RM-26 corrected. Filed: RM-169,
RM-170, RM-171, RM-172, RM-173, RM-174, RM-175.

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
