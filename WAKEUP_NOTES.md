# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-09, weekly-hygiene pass (relocated headless lane 6 RM-176 `2026-08-08`; newest 3 = DS coverage saturated `2026-08-08d` + orchestrated run `2026-08-08c` + RM-177 HSP flip `2026-08-08b`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-11 - Overlay Platform M submission compliance (operator-directed, interactive)

Commit `25fce0df`, pushed to main. RC `tests/` 18470 passed / 104 skipped / 0 failed. DS 10495 passed / 83 skipped / 0 failed. `ds_share_sync --check` in sync (engine 1.277.0, 533 files). Plan: `docs/OVERLAY_COMPLIANCE_PLAN.md`. Full detail: LEDGER 1238.

**What this session was.** Reviewed the Overlay Platform M app-proposal form + Riot's third-party rules, then cut every RC surface those rules ban and rebuilt the one worth keeping. Framework verdict for a future port: **ow-electron, not Overlay Platform M Native** (RC already ships an Electron shell and needs native node + a Python sidecar; Native is a CEF UI wrapper with no story for either).

**Removed:** enemy summoner-spell tap-tracker; summoner + ultimate cooldown ledger; ultimate power-spike cue; `/api/cooldown-watch` + `agents/daemon_slayer/cooldown_watch.py`. Every removal left an INVERTED guard test where the old case asserted the banned surface must exist - reinstating any of them turns a test red.

**Two things worth carrying forward:**
1. **B7 was a live routing bug, not just compliance.** `mode_from_game_mode_string` matched no branch on `"BRAWL"`, so a real Riot Brawl game defaulted to `MODE_SR` and got coached. Three OTHER sites tested substring `"BRAWL"` and so matched ONLY Riot Brawl, never RC's rotating modes. Gate is now `is_forbidden_game_mode()` + `MODE_UNSUPPORTED`, checked first, in `core/game_snapshot.py` (FROZEN file, edited with explicit operator approval).
2. **My own filed blocker B6 was wrong.** RC displays no TFT Legend/Augment win rates or average placements, and `core/augment_external_source.py` is an ARENA prior the TFT-scoped rule does not reach. Acting on the row as filed would have deleted a working Arena feature. Filed rows stay hypotheses until probed.

**The line, for any future session:** Riot bans **tracking** enemy cooldowns - the verb carries the rule. DDragon publishes every per-rank cooldown and the client shows them. The DS engine's cooldown math is untouched and must stay so; champ-select CC advice ("enemy comp has 4 hard-CC abilities, consider Cleanse") is legal; a per-instance countdown is not. `cc_threat_cell` is the compliant rebuild - CC duration and threat spell, no cooldown scalar, guarded against the scalar returning under a new name.

**OPERATOR ACTIONS OPEN (cannot be automated):**
- **RENAME the product.** "Amberstone" uses Riot's trademark and BLOCKS the Riot 3rd-party application. Operator has kept **Salt Circle** and **Lane Oracle**; full shortlist with domain-probe results is in `docs/OVERLAY_COMPLIANCE_PLAN.md` section 6b2. "Daemon Slayer" is NOT usable publicly (Shueisha's DEMON SLAYER covers computer game software; homophone, same class) - keep it as the internal engine codename.
- Riot Developer Portal product registration needs a Riot account login + form submission.
- A production key needs a public website, Terms of Service and Privacy Policy. None exist.

**NOT started:** B4 (move coach imperatives to pre/post-game, decision recorded in plan 6c - compute branches live, render nothing, review post-game), B8 (vision/OCR capture - DevRel question), B9 (LCU declaration), and the rename sweep itself.

---

# 2026-08-09 - weekly-hygiene pass (automated, unattended)

Relocated: `# 2026-08-08` (headless lane 6 RM-176, 43 lines) to `docs/history_notes.md`. WAKEUP_NOTES now holds 3 sessions.

CLAUDE.md: 40.6 KB, no stray ledger entries. CLEAN.

Memory suspects (operator judgment calls - do not act on these autonomously):
- `feedback_oauth_flip_injection_vectors.md` (45 days old, MEDIUM): "How to apply" step 1 cites `C:/RC-Agent/gamepc_bridge_daemon.py` on a retired machine as a live example. The NOTE (2026-06-24) says bridge files are deleted; core lesson transfers. Consider updating step 1 to remove the dead path citation.
- `feedback_gamepc_league_fullscreen_lockup.md` (Game-PC retired ADR-011): documents FS lockup on retired hardware. Low harm (filename self-labels it). Could move to `_retired/` when convenient.

Anomaly triage (all EXPECTED): RC pid=17624 alive, last_reload_ok=True; DS :8860 alive patch=16.15.1; all 24 RC-* tasks healthy (Ready or Running).
Open operator action (not new): bare `Amberstone` scheduled task (noted 2026-08-08c) - races RC-Supervisor for :8888 and loses, LastTaskResult=1. Deletion = system-settings change, operator territory.

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
`Amberstone` scheduled task (documented now, deletion is a system-settings
change), and RM-167's prompt-cache hoist (needs a live ARAM A/B).

**I restarted the live RC process by mistake** with a wildcard `taskkill /F /IM
pythonw.exe` intended for the DS bounce; the supervisor recovered it. Later pid
moves correlate with `pytest tests` runs and were filed as RM-188. **RM-188 was
then RUN and REFUTED the same day (`a7bcbd5a`) - do not re-file it.** Three
controlled arms, each against a 185 s idle control in which the pid did not
move: `pytest tests` from MAIN, the same suite from a fresh WORKTREE (the arm
the correlation actually came from), and an `RC-DaemonSlayer` bounce - pid
`21336` and `started_at` unchanged in all three. **The real trigger path is
`restart_trigger.txt`** (`ops/runtime/status.json` carries
`last_restart_reason: "restart_trigger"`, handled at
`ops/rc_supervisor.py:1595-1607`). One writer IS a test,
`agents/agent3_testing/suite/test_agent0.py`, but it sits in one of RM-170's
three unguarded trees and is NOT collected by `pytest tests` - only by
`pytest .`, already banned for deleting the live supervisor lock. Residual: two
of the four pid moves stay unexplained and correlate with merge / Share-sync
activity, not test runs. Watch `status.json.last_restart_reason` + `expected_pid`
across a merge; do not re-run the suite to chase it.

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
- **Filed, not actioned: a 25th scheduled task.** Bare `Amberstone`, logon
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

