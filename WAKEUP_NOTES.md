# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-28b - R213 ARAM overlay audit. Two MUST-FIX, and one of them taught more by being half wrong.

Gemini-loop cycle 18. Section-3b 5-phase audit of the ARAM coach overlay widget.
Full detail in `docs/LEDGER.md` 1090. Commit `3015bb79`.

## Shipped

- `aram_balance.js` - a failed `/api/aram-balance` fetch no longer poisons the
  cache. It used to write `{}`, which is not `null`, so the one-shot fetch never
  retried and every row rendered `no ARAM changes` off a dead route for the rest
  of the page lifetime. Now: null cache + `failedAt` stamp + 30s cooldown, every
  terminal branch repaints, unresolved paints an honest degraded line.
- `active_match.css` - `#aram-balance-panel` gets a NAMED third grid row
  (`:has()`-scoped, overlay shell excluded) and a 320px cap, replacing the
  implicit auto-placed row that `web/index.html:2211` had wrongly claimed was
  already pinned by this stylesheet.
- 9 tests, all RED first: 5 driving the real module in node with a stubbed
  `globalThis.fetch`, 3 static class guards, 1 reading COMPUTED style off the
  real page so a mis-parsed `:has()` fails in CI, not in a live game.

## The thing worth carrying forward

The audit agent found both defects and got the SECOND one's mechanism wrong. It
reasoned that the implicit row steals height from the `1fr` panes and clips
coach text. Reverting the CSS in place and re-reading computed style says
otherwise: `1537.98px 1537.98px 456px` before, `1537.98px 1537.98px 320px`
after - the `1fr` rows are identical, because the grid is content-sized by the
MAP pane and the section already scrolls 3610px into 1003px either way. The
symptom was real, the mechanism was invented, and it would have landed in the
ledger as fact. **An audit finding's REASON needs its own measurement, not just
its symptom.** Both CSS comments and both test docstrings now carry the
measurement so the stronger claim cannot be re-derived from them later.

## Owed / next

- OWED: live Electron overlay capture of this widget. Mode was `client` with no
  ARAM game; the ui_recon Playwright capture at `?ui_mock=1&mode=aram` stands in.
- Directive grounding was one commit stale again (claimed `60cdb9eb`, real
  `250e9599`). Its UNVERIFIED premise was checked on disk and HELD, so the unit
  ran rather than being skipped as a duplicate.

---

# 2026-07-27k - README redesign shipped across all four surfaces. Implementation-only session.

The drafting and auditing happened earlier; this session applied the staged
package and verified it. Full detail in `docs/LEDGER.md` 1088. Commit `c7a36f14`.

## Shipped

- **All four README surfaces rebuilt in one commit** so the post-commit gist
  sync published once: root `README.md`, the `docs/HEXCORE_offline.html` overlay,
  `Share/README.md` (517 -> 201 lines), and `_README_TEMPLATE` in
  `tools/gist_share_sync.py`.
- **The Share test-posture contradiction is gone.** One file told it three
  incompatible ways; the two stale statements are deleted, not reconciled. One
  dated block survives: measured 2026-07-27 on a clean unzip, 8044 passed,
  1 known standalone failure, 15 skipped, 4157 subtests, about 83 seconds.
- **The overlay can no longer fork-lag the root README** - it is a 221-word
  pointer card with no fact that changes, spliced by element id and measured in
  a browser at one screen, no scroll.
- **The gist "six archetypes" claim was removed, not corrected to seven.** The
  template has no restamp mechanism for a count, so it must never carry one.

## The rule worth keeping

A fact may appear in hand prose only if it is durable, machine-restamped on that
surface, or dated and owned by exactly ONE surface. Everything else is a pointer
to the live source. Consequence, and the reason this was worth a session: **an
ENGINE bump now touches zero hand prose on any of the four surfaces**, and a
test-count change touches one line in one file.

## Verified live, not assumed

`ops/runtime/gist_sync_status.json` ok=true / 0 unpushed at a fresh timestamp,
AND the live gist README refetched from its raw URL showing the new body with
`ENGINE_VERSION 1.262.0 - data patch 16.14.1` substituted. The gate set:
hexcore + gist tests 18 passed (`node --check` really ran), `ds_share_sync.py
--check` green, Share guards + drift guard 77 passed, the full live-derived
docs-guards selection (50 modules) 1398 passed / 6 skipped, ruff + py_compile
clean.

## Then two operator-directed follow-ups, both shipped in the same session

- **Machine codename scrubbed from the shipped extractors** (`fd67d819`). The
  wiki stats + ability extractors and their sibling `cdragon_spell_extract` named
  the development machine in module docstrings that ship inside Share.zip and,
  for the two wiki tools, as standalone gist files. Every access fact is kept -
  the vanity-alias vs `.wiki.gg` 401 block, the non-browser-UA Cloudflare 403 -
  phrased against "this development host" / "any host that reaches X", which is
  the more useful instruction anyway. Live gist copies refetched: 0 hits.
- **The last non-ASCII glyphs purged from the shipped tools** (`de04ef44`).
  Middot, three check marks, an arrow, a not-equal sign, all display strings.
  `Share/src/**/*.py` now scans byte-clean.

## The thing worth remembering from the second one

**The precommit gate scans STAGED LINES.** A glyph already on disk in a file
nobody edits is never in a diff and is never seen - which is exactly how five of
them survived the 2026-05-18 repo-wide purge with a green gate on every commit in
between. A retro purge is a whole-file byte scan, never something the hook
converges to on its own. Written into
`reference_git_hooks_authoritative_and_traps` as a scope limit (it is NOT a fifth
"hook does nothing" trap - the hook fires and is correct).

## Open for the operator

- **Sign-off GRANTED 2026-07-28 (operator):** the shortened Share Notation
  section stands as shipped - 20 lines that named internal id families in the
  most external doc, now a three-line generic disclaimer. No revert. This line
  is closed; do not re-raise it.
- **Left deliberately:** three host-only `tools/*.py` still carry non-ASCII -
  `p3_ascii_sweep.py` (its own glyph inventory, correct as-is), `extract_panels.py`,
  `rc_facts.py`. None ship in Share.zip. Say the word on the latter two.

---

# 2026-07-27j - RM-119 CI coverage + the preflip isolation class. Operator-directed.

Two asks after the f1 drain - "do the RM-119 CI change", then "fix the 7
preflip_mode isolation bugs" - plus supervising 17 autonomous loop cycles.
Full detail in `docs/LEDGER.md` 1087.

## Shipped

- **RM-119 DS half: 397 DS test files went 0 -> gated on every push.** Verified
  on the runner (9970 passed / 83 skipped / 2m47s), not just locally.
- **The 7 preflip failures, root-caused and fixed.** They were NEVER
  parallel-isolation bugs - the same 7 fail serially. Both classes derived
  `unittest.IsolatedAsyncioTestCase`, which enters the loop on the MAIN thread
  under Playwright's leaked running-loop marker. Fixed via the remedy RM-100
  already settled (`tests/_asyncio_isolation.run_coro`), assertions proven still
  failing when the production mirror is disabled.
- **The guard that should have caught it was blind** - it walks `ast.Call` and
  cannot see a base class. Now scans `IsolatedAsyncioTestCase` bases, with a
  negative control and a prose-ignoring test.
- Nightly is green and parallel; the loop shipped R205-R212 alongside.

## The number that changes a decision

A `workflow_dispatch` dry run priced the full dual suite ON A RUNNER before
anything was wired: **19m42s, 23607 passed / 258 skipped / ZERO failures**,
against 20m37s serial. **`-n auto` buys 55 seconds - about 4 percent - where
the local 8-core figure was 2m20s.** I had quoted that local number in a CI
comment as if it were the runner's; corrected in place with both numbers.

## NEXT SESSION - wire the RC half

RM-119's remaining half: push CI still collects **85 of 807** RC test files. The
preflip blocker is CLEARED, so this is now purely a cost decision:
- the `check` job would go from ~8m30s to ~20min per push
- it needs `pip install -r requirements.txt` on that job (the runtime stack)
- shape: replace the DS-only step with the full dual suite and drop the two
  steps that become pure subsets (`smoke + regression tests`, `panel snapshot
  tests`); KEEP the special-env steps (`RC_REQUIRE_HOOK_GATE`,
  `RC_REQUIRE_BUILD_ORDER_TABLES`) because they turn skips into failures in a
  way a plain run does not.
Operator has asked for it; it was deferred only to wrap this session cleanly.

## Other open items

- **`scripts/wakeup_prune.py` cannot see the loop's entries.** `SESSION_RE`
  requires `^# ` (H1); the loop writes `## ` (H2). So 12 loop sessions are
  invisible to it and `--check` reports COMPLIANT while this file has grown to
  61KB. Same defect class as everything else this session - a guard blind to a
  spelling. Fix the regex to `^#{1,2} `, then run the relocation as its own
  deliberate step (it will move ~12 entries; do not do it at a wrap).
- **Audit reasoning still is not persisted.** `directive_history.jsonl` stores
  only `VERDICT: REGRESS`, so diagnosing the two fabricated verdicts required
  reconstructing them by hand from the directive and git.
- **Loop is PARKED** (`STOP` present) for this CI work. Relaunch:
  `powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\loop\launch_loop.ps1" -Mode live`
  gemini recovered from a Google-side 503; if it 503s again the loop stops on
  its own and the relaunch is the whole fix.
- **NEW FLAKE IN THE PUSH GATE: `tests/snapshot_panels/test_home_view.py::
  test_home_week_pool_rows`.** Failed once on CI with
  `playwright TimeoutError: Page.wait_for_function: Timeout 10000ms exceeded`
  (412 passed, 1 failed), and PASSED on an immediate re-run of the same commit,
  so it is timing and not a regression. Suspicion worth testing rather than
  assuming: the `check` job got ~3 minutes heavier when the DS suite landed, and
  a 10s Playwright wait is the first thing that starves under load. The DDragon
  `FileNotFoundError` lines in that step are unrelated noise - those assets are
  a gitignored local mirror and never exist on a runner. If it recurs, raise the
  wait or make it wait on a condition rather than a fixed 10s.

- **Cloud scheduled routines commit to main ungated** - no local hook sees them
  and a `.md`-only commit skips CI. R207 removed the reports-dir hygiene
  exemption, so that one class is now caught; the general shape is not.

---

# 2026-07-26b - F1 cross-repo concurrency + the headless executor seam. 8 commits.

Paired session with Sibling-A. RC could not run headless at all before this: the
executor was inlined in the controller and hard-wired to the AHK GUI bridge, a
machine-wide singleton keyed on a window title. Full narrative in `docs/LEDGER.md` 1069.

SHIPPED
- `ops/loop/slots.py` + `ops/loop/winmutex.py` - BYTE-IDENTICAL-BY-CONTRACT with
  Sibling-A (`95077a62...` / `c21bfe4f...`). NEVER edit one repo's copy alone; both
  loops coordinate through `C:/ProgramData/lw-loop/slots` + the OS mutex namespace.
- `ops/loop/executor.py` - the channel seam. `channel` config key, sdk is now the DEFAULT.
- `claude_gui_bridge.ahk` double-Enter - a single `{Enter}` was being swallowed, leaving
  the directive typed-but-unsent until the deadline with no error.
- `{{FINAL_STEP}}` substitution - the two channels need OPPOSITE completion steps.
- Dollar cap REMOVED everywhere (Max 20x is a subscription; TIME is the only real budget).
- P5 concurrent run PASSED 4/4; phase-6 gate run PASSED 7/7.

DO NOT REDO
- Do NOT delete `done_sentinel.py`, `meter()`, `claude_gui_bridge.ahk` or the ahk path.
  Operator HELD the phase-6 deletions. Rollback is the one `channel` key.
- Do NOT re-derive the shared-file hashes from whatever is on disk later - they were
  pinned while both trees were provably in sync.

NEXT - an 11-item queue, agreed with LW, UNSTARTED:
1 `git update-index --chmod=+x .githooks/*` (all five are 100644, so hooks are INERT on
  any Linux clone) - 2 `gate_inactive_reason` checks the exec bit, not just presence -
3 log the sdk `session_id` on EVERY executor log path incl. success - 4 `ENGINE-IMPACT:
BUMP` must require a numbered step naming every anchor site (there are FIVE: the gate run
found `agents/daemon_slayer/CHANGELOG.md` is a different file from `Share/CHANGELOG.md`) -
5 `skipif` audit for preconditions that should be FAILURES - 5a pin the shared-file
sha256s as constants so CI enforces parity without the sibling tree - 6 CI arms the hook
gate then asserts it end-to-end, replacing the `skipUnless` that blinded RC - 7 directives
naming N parallel agents must assert disjoint files; the executor serializes AND RECORDS
the deviation - 9 `winmutex` POSIX branch emits `UNSERIALIZED` (today it is unserialized
AND untraced, so every guard passes vacuously off Windows) - joint edit, needs LW - 10
enumerate the defect class WITHIN the file before committing the fix - 11 score-invariance
claims ship as a test (the 171-champion claim was measured but left no durable artifact).

ALSO OPEN (drift_guard, 2 breaches, both pre-existing at wrap)
- `ROADMAP.md` at 94 percent of its 81920-byte budget - needs a relocation pass to
  `docs/ROADMAP_HISTORY.md`. Deliberately NOT grown this session because of it.
- version-anchor FALSE POSITIVE: the check excludes historical FILES by name but not
  historical LINES. `ROADMAP.md:98`, `docs/ORCHESTRATION_PLAN.md:649` and
  `Share/README.md:340,353` all name 1.259.0 as HISTORY, correctly. Fix the CHECK
  (line-level context) + add a `tests/test_drift_guard.py` case - do NOT loosen it.
