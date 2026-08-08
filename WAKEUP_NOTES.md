# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-07, automatic via `scripts/wakeup_prune.py --keep 3` (relocated lane 8 cycle 9 `2026-08-05c`; newest 3 = RM-26 anchor model + calibrator `2026-08-07b` + headless run 2026-08-06-02 `2026-08-07a` + lane 8 cycle 10 `2026-08-05d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-08b - lane 6 continued: RM-177 HSP flip, MERGED and DEPLOYED

Main `b697e139`. ENGINE **1.275.0 -> 1.275.2** across the day; `:8860` bounced
and serving 1.275.2 (probed). Merges `fb751846` (RM-176) + `6a407b0e` (RM-177).
CI 4/4 green on main. LEDGER 1231 + 1232.

- **RM-177 shipped: HSP composes ADDITIVELY** - `product(1 + chain_pct) *
  (1 + sum(hsp_pct))`. `hps.py` multiplied what `_hsp_amp` summed, off the same
  catalog field, for 73 engine revisions with a green test on each side. **This
  is the rare DELIBERATE default-output move** - `/api/spike-curve` amp
  1.3552 -> 1.3200. Operator cleared the gate LEDGER 1231 had recorded.
- **I wrote a FALSE claim into two shipped docs and the adjudicator caught it.**
  I asserted "item ordering did not change" from a 7-champion probe at ONE build
  state; a 3840-scenario sweep found ordering moves in **638 (16.6 pct)**, and
  every zero-change state is a 0-or-1-HSP state - which is exactly why the
  narrow probe read clean. Corrected visibly in three docs. **Top-1 is unchanged
  in 0 of 3840**, which is why the six build-order tables still regenerate
  2-line-diff. Lesson: I had written the "on these builds" caveat in chat and
  then dropped it from the artifact.
- **The `ally_chain_only` carve-out is only as good as the flag census, and the
  composition test CANNOT guard it** - it mirrors the branching rule. What
  guards it is `test_enchanter_hsp_magnitude_drift_r197.py:324`, pinning the
  flagged set against DDragon. A future heal-chain item must be added there.
- Do NOT re-derive: three tests were RENAMED not bent, all mutation-proven RED
  under all-additive, all-product AND branch-swapped engines.
- Wrap found + fixed 2 drift breaches: ROADMAP at 96 pct (relocated the RM-177
  filing plus two fully-closed rows to `ROADMAP_HISTORY.md`, now 89.3 pct) and
  three stale 1.275.0 anchors (CLAUDE.md:6, NEXT_SESSION_PROMPT, SKIPIF audit).

---

# 2026-08-08 - headless lane 6 (DS): RM-176, and the refutations were worth more than the fixes

Commit `d53c9673` on `lane/ds`, draft PR #12 (opened solely to exercise CI -
all three workflows trigger on push-to-main or PR, so a lane push runs nothing).
ENGINE 1.275.0 -> 1.275.1. Orchestrated: 4 parallel read-only audits over
disjoint engine module groups, then a separate adversarial refutation panel.

- **6 defects filed, 3 survived refutation. The panel was the highest-value
  step, not a formality.** The R212 Yasuo overflow saturation came in HIGH with
  a fully-cited root cause at `engine.py:217-218`. Simulating removal of that
  clamp changed nothing - **the binding clamp is `crit_total` in `dps.py`, three
  lines from the seam. A TRUE citation supporting a FALSE conclusion, and a fix
  aimed at the filed line would have shipped inert.** Kept as a ground-truth
  test pinning the saturation boundary, with a docstring saying game truth is
  unresolved, so the next agent does not re-file it.
- **Both real defects were hidden by a signal being read as safety.**
  `_recharge_to` contradicted its own docstring - it claimed to prevent
  DOUBLE-counting while actually DISCARDING time. And the extra-shot crit bug
  presented as ON/OFF `weighted_dps` being **bit-identical**, which reads like a
  well-behaved opt-in and was in fact the whole flag being arithmetically inert.
  **Byte-identity is only reassuring when you know which side should have moved.**
- **`--static` regen is load-bearing in a lane worktree.** `:8860` runs from the
  main tree, so a live-HTTP regen would have computed against a different engine
  than the one being shipped and returned a confident wrong answer. Same root
  cause as the one dual-suite failure (`test_live_three_profiles` asserts live
  `/health` == repo `ENGINE_VERSION`) - a lane cannot make the shared server
  serve its own code, and that is not a regression.
- **The post-commit hook clobbered the lane index.** It backgrounds
  `tools/gist_share_sync.py` against `C:/Riot Commander` whenever a commit
  touches `Share/`; its git calls left 5228 files staged as deleted while the
  working tree was intact. `git reset` restored it. **Do not panic-reset --hard
  on this** - the files were never gone, only the index was wrong. Also note the
  hook publishes `Share/` to a review gist automatically on any Share-touching
  commit.
- **Filed not fixed - RM-177:** HSP composes multiplicatively in `hps.py` and
  additively in `_hsp_amp.py`, on the DEFAULT path. The flip needs renaming
  tests whose NAMES assert the opposite physical model, so it is operator-gated;
  the adjudicating agent returned confirm-with-defer rather than shipping it.
- Suites measured, not carried: DS **10518** passed / 13195 subtests; RC
  `tests/` **18929** passed / 143 skipped / 2082 subtests / 1 failed (above).
  Independent verifier: CONFIRM 11/11.

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
