# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, lane-7 headless-repo pass (relocated `2026-08-29` upstream processing; newest 3 = lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c` + RM-222 flat-pen layout guard `2026-08-29b`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-30 - LANE 7 headless-repo: repo already clean, two doc fixes, two sweeps deferred

Outsider-clean audit in worktree `lane/repo`. Pre-flight caught that the launcher had
dropped the session in the MAIN tree with the `lane/repo` worktree ABSENT - created it
from main HEAD `2be9603c` and worked only there. `core.hooksPath` is the shared absolute
`.githooks` (reported, unchanged per 1b). Every standing guard was green on arrival
(drift_guard 0, archmap + state_schema up to date, ruff clean, worktree clean, the
byte-identical pair matching its pins), so the repo is clean at every machine-checkable
level; the value was in the uncovered surfaces.

**Shipped (LEDGER 1275, Tier-0 docs):**
- `docs/DAEMON_SLAYER.md:40` `cast_rates.` -> `ult_rates.` (the fn is defined only in
  `ult_rates.py:201`; line 50 already said so - a self-contradiction a stranger would grep and fail on).
- `docs/OPERATIONS.md:309` stale absolute rotation date ("~2026-08-01", a month past)
  replaced with a derive-from-mtime instruction.
- RM-227 filed (BACKLOG Reliability/hardening); DS_SWEEP_TRACKER pointer advanced to RM-228.

**Deferred, NOT executed (both filed under RM-227, anti-rediscovery):**
- Dead code: NO file dead to a HIGH bar. Five MED candidates (`ops/_scheduler_client.py`
  plus four re-runnable Phase-3 seeders), each with a retention rationale - a headless delete
  would be a wrong deletion. RM-195 already covers dead FUNCTIONS; this is files.
- Glyphs: 3,017 grandfathered U+2192/U+00D7/U+00B7/U+2248, already blocked NET-NEW by the
  `precommit_gate.py` catch-all (2026-07-28); population is deep-archive / DS-mirrored / frozen /
  FUNCTIONAL-delimiter (the coach arrow is a `_re.split` delimiter), so a rewrite is behaviour
  change, not hygiene. Outsider-facing living docs already clean.

**Out-of-repo: ZERO deletions executed** (67 GB 2026-07-30 snapshot fully stale on re-measure):
- `.gemini` 99 MB - distinct adjudicator APPROVED the purge on clean evidence (no live
  filesystem reader of `~/.gemini`), PROPOSED-ready but NOT deleted (permanent file deletion is
  operator territory under the standing safety rule).
- `Temp/claude/C--Sibling-A` 0.29 GB (was 35.5) - sibling repo, UNTOUCHED, propose-only.
- `.claude/projects` 1.19 GB - EVIDENCE, UNTOUCHED. `.cache` 13.8 GB - propose-only.
  RC Temp scratch 0.2 MB total - nothing older than 30d, no prune worthwhile.

**Gates:** doc guards green; full `tests/` from the worktree root **19131 passed / 144 skipped /
1 failed** - the one failure is the pre-existing fenced `test_subagent_prompt_flag.py::test_cli_version_still_matches_the_pin`
(PINNED_CLI 2.1.220 vs live CLI 2.1.251, needs `claude login`), 0 in this diff. No `.py` touched,
no `ENGINE_VERSION`, no Share mirror, no frozen-file edit. Branch `lane/repo` ready for the merger;
NOT merged to main from the worktree.

---

# 2026-08-29c - a cross-project port collision, found by answering a question

Operator asked which ports are reserved for Amberstone, DS, Sibling-E, Sibling-D,
Sibling-A and Sibling-C. `core/ports.py` could only answer for FOUR: the 2026-08-01
negotiation predates both Sibling-D and Sibling-E, so `BLOCKS` had no `ll` or `cs`
key and `block_for(8810)` returned None.

**Answering it turned up a live collision.** Sibling-E claimed band **8900-8911** with
its dashboard on **8901** - wholly inside Sibling-A's reserved 8900-8919, where
8901 is LW's `MONITOR` and 8900 its `RUNDASH`. Cause is the exact method `core/ports.py`
warns about in capitals: CS picked the band by SCANNING for a free listener, and LW's
monitor is an operator-launched GUI that is unbound most of the time, so the scan
reported a reserved block as free. CS names Sibling-A in zero files. It had already
met the symptom and mis-filed it - its BACKLOG blamed "an unrelated process" holding 8901
since 2026-08-16.

**Shipped:** RC `533d4f97` - `LL_BLOCK` + `CS_BLOCK` registered, `BLOCKS` now six, the
collision recorded in the docstring, two new guards (CS/LW disjointness pinned by NUMBER;
LL's widened 8815-8819). Mutation-proved RED three ways, `core/ports.py` restored
byte-identical. LEDGER 1274. Sibling-E moved to **8920-8939** base **8920** across 6
files; its `verify_env.py` went from a soft failure on every run since 2026-08-16 to
**PASS, ports free 20/20**.

**Do NOT redo:** Sibling-D was already correct (8810-8819) and already carried the
identical six-row table - it independently settled a one-digit ambiguity in the operator's
own message (prose said 8820-8839, the table said 8920-8939). It has uncommitted work from
its own session; leave it alone.

**BLOCKED, and it is not ours to clear:** the Sibling-E commit `67b00b2` exists and is
byte-identical to the intended content, but **the push is blocked by that repo's own
`pre-push` hook** (`pytest tests -q -x`). Its suite is red from ANOTHER session's in-flight
surface-contract work - an untracked `sibling_e/surface/api/contract.py` that its staged
`tests/surface/test_contract.py` imports. Two of the three failures name that file
directly; the third passes in isolation. `main` there is ahead 1, remote still `4ac5c3e`.
Never `--no-verify` it. It goes up when that session's work lands green.

**Process note worth keeping:** I edited a sibling repo another session was concurrently
working in. It resolved cleanly, but I checked Sibling-D for in-flight work and did NOT
check Sibling-E before writing. Check every sibling tree's `git status` first.

---

# 2026-08-29b - RM-222: the flat pen axis gets the live-vs-pinned layout guard the percent axis has had since it broke

Commit `e5b5c9e6`, Tier-1, one test module plus its Share mirror. No engine change, no
`ENGINE_VERSION` bump.

**The gap was real and asymmetric.** `test_pen_pct_catalog_r160.py` compares live
`data/meta/ddragon_items.json` against the pinned `data/daemon_slayer/16.15.1/items.json`
under a `_PINNED_CARRY_FORWARD` allowlist. `test_magic_pen_flat_catalog_r153.py` had NO
layout test - confirmed by enumerating its 9 `def test_` names, not inferred. The percent
axis got hardened because it broke; the FLAT axis stayed quiet while carrying the only
live divergence in either sweep (item 3175, RM-190 carried 18 -> 20 with the snapshot left
pinned). A second such move would have landed silently.

**Measured before the allowlist was written, not copied from the row:** both layouts sweep
10 ids and diverge on exactly `{'3175': ('20', '18')}`. Predicting it is not measuring it.
**Proved non-hollow three ways** - a wrong magnitude, a wrong id, an empty allowlist each
turn the guard RED - then the file was restored byte-identical, sha256 checked both sides.
Two of the three new tests make that permanent rather than a one-time authoring act:
`_layout_divergences` is a free function taking both sides, so one test perturbs live and
one asserts a VANISHED divergence is caught (the half that makes a stale entry go red after
a snapshot bump - an RM-223 trigger).

**Do NOT redo:** the fence held - the flat regex was NOT folded into R160's pattern tuple.
Both Share doc recitals (`21 skipped`, `10684 collected`) were already refreshed from a
FRESH mirror run. `docs/DAEMON_SLAYER.md` needed nothing; RM-210 already deleted its recital.

**The one RC `tests/` red is NOT a regression and must not be "fixed" by bumping the pin.**
`test_cli_version_still_matches_the_pin` moved skip -> fail since LEDGER 1272 because
Legion's `claude.exe` got FIXED: it now runs, reports 2.1.251 against `PINNED_CLI =
"2.1.220"`, and correctly fires the genuine-drift branch. The guard is right in both states;
that is also why the skip tally moved 97 -> 96. The pin needs the undocumented-flag canary
re-run first, which needs an authenticated CLI - still blocked on `claude login`.

**Measured this session:** DS **10687 passed / 13483 subtests / 0 failed**, collect-only
10687. RC `tests/` 19177 passed / 96 skipped / 1 failed (the CLI pin above). Share mirror
**8251 passed / 0 failed / 24 skipped / 11124 subtests**. `ds_share_sync --check` in sync at
529 files; `drift_guard` 0 breaches; ruff clean; hygiene 14 passed.
