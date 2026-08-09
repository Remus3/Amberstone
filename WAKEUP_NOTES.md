# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-08, automatic via `scripts/wakeup_prune.py --keep 3` (relocated RM-26 anchor model + calibrator `2026-08-07b`; newest 3 = orchestrated run 2026-08-08-01 `2026-08-08c` + lane 6 RM-177 `2026-08-08b` + lane 6 RM-176 `2026-08-08`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-08d - the DS coverage lanes are SATURATED, and the one real defect came from an adversarial pass whose other two findings were both wrong

Baseline `b18a9da9`, head `a27aa105`. ENGINE **1.275.3 -> 1.276.0 -> 1.277.0**.
Merges `94432a20` (RM-186), `11698be4` (provenance), `432c857d` (RM-166),
`ac332f4d` (ROADMAP trim), `845f9cea` (RM-187); plus `b3360d2c`, `7c323ec4`,
`2b6917c0`, `a27aa105`. LEDGER 1237.

**Measured in merged main, re-run by the merger rather than carried from any
agent:** DS **10599 passed / 13337 subtests**; RC `tests/` **19015 passed /
96 skipped / 4211 subtests**; `drift_guard` 0; `ds_share_sync --check` in sync
at 535 files; DS `:8860` bounced and serving 1.277.0; CI green on `2b6917c0`.

**FORK B was taken - no game was up all session, so the live-gated rows
(RM-168 log-rate under load, RM-164 live acceptance, RM-167) are all still
waiting and none of them moved.**

**The lane picks both REFUTED, and that is the durable result.** Immolate is
7/7 registered with magnitudes byte-stable across six patches; on-hit is 51/51
canonical, the 24 "missing" ids all being throwback-band that `mode_variants.py`
partitions out at load. **Coverage-level DS auditing is saturated - the next
real depth is magnitude-level, not another coverage scan.**

**Three things that were stated as fact and were WRONG - do not re-inherit
them:** (1) "the Meraki rule can only be fixed by the operator because it lives
in gitignored files" - `tools/headless-upgrade.md` and
`tools/directed-headless-upgrade.md` are TRACKED MIRRORS with identical text at
the same line numbers, and `drift_guard` enforces the pair; fixed in
`b3360d2c`. (2) "223069 ships TRUE damage against a false citation" - Meraki
files that passive under `active` with `passives: []`, so a passives-only probe
fabricated the defect. (3) "a worktree can rebuild the ingest bundle" - `dist/`
is gitignored, so the hook's success inside a worktree never crosses the merge;
`--check` drifted in main and the sync had to be re-run there.

**Two operator-facing items are OPEN and neither is mine to close:** the bare
`RiotCommander` scheduled task (documented now, deletion is a system-settings
change), and RM-167's prompt-cache hoist (needs a live ARAM A/B).

**I restarted the live RC process by mistake** with a wildcard `taskkill /F /IM
pythonw.exe` intended for the DS bounce; the supervisor recovered it. Later pid
moves correlate with `pytest tests` runs and are filed as RM-188 - an
observation with a plausible RM-173-family mechanism, deliberately NOT called a
defect because the window is confounded and the one clean discriminator has not
been run.

---

# 2026-08-08c - orchestrated run 2026-08-08-01: three merges, and two of the three root causes were WRONG on the first pass

Baseline `aa8a386a`, head at merge time `f1f10f5c`. ENGINE **1.275.2 -> 1.275.3**.
Merges `9752cdfc` (S1 / RM-164), `367b54e7` (S3 / Carve) + `a180b299` (restamp),
`f1f10f5c` (S4 / LCU dedupe). S2 was read-only and shipped nothing.
LEDGER 1233-1236.

Measured in MERGED MAIN, not inherited from any slice: RC `tests/` **19011 passed,
96 skipped, 4208 subtests, 0 failed**; DS `agents/daemon_slayer/tests/` **10535
passed, 13218 subtests, 0 failed** (taken before the S4 merge, which touches no DS
file). `drift_guard` 0 breaches, `ds_share_sync --check` in sync at 532 files,
`ruff check .` clean.

- **RC skips fell 138 -> 96 and that is the ENGINE BUMP, not a test change.** DS
  live at 1.275.3 unlocks the `require_live_engine` set. The inverse is the trap
  worth carrying: **a DS ENGINE bump red-lines RC guards OUTSIDE
  `agents/daemon_slayer`, and bouncing the shared `:8860` mid-run turns every
  gated worktree red at once.** A lane cannot make the shared server serve its
  own code, so `test_live_three_profiles` asserting live `/health` against the
  repo constant is STRUCTURAL, not a regression - it clears on merge plus bounce.
- **RM-164 consumer half shipped, and the second finding was worth more than the
  first.** The lean was being discarded at a call site that ALREADY had the enemy
  comp in scope (sr 71/173, aram 71/173, arena 67/173 diverge; Alistar diverges at
  the OPENING slot). But the verifier then found a **classifier fault escaping an
  unguarded boundary and returning `[]`, DELETING the served row** rather than
  degrading to the neutral order - strictly worse than the behaviour the module
  promises. Also: **`item_advisor.resolve_build` is ALREADY comp-aware**, so the
  obvious "byte-identical across comps" assertion would have been FALSE for a
  correct reason. ON-vs-OFF within one comp is the invariant.
- **Obsidian Cleaver Carve was four patches stale (0.35 against a stated 6 pct).
  The durable half is the CLASS: these rows store one PRODUCT while DDragon states
  two FACTORS, so the number had no machine link to its source and nothing could
  go red when Riot re-tuned a factor.** New guard re-derives `per_stack x cap`
  from the live snapshot, population pinned, four mutations killed. **TRAP:
  16.11.1 DDragon states Carve at "Armor by 500%"** - verified verbatim, so a red
  guard there means read the stat line, never copy it.
- **The Meraki audit rule cost a slice 7 phantom mismatches before it was caught,
  and the rule is now carved out in `CLAUDE.md`.** `items_meraki.json` at 16.15.1
  is **320 items against DDragon's 706, ZERO rows carry a `stats` key at all, and
  228005 is absent from Meraki entirely** - pen/lethality magnitudes live ONLY in
  the DDragon `<stats>` block. Meraki stays correct for `aram_modifiers` and item
  passive formulas; this is narrow, not "Meraki is wrong".
- **The LCU duplicate-log root cause was REFUTED once and the correction is the
  lesson: serialized callers on one shared throttle SELF-SUPPRESS.** There is ONE
  `LcuClient` with two 1 Hz callers, but shared state alone cannot duplicate - the
  second caller sees elapsed ~0. Both bodies run through `asyncio.to_thread` and
  land in different worker threads, so the read-compare-write is unsynchronized.
  **It is a RACE, which is what makes the filter's lock load-bearing rather than
  decorative.** Discriminator: the first-of-gap INFO line is 19 singles and never
  paired; the throttled DEBUG line is 1143 pairs and never a triple. **Do NOT
  "clean up" the rune writer's second `connect()`** - deliberate, mtime-guarded,
  added after the 2026-07-04 pid-6440 silent death.
- **A shipped test was found weaker than claimed and REPLACED rather than
  defended.** Removing the filter failed the racing test, but swapping the lock
  for `nullcontext` did not - the unlocked window is too narrow to preempt
  reliably. A deterministic lock-held test replaced it.
- **Orchestrator process miss worth recording: a mistyped pytest path collects
  nothing and reads as GREEN.** Ran `tests/test_next_buy_fallback.py`; the real
  file is `tests/test_next_buy_ds_fallback.py`. The protocol records this only for
  `tests/daemon_slayer` - it generalises to every path argument.
- **Filed, not actioned: a 25th scheduled task.** Bare `RiotCommander`, logon
  trigger, Administrator/Highest, `pythonw.exe main.py`, `LastTaskResult = 1`,
  LastRun 2026-08-05, no repo artifact installs it. It races `RC-Supervisor` for
  `:8888` and loses. **Deleting a Windows scheduled task is a system-settings
  change - operator territory.** `docs/OPERATIONS.md` documents 24 and is short by
  one whatever the operator decides.
- **RM-167 re-sized: `aram_coach` alone is $40.02 / 31.2 pct of all-time spend**
  over 12,413 calls, against the row's "10-15 pct" framing. Cache ratio
  re-measured at 0.000221 pct on the post-repair ledger. Still NEEDS-OPERATOR -
  the blocker is the live ARAM A/B, not the arithmetic.
- **RM-168 was sampled on an idle client with League not running for the THIRD
  time.** Stop re-sampling it headless.

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
